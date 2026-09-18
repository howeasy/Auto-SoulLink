local M={}
-- Read-only Red/Blue WRAM decoders for the scripted route point. `read(addr)` returns one byte.
-- The game facts (event bits, bag item ids) come from the foundation's facts table (P3b-e): the
-- vanilla twin at load, or the caller's lane through `with_facts`. Red/Blue values are
-- 56/57/0x04/0x46 (pokered constants/event_constants.asm: `const_next $28, +2, const_skip 14`).
local function here() return (debug.getinfo(1, "S").source or ""):match("^@(.*[/\\])") or "" end
function M.with_facts(facts)
    assert(facts and facts.EVENT and facts.ITEM, "point fields need a facts table")
    M.EVENT_OAK_GOT_PARCEL  = facts.EVENT.OAK_GOT_PARCEL
    M.EVENT_GOT_OAKS_PARCEL = facts.EVENT.GOT_OAKS_PARCEL
    M.POKE_BALL             = facts.ITEM.POKE_BALL
    M.OAKS_PARCEL           = facts.ITEM.OAKS_PARCEL
    return M
end
M.with_facts(dofile(here() .. "gen1_rb_facts.lua"))
local FACING={[0x00]="down",[0x04]="up",[0x08]="left",[0x0C]="right"}
function M.event_bit(read,base,bit)
    return math.floor(read(base+math.floor(bit/8))/(2^(bit%8)))%2==1
end
function M.bcd_money(read,base)
    local value=0
    for i=0,2 do
        local byte=read(base+i)
        value=value*100+math.floor(byte/16)*10+byte%16
    end
    return value
end
function M.bag_quantity(read,num_addr,items_addr,item_id)
    local count=read(num_addr)
    if count>20 then return 0 end
    for i=0,count-1 do
        local id=read(items_addr+i*2)
        if id==0xFF then break end
        if id==item_id then return read(items_addr+i*2+1) end
    end
    return 0
end
function M.facing_name(byte)
    return FACING[byte] or "unknown"
end
return M
