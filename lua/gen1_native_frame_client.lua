-- Durable accounting for a borrowed native owner. This never grants frames.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local M={SCHEMA="rby-client-native-frame-accounting-v1",QUERY="rby-native-handoff-query-v1"}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function same(a,b)return Canonical.encode(a)==Canonical.encode(b)end
local function integer(v)return type(v)=="number"and v%1==0 and v>=0 and v<=9007199254740991 end
local function token(v,n)return type(v)=="string"and #v==n and v:match("^[0-9a-f]+$")~=nil end
function M.borrowed(baseline)
    local state=baseline.native_frame_accounting
    return state~=nil and state.phase=="borrowed"
end
function M.validate_marker(baseline,context,host,frame)
    local state=baseline.native_frame_accounting
    if not state then return nil end
    assert(state.schema==M.SCHEMA and state.context_generation==context.context_generation
        and (state.phase=="borrowed"or state.phase=="handed_back")and integer(state.sequence)
        and state.baseline.phase=="idle"and integer(state.baseline.sequence)and integer(state.baseline.frame),
        "invalid native frame accounting marker")
    assert(host.failed==nil and not host.host.failed and not host.host.closed
        and host.host.owner_id==context.physical_instance and host.host.physical_stop_verified
        and host.expected_frame==frame,"native borrowed owner lost its exact physical boundary")
    return state
end
function M.adopt(marker,progress,context,frame)
    assert(marker.schema==M.SCHEMA and marker.phase=="handed_back"and marker.context_generation==context.context_generation,
        "acknowledged native handoff required")
    local handoff=assert(marker.handoff);local payload=handoff.payload.payload
    assert(handoff.phase=="acknowledged"and token(handoff.operation_id,32)
        and handoff.payload.event=="native_frame_handoff"and payload.schema=="rby-native-frame-return-v1"
        and payload.ledger_sequence==marker.sequence and payload.host.frame==frame
        and payload.inventory.frame==frame and payload.inventory.context_generation==context.context_generation,
        "native handoff marker differs from its acknowledged source/step count")
    if progress.native_handoff_operation_id==handoff.operation_id then return copy(progress)end
    assert(progress.context_generation==context.context_generation and progress.phase=="idle"and progress.sequence==marker.baseline.sequence and progress.frame==marker.baseline.frame,
        "native handoff replaced an ordinary frame obligation")
    local result=copy(progress)
    result.sequence=payload.ledger_sequence;result.frame=frame;result.inventory_frame=frame;result.last_operation_id=handoff.operation_id
    result.native_handoff_operation_id=handoff.operation_id;result.active=nil;result.completion=nil
    return result
end
function M.new(options)
    local journal=assert(options.journal);local self={query=nil,ready=false}
    local function sha(v)return journal.store.backend.sha256(assert(Canonical.encode(v)))end
    local function publish(event,baseline)
        if options.observe then return options.observe(JSON.array({event}),baseline)end
        return journal:append(event,baseline)
    end
    local function read()local data=assert(journal.store:read());return data,data.observation.native_frame_accounting end
    local function host()
        local value=options.host.status();local h=value.host
        assert(h.physical_stop_verified and value.expected_frame==emu.framecount(),"native return requires the exact owned hold")
        return {owner_id=h.owner_id,capability_id=h.capability_id,process_id=h.process_id,
            frame=value.expected_frame,steps=value.steps,held=true,bounded=value.single_frame_only and value.frame_callbacks_suppressed
                and value.load_state_invalidation and value.owner_exit_invalidation,failed=value.failed~=nil or h.failed or h.closed}
    end
    function self:accepted_grant(packet,sequence)
        local data,state=read();local context=options.owned()
        if not state or state.phase=="handed_back"then
            local ordinary=assert(data.observation.frame_progress,"ordinary frame baseline required before native borrowing")
            assert(ordinary.phase=="idle","ordinary frames still own the host")
            state={schema=M.SCHEMA,phase="borrowed",context_generation=context.context_generation,
                baseline=copy(ordinary),sequence=ordinary.sequence}
        end
        assert(state.context_generation==context.context_generation,"native loan context changed")
        if state.challenge~=packet.challenge then
            state.sequence=state.sequence+1;assert(integer(state.sequence),"native sequence overflow")
        else assert(state.response_digest==sha(packet),"native grant challenge changed its response")end
        state.challenge=packet.challenge;state.command_id=packet.scope.operation_id;state.command_sequence=sequence
        state.acceptance={schema="rby-native-grant-acceptance-v1",challenge=packet.challenge,host=host()}
        state.response_digest=sha(packet);data.observation.native_frame_accounting=state
        assert(journal.store:commit(data));self.ready=false
    end
    function self:acknowledge(payload,operation,baseline)
        local state=baseline.native_frame_accounting
        if not state then return nil end
        if payload.event=="native_frame_return"then
            assert(state.returning and state.returning.phase=="queued"and same(state.returning.payload,payload),"native return ACK differs")
            state.returning.phase="acknowledged";state.returning.operation_id=operation;self.ready=false
            return baseline
        end
        if payload.event=="native_frame_handoff"then
            assert(state.handoff and state.handoff.phase=="queued"and same(state.handoff.payload,payload),"native handoff ACK differs")
            state.handoff.phase="acknowledged";state.handoff.operation_id=operation;state.phase="handed_back"
            baseline.frame_progress=M.adopt(state,baseline.frame_progress,options.owned(),emu.framecount())
            if baseline.frame_progress.acquisition_source then
                assert(type(options.adopt_sources)=="function","native source handoff validator required")
                baseline.frame_progress.acquisition_source=options.adopt_sources(baseline.frame_progress.acquisition_source,state)
            end
            return baseline
        end
        local command=payload.command_id and journal:get_command(payload.command_id)
        if not command or state.phase~="borrowed"then return nil end
        local body=command.body.body or command.body
        local expected={native_receptionist="command_ack",native_trade_prompt="trade_decision",native_trade_prepare="trade_ready",
            native_trade_commit="trade_verified",native_trade_release="trade_ack",native_trade_abort="trade_ack"}
        if expected[body.cmd]~=payload.event then return nil end
        assert(command.outcome=="ACK"and same(command.receipt,payload.receipt),"native return lacks its exact completed receipt")
        local h=host();local current=options.owned()
        local inventory={schema="rby-initial-observation-v1",context_generation=current.context_generation,
            final_sha1=options.manifest.final_sha1,frame=h.frame,
            host={owner_id=h.owner_id,capability_id=h.capability_id,process_id=h.process_id,held=true},
            source=require("gen1_full_save").capture(options.memory,options.manifest.variant)}
        local checkpoint,native_checkpoint=JSON.null,JSON.null
        if options.memory.isPartyWriteSafe()then
            checkpoint=require("gen1_write_checkpoint").capture(options.memory.profile)
            native_checkpoint=require("gen1_trade_preparation").capture(options.memory,options.manifest)
        end
        if state.command_id~=payload.command_id then
            assert(body.cmd=="native_trade_abort"and payload.receipt.schema=="rby-trade-abort-v1"
                and state.returning and state.returning.phase=="acknowledged"
                and same(state.returning.payload.payload.inventory,inventory),"ungranted native command changed its held source")
        end
        state.returning={phase="captured",kind=body.cmd,payload={event="native_frame_return",payload={
            schema="rby-native-frame-return-v1",command_id=payload.command_id,command_sequence=payload.command_sequence,
            receipt_operation_id=operation,receipt_digest=sha(payload.receipt),grant_challenge=state.challenge,
            ledger_sequence=state.sequence,accounting=copy(state.acceptance),host=h,inventory=inventory,checkpoint=checkpoint,native_checkpoint=native_checkpoint}}}
        state.handoff=nil;self.ready=false
        return baseline
    end
    function self:acceptance()
        local _,state=read();return state and state.phase=="borrowed"and state.acceptance and copy(state.acceptance)or JSON.null
    end
    function self:pending()
        local _,state=read()
        return state and state.phase=="borrowed"and ((state.returning and state.returning.phase~="acknowledged")
            or state.handoff~=nil)or false
    end
    function self:request()
        local _,state=read();local returned=state and state.returning
        if not state or state.phase~="borrowed"or not returned or returned.phase~="acknowledged"
            or state.handoff or not ({native_trade_release=true,native_trade_abort=true,native_receptionist=true})[returned.kind] then return nil end
        local challenge=assert(require("platform_identity").new_nonce())
        self.query={schema=M.QUERY,challenge=challenge,return_operation_id=returned.operation_id,
            context_generation=state.context_generation}
        return {window={schema=M.QUERY,challenge=challenge},evidence=copy(self.query)}
    end
    function self:accept(packet)
        assert(self.query and type(packet)=="table"and packet.schema==M.QUERY and packet.challenge==self.query.challenge
            and packet.return_operation_id==self.query.return_operation_id and packet.context_generation==self.query.context_generation
            and type(packet.ready)=="boolean","native handoff readiness response differs")
        self.ready=packet.ready;self.query=nil;return true
    end
    function self:pump()
        local data,state=read();if not state or state.phase~="borrowed"then return end
        local returning=state.returning
        if returning and(returning.phase=="captured"or(returning.phase=="acknowledged"and self.ready))then
            assert(same(host(),returning.payload.payload.host)
                and same(require("gen1_full_save").capture(options.memory,options.manifest.variant),returning.payload.payload.inventory.source),
                "native return changed before durable publication")
        end
        if returning and returning.phase=="captured"then
            returning.phase="queued";assert(publish(copy(returning.payload),data.observation))
        elseif returning and returning.phase=="acknowledged"and self.ready and not state.handoff then
            local payload={event="native_frame_handoff",payload=copy(returning.payload.payload)}
            state.handoff={phase="queued",payload=payload};assert(publish(payload,data.observation));self.ready=false
        end
    end
    function self:revoke()self.query=nil;self.ready=false end
    return self
end
return M
