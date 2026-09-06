-- Pure, inactive RR4.1 withdrawal oracle. No memory, mailbox or persistence API.
-- See docs/rr_reference/WITHDRAWAL_ORACLE.md for pinned binary anchors and limits.
local Oracle = {}

local function integer(value, low, high)
    return type(value)=="number" and value%1==0 and value>=low and value<=high
end
local function u16(bytes, offset)
    return bytes:byte(offset+1)|(bytes:byte(offset+2)<<8)
end
local function u32(bytes, offset)
    return u16(bytes,offset)|(u16(bytes,offset+2)<<16)
end
local function sized(bytes, length)
    return type(bytes)=="string" and #bytes==length
end

-- `tables` contains immutable bytes from the pinned ROM, selected for this
-- source species. Association/provenance must be checked by the future binding.
-- `context` is an explicit input, not a claim that this helper grants admission.
function Oracle.derive(compressed, tables, context)
    if not sized(compressed,58) or type(tables)~="table" or type(context)~="table" then
        return nil,"invalid oracle input"
    end
    if context.mode~="default" or type(context.minimal_grinding)~="boolean"
        or type(context.frontier_active)~="boolean" then
        return nil,"unverified RR mode context"
    end
    -- The three scaling predicates read flag0930 and var5018 even outside battle.
    -- Keep every frontier context outside this first independently proven branch.
    if context.frontier_active then return nil,"frontier stat contexts are not modeled" end
    if not sized(tables.base_stats,28) or not sized(tables.experience,1024)
        or not sized(tables.nature,125) or type(tables.move_pp)~="table" then
        return nil,"incomplete pinned table evidence"
    end
    local species=u16(compressed,0x1C)
    if not integer(species,1,1375) or tables.species_id~=species then
        return nil,"species evidence mismatch"
    end
    if (compressed:byte(0x13+1)&1)~=0 then return nil,"bad-egg accessor is not modeled" end
    if tables.base_stats:byte(1)==0 or tables.growth_rate~=tables.base_stats:byte(20)
        or not integer(tables.growth_rate,0,5) then
        return nil,"invalid species or growth evidence"
    end
    local experience=u32(compressed,0x20)
    -- Actual GetLevelFromMonExp scans levels1..250, using256 u32s/growth row.
    -- Do not apply the campaign's EXP earning cap or silently clamp to100 here.
    local level=0
    for candidate=1,250 do
        if u32(tables.experience,candidate*4)>experience then break end
        level=candidate
    end
    local personality=u32(compressed,0)
    local nature=personality%25
    local iv_bits=u32(compressed,0x36)
    local stats={}
    for index=0,5 do
        local base=tables.base_stats:byte(index+1)
        local iv=(iv_bits>>(index*5))&31
        local ev=compressed:byte(0x2C+index+1)
        local scaled=((2*base+iv+(ev//4))*level)//100
        if index==0 then
            stats[1]=species==303 and 1 or math.min(scaled+level+10,65535)
        else
            local value=(scaled+5)&65535
            local modifier=tables.nature:byte(nature*5+index)
            if modifier~=0 and modifier~=1 and modifier~=255 then
                return nil,"invalid nature-table evidence"
            end
            -- RR's patched routine multiplies by9/11, truncates to u16, /10.
            if modifier~=0 then value=((value*(modifier==1 and 11 or 9))&65535)//10 end
            stats[index+1]=value
        end
    end
    local packed=0
    for index=0,4 do packed=packed|(compressed:byte(0x27+index+1)<<(index*8)) end
    local pp_bonuses=compressed:byte(0x24+1)
    local moves,pp={},{}
    for index=0,3 do
        local move=(packed>>(index*10))&1023
        local base=tables.move_pp[move]
        if not integer(base,0,255) then return nil,"missing move PP evidence" end
        moves[index+1]=move
        -- Includes move0: exact RR record0 PP=35. Do not normalize empty PP to0.
        pp[index+1]=(base+(base*20*((pp_bonuses>>(index*2))&3))//100)&255
    end
    -- Builder zeroes80 bytes, copies represented fields, marks+4F bit7, then
    -- fills moves/PP. BoxMonToMon sets status/HP/maxHP0 and mailFF before stats.
    local bytes={}
    for index=1,100 do bytes[index]=0 end
    local function copy(source, destination, length)
        for index=0,length-1 do bytes[destination+index+1]=compressed:byte(source+index+1) end
    end
    local function put16(offset,value)
        bytes[offset+1]=value&255;bytes[offset+2]=(value>>8)&255
    end
    copy(0,0,0x1C);copy(0x1C,0x20,11);copy(0x2C,0x38,6);copy(0x32,0x44,8)
    bytes[0x4F+1]=128
    for index=0,3 do put16(0x2C+index*2,moves[index+1]);bytes[0x34+index+1]=pp[index+1] end
    bytes[0x54+1]=level;bytes[0x55+1]=255
    put16(0x56,stats[1])
    for index=0,5 do put16(0x58+index*2,stats[index+1]) end
    return {schema="rr41-withdrawal-oracle-v1",party_bytes=string.char(table.unpack(bytes)),
        species_id=species,level=level,nature=nature,status=0,hp=stats[1],max_hp=stats[1],
        stats=stats,moves=moves,pp=pp,mail=255,
        evidence_scope="pinned-standard-stat-branch; not an admission or execution receipt"}
end

return Oracle
