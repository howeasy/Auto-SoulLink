-- Read-only GB mechanics. Domains, anchors, PC, stack and game predicate are inputs.
local M = {}
local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end
local function sequence(value, name)
    assert(type(value) == "table" and getmetatable(value) == nil, name .. " needs a plain array")
    local count, last = 0, 0
    for key in next, value do
        assert(integer(key, 1, 65536), name .. " has an invalid index")
        count, last = count + 1, math.max(last, key)
    end
    assert(count > 0 and count == last, name .. " is empty or sparse")
    return count
end
function M.check(spec, io, predicate)
    local ok, accepted, reason = pcall(function()
        assert(type(spec) == "table" and type(io) == "table", "checkpoint spec and io required")
        assert(type(predicate) == "function", "game state/ownership predicate required")
        assert(type(spec.domains) == "table" and next(spec.domains), "explicit domain bounds required")
        local available = {}
        for _, name in pairs(io.domains()) do available[name] = true end
        for name, bounds in pairs(spec.domains) do
            assert(type(name) == "string" and available[name], "required checkpoint domain unavailable")
            assert(type(bounds) == "table" and integer(bounds.first, 0, 0xFFFFFFFF)
                and integer(bounds.limit, 1, 0x100000000) and bounds.first < bounds.limit,
                "invalid checkpoint domain bounds")
        end
        local function byte(address, domain)
            local bounds = spec.domains[domain]
            assert(bounds and integer(address, bounds.first, bounds.limit - 1), "invalid checkpoint address")
            local value = io.read_u8(address, domain)
            assert(integer(value, 0, 255), "unavailable checkpoint byte")
            return value
        end
        local function register(name)
            assert(type(name) == "string" and name ~= "", "register name required")
            local value = io.register(name)
            assert(integer(value, 0, 65535), "unavailable checkpoint register")
            return value
        end
        sequence(spec.anchors, "anchors")
        for _, anchor in ipairs(spec.anchors) do
            local hex = anchor.expected_hex
            assert(type(hex) == "string" and #hex > 0 and #hex % 2 == 0
                and hex:match("^[%da-fA-F]+$"), "invalid checkpoint anchor bytes")
            local bounds = spec.domains[anchor.domain]
            assert(bounds and integer(anchor.address, bounds.first, bounds.limit - #hex / 2),
                "anchor outside declared domain")
            for offset = 0, #hex / 2 - 1 do
                if byte(anchor.address + offset, anchor.domain) ~= tonumber(hex:sub(offset * 2 + 1, offset * 2 + 2), 16) then
                    return false, "cartridge checkpoint instructions differ"
                end
            end
        end
        assert(integer(spec.pc, 0, 65535), "expected PC required")
        local stack = assert(spec.stack, "bounded caller stack required")
        assert(integer(stack.minimum_sp, 0, 65535) and integer(stack.exclusive_end, 1, 65536)
            and stack.minimum_sp < stack.exclusive_end and integer(stack.read_bytes, 2, 65536),
            "invalid caller stack bounds")
        local bounds = spec.domains[stack.domain]
        assert(bounds and stack.minimum_sp >= bounds.first and stack.exclusive_end <= bounds.limit,
            "caller stack outside declared domain")
        sequence(stack.words, "stack words")
        local offsets = {}
        for _, word in ipairs(stack.words) do
            assert(integer(word.offset, 0, stack.read_bytes - 2) and word.offset % 2 == 0
                and not offsets[word.offset], "invalid or duplicate stack word offset")
            offsets[word.offset] = true
            sequence(word.values, "caller/resume values")
            for _, value in ipairs(word.values) do
                assert(integer(value, 0, 65535), "invalid caller/resume value")
            end
        end
        local pc, sp = register("PC"), register("SP")
        if pc ~= spec.pc or sp < stack.minimum_sp or sp + stack.read_bytes > stack.exclusive_end then
            return false, "CPU is outside the verified checkpoint"
        end
        -- Read only declared little-endian words; never search for a return address.
        for _, word in ipairs(stack.words) do
            local address = sp + word.offset
            local value = byte(address, stack.domain) + 256 * byte(address + 1, stack.domain)
            local matches = false
            for _, expected in ipairs(word.values) do if value == expected then matches = true end end
            if not matches then return false, "main-thread caller or resume differs" end
        end
        local valid, why = predicate(byte, register)
        if valid ~= true then return false, why or "game state/ownership predicate refused" end
        return true, "checkpoint anchors and CPU match"
    end)
    if not ok then return false, "checkpoint evidence unavailable: " .. tostring(accepted) end
    return accepted, reason
end
return M
