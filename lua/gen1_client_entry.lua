-- Run-bound RBY client lifecycle under an independent hold. Initial-observation
-- clients may execute only server-permitted faint writes; ordinary frames stay held.
local M={}
local function hex(value,size)
    return type(value)=="string" and #value==size and value:match("^[0-9a-f]+$")~=nil
end
local function validate(launch)
    assert(type(launch)=="table" and launch.schema=="slink-gen1-launch-v1"
        and launch.protocol=="slink-gen1-durable-v1" and launch.mode=="held_service","unsupported RBY launch configuration")
    assert(hex(launch.run_id,32) and (launch.player=="a" or launch.player=="b"),"invalid launch run/player")
    assert(type(launch.host)=="string" and not launch.host:find("[%s%c]") and #launch.host>0 and #launch.host<=255
        and type(launch.port)=="number" and launch.port%1==0 and launch.port>=1 and launch.port<=65535,"invalid launch endpoint")
    assert(type(launch.cartridge)=="table" and hex(launch.cartridge.final_rom_sha1,40),"expected RBY cartridge required")
    assert(launch.initial_observations==nil or launch.initial_observations==true,"invalid initial observation selection")
    assert(launch.ordinary_frames==nil or launch.ordinary_frames==true and launch.initial_observations==true,
        "ordinary frames require initial observation enrollment")
    assert(launch.native_manifest==nil or type(launch.native_manifest)=="table"and launch.ordinary_frames==true
        and launch.cartridge.capabilities.pc_trade==true
        and launch.native_manifest.final_sha1==launch.cartridge.final_rom_sha1
        and launch.native_manifest.variant==launch.cartridge.variant,"native launch requires the admitted bounded companion")
    local variant=launch.cartridge.variant
    assert(variant=="red" or variant=="blue" or variant=="yellow","RBY variant required")
end

function M.start(launch,options)
    validate(launch)
    options=options or {}
    local root=assert(options.root or rawget(_G,"SLINK_ROOT"),"SLink client root required")
    package.path=root.."/lua/?.lua;"..root.."/data/games/gen1_rby/?.lua;"..package.path
    local JSON=require("json_codec")
    launch=assert(JSON.decode(assert(JSON.encode(launch))))
    local memory=require("memory_gb")
    memory.initProfile(require("games.gen1_rby"),launch.cartridge.variant)
    assert(gameinfo.getromhash():lower()==launch.cartridge.final_rom_sha1,"loaded ROM differs from the run launcher")
    local actual=assert(require("gen1_runtime_profiles").metadata(launch.cartridge.variant,launch.cartridge))
    assert(JSON.encode(actual)==JSON.encode(launch.cartridge),"loaded cartridge profile differs from the launcher")
    local self={phase="waiting_for_overworld",reason="Waiting for a verified overworld checkpoint",host=nil,runtime=nil,store=nil}
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
        if launch.ordinary_frames then
            self.bounded=assert(require("platform_bounded_execution").new({profile="gambatte",owner_id=instance,
                expected_host=assert(Execution.supported_profile("gambatte")),authorize=function(scope,checkpoint)
                    if scope.phase~="ordinary"then return self.native~=nil and self.native.authorize_step(scope,checkpoint)end
                    return self.frames~=nil and self.frames:authorize(scope,checkpoint)
                end}))
            self.host={set_held=self.bounded.set_held,yield_held=self.bounded.yield_held,status=function()
                local bounded=self.bounded.status();local status=bounded.host
                status.physical_stop_verified=status.physical_stop_verified and not bounded.failed
                    and emu.framecount()==bounded.expected_frame
                return status
            end}
        else
            self.host=assert(Execution.new({profile="gambatte",owner_id=instance,exclusive_ownership="emulator_process",
                control_context="between_frames",expected_host=assert(Execution.supported_profile("gambatte"))}))
        end
        assert(self.host.set_held(true,"waiting for qualified paired runtime bindings"))
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
        local Native=launch.native_manifest and require("gen1_native_runtime")or nil
        local callbacks=Native and Native.journal_options(Observation,function()return self.native end)or Observation
        local journal=assert(Journal.open(self.store,nil,callbacks))
        -- Execution hooks may run inside an authorized frame. They validate the
        -- stable ROM/save identity; publication and writes also require a hold.
        if launch.ordinary_frames then
            self.identity=require('gen1_identity_guard').new({variant=launch.cartridge.variant,
                final_sha1=launch.cartridge.final_rom_sha1,context=function()return context end})
        end
        local function source_owned()
            assert(gameinfo.getromhash():lower()==launch.cartridge.final_rom_sha1
                and string.format("%04X",memory.readPlayerId())==context.save_identity.ot_id
                and (self.identity and self.identity.check()or memory.readPlayerName()==context.save_identity.trainer_name),"ROM/save changed after launch")
            return context
        end
        local function owned()
            local expected=self.bounded and self.bounded.status().expected_frame or first_frame
            assert(self.host.status().physical_stop_verified and emu.framecount()==expected,"held physical context changed")
            return source_owned()
        end
        local function unavailable()error("cartridge execution is not selected in held-service launch mode",0)end
        local clock=assert(require("platform_clock").new())
        self.clock=clock
        local faint=Observation and require("gen1_held_faint").new({journal=journal,memory=memory,player=launch.player,
            variant=launch.cartridge.variant,owned=owned,host=self.host,clock=clock,
            saveram_directory=self.saveram_directory})or nil
        if Observation then self.observer=Observation.new({memory=memory,variant=launch.cartridge.variant,
            journal=journal,host=self.host,owned=owned,source_owned=source_owned,engine_signals=true,
            bootstrap=self.bootstrap,ordinary_frames=launch.ordinary_frames})end
        local operations=faint and faint.operations or nil
        local ready=faint and faint.ready or function()return false,"Waiting for qualified cartridge execution and reconciliation"end
        local executor=faint and faint.adapter or {prepare=unavailable,classify=unavailable,apply=unavailable,receipt=unavailable}
        if launch.ordinary_frames then
            local Frames=require("gen1_frame_client")
            self.acquisitions=require("gen1_acquisition_observers").new({variant=launch.cartridge.variant,
                final_sha1=launch.cartridge.final_rom_sha1,owned=source_owned,
                held=function()return self.host.status().physical_stop_verified==true end})
            local progress_path=tostring(luanet.import_type("System.IO.Path").GetDirectoryName(self.path)).."/frame-progress.json"
            self.frame_store=assert(Store.open(assert(Storage.new(progress_path)),
                {schema="rby-frame-progress-storage-binding-v1",run_id=launch.run_id,player=launch.player,
                    context_generation=generation,physical_instance=instance,cartridge=launch.cartridge},Frames.initial()))
            self.frames=Frames.new({journal=journal,progress_store=self.frame_store,owned=owned,host=self.host,clock=clock,
                native_host=self.bounded,
                observe=function(events,baseline)return self.runtime:observe(events,baseline)end,
                inflight=function()return self.runtime and self.runtime:status({summary=true}).request~=nil end,
                step_one=self.bounded.step_one,rate=self.bounded.status().frame_rate,
                signals=function()return self.observer.signals end,
                acquisitions=function()return self.acquisitions end,
                stop_after_step=function()
                    return self.native~=nil and require("gen1_receptionist_client").query(memory,launch.native_manifest)~=nil
                end,
                boundary=function()
                    local current=owned();local status=self.host.status()
                    return {schema="rby-frame-boundary-v1",context_generation=current.context_generation,
                        final_sha1=gameinfo.getromhash():lower(),frame=emu.framecount(),
                        host={owner_id=status.owner_id,capability_id=status.capability_id,process_id=status.process_id,held=true}}
                end,
                inventory=function()
                    local manifest=self.native and launch.native_manifest or nil
                    if not memory.isPartyWriteSafe()and not(manifest and require("gen1_receptionist_client").query(memory,manifest))then return nil end
                    return Observation.capture({owned=owned,host=self.host,memory=memory,variant=launch.cartridge.variant,native_manifest=manifest})
                end,
                native_checkpoint=launch.native_manifest and function()
                    if memory.getPartyCount()<1 then return nil end
                    return {schema="rby-native-observation-v1",
                        party=assert(require("gen1_command_receipts").party_snapshot(memory,launch.cartridge.variant))}
                end})
            local commands=faint
            if Native then
                self.native=Native.new({embedded=true,frame_accounting=true,memory=memory,manifest=launch.native_manifest,
                    variant=launch.cartridge.variant,player=launch.player,run_id=launch.run_id,
                    context=context,read_context=source_owned,clock=clock,host=self.bounded,journal=journal,
                    identity_check=function()return self.identity.check()end,
                    storage_directory=tostring(luanet.import_type("System.IO.Path").GetDirectoryName(self.path)).."/native",
                    saveram_directory=self.saveram_directory,
                    receptionist=true,
                    observe=function(events,baseline)return self.runtime:observe(events,baseline)end,
                    read_runtime_status=function()return self.runtime and self.runtime:status({summary=true})or {}end,
                    adopt_sources=function(source,marker)
                        assert(self.observer.signals:status().pending==0,"native execution left unaccounted engine signals")
                        return self.acquisitions:adopt_native_handoff(source,marker)
                    end})
                commands=require("command_service_router").new({
                    {handles=require("gen1_held_faint").handles,adapter=faint.adapter,ready=faint.ready,operations=faint.operations},
                    {handles=self.native.handles,adapter=self.native.executor_adapter,ready=self.native.ready,
                        operations=self.native.operations,update_control=self.native.update_control}})
                executor=commands.adapter
            end
            local function command_allowed(body)
                if not self.frames:blocks_commands()then return true end
                return self.native~=nil and self.frames:status().native_borrowed and self.native.handles(body)
            end
            local route
            operations={
                request=function(binding,control)
                    route=nil
                    if self.native then self.native.update_control(binding,control)end
                    local blocked=self.frames:blocks_commands()
                    if self.native and self.frames:status().native_borrowed then
                        local packet=self.native.operations.request(binding,control)
                        if packet then route="native";return packet end
                    elseif not blocked then
                        local packet=commands.operations.request(binding,control)
                        if packet then route="commands";return packet end
                    end
                    local packet=self.frames:request(binding,control)
                    if packet then route="ordinary";return packet end
                end,
                accept=function(packet,binding)
                    self.frames:control(binding)
                    local selected=route;route=nil
                    local ok,why=true
                    if selected=="ordinary"then ok,why=self.frames:accept(packet)
                    elseif selected=="commands"then ok,why=commands.operations.accept(packet)
                    elseif selected=="native"then ok,why=self.native.operations.accept(packet)
                    else assert(packet==nil,"unsolicited operation execution grant")end
                    if not ok then return false,why end
                    assert(self.frames:flush_closed_after_response())
                    return true
                end,
                authorize_apply=function(body,...)
                    if not command_allowed(body)then return false,"frame observations must close before command effects"end
                    return commands.operations.authorize_apply(body,...)
                end,
                revoke=function(why)route=nil;self.frames:revoke(why);commands.operations.revoke(why)end,
                status=function()return {ordinary=self.frames:status(),commands=commands.operations.status()}end}
            ready=function(body,...)
                if not command_allowed(body)then return false,"frame observations must close before command effects"end
                return commands.ready(body,...)
            end
        end
        self.runtime=assert(require("gen1_runtime").new({run_id=launch.run_id,player=launch.player,
            variant=launch.cartridge.variant,server_host=launch.host,server_port=launch.port,
            control_interval=launch.ordinary_frames and 0.5 or nil,
            sync_interval=launch.ordinary_frames and 1 or nil,
            prepared_cartridge=launch.cartridge,
            transport=require("connector"),journal=journal,clock=clock,
            host={set_held=function(held,reason)
                if not held then
                    self.host.set_held(true,"ordinary execution is not qualified for this launcher")
                    return false
                end
                return self.host.set_held(true,reason)
            end},
            read_context=owned,
            operation_execution=operations,
            operation_ready=ready,
            executor_adapter=executor}))
        self.phase="held_service";self.reason="Durable connection active; gameplay remains held"
        console.log("[SLink] Started run "..launch.run_id.." player "..launch.player.."; waiting for admission in held service")
    end
    function self:step()
        if self.phase=="failed"then return false,self.reason end
        local ok,why=pcall(function()
            assert(gameinfo.getromhash():lower()==launch.cartridge.final_rom_sha1,"launch cartridge changed")
            if not self.runtime then
                -- Hold at the first safe overworld frame that is also visible. A fresh
                -- New Game reaches write-safety inside the white fade into the
                -- bedroom (rBGP==0x00); holding there freezes a blank screen and
                -- proves nothing. Battery-save boots are already faded in.
                if not memory.isPartyWriteSafe() or memory.readPlayerName()=="" or memory.read_u8(0xFF47)==0 then return end
                begin()
            end
            if self.native and (not self.frames:blocks_commands()or self.frames:status().native_borrowed)then
                self.native:pump_native()
            end
            local began=self.clock()
            local serviced,reason=self.runtime:step()
            assert(serviced,reason)
            if self.native then self.native:after_service(began)end
            if self.observer then self.observer:step(self.runtime:is_bound())end
            if self.native and self.frames:status().native_borrowed then self.native:step_native()
            elseif self.frames then assert(self.frames:step(self.runtime:is_bound()))end
        end)
        if not ok then
            self.phase="failed";self.reason=tostring(why)
            if self.runtime then pcall(function()self.runtime:revoke("client entry failed")end)end
            if self.host then pcall(function()self.host.set_held(true,"client entry failed")end)end
            return false,self.reason
        end
        return true
    end
    function self:status()
        local initial,bootstrap
        if self.frames then initial,bootstrap=self.frames:enrollment()
        else
            local observation=self.store and self.store:read().observation or {}
            initial=observation.initial_inventory and observation.initial_inventory.phase
            bootstrap=observation.bootstrap and observation.bootstrap.phase
        end
        return assert(JSON.decode(assert(JSON.encode({phase=self.phase,reason=self.reason,run_id=launch.run_id,player=launch.player,
            context=context,journal_path=self.path,host=self.host and self.host.status() or nil,
            initial_observation=initial,
            bootstrap=self.bootstrap and self.bootstrap.status() or nil,
            bootstrap_observation=bootstrap,
            engine_signals=self.observer and self.observer.signals and self.observer.signals:status()or nil,
            runtime=self.runtime and self.runtime:status({summary=true}) or nil,
            frame_progress=self.frames and self.frames:status()or nil,ordinary_execution=false}))))
    end
    function self:close()
        if self.native then self.native:close()end
        if self.acquisitions then self.acquisitions:close()end
        if self.bootstrap then self.bootstrap.close()end
        if self.observer then self.observer:close()end
        if self.identity then self.identity.close()end
        if self.runtime then self.runtime:revoke("client service is closing")end
        if self.frame_store then self.frame_store:close()end
        if self.store then self.store:close()end
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
        if service.host then assert(service.host.yield_held())else emu.yield()end
    end
end
return M
