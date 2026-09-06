"""Actual arena Lua and clock module; fake private host/core callback surfaces."""

from pathlib import Path

import pytest
from lupa import LuaError, LuaRuntime

ROOT = Path(__file__).parents[2]
FIRST, LAST = 0x0203F769, 0x02040000

HOST = r"""
H={frame=0,seconds=0,register_delta=0.0001,remove_delta=0.0001,yield_delta=0.001,
    measurement_delta=0.01,frame_delta=1,yields=0,registrations={},hooks={},by_address={},
    registration_faults={},removal_faults={},cleanup={},checkpoints={},checks={},writes=4}
local function form(name) return {GetType=function() return {FullName=name} end} end
main=form('BizHawk.Client.EmuHawk.MainForm')
main.Rewinder={Active=false};main.PressRewind=false;main.IsRewinding=false
main.BlockFrameAdvance=false;main.EmulatorPaused=false
local Application={OpenForms={GetEnumerator=function()
    local items={main,form('BizHawk.Client.EmuHawk.LuaConsole')}
    if H.other_tool then items[#items+1]=form('BizHawk.Client.EmuHawk.Debugger') end
    local index=0;local result={}
    result.MoveNext=function(self) index=index+1;self.Current=items[index];return self.Current~=nil end
    return result
end}}
luanet={import_type=function(name)
    if name=='System.Windows.Forms.Application' then return Application end
    if name=='System.Diagnostics.Stopwatch' then
        return {StartNew=function() return {Elapsed=setmetatable({}, {__index=function(_,key)
            assert(key=='TotalSeconds');return H.seconds
        end})} end}
    end
    error('unexpected host import '..name)
end}
emu={framecount=function() return H.frame end,getregisters=function()
    if H.in_measurement and H.fail_register_reads then error('register read failed') end
    local result={R15=H.raw_pc or 0x0800051C,CPSR=0x6000003F}
    for i=0,14 do result['R'..i]=i end
    return result
end}
emu.yield=function()
    assert(main.BlockFrameAdvance,'yield without execution hold')
    H.seconds=H.seconds+H.yield_delta;H.yields=H.yields+1
    if H.yields==H.break_yield then
        if H.break_kind=='frame' then H.frame=H.frame+1
        elseif H.break_kind=='flag' then main.BlockFrameAdvance=false
        elseif H.break_kind=='pause' then main.EmulatorPaused=true
        elseif H.break_kind=='tool' then H.other_tool=true
        elseif H.break_kind=='rewind' then main.PressRewind=true end
    end
end
local function register(kind,fn,address,name,scope)
    assert(main.BlockFrameAdvance and not main.EmulatorPaused,'registration without verified hold')
    assert(type(address)=='number' and scope=='System Bus','wildcard/scope regression')
    H.seconds=H.seconds+H.register_delta
    local index=#H.registrations+1
    local id=string.format('%08x-0000-4000-8000-000000000000',index)
    local row={kind=kind,address=address,name=name,fn=fn,id=id}
    H.registrations[index]=row;H.hooks[name]=row;H.by_address[kind..address]=row
    local fault=H.registration_faults[index]
    if fault=='zero' then return '00000000-0000-0000-0000-000000000000' end
    if fault=='duplicate' then return H.registrations[1].id end
    if fault=='throw' then error('native registration exception') end
    return id
end
event={can_use_callback_params=function(kind) return kind=='memory' end,
    on_bus_write=function(...) return register('write',...) end,
    on_bus_exec=function(...) return register('exec',...) end,
    on_bus_read=function() error('this declared lane must not request read coverage') end,
    unregisterbyname=function(name)
        assert(main.BlockFrameAdvance and not main.EmulatorPaused,'cleanup without verified hold')
        H.seconds=H.seconds+H.remove_delta;H.cleanup[#H.cleanup+1]=name
        if H.removal_faults[#H.cleanup]=='throw' then error('native removal exception') end
        if H.removal_faults[#H.cleanup]=='false' then return false end
        local found=H.hooks[name]~=nil;H.hooks[name]=nil;return found
    end}
emu.frameadvance=function()
    assert(not main.BlockFrameAdvance and not main.EmulatorPaused,'illegal measured advance')
    if H.allow_boot and #H.registrations==0 then H.frame=H.frame+1;return end
    H.frame=H.frame+H.frame_delta;H.seconds=H.seconds+H.measurement_delta;H.in_measurement=true
    local exec=H.by_address['exec'..0x0800051A]
    assert(exec,'measured frame without complete execution coverage')
    if not H.no_exec then H.raw_pc=0x0800051C;exec.fn(exec.address,0,16384) end
    if not H.no_writes then
        local store=H.by_address['write'..0x0203F800]
        assert(store,'measured frame without write-start coverage')
        H.raw_pc=0x08378F7C
        -- A u32 store overlaps4 registered byte watchpoints, all routed by the
        -- managed dictionary to its actual-start callback. Keep all deliveries.
        for _=1,H.writes do store.fn(store.address,0x4B4E4C53,8192) end
    end
    H.in_measurement=false
end
memory={read_u8=function() return 0xAB end}
joypad={set=function() end}
report={evidence={}}
function make_context(root)
    local identity={core_assembly_file={sha256=string.rep('1',64)}}
    return {config={source_root=root,frames=1,purpose='validation',probe_options={arena_lane='writes_exec_v1'},
        descriptor={address=0x08001000,size=1,hex='ab'},fixture_kind='state',fixture_meta={host=identity},
        identity={run_id='synthetic',player='a'}},report=report,main_form=main,
        host={available=true,matches_requested_core=true,core_type='BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk',
            core_assembly_file=identity.core_assembly_file},
        checkpoint=function(phase) H.checkpoints[#H.checkpoints+1]=phase end,
        check=function(name,actual,expected)
            H.checks[#H.checks+1]={name=name,actual=actual,expected=expected,passed=actual==expected}
            assert(actual==expected,name)
        end}
end
"""


def fixture():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(HOST)
    ctx = lua.globals().make_context(ROOT.as_posix())
    probe = lua.execute((ROOT / "lua/tests/rr/arena_probe.lua").read_text())
    return lua, ctx, probe


def failures(ctx):
    return [row.code for row in ctx.report.evidence.runtime.failures.values()]


def test_full_padded_write_start_coverage_has_one_frame_and_verified_holds():
    lua, ctx, probe = fixture()
    probe(ctx)
    state, out = lua.globals().H, ctx.report.evidence.runtime
    registrations = list(state.registrations.values())
    assert {row.address for row in registrations if row.kind == "write"} == set(range(FIRST, LAST))
    assert len(registrations) == 2199 + 11 == len(state.cleanup)
    assert len({row.name for row in registrations}) == len(registrations)
    assert out.frames == state.frame == 1 and len(out.holds) == 2
    assert all(row.verified and row.released and row.yields > 0 for row in out.holds.values())
    assert (
        out.all_callbacks_removed and out.hold_released and not lua.globals().main.BlockFrameAdvance
    )
    assert not list(state.hooks.values())
    assert out.raw_write_callbacks == 4 and out.duplicate_candidates == 3
    assert len(out.trace) == 5 and out.trace_dropped == 0 and out.failure_count == 0
    assert out.ownership == "unresolved" and out.release_ready is False
    assert out.read_coverage.startswith("not_requested")
    assert all("pc" not in row and "writer" not in row for row in out.trace.values())


def test_all_registration_failures_retained_and_every_name_cleaned_without_a_frame():
    lua, ctx, probe = fixture()
    lua.globals().H.registration_faults = lua.table_from({2: "zero", 7: "duplicate", 10: "throw"})
    with pytest.raises(LuaError, match="arena_no_failures"):
        probe(ctx)
    out = ctx.report.evidence.runtime
    assert failures(ctx).count("registration_failed") == 3
    assert out.frames == 0 and lua.globals().H.frame == 0
    assert len(out.registration_attempts) == len(out.cleanup_attempts) == 2210
    assert out.all_callbacks_removed and not lua.globals().main.BlockFrameAdvance


def test_battery_boot_precedes_coverage_and_keeps_unique_assertion_ids():
    lua, ctx, probe = fixture()
    lua.globals().H.allow_boot = True
    ctx.config.fixture_kind = "battery"
    ctx.config.fixture_meta.boot_inputs = lua.table_from(
        [lua.table_from({"frames": 1}), lua.table_from({"frames": 2})]
    )
    ctx.config.fixture_meta.ram_assertions = lua.table_from(
        [lua.table_from({"address": 0x02010000, "width": 1, "expected": 0xAB})]
    )
    probe(ctx)
    out, state = ctx.report.evidence.runtime, lua.globals().H
    assert out.instrumentation_started_frame == 3 and out.frames == 1 and state.frame == 4
    assert out.holds[1].frame == 3 and out.holds[2].frame == 4
    ids = [row.name for row in state.checks.values()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("kind", ["frame", "flag", "pause", "tool", "rewind"])
def test_hold_loss_refuses_measurement_and_never_claims_cleanup(kind):
    lua, ctx, probe = fixture()
    lua.globals().H.break_yield = 2
    lua.globals().H.break_kind = kind
    with pytest.raises(LuaError, match="arena_no_failures"):
        probe(ctx)
    out = ctx.report.evidence.runtime
    assert out.frames == 0
    assert len(out.registration_attempts) == 32 and len(out.cleanup_attempts) == 0
    assert not out.all_callbacks_removed and not out.hold_released
    assert "cleanup_pipeline_failed" in failures(ctx)


def test_multiple_cleanup_failures_keep_private_execution_held():
    lua, ctx, probe = fixture()
    lua.globals().H.removal_faults = lua.table_from({2: "false", 7: "throw"})
    with pytest.raises(LuaError, match="arena_no_failures"):
        probe(ctx)
    out = ctx.report.evidence.runtime
    assert failures(ctx).count("cleanup_failed") == 2
    assert len(out.cleanup_attempts) == 2210 and out.cleanup.removed_count == 2208
    assert lua.globals().main.BlockFrameAdvance and out.own_hold_remaining
    assert not out.hold_released and not out.all_callbacks_removed


@pytest.mark.parametrize("phase", ["registration", "measurement", "cleanup"])
def test_wall_bounds_are_failures_with_partial_cleanup_evidence(phase):
    lua, ctx, probe = fixture()
    if phase == "registration":
        lua.globals().H.register_delta = 0.1
    elif phase == "measurement":
        lua.globals().H.measurement_delta = 20
    else:
        lua.globals().H.remove_delta = 0.1
    with pytest.raises(LuaError, match="arena_no_failures"):
        probe(ctx)
    out = ctx.report.evidence.runtime
    if phase == "registration":
        assert out.frames == 0 and 0 < len(out.registration_attempts) < 2210
        assert out.all_callbacks_removed and not lua.globals().main.BlockFrameAdvance
    elif phase == "measurement":
        assert "measurement_wall_bound" in failures(ctx)
        assert out.frames == 1 and out.all_callbacks_removed
    else:
        assert 0 < len(out.cleanup_attempts) < len(out.registration_attempts)
        assert not out.all_callbacks_removed and lua.globals().main.BlockFrameAdvance


def test_trace_overflow_is_retained_and_cannot_pass():
    lua, ctx, probe = fixture()
    lua.globals().H.writes = 8202
    with pytest.raises(LuaError, match="arena_no_failures"):
        probe(ctx)
    out = ctx.report.evidence.runtime
    assert len(out.trace) == 8192 and out.trace_dropped == 11
    assert out.raw_write_callbacks == 8202 and out.all_callbacks_removed
    assert "trace_overflow" in failures(ctx)


def test_simultaneous_measurement_failures_survive_cleanup():
    lua, ctx, probe = fixture()
    state = lua.globals().H
    state.frame_delta, state.measurement_delta, state.fail_register_reads = 2, 20, True
    with pytest.raises(LuaError, match="arena_no_failures"):
        probe(ctx)
    assert {"measurement_frame_bound", "measurement_wall_bound", "register_reads_failed"} <= set(
        failures(ctx)
    )
    assert ctx.report.evidence.runtime.all_callbacks_removed


def test_missing_controls_both_remain_visible():
    lua, ctx, probe = fixture()
    lua.globals().H.no_exec, lua.globals().H.no_writes = True, True
    with pytest.raises(LuaError, match="arena_no_failures"):
        probe(ctx)
    assert {"execute_control_observed", "write_hook_observed"} <= set(failures(ctx))
    assert ctx.report.evidence.runtime.all_callbacks_removed


@pytest.mark.parametrize("invalid", ["lane", "two_frames", "paused", "foreign_hold"])
def test_unapproved_scope_or_existing_host_control_is_untouched(invalid):
    lua, ctx, probe = fixture()
    main = lua.globals().main
    if invalid == "lane":
        ctx.config.probe_options.arena_lane = "reads_and_writes"
    elif invalid == "two_frames":
        ctx.config.frames = 2
    elif invalid == "paused":
        main.EmulatorPaused = True
    else:
        main.BlockFrameAdvance = True
    before = (main.EmulatorPaused, main.BlockFrameAdvance)
    with pytest.raises(LuaError):
        probe(ctx)
    assert before == (main.EmulatorPaused, main.BlockFrameAdvance)
    assert not list(lua.globals().H.registrations.values())
