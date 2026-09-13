-- Owner-keyed composition over one exclusive execution actuator.  Releasing an
-- owner's request can never clear another owner's hold; every aggregate result
-- is verified by the underlying host adapter.
local M={}

local function valid_name(value)
    return type(value)=="string" and #value>=1 and #value<=64
        and value:match("^[a-z][a-z0-9_.%-]*$")~=nil
end
local function valid_reason(value)
    return type(value)=="string" and #value>=1 and #value<=256 and not value:find("[%c]")
end
local function clone(source)
    local result={};for key,value in pairs(source)do result[key]=value end;return result
end

function M.new(options)
    assert(type(options)=="table" and type(options.host)=="table"
        and type(options.host.set_held)=="function","execution hold host required")
    assert(type(options.owners)=="table","explicit hold owners required")
    local allowed={}
    for _,owner in ipairs(options.owners)do
        assert(valid_name(owner) and not allowed[owner],"unique explicit hold owner required")
        allowed[owner]=true
    end
    assert(next(allowed)~=nil,"at least one hold owner required")
    local held,reasons={},{}
    local applied=nil
    local self={}
    local function aggregate()
        return next(held)~=nil
    end
    local function aggregate_reason(fallback)
        local owners={};for owner in pairs(held)do owners[#owners+1]=owner end
        table.sort(owners)
        if #owners==0 then return fallback end
        local owner=owners[1]
        return (owner..": "..reasons[owner]):sub(1,256)
    end
    function self:set(owner,value,why)
        assert(allowed[owner],"unknown execution hold owner")
        assert(type(value)=="boolean" and valid_reason(why),"boolean hold and explicit reason required")
        local before_held,before_reason=held[owner],reasons[owner]
        local before_aggregate=aggregate()
        if value then held[owner]=true;reasons[owner]=why else held[owner]=nil;reasons[owner]=nil end
        local after_aggregate=aggregate()
        if applied~=nil and before_aggregate==after_aggregate and applied==after_aggregate then return true end
        local called,accepted,problem=pcall(options.host.set_held,after_aggregate,aggregate_reason(why))
        if not called or accepted~=true then
            held[owner],reasons[owner]=before_held,before_reason
            return false,(not called and accepted) or problem or "aggregate execution hold was not verified"
        end
        applied=after_aggregate
        return true
    end
    function self:verify()
        assert(type(options.host.verify)=="function","execution hold verification unavailable")
        local ok,accepted,problem=pcall(options.host.verify)
        if not ok or accepted~=true then return false,(not ok and accepted)or problem or"aggregate execution hold was not verified"end
        return true
    end
    function self:is_held()return aggregate()end
    function self:held(owner)
        assert(allowed[owner],"unknown execution hold owner")
        return held[owner]==true
    end
    function self:adapter(owner)
        assert(allowed[owner],"unknown execution hold owner")
        -- status/yield_held read the underlying actuator when it offers them, so an owner adapter
        -- can stand in for the host of a layered owner (platform_bounded_execution). `held`
        -- reports THIS owner's vote; the physical stop is the actuator's verified readback.
        return {set_held=function(value,why)return self:set(owner,value,why)end,
            verify=function()return self:verify()end,
            status=function()
                local actual=type(options.host.status)=="function" and options.host.status() or {}
                local result={};for key,value in pairs(actual)do result[key]=value end
                result.held=held[owner]==true;result.owner=owner;result.aggregate_held=aggregate()
                return result
            end,
            yield_held=function()
                if not held[owner] then return false,"owner must hold execution before a held yield" end
                assert(type(options.host.yield_held)=="function","held yield unavailable on this actuator")
                return options.host.yield_held()
            end}
    end
    function self:construct_and_release(owner,why,current,build)
        assert(allowed[owner] and held[owner],"construction owner must hold execution")
        assert(valid_reason(why) and type(current)=="function" and type(build)=="function",
            "explicit construction lease and builder required")
        assert(current()==true,"current service lease required before construction")
        local value=build()
        assert(held[owner] and aggregate(),"construction released its execution hold")
        assert(current()==true,"service lease changed during construction")
        assert(self:set(owner,false,why))
        return value
    end
    function self:status()
        return {held=aggregate(),owners=clone(held),reasons=clone(reasons)}
    end
    return self
end

return M
