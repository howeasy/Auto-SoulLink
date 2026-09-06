-- Read-only prerequisite observation; no route inputs or native commands.
return function(ctx)
    dofile(ctx.config.source_root.."/lua/tests/rr/ghost_route_observation.lua")(ctx)
    local out=ctx.report.evidence.runtime
    out.classification="read_only_encounter_route_prerequisites"
    local r8,r16,r32=memory.read_u8,memory.read_u16_le,memory.read_u32_le
    local function hex(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",r8(a+i)) end;return table.concat(t)
    end
    -- VarGet0806E568 calls0806E454→09042DC4→090B9000. The verified
    -- expanded-var branch adds id*2 to02031374, so507E is0203B470.
    ctx.check("route_expanded_var_anchor",hex(0x090B9000,20),"094b0a4ac3181b041b0c934203d8084b4000c018")
    ctx.check("route_south_script_anchor",hex(0x0905AEA8,10),"290002167e5001006c02")
    out.prerequisites={var_507e_address=0x0203B470,var_507e=r16(0x0203B470),
        south_script=0x0905AEA8,south_script_hex=hex(0x0905AEA8,10),
        coordinate_event_tiles={{28,37},{29,37}},trigger_value=0,
        connections_address=r32(0x02036DFC+12),
        player_party_count=r8(0x02024029),
        player_mon_raw_hex=hex(0x02024284,100),
        scope="No traversal, encounter eligibility, ghost, battle, or return verdict"}
    ctx.check("encounter_prerequisites_captured",true,true)
end
