-- Bounded JSON decoding (RFC8259). No load()/evaluation and no dropped null entries.
-- Duplicate object keys, unpaired surrogates and non-interoperable numbers are
-- rejected deliberately. https://www.rfc-editor.org/rfc/rfc8259.html
local M = {null = {}}
local kinds = setmetatable({}, {__mode = "k"})
function M.kind(value)
    if value == M.null then return "null" end
    return type(value) == "table" and kinds[value] or type(value)
end
local escapes = {['"']='"', ['\\']='\\', ['/']='/', b='\b', f='\f', n='\n', r='\r', t='\t'}

local function utf8_character(value)
    if value < 0x80 then return string.char(value) end
    if value < 0x800 then return string.char(0xC0 + math.floor(value / 64), 0x80 + value % 64) end
    if value < 0x10000 then
        return string.char(0xE0 + math.floor(value / 4096), 0x80 + math.floor(value / 64) % 64, 0x80 + value % 64)
    end
    return string.char(0xF0 + math.floor(value / 262144), 0x80 + math.floor(value / 4096) % 64,
                       0x80 + math.floor(value / 64) % 64, 0x80 + value % 64)
end

function M.decode(input, limits)
    limits = limits or {}
    local maximum = limits.bytes or 4 * 1024 * 1024
    if type(input) ~= "string" or #input > maximum then return nil, "invalid or oversized JSON frame" end
    local max_depth, max_items = limits.depth or 32, limits.items or 100000
    local max_string = limits.string_bytes or 1024 * 1024
    local index, items = 1, 0
    local function fail(why) error(why .. " at JSON byte " .. index, 0) end
    local function ws()
        while true do
            local c = input:byte(index)
            if c ~= 32 and c ~= 9 and c ~= 10 and c ~= 13 then return end
            index = index + 1
        end
    end
    local function item()
        items = items + 1
        if items > max_items then fail("too many JSON values") end
    end
    local function hex4()
        local value = input:sub(index, index + 3)
        if #value ~= 4 or not value:match("^%x%x%x%x$") then fail("invalid Unicode escape") end
        index = index + 4
        return tonumber(value, 16)
    end
    local function quoted()
        if input:sub(index, index) ~= '"' then fail("expected JSON string") end
        index = index + 1
        local chunks, start, size = {}, index, 0
        local function add(value)
            size = size + #value
            if size > max_string then fail("JSON string exceeds limit") end
            chunks[#chunks + 1] = value
        end
        while index <= #input do
            local byte = input:byte(index)
            if byte == 34 then
                add(input:sub(start, index - 1))
                index = index + 1
                return table.concat(chunks)
            elseif byte == 92 then
                add(input:sub(start, index - 1))
                index = index + 1
                local escape = input:sub(index, index)
                index = index + 1
                if escape == "u" then
                    local value = hex4()
                    if value >= 0xD800 and value <= 0xDBFF then
                        if input:sub(index, index + 1) ~= "\\u" then fail("unpaired high surrogate") end
                        index = index + 2
                        local low = hex4()
                        if low < 0xDC00 or low > 0xDFFF then fail("unpaired high surrogate") end
                        value = 0x10000 + (value - 0xD800) * 1024 + low - 0xDC00
                    elseif value >= 0xDC00 and value <= 0xDFFF then
                        fail("unpaired low surrogate")
                    end
                    add(utf8_character(value))
                elseif escapes[escape] then
                    add(escapes[escape])
                else
                    fail("invalid JSON escape")
                end
                start = index
            elseif byte < 32 then
                fail("unescaped control character")
            elseif byte < 128 then
                index = index + 1
            else
                -- Validate raw UTF-8, including overlong forms and surrogate encodings.
                local length = (byte >= 0xC2 and byte <= 0xDF) and 2
                    or (byte >= 0xE0 and byte <= 0xEF) and 3
                    or (byte >= 0xF0 and byte <= 0xF4) and 4 or nil
                if not length then fail("invalid UTF-8 lead byte") end
                for offset = 1, length - 1 do
                    local next_byte = input:byte(index + offset)
                    if not next_byte or next_byte < 0x80 or next_byte > 0xBF then fail("invalid UTF-8 continuation") end
                end
                local second = input:byte(index + 1)
                if (byte == 0xE0 and second < 0xA0) or (byte == 0xED and second >= 0xA0)
                    or (byte == 0xF0 and second < 0x90) or (byte == 0xF4 and second > 0x8F) then
                    fail("non-scalar or overlong UTF-8")
                end
                index = index + length
            end
            if size + index - start > max_string then fail("JSON string exceeds limit") end
        end
        fail("unterminated JSON string")
    end
    local function number()
        local start = index
        if input:sub(index, index) == "-" then index = index + 1 end
        local first = input:sub(index, index)
        if first == "0" then
            index = index + 1
        elseif first:match("^[1-9]$") then
            repeat index = index + 1 until not input:sub(index, index):match("^%d$")
        else
            fail("invalid JSON number")
        end
        if input:sub(index, index) == "." then
            index = index + 1
            if not input:sub(index, index):match("^%d$") then fail("missing fraction digits") end
            repeat index = index + 1 until not input:sub(index, index):match("^%d$")
        end
        if input:sub(index, index):match("^[eE]$") then
            index = index + 1
            if input:sub(index, index):match("^[+-]$") then index = index + 1 end
            if not input:sub(index, index):match("^%d$") then fail("missing exponent digits") end
            repeat index = index + 1 until not input:sub(index, index):match("^%d$")
        end
        local value = tonumber(input:sub(start, index - 1))
        if not value or value ~= value or math.abs(value) > 9007199254740991 then
            fail("JSON number exceeds interoperable range")
        end
        return value
    end
    local value
    value = function(depth)
        if depth > max_depth then fail("JSON nesting exceeds limit") end
        ws(); item()
        local c = input:sub(index, index)
        if c == '"' then return quoted() end
        if c == "{" or c == "[" then
            local object, close = c == "{", c == "{" and "}" or "]"
            local result, seen, count = {}, {}, 0
            kinds[result] = object and "object" or "array"
            index = index + 1
            ws()
            if input:sub(index, index) == close then index = index + 1; return result end
            while true do
                local key
                if object then
                    ws(); key = quoted(); ws()
                    if seen[key] then fail("duplicate JSON object key") end
                    seen[key] = true
                    if input:sub(index, index) ~= ":" then fail("missing object colon") end
                    index = index + 1
                else
                    count = count + 1
                    key = count
                end
                result[key] = value(depth + 1)
                ws()
                local next_char = input:sub(index, index)
                index = index + 1
                if next_char == close then return result end
                if next_char ~= "," then fail("missing JSON separator") end
            end
        end
        for literal, result in pairs({["true"] = true, ["false"] = false, ["null"] = M.null}) do
            if input:sub(index, index + #literal - 1) == literal then
                index = index + #literal
                return result
            end
        end
        return number()
    end
    local success, result = pcall(function()
        local parsed = value(0)
        ws()
        if index <= #input then fail("trailing JSON content") end
        return parsed
    end)
    if not success then return nil, tostring(result) end
    return result
end

function M.array(value)
    value=value or {}
    assert(type(value)=="table" and value~=M.null,"array table required")
    kinds[value]="array"
    return value
end

function M.object(value)
    value=value or {}
    assert(type(value)=="table" and value~=M.null,"object table required")
    kinds[value]="object"
    return value
end

function M.encode(value, limits)
    limits=limits or {}
    local maximum=limits.bytes or 4*1024*1024
    local max_depth,max_items=limits.depth or 32,limits.items or 100000
    local max_string=limits.string_bytes or 1024*1024
    local parts,size,items,active={},0,0,{}
    local function append(text)
        size=size+#text
        if size>maximum then error("encoded JSON frame exceeds byte bound",0) end
        parts[#parts+1]=text
    end
    local function quote(text)
        if #text>max_string then error("JSON string exceeds byte bound",0) end
        return '"'..text:gsub('[%z\1-\31\\"]',function(char)
            if char=='"' then return '\\"' end
            if char=='\\' then return '\\\\' end
            return string.format('\\u%04x',char:byte())
        end)..'"'
    end
    local emit
    emit=function(item,depth)
        items=items+1
        if depth>max_depth or items>max_items then error("JSON structure exceeds bounds",0) end
        local kind=type(item)
        if item==nil or item==M.null then append("null")
        elseif kind=="boolean" then append(item and "true" or "false")
        elseif kind=="number" then
            if item~=item or item < -9007199254740991 or item>9007199254740991 then
                error("JSON number exceeds exact range",0)
            end
            append(item%1==0 and string.format("%.0f",item) or string.format("%.17g",item))
        elseif kind=="string" then append(quote(item))
        elseif kind=="table" then
            if active[item] or getmetatable(item)~=nil then error("cyclic or metatable JSON value",0) end
            active[item]=true
            local tag=M.kind(item)
            local is_array=tag=="array" or (tag~="object" and #item>0)
            local count,keys=0,{}
            for key in pairs(item) do
                count=count+1
                if is_array then
                    if type(key)~="number" or key%1~=0 or key<1 or key>#item then
                        error("JSON array must be contiguous",0)
                    end
                else
                    if type(key)~="string" then error("JSON object keys must be strings",0) end
                    keys[#keys+1]=key
                end
            end
            if is_array then
                if count~=#item then error("JSON array has a missing entry",0) end
                append("[")
                for i=1,#item do if i>1 then append(",") end; emit(item[i],depth+1) end
                append("]")
            else
                table.sort(keys)
                append("{")
                for i,key in ipairs(keys) do
                    if i>1 then append(",") end
                    append(quote(key)); append(":"); emit(item[key],depth+1)
                end
                append("}")
            end
            active[item]=nil
        else error("unsupported JSON value type",0) end
    end
    local ok,error=pcall(emit,value,0)
    if not ok then return nil,tostring(error) end
    local encoded=table.concat(parts)
    -- The decoder is also the canonical UTF-8, number and structural validator.
    -- This avoids a second subtly different Unicode implementation for output.
    local _,reason=M.decode(encoded,limits)
    if reason then return nil,reason end
    return encoded
end

return M
