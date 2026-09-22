-- Neutral reply pump. Pulls at most `budget` lines per step from an injected
-- source; each line is decoded and validated as a WHOLE before any handler runs,
-- then every command is handled in order, each isolated from the others.
-- Transport, codec, envelope shape, handlers, error reporting and the budget are
-- all injected policy. Lines past the budget are never pulled, so they stay in
-- the source in order.
local ReplyDispatch = {}

local function dense(list)
    if type(list) ~= "table" then return nil end
    local count, last = 0, 0
    for key in pairs(list) do
        if math.type(key) ~= "integer" or key < 1 then return nil end
        count, last = count + 1, math.max(last, key)
    end
    return count == last and count or nil
end

function ReplyDispatch.new(policy)
    assert(type(policy) == "table", "reply dispatch policy required")
    for _, name in ipairs({"receive", "decode", "validate", "handle", "on_error"}) do
        assert(type(policy[name]) == "function", "reply policy." .. name .. " required")
    end
    local budget = policy.budget
    assert(budget == math.huge or (math.type(budget) == "integer" and budget >= 1),
           "reply policy.budget must be a positive integer or math.huge")
    local busy = false
    local self = {}

    local function report(stage, why, subject)
        pcall(policy.on_error, stage, tostring(why), subject)
    end
    local function dispatch(line)
        local ok, envelope = pcall(policy.decode, line)
        if not ok then return report("decode", envelope, line) end
        local valid, commands, why = pcall(policy.validate, envelope)
        if not valid then return report("validate", commands, line) end
        local n = dense(commands)
        if not n then return report("validate", why or "command list is not a dense sequence", line) end
        for i = 1, n do
            local handled, err = pcall(policy.handle, commands[i], i, envelope)
            if not handled then report("handle", err, commands[i]) end
        end
    end

    -- Returns lines consumed and whether the budget stopped the pump early.
    -- receive() errors are the transport's and propagate unchanged.
    function self:step()
        assert(not busy, "reentrant reply pump")
        busy = true
        local ok, consumed, more = pcall(function()
            local count = 0
            while count < budget do
                local line = policy.receive()
                if line == nil then return count, false end
                count = count + 1
                dispatch(line)
            end
            return count, true
        end)
        busy = false
        if not ok then error(consumed, 0) end
        return consumed, more
    end
    return self
end

return ReplyDispatch
