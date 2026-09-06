-- Ordinary-input qualification of an observed Route1 wild battle. The default
-- has no ghost. A separate, source-bound component can observe/control presence.
-- The controller/menu oracle must pass before any escape selection input.
return function(ctx,component)
    local C,check=ctx.config,ctx.check
    dofile(C.source_root.."/lua/tests/rr/route1_traversal_probe.lua")(ctx)
    local arrival=ctx.report.evidence.runtime
    local JSON=dofile(C.source_root.."/lua/json_codec.lua")
    local file=assert(io.open(C.source_root.."/lua/tests/rr/route1_grass_route.json","rb"))
    local route=assert(JSON.decode(file:read("*a")));file:close()
    check("wild_route_schema",route.schema,"slink-rr-route1-grass-v1")
    check("wild_route_rom",C.identity.rom_sha256,route.rom_sha256)
    check("wild_route_fixture",C.identity.fixture_sha256,route.fixture_sha256)
    local out={classification="single_cartridge_no_ghost_natural_battle_qualification",
        release_ready=false,ghost_tested=false,visual_review="pending",route=route,arrival=arrival,
        trace={},screenshots={},resource_snapshots={},grass_steps=0,menu_inputs={},text_inputs={}}
    ctx.report.evidence.runtime=out
    if component then
        check("wild_component_schema",component.schema,"slink-rr-wild-presence-component-v1")
        for _,key in ipairs({"begin","before_frame","after_frame","finish"}) do
            check("wild_component_"..key,type(component[key]),"function")
        end
        out.classification="synthetic_single_cartridge_ghost_natural_battle_component"
        out.ghost_tested=true
    end
    local r8,r16,r32,s16=memory.read_u8,memory.read_u16_le,memory.read_u32_le,memory.read_s16_le
    local first=emu.framecount()
    local party_pid,party_ot,party_hp=r32(0x02024284),r32(0x02024288),r16(0x02024284+86)
    local function hex(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",r8(a+i)) end;return table.concat(t)
    end
    local function save_pointer_evidence(address,kind)
        local a=r32(address);local n=kind==1 and 6 or 14
        local evidence={address=address,value=a,valid=a>=0x02000000 and a+n<=0x02040000}
        if evidence.valid then
            if kind==1 then evidence.map_group=r8(a+4);evidence.map_num=r8(a+5)
            else evidence.trainer_name_hex=hex(a,8);evidence.trainer_id=r32(a+10) end
        end
        return evidence
    end
    local function sample(label)
        local id=r8(0x0203707D);local oe=0x02036E38+id*36;local sb1=r32(0x03003840)
        check("wild_save_pointer_"..(#out.trace+1),sb1>=0x02000000 and sb1+6<=0x02040000,true)
        local row={label=label,frame=emu.framecount(),callback2=r32(0x030030F4),script_lock=r8(0x03000F9C),
            map_group=r8(sb1+4),map_num=r8(sb1+5),layout=r32(0x02036DFC),player_id=id,
            x=s16(oe+16),y=s16(oe+18),previous_x=s16(oe+20),previous_y=s16(oe+22),flags=r8(oe),
            battle_type=r32(0x02022B4C),outcome=r8(0x02023E8A),battlers=r8(0x02023BCC),
            controller0=r32(0x03004FE0),controller1=r32(0x03004FE4),cursor=r8(0x02023FF8),
            battle_main=r32(0x03004F84),battle_player_species=r16(0x02023BE4),
            battle_player_hp=r16(0x02023BE4+40),battle_player_maxhp=r16(0x02023BE4+44),
            battle_enemy_species=r16(0x02023BE4+88),enemy_count=r8(0x0202402A),
            enemy_party_hp=r16(0x0202402C+86),enemy_party_maxhp=r16(0x0202402C+88),
            text_active=r8(0x02020034+27),text_state=r8(0x02020034+28),text_raw=hex(0x02020034,36),
            party_hp=r16(0x02024284+86),party_pid=r32(0x02024284),party_ot=r32(0x02024288),
            party_count=r8(0x02024029)}
        row.save_pointers={sb1_canonical=save_pointer_evidence(0x03005008,1),sb1_irq_alias=save_pointer_evidence(0x03003840,1),
            sb2_canonical=save_pointer_evidence(0x0300500C,2),sb2_irq_alias=save_pointer_evidence(0x03003838,2)}
        out.trace[#out.trace+1]=row;return row
    end
    local identity_checks=0
    local function identity_guard(p)
        identity_checks=identity_checks+1
        local n=identity_checks
        check("wild_party_identity_"..n,p.party_count==1 and p.party_pid==party_pid and p.party_ot==party_ot,true)
        check("wild_no_hp_loss_"..n,p.party_hp,party_hp)
        if out.action_menu and p.callback2~=0x080565B5 and p.outcome==0 then
            check("wild_no_active_hp_loss_"..n,p.battle_player_hp,party_hp)
        end
    end
    local function capture(label)
        local n=#out.screenshots;check("wild_capture_bound_"..n,n<1400,true)
        local path=C.result_path:gsub("%.json$","")..string.format("_wild_%04d.png",n)
        local prior=io.open(path,"rb");if prior then prior:close() end
        check("wild_capture_fresh_"..n,prior==nil,true)
        local ok,why=pcall(client.screenshot,path)
        check("wild_capture_call_"..n,ok and why~=false,true)
        local f=assert(io.open(path,"rb"));local data=f:read(4*1024*1024+1);f:close()
        check("wild_capture_png_"..n,#data>57 and #data<4*1024*1024
            and data:sub(1,8)=="\137PNG\13\10\26\10" and data:sub(17,24)==string.char(0,0,0,240,0,0,0,160),true)
        out.screenshots[#out.screenshots+1]={path=path,frame=emu.framecount(),label=label,bytes=#data}
    end
    local function resources(label)
        out.resource_snapshots[#out.resource_snapshots+1]={label=label,frame=emu.framecount(),
            refs=hex(0x0203B7D4,64),tiles=hex(0x02021B48,128),sprites=hex(0x0202063C,64*68),
            objects=hex(0x02036E38,16*36),palette=hex(0x020373F8,512),ghost=hex(0x0203F850,44)}
    end
    local function advance(buttons,label,record)
        check("wild_budget_"..#out.trace,emu.framecount()-first<route.max_post_arrival_frames,true)
        if component then component.before_frame() end
        joypad.set(buttons or {});emu.frameadvance();joypad.set({})
        local p=sample(label);p.input=buttons or {}
        if component then component.after_frame(p) end
        if record then capture(label) end
        identity_guard(p);return p
    end
    local function in_field(p) return p.callback2==0x080565B5 and p.script_lock==0 end
    local function field_guard(p,label)
        check(label.."_map",p.map_group==route.map_group and p.map_num==route.map_num and p.layout==route.layout,true)
        check(label.."_player",p.player_id<16 and (p.flags&1)==1,true)
        identity_guard(p)
    end
    local tiles={};for _,tile in ipairs(route.tiles) do tiles[tile.x..":"..tile.y]=tile end
    local api={advance=advance,capture=capture,resources=resources,sample=sample,out=out}
    local component_started=false
    local encountered=false
    local function step(button,x,y,label)
        local start=sample(label.."_start");field_guard(start,label)
        check(label.."_idle",in_field(start) and start.x==start.previous_x and start.y==start.previous_y and (start.flags&0x80)~=0,true)
        local tile=assert(tiles[x..":"..y],"Unreviewed destination")
        local width,grid=r32(0x03005040),r32(0x03005048)
        check(label.."_grid",width==route.grid_width and r32(0x03005044)==route.grid_height
            and grid>=0x02000000 and grid+width*route.grid_height*2<=0x02040000,true)
        check(label.."_tile",r16(grid+(y*width+x)*2),tile.word)
        check(label.."_passable",((tile.word>>10)&3)==0 and (tile.word>>12)==3,true)
        for id=0,15 do
            local a=0x02036E38+id*36
            if id~=start.player_id and (r8(a)&1)~=0 then
                local e=r8(a+11)&15
                check(label.."_actor_"..id,not ((e==0 or e==3) and ((s16(a+16)==x and s16(a+18)==y)
                    or (s16(a+20)==x and s16(a+22)==y))),true)
            end
        end
        local grass=((tile.attribute>>24)&7)==1
        if grass and component and not component_started then
            component.begin(api);component_started=true
        end
        if grass then out.grass_steps=out.grass_steps+1 end
        for i=1,48 do
            local p=sample(label.."_check_"..i)
            local buttons={};if p.x~=x or p.y~=y then buttons[button]=true end
            p=advance(buttons,label.."_frame_"..i,grass)
            field_guard(p,label.."_frame_"..i)
            if not in_field(p) then
                check("wild_transition_only_from_grass",grass,true)
                out.encounter_start=p;encountered=true;capture("encounter_transition");resources("encounter_transition")
                ctx.checkpoint("wild_encounter_transition");return
            end
            if p.x==x and p.y==y and p.previous_x==x and p.previous_y==y and (p.flags&0x80)~=0 then return end
        end
        error("Route step timeout: "..label)
    end
    local function action_menu(p)
        return p.callback2~=0x080565B5 and p.controller0==0x0802E439 and p.outcome==0
            and p.battlers==2 and p.enemy_party_hp>0 and p.enemy_party_maxhp>=p.enemy_party_hp and p.battle_player_species>0
            and p.battle_player_hp==party_hp and p.battle_player_maxhp>=party_hp
            and p.battle_enemy_species>0 and p.battle_type==4 and p.cursor<=3
    end
    local function text_wait(p)
        return p.callback2==0x08011101 and p.controller0==0x08030611 and p.battle_type==4
            and p.battlers==2 and p.text_active==1 and p.text_state>=1 and p.text_state<=3
    end
    local function text_buttons(p,label)
        if not text_wait(p) then return {} end
        check("wild_text_bound_"..#out.text_inputs,#out.text_inputs<8,true)
        out.text_inputs[#out.text_inputs+1]={frame=p.frame,label=label,button="B",controller=p.controller0,
            text_active=p.text_active,text_state=p.text_state,text_raw=p.text_raw}
        return {B=true}
    end
    local ok,why=xpcall(function()
        check("wild_action_hook_anchor",hex(0x0802E438,8),"00480047a19e0a09")
        check("wild_escape_hook_anchor",hex(0x08016748,8),"004908473d050909")
        check("wild_text_controller_anchor",hex(0x08030610,16),"00b50020d2f726fc0004002801d1fdf7")
        check("wild_text_wait_arrow_anchor",hex(0x08005634,8),"00490847590e0c09")
        check("wild_text_wait_anchor",hex(0x08005680,8),"00490847a50e0c09")
        check("wild_text_printer_table",r32(0x08002E78),0x02020034)
        check("wild_no_existing_ghost",r8(0x0203F850)==0 and r8(0x0203F851)==255,true)
        resources("arrival");capture("arrival")
        local index=0
        for _,target in ipairs(route.waypoints) do
            while not encountered do
                local p=sample("waypoint_check")
                if p.x==target.x and p.y==target.y then break end
                local dx=target.button=="Right" and 1 or 0
                local dy=target.button=="Down" and 1 or 0
                index=index+1;step(target.button,p.x+dx,p.y+dy,"grass_route_"..index)
            end
            if encountered then break end
        end
        while not encountered and out.grass_steps<route.max_grass_steps do
            local p=sample("grass_pair_check")
            local x=p.x==23 and 24 or 23
            index=index+1;step(x>p.x and "Right" or "Left",x,13,"grass_search_"..index)
        end
        check("wild_encounter_observed",encountered,true)
        local menu
        for i=1,720 do
            local before=sample("intro_before_"..i)
            -- A one-frame B pulse only at the pinned printer's wait state.
            -- Force a release between pulses; never send intro input to menus.
            local buttons=i%2==0 and text_buttons(before,"intro") or {}
            local p=advance(buttons,"intro_"..i,true)
            check("wild_intro_no_trainer_"..i,(p.battle_type&0x2208B)==0,true)
            if action_menu(p) then menu=p;break end
        end
        check("wild_action_menu_verified",menu~=nil,true)
        out.action_menu=menu;out.enemy_party_raw_hex=hex(0x0202402C,100)
        capture("verified_action_menu");resources("verified_action_menu");ctx.checkpoint("wild_action_menu_verified")
        local function menu_press(button,expected,label)
            local p=sample(label.."_before");check(label.."_ready",action_menu(p),true)
            out.menu_inputs[#out.menu_inputs+1]={frame=p.frame,button=button,cursor_before=p.cursor,controller=p.controller0}
            advance({[button]=true},label.."_pressed",true)
            p=advance({},label.."_released",true)
            check(label.."_cursor",action_menu(p) and p.cursor==expected,true)
        end
        if (menu.cursor&1)==0 then menu_press("Right",menu.cursor|1,"select_run_right") end
        menu=sample("run_vertical_check")
        if (menu.cursor&2)==0 then menu_press("Down",menu.cursor|2,"select_run_down") end
        menu=sample("run_confirm_check")
        check("wild_run_exact_menu",action_menu(menu) and menu.cursor==3,true)
        capture("verified_run_cursor")
        out.menu_inputs[#out.menu_inputs+1]={frame=menu.frame,button="A",cursor_before=menu.cursor,controller=menu.controller0}
        advance({A=true},"confirm_run",true)
        local escaped,returned=false,nil
        for i=1,360 do
            local before=sample("escape_before_"..i)
            local buttons=before.outcome==4 and i%2==0 and text_buttons(before,"escaped") or {}
            local p=advance(buttons,"escape_"..i,true)
            if p.outcome==4 then escaped=true;out.escape_outcome=out.escape_outcome or p end
            check("wild_escape_no_other_outcome_"..i,p.outcome==0 or p.outcome==4,true)
            if escaped and in_field(p) and p.x==p.previous_x and p.y==p.previous_y and (p.flags&0x80)~=0 then returned=p;break end
            if i>30 and action_menu(p) then error("Escape failed: action menu returned; no retry authorized") end
        end
        check("wild_escape_observed",escaped,true)
        check("wild_field_return_observed",returned~=nil,true)
        out.returned=returned;field_guard(returned,"returned")
        resources("returned");capture("returned");out.party_raw_hex=hex(0x02024284,100)
        if component then component.finish(api) end
        check("wild_no_ghost_after_return",r8(0x0203F850)==0 and r8(0x0203F851)==255,true)
        check("wild_qualification_complete",true,true);ctx.checkpoint("wild_qualification_complete")
    end,debug.traceback)
    joypad.set({})
    if not ok then out.error=tostring(why);capture("failure");resources("failure");ctx.checkpoint("wild_failed");error(why,0) end
end
