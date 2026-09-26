-- Neutral bounded byte-token scanning. Glyphs, terminator, bound and unknown
-- handling belong to the caller. No game data, IO, globals or Python oracle.
local Scanner = {}

local function integer(value, minimum, maximum)
    return type(value) == "number" and value >= minimum and value <= maximum
        and value < math.huge and value % 1 == 0
end

function Scanner.new(policy)
    assert(type(policy) == "table" and getmetatable(policy) == nil,
        "token scanner requires an explicit plain policy table")
    assert(type(policy.glyphs) == "table" and getmetatable(policy.glyphs) == nil,
        "token scanner requires a plain glyph table")
    assert(integer(policy.terminator, 0, 255), "token scanner requires a byte terminator")
    assert(integer(policy.max_length, 0, math.huge),
        "token scanner requires a finite nonnegative integer max_length")
    assert(type(policy.unknown) == "function", "token scanner requires unknown-token handling")

    -- Bind a stable policy: a callback cannot change the interpretation of the
    -- remaining tokens by mutating the caller's table during a scan.
    local glyphs = {}
    for byte, glyph in next, policy.glyphs do
        assert(integer(byte, 0, 255) and type(glyph) == "string",
            "token scanner glyphs must map byte keys to strings")
        glyphs[byte] = glyph
    end
    local terminator, maximum, unknown = policy.terminator, policy.max_length, policy.unknown

    return function(bytes)
        if type(bytes) ~= "table" or getmetatable(bytes) ~= nil then
            return nil, "byte stream must be a plain dense array"
        end
        -- Lua's #/ipairs alone cannot detect holes or extra dictionary keys.
        -- Validate the entire supplied field, including bytes after a terminator,
        -- before calling any policy callback or returning a display prefix.
        local snapshot, count, last = {}, 0, 0
        for index, value in next, bytes do
            if not integer(index, 1, math.huge) then
                return nil, "byte stream has an invalid index"
            end
            if index > maximum then return nil, "byte stream exceeds maximum length" end
            if not integer(value, 0, 255) then return nil, "byte stream contains a non-byte value" end
            count = count + 1
            last = math.max(last, index)
            snapshot[index] = value
        end
        if count ~= last then return nil, "byte stream is sparse" end

        local output = {}
        for index = 1, count do
            local byte = snapshot[index]
            if byte == terminator then break end
            local token = glyphs[byte]
            if token == nil then
                local ok, value, why = pcall(unknown, byte, index)
                if not ok then return nil, "unknown-token handler failed" end
                if type(value) ~= "string" then
                    return nil, type(why) == "string" and why or "unknown-token handler refused token"
                end
                token = value
            end
            output[#output + 1] = token
        end
        return table.concat(output)
    end
end

return Scanner
