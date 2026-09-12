-- Durable adapter for the cartridge's native partner YES/NO prompt.
-- A prompt is not a trade COMMIT. This adapter never grants frames or changes party/save bytes.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Identity=require("platform_identity")
local Receipts=require("gen1_command_receipts")
local Codec=require("gen1_party_codec")
local M={SCHEMA="rby-partner-prompt-lease-v1",INTENT="rby-partner-prompt-intent-v1"}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function same(a,b)return assert(JSON.encode(a))==assert(JSON.encode(b))end
local function hex(v,n)return type(v)=="string" and #v==n and v:match("^[0-9a-f]+$")~=nil end
function M.initial()return {schema=M.SCHEMA,phase="idle"}end
function M.new(options)
    local mem,manifest,store,journal=options.memory,copy(options.manifest),options.store,options.journal
    assert(manifest.schema=="gen1-native-trade-build-v1" and manifest.receptionist and manifest.foreground
        and manifest.readback and manifest.test_probe==JSON.null,"native prompt artifact required")
    assert(options.player=="a" or options.player=="b","prompt player required")
    assert(type(options.authorize)=="function" and type(options.context_generation)=="function",
        "private prompt authority/context required")
    local fg,ram,prompt=manifest.foreground,manifest.ram,manifest.receptionist.partner_prompt
    local self={hooks={},active=nil}
    local function sha(value)return store.backend.sha256(assert(Canonical.encode(value)))end
    local function r(p)return memory.read_u8(p,"System Bus")end
    local function w(p,v)memory.write_u8(p,v,"System Bus")end
    local function read(p,count,domain)
        local out={};for i=0,count-1 do out[#out+1]=memory.read_u8(p+i,domain or "System Bus")end;return out
    end
    local function put(p,values)for i,v in ipairs(values)do w(p+i-1,v)end end
    local function raw(text,count)
        assert(type(text)=="string" and #text==count*2 and text:match("^[0-9A-F]+$"),"canonical prompt bytes required")
        return assert(mem.hexToBytes(text))
    end
    local function lease()
        local value=assert(store:read())
        assert(value.schema==M.SCHEMA and ({idle=true,armed=true,complete=true,closing=true,closed=true})[value.phase],
            "invalid native prompt lease")
        return value
    end
    local function snapshot()
        local fields={};for name,p in pairs(prompt.saved_fields)do fields[name]=r(p)end
        return {party=assert(Receipts.party_snapshot(mem,manifest.variant)),map=r(ram.wCurMap),fields=fields,
            party_storage_hex=mem.bytesToHex(read(manifest.readback.party.address,manifest.readback.party.length)),
            tiles_hex=mem.bytesToHex(read(ram.wTileMap,360)),
            cart_digest=store.backend.sha256(mem.bytesToHex(read(0,0x8000,"CartRAM")))}
    end
    local function guard(action,body,identity,intent)
        assert(gameinfo.getromhash():lower()==manifest.final_sha1,"native prompt artifact changed")
        assert(options.authorize(action,copy(body),copy(identity),intent and copy(intent))==true,"native prompt authority unavailable")
        if intent then
            assert(intent.schema==M.INTENT and intent.command_id==identity.command_id
                and intent.command_sequence==identity.command_sequence and intent.body_digest==sha(body)
                and intent.context_generation==options.context_generation(),"native prompt command/context changed")
        end
    end
    local function request(body)
        assert(body.cmd=="native_trade_prompt" and body.player==options.player and hex(body.transaction_id,32)
            and hex(body.proposal_digest,64),"paired native prompt required")
        assert(body.payload.schema=="rby-native-prompt-v1" and sha(body.payload.proposal)==body.proposal_digest,
            "prompt proposal differs")
        local own=body.payload.proposal.participants[options.player]
        local peer=body.payload.proposal.participants[options.player=="a" and "b" or "a"]
        assert(own.context.player==options.player and own.context.context_generation==options.context_generation()
            and own.context.physical_instance~=peer.context.physical_instance and own.member_id~=peer.member_id,
            "prompt participant context differs")
        local current=assert(Receipts.party_snapshot(mem,manifest.variant))
        assert(current.battle_flag==0 and current.save_id==own.context.save_identity.ot_id
            and current.save_name==own.context.save_identity.trainer_name and same(current.party,own.snapshot.party),
            "prompt party/save changed")
        assert(type(own.slot)=="number" and own.slot%1==0 and own.slot>=0 and own.slot<current.party_count,
            "prompt selection is absent")
        local selected=assert(Codec.validateBlob(raw(current.party[own.slot+1],66),manifest.variant))
        local incoming=raw(peer.snapshot.party[peer.slot+1],66)
        local donor=assert(Codec.validateBlob(incoming,manifest.variant))
        assert(selected.key==own.key and donor.key==peer.key and selected.hp>0 and donor.hp>0,"prompt selected members changed")
        return {slot=own.slot,incoming=mem.bytesToHex(incoming)}
    end
    local function waiting(intent)
        if emu.getregister("PC")~=0x40 or r(ram.hLoadedROMBank)~=fg.service.bank then return false end
        local sp=emu.getregister("SP")
        return r(sp+2)+r(sp+3)*256==fg.wait_return and mem.bytesToHex(read(fg.overlay,5))=="534C543101"
            and r(fg.overlay+6)==intent.generation and r(fg.overlay+7)==intent.generation
            and mem.bytesToHex(read(fg.overlay+12,4))==intent.token_hex
    end
    local routines={service=fg.service,prompt=prompt,choice={bank=prompt.bank,address=prompt.choice}}
    for _,name in ipairs({"InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData"})do routines[name]=manifest.native_calls[name]end
    for name,routine in pairs(routines)do
        local id=event.on_bus_exec(function()
            local active=self.active
            if active and (routine.bank==0 or r(ram.hLoadedROMBank)==routine.bank)then
                active.counts[name]=(active.counts[name]or 0)+1
                active.sequence[#active.sequence+1]=name
                if ({"service","prompt","choice"})[#active.sequence]~=name then active.invalid=true end
            end
        end,routine.address,"slink-native-prompt-"..options.player.."-"..name,"System Bus")
        assert(id,"native prompt observer unavailable");self.hooks[#self.hooks+1]=id
    end
    lease()
    function self.prepare(body,identity)
        guard("prepare",body,identity)
        assert(mem.isPartyWriteSafe(),"prompt needs verified overworld checkpoint")
        local state=lease();assert(state.phase=="idle" or state.phase=="closed","prior native prompt needs closure")
        local selected=request(body)
        local nonce=assert((options.new_nonce or Identity.new_nonce)())
        assert(hex(nonce,32) and nonce:sub(1,8)~="00000000","fresh prompt lease token required")
        return {schema=M.INTENT,command_id=identity.command_id,command_sequence=identity.command_sequence,
            body_digest=sha(body),context_generation=options.context_generation(),before=snapshot(),request=selected,
            generation=tonumber(nonce:sub(9,10),16)%255+1,token_hex=nonce:sub(1,8):upper(),
            union_hex=mem.bytesToHex(read(fg.overlay,16))}
    end
    function self.classify(body,intent,identity)
        guard("observe",body,identity,intent)
        local state=lease()
        if state.phase=="idle" or state.phase=="closed" then
            assert(mem.isPartyWriteSafe() and same(request(body),intent.request) and same(snapshot(),intent.before)
                and mem.bytesToHex(read(fg.overlay,16))==intent.union_hex,"prepared prompt prestate changed")
            return "before",intent.before
        end
        assert(state.command_id==identity.command_id and state.intent_digest==sha(intent),"prompt lease belongs to another command")
        if state.phase=="complete" then
            assert(waiting(intent) and r(fg.overlay+5)==7 and r(fg.overlay+8)==state.receipt.result
                and same(snapshot(),state.receipt.after),"completed native prompt changed")
            return "after",copy(state.receipt)
        end
        assert(state.phase=="armed" and self.active and self.active.command_id==identity.command_id,
            "armed prompt requires explicit recovery after client/core replacement")
        if not waiting(intent) or r(fg.overlay+5)~=7 then
            return "armed",{schema="rby-prompt-pending-v1",command_id=identity.command_id}
        end
        local result=r(fg.overlay+8)
        assert(result==0 or result==1 or result==3,"native prompt result is uncertain")
        local sequence=result==3 and {"service","prompt"} or {"service","prompt","choice"}
        assert(same(self.active.sequence,sequence),"native prompt execution path differs")
        local after=snapshot();assert(same(after,intent.before),"native prompt changed party/save/map/controls")
        local receipt={schema="rby-native-prompt-v1",command_id=identity.command_id,
            command_sequence=identity.command_sequence,transaction_id=body.transaction_id,proposal_digest=body.proposal_digest,
            context_generation=intent.context_generation,final_sha1=manifest.final_sha1,result=result,
            token_hex=intent.token_hex,generation=intent.generation,before=intent.before,after=after,
            sequence=copy(self.active.sequence),counts=copy(self.active.counts)}
        state.phase="complete";state.receipt=receipt;assert(store:commit(state));self.execution_phase="complete"
        return "after",copy(receipt)
    end
    function self.apply(body,intent,identity)
        guard("arm",body,identity,intent)
        assert(mem.isPartyWriteSafe() and same(request(body),intent.request) and same(snapshot(),intent.before)
            and mem.bytesToHex(read(fg.overlay,16))==intent.union_hex,"native prompt prestate changed before arming")
        local state=lease();assert(state.phase=="idle" or state.phase=="closed","prompt already armed")
        assert(store:commit({schema=M.SCHEMA,phase="armed",command_id=identity.command_id,
            intent_digest=sha(intent),intent=copy(intent),body=copy(body),identity=copy(identity)}))
        self.active={command_id=identity.command_id,intent_digest=sha(intent),counts={},sequence={}}
        self.execution_phase="armed"
        local incoming=raw(intent.request.incoming,66)
        put(ram.wEnemyMons,{table.unpack(incoming,1,44)});put(ram.wEnemyMonOT,{table.unpack(incoming,45,55)})
        put(ram.wEnemyMonNicks,{table.unpack(incoming,56,66)});w(ram.wEnemyPartyCount,1);put(ram.wEnemyPartySpecies,{incoming[1],255})
        put(fg.backup,raw(intent.union_hex,16))
        local previous=intent.generation%255+1
        put(fg.overlay,{0x53,0x4c,0x54,0x31,1,3,previous,previous,255,intent.request.slot,1,0,table.unpack(raw(intent.token_hex,4))})
        w(fg.overlay+6,intent.generation)
    end
    function self.receipt(body,intent,observed,identity)
        guard("receipt",body,identity,intent)
        local state=lease();assert(state.phase=="complete" and same(state.receipt,observed),"durable native decision differs")
        return copy(observed)
    end
    function self.release()
        local state=lease();assert(state.phase=="complete" or state.phase=="closing","native prompt has no completed decision")
        guard("release",state.body,state.identity,state.intent)
        local inbox=assert(journal.store:read())
        local confirmed=inbox.command_floor>=state.identity.command_sequence
        for _,entry in ipairs(inbox.inbox)do
            if entry.command_id==state.command_id then
                confirmed=entry.confirmed==true and same(entry.receipt,state.receipt)
            end
        end
        assert(confirmed,"exact native decision has no durable server acknowledgement")
        assert(waiting(state.intent) and r(fg.overlay+8)==state.receipt.result,"prompt release checkpoint changed")
        state.phase="closing";assert(store:commit(state));self.execution_phase="closing";w(fg.overlay+5,8)
    end
    function self.finish_release()
        local state=lease();assert(state.phase=="closing","prompt release is not pending")
        guard("closed",state.body,state.identity,state.intent)
        assert(mem.isPartyWriteSafe() and same(snapshot(),state.receipt.after),"native prompt closure changed its checkpoint")
        state.phase="closed";assert(store:commit(state));self.active=nil;self.execution_phase="closed"
        return {schema="rby-prompt-closed-v1",command_id=state.command_id,context_generation=state.intent.context_generation}
    end
    function self.frames_pending(body)
        if body.cmd=="native_trade_prompt"then
            return self.execution_phase=="armed" and self.active~=nil and not self.active.invalid
                and not (r(fg.overlay+5)==7 and r(fg.overlay+6)==r(fg.overlay+7))
        end
        return (body.cmd=="native_trade_prepare" or body.cmd=="native_trade_abort")
            and self.execution_phase=="closing" and not mem.isPartyWriteSafe()
    end
    function self.needs_closure(body)
        local state=lease()
        if state.phase=="idle"then return false end
        if state.body.transaction_id~=body.transaction_id then
            assert(state.phase=="closed","previous prompt requires closure/recovery")
            return false
        end
        return true
    end
    function self.window_evidence(body,intent,identity)
        if body.cmd=="native_trade_prompt"then
            guard("observe",body,identity,intent)
            if self.frames_pending(body)then
                assert(self.active.command_id==identity.command_id and self.active.intent_digest==sha(intent),
                    "active prompt intent changed")
                return {phase="armed",intent_digest=self.active.intent_digest,sequence=JSON.array(copy(self.active.sequence))}
            end
            local phase=self.classify(body,intent,identity)
            if phase=="before"then return {phase="before",intent=copy(intent),
                checkpoint=require("gen1_trade_preparation").capture(mem,manifest)}end
            return {phase="complete"}
        end
        local phase=self.closure_adapter().classify(body,intent,identity)
        if phase=="after"then return {phase="prompt_closed"}end
        local state=lease()
        return {phase=phase=="before" and "prompt_before" or "prompt_closing",
            prompt_command_id=state.command_id,prompt_intent_digest=state.intent_digest,receipt=copy(state.receipt)}
    end
    function self.closure_adapter()
        local function checked(body,identity,intent)
            guard("observe_closure",body,identity)
            local state=lease()
            assert((body.cmd=="native_trade_prepare" or body.cmd=="native_trade_abort")
                and state.body and body.transaction_id==state.body.transaction_id
                and body.proposal_digest==state.body.proposal_digest
                and options.context_generation()==state.intent.context_generation,"prompt closure transaction/context differs")
            assert(state.receipt and (body.cmd~="native_trade_prepare" or state.receipt.result==0),
                "accepted native prompt required before preparation")
            if intent then
                assert(intent.schema=="rby-prompt-close-intent-v1" and intent.command_id==identity.command_id
                    and intent.command_sequence==identity.command_sequence and intent.body_digest==sha(body)
                    and intent.prompt_command_id==state.command_id and intent.prompt_intent_digest==state.intent_digest
                    and intent.context_generation==options.context_generation(),"prepared prompt closure differs")
            end
            if state.phase=="closing" or state.phase=="closed"then
                assert(state.close_command_id==identity.command_id and state.close_body_digest==sha(body),
                    "prompt closure belongs to another command")
            end
            return state
        end
        local adapter={}
        function adapter.prepare(body,identity)
            local state=checked(body,identity)
            assert(state.phase=="complete" and waiting(state.intent),"completed prompt checkpoint required")
            return {schema="rby-prompt-close-intent-v1",command_id=identity.command_id,
                command_sequence=identity.command_sequence,body_digest=sha(body),prompt_command_id=state.command_id,
                prompt_intent_digest=state.intent_digest,context_generation=options.context_generation()}
        end
        function adapter.classify(body,intent,identity)
            local state=checked(body,identity,intent)
            if state.phase=="complete"then
                assert(waiting(state.intent) and r(fg.overlay+5)==7 and r(fg.overlay+8)==state.receipt.result
                    and same(snapshot(),state.receipt.after),"completed prompt checkpoint changed")
                return "before",{schema="rby-prompt-close-before-v1"}
            end
            if state.phase=="closing"then
                if not mem.isPartyWriteSafe()then return "armed",{schema="rby-prompt-close-pending-v1",command_id=identity.command_id}end
                assert(same(snapshot(),state.receipt.after),"prompt return changed its checkpoint")
                state.phase="closed";assert(store:commit(state));self.active=nil;self.execution_phase="closed"
            end
            assert(state.phase=="closed" and mem.isPartyWriteSafe() and same(snapshot(),state.receipt.after),
                "closed prompt checkpoint changed")
            return "after",{schema="rby-prompt-closure-v1",command_id=identity.command_id,
                command_sequence=identity.command_sequence,transaction_id=body.transaction_id,
                proposal_digest=body.proposal_digest,context_generation=options.context_generation(),
                prompt_command_id=state.command_id,final_sha1=manifest.final_sha1,after=copy(state.receipt.after)}
        end
        function adapter.apply(body,intent,identity)
            local state=checked(body,identity,intent)
            assert(options.authorize("arm",copy(body),copy(identity),copy(intent))==true,"prompt closure frame authority required")
            assert(state.phase=="complete" and waiting(state.intent) and same(snapshot(),state.receipt.after),
                "prompt close checkpoint changed")
            local inbox=assert(journal.store:read());local confirmed=inbox.command_floor>=state.identity.command_sequence
            for _,entry in ipairs(inbox.inbox)do
                if entry.command_id==state.command_id then confirmed=entry.confirmed==true and same(entry.receipt,state.receipt)end
            end
            assert(confirmed,"native decision has no exact durable server acknowledgement")
            state.close_command_id=identity.command_id;state.close_body_digest=sha(body);state.phase="closing"
            assert(store:commit(state));self.execution_phase="closing";w(fg.overlay+5,8)
        end
        function adapter.receipt(body,intent,observed,identity)
            local phase,current=adapter.classify(body,intent,identity)
            assert(phase=="after" and same(current,observed),"prompt closure readback differs")
            return copy(current)
        end
        return adapter
    end
    function self.close()for _,id in ipairs(self.hooks)do event.unregisterbyid(id)end;self.hooks={}end
    return self
end
return M
