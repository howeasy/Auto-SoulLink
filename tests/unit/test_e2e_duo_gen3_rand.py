"""R4 oracle controls: positive -> deliberate falsifier -> restored positive.

Synthetic ROMs/flash exercise the oracle itself; optional hash-pinned clean and
scratch UPR ROMs exercise the production Lua collector and actual server ingest.
No emulator is started by this module. Live dependencies are a separate gate.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import e2e_duo as duo  # noqa: E402

from server.adapters.gen3_codec import encode_name  # noqa: E402
from tests.unit.test_e2e_duo_gen3 import PIDGEY, STARTER, _fixture, _mon, _saved  # noqa: E402


def _symbols(title):
    return {words[-1]: (int(words[0], 16), int(words[2], 16))
            for line in (ROOT / f"data/gen3/pret/poke{title}.sym").read_text().splitlines()
            if len(words := line.split()) == 4}


def _rom(title, species):
    """All expected bytes are synthetic; heads alone come from tracked symbols."""
    rom = bytearray(0x500000)
    rom[0xAC:0xB0] = b"BPRE" if title == "firered" else b"BPGE"
    syms = _symbols(title)
    head = syms["gTrainers"][0] - 0x08000000
    for tid in (102, 414):
        at = head + tid * 40
        rom[at + 4:at + 16] = encode_name("TEST", 12)
        rom[at + 32] = 1
        struct.pack_into("<I", rom, at + 36, 0x08480000 + tid * 8)
        struct.pack_into("<HBxH2x", rom, 0x480000 + tid * 8, 0, 5, species)
    head = syms["gWildMonHeaders"][0] - 0x08000000
    rom[head:head + 2] = bytes((3, 19))
    struct.pack_into("<I", rom, head + 4, 0x08490000)
    rom[0x490000] = 21
    struct.pack_into("<I", rom, 0x490004, 0x08490100)
    for slot in range(12):
        struct.pack_into("<BBH", rom, 0x490100 + slot * 4, 4, 6, species)
    rom[head + 20:head + 22] = b"\xFF\xFF"
    name_head = syms["gSpeciesNames"][0] - 0x08000000
    for number, name in ((1, "BULBASAUR"), (2, "IVYSAUR"), (3, "VENUSAUR")):
        rom[name_head + number * 11:name_head + (number + 1) * 11] = encode_name(name, 11)
    return bytes(rom)


@pytest.fixture(scope="module")
def facts():
    return {side: duo.gen3_rand_rom_facts(_rom(title, species), title)
            for side, title, species in (("a", "firered", 1), ("b", "leafgreen", 2),
                                          ("clean_b", "leafgreen", 3))}


def _hello(fact, kind="rand"):
    row = {"rom_type": fact["title"], "rom_sha1": fact["sha1"], "artifact_kind": kind}
    if kind == "rand":
        row["rom_content"] = copy.deepcopy(fact["payload"])
    return row


def _admission_case(phase, facts):
    status = {"players": {}, "gen3_rand_effective_kind": "rand", "gen3_rand_identity_errors": {}}
    hellos = {}
    for side in (("a", "b") if phase == "pair" else ("a",) if phase == "wrong_rom" else ("b",)):
        fact = facts[side] if phase == "pair" else facts["b"] if phase == "wrong_rom" else facts["clean_b"]
        hellos[side] = _hello(fact, "clean" if phase == "mixed_kind" else "rand")
        reason = "cartridge matches the contract"
        if phase == "wrong_rom":
            reason = ("this is not the cartridge built for player a (reported "
                      + facts["b"]["content_fingerprint"][:12] + ", expected "
                      + facts["a"]["content_fingerprint"][:12] + ")")
        if phase == "mixed_kind":
            reason = "Mixed artifact kinds: slot B runs a 'clean' ROM, this run is committed to 'rand'"
        status["players"][side] = {"connected": phase == "pair", "admission_reason": reason,
                                  "admission": "admitted" if phase == "pair" else "rejected"}
    return {"status": status, "hellos": hellos}


def _revert_checked(case, oracle, mutate, named):
    before = copy.deepcopy(case)
    assert oracle(case) == []
    mutate(case)
    assert any(named in problem for problem in oracle(case))
    case.clear()
    case.update(before)
    assert oracle(case) == []


@pytest.mark.parametrize("phase", ("pair", "wrong_rom", "mixed_kind"))
@pytest.mark.parametrize("fault", ("verdict", "reason", "kind", "sha1", "title"))
def test_admission_oracle_positive_negative_reverted(phase, fault, facts):
    case = _admission_case(phase, facts)
    side = "b" if phase == "mixed_kind" else "a"

    def mutate(case):
        player, hello = case["status"]["players"][side], case["hellos"][side]
        if fault == "verdict":
            player["admission"] = "rejected" if phase == "pair" else "admitted"
        elif fault == "reason":
            player["admission_reason"] = ""
        else:
            hello[{"kind": "artifact_kind", "sha1": "rom_sha1", "title": "rom_type"}[fault]] = "wrong"

    _revert_checked(case, lambda c: duo.gen3_rand_admission_problems(phase, **c, facts=facts), mutate,
                    {"verdict": "verdict" if phase == "pair" else "rejection",
                     "reason": "verdict" if phase == "pair" else "rejection",
                     "kind": "kind", "sha1": "SHA-1", "title": "title"}[fault])


@pytest.mark.parametrize("phase,side", (("wrong_rom", "a"), ("mixed_kind", "b")))
def test_rejected_player_must_not_adopt_state(phase, side, facts):
    case = _admission_case(phase, facts)
    _revert_checked(case, lambda c: duo.gen3_rand_admission_problems(phase, **c, facts=facts),
                    lambda c: c["status"]["players"][side].update(party_keys=["adopted"]), "adopted")


def test_pair_hello_table_swap_is_detected_and_reverted(facts):
    case = _admission_case("pair", facts)
    _revert_checked(case, lambda c: duo.gen3_rand_admission_problems("pair", **c, facts=facts),
                    lambda c: c["hellos"]["a"].update(rom_content=facts["b"]["payload"]), "table bytes")


def test_contract_binds_semantic_fingerprint_not_transport_sha1(facts):
    contract = duo.gen3_rand_contract(facts)
    for side in ("a", "b"):
        assert contract["players"][side]["fingerprint"] == facts[side]["content_fingerprint"]
        assert len(contract["players"][side]["fingerprint"]) == 64
        assert contract["players"][side]["fingerprint"] != facts[side]["payload"]["fingerprint"]


def test_ruling32_oracle_requires_declared_rand_but_effective_clean(facts):
    facts = copy.deepcopy(facts)
    facts["clean_a"] = facts["a"]
    facts["equivalent_a"] = {**facts["a"], "sha1": "f" * 40}
    case = {"status": {"gen3_rand_effective_kind": "clean", "gen3_rand_identity_errors": {},
                       "players": {side: {"connected": True, "admission": "admitted",
                           "admission_reason": "no randomized-ROM contract for this run"} for side in ("a", "b")}},
            "hellos": {"a": _hello(facts["equivalent_a"]), "b": _hello(facts["clean_b"], "clean")}}
    _revert_checked(case, lambda c: duo.gen3_rand_admission_problems("equivalent_pair", facts=facts, **c),
                    lambda c: c["status"].update(gen3_rand_effective_kind="rand"), "effective kind")


def test_rule_changed_oracle_requires_the_named_rule_refusal(facts):
    facts = {**facts, "forbidden_a": facts["a"]}
    case = {"status": {"players": {"a": {"admission": "rejected",
                "admission_reason": "firered cartridge has randomized evolutions and types/abilities/base stats"}}},
            "hellos": {"a": _hello(facts["forbidden_a"])}}
    _revert_checked(case, lambda c: duo.gen3_rand_admission_problems("rules_changed", facts=facts, **c),
                    lambda c: c["status"]["players"]["a"].update(admission_reason="wrong cartridge"),
                    "named rules_changed")


@pytest.mark.parametrize("bad", ("", 'RAND_HELLO {}\nRAND_HELLO {}\n', 'RAND_HELLO {broken}\n'))
def test_hello_marker_never_accepts_absent_duplicate_or_broken_json(bad):
    with pytest.raises(ValueError):
        duo.gen3_rand_hello(bad)


def _panel_case(facts):
    probes = {side: {"kind": "rand", "area": "viridian_forest", "briefs": {
        "102": {"area": "viridian_forest", "party": [{"species": name, "level": 5}]}},
        "calc_labels": {"102": ""}} for side, name in (("a", "Bulbasaur"), ("b", "Ivysaur"))}
    retail = {"102": {"area": "viridian_forest", "party": [{"species": "Weedle", "level": 6}]}}
    return {"probes": probes, "retail": retail, "expected_area": "viridian_forest"}


def test_panel_oracle_requires_an_explicit_expected_area(facts):
    case = _panel_case(facts)
    args = (case["probes"], facts, case["retail"])
    with pytest.raises(TypeError):     # no default may assume the FR/LG fixture's area
        duo.gen3_rand_panel_problems(*args)
    for falsy in ("", None):
        with pytest.raises(ValueError, match="expected_area"):
            duo.gen3_rand_panel_problems(*args, expected_area=falsy)


@pytest.mark.parametrize("fault", ("swapped", "retail", "level", "area", "label", "calc", "missing"))
def test_panel_oracle_positive_negative_reverted(fault, facts):
    case = _panel_case(facts)

    def mutate(c):
        a = c["probes"]["a"]
        if fault == "swapped":
            a["briefs"] = copy.deepcopy(c["probes"]["b"]["briefs"])
        elif fault == "retail":
            a["briefs"]["102"]["party"] = c["retail"]["102"]["party"]
        elif fault == "level":
            a["briefs"]["102"]["party"][0]["level"] = 99
        elif fault == "area":
            a["area"] = "route_1"
        elif fault == "label":
            a["briefs"]["102"]["calc_label"] = "retail setdex"
        elif fault == "calc":
            a["calc_labels"]["102"] = "retail setdex"
        else:
            a["briefs"] = {}

    _revert_checked(case, lambda c: duo.gen3_rand_panel_problems(facts=facts, **c), mutate,
                    "OWN ROM" if fault in ("swapped", "retail", "level") else
                    "nearby" if fault in ("area", "missing") else "fallback")


def test_panel_level_oracle_does_not_share_the_ingest_decoders_answer(facts):
    expected = copy.deepcopy(facts)
    for side in ("a", "b"):
        expected[side]["trainer_parties"] = {
            tid: copy.deepcopy(row["party"]) for tid, row in expected[side]["tables"]["trainers"].items()}
    case = _panel_case(expected)
    # A shared-decoder regression gives BOTH the server and tables decoder level 99.
    # The separate ROM-byte read still says level 5 and must falsify that agreement.
    case["probes"]["a"]["briefs"]["102"]["party"][0]["level"] = 99
    expected["a"]["tables"]["trainers"][102]["party"][0]["level"] = 99
    assert any("OWN ROM" in p for p in duo.gen3_rand_panel_problems(facts=expected, **case))


def test_panel_probe_and_oracle_are_rom_free_and_do_not_filter_on_adopted_area():
    retail = {"102": {"area": "viridian_forest", "party": [{"species": "Weedle", "level": 6}]}}
    facts = {}
    adapters = {}
    for side, species, name in (("a", 1, "Bulbasaur"), ("b", 2, "Ivysaur")):
        facts[side] = {"species_names": {species: name}, "trainer_parties": {
            102: [{"species": species, "level": 5}]}}
        brief = {"area": "viridian_forest", "party": [{"species": name, "level": 5}]}
        adapters[side] = SimpleNamespace(_artifact_kind="rand", _rom_trainers={"trainers": {
            102: {"area": "wrong-adopted-area"}}}, trainer_brief=lambda _tid, b=brief: copy.deepcopy(b))
    server = SimpleNamespace(adapter_for=adapters.__getitem__, player_area_id={
        "a": "viridian_forest", "b": "viridian_forest"}, state=SimpleNamespace(artifact_kind="rand",
                                                                               identity_error={}))
    probes = duo.gen3_rand_status_probe(server, {}, retail=retail)["gen3_rand_probe"]
    case = {"probes": probes, "retail": retail, "expected_area": "viridian_forest"}
    _revert_checked(case, lambda c: duo.gen3_rand_panel_problems(facts=facts, **c),
                    lambda c: c["probes"]["a"]["briefs"]["102"].update(area="wrong-area"), "not nearby")


def test_saved_state_oracle_positive_negative_reverted():
    fixture = _fixture([STARTER, PIDGEY])
    saved = _saved(fixture, 3, [STARTER, PIDGEY])
    case = {"saved": saved, "fixture": fixture}
    _revert_checked(case, lambda c: duo.gen3_rand_saved_problems(**c),
                    lambda c: c.update(saved=_saved(fixture, 3, [STARTER])), "party/boxes")
    case = {"saved": fixture, "fixture": fixture}
    _revert_checked(case, lambda c: duo.gen3_rand_saved_problems(**c, unchanged_bytes=True),
                    lambda c: c.update(saved=saved), "flash bytes")


@pytest.mark.parametrize("fault", ("missing", "duplicate", "boxed", "species", "level"))
def test_randomized_link_oracle_positive_negative_reverted(fault, facts):
    catch = _mon(123, species=1, level=5)
    key = duo.gen3_key(catch)
    fixture = _fixture([STARTER])
    good = _saved(fixture, 3, [STARTER, catch])
    case = {"saved": duo.gen3_decode(good)}

    def mutate(c):
        party, boxes = c["saved"]
        if fault == "missing":
            party.pop()
        elif fault == "duplicate":
            party.append(copy.deepcopy(party[-1]))
        elif fault == "boxed":
            boxes[(0, 0)] = copy.deepcopy(party[-1])
        else:
            party[-1][fault] = 3 if fault == "species" else 99

    _revert_checked(case, lambda c: duo.gen3_rand_capture_problems(key=key, facts=facts["a"], **c),
                    mutate, "exactly once" if fault in ("missing", "duplicate", "boxed") else "Route 1")


# E-RAND-CATCH: link_gen3_rand extends from FR<->LG to E<->E, reusing the already-pinned
# Emerald randomized ROM/seed path admit_randomized_emerald and trainer_panel_gen3_rand share
# (GEN3_RAND_SCRATCH / SLINK_GEN3_RAND_ROMS, "Emerald_allowed.gba" / "Emerald_allowed_b.gba").
def test_link_gen3_rand_extends_to_emerald_with_its_own_catch_fixture():
    entry = duo.SCENARIOS["link_gen3_rand"]
    assert set(entry["games"]) == {"gen3_frlg", "gen3_emerald"}
    # FR/LG keeps the R4-LINK SYNTH 20-ball fixture; Emerald reuses its own pre-existing
    # 20-ball `catch` fixture (tests/fixtures/gen3/README.md E2-FIX-VARIANTS round 3) -- no
    # new SYNTH file, following the Emerald `catch` fixture precedent the README documents.
    assert duo.scenario_target(entry, "gen3_frlg") == "catch_synth"
    assert duo.scenario_target(entry, "gen3_emerald") == "catch"
    assert duo.scenario_attempt_limit("link_gen3_rand", "gen3_emerald") == 3
    for stem in ("emerald_catch.sav", "emerald_catch_b.sav"):
        assert (ROOT / "tests/fixtures/gen3" / stem).is_file()


def test_capture_oracle_uses_each_titles_own_randomized_hunt_table():
    """pret map_groups: FR/LG Route 1 is (3, 19); Emerald Route 102 is (0, 17)
    (data/games/gen3_emerald/area_map.json "0:17": "route_102", the same key
    gen3_rand_encounter_problems already reads from the independent wild_slots probe)."""
    catch = _mon(123, species=1, level=5)
    key = duo.gen3_key(catch)
    fixture = _fixture([STARTER])
    saved = duo.gen3_decode(_saved(fixture, 3, [STARTER, catch]))
    slot = [{"land": {"rate": 20, "mons": [{"species": 1, "min_level": 3, "max_level": 6}]}}]
    firered_facts = {"title": "firered", "tables": {"wild_encounters": {(3, 19): slot}}}
    emerald_facts = {"title": "emerald", "tables": {"wild_encounters": {(0, 17): slot}}}
    assert duo.gen3_rand_capture_problems(saved, key, firered_facts) == []
    assert duo.gen3_rand_capture_problems(saved, key, emerald_facts) == []
    # the wrong title's table key must not satisfy the other title's oracle
    empty = {"title": "emerald", "tables": {"wild_encounters": {}}}
    assert any("Route 102" in p for p in duo.gen3_rand_capture_problems(saved, key, empty))
    empty = {"title": "firered", "tables": {"wild_encounters": {}}}
    assert any("Route 1" in p for p in duo.gen3_rand_capture_problems(saved, key, empty))


def test_catch_fixture_note_discloses_synth_only_for_frlg_not_emerald():
    fr = (ROOT / "tests/fixtures/gen3/firered_party_catch_synth.sav").read_bytes()
    note = duo.gen3_rand_catch_note("a", "firered", "firered_party_catch_synth.sav", fr)
    assert note.startswith("RAND_SYNTH_FIXTURE")
    assert "change=quantity_and_section_checksum_only" in note

    em = (ROOT / "tests/fixtures/gen3/emerald_catch.sav").read_bytes()
    note = duo.gen3_rand_catch_note("a", "emerald", "emerald_catch.sav", em)
    assert note.startswith("RAND_CATCH_FIXTURE")
    assert "SYNTH=false" in note
    assert "change=quantity_and_section_checksum_only" not in note


def test_catch_fixture_note_raises_when_ball_count_is_not_twenty():
    wrong = (ROOT / "tests/fixtures/gen3/firered_party_battle.sav").read_bytes()  # 4 balls
    with pytest.raises(RuntimeError, match="20 Poke Balls"):
        duo.gen3_rand_catch_note("a", "firered", "x", wrong)


def test_dependency_gate_reads_committed_sources_and_blocks_before_launch(monkeypatch):
    monkeypatch.setattr(duo, "gen3_rand_dependencies", lambda: ["CR-R1 missing", "CR-R2 missing"])
    for name in duo.GEN3_RAND_SCENARIOS:
        reason, allowed = duo.skip_reason(name, "gen3_frlg")
        assert reason == "BLOCKED: CR-R1 missing; CR-R2 missing" and not allowed
    run = object.__new__(duo.DuoRun)
    with pytest.raises(RuntimeError, match="BLOCKED: CR-R1 missing"):
        run._prepare_gen3_rand()  # no ROM lookup, server, or Popen can occur first


def test_randomized_run_artifacts_stay_under_the_worktree_build_directory(monkeypatch, tmp_path):
    # Exercise DuoRun's default BUILD path even when a release lane isolates state globally.
    monkeypatch.delenv("SLINK_STATE_DIR", raising=False)
    build = tmp_path / "patch" / "build"
    monkeypatch.setattr(duo, "BUILD", str(build))
    monkeypatch.setattr(duo, "free_port", lambda: 50000)
    run = duo.DuoRun("link_gen3_rand", SimpleNamespace(game="gen3_frlg", lane="r4"))
    assert Path(run.data_dir).is_relative_to(build) and Path(run.data_dir).is_dir()
    assert run.emus == [] and run.server is None


def test_dependency_committed_positive_missing_and_dirty_reverted(monkeypatch, tmp_path):
    sources = {"lua/gen3/entry.lua": 'Entry.BASE_KIND = {rand="clean"}; randomizable = true',
               "lua/gen3/client.lua": 'hello.rom_content = content:payload()',
               "server/adapters/gen3_frlge.py": 'def ingest_rom_content(self, payload): pass'}
    for name, text in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    def fake_git(args, **kwargs):
        if "diff" in args:   # `git diff --quiet HEAD -- <path>`: 1 when the file differs from HEAD
            return SimpleNamespace(returncode=int((tmp_path / args[-1]).read_text(encoding="utf-8") != sources[args[-1]]))
        return SimpleNamespace(returncode=0, stdout=sources[args[-1].removeprefix("HEAD:")])
    monkeypatch.setattr(duo.subprocess, "run", fake_git)
    assert duo.gen3_rand_dependencies(tmp_path) == []
    for name, label in (("lua/gen3/entry.lua", "CR-R1"), ("lua/gen3/client.lua", "CR-R2"),
                        ("server/adapters/gen3_frlge.py", "server ingest")):
        path = tmp_path / name
        path.write_text(sources[name] + "\n# uncommitted", encoding="utf-8")
        assert any(label in p and "uncommitted" in p for p in duo.gen3_rand_dependencies(tmp_path))
        path.write_text(sources[name], encoding="utf-8")
        assert duo.gen3_rand_dependencies(tmp_path) == []
        original = sources[name]
        sources[name] = "missing implementation"
        path.write_text(sources[name], encoding="utf-8")
        assert any(label in p for p in duo.gen3_rand_dependencies(tmp_path))
        sources[name] = original
        path.write_text(original, encoding="utf-8")
        assert duo.gen3_rand_dependencies(tmp_path) == []


def test_admission_driver_really_launches_other_rom_then_clean_then_correct_pair():
    run = object.__new__(duo.DuoRun)
    run._rand_inputs = {"a": {"rom": "rand_fr"}, "b": {"rom": "rand_lg"},
                        "clean_b": {"rom": "clean_lg"}}
    run._rand_current = {side: run._rand_inputs[side] for side in ("a", "b")}
    run._expected_exit = set()
    actions = []
    run._clear_attempt_artifacts = lambda: None
    run._start_gen3_rand_rule_controls = lambda: actions.append(("rule_controls",))
    run.launch_instance = lambda side, phase="initial": actions.append(
        ("launch", side, phase, run._rand_current[side]["rom"]))
    run._observe_gen3_rand_admission = lambda phase: actions.append(("observe", phase))
    run._finish_gen3_rand_negative = lambda side, phase: actions.append(("finish", side, phase))
    run._status = lambda: {"players": {"a": {"admission_reason": "cartridge matches the contract"}}}
    run.wait_for = lambda _label, predicate, _timeout: predicate()
    run._start_gen3_rand_admission()
    assert actions == [
        ("rule_controls",),
        ("launch", "a", "wrong_rom", "rand_lg"), ("observe", "wrong_rom"), ("finish", "a", "wrong_rom"),
        ("launch", "a", "initial", "rand_fr"), ("launch", "b", "mixed_kind", "clean_lg"),
        ("observe", "mixed_kind"), ("finish", "b", "mixed_kind"), ("launch", "b", "initial", "rand_lg"),
    ]


def test_ruling32_driver_uses_real_roms_and_a_fresh_server_before_the_rand_pair(tmp_path, facts):
    run = object.__new__(duo.DuoRun)
    run.data_dir = str(tmp_path)
    Path(tmp_path, "rom_contract.json").write_text("{}")
    run._rand_inputs = {key: {"rom": key} for key in ("a", "b", "forbidden_a", "equivalent_a", "clean_b")}
    run._rand_facts = facts
    run._rand_current = {side: run._rand_inputs[side] for side in ("a", "b")}
    run._expected_exit = set()
    actions = []
    run.launch_instance = lambda side, phase: actions.append(("launch", side, phase, run._rand_current[side]["rom"]))

    def observe(phase):
        actions.append(("observe", phase))
        assert Path(run.data_dir, "rom_contract.json").exists() == (phase == "rules_changed")

    run._observe_gen3_rand_admission = observe
    run._finish_gen3_rand_negative = lambda side, phase: actions.append(("passive_flash", side, phase))
    run.server = SimpleNamespace(terminate=lambda: actions.append(("stop_owned_server",)),
                                 wait=lambda **_: None)
    run.start_server = lambda: actions.append(("fresh_server",))
    run._start_gen3_rand_rule_controls()
    assert actions == [
        ("launch", "a", "rules_changed", "forbidden_a"), ("observe", "rules_changed"),
        ("passive_flash", "a", "rules_changed"),
        ("launch", "a", "equivalent", "equivalent_a"), ("launch", "b", "clean_partner", "clean_b"),
        ("observe", "equivalent_pair"), ("passive_flash", "a", "equivalent_a"),
        ("passive_flash", "b", "equivalent_b"), ("stop_owned_server",), ("fresh_server",),
    ]
    assert Path(run.data_dir).parent == tmp_path and run.data_dir != str(tmp_path)
    assert json.loads(Path(run.data_dir, "rom_contract.json").read_text()) == duo.gen3_rand_contract(facts)


@pytest.mark.parametrize("name", sorted(duo.GEN3_RAND_SCENARIOS))
def test_randomized_row_cannot_pass_without_its_live_legs(name):
    run = object.__new__(duo.DuoRun)
    run.cfg, run.scenario, run._live_complete = duo.SCENARIOS[name], name, {}
    assert not run._live_ok()
    run._live_complete[name] = True
    assert run._live_ok()
    del run._live_complete[name]
    assert not run._live_ok()


def test_admission_flush_is_the_selected_fresh_file_positive_negative_reverted(tmp_path):
    run = object.__new__(duo.DuoRun)
    selected = tmp_path / "randomized.SaveRAM"
    other = tmp_path / "clean.SaveRAM"
    selected.write_bytes(b"selected")
    other.write_bytes(b"unrelated seed")
    run._gen3_battery_path = lambda _side: str(selected)
    run._launch_times = {"a": 1000}
    os.utime(selected, (1001, 1001))
    assert run._gen3_rand_fresh_flushed("a") == b"selected"
    os.utime(selected, (999, 999))
    with pytest.raises(RuntimeError, match="no fresh flushed battery"):
        run._gen3_rand_fresh_flushed("a")
    os.utime(selected, (1001, 1001))
    assert run._gen3_rand_fresh_flushed("a") == b"selected"
    selected.unlink()
    with pytest.raises(RuntimeError, match="no fresh flushed battery"):
        run._gen3_rand_fresh_flushed("a")


@pytest.mark.parametrize("name", sorted(duo.GEN3_RAND_SCENARIOS))
def test_each_new_oracle_runs_after_its_save_witness_and_never_on_failure(name, monkeypatch):
    run = object.__new__(duo.DuoRun)
    run.game, run.gcfg, run.cfg = "gen3_frlg", duo.GAMES["gen3_frlg"], duo.SCENARIOS[name]
    run._gen3_source_dirty = []
    run._pydec_note = lambda _text: None
    calls = []
    monkeypatch.setattr(run, "check_save_witness_gen3", lambda _results: calls.append("witness"))
    monkeypatch.setattr(run, run.cfg["oracle"], lambda _results: calls.append("oracle"))
    run._run_oracle({})
    assert calls == ["witness", "oracle"]

    def failed(_results):
        raise RuntimeError("witness failed")

    calls.clear()
    monkeypatch.setattr(run, "check_save_witness_gen3", failed)
    with pytest.raises(RuntimeError, match="witness failed"):
        run._run_oracle({})
    assert calls == []
    monkeypatch.setattr(run, "check_save_witness_gen3", lambda _results: calls.append("witness"))
    run._run_oracle({})
    assert calls == ["witness", "oracle"]


def test_production_lua_collector_matches_independent_python_closure(facts):
    from tests.unit.test_gen3_rom_content_lua import collector, payload_from, symbols

    raw = _rom("firered", 1)
    _, obj, _ = collector(raw, symbols("firered", len(raw)))
    assert payload_from(obj) == facts["a"]["payload"]


def test_scenario_modules_observe_real_hello_and_propagate_link_save_failures(facts):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    observed = []
    ctx = lua.table(D=lua.table(wt=ROOT.as_posix()), phase="initial",
                    last_sent=lambda _event: lua.table_from(_hello(facts["a"]), recursive=True),
                    log=observed.append, wait_go=lambda *args: True, frames=lambda n: None,
                    writes=lambda: 0, save=lambda tag: (False, "SAVE refused"))
    admit = lua.eval("dofile")((ROOT / "lua/tests/duo/scenario_gen3_rand_admit.lua").as_posix())
    assert admit(ctx)[0] is True
    assert duo.gen3_rand_hello("\n".join(observed))["artifact_kind"] == "rand"
    panel = lua.eval("dofile")((ROOT / "lua/tests/duo/scenario_gen3_rand_trainer_panel.lua").as_posix())
    assert panel(ctx) == (False, "SAVE refused")
    link = lua.eval("dofile")((ROOT / "lua/tests/duo/scenario_gen3_rand_link.lua").as_posix())
    ctx.catch = lambda _label: (None, "no catch")
    assert link(ctx) == (False, "hunt ended no catch")
    ctx.last_sent = lambda _: lua.table_from(_hello(facts["a"], "clean"), recursive=True)
    assert admit(ctx)[0] is False


@pytest.mark.parametrize("title,label", (("firered", "FireRed"), ("leafgreen", "LeafGreen")))
def test_real_upr_tables_and_live_server_adapter_probe(title, label, tmp_path):
    from server.server import SLinkServer
    from tests.unit.test_gen3_rom_content_lua import collector, payload_from, symbols
    from tools.gen3_final_cut import STAGED, rom_pins

    clean = ROOT / STAGED[title]
    if not clean.is_file():
        pytest.skip(f"pinned clean {title} ROM absent")
    assert hashlib.sha1(clean.read_bytes()).hexdigest() == rom_pins(str(ROOT))[title]
    if duo.GEN3_RAND_SCRATCH is None:
        pytest.skip("SLINK_GEN3_RAND_ROMS is not set (randomized ROMs are never committed)")
    path = duo.GEN3_RAND_SCRATCH / f"{label}_allowed.gba"
    if not path.is_file():
        pytest.skip(f"UPR scratch {label}_allowed.gba absent")
    raw = path.read_bytes()
    fact = duo.gen3_rand_rom_facts(raw, title)
    _, obj, _ = collector(raw, symbols(title, len(raw)))
    payload = payload_from(obj)
    assert payload == fact["payload"]
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.state.rom_type, srv.state.artifact_kind = title, "rand"
    srv.connected_players["a"] = {"rom_type": title}
    srv.player_area_id["a"] = "viridian_forest"
    srv._ingest_rom_content("a", payload)
    partner_title, partner_label = ("leafgreen", "LeafGreen") if title == "firered" else ("firered", "FireRed")
    partner_path = duo.GEN3_RAND_SCRATCH / f"{partner_label}_allowed.gba"
    if not partner_path.is_file():
        pytest.skip(f"UPR scratch {partner_label}_allowed.gba absent")
    partner_raw = partner_path.read_bytes()
    partner_fact = duo.gen3_rand_rom_facts(partner_raw, partner_title)
    srv.connected_players["b"] = {"rom_type": partner_title}
    srv.player_area_id["b"] = "viridian_forest"
    srv._ingest_rom_content("b", partner_fact["payload"])
    probes = duo.gen3_rand_status_probe(srv, {})["gen3_rand_probe"]
    probe = probes["a"]
    assert probe["briefs"], "server did not expose the real nearby per-ROM briefs"
    expected = fact["trainer_parties"][102]
    assert [m["level"] for m in probe["briefs"]["102"]["party"]] == [m["level"] for m in expected]
    assert probe["calc_labels"]["102"] == ""
    retail = json.loads((ROOT / "data/games/gen3_frlge/frlg_trainers.json").read_text())["trainers"]
    case = {"probes": probes, "retail": retail, "expected_area": "viridian_forest"}
    both = {"a": fact, "b": partner_fact}
    _revert_checked(case, lambda c: duo.gen3_rand_panel_problems(facts=both, **c),
                    lambda c: c["probes"]["a"].update(briefs=copy.deepcopy(c["probes"]["b"]["briefs"])),
                    "OWN ROM")
