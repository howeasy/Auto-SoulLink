-- Manager-selected canonical companion, blank SaveRAM, normal New Game inputs.
-- The native entry claims its owner BEFORE the first frame after launcher load;
-- the observed/go handshake and intro frames precede that load. Unlike the
-- non-native free-service gate, menu inputs must be supplied on clean boot frames.
-- No CPU/register/cartridge writes; the only WRAM edit is a restored byte probe.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read(path)
    local file=io.open(path,"r");if not file then return nil end
    local value=assert(JSON.decode(file:read("*a")));file:close();return value
end
local input=assert(read(assert(os.getenv("SLINK_LAUNCHER_TEST_INPUT"))))
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_native_selected_fresh_gate",{no_boot=true})
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local clock=assert(dofile(ROOT.."/lua/platform_clock.lua").new())
local function publish(name,value)
    local path=input.directory.."/"..name.."-"..input.player..".json"
    local file=assert(io.open(path..".tmp","w"));file:write(assert(JSON.encode(value)));file:close()
    assert(os.rename(path..".tmp",path))
end
local function shot(name)client.screenshot(input.directory.."/"..input.player.."-"..name..".png")end
local symbols={}
do
    local source=t.variant=="yellow"and"pokeyellow"or"pokered"
    local target=t.variant=="blue"and"pokeblue"or source
    for line in io.lines(ROOT.."/.cache/pret/"..source.."/"..target..".sym")do
        local _,address,name=line:match("^(%x+):(%x+) (%S+)$")
        if address then symbols[name]=tonumber(address,16)end
    end
end
local function sym(name)return memory.read_u8(assert(symbols[name]),"System Bus")end
local idle={A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
local beat=0
local function menu_inputs()
    beat=beat+1;local moment=beat%16
    local buttons={A=moment<2,Start=moment==8}
    if sym("wMaxMenuItem")==3 and sym("wTopMenuItemY")==2 and sym("wTopMenuItemX")==1 then
        buttons={Down=sym("wCurrentMenuItem")==0,A=sym("wCurrentMenuItem")>0 and moment<2}
    end
    local pressed={};for key,value in pairs(idle)do pressed[key]=buttons[key]or value end
    joypad.set(pressed)
end
local saveram=assert(os.getenv("SLINK_GATE_SAVERAM"))
local save_directory=assert(os.getenv("SLINK_SAVERAM_DIRECTORY"))
assert(saveram:sub(1,#save_directory)==save_directory and saveram:match("candidate%.SaveRAM$"),
    "the gate must use its isolated candidate SaveRAM")
local save=assert(io.open(saveram,"rb"));local blank=save:read("*a");save:close()
assert(blank==string.rep(string.char(255),0x8000),"native fresh gate requires blank SaveRAM")
assert(gameinfo.getromhash():lower()==input.rom_sha1,"gate did not boot the exact Manager artifact")
publish("observed",{variant=t.variant,rom_sha1=gameinfo.getromhash():lower(),
    saveram_path=saveram,saveram_directory=save_directory})
local deadline=os.time()+45
while not read(input.directory.."/go.json")do
    if read(input.directory.."/abort.json")then
        t.check("Manager-selected native launch reached the paired go signal",false,"aborted before go")
        t.finish();return
    end
    assert(os.time()<deadline,"Manager launch timed out");t.step({})
end
for _=1,120 do t.step({})end;shot("intro")

local original_yield,original_advance=emu.yield,emu.frameadvance
local early_claim_frame,held_frame,loop_started,first_client_frame,frames_driven=nil,nil,nil,nil,0
local phases=JSON.array();local planned=assert(input.phases)
local index,current,reported,finished=0,nil,false,false
local function status_now()return SLINK_RUNTIME_STATUS and SLINK_RUNTIME_STATUS()end
local function begin_phase(status)
    index=index+1;local spec=planned[index]
    if not spec then current=nil;return false end
    assert(spec.frames%600==0 and type(spec.active)=="boolean","bounded 600-frame windows required")
    client.speedmode(spec.speed);client.frameskip(0);emu.minimizeframeskip(false)
    current={name=spec.name,speed=spec.speed,active=spec.active,planned_frames=spec.frames,
        began={frame=emu.framecount(),clock=clock()},window={frame=emu.framecount(),clock=clock()},
        windows=JSON.array(),probes=JSON.array()}
    if spec.active then
        for _=1,spec.frames/600 do current.probes[#current.probes+1]={address=assert(symbols.wPartyDataStart)+403}end
    end
    if index==1 then assert(status.runtime.pending_events==0,"free loop begins with a backlog")end
    return true
end
local function finish_phase()
    local now=clock();local frame=emu.framecount()
    phases[#phases+1]={name=current.name,speed=current.speed,active=current.active,planned_frames=current.planned_frames,
        frames=frame-current.began.frame,seconds=now-current.began.clock,
        fps=(frame-current.began.frame)/(now-current.began.clock),windows=current.windows,probes=current.probes}
end
local function finish_if_requested()
    if reported and read(input.directory.."/finish.json")then
        shot("free-end");finished=true
        t.check("Manager-selected native free service ran the fresh bedroom",true);t.finish()
    end
end
emu.yield=function()
    original_yield()
    assert(not read(input.directory.."/abort.json"),"paired native selected gate aborted")
    finish_if_requested()
    local status=status_now()
    if not status or status.observation_loop then return end
    local reattach=status.native_reattach
    if status.host and status.host.physical_stop_verified and not early_claim_frame then
        early_claim_frame=emu.framecount()
    end
    if reattach and not held_frame then
        held_frame=emu.framecount()
        assert(status.host.physical_stop_verified and reattach.read.frame>=held_frame,
            "native reattach was not first read under the held owner")
        shot("held-reattach")
    end
    if reattach then assert(held_frame and reattach.read.frame>=held_frame,
        "the native read preceded the held reattach checkpoint")end
    if held_frame then
        assert(emu.framecount()==held_frame and status.host.physical_stop_verified,
            "native startup advanced before the server released its read")
    end
end
emu.frameadvance=function()
    local frame=emu.framecount()
    -- Do not call the full status/JSON encoder on each active frame: the
    -- existing strict gate samples every 120 frames for the same reason.
    local status=(not loop_started or (frame-loop_started.frame)%120==0)and status_now()or nil
    if not loop_started then
        if status and status.observation_loop then
            assert(held_frame and status.native_reattach and status.native_reattach.server
                and status.native_reattach.server.verdict=="released", "loop began without released native read")
            loop_started={frame=frame,clock=clock()};shot("free-start");joypad.set(idle)
            assert(begin_phase(status))
        else
            -- Native start owns and releases one *clean* boot frame at a time. The
            -- gate supplies ordinary menu buttons on those frames, never while held.
            assert(status and status.phase=="waiting_for_overworld" and not status.native_reattach,
                "unexpected pre-loop free frame")
            assert(status.host and status.host.owner_id==status.context.physical_instance
                and not status.host.held,"clean New Game frame lost its exclusive native owner")
            early_claim_frame=early_claim_frame or frame
            first_client_frame=first_client_frame or frame
            menu_inputs();frames_driven=frames_driven+1
            assert(frames_driven<20000,"normal New Game did not reach the held checkpoint")
        end
    else
        local buttons={};for key,value in pairs(idle)do buttons[key]=value end
        buttons.Right=frame-loop_started.frame<16;joypad.set(buttons)
        if current and current.active then
            local offset=frame-current.began.frame
            local probe=current.probes[math.floor(offset/600)+1]
            if probe then
                local inside=offset%600
                if not probe.injected and inside>=90 then
                    probe.original=memory.read_u8(probe.address,"System Bus")
                    probe.replacement=(probe.original+1)%256
                    probe.injected_frame=frame
                    memory.write_u8(probe.address,probe.replacement,"System Bus");probe.injected=true
                elseif probe.injected and not probe.restored and inside>=180 then
                    memory.write_u8(probe.address,probe.original,"System Bus")
                    probe.restored_frame=frame;probe.restored=true
                end
            end
        end
        if status and (frame-loop_started.frame)%120==0 then
            assert(status.phase=="free_service" and status.runtime.connected
                and status.runtime.session_state=="admitted" and not status.runtime.failed,
                "native-selected free client lost its admitted service")
            assert(not status.engine_signals or not status.engine_signals.failed,"source observer failed")
            if current and frame-current.window.frame>=600 then
                local now=clock();local elapsed=now-current.window.clock
                current.windows[#current.windows+1]={first_frame=current.window.frame,last_frame=frame,
                    frames=frame-current.window.frame,seconds=elapsed,fps=(frame-current.window.frame)/elapsed,
                    pending_events=status.runtime.pending_events}
                current.window={frame=frame,clock=now}
            end
            if current and frame-current.began.frame>=current.planned_frames then
                finish_phase();begin_phase(status)
            elseif not current and not reported and status.runtime.pending_events==0 then
                publish("ready",{status=status,held_frame=held_frame,loop_started=loop_started,
                    early_claim_frame=early_claim_frame,first_client_frame=first_client_frame,
                    frame_after=frame,frames_driven=frames_driven,phases=phases,
                    final_source=require("gen1_full_save").capture(require("memory_gb"),t.variant)})
                reported=true
            end
            finish_if_requested()
        end
    end
    original_advance()
end
local ok,why=xpcall(function()dofile(input.launcher)end,debug.traceback)
emu.yield=original_yield;emu.frameadvance=original_advance
if not finished then
    pcall(function()shot("failed-frame")end)
    local status_ok,status=pcall(status_now)
    publish("failure",{error=tostring(why),status=status_ok and status or tostring(status)})
    t.check("Manager-selected native free-service launcher completed",false,tostring(why));t.finish()
end
