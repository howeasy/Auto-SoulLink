-- Expiring one-use permission. No frame API, host calls or memory writes.
local JSON=require("json_codec")
local M={SCHEMA="slink-held-write-permit-v1"}
local fields={operation_id=32,operation_digest=64,context_generation=32,binding_digest=64,phase=true}
local function token(value,size)return type(value)=="string" and #value==size and value:match("^[0-9a-f]+$")end
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function scope(value)
    assert(type(value)=="table" and value~=JSON.null and getmetatable(value)==nil and JSON.kind(value)~="array","held-write scope required")
    for k in pairs(value)do assert(fields[k],"unexpected scope field")end
    for k,n in pairs(fields)do
        if n==true then assert(type(value[k])=="string" and #value[k]<=64 and value[k]:match("^[a-z][a-z0-9_%-]*$"))
        else assert(token(value[k],n),"invalid scope field")end
    end
    return copy(value)
end
local function same(a,b)return JSON.encode(a)==JSON.encode(b)end
function M.new(options)
    assert(type(options.clock)=="function" and type(options.current_scope)=="function" and type(options.verify_grant)=="function")
    local clock,current,verify,nonce=options.clock,options.current_scope,options.verify_grant,options.new_nonce or require("platform_identity").new_nonce
    local pending,grant,last,failed=nil,nil,nil,nil;local nonces={};local count=0
    local self={}
    local function now()
        local t=clock()
        assert(type(t)=="number" and t==t and t>=0 and t<math.huge and (last==nil or t>=last),"monotonic permit clock failed")
        last=t;return t
    end
    local function guarded(fn)
        if failed then return false,failed end
        local ok,result=pcall(fn)
        if not ok then pending=nil;grant=nil;failed=tostring(result);return false,failed end
        return result
    end
    local function valid()
        if not grant then return false end
        local selected=grant;now();local value=current();local t=now()
        if grant~=selected or not value or not same(scope(value),selected.scope) or t>=selected.deadline then grant=nil;return false end
        return true
    end
    function self:challenge()
        return guarded(function()
            local t=now();local value=scope(assert(current()))
            if pending and same(value,pending.scope) and t<pending.issued+1 then return copy(pending.request)end
            local id=assert(nonce());assert(token(id,32) and not nonces[id] and count<4096,"invalid/repeated permit nonce")
            nonces[id]=true;count=count+1
            local request={schema=M.SCHEMA,challenge=id,scope=value}
            pending={request=request,scope=value,issued=t};return copy(request)
        end)
    end
    function self:accept(packet)
        return guarded(function()
            local request=assert(pending,"unsolicited held-write permit");local value=scope(assert(current()));local t=now()
            assert(JSON.kind(packet)=="object" and packet.schema==M.SCHEMA and packet.challenge==request.request.challenge
                and same(scope(packet.scope),request.scope) and same(value,request.scope),"held-write reply differs")
            local allowed={schema=true,challenge=true,scope=true,uses=true,ttl_ms=true,proof_digest=true}
            for k in pairs(packet)do assert(allowed[k],"unexpected held-write grant field")end
            assert(packet.uses==1 and type(packet.ttl_ms)=="number" and packet.ttl_ms%1==0 and packet.ttl_ms>=1 and packet.ttl_ms<=1000
                and token(packet.proof_digest,64),"invalid held-write grant")
            local deadline=request.issued+packet.ttl_ms/1000
            assert(t<deadline and verify(copy(packet),copy(value))==true,"held-write proof refused/expired")
            local checked=scope(assert(current()));local verified_time=now()
            assert(not failed and pending==request and verified_time<deadline and same(checked,value),"permit changed during verification")
            grant={scope=value,deadline=deadline,used=false};pending=nil;return true
        end)
    end
    function self:valid()return guarded(valid)end
    function self:consume()
        return guarded(function()if not valid() or grant.used then return false end;grant.used=true;return true end)
    end
    function self:revoke()pending=nil;grant=nil end
    function self:status()return {valid=self:valid()==true,used=grant and grant.used or false,failed=failed,ordinary_execution=false}end
    return self
end
return M
