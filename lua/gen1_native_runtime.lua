-- Owned native command service: real durable TCP, command windows, cartridge-rate
-- frames and verified SaveRAM. Ordinary gameplay/bootstrap and prompt scheduling
-- are separate bindings; unknown commands stay held rather than being discarded.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Runtime=require("gen1_runtime")
local Preparation=require("gen1_trade_preparation")
local Native=require("gen1_native_trade_executor")
local Prompt=require("gen1_partner_prompt_executor")
local M={}
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
-- Compose these callbacks before opening the ONE shared client journal. Native
-- typed completion events must not fall back to generic command acknowledgements.
function M.journal_options(observation,native_owner)
    local native=require("gen1_trade_events")
    if observation==nil and native_owner==nil then return native end
    observation=observation or {}
    assert(type(observation)=="table"and(native_owner==nil or type(native_owner)=="function"),"journal observation callbacks required")
    local result={}
    for _,name in ipairs({"completion_event","acknowledge_event"})do
        local a,b=native[name],observation[name]
        assert(b==nil or type(b)=="function","invalid shared journal callback")
        result[name]=function(...)
            local first=a and a(...)or nil
            local second=b and b(...)or nil
            assert(first==nil or second==nil,"multiple journal projections claimed one event")
            if name=="acknowledge_event"and native_owner then
                local owner=native_owner()
                if owner and owner.frame_accounting then
                    local payload,operation,baseline=...
                    local extra=owner.frame_accounting:acknowledge(payload,operation,first or second or baseline)
                    if extra~=nil then return extra end
                end
            end
            return first or second
        end
    end
    return result
end
function M.validate_manifest(manifest,variant)
    local profile=assert(require("gen1_companion_profiles").profiles[variant],"native RBY layout is unavailable")
    for _,field in ipairs({"schema","variant","ram","foreground","native_calls","readback",
        "receptionist","entry","size","payload_sha256","test_probe"})do
        assert(manifest[field]~=nil and Canonical.encode(manifest[field])==Canonical.encode(profile.manifest[field]),
            "native execution layout differs from the qualified profile: "..field)
    end
    return true
end
function M.new(options)
    local mem,manifest=options.memory,copy(options.manifest)
    local player=options.player
    assert(player=="a" or player=="b","native runtime player required")
    assert(manifest.variant==options.variant and gameinfo.getromhash():lower()==manifest.final_sha1,
        "loaded native runtime cartridge differs")
    M.validate_manifest(manifest,options.variant)
    local embedded=options.embedded==true
    assert(not options.frame_accounting or embedded,"native frame accounting requires the shared ordinary owner")
    if embedded then
        assert(type(options.context)=="table" and type(options.read_context)=="function"
            and type(options.clock)=="function" and type(options.host)=="table"
            and type(options.journal)=="table" and options.journal.store
            and type(options.read_runtime_status)=="function" and type(options.observe)=="function",
            "embedded native service needs its existing owner, context, clock, journal, observe and runtime-status reader")
    else
        assert(options.host==nil and options.journal==nil,"shared native owners require explicit embedded mode")
    end
    local context
    if options.context then context=copy(options.context)
    else
        local nonce=require("platform_identity").new_nonce
        context={context_generation=assert(nonce()),physical_instance=assert(nonce()),
            save_identity={ot_id=string.format("%04X",mem.readPlayerId()),trainer_name=mem.readPlayerName()}}
    end
    for _,name in ipairs({"context_generation","physical_instance"})do
        assert(type(context[name])=="string" and #context[name]==32 and context[name]:match("^[0-9a-f]+$"),"exact native owner context required")
    end
    local clock=options.clock or assert(require("platform_clock").new())
    assert(type(clock)=="function","native monotonic clock required")
    local self={binding=nil,current=nil,pending_proof=nil,last_service=nil,control=nil,timings={},embedded=embedded,
        metrics={services=0,service_seconds=0,frame_seconds=0,discarded_completed_grants=0,terminal_readback_deferred=0}}
    local adapters
    local function sha(v)return self.journal.store.backend.sha256(assert(Canonical.encode(v)))end
    local function read_context()
        if options.read_context then assert(Canonical.encode(options.read_context())==Canonical.encode(context),"injected native context changed")end
        local identity_matches
        if options.identity_check then identity_matches=options.identity_check()==true
        else identity_matches=mem.readPlayerName()==context.save_identity.trainer_name end
        assert(gameinfo.getromhash():lower()==manifest.final_sha1
            and string.format("%04X",mem.readPlayerId())==context.save_identity.ot_id
            and identity_matches,"owned native ROM/save changed")
        return copy(context)
    end
    read_context()
    local function scope()
        local current=self.current
        if not self.binding or not current or not current.intent or not adapters or not adapters[current.body.cmd] then return nil end
        local phase=current.body.cmd
        if phase=="native_trade_prepare" then
            local stage,schema=self.preparation.stage(current.command_id)
            if stage=="save"then phase="native_trade_prepare_save"
            elseif stage~="prompt" or schema~="rby-prompt-close-intent-v1"then return nil end
        elseif
        current.body.cmd~="native_receptionist" and current.body.cmd~="native_trade_commit" and current.body.cmd~="native_trade_release"
            and current.body.cmd~="native_trade_prompt" and current.intent.schema~="rby-prompt-close-intent-v1"then return nil end
        return {operation_id=current.command_id,operation_digest=current.digest,
            context_generation=context.context_generation,binding_digest=self.binding.binding_digest,phase=phase}
    end
    self.window=require("execution_window").new({clock=clock,current_scope=scope,max_operation_frames=60000,
        verify_grant=function(packet)return self.pending_proof~=nil and packet.proof_digest==self.pending_proof end})
    local function frames_pending(body)
        return (self.native and self.native.frames_pending(body)) or (self.prompt and self.prompt.frames_pending(body))
            or (self.receptionist and self.receptionist.frames_pending(body)) or false
    end
    function self.authorize_step(selected)
        read_context()
        return self.binding~=nil and self.control~=nil and self.control.admitted and self.current~=nil
            and self.last_service~=nil and clock()-self.last_service<0.25
            and frames_pending(self.current.body) and self.window:consume(selected)
    end
    self.host=options.host or require("platform_bounded_execution").new({profile="gambatte",owner_id=context.physical_instance,
        expected_host=require("platform_execution").supported_profile("gambatte"),authorize=self.authorize_step})
    local owner=self.host.status()
    assert(type(owner)=="table" and type(owner.host)=="table" and owner.host.owner_id==context.physical_instance
        and owner.host.physical_stop_verified and owner.single_frame_only and owner.frame_callbacks_suppressed
        and owner.load_state_invalidation and owner.owner_exit_invalidation,"native service requires the existing qualified bounded owner")
    local Journal=require("client_journal")
    local Store=require("state_store")
    local Storage=require("platform_storage")
    local binding={schema="rby-native-runtime-storage-v1",run_id=options.run_id,player=player,
        final_sha1=manifest.final_sha1,save_identity=context.save_identity}
    if embedded then
        self.journal=options.journal;self.command_store=self.journal.store
    else
        self.command_store=assert(Store.open(assert(Storage.new(options.storage_directory.."/journal.json")),binding,Journal.initial()))
        self.journal=assert(Journal.open(self.command_store,nil,M.journal_options(options.observation)))
    end
    if options.frame_accounting then
        self.frame_accounting=require("gen1_native_frame_client").new({journal=self.journal,host=self.host,
            owned=read_context,memory=mem,manifest=manifest,adopt_sources=options.adopt_sources,observe=options.observe})
    end
    self.native_store=assert(Store.open(assert(Storage.new(options.storage_directory.."/native.json")),binding,Native.initial()))
    self.prompt_store=assert(Store.open(assert(Storage.new(options.storage_directory.."/prompt.json")),binding,Prompt.initial()))
    self.preparation_store=assert(Store.open(assert(Storage.new(options.storage_directory.."/preparation.json")),binding,
        require("staged_command").initial()))
    local function refresh()
        local entry=assert(self.journal:pending_commands())[1]
        if not entry then self.current=nil;return end
        local body=Runtime.unwrap(entry.body,player)
        local fingerprint=sha({command_id=entry.command_id,command_sequence=entry.command_sequence,body=body})
        if self.current and self.current.digest~=fingerprint then self.window:revoke("oldest command changed")end
        self.current={command_id=entry.command_id,command_sequence=entry.command_sequence,body=body,
            digest=fingerprint,intent=entry.intent}
    end
    -- Call for the shared owner's verified control state even when no native
    -- command exists yet: receptionist discovery precedes command publication.
    function self.update_control(value,control)
        read_context();self.binding=copy(value);self.control=copy(control);refresh()
    end
    local function authorized(action,body,identity)
        read_context()
        local current=self.current
        if not self.binding or not self.control or not self.control.admitted or not current
            or current.command_id~=identity.command_id or current.command_sequence~=identity.command_sequence
            or sha(body)~=sha(current.body) then return false end
        if action=="arm" or action=="release"then return self.window:ready()end
        if action=="native_ui"then
            local selected=scope()
            return selected~=nil and selected.phase=="native_receptionist" and self.window:ready()
        end
        if action=="arm_full_save" or action=="full_save_ready"then
            local selected=scope()
            local ready=selected~=nil and selected.phase=="native_trade_prepare_save" and self.window:ready()
            if not ready then self.metrics.full_save_denied={action=action,phase=selected and selected.phase,
                reason=self.window:status().reason}end
            return ready
        end
        return true
    end
    self.native=Native.new({memory=mem,manifest=manifest,store=self.native_store,player=player,
        context_generation=function()return context.context_generation end,authorize=authorized})
    self.prompt=Prompt.new({memory=mem,manifest=manifest,store=self.prompt_store,journal=self.journal,player=player,
        context_generation=function()return context.context_generation end,authorize=authorized})
    local saved=require("gen1_saved_trade_executor").new({native=self.native,journal=self.journal,
        persist_save=function(receipt,intent,identity)
            assert(authorized("save",self.current.body,identity),"owned native save authority unavailable")
            local provider=require("platform_saveram").new({profile="gambatte",path=options.saveram_path,directory=options.saveram_directory,
                authorize=function()return authorized("save",self.current.body,identity)
                    and self.native_store:read().phase=="complete"end})
            local raw={};for i=0,0x7fff do raw[#raw+1]=memory.read_u8(i,"CartRAM")end
            local encoded=mem.bytesToHex(raw)
            local result=provider:flush(encoded)
            self.saved_image={command_id=identity.command_id,sha256=result.sha256,hex=encoded}
            return result
        end,save_image=function(file,identity)
            assert(self.saved_image and self.saved_image.command_id==identity.command_id
                and self.saved_image.sha256==file.sha256,"save image differs from the verified flush")
            return self.saved_image.hex
        end})
    local preparation=Preparation.new({memory=mem,manifest=manifest,player=player,
            context_generation=function()return context.context_generation end,sha256=self.command_store.backend.sha256,
            authorize=authorized})
    self.full_save=require("gen1_full_save").new({memory=mem,manifest=manifest,player=player,preparation=preparation,
        context_generation=function()return context.context_generation end,sha256=self.command_store.backend.sha256,
        authorize=authorized,persist_save=function(encoded,identity)
            local provider=require("platform_saveram").new({profile="gambatte",path=options.saveram_path,directory=options.saveram_directory,
                authorize=function()return authorized("full_save_ready",self.current.body,identity)end})
            return provider:flush(encoded)
        end})
    self.preparation=require("gen1_prepared_save").new({memory=mem,manifest=manifest,prompt=self.prompt,
        store=self.preparation_store,save=self.full_save,preparation=preparation,
        context_generation=function()return context.context_generation end})
    adapters={native_trade_commit=saved,native_trade_release=self.native.release_executor(),native_trade_prompt=self.prompt,
        native_trade_prepare=self.preparation}
    adapters.native_trade_abort=require("gen1_trade_abort").new({memory=mem,manifest=manifest,player=player,
        prompt=self.prompt,native_store=self.native_store,context_generation=function()return context.context_generation end,
        sha256=self.command_store.backend.sha256,authorize=authorized})
    if options.receptionist then
        local UI=require("gen1_receptionist_executor")
        self.receptionist_store=assert(Store.open(assert(Storage.new(options.storage_directory.."/receptionist.json")),binding,UI.initial()))
        self.receptionist=UI.new({memory=mem,manifest=manifest,player=player,journal=self.journal,observe=options.observe,
            store=self.receptionist_store,context_generation=function()return context.context_generation end,authorize=authorized})
        adapters.native_receptionist=self.receptionist
        self.entry_sent=self.command_store:read().observation.receptionist_entry~=nil
    end
    local router={}
    for _,name in ipairs({"prepare","classify","apply","receipt"})do
        router[name]=function(body,...)
            local adapter=assert(adapters[body.cmd],"native command adapter is not selected")
            return adapter[name](body,...)
        end
    end
    local operations={
        request=function(value,control)
            self.update_control(value,control)
            if self.frame_accounting then
                if self.frame_accounting:pending()then return nil end
                if not self.current or not adapters[self.current.body.cmd]then
                    local query=self.frame_accounting:request();if query then return query end
                end
            end
            local selected=scope();if not selected then return nil end
            local current=self.current
            local state=self.host.status();local host=state.host
            -- In the embedded free loop a command may arrive during the same
            -- ordinary tick that sends CONTROL, before the next boundary arms
            -- the native vote. Do not send unbounded evidence (which the server
            -- NACKs/disconnects); the armed next CONTROL requests the window.
            if embedded and not (state.single_frame_only and state.frame_callbacks_suppressed
                and state.load_state_invalidation and state.owner_exit_invalidation
                and host.held and host.host_blocked and host.lease_owned and host.physical_stop_verified
                and not state.failed and not host.failed and not host.closed)then return nil end
            local stage,child_intent
            if current.body.cmd=="native_trade_prepare"then stage,child_intent=self.preparation.current(current.command_id)end
            local intent=child_intent or current.intent
            local source=current.body.cmd=="native_receptionist" and self.receptionist or stage=="save" and self.full_save or
                (current.body.cmd=="native_trade_prompt" or intent.schema=="rby-prompt-close-intent-v1")
                and self.prompt or self.native
            local evidence={schema="rby-native-window-evidence-v1",command_id=current.command_id,
                command_sequence=current.command_sequence,context_generation=context.context_generation,
                final_sha1=manifest.final_sha1,host={owner_id=host.owner_id,capability_id=host.capability_id,
                    process_id=host.process_id,frame=state.expected_frame,steps=state.steps,
                    held=host.held and host.host_blocked and host.lease_owned and host.physical_stop_verified,
                    bounded=state.single_frame_only and state.frame_callbacks_suppressed and state.load_state_invalidation
                        and state.owner_exit_invalidation,failed=state.failed~=nil or host.failed or host.closed},
                native=source.window_evidence(current.body,intent,
                    {command_id=current.command_id,command_sequence=current.command_sequence})}
            if self.frame_accounting then evidence.accounting=self.frame_accounting:acceptance()end
            self.pending_proof=sha(evidence)
            self.pending_request=assert(self.window:challenge());self.pending_sequence=current.command_sequence
            return {window=copy(self.pending_request),evidence=evidence}
        end,
        accept=function(packet)
            if self.frame_accounting and packet and packet.schema=="rby-native-handoff-query-v1"then
                return self.frame_accounting:accept(packet)
            end
            if packet==nil then
                self.pending_request=nil;self.pending_proof=nil;self.window:revoke("server withheld native frames");return true
            end
            local current=scope();local request=self.pending_request
            if request and (not current or Canonical.encode(current)~=Canonical.encode(request.scope)) then
                -- A native command can finish while its renewal response is in
                -- flight. Discard that exact now-unneeded grant after proving
                -- durable completion; never attach it to the next command.
                assert(packet.schema==require("execution_window").SCHEMA and packet.challenge==request.challenge
                    and Canonical.encode(packet.scope)==Canonical.encode(request.scope)
                    and packet.proof_digest==self.pending_proof,"obsolete grant differs from its request")
                local entry=self.journal:get_command(request.scope.operation_id)
                local stage=request.scope.phase=="native_trade_prepare_save" and "save"
                    or request.scope.phase=="native_trade_prepare" and "prompt" or nil
                assert(entry and entry.outcome=="ACK" or self.command_store:read().command_floor>=self.pending_sequence
                    or stage and self.preparation.completed(request.scope.operation_id,stage),
                    "obsolete grant has no durable completed command")
                self.window:revoke("native command completed before its renewal response")
                self.pending_request=nil;self.pending_proof=nil
                self.metrics.discarded_completed_grants=self.metrics.discarded_completed_grants+1
                if self.frame_accounting then self.frame_accounting:accepted_grant(packet,self.pending_sequence)end
                return true
            end
            local ok,why=self.window:accept(packet)
            if not ok then self.metrics.native_window_refusal=tostring(why)end
            if ok and self.frame_accounting then self.frame_accounting:accepted_grant(packet,self.pending_sequence)end
            self.pending_proof=nil;return ok,why
        end,
        authorize_apply=function(body,intent,identity,control)
            self.control=copy(control)
            return authorized("arm",body,identity),"waiting for a verified native command window"
        end,
        revoke=function(why)
            if self.frame_accounting then self.frame_accounting:revoke()end
            if self.current and self.current.intent then
                self.metrics.first_operation_revocation=self.metrics.first_operation_revocation or tostring(why)
            end
            if (self.native and self.native.execution_phase=="armed") or (self.prompt and self.prompt.execution_phase=="armed") then
                self.metrics.first_native_revocation=self.metrics.first_native_revocation or tostring(why)
            end
            self.binding=nil;self.control=nil;self.pending_proof=nil;self.pending_request=nil;self.window:revoke(why)
        end,
        status=function()return self.window:status()end}
    self.executor_adapter=router;self.adapter=router;self.operations=operations
    self.ready=function(body,intent,control)
            if self.frame_accounting and self.frame_accounting:pending()then return false,"waiting for native frame return acknowledgement"end
            self.control=copy(control)
            if not self.current or Canonical.encode(self.current.body)~=Canonical.encode(body)then refresh()end
            if frames_pending(body)then return false,"original native routine is still running"end
            local status=options.read_runtime_status and options.read_runtime_status() or self.runtime and self.runtime:status()
            if status and status.request then
                -- Complete file/journal receipts can be large. Do not let that
                -- work starve an already in-flight control response. The owned
                -- outer loop independently holds a completed native routine.
                if body.cmd=="native_trade_commit" and self.native.execution_phase=="armed"then
                    self.metrics.terminal_readback_deferred=self.metrics.terminal_readback_deferred+1
                end
                return false,"waiting for the in-flight response before native command work"
            end
            return self.binding~=nil and adapters[body.cmd]~=nil,"waiting for a selected native command"
        end
    function self.handles(body)return type(body)=="table" and adapters[body.cmd]~=nil end
    function self.frame_scope()local value=scope();return value and copy(value)or nil end
    if not embedded then
        self.transport=require("connector")
        -- Preserve the standalone service's response/control/empty-poll budgets.
        self.runtime=assert(Runtime.new({player=player,variant=options.variant,run_id=options.run_id,
            prepared_cartridge=options.prepared_cartridge,server_host=options.server_host,server_port=options.server_port,
            response_timeout=1,control_interval=0.5,sync_interval=1,
            transport=self.transport,journal=self.journal,clock=clock,host=self.host,read_context=read_context,
            operation_execution=operations,executor_adapter=router,operation_ready=self.ready}))
    end
    local rate=self.host.status().frame_rate
    self.pacer=require("frame_pacer").new({clock=clock,numerator=rate.numerator,denominator=rate.denominator})
    -- Embedded owner calls pump_native before its single shared runtime pump,
    -- then after_service only when that pump succeeds. This timestamp is not a
    -- substitute for the independently scoped and expiring native window.
    function self:pump_native()
        read_context()
        if self.frame_accounting then self.frame_accounting:pump()end
            if self.receptionist then
                self.receptionist.step()
                local query=require("gen1_receptionist_client").query(mem,manifest)
                if self.binding and self.control and self.control.admitted and query and not self.entry_sent and not self.current then
                    local event={event="receptionist_entered",payload={schema="rby-receptionist-entry-v1",
                        context_generation=context.context_generation,final_sha1=manifest.final_sha1,
                        query=query,checkpoint=Preparation.capture(mem,manifest,true)}}
                    local baseline=self.command_store:read().observation
                    baseline.receptionist_entry={payload=event,phase="queued"}
                    if options.observe then assert(options.observe(JSON.array({event}),baseline))
                    else assert(self.journal:append(event,baseline))end
                    self.entry_sent=true
                elseif not query and not self.current and mem.isPartyWriteSafe() and self.receptionist_store:read().phase=="complete"then
                    self.entry_sent=false
                end
            end
    end
    function self:after_service(began)
        read_context();refresh();self.last_service=clock()
        self.metrics.services=self.metrics.services+1
        if began then self.metrics.service_seconds=self.metrics.service_seconds+self.last_service-began end
    end
    function self:step_native()
        read_context()
            local permitted=scope()~=nil and self.window:ready() and frames_pending(self.current.body)
            local allowed,problem=self.pacer:take(permitted,self.host.status().host.user_paused)
            assert(problem==nil,problem)
            if allowed then
                local id=self.current.command_id
                local timing=self.timings[id] or {command=self.current.body.cmd,frames=0,started=clock()}
                local began=clock()
                assert(self.host.step_one(scope()));timing.frames=timing.frames+1;timing.elapsed=clock()-timing.started
                self.metrics.frame_seconds=self.metrics.frame_seconds+clock()-began
                self.timings[id]=timing
            end
        return allowed
    end
    function self:step()
        if embedded then return false,"embedded native service must be driven by its single outer owner"end
        local ok,why=pcall(function()
            read_context()
            -- Nonblocking transport drains never issue command/frame authority.
            self.transport.pump();self:pump_native()
            if not self.last_service or clock()-self.last_service>=0.2 then
                local began=clock();assert(self.runtime:step());self:after_service(began)
            end
            self:step_native()
        end)
        if not ok then self.runtime:revoke("native command service failed");return false,tostring(why)end
        return true
    end
    function self:status()
        return {context=copy(context),runtime=self.runtime and self.runtime:status() or options.read_runtime_status(),host=self.host.status(),
            embedded=embedded,
            window=self.window:status(),native_phase=self.native_store:read().phase,prompt_phase=self.prompt_store:read().phase,
            preparation_phase=self.preparation_store:read().phase,timings=copy(self.timings),
            receptionist_phase=self.receptionist_store and self.receptionist_store:read().phase,
            metrics=copy(self.metrics),ordinary_execution=false}
    end
    function self:checkpoint()return Preparation.capture(mem,manifest,self.receptionist~=nil)end
    function self:close()
        if self.runtime then self.runtime:revoke("native service closing")else self.operations.revoke("embedded native service closing")end
        self.native.close();self.prompt.close()
        if self.receptionist then self.receptionist.close();self.receptionist_store:close()end
        self.preparation_store:close();self.prompt_store:close();self.native_store:close()
        if not embedded then self.command_store:close()end
    end
    return self
end
return M
