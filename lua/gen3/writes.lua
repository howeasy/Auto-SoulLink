-- Sole Gen 3 write sink. Mirrors gen1/writes.lua:54-86: arm, interval validation,
-- validate all bytes before mutation, provenance. Safety policy is injected, never bypassed.
local W = {}
local reasons = {overworld = true, battle_faint = true, battle_commit = true,
    native = true, memorial_rename = true}
local function uint(v, max)
    assert(type(v) == "number" and v % 1 == 0 and v >= 0 and v <= max, "invalid unsigned integer")
    return v
end
function W.new(deps)
    local safety = assert(deps.safety, "safety policy required")
    local window
    local self = {log = {}}
    function self:disarm() window = nil end
    function self:arm(reason, allow)
        window = nil
        assert(reasons[reason], "unknown arm reason")
        assert(type(allow) == "function", "explicit range allow predicate required")
        local frame = uint(deps.frame(), 9007199254740991)
        local snapshot, err = safety:snapshot()
        assert(snapshot, err)
        local ok, why = safety:check(snapshot, reason)
        assert(ok == true, why)
        window = {reason = reason, allow = allow, frame = frame, snapshot = snapshot}
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
        local ok, why = safety:check(window.snapshot, window.reason)
        assert(ok == true, why)
        -- No reads/callbacks between final revalidation and the first write.
        for i = 1, n do deps.io.write_u8(addr + i - 1, copy[i], "System Bus") end
        local record = {reason = window.reason, address = addr, len = n, frame = window.frame,
            why = window.reason, addr = addr, n = n}
        self.log[#self.log + 1] = record
        if deps.log then deps.log(record) end
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
