-- Persist intent before effects; recover from observed state, never from a return code.
-- Cartridge adapters own preparation, safe-state/identity checks and exact readback.
local JSON=require("json_codec")
local M={}
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function metadata(entry,command_id)
    assert(type(command_id)=="string" and #command_id==32 and command_id:match("^[0-9a-f]+$"),
        "invalid durable command identifier")
    assert(type(entry)=="table" and entry.command_id==command_id,"command identity differs from inbox request")
    local sequence=entry.command_sequence
    assert(type(sequence)=="number" and sequence%1==0 and sequence>=1 and sequence<=9007199254740991,
        "invalid durable command sequence")
    return {command_id=command_id,command_sequence=sequence}
end
local function armed(observation,identity)
    local evidence=copy(observation)
    assert(JSON.kind(evidence)=="object" and type(evidence.schema)=="string"
        and #evidence.schema>=1 and #evidence.schema<=64 and evidence.command_id==identity.command_id,
        "versioned, command-bound armed evidence required")
    -- This is neither a terminal receipt nor permission to run native frames.
    -- Only the cartridge/control binding may authorize a recovery procedure.
    return {outcome="PENDING",pending=true,phase="armed",evidence=evidence,
        command_id=identity.command_id,command_sequence=identity.command_sequence,
        native_execution_permitted=false}
end

function M.new(journal,adapter)
    assert(type(journal)=="table" and type(adapter)=="table","journal and adapter required")
    for _,name in ipairs({"prepare","classify","apply","receipt"}) do
        assert(type(adapter[name])=="function","executor callback required: "..name)
    end
    local self={busy=false}
    function self:step(command_id)
        if self.busy then return false,{outcome="NACK",retryable=true,phase="busy",reason="executor already running"} end
        self.busy=true
        local phase="read"
        local ok,result=pcall(function()
            local entry,reason=journal:get_command(command_id)
            if not entry then error(reason,0) end
            local identity=metadata(entry,command_id)
            if entry.outcome then
                return {outcome=entry.outcome,receipt=entry.receipt,replayed=true}
            end
            if not entry.intent then
                phase="prepare"
                local intent,why=adapter.prepare(copy(entry.body),copy(identity))
                if not intent then error(why or "command preparation refused",0) end
                phase="persist_intent"
                local saved,problem=journal:prepare_command(command_id,intent)
                if not saved then error(problem,0) end
                entry=assert(journal:get_command(command_id))
                local persisted_identity=metadata(entry,command_id)
                assert(persisted_identity.command_sequence==identity.command_sequence,
                    "command sequence changed during preparation")
            end
            phase="classify"
            local state,observation=adapter.classify(copy(entry.body),copy(entry.intent),copy(identity))
            if state=="armed" then return armed(observation,identity) end
            if state=="before" then
                phase="apply"
                -- An exception may occur after a partial or complete effect. Keep the
                -- prepared inbox entry; the next step must classify fresh readback.
                adapter.apply(copy(entry.body),copy(entry.intent),copy(identity))
                phase="readback"
                state,observation=adapter.classify(copy(entry.body),copy(entry.intent),copy(identity))
            end
            if state=="armed" then return armed(observation,identity) end
            if state~="after" then
                error(type(observation)=="string" and observation or "command poststate is not proven",0)
            end
            phase="receipt"
            local receipt,why=adapter.receipt(copy(entry.body),copy(entry.intent),copy(observation),copy(identity))
            if not receipt then error(why or "physical receipt refused",0) end
            phase="persist_receipt"
            local saved,problem=journal:complete_command(command_id,"ACK",receipt)
            if not saved then error(problem,0) end
            return {outcome="ACK",receipt=copy(receipt)}
        end)
        self.busy=false
        if not ok then
            -- This is a retryable diagnostic, not a terminal journal receipt. In
            -- particular, uncertain effects must never be dequeued by a NACK.
            return false,{outcome="NACK",retryable=true,phase=phase,reason=tostring(result)}
        end
        return result.outcome~="PENDING",result
    end
    return self
end
return M
