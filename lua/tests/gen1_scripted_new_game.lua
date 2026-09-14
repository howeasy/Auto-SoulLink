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
local chain_next,handoffs=1,JSON.array()
-- Every admitted route mode and the exact handoff chain the host stages for it (gen1_scripted_host).
local CHAINS={["rb-starter-rival"]={},["rb-parcel"]={{after="lab-loss-complete",terminal="first-ball-readback"}},
    ["rb-save"]={{after="lab-loss-complete",terminal="save-witnessed"}}}
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
local FIELDS=dofile(ROOT.."/lua/tests/gen1_rb_point_fields.lua")
local SIG=dofile(ROOT.."/lua/tests/gen1_rb_mart_signature.lua")
local function rd(addr)return memory.read_u8(addr,"System Bus")end
local function menu_inputs()
    beat=beat+1;local moment=beat%16
    local buttons={A=moment<2,Start=moment==8}
    if input.resume and sym("wTopMenuItemY")==2 and sym("wTopMenuItemX")==1 then
        -- pokered engine/menus/main_menu.asm:57-76: the main menu is at (1,2) with wMaxMenuItem =
        -- wSaveFileStatus (2 = CONTINUE/NEW GAME/OPTION, CONTINUE = index 0; 1 = NEW GAME first).
        -- Nothing here presses Down, so A/Start can only choose CONTINUE and then its confirm loop
        -- (:95-107, A held). Any other (1,2) menu means the resumed save was not offered or taken.
        assert(sym("wMaxMenuItem")==2 and sym("wSaveFileStatus")==2,"resumed cartridge offers no CONTINUE")
        assert(sym("wCurrentMenuItem")==0,"main menu cursor left CONTINUE")
    elseif sym("wMaxMenuItem")==3 and sym("wTopMenuItemY")==2 and sym("wTopMenuItemX")==1 then
        buttons={Down=sym("wCurrentMenuItem")==0,A=sym("wCurrentMenuItem")>0 and moment<2}
    end
    local pressed={};for key,value in pairs(idle)do pressed[key]=buttons[key]or value end
    joypad.set(pressed)
end
local function route_point()
    local event_byte=memory.read_u8(assert(symbols.wEventFlags)+4,"System Bus")
    local hp=memory.read_u8(assert(symbols.wPartyMon1HP),"System Bus")*256
        +memory.read_u8(assert(symbols.wPartyMon1HP)+1,"System Bus")
    local raw={map=sym("wCurMap"),x=sym("wXCoord"),y=sym("wYCoord"),
        party_count=sym("wPartyCount"),battle=sym("wIsInBattle"),opponent=sym("wCurOpponent"),
        menu_y=sym("wTopMenuItemY"),menu_x=sym("wTopMenuItemX"),menu_max=sym("wMaxMenuItem"),
        menu_index=sym("wCurrentMenuItem"),move2=memory.read_u8(assert(symbols.wBattleMonMoves)+1,"System Bus"),
        move2_pp=memory.read_u8(assert(symbols.wBattleMonPP)+1,"System Bus"),
        text_box=sym("wTextBoxID"),lab_script=sym("wOaksLabCurScript"),
        pallet_script=sym("wPalletTownCurScript"),joy_ignore=sym("wJoyIgnore"),
        npc_moving=sym("wStatusFlags5")%2==1,
        battle_result=sym("wBattleResult"),party_hp=hp,
        lab_rival_done=math.floor(event_byte/8)%2==1,
        ball_count=FIELDS.bag_quantity(rd,assert(symbols.wNumBagItems),assert(symbols.wBagItems),FIELDS.POKE_BALL),
        parcel_count=FIELDS.bag_quantity(rd,assert(symbols.wNumBagItems),assert(symbols.wBagItems),FIELDS.OAKS_PARCEL),
        money=FIELDS.bcd_money(rd,assert(symbols.wPlayerMoney)),
        got_parcel=FIELDS.event_bit(rd,assert(symbols.wEventFlags),FIELDS.EVENT_GOT_OAKS_PARCEL),
        oak_got_parcel=FIELDS.event_bit(rd,assert(symbols.wEventFlags),FIELDS.EVENT_OAK_GOT_PARCEL),
        mart_script=sym("wViridianMartCurScript"),
        simulated_joypad_index=sym("wSimulatedJoypadStatesIndex"),
        facing=FIELDS.facing_name(sym("wSpritePlayerStateData1FacingDirection")),
        battle_type=sym("wBattleType"),run_attempts=sym("wNumRunAttempts"),
        list_menu_id=sym("wListMenuID"),cur_item=sym("wCurItem"),quantity=sym("wItemQuantity"),
        chosen_menu_item=sym("wChosenMenuItem"),menu_exit_method=sym("wMenuExitMethod"),
        list_scroll_offset=sym("wListScrollOffset"),menu_watch_oob=sym("wMenuWatchMovingOutOfBounds"),
        font_loaded=sym("wFontLoaded")%2==1,save_file_status=sym("wSaveFileStatus"),
        -- "SAVE" glyphs (S,A,V,E = $92,$80,$95,$84; constants/charmap.asm) at tilemap (12,8): the
        -- no-Pokedex START menu's fourth row (engine/menus/draw_start_menu.asm:28-57, two rows apart).
        start_menu_save=rd(assert(symbols.wTileMap)+172)==0x92 and rd(symbols.wTileMap+173)==0x80
            and rd(symbols.wTileMap+174)==0x95 and rd(symbols.wTileMap+175)==0x84}
    raw.menu_kind,raw.item_id,raw.confirm_index=SIG.mart_menu(raw)
    return raw
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
            local shape=assert(CHAINS[input.route.mode],"unknown scripted route mode")
            assert(input.variant=="red" or input.variant=="blue")
            local chain=input.route.chain or {}
            assert(type(chain)=="table" and #chain==#shape)
            for i,entry in ipairs(shape)do
                assert(type(chain[i])=="table" and type(chain[i].module)=="string"
                    and chain[i].after==entry.after and chain[i].terminal==entry.terminal)
            end
            local handshake=read_optional(input.route.handshake)
            if handshake and not route_driver then
                assert(status.context and status.host and status.host.owner_id==status.context.physical_instance,
                    "R/B route needs the current owned context")
                route_expected={run_id=input.run_id,player=input.player,rom_sha1=input.rom_sha1,
                    context_generation=status.context.context_generation,
                    physical_instance=status.context.physical_instance}
                route_driver=assert(dofile(input.route.module)).new(route_expected)
            end
            local point,frame=route_driver and route_point() or JSON.null,emu.framecount()
            local buttons,phase=idle,"await-pair-handshake"
            if route_driver then
                route_frames=route_frames+1
                assert(route_frames<120000,"R/B route made no bounded progress")
            end
            while true do
                if route_driver then buttons,phase=route_driver.step(handshake,status,point,frame) end
                local entry=chain[chain_next]
                local handoff=route_driver and entry and phase==entry.after
                if handoff then
                    handoffs[#handoffs+1]={stage=phase,frame=frame,route_frames=route_frames}
                end
                if phase~=route_phase or route_frames%600==0 or handoff then
                    route_phase=phase
                    publish(input.route.progress,{stage=phase,player=input.player,frame=frame,
                        route_frames=route_frames,point=point,chain_handoffs=#chain>0 and handoffs or nil})
                end
                if not handoff then break end
                chain_next=chain_next+1
                route_driver=assert(dofile(entry.module)).new(route_expected)
            end
            joypad.set(buttons)
            local terminal=#chain==0 and "lab-loss-complete" or chain[#chain].terminal
            if chain_next>#chain and phase==terminal then
                joypad.set(idle)
                -- A terminal that ended in an in-game save persists it the way a normal emulator close
                -- would (the host is terminated, never closed); the flush writes the private SaveRAM.
                if input.route.flush_saveram then
                    client.saveram()
                    publish(input.route.progress,{stage=phase,player=input.player,frame=frame,
                        route_frames=route_frames,point=point,chain_handoffs=handoffs,saveram_flushed=true})
                end
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
