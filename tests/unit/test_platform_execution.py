"""Pinned actuator contracts using modeled host/OS handles, not live host proof."""

from pathlib import Path

import pytest
from lupa import LuaRuntime

SOURCE = Path(__file__).parents[2] / "lua/platform_execution.lua"

HOST = r"""
T={frame=100,pid=12345,blocked=false,paused=false,flag_writes=0,pause_writes=0,
    semaphores={},handles={},version='2.11.1',yields=0}
local function enumerator(items)
    local index=0;local result={}
    result.MoveNext=function(self) index=index+1;self.Current=items[index];return self.Current~=nil end
    return result
end
local function form(name) return {GetType=function() return {FullName=name} end} end
local core={GetType=function() return {FullName=T.core_type,Assembly={Location='core.dll'}} end}
main=setmetatable({Emulator=core,Rewinder={Active=false},PressRewind=false,IsRewinding=false,
    IsDisposed=false,InvokeRequired=false,GetType=function() return {FullName='BizHawk.Client.EmuHawk.MainForm'} end},
    {__index=function(_,key)
        if key=='BlockFrameAdvance' then
            if T.throw_next_block_read then T.throw_next_block_read=false;error('post-release readback failed') end
            return T.blocked
        end
        if key=='EmulatorPaused' then return T.paused end
    end,__newindex=function(object,key,value)
        if key=='BlockFrameAdvance' then
            T.flag_writes=T.flag_writes+1
            if not T.ignore_flag_setter then T.blocked=value end
            if T.setter_changes_pause then T.paused=not T.paused end
            if not value and T.release_readback_error then T.throw_next_block_read=true end
        elseif key=='EmulatorPaused' then T.pause_writes=T.pause_writes+1;T.paused=value
        else rawset(object,key,value) end
    end})
local function sem_new(initial,maximum,name)
    assert(initial==1 and maximum==1 and name=='Local\\SLink.PlatformExecution.v1.12345')
    local kernel=T.semaphores[name]
    if not kernel or T.bad_semaphore then kernel={count=initial,handles=0};T.semaphores[name]=kernel end
    kernel.handles=kernel.handles+1
    local handle={closed=false,kernel=kernel}
    T.handles[#T.handles+1]=handle
    handle.WaitOne=function(self,timeout)
        assert(not self.closed and timeout==0)
        if self.kernel.count==0 then return false end
        self.kernel.count=self.kernel.count-1;return true
    end
    handle.Release=function(self)
        assert(not self.closed)
        if T.release_error then error('semaphore release failed') end
        local previous=self.kernel.count
        assert(previous==0,'semaphore overrelease')
        self.kernel.count=1;return previous
    end
    handle.Dispose=function(self)
        if not self.closed then self.closed=true;self.kernel.handles=self.kernel.handles-1 end
    end
    return handle
end
local types={
    ['System.Windows.Forms.Application']={OpenForms={GetEnumerator=function()
        local items={main,form('BizHawk.Client.EmuHawk.LuaConsole')}
        if T.other_tool then items[#items+1]=form('BizHawk.Client.EmuHawk.Debugger') end
        if T.extra_main then items[#items+1]=form('BizHawk.Client.EmuHawk.MainForm') end
        return enumerator(items)
    end}},
    ['System.Diagnostics.Process']={GetCurrentProcess=function()
        return {Id=T.pid,MainModule={FileName='host.exe'},Modules={GetEnumerator=function()
            local native=T.native_name or 'mgba.dll'
            local items={{ModuleName=native,FileName=native}}
            if T.extra_native then items[#items+1]={ModuleName=native..'.so',FileName=native} end
            return enumerator(items)
        end}}
    end},
    ['System.Object']={ReferenceEquals=function(a,b) return rawequal(a,b) end},
    ['System.Threading.Semaphore']=sem_new,
    ['System.IO.File']={ReadAllBytes=function(path) return assert(T.hashes[path],'unknown host path') end},
    ['System.Security.Cryptography.SHA256']={Create=function()
        return {ComputeHash=function(_,bytes) return bytes end,Dispose=function() end}
    end},
    ['System.BitConverter']={ToString=function(value) return value end},
}
luanet={load_assembly=function(name) assert(name=='System' or name=='System.Windows.Forms') end,
    import_type=function(name) return types[name] end}
client={getversion=function() return T.version end,
    pause=function() error('adapter must never pause') end,unpause=function() error('adapter must never unpause') end}
emu={framecount=function() return T.frame end,frameadvance=function() error('no frame advance capability') end,
    yield=function()
        assert(T.blocked,'yield without hold');T.yields=T.yields+1
        if T.frame_during_yield then T.frame=T.frame+1 end
        if T.user_pause_during_yield then T.paused=true end
        if T.flag_during_yield then T.blocked=false end
    end}
memory=setmetatable({}, {__index=function() error('no game memory capability') end})
function setup(profile)
    T.core_type=profile.core_type
    T.hashes={['host.exe']=profile.emulator_sha256,['core.dll']=profile.core_assembly_sha256,
        [T.native_name or 'mgba.dll']=profile.native_module_sha256}
    return {owner_id=string.rep('a',32),expected_host=profile,exclusive_ownership='emulator_process',control_context='between_frames'}
end
"""


def make():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HOST)
    module = lua.execute(SOURCE.read_text())
    options = lua.globals().setup(module.supported_profile())
    return lua, module, options


@pytest.mark.parametrize("paused", [False, True])
def test_independent_flag_preserves_user_pause_and_requires_explicit_close(paused):
    lua, module, options = make()
    state = lua.globals().T
    state.paused = paused
    owner = module.new(options)
    assert owner.status().host_blocked is False and owner.status().user_paused is paused
    assert owner.set_held(True, "reconcile") is True
    assert owner.yield_held() is True and state.frame == 100
    assert owner.close()[0] is False  # Never releases a hold as a cleanup side effect.
    assert state.blocked and owner.status().lease_owned
    assert owner.set_held(False, "paired permission") is True
    assert state.paused is paused and not state.blocked and state.pause_writes == 0
    assert owner.close() is True and owner.status().closed


def test_second_module_and_same_owner_token_cannot_reenter_on_same_thread():
    lua, module, options = make()
    owner = module.new(options)
    # A fresh module instance has no shared Lua-local owner table to rely on.
    independent_module = lua.execute(SOURCE.read_text())
    contender, reason = independent_module.new(options)
    assert contender is None and "another Lua execution owner" in reason
    assert lua.globals().T.flag_writes == 0  # First owner's lease exists even while unheld.
    assert owner.set_held(True, "hold") is True
    contender, reason = independent_module.new(options)
    assert contender is None and "pre-existing execution hold" in reason
    assert owner.set_held(False, "release") is True and owner.close() is True
    replacement = independent_module.new(options)
    assert replacement is not None and replacement.close() is True


def test_same_thread_second_handle_self_check_refuses_broken_exclusion():
    lua, module, options = make()
    lua.globals().T.bad_semaphore = True
    owner, reason = module.new(options)
    assert owner is None and "same-thread exclusive ownership check failed" in reason
    assert lua.globals().T.flag_writes == 0
    assert all(handle.closed for handle in lua.globals().T.handles.values())


@pytest.mark.parametrize(
    "conflict", ["other_tool", "extra_main", "extra_native", "version", "hash", "rewind", "thread"]
)
def test_live_identity_and_exclusivity_fail_before_changing_execution(conflict):
    lua, module, options = make()
    state, main = lua.globals().T, lua.globals().main
    if conflict in {"other_tool", "extra_main", "extra_native"}:
        state[conflict] = True
    elif conflict == "version":
        state.version = "2.12"
    elif conflict == "hash":
        state.hashes["mgba.dll"] = "0" * 64
    elif conflict == "rewind":
        main.PressRewind = True
    else:
        main.InvokeRequired = True
    owner, reason = module.new(options)
    assert owner is None and reason and state.flag_writes == 0


@pytest.mark.parametrize(
    "missing", ["owner_id", "expected_host", "exclusive_ownership", "control_context"]
)
def test_explicit_evidence_and_ownership_contract_are_required(missing):
    lua, module, options = make()
    options[missing] = None
    owner, reason = module.new(options)
    assert owner is None and reason and lua.globals().T.flag_writes == 0


def test_unproved_core_profile_is_not_selected_implicitly():
    lua, module, options = make()
    options.expected_host.core_type = "BizHawk.Emulation.Cores.Nintendo.Gameboy.Gambatte"
    owner, reason = module.new(options)
    assert owner is None and "unproved host capability" in reason
    assert lua.globals().T.flag_writes == 0


@pytest.mark.parametrize(
    "fault", ["frame_during_yield", "flag_during_yield", "tool", "core", "rewind"]
)
def test_failed_owner_retains_lease_and_never_releases_or_adopts_a_flag(fault):
    lua, module, options = make()
    state, main = lua.globals().T, lua.globals().main
    owner = module.new(options)
    assert owner.set_held(True, "reconcile") is True
    if fault in {"frame_during_yield", "flag_during_yield"}:
        state[fault] = True
        assert owner.yield_held()[0] is False
    else:
        if fault == "tool":
            state.other_tool = True
        elif fault == "core":
            main.Emulator = lua.table()
        else:
            main.PressRewind = True
        assert owner.verify()[0] is False
    before = state.flag_writes
    assert owner.status().failed and owner.status().lease_owned
    assert owner.set_held(False, "must refuse")[0] is False
    assert owner.close()[0] is False and state.flag_writes == before
    assert module.new(options)[0] is None


def test_user_can_pause_during_hold_and_release_preserves_that_pause():
    lua, module, options = make()
    owner = module.new(options)
    assert owner.set_held(True, "hold") is True
    lua.globals().T.user_pause_during_yield = True
    assert owner.yield_held() is True
    assert owner.set_held(False, "release") is True
    assert lua.globals().T.paused and lua.globals().T.pause_writes == 0
    assert owner.close() is True


@pytest.mark.parametrize("fault", ["ignore_flag_setter", "setter_changes_pause"])
def test_setter_readback_failure_is_latched_without_automatic_release(fault):
    lua, module, options = make()
    owner = module.new(options)
    lua.globals().T[fault] = True
    assert owner.set_held(True, "hold")[0] is False
    before = lua.globals().T.flag_writes
    assert owner.status().failed and owner.status().lease_owned
    assert owner.close()[0] is False
    assert lua.globals().T.flag_writes == before


def test_preexisting_hold_without_an_adapter_cannot_be_adopted():
    lua, module, options = make()
    lua.globals().T.blocked = True  # Could be an abandoned/stopped owner's flag.
    owner, reason = module.new(options)
    assert owner is None and "cannot be adopted" in reason
    assert lua.globals().T.blocked and lua.globals().T.flag_writes == 0


def test_owner_identity_is_copied_and_unsupported_capabilities_stay_false():
    lua, module, options = make()
    owner = module.new(options)
    options.owner_id = "b" * 32
    status = owner.status()
    assert status.owner_id == "a" * 32
    for capability in [
        "reset_control",
        "load_state_control",
        "rewind_control",
        "debugger_control",
        "native_recovery_execution",
        "full_execution_safety",
        "production_selected",
    ]:
        assert status.capabilities[capability] is False
    assert owner.yield_held()[0] is False
    assert owner.close() is True


def test_failure_after_release_setter_reholds_under_the_retained_lease():
    lua, module, options = make()
    owner = module.new(options)
    assert owner.set_held(True, "hold") is True
    lua.globals().T.release_readback_error = True
    assert owner.set_held(False, "release")[0] is False
    state = owner.status()
    assert state.failed and state.host_blocked and state.physical_stop_verified
    assert state.emergency_attempts == 1 and state.lease_owned
    assert owner.set_held(True, "shared control emergency stop")[0] is True
    assert owner.set_held(False, "must not resume")[0] is False
    assert lua.globals().T.pause_writes == 0


def test_external_clear_is_reheld_but_original_failure_remains_latched():
    lua, module, options = make()
    owner = module.new(options)
    assert owner.set_held(True, "hold") is True
    lua.globals().T.blocked = False
    lua.globals().T.frame += 1
    assert owner.verify()[0] is False
    state = owner.status()
    assert state.failed and state.host_blocked and state.physical_stop_verified
    assert "changed outside" in state.failure
    assert owner.set_held(False, "cannot release failed owner")[0] is False


def test_unverifiable_actuator_failure_never_claims_a_physical_stop():
    lua, module, options = make()
    owner = module.new(options)
    assert owner.set_held(True, "hold") is True
    state = lua.globals().T
    state.blocked, state.ignore_flag_setter = False, True
    assert owner.verify()[0] is False
    status = owner.status()
    assert status.failed and status.host_blocked is False and status.physical_stop_verified is False
    assert status.emergency_error and status.lease_owned
    assert owner.set_held(True, "cannot verify emergency stop")[0] is False


def test_failed_old_owner_cannot_emergency_hold_after_its_lease_was_closed():
    lua, module, options = make()
    old = module.new(options)
    assert old.close() is True
    replacement = module.new(options)
    before = lua.globals().T.flag_writes
    assert old.set_held(True, "stale instance")[0] is False
    assert old.status().physical_stop_verified is False
    assert lua.globals().T.flag_writes == before
    assert replacement.close() is True


def test_shared_control_emergency_rehold_uses_the_failed_actuator_safely():
    lua, module, options = make()
    lua.globals().package.path = (SOURCE.parent / "?.lua").as_posix()
    control_module = lua.eval('require("control_service")')
    if isinstance(control_module, tuple):
        control_module = control_module[0]
    owner = module.new(options)
    control = control_module.new(
        lua.table_from(
            {
                "host": owner,
                "clock": lua.eval("function() return 0 end"),
                "new_nonce": lua.eval("function() return string.rep('e',32) end"),
            }
        )
    )
    binding = lua.table_from(
        {
            "session_id": "a" * 32,
            "admission_epoch": "b" * 32,
            "context_generation": "c" * 32,
            "binding_digest": "d" * 64,
        }
    )
    control.bind(control, binding)
    packet = control.challenge(control)
    packet.authority, packet.service_epoch, packet.service_digest = "run", "e" * 32, "2" * 64
    packet.recovery_epoch, packet.ticket_digest = "f" * 32, "1" * 64
    assert control.accept(control, packet) is True
    lua.globals().T.release_readback_error = True
    assert control.step(control)[0] is False
    assert control.status(control).held and not control.status(control).ordinary_execution
    assert owner.status().failed and owner.status().physical_stop_verified
    assert lua.globals().T.blocked and lua.globals().T.pause_writes == 0


def test_existing_default_profile_fields_are_unchanged_and_copied():
    _, module, _ = make()
    profile = dict(module.supported_profile())
    assert profile == {
        "capability_id": "bizhawk-2.11.1-mgba-exclusive-hold-v1", "emulator_version": "2.11.1",
        "emulator_sha256": "f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd",
        "core_type": "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk",
        "core_assembly_sha256": "444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5",
        "native_module_sha256": "ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1",
    }
    assert dict(module.supported_profile("mgba")) == profile
    changed = module.supported_profile("gambatte")
    changed.core_type = "untrusted"
    assert module.supported_profile("gambatte").core_type == "BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"


@pytest.mark.parametrize("selection", ["", "unknown", False, 7, []])
def test_invalid_explicit_profile_selection_never_falls_back(selection):
    lua, module, options = make()
    assert module.supported_profile(selection)[0] is None
    options.profile = selection
    owner, reason = module.new(options)
    assert owner is None and "unproved host profile selection" in reason
    assert lua.globals().T.flag_writes == 0 and not list(lua.globals().T.handles.values())


def test_gambatte_requires_explicit_selection_and_uses_its_own_native_module():
    lua, module, options = make()
    profile = module.supported_profile("gambatte")
    options.expected_host = profile
    assert module.new(options)[0] is None  # Pins cannot silently select a different core.
    lua.globals().T.native_name = "libgambatte.dll"
    options = lua.globals().setup(profile)
    options.profile = "gambatte"
    owner = module.new(options)
    assert owner.set_held(True, "Gambatte model") is True
    assert owner.yield_held() is True and owner.status().physical_stop_verified
    assert owner.status().capability_id == profile.capability_id
    assert owner.status().capabilities.full_execution_safety is False
    assert owner.status().capabilities.native_recovery_execution is False
    assert owner.set_held(False, "model complete") is True and owner.close() is True


@pytest.mark.parametrize("drift", ["core", "module", "native-hash", "host-version"])
def test_gambatte_selection_still_requires_every_live_identity_pin(drift):
    lua, module, _ = make()
    state = lua.globals().T
    state.native_name = "libgambatte.dll"
    options = lua.globals().setup(module.supported_profile("gambatte"))
    options.profile = "gambatte"
    if drift == "core":
        state.core_type = "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk"
    elif drift == "module":
        state.native_name = "mgba.dll"
    elif drift == "native-hash":
        state.hashes["libgambatte.dll"] = "0" * 64
    else:
        state.version = "2.12"
    owner, reason = module.new(options)
    assert owner is None and reason
    assert state.flag_writes == 0 and not list(state.handles.values())
