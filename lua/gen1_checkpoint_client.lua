-- R5b-2 (round 2): the read-only client side of paired checkpoint capture. This
-- service claims TWO commands: checkpoint_upload (sample one coherent CartRAM image,
-- take no write permit, never write cartridge memory) and checkpoint_release (the
-- server's terminal verdict on the paired request). It holds -- via pending() below,
-- polled by gen1_client_entry.lua's existing writer-hold loop -- from the moment its
-- sample/refusal is prepared until the release lands, because the paired capture is
-- not finished just because THIS player's half completed (F2). A capture that cannot
-- reach a verified sample within bounded attempts or a bounded wait completes with a
-- durable REFUSAL receipt instead of retrying forever (F1).
local JSON=require("json_codec")
local Full=require("gen1_full_save")
local M={INTENT_SCHEMA="rby-checkpoint-upload-intent-v1",RELEASE_INTENT_SCHEMA="rby-checkpoint-release-intent-v1",
    -- Matches gen1_engine_signals.PROJECTION: the persistent-save hex suffix after the
    -- three sprite work buffers (ram/sram.asm), same projection save_witness digests.
    PROJECTION="cartram-0498-8000-v1",
    -- F1 bounds: at most this many CartRAM samples per request, and at most this long
    -- (wall clock, via the injected clock) waiting for a write-safe drained overworld
    -- before refusing unsafe_timeout instead of retrying forever.
    MAX_SAMPLE_ATTEMPTS=3,CHECKPOINT_WAIT_SECONDS=90}
local UPLOAD_FIELDS={cmd=true,request_id=true,witness=true}
local RELEASE_FIELDS={cmd=true,request_id=true,outcome=true,reason=true}
local RELEASE_OUTCOMES={confirmed=true,abandoned=true}
local function hex(value,size)return type(value)=="string" and #value==size and value:match("^[0-9a-f]+$")~=nil end
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function request_id_ok(value)return type(value)=="string" and #value>=1 and #value<=256 end

function M.handles(body)
    return type(body)=="table" and (body.cmd=="checkpoint_upload" or body.cmd=="checkpoint_release")
end

-- The witness itself is server-owned (server/gen1_engine_signal_runtime.py's
-- SAVE_WITNESS component: frame/digest/projection/index/operation_id) and must
-- round-trip through the receipt byte-for-byte (server/gen1_checkpoint_runtime.py
-- compares it for exact equality), so only the two fields this client acts on are
-- checked here; anything else is opaque and passed through untouched.
function M.validate(body)
    assert(M.handles(body),"complete checkpoint command required")
    if body.cmd=="checkpoint_release" then
        for key in pairs(body)do assert(RELEASE_FIELDS[key],"unknown checkpoint_release field: "..tostring(key))end
        for key in pairs(RELEASE_FIELDS)do assert(body[key]~=nil,"missing checkpoint_release field: "..key)end
        assert(request_id_ok(body.request_id),"invalid checkpoint request id")
        assert(RELEASE_OUTCOMES[body.outcome],"invalid checkpoint release outcome")
        assert(type(body.reason)=="string" and #body.reason<=256,"invalid checkpoint release reason")
        return body
    end
    for key in pairs(body)do assert(UPLOAD_FIELDS[key],"unknown checkpoint_upload field: "..tostring(key))end
    for key in pairs(UPLOAD_FIELDS)do assert(body[key]~=nil,"missing checkpoint_upload field: "..key)end
    assert(request_id_ok(body.request_id),"invalid checkpoint request id")
    local witness=body.witness
    assert(type(witness)=="table","checkpoint witness required")
    assert(hex(witness.digest,64),"invalid checkpoint witness digest")
    assert(witness.projection==M.PROJECTION,"unsupported checkpoint witness projection")
    return body
end

-- The typed completions the server's gen1_checkpoint_runtime dispatches on (R5b-1).
-- No other command shares either projection; mirrors gen1_trade_events.completion_event.
function M.completion_event(entry,outcome,receipt)
    local body=entry.body.body or entry.body
    if not M.handles(body)then return nil end
    assert(outcome=="ACK","checkpoint capture cannot publish a terminal NACK")
    if body.cmd=="checkpoint_release" then
        return {event="checkpoint_release",command_id=entry.command_id,command_sequence=entry.command_sequence,receipt=receipt}
    end
    return {event="save_upload",command_id=entry.command_id,command_sequence=entry.command_sequence,receipt=receipt}
end

function M.new(options)
    assert(type(options)=="table" and type(options.journal)=="table" and type(options.memory)=="table"
        and type(options.owned)=="function" and type(options.host)=="table" and type(options.clock)=="function"
        and type(options.overlay)=="table" and type(options.overlay.present)=="function"
        and (options.variant=="red" or options.variant=="blue" or options.variant=="yellow"),
        "client journal, memory, owned context, host, clock, overlay and variant required")
    local journal,mem,owned,host,variant,clock,overlay=
        options.journal,options.memory,options.owned,options.host,options.variant,options.clock,options.overlay
    local unwrap=options.unwrap or function(body)return require("gen1_runtime").unwrap(body,options.player)end
    local self={awaiting_release=nil,release_notice_at=nil}
    local track={} -- command_id -> {first_seen,attempts,context_generation,physical_instance}
    local function sha(text)return journal.store.backend.sha256(text)end
    local function note_seen(command_id)
        local info=track[command_id]
        if not info then info={first_seen=clock(),attempts=0};track[command_id]=info end
        return info
    end
    -- Best-effort, side-effect-only local status text: never blocks or fails the
    -- durable command flow. Routes through hud.lua's OWN sanitize() (H.present),
    -- the same call gen1_hud_service uses for server-issued notices -- this one is
    -- purely client-local (never a durable command, never ACKed to the server).
    local function notify(text,r,g,b,frames)
        pcall(overlay.present,{surface="hud",text=text,r=r or 255,g=g or 255,b=b or 255,frames=frames or 180})
    end
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
    local function drained()
        local pending_events,err=journal:pending_events()
        assert(pending_events,err)
        return #pending_events==0
    end
    local function timed_out(info)return (clock()-info.first_seen)>=M.CHECKPOINT_WAIT_SECONDS end
    -- command_service_router service shape: handles/ready/adapter/operations.
    self.handles=M.handles
    -- Cheap readiness the outer writer-hold loop polls every free-running tick (no
    -- CartRAM read here): worth taking the hold once the durable outbox is drained
    -- and the game state looks write-safe (or the wait budget has run out and we are
    -- about to durably refuse instead) -- AND, per F2, for as long as this player's
    -- own upload/refusal has completed but the server's paired checkpoint_release
    -- verdict has not yet arrived: the paired capture is not finished at that point,
    -- so gameplay must not resume silently in between.
    self.pending=function()
        if self.awaiting_release then
            -- Clear only once the release command's ACK is itself durable (the single
            -- source of truth is the journal, not receipt()'s return value): if
            -- complete_command ever failed after adapter.receipt ran, this keeps
            -- waiting rather than releasing on an unpersisted assumption.
            local release_id=self.awaiting_release.release_command_id
            local released=release_id and journal:get_command(release_id)
            if released and released.outcome=="ACK" then
                self.awaiting_release=nil
                return false
            end
            local now=clock()
            if not self.release_notice_at or now-self.release_notice_at>=3 then
                self.release_notice_at=now
                notify("Checkpoint pending - waiting for the server",255,220,120)
            end
            return true
        end
        local entry=head()
        if not entry then return false end
        if entry.body.cmd=="checkpoint_release" then return true end
        if mem.isPartyWriteSafe()==true and drained() then return true end
        local info=track[entry.command_id]
        return info~=nil and timed_out(info)
    end
    self.ready=function(body,intent,control)
        local ok,entry=matches(body)
        if not ok then return false,entry end
        if not control.admitted or not control.operation_held then return false,"waiting for a held checkpoint window"end
        if body.cmd=="checkpoint_release" then return true end
        local info=note_seen(entry.command_id)
        if safe() and drained() then return true end
        if timed_out(info) then return true end -- forced entry: prepare durably refuses unsafe_timeout
        return false,"checkpoint capture requires the party write-safe, drained overworld hold"
    end
    self.adapter={}
    local function refusal_intent(body,identity,code,reason)
        return {schema=M.INTENT_SCHEMA,command_id=identity.command_id,command_sequence=identity.command_sequence,
            request_id=body.request_id,witness=copy(body.witness),refused={code=code,reason=reason}}
    end
    -- The one and only path that may read CartRAM. Everything upstream (ready, and
    -- the guards repeated here in case prepare is ever invoked directly) must refuse
    -- before this point. A digest mismatch or a still-unsafe state raises (a transient
    -- NACK: no partial state is persisted, so a retry re-enters this same function) UNTIL
    -- its bound is reached, at which point this returns a REFUSAL intent successfully --
    -- and a successful return is what journal:prepare_command persists, so a refusal
    -- (like a real sample) is taken exactly once and never revisited on replay.
    function self.adapter.prepare(body,identity)
        M.validate(body)
        local ok,entry=matches(body)
        assert(ok,entry)
        assert(entry.command_id==identity.command_id and entry.command_sequence==identity.command_sequence,
            "checkpoint command identity differs from the command head")
        if body.cmd=="checkpoint_release" then
            assert(self.awaiting_release and self.awaiting_release.request_id==body.request_id,
                "checkpoint release does not match this client's awaited checkpoint request")
            -- A confirmed command is pruned from state.inbox the moment it retires
            -- (client_journal.lua's accept_response floor-advance), so get_command
            -- cannot see it here: command_floor having reached this player's own
            -- upload sequence is the durable proof accept_response actually leaves.
            local state,revision_or_error=journal.store:read() -- state_store:read() returns (payload,revision) on success
            assert(state,revision_or_error)
            assert(state.command_floor>=self.awaiting_release.upload_command_sequence,
                "checkpoint release arrived before this client's own upload was acknowledged")
            -- Remember which command_id to watch for durable ACK confirmation
            -- (pending() below clears awaiting_release only once that is true).
            self.awaiting_release.release_command_id=identity.command_id
            return {schema=M.RELEASE_INTENT_SCHEMA,command_id=identity.command_id,command_sequence=identity.command_sequence,
                request_id=body.request_id,outcome=body.outcome,reason=body.reason}
        end
        local info=note_seen(identity.command_id)
        local context=owned()
        if info.context_generation and (info.context_generation~=context.context_generation
            or info.physical_instance~=context.physical_instance) then
            return refusal_intent(body,identity,"identity_changed",
                "the held physical context changed while this checkpoint request was pending")
        end
        info.context_generation=info.context_generation or context.context_generation
        info.physical_instance=info.physical_instance or context.physical_instance
        if not (safe() and drained()) then
            if timed_out(info) then
                return refusal_intent(body,identity,"unsafe_timeout",
                    "the party write-safe drained overworld hold was not available within "
                        ..M.CHECKPOINT_WAIT_SECONDS.." seconds")
            end
            error("checkpoint capture requires the party write-safe, drained overworld hold",0)
        end
        info.attempts=info.attempts+1
        local frame=emu.framecount()
        local point=Full.capture(mem,variant) -- lua/gen1_full_save.lua:12-40's bulk CartRAM read pattern
        local digest=sha(point.cart_hex:sub(0x498*2+1))
        if digest~=body.witness.digest then
            if info.attempts>=M.MAX_SAMPLE_ATTEMPTS then
                return refusal_intent(body,identity,"digest_mismatch",
                    "the sampled save did not match the pinned witness after "..M.MAX_SAMPLE_ATTEMPTS.." attempts")
            end
            error("checkpoint witness digest differs from the sampled save",0)
        end
        assert(safe() and emu.framecount()==frame,"checkpoint sample requires a continuously held frame")
        return {schema=M.INTENT_SCHEMA,command_id=identity.command_id,command_sequence=identity.command_sequence,
            request_id=body.request_id,witness=copy(body.witness),frame=frame,
            context_generation=context.context_generation,physical_instance=context.physical_instance,
            final_sha1=gameinfo.getromhash():lower(),cart_hex=point.cart_hex}
    end
    -- The read (or the bounded refusal) already happened in prepare and is persisted
    -- in the durable intent. A retry (durable replay, or a fresh executor pass before
    -- the receipt lands) classifies that SAME intent; it is never reclassified into
    -- "before" and therefore never triggers apply or a second CartRAM read.
    function self.adapter.classify(body,intent,identity)
        local ok,entry=matches(body)
        assert(ok,entry)
        local schema=body.cmd=="checkpoint_release" and M.RELEASE_INTENT_SCHEMA or M.INTENT_SCHEMA
        assert(type(intent)=="table" and intent.schema==schema and intent.command_id==identity.command_id
            and intent.command_sequence==identity.command_sequence,
            "checkpoint command intent differs from the command head")
        return "after",intent
    end
    function self.adapter.apply()
        error("checkpoint_upload/checkpoint_release never write cartridge memory",0)
    end
    function self.adapter.receipt(body,intent,observed,identity)
        local ok,entry=matches(body)
        assert(ok,entry)
        assert(type(observed)=="table" and observed.command_id==identity.command_id,
            "checkpoint receipt requires its completed read")
        if body.cmd=="checkpoint_release" then
            -- awaiting_release itself clears lazily in pending(), once this command's
            -- own ACK is durably confirmed in the journal (not eagerly here): if
            -- complete_command later fails after this returns, pending() keeps
            -- holding rather than releasing on an unpersisted assumption. The
            -- terminal notice is cosmetic and safe to fire now, while still held.
            if intent.outcome=="confirmed" then notify("Checkpoint saved",120,255,120)
            else notify("Checkpoint abandoned: "..intent.reason,255,160,80,240)end
            return {request_id=intent.request_id,outcome=intent.outcome}
        end
        if intent.refused then
            notify("Checkpoint refused: "..intent.refused.reason,255,120,120,240)
            self.awaiting_release={request_id=intent.request_id,upload_command_sequence=identity.command_sequence}
            return {request_id=intent.request_id,witness=copy(intent.witness),refused=copy(intent.refused)}
        end
        self.awaiting_release={request_id=intent.request_id,upload_command_sequence=identity.command_sequence}
        return {request_id=intent.request_id,witness=copy(intent.witness),frame=intent.frame,
            context_generation=intent.context_generation,physical_instance=intent.physical_instance,
            final_sha1=intent.final_sha1,cart_hex=intent.cart_hex}
    end
    -- No write permit is ever requested: classify never returns "before", so apply
    -- (and therefore authorize_apply) is never reached for either command.
    self.operations={
        request=function()return nil end,
        accept=function(packet)assert(packet==nil,"checkpoint capture takes no operation grant");return true end,
        authorize_apply=function()return false,"checkpoint capture never writes cartridge memory"end,
        revoke=function()end,
        status=function()return {pending=self.pending(),awaiting_release=self.awaiting_release~=nil}end}
    return self
end
return M
