-- Test-only wrapper for the unchanged Manager launcher. Normal New Game keys
-- occur only on the already owned native boot-frame call; no extra frame is
-- advanced by this wrapper after the launcher starts.
local ROOT=assert(SLINK_ROOT or os.getenv("SLINK_ROOT"))
local JSON=dofile(ROOT.."/lua/json_codec.lua")
local function read(path)
    local file=assert(io.open(path,"r"));local value=assert(JSON.decode(file:read("*a")))
    file:close();return value
end
local function read_optional(path)
    local file=io.open(path,"r");if not file then return nil end
    local value=assert(JSON.decode(file:read("*a")));file:close();return value
end
local input=read(assert(os.getenv("SLINK_SCRIPTED_INPUT")))
assert(input.schema=="gen1-scripted-normal-buttons-v1" and (input.player=="a" or input.player=="b")
    and (input.variant=="red" or input.variant=="blue" or input.variant=="yellow"))
assert(gameinfo.getromhash():lower()==input.rom_sha1,"scripted host booted a different cartridge")
local function publish(path,value)
    local file=assert(io.open(path..".tmp","w"))
    file:write(assert(JSON.encode(value)));file:close()
    os.remove(path)
    assert(os.rename(path..".tmp",path))
end
local idle={A=false,B=false,Start=false,Select=false,Up=false,Down=false,Left=false,Right=false}
local original_advance,original_yield=emu.frameadvance,emu.yield
local deadline=os.time()+input.deadline_seconds
local frames,beat,stopped=0,0,false
local route_driver,route_expected,route_phase,route_frames=nil,nil,nil,0
local function status_now()return SLINK_RUNTIME_STATUS and SLINK_RUNTIME_STATUS()end
local symbols={}
do
    local variant=input.variant
    local source=variant=="yellow"and"pokeyellow"or"pokered"
    local target=variant=="yellow"and"pokeyellow"or"pokeblue"
    if variant=="red"then target="pokered"end
    for line in io.lines(ROOT.."/.cache/pret/"..source.."/"..target..".sym")do
        local _,address,name=line:match("^(%x+):(%x+) (%S+)$")
        if address then symbols[name]=tonumber(address,16)end
    end
end
local function sym(name)return memory.read_u8(assert(symbols[name]),"System Bus")end
local function menu_inputs()
    beat=beat+1;local moment=beat%16
    local buttons={A=moment<2,Start=moment==8}
    if sym("wMaxMenuItem")==3 and sym("wTopMenuItemY")==2 and sym("wTopMenuItemX")==1 then
        buttons={Down=sym("wCurrentMenuItem")==0,A=sym("wCurrentMenuItem")>0 and moment<2}
    end
    local pressed={};for key,value in pairs(idle)do pressed[key]=buttons[key]or value end
    joypad.set(pressed)
end
local function route_point()
    local event_byte=memory.read_u8(assert(symbols.wEventFlags)+4,"System Bus")
    local hp=memory.read_u8(assert(symbols.wPartyMon1HP),"System Bus")*256
        +memory.read_u8(assert(symbols.wPartyMon1HP)+1,"System Bus")
    return {map=sym("wCurMap"),x=sym("wXCoord"),y=sym("wYCoord"),
        party_count=sym("wPartyCount"),battle=sym("wIsInBattle"),opponent=sym("wCurOpponent"),
        menu_y=sym("wTopMenuItemY"),menu_x=sym("wTopMenuItemX"),menu_max=sym("wMaxMenuItem"),
        menu_index=sym("wCurrentMenuItem"),move2=memory.read_u8(assert(symbols.wBattleMonMoves)+1,"System Bus"),
        move2_pp=memory.read_u8(assert(symbols.wBattleMonPP)+1,"System Bus"),
        text_box=sym("wTextBoxID"),lab_script=sym("wOaksLabCurScript"),
        pallet_script=sym("wPalletTownCurScript"),joy_ignore=sym("wJoyIgnore"),
        npc_moving=sym("wStatusFlags5")%2==1,
        battle_result=sym("wBattleResult"),party_hp=hp,
        lab_rival_done=math.floor(event_byte/8)%2==1}
end

publish(input.progress,{stage="wrapper-ready",player=input.player,frame=emu.framecount(),boot_frames=0})
local function wrapped_yield()
    local status=status_now()
    if status and (status.host and status.host.held or status.native_reattach)then joypad.set(idle)end
    if route_driver and status and status.context and (status.context.context_generation~=route_expected.context_generation
        or status.context.physical_instance~=route_expected.physical_instance)then
        error("R/B route changed admitted context during a hold")
    end
    return original_yield()
end
local function wrapped_advance()
    local status=assert(status_now(),"selected runtime status missing")
    if status.observation_loop then
        joypad.set(idle)
        if not stopped then
            stopped=true
            publish(input.progress,{stage="input-stopped",player=input.player,frame=emu.framecount(),boot_frames=frames})
        end
        if input.route then
            assert(input.route.mode=="rb-starter-rival" and input.variant~="yellow")
            local handshake=read_optional(input.route.handshake)
            if handshake and not route_driver then
                assert(status.context and status.host and status.host.owner_id==status.context.physical_instance,
                    "R/B route needs the current owned context")
                route_expected={run_id=input.run_id,player=input.player,rom_sha1=input.rom_sha1,
                    context_generation=status.context.context_generation,
                    physical_instance=status.context.physical_instance}
                route_driver=assert(dofile(input.route.module)).new(route_expected)
            end
            local buttons,phase
            if route_driver then
                route_frames=route_frames+1
                assert(route_frames<120000,"R/B starter/rival route made no bounded progress")
                buttons,phase=route_driver.step(handshake,status,route_point(),emu.framecount())
            else buttons,phase=idle,"await-pair-handshake"end
            joypad.set(buttons)
            if phase~=route_phase or route_frames%600==0 then
                route_phase=phase
                publish(input.route.progress,{stage=phase,player=input.player,frame=emu.framecount(),
                    route_frames=route_frames,point=route_driver and route_point() or JSON.null})
            end
            if phase=="lab-loss-complete" then
                joypad.set(idle)
                if emu.frameadvance==wrapped_advance then emu.frameadvance=original_advance end
                if emu.yield==wrapped_yield then emu.yield=original_yield end
            end
        else
            if emu.frameadvance==wrapped_advance then emu.frameadvance=original_advance end
            if emu.yield==wrapped_yield then emu.yield=original_yield end
        end
    else
        assert(os.time()<deadline and frames<input.max_boot_frames,"scripted New Game made no bounded progress")
        assert(status.phase=="waiting_for_overworld" and not status.native_reattach,
            "scripted input refused outside clean boot")
        assert(status.host and status.host.lease_owned and status.host.owner_id
            and (not status.context or status.host.owner_id==status.context.physical_instance)
            and not status.host.held,"scripted input requires the clean native owner")
        menu_inputs();frames=frames+1
        if frames%120==0 then
            publish(input.progress,{stage="normal-buttons",player=input.player,
                frame=emu.framecount(),boot_frames=frames})
        end
    end
    return original_advance()
end
emu.yield,emu.frameadvance=wrapped_yield,wrapped_advance
local ok,why=xpcall(function()dofile(input.launcher)end,debug.traceback)
if emu.frameadvance==wrapped_advance then emu.frameadvance=original_advance end
if emu.yield==wrapped_yield then emu.yield=original_yield end
if not ok then
    joypad.set(idle)
    publish(input.failure,{stage="failure",player=input.player,error=tostring(why),
        frame=emu.framecount(),boot_frames=frames})
    error(why)
end
