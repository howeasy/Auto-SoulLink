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
    "pc_menu": "task_pc_main_menu_active_60",
    "script_running": "script_context_not_shutdown_60",
}
CORE = set(range(1, 8))


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
    assert 'FAIL not run' in SOURCE and "passed = false" in SOURCE
    assert "#write_log == 0" in SOURCE
    assert "memory.write" not in SOURCE
    assert 'dofile(wt .. "/lua/gen3/writes.lua")' not in SOURCE


def test_artifact_rows_are_negative_and_gated(module):
    _, probe = module
    rows = {row.name: row for row in probe.STATES.values()}
    for name in ("pc_menu", "script_running"):
        assert rows[name].expectation == "negative"
    assert set(rows["pc_menu"].artifacts.keys()) == {"radical_red/companion"}
    assert set(rows["script_running"].artifacts.keys()) == {"firered/clean", "radical_red/companion"}
    assert all(rows[n].artifacts is None for n in TERMINALS if n not in ("pc_menu", "script_running"))


@pytest.mark.parametrize("title,kind,env,want", [
    ("firered", "clean", None, CORE | {9}),
    ("radical_red", "companion", None, CORE | {8, 9}),
    ("radical_red", "clean", None, CORE),
    ("leafgreen", "clean", None, CORE),
    ("radical_red", "companion", "script_running", CORE | {9}),
    ("radical_red", "companion", "pc_menu, script_running", CORE | {8, 9}),
    ("radical_red", "companion", "none", CORE),
    ("firered", "clean", "", CORE | {9}),
])
def test_planned_rows_by_artifact(module, title, kind, env, want):
    _, probe = module
    plan = probe.planned(title, kind, env)
    assert {i for i in plan if plan[i]} == want


@pytest.mark.parametrize("title,kind,env", [
    ("firered", "clean", "pc_menu"),        # RR-only row asked of FR: loud, not skipped
    ("radical_red", "clean", "script_running"),
    ("firered", "clean", "idle"),           # core rows cannot be narrowed away
    ("firered", "clean", "bogus"),
])
def test_planned_rejects_inadmissible_or_unknown_rows(module, title, kind, env):
    _, probe = module
    with pytest.raises(lupa.LuaError):
        probe.planned(title, kind, env)


def test_witnesses_read_engine_state_not_safety(module):
    lua, probe = module
    assert probe.SCRIPT_STATUS == 0x03000EA8 and probe.TASK_PC_MAIN_MENU == 0x0808C39C
    mem = {}
    read_u8 = lambda a: mem.get(a, 0)  # noqa: E731
    read_u32 = lambda a: mem.get(a, 0)  # noqa: E731
    for status, want in ((0, True), (1, True), (2, False)):
        mem[0x03000EA8] = status
        assert probe.script_active(read_u8) is want
    tasks = lua.table_from({"address": 0x03005090, "count": 16, "struct_size": 40,
                            "func_offset": 0, "is_active_offset": 4})
    slot = 0x03005090 + 3 * 40
    mem[slot] = 0x0808C39D                  # Thumb bit set, as gTasks stores it
    assert probe.task_active(read_u8, read_u32, tasks, 0x0808C39C) is False  # inactive slot
    mem[slot + 4] = 1
    assert probe.task_active(read_u8, read_u32, tasks, 0x0808C39C) is True
    mem[slot] = 0x0806E811                  # an allowed overworld task is not the PC menu
    assert probe.task_active(read_u8, read_u32, tasks, 0x0808C39C) is False
    # The witness closures route through these helpers only; safety is never consulted.
    assert "P.task_active(memory.read_u8, memory.read_u32_le, tasks, P.TASK_PC_MAIN_MENU)" in SOURCE
    assert "local function running() return P.script_active(memory.read_u8) end" in SOURCE
    start = SOURCE.index("function P.script_active")
    helpers = SOURCE[start:SOURCE.index("function P.planned")]
    assert "safety" not in helpers and "check(" not in helpers
    assert "begin(8, pc_up)" in SOURCE and "begin(9, running)" in SOURCE
    assert "p.address == P.SCRIPT_STATUS" in SOURCE  # pack must agree with the sym address
