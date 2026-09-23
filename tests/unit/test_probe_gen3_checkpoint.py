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
    row = lua.table_from({"expectation": expectation, "samples": samples, "yes": yes, "reached": reached,
                          "non_irq_samples": samples, "non_irq_yes": yes,
                          "error": error, "expect_clauses": lua.table_from({"in_battle": True})})
    assert probe.verdict(row)[0] is want


def run_row(lua, probe, spec_name, refusals, reached=True):
    """Build a row from the real spec and tally one safety refusal per clause list."""
    spec = next(r for r in probe.STATES.values() if r.name == spec_name)
    row = lua.table_from({"expectation": spec.expectation, "expect_clauses": spec.expect_clauses,
                          "min_samples": spec.min_samples, "samples": 0, "yes": 0, "no": 0,
                          "reached": reached})
    for clauses in refusals:
        probe.tally(row, False, "first", lua.table_from(clauses))
    return row


def test_verdict_fails_on_refusal_by_unexpected_clause(module):
    lua, probe = module
    row = run_row(lua, probe, "script_running", [["script_context_status"]] * 60 + [["cpu"]])
    ok, why = probe.verdict(row)
    assert ok is False and "1 refusals without an expected clause" in why and "refused by cpu" in why
    # The FR 2026-09-22b shape: script_running refused by an unrelated predicate alone.
    row = run_row(lua, probe, "script_running", [["wireless_comm_type"]] * 123)
    assert probe.verdict(row)[0] is False
    assert probe.clause_counts(row) == "wireless_comm_type:123"


def test_positive_excludes_irq_from_rate_but_records_raw_counts(module):
    lua, probe = module
    row = lua.table_from({"expectation": "positive", "samples": 0, "yes": 0, "no": 0,
                          "irq": 0, "non_irq_samples": 0, "non_irq_yes": 0,
                          "reached": True})
    for _ in range(260):
        probe.tally(row, True, "ok", None, 0x1F)
    for _ in range(40):
        probe.tally(row, False, "IRQ mode refused", lua.table_from(["cpu"]), 0x12)
    assert row.samples == 300 and row.yes == 260 and row.no == 40
    assert row.irq == 40 and row.non_irq_samples == 260 and row.non_irq_yes == 260
    assert row.yes / row.samples < 0.90 <= row.non_irq_yes / row.non_irq_samples
    assert tuple(probe.verdict(row)) == (True, "positive rate")


def test_positive_still_fails_when_non_irq_rate_is_below_bar(module):
    lua, probe = module
    row = lua.table_from({"expectation": "positive", "samples": 0, "yes": 0, "no": 0,
                          "irq": 0, "non_irq_samples": 0, "non_irq_yes": 0,
                          "reached": True})
    for _ in range(267):
        probe.tally(row, True, "ok", None, 0x1F)
    for _ in range(33):
        probe.tally(row, False, "other refusal", lua.table_from(["task"]), 0x1F)
    for _ in range(15):
        probe.tally(row, False, "IRQ refused", lua.table_from(["cpu"]), 0x12)
    assert row.samples == 315 and row.irq == 15
    assert row.non_irq_samples == 300 and row.non_irq_yes == 267
    assert probe.verdict(row)[0] is False


def test_positive_with_only_irq_samples_fails_and_negative_still_counts_irq(module):
    lua, probe = module
    pos = lua.table_from({"expectation": "positive", "samples": 0, "yes": 0, "no": 0,
                          "irq": 0, "non_irq_samples": 0, "non_irq_yes": 0,
                          "reached": True})
    for _ in range(300):
        probe.tally(pos, False, "IRQ", lua.table_from(["cpu"]), 0x12)
    assert probe.verdict(pos)[0] is False

    neg = run_row(lua, probe, "battle", [])
    probe.tally(neg, True, "wrongly accepted", None, 0x12)
    assert neg.samples == 1 and neg.irq == 1
    assert probe.verdict(neg)[0] is False


def test_positive_row_needs_a_non_irq_denominator_floor(module):
    """C3-35: a 90% rate over five frames is not evidence.

    A positive row's raw count can be large while its non-IRQ denominator is tiny -- safety
    refuses CPSR mode 0x12 by design, so 300 witnessed frames may leave a handful of usable
    ones. Five accepted non-IRQ frames of 300 raw samples is a 100% "rate" and must FAIL.
    """
    lua, probe = module
    row = lua.table_from({"expectation": "positive", "samples": 0, "yes": 0, "no": 0,
                          "irq": 0, "non_irq_samples": 0, "non_irq_yes": 0, "reached": True})
    for _ in range(5):
        probe.tally(row, True, "ok", None, 0x1F)
    for _ in range(295):
        probe.tally(row, False, "IRQ mode refused", lua.table_from(["cpu"]), 0x12)
    assert (row.samples, row.irq, row.non_irq_samples, row.non_irq_yes) == (300, 295, 5, 5)
    assert row.non_irq_yes / row.non_irq_samples >= 0.90      # the rate alone would certify it
    ok, why = probe.verdict(row)
    assert ok is False and "non-IRQ samples 5 < floor 30" in why


def test_positive_floor_is_min_samples_or_the_probe_floor(module):
    """The floor is the row's own min_samples when that is larger, and never below the probe
    floor. (idle is the only positive row today and carries no min_samples.)"""
    lua, probe = module
    assert probe.POSITIVE_MIN_NON_IRQ == 30
    for min_samples, want in ((None, 30), (1, 30), (29, 30), (30, 30), (60, 60), (120, 120)):
        row = lua.table_from({"min_samples": min_samples})
        assert probe.non_irq_floor(row) == want, min_samples
    row = lua.table_from({"expectation": "positive", "min_samples": 60, "samples": 60,
                          "non_irq_samples": 44, "non_irq_yes": 44, "reached": True})
    ok, why = probe.verdict(row)
    assert ok is False and "non-IRQ samples 44 < floor 60" in why


def test_negative_rows_are_unaffected_by_the_positive_floor(module):
    """A negative row's evidence is its attributable refusals, not a rate: it may carry zero
    non-IRQ samples and still pass on its expected clause."""
    lua, probe = module
    row = run_row(lua, probe, "pc_menu", [])
    for _ in range(122):
        probe.tally(row, False, "IRQ mode refused", lua.table_from(["task"]), 0x12)
    assert (row.samples, row.irq) == (122, 122)
    assert not row.non_irq_samples           # never set: every witnessed frame was IRQ mode
    assert tuple(probe.verdict(row)) == (True, "-")


def test_the_physical_receipt_shapes_still_pass(module):
    """docs/gen3/probes/checkpoint_fr_clean_2026-09-23_nonirq.txt: idle 276 non-IRQ of 300 (all
    276 accepted), walking 109 of 120. The floor must not turn either row into a failure."""
    lua, probe = module
    idle = run_row(lua, probe, "idle", [])
    for _ in range(276):
        probe.tally(idle, True, "ok", None, 0x1F)
    for _ in range(24):
        probe.tally(idle, False, "CPU outside parked checkpoint", lua.table_from(["cpu"]), 0x12)
    assert (idle.samples, idle.irq, idle.non_irq_samples, idle.non_irq_yes) == (300, 24, 276, 276)
    assert tuple(probe.verdict(idle)) == (True, "positive rate")

    walking = run_row(lua, probe, "walking", [])
    for _ in range(109):
        probe.tally(walking, True, "ok", None, 0x1F)
    for _ in range(11):
        probe.tally(walking, False, "CPU outside parked checkpoint", lua.table_from(["cpu"]), 0x12)
    assert (walking.samples, walking.non_irq_samples) == (120, 109)
    assert tuple(probe.verdict(walking)) == (True, "-")


def test_receipt_prints_the_positive_floor():
    """The floor is derived from min_samples, so the receipt line states it rather than leaving a
    reader to re-derive it (the irq/non_irq counts stay where C3-32 put them)."""
    assert "irq=%d non_irq_sampled=%d non_irq_true=%d%s terminal=%s" in SOURCE
    assert 'string.format(" floor=%d", P.non_irq_floor(row))' in SOURCE


def test_verdict_passes_when_expected_clause_is_among_several(module):
    lua, probe = module
    row = run_row(lua, probe, "pc_menu", [["script_context_status", "task"]] * 122)
    assert tuple(probe.verdict(row)) == (True, "-")
    assert probe.clause_counts(row) == "script_context_status:122,task:122"
    # script_context_status alone is NOT the pc_menu clause (the RR 22b receipt's reported reason).
    row = run_row(lua, probe, "pc_menu", [["script_context_status"]] * 122)
    assert probe.verdict(row)[0] is False


def test_every_negative_row_declares_expect_clauses(module):
    lua, probe = module
    want = {"start_menu": {"field_controls_locked"},
            "dialog": {"save_dialog_cb", "field_controls_locked"},
            "save": {"save_dialog_cb", "field_controls_locked"},
            "battle": {"in_battle", "callback1", "callback2"},
            "fade": {"palette_fade_active"},
            "pc_menu": {"task"},
            "script_running": {"script_context_status"}}
    got = {r.name: set(r.expect_clauses.keys()) for r in probe.STATES.values() if r.expectation == "negative"}
    assert got == want
    row = lua.table_from({"expectation": "negative", "samples": 5, "yes": 0, "reached": True})
    assert probe.verdict(row)[0] is False  # a negative row without expect_clauses cannot pass


def test_min_samples_from_spec(module):
    lua, probe = module
    rows = {r.name: r for r in probe.STATES.values()}
    assert rows["pc_menu"].min_samples == 60 and rows["script_running"].min_samples == 60
    row = run_row(lua, probe, "script_running", [["script_context_status"]] * 59)
    ok, why = probe.verdict(row)
    assert ok is False and "59 < min_samples 60" in why
    probe.tally(row, False, "first", lua.table_from(["script_context_status"]))
    assert probe.verdict(row)[0] is True
    assert "row.samples >= 60" not in SOURCE  # the hold lives only in the spec


def test_real_safety_names_every_failing_clause_sorted():
    from tests.unit.test_gen3_safety import World
    w = World("radical_red", "companion")
    for name in ("script_context_status", "field_controls_locked"):
        p = w.pack["predicates"][name]
        w.lua.globals().put(p["address"] + p["offset"], p.get("mask", p["expect"] ^ 1), p["width"])
    w.lua.globals().idle = False
    ok, reason = w.safety.check(w.safety, None)  # arity unchanged: writes.lua unpacks two
    assert ok is False and reason
    assert list(w.safety.last_clauses.values()) == ["field_controls_locked", "native", "script_context_status"]
    w.lua.globals().rom[w.pack["anchors"]["frame_control"]["rom_offset"]] ^= 1
    assert w.safety.check(w.safety, None)[0] is False
    assert list(w.safety.last_clauses.values()) == ["pack"]
    idle = World()
    assert idle.check() and len(idle.safety.last_clauses) == 0


def sym(path, name):
    for line in (ROOT / "data/gen3/pret" / path).read_text().splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[3] == name:
            return int(parts[0], 16)
    raise KeyError(name)


def test_witness_addresses_derived_from_sym(module):
    _, probe = module
    assert sym("pokefirered.sym", "Task_PCMainMenu") == probe.TASK_PC_MAIN_MENU
    assert sym("pokefirered.sym", "sGlobalScriptContextStatus") == probe.SCRIPT_STATUS
    # LeafGreen's Task_PCMainMenu differs, so the pc_menu row must not admit leafgreen.
    assert sym("pokeleafgreen.sym", "Task_PCMainMenu") != probe.TASK_PC_MAIN_MENU
    pc_menu = next(r for r in probe.STATES.values() if r.name == "pc_menu")
    assert not any(k.startswith("leafgreen/") for k in pc_menu.artifacts)


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
    assert "WRITE_SURFACE none (predicate-only probe)" in SOURCE and "WRITE_LOG" not in SOURCE
    assert "P.tally(active, ok, reason, safety.last_clauses, regs.CPSR)" in SOURCE
    assert "irq=%d non_irq_sampled=%d non_irq_true=%d" in SOURCE
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
