-- Neutral synchronous connection/hello scheduler. Readiness means a hello was
-- queued for the current connection/identity; it is NOT server admission or ACK.
-- Transport, identity, game readiness, payload, retries and cleanup are policies.
local HelloSession = {}
local function integer(value) return type(value) == "number" and value % 1 == 0 and value >= 0 end
local function identity_key(value)
    return (type(value) == "string" and value ~= "")
           or (type(value) == "number" and value == value and math.abs(value) ~= math.huge)
end

function HelloSession.new(policy)
    assert(type(policy) == "table", "hello session policy required")
    for _, name in ipairs({"connected", "identity", "ready", "send", "retry_delay", "on_invalidate", "on_error"}) do
        assert(type(policy[name]) == "function", "hello policy." .. name .. " required")
    end
    -- Explicit binder choices, no defaults: what a backward clock (savestate load) and a
    -- throwing callback mean for the session.
    assert(policy.clock_rewind == "invalidate" or policy.clock_rewind == "keep",
           "hello policy.clock_rewind must be 'invalidate' or 'keep'")
    assert(policy.callback_error == "invalidate" or policy.callback_error == "raise",
           "hello policy.callback_error must be 'invalidate' or 'raise'")
    local state = {ready=false, connected=false, attempts=0, generation=0}
    local pending_cleanup, stage
    local self = {}

    local function report_error(where, why)
        state.last_error = where .. ": " .. tostring(why)
        pcall(policy.on_error, where, tostring(why))
    end
    local function cleanup()
        if not pending_cleanup then return true end
        local ok, why = pcall(policy.on_invalidate, pending_cleanup.reason, pending_cleanup.identity)
        if not ok then report_error("on_invalidate", why); return false end
        pending_cleanup = nil
        return true
    end
    function self:invalidate(reason)
        local previous = state.identity or state.last_identity
        state.ready, state.connected, state.identity = false, false, nil
        state.attempts, state.next_attempt = 0, nil
        state.generation = state.generation + 1
        state.reason = tostring(reason or "invalidated")
        pending_cleanup = {reason=state.reason, identity=previous}
        return cleanup()
    end
    function self:status()
        local result = {}
        for key, value in pairs(state) do result[key] = value end
        result.cleanup_pending = pending_cleanup ~= nil
        return result
    end
    local function call(name, ...)
        stage = name
        return policy[name](...)
    end
    local function retry(now, why)
        local delay = call("retry_delay", state.attempts, why)
        assert(integer(delay), "retry delay must be a nonnegative integer")
        local deadline = now + delay
        assert(integer(deadline) and deadline >= now and deadline - now == delay, "retry deadline overflow")
        state.next_attempt, state.reason = deadline, tostring(why or "hello pending")
        return false, state.reason
    end
    local function step(now, force)
        stage = "clock"
        assert(integer(now), "hello clock must be a nonnegative integer")
        if state.last_now and now < state.last_now then
            if policy.clock_rewind == "keep" then
                state.next_attempt = nil -- a deadline on the abandoned timeline means nothing
            elseif not self:invalidate("clock_rewound") then
                return false, "invalidation cleanup failed"
            end
        end
        state.last_now = now
        if not cleanup() then return false, "invalidation cleanup failed" end
        if call("connected") ~= true then self:invalidate("disconnected"); return false, "disconnected" end
        state.connected = true
        local identity, identity_reason = call("identity")
        if not identity_key(identity) then
            self:invalidate("identity_unavailable")
            return false, identity_reason or "identity unavailable"
        end
        local previous_identity = state.identity or state.last_identity
        if previous_identity ~= nil and identity ~= previous_identity then
            if not self:invalidate("identity_changed") then return false, "invalidation cleanup failed" end
            state.connected = true
        end
        state.identity, state.last_identity = identity, identity
        if not force then
            if state.ready then return true end
            if state.next_attempt and now < state.next_attempt then return false, state.reason end
            local ready, why = call("ready", identity)
            if ready ~= true then return retry(now, why or "not ready for hello") end
        end
        local generation = state.generation
        state.attempts = state.attempts + 1
        local sent, send_reason = call("send", identity)
        if call("connected") ~= true then self:invalidate("disconnected"); return false, "disconnected during hello" end
        if call("identity") ~= identity then self:invalidate("identity_changed"); return false, "identity changed during hello" end
        if state.generation ~= generation then return false, "hello invalidated during send" end
        if sent ~= true then return retry(now, send_reason or "hello was not queued") end
        state.ready, state.next_attempt, state.reason = true, nil, nil
        return true
    end
    local function run(now, force)
        local ok, ready, why = pcall(step, now, force)
        if not ok then
            local failed_stage = stage or "step"
            if policy.callback_error == "raise" then
                state.last_error = failed_stage .. ": " .. tostring(ready)
                error(ready, 0)
            end
            self:invalidate("callback_error")
            report_error(failed_stage, ready)
            -- A throwing callback is paced like a refusal: the injected delay still applies,
            -- unless the clock or the delay policy itself is what failed.
            if failed_stage ~= "clock" and failed_stage ~= "retry_delay" then
                local scheduled, why = pcall(retry, now, state.last_error)
                if not scheduled then report_error("retry_delay", why) end
            end
            return false, state.last_error
        end
        return ready, why
    end
    function self:step(now) return run(now, false) end
    -- An explicit request (e.g. a harness) to hello now: skips the ready gate, the retry
    -- pacing and an existing readiness; still checks connection and identity around send.
    function self:send_now(now) return run(now, true) end
    return self
end

return HelloSession
