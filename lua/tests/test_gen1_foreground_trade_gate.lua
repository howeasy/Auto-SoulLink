-- Natural patched DelayFrame entry. This harness never redirects CPU registers.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..package.path
local JSON=require("json_codec")
local early_spec
if os.getenv("SLINK_NATIVE_SPEC")then
    local f=assert(io.open(os.getenv("SLINK_NATIVE_SPEC"),"r"));early_spec=assert(JSON.decode(f:read("*a")));f:close()
end
local map_fixture=require("tests.gen1_map_fixture").start(early_spec and early_spec.fixture,"native-ui-pair")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_foreground_trade_gate")
map_fixture:close()
local M=t.M
package.path=ROOT.."/lua/?.lua;"..package.path
local JSON=require("json_codec")
local Native=require("gen1_native_trade_executor")
local Store=require("state_store")
local Storage=require("platform_storage")
local Journal=require("client_journal")
local Executor=require("command_executor")
local Identity=require("platform_identity")
local Receipts=require("gen1_command_receipts")
local function json_file(path)
    local file=assert(io.open(path,"r"));local value=assert(JSON.decode(file:read("*a")));file:close();return value
end
local spec=json_file(os.getenv("SLINK_NATIVE_SPEC") or ROOT.."/.cache/foreground-trade-"..t.variant..".json")
local manifest=spec.manifest or json_file(ROOT.."/patch/gen1/build/foreground_"..t.variant.."/manifest.json")
local output_path=os.getenv("SLINK_NATIVE_RESULT") or ROOT.."/.cache/foreground-trade-result-"..t.variant..".json"
local player=spec.player or "a"
local bounded_owner,pacer,pacing_clock,pacing_started
if spec.bounded_host then
    local authority={}
    bounded_owner=require("platform_bounded_execution").new({profile="gambatte",
        owner_id=assert(Identity.new_nonce()),expected_host=require("platform_execution").supported_profile("gambatte"),
        authorize=function(value)return value==authority end}) -- explicit test control policy
    if spec.paced_host then
        client.speedmode(100)
        pacing_clock=assert(require("platform_clock").new())
        local rate=bounded_owner.status().frame_rate
        pacer=require("frame_pacer").new({clock=pacing_clock,numerator=rate.numerator,denominator=rate.denominator})
        pacing_started=pacing_clock()
    end
    t.step=function(buttons)
        joypad.set(buttons or {})
        if pacer then
            while not pacer:take(true,bounded_owner.status().host.user_paused)do assert(bounded_owner.yield_held())end
        end
        local stepped,receipt=bounded_owner.step_one(authority)
        assert(stepped,receipt)
        t.frame=t.frame+1
        assert(bounded_owner.yield_held())
    end
end
local function publish(path,value)
    local file=assert(io.open(path..".tmp","w"));file:write(assert(JSON.encode(value)));file:close()
    assert(os.rename(path..".tmp",path))
end
local function await_document(path)
    local deadline=os.time()+75
    while os.time()<deadline do
        local file=io.open(path,"r")
        if file then local value=assert(JSON.decode(file:read("*a")));file:close();return value end
        t.step({})
    end
    error("paired coordinator response timed out: "..path,0)
end
assert(manifest.foreground and manifest.test_probe==JSON.null,"foreground-only artifact required")
assert(gameinfo.getromhash():lower()==manifest.final_sha1,"wrong foreground artifact")
local source=t.variant=="yellow" and "pokeyellow" or "pokered"
local target=t.variant=="blue" and "pokeblue" or source
local oracle=dofile(ROOT.."/lua/tests/gb_routine_oracle.lua").new({
    symbols_path=ROOT.."/.cache/pret/"..source.."/"..target..".sym",step=t.step,
    scratch=0xCB00,marker=0xCBF0,stack=0xDFFE,bankswitch="Bankswitch"})
local a,r,w=oracle.address,oracle.read,oracle.write
local function read_bytes(address,count,domain)
    local out={};for i=0,count-1 do out[#out+1]=memory.read_u8(address+i,domain or "System Bus")end;return out
end
local function put(address,bytes)for i,value in ipairs(bytes)do w(address+i-1,value)end end
local function party()
    local out=JSON.array();for slot=0,M.getPartyCount()-1 do out[#out+1]=M.bytesToHex(assert(M.readPartyBlob(slot)))end;return out
end
local overlay=manifest.foreground.overlay
local routines={service=manifest.foreground.service}
for _,name in ipairs({"InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData"})do
    routines[name]=manifest.native_calls[name]
end
local observer=dofile(ROOT.."/lua/tests/gb_foreground_observer.lua").new({
    name="foreground-native-trade",bridge_entry=1,bank_address=a("hLoadedROMBank"),
    return_addresses=manifest.foreground.original_callers,routines=routines})
local adapter,command_store,lease_store
local ok,why=xpcall(function()
    for slot,hex in ipairs(spec.party)do
        local blob=assert(M.hexToBytes(hex))
        put(M.PARTY_BASE_ADDR+(slot-1)*44,{table.unpack(blob,1,44)})
        put(M.PARTY_OT_NAMES_ADDR+(slot-1)*11,{table.unpack(blob,45,55)})
        put(M.PARTY_NICKS_ADDR+(slot-1)*11,{table.unpack(blob,56,66)})
        w(M.PARTY_SPECIES_ADDR+slot-1,blob[1])
    end
    w(M.PARTY_COUNT_ADDR,#spec.party);w(M.PARTY_SPECIES_ADDR+#spec.party,255)
    local incoming=assert(M.hexToBytes(spec.incoming))
    for _=1,300 do if M.isPartyWriteSafe()then break end;t.step({})end
    assert(M.isPartyWriteSafe(),"pre-arm main-loop checkpoint absent")
    local original_map=M.getCurrentMap()
    local original_tiles=M.bytesToHex(read_bytes(a("wTileMap"),360))
    local run=assert(Identity.new_nonce())
    local context=assert(Identity.new_nonce())
    local command_id=assert(Identity.new_nonce())
    local root=ROOT.."/.cache/native-client-"..run
    local binding={run=run,player=player,variant=t.variant,rom=manifest.final_sha1,context=context}
    local function open_command_store()
        command_store=assert(Store.open(assert(Storage.new(root.."/commands.json")),binding,Journal.initial()))
        return assert(Journal.open(command_store,nil,spec.native_ui and require("gen1_trade_events") or nil))
    end
    local journal=open_command_store()
    lease_store=assert(Store.open(assert(Storage.new(root.."/native.json")),binding,Native.initial()))
    local function digest(value)return lease_store.backend.sha256(assert(JSON.encode(value)))end
    local before=assert(Receipts.party_snapshot(M,t.variant))
    local codec=require("gen1_party_codec")
    local selected=assert(codec.validateBlob(assert(M.readPartyBlob(spec.slot)),t.variant))
    local received=assert(codec.validateBlob(incoming,t.variant))
    local save={ot_id=before.save_id,trainer_name=before.save_name}
    local proposal={link_id=assert(Identity.new_nonce()),participants={
        a={context={player="a",context_generation=context,save_identity=save,physical_instance=run},
           member_id=assert(Identity.new_nonce()),key=selected.key,slot=spec.slot,evidence_digest=string.rep("1",64),
           snapshot={schema="rby-native-party-v1",party=before.party}},
        b={context={player="b",context_generation=assert(Identity.new_nonce()),save_identity=save,physical_instance=assert(Identity.new_nonce())},
           member_id=assert(Identity.new_nonce()),key=received.key,slot=0,evidence_digest=string.rep("2",64),
           snapshot={schema="rby-native-party-v1",party=JSON.array({spec.incoming})}}}}
    local prepared={proposal_digest=digest(proposal),context_generation=context,evidence_digest=string.rep("1",64),
        details={schema="rby-native-prepared-v1",evolved_species=spec.evolved_species or incoming[1],
            peer_name_hex="8F84849150505050505050"}}
    local body={cmd="native_trade_commit",player="a",transaction_id=assert(Identity.new_nonce()),proposal_digest=digest(proposal),
        payload={schema="paired-native-commit-v1",proposal=proposal,prepared=prepared,prepared_digest=digest(prepared)}}
    local command_sequence=1
    if spec.paired_directory then
        publish(spec.paired_directory.."/observed-"..player..".json",{player=player,variant=t.variant,
            context_generation=context,physical_instance=run,final_sha1=manifest.final_sha1,
            snapshot=before,slot=spec.slot,nickname=M.readPartyNickname(spec.slot),
            checkpoint=spec.native_ui and require("gen1_trade_preparation").capture(M,manifest) or nil,
            evolved_species=spec.evolved_species or incoming[1]})
        if spec.native_ui then
            local driver=require("tests.gen1_trade_ui_driver")
            local ui_result
            if player=="a"then
                ui_result=driver.receptionist(t,manifest,journal,context,spec.paired_directory)
            else
                local prompt_command=await_document(spec.paired_directory.."/prompt-"..player..".json")
                local prompt_store=assert(Store.open(assert(Storage.new(root.."/prompt.json")),binding,
                    require("gen1_partner_prompt_executor").initial()))
                ui_result=driver.partner(t,manifest,journal,prompt_store,context,player,prompt_command,spec.paired_directory)
                prompt_store:close()
            end
            publish(spec.paired_directory.."/ui-closed-"..player..".json",ui_result)
            assert(M.isPartyWriteSafe(),"native UI did not close at a verified checkpoint")
            original_tiles=M.bytesToHex(read_bytes(a("wTileMap"),360))
            local issued_prepare=await_document(spec.paired_directory.."/prepare-"..player..".json")
            local poll_prepare=assert(journal:append({event="tick"}))
            assert(journal:accept_response(poll_prepare,JSON.array({issued_prepare})))
            local prepare_adapter=require("gen1_trade_preparation").new({memory=M,manifest=manifest,
                player=player,context_generation=function()return context end,
                sha256=lease_store.backend.sha256,authorize=function()return true end}) -- fixture host ownership only
            local ready_ok,ready_result=Executor.new(journal,prepare_adapter):step(issued_prepare.command_id)
            assert(ready_ok,ready_result.reason)
            local events=journal:pending_events();assert(#events==1 and events[1].payload.event=="trade_ready")
            driver.exchange(spec.paired_directory.."/ready-"..player..".json",events[1])
            assert(journal:accept_response(events[1].operation_id,JSON.array()))
        end
        local issued=await_document(spec.paired_directory.."/commit-"..player..".json")
        body=issued.body;command_id=issued.command_id;command_sequence=issued.command_sequence
    end
    local poll=assert(journal:append({event="tick"}))
    assert(journal:accept_response(poll,JSON.array({{command_id=command_id,command_sequence=command_sequence,body=body}})))
    local adapter_options={memory=M,manifest=manifest,store=lease_store,player=player,
        context_generation=function()return context end,
        -- Explicit test authority fixture. No production host control is claimed.
        authorize=function()return true end}
    adapter=Native.new(adapter_options)
    local execution_adapter=adapter
    if spec.native_ui then
        execution_adapter=require("gen1_saved_trade_executor").new({native=adapter,journal=journal,
            persist_save=function(native_receipt,native_intent)
                local provider=require("platform_saveram").new({profile="gambatte",path=assert(os.getenv("SLINK_GATE_SAVERAM")),
                    authorize=function()return context==native_intent.context_generation and r(overlay+5)==7 and r(overlay+8)==0 end})
                return provider:flush(M.bytesToHex(read_bytes(0,0x8000,"CartRAM")))
            end})
    end
    local executor=Executor.new(journal,execution_adapter)
    observer:start()
    local executed,pending=executor:step(command_id)
    assert(not executed and pending.outcome=="PENDING" and pending.native_execution_permitted==false,
        "armed trade must remain pending without granting frames")
    local intent=journal:get_command(command_id).intent
    assert(intent and lease_store:read().phase=="armed" and #journal:pending_events()==0,
        "intent and local lease must precede native effects")
    if spec.client_fault=="reload_after_arm" or spec.client_fault=="stale_context_after_arm" then
        local bus=M.bytesToHex(read_bytes(0xC000,0x2000))
        if spec.client_fault=="reload_after_arm" then
            adapter.close();adapter=Native.new(adapter_options)
        else context=assert(Identity.new_nonce())end
        local applied,diagnostic=Executor.new(journal,adapter):step(command_id)
        assert(not applied and diagnostic.outcome=="NACK" and diagnostic.retryable,
            "lost native execution evidence must require explicit recovery")
        assert(journal:get_command(command_id).outcome==nil and #journal:pending_events()==0
            and lease_store:read().phase=="armed" and M.bytesToHex(read_bytes(0xC000,0x2000))==bus,
            "uncertain native restart must not stage again, write, ACK or release")
        assert((observer.counts.service or 0)==0,"fault must precede the first native frame")
        local file=assert(io.open(output_path,"w"))
        file:write(assert(JSON.encode({variant=t.variant,final_sha1=manifest.final_sha1,fault=spec.client_fault,
            recovery_required=true,receipt=false,additional_writes=0,native_frames=0,runtime_ready=false})));file:close()
        return
    end
    t.log("durable foreground request armed")
    local complete=false;local frames=0;local receipt
    for frame=1,16000 do
        t.step({A=frame%20<8});frames=frame
        if emu.getregister("PC")==0x40 then
            local sp=emu.getregister("SP")
            local caller=r(sp+2)+256*r(sp+3)
            if caller==manifest.foreground.wait_return and r(overlay+5)==7 and r(overlay+7)==intent.generation then
                complete=true;break
            end
        end
    end
    assert(complete,"foreground service did not reach its receipt wait")
    local replace=command_store.backend.replace
    if spec.client_fault=="receipt_store_failure" then
        command_store.backend.replace=function()return false,"injected local receipt publication failure"end
        local applied,diagnostic=executor:step(command_id)
        assert(not applied and diagnostic.outcome=="NACK" and diagnostic.phase=="persist_receipt",
            "journal failure must not report native command completion")
        assert(lease_store:read().phase=="complete","independent native receipt must survive inbox failure")
        command_store.backend.replace=replace
        command_store:close();journal=open_command_store()
        adapter.close();lease_store:close()
        lease_store=assert(Store.open(assert(Storage.new(root.."/native.json")),binding,Native.initial()))
        adapter_options.store=lease_store;adapter=Native.new(adapter_options)
        executor=Executor.new(journal,adapter)
    end
    local completed,result=executor:step(command_id)
    assert(completed and result.outcome=="ACK",JSON.encode(result))
    local published_receipt=result.receipt
    receipt=spec.native_ui and result.receipt.native or result.receipt
    local save_file=require("platform_saveram").new({profile="gambatte",path=assert(os.getenv("SLINK_GATE_SAVERAM")),
        authorize=function()return context==intent.context_generation and r(overlay+5)==7 and r(overlay+8)==0 end})
    local expected_file=M.bytesToHex(read_bytes(0,0x8000,"CartRAM"))
    local save_receipt=save_file:flush(expected_file)
    assert(save_receipt.flushed and save_receipt.readback,"native save-file persistence unavailable")
    local wrong_destination=pcall(function()
        require("platform_saveram").new({profile="gambatte",path=save_receipt.path..".wrong",authorize=function()return true end})
    end)
    assert(not wrong_destination,"unbound save destination must fail before writing")
    local wrong_readback=pcall(function()save_file:flush("00"..expected_file:sub(3))end)
    -- A zero leading byte may already match SRAM; deliberately flip that byte.
    if expected_file:sub(1,2)=="00" then wrong_readback=pcall(function()save_file:flush("01"..expected_file:sub(3))end)end
    assert(not wrong_readback,"mismatched save-file readback must not produce a receipt")
    save_receipt=save_file:flush(expected_file)
    -- Persist the separate file proof under the same command before announcing
    -- it to the paired driver. The local native ACK alone cannot release trade.
    local durable_lease=assert(lease_store:read())
    durable_lease.save_file_receipt=save_receipt;assert(lease_store:commit(durable_lease))
    if spec.paired_directory then
        publish(spec.paired_directory.."/native-"..player..".json",{command=journal:get_command(command_id),
            receipt=receipt,save_file_receipt=save_receipt,native_lease_path=root.."/native.json",
            events=spec.native_ui and journal:pending_events() or nil})
    end
    assert(lease_store:read().phase=="complete" and #journal:pending_events()==(spec.native_ui and 2 or 1),
        "native evidence and durable receipt must be published before release")
    -- Reopen the real flushed journal at the native receipt wait. A response
    -- replay must return the same receipt without staging/animating again.
    command_store:close();journal=open_command_store()
    local replayed,replay=Executor.new(journal,adapter):step(command_id)
    assert(replayed and replay.replayed and JSON.encode(replay.receipt)==JSON.encode(published_receipt),"native receipt replay differs")
    if spec.native_ui then
        for index,packet in ipairs(journal:pending_events())do
            require("tests.gen1_trade_ui_driver").exchange(spec.paired_directory.."/native-event-"..player.."-"..index..".json",packet)
            assert(journal:accept_response(packet.operation_id,JSON.array()))
        end
        assert(journal.store:read().command_floor>=command_sequence,"native file receipt was not confirmed in the journal")
    end
    t.log("foreground receipt wait reached")
    local counts,before=observer.counts,observer.before
    local service_sp=observer.entries.service and observer.entries.service.SP
    assert(counts.service==1 and before and service_sp,"trade did not enter exactly once through the real bridge")
    assert(r(overlay+8)==0,"physical engine refused or became uncertain")
    local traded=party()
    local restored_union=read_bytes(manifest.foreground.backup,16)
    -- A stale acknowledgement may not release the foreground lease.
    w(overlay+5,8);w(overlay+6,intent.generation%255+1)
    for _=1,5 do t.step({});assert(not M.isPartyWriteSafe(),"stale generation released the game")end
    w(overlay+6,intent.generation);local last=r(overlay+15);w(overlay+15,(last+1)%256)
    for _=1,5 do t.step({});assert(not M.isPartyWriteSafe(),"wrong digest released the game")end
    w(overlay+15,last);w(overlay+5,7)
    local release={body={cmd="native_trade_release",transaction_id=body.transaction_id,proposal_digest=body.proposal_digest},
        command_id=assert(Identity.new_nonce()),command_sequence=command_sequence+1}
    if spec.paired_directory then release=await_document(spec.paired_directory.."/release-"..player..".json")end
    assert(JSON.encode(lease_store:read().intent)==JSON.encode(intent),"native lease lost its prepared intent")
    local release_executor
    if spec.native_ui then
        local poll_release=assert(journal:append({event="tick"}))
        assert(journal:accept_response(poll_release,JSON.array({release})))
        release_executor=Executor.new(journal,adapter.release_executor())
        local ok,result=release_executor:step(release.command_id)
        assert(not ok and result.pending,"release must retain a durable intent while native return is pending")
    else
        adapter.release(release.body,{command_id=release.command_id,command_sequence=release.command_sequence})
    end
    observer:release()
    for _=1,300 do t.step({});if observer.after and M.isPartyWriteSafe()then break end end
    local after=observer.after
    assert(after and M.isPartyWriteSafe(),"foreground receipt did not return to ordinary play")
    local closure
    if release_executor then
        if spec.release_receipt_fault then
            local replace_release=command_store.backend.replace
            command_store.backend.replace=function()return false,"injected release receipt failure"end
            local ok,problem=release_executor:step(release.command_id)
            assert(not ok and problem.phase=="persist_receipt" and lease_store:read().phase=="released",
                "release receipt failure lost native completion")
            command_store.backend.replace=replace_release
            command_store:close();journal=open_command_store()
            adapter.close();lease_store:close()
            lease_store=assert(Store.open(assert(Storage.new(root.."/native.json")),binding,Native.initial()))
            adapter_options.store=lease_store;adapter=Native.new(adapter_options)
            release_executor=Executor.new(journal,adapter.release_executor())
        end
        local ok,result=release_executor:step(release.command_id);assert(ok,result.reason)
        closure=result.receipt
        local events=journal:pending_events();assert(#events==1 and events[1].payload.event=="trade_ack")
        require("tests.gen1_trade_ui_driver").exchange(spec.paired_directory.."/closure-"..player..".json",events[1])
        assert(journal:accept_response(events[1].operation_id,JSON.array()))
    else closure=adapter.finish_release()end
    assert(closure.native_command_id==command_id and lease_store:read().phase=="released","durable native closure absent")
    for name,value in pairs(before)do
        assert(after[name]==value+(name=="SP" and 2 or 0),"DelayFrame changed caller register "..name)
    end
    assert(after.bank==before.bank,"DelayFrame changed caller ROM bank")
    assert(M.bytesToHex(read_bytes(overlay,16))==M.bytesToHex(restored_union),"borrowed map/menu union was not restored")
    assert(M.getCurrentMap()==original_map and M.bytesToHex(read_bytes(a("wTileMap"),360))==original_tiles,"foreground trade changed the map presentation")
    assert(JSON.encode(party())==JSON.encode(traded),"receipt release changed the traded party")
    for _,name in ipairs({"InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData"})do assert(counts[name]==1,name.." did not execute once")end
    local file=assert(io.open(output_path,"w"))
    file:write(assert(JSON.encode({variant=t.variant,final_sha1=manifest.final_sha1,frames=frames,
        party=traded,before=before,after=after,service_sp=service_sp,counts=counts,union_restored=true,
        direct_cpu_redirect=false,runtime_ready=false,durable_receipt=receipt,journal_reopened=true,
        native_release_receipt=closure,release_receipt_fault=spec.release_receipt_fault or false,
        save_file_receipt=save_receipt,bounded_host=bounded_owner and bounded_owner.status()or nil,
        playback=pacer and {paced=true,elapsed=pacing_clock()-pacing_started,scheduled=pacer:status().scheduled,
            frame_rate=bounded_owner.status().frame_rate}or nil,
        native_lease_path=root.."/native.json",command_journal_path=root.."/commands.json",fault=spec.client_fault})));file:close()
end,debug.traceback)
if adapter then adapter.close()end
if command_store then command_store:close()end
if lease_store then lease_store:close()end
observer:close()
t.check("natural foreground trade and receipt release",ok,tostring(why))
t.finish()
