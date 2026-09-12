-- Initial inventory enrollment under an already-owned fixed-frame hold.
-- Observation and baseline publish together; this grants no frames or writes.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Full=require("gen1_full_save")
local Stream=require("observation_stream")
local M={COMPACT="rby-initial-observation-cursor-v1"}
local function token(value,size)return type(value)=="string"and#value==size and value:match("^[0-9a-f]+$")~=nil end
local function initial_payload(entry)
    return entry and entry.payload and entry.payload.payload or nil
end
function M.initial_cursor(entry)
    assert(type(entry)=="table"and entry.phase=="acknowledged"and token(entry.operation_id,32),
        "acknowledged initial observation required")
    local payload=initial_payload(entry)
    if payload then
        return {context_generation=payload.context_generation,final_sha1=payload.final_sha1,frame=payload.frame,
            operation_id=entry.operation_id,payload_digest=nil,full=true}
    end
    assert(entry.schema==M.COMPACT and token(entry.context_generation,32)and token(entry.final_sha1,40)
        and type(entry.frame)=="number"and entry.frame%1==0 and entry.frame>=0 and token(entry.payload_digest,64),
        "invalid compact initial observation cursor")
    return {context_generation=entry.context_generation,final_sha1=entry.final_sha1,frame=entry.frame,
        operation_id=entry.operation_id,payload_digest=entry.payload_digest,full=false}
end
function M.compact_initial(entry,sha256)
    local cursor=M.initial_cursor(entry)
    if not cursor.full then return entry,false end
    assert(type(sha256)=="function","initial observation digest required")
    local payload=assert(initial_payload(entry))
    local digest=sha256(assert(Canonical.encode(payload)))
    assert(token(digest,64),"initial observation digest unavailable")
    return {schema=M.COMPACT,phase="acknowledged",operation_id=cursor.operation_id,
        context_generation=cursor.context_generation,final_sha1=cursor.final_sha1,frame=cursor.frame,payload_digest=digest},true
end
function M.capture(options)
    local context=assert(JSON.decode(assert(JSON.encode(options.owned()))));local frame=emu.framecount();local host=options.host.status()
    local query=options.native_manifest and require("gen1_receptionist_client").query(options.memory,options.native_manifest)
    assert((options.memory.isPartyWriteSafe()or query)and host.physical_stop_verified,
        "initial observation needs a verified held overworld or native receptionist query")
    local source=Full.capture(options.memory,options.variant)
    local current=options.owned()
    assert(frame==emu.framecount() and JSON.encode(current)==JSON.encode(context),"initial observation context changed")
    return {schema="rby-initial-observation-v1",context_generation=context.context_generation,
        final_sha1=gameinfo.getromhash():lower(),frame=frame,source=source,
        host={owner_id=host.owner_id,capability_id=host.capability_id,process_id=host.process_id,held=true}}
end
function M.new(options)
    assert(type(options.owned)=="function" and options.journal and options.memory and options.host,
        "owned held reader and durable journal required")
    assert(options.source_owned==nil or type(options.source_owned)=="function","source identity reader must be callable")
    local self={}
    local stream=not options.free_service and Stream.new({journal=options.journal,key="inventory_stream",event="inventory_observation",owned=options.owned,
        seed=function(baseline)
            local initial=baseline.initial_inventory
            if initial and initial.phase=="acknowledged"then
                return {sequence=0,operation_id=initial.operation_id,observation=initial.payload.payload}
            end
        end,
        verify=function(point)return emu.framecount()==point.frame and options.host.status().physical_stop_verified end,
        sample=function(previous)
            assert(previous.context_generation==options.owned().context_generation,"inventory checkpoint context changed")
            assert(emu.framecount()>=previous.frame,"inventory checkpoint frame moved backwards")
            if emu.framecount()==previous.frame then return nil end
            return M.capture(options)
        end})or nil
    function self:step(admitted)
        if not admitted then return false end
        if options.free_service and self.enrolled and self.signals then options.owned();return false end
        local baseline=assert(options.journal.store:read()).observation
        if baseline.initial_inventory then
            local recorded=initial_payload(baseline.initial_inventory)
            local generation=recorded and recorded.context_generation or M.initial_cursor(baseline.initial_inventory).context_generation
            assert(generation==options.owned().context_generation,
                "initial inventory belongs to a replaced context; reconciliation required")
            if options.engine_signals and baseline.initial_inventory.phase=="acknowledged"then
                if not self.signals then
                    if options.source_owned then
                        assert(JSON.encode(options.source_owned())==JSON.encode(options.owned()),"source observation identity differs from held owner")
                    end
                    self.signals=require("gen1_engine_signals").new({journal=options.journal,variant=options.variant,
                        final_sha1=gameinfo.getromhash():lower(),owned=options.source_owned or options.owned,
                        fast_path=options.free_service,
                        held=function()return options.host.status().physical_stop_verified or (options.at_boundary and options.at_boundary()==true)end})
                end
                if not options.free_service then self.signals:flush()end
            end
            if options.bootstrap and baseline.initial_inventory.phase=="acknowledged" and not baseline.bootstrap then
                -- Exactly one raw New Game receipt, only after enrollment is
                -- acknowledged. A launch that never witnessed New Game, or whose
                -- observer failed, publishes nothing and keeps its hold.
                local witness=options.bootstrap.status()
                if witness.complete and not witness.failed then
                    local event={event="bootstrap_observation",payload=assert(options.bootstrap.peek())}
                    baseline.bootstrap={phase="queued",payload=event}
                    assert(options.journal:append(event,baseline))
                    return true
                end
            end
            if options.free_service then -- the loop publishes the inventory stream inside its batches
                self.enrolled=baseline.initial_inventory.phase=="acknowledged"and baseline.bootstrap and baseline.bootstrap.phase=="acknowledged"
                return false
            end
            return assert(stream):step()
        end
        local context=assert(JSON.decode(assert(JSON.encode(options.owned()))));local frame=emu.framecount()
        local payload=M.capture(options)
        local event={event="initial_observation",payload=payload}
        baseline.initial_inventory={phase="queued",payload=event}
        assert(options.journal:append(event,baseline))
        assert(frame==emu.framecount() and JSON.encode(options.owned())==JSON.encode(context),"initial observation owner changed during publication")
        return true
    end
    function self:close()if self.signals then self.signals:close()end end
    return self
end
function M.acknowledge_event(payload,operation_id,baseline)
    if payload.event=="observation"then
        assert(payload.schema=="rby-observation-v1" and type(payload.sequence)=="number"
            and payload.sequence%1==0 and payload.sequence>=1 and type(payload.frame)=="number"
            and payload.frame%1==0 and payload.frame>=0,"invalid acknowledged observation cursor")
        assert(type(baseline.observation_sequence)=="number"
            and baseline.observation_sequence>=payload.sequence,
            "acknowledged observation exceeds the persisted producer cursor")
        local prior=baseline.observation_cursor
        if prior then
            assert(payload.sequence==prior.sequence+1 and payload.frame>=prior.frame,
                "acknowledged observation cursor skipped or moved backwards")
        end
        baseline.observation_cursor={sequence=payload.sequence,operation_id=operation_id,frame=payload.frame}
        return baseline
    end
    if payload.event=="inventory_observation"then
        return Stream.acknowledge("inventory_stream","inventory_observation",payload,operation_id,baseline)
    end
    local entry=baseline.initial_inventory
    if payload.event=="initial_observation" and entry and entry.phase=="queued"
        and JSON.encode(entry.payload)==JSON.encode(payload)then
        entry.phase="acknowledged";entry.operation_id=operation_id;return baseline
    end
    local proof=baseline.bootstrap
    if payload.event=="bootstrap_observation" and proof and proof.phase=="queued"
        and JSON.encode(proof.payload)==JSON.encode(payload)then
        proof.phase="acknowledged";proof.operation_id=operation_id;return baseline
    end
end
return M
