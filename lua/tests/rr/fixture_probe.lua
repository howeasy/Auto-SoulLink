-- Observe a private historical battery candidate through the actual game engine.
-- No forced RAM/register writes, mailbox opcodes, savestate loads, or in-game saves.
-- This deliberately cannot certify compatibility; an assessor reviews its output.
return function(ctx)
    local C,report,check=ctx.config,ctx.report,ctx.check
    check("observation_purpose",C.purpose,"fixture_discovery")
    local out={snapshots={},screenshots={},input_samples={},ownership="unresolved",compatibility="unverified",
        provenance=C.fixture_meta.provenance,all_bus_callbacks_enabled=false}
    report.evidence.runtime=out
    local main_form=ctx.main_form
    out.host=ctx.host or {available=false,error="Explicit host_identity.lua dependency was not selected"}
    ctx.checkpoint("host_identity_observed")
    local function r8(a) return memory.read_u8(a,"System Bus") end
    local function r16(a) return memory.read_u16_le(a,"System Bus") end
    local function r32(a) return memory.read_u32_le(a,"System Bus") end
    local function valid(a,size) return a>=0x02000000 and a+size<=0x02040000 end
    local function field_hint()
        return r32(0x030030F4)==0x080565B5 and r8(0x03000F9C)==0
            and r8(0x02024029)>=1 and r8(0x02024029)<=6
    end
    local function hexbytes(a,n)
        local t={};for i=0,n-1 do t[#t+1]=string.format("%02X",r8(a+i)) end
        return table.concat(t)
    end
    local function sb2(pointer_address)
        local p=r32(pointer_address);local t={pointer_address=pointer_address,pointer=p,valid=valid(p,14)}
        if t.valid then t.name_hex=hexbytes(p,8);t.trainer_id_hex=hexbytes(p+0xA,4) end
        return t
    end
    local function sb1(pointer_address)
        local p=r32(pointer_address);local t={pointer_address=pointer_address,pointer=p,valid=valid(p,0x9C)}
        if t.valid then
            t.x=r16(p);t.y=r16(p+2);t.map_group=r8(p+4);t.map_num=r8(p+5)
            t.shadow_party_count=r8(p+0x34);t.shadow_party_pid=r32(p+0x38)
        end
        return t
    end
    local function sample(label)
        local p=0x02024284
        local raw_party={count=r8(0x02024029),records={},frame_before=emu.framecount()}
        raw_party.bounded=raw_party.count>=0 and raw_party.count<=6
        if raw_party.bounded then
            for slot=0,raw_party.count-1 do
                local address=p+slot*100
                raw_party.records[#raw_party.records+1]={slot=slot,address=address,size_bytes=100,
                    raw_hex=hexbytes(address,100)}
            end
        end
        raw_party.frame_after=emu.framecount()
        raw_party.count_after=r8(0x02024029)
        raw_party.coherent=raw_party.bounded and raw_party.count==raw_party.count_after
            and raw_party.frame_before==raw_party.frame_after
        out.snapshots[#out.snapshots+1]={label=label,frame=emu.framecount(),
            callback2=r32(0x030030F4),script_context2=r8(0x03000F9C),idle_field_hint=field_hint(),
            raw_party=raw_party,
            profile_sb1=sb1(0x03003840),profile_sb2=sb2(0x03003838),
            vanilla_sb1=sb1(0x03005008),vanilla_sb2=sb2(0x0300500C),
            party_count=r8(0x02024029),party0={pid=r32(p),ot=r32(p+4),species=r16(p+0x20),
                level=r8(p+0x54),hp=r16(p+0x56),max_hp=r16(p+0x58)},
            mode_bytes={mgm_easy_hardcore=r8(0x0203B25A),restricted=r8(0x0203B25B),
                randomizers=r8(0x0203B17C),hard_randomizer=r8(0x0203B17B)}}
        local path=C.result_path:gsub("%.json$","").."_"..label..".png"
        client.screenshot(path)
        out.screenshots[#out.screenshots+1]=path
    end
    if C.descriptor then
        check("descriptor_matches_bound_rom",hexbytes(C.descriptor.address,C.descriptor.size):lower(),C.descriptor.hex)
    end
    sample("before")
    local first=emu.framecount()
    local allowed={A=true,B=true,Start=true,Select=true,Up=true,Down=true,Left=true,Right=true,L=true,R=true}
    local stop_inputs=false
    for index,step in ipairs(C.probe_options.steps or {}) do
        check("step_bound_"..index,type(step.frames)=="number" and step.frames%1==0 and step.frames>=1 and step.frames<=600,true)
        for button,_ in pairs(step.buttons or {}) do if not allowed[button] then error("Unknown input "..button) end end
        for step_frame=1,step.frames do
            if C.probe_options.stop_at_field and field_hint() then stop_inputs=true;break end
            joypad.set(step.buttons or {});emu.frameadvance()
            if step_frame==1 then
                out.input_samples[#out.input_samples+1]={step=index,frame=emu.framecount(),
                    requested=step.buttons or {},joypad=joypad.get(),key_input=r16(0x04000130)}
            end
        end
        joypad.set({});sample("step"..index)
        if stop_inputs then break end
    end
    for _=1,C.frames do emu.frameadvance() end
    if (C.probe_options.host_hold_ms or 0)>0 then
        check("host_hold_field_checkpoint",field_hint(),true)
        check("host_hold_main_form_available",main_form~=nil and out.host.available,true)
        check("host_hold_actual_core",out.host.matches_requested_core,true)
        check("host_hold_core_hash_available",type(out.host.core_assembly_file.sha256)=="string",true)
        local function no_other_tools()
            local Application=luanet.import_type("System.Windows.Forms.Application")
            local iterator=Application.OpenForms:GetEnumerator()
            while iterator:MoveNext() do
                local name=tostring(iterator.Current:GetType().FullName)
                if name~="BizHawk.Client.EmuHawk.MainForm" and name~="BizHawk.Client.EmuHawk.LuaConsole" then return false end
            end
            return true
        end
        check("host_hold_no_conflicting_tools",no_other_tools(),true)
        check("host_hold_rewind_inactive",main_form.Rewinder==nil or not main_form.Rewinder.Active,true)
        check("host_hold_no_rewind_request",main_form.PressRewind,false)
        check("host_hold_not_already_owned",main_form.BlockFrameAdvance,false)
        if C.probe_options.host_pause_before_hold then
            -- Deliberately set the already-paused scenario in this private host.
            -- The hold must preserve it, including after its explicit test step.
            client.pause();ctx.checkpoint("private_pause_requested");emu.yield()
            check("host_hold_requested_private_pause",main_form.EmulatorPaused,true)
            ctx.checkpoint("private_pause_yield_resumed")
        end
        local clock,why=dofile(C.source_root.."/lua/platform_clock.lua").new()
        if not clock then error(why) end
        local before=emu.framecount()
        local paused_before=main_form.EmulatorPaused
        local timing={frame_before=before,paused_before=paused_before,hold_ms=C.probe_options.host_hold_ms,
            yields=0,scope="exclusive_private_host_hold_no_production_service"}
        timing.pause_origin=C.probe_options.host_pause_before_hold and "probe_requested_private_pause" or "existing_host_state"
        out.host_hold=timing
        local started=clock()
        local conflict=false
        main_form.BlockFrameAdvance=true
        ctx.checkpoint("host_hold_acquired")
        local ok,err=pcall(function()
            while (clock()-started)*1000<C.probe_options.host_hold_ms do
                emu.yield();timing.yields=timing.yields+1
                if not no_other_tools() then conflict=true;error("Tool appeared while host hold was owned") end
                if main_form.PressRewind or main_form.IsRewinding then error("Rewind interfered with host hold") end
                if not main_form.BlockFrameAdvance then error("Host hold was changed by another owner") end
                if emu.framecount()~=before then error("Core advanced during owned host hold") end
            end
        end)
        if not conflict and main_form.BlockFrameAdvance then main_form.BlockFrameAdvance=false end
        timing.elapsed_ms=(clock()-started)*1000
        timing.frame_after_hold=emu.framecount()
        timing.paused_after_hold=main_form.EmulatorPaused
        timing.block_after_release=main_form.BlockFrameAdvance
        if not ok then error(err) end
        check("host_hold_frames_constant",timing.frame_after_hold,before)
        check("host_hold_clock_progress",timing.elapsed_ms>=C.probe_options.host_hold_ms,true)
        check("host_hold_yield_resumed",timing.yields>0,true)
        check("host_hold_user_pause_preserved",timing.paused_after_hold,paused_before)
        check("host_hold_own_flag_released",main_form.BlockFrameAdvance,false)
        ctx.checkpoint("host_hold_released")
        if paused_before then
            -- emu.frameadvance waits for a frame; it does not force a paused
            -- host to step. Preserve the pause and observe live yields instead.
            local released=clock()
            timing.yields_after_release=0
            while (clock()-released)*1000<C.probe_options.host_hold_ms do
                emu.yield();timing.yields_after_release=timing.yields_after_release+1
                if not main_form.EmulatorPaused then error("Private pause changed after hold release") end
                if main_form.BlockFrameAdvance then error("Another hold appeared after release") end
                if emu.framecount()~=before then error("Paused core advanced after hold release") end
            end
            timing.elapsed_after_release_ms=(clock()-released)*1000
            timing.frame_after_release_observation=emu.framecount()
            check("host_hold_paused_after_release",main_form.EmulatorPaused,true)
            check("host_hold_paused_frames_after_release",emu.framecount(),before)
            check("host_hold_paused_yields_after_release",timing.yields_after_release>0,true)
            timing.explicit_step="not_requested_while_paused"
        else
            emu.frameadvance()
            timing.frame_after_explicit_step=emu.framecount()
            timing.paused_after_explicit_step=main_form.EmulatorPaused
            check("host_hold_explicit_step_after_release",timing.frame_after_explicit_step,before+1)
            check("host_hold_pause_still_preserved",timing.paused_after_explicit_step,paused_before)
        end
        ctx.checkpoint("host_post_release_observed")
    end
    sample("after")
    out.frames_advanced=emu.framecount()-first
    out.inputs_stopped_at_field_hint=stop_inputs
    check("fixture_observation_complete",out.frames_advanced>=C.frames,true)
    -- A checksum, good-looking RAM, or zero arena hits is not a compatibility certificate.
    out.compatibility="unverified";out.ownership="unresolved"
end
