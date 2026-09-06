-- Candidate07 current-map proof through the actual Lua receiver and native ghost.
-- Ordinary route input; synthetic same-avatar peer. No party/storage mutations.
return function(ctx)
    local C,check=ctx.config,ctx.check
    check("connection_candidate",C.identity.rom_sha256,"d77635218962ffe0ff0b44d7c797f514f896e6e54281f8d17a703f4e1ecc7c37")
    check("connection_build",C.descriptor.build_id,"217a610a94bc6f602664d8a185417859e28b6b0326c0f8e0a551fb72217dd3e1")
    dofile(C.source_root.."/lua/tests/rr/route1_traversal_probe.lua")(ctx)
    local route=ctx.report.evidence.runtime
    local out={classification="candidate07_connection_receiver_component",release_ready=false,
        visual_review="pending",route=route,screenshots={},trace={}}
    ctx.report.evidence.runtime=out
    local MB=dofile(C.source_root.."/lua/mailbox.lua");package.loaded.mailbox=MB
    local PG=dofile(C.source_root.."/lua/peer_ghost_npc.lua");PG.init()
    local Position=dofile(C.source_root.."/lua/rr/peer_position.lua")
    local L=MB.LAYOUT;local GH=L.regions.ghost.address
    local O,S,REFS,TILES=0x02036E38,0x0202063C,0x0203B7D4,0x02021B48
    local r8,r16,r32,s16=memory.read_u8,memory.read_u16_le,memory.read_u32_le,memory.read_s16_le
    local first=emu.framecount()
    local function hex(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",r8(a+i)) end;return table.concat(t)
    end
    local function capture(label)
        local path=C.result_path:gsub("%.json$","").."_"..label..".png"
        local f=io.open(path,"rb");if f then f:close();error("reused screenshot") end
        client.screenshot(path);f=assert(io.open(path,"rb"));local raw=f:read("*a");f:close()
        check(label.."_png",#raw>57 and raw:sub(1,8)=="\137PNG\13\10\26\10",true)
        out.screenshots[#out.screenshots+1]={frame=emu.framecount(),path=path,label=label,bytes=#raw}
    end
    local function field()
        return r32(0x030030F4)==0x080565B5 and r8(0x03000F9C)==0 and r8(L.regions.swap.address)==0
    end
    check("connection_field",field(),true)
    local id=r8(0x0203707D);check("connection_player_index",id<16,true)
    local player=O+id*36;local sid=r8(player+4);check("connection_player_sprite",sid<64,true)
    local sprite=S+sid*68
    local pos=assert(Position.new(memory).sample(player,true))
    local source_tag=r16(REFS+((r16(sprite+4)>>12)&15)*4+2)
    check("connection_avatar_reference",pos.gfx==0 and r32(0x08EB1000)==0x08EB140C
        and r16(0x08EB140C+6)==512,true)
    check("connection_current_map",pos.mg==3 and pos.mn==19 and pos.x==17 and pos.y==7,true)
    check("connection_retained_spawn_map",r8(player+10)==3 and r8(player+9)==1,true)
    local width,height,grid=r32(0x03005040),r32(0x03005044),r32(0x03005048)
    check("connection_grid",width==39 and height==54 and grid>=0x02000000 and grid+width*height*2<=0x02040000,true)
    local target_word=r16(grid+(pos.y*width+pos.x+2)*2)
    check("connection_peer_tile",target_word~=0x3FF and ((target_word>>10)&3)==0 and (target_word>>12)==3,true)
    local palette=(r16(sprite+4)>>12)&15
    local colors={};for i=0,15 do colors[#colors+1]=string.format("%04X",r16(0x020373F8+palette*32+i*2)) end
    local packet={mg=pos.mg,mn=pos.mn,x=pos.wx+32,y=pos.wy,f=r8(player+24)&15,mv=0,run=0,
        an=r8(sprite+0x2A),gfx=pos.gfx,imgs=pos.imgs,anim=pos.anims,pcol=table.concat(colors)}
    out.packet=packet;out.before={refs=hex(REFS,64),tiles=hex(TILES,128),party=hex(0x02024284,600)}
    -- Read-only durable context preparation remains unsubmitted.
    check("connection_generation",MB.set_context_generation("private-connection-07"),true)
    local prepared=assert(MB.prepare(MB.OP_PING,{},"0000000000000060"))
    check("connection_prepared_map",prepared.context.map_group==3 and prepared.context.map_num==19
        and prepared.context.saveblock1==0x0202552C,true)
    out.preparation=prepared
    -- No submit: this isolated process retains the unused read-only preparation.
    capture("connection_before")
    check("connection_packet_accepted",PG.on_ghost_pos(packet),true)
    local n=0
    local function tick(label)
        n=n+1;check("connection_budget_"..n,emu.framecount()-first<240,true)
        check("connection_field_"..n,field(),true)
        MB.pump();PG.on_frame();joypad.set({});emu.frameadvance();MB.pump()
        local map=assert(Position.current_map(memory))
        check("connection_post_field_"..n,field(),true)
        check("connection_post_mailbox_"..n,MB.present() and MB.session_error()==nil,true)
        check("connection_map_retained_"..n,map.mg==3 and map.mn==19 and map.layout==pos.layout
            and map.saveblock1==pos.saveblock1,true)
        check("connection_party_count_"..n,r8(0x02024029),1)
        check("connection_party_"..n,hex(0x02024284,600),out.before.party)
        out.trace[#out.trace+1]={frame=emu.framecount(),label=label,ghost_id=MB.ghost_oe(),
            native_map_group=r8(GH+12),native_map_num=r8(GH+13),pg=PG.debug(),mailbox_fault=MB.session_error()}
    end
    local gid,gs
    local function owned()
        gid=MB.ghost_oe();if gid>=16 then return false end
        local oe=O+gid*36;local gsid=r8(oe+4);if gsid>=64 then return false end;gs=S+gsid*68
        local gp=(r16(gs+4)>>12)&15
        local tile=r16(gs+4)&1023
        if r16(gs+58)~=512 or tile+16>1024 then return false end
        for bit=tile,tile+15 do if ((r8(TILES+(bit>>3))>>(bit&7))&1)~=1 then return false end end
        return (r8(oe)&1)==1 and r8(oe+8)==0xF0 and (r8(gs+62)&7)==3 and r32(gs+28)==0x0837A9B5
            and r16(gs+60)==0x534C and r16(gs+46)==gid and r8(REFS+gp*4)==6 and r8(REFS+gp*4+1)==1
            and r16(REFS+gp*4+2)==source_tag and gp~=palette
            and (r16(gs)&0xC000)==(r16(sprite)&0xC000) and (r16(gs+2)&0xC000)==(r16(sprite+2)&0xC000)
            and r32(gs+12)==pos.imgs and r32(gs+8)==pos.anims and r8(GH+17)==0
    end
    for i=1,90 do tick("spawn");if owned() then break end end
    check("connection_native_owned",owned(),true)
    check("connection_native_current_map",r8(GH+12)==3 and r8(GH+13)==19,true)
    out.owned={object=hex(O+gid*36,36),sprite=hex(gs,68),refs=hex(REFS,64),tiles=hex(TILES,128)}
    for i=1,12 do tick("visible");check("connection_visible_owner_"..i,owned(),true);capture("connection_visible_"..i) end
    check("connection_visible_relative",s16(gs+32)==s16(sprite+32)+32 and s16(gs+34)==s16(sprite+34),true)
    PG.on_ghost_clear()
    for i=1,60 do tick("clear");if MB.ghost_oe()==255 and r8(GH)==0 then break end end
    check("connection_removed",MB.ghost_oe()==255 and r8(GH)==0,true)
    for _=1,8 do tick("cleanup") end
    check("connection_palette_restored",hex(REFS,64),out.before.refs)
    check("connection_tiles_restored",hex(TILES,128),out.before.tiles)
    for i=0,15 do check("connection_no_object_"..i,(r8(O+i*36)&1)==0 or r8(O+i*36+8)~=0xF0,true) end
    for i=0,63 do check("connection_no_sprite_"..i,(r8(S+i*68+62)&1)==0
        or (r32(S+i*68+28)~=0x0837A9B5 and r16(S+i*68+60)~=0x534C),true) end
    capture("connection_after")
    check("connection_component_complete",true,true)
end
