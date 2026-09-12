-- Exact in-memory dirty vector for every byte the RBY inventory decoder consumes.
-- Use the native bulk binary reader and compare immutable Lua strings byte-for-byte;
-- no digest collision or partial sample may hide a change. Nothing from this private
-- vector is accepted by the server: a difference still publishes the complete
-- existing rby-full-save-point-v1 evidence.
local Layout=require("gen1_full_save_layout")
local M={SCHEMA="rby-inventory-fingerprint-v1"}
local function read(address,count,domain)
    assert(memory.read_bytes_as_binary_string,"native bulk binary memory reader unavailable")
    local ok,value=pcall(memory.read_bytes_as_binary_string,address,count,domain)
    assert(ok,"bulk binary memory read failed: "..tostring(value))
    assert(type(value)=="string"and#value==count,"bulk binary memory read returned an incomplete range")
    return value
end
function M.capture(mem,variant)
    local info=assert(Layout[variant]);local fields={}
    for _,name in ipairs({"party","box","name"})do
        local region=assert(info.regions[name]);fields[name]=read(region.address,region.length,"System Bus")
    end
    fields.player_id=read(assert(mem.PLAYER_ID_ADDR),2,"System Bus")
    fields.current_box=read(assert(mem.CURRENT_BOX_NUM_ADDR),1,"System Bus")
    local boxes={}
    for index=0,11 do
        local offset=(2+math.floor(index/6))*0x2000+(index%6)*1122
        boxes[index+1]=read(offset,1122,"CartRAM")
    end
    return {schema=M.SCHEMA,variant=variant,fields=fields,boxes=boxes}
end
function M.same(a,b)
    if type(a)~="table"or type(b)~="table"or a.schema~=M.SCHEMA or b.schema~=M.SCHEMA
        or a.variant~=b.variant then return false end
    for _,name in ipairs({"party","box","name","player_id","current_box"})do
        if a.fields[name]~=b.fields[name]then return false end
    end
    if #a.boxes~=12 or #b.boxes~=12 then return false end
    for index=1,12 do if a.boxes[index]~=b.boxes[index]then return false end end
    return true
end
return M
