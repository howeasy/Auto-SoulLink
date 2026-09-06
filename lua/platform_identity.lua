-- OS-backed identifiers shared by the BizHawk clients.
local M = {}
local function token(value)
    return type(value)=="string" and #value==32 and value:match("^[0-9a-f]+$")~=nil
end
function M.new_nonce()
    -- BizHawk hosts .NET. Guid.NewGuid uses the operating system's random source;
    -- clocks, frame counters and math.random are not session identity evidence.
    local ok,value=pcall(function()
        local Guid=luanet.import_type("System.Guid")
        return tostring(Guid.NewGuid():ToString("N")):lower()
    end)
    if not ok or not token(value) then return nil,"secure session nonce API unavailable" end
    return value
end


return M
