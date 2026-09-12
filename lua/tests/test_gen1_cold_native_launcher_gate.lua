-- Actual composed HTTP launcher from blank SaveRAM; only physical button inputs.
local ROOT=SLINK_ROOT or os.getenv("SLINK_ROOT")
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read(path)
    local file=io.open(path,"r");if not file then return nil end
    local text=file:read("*a");file:close();return JSON.decode(text)
end
local input=assert(read(assert(os.getenv("SLINK_COLD_NATIVE_INPUT"))))
local G=dofile(ROOT.."/lua/tests/gatelib.lua")
local t=G.start("test_gen1_cold_native_launcher_gate",{no_boot=true})
local symbols={}
local repo=t.variant=="yellow"and"pokeyellow"or"pokered"
local target=t.variant=="blue"and"pokeblue"or repo
for line in io.lines(ROOT.."/.cache/pret/"..repo.."/"..target..".sym")do
    local _,address,name=line:match("^(%x+):(%x+) (%S+)$")
    if address then symbols[name]=tonumber(address,16)end
end
local function byte(name)return memory.read_u8(assert(symbols[name],"missing route symbol: "..name),"System Bus")end
local function publish(name,value)
    local path=input.directory.."/"..name.."-"..input.player..".json"
    local file=assert(io.open(path..".tmp","w"));file:write(assert(JSON.encode(value)));file:close()
    local previous=io.open(path,"r");if previous then
        previous:close();local removed,why=os.remove(path)
        -- Route snapshots are diagnostics only. Windows readers can briefly
        -- deny replacement; retain the old snapshot and retry next boundary.
        if not removed and name=="route"then return false end
        assert(removed,why)
    end
    assert(os.rename(path..".tmp",path))
end
local function shot(label)client.screenshot(input.directory.."/"..input.player.."-"..label..".png")end
local idle={A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
local Driver=dofile(ROOT.."/lua/tests/gen1_cold_trade_inputs.lua")
local driver=Driver.new({variant=t.variant,initiator=input.player=="a",max_frames=24000})
local timing=dofile(ROOT..'/lua/tests/gen1_cold_timing.lua').install(ROOT,JSON)
publish("booted",{variant=t.variant,blank_boot=true})
local deadline=os.time()+60
while not read(input.directory.."/go.json")do assert(os.time()<deadline,"cold launcher startup timed out");t.step({})end
for _=1,120 do t.step({})end;shot("intro")
local original_yield=emu.yield
local beat,previous_phase,previous_frame,finished=0,nil,nil,false
local calls={};local hooked=false
local pending_shots={};local animation_frame;local animation_shots={};local linked_shot=false
local function hooks()
    if hooked then return end;hooked=true
    for _,name in ipairs({"InternalClockTradeAnim","TryEvolvingMon","SavePartyAndDexData"})do
        local routine=assert(input.manifest.native_calls[name])
        assert(event.on_bus_exec(function()
            if routine.bank==0 or byte("hLoadedROMBank")==routine.bank then
                calls[name]=(calls[name]or 0)+1
                if name=="InternalClockTradeAnim"then animation_frame=emu.framecount()end
            end
        end,routine.address,"cold-native-independent-"..name,"System Bus"))
    end
    local restore=require('gen1_identity_sites').titles[t.variant].sites.restore_done
    assert(event.on_bus_exec(function()
        if byte('hLoadedROMBank')==restore.bank then pending_shots['tutorial-restored']=true end
    end,restore.address,'cold-native-tutorial-restored','System Bus'))
end
emu.yield=function()
    original_yield()
    assert(not read(input.directory.."/abort.json"),"paired cold native route aborted")
    if not SLINK_RUNTIME_STATUS then return end
    local status=SLINK_RUNTIME_STATUS()
    if not status.host then
        beat=beat+1;local phase=beat%16;local buttons={A=phase<2,Start=phase==8}
        if byte("wMaxMenuItem")==3 and byte("wTopMenuItemY")==2 and byte("wTopMenuItemX")==1 then
            buttons={Down=byte("wCurrentMenuItem")==0,A=byte("wCurrentMenuItem")>0 and phase<2}
        end
        local pressed={};for name in pairs(idle)do pressed[name]=buttons[name]or false end
        joypad.set(pressed);assert(beat<20000,"normal New Game did not finish");return
    end
    hooks()
    assert(status.host.physical_stop_verified,"composed owner did not return to its hold")
    local server=read(input.directory.."/handshake.json")or {}
    local progress={enrolled=status.initial_observation=="acknowledged",bootstrap=status.bootstrap_observation=="acknowledged",
        saved=server.saved==true,linked=server.linked==true,both_at_center=server.both_at_center==true,
        trade_complete=server.trade_complete==true,native_borrowed=status.frame_progress and status.frame_progress.native_borrowed==true}
    for label in pairs(pending_shots)do shot(label);pending_shots[label]=nil end
    if progress.linked and not linked_shot then shot('starter-settled');linked_shot=true end
    if animation_frame then
        for _,offset in ipairs({0,60,180,360,600})do
            if emu.framecount()-animation_frame>=offset and not animation_shots[offset]then
                shot('native-animation-'..offset);animation_shots[offset]=true
            end
        end
    end
    local query=require("gen1_receptionist_client").query(t.M,input.manifest)
    local point={frame=emu.framecount(),map=byte("wCurMap"),x=byte("wXCoord"),y=byte("wYCoord"),
        battle=byte("wIsInBattle"),battle_type=byte("wBattleType"),joy_ignore=byte("wJoyIgnore"),party_count=byte("wPartyCount"),
        naming_screen=byte("wNamingScreenType"),safe=t.M.isPartyWriteSafe(),text_active=byte("wFontLoaded")%2==1,
        starter=math.floor(byte("wStatusFlags4")/8)%2==1,
        native_query=query~=nil,menu={top_x=byte("wTopMenuItemX"),top_y=byte("wTopMenuItemY"),
            maximum=byte("wMaxMenuItem"),index=byte("wCurrentMenuItem")}}
    local buttons,phase=driver:buttons(point,progress);joypad.set(buttons)
    if phase~=previous_phase then
        previous_phase=phase;shot(phase)
        publish("route",{route=driver:status(),point=point,status=status,native_calls=calls})
    elseif previous_frame==nil or point.frame-previous_frame>=120 then
        publish("route",{route=driver:status(),point=point,status=status,native_calls=calls})
    end
    previous_frame=previous_frame or point.frame
    if point.frame-previous_frame>=120 then previous_frame=point.frame end
    if server.trade_complete and not progress.native_borrowed then
        shot("trade-complete")
        publish("complete",{route=driver:status(),point=point,status=status,native_calls=calls})
        publish('timing',timing.report())
        finished=true;t.check("cold composed launcher reaches original trade and returns its frame owner",true);t.finish()
    end
end
local ok,why=xpcall(function()dofile(input.launcher)end,debug.traceback)
emu.yield=original_yield
if not finished then
    pcall(function()shot("failed-route")end)
    publish("error",{error=tostring(why),route=driver:status(),frame=emu.framecount(),map=byte("wCurMap"),x=byte("wXCoord"),y=byte("wYCoord")})
    publish('timing',timing.report())
    t.check("cold composed route completed",false,tostring(why));t.finish()
end
