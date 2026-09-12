-- Adopt an actual native receptionist query, then own its menu and return.
-- The existing client publishes availability/offer acknowledgements. Every
-- emulated frame remains subject to the runtime's server-issued UI window.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Client=require("gen1_receptionist_client")
local Capture=require("gen1_trade_preparation")
local Identity=require("platform_identity")
local M={SCHEMA="rby-receptionist-lease-v1",INTENT="rby-receptionist-intent-v1"}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function same(a,b)return assert(Canonical.encode(a))==assert(Canonical.encode(b))end
local paths={{"after_query","party","offer","offer_result","menus_restored"},
    {"after_query","party","menus_restored"},{"after_query","menus_restored"},
    {"after_query","menus_restored","cable"}}
function M.initial()return {schema=M.SCHEMA,phase="idle"}end
function M.new(options)
    local mem,manifest,store,journal=options.memory,options.manifest,options.store,options.journal
    local self={active=nil,hooks={}}
    local function sha(value)return store.backend.sha256(assert(Canonical.encode(value)))end
    local function state()
        local value=assert(store:read());assert(value.schema==M.SCHEMA,"invalid receptionist lease")
        return value
    end
    local function guard(action,body,identity,intent)
        assert(gameinfo.getromhash():lower()==manifest.final_sha1 and body.cmd=="native_receptionist"
            and body.player==options.player and body.payload.context_generation==options.context_generation()
            and options.authorize(action,body,identity)==true,"owned receptionist authority required")
        if intent then assert(intent.schema==M.INTENT and intent.command_id==identity.command_id
            and intent.command_sequence==identity.command_sequence and intent.body_digest==sha(body)
            and intent.context_generation==options.context_generation(),"receptionist intent/context changed")end
    end
    self.client=Client.new({memory=mem,manifest=manifest,journal=journal,observe=options.observe,
        context_generation=options.context_generation,
        authorize=function()
            local active=self.active
            return active~=nil and options.authorize("native_ui",active.body,active.identity)==true
        end,
        eligible_slots=function(snapshot)
            assert(self.active and same(snapshot,self.active.body.payload.checkpoint.party),"receptionist party changed")
            return self.active.body.eligible_mask
        end})
    local ui=manifest.receptionist
    local routines={after_query={bank=ui.entry.bank,address=ui.after_query},party={bank=ui.entry.bank,address=ui.party_entry},
        offer={bank=ui.entry.bank,address=ui.offer_entry},offer_result={bank=ui.entry.bank,address=ui.offer_result},
        menus_restored={bank=ui.entry.bank,address=ui.menus_restored},cable=ui.original}
    for name,routine in pairs(routines)do
        self.hooks[#self.hooks+1]=assert(event.on_bus_exec(function()
            local active=self.active
            if active and (routine.bank==0 or memory.read_u8(manifest.ram.hLoadedROMBank,"System Bus")==routine.bank)then
                active.sequence[#active.sequence+1]=name
                if name=="offer_result"then active.offer_result=emu.getregister("B")end
                local valid=false
                for _,path in ipairs(paths)do
                    local prefix={};for i=1,#active.sequence do prefix[i]=path[i]end
                    if same(active.sequence,prefix)then valid=true end
                end
                if not valid then active.invalid=true end
            end
        end,routine.address,"slink-receptionist-runtime-"..options.player.."-"..name,"System Bus"))
    end
    function self.prepare(body,identity)
        guard("observe_ui",body,identity)
        assert(state().phase=="idle" or state().phase=="complete","previous receptionist needs recovery")
        assert(same(Client.query(mem,manifest),body.payload.query)
            and same(Capture.capture(mem,manifest,true),body.payload.checkpoint),"native query/party changed")
        local nonce=assert(Identity.new_nonce());assert(nonce:sub(1,8)~="00000000")
        return {schema=M.INTENT,command_id=identity.command_id,command_sequence=identity.command_sequence,
            body_digest=sha(body),context_generation=options.context_generation(),token_hex=nonce:sub(1,8):upper()}
    end
    function self.classify(body,intent,identity)
        guard("observe_ui",body,identity,intent)
        local value=state()
        if value.phase=="idle" or value.command_id~=identity.command_id then
            assert(value.phase=="idle" or value.phase=="complete","prior receptionist requires closure")
            assert(same(Client.query(mem,manifest),body.payload.query)
                and same(Capture.capture(mem,manifest,true),body.payload.checkpoint),"receptionist prestate changed")
            return "before",body.payload.query
        end
        assert(value.intent_digest==sha(intent),"receptionist belongs to another intent")
        if value.phase=="complete"then
            assert(same(Capture.capture(mem,manifest),value.receipt.checkpoint),"completed receptionist checkpoint changed")
            return "after",copy(value.receipt)
        end
        local active=self.active
        assert(value.phase=="active" and active and active.command_id==identity.command_id and not active.invalid,
            "receptionist execution requires recovery")
        if not mem.isPartyWriteSafe()then return "armed",{schema="rby-receptionist-pending-v1",command_id=identity.command_id}end
        local point=Capture.capture(mem,manifest);assert(same(point,body.payload.checkpoint),"receptionist changed party/save/map")
        local complete=false;for _,path in ipairs(paths)do if same(active.sequence,path)then complete=true end end
        assert(complete,"receptionist did not return through its original path")
        local offer=JSON.null
        if active.offer_result~=nil then
            assert(active.offer_result==0,"native receptionist did not confirm offer delivery")
            local baseline=journal.store:read().observation.gen1_receptionist
            if not baseline or baseline.phase~="acknowledged"then
                return "armed",{schema="rby-receptionist-awaiting-ack-v1",command_id=identity.command_id}
            end
            offer=baseline.operation_id
        end
        local receipt={schema="rby-receptionist-return-v1",command_id=identity.command_id,
            command_sequence=identity.command_sequence,context_generation=options.context_generation(),
            final_sha1=manifest.final_sha1,sequence=JSON.array(copy(active.sequence)),checkpoint=point,
            offer_operation_id=offer,frame=emu.framecount(),token_hex=intent.token_hex}
        value.phase="complete";value.receipt=receipt;assert(store:commit(value));self.active=nil
        return "after",copy(receipt)
    end
    function self.apply(body,intent,identity)
        guard("native_ui",body,identity,intent)
        assert(self.classify(body,intent,identity)=="before","receptionist is not in its original query")
        assert(store:commit({schema=M.SCHEMA,phase="active",command_id=identity.command_id,intent_digest=sha(intent)}))
        self.active={command_id=identity.command_id,body=copy(body),identity=copy(identity),sequence={}}
        self.client.visit=nil -- the completed prior lease cannot own this unanswered query
        self.client.adopt_query(intent.token_hex);self.client.step()
    end
    function self.receipt(body,intent,observed,identity)
        local phase,current=self.classify(body,intent,identity)
        assert(phase=="after" and same(observed,current),"receptionist receipt changed");return current
    end
    function self.frames_pending(body)
        return body.cmd=="native_receptionist" and self.active~=nil and not self.active.invalid and not mem.isPartyWriteSafe()
    end
    function self.step()if self.active then self.client.step()end end
    function self.window_evidence(body,intent,identity)
        guard("observe_ui",body,identity,intent)
        if self.active then return {phase="active",intent_digest=sha(intent),sequence=JSON.array(copy(self.active.sequence))}end
        local phase=self.classify(body,intent,identity)
        if phase=="after"then return {phase="complete"}end
        return {phase="before",intent=copy(intent),query=Client.query(mem,manifest),checkpoint=Capture.capture(mem,manifest,true)}
    end
    function self.close()self.client.close();for _,hook in ipairs(self.hooks)do event.unregisterbyid(hook)end end
    return self
end
return M
