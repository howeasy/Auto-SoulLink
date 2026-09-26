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
    "dialog": "start_menu_save_callback_under_live_task",
    "save": "new_counter_partial_slot_then_14_sectors",
    "battle": "in_battle_mask_nonzero",
    "fade": "palette_fade_active_then_map_changed",
    "pc_menu": "task_pc_main_menu_active_60",
    "script_running": "script_context_not_shutdown_60",
}
# C4-B2 reason rows (battle/battle_commit/native/sound), P.STATES indices 10..22.
REASON_TERMINALS = {
    "battle_input_wild": "battle_main_func==HandleTurnActionSelectionState and "
        "gBattleCommunication[0]==1",
    "battle_input_trainer": "battle_main_func==HandleTurnActionSelectionState and "
        "gBattleCommunication[0]==1",
    "battle_move_menu": "gBattleCommunication[0]==2",
    "battle_animation":
        "gBattleControllerExecFlags~=0 and gBattlerControllerFuncs[0]~=HandleInputChooseAction",
    "battle_faint_prompt": "gBattleMainFunc ~= HandleTurnActionSelectionState",
    "battle_intro": "gBattleMainFunc ~= HandleTurnActionSelectionState",
    "battle_link": "gBattleTypeFlags & 2",
    "battle_over": "gBattleOutcome~=0",
    "battle_commit_state3": "gBattleCommunication[0]>=3",
    "native_idle_field": "companion beacon present and mailbox idle",
    "native_idle_battle": "companion beacon present and mailbox idle in battle",
    "native_absent": "no native block in this pack",
    "sound_driver": "m4a SE1 ident == ID_NUMBER",
    "battle_commit_held_rr": "battle_main_func==HandleTurnActionSelectionState and "
        "gBattleCommunication[0]==1 and BATTLE_TYPE_TRAINER",
    # E2-CKPT: Emerald-only rows, appended after battle_commit_held_rr (indices 33..36)
    "center_idle": "center_1f_idle_300",
    "map_popup": "Task_MapNamePopUpWindow_live_field_settled",
    "battle_intro_field": "in_battle_mask_nonzero",
    "trainer_battle_field": "in_battle_mask_nonzero",
}
# 2B-INTEGRATE-PROBE: the G4 2b battle-window rows, P.STATES indices 23..31, in run order
# (N8 last: its bag helper can end the whole run). name -> gen3_battle_window_rows row.
BW_ROWS = {"bw_n1_action_draw": "N1", "bw_n4_bag": "N4", "bw_n5_party": "N5", "bw_n6_summary": "N6",
           "bw_n7_switch": "N7", "bw_n9_run": "N9", "bw_u1_oldman": "U1", "bw_u2_pokedude": "U2",
           "bw_n8_item": "N8"}
BW_INDICES = set(range(23, 32))
CORE = set(range(1, 8))
# Reason-row P.STATES indices (10..22, REASON_BASE = 22 - 13 + 1), by name -- planned() per
# artifact (docs/gen3/research/battle_write_predicate.md §6): the battle_animation row is
# FR/LG-only, native_busy is model-only (no probe row), the rest gate on `artifacts`.
BATTLE_INPUT_WILD, BATTLE_INPUT_TRAINER, BATTLE_MOVE_MENU = 10, 11, 12
BATTLE_ANIMATION, BATTLE_FAINT_PROMPT, BATTLE_INTRO = 13, 14, 15
BATTLE_LINK, BATTLE_OVER, BATTLE_COMMIT_STATE3 = 16, 17, 18
NATIVE_IDLE_FIELD, NATIVE_IDLE_BATTLE, NATIVE_ABSENT, SOUND_DRIVER = 19, 20, 21, 22
# planned() reason-row selection per artifact (OMP C4-B2 report: 11/10/3/7 rows).
FIRERED_CLEAN_REASON_ROWS = {BATTLE_INPUT_WILD, BATTLE_INPUT_TRAINER, BATTLE_MOVE_MENU,
    BATTLE_ANIMATION, BATTLE_FAINT_PROMPT, BATTLE_INTRO, BATTLE_LINK, BATTLE_OVER,
    BATTLE_COMMIT_STATE3, NATIVE_ABSENT, SOUND_DRIVER}
LEAFGREEN_CLEAN_REASON_ROWS = {BATTLE_INPUT_WILD, BATTLE_INPUT_TRAINER, BATTLE_MOVE_MENU,
    BATTLE_ANIMATION, BATTLE_FAINT_PROMPT, BATTLE_INTRO, BATTLE_LINK, BATTLE_OVER,
    BATTLE_COMMIT_STATE3, NATIVE_ABSENT, SOUND_DRIVER}
RADICAL_RED_CLEAN_REASON_ROWS = {BATTLE_INPUT_WILD, NATIVE_ABSENT, SOUND_DRIVER}
BATTLE_COMMIT_HELD_RR = 32   # a1bbc686: appended after the bw rows (23..31), RR companion only
RADICAL_RED_COMPANION_REASON_ROWS = {BATTLE_INPUT_WILD, BATTLE_MOVE_MENU,
    BATTLE_OVER, BATTLE_COMMIT_STATE3, NATIVE_IDLE_FIELD, NATIVE_IDLE_BATTLE, BATTLE_COMMIT_HELD_RR}
assert len(FIRERED_CLEAN_REASON_ROWS) == 11
assert len(LEAFGREEN_CLEAN_REASON_ROWS) == 11
assert len(RADICAL_RED_CLEAN_REASON_ROWS) == 3
assert len(RADICAL_RED_COMPANION_REASON_ROWS) == 7


@pytest.fixture
def module():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    # Executing the definition chunk also compiles it, without entering main.
    return lua, lua.execute(SOURCE)


def test_all_states_have_named_terminals(module):
    _, probe = module
    states = {row.name: row.terminal for row in probe.STATES.values() if row.bw is None}
    assert states == {**TERMINALS, **REASON_TERMINALS}
    assert [r.name for r in probe.STATES.values() if r.bw is not None] == list(BW_ROWS)
    for name, terminal in TERMINALS.items():
        assert f'name="{name}", terminal="{terminal}"' in SOURCE
    # Reason-row terminals are built with `..` string concatenation across lines in the source
    # (the multi-line ones), so only the name literal -- not the full concatenated terminal --
    # is checked against SOURCE; the terminal TEXT itself is checked against the parsed table.
    for name in REASON_TERMINALS:
        assert f'name="{name}"' in SOURCE
    for row in probe.STATES.values():
        assert row.terminal and row.terminal.strip(), row.name


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
            "dialog": {"task", "field_controls_locked"},   # C4-SAVE: not the stale pointer
            "save": {"task", "field_controls_locked"},
            "battle": {"in_battle", "callback1", "callback2"},
            "fade": {"palette_fade_active"},
            "pc_menu": {"task"},
            "script_running": {"script_context_status"},
            # C4-B2 reason rows (docs/gen3/research/battle_write_predicate.md §6):
            "battle_move_menu": {"battle_comm_0"},
            "battle_animation": {"battle_exec_flags_input", "battle_input_controller", "battle_main_func"},
            "battle_faint_prompt": {"battle_main_func", "battle_exec_flags_input", "battle_input_controller"},
            "battle_intro": {"battle_main_func", "battle_exec_flags_input", "battle_input_controller"},
            "battle_link": {"battle_not_link"},
            "battle_over": {"battle_outcome_open", "battle_engine_loaded"},
            "battle_commit_state3": {"battle_commit_guard"},
            "native_absent": {"native_present"},
            "battle_commit_held_rr": {"battle_commit_hold"},
            # E2-CKPT: Emerald battles under the overworld reason
            "battle_intro_field": {"in_battle", "callback1", "callback2"},
            "trainer_battle_field": {"in_battle", "callback1", "callback2"}}
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
    emulator = lua.eval("""{getregister=function(n)
            if n == 'R15' then return 452 elseif n == 'R14' then return 0x1C4 end
            return -2147483617
        end, framecount=function() return 73 end}""")
    deps = probe.build_deps(mem, emulator, lua.eval("function() return true end"))
    assert deps.io.read_u8(5, "ROM") == 5
    assert deps.io.read_u16_le(5, "System Bus") == 6
    assert deps.io.read_u32_le(5, "System Bus") == 7
    assert deps.regs().R15 == 452
    assert deps.regs().CPSR == -2147483617  # probe must not hide core register behavior
    # G5-CPU-HARDEN: R14 (the current mode's bank, R14_irq at an IRQ entry) reaches safety.lua's
    # irq_entry clause, as lua/gen3/entry.lua forwards it
    assert deps.regs().R14 == 0x1C4
    assert deps.frame() == 73 and deps.native_idle()
    assert all(not key.startswith("write") for key in deps.io)


def test_gatelib_safety_regs_forward_r14():
    """G5-CPU-HARDEN: the gate harness's safety facade forwards R14 like lua/gen3/entry.lua."""
    gatelib = (ROOT / "lua/tests/gen3_gatelib.lua").read_text(encoding="utf-8")
    assert 'R14 = emu.getregister("R14")' in gatelib


def test_real_safety_frame_end_sampling_and_save_witness_are_wired():
    assert 'dofile(wt .. "/lua/gen3/safety.lua")' in SOURCE
    assert "S.new(cp, deps, kind)" in SOURCE
    assert "event.onframeend(function()" in SOURCE
    # C4-B2: the reason runner passes the row's reason/args through; core rows carry neither, so
    # this is a byte-identical `safety:check(nil, nil, nil)` for them.
    assert "safety:check(nil, active.write_reason, active.args)" in SOURCE
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
    assert set(rows["script_running"].artifacts.keys()) == {
        "firered/clean", "leafgreen/clean", "radical_red/companion", "emerald/clean"}
    assert all(rows[n].artifacts is None for n in TERMINALS if n not in ("pc_menu", "script_running"))


@pytest.mark.parametrize("title,kind,env,want", [
    ("firered", "clean", None, CORE | {9} | FIRERED_CLEAN_REASON_ROWS | BW_INDICES),
    ("radical_red", "companion", None, CORE | {8, 9} | RADICAL_RED_COMPANION_REASON_ROWS),
    ("radical_red", "clean", None, CORE | RADICAL_RED_CLEAN_REASON_ROWS),
    ("leafgreen", "clean", None, CORE | {9} | LEAFGREEN_CLEAN_REASON_ROWS | BW_INDICES),
    ("radical_red", "companion", "script_running", CORE | {9}),
    ("radical_red", "companion", "pc_menu, script_running", CORE | {8, 9}),
    ("radical_red", "companion", "none", CORE),
    ("firered", "clean", "", CORE | {9} | FIRERED_CLEAN_REASON_ROWS | BW_INDICES),
    ("leafgreen", "clean", "bw_u2_pokedude, bw_n9_run", CORE | {28, 30}),
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
    ("radical_red", "companion", "bw_n9_run"),   # the 2b rows are FR/LG only
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



# ── C4-6t (Codex cx-3e10776a): the dialog row's witness after an earlier save ─────────────────
def test_the_dialog_row_uses_the_shared_start_menu_witness(module):
    lua, probe = module
    ready = lua.eval("function() return 'ready' end")
    running = lua.eval("function() return 'running' end")
    G = lua.table(start_menu_witness=lua.eval("function(r, s) return function(t) return r, s end end")(ready, running))
    arm, opened = probe.dialog_witness(G, lua.table(), "firered")
    assert arm() == "ready" and opened() == "running"
    assert 'begin(4,function() return dialog_open() end)' in SOURCE
    assert 'not G.pred_ok(cp,"save_dialog_cb")' not in SOURCE


def test_the_rr_fallback_needs_the_pointer_to_move_after_the_press(module):
    lua, probe = module
    lua.execute("CB = 0x0806F9E1")                     # stale: an earlier save's ReturnSuccess
    G = lua.eval("""{ start_menu_witness = function() return nil end,
                      pred = function(_, name) return CB, 0 end }""")
    arm, opened = probe.dialog_witness(G, lua.table(), "radical_red")
    assert opened() is False                           # never armed: nothing to compare against
    arm()
    assert opened() is False                           # stale non-zero alone is NOT a dialog
    lua.execute("CB = 0x0806F7A1")
    assert opened() is True


# ── C4-PROBE2: LG script_running + the send-out prompt witness ────────────────────────────────
def _sym(name, sym):
    import re
    text = (ROOT / "data/gen3/pret" / sym).read_text(encoding="utf-8")
    return int(re.search(rf"^([0-9a-f]{{8}}) \S+ \S+ {name}$", text, re.M).group(1), 16)


@pytest.mark.parametrize("sym", ["pokefirered.sym", "pokeleafgreen.sym"])
def test_send_out_prompt_is_wait_for_mon_selection_on_both_titles(module, sym):
    _, probe = module
    assert _sym("WaitForMonSelection", sym) | 1 == probe.WAIT_FOR_MON_SELECTION
    faint = next(r for r in probe.STATES.values() if r.name == "battle_faint_prompt")
    assert faint.until_witness == "send_out_prompt"
    assert set(faint.artifacts.keys()) == {"firered/clean", "leafgreen/clean"}
    assert "send_out_prompt = function() return w32(ctrl_a) == P.WAIT_FOR_MON_SELECTION end" in SOURCE
    # the row is only reached when the prompt was: a mash that stops short fails by name
    assert "row.reached = held > 0 and arrived" in SOURCE
    assert 'row.reason = spec.until_witness .. " never reached"' in SOURCE


def test_frlg_script_row_uses_the_built_state_at_the_woman_tile(module):
    _, probe = module
    assert list(probe.SCRIPT_TILE.values()) == [20, 13]
    assert '"slink_script.State"' in SOURCE and "slink_fr_parcel_deliver" not in SOURCE
    assert "walk({}, P.SCRIPT_TILE[1], P.SCRIPT_TILE[2])" in SOURCE


# ── C4-PROBE2 review (A-1 + low a): trainer witness, state loading, witness names ─────────────
import json  # noqa: E402

FRLG_PACK = json.loads((ROOT / "data/games/gen3_frlg/write_checkpoint.json").read_text(encoding="utf-8"))


def parked_menu(pack, type_flags):
    """Fake RAM for a parked action menu; r8 and r32 read the same address->value map."""
    cl = {c["name"]: c for c in pack["battle"]["clauses"]}

    def addr(n):
        return cl[n]["address"] + cl[n].get("offset", 0)
    return {addr("battle_main_func"): cl["battle_main_func"]["expect"], addr("battle_comm_0"): cl["battle_comm_0"]["expect"],
            addr("battle_not_link"): type_flags}


def witness_table(lua, probe, pack, mem):
    def read(a):
        return mem.get(a, 0)
    return probe.witnesses(lua.table_from(pack, recursive=True), read, read)


def run_reason_row(lua, probe, WIT, name, frames=180):
    """The runner's hold loop: one tally per frame the row's witness holds (ok = the permit)."""
    spec = next(r for r in probe.STATES.values() if r.name == name)
    witness, _ = probe.row_witness(WIT, spec)
    row = lua.table_from({"expectation": spec.expectation, "expect_clauses": spec.expect_clauses,
                          "min_samples": spec.min_samples, "samples": 0, "yes": 0, "no": 0,
                          "irq": 0, "non_irq_samples": 0, "non_irq_yes": 0})
    held = 0
    for _ in range(frames):
        if witness():
            held += 1
            probe.tally(row, True, "ok", None, 0x1F)
    row.reached = held > 0
    return row


EMERALD_PACK = json.loads((ROOT / "data/games/gen3_emerald/write_checkpoint.json").read_text(encoding="utf-8"))["emerald"]


def test_emerald_battle_witnesses_follow_the_pack_comm_numbering(module):
    """E2 F-B: Emerald parks the action menu at gBattleCommunication[0] == 2, not FR's 1."""
    lua, probe = module
    comm = next(c for c in EMERALD_PACK["battle"]["clauses"] if c["name"] == "battle_comm_0")
    assert comm["expect"] == 2
    mem = parked_menu(EMERALD_PACK, 0xC)
    W = witness_table(lua, probe, EMERALD_PACK, mem)
    assert W.battle_input() is True and W.battle_input_trainer() is True

    def holds(name, value):
        mem[comm["address"] + comm.get("offset", 0)] = value
        spec = next(r for r in probe.STATES.values() if r.name == name)
        return probe.row_witness(W, spec)[0]()
    assert holds("battle_input_wild", 1) is False       # FR's number is not Emerald's menu
    assert holds("battle_move_menu", 3) is True and holds("battle_move_menu", 2) is False
    assert holds("battle_commit_state3", 4) is True and holds("battle_commit_state3", 3) is False


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_a1_trainer_row_fails_on_a_wild_parked_menu(module, title):
    lua, probe = module
    pack = FRLG_PACK[title]
    wild = witness_table(lua, probe, pack, parked_menu(pack, 0x4))
    assert wild.battle_input() is True and wild.battle_input_trainer() is False
    ok, why = probe.verdict(run_reason_row(lua, probe, wild, "battle_input_trainer"))
    assert ok is False and why == "terminal not reached"
    # positive control: the recorded trainer tuple (type=0000000C, c4probe2 receipt) passes
    trainer = witness_table(lua, probe, pack, parked_menu(pack, 0xC))
    assert trainer.battle_input_trainer() is True
    assert tuple(probe.verdict(run_reason_row(lua, probe, trainer, "battle_input_trainer"))) == (True, "positive rate")
    # the wild row keeps the plain parked witness
    wild_row = next(r for r in probe.STATES.values() if r.name == "battle_input_wild")
    assert wild_row.witness == "battle_input" and probe.BATTLE_TYPE_TRAINER == 8


def test_a1_missing_or_refused_state_never_loads(module, tmp_path):
    lua, probe = module
    io_open = lua.eval("io.open")
    calls = []

    def load_fn(path):
        calls.append(path)
        return True
    missing = (tmp_path / "slink_pretrainer.State").as_posix()
    ok, why = probe.load_state(missing, load_fn, io_open)
    assert ok is False and why == "state missing: " + missing and calls == []
    present = tmp_path / "slink_prebattle.State"
    present.write_bytes(b"x")
    ok, why = probe.load_state(present.as_posix(), lambda p: False, io_open)
    assert ok is False and why.startswith("savestate.load refused (returned false): ")
    assert probe.load_state(present.as_posix(), load_fn, io_open) is True and len(calls) == 1
    assert probe.state_path("slink_x.State", "D:/s") == "D:/s/slink_x.State"
    assert probe.state_path("C:/a/slink_x.State", "D:/s") == "C:/a/slink_x.State"


def test_a1_a_blocked_row_fails_by_name_whatever_it_counted(module):
    lua, probe = module
    pack = FRLG_PACK["firered"]
    row = run_reason_row(lua, probe, witness_table(lua, probe, pack, parked_menu(pack, 0xC)),
                         "battle_input_trainer")
    assert probe.verdict(row)[0] is True
    row.blocked = "UNREACHED state missing: X/slink_pretrainer.State"
    assert tuple(probe.verdict(row)) == (False, "UNREACHED state missing: X/slink_pretrainer.State")
    # the runner: the core phases assert the load, a reason row is blocked by name
    assert SOURCE.count("must_load(") == 9 and "assert(load(" not in SOURCE   # def + 8 core sites
    assert 'row.blocked, row.reason = "UNREACHED " .. why, why' in SOURCE
    assert "savestate.load(name)" not in SOURCE


def test_low_a_unknown_witness_names_are_errors(module):
    lua, probe = module
    WIT = witness_table(lua, probe, FRLG_PACK["firered"], {})
    for spec in probe.STATES.values():
        if spec.witness is not None:
            probe.row_witness(WIT, spec)          # every declared name resolves
    with pytest.raises(lupa.LuaError, match="unknown witness bogus"):
        probe.row_witness(WIT, lua.table_from({"name": "x", "witness": "bogus"}))
    with pytest.raises(lupa.LuaError, match="unknown until_witness send_out_promt"):
        probe.row_witness(WIT, lua.table_from({"name": "x", "witness": "always",
                                               "until_witness": "send_out_promt"}))
    w, stop = probe.row_witness(WIT, lua.table_from({"name": "x", "witness": "always"}))
    assert w() is True and stop() is True


# ── 2B-INTEGRATE-PROBE: the G4 2b battle-window rows ─────────────────────────────────────────
from tests.unit.test_gen3_battle_window_rows import HASHES, World, committed, parked  # noqa: E402

RR_ROWS = lupa.LuaRuntime(unpack_returned_tuples=True).execute(
    (ROOT / "lua/tests/gen3_battle_window_rows.lua").read_text(encoding="utf-8"))


def bw_specs(probe):
    return {r.name: r for r in probe.STATES.values() if r.bw is not None}


def test_bw_rows_are_the_matrix_rows_not_duplicates(module):
    _, probe = module
    specs = bw_specs(probe)
    assert {n: s.bw for n, s in specs.items()} == BW_ROWS
    obs = {r.name for r in RR_ROWS.ROWS.values()}
    for name, spec in specs.items():
        assert spec.bw in obs, name
        assert spec.expectation == "bw" and spec.reason == "battle_faint", name
        assert set(spec.artifacts.keys()) == {"firered/clean", "leafgreen/clean"}, name
        assert spec.state_env and spec.state, name
        assert probe.check_inputs(spec) is True
    # N3 needs a doubles fixture (recorded limit); N2/N10-N13 are existing rows, cross-referenced
    assert "N3" not in set(BW_ROWS.values())
    notes = " ".join(s.note for s in specs.values())
    for existing in ("battle_move_menu (N2)", "battle_intro (N10)", "battle_faint_prompt (N11)",
                     "battle_animation (N12)", "battle_over (N13)"):
        assert existing in notes
    # the tutorial rows default to the 2B-TUTORIAL-STATES names under their own env
    assert (specs["bw_u1_oldman"].state_env, specs["bw_u1_oldman"].state) == (
        "SLINK_CHECKPOINT_OLDMAN_STATE", "slink_oldman.State")
    assert (specs["bw_u2_pokedude"].state_env, specs["bw_u2_pokedude"].state) == (
        "SLINK_CHECKPOINT_POKEDUDE_STATE", "slink_pokedude.State")
    # N1 samples from the intro state (before the draw frame); N7/N8/N9 load the parked menu,
    # and their committing A is pressed with the row already sampling
    assert specs["bw_n1_action_draw"].state == "slink_preintro.State"
    assert probe.WAIT_FOR_MON_SELECTION == 0x08030685


def test_u2_presses_no_b_at_all(module):
    lua, probe = module
    u2 = bw_specs(probe)["bw_u2_pokedude"]
    assert u2.forbid_b is True and len(u2.inputs) == 0
    for step in ({"tap": "B"}, {"pulse": "B", "frames": 10, "stop": "turn_over"}):
        bad = lua.table_from({"name": "u2", "bw": "U2", "forbid_b": True,
                              "inputs": lua.table_from([lua.table_from(step)])})
        with pytest.raises(lupa.LuaError, match="B is forbidden"):
            probe.check_inputs(bad)
    assert 'assert(btn ~= "B" or not (bw_last and' in SOURCE        # the runtime guard too


@pytest.mark.parametrize("step,msg", [
    ({"hop": 1}, "unknown input step"),
    ({"tap": "A", "idle": 3}, "several step kinds"),
    ({"wait": "bag_opne"}, "unknown wait bag_opne"),
    ({"pulse": "B", "frames": 9}, "a pulse needs a stop"),
])
def test_check_inputs_rejects_malformed_steps(module, step, msg):
    lua, probe = module
    spec = lua.table_from({"name": "x", "bw": "N4", "inputs": lua.table_from([lua.table_from(step)])})
    with pytest.raises(lupa.LuaError, match=msg):
        probe.check_inputs(spec)
    plain = lua.table_from({"name": "x", "inputs": lua.table_from([lua.table_from({"action": 1})])})
    with pytest.raises(lupa.LuaError, match="battle-window step"):
        probe.check_inputs(plain)


def test_a_bw_row_wired_without_its_sampler_never_passes(module):
    lua, probe = module
    row = lua.table_from({"name": "bw_n9_run", "expectation": "bw", "samples": 0, "yes": 0, "no": 0,
                          "reached": True})
    assert tuple(probe.verdict(row)) == (False, "battle-window row has no sampler")


def bw_world(title):
    w = World(title)
    return w, w.lua.execute(SOURCE)


def bw_row(w, name):
    return w.lua.table_from({"name": name, "expectation": "bw", "bw": w.R.row(w.ctx, name),
                             "samples": 0, "yes": 0, "no": 0})


def feed(w, probe, row, states):
    extra = w.lua.table_from({"map": "3.19", "pos": "12,37"})
    for st in states:
        w.set(**st)
        probe.bw_feed(row, w.safety, extra)


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_an_unreached_accumulator_fails_the_probe(title):
    w, probe = bw_world(title)
    row = bw_row(w, "N9")
    feed(w, probe, row, [parked(title)] * 120)          # sampled, but never the committed RUN
    assert row.bw.samples == 0
    assert tuple(probe.verdict(row)) == (False, "UNREACHED no qualifying sample")
    # positive control through the same path: RUN committed, then gBattleOutcome == RAN
    row = bw_row(w, "N9")
    ran = committed(title, ret=(0x21, 3, 0, 0))
    feed(w, probe, row, [parked(title)] * 5 + [ran] * 4 + [dict(ran, outcome=4)])
    assert tuple(probe.verdict(row)) == (True, "PASS -")
    # a committed window with no terminal (failed escape reopens the menu) is UNREACHED
    row = bw_row(w, "N9")
    feed(w, probe, row, [parked(title)] * 5 + [ran] * 4 + [parked(title)] * 5)
    ok, why = probe.verdict(row)
    assert ok is False and why.startswith("UNREACHED terminal never observed")


def test_a_fail_accumulator_fails_the_probe():
    w = World("firered", drop="battle_input_controller")
    probe = w.lua.execute(SOURCE)
    assert tuple(probe.verdict(bw_row(w, "N9"))) == (False, "FAIL pack lacks clause(s) P")


def test_a_missing_state_blocks_even_a_passing_bw_row():
    w, probe = bw_world("firered")
    row = bw_row(w, "N9")
    ran = committed("firered", ret=(0x21, 3, 0, 0))
    feed(w, probe, row, [parked("firered")] * 5 + [ran] * 4 + [dict(ran, outcome=4)])  # fresh arm (bdbf5736)
    assert probe.verdict(row)[0] is True
    row.blocked = "UNREACHED state missing: X/slink_pokedude.State"
    assert tuple(probe.verdict(row)) == (False, "UNREACHED state missing: X/slink_pokedude.State")
    assert 'row.blocked = "UNREACHED " .. why' in SOURCE and "if not meta then row.blocked = mwhy end" in SOURCE


def test_bw_meta_needs_all_five_hashes_and_makes_a_receipt():
    w, probe = bw_world("firered")
    L = w.lua
    doc = {"pack": "p0", "source": "s0",
           "states": {"slink_prebattle.State": {"state": "st0", "fixture": "f0", "prep": "mkstates battle"}}}
    path = "D:/states/slink_prebattle.State"
    meta = probe.bw_meta(L.table_from(doc, recursive=True), "r0", path, "N9")
    assert dict(meta.hashes) == HASHES and meta.prep == "mkstates battle" and meta.state_path == path
    line = w.ctx.receipt(w.ctx, w.sample(), meta)
    assert line.startswith("BWSAMPLE N9 title=firered") and "state_path=" + path in line
    assert probe.bw_meta(L.table_from(doc, recursive=True), None, path, "N9")[1] == \
        "receipt needs the rom hash for slink_prebattle.State"
    for key in ("fixture", "state"):
        inner = {k: v for k, v in doc["states"]["slink_prebattle.State"].items() if k != key}
        partial = {**doc, "states": {"slink_prebattle.State": inner}}
        assert probe.bw_meta(L.table_from(partial, recursive=True), "r0", path, "N9")[1] == \
            f"receipt needs the {key} hash for slink_prebattle.State"
    assert probe.bw_meta(None, "r0", path, "N9")[1] == "receipt needs the fixture hash for slink_prebattle.State"
    other = probe.bw_meta(L.table_from(doc, recursive=True), "r0", "D:/states/slink_oldman.State", "U1")
    assert other[0] is None                    # a state the hash file does not name


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_bw_waits_read_the_sample(title):
    w, probe = bw_world(title)
    W = probe.BW_WAITS
    w.set(**parked(title))
    s = w.sample()
    assert W.action_input(s, w.ctx) is True and W.turn_over(s, w.ctx) is True
    assert W.party_input(s, w.ctx) is False and W.bag_input(s, w.ctx) is False
    ran = committed(title, ret=(0x21, 3, 0, 0))
    w.set(**ran)
    s = w.sample()
    assert W.action_input(s, w.ctx) is False and W.turn_over(s, w.ctx) is False
    w.set(**dict(ran, outcome=4))
    assert W.turn_over(w.sample(), w.ctx) is True


def test_frame_end_feeds_bw_rows_under_the_callback_pcall():
    assert "bw_last = P.bw_feed(active, safety, extra)" in SOURCE
    assert "local success, why = pcall(sample)" in SOURCE
    assert 'dofile(wt .. "/lua/tests/gen3_battle_window_rows.lua").bind(cp, title, deps, wt)' in SOURCE
    assert "G.log(line)" in SOURCE
    assert 'G.log(bw_ctx:receipt(acc[k], meta, acc) .. " at=" .. k .. P.bw_diag("", acc[k]))' in SOURCE
    assert "memory.write" not in SOURCE


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_the_runner_glue_names_exist_on_the_bound_ctx(title):
    """bw_row/bw_steps call these through the bound ctx; a typo would only surface live."""
    w = World(title)
    ctx = w.ctx
    acc = ctx.row(ctx, "N9")
    line, status = ctx.verdict_line(acc)
    assert line.startswith("BWROW N9 UNREACHED") and status == "UNREACHED"
    assert ctx.K.BATTLE_TYPE_POKEDUDE == 0x10000 and ctx.T.ACTION_CURSOR_ADDR == 0x02023FF8
    for name in ("HANDLE_INPUT_CHOOSE_ACTION", "CB2_BAG_MENU_RUN", "TASK_BAG_MENU_HANDLE_INPUT",
                 "TASK_ANIMATE_WIN0V", "CB2_UPDATE_PARTY_MENU", "TASK_CHOOSE_MON", "TASK_SELECTION_POPUP"):
        assert ctx.T[name], name
    assert ctx.W.CB2_RUN_SUMMARY_SCREEN
    for name in ("bw_row(i, spec)", "row.bw, bw_last = bw_ctx:row(spec.bw), nil",
                 "local line, status = bw_ctx.verdict_line(acc)", "bw_ctx.K.BATTLE_TYPE_POKEDUDE",
                 "memory.read_u8(bw_ctx.T.ACTION_CURSOR_ADDR)", "SP.throw_pokeball_from_bag(cp, spec.name)"):
        assert name in SOURCE, name


# ── live 765beb48: bw_n7_switch UNREACHED on FR and LG (samples=0 windows=0) ────────────────
# ffceb394 opened the SHIFT popup with A (gap 0), waited for the popup (already up: zero frames)
# and pressed A again: one continuous A, so JOY_NEW fired once, SHIFT was never chosen, and the
# B pulse cancelled the popup and the menu (CHOSENMONRETURNVALUE with PARTY_SIZE: no arm).
FFCEB394_N7 = [{"wait": "action_input"}, {"action": 2}, {"tap": "A", "frames": 3, "gap": 0},
               {"wait": "party_input"}, {"slot": 1}, {"tap": "A", "frames": 3, "gap": 0},
               {"wait": "party_popup"}, {"tap": "A", "frames": 3, "gap": 0},
               {"pulse": "B", "frames": 3000, "stop": "turn_over"}]


def spec_of(lua, steps, **kw):
    return lua.table_from({"name": "n7", "bw": "N7", **kw,
                           "inputs": lua.table_from([lua.table_from(s) for s in steps])})


def test_n7_ffceb394_inputs_merge_two_presses_into_one(module):
    lua, probe = module
    with pytest.raises(lupa.LuaError, match="input 6: A pressed again with no released frame"):
        probe.check_inputs(spec_of(lua, FFCEB394_N7))     # party-open A .. SHIFT-popup A: timing-safe only
    live = [dict(s, gap=1) if i == 2 else s for i, s in enumerate(FFCEB394_N7)]
    with pytest.raises(lupa.LuaError, match="input 8: A pressed again with no released frame"):
        probe.check_inputs(spec_of(lua, live))            # popup A .. SHIFT A: the live failure
    # the same A-A pair is fine once a frame is released between them, by any releasing step
    for between in ({"idle": 1}, {"tap": "Down"}, {"mash": 10, "stop": "action_input"}):
        steps = [{"tap": "A", "gap": 0}, {"wait": "party_popup"}, between, {"tap": "A"}]
        assert probe.check_inputs(spec_of(lua, steps)) is True
    for zero in ({"wait": "party_popup"}, {"action": 2}, {"slot": 1}, {"idle": 0}):
        with pytest.raises(lupa.LuaError, match="no released frame"):
            probe.check_inputs(spec_of(lua, [{"tap": "A", "gap": 0}, zero, {"tap": "A"}]))


def test_every_bw_row_releases_between_presses(module):
    _, probe = module
    for spec in bw_specs(probe).values():
        assert probe.check_inputs(spec) is True, spec.name
        for step in spec.inputs.values():
            assert step.tap is None or step.gap != 0, (spec.name, step.tap)
    n7 = bw_specs(probe)["bw_n7_switch"]
    kinds = [next(k for k in ("wait", "action", "slot", "tap", "pulse") if s[k] is not None)
             for s in n7.inputs.values()]
    assert kinds == ["wait", "action", "tap", "wait", "slot", "tap", "wait", "tap", "pulse"]


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_n8_ball_count_comes_from_the_shared_reader_with_the_key(title):
    """bdbf5736: N8 needs extra.balls. The probe reads it with lua/gen3/reads.lua read_balls
    (SaveBlock1 +0x430, 13 slots, quantity ^ low16(SaveBlock2 +0xF20)) from this profile."""
    import json as _json
    prof = _json.loads((ROOT / "data/games/gen3_frlg/profile.json").read_text(encoding="utf-8"))["titles"][title]
    d = prof["derived"]
    assert (d["SB1_BALL_POCKET_OFFSET"], d["SB1_BALL_POCKET_COUNT"], d["SB2_ENC_KEY_OFFSET"]) == (0x430, 13, 0xF20)
    assert not d.get("BAG_IN_EWRAM") and d.get("BALL_POCKET_ENC") is not False
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    reads = lua.execute((ROOT / "lua/gen3/reads.lua").read_text(encoding="utf-8"))
    pack = FRLG_PACK[title]
    sb1, sb2, key = 0x02025000, 0x02024000, 0xBEEF1234
    mem = {pack["pointers"]["gSaveBlock1Ptr"]["address"]: sb1, pack["pointers"]["gSaveBlock2Ptr"]["address"]: sb2,
           sb2 + 0xF20: key, sb1 + 0x430: 4, sb1 + 0x432: 5 ^ 0x1234}
    rd = lambda a: mem.get(a, 0)  # noqa: E731
    io = lua.table_from({"read_u8": rd, "read_u16": rd, "read_u32": rd,
                         "read_bytes": lambda a, k: lua.table_from([0] * k)})
    r = reads.new(lua.table_from(prof, recursive=True), io, lua.table_from(pack["pointers"], recursive=True))
    assert r.read_balls().ball_count == 5
    assert "local balls = bag.read_balls()" in SOURCE and "extra.balls = balls and balls.ball_count" in SOURCE
    assert "if active.bw.spec.receipt_fields then" in SOURCE


# ── OMP review of 0c7fc5fb/920d46af/ffceb394 (B2, B5, B6, C1, A2, A3, A4) ──────────────────────
def finished_row(lua, probe, name, **fields):
    index = next(i for i, r in probe.STATES.items() if r.name == name)
    spec = probe.STATES[index]
    base = {"name": name, "terminal": spec.terminal, "expectation": spec.expectation,
            "expect_clauses": spec.expect_clauses, "min_samples": spec.min_samples, "samples": 0,
            "yes": 0, "no": 0, "irq": 0, "non_irq_samples": 0, "non_irq_yes": 0, "reached": True,
            "reason": "-", "index": index, "spent0": 1000}
    return index, lua.table_from({**base, **fields})


def test_b2_a_helper_finish_mid_run_keeps_every_completed_row_line(module):
    """Rows log their PROBE line as they end; a later G.finish (throw_pokeball_from_bag's own)
    that never reaches the summary loses nothing already finished."""
    lua, probe = module
    log = []
    done = {}
    for name, fields in (("idle", {"samples": 300, "yes": 300, "non_irq_samples": 300, "non_irq_yes": 300}),
                         ("battle", {"samples": 120, "no": 120,
                                     "clauses": lua.table_from({"in_battle": 120})}),
                         ("script_running", {"samples": 120, "no": 120,
                                             "clauses": lua.table_from({"script_context_status": 120})})):
        i, row = finished_row(lua, probe, name, **fields)
        done[i] = row
        assert probe.finish_row(row, 1300, log.append) is True
    # ... then the N8 helper calls G.finish: the run ends here, no summary pass runs
    assert [ln.split()[1:3] for ln in log] == [["idle", "PASS"], ["battle", "PASS"], ["script_running", "PASS"]]
    assert all(" frames=300 " in ln for ln in log)
    # a normal end: the summary does not repeat logged rows, logs the rest, and counts all
    plan = lua.table_from(dict.fromkeys((1, 6, 9, 10), True))
    later = []
    passed = probe.summary(lua.table_from(done), plan, "firered", "clean", True, later.append)
    assert passed is False                                  # row 10 planned but never run
    assert [ln for ln in later if ln.split()[1] in ("idle", "battle", "script_running")] == []
    assert "PROBE battle_input_wild FAIL not run" in later
    # the run itself: every row end goes through finish(), and the script row precedes the
    # reason rows (the last of which, bw_n8_item, can end the run)
    assert SOURCE.count("finish(row)") == 14 and SOURCE.count("active = nil") == 3   # +2 E2-CKPT custom rows
    assert SOURCE.index("if plan[9] then") < SOURCE.index("for i = P.REASON_BASE, #P.STATES do")
    assert "P.summary(rows, plan, title, kind, ok and callback_error == nil, G.log)" in SOURCE


def test_b2_a_logged_row_still_counts_in_the_verdict(module):
    lua, probe = module
    i, row = finished_row(lua, probe, "battle", samples=120, yes=1, no=119,
                          clauses=lua.table_from({"in_battle": 119}))
    log = []
    assert probe.finish_row(row, 1100, log.append) is False and log[0].split()[1:3] == ["battle", "FAIL"]
    assert probe.summary(lua.table_from({i: row}), lua.table_from({i: True}), "firered", "clean",
                         True, log.append) is False
    assert len([ln for ln in log if ln.startswith("PROBE battle ")]) == 1


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_b5_bw_diag_carries_the_menu_and_party_state(title):
    w, probe = bw_world(title)
    assert probe.bw_diag("BWLAST N7", None) == "BWLAST N7 no sample fed yet"
    w.set(**parked(title), pm=(1, 0, 1), bag_location=5, fade=True)
    s = w.ctx.sample(w.ctx, w.safety, "battle_faint", None,
                     w.lua.table_from({"map": "3.19", "pos": "12,37", "party_count": 2, "slot1_hp": 17}))
    line = probe.bw_diag("BWSTEP N7 6", s)
    for field in ("BWSTEP N7 6 frame=100", "pm_type=1", "pm_slot=1", "pm_action=0", "bag_location=5",
                  "fade=true", "party_count=2", "slot1_hp=17", "slot1_usable=true", "chosen0=0"):
        assert field in line, field
    for count, hp in ((1, 17), (2, 0)):
        s.extra = w.lua.table_from({"party_count": count, "slot1_hp": hp})
        assert "slot1_usable=false" in probe.bw_diag("x", s)
    assert probe.PARTY_MON_SIZE == 100 and probe.MON_HP_OFF == 0x56
    assert 'G.log(P.bw_diag("BWSTEP " .. spec.bw .. " " .. n, bw_last))' in SOURCE
    assert 'G.log(P.bw_diag("BWLAST " .. spec.bw, bw_last))' in SOURCE


def test_b6_every_planned_row_is_validated_before_any_row_runs(module):
    lua, probe = module
    WIT = witness_table(lua, probe, FRLG_PACK["firered"], {})
    for title, kind in (("firered", "clean"), ("leafgreen", "clean"), ("radical_red", "companion"),
                        ("radical_red", "clean")):
        assert probe.validate(probe.planned(title, kind, None), WIT) is True
    i = next(i for i, r in probe.STATES.items() if r.name == "battle_move_menu")
    spec = probe.STATES[i]
    saved = spec.inputs
    spec.inputs = lua.table_from([lua.table_from({"tap": "A", "gap": 0}), lua.table_from({"tap": "A"})])
    try:
        with pytest.raises(lupa.LuaError, match="battle_move_menu input 2: A pressed again"):
            probe.validate(probe.planned("firered", "clean", None), WIT)
    finally:
        spec.inputs = saved
    assert SOURCE.index("P.validate(plan, WIT)") < SOURCE.index("hook = event.onframeend(")


def test_c1_frames_are_logged_per_row_and_at_the_end(module):
    lua, probe = module
    _, row = finished_row(lua, probe, "battle", samples=120, no=120, clauses=lua.table_from({"in_battle": 120}))
    log = []
    probe.finish_row(row, 1777, log.append)
    assert " frames=777 " in log[0]
    assert 'G.log(string.format("FRAMES spent=%d budget=%d", G.spent, G.budget))' in SOURCE
    assert "index=index, spent0=G.spent}" in SOURCE


def test_a2_a_nil_savestate_load_is_not_a_load(module, tmp_path):
    lua, probe = module
    present = tmp_path / "slink_prebattle.State"
    present.write_bytes(b"x")
    ok, why = probe.load_state(present.as_posix(), lambda p: None, lua.eval("io.open"))
    assert ok is False and why.startswith("savestate.load refused (returned nil): ")


def test_a3_core_phase_loads_name_the_state(module):
    """Plain assert(load(x)) already forwarded load's second return as the message (lupa below);
    must_load keeps that explicit and says which kind of phase failed."""
    lua, probe = module
    ok, msg = lua.execute("return pcall(function() assert((function() return false, 'state missing: X' end)()) end)")
    assert ok is False and "state missing: X" in msg
    assert 'assert(ok, "core phase state: " .. tostring(why))' in SOURCE


def test_a4_witness_value_only_with_a_factory_and_never_on_until(module):
    lua, probe = module
    WIT = witness_table(lua, probe, FRLG_PACK["firered"], {})
    with pytest.raises(lupa.LuaError, match="battle_input takes no witness_value"):
        probe.row_witness(WIT, lua.table_from({"name": "x", "witness": "battle_input", "witness_value": 2}))
    with pytest.raises(lupa.LuaError, match="battle_comm_eq is a factory and needs witness_value"):
        probe.row_witness(WIT, lua.table_from({"name": "x", "witness": "battle_comm_eq"}))
    with pytest.raises(lupa.LuaError, match="until_witness battle_comm_ge is a factory"):
        probe.row_witness(WIT, lua.table_from({"name": "x", "witness": "battle_comm_eq", "witness_value": 2,
                                               "until_witness": "battle_comm_ge"}))
    w, stop = probe.row_witness(WIT, lua.table_from({"name": "x", "witness": "battle_comm_eq",
                                                     "witness_value": 0}))
    assert w() is True and stop() is True             # comm0 reads 0 in the empty fake RAM


# ── N7 live at d8a62085: SHIFT A merged with the popup A in the GAME's key reads ─────────────
class Game:
    """ReadKeys (pret src/main.c:296-300) once per main-loop pass; `lag` frames get no pass
    (the pass that started earlier overran). Counts JOY_NEW(button) edges."""

    def __init__(self, lag=()):
        self.lag, self.frame, self.pad, self.held, self.edges = set(lag), 0, {}, 0, []

    def set(self, keys):
        self.pad = dict(keys.items())

    def advance(self):
        self.frame += 1
        if self.frame not in self.lag:
            keys = sum(bit for name, bit in (("A", 1), ("B", 2), ("Down", 0x80)) if self.pad.get(name))
            new = keys & ~self.held
            if new:
                self.edges.append((self.frame, new))
            self.held = keys
        self.pad = {}                       # joypad.set holds for one frame only


def old_taps(game, taps):
    """G.tap(btn, 3, gap): 3 pressed frames, then `gap` released ones (0b37e14d..a596b337 TAP_A)."""
    for btn, gap in taps:
        for _ in range(3):
            game.set({btn: True})
            game.advance()
        for _ in range(gap):
            game.set({})
            game.advance()


def test_n7_trace_shape_one_release_frame_in_a_lag_frame_is_one_press():
    """The live shape: popup A at 1925-1927, one release frame 1928, SHIFT A 1929-1931. If the
    game's pass skips 1928, it reads A held throughout: ONE edge, SHIFT never chosen."""
    g = Game(lag={4})                                  # frame 4 == the 1928 release frame
    old_taps(g, [("A", 1), ("A", 1)])
    assert g.edges == [(1, 1)]
    g = Game()
    old_taps(g, [("A", 1), ("A", 1)])
    assert [f for f, _ in g.edges] == [1, 5]           # without the lag it worked on paper


@pytest.mark.parametrize("lag", [(), (4,), (2, 3, 4, 5), (1, 2, 6, 7, 8), tuple(range(3, 12, 2))])
def test_press_makes_every_tap_a_game_read_edge(module, lag):
    lua, probe = module
    g = Game(lag=lag)
    held = lambda: g.held  # noqa: E731
    for _ in range(3):
        ok, frames = probe.press("A", lambda k: g.set(k), g.advance, held, 1)
        assert ok is True and frames >= 3
    assert len([e for e in g.edges if e[1] & 1]) == 3


def test_press_fails_by_name_when_the_game_never_reads_it(module):
    lua, probe = module
    g = Game(lag=range(1, 200))                        # the game never runs a pass
    ok, why = probe.press("A", lambda k: g.set(k), g.advance, lambda: g.held, 1)
    assert ok is False and why == "A: the game never read A pressed in 30 frames"
    stuck = Game()
    ok, why = probe.press("B", lambda k: stuck.set(k), stuck.advance, lambda: 0x2, 0)
    assert ok is False and "never read B released" in why


def test_held_keys_offset_is_gmain_heldkeys_on_both_titles(module):
    _, probe = module
    for sym_file in ("pokefirered.sym", "pokeleafgreen.sym"):
        assert _sym("gMain", sym_file) == 0x030030F0
    assert 0x030030F4 + probe.HELD_KEYS_OFF == 0x030030F0 + 0x2C
    assert "local pressed, why = P.press(step.tap, function(k) joypad.set(k) end, G.advance, held_keys," in SOURCE
    assert 'G.log("BWPRESS " .. spec.bw .. " " .. n .. " " .. why)' in SOURCE


@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_party_popup_wait_is_the_selection_task_not_the_list(title):
    """pret party_menu.c:1211-1213 + 3055-3060: A on a CHOOSE_MON list calls
    Task_TryCreateSelectionWindow synchronously, which sets Task_HandleSelectionMenuInput in the
    same frame; that task reads input from the next frame (:3062-3066, no fade). So a zero-frame
    popup wait right after the A is correct -- but the list task alone must never satisfy it."""
    w, probe = bw_world(title)
    T = w.ctx.T
    w.set(**parked(title), cb2=T.CB2_UPDATE_PARTY_MENU, tasks=(T.TASK_CHOOSE_MON,), pm=(1, 0, 1))
    assert probe.BW_WAITS.party_input(w.sample(), w.ctx) is True
    assert probe.BW_WAITS.party_popup(w.sample(), w.ctx) is False
    w.set(**parked(title), cb2=T.CB2_UPDATE_PARTY_MENU, tasks=(T.TASK_SELECTION_POPUP,), pm=(1, 0, 1))
    assert probe.BW_WAITS.party_popup(w.sample(), w.ctx) is True


def test_press_first_waits_for_the_game_to_read_the_release(module):
    """The previous input (here a gap-0 G.tap, as the non-bw rows still press) left A held in the
    game's last read and the next frame is a lag frame: pressing at once would be no edge."""
    lua, probe = module
    g = Game(lag={4})
    old_taps(g, [("A", 0)])
    ok, _ = probe.press("A", lambda k: g.set(k), g.advance, lambda: g.held, 0)
    assert ok is True and [f for f, _ in g.edges] == [1, 6]


# ── a1bbc686: RR holds battle_commit, so the trainer tuple signs a refusal there ─────────────
@pytest.mark.parametrize("kind", ["clean", "companion"])
def test_rr_parked_trainer_commit_is_a_held_refusal_row(module, kind):
    from tests.unit.test_gen3_safety import rr_battle_world
    lua, probe = module
    rows = {r.name: r for r in probe.STATES.values()}
    assert set(rows["battle_input_trainer"].artifacts.keys()) == {"firered/clean", "leafgreen/clean", "emerald/clean"}
    held = rows["battle_commit_held_rr"]
    assert set(held.artifacts.keys()) == {"radical_red/companion"}
    assert (held.reason, held.args.battler, held.witness, held.state) == (
        "battle_commit", 0, "battle_input_trainer", "slink_pretrainer.State")
    # the real RR pack + safety at the parked menu: battle_commit refused by the hold alone
    ok, _, clauses = rr_battle_world(kind, 1, 1, 0x0802E439).check_reason("battle_commit", {"battler": 0})
    assert ok is False and clauses == ["battle_commit_hold"]
    row = run_row(lua, probe, "battle_commit_held_rr", [clauses] * 60)
    assert tuple(probe.verdict(row)) == (True, "-")
    # ...which the positive trainer row could never have passed on RR
    pos = run_row(lua, probe, "battle_input_trainer", [clauses] * 60)
    pos.non_irq_samples, pos.non_irq_yes = 60, 0
    assert probe.verdict(pos)[0] is False
    # a refusal by anything else (the hold lifted) is not this row's evidence
    row = run_row(lua, probe, "battle_commit_held_rr", [["battle_input_controller"]] * 60)
    assert probe.verdict(row)[0] is False
    with pytest.raises(lupa.LuaError):
        probe.planned("radical_red", "companion", "battle_input_trainer")
