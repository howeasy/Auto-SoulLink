-- Shared execution authority policy. No RAM addresses, game writes or frame advance.
-- The host adapter owns an independent execution hold and preserves user pause.
-- Caller must service this from an emu.yield loop even while emulation is held.
local Identity=require("platform_identity")
local M={}
local function hex(value,size)
    return type(value)=="string" and #value==size and value:match("^[0-9a-f]+$")~=nil
end
local function reason(value)
    return type(value)=="string" and #value>0 and #value<=256 and not value:find("[%c]")
end
function M.new(options)
    assert(type(options)=="table" and type(options.clock)=="function","monotonic clock required")
    assert(type(options.host)=="table" and type(options.host.set_held)=="function",
        "execution hold adapter required")
    local timeout=options.timeout or 2
    assert(type(timeout)=="number" and timeout>0 and timeout<math.huge,"invalid watchdog timeout")
    assert(options.service_execution==nil or type(options.service_execution)=="boolean",
        "explicit service execution selection must be boolean")
    local service_selected=options.service_execution==true
    local audit_interval=options.audit_interval or 0.05
    assert(type(audit_interval)=="number"and audit_interval>0 and audit_interval<=0.5,
        "bounded host audit interval required")
    local state={held=true,reason="waiting for paired admission and reconciliation",last_clock=nil,
        binding=nil,pending=nil,last_started=nil,ticket=nil,last_nonce=nil,failed=false,barred_epoch=nil,
        authority="hold",service_epoch=nil,service_digest=nil,barred_service_epoch=nil,last_host_audit=nil}
    local self={}
    local function set_held(value,why)
        assert(options.host.set_held(value,why)==true,"execution hold was not verified")
    end
    local function audit(time,force)
        if not force and state.last_host_audit and time-state.last_host_audit<audit_interval then return true end
        if options.host.verify then assert(options.host.verify()==true,"execution hold audit was not verified")end
        state.last_host_audit=time
        return true
    end
    local function now()
        local ok,value=pcall(options.clock)
        if not ok or type(value)~="number" or value~=value or value<0 or value==math.huge
            or (state.last_clock and value<state.last_clock) then
            state.failed=true
            self:revoke("monotonic clock failed")
            error("monotonic clock failed",0)
        end
        state.last_clock=value
        -- Enforce expiry before any callback can replace last_started with a
        -- younger in-flight challenge. The service itself may cross the deadline.
        if state.last_started and value-state.last_started>=timeout then
            self:revoke("paired connection liveness expired; fresh admission required")
        end
        return value
    end
    local function hold(why,bar_service)
        assert(type(bar_service)=="boolean","explicit service-epoch disposition required")
        if state.ticket then state.barred_epoch=state.ticket.epoch end
        if bar_service and state.service_epoch then state.barred_service_epoch=state.service_epoch end
        state.held=true;state.reason=why;state.ticket=nil;state.last_started=nil
        state.authority="hold";state.service_epoch=nil;state.service_digest=nil
        set_held(true,why)
    end
    function self:revoke(why)
        assert(reason(why),"explicit revocation reason required")
        state.binding=nil;state.pending=nil
        hold(why,true)
    end
    function self:bind(binding)
        assert(type(binding)=="table","admitted control binding required")
        for _,key in ipairs({"session_id","admission_epoch","context_generation"}) do
            assert(hex(binding[key],32),"invalid control "..key)
        end
        assert(hex(binding.binding_digest,64),"invalid control binding digest")
        assert(not state.failed,"control service failure requires reopening")
        self:revoke("new session requires fresh paired reconciliation")
        state.binding={}
        for _,key in ipairs({"session_id","admission_epoch","context_generation","binding_digest"}) do
            state.binding[key]=binding[key]
        end
    end
    function self:challenge()
        local time=now()
        assert(state.binding and not state.failed,"no active control binding")
        if not state.pending or time-state.pending.issued>=timeout then
            local nonce,why=(options.new_nonce or Identity.new_nonce)()
            assert(hex(nonce,32),why or "invalid control challenge")
            assert(nonce~=state.last_nonce,"control nonce repeated")
            state.last_nonce=nonce;state.pending={nonce=nonce,issued=time}
        end
        local out={challenge=state.pending.nonce}
        for key,value in pairs(state.binding) do out[key]=value end
        return out
    end
    function self:accept(packet)
        -- Caller has already validated the authenticated session response shape.
        -- A ticket alone, TCP connect, or any semantic ACK cannot grant execution.
        local time=now()
        if not state.binding or state.failed or type(packet)~="table" then return false end
        for key,value in pairs(state.binding) do if packet[key]~=value then return false end end
        local pending=state.pending
        if not pending or packet.challenge~=pending.nonce then return false end
        state.pending=nil
        if time-pending.issued>=timeout then return false end
        local function exact(fields)
            local expected={challenge=true,authority=true}
            for key in pairs(state.binding)do expected[key]=true end
            for _,key in ipairs(fields)do expected[key]=true end
            for key in pairs(packet)do if not expected[key]then return false end end
            for key in pairs(expected)do if packet[key]==nil then return false end end
            return true
        end
        if packet.authority=="hold" and exact({"reason"}) and reason(packet.reason) then
            hold(packet.reason,false);return true
        end
        if (packet.authority~="service" and packet.authority~="run")
            or not hex(packet.service_epoch,32) or not hex(packet.service_digest,64) then
            hold("invalid paired execution authority",true);return false
        end
        if packet.service_epoch==state.barred_service_epoch then
            hold("service authority predates the execution hold",true);return false
        end
        if packet.authority=="service" then
            if not exact({"service_epoch","service_digest","reason"}) or not reason(packet.reason) then
                hold("invalid paired service authority",true);return false
            end
            state.authority="service";state.service_epoch=packet.service_epoch
            state.service_digest=packet.service_digest;state.ticket=nil
            state.last_started=pending.issued;state.reason=packet.reason
            return true
        end
        if not exact({"service_epoch","service_digest","recovery_epoch","ticket_digest"})
            or not hex(packet.recovery_epoch,32) or not hex(packet.ticket_digest,64) then
            hold("invalid paired execution authority",true);return false
        end
        if packet.recovery_epoch==state.barred_epoch then
            hold("reconciliation predates the execution hold",true);return false
        end
        state.authority="run";state.service_epoch=packet.service_epoch
        state.service_digest=packet.service_digest
        state.ticket={epoch=packet.recovery_epoch,digest=packet.ticket_digest}
        state.last_started=pending.issued
        state.reason="paired reconciliation and fresh roundtrip confirmed"
        return true
    end
    function self:step(service)
        -- Reconciliation/network persistence may continue under the hold. Ordinary
        -- observation detection and physical operations are separate gated callers.
        local ok,why=pcall(function()
            local time=now()
            if service then service(self) end
            time=now()
            local service_permitted=service_selected and state.authority=="service"
            local permitted=not state.failed and state.binding and state.last_started
                and time-state.last_started<timeout and (state.authority=="run" or service_permitted)
            set_held(not permitted,state.reason)
            state.held=not permitted
            audit(time,false)
        end)
        if not ok then
            state.failed=true;state.binding=nil;state.pending=nil
            -- Try the independent host hold even after a clock/network/store failure.
            local held,problem=pcall(hold,"control service failed: "..tostring(why):sub(1,200),true)
            if not held then return false,"execution hold failed: "..tostring(problem) end
            return false,tostring(why)
        end
        return true
    end
    function self:status()
        return {held=state.held,reason=state.reason,failed=state.failed,authority=state.authority,
            admitted=state.binding~=nil,recovery_epoch=state.ticket and state.ticket.epoch or nil,
            service_epoch=state.service_epoch,service_digest=state.service_digest,
            barred_service_epoch=state.barred_service_epoch,
            service_execution=service_selected and not state.held
                and (state.authority=="service" or state.authority=="run"),
            ordinary_execution=state.authority=="run" and not state.held,
            read_only_service=true,native_recovery_execution=false}
    end
    function self:verify()return audit(now(),true)end
    -- Fail before exposing an object if the host cannot establish the initial hold.
    set_held(true,state.reason)
    return self
end
return M
