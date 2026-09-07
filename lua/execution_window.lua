-- Command-scoped, expiring frame credits. No host calls, RAM writes or ordinary
-- gameplay permission. Caller validates the authenticated server/generation proof.
local JSON=require("json_codec")
local Identity=require("platform_identity")
local M={SCHEMA="slink-operation-execution-window-v1"}
local scope_fields={operation_id=32,operation_digest=64,context_generation=32,binding_digest=64,phase=true}
local function token(value,size)return type(value)=="string"and #value==size and value:match("^[0-9a-f]+$")~=nil end
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
-- Both operands have already passed checked_scope (or are private copies of it).
-- This closed, flat schema contains only strings, so equality needs no JSON work
-- on the per-frame path. Grant serialization and external proof validation stay separate.
local function same(a,b)
    for name in pairs(scope_fields)do if a[name]~=b[name]then return false end end
    return true
end
local function checked_scope(value)
    assert(type(value)=="table"and value~=JSON.null and getmetatable(value)==nil
        and JSON.kind(value)~="array","owned operation scope required")
    for name in pairs(value)do assert(scope_fields[name],"unexpected operation scope field")end
    local result={}
    for name,size in pairs(scope_fields)do
        if size==true then
            assert(type(value[name])=="string"and #value[name]<=64 and value[name]:match("^[a-z][a-z0-9_%-]*$"),"bounded operation phase required")
        else assert(token(value[name],size),"invalid operation "..name)end
        result[name]=value[name]
    end
    return JSON.object(result)
end
function M.new(options)
    assert(type(options)=="table"and type(options.clock)=="function"and type(options.current_scope)=="function"
        and type(options.verify_grant)=="function","clock, owned scope and private grant verifier required")
    local maximum=options.max_frames or 120
    local lifetime=options.max_lifetime_ms or 1000
    local operation_limit=options.max_operation_frames or 6000
    assert(type(maximum)=="number"and maximum%1==0 and maximum>=1 and maximum<=600,"bounded maximum frames required")
    assert(type(lifetime)=="number"and lifetime%1==0 and lifetime>=1 and lifetime<=2000,"bounded maximum lifetime required")
    assert(type(operation_limit)=="number"and operation_limit%1==0 and operation_limit>=1 and operation_limit<=60000,
        "bounded operation-wide frame ceiling required")
    local state={pending=nil,grant=nil,failed=nil,last_clock=nil,nonces={},nonce_count=0,consumed=0,scope_counts={}}
    local self={}
    local function clear(why)
        state.pending=nil;state.grant=nil;state.reason=tostring(why or "operation authority revoked")
    end
    local function failed(why)
        state.failed=state.failed or tostring(why);clear(state.failed)
        return false,state.failed
    end
    local function now()
        local value=options.clock()
        if not(type(value)=="number"and value==value and value>=0 and value<math.huge
            and (state.last_clock==nil or value>=state.last_clock))then
            failed("monotonic operation clock failed");error(state.failed,0)
        end
        state.last_clock=value;return value
    end
    local function scope()
        local current=options.current_scope()
        if current==nil then clear("no owned operation");return nil end
        return checked_scope(current)
    end
    local function live()
        if state.failed then return false end
        now();local current=scope();local time=now();local grant=state.grant
        if not grant then return false end
        if not current or not same(current,grant.scope)then clear("operation scope changed");return false end
        if time>=grant.deadline then state.grant=nil;state.reason="operation execution window expired";return false end
        if grant.remaining==0 then state.reason="operation frame budget exhausted";return false end
        if (state.scope_counts[grant.key]or 0)>=operation_limit then state.reason="operation-wide frame ceiling reached";return false end
        return true
    end
    function self:challenge()
        if state.failed then return nil,state.failed end
        local ok,result=pcall(function()
            local time=now();local current=assert(scope(),"no owned operation")
            if state.grant and not same(current,state.grant.scope)then clear("operation scope changed")end
            local pending=state.pending
            if pending and same(current,pending.scope)and time<pending.issued+lifetime/1000 then
                return {schema=M.SCHEMA,challenge=pending.challenge,scope=copy(current)}
            end
            local nonce=assert((options.new_nonce or Identity.new_nonce)())
            assert(token(nonce,32)and not state.nonces[nonce],"operation challenge repeated or invalid")
            assert(state.nonce_count<4096,"operation challenge history requires a new service")
            state.nonces[nonce]=true;state.nonce_count=state.nonce_count+1
            state.pending={challenge=nonce,scope=current,issued=time}
            return {schema=M.SCHEMA,challenge=nonce,scope=copy(current)}
        end)
        if not ok then failed(result);return nil,result end
        return result
    end
    function self:accept(packet)
        if state.failed then return false,state.failed end
        local ok,result=pcall(function()
            local time=now();local current=scope();local pending=state.pending
            assert(JSON.kind(packet)=="object"and packet.schema==M.SCHEMA and pending
                and packet.challenge==pending.challenge and same(checked_scope(packet.scope),pending.scope)
                and current and same(current,pending.scope),"operation response differs from the current challenge/scope")
            local fields={schema=true,challenge=true,scope=true,frames=true,ttl_ms=true,proof_digest=true}
            for name in pairs(packet)do assert(fields[name],"unexpected execution grant field")end
            assert(type(packet.frames)=="number"and packet.frames%1==0 and packet.frames>=1 and packet.frames<=maximum,
                "invalid operation frame budget")
            assert(type(packet.ttl_ms)=="number"and packet.ttl_ms%1==0 and packet.ttl_ms>=1 and packet.ttl_ms<=lifetime,
                "invalid operation lifetime")
            assert(token(packet.proof_digest,64),"operation-specific server proof required")
            local key=assert(JSON.encode(pending.scope))
            assert(packet.frames<=operation_limit-(state.scope_counts[key]or 0),"operation-wide frame ceiling exceeded")
            local deadline=pending.issued+packet.ttl_ms/1000
            assert(time<deadline,"operation response already expired")
            assert(options.verify_grant(copy(packet),copy(pending.scope))==true,"operation grant proof was not verified")
            -- Verification time and context changes must not extend or rescue a lease.
            current=scope();time=now()
            assert(not state.failed and state.pending==pending and time<deadline and current and same(current,pending.scope),
                "operation authority changed during verification")
            assert(packet.frames<=operation_limit-(state.scope_counts[key]or 0),"operation budget changed during verification")
            state.pending=nil
            state.grant={challenge=packet.challenge,scope=copy(pending.scope),deadline=deadline,
                remaining=packet.frames,proof_digest=packet.proof_digest,key=key}
            state.reason="fresh verified operation window"
            return true
        end)
        if not ok then clear(result);return false,tostring(result)end
        return result
    end
    function self:ready()
        local ok,result=pcall(live)
        if not ok then return failed(result)end
        return result
    end
    function self:consume(current)
        local ok,result=pcall(function()
            if not live()or not same(checked_scope(current),state.grant.scope)then return false end
            -- Spend before the caller invokes its physical frame. Failure never
            -- refunds a credit or retries a frame behind the caller's back.
            state.grant.remaining=state.grant.remaining-1
            state.scope_counts[state.grant.key]=(state.scope_counts[state.grant.key]or 0)+1
            state.consumed=state.consumed+1
            return true
        end)
        if not ok then return failed(result)end
        return result
    end
    function self:revoke(why)clear(why)end
    function self:status()
        local available=self:ready()
        return {schema=M.SCHEMA,available=available==true,remaining=state.grant and state.grant.remaining or 0,
            consumed=state.consumed,failed=state.failed,reason=state.reason,
            operation_limit=operation_limit,
            ordinary_execution=false,native_recovery_execution=false}
    end
    return self
end
return M
