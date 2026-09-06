-- Canonical ASCII JSON for integer-valued cross-language journal documents.
-- Matches ProtocolJournal._encode for this deliberately bounded data domain.
-- Transport/local-store JSON keeps its existing UTF-8 encoding unchanged.
local JSON=require("json_codec")
local M={}
local controls={['0008']='\\b',['0009']='\\t',['000a']='\\n',['000c']='\\f',['000d']='\\r'}
function M.encode(value)
    local encoded,why=JSON.encode(value)
    if not encoded then return nil,why end
    local function integers(item)
        if type(item)=="number" then
            assert(item%1==0 and (not math.type or math.type(item)=="integer"),
                "canonical journal proof requires integer numbers")
        elseif type(item)=="table" and item~=JSON.null then
            for _,child in pairs(item)do integers(child)end
        end
    end
    local ok,result=pcall(function()
        integers(value)
        local out,index,size={},1,0
        local function append(part)
            size=size+#part;assert(size<=4*1024*1024,"canonical journal document exceeds byte bound")
            out[#out+1]=part
        end
        while index<=#encoded do
            local byte=encoded:byte(index)
            if byte==92 then
                local code=encoded:sub(index+2,index+5)
                if encoded:sub(index+1,index+1)=='u' and controls[code] then
                    append(controls[code]);index=index+6
                else
                    append(encoded:sub(index,index+1));index=index+2
                end
            elseif byte>=127 then
                local count,point=1,byte
                if byte>=240 then count,point=4,byte-240
                elseif byte>=224 then count,point=3,byte-224
                elseif byte>=192 then count,point=2,byte-192 end
                for offset=1,count-1 do point=point*64+encoded:byte(index+offset)-128 end
                if point<=65535 then append(string.format('\\u%04x',point))
                else
                    point=point-65536
                    append(string.format('\\u%04x\\u%04x',55296+math.floor(point/1024),56320+point%1024))
                end
                index=index+count
            else append(encoded:sub(index,index));index=index+1 end
        end
        return table.concat(out)
    end)
    if not ok then return nil,tostring(result)end
    return result
end
return M
