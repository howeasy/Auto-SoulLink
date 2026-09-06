-- Private verification of the actual inactive platform_execution adapter.
-- No cartridge writes or mailbox requests. Faults touch only this host's flag.
return function(ctx)
    local C,check=ctx.config,ctx.check
    local O=C.probe_options
    local out={classification="platform_execution_private_component",mode=O.mode,
        initial_paused=O.initial_paused,adapter_sha256=O.adapter_sha256,
        constructor_attempts={},statuses={},periods={},release_ready=false,
        limitations={"No production control service selected","No reset/load/rewind/debugger interlock proof",
            "Emergency re-hold cannot undo escaped frames","Stopped-held-script refusal does not prove unheld garbage-collection behavior"}}
    ctx.report.evidence.runtime=out
    check("execution_probe_purpose",C.purpose,"validation")
    check("execution_probe_mode",O.mode=="lifecycle" or O.mode=="external_clear" or O.mode=="stopped_reload",true)
    check("execution_host_identity",ctx.host.available and ctx.host.matches_requested_core,true)
    local main=ctx.main_form
    local Thread=luanet.import_type("System.Threading.Thread")
    local function thread_id() return tonumber(Thread.CurrentThread.ManagedThreadId) end
    out.ui_thread_id=thread_id()
    check("execution_ui_thread",main.InvokeRequired,false)
    local clock,why=dofile(C.source_root.."/lua/platform_clock.lua").new()
    if not clock then error(why) end
    local first_frame=emu.framecount()
    local function hex(a,n)
        local bytes={};for i=0,n-1 do bytes[#bytes+1]=string.format("%02x",memory.read_u8(a+i,C.descriptor.domain or "System Bus")) end
        return table.concat(bytes)
    end
    check("descriptor_matches_bound_rom",hex(C.descriptor.address,C.descriptor.size),C.descriptor.hex)
    if C.fixture_kind=="battery" then
        for index,step in ipairs(C.fixture_meta.boot_inputs) do
            check("execution_boot_bound_"..index,type(step.frames)=="number" and step.frames%1==0 and step.frames>=1 and step.frames<=600,true)
            for _=1,step.frames do
                check("execution_boot_budget_"..tostring(emu.framecount()-first_frame),emu.framecount()-first_frame<C.frames,true)
                joypad.set(step.buttons or {});emu.frameadvance()
            end
        end
        joypad.set({})
        for index,a in ipairs(C.fixture_meta.ram_assertions) do
            local value=a.width==1 and memory.read_u8(a.address)
                or (a.width==2 and memory.read_u16_le(a.address) or memory.read_u32_le(a.address))
            check("fixture_ram_"..index,value,a.expected)
        end
        check("fixture_loaded",true,true)
    end
    ctx.checkpoint("execution_fixture_boot_complete")
    if O.initial_paused then client.pause();emu.yield() end
    check("execution_initial_pause",main.EmulatorPaused,O.initial_paused)
    check("execution_initial_flag",main.BlockFrameAdvance,false)
    local module_path=C.source_root.."/lua/platform_execution.lua"
    local first_module,second_module=dofile(module_path),dofile(module_path)
    check("execution_distinct_module_instances",first_module~=second_module,true)
    ctx.checkpoint("execution_modules_loaded")
    local function options(owner)
        return {owner_id=owner,profile=O.profile,expected_host=O.expected_host,
            exclusive_ownership="emulator_process",control_context="between_frames"}
    end
    local function claim(module,owner,label,expected)
        local frame,blocked,paused=emu.framecount(),main.BlockFrameAdvance,main.EmulatorPaused
        local id=thread_id()
        local ok,actuator,reason=pcall(module.new,options(owner))
        local diagnostic_reason=reason
        if not ok then diagnostic_reason=tostring(actuator) end
        out.constructor_attempts[#out.constructor_attempts+1]={label=label,owner_id=owner,
            call_ok=ok,accepted=ok and actuator~=nil,reason=diagnostic_reason,
            ui_thread_id=id,thread_after=thread_id(),frame_before=frame,frame_after=emu.framecount(),
            blocked_before=blocked,blocked_after=main.BlockFrameAdvance,paused_before=paused,paused_after=main.EmulatorPaused}
        ctx.checkpoint("execution_claim_"..label)
        check(label.."_constructor_call",ok,true)
        check(label.."_accepted",actuator~=nil,expected)
        check(label.."_same_ui_thread",id==out.ui_thread_id and thread_id()==id,true)
        check(label.."_no_frame_change",emu.framecount(),frame)
        check(label.."_no_flag_change",main.BlockFrameAdvance,blocked)
        check(label.."_pause_preserved",main.EmulatorPaused,paused)
        if not expected then check(label.."_refusal_reason",type(reason)=="string" and #reason>0,true) end
        return actuator,reason
    end
    local function snapshot(owner,label)
        local status=owner.status();out.statuses[#out.statuses+1]={label=label,frame=emu.framecount(),status=status}
        return status
    end
    local function contenders(label,expected_fragment)
        for index,case in ipairs({{first_module,O.contender_id},{first_module,O.owner_id},
                {second_module,O.contender_id},{second_module,O.owner_id}}) do
            local _,reason=claim(case[1],case[2],label.."_"..index,false)
            check(label.."_reason_"..index,reason:find(expected_fragment,1,true)~=nil,true)
        end
    end
    local function period(owner,label,blocked)
        local start,frame=clock(),emu.framecount()
        local record={label=label,frame_before=frame,paused_before=main.EmulatorPaused,yields=0}
        out.periods[#out.periods+1]=record
        while (clock()-start)*1000<O.hold_ms do
            if owner then
                local ok,reason=owner.yield_held()
                if not ok then error(reason) end
            else emu.yield() end
            record.yields=record.yields+1
            check(label.."_thread_"..record.yields,thread_id(),out.ui_thread_id)
            check(label.."_frame_"..record.yields,emu.framecount(),frame)
            check(label.."_flag_"..record.yields,main.BlockFrameAdvance,blocked)
            check(label.."_pause_"..record.yields,main.EmulatorPaused,O.initial_paused)
        end
        record.elapsed_ms=(clock()-start)*1000;record.frame_after=emu.framecount()
        check(label.."_live_yields",record.yields>0,true)
        ctx.checkpoint("execution_period_"..label)
    end
    if O.mode=="stopped_reload" then
        check("execution_stop_helper_selected",type(O.helper_path)=="string",true)
        local Application=luanet.import_type("System.Windows.Forms.Application")
        ctx.checkpoint("execution_stop_console_lookup")
        local iterator=Application.OpenForms:GetEnumerator();local console
        while iterator:MoveNext() do
            if tostring(iterator.Current:GetType().FullName)=="BizHawk.Client.EmuHawk.LuaConsole" then console=iterator.Current end
        end
        check("execution_lua_console",console~=nil,true)
        ctx.checkpoint("execution_stop_console_found")
        local Type=luanet.import_type("System.Type")
        local Delegate=luanet.import_type("System.Delegate")
        local action_type=Type.GetType("System.Action`1[System.String]")
        check("execution_queue_types",action_type~=nil,true)
        ctx.checkpoint("execution_stop_queue_types")
        local function queued_file_action(method_name,label)
            -- ResumeScripts iterates its live ScriptList. Queue the exact .NET
            -- method; never mutate that list from the observer's active resume
            -- or use a Lua delegate that re-enters the interpreter.
            local method=console:GetType():GetMethod(method_name)
            check(label.."_public_method",method~=nil,true)
            ctx.checkpoint(label.."_method_found")
            local callback=Delegate.CreateDelegate(action_type,console,method)
            ctx.checkpoint(label.."_delegate_created")
            -- Pass one scalar through the params bridge. Supplying a CLR
            -- object[] here can be repacked as one nested delegate argument.
            local pending=console:BeginInvoke(callback,O.helper_path)
            ctx.checkpoint(label.."_queued")
            -- Completion is established by the helper's independent heartbeat
            -- or exit acknowledgement, not an early blocking EndInvoke.
            return pending
        end
        local status_path=C.result_path:gsub("%.json$","_helper.txt")
        local function read_helper()
            local file=io.open(status_path,"r");if not file then return nil end
            local line=file:read("*l");file:close()
            if not line then return nil end
            local fields={};for value in (line.."\t"):gmatch("(.-)\t") do fields[#fields+1]=value end
            if #fields~=9 then return nil end
            return {phase=fields[1],ticks=tonumber(fields[2]),frame=tonumber(fields[3]),thread=tonumber(fields[4]),
                blocked=fields[5]=="true",paused=fields[6]=="true",owner_id=fields[7],lease=fields[8],reason=fields[9]}
        end
        local function wait_helper(label,predicate)
            local begun,attempts=clock(),0
            while (clock()-begun)<3 do
                local value=read_helper()
                if value and predicate(value) then out[label]=value;return value end
                if value and (value.phase=="failed" or value.phase=="refused") then
                    out[label]=value;error("Unexpected helper "..value.phase..": "..value.reason)
                end
                attempts=attempts+1
                check(label.."_frame_budget_"..attempts,emu.framecount()-first_frame<C.frames,true)
                emu.yield()
            end
            error("Bounded helper phase did not arrive: "..label)
        end
        SLINK_EXEC_HELPER={source_root=C.source_root,status_path=status_path,owner_id=O.owner_id,profile=O.profile,expected_host=O.expected_host}
        local loading=queued_file_action("LoadLuaFile","execution_helper_load")
        local held=wait_helper("helper_held",function(value) return value.phase=="held" and value.ticks>=3 end)
        console:EndInvoke(loading)
        check("execution_helper_same_ui_thread",held.thread,out.ui_thread_id)
        check("execution_helper_holds",held.blocked and main.BlockFrameAdvance,true)
        local frame=emu.framecount()
        local stopping=queued_file_action("RemoveLuaFile","execution_helper_stop")
        local stopped=wait_helper("helper_stopped",function(value) return value.phase=="exit" end)
        console:EndInvoke(stopping)
        period(nil,"stopped_helper_flag_retained",true)
        check("execution_helper_stopped_ticks",read_helper().ticks,stopped.ticks)
        check("execution_helper_stop_preserved_frame",emu.framecount(),frame)
        SLINK_EXEC_HELPER={source_root=C.source_root,status_path=status_path,owner_id=O.contender_id,profile=O.profile,expected_host=O.expected_host}
        local reloading=queued_file_action("LoadLuaFile","execution_helper_reload")
        local refused=wait_helper("helper_reloaded_refusal",function(value) return value.phase=="refused" and value.owner_id==O.contender_id end)
        console:EndInvoke(reloading)
        check("execution_reload_refuses_retained_flag",refused.reason:find("pre-existing execution hold",1,true)~=nil,true)
        check("execution_reload_keeps_flag",main.BlockFrameAdvance,true)
        queued_file_action("RemoveLuaFile","execution_refused_helper_remove")
        -- The refused helper has no owner/hold and no registered exit event.
        -- Pump two held host iterations to process its queued removal; there is
        -- deliberately no final EndInvoke that could hide a missing acknowledgement.
        emu.yield();emu.yield()
        out.teardown="process_exit_with_abandoned_hold; no ownership adoption or flag release"
        check("execution_stopped_reload_complete",true,true)
    else
        local owner=claim(first_module,O.owner_id,"primary",true)
        local status=snapshot(owner,"claimed_unheld")
        check("execution_process_id",status.process_id,ctx.host.process_id)
        check("execution_lease_name",status.lease_name,"Local\\SLink.PlatformExecution.v1."..string.format("%d",ctx.host.process_id))
        check("execution_lease_claimed",status.lease_owned,true)
        contenders("unheld_contender","another Lua execution owner")
        check("execution_hold_acquired",owner.set_held(true,"private adapter validation"),true)
        check("execution_close_held_refused",owner.close(),false)
        contenders("held_contender","pre-existing execution hold")
        period(owner,"adapter_held",true)
        snapshot(owner,"held_yield_verified")
        if O.mode=="lifecycle" then
            check("execution_hold_released",owner.set_held(false,"explicit private validation release"),true)
            contenders("released_contender","another Lua execution owner")
            check("execution_healthy_close",owner.close(),true)
            snapshot(owner,"closed")
            local replacement=claim(second_module,O.contender_id,"replacement",true)
            check("execution_stale_owner_refused",owner.set_held(true,"stale owner must not alter replacement"),false)
            check("execution_stale_owner_no_flag",main.BlockFrameAdvance,false)
            check("execution_replacement_healthy",replacement.verify(),true)
            check("execution_replacement_close",replacement.close(),true)
            snapshot(replacement,"replacement_closed")
            if O.initial_paused then period(nil,"pause_after_close",false)
            else
                local frame=emu.framecount();emu.frameadvance()
                check("execution_ordinary_frame_after_close",emu.framecount(),frame+1)
            end
            check("execution_final_pause",main.EmulatorPaused,O.initial_paused)
            check("execution_lifecycle_complete",true,true)
        else
            out.fault={kind="intentional_private_external_clear",frame_before=emu.framecount(),paused_before=main.EmulatorPaused}
            main.BlockFrameAdvance=false
            out.fault.flag_after_clear=main.BlockFrameAdvance
            ctx.checkpoint("execution_external_flag_cleared")
            check("execution_external_clear_observed",main.BlockFrameAdvance,false)
            check("execution_fault_detected",owner.verify(),false)
            local failed=snapshot(owner,"emergency_reheld")
            check("execution_failure_latched",failed.failed,true)
            check("execution_emergency_stop_verified",failed.physical_stop_verified,true)
            check("execution_failed_lease_retained",failed.lease_owned,true)
            check("execution_failed_release_refused",owner.set_held(false,"must not release failed owner"),false)
            check("execution_failed_close_refused",owner.close(),false)
            check("execution_failed_emergency_rehold",owner.set_held(true,"repeat emergency stop only"),true)
            period(nil,"failed_owner_stopped",true)
            snapshot(owner,"failed_at_teardown")
            out.fault.frame_after=emu.framecount()
            check("execution_no_escaped_frame_in_fault",out.fault.frame_after,out.fault.frame_before)
            out.teardown="process_exit_with_failed_owner_held; no release or close"
            check("execution_external_clear_complete",true,true)
        end
    end
    out.frames_advanced=emu.framecount()-first_frame
    check("execution_probe_frame_budget",out.frames_advanced<=C.frames,true)
    ctx.checkpoint("execution_adapter_probe_complete")
end
