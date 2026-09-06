-- Private one-frame canonical-write/allocator-execute instrumentation only.
-- No RAM writes or mailbox commands. Owns only this private host's execution hold.
return function(ctx)
    local C,report,check,host,main=ctx.config,ctx.report,ctx.check,ctx.host,ctx.main_form
    local FIRST,LAST=0x0203F769,0x02040000 -- union startsF76C, plus3-byte lower padding
    local LIMIT={registration_ms=15000,measurement_ms=15000,cleanup_ms=15000,total_ms=45000,
        trace=8192,batch=32,checkpoint_batch=256}
    local entries={
        {name="frame_callback_control",address=0x0800051A},
        {name="_free_r",address=0x081E8264},
        {name="_malloc_trim_r",address=0x081E8424},
        {name="malloc_extend_top",address=0x081E8898},
        {name="_malloc_r",address=0x081E89F4},
        {name="_sbrk_r",address=0x081E9804},
        {name="vsprintf",address=0x081E5FD4},
        {name="AGBPrintf",address=0x081E39D8},
        {name="AGBAssert",address=0x081E3B14},
        {name="mgba_printf",address=0x090A9B08},
        {name="NoCashGBAPrintf",address=0x090A9B74},
    }
    local out={classification="canonical_writes_and_allocator_exec_v1",ownership="unresolved",
        release_ready=false,phase="preconditions",frames=0,failures={},registration_attempts={},
        cleanup_attempts={},holds={},entries={},trace={},trace_dropped=0,raw_write_callbacks=0,
        register_read_failures=0,callbacks_outside_measurement=0,unexpected_start_addresses=0,
        duplicate_candidates=0,read_coverage="not_requested; requires a separate explicitly reviewed lane",
        writes_registered=0,exec_registered=0,all_callbacks_removed=false,hold_released=false,
        limitations={"Raw callback count includes overlapping-watchpoint duplicates; no deduplication performed",
            "Native callback width, accessSource, oldValue and watchpoint identity are unavailable",
            "DMA/system accesses cannot be attributed solely from raw R15",
            "Callback value is not authoritative for every store form, including STM",
            "Coverage is canonical bus access starts only; mirrors/host direct writes/boot are excluded",
            "Zero hits or zero/unchanged snapshots never prove unowned memory"}}
    report.evidence.runtime=out
    report.evidence.static={lane="writes_exec_v1",scope="System Bus",limits=LIMIT,
        ranges={{name="libc_allocator_metadata",first=0x0203F76C,last=0x0203FBB0},
            {name="slink_declared_arena",first=0x0203F800,last=LAST}},
        access_start_coverage={first=FIRST,last_exclusive=LAST,lower_padding=3,count=LAST-FIRST},
        entry_points=entries,planned_registrations=LAST-FIRST+#entries,
        qualification="Complete declared canonical write-start coverage, not a general arena ownership certificate"}
    check("arena_explicit_lane",C.probe_options and C.probe_options.arena_lane,"writes_exec_v1")
    check("arena_validation_purpose",C.purpose,"validation")
    check("arena_requested_one_frame",C.frames,1)
    check("arena_private_host_available",main~=nil and host~=nil and host.available==true,true)
    check("arena_private_core",host.matches_requested_core==true and
        host.core_type=="BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk",true)
    check("arena_bound_host_evidence",C.fixture_meta.host~=nil and host.core_assembly_file~=nil and
        host.core_assembly_file.sha256==C.fixture_meta.host.core_assembly_file.sha256,true)
    check("callback_parameters_supported",event.can_use_callback_params("memory"),true)
    local Application=luanet.import_type("System.Windows.Forms.Application")
    local clock,why=dofile(C.source_root.."/lua/platform_clock.lua").new()
    if not clock then error(why) end
    local function no_other_tools()
        local iterator=Application.OpenForms:GetEnumerator()
        while iterator:MoveNext() do
            local name=tostring(iterator.Current:GetType().FullName)
            if name~="BizHawk.Client.EmuHawk.MainForm" and name~="BizHawk.Client.EmuHawk.LuaConsole" then return false end
        end
        return true
    end
    local function host_exclusive()
        return no_other_tools() and (main.Rewinder==nil or not main.Rewinder.Active)
            and not main.PressRewind and not main.IsRewinding
    end
    local function hex(address,count)
        local result={}
        for offset=0,count-1 do result[#result+1]=string.format("%02x",memory.read_u8(address+offset)) end
        return table.concat(result)
    end
    check("descriptor_matches_bound_rom",hex(C.descriptor.address,C.descriptor.size),C.descriptor.hex)
    if C.fixture_kind=="battery" then
        local allowed={A=true,B=true,Start=true,Select=true,Up=true,Down=true,Left=true,Right=true,L=true,R=true}
        for index,step in ipairs(C.fixture_meta.boot_inputs or {}) do
            check("arena_boot_step_bound_"..index,type(step.frames)=="number" and step.frames%1==0 and step.frames>0 and step.frames<=3600,true)
            for button,value in pairs(step.buttons or {}) do
                if not allowed[button] or type(value)~="boolean" then error("Invalid fixture boot input") end
            end
            for _=1,step.frames do joypad.set(step.buttons or {});emu.frameadvance() end
        end
        joypad.set({})
        for index,a in ipairs(C.fixture_meta.ram_assertions) do
            check("arena_fixture_range_"..index,type(a.address)=="number" and
                (a.width==1 or a.width==2 or a.width==4) and
                ((a.address>=0x02000000 and a.address+a.width<=0x02040000) or
                (a.address>=0x03000000 and a.address+a.width<=0x03008000)),true)
            local value=a.width==1 and memory.read_u8(a.address) or
                (a.width==2 and memory.read_u16_le(a.address) or memory.read_u32_le(a.address))
            check("fixture_ram_"..index,value,a.expected)
        end
        check("fixture_loaded",true,true)
    end
    check("arena_host_exclusive_before",host_exclusive(),true)
    check("arena_host_unpaused_before",main.EmulatorPaused,false)
    check("arena_hold_unowned_before",main.BlockFrameAdvance,false)
    local registers=emu.getregisters()
    check("arena_registers_available",type(registers.R15)=="number" and type(registers.CPSR)=="number",true)
    local begun=clock()
    local function elapsed(start) return (clock()-start)*1000 end
    local function fail(code,detail)
        out.failures[#out.failures+1]={code=code,detail=tostring(detail),phase=out.phase,frame=emu.framecount()}
    end
    local function demand(condition,code,detail)
        if not condition then fail(code,detail);error(code) end
    end
    local held,hold=false,nil
    local function verify_hold()
        if hold then hold.verified=false end
        demand(held and main.BlockFrameAdvance==true,"hold_not_owned","Execution hold changed")
        demand(host_exclusive(),"hold_host_conflict","Tool or rewind conflict")
        demand(main.EmulatorPaused==false,"hold_pause_changed","Private pause state changed")
        demand(emu.framecount()==hold.frame,"hold_frame_changed","Core advanced while hold was owned")
        hold.verified=true
    end
    local function hold_yield()
        verify_hold();emu.yield();hold.yields=hold.yields+1;verify_hold()
    end
    local function acquire_hold(name)
        demand(not held and main.BlockFrameAdvance==false,"hold_already_owned","Another hold exists")
        demand(host_exclusive() and main.EmulatorPaused==false,"hold_precondition","Private host changed")
        hold={name=name,frame=emu.framecount(),yields=0,verified=false,started_ms=elapsed(begun)}
        out.holds[#out.holds+1]=hold
        main.BlockFrameAdvance=true;held=true
        hold_yield()
    end
    local function release_hold()
        verify_hold();main.BlockFrameAdvance=false;held=false
        hold.released=true;hold.ended_ms=elapsed(begun)
    end
    local function wall(start,limit)
        demand(elapsed(start)<=limit,"phase_wall_bound",out.phase)
        demand(elapsed(begun)<=LIMIT.total_ms,"total_wall_bound",out.phase)
    end
    local prior=nil
    local measure_start=nil
    local function trace(kind,address,value,flags,name)
        if out.phase~="measurement" then out.callbacks_outside_measurement=out.callbacks_outside_measurement+1 end
        local ok,regs=pcall(emu.getregisters)
        local valid=ok and type(regs)=="table" and type(regs.R15)=="number" and type(regs.CPSR)=="number"
        if not valid then out.register_read_failures=out.register_read_failures+1 end
        local row={ordinal=#out.trace+out.trace_dropped+1,kind=kind,address=address,value=value,flags=flags,
            entry=name or "",frame=emu.framecount(),registers_available=valid,raw_registers=valid and regs or tostring(regs)}
        -- Retain suspected duplicates. They are not a proven physical-event key.
        if prior and prior.kind==kind and prior.address==address and prior.value==value and prior.flags==flags
            and prior.frame==row.frame and valid and prior.registers_available and prior.raw_registers.R15==regs.R15 then
            row.duplicate_candidate=true;out.duplicate_candidates=out.duplicate_candidates+1
        end
        if #out.trace<LIMIT.trace then out.trace[#out.trace+1]=row else out.trace_dropped=out.trace_dropped+1 end
        prior=row
        if measure_start and elapsed(measure_start)>LIMIT.measurement_ms then out.measurement_wall_exceeded=true end
    end
    local prefix="slink_rr_arena_"..tostring(C.identity.run_id).."_"..tostring(C.identity.player).."_"
    local seen={}
    local function register(kind,address,name,callback)
        verify_hold()
        local full_name=prefix..name
        local ok,id=pcall(event["on_bus_"..kind],callback,address,full_name,"System Bus")
        local compact=ok and type(id)=="string" and id:gsub("[{}%-]",""):lower() or ""
        local usable=#compact==32 and compact:match("^[0-9a-f]+$")~=nil and compact~=string.rep("0",32) and not seen[compact]
        local row={kind=kind,address=address,name=full_name,call_ok=ok,raw_result=tostring(id),result_type=type(id),usable=usable}
        out.registration_attempts[#out.registration_attempts+1]=row
        if not usable then fail("registration_failed",full_name..": "..tostring(id))
        else
            seen[compact]=true
            local field=kind=="write" and "writes_registered" or "exec_registered"
            out[field]=out[field]+1
        end
        local count=#out.registration_attempts
        if count%LIMIT.checkpoint_batch==0 then ctx.checkpoint("arena_registration_"..count) end
        if count%LIMIT.batch==0 then hold_yield() end
    end
    local function write_callback(address,value,flags)
        out.raw_write_callbacks=out.raw_write_callbacks+1
        if address<FIRST or address>=LAST then out.unexpected_start_addresses=out.unexpected_start_addresses+1 end
        if address==0x0203F800 then out.beacon_write_callbacks=(out.beacon_write_callbacks or 0)+1 end
        trace("write",address,value,flags)
    end
    local body_ok,body_error=pcall(function()
        out.phase="registration";out.registration={};local started=clock()
        acquire_hold("registration");ctx.checkpoint("arena_registration_hold_acquired")
        for address=FIRST,LAST-1 do
            wall(started,LIMIT.registration_ms)
            register("write",address,string.format("write_%08X",address),write_callback)
        end
        for _,entry in ipairs(entries) do
            local name=entry.name;out.entries[name]=0
            wall(started,LIMIT.registration_ms)
            register("exec",entry.address,"entry_"..name,function(a,v,f)
                out.entries[name]=out.entries[name]+1;trace("execute",a,v,f,name)
            end)
        end
        verify_hold();wall(started,LIMIT.registration_ms)
        out.registration.elapsed_ms=elapsed(started);out.registration.frame=hold.frame
        demand(out.writes_registered==LAST-FIRST and out.exec_registered==#entries and #out.failures==0,
            "registration_incomplete","No measured frame may run with partial coverage")
        ctx.checkpoint("arena_exact_registration_complete")
        out.instrumentation_started_frame=emu.framecount();out.boot_instrumented=false
        release_hold()
        out.phase="measurement";measure_start=clock()
        emu.frameadvance()
        out.frames=emu.framecount()-out.instrumentation_started_frame
        out.measurement={elapsed_ms=elapsed(measure_start),start_frame=out.instrumentation_started_frame,end_frame=emu.framecount()}
        out.phase="cleanup";acquire_hold("cleanup")
        ctx.checkpoint("arena_measurement_complete_cleanup_held")
        if out.frames~=1 then fail("measurement_frame_bound",out.frames) end
        if out.measurement_wall_exceeded or out.measurement.elapsed_ms>LIMIT.measurement_ms then
            fail("measurement_wall_bound",out.measurement.elapsed_ms)
        end
        if out.trace_dropped~=0 then fail("trace_overflow",out.trace_dropped) end
        if out.register_read_failures~=0 then fail("register_reads_failed",out.register_read_failures) end
    end)
    if not body_ok then fail("measurement_pipeline_failed",body_error) end
    -- Clean every attempted NAME, including zero/duplicate-ID attempts:
    -- EventsLua can create a name before native Add fails.
    out.phase="cleanup";out.cleanup={};local cleanup_started=clock()
    local cleanup_ok,cleanup_error=pcall(function()
        if not held then acquire_hold("cleanup_after_failure") else verify_hold() end
        out.cleanup.hold_index=#out.holds;out.cleanup.hold_verified=true
        for index,attempt in ipairs(out.registration_attempts) do
            verify_hold();wall(cleanup_started,LIMIT.cleanup_ms)
            local ok,removed=pcall(event.unregisterbyname,attempt.name)
            out.cleanup_attempts[#out.cleanup_attempts+1]={name=attempt.name,registration_result=attempt.raw_result,
                call_ok=ok,removed=removed==true,raw_result=tostring(removed)}
            if not ok or removed~=true then fail("cleanup_failed",attempt.name..": "..tostring(removed)) end
            if index%LIMIT.checkpoint_batch==0 then ctx.checkpoint("arena_cleanup_"..index) end
            if index%LIMIT.batch==0 then hold_yield() end
        end
        verify_hold();wall(cleanup_started,LIMIT.cleanup_ms)
        out.cleanup.elapsed_ms=elapsed(cleanup_started)
        local removed=0
        for _,attempt in ipairs(out.cleanup_attempts) do if attempt.removed then removed=removed+1 end end
        out.all_callbacks_removed=removed==#out.registration_attempts
        out.cleanup.removed_count=removed
        if out.all_callbacks_removed then release_hold();out.hold_released=true end
    end)
    if not cleanup_ok then fail("cleanup_pipeline_failed",cleanup_error) end
    -- An uncertain own hold stays in place until the runner exits this private
    -- process. Never resume with callback cleanup or hold ownership uncertain.
    out.elapsed_ms=elapsed(begun);out.phase="finished"
    out.registration_attempt_count=#out.registration_attempts;out.cleanup_attempt_count=#out.cleanup_attempts
    out.own_hold_remaining=held;out.host_block_flag_after=main.BlockFrameAdvance
    local verdicts={
        {"arena_write_start_coverage_complete",out.writes_registered,LAST-FIRST},
        {"arena_exec_coverage_complete",out.exec_registered,#entries},
        {"arena_registration_hold_verified",#out.holds>0 and out.holds[1].verified and out.holds[1].yields>0,true},
        {"arena_cleanup_hold_verified",out.cleanup.hold_verified==true and
            out.holds[out.cleanup.hold_index].verified and out.holds[out.cleanup.hold_index].yields>0,true},
        {"arena_measurement_one_frame",out.frames,1},
        {"execute_control_observed",(out.entries.frame_callback_control or 0)>0,true},
        {"write_hook_observed",(out.beacon_write_callbacks or 0)>0,true},
        {"arena_no_unmeasured_callbacks",out.callbacks_outside_measurement,0},
        {"arena_declared_starts_only",out.unexpected_start_addresses,0},
        {"arena_trace_complete",out.trace_dropped,0},
        {"arena_register_reads_complete",out.register_read_failures,0},
        {"arena_all_callbacks_removed",out.all_callbacks_removed,true},
        {"arena_own_hold_released",out.hold_released and not main.BlockFrameAdvance,true},
        {"arena_pause_preserved",main.EmulatorPaused,false},
        {"arena_wall_bounds",out.elapsed_ms<=LIMIT.total_ms,true},
    }
    for _,v in ipairs(verdicts) do if v[2]~=v[3] then fail(v[1],"actual="..tostring(v[2]).." expected="..tostring(v[3])) end end
    out.failure_count=#out.failures
    ctx.checkpoint("arena_exact_probe_finished")
    check("arena_no_failures",out.failure_count,0)
    for _,v in ipairs(verdicts) do check(v[1],v[2],v[3]) end
end
