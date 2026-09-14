-- R5b-2 (round 3): the read-only client side of paired checkpoint capture, matched to
-- the authoritative joint protocol at docs/gen1_reference/reviews/R5b-joint-protocol.md
-- and server/gen1_checkpoint_runtime.py (R5b-1 round 2). This service claims TWO
-- commands: checkpoint_upload (sample one coherent CartRAM image, no write permit, no
-- cartridge write) and checkpoint_release (the server's terminal verdict). It never
-- raises a transient condition into durable_runtime's fatal path (F1): every
-- "not ready yet" state -- unsafe, undrained, a mismatched sample, an identity change --
-- is expressed as a non-raising classify() outcome (durable "armed"/PENDING, or a
-- durable typed refusal), never a thrown error reaching command_executor while
-- ready()==true. The 90s unsafe deadline and the identity pin both start at DISCOVERY
-- (F2/F7), before admission/hold is even known, and both are carried in the durable
-- intent so they survive a reload. The paired hold (F3) clears only once the matching
-- checkpoint_release command's OWN sequence has itself been confirmed-retired
-- (command_floor advance), never on this client's local completion alone; that
-- request_id/upload-sequence/release-sequence triple is itself persisted durably in the
-- journal's observation baseline (F5), reconstructed on open. gen1_client_entry.lua's
-- writer-hold loop keeps the "writer" vote (and therefore the physical hold) engaged
-- for as long as pending() is true, with no 2s bound, while this remains true (F4).
local JSON=require("json_codec")
local Full=require("gen1_full_save")
local M={
    INTENT_SCHEMA="rby-checkpoint-upload-intent-v1",
    RELEASE_INTENT_SCHEMA="rby-checkpoint-release-intent-v1",
    STATE_SCHEMA="rby-checkpoint-client-state-v1", -- durable observation-baseline record (F5)
    -- Matches gen1_engine_signals.PROJECTION: the persistent-save hex suffix after the
    -- three sprite work buffers (ram/sram.asm), same projection save_witness digests.
    PROJECTION="cartram-0498-8000-v1",
    -- F1 bounds: at most this many CartRAM samples per request, and at most this long
    -- (wall clock, via the injected clock, from DISCOVERY) waiting for a write-safe
    -- drained overworld before refusing unsafe_timeout instead of retrying forever.
    MAX_SAMPLE_ATTEMPTS=3,CHECKPOINT_WAIT_SECONDS=90}
local UPLOAD_FIELDS={cmd=true,request_id=true,witness=true}
local WITNESS_FIELDS={frame=true,digest=true,projection=true,index=true,operation_id=true}
local RELEASE_FIELDS={cmd=true,request_id=true,outcome=true,reason=true}
local RELEASE_OUTCOMES={confirmed=true,abandoned=true}
local MAX_SEQ=9007199254740991
local function hex(value,size)return type(value)=="string" and #value==size and value:match("^[0-9a-f]+$")~=nil end
local function integer(value,min,max)return type(value)=="number" and value%1==0 and value>=min and value<=max end
local function printable_ascii(value,min,max)
    return type(value)=="string" and #value>=min and #value<=max and not value:find("[^ -~]")
end
local function request_id_ok(value)
    return type(value)=="string" and #value>=1 and #value<=64 and value:match("^[A-Za-z0-9_.%-]+$")~=nil
end
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end

function M.handles(body)
    return type(body)=="table" and (body.cmd=="checkpoint_upload" or body.cmd=="checkpoint_release")
end

-- Wire shapes and bounds per the joint protocol §2: exact field sets, request_id
-- [A-Za-z0-9_.-]{1,64}, the exact witness field set {frame,digest,projection,index,
-- operation_id}, and a release reason that is a printable-ASCII string 0..256 (empty
-- allowed, JSON null refused by the plain string type check).
function M.validate(body)
    assert(M.handles(body),"complete checkpoint command required")
    if body.cmd=="checkpoint_release" then
        for key in pairs(body)do assert(RELEASE_FIELDS[key],"unknown checkpoint_release field: "..tostring(key))end
        for key in pairs(RELEASE_FIELDS)do assert(body[key]~=nil,"missing checkpoint_release field: "..key)end
        assert(request_id_ok(body.request_id),"invalid checkpoint request id")
        assert(RELEASE_OUTCOMES[body.outcome],"invalid checkpoint release outcome")
        assert(printable_ascii(body.reason,0,256),"invalid checkpoint release reason")
        return body
    end
    for key in pairs(body)do assert(UPLOAD_FIELDS[key],"unknown checkpoint_upload field: "..tostring(key))end
    for key in pairs(UPLOAD_FIELDS)do assert(body[key]~=nil,"missing checkpoint_upload field: "..key)end
    assert(request_id_ok(body.request_id),"invalid checkpoint request id")
    local witness=body.witness
    assert(type(witness)=="table","checkpoint witness required")
    for key in pairs(witness)do assert(WITNESS_FIELDS[key],"unknown checkpoint witness field: "..tostring(key))end
    for key in pairs(WITNESS_FIELDS)do assert(witness[key]~=nil,"missing checkpoint witness field: "..key)end
    assert(integer(witness.frame,0,MAX_SEQ),"invalid checkpoint witness frame")
    assert(hex(witness.digest,64),"invalid checkpoint witness digest")
    assert(witness.projection==M.PROJECTION,"unsupported checkpoint witness projection")
    assert(integer(witness.index,0,MAX_SEQ),"invalid checkpoint witness index")
    assert(hex(witness.operation_id,32),"invalid checkpoint witness operation id")
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
    local self={awaiting_release=nil}
    -- Local-only, per-command_id read-attempt cache: attempts/matched/refused/frame/
    -- cart_hex. Deliberately NOT durable -- a reload just restarts the bounded attempt
    -- count cleanly (still <=MAX_SAMPLE_ATTEMPTS more reads), never resampling past a
    -- DURABLE completion (command_executor's own replay-before-prepare short circuit).
    local track={}
    local last_status=nil
    local function sha(text)return journal.store.backend.sha256(text)end
    local function read_state()
        local state,revision_or_error=journal.store:read() -- (payload,revision) on success
        assert(state,revision_or_error)
        return state
    end
    -- F5/joint-protocol §1: durable request_id + upload/release sequence, reconstructed
    -- on open from the journal's own observation baseline (survives a reload). The
    -- upload command's own durable intent is pruned the instant its sequence is
    -- confirmed-retired (client_journal.lua's floor-advance), so it cannot carry this
    -- information past that point; the baseline is the only surviving durable trace.
    local function persist_awaiting(value)
        local baseline=copy(read_state().observation)
        baseline.gen1_checkpoint=value and {schema=M.STATE_SCHEMA,request_id=value.request_id,
            upload_command_sequence=value.upload_command_sequence,
            release_command_sequence=value.release_command_sequence or JSON.null} or JSON.null
        assert(journal:append_many(JSON.array(),baseline))
    end
    do
        -- Tolerate a minimal/synthetic journal double that has no real state_store
        -- (this module is constructed unconditionally by gen1_client_entry.lua whenever
        -- initial_observations is enabled, whether or not the caller cares about
        -- checkpoint capture at all): a reconstruction failure here is never worse than
        -- the in-memory-only behavior this replaced, so it degrades quietly rather than
        -- taking down the whole client's startup.
        local ok,saved=pcall(function()return read_state().observation.gen1_checkpoint end)
        if ok and saved and saved~=JSON.null then
            self.awaiting_release={request_id=saved.request_id,upload_command_sequence=saved.upload_command_sequence,
                release_command_sequence=saved.release_command_sequence~=JSON.null and saved.release_command_sequence or nil}
        end
    end
    -- Best-effort, side-effect-only local status text: never blocks or fails the
    -- durable command flow. F6: at most ONE retained hud.lua entry for this module at a
    -- time -- a repeat of the SAME text is skipped while it is still retained (H.present
    -- is the only sanitize-safe draw path hud.lua exposes; it has no in-place update, so
    -- de-duplicating on the caller side is what keeps this bounded during a long hold).
    local function status_line(text,r,g,b,frames)
        if text==last_status then
            local retained=type(overlay.retained)=="function" and overlay.retained() or nil
            if retained and (retained.hud or 0)>0 then return end
        end
        last_status=text
        pcall(overlay.present,{surface="hud",text=text,r=r or 255,g=g or 255,b=b or 255,frames=frames or 180})
    end
    local function head()
        local entry=assert(journal:pending_commands())[1]
        if not entry then return nil end
        entry=copy(entry);entry.body=unwrap(entry.body)
        if not M.handles(entry.body)then return nil end
        if entry.body.cmd=="checkpoint_upload" and not track[entry.command_id] then
            -- F2/F7: discovery-time pin -- BEFORE admission/hold/safety are even known --
            -- of both the 90s wait clock and the identity this request is bound to.
            local context=owned()
            track[entry.command_id]={first_seen=clock(),attempts=0,
                context_generation=context.context_generation,physical_instance=context.physical_instance}
        end
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
    local function command_floor()return read_state().command_floor end
    -- command_service_router service shape: handles/ready/adapter/operations.
    self.handles=M.handles
    -- Cheap readiness the outer writer-hold loop polls every free-running tick (no
    -- CartRAM read here): worth taking the hold once the durable outbox is drained and
    -- the game state looks write-safe (or the wait budget has run out and we are about
    -- to durably refuse instead) -- AND, per F2/F3, for as long as this player's own
    -- upload/refusal has completed but the matching checkpoint_release has not yet
    -- itself been CONFIRMED-retired: the paired capture is not finished at that point,
    -- so gameplay must not resume silently in between.
    self.pending=function()
        if self.awaiting_release then
            local seq=self.awaiting_release.release_command_sequence
            if seq and command_floor()>=seq then
                self.awaiting_release=nil
                persist_awaiting(nil)
                return false
            end
            status_line("Checkpoint pending - waiting for the server",255,220,120)
            return true
        end
        local entry=head()
        if not entry then return false end
        if entry.body.cmd=="checkpoint_release" then return true end
        if mem.isPartyWriteSafe()==true and drained() then return true end
        local info=track[entry.command_id]
        return info~=nil and (clock()-info.first_seen)>=M.CHECKPOINT_WAIT_SECONDS
    end
    -- F1: readiness gates only identity/admission/hold -- it never blocks entry into the
    -- executor for an "unsafe" or "not yet matched" reason. classify() below is what
    -- expresses those as a non-raising "armed"/PENDING state, which command_executor
    -- reports as {pending=true} and durable_runtime.execute_one therefore never treats
    -- as a fatal failure (contrast a raised error from prepare, which it always does).
    self.ready=function(body,intent,control)
        local ok,entry=matches(body)
        if not ok then return false,entry end
        if not control.admitted or not control.operation_held then return false,"waiting for a held checkpoint window"end
        return true
    end
    self.adapter={}
    -- Runs exactly once per command (command_executor never calls prepare again once
    -- journal:prepare_command has persisted its intent). It never reads CartRAM and
    -- never raises for a transient reason: it only pins the request/witness/identity
    -- (from the discovery-time track entry) or reconstructs an in-flight release.
    function self.adapter.prepare(body,identity)
        M.validate(body)
        local ok,entry=matches(body)
        assert(ok,entry)
        assert(entry.command_id==identity.command_id and entry.command_sequence==identity.command_sequence,
            "checkpoint command identity differs from the command head")
        if body.cmd=="checkpoint_release" then
            -- F5: a same-owner reopen after this client's own upload already retired
            -- (and was pruned) has no in-memory awaiting_release; reconstruct it from
            -- the release's OWN request_id -- a controlled adoption, not a missing-
            -- state assert. FIFO ordering (checkpoint_upload always precedes
            -- checkpoint_release in the inbox) already proves the upload retired the
            -- instant this release is even visible as the head command.
            if not self.awaiting_release then
                self.awaiting_release={request_id=body.request_id,upload_command_sequence=command_floor()}
                persist_awaiting(self.awaiting_release)
            end
            assert(self.awaiting_release.request_id==body.request_id,
                "checkpoint release does not match this client's awaited checkpoint request")
            assert(command_floor()>=self.awaiting_release.upload_command_sequence,
                "checkpoint release arrived before this client's own upload was acknowledged")
            return {schema=M.RELEASE_INTENT_SCHEMA,command_id=identity.command_id,command_sequence=identity.command_sequence,
                request_id=body.request_id,outcome=body.outcome,reason=body.reason}
        end
        local info=track[identity.command_id]
        assert(info,"checkpoint command was not discovered before preparation")
        -- The discovery-time pin travels into the DURABLE intent (F5/F7): a reload
        -- reads it back from here, not from track (which is reseeded fresh on reload),
        -- so the identity/deadline this request is bound to survives intact.
        return {schema=M.INTENT_SCHEMA,command_id=identity.command_id,command_sequence=identity.command_sequence,
            request_id=body.request_id,witness=copy(body.witness),first_seen=info.first_seen,
            context_generation=info.context_generation,physical_instance=info.physical_instance}
    end
    -- Called every tick once the intent exists. Never raises: every "not yet" outcome
    -- is the non-raising "armed" PENDING state; every terminal outcome (a real sample or
    -- a bounded refusal) is "after". This is the ONE place that may read CartRAM.
    function self.adapter.classify(body,intent,identity)
        local ok,entry=matches(body)
        assert(ok,entry)
        if body.cmd=="checkpoint_release" then
            assert(type(intent)=="table" and intent.schema==M.RELEASE_INTENT_SCHEMA and intent.command_id==identity.command_id
                and intent.command_sequence==identity.command_sequence,
                "checkpoint command intent differs from the command head")
            -- Pin the release's own sequence for the F3 floor-settlement check, durably
            -- (F5), the instant it is known -- before this command can even ACK.
            if not self.awaiting_release.release_command_sequence then
                self.awaiting_release.release_command_sequence=identity.command_sequence
                persist_awaiting(self.awaiting_release)
            end
            return "after",intent
        end
        assert(type(intent)=="table" and intent.schema==M.INTENT_SCHEMA and intent.command_id==identity.command_id
            and intent.command_sequence==identity.command_sequence,
            "checkpoint command intent differs from the command head")
        -- F7: compared against the identity pinned DURABLY in the intent (surviving a
        -- reload), never a fresh post-reload discovery pin -- a plain same-owner
        -- reattach is therefore never itself a refusal; only a genuinely different
        -- physical context inheriting this exact durable command is.
        local context=owned()
        if context.context_generation~=intent.context_generation or context.physical_instance~=intent.physical_instance then
            return "after",{refused={code="identity_changed",
                reason="the held physical context changed while this checkpoint request was pending"}}
        end
        if not (safe() and drained()) then
            if (clock()-intent.first_seen)>=M.CHECKPOINT_WAIT_SECONDS then
                return "after",{refused={code="unsafe_timeout",
                    reason="the party write-safe drained overworld hold was not available within "
                        ..M.CHECKPOINT_WAIT_SECONDS.." seconds"}}
            end
            return "armed",{schema="rby-checkpoint-awaiting-safety-v1",command_id=identity.command_id}
        end
        local sample=track[identity.command_id]
        if not sample then sample={attempts=0};track[identity.command_id]=sample end
        if sample.matched then return "after",{frame=sample.frame,cart_hex=sample.cart_hex}end
        if sample.refused then return "after",{refused=sample.refused}end
        -- One bounded, owned read attempt per tick while safe+drained; never raises.
        sample.attempts=sample.attempts+1
        local frame=emu.framecount()
        local point=Full.capture(mem,variant) -- lua/gen1_full_save.lua:12-40's bulk CartRAM read pattern
        local digest=sha(point.cart_hex:sub(0x498*2+1))
        if digest==body.witness.digest then
            assert(safe() and emu.framecount()==frame,"checkpoint sample requires a continuously held frame")
            sample.matched=true;sample.frame=frame;sample.cart_hex=point.cart_hex
            return "after",{frame=frame,cart_hex=point.cart_hex}
        end
        if sample.attempts>=M.MAX_SAMPLE_ATTEMPTS then
            sample.refused={code="digest_mismatch",
                reason="the sampled save did not match the pinned witness after "..M.MAX_SAMPLE_ATTEMPTS.." attempts"}
            return "after",{refused=sample.refused}
        end
        return "armed",{schema="rby-checkpoint-sample-retry-v1",command_id=identity.command_id,attempt=sample.attempts}
    end
    function self.adapter.apply()
        error("checkpoint_upload/checkpoint_release never write cartridge memory",0)
    end
    function self.adapter.receipt(body,intent,observed,identity)
        local ok,entry=matches(body)
        assert(ok,entry)
        assert(type(observed)=="table","checkpoint receipt requires its completed read")
        if body.cmd=="checkpoint_release" then
            if intent.outcome=="confirmed" then status_line("Checkpoint saved",120,255,120)
            else status_line("Checkpoint abandoned: "..intent.reason,255,160,80,240)end
            return {request_id=intent.request_id,outcome=intent.outcome}
        end
        if observed.refused then
            status_line("Checkpoint refused: "..observed.refused.reason,255,120,120,240)
            self.awaiting_release={request_id=intent.request_id,upload_command_sequence=identity.command_sequence}
            persist_awaiting(self.awaiting_release)
            track[identity.command_id]=nil
            return {request_id=intent.request_id,witness=copy(intent.witness),refused=copy(observed.refused)}
        end
        self.awaiting_release={request_id=intent.request_id,upload_command_sequence=identity.command_sequence}
        persist_awaiting(self.awaiting_release)
        track[identity.command_id]=nil
        return {request_id=intent.request_id,witness=copy(intent.witness),frame=observed.frame,
            context_generation=intent.context_generation,physical_instance=intent.physical_instance,
            final_sha1=gameinfo.getromhash():lower(),cart_hex=observed.cart_hex}
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
