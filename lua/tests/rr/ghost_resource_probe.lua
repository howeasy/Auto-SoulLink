-- Synthetic single-cartridge component evidence, launched only by native_gate.
-- Instrumentation is read-only. The only cartridge mutations are production MB
-- ghost requests; no raw RAM/register writes, event-ring drops or reconcile reset.
-- Frame-boundary resource assertions and captured PNGs are not duo/visual approval.
return function(ctx)
    local C,report,check=ctx.config,ctx.report,ctx.check
    local L=dofile(C.source_root.."/lua/rr/native_layout.lua")
    package.loaded["rr.native_layout"]=L -- exact private source closure, no cached foreign layout
    local R,F=L.regions,L.structures
    local O=C.probe_options or {}
    local out={classification="synthetic_single_cartridge_component",release_ready=false,
        visual_review="pending",arena_ownership="unresolved",cycles={},screenshots={},frames=0,
        limitations={"Frame-boundary snapshots do not attribute transient native writes",
            "Quiet-field normal allocation only; scene reset, exhaustion and effects require separate gates",
            "Same-player avatar reference is not a second player's transport or gameplay",
            "PNG capture is required but does not establish graphical correctness"}}
    report.evidence.runtime=out
    check("resource_probe_purpose",C.purpose,"validation")
    check("resource_probe_fixture_kind",C.fixture_kind=="state" or C.fixture_kind=="battery",true)
    local function integer(v,lo,hi) return type(v)=="number" and v%1==0 and v>=lo and v<=hi end
    local cycles,phase_frames,visible_frames,quiet_frames=O.cycles or 3,O.phase_frames or 60,O.visible_frames or 12,O.quiet_frames or 6
    check("resource_cycle_bound",integer(cycles,3,20),true)
    check("resource_phase_bound",integer(phase_frames,1,180),true)
    check("resource_visible_bound",integer(visible_frames,2,60),true)
    check("resource_quiet_bound",integer(quiet_frames,2,30),true)
    check("resource_total_bound",integer(C.frames,1,3600),true)
    check("resource_descriptor_required",type(C.descriptor)=="table" and C.descriptor.size==F.NativeDescriptor.size,true)
    local encoded_layout=L.sha256:gsub(".",function(c) return string.format("%02x",string.byte(c)) end).."00"
    local layout_start=F.NativeDescriptor.offsets.layout_sha256*2+1
    check("resource_layout_matches_selected_descriptor",
        C.descriptor.hex:sub(layout_start,layout_start+F.NativeDescriptor.bytes.layout_sha256*2-1),encoded_layout)
    local contract=O.native_contract or {}
    check("resource_symbol_build_bound",type(contract.build_id)=="string" and #contract.build_id==64
        and contract.build_id==C.descriptor.build_id,true)
    check("resource_callback_bound",integer(contract.ghost_callback,0x08000000,0x09FFFFFE)
        and contract.ghost_callback%2==0,true)

    local r8,r16,r32=memory.read_u8,memory.read_u16_le,memory.read_u32_le
    local s16=memory.read_s16_le
    local OBJECTS,SPRITES,REFS,TILES,GH=0x02036E38,0x0202063C,0x0203B7D4,0x02021B48,R.ghost.address
    local function hex(address,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",r8(address+i)) end
        return table.concat(t)
    end
    check("descriptor_matches_bound_rom",hex(C.descriptor.address,C.descriptor.size),C.descriptor.hex)
    local MB=dofile(C.source_root.."/lua/mailbox.lua")
    local function primitive_field()
        if not MB.present() then return false end
        if r32(0x030030F4)~=0x080565B5 or r8(0x03000F9C)~=0 or r8(R.swap.address)~=0
            or r8(R.ui.address)~=0 or r8(R.battle_notif.address)~=0 then return false end
        for i=0,15 do
            local t=0x03005090+i*40
            if r8(t+4)~=0 and (r32(t)==0x09094295 or r32(t)==0x0909411D) then return false end
        end
        local id=r8(0x0203707D)
        if id>=16 then return false end
        local oe=OBJECTS+id*0x24
        return (r8(oe)&0x81)==0x81 and r8(oe+4)<64
            and r16(oe+16)==r16(oe+20) and r16(oe+18)==r16(oe+22)
    end
    local first=emu.framecount()
    local function bounded_frame()
        check("frame_budget_"..out.frames,out.frames<C.frames,true)
        local prior=out.frames
        joypad.set({});emu.frameadvance()
        out.frames=emu.framecount()-first
        check("frame_advanced_"..prior,out.frames,prior+1)
    end
    if C.fixture_kind=="battery" then
        -- Only reviewed fixture inputs may boot. Discovery candidates cannot enter
        -- this script; native_gate validates the exact battery/ROM sidecar first.
        local allowed={A=true,B=true,Start=true,Select=true,Up=true,Down=true,Left=true,Right=true,L=true,R=true}
        for index,step in ipairs(C.fixture_meta.boot_inputs or {}) do
            check("boot_bound_"..index,integer(step.frames,1,600),true)
            for button,value in pairs(step.buttons or {}) do
                check("boot_button_"..index.."_"..tostring(button),allowed[button] and type(value)=="boolean",true)
            end
            for _=1,step.frames do
                check("boot_total_"..out.frames,out.frames<C.frames,true)
                joypad.set(step.buttons or {});emu.frameadvance();out.frames=emu.framecount()-first
            end
        end
        joypad.set({})
        check("fixture_assertions_present",type(C.fixture_meta.ram_assertions)=="table" and #C.fixture_meta.ram_assertions>0,true)
        for index,a in ipairs(C.fixture_meta.ram_assertions) do
            check("fixture_range_"..index,integer(a.address,0x02000000,0x03007FFF)
                and (a.width==1 or a.width==2 or a.width==4)
                and ((a.address+a.width<=0x02040000) or (a.address>=0x03000000 and a.address+a.width<=0x03008000)),true)
            local actual=a.width==1 and r8(a.address) or (a.width==2 and r16(a.address) or r32(a.address))
            check("fixture_ram_"..index,actual,a.expected)
        end
        check("fixture_loaded",true,true)
    end
    check("resource_field_prerequisite",primitive_field(),true)
    check("resource_mailbox_idle",r16(MB.BASE+6)==0 and r16(MB.BASE+10)==MB.ST_IDLE,true)
    check("resource_no_existing_presence",r8(GH+F.GhostState.offsets.active)==0 and r8(GH+F.GhostState.offsets.oeId)==255
        and r8(R.trade_npc.address)==0 and r8(R.peer_interact.address+F.SlinkState.offsets.pi_armed)==0,true)
    for i=0,15 do
        local oe=OBJECTS+i*36
        check("resource_no_sentinel_"..i,(r8(oe)&1)==0 or (r8(oe+8)~=0xF0 and r8(oe+8)~=0xF1),true)
        check("resource_no_private_reference_"..i,r8(REFS+i*4)~=6,true)
    end

    local player_id=r8(0x0203707D)
    local player=OBJECTS+player_id*0x24
    local player_sid=r8(player+4)
    local player_sprite=SPRITES+player_sid*0x44
    local reference={player_id=player_id,sprite_id=player_sid,map_group=r8(player+10),map_num=r8(player+9),
        x=s16(player+16),y=s16(player+18),facing=r8(player+24)&15,
        gfx=r8(player+5)|(r8(player+35)<<8),images=r32(player_sprite+12),anims=r32(player_sprite+8),
        palette=(r16(player_sprite+4)>>12)&15,shape=r16(player_sprite)&0xC000,size=r16(player_sprite+2)&0xC000,
        party_count=r8(0x02024029),party=hex(0x02024284,600)}
    reference.player_address=player;reference.sprite_address=player_sprite
    reference.raw_avatar_flags=r8(0x02037078);reference.anim_num=r8(player_sprite+42)
    reference.previous_x=s16(player+20);reference.previous_y=s16(player+22)
    reference.anim_cmd_index=r8(player_sprite+43);reference.anim_delay_pause=r8(player_sprite+44)
    reference.anim_flags=r8(player_sprite+63);reference.object_hex=hex(player,36)
    reference.sprite_hex=hex(player_sprite,68)
    out.reference=reference -- Preserve actual evidence even when a prerequisite refuses the probe.
    check("reference_facing",integer(reference.facing,1,4),true)
    check("reference_world_position_bound",integer(reference.x,-2048,2045) and integer(reference.y,-2048,2047),true)
    check("reference_sprite_owned",(r8(player_sprite+62)&1)==1 and r16(player_sprite+46)==player_id,true)
    -- RR UpdateMovementNormal08064788 finishes by synchronizing previousCoords
    -- and setting Sprite+2C bit40 (080647B2..B6), retaining the walk animNum.
    -- A face animation is therefore not the definition of a stopped player.
    local paused_locomotion=reference.anim_num>=4 and reference.anim_num<=19
        and reference.anim_num%4==reference.facing-1 and (reference.anim_delay_pause&0x40)~=0
    local reference_idle=(reference.raw_avatar_flags&0x0F)==1
        and (reference.anim_num==reference.facing-1 or paused_locomotion)
    reference.stopped_animation=paused_locomotion and "paused_locomotion" or "face"
    if not reference_idle then
        -- Diagnostic only: the strict gate below still fails. Never reuse an old
        -- capture or count this unqualified screenshot toward component evidence.
        local path=C.result_path:gsub("%.json$","").."_ghost_reference_rejected.png"
        local capture={path=path,frame=emu.framecount(),qualified=false,visual_review="pending"}
        out.reference_precondition_screenshot=capture
        local existing=io.open(path,"rb")
        if existing then existing:close();capture.error="refused existing diagnostic capture"
        else
            local ok,why=pcall(client.screenshot,path)
            local file=io.open(path,"rb")
            capture.capture_ok=ok and why~=false and file~=nil
            if file then capture.png_signature=file:read(8)=="\137PNG\13\10\26\10";file:close() end
            if not capture.capture_ok then capture.error=tostring(why or "capture file missing") end
        end
    end
    check("reference_on_foot_idle",reference_idle,true)
    check("reference_rom_tables",integer(reference.images,0x08000000,0x09FFFFF8) and reference.images%4==0
        and integer(reference.anims,0x08000000,0x09FFFFF0) and reference.anims%4==0,true)
    -- RR spawns against graphicsInfo.size, not image[0].size. The latter is
    -- merely one frame's transfer length (actual gfx0:512 reserved,256 frame0).
    -- Keep this probe limited to direct ROM graphics IDs; dynamic aliases need
    -- their own context proof, not a guessed implementation of VarGet.
    local bank,low=reference.gfx>>8,reference.gfx&255
    check("reference_direct_graphics",bank~=255 and low~=6 and low~=13 and not (bank==0 and low>=0xF0),true)
    local graphics_table=r32(0x091468CC+bank*4)
    if graphics_table==0 then graphics_table=0x08EB1000 end
    check("reference_graphics_table",integer(graphics_table,0x08000000,0x09FFFC00) and graphics_table%4==0,true)
    local info=r32(graphics_table+low*4)
    if info==0 then info=r32(0x08EB1000+16*4) end
    check("reference_graphics_record",integer(info,0x08000000,0x09FFFFDC) and info%4==0,true)
    reference.graphics_table=graphics_table;reference.graphics_info=info
    reference.graphics_info_hex=hex(info,36);reference.first_frame_bytes=r16(reference.images+4)
    reference.allocation=r16(info+6)
    check("reference_graphics_association",r32(info+28)==reference.images and r32(info+24)==reference.anims,true)
    check("reference_allocation",integer(reference.allocation,32,2048) and reference.allocation%32==0,true)
    check("reference_frame_fits_allocation",integer(reference.first_frame_bytes,32,reference.allocation)
        and reference.first_frame_bytes%32==0,true)
    local colors={};for i=0,15 do colors[#colors+1]=string.format("%04X",r16(0x020373F8+reference.palette*32+i*2)) end
    reference.colors=table.concat(colors)
    out.reference=reference
    local function field_guard(label)
        check(label.."_field",primitive_field(),true)
        check(label.."_player",r8(0x0203707D)==player_id and r8(player+4)==player_sid
            and r8(player+10)==reference.map_group and r8(player+9)==reference.map_num
            and s16(player+16)==reference.x and s16(player+18)==reference.y,true)
        check(label.."_avatar",(r8(player+5)|(r8(player+35)<<8))==reference.gfx
            and r32(player_sprite+12)==reference.images and r32(player_sprite+8)==reference.anims
            and ((r16(player_sprite+4)>>12)&15)==reference.palette,true)
        check(label.."_party",r8(0x02024029)==reference.party_count and hex(0x02024284,600)==reference.party,true)
    end
    local function advance(n,label)
        for i=1,n do field_guard(label.."_before_"..i);bounded_frame();field_guard(label.."_after_"..i) end
    end
    local function snapshot(label)
        local s={label=label,frame=emu.framecount(),refs={},tiles={},sprites={},objects={},
            reserved_tiles=r16(TILES-2),ref_bytes=hex(REFS,64),tile_bytes=hex(TILES,128)}
        for i=0,15 do
            local a=REFS+i*4
            s.refs[i+1]={kind=r8(a),count=r8(a+1),tag=r16(a+2),colors=hex(0x020373F8+i*32,32)}
            local oe=OBJECTS+i*36
            if (r8(oe)&1)~=0 then s.objects[tostring(i)]=string.format("%d:%d:%d:%d:%d",r8(oe+4),r8(oe+8),r8(oe+9),r8(oe+10),r8(oe+5)|(r8(oe+35)<<8)) end
        end
        for i=0,1023 do s.tiles[i+1]=(r8(TILES+(i>>3))>>(i&7))&1 end
        for i=0,63 do
            local a=SPRITES+i*68
            if (r8(a+62)&1)~=0 then
                s.sprites[tostring(i)]=string.format("%d:%d:%d:%d:%d:%d:%d",r16(a)&0xC000,r16(a+2)&0xC000,
                    r16(a+4)&0xF3FF,r32(a+8),r32(a+12),r32(a+20),r32(a+28))
            end
        end
        return s
    end
    local function existing_equal(label,base,now,ghost_id,ghost_sid,private_slot)
        check(label.."_reserved_tiles",now.reserved_tiles,base.reserved_tiles)
        for key,value in pairs(base.objects) do check(label.."_object_"..key,now.objects[key],value) end
        for key in pairs(now.objects) do check(label.."_new_object_"..key,base.objects[key]~=nil or tonumber(key)==ghost_id,true) end
        for key,value in pairs(base.sprites) do check(label.."_sprite_"..key,now.sprites[key],value) end
        for key in pairs(now.sprites) do check(label.."_new_sprite_"..key,base.sprites[key]~=nil or tonumber(key)==ghost_sid,true) end
        for i=0,15 do
            local before,after=base.refs[i+1],now.refs[i+1]
            if i~=private_slot then
                check(label.."_ref_"..i,string.format("%d:%d:%d",after.kind,after.count,after.tag),
                    string.format("%d:%d:%d",before.kind,before.count,before.tag))
                if before.kind~=0 then check(label.."_colors_"..i,after.colors,before.colors) end
            end
        end
    end
    local function be32(bytes,offset)
        local a,b,c,d=bytes:byte(offset,offset+3)
        return ((a*256+b)*256+c)*256+d
    end
    local function screenshot(label)
        local path=C.result_path:gsub("%.json$","").."_ghost_"..label..".png"
        local existing=io.open(path,"rb");if existing then existing:close() end
        check("screenshot_fresh_"..label,existing==nil,true)
        local ok,why=pcall(client.screenshot,path)
        check("screenshot_call_"..label,ok and why~=false,true)
        local file=io.open(path,"rb")
        check("screenshot_exists_"..label,file~=nil,true)
        local data=file:read(4*1024*1024+1);file:close()
        check("screenshot_png_"..label,type(data)=="string" and #data>=57 and #data<=4*1024*1024
            and data:sub(1,8)=="\137PNG\13\10\26\10" and data:sub(13,16)=="IHDR"
            and data:sub(-8,-5)=="IEND",true)
        local offset,idat,ended=9,false,false
        while offset+11<=#data do
            local length=be32(data,offset)
            local kind=data:sub(offset+4,offset+7)
            check("screenshot_chunk_"..label.."_"..offset,offset+11+length<=#data,true)
            if offset==9 then check("screenshot_ihdr_"..label,length,13) end
            if kind=="IDAT" and length>0 then idat=true end
            if kind=="IEND" then ended=length==0 and offset+11==#data;break end
            offset=offset+length+12
        end
        check("screenshot_chunks_complete_"..label,idat and ended,true)
        local width,height=be32(data,17),be32(data,21)
        check("screenshot_dimensions_"..label,width==240 and height==160,true)
        out.screenshots[#out.screenshots+1]={path=path,label=label,bytes=#data,width=width,height=height,
            frame=emu.framecount(),visual_review="pending"}
    end
    local function wait_for(label,predicate)
        for i=0,phase_frames do
            field_guard(label.."_guard_"..i)
            if predicate() then return end
            if i<phase_frames then bounded_frame() end
        end
        check(label.."_completed",false,true)
    end
    local function request(label,fn)
        field_guard(label.."_admission")
        check(label.."_mailbox_idle",r16(MB.BASE+6)==0 and r16(MB.BASE+10)==MB.ST_IDLE and MB.session_error()==nil,true)
        local token,why=fn()
        check(label.."_posted",token~=nil,true)
        wait_for(label.."_ack",function()
            local status,reason=MB.poll(token)
            if status==MB.ST_FAIL or MB.session_error() then error(label.." native failure: "..tostring(reason or MB.session_error())) end
            return status==MB.ST_OK
        end)
        return {token=token,reason=why or "",ack_frame=emu.framecount()}
    end
    local requested=false
    local function run()
        local unquiet=snapshot("initial")
        advance(quiet_frames,"quiet")
        local baseline=snapshot("before")
        existing_equal("quiet_resources",unquiet,baseline,nil,nil,nil)
        check("quiet_tile_bitmap",baseline.tile_bytes,unquiet.tile_bytes)
        out.before=baseline
        screenshot("before")
        for cycle=1,cycles do
            local label="cycle_"..cycle
            local row={index=cycle};out.cycles[#out.cycles+1]=row
            requested=true
            row.spawn=request(label.."_spawn",function() return MB.ghost_spawn(reference.gfx) end)
            wait_for(label.."_owned_spawn",function() return MB.ghost_oe()<16 end)
            local oeid=MB.ghost_oe();local oe=OBJECTS+oeid*36
            local sid=r8(oe+4)
            row.spawn_state={object_id=oeid,object_address=oe,object_hex=hex(oe,36),sprite_id=sid}
            check(label.."_sid_bound",sid<64,true)
            local sprite=SPRITES+sid*68
            row.spawn_state.sprite_address=sprite;row.spawn_state.sprite_hex=hex(sprite,68)
            row.spawn_state.images=r32(sprite+12);row.spawn_state.anims=r32(sprite+8)
            row.spawn_state.callback=r32(sprite+28);row.spawn_state.allocation=r16(sprite+58)
            row.spawn_state.shape=r16(sprite)&0xC000;row.spawn_state.size=r16(sprite+2)&0xC000
            row.spawn_state.palette=(r16(sprite+4)>>12)&15;row.spawn_state.tile_start=r16(sprite+4)&1023
            check(label.."_object_owner",(r8(oe)&1)==1 and r8(oe+8)==0xF0 and r16(sprite+46)==oeid,true)
            check(label.."_callback_owner",r32(sprite+28),contract.ghost_callback|1)
            check(label.."_sprite_marker",r16(sprite+60),0x534C)
            check(label.."_native_allocation",r16(sprite+58),reference.allocation)
            check(label.."_geometry",(r16(sprite)&0xC000)==reference.shape and (r16(sprite+2)&0xC000)==reference.size,true)
            check(label.."_individual_tiles",(r8(sprite+63)&0x40)==0,true)
            field_guard(label.."_avatar_admission")
            check(label.."_avatar_posted",MB.ghost_set_avatar(reference.images,reference.anims,reference.colors),true)
            check(label.."_position_posted",MB.ghost_set_pos((reference.x+2)*16,reference.y*16,reference.facing,false,reference.facing-1,false),true)
            check(label.."_snap_posted",MB.ghost_snap(),true)
            wait_for(label.."_avatar_acceptance",function()
                return r8(GH+F.GhostState.offsets.avatarDirty)==0 and r32(sprite+12)==reference.images and r32(sprite+8)==reference.anims
                    and (r8(sprite+62)&5)==1
            end)
            advance(visible_frames,label.."_visible")
            check(label.."_still_owned",MB.ghost_oe()==oeid and r8(oe+4)==sid and (r8(oe)&1)==1
                and (r8(sprite+62)&5)==1 and r16(sprite+46)==oeid and r16(sprite+60)==0x534C
                and r16(sprite+58)==reference.allocation and r32(sprite+28)==(contract.ghost_callback|1),true)
            local screenx=s16(sprite+32)+s16(0x02021BC8)
            local screeny=s16(sprite+34)+s16(0x02021BCA)
            check(label.."_on_screen",screenx>=0 and screenx<240 and screeny>=0 and screeny<160,true)
            check(label.."_position",s16(sprite+32)-s16(player_sprite+32)==32
                and s16(sprite+34)==s16(player_sprite+34),true)
            local live=snapshot(label.."_visible")
            local palette=(r16(sprite+4)>>12)&15
            local tile=r16(sprite+4)&1023
            local count=reference.allocation//32
            check(label.."_private_slot",baseline.refs[palette+1].kind==0 and baseline.refs[palette+1].count==0
                and palette~=reference.palette,true)
            check(label.."_private_reference",live.refs[palette+1].kind==6 and live.refs[palette+1].count==1
                and live.refs[palette+1].tag==baseline.refs[reference.palette+1].tag,true)
            check(label.."_private_colors",live.refs[palette+1].colors,baseline.refs[reference.palette+1].colors)
            check(label.."_tile_range",tile>=baseline.reserved_tiles and tile+count<=1024,true)
            existing_equal(label.."_preserved",baseline,live,oeid,sid,palette)
            for bit=0,1023 do
                if bit>=tile and bit<tile+count then
                    check(label.."_tile_was_free_"..bit,baseline.tiles[bit+1],0)
                    check(label.."_tile_owned_"..bit,live.tiles[bit+1],1)
                else check(label.."_foreign_tile_"..bit,live.tiles[bit+1],baseline.tiles[bit+1]) end
            end
            row.visible=live;row.owner={object_id=oeid,sprite_id=sid,palette=palette,tile_start=tile,tile_count=count}
            screenshot(label.."_visible")
            row.clear=request(label.."_clear",function() return MB.ghost_clear() end)
            wait_for(label.."_removed",function() return MB.ghost_oe()==255 and r8(GH)==0 end)
            advance(quiet_frames,label.."_cleanup")
            local after=snapshot(label.."_after")
            existing_equal(label.."_restored",baseline,after,nil,nil,nil)
            check(label.."_all_refs_restored",after.ref_bytes,baseline.ref_bytes)
            check(label.."_all_tiles_restored",after.tile_bytes,baseline.tile_bytes)
            check(label.."_interaction_disarmed",r8(R.peer_interact.address+F.SlinkState.offsets.pi_armed),0)
            row.after=after;requested=false
            screenshot(label.."_after")
        end
        check("resource_cycles_completed",#out.cycles,cycles)
        check("resource_screenshots_complete",#out.screenshots,1+cycles*2)
        check("resource_frame_budget",out.frames<=C.frames,true)
        check("resource_normal_lifetime_complete",true,true)
    end
    local ok,why=pcall(run)
    if not ok then
        -- Best-effort ordinary cleanup only while the exact quiet field remains
        -- ours and no uncertain mailbox operation is pending. Never force RAM.
        out.failure_cleanup={attempted=false,completed=false}
        if requested and primitive_field() and r16(MB.BASE+6)==0 and r16(MB.BASE+10)==MB.ST_IDLE
            and MB.session_error()==nil and out.frames<C.frames then
            out.failure_cleanup.attempted=true
            local cleaned,problem=pcall(function()
                request("failure_clear",function() return MB.ghost_clear() end)
                wait_for("failure_removed",function() return MB.ghost_oe()==255 and r8(GH)==0 end)
            end)
            out.failure_cleanup.completed=cleaned
            if not cleaned then out.failure_cleanup.error=tostring(problem) end
        end
        error(why,0)
    end
    -- Test-only composition seam: another bounded component may reuse this
    -- already-settled volatile mailbox instance instead of reloading its owner.
    -- These closures grant no production admission or frame-execution authority.
    return {mailbox=MB,reference=reference,resources_snapshot=snapshot}
end
