-- Capture exactly the reads made by the source-qualified safe-state predicate.
local M={}
function M.capture(profile)
    local JSON=require("json_codec");local point={pc=emu.getregister("PC"),sp=emu.getregister("SP"),rom=JSON.object(),system=JSON.object()}
    local safe,reason=require("gen1_write_safety").check(profile,{
        domains=function()return memory.getmemorydomainlist()end,
        register=function(name)return name=="PC" and point.pc or point.sp end,
        read_u8=function(address,domain)
            local value=memory.read_u8(address,domain);local field=domain=="ROM" and "rom" or "system"
            point[field][tostring(address)]=value;return value
        end})
    assert(safe,reason);return point
end
return M
