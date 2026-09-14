local M={}
-- Read-only Red/Blue WRAM decoders for the scripted route point. `read(addr)` returns one byte.
M.EVENT_OAK_GOT_PARCEL=56  -- pokered constants/event_constants.asm: const_next $28, +2, skip 14
M.EVENT_GOT_OAKS_PARCEL=57
M.POKE_BALL=0x04
M.OAKS_PARCEL=0x46
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
