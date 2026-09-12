-- Ordinary frames consume server-issued credits through the one bounded owner.
-- Every step persists its observed signals before another physical step. A closed
-- range is a real journal event; its ACK precedes every subsequent grant.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Window=require("execution_window")
local M={SCHEMA="rby-client-frame-progress-v1",STORE="rby-client-frame-store-v1"}
function M.initial()return {schema=M.STORE,progress=JSON.null}end
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function same(a,b)return assert(Canonical.encode(a))==assert(Canonical.encode(b))end
local function local_same(a,b)return assert(JSON.encode(a))==assert(JSON.encode(b))end
local function number(v)return type(v)=="number"and v%1==0 and v>=0 and v<=9007199254740991 end
function M.acknowledge_event(payload,operation,baseline)
    local progress=baseline.frame_progress
    assert(progress and progress.schema==M.SCHEMA and progress.phase=="queued"
        and same(progress.completion,payload),"frame ACK differs from its durable completion")
    progress.phase="idle";progress.sequence=payload.receipt.sequence;progress.frame=payload.receipt.after
    progress.last_operation_id=operation;progress.active=nil;progress.completion=nil
    return baseline
end
function M.new(options)
    local journal=assert(options.journal)
    assert(type(options.owned)=="function"and type(options.boundary)=="function"and type(options.inventory)=="function"
        and type(options.signals)=="function"and type(options.clock)=="function"and options.host,"owned frame client dependencies required")
    local self={binding=nil,last_control=nil,failed=nil,close_requested=false,
        metrics={steps=0,persist_seconds=0,request_seconds=0,revocations=JSON.array()}}
    local function sha(value)return journal.store.backend.sha256(assert(Canonical.encode(value)))end
    local cached_revision,cached_baseline,cached_marker,cached_state
    local progress_revision,cached_progress
    local function read()
        local revision=journal.store.revision and assert(journal.store:revision())
        if revision==nil or cached_revision~=revision or cached_state==nil then
            cached_state=assert(journal.store:read());cached_baseline=cached_state.observation;cached_revision=revision
            cached_marker=cached_baseline.frame_progress and copy(cached_baseline.frame_progress)or nil
        end
        local baseline=cached_baseline
        local progress=baseline.frame_progress
        local native_api,native
        if baseline.native_frame_accounting then
            native_api=require("gen1_native_frame_client")
            native=native_api.validate_marker(baseline,options.owned(),assert(options.native_host,
                "native accounting requires the bounded native owner").status(),emu.framecount())
        end
        self.native_borrowed=native~=nil and native.phase=="borrowed"
        if self.native_borrowed then
            assert(cached_marker and local_same(cached_marker,native.baseline),
                "native loan changed the committed idle ordinary baseline")
        end
        local function adopt_native(current)
            if not native or native.phase~="handed_back"then return current,false end
            local handoff=assert(native.handoff)
            assert(handoff.phase=="acknowledged"and cached_marker
                and cached_marker.native_handoff_operation_id==handoff.operation_id,
                "native handoff was not atomically acknowledged with ordinary progress")
            if current and current.native_handoff_operation_id==handoff.operation_id then
                if current.acquisition_source then
                    assert(current.acquisition_source.frame==current.frame
                        and current.acquisition_source.native_handoff_operation_id==handoff.operation_id,
                        "native handoff lost its acknowledged acquisition source baseline")
                end
                return current,false
            end
            local previous=current or native.baseline
            local adopted=native_api.adopt(native,previous,options.owned(),emu.framecount())
            if previous.acquisition_source then
                local source=assert(options.acquisitions and options.acquisitions(),"native handoff lost acquisition source owner")
                adopted.acquisition_source=source:adopt_native_handoff(previous.acquisition_source,native)
            end
            assert(local_same(adopted,cached_marker),"native handoff differs between main and auxiliary progress")
            return adopted,true
        end
        if options.progress_store then
            local current=assert(options.progress_store:revision())
            if progress_revision~=current then
                local state=assert(options.progress_store:read())
                assert(state.schema==M.STORE,"unsupported client frame store")
                cached_progress=state.progress~=JSON.null and state.progress or nil;progress_revision=current
            end
            progress=cached_progress
            -- Main journal publication/ACK is authoritative if a crash occurred
            -- between the two stores. A matched queued event must never run again.
            local marker=cached_marker
            local adopted
            progress,adopted=adopt_native(progress)
            if adopted then -- Main ACK is authoritative; complete its auxiliary cursor handoff.
                assert(options.progress_store:commit({schema=M.STORE,progress=progress}))
                progress_revision=assert(options.progress_store:revision())
            elseif marker and not progress then progress=copy(marker)
            elseif marker and progress and marker.phase=="queued"and progress.phase=="active"
                and marker.sequence==progress.sequence then
                assert(marker.frame==progress.frame and same(marker.active.scope,progress.active.scope),
                    "published frame closure differs from auxiliary physical progress")
                progress=copy(marker)
            elseif marker and progress and marker.phase=="idle"and marker.sequence>progress.sequence then
                assert(marker.sequence==progress.sequence+1 and marker.frame==progress.frame,
                    "acknowledged frame differs from auxiliary physical progress")
                progress=copy(marker)
            end
            cached_progress=progress;baseline.frame_progress=progress
        else
            progress=adopt_native(progress);baseline.frame_progress=progress
        end
        if progress then
            assert(progress.schema==M.SCHEMA and number(progress.sequence)and number(progress.frame)
                and progress.context_generation==options.owned().context_generation,"frame progress belongs to another context")
            if self.native_borrowed then
                assert(progress.phase=="idle"and progress.frame==native.baseline.frame
                    and progress.sequence==native.baseline.sequence
                    and same(progress.acquisition_source,native.baseline.acquisition_source),
                    "native loan replaced the frozen ordinary/source baseline")
            else
                assert(progress.frame==emu.framecount(),"physical frame differs from persisted frame progress")
            end
        end
        if cached_marker and cached_marker.phase=="idle"
            and cached_marker.sequence>(self.metrics.acknowledged_sequence or 0)then
            self.metrics.acknowledged_sequence=cached_marker.sequence
            if self.metrics.first_grant_request_at then
                self.metrics.end_to_end_seconds=options.clock()-self.metrics.first_grant_request_at
                self.metrics.acknowledged_steps=cached_marker.frame-self.metrics.first_frame
            end
        end
        return baseline,progress
    end
    local function saved(baseline)
        cached_baseline=baseline;cached_revision=journal.store.revision and assert(journal.store:revision())
        cached_marker=baseline.frame_progress and copy(baseline.frame_progress)or nil
        cached_state=nil -- An event publication may have changed the outbox.
    end
    local function save(baseline)
        if options.progress_store then
            local progress=assert(baseline.frame_progress)
            assert(options.progress_store:commit({schema=M.STORE,progress=progress}))
            cached_progress=progress;progress_revision=assert(options.progress_store:revision())
        else
            assert(journal:append_many(JSON.array(),baseline));saved(baseline)
        end
    end
    local function events_block()
        read()
        for _,event in ipairs(cached_state.outbox)do
            if event.payload.event~="sync"then return true end
        end
        return false
    end
    local function commands_pending()
        read()
        for _,command in ipairs(cached_state.inbox)do if not command.outcome then return true end end
        return false
    end
    local function scope()
        local _,p=read();local active=p and p.active
        if not self.binding or not active or p.phase~="active"or active.scope.binding_digest~=self.binding.binding_digest then return nil end
        return active.scope
    end
    local function new_window()
        return Window.new({clock=options.clock,current_scope=scope,max_frames=120,max_lifetime_ms=1000,max_operation_frames=120,
            new_nonce=options.new_nonce,verify_grant=function(packet)
                local _,p=read();return p and p.active and packet.proof_digest==sha(p.active.evidence)
            end})
    end
    self.window=new_window()
    local rate=options.rate or {numerator=262144,denominator=4389}
    local pacer=require("frame_pacer").new({clock=options.clock,numerator=rate.numerator,denominator=rate.denominator})
    local function bootstrap_ready(baseline)
        return baseline.initial_inventory and baseline.initial_inventory.phase=="acknowledged"
            and baseline.bootstrap and baseline.bootstrap.phase=="acknowledged" and options.signals()~=nil
            and(not options.acquisitions or options.acquisitions()~=nil)
    end
    function self:blocks_commands()
        local _,p=read();return self.native_borrowed or p~=nil and p.phase~="idle"
    end
    function self:control(binding)
        self.last_control=options.clock();self.binding=copy(binding)
    end
    function self:request(binding,control)
        local began=options.clock()
        self.binding=copy(binding)
        if self.failed or not control.admitted or not control.held or options.host.status().user_paused==true then return nil end
        local baseline,p=read()
        if self.native_borrowed then return nil end
        if p and p.phase~="idle"then return nil end
        if not bootstrap_ready(baseline)or commands_pending()or #cached_state.outbox>0 then return nil end
        self.close_requested=false -- Fresh admission may request only when no prior range is open.
        if not p then
            local initial=baseline.initial_inventory.payload.payload
            assert(initial.frame==emu.framecount(),"initial frame changed before accounting")
            p={schema=M.SCHEMA,context_generation=options.owned().context_generation,sequence=0,frame=initial.frame,
                inventory_frame=initial.frame,phase="idle"};baseline.frame_progress=p
        end
        local acquisitions=options.acquisitions and options.acquisitions()
        if acquisitions then
            if not p.acquisition_source then p.acquisition_source=acquisitions:initial(p.frame)end
            assert(acquisitions:ready(p.acquisition_source))
        end
        local boundary=options.boundary()
        local evidence={schema="rby-frame-request-v1",boundary=boundary,sequence=p.sequence+1}
        local operation=assert((options.new_nonce or require("platform_identity").new_nonce)())
        local selected={operation_id=operation,operation_digest=sha({event="frame_grant",evidence=evidence}),
            context_generation=p.context_generation,binding_digest=binding.binding_digest,phase="ordinary"}
        p.phase="active";p.active={scope=selected,evidence=evidence,before=p.frame,steps=0,signals=JSON.array(),request_started=began}
        if acquisitions then p.active.acquisitions=JSON.array()end
        save(baseline)
        -- A new, durably distinct operation follows the previous range's ACK.
        -- Per-operation window bookkeeping cannot grow with hours of gameplay.
        self.window=new_window()
        self.window_issued=options.clock()
        local challenge=assert(self.window:challenge())
        self.metrics.request_seconds=options.clock()-began
        return {window=challenge,evidence=copy(evidence)}
    end
    function self:accept(packet)
        local baseline,p=read()
        assert(not self.native_borrowed or packet==nil,"ordinary grant arrived while native owner borrowed execution")
        if packet==nil then
            -- An explicit refusal to this challenge consumed no physical frame.
            if p and p.phase=="active"and not p.active.grant then
                self.metrics.declined_frame=p.frame
                p.phase="idle";p.active=nil;save(baseline);self.window:revoke("ordinary request declined")
            end
            return true
        end
        assert(p and p.phase=="active"and not p.active.grant,"ordinary grant has no outstanding request")
        local accepted,why=self.window:accept(packet)
        if not accepted then return false,why end
        if not self.metrics.first_grant_request_at then
            self.metrics.first_grant_request_at=p.active.request_started;self.metrics.first_frame=p.active.before
        end
        p.active.grant=copy(packet);p.active.deadline=assert(self.window_issued)+packet.ttl_ms/1000
        save(baseline);return true
    end
    function self:revoke(reason)
        self.metrics.revocations[#self.metrics.revocations+1]={reason=tostring(reason),frame=emu.framecount(),at=options.clock()}
        if #self.metrics.revocations>16 then table.remove(self.metrics.revocations,1)end
        self.window:revoke(reason);self.binding=nil;self.last_control=nil;self.close_requested=true;self.revoke_reason=tostring(reason)
    end
    function self:authorize(selected,checkpoint)
        if self.failed or self.close_requested or not self.last_control or options.clock()-self.last_control>=1 then return false end
        local _,p=read()
        if self.native_borrowed then return false end
        if not p or p.phase~="active"or not p.active.grant or p.frame~=checkpoint.frame
            or commands_pending()or events_block()then return false end
        local hooks=options.signals()
        assert(hooks and hooks:status().pending==0 and not hooks:status().failed,"previous frame signals were not persisted")
        if options.acquisitions then
            assert(options.acquisitions():ready(p.acquisition_source))
        end
        return self.window:consume(selected)==true
    end
    local function close_range(baseline,p)
        assert(not self.native_borrowed,"native owner still owns the physical frame range")
        local active=assert(p.active)
        assert(active.grant,"unanswered frame grant requires reconciliation")
        local boundary=options.boundary()
        assert(boundary.frame==p.frame,"closing frame changed")
        local inventory=JSON.null
        if p.frame>p.inventory_frame then inventory=options.inventory()or JSON.null end
        if inventory~=JSON.null then assert(inventory.frame==p.frame);p.inventory_frame=p.frame end
        local signals=JSON.null
        if #active.signals>0 then
            local old=baseline.engine_signals
            local seq=(old and old.sequence or 0)+1
            signals=options.signals():batch(active.signals,seq)
            baseline.engine_signals={context=copy(options.owned()),sequence=seq}
        end
        local bundle={boundary=boundary,inventory=inventory,engine_signals=signals}
        if active.acquisitions then bundle.acquisitions=copy(active.acquisitions)end
        if options.native_checkpoint and inventory~=JSON.null then
            local native=options.native_checkpoint(inventory)
            assert(emu.framecount()==p.frame,"native checkpoint changed the held frame")
            if native then bundle.native_checkpoint=native end
        end
        local receipt={schema="slink-frame-progress-receipt-v1",sequence=p.sequence+1,scope=copy(active.scope),
            before=active.before,after=p.frame,steps=active.steps,observations_digest=sha(bundle)}
        local event={event="frame_complete",receipt=receipt,bundle=bundle}
        p.phase="queued";p.completion=copy(event);p.metrics=copy(self.metrics)
        if options.observe then
            assert(options.observe(JSON.array({event}),baseline))
        else
            assert(journal:append(event,baseline))
        end
        saved(baseline)
        if options.progress_store then save(baseline)end
        self.window:revoke("frame range awaits durable ACK");self.close_requested=false
    end
    function self:flush_closed_after_response()
        -- Called only after the owner's control response was accepted. Its
        -- request is still visible inside durable_runtime.receive, but no I/O
        -- reply remains to wait for. Publish the stopped range before another
        -- control/sync request can keep the ordinary loop perpetually busy.
        if self.failed then return false,self.failed end
        local ok,why=pcall(function()
            local baseline,p=read()
            if self.native_borrowed then return end
            if not p or p.phase~="active"or not p.active.grant then return end
            local ending=p.active.deadline and options.clock()>=p.active.deadline-0.05
            if self.close_requested or ending or not self.window:ready()then close_range(baseline,p)end
        end)
        if not ok then self.failed=tostring(why);self.window:revoke(self.failed);return false,self.failed end
        return true
    end
    function self:step(admitted)
        if self.failed then return false,self.failed end
        local ok,why=pcall(function()
            local baseline,p=read()
            if self.native_borrowed then return end
            if not p or p.phase~="active"then self.close_requested=false;return end
            if not p.active.grant then
                if self.close_requested then error("unanswered ordinary grant requires reconciliation: "..tostring(self.revoke_reason),0)end
                return
            end
            local pending=commands_pending()or events_block()
            -- Leave a bounded setup margin before entering the native actuator;
            -- its final consume remains mandatory and may still refuse a stall.
            local ending=p.active.deadline and options.clock()>=p.active.deadline-0.05
            if not admitted or pending or self.close_requested or ending or not self.window:ready()then
                self.close_requested=true
                if options.inflight and options.inflight()then return end
                close_range(baseline,p);return
            end
            local allowed,error=pacer:take(true,options.host.status().user_paused==true)
            assert(error==nil,error)
            if not allowed then return end
            local before=p.frame
            self.metrics.started=self.metrics.started or options.clock()
            assert(options.step_one(copy(p.active.scope)))
            assert(emu.framecount()==before+1,"bounded step advanced an unexpected frame count")
            local hooks=assert(options.signals());local captured=hooks:peek()
            local acquisition_owner=options.acquisitions and assert(options.acquisitions())
            local acquisitions=acquisition_owner and acquisition_owner:prepare(p.acquisition_source)
            p.frame=before+1;p.active.steps=p.active.steps+1
            for _,signal in ipairs(captured)do p.active.signals[#p.active.signals+1]=copy(signal)end
            assert(#p.active.signals<=32,"frame signal batch exceeds source bounds")
            if acquisitions then
                p.acquisition_source=acquisitions.state
                for _,row in ipairs(acquisitions.receipts)do p.active.acquisitions[#p.active.acquisitions+1]=copy(row)end
                assert(#p.active.acquisitions<=16,"frame acquisition batch exceeds source bounds")
            end
            local published=options.clock()
            save(baseline) -- Physical return and hooks are durable before drain/next step.
            self.metrics.persist_seconds=self.metrics.persist_seconds+options.clock()-published
            self.metrics.steps=self.metrics.steps+1;self.metrics.elapsed=options.clock()-self.metrics.started
            assert(hooks:drain(captured))
            if acquisitions then assert(acquisition_owner:drain(acquisitions))end
            local stop=options.stop_after_step and options.stop_after_step()==true
            if stop or #captured>0 or acquisitions and #acquisitions.receipts>0 or not self.window:ready()then
                self.close_requested=true
                if not options.inflight or not options.inflight()then close_range(baseline,p)end
            end
        end)
        if not ok then self.failed=tostring(why);self.window:revoke(self.failed);return false,self.failed end
        return true
    end
    function self:status()
        local _,p=read()
        return {schema=M.SCHEMA,failed=self.failed,phase=self.native_borrowed and "native_borrowed"or p and p.phase or "awaiting_enrollment",
            sequence=p and p.sequence or 0,frame=p and p.frame or emu.framecount(),window=self.window:status(),
            metrics=copy(self.metrics),ordinary_execution=false,native_borrowed=self.native_borrowed or false}
    end
    function self:enrollment()
        local baseline=read()
        return baseline.initial_inventory and baseline.initial_inventory.phase,
            baseline.bootstrap and baseline.bootstrap.phase
    end
    return self
end
return M
