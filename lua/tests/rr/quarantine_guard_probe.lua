-- Private quarantine-only MainForm routing proof. Never releases the initial
-- hold, executes restored native PING, or selects production execution safety.
return function(ctx)
    local C,O,check=ctx.config,ctx.config.probe_options,ctx.check
    local main=ctx.main_form
    local out={classification="quarantine_only_host_routing",release_ready=false,production_selected=false,
        general_interlock_proved=false,actions={},statuses={},periods={}}
    ctx.report.evidence.runtime=out
    local Type=luanet.import_type("System.Type")
    local Delegate=luanet.import_type("System.Delegate")
    local Enum=luanet.import_type("System.Enum")
    local File=luanet.import_type("System.IO.File")
    local Hash=luanet.import_type("System.Security.Cryptography.SHA256")
    local Bits=luanet.import_type("System.BitConverter")
    local Object=luanet.import_type("System.Object")
    local function digest(path)
        local hash=Hash.Create();local stream=File.OpenRead(path)
        local result=tostring(Bits.ToString(hash:ComputeHash(stream))):gsub("-",""):lower()
        stream:Dispose();hash:Dispose();return result
    end
    local function hex(a,n)
        local bytes={};for i=0,n-1 do bytes[#bytes+1]=string.format("%02x",memory.read_u8(a+i)) end
        return table.concat(bytes)
    end
    local nlua=Type.GetType("NLua.Lua, NLua")
    check("quarantine_nlua_loaded",nlua~=nil,true)
    check("quarantine_nlua_hash",digest(tostring(nlua.Assembly.Location)),
        "f413017bfc7a37dfcaeb6e6c24812fd12ceb2b4b107a066512ed28c13010b234")
    local Process=luanet.import_type("System.Diagnostics.Process")
    local process=Process.GetCurrentProcess()
    local modules=process.Modules:GetEnumerator();local lua_count=0
    while modules:MoveNext() do
        local module=modules.Current
        if tostring(module.ModuleName):lower()=="lua54.dll" then
            lua_count=lua_count+1
            check("quarantine_native_lua_hash",digest(tostring(module.FileName)),
                "4786e0df4caf120e3bedf0b6dda260525df2187c66ded220a21a53ace76b0501")
        end
    end
    check("quarantine_native_lua_unique",lua_count,1)
    process:Dispose()
    check("quarantine_purpose",C.purpose,"validation")
    check("quarantine_frozen03",C.identity.rom_sha256,"3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301")
    check("descriptor_matches_bound_rom",hex(C.descriptor.address,C.descriptor.size),C.descriptor.hex)
    local first=emu.framecount()
    for _,step in ipairs(C.fixture_meta.boot_inputs) do
        for _=1,step.frames do
            check("quarantine_boot_budget_"..emu.framecount(),emu.framecount()-first<C.frames,true)
            joypad.set(step.buttons or {});emu.frameadvance()
        end
    end
    joypad.set({})
    for i,a in ipairs(C.fixture_meta.ram_assertions) do
        local value=a.width==1 and memory.read_u8(a.address) or (a.width==2 and memory.read_u16_le(a.address) or memory.read_u32_le(a.address))
        check("quarantine_fixture_"..i,value,a.expected)
    end
    check("fixture_loaded",true,true)
    if O.initial_user_pause then client.pause() end
    check("quarantine_requested_pause",main.EmulatorPaused,O.initial_user_pause==true)
    local dll=C.source_root.."/host_artifacts/SLink.QuarantineGuard.dll"
    local loader_dll=C.source_root.."/host_artifacts/SLink.QuarantineProbe.dll"
    local state_path=C.source_root.."/host_artifacts/busy_ping.State"
    check("quarantine_dll_hash",digest(dll),O.dll_sha256)
    check("quarantine_loader_hash",digest(loader_dll),O.loader_sha256)
    check("quarantine_state_hash",digest(state_path),O.state_sha256)
    check("quarantine_adapter_hash",digest(C.source_root.."/lua/platform_execution.lua"),O.adapter_sha256)
    local Execution=dofile(C.source_root.."/lua/platform_execution.lua")
    local owner,why=Execution.new({owner_id=O.owner_id,expected_host=O.expected_host,
        exclusive_ownership="emulator_process",control_context="between_frames"})
    check("quarantine_initial_actuator",owner~=nil,true)
    if not owner then error(why) end
    check("quarantine_preheld",owner.set_held(true,"private quarantine routing probe"),true)
    check("quarantine_initial_held_yield",owner.yield_held(),true)
    out.initial_actuator=owner.status()
    local frame,pause,core=emu.framecount(),main.EmulatorPaused,main.Emulator
    local before_mailbox,before_party=hex(0x0203F800,64),hex(0x02024284,600)
    out.initial_frame=frame;out.initial_mailbox=before_mailbox
    -- Exact source-verified private field lookup, used only by this probe to call
    -- the public tool loader. It never changes the manager's registry directly.
    local flags=Enum.Parse(Type.GetType("System.Reflection.BindingFlags"),"Instance, NonPublic")
    local field=main:GetType():GetField("Tools",flags)
    check("quarantine_manager_field",field~=nil,true)
    local manager=field:GetValue(main)
    check("quarantine_manager_type",tostring(manager:GetType().FullName),"BizHawk.Client.EmuHawk.ToolManager")
    -- NLua load_assembly resolves assembly names; use the CLR path loader first.
    local Assembly=luanet.import_type("System.Reflection.Assembly")
    local loaded=Assembly.LoadFrom(loader_dll)
    check("quarantine_loader_actual_hash",digest(tostring(loaded.Location)),O.loader_sha256)
    luanet.load_assembly(tostring(loaded.FullName))
    local Loader=luanet.import_type("SLink.Tests.QuarantineLoader")
    local loader=Loader(manager,dll)
    local callback=Delegate.CreateDelegate(Type.GetType("System.Action"),loader,loader:GetType():GetMethod("Run"))
    ctx.checkpoint("quarantine_loader_ready")
    -- Scalar params arguments avoid NLua wrapping a supplied object[] again.
    local pending=main:BeginInvoke(callback)
    ctx.checkpoint("quarantine_loader_queued")
    local clock=assert(dofile(C.source_root.."/lua/platform_clock.lua").new())
    local started=clock();local loader_ticks=0
    while not pending.IsCompleted do
        loader_ticks=loader_ticks+1
        check("quarantine_loader_deadline_"..loader_ticks,clock()-started<5,true)
        emu.yield()
    end
    main:EndInvoke(pending)
    out.loader_error=loader.Error and tostring(loader.Error) or nil
    ctx.checkpoint("quarantine_loader_returned")
    check("quarantine_loader_no_error",loader.Completed and loader.Error==nil,true)
    local guard=loader.Result
    check("quarantine_loaded",guard~=nil,true)
    check("quarantine_actual_type",tostring(guard:GetType().FullName),"SLink.Host.QuarantineGuard")
    check("quarantine_actual_dll",digest(tostring(guard:GetType().Assembly.Location)),O.dll_sha256)
    check("quarantine_load_kept_hold",main.BlockFrameAdvance,true)
    check("quarantine_load_kept_frame",emu.framecount(),frame)
    check("quarantine_armed",guard:QuarantineArm(O.guard_nonce),true)
    -- The extra tool is outside the old actuator's ordinary scope. Retain that
    -- object/lease but never ask it to release/adopt the expanded host scope.
    out.actuator_scope="held lease retained; no original actuator operations after tool load"
    local function status(label)
        local s=guard:QuarantineStatus()
        local result={label=label,armed=s.Armed,failed=s.Failed,failure=tostring(s.Failure),
            held=s.HoldReadbackVerified,blocked=s.HostBlocked,selected=s.SelectedForAllControls,
            original_core=s.OriginalCore,frame=s.CurrentFrame,last_sequence=tonumber(s.LastSequence),
            full_execution_safety=s.FullExecutionSafety,production_selected=s.ProductionSelected}
        out.statuses[#out.statuses+1]=result;return result
    end
    local s=status("armed")
    check("quarantine_selected",s.selected and s.original_core and s.held and not s.failed,true)
    check("quarantine_no_activation",not s.full_execution_safety and not s.production_selected,true)
    -- Pinned NLua's name-cache fast path extracts arg1 before removing the
    -- instance receiver. A MethodInfo-backed signature binding retains its
    -- target separately and correctly supplies repeated Int64 cursor arguments.
    local poll=luanet.get_method_bysig(guard,"QuarantinePoll","System.Int64")
    local load_state=luanet.get_method_bysig(main,"LoadState","System.String","System.String","System.Boolean")
    local function unchanged(label)
        check(label.."_hold",main.BlockFrameAdvance,true)
        check(label.."_pause",main.EmulatorPaused,pause)
        check(label.."_frame",emu.framecount(),frame)
        check(label.."_core",Object.ReferenceEquals(main.Emulator,core),true)
        check(label.."_mailbox",hex(0x0203F800,64),before_mailbox)
        check(label.."_party",hex(0x02024284,600),before_party)
    end
    local function action(label,expected_action,expected_return,call)
        local cursor=tonumber(guard:QuarantineStatus().LastSequence)
        local ok,value=pcall(call)
        local recorded={label=label,call_ok=ok,returned=value};out.actions[#out.actions+1]=recorded
        check(label.."_call",ok,true)
        if expected_return~=nil then check(label.."_return",value,expected_return) end
        check(label.."_cursor_exact",cursor~=nil and cursor>=0 and cursor==math.floor(cursor) and cursor<9007199254740992,true)
        recorded.cursor_decimal=string.format("%.0f",cursor)
        local records=poll(cursor)
        check(label.."_record_count",tonumber(records.Length),1)
        recorded.action=tostring(records[0].Action);recorded.outcome=tostring(records[0].Outcome)
        recorded.slot=tonumber(records[0].Slot)
        check(label.."_slot",recorded.slot,expected_action=="load_quick_save" and 3 or -1)
        check(label.."_routed",recorded.action,expected_action)
        check(label.."_denied",recorded.outcome,"denied_not_performed")
        unchanged(label)
    end
    action("named_load","load_state",false,function() return load_state(state_path,"private busy state",true) end)
    action("quick_load","load_quick_save",false,function() return main:LoadQuickSave(3,true) end)
    -- Pinned MainForm's private method is the dialog route. Invoke that exact
    -- no-argument entry; this is not evidence of a physical menu click.
    local load_as=main:GetType():GetMethod("LoadStateAs",flags)
    check("quarantine_named_route_found",load_as~=nil,true)
    action("named_dialog","load_state_as",false,function() return load_as:Invoke(main,nil) end)
    action("reboot","reboot_core",true,function() return main:RebootCore() end)
    local save_path=C.result_path:gsub("result.json$","denied-save.State")
    check("quarantine_save_fresh",File.Exists(save_path),false)
    action("named_save","save_state",nil,function()
        main:SaveState(save_path,"private refused save",true);return "host return is not a save receipt"
    end)
    check("quarantine_save_not_written",File.Exists(save_path),false)
    local before_capture=guard:QuarantineStatus().LastSequence
    guard:CaptureRewind()
    check("quarantine_capture_not_request",guard:QuarantineStatus().LastSequence,before_capture)
    local period={frame_before=frame,yields=0};out.periods[#out.periods+1]=period;started=clock()
    while clock()-started<0.25 do
        emu.yield();period.yields=period.yields+1
        check("quarantine_verify_"..period.yields,guard:QuarantineVerify(),true)
        unchanged("quarantine_yield_"..period.yields)
    end
    period.elapsed_ms=(clock()-started)*1000;period.frame_after=emu.framecount()
    status("after_routed_denials")
    if O.inject_hold_loss then
        check("quarantine_fault_requires_user_pause",pause,true)
        -- Private same-thread fault injection under a user-owned pause. No yield
        -- occurs between the flag clear and the guard's hold-only verification.
        main.BlockFrameAdvance=false
        check("quarantine_fault_latched",guard:QuarantineVerify(),false)
        local failed=status("after_injected_hold_loss")
        check("quarantine_fault_retained",failed.failed and failed.held and failed.blocked and failed.selected,true)
        unchanged("quarantine_fault")
        action("failed_named_load","load_state",false,function() return load_state(state_path,"refused after fault",true) end)
    end
    -- Public manager close(Type) removes the registration after Form.Close.
    manager:Close(guard:GetType())
    local closed=status("after_manager_close")
    check("quarantine_close_failed",closed.failed,true)
    check("quarantine_close_hold",closed.held and closed.blocked,true)
    check("quarantine_close_unselected",closed.selected,false)
    unchanged("quarantine_closed")
    out.teardown="private process exit with original and guard holds retained"
    check("quarantine_routing_complete",true,true)
end
