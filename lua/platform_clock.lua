-- Monotonic wall time from the pinned BizHawk .NET host, independent of frames.
local M={}
function M.new()
    local ok,watch=pcall(function()
        luanet.load_assembly("System")
        return luanet.import_type("System.Diagnostics.Stopwatch").StartNew()
    end)
    if not ok or not watch then return nil,"monotonic host clock unavailable" end
    local previous=0
    return function()
        local seconds=tonumber(watch.Elapsed.TotalSeconds)
        assert(seconds and seconds==seconds and seconds>=previous and seconds<math.huge,
            "monotonic host clock failed")
        previous=seconds
        return seconds
    end
end
return M
