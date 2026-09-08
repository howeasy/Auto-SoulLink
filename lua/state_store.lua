-- Shared checked local state: binding, checksum, revision and readback after atomic replace.
-- A failed/ambiguous update latches the instance until it is closed and reopened.
local JSON=require("json_codec")
local M={SCHEMA="slink-local-state-v1"}

local function encode(value)
    local text,reason=JSON.encode(value)
    if not text then error(reason,0) end
    return text
end
local function clone(value) return assert(JSON.decode(encode(value))) end
-- Only for the private cache produced by unpack(), after full JSON validation.
-- Strings/numbers are immutable; table tags and the null sentinel are preserved.
-- External initial/replacement values still take the full codec validation path.
local function clone_validated(value)
    if value==JSON.null or type(value)~="table"then return value end
    local result=JSON.kind(value)=="array" and JSON.array() or JSON.object()
    for key,child in pairs(value)do result[key]=clone_validated(child)end
    return result
end
local function exact_fields(value,fields)
    if type(value)~="table" then return false end
    local count=0
    for key in pairs(value) do if not fields[key] then return false end; count=count+1 end
    local required=0;for _ in pairs(fields) do required=required+1 end
    return count==required
end

function M.open(backend,binding,initial)
    local ok,result=pcall(function()
        assert(type(backend)=="table" and type(backend.read)=="function" and
            type(backend.replace)=="function" and type(backend.sha256)=="function","storage backend required")
        local binding_text=encode(binding)
        if JSON.kind(JSON.decode(binding_text))~="object" then error("state binding must be an object",0) end
        local self={backend=backend,fault=nil,closed=false}
        local function unpack(text)
            local envelope,reason=JSON.decode(text)
            if reason or JSON.kind(envelope)~="object" then error(reason or "invalid state envelope",0) end
            if not exact_fields(envelope,{document=true,sha256=true}) then error("unexpected state envelope fields",0) end
            local document=envelope.document
            if JSON.kind(document)~="object" or document.schema~=M.SCHEMA then error("unsupported local state schema",0) end
            if not exact_fields(document,{schema=true,binding=true,revision=true,payload=true}) then error("unexpected state document fields",0) end
            if encode(document.binding)~=binding_text then error("local state belongs to a different run/save/cartridge",0) end
            if type(document.revision)~="number" or document.revision%1~=0 or document.revision<0 or document.revision>9007199254740991 then
                error("invalid local state revision",0)
            end
            if JSON.kind(document.payload)~="object" then error("local state payload must be an object",0) end
            if type(envelope.sha256)~="string" or envelope.sha256~=backend.sha256(encode(document)) then
                error("local state checksum mismatch",0)
            end
            return document
        end
        local text,reason=backend.read()
        if not text then
            if reason~="missing" then error(reason or "local state read failed",0) end
            local document={schema=M.SCHEMA,binding=clone(binding),revision=0,payload=clone(initial)}
            if JSON.kind(document.payload)~="object" then error("local state payload must be an object",0) end
            text=encode({document=document,sha256=backend.sha256(encode(document))})
            local saved,why=backend.replace(text)
            if not saved then error(why or "initial state publication failed",0) end
            local actual,read_error=backend.read()
            if actual~=text then error(read_error or "initial state readback differs",0) end
        end
        local document,wire=unpack(text),text
        function self:read()
            if self.closed or self.fault then return nil,self.fault or "state store is closed" end
            return clone_validated(document.payload),document.revision
        end
        function self:revision()
            if self.closed or self.fault then return nil,self.fault or "state store is closed" end
            return document.revision
        end
        function self:commit(payload)
            if self.closed or self.fault then return false,self.fault or "state store is closed" end
            local success,error=pcall(function()
                local actual,reason=backend.read()
                if actual~=wire then error(reason or "local state changed outside its owner",0) end
                if document.revision>=9007199254740991 then error("local state revision exhausted",0) end
                local next_document={schema=M.SCHEMA,binding=document.binding,
                    revision=document.revision+1,payload=clone(payload)}
                if JSON.kind(next_document.payload)~="object" then error("local state payload must be an object",0) end
                local next_wire=encode({document=next_document,sha256=backend.sha256(encode(next_document))})
                local saved,why=backend.replace(next_wire)
                if not saved then error(why or "state publication failed",0) end
                local observed,read_error=backend.read()
                if observed~=next_wire then error(read_error or "state publication readback differs",0) end
                document=unpack(observed);wire=observed
            end)
            if not success then self.fault=tostring(error);return false,self.fault end
            return true
        end
        function self:close()
            if not self.closed and backend.close then backend.close() end
            self.closed=true
        end
        return self
    end)
    if not ok then
        if backend and backend.close then pcall(backend.close) end
        return nil,tostring(result)
    end
    return result
end
return M
