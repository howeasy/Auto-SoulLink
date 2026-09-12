-- Durable client binding for the original RBY foreground trade engine.
-- An armed lease is never inferred from party equality or a mailbox pattern.
-- The runtime must supply current private execution/COMMIT authority. This
-- adapter does not grant frames, reconcile a replaced core, or flush SaveRAM.
local JSON=require("json_codec")
local Codec=require("gen1_party_codec")
local Receipts=require("gen1_command_receipts")
local Identity=require("platform_identity")
local Canonical=require("journal_document")
local M={SCHEMA="gen1-native-trade-lease-v1",INTENT="gen1-native-trade-intent-v1"}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function same(a,b)return assert(JSON.encode(a))==assert(JSON.encode(b))end
local function hex(value,length)
    return type(value)=="string" and #value==length and value:match("^[0-9a-f]+$")~=nil
end
local function bytes(value,length)
    assert(type(value)=="string" and #value==length*2 and value:match("^[0-9A-F]+$"),"canonical byte string required")
    local out={};for i=1,#value,2 do out[#out+1]=tonumber(value:sub(i,i+1),16)end;return out
end
function M.initial()return {schema=M.SCHEMA,phase="idle"}end

function M.new(options)
    local mem,manifest,store=options.memory,copy(options.manifest),options.store
    assert(type(options.authorize)=="function" and type(options.context_generation)=="function",
        "private command authority and live context readers required")
    assert(manifest.schema=="gen1-native-trade-build-v1" and manifest.foreground
        and manifest.test_probe==JSON.null and manifest.readback,"qualified foreground layout required")
    local variant,ram,fg=manifest.variant,manifest.ram,manifest.foreground
    assert(variant=="red" or variant=="blue" or variant=="yellow","RBY cartridge required")
    assert(options.player=="a" or options.player=="b","player scope required")
    local self={hooks={},active=nil}
    local function sha(value)return store.backend.sha256(assert(Canonical.encode(value)))end
    local function read(address,length,domain)
        local out={};for i=0,length-1 do out[#out+1]=memory.read_u8(address+i,domain or "System Bus")end;return out
    end
    local function put(address,values)
        for i,v in ipairs(values)do memory.write_u8(address+i-1,v,"System Bus")end
    end
    local function r(address)return memory.read_u8(address,"System Bus")end
    local function w(address,value)memory.write_u8(address,value,"System Bus")end
    local function lease()
        local value=assert(store:read())
        assert(value.schema==M.SCHEMA and ({idle=true,armed=true,complete=true,releasing=true,released=true})[value.phase],
            "invalid persisted native lease")
        return value
    end
    lease()
    local function guard(action,body,identity,intent)
        assert(gameinfo.getromhash():lower()==manifest.final_sha1,"native artifact changed")
        assert(options.authorize(action,copy(body),copy(identity),intent and copy(intent))==true,
            "current native execution authority unavailable")
        if intent then
            assert(options.context_generation()==intent.context_generation,"native physical context changed")
            assert(intent.command_id==identity.command_id and intent.command_sequence==identity.command_sequence
                and intent.body_digest==sha(body),"prepared native command changed")
            assert(string.format("%04X",mem.readPlayerId())==intent.before.party.save_id
                and mem.readPlayerName()==intent.before.party.save_name,"native save identity changed")
        end
    end
    local function snapshot()
        local observed={party=assert(Receipts.party_snapshot(mem,variant))}
        for name,region in pairs({party_storage=manifest.readback.party,save_region=manifest.readback.save})do
            observed[name.."_hex"]=mem.bytesToHex(read(region.address,region.length,region.domain))
        end
        observed.dex_hex=mem.bytesToHex(read(ram.wPokedexOwned,38))
        observed.save_name_hex=mem.bytesToHex(read(ram.wPlayerName,11))
        observed.map=r(ram.wCurMap)
        if variant=="yellow"then observed.pikachu_hex=mem.bytesToHex(read(ram.wPikachuHappiness,2))end
        return observed
    end
    local function request(body)
        assert(body.cmd=="native_trade_commit" and body.player==options.player
            and hex(body.transaction_id,32) and hex(body.proposal_digest,64),"paired native COMMIT required")
        local payload=body.payload
        assert(payload.schema=="paired-native-commit-v1" and sha(payload.proposal)==body.proposal_digest
            and sha(payload.prepared)==payload.prepared_digest,"persisted paired preparation differs")
        local own=payload.proposal.participants[options.player]
        local peer=payload.proposal.participants[options.player=="a" and "b" or "a"]
        local detail=payload.prepared.details
        assert(detail.schema=="rby-native-prepared-v1","RBY native preparation required")
        if detail.checkpoint_digest~=nil then
            assert(sha(require("gen1_trade_preparation").capture(mem,manifest))==detail.checkpoint_digest,
                "physical trade checkpoint changed after paired preparation")
        end
        assert(own.context.player==options.player and own.context.context_generation==options.context_generation()
            and payload.prepared.context_generation==own.context.context_generation
            and payload.prepared.proposal_digest==body.proposal_digest
            and payload.prepared.evidence_digest==own.evidence_digest,"prepared participant context differs")
        assert(own.context.physical_instance~=peer.context.physical_instance and own.member_id~=peer.member_id,
            "trade needs distinct physical participants")
        local current=assert(Receipts.party_snapshot(mem,variant))
        assert(same(current.party,own.snapshot.party) and current.save_id==own.context.save_identity.ot_id
            and current.save_name==own.context.save_identity.trainer_name,"selected physical party or save changed")
        local party={};for _,raw in ipairs(current.party)do party[#party+1]=bytes(raw,66)end
        local incoming=bytes(peer.snapshot.party[peer.slot+1],66)
        local boxes=assert(mem.storedBoxKeys())
        assert(Codec.prepareExchange(party,variant,own.slot,incoming,own.key,peer.key,detail.evolved_species,boxes))
        local peer_name=bytes(detail.peer_name_hex,11)
        -- Reuse the same exact cartridge name alphabet/terminator validation.
        local named={table.unpack(incoming)};for i=1,11 do named[44+i]=peer_name[i]end
        assert(Codec.validateBlob(named,variant),"invalid partner trainer name")
        return {slot=own.slot,incoming=mem.bytesToHex(incoming),peer_name_hex=detail.peer_name_hex,
            expected_key=own.key,incoming_key=peer.key,evolved_species=detail.evolved_species}
    end
    local function waiting(intent)
        if emu.getregister("PC")~=0x40 then return false end
        local sp=emu.getregister("SP")
        return r(sp+2)+256*r(sp+3)==fg.wait_return and r(ram.hLoadedROMBank)==fg.service.bank
            and same(read(fg.overlay,5),{0x53,0x4c,0x54,0x31,1})
            and r(fg.overlay+6)==intent.generation and r(fg.overlay+7)==intent.generation
            and same(read(fg.overlay+12,4),bytes(intent.token_hex,4))
    end
    local order={"service","InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData"}
    local routines={service=fg.service}
    for i=2,#order do routines[order[i]]=manifest.native_calls[order[i]]end
    for name,routine in pairs(routines)do
        local id=event.on_bus_exec(function()
            local active=self.active
            if active and (routine.bank==0 or r(ram.hLoadedROMBank)==routine.bank)then
                active.counts[name]=(active.counts[name]or 0)+1
                active.sequence[#active.sequence+1]=name
                if order[#active.sequence]~=name then active.invalid=true end
            end
        end,routine.address,"slink-native-"..options.player.."-"..name,"System Bus")
        assert(id,"native execution observer unavailable");self.hooks[#self.hooks+1]=id
    end
    function self.prepare(body,identity)
        guard("prepare",body,identity)
        assert(mem.isPartyWriteSafe(),"native preparation requires the verified overworld checkpoint")
        local state=lease()
        assert(state.phase=="idle" or state.phase=="released","another native lease needs recovery/closure")
        local selected=request(body)
        local nonce=assert((options.new_nonce or Identity.new_nonce)())
        assert(hex(nonce,32) and nonce:sub(1,8)~="00000000","fresh native lease token required")
        local context=options.context_generation();assert(hex(context,32),"physical context generation required")
        local before=snapshot()
        local sum=0;for _,value in ipairs(bytes(before.save_region_hex,manifest.readback.save.length))do sum=sum+value end
        assert(sum%256==255,"valid canonical save required before native trade")
        return {schema=M.INTENT,command_id=identity.command_id,command_sequence=identity.command_sequence,
            body_digest=sha(body),context_generation=context,before=before,request=selected,
            token_hex=nonce:sub(1,8):upper(),generation=tonumber(nonce:sub(9,10),16)%255+1,
            union_hex=mem.bytesToHex(read(fg.overlay,16))}
    end
    function self.classify(body,intent,identity)
        guard("observe",body,identity,intent)
        assert(intent.schema==M.INTENT,"native intent schema differs")
        local state=lease()
        if state.phase=="idle" or state.phase=="released" then
            assert(mem.isPartyWriteSafe() and same(request(body),intent.request)
                and same(snapshot(),intent.before) and mem.bytesToHex(read(fg.overlay,16))==intent.union_hex,
                "native prepared prestate changed")
            return "before",intent.before
        end
        assert(state.command_id==identity.command_id and state.intent_digest==sha(intent),"native lease belongs to another command")
        if state.phase=="complete" then
            assert(waiting(intent) and r(fg.overlay+5)==7 and r(fg.overlay+8)==0
                and same(snapshot(),state.receipt.after),"completed native lease changed before durable delivery")
            return "after",state.receipt
        end
        assert(state.phase=="armed","native release is already in progress")
        local active=self.active
        assert(active and active.command_id==identity.command_id,
            "armed native command requires explicit recovery after client/core replacement")
        assert(not active.invalid,"native execution sequence diverged")
        if not waiting(intent) or r(fg.overlay+5)~=7 then
            return "armed",{schema="rby-native-pending-v1",command_id=identity.command_id,counts=copy(active.counts)}
        end
        assert(r(fg.overlay+8)==0,"native trade refused or became uncertain; paired recovery required")
        assert(same(active.sequence,order),"complete original animation/evolution/save path was not observed")
        local after=snapshot()
        local region=bytes(after.save_region_hex,manifest.readback.save.length)
        local sum=0;for _,value in ipairs(region)do sum=sum+value end
        local offset=manifest.readback.saved_party_offset*2
        assert(sum%256==255 and after.save_region_hex:sub(offset+1,offset+808)==after.party_storage_hex,
            "canonical native save differs from live party")
        assert(after.map==intent.before.map,"native trade did not restore the source map")
        local receipt={schema="rby-native-execution-v1",command_id=identity.command_id,
            command_sequence=identity.command_sequence,transaction_id=body.transaction_id,
            proposal_digest=body.proposal_digest,prepared_digest=body.payload.prepared_digest,
            context_generation=intent.context_generation,final_sha1=manifest.final_sha1,
            before=intent.before,after=after,counts=copy(active.counts),sequence=copy(active.sequence),
            token_hex=intent.token_hex,generation=intent.generation,save_file_verified=false}
        state.phase="complete";state.receipt=receipt
        assert(store:commit(state))
        return "after",copy(receipt)
    end
    function self.apply(body,intent,identity)
        guard("arm",body,identity,intent)
        assert(mem.isPartyWriteSafe() and same(request(body),intent.request) and same(snapshot(),intent.before)
            and mem.bytesToHex(read(fg.overlay,16))==intent.union_hex,"prestate changed before native arming")
        local state=lease();assert(state.phase=="idle" or state.phase=="released","native command is already armed")
        -- This irreversible local marker precedes every RAM write. A crash in
        -- the following staging window cannot cause an automatic second trade.
        assert(store:commit({schema=M.SCHEMA,phase="armed",command_id=identity.command_id,
            intent_digest=sha(intent),intent=copy(intent),transaction_id=body.transaction_id,proposal_digest=body.proposal_digest}))
        self.active={command_id=identity.command_id,intent_digest=sha(intent),counts={},sequence={}}
        self.execution_phase="armed"
        local incoming=bytes(intent.request.incoming,66)
        w(ram.wEnemyPartyCount,1);put(ram.wEnemyPartySpecies,{incoming[1],255})
        put(ram.wEnemyMons,{table.unpack(incoming,1,44)})
        put(ram.wEnemyMonOT,{table.unpack(incoming,45,55)})
        put(ram.wEnemyMonNicks,{table.unpack(incoming,56,66)})
        put(ram.wLinkEnemyTrainerName,bytes(intent.request.peer_name_hex,11))
        put(fg.backup,bytes(intent.union_hex,16))
        local previous=intent.generation%255+1
        local token=bytes(intent.token_hex,4)
        put(fg.overlay,{0x53,0x4c,0x54,0x31,1,5,previous,previous,255,intent.request.slot,1,0,table.unpack(token)})
        w(fg.overlay+6,intent.generation) -- publish last
    end
    function self.receipt(body,intent,observed,identity)
        guard("receipt",body,identity,intent)
        local state=lease()
        assert(state.phase=="complete" and state.command_id==identity.command_id
            and same(state.receipt,observed),"durable native receipt differs")
        return copy(observed)
    end
    function self.release(body,identity,intent)
        guard("release",body,identity)
        local state=lease()
        -- The command inbox may have been confirmed and pruned before paired
        -- finalization arrives. The irreversible lease retains its own intent.
        intent=intent or state.intent
        assert(type(intent)=="table","native release needs its persisted prepared intent")
        assert(body.cmd=="native_trade_release" and body.transaction_id==state.transaction_id
            and body.proposal_digest==state.proposal_digest,"paired finalization release differs")
        assert(state.phase=="complete" or state.phase=="releasing","completed native lease required")
        assert(options.context_generation()==intent.context_generation and state.intent_digest==sha(intent)
            and waiting(intent) and r(fg.overlay+8)==0,"native release checkpoint changed")
        if state.release_identity then
            assert(same(state.release_identity,identity) and state.release_body_digest==sha(body),
                "native release belongs to another command")
        end
        state.release_identity=copy(identity);state.release_body_digest=sha(body)
        state.phase="releasing";assert(store:commit(state));self.execution_phase="releasing";w(fg.overlay+5,8)
    end
    function self.finish_release()
        local state=lease();assert(state.phase=="releasing","native release is not pending")
        assert(gameinfo.getromhash():lower()==manifest.final_sha1
            and options.context_generation()==state.receipt.context_generation
            and mem.isPartyWriteSafe(),"native release has not returned to its physical context")
        -- Subsequent gameplay can change PP/HP; close only at the first checkpoint.
        assert(same(snapshot(),state.receipt.after),"native release changed the verified party/save")
        state.phase="released";assert(store:commit(state));self.active=nil;self.execution_phase="released"
        return {schema="rby-native-release-v1",transaction_id=state.transaction_id,
            native_command_id=state.command_id,context_generation=state.receipt.context_generation}
    end
    function self.release_executor()
        local function checked(body,identity,intent)
            guard("observe_release",body,identity)
            local state=lease()
            assert(body.cmd=="native_trade_release" and body.transaction_id==state.transaction_id
                and body.proposal_digest==state.proposal_digest
                and body.payload.schema=="paired-trade-release-v1", "paired release command required")
            assert(state.receipt and options.context_generation()==state.receipt.context_generation,
                "native release context changed")
            if intent then
                assert(intent.schema=="rby-release-intent-v1" and intent.command_id==identity.command_id
                    and intent.command_sequence==identity.command_sequence and intent.body_digest==sha(body)
                    and intent.native_command_id==state.command_id and intent.native_intent_digest==state.intent_digest
                    and intent.context_generation==options.context_generation(),"prepared release differs")
            end
            if state.phase=="releasing" or state.phase=="released" then
                assert(same(state.release_identity,identity) and state.release_body_digest==sha(body),
                    "native release belongs to another command")
            end
            return state
        end
        local adapter={}
        function adapter.prepare(body,identity)
            local state=checked(body,identity)
            assert(state.phase=="complete" and state.intent and waiting(state.intent),
                "completed native lease required before preparing release")
            return {schema="rby-release-intent-v1",command_id=identity.command_id,
                command_sequence=identity.command_sequence,body_digest=sha(body),native_command_id=state.command_id,
                native_intent_digest=state.intent_digest,context_generation=options.context_generation()}
        end
        function adapter.classify(body,intent,identity)
            local state=checked(body,identity,intent)
            if state.phase=="complete" then
                assert(waiting(state.intent) and r(fg.overlay+5)==7 and r(fg.overlay+8)==0
                    and same(snapshot(),state.receipt.after),"native release checkpoint changed")
                return "before",{schema="rby-release-before-v1"}
            end
            if state.phase=="releasing" then
                if not mem.isPartyWriteSafe()then
                    return "armed",{schema="rby-release-pending-v1",command_id=identity.command_id}
                end
                self.finish_release();state=lease()
            end
            assert(state.phase=="released" and mem.isPartyWriteSafe() and same(snapshot(),state.receipt.after),
                "native closure has not retained the verified party/save")
            return "after",{schema="rby-native-release-receipt-v1",command_id=identity.command_id,
                command_sequence=identity.command_sequence,transaction_id=state.transaction_id,
                proposal_digest=state.proposal_digest,native_command_id=state.command_id,
                context_generation=state.receipt.context_generation,final_sha1=manifest.final_sha1,
                after=copy(state.receipt.after)}
        end
        function adapter.apply(body,intent,identity)
            checked(body,identity,intent);self.release(body,identity)
        end
        function adapter.receipt(body,intent,observed,identity)
            local phase,current=adapter.classify(body,intent,identity)
            assert(phase=="after" and same(current,observed),"durable native closure differs")
            return copy(current)
        end
        return adapter
    end
    function self.frames_pending(command)
        -- Called between owned frames. The runtime separately checks admission,
        -- command scope and spends its window credit before the physical step.
        if command.cmd=="native_trade_commit" then
            return self.execution_phase=="armed" and self.active~=nil and not self.active.invalid
                and not (r(fg.overlay+5)==7 and r(fg.overlay+6)==r(fg.overlay+7))
        end
        return command.cmd=="native_trade_release" and self.execution_phase=="releasing" and not mem.isPartyWriteSafe()
    end
    function self.window_evidence(body,intent,identity)
        if body.cmd=="native_trade_commit" and self.frames_pending(body) then
            guard("observe",body,identity,intent)
            assert(self.active.command_id==identity.command_id and self.active.intent_digest==sha(intent),
                "active native intent changed")
            return {phase="armed",intent_digest=self.active.intent_digest,sequence=JSON.array(copy(self.active.sequence))}
        end
        local state=lease()
        if body.cmd=="native_trade_commit" then
            local phase=self.classify(body,intent,identity)
            if phase=="before" then
                return {phase="before",intent=copy(intent),
                    checkpoint=require("gen1_trade_preparation").capture(mem,manifest)}
            end
            if phase=="armed" then
                return {phase="armed",intent_digest=sha(intent),sequence=JSON.array(copy(self.active.sequence))}
            end
            return {phase="complete"}
        end
        assert(body.cmd=="native_trade_release","native execution window command required")
        local phase=self.release_executor().classify(body,intent,identity)
        if phase=="after" then return {phase="released"}end
        return {phase=phase=="before" and "before" or "releasing",native_command_id=state.command_id,
            native_intent_digest=state.intent_digest,after=copy(state.receipt.after)}
    end
    function self.close()for _,id in ipairs(self.hooks)do event.unregisterbyid(id)end;self.hooks={} end
    return self
end
return M
