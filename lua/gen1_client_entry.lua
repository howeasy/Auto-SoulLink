-- Run-bound RBY client lifecycle under an independent hold. held_service clients
-- enroll and may execute only server-permitted writes; gameplay stays held.
-- free_service (P10): observe free, hold to write. The loop of gen1_observation_loop.lua
-- ticks once per emulated frame; the heartbeat checkpoint and every write take a
-- momentary verified hold of their own.
local M={WRITE_SERVICE_SECONDS=2}
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
        self.host=assert(Execution.new({profile="gambatte",owner_id=instance,exclusive_ownership="emulator_process",
            control_context="between_frames",expected_host=assert(Execution.supported_profile("gambatte"))}))
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
        if free then
            self.acquisitions=require("gen1_acquisition_observers").new({variant=launch.cartridge.variant,
                final_sha1=launch.cartridge.final_rom_sha1,owned=source_owned,
                held=function()return self.host.status().physical_stop_verified==true or at_boundary() end})
            -- In-battle death delivery (handoff item 5): the window service arms the one-instruction executor
            -- under the loop boundary predicate; its rows close the server's battle_instruction command.
            self.instruction=require("battle_force_authority").service({journal=journal,memory=memory,owner_id=instance,held=at_boundary,
                unwrap=function(entry)return require("gen1_runtime").unwrap(entry.body,launch.player)end})
        end
        self.runtime=assert(require("gen1_runtime").new({run_id=launch.run_id,player=launch.player,
            variant=launch.cartridge.variant,server_host=launch.host,server_port=launch.port,
            control_interval=free and 0.5 or nil,
            sync_interval=free and 1 or nil,
            prepared_cartridge=launch.cartridge,
            transport=require("connector"),journal=journal,clock=clock,
            host={set_held=function(held,reason)
                -- Authority bookkeeping only once the loop runs: the loop and its writer own the physical hold (P10).
                if free and self.loop then return true end
                if not held then
                    self.host.set_held(true,"ordinary execution is not qualified for this launcher")
                    return false
                end
                return self.host.set_held(true,reason)
            end},
            read_context=free and source_owned or owned,
            operation_execution=operations,
            operation_ready=ready,
            executor_adapter=executor}))
        if free then
            local Loop=require("gen1_observation_loop")
            local function loop_ready()
                local baseline=assert(self.store:read()).observation
                -- Held-phase writes finish, and every held-phase event is acknowledged, before the
                -- core is released: the initial save is an image command prepared from the enrollment
                -- checkpoint, and gen1_held_save_image.classify refuses it once the core has moved.
                if #assert(journal:pending_commands())>0 or #assert(journal:pending_events())>0 then return false end
                return self.runtime:is_bound() and self.observer.signals~=nil and self.acquisitions~=nil
                    and baseline.initial_inventory~=nil and baseline.initial_inventory.phase=="acknowledged"
                    and baseline.bootstrap~=nil and baseline.bootstrap.phase=="acknowledged"
            end
            local function writer_pending()
                if not memory.isPartyWriteSafe()then return false end -- in battle the command waits (item 5)
                local entry=assert(journal:pending_commands())[1]
                return entry~=nil and require("gen1_held_faint").handles(require("gen1_runtime").unwrap(entry.body,launch.player))
            end
            self.start_loop=function()
                if self.loop or not loop_ready()then return end
                self.loop_ctx={engine=self.observer.signals,observers=self.acquisitions,owned=source_owned,instruction=self.instruction,
                    rom_hash=function()return gameinfo.getromhash():lower()end,
                    baseline=function()return assert(self.store:read()).observation end,
                    journal={append=function(_,event,baseline)
                            local ids,why=self.runtime:observe(JSON.array({event}),baseline);return ids and ids[1],why end,
                        append_many=function(_,events,baseline)return self.runtime:observe(events,baseline)end},
                    session={pump=function()assert(self.runtime:step())end}, -- never blocks: connector settimeout(0)
                    inventory=function()
                        -- Captured under a momentary verified hold, so the host stanza (held=true) is true
                        -- and matches the initial observation the server compares it with.
                        if not memory.isPartyWriteSafe()then return nil end
                        assert(self.host.set_held(true,"heartbeat inventory checkpoint"))
                        local ok,point=pcall(Observation.capture,{owned=owned,host=self.host,memory=memory,variant=launch.cartridge.variant})
                        assert(self.host.set_held(false,"free-running observation"))
                        if not ok then error(point,0)end
                        return point
                    end,
                    writer={pending=writer_pending,service=function()
                        -- ponytail: whole-command hold, bounded per tick and retried while pending; item 4
                        -- maps every engine command to its executor and item 5 adds the in-battle window.
                        assert(self.host.set_held(true,"servicing a held write command"))
                        local deadline=clock()+M.WRITE_SERVICE_SECONDS
                        local ok,why=pcall(function()
                            while writer_pending() and clock()<deadline do
                                assert(self.runtime:step());assert(self.host.yield_held())
                            end
                        end)
                        assert(self.host.set_held(false,"free-running observation"))
                        if not ok then error(why,0)end
                    end}}
                self.loop=Loop.new(self.loop_ctx) -- adopts the persisted cursor, or takes observers:initial under the hold
                assert(self.host.set_held(false,"free-running observation"))
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
                if self.host.status().held then assert(self.runtime:step())else self.loop:tick()end
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
            if self.host then pcall(function()self.host.set_held(true,"client entry failed")end)end
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
            ordinary_execution=false,
            free_service=free,observation_loop=self.loop~=nil}))))
    end
    function self:close()
        if self.instruction then self.instruction:close()end
        if self.acquisitions then self.acquisitions:close()end
        if self.bootstrap then self.bootstrap.close()end
        if self.observer then self.observer:close()end
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
