-- Read-only allocator-wrapper observations around the frozen03 ghost/battle scenario.
-- This wrapper adds no frame advancement, hold ownership, RAM writes or allocator
-- calls. The inner frozen scenario still drives its ordinary game inputs/frames.
return function(ctx)
    local C,report,check=ctx.config,ctx.report,ctx.check
    if report.evidence.heap~=nil then error("heap observation namespace already occupied") end
    local out={schema="slink-rr-heap-wrapper-observation-v1",classification="wrapper_boundary_observation",
        complete=false,release_ready=false,capacity_proof=false,ownership_proof=false,complete_peak_coverage=false,
        phase="preflight",trace={},registration_attempts={},cleanup_attempts={},failures={},extents={},
        counts={},frame_control={hits=0},assert_hits=0,valid_snapshots=0,unavailable_snapshots=0,
        register_read_errors=0,heap_read_errors=0,trace_overflow=0,scan_overflow=0,pair_errors=0,
        callbacks_outside_observation=0,parent_started=false,parent_returned=false,
        limitations={"Only the four declared game-heap wrappers are observed",
            "Internal/direct allocator calls, raw CPU/DMA writes and libc allocations are outside coverage",
            "Unavailable or transitional headers have no capacity value",
            "Observed minima are per heap extent and do not establish a complete peak or safe reservation"}}
    report.evidence.heap=out
    local operations={
        {name="init",entry=0x08002B80,post=0x08002B8E,bytes="00b5044a1060044a1160fff7ddfe01bc00470000380a00033c0a0003"},
        {name="alloc",entry=0x08002B9C,post=0x08002BA8,bytes="00b5011c02480068fff7dafe02bc0847380a0003"},
        {name="alloc_zeroed",entry=0x08002BB0,post=0x08002BBC,bytes="00b5011c02480068fff796ff02bc0847380a0003"},
        {name="free",entry=0x08002BC4,post=0x08002BD0,bytes="00b5011c02480068fff71cff01bc0047380a0003"},
    }
    out.wrappers=operations
    local fatal,Heap,limits,checkpoint_fatal
    local stack,extent_index={},{}
    local call_id=0
    local function describe(value)
        local ok,text=pcall(tostring,value)
        return ok and text:sub(1,512) or "<unprintable>"
    end
    local function fail(code,detail)
        local first=fatal==nil
        if first then fatal=code;out.fatal_context=out.active_callback end
        if #out.failures<16 then out.failures[#out.failures+1]={code=code,detail=describe(detail)}
        else out.failures_dropped=(out.failures_dropped or 0)+1 end
        if first and checkpoint_fatal then checkpoint_fatal(code) end
    end
    checkpoint_fatal=function(code)
        if out.fatal_checkpoint then return end
        local attempt={name="heap_observation_fatal_"..code,phase=out.phase,state="attempting"}
        out.fatal_checkpoint=attempt -- recursion guard and failure latch precede external IO
        local ok,why=pcall(ctx.checkpoint,attempt.name)
        attempt.call_ok=ok;attempt.state=ok and "returned" or "failed"
        if not ok then attempt.error=describe(why) end -- never recursively checkpoint a checkpoint failure
    end
    local function demand(condition,code,detail)
        if not condition then fail(code,detail or code);error(code,0) end
    end
    local function integer(value,low,high)
        return type(value)=="number" and value%1==0 and value>=low and value<=high
    end
    local function frame()
        local value=emu.framecount()
        demand(integer(value,0,0xFFFFFFFF),"frame_read_failed",tostring(value))
        return value
    end
    local bus={
        read_u16_le=function(a) return memory.read_u16_le(a,"System Bus") end,
        read_u32_le=function(a) return memory.read_u32_le(a,"System Bus") end,
    }
    local allowed_unavailable={uninitialized_or_invalid_extent=true,invalid_header_address=true,
        invalid_header=true,invalid_block_extent=true,invalid_previous_link=true,
        invalid_next_link=true,premature_ring_end=true}
    local function snapshot(at_frame)
        local ok,snap,reason=pcall(Heap.read,bus,emu.framecount,limits.max_blocks)
        if not ok or reason=="read_failed" or reason=="invalid_frame" or reason=="context_changed" then
            out.heap_read_errors=out.heap_read_errors+1
            fail("heap_read_failed",ok and reason or snap)
            return {available=false,reason=ok and reason or "reader_exception"}
        end
        if not snap then
            out.unavailable_snapshots=out.unavailable_snapshots+1
            if reason=="block_budget_exceeded" then
                out.scan_overflow=out.scan_overflow+1;fail("heap_scan_overflow",reason)
            elseif not allowed_unavailable[reason] then fail("heap_reader_contract",reason) end
            return {available=false,reason=reason or "missing_reason"}
        end
        demand(type(snap)=="table" and snap.frame==at_frame,"snapshot_frame_mismatch","Heap sample is not from callback frame")
        local summary={available=true}
        for _,key in ipairs({"root","size","free_bytes","largest_free","allocated_bytes","header_bytes","block_count"}) do
            demand(integer(snap[key],0,0xFFFFFFFF),"heap_reader_contract",key)
            summary[key]=snap[key]
        end
        demand(summary.free_bytes+summary.allocated_bytes+summary.header_bytes==summary.size,
            "heap_reader_contract","Incomplete heap byte accounting")
        out.valid_snapshots=out.valid_snapshots+1
        local key=string.format("%08X:%d",snap.root,snap.size)
        local extent=extent_index[key]
        if not extent then
            demand(#out.extents<16,"heap_extent_overflow",key)
            extent={root=snap.root,size=snap.size,samples=0,first_frame=at_frame,
                min_free_bytes=snap.free_bytes,min_largest_free=snap.largest_free,max_allocated_bytes=0}
            extent_index[key]=extent;out.extents[#out.extents+1]=extent
        end
        extent.samples=extent.samples+1;extent.last_frame=at_frame
        extent.min_free_bytes=math.min(extent.min_free_bytes,snap.free_bytes)
        extent.min_largest_free=math.min(extent.min_largest_free,snap.largest_free)
        extent.max_allocated_bytes=math.max(extent.max_allocated_bytes,snap.allocated_bytes)
        return summary
    end
    local function registers(quiet)
        local ok,regs=pcall(emu.getregisters)
        local result={}
        for _,key in ipairs({"R0","R1","R14","R15","CPSR"}) do
            if not ok or type(regs)~="table" or not integer(regs[key],0,0xFFFFFFFF) then
                out.register_read_errors=out.register_read_errors+1
                if not quiet then fail("register_read_failed",key) end;return nil
            end
            result[key]=regs[key]
        end
        return result
    end
    local function observed_callback(body,name,address)
        return function()
            if not fatal then out.active_callback={name=name,address=address,phase=out.phase} end
            if out.phase~="observing" then
                out.callbacks_outside_observation=out.callbacks_outside_observation+1
                fail("callback_outside_observation",out.phase);return
            end
            if fatal then return end
            local ok,why=pcall(body)
            if not ok then fail("callback_failed",why) end
        end
    end
    local function operation_callback(op,point,address)
        return observed_callback(function()
            local counts=out.counts[op];counts[point]=counts[point]+1
            local at_frame=frame();out.active_callback.frame=at_frame
            local regs=registers();if not regs then return end
            out.active_callback.registers=regs
            local pending=stack[#stack]
            out.active_callback.caller=point=="post" and pending and pending.caller or regs.R14
            out.active_callback.call_id=point=="post" and pending and pending.id or nil
            if #out.trace>=limits.max_records then out.trace_overflow=out.trace_overflow+1;fail("heap_trace_overflow",op);return end
            local row={ordinal=#out.trace+1,operation=op,point=point,address=address,frame=at_frame,registers=regs}
            out.active_callback=row
            if point=="entry" then
                demand(#stack<limits.max_depth,"heap_call_depth_overflow",op)
                call_id=call_id+1
                local entry={operation=op,id=call_id,frame=at_frame,caller=regs.R14,r0=regs.R0,r1=regs.R1}
                stack[#stack+1]=entry;row.call_id=entry.id;row.caller=entry.caller
                row.args=op=="init" and {root=regs.R0,size=regs.R1}
                    or op=="free" and {pointer=regs.R0} or {size=regs.R0}
            else
                local entry=stack[#stack]
                if not entry or entry.operation~=op then
                    out.pair_errors=out.pair_errors+1;fail("heap_unmatched_post",op)
                else
                    stack[#stack]=nil;row.call_id=entry.id;row.caller=entry.caller;row.entry_frame=entry.frame
                    row.entry_r0=entry.r0;row.entry_r1=entry.r1
                    if op=="alloc" or op=="alloc_zeroed" then row.result_pointer=regs.R0 end
                end
            end
            row.heap=snapshot(at_frame)
            row.callback2=memory.read_u32_le(0x030030F4,"System Bus")
            demand(frame()==at_frame,"callback_frame_changed",op)
            if point=="post" and row.heap.available then counts.valid_posts=counts.valid_posts+1 end
            out.trace[#out.trace+1]=row
        end,op.."_"..point,address)
    end
    local function uuid(value)
        if type(value)~="string" then return nil end
        local raw=value:lower()
        if #raw==38 and raw:sub(1,1)=="{" and raw:sub(-1)=="}" then raw=raw:sub(2,-2) end
        if #raw==36 then
            if raw:sub(9,9)~="-" or raw:sub(14,14)~="-" or raw:sub(19,19)~="-" or raw:sub(24,24)~="-" then return nil end
            raw=raw:gsub("-","")
        end
        if #raw~=32 or not raw:match("^[0-9a-f]+$") or raw==string.rep("0",32) then return nil end
        return raw
    end
    local pipeline_ok,pipeline_error=xpcall(function()
        check("heap_observation_rom",C.identity.rom_sha256,"3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301")
        check("heap_observation_build",C.descriptor.build_id,"a568a586fee86a54150bd09d148f78eb7e85f6b521b58a2d56a043a5dd8d101c")
        check("heap_observation_purpose",C.purpose,"validation")
        local options=C.probe_options.heap_observation
        if options==nil then options={} end
        demand(type(options)=="table","invalid_heap_observation_limits","Expected options table")
        local known={max_records=true,max_blocks=true,max_depth=true}
        for key in pairs(options) do demand(known[key],"invalid_heap_observation_limits",key) end
        local function option(name,default) if options[name]==nil then return default end;return options[name] end
        limits={max_records=option("max_records",8192),max_blocks=option("max_blocks",512),max_depth=option("max_depth",16)}
        demand(integer(limits.max_records,1,32768) and integer(limits.max_blocks,1,8192)
            and integer(limits.max_depth,1,64),"invalid_heap_observation_limits","Unsupported budget")
        out.limits=limits
        Heap=dofile(C.source_root.."/lua/rr/heap_snapshot.lua")
        demand(type(Heap)=="table" and type(Heap.read)=="function","heap_snapshot_unavailable","Expected read-only helper")
        out.api_types={on_bus_exec=type(event.on_bus_exec),unregisterbyname=type(event.unregisterbyname),
            getregisters=type(emu.getregisters),can_use_callback_params=type(event.can_use_callback_params)}
        out.api_present={on_bus_exec=event.on_bus_exec~=nil,unregisterbyname=event.unregisterbyname~=nil,
            getregisters=emu.getregisters~=nil,can_use_callback_params=event.can_use_callback_params~=nil}
        -- Pinned NLua exposes these host methods as callable userdata (actual64).
        -- Type admits a candidate only: guarded calls and checked results below
        -- establish usability; arbitrary userdata is never treated as proof.
        local function host_binding(value) return type(value)=="function" or type(value)=="userdata" end
        demand(host_binding(event.on_bus_exec) and host_binding(event.unregisterbyname)
            and host_binding(emu.getregisters),"heap_callback_api_unavailable","Missing exact bus/register API")
        demand(type(ctx.checkpoint)=="function","heap_checkpoint_api_unavailable","Fatal guest paths may not return")
        out.preflight_registers=registers()
        demand(out.preflight_registers~=nil,"heap_register_api_unusable","Required register read failed before registration")
        local function pin(address,bytes,label)
            local raw={}
            for i=0,#bytes//2-1 do raw[#raw+1]=string.format("%02x",memory.read_u8(address+i,"System Bus")) end
            check("heap_wrapper_bytes_"..label,table.concat(raw),bytes)
        end
        for _,op in ipairs(operations) do pin(op.entry,op.bytes,op.name);out.counts[op.name]={entry=0,post=0,valid_posts=0} end
        pin(0x0800051A,"78f329fd","frame_control")
        pin(0x081E3B14,"80b584b06f4638607960ba60","agb_assert")
        local run,player=C.identity.run_id,C.identity.player
        demand(type(run)=="string" and #run>0 and #run<=80 and run:match("^[%w_-]+$")
            and type(player)=="string" and #player>0 and #player<=80 and player:match("^[%w_-]+$"),"invalid_heap_hook_identity","Expected private run/player")
        local prefix="slink_heap_"..run.."_"..player.."_"
        local seen={};out.phase="registration";out.install_frame=frame()
        local function install(address,name,callback)
            local attempt={name=prefix..name,address=address}
            out.registration_attempts[#out.registration_attempts+1]=attempt -- before API call, including failures
            local ok,id=pcall(event.on_bus_exec,callback,address,attempt.name,"System Bus")
            local normalized=ok and uuid(id) or nil
            attempt.call_ok=ok;attempt.raw_result=describe(id);attempt.result_type=type(id)
            attempt.usable=normalized~=nil and not seen[normalized]
            if normalized then seen[normalized]=true end
            demand(attempt.usable,"heap_registration_failed",attempt.name..": "..describe(id))
            demand(frame()==out.install_frame,"heap_install_frame_changed",attempt.name)
            demand(not fatal,"heap_install_callback_race",fatal)
        end
        install(0x0800051A,"frame_control",observed_callback(function()
            local f=frame();out.frame_control.hits=out.frame_control.hits+1
            out.frame_control.first_frame=out.frame_control.first_frame or f;out.frame_control.last_frame=f
        end,"frame_control",0x0800051A))
        install(0x081E3B14,"agb_assert",function()
            out.assert_hits=out.assert_hits+1
            out.assert_address=0x081E3B14;out.assert_phase=out.phase
            local frame_ok,at_frame=pcall(emu.framecount)
            if frame_ok and integer(at_frame,0,0xFFFFFFFF) then out.assert_frame=at_frame end
            local ok,regs=pcall(registers,true);out.assert_registers=ok and regs or nil
            out.active_callback={name="agb_assert",address=0x081E3B14,frame=out.assert_frame,registers=out.assert_registers,phase=out.phase}
            fail("agb_assert_observed","Guest assertion handler executed")
        end)
        for _,op in ipairs(operations) do
            install(op.entry,op.name.."_entry",operation_callback(op.name,"entry",op.entry))
            install(op.post,op.name.."_post",operation_callback(op.name,"post",op.post))
        end
        out.phase="observing";out.start_frame=frame();out.before=snapshot(out.start_frame)
        demand(not fatal,"heap_initial_observation_failed",fatal)
        local inner={};for key,value in pairs(ctx) do inner[key]=value end
        local delivered=false
        inner.check=function(...)
            if fatal and not delivered then delivered=true;error("heap observation: "..fatal,0) end
            return check(...)
        end
        out.parent_started=true
        dofile(C.source_root.."/lua/tests/rr/ghost_natural_battle_probe.lua")(inner)
        out.parent_returned=true;out.end_frame=frame();out.after=snapshot(out.end_frame)
        out.pending_calls=#stack
        demand(not fatal,"heap_observation_failed",fatal)
        demand(#stack==0,"heap_unfinished_calls",#stack)
        demand(out.frame_control.hits>0,"heap_frame_control_missing","No frame positive control")
        for _,name in ipairs({"init","alloc","free"}) do
            local c=out.counts[name]
            demand(c.entry>0 and c.entry==c.post and c.valid_posts>0,"heap_positive_control_missing",name)
        end
    end,debug.traceback)
    out.pipeline_ok=pipeline_ok
    if not pipeline_ok then out.pipeline_error=tostring(pipeline_error);fail("heap_pipeline_failed",pipeline_error) end
    out.pending_calls=#stack;out.phase="cleanup"
    -- Never let one cleanup failure prevent later attempted names being removed.
    local all_removed=true
    for _,attempt in ipairs(out.registration_attempts) do
        local ok,removed=pcall(event.unregisterbyname,attempt.name)
        out.cleanup_attempts[#out.cleanup_attempts+1]={name=attempt.name,call_ok=ok,removed=removed==true,raw_result=describe(removed)}
        if not ok or removed~=true then all_removed=false;fail("heap_cleanup_failed",attempt.name..": "..describe(removed)) end
    end
    out.all_callbacks_removed=all_removed;out.phase="finished"
    out.complete=pipeline_ok and not fatal and all_removed and #out.registration_attempts==10
    if out.complete then
        check("heap_observation_frame_control",out.frame_control.hits>0,true)
        check("heap_observation_no_agb_assert",out.assert_hits,0)
        for _,name in ipairs({"init","alloc","free"}) do
            local counts=out.counts[name]
            check("heap_observation_"..name.."_observed",counts.entry>0 and counts.entry==counts.post and counts.valid_posts>0,true)
        end
    end
    check("heap_observation_callbacks_removed",all_removed,true)
    check("heap_observation_complete",out.complete,true)
end
