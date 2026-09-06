-- Frozen03 synthetic peer; ordinary natural-battle/menu inputs are shared with
-- the qualified no-ghost scenario. No native requests are sent during battle.
return function(ctx)
    local C,check=ctx.config,ctx.check
    local r8,r16,r32,s16=memory.read_u8,memory.read_u16_le,memory.read_u32_le,memory.read_s16_le
    local O,S,REFS,TILES,GH=0x02036E38,0x0202063C,0x0203B7D4,0x02021B48,0x0203F850
    local MB,Position,ref,api,active,last_p,last_frame
    local phase="not_started"
    local out={classification="synthetic_same_avatar_peer",release_ready=false,visual_review="pending",
        arena_ownership="unresolved",requests={},publications={},owners={},field_owned_frames=0,
        nonfield_frames=0,suspended_frames=0,allocations={},resource_review="pending"}
    local allocation_keys={}
    local peer_tiles={}
    local contract=C.probe_options.native_contract or {}
    check("ghost_wild_build",contract.build_id,C.descriptor.build_id)
    check("ghost_wild_callback",contract.ghost_callback,0x0837A970)
    local function hex(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",r8(a+i)) end;return table.concat(t)
    end
    local function field()
        return r32(0x030030F4)==0x080565B5 and r8(0x03000F9C)==0
            and not (r16(0x02023BE4+44)>0 and r8(0x02023E8A)==0)
    end
    local function state()
        local g={frame=emu.framecount(),phase=phase,active=r8(GH),id=r8(GH+1),lifecycle=r8(GH+43),
            gh_hex=hex(GH,44),refs=hex(REFS,64),tiles=hex(TILES,128)}
        if g.id<16 then
            local a=O+g.id*36;g.object_hex=hex(a,36);g.sid=r8(a+4);g.local_id=r8(a+8)
            g.object_active=(r8(a)&1)==1;g.x=s16(a+16);g.y=s16(a+18)
            g.previous_x=s16(a+20);g.previous_y=s16(a+22)
            if g.sid<64 then
                a=S+g.sid*68;g.sprite_hex=hex(a,68);g.sprite_flags=r8(a+62)
                g.callback=r32(a+28);g.marker=r16(a+60);g.allocation=r16(a+58);g.binding=r16(a+46)
                g.images=r32(a+12);g.anims=r32(a+8);g.tile=r16(a+4)&1023;g.palette=(r16(a+4)>>12)&15
                g.palette_kind=r8(REFS+g.palette*4);g.palette_count=r8(REFS+g.palette*4+1)
                g.screen_x=s16(a+32)+s16(0x02021BC8);g.screen_y=s16(a+34)+s16(0x02021BCA)
            end
        end
        return g
    end
    local function owned(g)
        return g.id<16 and g.sid and g.sid<64 and g.object_active and g.local_id==0xF0
            and (g.sprite_flags&7)==3 and g.callback==(contract.ghost_callback|1)
            and g.marker==0x534C and g.binding==g.id and g.allocation==ref.allocation
            and g.images==ref.images and g.anims==ref.anims and g.palette_kind==6 and g.palette_count==1
            and r8(GH+17)==0
    end
    local function attributable_allocation(g)
        return g.id<16 and g.sid and g.sid<64 and g.object_active and g.local_id==0xF0
            and (g.sprite_flags&1)==1 and g.callback==(contract.ghost_callback|1)
            and g.marker==0x534C and g.binding==g.id and g.allocation>=32 and g.allocation<=2048
            and g.allocation%32==0 and g.tile+g.allocation//32<=1024
    end
    local function assert_owner(label)
        local g=state();out.owners[#out.owners+1]=g
        check(label.."_owned",owned(g),true)
        check(label.."_visible",g.screen_x>=0 and g.screen_x<240 and g.screen_y>=0 and g.screen_y<160,true)
        local player_sid=r8(O+r8(0x0203707D)*36+4)
        check(label.."_player_sprite",player_sid<64,true)
        local player_sprite=S+player_sid*68
        local player=O+r8(0x0203707D)*36
        check(label.."_relative_position",g.screen_x==s16(player_sprite+32)+s16(0x02021BC8)+32
            and g.screen_y==s16(player_sprite+34)+s16(0x02021BCA),true)
        check(label.."_private_player_palette",g.palette~=((r16(player_sprite+4)>>12)&15),true)
        check(label.."_occupancy",g.x==g.previous_x and g.y==g.previous_y
            and g.x==s16(player+16)+2 and g.y==s16(player+18),true)
        check(label.."_tile_bounds",g.tile+g.allocation//32<=1024,true)
        for bit=g.tile,g.tile+g.allocation//32-1 do
            check(label.."_tile_"..bit,(r8(TILES+(bit>>3))>>(bit&7))&1,1)
        end
        return g
    end
    local function stock_grass_reassignment()
        local matches={};local player_id=r8(0x0203707D);local player=O+player_id*36
        check("ghost_wild_grass_player",player_id<16 and (r8(player)&1)==1 and r8(player+8)==255,true)
        local owners=0
        for id=0,15 do
            if (r8(O+id*36)&1)==1 and r8(O+id*36+8)==255 then owners=owners+1 end
        end
        check("ghost_wild_grass_unique_player",owners,1)
        -- Actual RR's FF owner lookup goes through09042B08 then0805E044;
        -- the player branch resolves localId alone. Map bytes are diagnostic.
        for sid=0,63 do
            local a=S+sid*68
            if (r8(a+62)&1)~=0 and r32(a+28)==0x080DB3ED then
                local g={sid=sid,tile=r16(a+4)&1023,palette=(r16(a+4)>>12)&15,bytes=128,
                    callback=r32(a+28),template=r32(a+20),images=r32(a+12),anims=r32(a+8),
                    data_hex=hex(a+46,16),sprite_hex=hex(a,68),owner_id=player_id,owner_hex=hex(player,36)}
                check("ghost_wild_grass_template_"..sid,g.template==0x083A5420 and g.images==0x083A53DC
                    and g.anims==0x083A541C and (r8(a+62)&7)==3 and r16(a+60)==0
                    and (r16(a)&0xC000)==0 and (r16(a+2)&0xC000)==0x4000,true)
                check("ghost_wild_grass_owner_"..sid,(r16(a+52)>>8)==255
                    and s16(a+48)==s16(player+16) and s16(a+50)==s16(player+18)
                    and r16(player+16)==r16(player+20) and r16(player+18)==r16(player+22),true)
                check("ghost_wild_grass_rom_template_"..sid,r16(g.template)==65535 and r16(g.template+2)==0x1005
                    and r32(g.template+8)==g.anims and r32(g.template+12)==g.images
                    and r32(g.template+20)==g.callback,true)
                for frame=0,4 do check("ghost_wild_grass_frame_"..sid.."_"..frame,r16(g.images+frame*8+4),128) end
                check("ghost_wild_grass_ref_"..sid,r8(REFS+g.palette*4)==2 and r8(REFS+g.palette*4+1)==1
                    and r16(REFS+g.palette*4+2)==0x1005 and g.tile+4<=1024,true)
                matches[#matches+1]=g
            end
        end
        check("ghost_wild_grass_single_owner",#matches<=1,true)
        return matches
    end
    local function request(label,fn)
        check(label.."_field",field(),true)
        check(label.."_idle",r16(MB.BASE+6)==0 and r16(MB.BASE+10)==MB.ST_IDLE and MB.session_error()==nil,true)
        local token,why=fn();check(label.."_posted",token~=nil,true)
        out.requests[#out.requests+1]={label=label,token=token,frame=emu.framecount(),reason=why or ""}
        for i=0,60 do
            check(label.."_wait_field_"..i,field(),true)
            local status,error_text=MB.poll(token)
            if status==MB.ST_FAIL or MB.session_error() then error(label..": "..tostring(error_text or MB.session_error())) end
            if status==MB.ST_OK then return end
            api.advance({},label.."_wait_"..i,true)
        end
        error(label.." receipt timeout")
    end
    local component={schema="slink-rr-wild-presence-component-v1"}
    function component.before_frame()
        if not active or not field() or (last_frame and emu.framecount()-last_frame<2) then return end
        local id=r8(0x0203707D);local oe=O+id*36
        local p=Position.sample(oe,true)
        if not p then return end
        local face=r8(oe+24)&15;local anim=r8(S+p.sid*68+42)
        local moving=last_p~=nil and (p.wx~=last_p.wx or p.wy~=last_p.wy)
        local x,y=(p.wx+32)//16,p.wy//16
        local tile=peer_tiles[x..":"..y]
        local width,grid=r32(0x03005040),r32(0x03005048)
        check("ghost_wild_target_"..emu.framecount(),tile~=nil and width==39
            and grid>=0x02000000 and grid+39*54*2<=0x02040000
            and r16(grid+(y*width+x)*2)==tile.word,true)
        check("ghost_wild_publish_"..emu.framecount(),MB.ghost_set_pos(p.wx+32,p.wy,face,moving,anim,false),true)
        out.publications[#out.publications+1]={frame=emu.framecount(),wx=p.wx,wy=p.wy,peer_wx=p.wx+32,
            peer_wy=p.wy,moving=moving,face=face,anim=anim,callback2=r32(0x030030F4),script_lock=r8(0x03000F9C)}
        last_p=p;last_frame=emu.framecount()
    end
    function component.after_frame(p)
        if not MB then return end
        p.ghost=state()
        if field() then
            if attributable_allocation(p.ghost) then
                local key=p.ghost.tile..":"..p.ghost.allocation
                if not allocation_keys[key] then
                    allocation_keys[key]=true
                    out.allocations[#out.allocations+1]={first_frame=p.frame,tile=p.ghost.tile,bytes=p.ghost.allocation,
                        sprite_flags=p.ghost.sprite_flags,avatar_dirty=r8(GH+17),fully_owned=ref and owned(p.ghost) or false}
                end
            end
            if ref and owned(p.ghost) then
                out.field_owned_frames=out.field_owned_frames+1
            end
        else
            out.nonfield_frames=out.nonfield_frames+1
            -- Lifecycle is a diagnostic; active/OE ownership may remain stale.
            if p.ghost.lifecycle==2 then out.suspended_frames=out.suspended_frames+1 end
        end
    end
    function component.begin(scenario)
        api=scenario;api.out.ghost_component=out
        for _,tile in ipairs(api.out.route.peer_tiles or {}) do
            check("ghost_wild_peer_tile_"..tile.x.."_"..tile.y,((tile.word>>10)&3)==0
                and (tile.word>>12)==3 and ((tile.attribute>>24)&7)<=1,true)
            peer_tiles[tile.x..":"..tile.y]=tile
        end
        check("ghost_wild_begin_field",field(),true)
        local id=r8(0x0203707D);local oe=O+id*36;local sid=r8(oe+4);local sprite=S+sid*68
        check("ghost_wild_checkpoint",id<16 and sid<64 and s16(oe+16)==23 and s16(oe+18)==12
            and r16(oe+16)==r16(oe+20) and r16(oe+18)==r16(oe+22) and (r8(oe)&0x81)==0x81,true)
        check("ghost_wild_on_foot",(r8(0x02037078)&15)==1,true)
        check("ghost_wild_no_native_ui",r8(0x0203F840)==0 and r8(0x0203FC80)==0 and r8(0x0203FD00)==0,true)
        ref={player_id=id,sid=sid,gfx=r8(oe+5)|(r8(oe+35)<<8),images=r32(sprite+12),anims=r32(sprite+8),
            palette=(r16(sprite+4)>>12)&15,refs=hex(REFS,64),tiles=hex(TILES,128),party=hex(0x02024284,100)}
        check("ghost_wild_direct_gfx",ref.gfx,0)
        local info=r32(0x08EB1000)
        check("ghost_wild_graphics_record",info,0x08EB140C)
        ref.allocation=r16(info+6);ref.first_frame_bytes=r16(ref.images+4)
        check("ghost_wild_graphics_association",r32(info+28)==ref.images and r32(info+24)==ref.anims,true)
        check("ghost_wild_allocation",ref.allocation,512)
        local colors={};for i=0,15 do colors[#colors+1]=string.format("%04X",r16(0x020373F8+ref.palette*32+i*2)) end
        ref.colors=table.concat(colors);out.reference=ref
        for i=0,15 do check("ghost_wild_no_private_before_"..i,r8(REFS+i*4)~=6,true) end
        MB=dofile(C.source_root.."/lua/mailbox.lua")
        Position=dofile(C.source_root.."/lua/rr/peer_position.lua").new(memory)
        check("ghost_wild_mb_present",MB.present(),true)
        api.resources("ghost_before_spawn");api.capture("ghost_before_spawn");phase="spawning"
        request("ghost_wild_spawn",function() return MB.ghost_spawn(ref.gfx) end)
        for i=1,60 do
            if MB.ghost_oe()<16 then break end
            api.advance({},"ghost_spawn_"..i,true)
        end
        check("ghost_wild_spawned",MB.ghost_oe()<16,true)
        check("ghost_wild_avatar",MB.ghost_set_avatar(ref.images,ref.anims,ref.colors),true)
        active=true;component.before_frame();check("ghost_wild_snap",MB.ghost_snap(),true)
        for i=1,60 do
            api.advance({},"ghost_initial_settle_"..i,true)
            if owned(state()) then break end
        end
        phase="visible_field";out.initial=assert_owner("ghost_wild_initial")
        check("ghost_wild_initial_mailbox_settled",r16(MB.BASE+6)==0 and r16(MB.BASE+10)==MB.ST_IDLE
            and MB.session_error()==nil and r8(GH+17)==0,true)
        api.resources("ghost_initial_owned");api.capture("ghost_initial_owned")
    end
    function component.finish(scenario)
        api=scenario;phase="field_return_settle";last_p=nil;last_frame=nil;Position.reset()
        for i=1,90 do
            api.advance({},"ghost_return_settle_"..i,true)
            if owned(state()) then break end
        end
        out.returned=assert_owner("ghost_wild_returned")
        check("ghost_wild_battle_seen",out.nonfield_frames>0,true)
        -- Ownership can precede the displayed framebuffer. Run56 cleared on
        -- that same frame, so its screenshots never showed the restored ghost.
        -- Retain a stable owner through a bounded presentation interval first.
        out.return_presentation={first_frame=emu.framecount(),frames=12}
        for i=1,12 do
            api.advance({},"ghost_return_present_"..i,true)
            assert_owner("ghost_wild_return_present_"..i)
        end
        out.return_presentation.last_frame=emu.framecount()
        check("ghost_wild_return_presentation_observed",true,true)
        api.resources("ghost_returned_owned");api.capture("ghost_returned_owned")
        active=false;phase="clearing"
        request("ghost_wild_clear",function() return MB.ghost_clear() end)
        for i=1,60 do
            if MB.ghost_oe()==255 and r8(GH)==0 then break end
            api.advance({},"ghost_clear_"..i,true)
        end
        check("ghost_wild_removed",MB.ghost_oe()==255 and r8(GH)==0,true)
        for i=1,60 do api.advance({},"ghost_cleanup_settle_"..i,true) end
        for i=0,15 do
            local a=O+i*36
            check("ghost_wild_no_sentinel_after_"..i,(r8(a)&1)==0 or r8(a+8)~=0xF0,true)
            check("ghost_wild_no_private_after_"..i,r8(REFS+i*4)~=6,true)
        end
        for i=0,63 do
            local a=S+i*68
            check("ghost_wild_no_owned_sprite_after_"..i,(r8(a+62)&1)==0
                or (r32(a+28)~=(contract.ghost_callback|1) and r16(a+60)~=0x534C),true)
        end
        out.after={frame=emu.framecount(),refs=hex(REFS,64),tiles=hex(TILES,128),party=hex(0x02024284,100)}
        check("ghost_wild_final_field",field(),true)
        out.stock_reassignments=stock_grass_reassignment()
        local reassigned,grass_palettes={},{}
        for _,grass in ipairs(out.stock_reassignments) do
            grass_palettes[grass.palette]=true
            for bit=grass.tile,grass.tile+3 do reassigned[bit]=true end
        end
        for index,range in ipairs(out.allocations) do
            for bit=range.tile,range.tile+range.bytes//32-1 do
                check("ghost_wild_allocated_tile_accounted_"..index.."_"..bit,
                    ((r8(TILES+(bit>>3))>>(bit&7))&1)==0 or reassigned[bit]==true,true)
            end
        end
        for palette=0,15 do
            local baseline=ref.refs:sub(palette*8+1,palette*8+8)
            check("ghost_wild_ref_accounted_"..palette,out.after.refs:sub(palette*8+1,palette*8+8)==baseline
                or (grass_palettes[palette] and baseline=="00000000"),true)
        end
        for bit=0,1023 do
            local baseline=tonumber(ref.tiles:sub((bit>>3)*2+1,(bit>>3)*2+2),16)
            local expected=((baseline>>(bit&7))&1)==1 or reassigned[bit]==true
            check("ghost_wild_bitmap_accounted_"..bit,((r8(TILES+(bit>>3))>>(bit&7))&1)==1,expected)
        end
        check("ghost_wild_refs_accounted",true,true)
        check("ghost_wild_tiles_accounted",true,true)
        check("ghost_wild_party_preserved",out.after.party,ref.party)
        api.resources("ghost_after_clear");api.capture("ghost_after_clear");phase="complete"
        check("ghost_wild_component_complete",true,true)
    end
    dofile(C.source_root.."/lua/tests/rr/natural_battle_probe.lua")(ctx,component)
end
