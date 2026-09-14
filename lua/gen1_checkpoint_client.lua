-- R5b-2: the read-only client side of paired checkpoint capture. This service claims
-- exactly ONE command (checkpoint_upload), takes no write permit and never writes
-- cartridge memory: it samples one coherent CartRAM image under the SAME dedicated
-- hold the held-write path already uses (gen1_client_entry.lua's writer service, armed
-- by this module's pending()), checks the sample against the server's pinned witness
-- digest locally, and returns it verbatim as a typed save_upload completion.
local JSON=require("json_codec")
local Full=require("gen1_full_save")
local M={INTENT_SCHEMA="rby-checkpoint-upload-intent-v1",
    -- Matches gen1_engine_signals.PROJECTION: the persistent-save hex suffix after the
    -- three sprite work buffers (ram/sram.asm), same projection save_witness digests.
    PROJECTION="cartram-0498-8000-v1"}
local FIELDS={cmd=true,request_id=true,witness=true}
local function hex(value,size)return type(value)=="string" and #value==size and value:match("^[0-9a-f]+$")~=nil end
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end

function M.handles(body)return type(body)=="table" and body.cmd=="checkpoint_upload"end

-- Mirrors the other Gen 1 command validators for the OUTER body's field set. The
-- witness itself is server-owned (server/gen1_engine_signal_runtime.py's SAVE_WITNESS
-- component: frame/digest/projection/index/operation_id) and must round-trip through
-- the receipt byte-for-byte (server/gen1_checkpoint_runtime.py compares it for exact
-- equality), so only the two fields this client actually acts on are checked here;
-- anything else is opaque and passed through untouched by adapter.prepare below.
function M.validate(body)
    assert(M.handles(body),"complete checkpoint_upload command required")
    for key in pairs(body)do assert(FIELDS[key],"unknown checkpoint_upload field: "..tostring(key))end
    for key in pairs(FIELDS)do assert(body[key]~=nil,"missing checkpoint_upload field: "..key)end
    assert(type(body.request_id)=="string" and #body.request_id>=1 and #body.request_id<=256,
        "invalid checkpoint request id")
    local witness=body.witness
    assert(type(witness)=="table","checkpoint witness required")
    assert(hex(witness.digest,64),"invalid checkpoint witness digest")
    assert(witness.projection==M.PROJECTION,"unsupported checkpoint witness projection")
    return body
end

-- The typed completion the server's gen1_checkpoint_runtime dispatches on (R5b-1).
-- No other command shares this projection; mirrors gen1_trade_events.completion_event.
function M.completion_event(entry,outcome,receipt)
    local body=entry.body.body or entry.body
    if not M.handles(body)then return nil end
    assert(outcome=="ACK","checkpoint capture cannot publish a terminal NACK")
    return {event="save_upload",command_id=entry.command_id,command_sequence=entry.command_sequence,receipt=receipt}
end

function M.new(options)
    assert(type(options)=="table" and type(options.journal)=="table" and type(options.memory)=="table"
        and type(options.owned)=="function" and type(options.host)=="table"
        and (options.variant=="red" or options.variant=="blue" or options.variant=="yellow"),
        "client journal, memory, owned context, host and variant required")
    local journal,mem,owned,host,variant=options.journal,options.memory,options.owned,options.host,options.variant
    local unwrap=options.unwrap or function(body)return require("gen1_runtime").unwrap(body,options.player)end
    local self={}
    local function sha(text)return journal.store.backend.sha256(text)end
    local function head()
        local entry=assert(journal:pending_commands())[1]
        if not entry then return nil end
        entry=copy(entry);entry.body=unwrap(entry.body)
        if not M.handles(entry.body)then return nil end
        return entry
    end
    local function matches(body)
        local entry=head()
        if not entry or assert(JSON.encode(entry.body))~=assert(JSON.encode(body))then
            return false,"waiting for the owned checkpoint command at the command head"
        end
        return true,entry
    end
    -- Same two-part condition as gen1_held_faint.safe(): the game state is at the
    -- verified overworld checkpoint AND the platform host proves the core is actually
    -- stopped there. Neither alone is a coherent read point.
    local function safe()
        owned();return mem.isPartyWriteSafe()==true and host.status().physical_stop_verified==true
    end
    -- command_service_router service shape: handles/ready/adapter/operations.
    self.handles=M.handles
    -- Cheap readiness the outer writer-hold loop polls every free-running tick (no
    -- CartRAM read here): worth taking the hold only once the durable outbox is
    -- already drained and the game state itself looks write-safe.
    self.pending=function()
        local entry=head()
        if not entry then return false end
        local pending_events,err=journal:pending_events()
        assert(pending_events,err)
        return mem.isPartyWriteSafe()==true and #pending_events==0
    end
    self.ready=function(body,intent,control)
        local ok,why=matches(body)
        if not ok then return false,why end
        if not control.admitted or not control.operation_held then return false,"waiting for a held checkpoint window"end
        if not safe()then return false,"checkpoint capture requires the party write-safe overworld"end
        local pending_events,err=journal:pending_events()
        assert(pending_events,err)
        if #pending_events>0 then return false,"durable events must drain before checkpoint capture"end
        return true
    end
    self.adapter={}
    -- The one and only CartRAM read for this command. Everything upstream (ready,
    -- and the two guards repeated here in case prepare is ever invoked directly)
    -- must refuse before this point: no partial or speculative sample is possible.
    function self.adapter.prepare(body,identity)
        M.validate(body)
        local ok,entry=matches(body)
        assert(ok,entry)
        assert(entry.command_id==identity.command_id and entry.command_sequence==identity.command_sequence,
            "checkpoint command identity differs from the command head")
        local pending_events,err=journal:pending_events()
        assert(pending_events,err)
        assert(#pending_events==0,"durable events must drain before checkpoint capture")
        assert(safe(),"checkpoint capture requires the party write-safe overworld hold")
        local frame=emu.framecount()
        local point=Full.capture(mem,variant) -- lua/gen1_full_save.lua:12-40's bulk CartRAM read pattern
        local digest=sha(point.cart_hex:sub(0x498*2+1))
        assert(digest==body.witness.digest,"checkpoint witness digest differs from the sampled save")
        assert(safe() and emu.framecount()==frame,"checkpoint sample requires a continuously held frame")
        local context=owned()
        return {schema=M.INTENT_SCHEMA,command_id=identity.command_id,command_sequence=identity.command_sequence,
            request_id=body.request_id,witness=copy(body.witness),frame=frame,
            context_generation=context.context_generation,physical_instance=context.physical_instance,
            final_sha1=gameinfo.getromhash():lower(),cart_hex=point.cart_hex}
    end
    -- The read already happened in prepare and is persisted in the durable intent.
    -- A retry (durable replay, or a fresh executor pass before the receipt lands)
    -- classifies that SAME sampled intent; it is never reclassified into "before"
    -- and therefore never triggers apply or a second CartRAM read.
    function self.adapter.classify(body,intent,identity)
        local ok,entry=matches(body)
        assert(ok,entry)
        assert(type(intent)=="table" and intent.schema==M.INTENT_SCHEMA and intent.command_id==identity.command_id
            and intent.command_sequence==identity.command_sequence,
            "checkpoint command intent differs from the command head")
        return "after",intent
    end
    function self.adapter.apply()
        error("checkpoint_upload never writes cartridge memory",0)
    end
    function self.adapter.receipt(body,intent,observed,identity)
        local ok,entry=matches(body)
        assert(ok,entry)
        assert(type(observed)=="table" and observed.command_id==identity.command_id,
            "checkpoint receipt requires its completed read")
        return {request_id=intent.request_id,witness=copy(intent.witness),frame=intent.frame,
            context_generation=intent.context_generation,physical_instance=intent.physical_instance,
            final_sha1=intent.final_sha1,cart_hex=intent.cart_hex}
    end
    -- No write permit is ever requested: classify never returns "before", so apply
    -- (and therefore authorize_apply) is never reached for this command.
    self.operations={
        request=function()return nil end,
        accept=function(packet)assert(packet==nil,"checkpoint capture takes no operation grant");return true end,
        authorize_apply=function()return false,"checkpoint capture never writes cartridge memory"end,
        revoke=function()end,
        status=function()return {pending=self.pending()}end}
    return self
end
return M
