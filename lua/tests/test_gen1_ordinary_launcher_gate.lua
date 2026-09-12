-- Downloaded ordinary launcher: normal New Game, finite server-granted bedroom
-- steps, then an explicit grant refusal. Inputs only; no CPU/register/cartridge
-- writes or injected stop. The client owns its one bounded host throughout.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read(path)
    local file=io.open(path,"r");if not file then return nil end
    local value=assert(JSON.decode(file:read("*a")));file:close();return value
end
local input=assert(read(assert(os.getenv("SLINK_LAUNCHER_TEST_INPUT"))))
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_ordinary_launcher_gate",{no_boot=input.cold_boot==true})
local M=t.M
package.path=ROOT.."/lua/?.lua;"..ROOT.."/data/games/gen1_rby/?.lua;"..package.path
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
if input.cold_boot then
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
    -- Same input-only recipe as the repaired bootstrap gate: mash A/Start through
    -- the intro, take NEW GAME on the title menu, accept default naming choices.
    beat=beat+1;local phase=beat%16
    local buttons={A=phase<2,Start=phase==8}
    if sym("wMaxMenuItem")==3 and sym("wTopMenuItemY")==2 and sym("wTopMenuItemX")==1 then
        buttons={Down=sym("wCurrentMenuItem")==0,A=sym("wCurrentMenuItem")>0 and phase<2}
    end
    local pressed={};for k,v in pairs(idle)do pressed[k]=buttons[k] or v end
    joypad.set(pressed)
end
publish("observed",{variant=t.variant,cold_boot=input.cold_boot==true})
local deadline=os.time()+45
while not read(input.directory.."/go.json")do assert(os.time()<deadline,"launcher startup timed out");t.step({})end
if input.cold_boot then
    for _=1,120 do t.step({})end;shot("intro")
else
    for _=1,180 do if M.isPartyWriteSafe()then break end;t.step({})end
    assert(M.isPartyWriteSafe(),"fixture launch needs a verified initial checkpoint")
end
local original_yield=emu.yield
local held_frame,reported,finished=nil,false,false
local frames_driven=0
local refused_frame,refused_ticks=nil,0
local recorded_revocations=0
emu.yield=function()
    original_yield()
    assert(not read(input.directory.."/abort.json"),"paired ordinary launcher test aborted")
    if not SLINK_RUNTIME_STATUS then return end
    local status=SLINK_RUNTIME_STATUS()
    if not status.host then
        -- Before the client's own hold: ordinary frames under normal inputs only.
        if input.cold_boot then menu_inputs();frames_driven=frames_driven+1
            assert(frames_driven<20000,"normal new game did not reach the held checkpoint") end
        return
    end
    if not held_frame then held_frame=emu.framecount();shot("held-checkpoint");joypad.set(idle)end
    assert(status.host.physical_stop_verified,"ordinary step did not restore its owned hold")
    assert(not status.engine_signals or not status.engine_signals.failed,"engine source observer failed while moving")
    local progress=status.frame_progress
    if progress and #progress.metrics.revocations>recorded_revocations then
        recorded_revocations=#progress.metrics.revocations
        publish("revocation-"..recorded_revocations,status)
    end
    local moved=emu.framecount()-held_frame
    local buttons={};for key,value in pairs(idle)do buttons[key]=value end
    buttons.Right=moved<16;joypad.set(buttons)
    local refused=progress and progress.sequence>=1 and not progress.window.available
        and progress.metrics.declined_frame==emu.framecount()and moved>=8
    if refused then
        if refused_frame==emu.framecount()then refused_ticks=refused_ticks+1 else refused_frame=emu.framecount();refused_ticks=1 end
    else refused_ticks=0 end
    local runtime=status.runtime
    local enrolled=status.initial_observation=="acknowledged"
    local proved=not input.cold_boot or status.bootstrap_observation=="acknowledged"
    if runtime and runtime.session_state=="admitted" and enrolled and proved and refused_ticks>=20 and not reported then
        publish("ready",{status=status,held_frame=held_frame,frame_after=emu.framecount(),frames_driven=frames_driven,
            screenshots=screenshots,actual_generated_launcher=true,refused_ticks=refused_ticks})
        reported=true
    end
    if reported and read(input.directory.."/finish.json")then
        if input.cold_boot then shot("initial-save-complete")end
        shot("ordinary-refusal")
        finished=true
        t.check("generated launcher consumes server frames and holds when further grants are denied",true)
        t.finish()
    end
end
local ok,why=xpcall(function()dofile(input.launcher)end,debug.traceback)
emu.yield=original_yield
if not finished then
    pcall(function()shot("failed-held-frame")end)
    local status_ok,status=pcall(function()return SLINK_RUNTIME_STATUS and SLINK_RUNTIME_STATUS()end)
    publish("failure",{error=tostring(why),status=status_ok and status or tostring(status)})
    t.check("generated launcher completed ordinary frame qualification",false,tostring(why));t.finish()
end
