"""SP-LOWWATER (docs/gen2/POST_RC_CARDS.md): the pure verdicts, no emulator.

The Lua half (lua/tests/gen2_sfx_gate.lua P.lowwater_verdict / P.lowwater_margin, under lupa) and the release
verifier's re-judgement (tools/verify_gen2_release._sp_lowwater_gate_row_errors) each see one known-good run and the
design's falsifiers; plus the design's static bound against the stack capacities in the overlay .sym files.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

import lupa
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import verify_gen2_release as gate  # noqa: E402

GATE = (REPO / "lua/tests/gen2_sfx_gate.lua").as_posix()
STACK = {"crystal": (0xC000, 0xC0FF), "gold": (0xDF03, 0xDFFF), "silver": (0xDF03, 0xDFFF)}


def _lua():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    return lua, lua.eval(f'dofile("{GATE}")')


def _row(site, sp, frame=100):
    return {"site": site, "frame": frame, "sp": sp, "pc": 0x320A, "rom_bank": 0x0F, "hvblank": 0, "rie": 0x1F,
            "text_delay": 1, "vblank_occurred": 1, "mailbox": {"sfx": 0, "phone_req": 0, "phone_armed": 2}}


def good_run(mode="A_held", title="gold"):
    bottom, top = STACK[title]
    trigger = dict(_row("PrintLetterDelay.checkjoypad", top - 20), battle_mode=1,
                   joy_down=gate.SP_LOWWATER_MODES[mode])
    return {
        "mode": mode, "verdict": "PASS", "trigger": trigger,
        "service_irq": _row("SlinkDelayFrameBridge", top - 30),
        "delay_path": None if mode == "released" else 100, "resumed": 101,
        "sfx": {"code": 1, "id": 1, "accepted": True, "pre_playing": False, "posted": 100, "consumed": 100, "played": 101},
        "phone": {"id": 2, "accepted": True, "posted": 100, "acked": 101, "armed_id": 2, "rings_in_battle": 0},
        "stack": {"bottom": bottom, "top": top, "floor": bottom + 32, "hook_failures": 0, "pushes": 0,
                  "armed_start": bottom, "armed_end": min(top, bottom + 95),
                  "armed_count": min(top, bottom + 95) - bottom + 1,
                  "canary": {"address": top - 10, "sp": top - 9, "hit": True, "frame": 90},
                  "low_water_state": ">floor+64"},
        "guards": {site: {"hits": 5, "low": _row(site, top - 60)} for site in gate.SP_LOWWATER_GUARDS},
        "excursions": [],
        "nested_vblank": {"count": 1, "windows": 40, "with_sfx": 1, "min_sp": top - 90,
                          "deepest": dict(_row("VBlank", top - 90), entry_sp=top - 70, min_sp=top - 90)},
        # service-chain SP floor top-60 less a 40-byte handler: composed margin (top - bottom) - 100
        "composition": {"note": gate.SP_LOWWATER_NESTED_POLICY, "service_windows": 40, "service_min_sp": top - 60,
                        "vblank_samples": 500, "vblank_max_depth": 40},
        "battle": {"from": 50, "to": 900},
    }


def good_receipt(bind):
    """A per-title receipt as tests/live/test_gen2_sp_lowwater_gate.combine writes it, over `bind` (the overlay
    binding: result/evidence_level/title/overlay_sha1/fixture/fixture_sha256)."""
    title = bind["title"]
    return {**bind, "schema": "gen2-sp-lowwater-v1", "bounds": dict(gate.SP_LOWWATER_BOUNDS),
            "nested_vblank_policy": gate.SP_LOWWATER_NESTED_POLICY,
            "static_bound": {"print_letter_delay": 12, "service_chain": 38, "vblank": 36},
            "runs": {mode: good_run(mode, title) for mode in gate.SP_LOWWATER_MODES}, "harness_write_scopes": [],
            "core_mode": "CGB", "input_mode": "normal_buttons"}


def _set(run, path, value):
    *keys, last = path.split(".")
    node = run
    for key in keys:
        node = node[key]
    if value is _DEL:
        del node[last]
    else:
        node[last] = value


_DEL = object()
BOTTOM, TOP = STACK["gold"]
# (name, [(path, value)], Lua problem substring, verifier error substring)
FALSIFIERS = [
    ("margin_below_N", [("stack.low_water_state", "exact"),
                        ("stack.low_water", {"stack_addr": BOTTOM + 20, "sp": BOTTOM + 21})],
     "stack margin 20", "within 32 bytes"),
    ("canary_never_hit", [("stack.canary.hit", False)], "no canary hit", "canary/coverage"),
    ("canary_off_stack", [("stack.canary.address", 0xCE58)], "off the stack", "canary/coverage"),
    ("coverage_gap", [("stack.armed_count", 95)], "coverage incomplete", "canary/coverage"),
    ("hook_failure", [("stack.hook_failures", 1)], "coverage incomplete", "canary/coverage"),
    ("low_water_unknown", [("stack.low_water_state", "exact")], "neither exact", "neither exact"),
    ("guard_below_floor", [("guards._PlaySFX.low.sp", BOTTOM + 10)], "SP guard _PlaySFX", "SP guard _PlaySFX"),
    ("guard_off_stack", [("guards.VBlank.low.sp", 0xE010)], "SP guard VBlank", "SP guard VBlank"),
    ("guard_unhooked", [("guards.SlinkPhoneService", _DEL)], "SP guard SlinkPhoneService", "SP guard SlinkPhoneService"),
    ("excursion", [("excursions", [_row("_PlaySFX", BOTTOM + 4)])], "below the floor", "below the floor"),
    ("not_battle", [("trigger.battle_mode", 0)], "wBattleMode 1", "wBattleMode 1"),
    ("no_text_delay", [("trigger.text_delay", 0)], "wTextDelayFrames > 0", "wTextDelayFrames > 0"),
    ("joy_not_the_mode", [("trigger.joy_down", 0)], "hJoyDown", "hJoyDown"),
    ("hvblank_not_normal", [("trigger.hvblank", 2)], "at the trigger", "at the trigger"),
    ("rie_no_vblank", [("service_irq.rie", 0x1E)], "first service", "first service"),
    ("no_service_after_trigger", [("service_irq", None)], "first service", "first service"),
    ("held_without_delayframe", [("delay_path", None)], ".delay", ".delay"),
    ("text_not_resumed", [("resumed", 401)], "did not resume", "did not resume"),
    ("sfx_refused", [("sfx.accepted", False)], "not posted by the binding", "SFX"),
    ("sfx_pre_playing", [("sfx.pre_playing", True)], "already on a channel", "SFX"),
    ("sfx_never_consumed", [("sfx.consumed", None)], "consumed and played", "SFX"),
    ("sfx_never_played", [("sfx.played", None)], "consumed and played", "SFX"),
    ("sfx_late", [("sfx.played", 401)], "consumed and played", "SFX"),
    ("phone_refused", [("phone.accepted", False)], "not posted by the binder", "phone"),
    ("phone_unacked", [("phone.acked", None)], "acked and ARMED", "phone"),
    ("phone_wrong_armed", [("phone.armed_id", 1)], "acked and ARMED", "phone"),
    ("phone_rang_in_battle", [("phone.rings_in_battle", 1)], "rang in battle", "rang in battle"),
]


def _mutated(mode, edits):
    run = good_run(mode)
    for path, value in edits:
        _set(run, path, copy.deepcopy(value) if value is not _DEL else _DEL)
    return run


def _lua_verdict(run):
    lua, P = _lua()
    verdict, problems = P.lowwater_verdict(lua.table_from(run, recursive=True))
    return verdict, [problems[i] for i in range(1, len(problems) + 1)]


@pytest.mark.parametrize("mode", list(gate.SP_LOWWATER_MODES))
def test_the_known_good_run_passes_both_halves(mode):
    assert _lua_verdict(good_run(mode)) == ("PASS", [])
    assert gate._sp_lowwater_run_errors(mode, good_run(mode)) == []


@pytest.mark.parametrize("name,edits,lua_why,py_why", FALSIFIERS, ids=[f[0] for f in FALSIFIERS])
def test_each_falsifier_fails_both_halves(name, edits, lua_why, py_why):
    verdict, problems = _lua_verdict(_mutated("A_held", edits))
    assert verdict == "FAIL" and any(lua_why in p for p in problems), (verdict, problems)
    errors = gate._sp_lowwater_run_errors("A_held", _mutated("A_held", edits))
    assert any(py_why in e for e in errors), errors


def test_no_trigger_fails():
    run = _mutated("B_held", [("trigger", None)])
    assert _lua_verdict(run) == ("FAIL", ["never triggered at PrintLetterDelay.checkjoypad in battle text"])
    assert any("trigger" in e for e in gate._sp_lowwater_run_errors("B_held", run))


def test_a_nested_vblank_is_bounded_by_composition_not_required():
    run = _mutated("released", [("nested_vblank.count", 0), ("nested_vblank.min_sp", None)])
    assert _lua_verdict(run) == ("PASS", [])
    assert gate._sp_lowwater_run_errors("released", run) == []


@pytest.mark.parametrize("margin,verdict", [(32, "PASS"), (31, "FAIL")])
def test_the_composed_margin_passes_at_exactly_N(margin, verdict):
    # service_min_sp - bottom - vblank_max_depth == margin
    run = _mutated("A_held", [("composition.service_min_sp", BOTTOM + 80), ("composition.vblank_max_depth", 80 - margin)])
    lua_verdict, problems = _lua_verdict(run)
    assert lua_verdict == verdict, problems
    assert (gate._sp_lowwater_run_errors("A_held", run) == []) is (verdict == "PASS")
    if verdict == "FAIL":
        assert any("composed margin 31" in p for p in problems)
        assert any("composed margin" in e for e in gate._sp_lowwater_run_errors("A_held", run))
    lua, P = _lua()
    assert P.lowwater_composed(lua.table_from(run["composition"]), BOTTOM) == margin


@pytest.mark.parametrize("edits,why", [
    ([("composition.vblank_samples", 0)], "no VBlank handler was measured"),
    ([("composition.vblank_max_depth", None)], "no VBlank handler was measured"),
    ([("composition.service_windows", 0)], "no service window was measured"),
    ([("composition", None)], "no service window was measured"),
])
def test_a_missing_composition_component_is_inconclusive(edits, why):
    run = _mutated("B_held", edits)
    verdict, problems = _lua_verdict(run)
    assert verdict == "INCONCLUSIVE" and why in problems[0], problems
    errors = gate._sp_lowwater_run_errors("B_held", run)
    assert f"INCONCLUSIVE: {why}" in errors and all(e.startswith("INCONCLUSIVE: ") for e in errors), errors
    # a real failure outranks INCONCLUSIVE
    assert _lua_verdict(_mutated("B_held", edits + [("phone.rings_in_battle", 1)]))[0] == "FAIL"


def test_an_observed_nested_vblank_under_N_fails_even_when_the_composition_passes():
    run = _mutated("A_held", [("nested_vblank.min_sp", BOTTOM + 31), ("nested_vblank.deepest.sp", BOTTOM + 31)])
    assert gate._sp_lowwater_run_errors("A_held", _mutated("A_held", [])) == []   # composition alone passes
    verdict, problems = _lua_verdict(run)
    assert verdict == "FAIL" and any("nested VBlank came within 32" in p for p in problems), problems
    assert any("nested VBlank came within 32" in e for e in gate._sp_lowwater_run_errors("A_held", run))
    at_n = _mutated("A_held", [("nested_vblank.min_sp", BOTTOM + 32), ("nested_vblank.deepest.sp", BOTTOM + 32)])
    assert _lua_verdict(at_n)[0] == "PASS" and gate._sp_lowwater_run_errors("A_held", at_n) == []
    assert _lua_verdict(_mutated("A_held", [("nested_vblank.min_sp", None)]))[0] == "FAIL"   # count 1, no depth


def test_the_released_mode_needs_no_delayframe_but_the_held_modes_do():
    assert _lua_verdict(good_run("released"))[0] == "PASS"
    assert _lua_verdict(_mutated("A_held", [("delay_path", None)]))[0] == "FAIL"


def test_an_exact_low_water_at_the_floor_passes_and_one_byte_lower_fails():
    lua, P = _lua()
    stack = good_run()["stack"]
    for addr, ok in ((BOTTOM + 32, True), (BOTTOM + 31, False)):
        stack.update(low_water_state="exact", low_water={"stack_addr": addr, "sp": addr + 1})
        margin, kind = P.lowwater_margin(lua.table_from(stack, recursive=True))
        assert (margin, kind) == (addr - BOTTOM, "exact")
        run = _mutated("A_held", [("stack", stack)])
        assert (_lua_verdict(run)[0] == "PASS") is ok
        assert (gate._sp_lowwater_run_errors("A_held", run) == []) is ok
    stack.update(low_water_state=">floor+64", low_water=None)
    assert P.lowwater_margin(lua.table_from(stack, recursive=True)) == (96, "lower_bound")


def test_the_verifier_rejudges_the_facts_not_the_verdict_string():
    run = _mutated("A_held", [("phone.rings_in_battle", 1)])   # verdict still says "PASS"
    assert run["verdict"] == "PASS" and gate._sp_lowwater_run_errors("A_held", run)
    assert any("verdict" in e for e in gate._sp_lowwater_run_errors("A_held", dict(good_run(), verdict="INCONCLUSIVE")))


def _receipt_tree(tmp_path, title="gold"):
    (tmp_path / "data/gen2").mkdir(parents=True)
    provenance = (REPO / "data/gen2/overlay_provenance.json").read_bytes()
    (tmp_path / "data/gen2/overlay_provenance.json").write_bytes(provenance)
    sha1 = next(r["sha1"] for r in json.loads(provenance)["outputs"].values() if r["slink_title"] == title)
    sym = f"data/gen2/{title}_slink.sym"
    (tmp_path / sym).write_bytes((REPO / sym).read_bytes())
    # the verifier re-checks the receipt's binding pin against the published sidecar (stream C, cx-e10f9ad3 B2)
    binding = f"data/games/gen2_{title}/overlay/binding.json"
    (tmp_path / binding).parent.mkdir(parents=True)
    (tmp_path / binding).write_bytes((REPO / binding).read_bytes())
    raw = (REPO / "tests/fixtures/gen2" / f"{title}_battle.SaveRAM").read_bytes()
    (tmp_path / "tests/fixtures/gen2").mkdir(parents=True)
    (tmp_path / "tests/fixtures/gen2" / f"{title}_battle.SaveRAM").write_bytes(raw)
    out = next(r for r in json.loads(provenance)["outputs"].values() if r["slink_title"] == title)
    identity = {"artifact_kind": "overlay", "rom_sha1": sha1, "base_sha1": out["base_sha1"],
                "binding_sha256": hashlib.sha256((REPO / binding).read_bytes().replace(bytes([13, 10]), bytes([10]))).hexdigest()}
    return good_receipt({"result": "PASS", "evidence_level": "PHYSICAL", "title": title, "overlay_sha1": sha1,
                         "fixture": f"{title}_battle", "fixture_sha256": hashlib.sha256(raw).hexdigest(), **identity})


def test_the_release_row_is_green_only_on_the_whole_receipt(tmp_path):
    receipt = _receipt_tree(tmp_path)
    assert gate._sp_lowwater_gate_row_errors(tmp_path, "gold", receipt) == []
    bad = copy.deepcopy(receipt)
    del bad["runs"]["released"]
    assert any("A_held, B_held and released" in e for e in gate._sp_lowwater_gate_row_errors(tmp_path, "gold", bad))
    bad = dict(copy.deepcopy(receipt), bounds=dict(gate.SP_LOWWATER_BOUNDS, margin_floor=16))
    assert any("bounds" in e for e in gate._sp_lowwater_gate_row_errors(tmp_path, "gold", bad))
    bad = dict(copy.deepcopy(receipt), overlay_sha1="0" * 40)
    assert any("another overlay" in e for e in gate._sp_lowwater_gate_row_errors(tmp_path, "gold", bad))
    bad = dict(copy.deepcopy(receipt), schema="gen2-sfx-gate-v1")
    assert any("PHYSICAL PASS" in e for e in gate._sp_lowwater_gate_row_errors(tmp_path, "gold", bad))
    bad = copy.deepcopy(receipt)
    bad["runs"]["B_held"]["composition"]["vblank_samples"] = 0
    assert gate._sp_lowwater_gate_row_errors(tmp_path, "gold", bad) == [
        "sp-lowwater gate B_held: INCONCLUSIVE: no VBlank handler was measured"]
    bad = dict(copy.deepcopy(receipt), nested_vblank_policy=None)
    assert any("nested-VBlank policy" in e for e in gate._sp_lowwater_gate_row_errors(tmp_path, "gold", bad))


def test_the_static_bound_fits_the_stack_capacities_with_the_margin():
    """The design's static bound (86 B = PrintLetterDelay 12 + bridge/service/SFX/_PlaySFX leaf 38 + normal VBlank 36)
    against the capacities wStackTop - wStackBottom in the overlay .sym (Crystal 255, Gold/Silver 252)."""
    _, P = _lua()
    static = dict(P.LW_STATIC.items())
    assert static == {"print_letter_delay": 12, "service_chain": 38, "vblank": 36} and sum(static.values()) == 86
    capacities = {}
    for title in STACK:
        sym = (REPO / "data/gen2" / f"{title}_slink.sym").read_text(encoding="utf-8")
        addr = {name: int(a, 16) for a, name in re.findall(r"^[0-9a-f]{2}:([0-9a-f]{4}) (wStack(?:Bottom|Top))$", sym, re.M)}
        assert (addr["wStackBottom"], addr["wStackTop"]) == STACK[title]
        capacities[title] = addr["wStackTop"] - addr["wStackBottom"]
    assert capacities == {"crystal": 255, "gold": 252, "silver": 252}
    assert all(cap >= 86 + P.LW_MARGIN for cap in capacities.values())
    assert P.LW_MARGIN == gate.SP_LOWWATER_BOUNDS["margin_floor"] == 32
    assert P.LW_EXACT == gate.SP_LOWWATER_BOUNDS["exact_window"] == 64
    assert [P.LW_GUARDS[i] for i in range(1, len(P.LW_GUARDS) + 1)] == list(gate.SP_LOWWATER_GUARDS)
    assert dict(P.LW_MODES.items()) == gate.SP_LOWWATER_MODES
    assert P.LW_NESTED_POLICY == gate.SP_LOWWATER_NESTED_POLICY


# OMP cx-cd30c22b F2/F4: the composition facts are bounded, and the nested record is the handler's deepest SP
CAPACITY = TOP - BOTTOM
REFUSED = [
    ("depth_negative", [("composition.vblank_max_depth", -1_000_000)]),
    ("depth_past_capacity", [("composition.vblank_max_depth", CAPACITY + 1)]),
    ("service_sp_above_the_stack", [("composition.service_min_sp", TOP + 50)]),
    ("service_sp_below_the_stack", [("composition.service_min_sp", BOTTOM - 1)]),
    ("nested_count_negative", [("nested_vblank.count", -1), ("nested_vblank.min_sp", BOTTOM + 1)]),
    ("nested_count_missing", [("nested_vblank.count", None)]),
    ("nested_count_fractional", [("nested_vblank.count", 0.5)]),
    ("nested_without_min_sp", [("nested_vblank.min_sp", None)]),
    ("nested_min_sp_off_stack", [("nested_vblank.min_sp", TOP + 2), ("nested_vblank.deepest.sp", TOP + 2)]),
    ("nested_deepest_is_the_entry_sp", [("nested_vblank.deepest.sp", TOP - 70)]),
    ("nested_without_deepest", [("nested_vblank.deepest", None)]),
]


@pytest.mark.parametrize("name,edits", REFUSED, ids=[r[0] for r in REFUSED])
def test_unbounded_composition_facts_are_refused_by_both_halves(name, edits):
    run = _mutated("A_held", edits)
    verdict, problems = _lua_verdict(run)
    assert verdict == "FAIL", (verdict, problems)
    errors = gate._sp_lowwater_run_errors("A_held", run)
    assert errors and not all(e.startswith("INCONCLUSIVE") for e in errors), errors


def test_the_capacity_bounds_are_inclusive():
    for edits in ([("composition.vblank_max_depth", 0)], [("composition.service_min_sp", TOP + 1)]):
        run = _mutated("A_held", edits)
        assert _lua_verdict(run) == ("PASS", []) and gate._sp_lowwater_run_errors("A_held", run) == []


# OMP cx-cd30c22b F3: the per-title binding the producer asserts, re-checked by the verifier
def _mode_swapped(r):
    r["runs"]["A_held"]["mode"] = "B_held"


def _bottom_moved(r):
    for run in r["runs"].values():   # consistent inside the receipt, but not the title's own wStackBottom
        run["stack"]["bottom"] -= 0x100
        run["stack"]["armed_start"] -= 0x100


def _top_moved(r):
    r["runs"]["released"]["stack"]["top"] += 1


F3 = [
    ("mode_differs_from_its_key", _mode_swapped, "mode"),
    ("bottom_not_the_titles", _bottom_moved, "wStackBottom"),
    ("top_not_the_titles", _top_moved, "wStackTop"),
    ("no_static_bound", lambda r: r.pop("static_bound"), "static_bound"),
    ("static_bound_edited", lambda r: r["static_bound"].update(vblank=20), "static_bound"),
    ("core_mode", lambda r: r.update(core_mode="DMG"), "core_mode"),
    ("input_mode", lambda r: r.update(input_mode="harness_writes"), "input_mode"),
    ("harness_writes", lambda r: r.update(harness_write_scopes=["wSpecialPhoneCallID"]), "harness_write_scopes"),
]


@pytest.mark.parametrize("name,mutate,why", F3, ids=[f[0] for f in F3])
def test_the_row_rechecks_the_producer_binding(tmp_path, name, mutate, why):
    receipt = _receipt_tree(tmp_path)
    assert gate._sp_lowwater_gate_row_errors(tmp_path, "gold", receipt) == []
    mutate(receipt)
    errors = gate._sp_lowwater_gate_row_errors(tmp_path, "gold", receipt)
    assert any(why in e for e in errors), errors


def test_the_row_needs_the_provenance_bound_sym(tmp_path):
    receipt = _receipt_tree(tmp_path)
    sym = tmp_path / "data/gen2/gold_slink.sym"
    sym.write_bytes(sym.read_bytes() + b"\n")
    assert any("sym" in e for e in gate._sp_lowwater_gate_row_errors(tmp_path, "gold", receipt))
