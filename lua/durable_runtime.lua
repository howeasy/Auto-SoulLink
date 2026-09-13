-- Explicit durable runtime composition. No client auto-selection, host qualification,
-- frame advancement, cartridge addresses or observation-baseline inference.
-- Methods on the returned runtime are colon calls; transport/host callbacks are
-- the frozen modules' dot-call APIs. Call step from the owned held-service loop.
local JSON=require("json_codec")
local Session=require("client_session")
local Control=require("control_service")
local Executor=require("command_executor")
local WATCHDOG=2
local M={WATCHDOG=WATCHDOG}
local delivery={protocol=true,player=true,admission_epoch=true,session_id=true,seq=true,
    operation_id=true,command_index=true,command_id=true,command_sequence=true}
local queue_fields={"send_lines","send_bytes","send_offset","receive_lines","receive_bytes",
    "partial_receive_bytes","pending_receive_bytes","ready_receive_bytes"}
local function token(value,n)
    return type(value)=="string" and #value==n and value:match("^[0-9a-f]+$")~=nil
end
local function copy(value)return assert(JSON.decode(assert(JSON.encode(value))))end
local function reason(value)
    local text=tostring(value or "durable runtime revoked"):gsub("[%c]"," "):sub(1,240)
    return text~="" and text or "durable runtime revoked"
end
local function interval(value,default,maximum)
    value=value or default
    assert(type(value)=="number" and value==value and value>=0.05 and value<=maximum,"invalid runtime interval")
    return value
end
local function empty_commands(packet)
    return JSON.kind(packet.commands)=="array" and #packet.commands==0
end
local function name(value)
    return type(value)=="string" and #value>=1 and #value<=64 and value:match("^[a-z][a-z0-9_.%-]*$")~=nil
end

function M.new(options)
    local control,transport
    local ok,result=pcall(function()
        assert(type(options)=="table","runtime options required")
        transport=options.transport
        local protocol,hold_event=options.protocol,options.hold_event
        assert(name(protocol),"explicit bounded protocol required")
        assert(name(hold_event) and hold_event~="hello" and hold_event~="control"
            and hold_event~="sync" and hold_event~="command_ack","distinct bounded hold_event required")
        assert(options.variant==nil or name(options.variant),"invalid runtime variant")
        local reserved={hello=true,control=true,[hold_event]=true}
        if options.reserved_events~=nil then
            assert(type(options.reserved_events)=="table","reserved_events must be a set")
            for event,enabled in pairs(options.reserved_events) do
                assert(name(event) and enabled==true and event~="sync" and event~="command_ack",
                    "invalid reserved transient event")
                reserved[event]=true
            end
        end
        local function semantic(payload)
            assert(type(payload)=="table" and not reserved[payload.event],
                "transient protocol message cannot enter the durable journal")
        end
        assert(type(transport)=="table","initialized connector API required")
        for _,name in ipairs({"init","connected","pump","send","receive","disconnect","queue_status"}) do
            assert(type(transport[name])=="function","connector method required: "..name)
        end
        assert(type(options.server_host)=="string" and #options.server_host>0 and #options.server_host<=255
            and not options.server_host:find("[%s%c]"),"explicit server_host required")
        assert(type(options.server_port)=="number" and options.server_port%1==0
            and options.server_port>=1 and options.server_port<=65535,"explicit server_port required")
        assert(options.player=="a" or options.player=="b","explicit player required")
        assert(type(options.journal)=="table" and type(options.clock)=="function","journal and monotonic clock required")
        assert(options.service_execution~=true or type(options.host)=="table"and type(options.host.verify)=="function",
            "service execution requires a host audit")
        assert(type(options.read_hello)=="function" and type(options.metadata_matches)=="function","metadata callbacks required")
        assert(type(options.operation_ready)=="function","operation-specific readiness policy required")
        assert(options.reconciliation==nil or type(options.reconciliation)=="function","invalid reconciliation callback")
        assert(options.service_continuity==nil or type(options.service_continuity)=="function",
            "invalid service continuity callback")
        assert(options.on_service_authority==nil or type(options.on_service_authority)=="function",
            "invalid service-authority callback")
        assert(options.operation_held==nil or type(options.operation_held)=="function",
            "operation hold readback must be a function")
        assert(options.on_revoke==nil or type(options.on_revoke)=="function",
            "runtime revocation callback must be a function")
        local operation_execution=options.operation_execution
        if operation_execution~=nil then
            assert(type(operation_execution)=="table","operation execution binding must be a table")
            for _,method in ipairs({"request","accept","authorize_apply","revoke","status"})do
                assert(type(operation_execution[method])=="function","operation execution callback required: "..method)
            end
            operation_execution.revoke("runtime initialization requires fresh operation authority")
        end
        local journal,adapter=options.journal,options.executor_adapter
        assert(type(adapter)=="table","executor_adapter required")
        for _,name in ipairs({"prepare","classify","apply","receipt"}) do
            assert(type(adapter[name])=="function","executor callback required: "..name)
        end
        local heartbeat=interval(options.control_interval,0.25,0.5)
        local response_timeout=interval(options.response_timeout,0.75,1)
        local sync_interval=interval(options.sync_interval,0.5,2)
        assert(options.pending_delivery_hint==nil or type(options.pending_delivery_hint)=="boolean",
            "pending delivery hint selection must be boolean")
        local metadata_interval=interval(options.metadata_interval,0.05,0.5)
        local state={phase="connection_pending",connected=false,failed=false,reason="waiting for admission",
            last_clock=nil,last_control=nil,last_sync=nil,last_semantic=nil,last_metadata=nil,pending_delivery=nil,
            request=nil,binding=nil,admission=nil,recovery=nil,
            service_recovery=nil,
            event_count=0,command_count=0,hold_verified=false,host_request_verified=false}
        local self={}
        local function now()
            local value=options.clock()
            assert(type(value)=="number" and value==value and value>=0 and value<math.huge
                and (state.last_clock==nil or value>=state.last_clock),"monotonic clock failed")
            state.last_clock=value;return value
        end
        local function read_report()
            local report,why=options.read_hello() -- Caller must classify ownership before supplying metadata.
            if report==nil then return nil,reason(why or "ownership/metadata is not ready") end
            report=copy(report)
            assert(JSON.kind(report)=="object" and token(report.context_generation,32),"context_generation metadata required")
            for key in pairs(delivery) do assert(report[key]==nil,"delivery envelope in HELLO metadata") end
            assert(report.event==nil and report.client_nonce==nil and report.commands==nil
                and report.control==nil and report.reconciliation==nil,"delivery data in HELLO metadata")
            return report
        end
        local function matches(admission,report)
            return options.metadata_matches(copy(admission),copy(report))==true
        end
        local session=Session.new({protocol=protocol,player=options.player,variant=options.variant,durable_ids=true,
            read_metadata=read_report,metadata_matches=matches,new_nonce=options.new_nonce})
        assert(type(options.host)=="table" and type(options.host.set_held)=="function","hold host required")
        control=Control.new({clock=options.clock,timeout=WATCHDOG,new_nonce=options.new_nonce,
            service_execution=options.service_execution,
            host={set_held=function(held,why)
                state.host_request_verified=false;state.hold_verified=false
                local accepted=options.host.set_held(held,why)
                state.host_request_verified=accepted==true
                state.hold_verified=accepted==true and held==true
                return accepted
            end,verify=options.host.verify and function()return options.host.verify()end or nil}})
        local function queues_empty()
            local snapshot=transport.queue_status()
            assert(type(snapshot)=="table","connector queue readback unavailable")
            for _,key in ipairs(queue_fields) do assert(snapshot[key]==0,"connector delivery queue was not discarded: "..key) end
        end
        local function revoke(why,fatal)
            why=reason(why)
            if fatal and not state.failure then state.failure=why end
            state.failed=state.failed or fatal
            state.reason=why;state.phase=state.failed and "failed" or "connection_pending"
            state.request=nil;state.binding=nil;state.admission=nil;state.recovery=nil;state.service_recovery=nil;state.last_control=nil
            state.last_verified_control=nil;state.last_metadata=nil;state.pending_delivery=nil
            if options.on_revoke then
                local stopped,problem=pcall(options.on_revoke,why)
                if not stopped or problem~=true then
                    state.failed=true;state.failure=state.failure or reason(not stopped and problem or "runtime revocation was not verified")
                end
            end
            if operation_execution then
                local revoked,problem=pcall(operation_execution.revoke,why)
                if not revoked then state.failed=true;state.failure=state.failure or reason(problem)end
            end
            local held,hold_error=pcall(function()control:revoke(why)end)
            session:revoke(why)
            local cleared,clear_error=pcall(function()transport.disconnect();queues_empty()end)
            state.connected=false
            if state.failed then state.phase="failed";state.reason=state.failure or state.reason end
            if not held or not cleared then
                state.failed=true;state.phase="failed"
                state.failure=state.failure or reason(not held and hold_error or clear_error)
                state.reason=state.failure
            end
        end
        local event_revision,event_list,command_revision,command_list
        local function revision()return journal.store.revision and assert(journal.store:revision())or nil end
        local function events()
            local current=revision()
            if current~=nil and current==event_revision then state.event_count=#event_list;return event_list end
            local list,why=journal:pending_events()
            assert(list,why or "durable events unavailable")
            for _,entry in ipairs(list) do semantic(entry.payload) end
            event_revision,event_list=current,list
            state.event_count=#list;return list
        end
        local function commands()
            local current=revision()
            if current~=nil and current==command_revision then state.command_count=#command_list;return command_list end
            local list,why=journal:pending_commands()
            assert(list,why or "durable commands unavailable")
            command_revision,command_list=current,list
            state.command_count=#list;return list
        end
        local function current_metadata(force)
            if session.state~="admitted" or not state.binding then return false end
            local time=now()
            if not force and state.last_metadata and time-state.last_metadata<metadata_interval then return true end
            local report,why=read_report()
            if not report or report.context_generation~=state.binding.context_generation or not matches(state.admission,report) then
                revoke(why or "context changed; fresh admission required",false);return false
            end
            state.last_metadata=time
            return true
        end
        local function control_tick()
            local success,why=control:step()
            assert(success,why)
            if state.binding and not control:status().admitted then
                revoke("control watchdog revoked admission",false);return false
            end
            return true
        end
        local function control_status()
            local status=control:status()
            if options.operation_held then status.operation_held=options.operation_held()
            else status.operation_held=status.held end
            assert(type(status.operation_held)=="boolean","operation hold readback must be boolean")
            return status
        end
        local function permission(body,intent)
            if not control_tick() or not current_metadata(true) then return false,"current binding is unavailable" end
            if operation_execution and (not state.last_verified_control or now()-state.last_verified_control>=WATCHDOG)then
                return false,"fresh control roundtrip required for operation execution"
            end
            local before=control_status()
            local allowed,why=options.operation_ready(copy(body),intent and copy(intent) or nil,copy(before))
            assert(type(allowed)=="boolean","operation readiness must explicitly allow or defer")
            -- A slow readiness callback cannot use an expired ticket to apply.
            if not control_tick() or not current_metadata(true) then return false,"authority changed during readiness" end
            if operation_execution and (not state.last_verified_control or now()-state.last_verified_control>=WATCHDOG)then
                return false,"control liveness expired during readiness"
            end
            local after=control_status()
            if before.admitted~=after.admitted or before.held~=after.held
                or before.authority~=after.authority or before.service_epoch~=after.service_epoch
                or before.recovery_epoch~=after.recovery_epoch
                or before.operation_held~=after.operation_held then return false,"authority changed during readiness" end
            return allowed,why
        end
        local apply_deferred
        local executor=Executor.new(journal,{prepare=adapter.prepare,classify=adapter.classify,receipt=adapter.receipt,
            apply=function(body,intent,identity)
                local allowed,why=permission(body,intent)
                -- Configured generations may require command-scoped authority
                -- even while an ordinary run ticket exists. No generic native
                -- or recovery permission is inferred by this composition.
                if allowed then
                    if not control_tick() or not current_metadata(true)then
                        allowed=false;why="current execution binding is unavailable"
                    elseif operation_execution then
                        allowed,why=operation_execution.authorize_apply(copy(body),copy(intent),copy(identity),copy(control_status()))
                        assert(type(allowed)=="boolean","operation apply authority must explicitly allow or defer")
                        if allowed and (not control_tick() or not current_metadata(true) or not state.last_verified_control
                            or now()-state.last_verified_control>=WATCHDOG)then
                            allowed=false;why="authority changed during operation authorization"
                        end
                    else
                        allowed=control:status().ordinary_execution==true
                        why="ordinary execution authority is required to apply"
                    end
                end
                if not allowed then
                    apply_deferred=reason(why or "operation is not ready")
                    error(apply_deferred,0) -- No physical adapter call occurred.
                end
                return adapter.apply(body,intent,identity)
            end})
        local function execute_one()
            if state.failed or session.state~="admitted" or not state.binding then return end
            local entry=commands()[1]
            if not entry then return end
            state.command_id=entry.command_id
            local allowed,why=permission(entry.body,entry.intent)
            if not allowed then state.deferred=reason(why or "operation is not ready");return end
            state.deferred=nil;apply_deferred=nil
            local complete,diagnostic=executor:step(entry.command_id)
            state.execution=copy(diagnostic)
            if not complete and not diagnostic.pending then
                if apply_deferred then state.deferred=apply_deferred
                else revoke("command "..tostring(diagnostic.phase)..": "..tostring(diagnostic.reason),true) end
            end
            -- PENDING retains this oldest obligation. It grants no authority, but
            -- does not revoke an existing run ticket needed for ordinary progress.
            events();commands()
        end
        local function send(packet,kind,time)
            local decorated,why=session:decorate(packet)
            assert(decorated,why)
            local encoded,error=JSON.encode(packet)
            assert(encoded,error)
            local accepted,problem=transport.send(encoded)
            if accepted~=true then revoke(problem or "connector refused delivery",false);return false end
            session:queued(packet)
            state.request={kind=kind,operation_id=packet.operation_id,seq=packet.seq,started=time,
                deadline=time+response_timeout}
            return true
        end
        local function receive(packet)
            assert(JSON.kind(packet)=="object","response must be an object")
            if packet.event==hold_event then
                if session.state~="admitted" or packet.protocol~=protocol or packet.player~=options.player
                    or packet.admission_epoch~=session.epoch or packet.session_id~=session.session_id then return end
                assert(empty_commands(packet) and type(packet.reason)=="string" and #packet.reason>0
                    and #packet.reason<=256 and not packet.reason:find("[%c]"),"invalid current hold notice")
                revoke(packet.reason,false);return
            end
            local request=state.request
            assert(request and packet.seq==request.seq and packet.operation_id==request.operation_id,
                "response does not match the single in-flight request")
            if request.kind~="semantic" then assert(empty_commands(packet),"HELLO/control cannot deliver commands") end
            local batch,why=session:receive(packet)
            if not batch then revoke(why,false);return end
            if request.kind~="semantic" then
                assert(packet.recovery==nil or packet.recovery==JSON.null or JSON.kind(packet.recovery)=="object",
                    "invalid recovery document")
                local service=packet.service_recovery
                if options.service_continuity then
                    assert(JSON.kind(service)=="object" and service.schema=="slink-service-recovery-v1"
                        and type(service.required)=="boolean" and token(service.service_epoch,32)
                        and type(service.paired_admission)=="boolean"
                        and JSON.kind(service.proofs)=="object" and type(service.proofs.a)=="boolean"
                        and type(service.proofs.b)=="boolean" and JSON.kind(service.refusals)=="object",
                        "invalid service recovery document")
                    for key in pairs(service)do
                        assert(key=="schema"or key=="required"or key=="service_epoch"or key=="paired_admission"
                            or key=="proofs"or key=="refusals",
                            "unknown service recovery field")
                    end
                    for key in pairs(service.proofs)do assert(key=="a"or key=="b","unknown service recovery player")end
                    for key,value in pairs(service.refusals)do
                        assert((key=="a"or key=="b")and(value==JSON.null or type(value)=="string"
                            and #value>0 and #value<=256 and not value:find("[%c]")),"invalid service continuity refusal")
                    end
                    state.service_recovery=copy(service)
                else
                    assert(service==nil or service==JSON.null or JSON.kind(service)=="object",
                        "invalid optional service recovery document")
                end
            end
            if request.kind=="hello" then
                local binding=packet.admission.control_binding
                assert(type(binding)=="table" and binding.session_id==session.session_id
                    and binding.admission_epoch==session.epoch
                    and binding.context_generation==session.report.context_generation,
                    "missing or mismatched control binding")
                local fresh,problem=read_report()
                assert(fresh,problem)
                assert(fresh.context_generation==binding.context_generation and matches(packet.admission,fresh),
                    "metadata changed during HELLO")
                control:bind(binding)
                if operation_execution then operation_execution.revoke("new admission binding")end
                state.binding=copy(binding);state.admission=copy(packet.admission)
                state.recovery=packet.recovery~=JSON.null and packet.recovery and copy(packet.recovery) or nil
                state.pending_delivery=nil
                state.phase="admitted";state.reason="waiting for paired control authority"
            elseif request.kind=="control" then
                assert(JSON.kind(packet.control)=="object","control response packet required")
                assert(JSON.kind(packet.recovery)=="object","control response recovery document required")
                assert(control:accept(packet.control),"stale or invalid control authority")
                state.last_verified_control=request.started
                -- The response envelope and exact CONTROL challenge were just
                -- accepted. An absent/malformed hint keeps the old sync cadence.
                if options.pending_delivery_hint and type(packet.pending_delivery)=="boolean" then
                    state.pending_delivery=packet.pending_delivery
                else state.pending_delivery=nil end
                if (packet.control.authority=="service"or packet.control.authority=="run")
                    and options.on_service_authority then
                    assert(options.on_service_authority(copy(packet.control),copy(state.service_recovery))==true,
                        "service authority did not release its lifecycle hold")
                end
                if operation_execution then
                    local grant=packet.operation_execution
                    assert(grant==nil or grant==JSON.null or JSON.kind(grant)=="object","invalid operation execution response")
                    assert(operation_execution.accept(grant~=JSON.null and grant and copy(grant)or nil,copy(state.binding))==true,
                        "operation execution response was not accepted")
                end
                state.recovery=packet.recovery~=JSON.null and packet.recovery and copy(packet.recovery) or nil
                state.reason=control:status().reason
            else
                local oldest=events()[1]
                assert(oldest and oldest.operation_id==request.operation_id,
                    "semantic response lacks its oldest durable event")
                local semantic_result=packet.observation_result
                if oldest.payload.event=="observation"then
                    assert(JSON.kind(semantic_result)=="object"
                        and semantic_result.schema=="rby-observation-result-v1"
                        and semantic_result.operation_id==request.operation_id
                        and semantic_result.sequence==oldest.payload.sequence
                        and semantic_result.frame==oldest.payload.frame,
                        "observation response lacks its exact committed settlement")
                    local inventory=oldest.payload.inventory
                    local status=semantic_result.inventory_status
                    assert((inventory==JSON.null and status=="absent")
                        or (inventory~=JSON.null and (status=="recorded"or status=="deferred")),
                        "observation settlement differs from its durable inventory")
                else
                    assert(semantic_result==nil,"unsolicited observation settlement")
                end
                local durable=JSON.array()
                for _,command in ipairs(batch) do
                    local body=JSON.object()
                    for key,value in pairs(command) do if not delivery[key] then body[key]=value end end
                    durable[#durable+1]={command_id=command.command_id,command_sequence=command.command_sequence,body=body}
                end
                local safe,saved,problem=pcall(function()
                    local accepted,error=journal:accept_response(request.operation_id,durable,semantic_result)
                    if accepted then events();commands() end
                    return accepted,error
                end)
                if not safe or not saved then
                    revoke(not safe and saved or problem or "response publication is uncertain",true);return
                end
                state.pending_delivery=nil -- this semantic reply already fetched current delivery
                state.last_semantic=now()
            end
            state.request=nil
            state.last_completed=request.kind
        end
        local function service()
            local time=now()
            if state.failed then return end
            if state.binding and not control:status().admitted then revoke("control watchdog revoked admission",false);return end
            if state.connected and not transport.connected() then revoke("connector disconnected",false);return end
            if state.request and time>=state.request.deadline then revoke("response deadline expired",false);return end
            transport.pump()
            if not transport.connected() then
                if state.connected then revoke("connector disconnected",false) end
                state.connected=false;return
            end
            state.connected=true
            for _=1,16 do
                local raw=transport.receive()
                if raw==nil then break end
                local packet,why=JSON.decode(raw)
                if not packet then revoke(why,false);return end
                local accepted,problem=pcall(receive,packet)
                if not accepted then revoke(problem,false);return end
                if not state.connected or state.failed then return end
            end
            if session.state=="admitted" and not current_metadata(false) then return end
            execute_one()
            if state.failed or not state.connected or state.request then return end
            time=now()
            if session.state=="contract_pending" then
                local started,why=session:begin()
                if not started then state.phase="metadata_pending";state.reason=reason(why);return end
                if send({event="hello"},"hello",time) then state.phase="hello_sent" end
            elseif session.state=="admitted" then
                if not control_tick() then return end
                if (not state.last_control or time-state.last_control>=heartbeat)
                    and not (state.last_completed=="control" and state.event_count>0)then
                    local proof
                    if options.reconciliation and state.recovery then
                        proof=options.reconciliation(copy(state.recovery))
                        if proof~=nil then
                            proof=copy(proof)
                            assert(JSON.kind(proof)=="object","reconciliation evidence must be an object, not a success flag")
                        end
                    end
                    local continuity
                    if options.service_continuity and state.service_recovery and state.service_recovery.required
                        and state.service_recovery.paired_admission then
                        continuity=options.service_continuity(copy(state.service_recovery),copy(state.binding))
                        if continuity~=nil then
                            continuity=copy(continuity)
                            assert(JSON.kind(continuity)=="object",
                                "service continuity evidence must be an object, not a success flag")
                        end
                    end
                    local challenge=control:challenge()
                    local operation
                    if operation_execution then
                        operation=operation_execution.request(copy(state.binding),copy(control_status()))
                        if operation~=nil then
                            operation=copy(operation);assert(JSON.kind(operation)=="object","operation execution request must be an object")
                        end
                    end
                    if send({event="control",operation_id=challenge.challenge,control=challenge,reconciliation=proof,
                        service_continuity=continuity,operation_execution=operation},"control",time) then
                        state.last_control=time
                    end
                else
                    local pending=events()
                    local recent=state.last_sync
                    if state.last_semantic and (not recent or state.last_semantic>recent)then recent=state.last_semantic end
                    if #pending==0 and (state.pending_delivery==true
                        or state.pending_delivery~=false and (not recent or time-recent>=sync_interval)) then
                        local id,why=journal:append(JSON.object({event="sync"}))
                        assert(id,why);state.last_sync=time;state.pending_delivery=nil;pending=events()
                    end
                    if pending[1] then
                        local packet=copy(pending[1].payload);packet.operation_id=pending[1].operation_id
                        send(packet,"semantic",time)
                    end
                end
            end
            if state.connected then
                transport.pump()
                if not transport.connected() then revoke("connector disconnected during delivery",false) end
            end
        end
        function self:observe(payloads,baseline)
            if state.failed then return nil,state.failure end
            local safe,ids,why=pcall(function()
                -- The journal immediately validates and detaches this whole
                -- batch before it can publish anything.  Check transient
                -- event kinds first, but do not encode/decode the full point
                -- twice on the same single-threaded observation boundary.
                assert(type(payloads)=="table","observation array required")
                for _,payload in ipairs(payloads) do semantic(payload) end
                return journal:append_many(payloads,baseline)
            end)
            if not safe or not ids then
                revoke(safe and why or ids,true);return nil,state.failure
            end
            state.event_count=state.event_count+#ids
            return ids
        end
        function self:revoke(why)revoke(why,false)end
        function self:step()
            local callback
            if not state.failed then callback=service end
            local serviced,why=control:step(callback)
            if not serviced then revoke(why,true) end
            if state.binding and not control:status().admitted then revoke("control watchdog revoked admission",false) end
            if state.failed then return false,state.failure end
            return true
        end
        function self:is_bound()
            return state.binding~=nil and control:status().admitted
        end
        function self:has_service_lease()
            if state.failed or not state.binding then return false end
            local serviced,why=control:step()
            if not serviced then revoke(why,true);return false end
            if state.binding and not control:status().admitted then
                revoke("control watchdog revoked admission",false);return false
            end
            local status=control:status()
            return state.last_verified_control~=nil and now()-state.last_verified_control<WATCHDOG
                and status.admitted and status.service_execution==true
        end
        function self:status(options)
            local execution=state.execution
            if options and options.summary and execution then
                execution={outcome=execution.outcome,phase=execution.phase,pending=execution.pending,
                    reason=execution.reason,retryable=execution.retryable,replayed=execution.replayed}
            end
            return copy({protocol=protocol,phase=state.phase,connected=state.connected,failed=state.failed,
                reason=state.reason,failure=state.failure,session_state=session.state,session_id=session.session_id,
                admission_epoch=session.epoch,context_generation=state.binding and state.binding.context_generation,
                binding_missing=state.binding==nil or not control:status().admitted,
                request=state.request,pending_events=state.event_count,pending_commands=state.command_count,
                service_recovery=state.service_recovery,
                command_id=state.command_id,execution=execution,deferred=state.deferred,control=control:status(),
                hold_verified=state.hold_verified,host_request_verified=state.host_request_verified,
                operation_execution=operation_execution and operation_execution.status()or nil,
                production_selected=false,host_qualification_proved=false,native_recovery_execution=false})
        end
        events();commands()
        transport.init(options.server_host,options.server_port,{discard_on_disconnect=true})
        queues_empty()
        return self
    end)
    if not ok then
        local held,problem=pcall(function()
            if type(options)=="table" and type(options.on_revoke)=="function" then
                assert(options.on_revoke("durable runtime initialization failed")==true,
                    "runtime initialization revocation was not verified")
            end
            if control then control:revoke("durable runtime initialization failed")
            elseif type(options)=="table" and type(options.host)=="table" and type(options.host.set_held)=="function" then
                assert(options.host.set_held(true,"durable runtime initialization failed")==true,"initial hold was not verified")
            end
        end)
        if transport and type(transport.disconnect)=="function" then pcall(transport.disconnect) end
        return nil,reason(held and result or "initialization hold failed: "..tostring(problem))
    end
    return result
end
return M
