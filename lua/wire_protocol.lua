-- Shared response decoding. Game adapters validate command meaning and write payloads.
local JSON=require("json_codec")
local M={}

function M.validate_response(packet)
    if JSON.kind(packet)~="object" then return {},"response must be an object" end
    local commands=packet.commands
    if commands==nil then return {} end
    if JSON.kind(commands)~="array" then return {},"commands must be an array" end
    local count=0
    for index in pairs(commands) do
        if type(index)~="number" or index%1~=0 or index<1 or index>#commands then
            return {},"commands must be a contiguous array"
        end
        count=count+1
    end
    if count~=#commands then return {},"missing command array entry" end
    for _,command in ipairs(commands) do
        if JSON.kind(command)~="object" or type(command.cmd)~="string" then
            return {},"each command must name its operation"
        end
        -- Optional top-level nulls mean absent. Nested nulls remain explicit so
        -- a malformed stat/blob list cannot be silently shortened by a parser.
        for key,value in pairs(command) do
            if value==JSON.null then command[key]=nil end
        end
    end
    return commands
end

function M.parse_commands(raw)
    local packet,error=JSON.decode(raw)
    if error then return {},error end
    local commands,reason=M.validate_response(packet)
    return commands,reason,packet
end
return M
