-- Run-bound RBY client lifecycle under an independent hold. held_service clients
-- enroll and may execute only server-permitted writes; gameplay stays held.
-- free_service (P10): observe free, hold to write. The loop of gen1_observation_loop.lua
-- ticks once per emulated frame; the heartbeat checkpoint and every write take a
-- momentary verified hold of their own. Durable commands reach exactly one service through
-- command_service_router: physical commands take the held faint service (permit + hold),
-- hud_notice takes gen1_hud_service, which draws on the lua/hud.lua overlay with no write,
-- permit or hold and therefore settles even while lifecycle-held.
local M={WRITE_SERVICE_SECONDS=2,CONTINUITY_RETRY_SECONDS=2}
-- GB overlay geometry, as lua/clients/gen1_rby_client.lua:185.
local OVERLAY={screen_w=160,screen_h=144,hud_x=2,hud_y=134,hud_right=158,prompt_y=36,prompt_h=10,gameover_y=50,
    font_size=8,char_width=5}
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
    if launch.native_manifest~=nil then
        -- Native trade rides the free-service client: ordinary gameplay stays free; only the original
        -- ROM trade routine steps under an owned bounded window (gen1_native_host).
        local native=launch.native_manifest
        assert(launch.mode=="free_service" and launch.initial_observations==true,
            "native launch requires the free-service client with initial observations")
        assert(type(native)=="table" and native.schema=="gen1-native-trade-build-v1" and native.variant==launch.cartridge.variant
            and native.final_sha1==launch.cartridge.final_rom_sha1 and type(native.foreground)=="table"
            and type(native.foreground.overlay)=="number","native launch requires the admitted companion manifest")
    end
    assert(launch.mode~="free_service" or launch.initial_observations==true,
        "free-run observation requires initial observation enrollment")
    if launch.resume~=nil then
        -- Run-boundary resume (P2A-2C): this run continues a closed predecessor; the player must
        -- CONTINUE the exact save the predecessor last acknowledged, digested under the named projection.
        local resume=launch.resume
        assert(type(resume)=="table" and type(resume.from_run)=="string" and #resume.from_run>0
            and hex(resume.required_digest,64) and resume.projection=="cartram-0498-8000-v1"
            and launch.initial_observations==true,"invalid resume contract")
        for key in pairs(resume)do
            assert(key=="from_run" or key=="required_digest" or key=="projection","invalid resume contract")
        end
    end
    local variant=launch.cartridge.variant
    assert(variant=="red" or variant=="blue" or variant=="yellow","RBY variant required")
end

function M.start(launch,options)
    options=options or {}
    local root=assert(options.root or rawget(_G,"SLINK_ROOT"),"SLink client root required")
    package.path=root.."/lua/?.lua;"..root.."/data/games/gen1_rby/?.lua;"..package.path
    -- A native launch script may be loaded onto an APPLY-armed core. Claim the exclusive actuator
    -- and hold it BEFORE anything that can fail (launch validation, profile, ROM checks): a startup
    -- error then leaves the core stopped (platform_execution never releases on its own) instead of
    -- free-running one unowned frame. Nothing here reads the manifest.
    local early_host,early_holds,early_instance
    if type(launch)=="table" and launch.native_manifest~=nil then
        local Execution=require("platform_execution")
        early_instance=assert(require("platform_identity").new_nonce())
        early_host=assert(Execution.new({profile="gambatte",owner_id=early_instance,exclusive_ownership="emulator_process",
            control_context="between_frames",expected_host=assert(Execution.supported_profile("gambatte"))}))
        early_holds=require("hold_mux").new({host=early_host,owners={"startup","control","writer","lifecycle","native"}})
        assert(early_holds:set("startup",true,"native launch: held before the first frame"))
    end
    validate(launch)
    local free=launch.mode=="free_service"
    local native=launch.native_manifest
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
    local generation,instance=assert(nonce()),early_instance or assert(nonce())
    self.host,self.holds=early_host,early_holds
    -- Native physical read, source-grounded (patch/gen1/src/trade_service.asm), taken before EVERY
    -- pre-begin free frame and once more under the hold:
    --  * armed/done: the overlay word is published in WRAM ("SLT1", byte4 == 1): the next free frame
    --    could enter the service at the DelayFrame bridge (byte5 == 5, byte6 ~= byte7), or the
    --    routine is halted at DONE waiting for release (byte5 == 7);
    --  * mid_routine: the service saved the word on the STACK (save_overlay_on_stack: pairs pushed
    --    so the magic reads 31 54 4C 53 ascending, preceded by byte5, byte4) and swapped the overlay
    --    to tiles; the CPU is inside the original trade routine. The stack is the fixed pret
    --    SECTION "Stack" ($DF00..$DFFF, wStack = $DFFF, ram/wram.asm) and everything pushed lives
    --    inside it, so that whole section is scanned regardless of SP: no nesting-depth assumption,
    --    and no dependence on SP, which a cold core reports outside WRAM before home/init.asm sets
    --    `ld sp, wStack` and home/vcopy.asm borrows transiently.
    -- A cold boot shows neither (WRAM re-derived from SaveRAM, probe a4e3f1b), however late this
    -- script starts; a script attached mid-play shows one of them exactly when a free frame would be
    -- unowned. No frame-count heuristic is involved. The read runs under the startup hold that a
    -- native launch claims in start(), before its first frame: a failing read leaves the core held.
    local function native_physical()
        if not native then return "clean" end
        local base=native.foreground.overlay
        if memory.read_u8(base)==0x53 and memory.read_u8(base+1)==0x4c and memory.read_u8(base+2)==0x54
            and memory.read_u8(base+3)==0x31 and memory.read_u8(base+4)==1 then return "armed" end
        for address=0xDF00,0xE000-4 do
            if memory.read_u8(address)==0x31 and memory.read_u8(address+1)==0x54 and memory.read_u8(address+2)==0x4c
                and memory.read_u8(address+3)==0x53 then return "mid_routine" end
        end
        return "clean"
    end
    self.native_physical=native_physical
    -- An in-process script reload evicts the module cache but retains globals.  The
    -- previous overlay closure can still erase BizHawk's persistent GUI pixels before
    -- the fresh module loses that visibility state.
    local previous_overlay_clear=rawget(_G,"SLINK_RUNTIME_OVERLAY_CLEAR")
    if type(previous_overlay_clear)=="function" then pcall(previous_overlay_clear)end
    _G.SLINK_RUNTIME_OVERLAY_CLEAR=nil
    self.overlay=require("hud");self.overlay.init(OVERLAY)
    self.overlay_clear=function()return self.overlay.clear()end
    _G.SLINK_RUNTIME_OVERLAY_CLEAR=self.overlay_clear
    local context,first_frame
    if launch.initial_observations then
        -- Installed before New Game so its bus hooks witness the normal
        -- StartNewGame entry/return. Stable pre-admission scope only: it holds
        -- no host, cannot release one, and publishes nothing by itself.
        -- A resumed run witnesses CONTINUE instead, and proves at the load that the save is the
        -- predecessor's acknowledged one (sha256 through the .NET host: no store exists yet).
        local witness={variant=launch.cartridge.variant,final_sha1=launch.cartridge.final_rom_sha1,
            owned=function()return {context_generation=generation,physical_instance=instance}end,
            held=function()return self.host~=nil and self.host.status().physical_stop_verified==true end}
        if launch.resume then
            luanet.load_assembly("System")
            local Hash,Bits=luanet.import_type("System.Security.Cryptography.SHA256"),luanet.import_type("System.BitConverter")
            local utf8=luanet.import_type("System.Text.UTF8Encoding")(false,true)
            witness.required_digest,witness.projection=launch.resume.required_digest,launch.resume.projection
            witness.sha256=function(text)
                local hash=Hash.Create()
                local ok,value=pcall(function()return tostring(Bits.ToString(hash:ComputeHash(utf8:GetBytes(text)))):gsub("-",""):lower()end)
                hash:Dispose();assert(ok,value);return value
            end
            self.continue_observer=require("gen1_continue_observer").new(witness)
        else
            self.bootstrap=require("gen1_bootstrap_observer").new(witness)
        end
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
    local Execution=require("platform_execution")
    -- Claim the one exclusive actuator and take the startup hold. A native launch claims it in
    -- start(), before this script's first frame, so every pre-begin read runs held and a failure
    -- anywhere leaves the core stopped (platform_execution never releases on its own).
    local function claim_host(reason)
        if self.host then return end   -- a native launch already claimed and holds it (above)
        self.host=assert(Execution.new({profile="gambatte",owner_id=instance,exclusive_ownership="emulator_process",
            control_context="between_frames",expected_host=assert(Execution.supported_profile("gambatte"))}))
        self.holds=require("hold_mux").new({host=self.host,owners={"startup","control","writer","lifecycle","native"}})
        assert(self.holds:set("startup",true,reason or "waiting for qualified paired runtime bindings"))
    end
    local function begin()
        claim_host()
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
        local Native=native and require("gen1_native_runtime") or nil
        local callbacks=Native and Native.journal_options(Observation,function()return self.native end) or Observation
        if native then
            -- The server's verdict on the published held read arrives as the event's acknowledged
            -- result. Only a `released` verdict whose read_digest equals the read this client
            -- published can ever release the startup hold; anything else keeps it (fail closed).
            local inner={};for k,v in pairs(callbacks)do inner[k]=v end
            callbacks=inner
            local acknowledge=inner.acknowledge_event
            callbacks.acknowledge_event=function(event,operation_id,baseline,result)
                if type(event)=="table" and event.event=="native_reattach" then
                    local verdict=type(result)=="table" and result.schema=="rby-native-reattach-result-v1" and result or nil
                    if verdict and verdict.read_digest==self.reattach_read_digest and (verdict.verdict=="released" or verdict.verdict=="held") then
                        self.reattach_server={verdict=verdict.verdict,class=verdict.class,read_digest=verdict.read_digest,operation_id=operation_id}
                    else
                        self.reattach_server={verdict="held",class="verdict_mismatch",read_digest=self.reattach_read_digest,operation_id=operation_id}
                    end
                    baseline.native_reattach={read_digest=self.reattach_read_digest,verdict=self.reattach_server.verdict,class=self.reattach_server.class}
                    return baseline
                end
                if acknowledge then return acknowledge(event,operation_id,baseline,result)end
                return nil
            end
        end
        local journal=assert(Journal.open(self.store,nil,callbacks))
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
            bootstrap=self.bootstrap,continue_observer=self.continue_observer,free_service=free,at_boundary=at_boundary})end
        -- HUD notices are no-write commands: no memory, permit, hold or sound. They settle while
        -- lifecycle-held so a pending notice can never block service continuity; every other
        -- command stays with the held faint service, and writer_pending stays physical-only.
        self.hud=require("gen1_hud_service").new({journal=journal,overlay=self.overlay,player=launch.player})
        local services={self.hud}
        if faint then services[#services+1]=faint end
        if Native then
            -- Construct the native service under the startup hold with its host ARMED so it can
            -- verify a held, bounded owner; then disarm so ordinary gameplay stays free. A later
            -- native command re-arms a fresh bounded owner at that command's boundary.
            assert(self.holds:set("native",true,"native service construction"))
            self.native_host=require("gen1_native_host").new({adapter=self.holds:adapter("native"),owner_id=instance,
                expected_host=assert(Execution.supported_profile("gambatte")),
                authorize=function(scope,checkpoint)return self.native~=nil and self.native.authorize_step(scope,checkpoint)end})
            assert(self.native_host.arm("native service construction"))
            self.native=Native.new({embedded=true,memory=memory,manifest=native,variant=launch.cartridge.variant,
                player=launch.player,run_id=launch.run_id,context=context,read_context=source_owned,clock=clock,
                host=self.native_host,journal=journal,receptionist=true,
                storage_directory=tostring(luanet.import_type("System.IO.Path").GetDirectoryName(self.path)).."/native",
                saveram_directory=self.saveram_directory,
                observe=function(events,baseline)return self.runtime:observe(events,baseline)end,
                read_runtime_status=function()return self.runtime and self.runtime:status({summary=true})or {}end})
            -- The start-of-script read: overlay word, lease, CPU, under the held owner, no frame.
            self.reattach_read=require("gen1_native_reattach").read({host=self.host,memory=memory,manifest=native,
                lease=function()return self.native.native_store:read()end})
            assert(self.native_host.disarm("native service constructed"))
            services[#services+1]={handles=self.native.handles,adapter=self.native.executor_adapter,ready=self.native.ready,
                operations=self.native.operations,update_control=self.native.update_control}
        end
        local router=require("command_service_router").new(services)
        local operations,ready,executor=router.operations,router.ready,router.adapter
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
            -- A re-admission rotates the control binding: the server accepts no earlier read as this
            -- session's evidence, so the held read is republished once the runtime is bound again.
            -- The remembered verdict is dropped HERE, not on the later republish: loop_ready can
            -- never consult a pre-revoke release across a new admission whatever the step order.
            if native then self.reattach_server=nil;self.reattach_republish=true end
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
                local proof={schema="rby-free-service-continuity-v1",service_epoch=recovery.service_epoch,
                    binding_digest=binding.binding_digest,
                    initial_operation_id=baseline.initial_inventory.operation_id,
                    cursor=continuity.cursor,inventory=point,idle=continuity.idle}
                if baseline.pending_inventory_retry then
                    proof.pending_inventory_retry=baseline.pending_inventory_retry
                end
                if native then
                    -- Terminal-only native continuity: stated under this lifecycle hold from the live
                    -- lease and host, never from a remembered verdict.
                    proof.native={lease_phase=assert(self.native.native_store:read()).phase,
                        host_armed=self.native_host.armed(),host_failure=self.native_host.failure() or JSON.null}
                end
                return proof
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
            semantic_settlement=native and function(oldest,packet)
                -- Only the typed native read settles here; every other semantic event (sync,
                -- command_ack, trade events) settles as before, and a verdict riding one of those
                -- replies is unsolicited and refused.
                if type(oldest)~="table" or type(oldest.payload)~="table" or oldest.payload.event~="native_reattach" then
                    assert(type(packet)~="table" or packet.native_reattach_result==nil,"unsolicited native reattach settlement")
                    return nil
                end
                return require("gen1_native_reattach").settlement(oldest,packet,self.store.backend.sha256)
            end or nil,
            operation_execution=operations,
            operation_ready=ready,
            executor_adapter=executor}))
        if free then
            local Loop=require("gen1_observation_loop")
            local Checkpoint=require("gen1_inventory_checkpoint")
            local function loop_ready()
                local baseline=assert(self.store:read()).observation
                -- Held-phase writes finish, and every held-phase event is acknowledged, before the
                -- core is released: the initial save is an image command prepared from the enrollment
                -- checkpoint, and gen1_held_save_image.classify refuses it once the core has moved.
                if #assert(journal:pending_commands())>0 or #assert(journal:pending_events())>0 then return false end
                return self.runtime:has_service_lease() and self.observer.signals~=nil and self.acquisitions~=nil
                    and baseline.initial_inventory~=nil and baseline.initial_inventory.phase=="acknowledged"
                    and (launch.resume~=nil or (baseline.bootstrap~=nil and baseline.bootstrap.phase=="acknowledged"))
                    and (not native or (self.reattach_verdict=="clean" and self.reattach_server~=nil
                        and self.reattach_server.verdict=="released" and self.reattach_server.read_digest==self.reattach_read_digest))
            end
            local function writer_pending()
                return (faint~=nil and faint.pending()) or (self.native~=nil and self.native:pending())
            end
            self.start_loop=function()
                if self.loop or not loop_ready()then return end
                local checkpoint=Checkpoint.new({memory=memory,variant=launch.cartridge.variant,host=self.host,holds=self.holds,
                    owned=owned,source_owned=source_owned,native=native~=nil})
                self.loop_ctx={engine=self.observer.signals,observers=self.acquisitions,owned=source_owned,instruction=self.instruction,
                    rom_hash=function()return gameinfo.getromhash():lower()end,
                    baseline=function()return assert(self.store:read()).observation end,
                    pending_inventory_retry=function()
                        return assert(self.store:read()).observation.pending_inventory_retry
                    end,
                    verify=function()
                        assert(self.holds:verify())
                        source_owned()
                        return true
                    end,
                    journal={append=function(_,event,baseline)
                            local ids,why=self.runtime:observe(JSON.array({event}),baseline);return ids and ids[1],why end,
                        append_many=function(_,events,baseline)return self.runtime:observe(events,baseline)end},
                    session={pump=function()assert(self.runtime:step())end}, -- never blocks: connector settimeout(0)
                    inventory=function(frame)return checkpoint:inventory(frame)end,
                    checkpoint=function(previous,force,frame)return checkpoint:checkpoint(previous,force,frame)end,
                    writer={pending=writer_pending,service=function()
                        if self.native and self.native:pending() and not (faint~=nil and faint.pending()) then
                            -- Arm at this loop boundary (between frames). The native vote keeps the core held
                            -- until the command completes; the entry services it in step() slices.
                            self.native:hold()
                            return
                        end
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
            if self.continue_observer then local w=self.continue_observer.status();assert(not w.failed,w.failed)end
            local physical_frame=emu.framecount()
            -- Retained notices count emulated frames: one overlay render per new frame, none while held.
            if physical_frame~=self.rendered_frame then self.rendered_frame=physical_frame;self.overlay.render()end
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
                local visible=memory.isPartyWriteSafe() and memory.readPlayerName()~="" and memory.read_u8(0xFF47)~=0
                if native then
                    -- Held (claimed in start()): read the physical arming state, then either begin under
                    -- this hold (in play, or a reattach that must not see a free frame) or release the
                    -- hold for exactly one boot frame and read again before the next.
                    assert(self.holds:set("startup",true,"native pre-frame check"))
                    local physical=native_physical()
                    if physical=="clean" and not visible then
                        assert(self.holds:set("startup",false,"clean boot frame may run"))
                        self.booting=true
                        return
                    end
                    self.booting=false
                    self.reattach_required=physical~="clean"
                    begin()
                    self:classify_reattach(physical)
                    return
                end
                if not visible then return end
                begin()
            end
            if native and self.reattach_republish and self.runtime:is_bound() and self.holds:is_held() then
                self.reattach_republish=false
                self:republish_reattach()
            end
            if self.loop then
                -- One tick per emulated frame (run() advances it). Under a hold taken outside the loop
                -- only the runtime pumps, so a tick never re-observes the same frame; a native command
                -- holds through its own vote and is serviced in bounded slices instead.
                if self.holds:is_held() then
                    if self.native_host and self.native_host.armed() then
                        self.native:service_slice(function()return self.runtime:step()end)
                    else assert(self.runtime:step())end
                else self.loop:tick()end
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
    -- The physical verdict under the hold. It never releases anything by itself: the free loop is
    -- constructed only when this is "clean" AND the server has granted the service lease and
    -- delivered no pending command (loop_ready), i.e. the server, not these bytes, says nothing is
    -- owed. Anything else stays held (no forward recovery in this build). Publication of the read
    -- as the first post-HELLO semantic evidence is a pending shared-file seam (gen1_runtime.py).
    function self:classify_reattach(physical)
        local read=assert(self.reattach_read,"native reattach read required")
        local lease=read.lease
        if physical=="clean" and (read.published or read.armed or read.done) then physical="armed" end
        if physical=="clean" and lease.phase~="idle" and lease.phase~="released" then physical="lease_open" end
        self.reattach_verdict=physical
        if physical~="clean" then
            self.phase="native_reattach_held";self.reason="native reattach requires classification ("..physical.."); execution stays held"
        end
        -- Publish the read as this client's first NEW semantic evidence after HELLO/control, still
        -- held (older durable outbox items, if any, precede it; they carry no authority). The hold
        -- is released only by the server's exact verdict on this digest (see the journal callback).
        local Canonical=require("journal_document")
        self.reattach_read_digest=self.store.backend.sha256(assert(Canonical.encode(read)))
        local event={event="native_reattach",payload={schema="rby-native-reattach-v1",
            context_generation=context.context_generation,final_sha1=launch.cartridge.final_rom_sha1,physical=physical,read=read}}
        local baseline=assert(self.store:read()).observation
        baseline.native_reattach={read_digest=self.reattach_read_digest,verdict="pending",class=physical}
        local ids,why=self.runtime:observe(JSON.array({event}),baseline)
        assert(ids,why)
        return physical
    end
    -- After a revoke/re-admission: a fresh held read under the current binding (the old verdict is
    -- discarded; the loop, if any, stays under the lifecycle hold until the server answers again).
    function self:republish_reattach()
        assert(self.host.status().physical_stop_verified,"native reattach republication requires the hold")
        self.reattach_read=require("gen1_native_reattach").read({host=self.host,memory=memory,manifest=native,
            lease=function()return self.native.native_store:read()end})
        self.reattach_server=nil
        return self:classify_reattach(native_physical())
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
            resume=launch.resume,continue_observer=self.continue_observer and self.continue_observer.status() or nil,
            engine_signals=self.observer and self.observer.signals and self.observer.signals:status()or nil,
            runtime=self.runtime and self.runtime:status({summary=true}) or nil,
            observation_diagnostics=self.loop and self.loop:status()or nil,
            hud=self.hud and self.hud.status() or nil,
            continuity=self.continuity_status,
            hold_mux=self.holds and self.holds:status() or nil,
            native=self.native and self.native:status() or nil,
            native_host=self.native_host and self.native_host.status() or nil,
            native_reattach=self.reattach_read and {read=self.reattach_read,verdict=self.reattach_verdict,
                read_digest=self.reattach_read_digest,server=self.reattach_server,
                required_before_first_frame=self.reattach_required} or nil,
            ordinary_execution=false,
            free_service=free,observation_loop=self.loop~=nil}))))
    end
    function self:close()
        if self.holds then assert(self.holds:set("lifecycle",true,"client service is closing"))end
        if self.instruction then self.instruction:close()end
        if self.acquisitions then self.acquisitions:close()end
        if self.bootstrap then self.bootstrap.close()end
        if self.continue_observer then self.continue_observer.close()end
        if self.observer then self.observer:close()end
        if self.load_state_hook then event.unregisterbyid(self.load_state_hook);self.load_state_hook=nil end
        if self.runtime then self.runtime:revoke("client service is closing")end
        if self.native then self.native:close()end
        if self.store then self.store:close()end
        if self.overlay_clear then
            assert(self.overlay_clear()==true)
            if rawget(_G,"SLINK_RUNTIME_OVERLAY_CLEAR")==self.overlay_clear then
                _G.SLINK_RUNTIME_OVERLAY_CLEAR=nil
            end
        end
        -- Stopping a Lua service cannot release gameplay. Its independent host
        -- lease remains held until controlled recovery or process exit.
    end
    return self
end

function M.run(launch)
    local service=M.start(launch)
    _G.SLINK_RUNTIME_STATUS=function()return service:status()end
    console.log("[SLink] Waiting for the initial verified overworld checkpoint")
    while true do
        local ok,why=service:step()
        if not ok then
            local captured,status=pcall(function()return service:status()end)
            if captured then _G.SLINK_RUNTIME_STATUS=function()return status end end
            service:close();error(why,0)
        end
        if (service.loop or service.booting) and not service.host.status().held then emu.frameadvance()
        elseif service.host then assert(service.host.yield_held())else emu.yield()end
    end
end
return M
