-- Inactive pinned host actuator. No game-memory, network or frame-advance API.
-- Use only from the exclusive between-frame Lua control loop, never a bus callback.
local M={}
local PROFILES={mgba={capability_id="bizhawk-2.11.1-mgba-exclusive-hold-v1",emulator_version="2.11.1",
    emulator_sha256="f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd",
    core_type="BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk",
    core_assembly_sha256="444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5",
    native_module_sha256="ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1"},
    gambatte={capability_id="bizhawk-2.11.1-gambatte-exclusive-hold-v1",emulator_version="2.11.1",
    emulator_sha256="f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd",
    core_type="BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy",
    core_assembly_sha256="444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5",
    native_module_sha256="320d615454af44bbe586bcb53afa14a64e834a4156c0d4a731d59cda30ce0722"}}
local NATIVE={mgba={fragment="mgba",filename="mgba.dll"},gambatte={fragment="gambatte",filename="libgambatte.dll"}}
local function copy(source)
    local result={};for key,value in pairs(source) do result[key]=value end;return result
end
local function text(value,size)
    return type(value)=="string" and #value>0 and #value<=size and not value:find("[%c]")
end
local function owner_id(value)
    return type(value)=="string" and #value==32 and value:match("^[0-9a-f]+$")~=nil
end
function M.supported_profile(selection)
    if selection==nil then selection="mgba" end
    if type(selection)~="string" or not PROFILES[selection] then return nil,"unproved host profile selection" end
    return copy(PROFILES[selection])
end

function M.new(options)
    local semaphore,lease_acquired
    local ok,result=pcall(function()
        assert(type(options)=="table" and owner_id(options.owner_id),"explicit32-hex owner_id required")
        -- Existing callers retain exactly the mGBA default and pin fields. A
        -- different core requires an explicit selection, never inferred pins.
        local selection=options.profile
        if selection==nil then selection="mgba" end
        assert(type(selection)=="string" and PROFILES[selection],"unproved host profile selection")
        local PROFILE,native=PROFILES[selection],NATIVE[selection]
        assert(options.exclusive_ownership=="emulator_process" and options.control_context=="between_frames",
            "explicit exclusive between-frame control ownership required")
        assert(type(options.expected_host)=="table","exact expected host/core evidence required")
        for key,value in pairs(PROFILE) do
            assert(options.expected_host[key]==value,"unproved host capability or expected identity: "..key)
        end
        local owner=options.owner_id
        luanet.load_assembly("System")
        luanet.load_assembly("System.Windows.Forms")
        local Application=luanet.import_type("System.Windows.Forms.Application")
        local Process=luanet.import_type("System.Diagnostics.Process")
        local Object=luanet.import_type("System.Object")
        local Semaphore=luanet.import_type("System.Threading.Semaphore")
        local File=luanet.import_type("System.IO.File")
        local Hash=luanet.import_type("System.Security.Cryptography.SHA256")
        local Bits=luanet.import_type("System.BitConverter")
        local function fingerprint(path)
            local algorithm=Hash.Create()
            local hash_ok,value=pcall(function()
                return tostring(Bits.ToString(algorithm:ComputeHash(File.ReadAllBytes(path)))):gsub("-",""):lower()
            end)
            algorithm:Dispose()
            assert(hash_ok,value);return value
        end
        local main
        local function exclusive_forms()
            local main_count,lua_count=0,0
            local iterator=Application.OpenForms:GetEnumerator()
            while iterator:MoveNext() do
                local form=iterator.Current
                local name=tostring(form:GetType().FullName)
                if name=="BizHawk.Client.EmuHawk.MainForm" then
                    main_count=main_count+1
                    if main and not Object.ReferenceEquals(main,form) then return false end
                    main=form
                elseif name=="BizHawk.Client.EmuHawk.LuaConsole" then lua_count=lua_count+1
                else return false end
            end
            return main_count==1 and lua_count==1
        end
        assert(exclusive_forms(),"exclusive MainForm/LuaConsole surfaces unavailable")
        local process=Process.GetCurrentProcess()
        local pid=tonumber(process.Id)
        assert(pid and pid%1==0 and pid>0,"host process identity unavailable")
        assert(client.getversion()==PROFILE.emulator_version,"live host version mismatch")
        assert(fingerprint(process.MainModule.FileName)==PROFILE.emulator_sha256,"live executable hash mismatch")
        local core=main.Emulator
        local core_type=core:GetType()
        assert(tostring(core_type.FullName)==PROFILE.core_type,"live core type mismatch")
        assert(fingerprint(core_type.Assembly.Location)==PROFILE.core_assembly_sha256,"live core assembly hash mismatch")
        local modules=process.Modules:GetEnumerator()
        local native_count=0
        while modules:MoveNext() do
            local module=modules.Current
            if tostring(module.ModuleName):lower():find(native.fragment,1,true) then
                native_count=native_count+1
                assert(tostring(module.ModuleName):lower()==native.filename and
                    fingerprint(module.FileName)==PROFILE.native_module_sha256,"live native module mismatch")
            end
        end
        assert(native_count==1,"exact native module evidence unavailable")
        local function host_valid()
            return exclusive_forms() and Object.ReferenceEquals(core,main.Emulator)
                and not main.IsDisposed and not main.InvokeRequired
                and (main.Rewinder==nil or not main.Rewinder.Active)
                and not main.PressRewind and not main.IsRewinding
        end
        assert(host_valid(),"host/core/tool/rewind conflict")
        assert(type(main.BlockFrameAdvance)=="boolean" and type(main.EmulatorPaused)=="boolean",
            "execution/pause readback unavailable")
        assert(main.BlockFrameAdvance==false,"pre-existing execution hold cannot be adopted")
        -- A kernel semaphore is not reentrant by OS thread. The fixed process
        -- name prevents two Lua callers choosing different lock paths/names.
        local lease_name="Local\\SLink.PlatformExecution.v1."..string.format("%d",pid)
        semaphore=Semaphore(1,1,lease_name)
        assert(semaphore:WaitOne(0)==true,"another Lua execution owner holds this process")
        lease_acquired=true
        local second=Semaphore(1,1,lease_name)
        local check_ok,second_acquired=pcall(function() return second:WaitOne(0) end)
        if check_ok and second_acquired then second:Release() end
        second:Dispose()
        assert(check_ok and second_acquired==false,"same-thread exclusive ownership check failed")
        assert(host_valid() and main.BlockFrameAdvance==false,"host changed during ownership claim")
        local state={held=false,failed=false,closed=false,reason="exclusive actuator claimed; policy has not requested a hold",
            failure=nil,frame=nil,yield_verified=false,yields=0,lease_owned=true,stop_verified=false,
            emergency_attempts=0,emergency_error=nil}
        local self={}
        local function verify_lease()
            assert(not state.closed and state.lease_owned and lease_acquired and semaphore,
                "execution process lease is not owned")
            local probe=Semaphore(1,1,lease_name)
            local probe_ok,acquired=pcall(function() return probe:WaitOne(0) end)
            if probe_ok and acquired then probe:Release() end
            probe:Dispose()
            assert(probe_ok and acquired==false,"execution process lease lost exclusion")
        end
        local function emergency_hold()
            state.emergency_attempts=state.emergency_attempts+1;state.stop_verified=false
            local stopped,why=pcall(function()
                verify_lease()
                assert(host_valid(),"emergency hold host/core/tool/rewind conflict")
                local paused=main.EmulatorPaused
                assert(type(paused)=="boolean","emergency pause readback unavailable")
                local frame=emu.framecount()
                -- Reassert only a STOP under our still-exclusive process lease.
                -- Never clear/adopt a foreign flag and never modify user pause.
                if main.BlockFrameAdvance~=true then main.BlockFrameAdvance=true end
                assert(main.BlockFrameAdvance==true,"emergency hold setter did not read back")
                assert(main.EmulatorPaused==paused,"emergency hold changed user pause")
                assert(emu.framecount()==frame,"frame advanced while acquiring emergency hold")
                state.held=true;state.frame=frame;state.stop_verified=true;state.yield_verified=false
            end)
            state.emergency_error=not stopped and tostring(why) or nil
            return stopped,state.emergency_error
        end
        local function fail(why)
            state.failed=true;state.failure=tostring(why)
            -- A release/readback failure may already have cleared the host flag.
            -- Try to stop it under retained ownership; never claim success from
            -- state.held alone. No automatic release/finalizer/exit hook exists.
            emergency_hold()
            return false,state.failure
        end
        local function verify()
            assert(not state.failed,state.failure or "execution owner failed")
            verify_lease()
            assert(host_valid(),"host/core/tool/rewind conflict")
            assert(type(main.EmulatorPaused)=="boolean","user pause readback unavailable")
            assert(main.BlockFrameAdvance==state.held,"execution hold changed outside its owner")
            if state.held then assert(emu.framecount()==state.frame,"core advanced during execution hold") end
            return true
        end
        function self.verify()
            local verified,why=pcall(verify)
            if not verified then return fail(why) end
            return true
        end
        function self.set_held(value,why)
            if type(value)~="boolean" or not text(why,256) then return false,"boolean hold and explicit reason required" end
            if state.failed then
                if value then return emergency_hold() end
                return false,state.failure or "failed execution owner cannot release"
            end
            local changed,problem=pcall(function()
                verify()
                local paused=main.EmulatorPaused
                if value~=state.held then
                    local frame=emu.framecount()
                    main.BlockFrameAdvance=value
                    -- Ownership changes only after the setter's readback. On
                    -- uncertainty retain the handle and never attempt a release.
                    assert(main.BlockFrameAdvance==value,"execution hold setter did not read back")
                    assert(main.EmulatorPaused==paused,"execution hold setter changed user pause")
                    state.held=value;state.frame=value and frame or nil;state.yield_verified=false;state.stop_verified=value
                end
                state.reason=why
                verify()
            end)
            if not changed then return fail(problem) end
            return true
        end
        function self.yield_held()
            if not state.held then return false,"verified execution hold required before yield" end
            local yielded,problem=pcall(function()
                verify();emu.yield();state.yields=state.yields+1;verify();state.yield_verified=true
            end)
            if not yielded then return fail(problem) end
            return true
        end
        function self.close()
            if state.closed then return false,"execution owner is already closed" end
            if state.failed then return false,state.failure or "failed execution owner cannot close" end
            if state.held then return false,"explicit verified hold release required before close" end
            local closed,problem=pcall(function()
                verify()
                assert(semaphore:Release()==0,"exclusive ownership release was not exact")
                lease_acquired=false;state.lease_owned=false
                semaphore:Dispose();semaphore=nil;state.closed=true
            end)
            if not closed then return fail(problem) end
            return true
        end
        function self.status()
            local read_ok,blocked,paused=pcall(function() return main.BlockFrameAdvance,main.EmulatorPaused end)
            local scope_ok,scope_valid=pcall(function()
                return host_valid() and state.lease_owned and lease_acquired and
                    state.frame~=nil and emu.framecount()==state.frame
            end)
            local block_value,pause_value
            if read_ok then block_value,pause_value=blocked,paused end
            return {capability_id=PROFILE.capability_id,owner_id=owner,process_id=pid,lease_name=lease_name,
                held=state.held,failed=state.failed,closed=state.closed,failure=state.failure,reason=state.reason,
                lease_owned=state.lease_owned,host_readback_available=read_ok,
                host_blocked=block_value,user_paused=pause_value,
                physical_stop_verified=state.stop_verified and read_ok and blocked==true and scope_ok and scope_valid,
                emergency_attempts=state.emergency_attempts,emergency_error=state.emergency_error,
                held_yield_verified=state.yield_verified,yields=state.yields,
                capabilities={exclusive_between_frame_hold=true,preserves_user_pause=true,
                    reset_control=false,load_state_control=false,rewind_control=false,debugger_control=false,
                    native_recovery_execution=false,full_execution_safety=false,production_selected=false}}
        end
        return self
    end)
    if not ok then
        -- Construction never changes BlockFrameAdvance. Close only our own
        -- temporary handles, and never adopt or release an existing host flag.
        if semaphore then
            if lease_acquired then pcall(function() semaphore:Release() end) end
            pcall(function() semaphore:Dispose() end)
        end
        return nil,tostring(result)
    end
    return result
end
return M
