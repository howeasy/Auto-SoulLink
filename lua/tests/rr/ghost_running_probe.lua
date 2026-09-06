-- Staged running-only component. Actual B/Left input, production ghost APIs and
-- contiguous framebuffer captures; no battle, position, party or RNG injection.
return function(ctx)
    local C,report,check=ctx.config,ctx.report,ctx.check
    local first=emu.framecount()
    local JSON=dofile(C.source_root.."/lua/json_codec.lua")
    local route_file=assert(io.open(C.source_root.."/lua/tests/rr/viridian_west_running_route.json","rb"))
    local route=assert(JSON.decode(route_file:read("*a")));route_file:close()
    check("running_route_schema",route.schema,"slink-rr-running-route-v1")
    check("running_rom_binding",C.identity.rom_sha256,route.rom_sha256)
    check("running_fixture_binding",C.identity.fixture_sha256,route.fixture_sha256)
    -- Run the existing normal-lifetime control first, retaining its complete
    -- result and its settled mailbox owner. This also performs the reviewed boot.
    local control=dofile(C.source_root.."/lua/tests/rr/ghost_resource_probe.lua")(ctx)
    local MB,reference=control.mailbox,control.reference
    local out={classification="synthetic_single_cartridge_running_component",release_ready=false,
        visual_review="pending",resource_review="pending",natural_battle_tested=false,route=route,normal_control=report.evidence.runtime,
        trace={},recording={fps_numerator=262144,fps_denominator=4389,frames={}},native_requests={},
        running_frames=0,max_consecutive_running=0,ghost_running_frames=0,frames=emu.framecount()-first}
    report.evidence.runtime=out
    local r8,r16,r32,s16=memory.read_u8,memory.read_u16_le,memory.read_u32_le,memory.read_s16_le
    local player=0x02036E38+reference.player_id*36
    local player_sprite=0x0202063C+reference.sprite_id*68
    local callback=C.probe_options.native_contract.ghost_callback|1
    local expected_party_keys={}
    for slot=0,reference.party_count-1 do
        expected_party_keys[slot+1]=reference.party:sub(slot*200+1,slot*200+16)
    end
    local function hex(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",r8(a+i)) end;return table.concat(t)
    end
    local align_x,align_y,align_cx,align_cy
    local function sample(label)
        local p={label=label,frame=emu.framecount(),callback2=r32(0x030030F4),script_lock=r8(0x03000F9C),
            map_group=r8(player+10),map_num=r8(player+9),x=s16(player+16),y=s16(player+18),
            previous_x=s16(player+20),previous_y=s16(player+22),flags=r8(player),facing=r8(player+24)&15,
            anim=r8(player_sprite+42),pause=r8(player_sprite+44),coffx=s16(0x02021BC8),coffy=s16(0x02021BCA),
            player_px=s16(player_sprite+32),player_py=s16(player_sprite+34),ghost_id=MB.ghost_oe(),
            party_hex=hex(0x02024284,600)}
        if (p.flags&0x80)~=0 or align_x==nil then
            align_x,align_y,align_cx,align_cy=p.x,p.y,p.coffx,p.coffy
        end
        p.wx=align_x*16+(align_cx-p.coffx);p.wy=align_y*16+(align_cy-p.coffy)
        p.actors={}
        for id=0,15 do
            local a=0x02036E38+id*36
            if (r8(a)&1)~=0 then
                local actor={id=id,local_id=r8(a+8),x=s16(a+16),y=s16(a+18),previous_x=s16(a+20),
                    previous_y=s16(a+22),elevation=r8(a+11)&15,sprite_id=r8(a+4)}
                if actor.sprite_id<64 then
                    local sprite=0x0202063C+actor.sprite_id*68
                    actor.sprite_flags=r8(sprite+62);actor.binding=r16(sprite+46)
                    actor.palette=(r16(sprite+4)>>12)&15
                    actor.palette_kind=r8(0x0203B7D4+actor.palette*4)
                    actor.palette_count=r8(0x0203B7D4+actor.palette*4+1)
                end
                p.actors[#p.actors+1]=actor
            end
        end
        if p.ghost_id<16 then
            local oe=0x02036E38+p.ghost_id*36;local sid=r8(oe+4)
            p.ghost={object_address=oe,object_hex=hex(oe,36),sprite_id=sid}
            if sid<64 then
                local a=0x0202063C+sid*68
                local g=p.ghost
                g.sprite_address=a;g.sprite_hex=hex(a,68);g.callback=r32(a+28)
                g.flags=r8(a+62);g.marker=r16(a+60);g.allocation=r16(a+58);g.object_binding=r16(a+46)
                g.images=r32(a+12);g.anims=r32(a+8);g.anim=r8(a+42)
                g.palette=(r16(a+4)>>12)&15;g.tile=r16(a+4)&1023
                g.screen_x=s16(a+32)+p.coffx;g.screen_y=s16(a+34)+p.coffy
                g.palette_kind=r8(0x0203B7D4+g.palette*4)
                g.palette_count=r8(0x0203B7D4+g.palette*4+1)
                g.palette_tag=r16(0x0203B7D4+g.palette*4+2)
            end
        end
        return p
    end
    local function guard(p,label)
        check(label.."_field",MB.present() and p.callback2==0x080565B5 and p.script_lock==0,true)
        check(label.."_same_map",p.map_group==route.map_group and p.map_num==route.map_num
            and r32(0x02036DFC)==route.layout,true)
        check(label.."_same_player",r8(0x0203707D)==reference.player_id and r8(player+4)==reference.sprite_id
            and (r8(player)&1)==1 and (r8(player_sprite+62)&1)==1 and r16(player_sprite+46)==reference.player_id,true)
        check(label.."_party_count",r8(0x02024029),reference.party_count)
        for slot,key in ipairs(expected_party_keys) do
            check(label.."_party_identity_"..slot,hex(0x02024284+(slot-1)*100,8),key)
        end
        check(label.."_no_native_ui",r8(0x0203FC80)==0 and r8(0x0203F840)==0 and r8(0x0203FD00)==0,true)
        check(label.."_row_bounds",p.y==route.row and p.x>=route.end_x and p.x<=route.start_x,true)
    end
    local function capture(p)
        local index=#out.recording.frames
        check("running_capture_count_"..index,index<200,true)
        local path=C.result_path:gsub("%.json$","")..string.format("_running_frame_%06d.png",index)
        out.recording.pending_capture={index=index,frame=p.frame,path=path,label=p.label}
        local prior=io.open(path,"rb");if prior then prior:close() end
        check("running_capture_fresh_"..index,prior==nil,true)
        local ok,why=pcall(client.screenshot,path)
        check("running_capture_call_"..index,ok and why~=false,true)
        local file=io.open(path,"rb");check("running_capture_exists_"..index,file~=nil,true)
        local data=file:read(4*1024*1024+1);file:close()
        check("running_capture_png_"..index,type(data)=="string" and #data>=57 and #data<=4*1024*1024
            and data:sub(1,8)=="\137PNG\13\10\26\10" and data:sub(-8,-5)=="IEND"
            and data:sub(17,24)==string.char(0,0,0,240,0,0,0,160),true)
        out.recording.frames[#out.recording.frames+1]={index=index,frame=p.frame,path=path,bytes=#data,label=p.label}
        out.recording.pending_capture=nil
    end
    local function owner(p,label)
        local g=p.ghost
        check(label.."_ghost_present",g~=nil and g.sprite_id<64,true)
        check(label.."_ghost_owner",(r8(g.object_address)&1)==1 and r8(g.object_address+8)==0xF0
            and (g.flags&5)==1 and g.marker==0x534C and g.callback==callback and g.object_binding==p.ghost_id,true)
        check(label.."_ghost_allocation",g.allocation,reference.allocation)
        check(label.."_ghost_avatar",g.images==reference.images and g.anims==reference.anims,true)
        check(label.."_private_palette",g.palette~=reference.palette and g.palette_kind==6 and g.palette_count==1
            and g.palette_tag==r16(0x0203B7D4+reference.palette*4+2),true)
        check(label.."_visible_bounds",g.screen_x>=0 and g.screen_x<240 and g.screen_y>=0 and g.screen_y<160,true)
        check(label.."_tile_range",g.tile+g.allocation//32<=1024,true)
        for bit=g.tile,g.tile+g.allocation//32-1 do
            check(label.."_tile_"..bit,(r8(0x02021B48+(bit>>3))>>(bit&7))&1,1)
        end
        for _,actor in ipairs(p.actors) do
            check(label.."_actor_owner_"..actor.id,actor.sprite_id<64 and (actor.sprite_flags&1)==1
                and actor.binding==actor.id and actor.palette_kind>0 and actor.palette_count>0,true)
        end
    end
    local recording,peer_requested=false,false
    local last_published,last_publish_frame
    local function publish(p,force)
        if not peer_requested or (not force and last_publish_frame and p.frame-last_publish_frame<route.publish_interval) then return end
        local moving=last_published~=nil and (p.flags&0x80)==0 and (p.wx~=last_published.wx or p.wy~=last_published.wy)
        local running=p.anim>=20 and p.anim<=23
        check("running_publish_"..p.frame,MB.ghost_set_pos(p.wx+route.ghost_offset_x,p.wy,p.facing,moving,p.anim,running),true)
        last_published=p;last_publish_frame=p.frame
    end
    local function advance(buttons,label)
        local before=sample(label.."_before");guard(before,label.."_before")
        publish(before,false)
        check(label.."_budget",emu.framecount()-first<C.frames,true)
        joypad.set(buttons);emu.frameadvance();out.frames=emu.framecount()-first
        local after=sample(label);after.input=buttons;out.trace[#out.trace+1]=after
        if recording then capture(after) end -- Retain the actual failure frame before checking it.
        check(label.."_frame_delta",after.frame,before.frame+1)
        guard(after,label.."_after")
        return after
    end
    local function wait_for(label,predicate)
        for i=0,30 do
            if predicate() then return end
            if i<30 then advance({},label.."_"..i) end
        end
        check(label.."_completed",false,true)
    end
    local function request(label,fn)
        guard(sample(label),label.."_admission")
        check(label.."_mailbox_idle",r16(MB.BASE+6)==0 and r16(MB.BASE+10)==MB.ST_IDLE and MB.session_error()==nil,true)
        local token=fn();check(label.."_posted",token~=nil,true)
        out.native_requests[#out.native_requests+1]={kind=label,token=token,frame=emu.framecount()}
        wait_for(label.."_ack",function()
            local status,reason=MB.poll(token)
            if status==MB.ST_FAIL or MB.session_error() then error(label.." failed: "..tostring(reason or MB.session_error())) end
            return status==MB.ST_OK
        end)
    end
    local function route_preconditions()
        local p=sample("running_initial");guard(p,"running_initial")
        check("running_exact_start",p.x==route.start_x and p.y==route.row and p.previous_x==p.x and p.previous_y==p.y,true)
        check("running_grid_dimensions",r32(0x03005040)==route.grid_width and r32(0x03005044)==route.grid_height,true)
        local grid=r32(0x03005048)
        check("running_grid_pointer",grid>=0x02000000 and grid+route.grid_width*route.grid_height*2<=0x02040000,true)
        local primary=r32(route.layout+16)
        check("running_primary_tileset",primary>=0x08000000 and primary+24<=0x0A000000,true)
        check("running_attribute_table",r32(primary+20),route.primary_attributes)
        for i,word in ipairs(route.corridor_words) do
            local x=route.corridor_first_x+i-1
            check("running_corridor_"..x,r16(grid+(route.row*route.grid_width+x)*2),word)
            check("running_clear_cell_"..x,word~=0x03FF and ((word>>10)&3)==0 and (word>>12)==route.elevation,true)
            local id=word&1023
            check("running_plain_terrain_"..x,id<640 and route.metatile_attributes[tostring(id)]==0
                and r32(route.primary_attributes+id*4)==0,true)
        end
        check("running_map_events",r32(0x02036DFC+4),route.map_events)
        check("running_warp_binding",r8(route.map_events+1)==route.warp_count and r32(route.map_events+8)==route.warp_pointer,true)
        check("running_coord_binding",r8(route.map_events+2)==route.coord_count and r32(route.map_events+12)==route.coord_pointer,true)
        check("running_warp_bytes",hex(route.warp_pointer,route.warp_count*8),route.warp_hex)
        check("running_coord_bytes",hex(route.coord_pointer,route.coord_count*16),route.coord_hex)
        for _,entry in ipairs({{kind="warp",pointer=route.warp_pointer,count=route.warp_count,stride=8},
                              {kind="coord",pointer=route.coord_pointer,count=route.coord_count,stride=16}}) do
            for i=0,entry.count-1 do
                local a=entry.pointer+i*entry.stride;local x,y=s16(a)+7,s16(a+2)+7
                check("running_no_"..entry.kind.."_"..i,y~=route.row or x<route.end_x or x>route.start_x,true)
            end
        end
        check("running_anim_table",r8(0x083A6493+3),route.running_animation_west)
        out.before=control.resources_snapshot("running_before")
    end
    local function run()
        route_preconditions()
        peer_requested=true
        request("running_spawn",function() return MB.ghost_spawn(reference.gfx) end)
        wait_for("running_owned_spawn",function() return MB.ghost_oe()<16 end)
        check("running_avatar_posted",MB.ghost_set_avatar(reference.images,reference.anims,reference.colors),true)
        publish(sample("running_avatar"),true);check("running_snap_posted",MB.ghost_snap(),true)
        wait_for("running_avatar_ready",function() return r8(MB.GH+17)==0 end)
        local p=advance({},"running_settle_0");p=advance({},"running_settle_1");owner(p,"running_ready")
        out.run_start=p;recording=true;capture(p)
        local consecutive=0
        for i=1,route.input_frame_limit do
            local before=sample("running_step_"..i)
            if before.x==route.end_x and before.previous_x==route.end_x and (before.flags&0x80)~=0 then break end
            if before.x>route.end_x and (before.flags&0x80)~=0 then
                for _,actor in ipairs(before.actors) do
                    if actor.id~=reference.player_id and actor.id~=before.ghost_id then
                        local target=(actor.x==before.x-1 and actor.y==route.row)
                            or (actor.previous_x==before.x-1 and actor.previous_y==route.row)
                        local elevation=actor.elevation==0 or route.elevation==0 or actor.elevation==route.elevation
                        check("running_step_"..i.."_clear_actor_"..actor.id,not (target and elevation),true)
                    end
                end
            end
            local buttons=before.x>route.end_x and {B=true,Left=true} or {}
            local after=advance(buttons,"running_step_"..i);owner(after,"running_step_"..i)
            if after.anim==route.running_animation_west and after.wx-before.wx==-2 and after.wy==before.wy then
                out.running_frames=out.running_frames+1;consecutive=consecutive+1
                out.max_consecutive_running=math.max(out.max_consecutive_running,consecutive)
            else consecutive=0 end
            if after.ghost.anim==route.running_animation_west then out.ghost_running_frames=out.ghost_running_frames+1 end
        end
        joypad.set({})
        local stopped=sample("running_endpoint");out.endpoint=stopped
        check("running_endpoint_reached",stopped.x==route.end_x and stopped.previous_x==route.end_x
            and stopped.y==route.row and (stopped.flags&0x80)~=0,true)
        request("running_clear",function() return MB.ghost_clear() end)
        wait_for("running_removed",function() return MB.ghost_oe()==255 and r8(MB.GH)==0 end)
        peer_requested=false
        advance({},"running_after_clear_0");advance({},"running_after_clear_1")
        out.after=control.resources_snapshot("running_after")
        out.party_after=hex(0x02024284,600)
        out.party_changed=out.party_after~=reference.party
        out.party_review=out.party_changed and "pending" or "unchanged"
        for id=0,15 do
            local a=0x02036E38+id*36
            check("running_no_orphan_"..id,(r8(a)&1)==0 or r8(a+8)~=0xF0,true)
            check("running_no_private_ref_"..id,r8(0x0203B7D4+id*4)~=6,true)
        end
        check("running_interaction_disarmed",r8(0x0203F8D1),0)
        check("running_native_motion_observed",out.max_consecutive_running>=route.minimum_consecutive_running_frames,true)
        check("running_ghost_animation_observed",out.ghost_running_frames>=route.minimum_consecutive_running_frames,true)
        check("running_recording_complete",#out.recording.frames>=route.minimum_consecutive_running_frames+1,true)
        -- Motion/owned-frame/coarse-clear scope only. The retained before/after
        -- snapshots still need orphan sprite/tile attribution across camera culls.
        check("running_component_complete",true,true)
    end
    local ok,why=pcall(run)
    if not ok then
        recording=false -- A failed capture must not prevent an otherwise safe ordinary clear.
        joypad.set({});out.failure_cleanup={attempted=false,completed=false}
        if peer_requested and MB.present() and r32(0x030030F4)==0x080565B5 and r8(0x03000F9C)==0
            and r16(MB.BASE+6)==0 and r16(MB.BASE+10)==MB.ST_IDLE and MB.session_error()==nil then
            out.failure_cleanup.attempted=true
            local cleaned,problem=pcall(function()
                request("running_failure_clear",function() return MB.ghost_clear() end)
                wait_for("running_failure_removed",function() return MB.ghost_oe()==255 and r8(MB.GH)==0 end)
            end)
            out.failure_cleanup.completed=cleaned
            if not cleaned then out.failure_cleanup.error=tostring(problem) end
        end
        error(why,0)
    end
end
