-- Durable observation outbox and command inbox, independent of cartridge layout.
-- Executor/coordinator callbacks must prove effects; this module never invents ACKs.
local JSON=require("json_codec")
local Identity=require("platform_identity")
local M={VERSION="slink-client-journal-v1",COMPOSED_VERSION="slink-client-journal-v2",
    HUD_VERSION="slink-client-journal-v3",HUD_STATE="slink-gen1-hud-client-state-v1",
    MAX_EVENTS=128,MAX_COMMANDS=256}
local transport={protocol=true,player=true,admission_epoch=true,session_id=true,seq=true,operation_id=true}
local function token(value)return type(value)=="string" and #value==32 and value:match("^[0-9a-f]+$")~=nil end
local function integer(value)return type(value)=="number" and value%1==0 and value>=0 and value<=9007199254740991 end
local function encoded(value)return assert(JSON.encode(value))end
local function copy(value)return assert(JSON.decode(encoded(value)))end
local function clone_json_validated(value)
    if value==JSON.null or type(value)~="table"then return value end
    local kind=JSON.kind(value)
    local clone=(kind=="array" or kind~="object" and #value>0) and JSON.array() or JSON.object()
    for key,child in pairs(value)do clone[key]=clone_json_validated(child)end
    return clone
end
local function copy_after_json_check(value)
    -- encode() strict-decodes its own wire before returning.  Keep that full
    -- validation but detach the already-proven batch without decoding a
    -- 70-KiB source string for a second time.
    encoded(value)
    return clone_json_validated(value)
end
local function hex(value,size)return type(value)=="string" and #value==size and value:match("^[0-9a-f]+$")~=nil end
local function display_state(value)
    if JSON.kind(value)~="object" or value.schema~=M.HUD_STATE
        or value.mode~="game_over" or value.text~=""
        or not hex(value.command_id,32) or not integer(value.command_sequence) or value.command_sequence<1
        or not hex(value.body_digest,64) or not integer(value.frame) then
        error("invalid versioned client HUD state",0)
    end
    for key in pairs(value)do
        if key~="schema" and key~="mode" and key~="text" and key~="command_id"
            and key~="command_sequence" and key~="body_digest" and key~="frame"then
            error("unknown client HUD state field",0)
        end
    end
end
local function completion(payload,entry)
    assert(JSON.kind(payload)=="object" and type(payload.event)=="string" and #payload.event>=1
        and #payload.event<=64 and payload.event~="hello" and payload.event~="control"
        and payload.event~="sync" and payload.command_id==entry.command_id
        and payload.command_sequence==entry.command_sequence and JSON.kind(payload.receipt)=="object"
        and encoded(payload.receipt)==encoded(entry.receipt),"typed completion must retain exact command and receipt")
    for field in pairs(transport)do assert(payload[field]==nil,"delivery envelope in typed completion")end
    if payload.outcome~=nil then assert(payload.outcome==entry.outcome,"typed completion outcome differs")end
    if payload.event=="command_ack" then assert(payload.outcome==entry.outcome,"generic ACK requires its outcome")end
end

function M.initial()
    return {version=M.VERSION,outbox=JSON.array(),inbox=JSON.array(),command_floor=0,observation=JSON.object()}
end

local function validate(state)
    if type(state)~="table" or (state.version~=M.VERSION and state.version~=M.COMPOSED_VERSION
        and state.version~=M.HUD_VERSION) or not integer(state.command_floor)
        or JSON.kind(state.outbox)~="array" or #state.outbox>M.MAX_EVENTS
        or JSON.kind(state.inbox)~="array" or #state.inbox>M.MAX_COMMANDS
        or JSON.kind(state.observation)~="object" then error("invalid client journal",0) end
    if state.version==M.HUD_VERSION then
        if state.hud_state==nil then error("versioned client HUD state required",0)end
        display_state(state.hud_state)
    elseif state.hud_state~=nil then error("client HUD state requires versioned journal",0)end
    for key in pairs(state)do
        if key~="version"and key~="outbox"and key~="inbox"and key~="command_floor"
            and key~="observation"and key~="hud_state"then error("unknown client journal field",0)end
    end
    local event_ids,command_ids={},{}
    for _,entry in ipairs(state.outbox) do
        if not token(entry.operation_id) or JSON.kind(entry.payload)~="object" or event_ids[entry.operation_id] then
            error("invalid or duplicate outbox operation",0)
        end
        event_ids[entry.operation_id]=true
        if type(entry.payload.event)~="string" or #entry.payload.event<1 or #entry.payload.event>64
            or entry.payload.event=="hello" then error("invalid journal event",0) end
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
        if entry.intent~=nil and (JSON.kind(entry.intent)~="object"
            or type(entry.intent.schema)~="string" or entry.intent.schema=="") then
            error("prepared command needs a versioned intent",0)
        end
        if entry.confirmed~=nil and type(entry.confirmed)~="boolean" then error("invalid receipt confirmation",0) end
        if entry.confirmed and not entry.outcome then error("unapplied command cannot be confirmed",0) end
        if entry.completion_payload~=nil then
            assert((state.version==M.COMPOSED_VERSION or state.version==M.HUD_VERSION)
                and entry.outcome and token(entry.completion_operation_id),
                "typed completion requires composed journal version and exact event identity")
            completion(entry.completion_payload,entry)
        end
        command_ids[entry.command_id]=true;previous=entry.command_sequence
    end
end

function M.open(store,new_id,options)
    options=options or {}
    if type(options)~="table" or (options.completion_event~=nil and type(options.completion_event)~="function")
        or (options.acknowledge_event~=nil and type(options.acknowledge_event)~="function") then
        return nil,"invalid journal composition callbacks"
    end
    local initial,reason=store:read()
    if not initial then return nil,reason end
    local ok,validation_error=pcall(validate,initial)
    if not ok then return nil,tostring(validation_error) end
    local self={store=store,new_id=new_id or Identity.new_nonce}
    local function mutate(fn,definitely_changed)
        local state,reason=store:read()
        if not state then return false,reason end
        local ok,result=pcall(function()
            validate(state)
            local before=not definitely_changed and encoded(state) or nil
            local result=fn(state)
            validate(state)
            -- A nonempty append necessarily adds an outbox entry.  The store
            -- still performs full JSON validation, detached copying and exact
            -- flushed readback; only its redundant no-op comparison is skipped.
            if not definitely_changed and encoded(state)==before then return result end
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
    function self:get_command(command_id)
        local state,reason=store:read()
        if not state then return nil,reason end
        for _,entry in ipairs(state.inbox) do
            if entry.command_id==command_id then return entry end
        end
        return nil,"unknown durable command"
    end
    function self:hud_state()
        local state,reason=store:read()
        if not state then return nil,reason end
        validate(state)
        return state.hud_state and copy(state.hud_state) or nil
    end
    function self:record_hud_state(command_id,proposal)
        return mutate(function(state)
            local value=copy(proposal)
            display_state(value)
            if value.command_id~=command_id then error("HUD state command identity differs",0)end
            local head
            for _,entry in ipairs(state.inbox)do if not entry.outcome then head=entry;break end end
            if not head or head.command_id~=command_id or head.command_sequence~=value.command_sequence
                or head.body.cmd~="hud_state" then error("HUD state requires its pending command head",0)end
            local old=state.hud_state
            if old and old.command_sequence>value.command_sequence then
                error("stale HUD state cannot replace terminal game over",0)
            end
            if old and old.command_sequence==value.command_sequence then
                if encoded(old)~=encoded(value)then error("conflicting HUD state replay",0)end
                return true
            end
            state.hud_state=value;state.version=M.HUD_VERSION
            return true
        end)
    end
    function self:prepare_command(command_id,intent)
        return mutate(function(state)
            local entry
            for _,candidate in ipairs(state.inbox) do if candidate.command_id==command_id then entry=candidate end end
            if not entry then error("unknown durable command",0) end
            local prepared=copy(intent)
            if JSON.kind(prepared)~="object" or type(prepared.schema)~="string" or prepared.schema=="" then
                error("versioned command intent required",0)
            end
            if entry.intent then
                if encoded(entry.intent)~=encoded(prepared) then error("conflicting command preparation",0) end
                return true
            end
            if entry.outcome then error("completed command cannot be prepared",0) end
            entry.intent=prepared
            return true
        end)
    end
    function self:append_many(payloads,observation)
        -- A frame may produce several observations. Publish all their IDs and
        -- the next detector baseline together, so a crash cannot leave a new
        -- baseline hiding an observation that never reached the durable outbox.
        local prepared,proposal=pcall(function()
            local batch=copy_after_json_check(payloads)
            if JSON.kind(batch)~="array" or #batch>M.MAX_EVENTS then
                error("bounded observation array required",0)
            end
            if #batch==0 and observation==nil then
                error("empty observation batch requires an explicit baseline",0)
            end
            local entries,ids=JSON.array(),JSON.array()
            for _,payload in ipairs(batch) do
                local id,reason=self.new_id()
                if not token(id) then error(reason or "operation identifier unavailable",0) end
                entries[#entries+1]={operation_id=id,payload=payload}
                ids[#ids+1]=id
            end
            local preview=M.initial()
            preview.outbox=entries
            if observation~=nil then preview.observation=copy(observation) end
            validate(preview) -- payloads, IDs, duplicates and baseline shape, before publication
            return {entries=entries,ids=ids,baseline=preview.observation}
        end)
        if not prepared then return nil,tostring(proposal) end
        local ok,result=mutate(function(state)
            if #state.outbox+#proposal.entries>M.MAX_EVENTS then error("durable event outbox is full",0) end
            for _,entry in ipairs(proposal.entries) do state.outbox[#state.outbox+1]=entry end
            if observation~=nil then state.observation=proposal.baseline end
            return proposal.ids
        end,#proposal.entries>0)
        if not ok then return nil,result end
        return result
    end
    function self:append(payload,observation)
        -- Keep the single-observation API and its scalar identifier result.
        -- A nil payload must not turn into an empty baseline-only batch.
        if payload==nil then return nil,"observation payload required" end
        local ids,reason=self:append_many(JSON.array({payload}),observation)
        if not ids then return nil,reason end
        return ids[1]
    end
    function self:accept_response(operation_id,commands,semantic_result)
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
            local entry=by_id[event.command_id]
            if event.event=="command_ack" or (entry and entry.completion_operation_id==operation_id) then
                local expected=entry and entry.completion_payload
                if not entry or (expected and encoded(event)~=encoded(expected))
                    or (not expected and (entry.outcome~=event.outcome or encoded(entry.receipt)~=encoded(event.receipt))) then
                    error("command receipt differs from its durable inbox record",0)
                end
                entry.confirmed=true
                while state.inbox[1] and state.inbox[1].confirmed do
                    state.command_floor=table.remove(state.inbox,1).command_sequence
                end
            end
            if options.acknowledge_event then
                local baseline=options.acknowledge_event(copy(event),operation_id,copy(state.observation),
                    semantic_result and copy(semantic_result) or nil)
                if baseline~=nil then
                    assert(JSON.kind(baseline)=="object","acknowledged observation baseline must be an object")
                    if encoded(baseline)~=encoded(state.observation)then
                        if state.version~=M.HUD_VERSION then state.version=M.COMPOSED_VERSION end
                        state.observation=copy(baseline)
                    end
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
            local payload=options.completion_event and options.completion_event(copy(entry),outcome,copy(proof))
            if payload~=nil then
                payload=copy(payload);completion(payload,entry)
                entry.completion_payload=copy(payload);entry.completion_operation_id=id
                if state.version~=M.HUD_VERSION then state.version=M.COMPOSED_VERSION end
            else
                payload=JSON.object({event="command_ack",command_id=command_id,
                    command_sequence=entry.command_sequence,outcome=outcome,receipt=proof})
            end
            state.outbox[#state.outbox+1]={operation_id=id,payload=payload}
            return true
        end)
    end
    return self
end
return M
