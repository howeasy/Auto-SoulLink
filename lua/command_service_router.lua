-- Route one durable command to exactly one generation-supplied service.
-- This does not select frame ownership; the outer owner gates when commands run.
local M={}
function M.new(services)
    assert(type(services)=="table" and #services>0,"command services required")
    for _,service in ipairs(services)do
        assert(type(service.handles)=="function" and type(service.ready)=="function"
            and type(service.adapter)=="table" and type(service.operations)=="table","complete command service required")
    end
    local route=nil
    local function select(body)
        local selected
        for _,service in ipairs(services)do
            if service.handles(body)then
                assert(selected==nil,"multiple services claim the same command")
                selected=service
            end
        end
        return selected
    end
    local self={adapter={},operations={}}
    for _,name in ipairs({"prepare","classify","apply","receipt"})do
        self.adapter[name]=function(body,...)
            local service=assert(select(body),"command has no selected service")
            return service.adapter[name](body,...)
        end
    end
    self.ready=function(body,...)
        local service=select(body)
        if not service then return false,"command has no selected service"end
        return service.ready(body,...)
    end
    self.operations.request=function(binding,control)
        assert(route==nil,"command authority request is already in flight")
        -- Discovery can precede commands (for example the native receptionist).
        for _,service in ipairs(services)do
            if service.update_control then service.update_control(binding,control)end
        end
        for _,service in ipairs(services)do
            local packet=service.operations.request(binding,control)
            if packet then route=service;return packet end
        end
    end
    self.operations.accept=function(packet,...)
        local selected=route;route=nil
        if selected then return selected.operations.accept(packet,...)end
        assert(packet==nil,"unsolicited command service authority")
        return true
    end
    self.operations.authorize_apply=function(body,...)
        local service=select(body)
        if not service then return false,"command has no selected service"end
        return service.operations.authorize_apply(body,...)
    end
    self.operations.revoke=function(reason)
        route=nil
        local first
        for _,service in ipairs(services)do
            local ok,why=pcall(service.operations.revoke,reason)
            if not ok and first==nil then first=why end
        end
        if first~=nil then error(first,0)end
    end
    self.operations.status=function()
        local result={}
        for index,service in ipairs(services)do result[index]=service.operations.status()end
        return result
    end
    return self
end
return M
