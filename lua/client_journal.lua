-- Durable observation outbox and command inbox, independent of cartridge layout.
-- Executor/coordinator callbacks must prove effects; this module never invents ACKs.
local JSON=require("json_codec")
local Identity=require("platform_identity")
local M={VERSION="slink-client-journal-v1",MAX_EVENTS=128,MAX_COMMANDS=256}
local transport={protocol=true,player=true,admission_epoch=true,session_id=true,seq=true,operation_id=true}
local function token(value)return type(value)=="string" and #value==32 and value:match("^[0-9a-f]+$")~=nil end
local function integer(value)return type(value)=="number" and value%1==0 and value>=0 and value<=9007199254740991 end
local function encoded(value)return assert(JSON.encode(value))end
local function copy(value)return assert(JSON.decode(encoded(value)))end

function M.initial()
    return {version=M.VERSION,outbox=JSON.array(),inbox=JSON.array(),command_floor=0,observation=JSON.object()}
end

local function validate(state)
    if type(state)~="table" or state.version~=M.VERSION or not integer(state.command_floor)
        or JSON.kind(state.outbox)~="array" or #state.outbox>M.MAX_EVENTS
        or JSON.kind(state.inbox)~="array" or #state.inbox>M.MAX_COMMANDS
        or JSON.kind(state.observation)~="object" then error("invalid client journal",0) end
    local event_ids,command_ids={},{}
    for _,entry in ipairs(state.outbox) do
        if not token(entry.operation_id) or JSON.kind(entry.payload)~="object" or event_ids[entry.operation_id] then
            error("invalid or duplicate outbox operation",0)
        end
        event_ids[entry.operation_id]=true
        if type(entry.payload.event)~="string" or entry.payload.event=="hello" then error("invalid journal event",0) end
        for key in pairs(transport) do if entry.payload[key]~=nil then error("delivery envelope in durable event",0) end end
    end
    local previous=state.command_floor
    for _,entry in ipairs(state.inbox) do
        if not token(entry.command_id) or command_ids[entry.command_id] or not integer(entry.command_sequence)
            or entry.command_sequence<=previous or JSON.kind(entry.body)~="object" or type(entry.body.cmd)~="string" then
            error("invalid or unordered command inbox",0)
        end
        if entry.outcome~=nil and entry.outcome~="ACK" and entry.outcome~="NACK" then error("invalid command outcome",0) end
        if entry.outcome and JSON.kind(entry.receipt)~="object" then error("command outcome needs a receipt",0) end
        if entry.confirmed and not entry.outcome then error("unapplied command cannot be confirmed",0) end
        command_ids[entry.command_id]=true;previous=entry.command_sequence
    end
end

function M.open(store,new_id)
    local initial,reason=store:read()
    if not initial then return nil,reason end
    local ok,validation_error=pcall(validate,initial)
    if not ok then return nil,tostring(validation_error) end
    local self={store=store,new_id=new_id or Identity.new_nonce}
    local function mutate(fn)
        local state,reason=store:read()
        if not state then return false,reason end
        local ok,result=pcall(function()
            validate(state)
            local before=encoded(state)
            local result=fn(state)
            validate(state)
            if encoded(state)==before then return result end
            local saved,why=store:commit(state)
            if not saved then error(why,0) end
            return result
        end)
        if not ok then return false,tostring(result) end
        return true,result
    end
    function self:pending_events()
        local state,reason=store:read()
        if not state then return nil,reason end
        return state.outbox
    end
    function self:pending_commands()
        local state,reason=store:read()
        if not state then return nil,reason end
        local commands=JSON.array()
        for _,entry in ipairs(state.inbox) do if not entry.outcome then commands[#commands+1]=entry end end
        return commands
    end
    function self:append(payload,observation)
        local id,reason=self.new_id()
        if not token(id) then return nil,reason or "operation identifier unavailable" end
        local ok,result=mutate(function(state)
            if #state.outbox>=M.MAX_EVENTS then error("durable event outbox is full",0) end
            state.outbox[#state.outbox+1]={operation_id=id,payload=copy(payload)}
            if observation then state.observation=copy(observation) end
            return id
        end)
        if not ok then return nil,result end
        return result
    end
    function self:accept_response(operation_id,commands)
        return mutate(function(state)
            if not state.outbox[1] or state.outbox[1].operation_id~=operation_id then
                error("response does not acknowledge the oldest durable event",0)
            end
            if JSON.kind(commands)~="array" then error("command array required",0) end
            local by_id={}
            for _,entry in ipairs(state.inbox) do by_id[entry.command_id]=entry end
            for _,command in ipairs(commands) do
                if not token(command.command_id) or not integer(command.command_sequence) then error("invalid command identity",0) end
                local existing=by_id[command.command_id]
                if existing then
                    if existing.command_sequence~=command.command_sequence or encoded(existing.body)~=encoded(command.body) then
                        error("conflicting replay of a durable command",0)
                    end
                else
                    local last=state.inbox[#state.inbox]
                    if command.command_sequence<=(last and last.command_sequence or state.command_floor) then
                        error("stale or unordered durable command",0)
                    end
                    if #state.inbox>=M.MAX_COMMANDS then error("durable command inbox is full",0) end
                    local entry={command_id=command.command_id,command_sequence=command.command_sequence,body=copy(command.body)}
                    state.inbox[#state.inbox+1]=entry;by_id[entry.command_id]=entry
                end
            end
            local event=table.remove(state.outbox,1).payload
            if event.event=="command_ack" then
                local entry=by_id[event.command_id]
                if not entry or entry.outcome~=event.outcome or encoded(entry.receipt)~=encoded(event.receipt) then
                    error("command receipt differs from its durable inbox record",0)
                end
                entry.confirmed=true
                while state.inbox[1] and state.inbox[1].confirmed do
                    state.command_floor=table.remove(state.inbox,1).command_sequence
                end
            end
            return true
        end)
    end
    function self:complete_command(command_id,outcome,receipt)
        local id,reason=self.new_id()
        if not token(id) then return false,reason or "receipt identifier unavailable" end
        return mutate(function(state)
            local entry
            for _,candidate in ipairs(state.inbox) do if candidate.command_id==command_id then entry=candidate end end
            if not entry then error("unknown durable command",0) end
            if outcome~="ACK" and outcome~="NACK" then error("explicit command outcome required",0) end
            local proof=copy(receipt)
            if JSON.kind(proof)~="object" or next(proof)==nil then error("verified receipt required",0) end
            if entry.outcome then
                if entry.outcome~=outcome or encoded(entry.receipt)~=encoded(proof) then error("conflicting physical receipt",0) end
                return true
            end
            if #state.outbox>=M.MAX_EVENTS then error("durable event outbox is full",0) end
            entry.outcome=outcome;entry.receipt=proof
            state.outbox[#state.outbox+1]={operation_id=id,payload=JSON.object({event="command_ack",command_id=command_id,
                command_sequence=entry.command_sequence,outcome=outcome,receipt=proof})}
            return true
        end)
    end
    return self
end
return M
