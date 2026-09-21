"""Probe contract/parse checks; physical state transitions belong to the lane."""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "lua/tests/probe_gen3_checkpoint.lua").read_text(encoding="utf-8")
TERMINALS = {
    "idle": "field_idle_300",
    "walking": "position_changed_120",
    "start_menu": "field_controls_locked",
    "dialog": "save_dialog_cb_nonzero",
    "save": "new_counter_partial_slot_then_14_sectors",
    "battle": "in_battle_mask_nonzero",
    "fade": "palette_fade_active_then_map_changed",
}


@pytest.fixture
def module():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    # Executing the definition chunk also compiles it, without entering main.
    return lua, lua.execute(SOURCE)


def test_all_states_have_named_terminals(module):
    _, probe = module
    states = {row.name: row.terminal for row in probe.STATES.values()}
    assert states == TERMINALS
    for name, terminal in TERMINALS.items():
        assert f'name="{name}", terminal="{terminal}"' in SOURCE


@pytest.mark.parametrize("expectation,samples,yes,reached,error,want", [
    ("positive", 300, 270, True, None, True),
    ("positive", 300, 269, True, None, False),
    ("negative", 120, 0, True, None, True),
    ("negative", 120, 1, True, None, False),
    ("negative", 0, 0, True, None, False),
    ("negative", 120, 0, False, None, False),
    ("negative", 120, 0, True, "unreadable", False),
    ("report", 120, 2, True, None, True),
])
def test_verdict_requires_nonvacuous_terminal(module, expectation, samples, yes, reached, error, want):
    lua, probe = module
    row = lua.table_from({"expectation": expectation, "samples": samples, "yes": yes, "reached": reached, "error": error})
    assert probe.verdict(row) is want


def test_read_only_dependencies_forward_domain_and_raw_registers(module):
    lua, probe = module
    mem = lua.eval("""{read_u8=function(a,d) return d == 'ROM' and a or -1 end,
        read_u16_le=function(a,d) return d == 'System Bus' and a+1 or -1 end,
        read_u32_le=function(a,d) return d == 'System Bus' and a+2 or -1 end}""")
    emulator = lua.eval("""{getregister=function(n) return n == 'R15' and 452 or -2147483617 end,
        framecount=function() return 73 end}""")
    deps = probe.build_deps(mem, emulator, lua.eval("function() return true end"))
    assert deps.io.read_u8(5, "ROM") == 5
    assert deps.io.read_u16_le(5, "System Bus") == 6
    assert deps.io.read_u32_le(5, "System Bus") == 7
    assert deps.regs().R15 == 452
    assert deps.regs().CPSR == -2147483617  # probe must not hide core register behavior
    assert deps.frame() == 73 and deps.native_idle()
    assert all(not key.startswith("write") for key in deps.io)


def test_real_safety_frame_end_sampling_and_save_witness_are_wired():
    assert 'dofile(wt .. "/lua/gen3/safety.lua")' in SOURCE
    assert "S.new(cp, deps, kind)" in SOURCE
    assert "event.onframeend(function()" in SOURCE
    assert "safety:check()" in SOURCE
    assert "counter > before and G.sectors_at(domain,counter) < 14" in SOURCE
    assert "G.sectors_at(domain,after) >= 14" in SOURCE
    assert "#rows == #P.STATES" in SOURCE
    assert "#write_log == 0" in SOURCE
    assert "memory.write" not in SOURCE
    assert 'dofile(wt .. "/lua/gen3/writes.lua")' not in SOURCE
