-- Sole Gen 3 write sink. Mirrors gen1/writes.lua:54-86: arm, interval validation,
-- validate all bytes before mutation, provenance. Safety policy is injected, never bypassed.
local W = {}
local reasons = {overworld = true, battle_faint = true, battle_commit = true,
    native = true, memorial_rename = true, sound = true}
local function uint(v, max)
    assert(type(v) == "number" and v % 1 == 0 and v >= 0 and v <= max, "invalid unsigned integer")
    return v
end
function W.new(deps)
    local safety = assert(deps.safety, "safety policy required")
    local window
    -- `attempted` counts every byte handed to the sink, incremented BEFORE the external write:
    -- a sink that throws on byte k leaves attempted >= k, so a caller can tell "nothing was
    -- written" (unchanged) from "RAM may have changed" (moved) even when no log receipt exists.
    local self = {log = {}, attempted = 0}
    function self:disarm() window = nil end
    function self:arm(reason, allow, args)
        window = nil
        assert(reasons[reason], "unknown arm reason")
        assert(type(allow) == "function", "explicit range allow predicate required")
        local frame = uint(deps.frame(), 9007199254740991)
        local snapshot, err = safety:snapshot()
        assert(snapshot, err)
        local ok, why = safety:check(snapshot, reason, args)
        assert(ok == true, why)
        window = {reason = reason, allow = allow, frame = frame, snapshot = snapshot, args = args}
    end
    function self:write_bytes(addr, bytes)
        assert(window, "write refused: no armed write window")
        uint(addr, 4294967295)
        assert(type(bytes) == "table", "byte table required")
        local n = 0
        for k in pairs(bytes) do uint(k, 4294967295); assert(k > 0, "invalid byte index"); n = math.max(n, k) end
        assert(n > 0 and addr + n - 1 <= 4294967295, "invalid write interval")
        local copy = {}
        for i = 1, n do copy[i] = uint(bytes[i], 255) end
        assert(deps.frame() == window.frame, "write window expired")
        assert(window.allow(addr, n) == true, "write outside allow range")
        local ok, why = safety:check(window.snapshot, window.reason, window.args)
        assert(ok == true, why)
        -- No reads/callbacks between final revalidation and the first write.
        for i = 1, n do
            self.attempted = self.attempted + 1
            deps.io.write_u8(addr + i - 1, copy[i], "System Bus")
        end
        local record = {reason = window.reason, address = addr, len = n, frame = window.frame,
            why = window.reason, addr = addr, n = n}
        self.log[#self.log + 1] = record
        if deps.log then deps.log(record) end
    end
    -- G4-PH (docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md §3.3): a whole plan,
    -- {{addr, width, value}, ...}, validated ONCE. A plan ending in the controller hand-off has
    -- two self-invalidating writes (comm = 3, then the slot), so write_bytes' per-write
    -- revalidation would refuse the last after the rest landed. Same invariant as write_bytes:
    -- every entry is checked (shape, allow) and the policy re-run immediately before the first
    -- byte, then no reads/callbacks until the last byte. Only the plan the window was armed with
    -- (args.plan, which the policy judged) may be written this way.
    function self:write_plan(plan)
        assert(window, "write refused: no armed write window")
        assert(type(plan) == "table" and #plan > 0, "plan required")
        assert(window.args and window.args.plan == plan, "write_plan: not the armed plan")
        local jobs = {}
        for i, w in ipairs(plan) do
            local addr, width, value = uint(w[1], 4294967295), w[2], w[3]
            assert(width == 1 or width == 2 or width == 4, "invalid plan width")
            uint(value, 256 ^ width - 1)
            assert(addr + width - 1 <= 4294967295, "invalid write interval")
            assert(window.allow(addr, width) == true, "write outside allow range")
            local bytes = {}
            for k = 1, width do bytes[k] = value % 256; value = math.floor(value / 256) end
            jobs[i] = {addr = addr, bytes = bytes}
        end
        assert(deps.frame() == window.frame, "write window expired")
        local ok, why = safety:check(window.snapshot, window.reason, window.args)
        assert(ok == true, why)
        for _, job in ipairs(jobs) do
            for k, byte in ipairs(job.bytes) do
                self.attempted = self.attempted + 1
                deps.io.write_u8(job.addr + k - 1, byte, "System Bus")
            end
        end
        for _, job in ipairs(jobs) do
            local n = #job.bytes
            local record = {reason = window.reason, address = job.addr, len = n, frame = window.frame,
                why = window.reason, addr = job.addr, n = n}
            self.log[#self.log + 1] = record
            if deps.log then deps.log(record) end
        end
    end
    function self:write_u16(addr, value)
        uint(value, 65535)
        self:write_bytes(addr, {value % 256, math.floor(value / 256)})
    end
    function self:write_u32(addr, value)
        uint(value, 4294967295)
        local bytes = {}
        for i = 1, 4 do bytes[i] = value % 256; value = math.floor(value / 256) end
        self:write_bytes(addr, bytes)
    end
    return self
end
return W
