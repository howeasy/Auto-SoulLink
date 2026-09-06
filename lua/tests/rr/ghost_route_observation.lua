-- Read-only map/actor observation before deriving a private gameplay input route.
-- Exact reviewed battery boot inputs are the only game controls used here.
-- No mailbox requests, RAM/register writes, encounters or route success claims.
return function(ctx)
    local C,report,check=ctx.config,ctx.report,ctx.check
    local out={classification="read_only_route_observation",release_ready=false,frames=0,
        limitations={"Static collision/attributes do not model NPC movement, scripts or one-way terrain",
            "Connected border cells require actual map-transition confirmation",
            "This observation does not establish a natural battle or ghost behavior"}}
    report.evidence.runtime=out
    check("route_observation_purpose",C.purpose,"validation")
    local function integer(v,lo,hi) return type(v)=="number" and v%1==0 and v>=lo and v<=hi end
    check("route_observation_budget",integer(C.frames,1,3600),true)
    local first=emu.framecount()
    if C.fixture_kind=="battery" then
        for index,step in ipairs(C.fixture_meta.boot_inputs or {}) do
            check("route_boot_step_"..index,integer(step.frames,1,600),true)
            for _=1,step.frames do
                check("route_boot_budget_"..out.frames,out.frames<C.frames,true)
                joypad.set(step.buttons or {});emu.frameadvance();out.frames=emu.framecount()-first
            end
        end
        joypad.set({})
        check("route_fixture_assertions",type(C.fixture_meta.ram_assertions)=="table" and #C.fixture_meta.ram_assertions>0,true)
        for index,a in ipairs(C.fixture_meta.ram_assertions) do
            check("route_fixture_range_"..index,integer(a.address,0x02000000,0x03007FFF)
                and (a.width==1 or a.width==2 or a.width==4)
                and ((a.address+a.width<=0x02040000) or (a.address>=0x03000000 and a.address+a.width<=0x03008000)),true)
            local value=a.width==1 and memory.read_u8(a.address) or
                (a.width==2 and memory.read_u16_le(a.address) or memory.read_u32_le(a.address))
            check("route_fixture_ram_"..index,value,a.expected)
        end
        check("fixture_loaded",true,true)
    else check("route_fixture_state",C.fixture_kind,"state") end
    local r8,r16,r32=memory.read_u8,memory.read_u16_le,memory.read_u32_le
    local function hex(address,length)
        local bytes={};for i=0,length-1 do bytes[#bytes+1]=string.format("%02x",r8(address+i)) end
        return table.concat(bytes)
    end
    local function rom(address,length) return integer(address,0x08000000,0x09FFFFFF) and address+length<=0x0A000000 end
    check("route_descriptor_required",type(C.descriptor)=="table" and C.descriptor.size==156,true)
    check("descriptor_matches_bound_rom",hex(C.descriptor.address,C.descriptor.size),C.descriptor.hex)
    check("route_field",r32(0x030030F4)==0x080565B5 and r8(0x03000F9C)==0,true)
    local frame=emu.framecount()
    local player_id=r8(0x0203707D)
    check("route_player_bound",player_id<16,true)
    local oe=0x02036E38+player_id*36
    out.player={id=player_id,map_group=r8(oe+10),map_num=r8(oe+9),x=r16(oe+16),y=r16(oe+18),
        previous_x=r16(oe+20),previous_y=r16(oe+22),flags=r8(oe),facing=r8(oe+24)&15,
        elevation=r8(oe+11)&15,avatar_flags=r8(0x02037078),sprite_id=r8(oe+4),object_hex=hex(oe,36)}
    check("route_player_stopped",(out.player.flags&0x81)==0x81 and out.player.x==out.player.previous_x
        and out.player.y==out.player.previous_y,true)
    local layout=r32(0x02036DFC)
    check("route_layout_pointer",rom(layout,28),true)
    local primary,secondary=r32(layout+16),r32(layout+20)
    check("route_tileset_pointers",rom(primary,24) and rom(secondary,24),true)
    local attributes1,attributes2=r32(primary+20),r32(secondary+20)
    check("route_attribute_pointers",rom(attributes1,640*4) and rom(attributes2,384*4),true)
    local width,height,grid=r32(0x03005040),r32(0x03005044),r32(0x03005048)
    check("route_grid_dimensions",integer(width,1,128) and integer(height,1,128),true)
    check("route_grid_pointer",integer(grid,0x02000000,0x0203FFFF) and grid%2==0 and grid+width*height*2<=0x02040000,true)
    check("route_player_inside_grid",out.player.x<width and out.player.y<height,true)
    out.map={header_hex=hex(0x02036DFC,28),layout=layout,layout_hex=hex(layout,28),
        width=r32(layout),height=r32(layout+4),grid_width=width,grid_height=height,grid_address=grid,
        primary_tileset=primary,secondary_tileset=secondary,primary_attributes=attributes1,secondary_attributes=attributes2,
        grid_words={},metatile_attributes={},border_offset=7,
        decoder="RR08058DC4 grid width/height/map at03005040; collision(bits10..11), elevation(bits12..15), metatile(bits0..9); RR08059080 attrs32/primary640"}
    for i=0,width*height-1 do out.map.grid_words[#out.map.grid_words+1]=r16(grid+i*2) end
    for i=0,1023 do
        local address=i<640 and attributes1+i*4 or attributes2+(i-640)*4
        out.map.metatile_attributes[#out.map.metatile_attributes+1]=r32(address)
    end
    out.objects={}
    for id=0,15 do
        local a=0x02036E38+id*36
        if (r8(a)&1)~=0 then out.objects[#out.objects+1]={id=id,local_id=r8(a+8),x=r16(a+16),y=r16(a+18),
            previous_x=r16(a+20),previous_y=r16(a+22),elevation=r8(a+11)&15,map_group=r8(a+10),map_num=r8(a+9),raw_hex=hex(a,36)} end
    end
    check("map_grid_captured",#out.map.grid_words,width*height)
    check("snapshot_context_stable",emu.framecount()==frame and r32(0x030030F4)==0x080565B5
        and r32(0x02036DFC)==layout and r8(0x0203707D)==player_id,true)
    local path=C.result_path:gsub("%.json$","").."_route_observation.png"
    local prior=io.open(path,"rb");if prior then prior:close() end
    check("route_capture_fresh",prior==nil,true)
    local ok,why=pcall(client.screenshot,path)
    check("route_capture_call",ok and why~=false,true)
    local file=io.open(path,"rb");check("route_capture_exists",file~=nil,true)
    local bytes=file:read(4*1024*1024+1);file:close()
    check("route_capture_png",type(bytes)=="string" and #bytes>=57 and #bytes<=4*1024*1024
        and bytes:sub(1,8)=="\137PNG\13\10\26\10" and bytes:sub(-8,-5)=="IEND",true)
    out.screenshot={path=path,bytes=#bytes,frame=frame,visual_review="pending"}
    check("map_observation_complete",true,true)
end
