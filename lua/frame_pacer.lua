-- Monotonic cartridge-rate scheduling. No frame calls or execution permission.
local M={}
function M.new(options)
    assert(type(options)=="table"and type(options.clock)=="function","monotonic frame clock required")
    local numerator,denominator=options.numerator,options.denominator
    for _,value in ipairs({numerator,denominator})do
        assert(type(value)=="number"and value%1==0 and value>=1 and value<=1000000000,"bounded frame-rate ratio required")
    end
    assert(numerator and denominator and numerator/denominator>=1 and numerator/denominator<=1000,"unsupported frame rate")
    local period=denominator/numerator
    local previous,next_frame,failed,scheduled=nil,nil,nil,0
    local self={}
    function self:take(permitted,user_paused)
        if failed then return false,failed end
        local ok,result=pcall(function()
            assert(type(permitted)=="boolean"and type(user_paused)=="boolean","explicit authority and user pause required")
            local now=options.clock()
            assert(type(now)=="number"and now==now and now>=0 and now<math.huge
                and (previous==nil or now>=previous),"monotonic frame clock failed")
            previous=now
            if not permitted or user_paused then next_frame=nil;return false end
            if next_frame and now<next_frame then return false end
            if not next_frame or now-next_frame>=period then next_frame=now+period
            else next_frame=next_frame+period end
            scheduled=scheduled+1;return true
        end)
        if not ok then failed=tostring(result);next_frame=nil;return false,failed end
        return result
    end
    function self:status()
        return {period=period,scheduled=scheduled,failed=failed,ordinary_execution=false}
    end
    return self
end
return M
