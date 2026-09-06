-- Disposable frozen03 experiment. Only OP_PING may be posted. Never adopts a
-- restored owner or releases a hold after load (including a failed load).
return function(ctx)
    local C,check,main=ctx.config,ctx.check,ctx.main_form
    local O=C.probe_options or {}
    local ROM1="65c6b2739bab54f8ffda590d79ba551a0b7baec8"
    local ROM256="3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301"
    local BATTERY="c8eb84b434b80dc5c7cac7b84a9a8106d78088078d277a860fb6e4b067b43d13"
    local LAYOUT="878066ab0db1dbff0bee8cd0935f5eabe2b0dc1b6259ff6d5af6c054843bdd56"
    local BASE,NATIVE,FRAME=0x0203F800,0x08378F70,0x0800051A
    local out={mode=O.mode,classification="controlled_load_incomplete",phase="preflight",
        trace={},trace_dropped=0,registrations={},cleanup={},failures={},load_events={},
        forward_frames=0,general_interlock_proved=false,release_ready=false,
        limitations={"Controlled pre-held load only; manual reset/rewind/future-frame routes are unproved",
            "Execute callbacks are bounded dispatch observations, not a general memory ownership proof",
            "Restored continuity remains failed; no replacement owner, reconciliation or release is attempted"}}
    ctx.report.evidence.runtime=out
    check("controlled_mode",O.mode=="produce" or O.mode=="valid" or O.mode=="late_failure",true)
    check("controlled_purpose",C.purpose,"validation")
    check("controlled_frozen03",C.identity.rom_sha1:lower()==ROM1 and C.identity.rom_sha256==ROM256,true)
    check("controlled_fixture_battery",C.fixture_kind=="battery" and C.identity.fixture_sha256==BATTERY,true)
    check("controlled_host",main~=nil and ctx.host.available and ctx.host.matches_requested_core,true)
    check("controlled_initial_unpaused_unheld",main.EmulatorPaused==false and main.BlockFrameAdvance==false,true)
    check("controlled_hold_bound",type(O.hold_ms)=="number" and O.hold_ms>=100 and O.hold_ms<=1000,true)
    local clock,clock_error=dofile(C.source_root.."/lua/platform_clock.lua").new()
    assert(clock,clock_error)
    local File=luanet.import_type("System.IO.File")
    local Hash=luanet.import_type("System.Security.Cryptography.SHA256")
    local Bits=luanet.import_type("System.BitConverter")
    local function fingerprint(path)
        local algorithm=Hash.Create()
        local ok,value=pcall(function()
            local value=tostring(Bits.ToString(algorithm:ComputeHash(File.ReadAllBytes(path))))
            return (value:gsub("-",""):lower())
        end)
        algorithm:Dispose();assert(ok,value);return value
    end
    local function hex(address,count)
        local bytes={}
        for offset=0,count-1 do bytes[#bytes+1]=string.format("%02x",memory.read_u8(address+offset,"System Bus")) end
        return table.concat(bytes)
    end
    local function no_preview_or_movie()
        return main.PreFutureFrameCallback==nil and main.MaxFutureFrames==0
            and main.MovieSession~=nil and main.MovieSession.Movie==nil and main.MovieSession.NewMovieQueued==false
    end
    local function busy_ping(value)
        if type(value)~="string" or #value~=128 or not value:match("^[0-9a-f]+$") then return false end
        local function word(offset)
            return tonumber(value:sub(offset*2+1,offset*2+2),16)
                +256*tonumber(value:sub(offset*2+3,offset*2+4),16)
        end
        return value:sub(1,8)=="534c4e4b" and word(4)==2 and word(6)==1 and word(10)==1
            and word(8)~=word(12) and word(14)==0 and value:sub(33,80)==string.rep("0",48)
            and value:sub(81,96)~=string.rep("0",16) and value:sub(97)==string.rep("0",32)
    end
    local boot_frames=0
    for _,step in ipairs(C.fixture_meta.boot_inputs) do
        assert(type(step.frames)=="number" and step.frames%1==0 and step.frames>=1 and step.frames<=600,"invalid boot bound")
        boot_frames=boot_frames+step.frames
    end
    check("controlled_frame_budget",boot_frames==1656 and C.frames==boot_frames+3,true)
    local function advance()
        assert(out.forward_frames<C.frames,"forward frame budget exceeded")
        emu.frameadvance();out.forward_frames=out.forward_frames+1
    end
    check("descriptor_matches_bound_rom",hex(C.descriptor.address,C.descriptor.size),C.descriptor.hex)
    check("controlled_native_entry_anchor",hex(NATIVE,8),"f0b5b84bb84c89b0")
    for _,step in ipairs(C.fixture_meta.boot_inputs) do
        for _=1,step.frames do joypad.set(step.buttons or {});advance() end
    end
    joypad.set({})
    for index,a in ipairs(C.fixture_meta.ram_assertions) do
        assert(a.width==1 or a.width==2 or a.width==4,"invalid fixture read width")
        local value=a.width==1 and memory.read_u8(a.address) or
            (a.width==2 and memory.read_u16_le(a.address) or memory.read_u32_le(a.address))
        check("fixture_ram_"..index,value,a.expected)
    end
    check("fixture_loaded",true,true)
    check("controlled_unpaused",main.EmulatorPaused,false)
    check("controlled_no_preview_movie",no_preview_or_movie(),true)
    ctx.checkpoint("controlled_boot_complete")
    local owner,owner_error=dofile(C.source_root.."/lua/platform_execution.lua").new({owner_id=O.owner_id,
        expected_host=O.expected_host,exclusive_ownership="emulator_process",control_context="between_frames"})
    assert(owner,owner_error)
    local MB=dofile(C.source_root.."/lua/mailbox.lua")
    local names,ids={},{}
    local function held()
        local ok,why=owner.set_held(true,"private controlled-load quarantine")
        assert(ok,why)
        local status=owner.status()
        assert(status.lease_owned and status.physical_stop_verified and main.BlockFrameAdvance==true,"physical hold unavailable")
        assert(main.EmulatorPaused==false and no_preview_or_movie(),"private host scope changed")
        return status
    end
    local function trace(kind,address,value,flags)
        if #out.trace>=256 then out.trace_dropped=out.trace_dropped+1;return end
        out.trace[#out.trace+1]={kind=kind,phase=out.phase,frame=emu.framecount(),address=address,
            value=value,flags=flags,host_blocked=main.BlockFrameAdvance,
            opcode=memory.read_u16_le(BASE+6),status=memory.read_u16_le(BASE+10)}
    end
    local function register(kind,address)
        local name="slink_controlled_"..O.owner_id.."_"..kind
        names[#names+1]=name
        local callback=function(a,v,f) trace(kind,a,v,f) end
        local ok,id
        if kind=="load" then
            callback=function(value)
                if #out.load_events>=16 then out.trace_dropped=out.trace_dropped+1;return end
                out.load_events[#out.load_events+1]={phase=out.phase,frame=emu.framecount(),
                    host_blocked=main.BlockFrameAdvance,value=tostring(value)}
            end
            ok,id=pcall(event.onloadstate,callback,name)
        else ok,id=pcall(event.on_bus_exec,callback,address,name,"System Bus") end
        local value=tostring(id)
        local compact=value:gsub("-","")
        out.registrations[#out.registrations+1]={kind=kind,name=name,address=address,call_ok=ok,id=value}
        assert(ok and #value==36 and #compact==32 and compact:match("^%x+$")
            and value:sub(9,9)=="-" and value:sub(14,14)=="-" and value:sub(19,19)=="-" and value:sub(24,24)=="-"
            and value~="00000000-0000-0000-0000-000000000000" and not ids[value],"callback registration failed")
        ids[value]=true
    end
    local function one_frame()
        held();assert(owner.verify())
        assert(owner.set_held(false,"private positive-control forward frame"))
        advance()
        held()
    end
    local function idle_mailbox()
        return memory.read_u16_le(BASE+6)==0 and memory.read_u16_le(BASE+10)==0
    end
    local function observe_hold(expected_frame,expected_mailbox,failed)
        local started,yields=clock(),0
        while (clock()-started)*1000<O.hold_ms do
            assert(clock()-started<5 and yields<256,"held observation wall/yield bound")
            local status=held()
            assert(status.failed==failed,"unexpected owner continuity state")
            emu.yield();yields=yields+1
            assert(emu.framecount()==expected_frame and hex(BASE,64)==expected_mailbox,"restored frame/mailbox changed while held")
            assert(main.BlockFrameAdvance==true,"hold cleared during observer yield")
        end
        held();out.held_period={yields=yields,elapsed_ms=(clock()-started)*1000,frame=emu.framecount()}
        assert(yields>0,"held period had no serviced yields")
    end
    local ok,problem=xpcall(function()
        held();assert(owner.yield_held())
        register("frame",FRAME);register("native",NATIVE);register("load")
        check("controlled_idle_before_ping",idle_mailbox(),true)
        out.phase="positive_control"
        local token,why=MB.send(MB.OP_PING,{})
        assert(token,why)
        check("controlled_positive_busy",busy_ping(hex(BASE,64)),true)
        one_frame()
        local descriptor,reason=MB.read_descriptor(token)
        out.positive_descriptor=descriptor;out.positive_error=reason
        check("controlled_positive_ping_receipt",descriptor~=nil and descriptor.abi==2 and
            descriptor.build_id==C.descriptor.build_id and descriptor.layout_sha256==LAYOUT,true)
        local native,frame=0,0
        for _,row in ipairs(out.trace) do
            if row.phase=="positive_control" and row.kind=="native" then native=native+1 end
            if row.phase=="positive_control" and row.kind=="frame" then frame=frame+1 end
        end
        check("controlled_positive_native_dispatch",native>0 and frame>0 and idle_mailbox(),true)
        out.positive_dispatch={native=native,frame=frame};ctx.checkpoint("controlled_positive_control_complete")
        if O.mode=="produce" then
            out.phase="producer_alignment";one_frame();one_frame()
            check("controlled_pre_save_hold",held().physical_stop_verified,true)
            assert(MB.send(MB.OP_PING,{}))
            local header,frame=hex(BASE,64),emu.framecount()
            check("controlled_saved_busy_ping",busy_ping(header),true)
            local path=C.result_path:gsub("result%.json$","busy_ping.State")
            assert(path~=C.result_path and not File.Exists(path),"private fixed state output must be new")
            local first_trace=#out.trace
            out.phase="saving_held";ctx.checkpoint("controlled_before_save")
            check("controlled_save_return",savestate.save(path,true),true)
            check("controlled_saved_state_exists",File.Exists(path),true)
            out.produced={path=path,state_sha256=fingerprint(path),frame=frame,mailbox_hex=header}
            observe_hold(frame,header,false)
            check("controlled_saved_state_held",owner.verify() and hex(BASE,64)==header,true)
            check("controlled_zero_save_dispatch",#out.trace,first_trace)
            out.classification="controlled_busy_ping_state_producer"
        else
            local E=O.experiment
            assert(type(E)=="table" and E.schema=="slink-rr-controlled-load-experiment-v1"
                and E.rom_sha1==ROM1 and E.rom_sha256==ROM256 and E.battery_sha256==BATTERY
                and E.general_interlock_proved==false and E.release_ready==false,"invalid bound experiment metadata")
            assert(type(E.saved_frame)=="number" and E.saved_frame%1==0 and busy_ping(E.mailbox_hex),"invalid producer marker")
            local filename=O.mode=="valid" and "busy_ping.State" or "busy_late_failure.State"
            local artifact=O.mode=="valid" and E.valid or E.late_failure
            assert(artifact.file_name==filename,"unexpected state artifact name")
            local path=C.source_root.."/probe_artifacts/"..filename
            check("controlled_state_hash",fingerprint(path),artifact.sha256)
            out.phase="consumer_alignment"
            if emu.framecount()==E.saved_frame then one_frame() end
            check("controlled_distinct_restore_frame",emu.framecount()~=E.saved_frame,true)
            check("controlled_pre_load_hold",held().physical_stop_verified and owner.verify(),true)
            out.before_load={frame=emu.framecount(),mailbox_hex=hex(BASE,64),owner=owner.status()}
            out.phase="restore_held";ctx.checkpoint("controlled_before_load")
            assert(owner.verify() and idle_mailbox())
            local first_trace=#out.trace
            local load_ok,loaded=pcall(savestate.load,path,true)
            -- First restored boundary: invalidate the old frame anchor, retain
            -- its lease and emergency STOP. Never construct a replacement owner.
            local verified,verify_error=owner.verify()
            out.after_load={call_ok=load_ok,returned=load_ok and loaded or nil,
                error=not load_ok and tostring(loaded) or nil,old_owner_verified=verified,
                verify_error=verify_error,frame=emu.framecount(),mailbox_hex=hex(BASE,64),owner=owner.status()}
            held()
            check("controlled_old_owner_invalidated",verified==false and owner.status().failed,true)
            check("controlled_load_return",load_ok and loaded==true,O.mode=="valid")
            check("controlled_success_notifications",#out.load_events,O.mode=="valid" and 1 or 0)
            for _,row in ipairs(out.load_events) do assert(row.host_blocked and row.phase=="restore_held","notification was not pre-held") end
            check("controlled_restored_frame",emu.framecount(),E.saved_frame)
            check("controlled_restored_busy",hex(BASE,64),E.mailbox_hex)
            out.phase="restored_quarantine"
            observe_hold(E.saved_frame,E.mailbox_hex,true)
            check("controlled_zero_restored_dispatch",#out.trace,first_trace)
            check("controlled_retained_busy",hex(BASE,64),E.mailbox_hex)
            out.classification=O.mode=="valid" and "controlled_valid_load_preheld" or "controlled_late_failed_load_preheld"
        end
        check("controlled_trace_complete",out.trace_dropped,0)
    end,debug.traceback)
    if not ok then out.failures[#out.failures+1]=tostring(problem) end
    out.phase="cleanup_held"
    local stop_ok,stop_error=pcall(held)
    if not stop_ok then out.failures[#out.failures+1]=tostring(stop_error) end
    if stop_ok then
        for _,name in ipairs(names) do
            local removed,value=pcall(event.unregisterbyname,name)
            out.cleanup[#out.cleanup+1]={name=name,call_ok=removed,removed=value==true}
            if not removed or value~=true then out.failures[#out.failures+1]="callback cleanup failed: "..name end
        end
    end
    out.final_owner=owner.status();out.teardown="private process exit with held lease; no close, release or mailbox cleanup"
    ctx.checkpoint("controlled_teardown_held")
    check("controlled_callbacks_removed",#out.cleanup==#names and #out.failures==0,true)
    check("controlled_exit_held",out.final_owner.lease_owned and out.final_owner.physical_stop_verified and main.BlockFrameAdvance,true)
    check("controlled_no_failures",#out.failures,0)
end
