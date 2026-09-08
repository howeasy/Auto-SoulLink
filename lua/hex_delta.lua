-- Same-length byte deltas. The caller owns addresses and execution authority.
local JSON=require("json_codec")
local M={}
local function hex(value)
    assert(type(value)=="string" and #value>0 and #value<=2*1024*1024 and #value%2==0 and value:match("^[0-9A-F]+$"),"bounded canonical hex required")
    return value
end
function M.apply(before,delta)
    hex(before)
    assert(type(delta)=="table" and delta.length==#before/2 and JSON.kind(delta.runs)=="array","exact byte delta geometry required")
    for k in pairs(delta)do assert(k=="length" or k=="runs","unexpected delta field")end
    local last=0;local parts={}
    for _,run in ipairs(delta.runs)do
        for k in pairs(run)do assert(k=="offset" or k=="before" or k=="after","unexpected delta run field")end
        local old,new=hex(run.before),hex(run.after);local at=run.offset
        assert(type(at)=="number" and at%1==0 and at>=last and #old==#new and at+#old/2<=#before/2,"overlapping/resized delta")
        assert(before:sub(at*2+1,at*2+#old)==old,"delta preimage differs")
        parts[#parts+1]=before:sub(last*2+1,at*2);parts[#parts+1]=new;last=at+#old/2
    end
    parts[#parts+1]=before:sub(last*2+1)
    return table.concat(parts)
end
function M.recover_before(current,delta)
    hex(current)
    assert(type(delta)=="table" and JSON.kind(delta.runs)=="array","exact recovery delta required")
    local last=0;local parts={}
    for _,run in ipairs(delta.runs)do
        local old,new=hex(run.before),hex(run.after);local at=run.offset
        assert(type(at)=="number" and at%1==0 and at>=last and #old==#new and at+#old/2<=#current/2,"invalid recovery geometry")
        for i=1,#old,2 do
            local byte=current:sub(at*2+i,at*2+i+1)
            assert(byte==old:sub(i,i+1) or byte==new:sub(i,i+1),"partial image contains foreign bytes")
        end
        parts[#parts+1]=current:sub(last*2+1,at*2);parts[#parts+1]=old;last=at+#old/2
    end
    parts[#parts+1]=current:sub(last*2+1)
    local before=table.concat(parts);M.apply(before,delta)
    return before
end
return M
