-- Exact-address callback capability only. No ROM/RAM writes or mailbox commands.
-- Callback addresses, values, flags and pipeline registers remain raw evidence.
return function(ctx)
    local C,report,check=ctx.config,ctx.report,ctx.check
    local controls={
        {name="read_callback2",kind="read",address=0x030030F4},
        {name="write_beacon",kind="write",address=0x0203F800},
        {name="write_plus_one_diagnostic",kind="write",address=0x0203F801},
        {name="exec_frame_control",kind="exec",address=0x0800051A},
    }
    report.evidence.static={controls=controls,scope="System Bus",
        write_basis="Bound native handlers.c unconditionally writes the signature beacon each frame"}
    local out={classification="exact_callback_capability_only",arena_ownership="unresolved",
        registrations={},hits={},trace={},trace_dropped=0,pc_unavailable=0,cleanup={},release_ready=false,
        limitations={"No wildcard or masked callback support claim",
            "Interior-address overlap is diagnostic; callback dispatch may use the access start address",
            "Raw callback read values may not represent the loaded word",
            "R15 is a raw pipeline register; no instruction-PC normalization is assumed"}}
    report.evidence.runtime=out
    check("capability_probe_purpose",C.purpose,"validation")
    check("capability_frame_bound",type(C.frames)=="number" and C.frames%1==0 and C.frames>=1 and C.frames<=2,true)
    local function hex(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02x",memory.read_u8(a+i)) end
        return table.concat(t)
    end
    check("descriptor_matches_bound_rom",hex(C.descriptor.address,C.descriptor.size),C.descriptor.hex)
    if C.fixture_kind=="battery" then
        for _,step in ipairs(C.fixture_meta.boot_inputs or {}) do
            for _=1,step.frames do joypad.set(step.buttons or {});emu.frameadvance() end
        end
        joypad.set({})
        for index,a in ipairs(C.fixture_meta.ram_assertions) do
            local value=a.width==1 and memory.read_u8(a.address)
                or (a.width==2 and memory.read_u16_le(a.address) or memory.read_u32_le(a.address))
            check("fixture_ram_"..index,value,a.expected)
        end
        check("fixture_loaded",true,true)
    end
    local registers=emu.getregisters()
    local pc=registers.R15~=nil and "R15" or (registers.PC~=nil and "PC" or nil)
    local cpsr=registers.CPSR~=nil and "CPSR" or (registers.cpsr~=nil and "cpsr" or nil)
    check("capability_pc_register",pc~=nil,true)
    out.pc_register=pc;out.cpsr_register=cpsr
    local ids,seen={},{}
    local function record(control,address,value,flags)
        out.hits[control.name]=out.hits[control.name]+1
        local ok,raw_pc=pcall(emu.getregister,pc)
        if not ok then out.pc_unavailable=out.pc_unavailable+1 end
        local row={callback=control.name,address=address,value=value,flags=flags,
            raw_pc=ok and raw_pc or tostring(raw_pc),frame=emu.framecount()}
        if cpsr then
            local status,result=pcall(emu.getregister,cpsr)
            row.cpsr_available=status;row.raw_cpsr=status and result or tostring(result)
        end
        if type(emu.totalexecutedcycles)=="function" then
            local status,result=pcall(emu.totalexecutedcycles)
            row.cycles_available=status;row.raw_cycles=status and result or tostring(result)
        end
        if #out.trace<128 then out.trace[#out.trace+1]=row else out.trace_dropped=out.trace_dropped+1 end
    end
    local first=emu.framecount()
    local ok,err=pcall(function()
        for _,control in ipairs(controls) do
            out.hits[control.name]=0
            local fn=event["on_bus_"..control.kind]
            local status,id=pcall(fn,function(a,v,f) record(control,a,v,f) end,control.address,control.name,"System Bus")
            out.registrations[#out.registrations+1]={name=control.name,address=control.address,
                call_ok=status,raw_result=tostring(id),result_type=type(id)}
            local valid=status and type(id)=="string" and id~=""
                and id:gsub("[{}%-]","")~=string.rep("0",32) and not seen[id]
            check("registered_"..control.name,valid,true)
            ids[#ids+1]=id;seen[id]=true
        end
        ctx.checkpoint("exact_callbacks_registered")
        for _=1,C.frames do emu.frameadvance() end
        out.frames=emu.framecount()-first
        check("capability_frames_complete",out.frames,C.frames)
        check("exact_read_observed",out.hits.read_callback2>0,true)
        check("exact_write_observed",out.hits.write_beacon>0,true)
        check("exact_exec_observed",out.hits.exec_frame_control>0,true)
        check("capability_pc_reads_available",out.pc_unavailable,0)
        check("capability_trace_complete",out.trace_dropped,0)
    end)
    local all_removed=true
    for _,id in ipairs(ids) do
        local status,removed=pcall(event.unregisterbyid,id)
        out.cleanup[#out.cleanup+1]={id=id,call_ok=status,removed=removed==true}
        if not status or removed~=true then all_removed=false end
    end
    if not ok then error(err) end
    check("capability_callbacks_removed",all_removed,true)
end
