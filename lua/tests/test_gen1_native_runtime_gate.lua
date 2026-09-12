-- Only fixture bootstrap and user buttons are supplied here. Native command
-- routing, TCP, preparation, authority/windows, frames and save receipts are real.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local JSON=require("json_codec")
local function read(path)
    local f=io.open(path,"r");if not f then return nil end
    local value=assert(JSON.decode(f:read("*a")));f:close();return value
end
local input=assert(read(os.getenv("SLINK_NATIVE_RUNTIME_INPUT")))
local map_fixture=require("tests.gen1_map_fixture").start(input.fixture~=JSON.null and input.fixture or nil,"native-tcp")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_native_runtime_gate")
map_fixture:close()
local function publish(name,value)
    local path=input.directory.."/"..name.."-"..input.player..".json"
    local f=assert(io.open(path..".tmp","w"));f:write(assert(JSON.encode(value)));f:close()
    assert(os.rename(path..".tmp",path))
end
local service
local ok,why=xpcall(function()
    local mem=t.M;local blob=assert(mem.hexToBytes(input.blob))
    for i=1,44 do mem.write_u8(mem.PARTY_BASE_ADDR+i-1,blob[i])end
    for i=1,11 do
        mem.write_u8(mem.PARTY_OT_NAMES_ADDR+i-1,blob[44+i]);mem.write_u8(mem.PARTY_NICKS_ADDR+i-1,blob[55+i])
    end
    mem.write_u8(mem.PARTY_COUNT_ADDR,1);mem.write_u8(mem.PARTY_SPECIES_ADDR,blob[1]);mem.write_u8(mem.PARTY_SPECIES_ADDR+1,255)
    for _=1,180 do if mem.isPartyWriteSafe()then break end;t.step({})end
    assert(mem.isPartyWriteSafe())
    if input.receptionist then
        for frame=1,300 do
            t.step(frame<=8 and {Up=true} or {A=frame%30<6})
            if require("gen1_receptionist_client").query(mem,input.manifest)then break end
        end
        assert(require("gen1_receptionist_client").query(mem,input.manifest),"physical A did not open original receptionist query")
    end
    client.speedmode(100)
    service=require("gen1_native_runtime").new({memory=mem,manifest=input.manifest,
        player=input.player,variant=t.variant,run_id=input.run_id,server_host="127.0.0.1",server_port=input.port,
        prepared_cartridge=input.cartridge,receptionist=input.receptionist,
        storage_directory=input.directory.."/client-"..input.player,saveram_path=os.getenv("SLINK_GATE_SAVERAM")})
    local choice_frame,menu_frame,notice_frame;local native_calls={};local native_hooks={}
    if input.receptionist then
        for _,item in ipairs({{input.manifest.receptionist.menu_input,function()menu_frame=emu.framecount()end},
            {input.manifest.receptionist.notice,function()notice_frame=emu.framecount()end},
            {input.manifest.receptionist.notice_done,function()notice_frame=nil end}})do
            native_hooks[#native_hooks+1]=event.on_bus_exec(function()
                if memory.read_u8(input.manifest.ram.hLoadedROMBank,"System Bus")==input.manifest.receptionist.entry.bank then item[2]()end
            end,item[1],"native-tcp-receptionist-buttons-"..item[1],"System Bus")
        end
    end
    for _,name in ipairs({"InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData"})do
        local routine=input.manifest.native_calls[name]
        native_hooks[#native_hooks+1]=event.on_bus_exec(function()
            if routine.bank==0 or memory.read_u8(input.manifest.ram.hLoadedROMBank,"System Bus")==routine.bank then
                native_calls[name]=(native_calls[name]or 0)+1
            end
        end,routine.address,"native-runtime-independent-"..name,"System Bus")
    end
    local choice_hook=event.on_bus_exec(function()
        if memory.read_u8(input.manifest.ram.hLoadedROMBank,"System Bus")==input.manifest.receptionist.partner_prompt.bank then
            choice_frame=emu.framecount()
        end
    end,input.manifest.receptionist.partner_prompt.choice,"native-runtime-choice-buttons","System Bus")
    local checkpoint=service:checkpoint();local initial=service:status()
    publish("observed",{checkpoint=checkpoint,snapshot=checkpoint.party,context=initial.context,
        final_sha1=input.manifest.final_sha1,host=initial.host,save_path=os.getenv("SLINK_GATE_SAVERAM")})
    local clock=assert(require("platform_clock").new());local deadline=clock()+200
    while not read(input.directory.."/go.json")do assert(clock()<deadline);assert(service.host.yield_held())end
    local complete=false;local stopped_frame,stopped_at
    while clock()<deadline do
        -- Simulated physical buttons only. The production service owns every frame.
        if service.receptionist and service.receptionist.active then
            local sequence=service.receptionist.active.sequence
            local age=emu.framecount()-(notice_frame or menu_frame or emu.framecount())
            local row=input.receptionist_choice=="cancel" and 2 or input.receptionist_choice=="cable" and 1 or 0
            local down=not notice_frame and ((row>=1 and age>=20 and age<25)or(row==2 and age>=40 and age<45))
            joypad.set({Down=down,A=sequence[#sequence]=="cable" and emu.framecount()%30<6
                or notice_frame and age>=12 and age%30<6 or not notice_frame and age>=90 and age<96})
        elseif service.prompt.execution_phase=="armed"then
            local age=choice_frame and emu.framecount()-choice_frame
            local pressed=age~=nil and age>=35 and age<41
            joypad.set(input.decision=="decline" and {B=pressed} or {A=pressed})
        elseif service.prompt.execution_phase=="closing" or service.native.execution_phase=="releasing"then
            joypad.set({})
        else joypad.set({A=emu.framecount()%20<8})end
        local stepped,problem=service:step();assert(stepped,problem)
        if not input.expected_disconnect and service.metrics.first_native_revocation then
            error(service.metrics.first_native_revocation..": "..tostring(service.metrics.native_window_refusal))
        end
        if not input.expected_disconnect and service.metrics.first_operation_revocation then
            error(service.metrics.first_operation_revocation..": "..tostring(service.metrics.native_window_refusal))
        end
        if input.expected_disconnect and service.native.execution_phase=="armed" and service.binding==nil then
            if not stopped_frame then stopped_frame=emu.framecount();stopped_at=clock()end
            assert(emu.framecount()==stopped_frame,"socket loss permitted another native frame")
            if clock()-stopped_at>=2.25 and not complete then
                complete=true
                publish("stopped",{frame_before=stopped_frame,frame_after=emu.framecount(),status=service:status()})
            end
        elseif stopped_frame then
            assert(emu.framecount()==stopped_frame,"reconnection silently resumed native animation")
            if clock()-stopped_at>=2.25 and not complete then
                complete=true
                publish("stopped",{frame_before=stopped_frame,frame_after=emu.framecount(),status=service:status()})
            end
        end
        local refusal=input.decision=="decline" or input.decision=="late"
        local returned=service.native.execution_phase=="released" or (refusal and (input.player=="a" or service.prompt.execution_phase=="closed"))
        returned=returned or input.ui_only and (input.player=="b" or service.receptionist_store:read().phase=="complete")
        if returned and service.current==nil and (service.command_store:read().command_floor>0 or input.ui_only and input.player=="b")then
            local status=service:status()
            if status.runtime.failed then error(status.runtime.failure)end
            if not status.runtime.binding_missing and status.runtime.pending_events==0 and status.runtime.pending_commands==0 then
            if not complete then
                complete=true
                publish("complete",{status=status,lease=service.native_store:read(),journal=service.command_store:read(),
                    preparation=service.preparation_store:read(),native_calls=native_calls,
                    receptionist=service.receptionist_store and service.receptionist_store:read()})
            end
            end
        end
        if read(input.directory.."/finish.json")then break end
        assert(service.host.yield_held())
    end
    assert(complete,"native runtime did not finish the paired commands")
    event.unregisterbyid(choice_hook)
    for _,hook in ipairs(native_hooks)do event.unregisterbyid(hook)end
end,debug.traceback)
if not ok then publish("error",{reason=tostring(why),status=service and service:status()or nil})end
if service then pcall(function()service:close()end)end
t.check("owned native TCP/window/animation/save/closure path",ok,tostring(why));t.finish()
