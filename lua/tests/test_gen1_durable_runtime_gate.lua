-- Actual clean RBY host, LuaSocket, flushed journal and independent execution hold.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_durable_runtime_gate")
local M=t.M
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local JSON=require("json_codec")
local function read_file(path)
    local file=io.open(path,"r");if not file then return nil end
    local value=assert(JSON.decode(file:read("*a")));file:close();return value
end
local input=assert(read_file(assert(os.getenv("SLINK_DURABLE_RUNTIME_INPUT"))))
local function publish(name,value)
    local path=input.directory.."/"..name.."-"..input.player..".json"
    local file=assert(io.open(path..".tmp","w"));file:write(assert(JSON.encode(value)));file:close()
    assert(os.rename(path..".tmp",path))
end
local function bytes(address,count)
    local out={};for i=0,count-1 do out[#out+1]=memory.read_u8(address+i,"System Bus")end;return out
end
local host,store,runtime
local ok,why=xpcall(function()
    for _=1,180 do if M.isPartyWriteSafe()then break end;t.step({})end
    assert(M.isPartyWriteSafe(),"initial owned overworld checkpoint required")
    -- Test fixture setup only; every network/held assertion starts afterward.
    local blob=assert(M.hexToBytes(input.blob))
    for i=1,44 do M.write_u8(M.PARTY_BASE_ADDR+i-1,blob[i])end
    for i=1,11 do
        M.write_u8(M.PARTY_OT_NAMES_ADDR+i-1,blob[44+i]);M.write_u8(M.PARTY_NICKS_ADDR+i-1,blob[55+i])
    end
    M.write_u8(M.PARTY_COUNT_ADDR,1);M.write_u8(M.PARTY_SPECIES_ADDR,blob[1]);M.write_u8(M.PARTY_SPECIES_ADDR+1,255)
    local observed=assert(require("gen1_command_receipts").party_snapshot(M,t.variant))
    local Identity=require("platform_identity")
    local owner=assert(Identity.new_nonce())
    local generation=assert(Identity.new_nonce())
    local Execution=require("platform_execution")
    host=assert(Execution.new({owner_id=owner,profile="gambatte",exclusive_ownership="emulator_process",
        control_context="between_frames",expected_host=assert(Execution.supported_profile("gambatte"))}))
    assert(host.set_held(true,"durable runtime live qualification"))
    local first_frame=emu.framecount()
    local before=M.bytesToHex(bytes(0xC000,0x2000))
    local context={context_generation=generation,physical_instance=owner,
        save_identity={ot_id=observed.save_id,trainer_name=observed.save_name}}
    publish("observed",{variant=t.variant,context=context,snapshot=observed,frame=first_frame,
        host=host.status(),save_path=os.getenv("SLINK_GATE_SAVERAM")})
    local clock=assert(require("platform_clock").new())
    local deadline=clock()+45
    while not read_file(input.directory.."/go.json")do
        assert(clock()<deadline,"runtime bootstrap signal timed out")
        assert(host.yield_held())
    end
    local Journal=require("client_journal")
    local storage=require("platform_storage")
    store=assert(require("state_store").open(assert(storage.new(input.directory.."/client-"..input.player..".json")),
        {run=input.run_id,player=input.player,context=context},Journal.initial()))
    local journal=assert(Journal.open(store))
    local apply_count=0
    runtime=assert(require("gen1_runtime").new({player=input.player,variant=t.variant,run_id=input.run_id,
        server_host="127.0.0.1",server_port=input.port,transport=require("connector"),
        journal=journal,clock=clock,host=host,
        read_context=function()
            assert(host.status().physical_stop_verified,"physical host context changed")
            return context
        end,
        operation_ready=function()return false,"held transport qualification; physical executor unselected"end,
        executor_adapter={prepare=function()error("unexpected preparation")end,classify=function()error("unexpected classification")end,
            apply=function()apply_count=apply_count+1;error("unexpected native effect")end,
            receipt=function()error("unexpected physical receipt")end}}))
    local operation,done,report
    deadline=clock()+25
    while clock()<deadline do
        assert(runtime:step())
        local status=runtime:status()
        assert(emu.framecount()==first_frame and host.status().held and apply_count==0,"held runtime advanced or wrote")
        assert(M.bytesToHex(bytes(0xC000,0x2000))==before,"held network service changed WRAM")
        if status.session_state=="admitted" then
            if input.player=="a" and not operation then
                local ids=assert(runtime:observe(JSON.array({{event="faint",key=input.key}}),{schema="live-runtime-baseline-v1",hp=0}))
                operation=ids[1]
            end
            local document=assert(store:read())
            if input.player=="a" and operation then
                local retained=false
                for _,entry in ipairs(document.outbox)do if entry.operation_id==operation then retained=true end end
                done=not retained
            elseif input.player=="b" then
                for _,entry in ipairs(document.inbox)do
                    if entry.body.cmd=="force_faint" and entry.body.body.key==input.key and not entry.outcome then done=true end
                end
            end
            if done and not report then
                report={player=input.player,variant=t.variant,frame_before=first_frame,frame_after=emu.framecount(),
                    host=host.status(),applied=apply_count,state=document,status=status,operation_id=operation,
                    wram_unchanged=true,physical_execution_qualified=false}
                publish("ready",report)
            end
        end
        if report and read_file(input.directory.."/finish.json")then break end
        assert(host.yield_held())
    end
    assert(report and done,"durable paired delivery did not complete under the hold")
    runtime:revoke("live qualification complete; fixture processes are exiting")
    assert(emu.framecount()==first_frame and M.bytesToHex(bytes(0xC000,0x2000))==before,"shutdown changed held game")
end,debug.traceback)
if runtime then pcall(function()runtime:revoke("qualification ending")end)end
if store then store:close()end
-- The test process exits while held; no ordinary-play release is manufactured.
t.check("actual durable network service remains independently held",ok,tostring(why))
t.finish()
