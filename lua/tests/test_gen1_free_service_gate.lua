-- Downloaded free_service launcher (proposals P4 + P10): a normal cold New Game, then the
-- client releases its hold and lua/gen1_observation_loop.lua observes the free-running core.
-- Inputs only; no CPU/register/cartridge writes or injected stop. Every hold the client
-- takes (heartbeat checkpoint, held writes) is its own and momentary. The phases in the
-- input spec sets production speed (100 = cartridge rate, 300 = 3x) and the frames each
-- must run; the gate reports frames and
-- monotonic seconds per phase so the test can compute the emulator-side FPS.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read(path)
    local file=io.open(path,"r");if not file then return nil end
    local value=assert(JSON.decode(file:read("*a")));file:close();return value
end
local input=assert(read(assert(os.getenv("SLINK_LAUNCHER_TEST_INPUT"))))
assert(input.cold_boot==true,"the free-service gate drives a normal cold New Game")
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_free_service_gate",{no_boot=true})
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
local clock=assert(dofile(ROOT.."/lua/platform_clock.lua").new())
local function independent_inventory()
    -- The gate's read-only full-source oracle at a between-frame boundary; no
    -- production debug command or additional public runtime capability.
    return require("gen1_full_save").capture(require("memory_gb"),t.variant)
end
local function publish(name,value)
    local path=input.directory.."/"..name.."-"..input.player..".json"
    local file=assert(io.open(path..".tmp","w"));file:write(assert(JSON.encode(value)));file:close()
    assert(os.rename(path..".tmp",path))
end
local screenshots=JSON.array()
local function shot(label)
    local path=input.directory.."/"..input.player.."-"..label..".png";client.screenshot(path);screenshots[#screenshots+1]=path
end
local symbols={}
do
    local source=t.variant=="yellow" and "pokeyellow" or "pokered"
    local target=t.variant=="blue" and "pokeblue" or source
    for line in io.lines(ROOT.."/.cache/pret/"..source.."/"..target..".sym")do
        local _,address,name=line:match("^(%x+):(%x+) (%S+)$");if address then symbols[name]=tonumber(address,16)end
    end
end
local function sym(name)return memory.read_u8(assert(symbols[name]),"System Bus")end
local idle={A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
local beat=0
local function menu_inputs()
    -- Same input-only recipe as the bootstrap and ordinary gates: mash A/Start through
    -- the intro, take NEW GAME on the title menu, accept default naming choices.
    beat=beat+1;local phase=beat%16
    local buttons={A=phase<2,Start=phase==8}
    if sym("wMaxMenuItem")==3 and sym("wTopMenuItemY")==2 and sym("wTopMenuItemX")==1 then
        buttons={Down=sym("wCurrentMenuItem")==0,A=sym("wCurrentMenuItem")>0 and phase<2}
    end
    local pressed={};for k,v in pairs(idle)do pressed[k]=buttons[k] or v end
    joypad.set(pressed)
end
publish("observed",{variant=t.variant,cold_boot=true})
local deadline=os.time()+45
while not read(input.directory.."/go.json")do assert(os.time()<deadline,"launcher startup timed out");t.step({})end
for _=1,120 do t.step({})end;shot("intro")
local PHASES=assert(input.phases)
assert(#PHASES>=1,"at least one free-running phase required")
local WINDOW=600
local original_yield,original_advance=emu.yield,emu.frameadvance
local held_frame,reported,finished=nil,false,false
local dirty_probe
local frames_driven,loop_started=0,nil
local phase_index,phase,phases=0,nil,JSON.array()
local function status_now()return SLINK_RUNTIME_STATUS and SLINK_RUNTIME_STATUS()end
local function begin_phase(status)
    phase_index=phase_index+1;phase=PHASES[phase_index]
    if not phase then return false end
    client.speedmode(phase.speed)
    client.frameskip(0)
    emu.minimizeframeskip(false)
    phase.began={frame=emu.framecount(),clock=clock(),pending_events=status.runtime.pending_events}
    phase.windows=JSON.array();phase.window={frame=emu.framecount(),clock=clock()}
    phase.diagnostics_before=status.observation_diagnostics
    phase.active={injected=false,restored=false,address=assert(symbols.wPartyDataStart)+403}
    return true
end
local function end_phase(status)
    local ended={frame=emu.framecount(),clock=clock(),pending_events=status.runtime.pending_events}
    local frames,seconds=ended.frame-phase.began.frame,ended.clock-phase.began.clock
    phases[#phases+1]={name=phase.name,speed=phase.speed,planned_frames=phase.frames,frames=frames,seconds=seconds,
        fps=frames/seconds,began=phase.began,ended=ended,windows=phase.windows,
        diagnostics={before=phase.diagnostics_before,after=status.observation_diagnostics},active=phase.active}
end
emu.yield=function()
    -- Held phases yield here, as the credit-loop gate does: normal inputs before the hold,
    -- then held service until the loop starts. Once the loop runs the entry advances
    -- frames itself and never yields.
    original_yield()
    assert(not read(input.directory.."/abort.json"),"paired free-service launcher test aborted")
    if reported and read(input.directory.."/finish.json")then
        shot("free-end");finished=true
        t.check("generated free-service launcher free-runs the bedroom and publishes observation batches",true)
        t.finish()
    end
    local status=status_now();if not status or status.observation_loop then return end
    if not status.host then
        menu_inputs();frames_driven=frames_driven+1
        assert(frames_driven<20000,"normal new game did not reach the held checkpoint")
        return
    end
    if not held_frame then held_frame=emu.framecount();shot("held-checkpoint");joypad.set(idle)end
    assert(status.host.physical_stop_verified and emu.framecount()==held_frame,"held service advanced the game before the loop")
end
emu.frameadvance=function()
    -- Free-running: the entry advances one frame per loop tick. Drive the profile inputs
    -- (one step Right, then idle) every frame; read the status every 120 frames, not every
    -- frame, so the gate itself does not shape the per-frame cost it measures.
    local status
    if not loop_started or dirty_probe or (emu.framecount()-loop_started.frame)%120==0 then status=status_now()end
    if not loop_started then
        if status and status.observation_loop then
            loop_started={frame=emu.framecount(),clock=clock()};shot("free-start");joypad.set(idle)
            assert(begin_phase(status))
        end
    else
        local buttons={};for key,value in pairs(idle)do buttons[key]=value end
        buttons.Right=emu.framecount()-loop_started.frame<16;joypad.set(buttons)
        if phase then
            local offset=emu.framecount()-phase.began.frame
            if not phase.active.injected and offset>=90 then
                phase.active.original=memory.read_u8(phase.active.address,"System Bus")
                phase.active.replacement=(phase.active.original+1)%256
                phase.active.injected_frame=emu.framecount()
                memory.write_u8(phase.active.address,phase.active.replacement,"System Bus")
                phase.active.injected=true
            elseif phase.active.injected and not phase.active.restored and offset>=180 then
                memory.write_u8(phase.active.address,phase.active.original,"System Bus")
                phase.active.restored_frame=emu.framecount();phase.active.restored=true
            end
        end
        if status then
            if phase and emu.framecount()-phase.window.frame>=WINDOW then
                local now=clock();local frames=emu.framecount()-phase.window.frame
                phase.windows[#phase.windows+1]={first_frame=phase.window.frame,last_frame=emu.framecount(),frames=frames,
                    seconds=now-phase.window.clock,fps=frames/(now-phase.window.clock)}
                phase.window={frame=emu.framecount(),clock=now}
            end
            assert(not read(input.directory.."/abort.json"),"paired free-service launcher test aborted")
            assert(status.phase=="free_service" and not status.runtime.failed,"free-service client failed: "..tostring(status.reason))
            assert(not status.engine_signals or not status.engine_signals.failed,"engine source observer failed while free-running")
            assert(status.runtime.connected and status.runtime.session_state=="admitted","client lost its admitted connection")
            if dirty_probe then
                local publications=status.observation_diagnostics.inventory_publications
                assert(emu.framecount()<dirty_probe.deadline,"inventory dirty probe did not settle")
                if dirty_probe.phase=="changed"and publications>=dirty_probe.before+1
                    and status.runtime.pending_events==0 then
                    memory.write_u8(dirty_probe.address,dirty_probe.original,"System Bus")
                    dirty_probe.phase="restored";dirty_probe.changed_frame=emu.framecount()
                elseif dirty_probe.phase=="restored"and publications>=dirty_probe.before+2
                    and status.runtime.pending_events==0 then
                    dirty_probe.restored_frame=emu.framecount();dirty_probe.after=publications
                    local proof=dirty_probe;dirty_probe=nil
                    publish("ready",{status=status,held_frame=held_frame,loop_started=loop_started,frame_after=emu.framecount(),
                        clock_after=clock(),frames_driven=frames_driven,screenshots=screenshots,phases=phases,
                        dirty_probe=proof,final_source=independent_inventory(),actual_generated_launcher=true})
                    reported=true
                end
            elseif not reported and phase and emu.framecount()-phase.began.frame>=phase.frames then
                end_phase(status)
                if not begin_phase(status) then
                    local address=assert(symbols.wPartyDataStart)+403
                    local original=memory.read_u8(address,"System Bus")
                    dirty_probe={schema="rby-inventory-dirty-negative-control-v1",phase="changed",address=address,
                        original=original,replacement=(original+1)%256,before=status.observation_diagnostics.inventory_publications,
                        began_frame=emu.framecount(),deadline=emu.framecount()+300}
                    memory.write_u8(address,dirty_probe.replacement,"System Bus")
                end
            end
            if reported and read(input.directory.."/finish.json")then
                shot("free-end");finished=true
                t.check("generated free-service launcher free-runs the bedroom and publishes observation batches",true)
                t.finish()
            end
        end
    end
    original_advance()
end
local ok,why=xpcall(function()dofile(input.launcher)end,debug.traceback)
emu.yield=original_yield;emu.frameadvance=original_advance
if not finished then
    pcall(function()shot("failed-frame")end)
    local status_ok,status=pcall(function()return SLINK_RUNTIME_STATUS and SLINK_RUNTIME_STATUS()end)
    publish("failure",{error=tostring(why),status=status_ok and status or tostring(status)})
    t.check("generated launcher completed free-service qualification",false,tostring(why));t.finish()
end
