-- Run-bound RBY client lifecycle under an independent hold. held_service clients
-- enroll and may execute only server-permitted writes; gameplay stays held.
-- free_service (P10): observe free, hold to write. The loop of gen1_observation_loop.lua
-- ticks once per emulated frame; the heartbeat checkpoint and every write take a
-- momentary verified hold of their own.
local M={WRITE_SERVICE_SECONDS=2,CONTINUITY_RETRY_SECONDS=2}
local function hex(value,size)
    return type(value)=="string" and #value==size and value:match("^[0-9a-f]+$")~=nil
end
local function validate(launch)
    assert(type(launch)=="table" and launch.schema=="slink-gen1-launch-v1"
        and launch.protocol=="slink-gen1-durable-v1" and (launch.mode=="held_service" or launch.mode=="free_service"),
        "unsupported RBY launch configuration")
    assert(hex(launch.run_id,32) and (launch.player=="a" or launch.player=="b"),"invalid launch run/player")
    assert(type(launch.host)=="string" and not launch.host:find("[%s%c]") and #launch.host>0 and #launch.host<=255
        and type(launch.port)=="number" and launch.port%1==0 and launch.port>=1 and launch.port<=65535,"invalid launch endpoint")
    assert(type(launch.cartridge)=="table" and hex(launch.cartridge.final_rom_sha1,40),"expected RBY cartridge required")
    assert(launch.initial_observations==nil or launch.initial_observations==true,"invalid initial observation selection")
    assert(launch.ordinary_frames==nil,"the frame-credit client is retired; relaunch in free_service mode")
    assert(launch.native_manifest==nil,"native launch requires the composed bounded owner, which this entry no longer composes")
    assert(launch.mode~="free_service" or launch.initial_observations==true,
        "free-run observation requires initial observation enrollment")
    local variant=launch.cartridge.variant
    assert(variant=="red" or variant=="blue" or variant=="yellow","RBY variant required")
end

function M.start(launch,options)
    validate(launch)
    options=options or {}
    local free=launch.mode=="free_service"
    local root=assert(options.root or rawget(_G,"SLINK_ROOT"),"SLink client root required")
    package.path=root.."/lua/?.lua;"..root.."/data/games/gen1_rby/?.lua;"..package.path
    local JSON=require("json_codec")
    launch=assert(JSON.decode(assert(JSON.encode(launch))))
    local memory=require("memory_gb")
    memory.initProfile(require("games.gen1_rby"),launch.cartridge.variant)
    assert(gameinfo.getromhash():lower()==launch.cartridge.final_rom_sha1,"loaded ROM differs from the run launcher")
    local actual=assert(require("gen1_runtime_profiles").metadata(launch.cartridge.variant,launch.cartridge))
    assert(JSON.encode(actual)==JSON.encode(launch.cartridge),"loaded cartridge profile differs from the launcher")
    local self={phase="waiting_for_overworld",reason="Waiting for a verified overworld checkpoint",host=nil,holds=nil,runtime=nil,store=nil,
        continuity_invalidated=nil,last_physical_frame=nil,load_state_hook=nil,continuity_cache=nil,
        continuity_retry=nil,continuity_epoch=nil,
        continuity_status={state="unavailable",reason="free service is not initialized"}}
    local nonce=require("platform_identity").new_nonce
    local generation,instance=assert(nonce()),assert(nonce())
    local context,first_frame
    if launch.initial_observations then
        -- Installed before New Game so its bus hooks witness the normal
        -- StartNewGame entry/return. Stable pre-admission scope only: it holds
        -- no host, cannot release one, and publishes nothing by itself.
        self.bootstrap=require("gen1_bootstrap_observer").new({variant=launch.cartridge.variant,
            final_sha1=launch.cartridge.final_rom_sha1,
            owned=function()return {context_generation=generation,physical_instance=instance}end,
            held=function()return self.host~=nil and self.host.status().physical_stop_verified==true end})
    end
    local function storage_path()
        luanet.load_assembly("System")
        local Path=luanet.import_type("System.IO.Path")
        local base=options.storage_root or os.getenv("SLINK_CLIENT_STORAGE_ROOT")
        if not base then
            local Environment=luanet.import_type("System.Environment")
            local Folder=luanet.import_type("System.Environment+SpecialFolder")
            base=tostring(Environment.GetFolderPath(Folder.LocalApplicationData)).."/SLink/clients"
        end
        assert(type(base)=="string" and #base>0,"local client storage directory required")
        return tostring(Path.GetFullPath(base.."/"..launch.run_id.."/"..launch.player.."/journal.json"))
    end
    local function begin()
        local Execution=require("platform_execution")
        self.host=assert(Execution.new({profile="gambatte",owner_id=instance,exclusive_ownership="emulator_process",
            control_context="between_frames",expected_host=assert(Execution.supported_profile("gambatte"))}))
        self.holds=require("hold_mux").new({host=self.host,owners={"startup","control","writer","lifecycle"}})
        assert(self.holds:set("startup",true,"waiting for qualified paired runtime bindings"))
        first_frame=emu.framecount()
        context={context_generation=generation,physical_instance=instance,
            save_identity={ot_id=string.format("%04X",memory.readPlayerId()),trainer_name=memory.readPlayerName()}}
        local Journal=require("client_journal")
        local Store=require("state_store")
        local Storage=require("platform_storage")
        self.path=storage_path()
        self.saveram_directory=options.saveram_directory or os.getenv("SLINK_SAVERAM_DIRECTORY")
            or tostring(luanet.import_type("System.IO.Path").GetDirectoryName(self.path)).."/SaveRAM"
        self.store=assert(Store.open(assert(Storage.new(self.path)),
            {schema="slink-gen1-client-binding-v1",run_id=launch.run_id,player=launch.player,
             cartridge=launch.cartridge,save_identity=context.save_identity},Journal.initial()))
        local Observation=launch.initial_observations and require("gen1_initial_observation")or nil
        local journal=assert(Journal.open(self.store,nil,Observation))
        -- Source hooks may run inside a free-running frame. They validate the stable
        -- ROM/save identity; publication and writes also require a hold.
        local function source_owned()
            assert(gameinfo.getromhash():lower()==launch.cartridge.final_rom_sha1
                and string.format("%04X",memory.readPlayerId())==context.save_identity.ot_id
                and memory.readPlayerName()==context.save_identity.trainer_name,"ROM/save changed after launch")
            return context
        end
        local function owned()
            if free then -- the hold is momentary under free-run: verified now, not pinned to the launch frame
                assert(self.host.status().physical_stop_verified,"held physical context required");return source_owned()
            end
            assert(self.host.status().physical_stop_verified and emu.framecount()==first_frame,"held physical context changed")
            return source_owned()
        end
        local function unavailable()error("cartridge execution is not selected in held-service launch mode",0)end
        local clock=assert(require("platform_clock").new())
        self.clock=clock
        -- Free-run: the executor reads that run on every control turn (operations.request,
        -- ready) happen unheld, and gen1_held_faint.safe() already answers false without the
        -- hold; the identity reader it calls first must therefore not assert one. Every write
        -- still runs under the writer hold below, which safe() requires.
        local faint=Observation and require("gen1_held_faint").new({journal=journal,memory=memory,player=launch.player,
            variant=launch.cartridge.variant,owned=free and source_owned or owned,host=self.host,clock=clock,
            saveram_directory=self.saveram_directory})or nil
        -- Free-run boundary predicate (P4 section 4): "held" also reads "between frames, inside the loop".
        local function at_boundary()return self.loop_ctx~=nil and self.loop_ctx.at_boundary==true end
        -- free_service: no standalone engine flush and no inventory stream from the observer;
        -- the loop publishes both inside its observation batches.
        if Observation then self.observer=Observation.new({memory=memory,variant=launch.cartridge.variant,
            journal=journal,host=self.host,owned=owned,source_owned=source_owned,engine_signals=true,
            bootstrap=self.bootstrap,free_service=free,at_boundary=at_boundary})end
        local operations=faint and faint.operations or nil
        local ready=faint and faint.ready or function()return false,"Waiting for qualified cartridge execution and reconciliation"end
        local executor=faint and faint.adapter or {prepare=unavailable,classify=unavailable,apply=unavailable,receipt=unavailable}
        local function new_instruction()
            return require("battle_force_authority").service({journal=journal,memory=memory,owner_id=instance,held=at_boundary,
                unwrap=function(entry)return require("gen1_runtime").unwrap(entry.body,launch.player)end})
        end
        if free then
            self.acquisitions=require("gen1_acquisition_observers").new({variant=launch.cartridge.variant,
                final_sha1=launch.cartridge.final_rom_sha1,owned=source_owned,
                fast_path=true,
                held=function()return self.host.status().physical_stop_verified==true or at_boundary() end})
            -- In-battle death delivery (handoff item 5): the window service arms the one-instruction executor
            -- under the loop boundary predicate; its rows close the server's battle_instruction command.
            self.instruction=new_instruction()
        end
        local function hard_revoke(reason)
            assert(self.holds:set("lifecycle",true,reason))
            if self.instruction then assert(self.instruction:revoke(reason))end
            return true
        end
        if free then
            assert(event and event.onloadstate,"savestate lifecycle callback required")
            self.load_state_hook=assert(event.onloadstate(function()
                self.continuity_invalidated="savestate load requires controlled recovery"
                hard_revoke(self.continuity_invalidated)
                if self.runtime then self.runtime:revoke(self.continuity_invalidated)end
            end,"slink-free-service-load-"..instance))
        end
        local function service_continuity(recovery,binding)
            local function deferred(why)
                local text=tostring(why or "service continuity is not ready"):gsub("[%c]"," "):sub(1,240)
                self.continuity_status={state="deferred",service_epoch=recovery and recovery.service_epoch or nil,
                    reason=text~=""and text or "service continuity is not ready"}
                return nil
            end
            if not free or self.continuity_invalidated or not self.loop then
                return deferred(self.continuity_invalidated or "free observation loop is not initialized")
            end
            if self.continuity_epoch~=recovery.service_epoch then
                self.continuity_epoch=recovery.service_epoch
                self.continuity_cache=nil;self.continuity_retry=nil
            end
            local refused=recovery.refusals and recovery.refusals[launch.player]
            if refused and refused~=JSON.null then
                self.continuity_cache=nil
                local now=clock()
                if not self.continuity_retry or self.continuity_retry.reason~=refused then
                    self.continuity_retry={reason=refused,retry_at=now+M.CONTINUITY_RETRY_SECONDS}
                end
                if now<self.continuity_retry.retry_at then
                    deferred(refused)
                    self.continuity_status.retry_at=self.continuity_retry.retry_at
                    return nil
                end
                self.continuity_retry=nil
            end
            if self.continuity_cache and self.continuity_cache.service_epoch==recovery.service_epoch then
                self.continuity_status={state="ready",service_epoch=recovery.service_epoch,reason="cached held continuity proof"}
                return assert(JSON.decode(assert(JSON.encode(self.continuity_cache))))
            end
            local ok,proof=pcall(function()
                assert(self.holds:held("lifecycle") and self.host.status().physical_stop_verified,
                    "service continuity requires the lifecycle hold")
                local pending_events,event_error=journal:pending_events()
                local pending_commands,command_error=journal:pending_commands()
                assert(pending_events,event_error or "durable events unavailable")
                assert(pending_commands,command_error or "durable commands unavailable")
                assert(#pending_events==0 and #pending_commands==0,"client journal is not idle")
                local continuity,continuity_error=self.loop:continuity()
                assert(continuity,continuity_error)
                local point=self.loop_ctx.inventory()
                assert(point,"party write-safe inventory checkpoint is unavailable")
                assert(point.frame==continuity.idle.source_frame,
                    "continuity inventory differs from its idle source frame")
                continuity.idle.pending_events=0;continuity.idle.pending_commands=0
                local baseline=assert(self.store:read()).observation
                return {schema="rby-free-service-continuity-v1",service_epoch=recovery.service_epoch,
                    binding_digest=binding.binding_digest,
                    initial_operation_id=baseline.initial_inventory.operation_id,
                    cursor=continuity.cursor,inventory=point,idle=continuity.idle}
            end)
            if not ok then return deferred(proof)end
            self.continuity_cache=assert(JSON.decode(assert(JSON.encode(proof))))
            self.continuity_retry=nil
            self.continuity_status={state="ready",service_epoch=recovery.service_epoch,reason="held continuity proof captured"}
            return proof
        end
        local function accept_service(_,recovery)
            assert(not self.continuity_invalidated,"invalidated physical context cannot resume service")
            if self.holds:held("lifecycle") then
                assert(recovery.required==false and recovery.proofs.a==true and recovery.proofs.b==true,
                    "paired service continuity proof is incomplete")
                if self.instruction and self.instruction:status().revoked then
                    self.instruction=new_instruction()
                    if self.loop_ctx then self.loop_ctx.instruction=self.instruction end
                end
                assert(self.holds:set("lifecycle",false,"paired service continuity verified"))
            end
            return true
        end
        self.runtime=assert(require("gen1_runtime").new({run_id=launch.run_id,player=launch.player,
            variant=launch.cartridge.variant,server_host=launch.host,server_port=launch.port,
            control_interval=free and 0.5 or nil,
            sync_interval=free and 0.5 or nil,
            prepared_cartridge=launch.cartridge,
            transport=require("connector"),journal=journal,clock=clock,
            host=self.holds:adapter("control"),service_execution=free,
            operation_held=function()
                -- Enrollment commands run under the startup hold.  Only after
                -- the observation loop exists does the momentary writer own it.
                local owner=free and self.loop and "writer" or "startup"
                return self.holds:held(owner) and self.host.status().physical_stop_verified==true
            end,
            on_revoke=hard_revoke,
            service_continuity=free and service_continuity or nil,
            on_service_authority=free and accept_service or nil,
            read_context=free and source_owned or owned,
            operation_execution=operations,
            operation_ready=ready,
            executor_adapter=executor}))
        if free then
            local Loop=require("gen1_observation_loop")
            local Fingerprint=require("gen1_inventory_fingerprint")
            local function loop_ready()
                local baseline=assert(self.store:read()).observation
                -- Held-phase writes finish, and every held-phase event is acknowledged, before the
                -- core is released: the initial save is an image command prepared from the enrollment
                -- checkpoint, and gen1_held_save_image.classify refuses it once the core has moved.
                if #assert(journal:pending_commands())>0 or #assert(journal:pending_events())>0 then return false end
                return self.runtime:has_service_lease() and self.observer.signals~=nil and self.acquisitions~=nil
                    and baseline.initial_inventory~=nil and baseline.initial_inventory.phase=="acknowledged"
                    and baseline.bootstrap~=nil and baseline.bootstrap.phase=="acknowledged"
            end
            local function writer_pending()
                return faint~=nil and faint.pending()
            end
            self.start_loop=function()
                if self.loop or not loop_ready()then return end
                local function capture_inventory()
                    if not memory.isPartyWriteSafe()then return nil end
                    assert(self.holds:set("writer",true,"full inventory checkpoint"))
                    local ok,point=pcall(Observation.capture,{owned=owned,host=self.host,memory=memory,
                        variant=launch.cartridge.variant})
                    assert(self.holds:set("writer",false,"full inventory checkpoint complete"))
                    if not ok then error(point,0)end
                    return point
                end
                local function checkpoint(previous)
                    if not memory.isPartyWriteSafe()then return nil,previous,false end
                    assert(self.holds:set("writer",true,"inventory fingerprint checkpoint"))
                    local ok,point,fingerprint,changed=pcall(function()
                        local frame=emu.framecount();source_owned()
                        local current=Fingerprint.capture(memory,launch.cartridge.variant)
                        local dirty=previous~=false and(not previous or not Fingerprint.same(previous,current))
                        local full=dirty and Observation.capture({owned=owned,host=self.host,memory=memory,
                            variant=launch.cartridge.variant})or nil
                        source_owned();assert(emu.framecount()==frame,"inventory fingerprint frame changed")
                        return full,current,dirty
                    end)
                    assert(self.holds:set("writer",false,"inventory fingerprint checkpoint complete"))
                    if not ok then error(point,0)end
                    return point,fingerprint,changed
                end
                self.loop_ctx={engine=self.observer.signals,observers=self.acquisitions,owned=source_owned,instruction=self.instruction,
                    rom_hash=function()return gameinfo.getromhash():lower()end,
                    baseline=function()return assert(self.store:read()).observation end,
                    verify=function()
                        assert(self.holds:verify())
                        source_owned()
                        return true
                    end,
                    journal={append=function(_,event,baseline)
                            local ids,why=self.runtime:observe(JSON.array({event}),baseline);return ids and ids[1],why end,
                        append_many=function(_,events,baseline)return self.runtime:observe(events,baseline)end},
                    session={pump=function()assert(self.runtime:step())end}, -- never blocks: connector settimeout(0)
                    inventory=capture_inventory,checkpoint=checkpoint,
                    writer={pending=writer_pending,service=function()
                        -- ponytail: whole-command hold, bounded per tick and retried while pending; item 4
                        -- maps every engine command to its executor and item 5 adds the in-battle window.
                        assert(self.holds:set("writer",true,"servicing a held write command"))
                        local deadline=clock()+M.WRITE_SERVICE_SECONDS
                        local ok,why=pcall(function()
                            while writer_pending() and clock()<deadline do
                                assert(self.runtime:step());assert(self.host.yield_held())
                            end
                        end)
                        assert(self.holds:set("writer",false,"held write service complete"))
                        if not ok then error(why,0)end
                    end}}
                local loop=self.holds:construct_and_release("startup","free-running observation loop constructed",
                    function()return self.runtime:has_service_lease()end,
                    function()
                        local loop=Loop.new(self.loop_ctx) -- adopt everything before compacting the acknowledged enrollment
                        if type(Observation.compact_initial)=="function"then
                            local baseline=assert(self.store:read()).observation
                            local compact,changed=Observation.compact_initial(
                                baseline.initial_inventory,assert(journal.store).backend.sha256)
                            if changed then
                                baseline.initial_inventory=compact
                                assert(journal:append_many(JSON.array(),baseline))
                            end
                        end
                        return loop
                    end)
                self.loop=loop
                self.phase="free_service";self.reason="Free-running observation; writes take the hold"
                console.log("[SLink] Free-running observation loop started at frame "..emu.framecount())
            end
        end
        self.phase="held_service";self.reason="Durable connection active; gameplay remains held"
        console.log("[SLink] Started run "..launch.run_id.." player "..launch.player.."; waiting for admission in held service")
    end
    function self:step()
        if self.phase=="failed"then return false,self.reason end
        local ok,why=pcall(function()
            assert(gameinfo.getromhash():lower()==launch.cartridge.final_rom_sha1,"launch cartridge changed")
            local physical_frame=emu.framecount()
            if self.last_physical_frame and physical_frame<self.last_physical_frame then
                self.continuity_invalidated="emulator frame moved backwards; controlled recovery is required"
                if self.holds then assert(self.holds:set("lifecycle",true,self.continuity_invalidated))end
                error(self.continuity_invalidated,0)
            end
            self.last_physical_frame=physical_frame
            if not self.runtime then
                -- Hold at the first safe overworld frame that is also visible. A fresh
                -- New Game reaches write-safety inside the white fade into the
                -- bedroom (rBGP==0x00); holding there freezes a blank screen and
                -- proves nothing. Battery-save boots are already faded in.
                if not memory.isPartyWriteSafe() or memory.readPlayerName()=="" or memory.read_u8(0xFF47)==0 then return end
                begin()
            end
            if self.loop then
                -- One tick per emulated frame (run() advances it). Under a hold taken outside the loop
                -- only the runtime pumps, so a tick never re-observes the same frame.
                if self.holds:is_held() then assert(self.runtime:step())else self.loop:tick()end
                return
            end
            local serviced,reason=self.runtime:step()
            assert(serviced,reason)
            if self.observer then self.observer:step(self.runtime:is_bound())end
            if self.start_loop then self.start_loop()end
        end)
        if not ok then
            self.phase="failed";self.reason=tostring(why)
            if self.runtime then pcall(function()self.runtime:revoke("client entry failed")end)end
            if self.holds then pcall(function()self.holds:set("lifecycle",true,"client entry failed")end)
            elseif self.host then pcall(function()self.host.set_held(true,"client entry failed")end)end
            return false,self.reason
        end
        return true
    end
    function self:status()
        local observation=self.store and self.store:read().observation or {}
        local initial=observation.initial_inventory and observation.initial_inventory.phase
        local bootstrap=observation.bootstrap and observation.bootstrap.phase
        return assert(JSON.decode(assert(JSON.encode({phase=self.phase,reason=self.reason,run_id=launch.run_id,player=launch.player,
            context=context,journal_path=self.path,host=self.host and self.host.status() or nil,
            initial_observation=initial,
            bootstrap=self.bootstrap and self.bootstrap.status() or nil,
            bootstrap_observation=bootstrap,
            engine_signals=self.observer and self.observer.signals and self.observer.signals:status()or nil,
            runtime=self.runtime and self.runtime:status({summary=true}) or nil,
            observation_diagnostics=self.loop and self.loop:status()or nil,
            continuity=self.continuity_status,
            hold_mux=self.holds and self.holds:status() or nil,
            ordinary_execution=false,
            free_service=free,observation_loop=self.loop~=nil}))))
    end
    function self:checkpoint()
        assert(self.loop and self.loop_ctx and self.loop_ctx.inventory,"free-service checkpoint unavailable")
        return assert(self.loop_ctx.inventory(),"write-safe full inventory checkpoint unavailable")
    end
    function self:close()
        if self.holds then assert(self.holds:set("lifecycle",true,"client service is closing"))end
        if self.instruction then self.instruction:close()end
        if self.acquisitions then self.acquisitions:close()end
        if self.bootstrap then self.bootstrap.close()end
        if self.observer then self.observer:close()end
        if self.load_state_hook then event.unregisterbyid(self.load_state_hook);self.load_state_hook=nil end
        if self.runtime then self.runtime:revoke("client service is closing")end
        if self.store then self.store:close()end
        -- Stopping a Lua service cannot release gameplay. Its independent host
        -- lease remains held until controlled recovery or process exit.
    end
    return self
end

function M.run(launch)
    local service=M.start(launch)
    _G.SLINK_RUNTIME_STATUS=function()return service:status()end
    _G.SLINK_RUNTIME_CHECKPOINT=function()return service:checkpoint()end
    console.log("[SLink] Waiting for the initial verified overworld checkpoint")
    while true do
        local ok,why=service:step()
        if not ok then
            local captured,status=pcall(function()return service:status()end)
            if captured then _G.SLINK_RUNTIME_STATUS=function()return status end end
            service:close();error(why,0)
        end
        if service.loop and not service.host.status().held then emu.frameadvance()
        elseif service.host then assert(service.host.yield_held())else emu.yield()end
    end
end
return M
