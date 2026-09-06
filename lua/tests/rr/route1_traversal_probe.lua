-- Bounded ordinary-input traversal only. No ghost, battle or RAM-write commands.
return function(ctx)
    local C,check=ctx.config,ctx.check
    dofile(C.source_root.."/lua/tests/rr/encounter_route_observation.lua")(ctx)
    local initial=ctx.report.evidence.runtime
    local out={classification="private_route1_traversal_observation",initial=initial,
        trace={},screenshots={},frames=0,release_ready=false,natural_battle_tested=false}
    ctx.report.evidence.runtime=out
    check("route1_trigger_disabled",initial.prerequisites.var_507e,1)
    local r8,r16,r32,s16=memory.read_u8,memory.read_u16_le,memory.read_u32_le,memory.read_s16_le
    local Position=dofile(C.source_root.."/lua/rr/peer_position.lua").new(memory)
    local first=emu.framecount()
    local original_party=r32(0x02024284)..":"..r32(0x02024288)
    local counter=0
    local function hex(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",r8(a+i)) end;return table.concat(t)
    end
    local function sample(label,input)
        local id=r8(0x0203707D);local oe=0x02036E38+id*36
        local sb1=r32(0x03003840)
        check("route1_save_pointer_"..(#out.trace+1),sb1>=0x02000000 and sb1+6<=0x02040000,true)
        local field=r32(0x030030F4)==0x080565B5 and r8(0x03000F9C)==0
        local pos=Position.sample(oe,field)
        local row={label=label,frame=emu.framecount(),input=input or {},callback2=r32(0x030030F4),
            script_lock=r8(0x03000F9C),player_id=id,map_group=r8(sb1+4),map_num=r8(sb1+5),
            saveblock1=sb1,object_spawn_map_group=r8(oe+10),object_spawn_map_num=r8(oe+9),layout=r32(0x02036DFC),
            x=s16(oe+16),y=s16(oe+18),previous_x=s16(oe+20),previous_y=s16(oe+22),
            flags=r8(oe),elevation=r8(oe+11)&15,field=field,position=pos,
            battle_type=r32(0x02022B4C),battle_outcome=r8(0x02023E8A),
            controller0=r32(0x03004FE0),controller1=r32(0x03004FE4)}
        out.trace[#out.trace+1]=row;return row
    end
    local function shot(label)
        local path=C.result_path:gsub("%.json$","").."_"..label..".png"
        local file=io.open(path,"rb");if file then file:close();error("Screenshot already exists") end
        client.screenshot(path);file=assert(io.open(path,"rb"));local data=file:read("*a");file:close()
        check(label.."_png",#data>57 and data:sub(1,8)=="\137PNG\13\10\26\10",true)
        out.screenshots[#out.screenshots+1]={path=path,label=label,frame=emu.framecount(),bytes=#data}
    end
    local function base_guard(row,label)
        check(label.."_party",r8(0x02024029)==1 and r32(0x02024284)..":"..r32(0x02024288)==original_party,true)
        check(label.."_player",row.player_id<16 and (row.flags&1)~=0,true)
        check(label.."_no_script",row.script_lock,0)
        check(label.."_no_action_controller",row.controller0~=0x0802E439 and row.controller1~=0x0802E439,true)
    end
    local function next_clear(row,button)
        local dx=button=="Left" and -1 or (button=="Right" and 1 or 0)
        local dy=button=="Up" and -1 or (button=="Down" and 1 or 0)
        local x,y=row.x+dx,row.y+dy
        local width,height,grid=r32(0x03005040),r32(0x03005044),r32(0x03005048)
        check("step_grid_"..counter,x>=0 and y>=0 and x<width and y<height,true)
        local tile=r16(grid+(y*width+x)*2)
        check("step_plain_"..counter,tile~=0x3FF and ((tile>>10)&3)==0 and (tile>>12)==3,true)
        if row.map_num==1 then
            check("step_observed_word_"..counter,tile,initial.map.grid_words[y*initial.map.grid_width+x+1])
            local attr=initial.map.metatile_attributes[(tile&1023)+1]
            check("step_observed_plain_"..counter,(attr&511)==0 and ((attr>>24)&7)==0,true)
        end
        for id=0,15 do
            local a=0x02036E38+id*36
            if id~=row.player_id and (r8(a)&1)~=0 then
                local e=r8(a+11)&15
                local occupies=(s16(a+16)==x and s16(a+18)==y) or (s16(a+20)==x and s16(a+22)==y)
                check("step_actor_"..counter.."_"..id,not (occupies and (e==0 or e==row.elevation)),true)
            end
        end
    end
    local function advance(button,label)
        counter=counter+1;out.frames=emu.framecount()-first
        check("traversal_budget_"..counter,out.frames<900,true)
        local before=sample(label.."_before",button and {[button]=true} or {})
        base_guard(before,label.."_guard_"..counter)
        if button and (before.flags&0x80)~=0 and before.x==before.previous_x and before.y==before.previous_y then
            next_clear(before,button)
        end
        joypad.set(button and {[button]=true} or {});emu.frameadvance();joypad.set({})
        return sample(label.."_after")
    end
    local function waypoint(button,x,y,limit,label)
        for _=1,limit do
            local row=sample(label.."_check")
            check(label.."_context_"..counter,row.field and row.map_group==3 and row.map_num==1
                and row.layout==initial.map.layout,true)
            if row.x==x and row.y==y and row.previous_x==x and row.previous_y==y and (row.flags&0x80)~=0 then
                shot(label);ctx.checkpoint(label);return
            end
            local input=button
            if row.x==x and row.y==y then input=nil end
            advance(input,label)
        end
        error("Waypoint timeout: "..label)
    end
    local ok,error_text=xpcall(function()
        shot("route1_start")
        waypoint("Down",33,36,128,"route1_waypoint_south2")
        waypoint("Left",29,36,192,"route1_waypoint_west4")
        check("route1_trigger_still_disabled",r16(0x0203B470),1)
        waypoint("Down",29,46,384,"route1_waypoint_south10")
        out.prediction={map_group=3,map_num=19,x=17,y=7,meaning="connection expectation, not prior observed position"}
        for i=1,240 do
            local row=sample("route1_connection_check")
            base_guard(row,"connection_guard_"..i)
            if row.field and row.map_group==3 and row.map_num==19 then
                if row.x==row.previous_x and row.y==row.previous_y and (row.flags&0x80)~=0 then
                    check("route1_expected_arrival",row.x==17 and row.y==7 and row.layout==0x082E55CC,true)
                    out.arrival=row;break
                end
            elseif row.map_group~=3 or (row.map_num~=1 and row.map_num~=19) then error("Unexpected map at connection") end
            local button=row.field and row.map_num==1 and row.y<47 and "Down" or nil
            advance(button,"route1_connection")
        end
        check("route1_idle_arrival",out.arrival~=nil,true)
        shot("route1_arrival")
        local width,height,grid=r32(0x03005040),r32(0x03005044),r32(0x03005048)
        local layout=r32(0x02036DFC)
        check("route1_layout_range",layout>=0x08000000 and layout+28<=0x0A000000,true)
        local primary,secondary=r32(layout+16),r32(layout+20)
        check("route1_tileset_range",primary>=0x08000000 and primary+24<=0x0A000000
            and secondary>=0x08000000 and secondary+24<=0x0A000000,true)
        local a1,a2=r32(primary+20),r32(secondary+20)
        check("route1_snapshot_ranges",width>0 and height>0 and width*height<=16384
            and grid>=0x02000000 and grid+width*height*2<=0x02040000
            and a1>=0x08000000 and a1+640*4<=0x0A000000
            and a2>=0x08000000 and a2+384*4<=0x0A000000,true)
        out.map={header_hex=hex(0x02036DFC,28),layout=layout,width=r32(layout),height=r32(layout+4),
            grid_width=width,grid_height=height,grid_address=grid,grid_words={},metatile_attributes={},
            events=r32(0x02036E00),connections=r32(0x02036E08)}
        for i=0,width*height-1 do out.map.grid_words[#out.map.grid_words+1]=r16(grid+i*2) end
        for i=0,1023 do out.map.metatile_attributes[#out.map.metatile_attributes+1]=r32(i<640 and a1+i*4 or a2+(i-640)*4) end
        out.party_raw_hex=hex(0x02024284,100)
        out.frames=emu.framecount()-first
        check("route1_traversal_complete",true,true)
    end,debug.traceback)
    joypad.set({})
    if not ok then out.error=tostring(error_text);shot("route1_failure");ctx.checkpoint("route1_failed");error(error_text,0) end
    ctx.checkpoint("route1_complete")
end
