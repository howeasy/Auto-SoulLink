"""E-RAND-LIVE oracle falsifiers; these tests never launch an emulator."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import e2e_duo as duo  # noqa: E402


@pytest.fixture(scope="module")
def cartridges():
    folder = os.environ.get("SLINK_GEN3_RAND_ROMS")
    if not folder:
        pytest.skip("set SLINK_GEN3_RAND_ROMS for E-RAND-LIVE cartridge controls")
    from tools.gen3_final_cut import STAGED, rom_pins

    # absent input = named skip; present-but-wrong = fail (tests/TESTING.md)
    staged = ROOT / STAGED["emerald"]
    if not staged.is_file():
        pytest.skip(f"staged clean Emerald dump absent: {staged}")
    names = ("Emerald_allowed.gba", "Emerald_allowed_b.gba", "Emerald_widest.gba")
    missing = [n for n in names if not (Path(folder) / n).is_file()]
    if missing:
        pytest.skip(f"randomized Emerald ROMs absent from SLINK_GEN3_RAND_ROMS: {missing}")
    clean = staged.read_bytes()
    assert hashlib.sha1(clean).hexdigest() == rom_pins(str(ROOT))["emerald"]
    return {"a": (Path(folder) / "Emerald_allowed.gba").read_bytes(),
            "b": (Path(folder) / "Emerald_allowed_b.gba").read_bytes(),
            "widest": (Path(folder) / "Emerald_widest.gba").read_bytes(), "clean": clean}


@pytest.fixture(scope="module")
def facts(cartridges):
    return {side: duo.gen3_rand_rom_facts(raw, "emerald") for side, raw in cartridges.items()}


def test_emerald_admission_dispatches_the_real_multi_cartridge_controls():
    name = "admit_randomized_emerald"
    assert "gen3_emerald" in duo.SCENARIOS[name]["games"]
    assert "gen3_emerald" in duo.SCENARIOS["trainer_panel_gen3_rand"]["games"]
    run = object.__new__(duo.DuoRun)
    run.scenario = name
    calls = []
    run._start_gen3_rand_admission = lambda: calls.append("actual cartridge controls")
    run.start_instances()
    assert calls == ["actual cartridge controls"]
    assert duo.scenario_attempt_limit(name, "gen3_emerald") == 1


def test_emerald_preparation_keeps_distinct_seeds_and_all_negative_controls(monkeypatch, tmp_path, cartridges):
    from tools import gen3_final_cut as cut

    pins = cut.rom_pins(str(ROOT))
    staged = tmp_path / cut.STAGED["emerald"]
    staged.parent.mkdir(parents=True)
    staged.write_bytes(cartridges["clean"])
    monkeypatch.setattr(duo, "REPO", str(tmp_path))
    monkeypatch.setattr(duo, "BUILD", str(staged.parent))
    monkeypatch.setattr(duo, "gen3_rand_dependencies", lambda: [])
    monkeypatch.setattr(cut, "rom_pins", lambda _: pins)
    monkeypatch.delenv("SLINK_STATE_DIR", raising=False)
    # patch-first: every randomized cartridge launches WITH the published companion overlay, and the plain
    # companion (byte-pinned build) is the mixed-kind / clean-equivalent partner
    from tools.gen3_companions import overlay_randomized, published

    patched, _row = published("emerald", cartridges["clean"])
    companion = staged.parent / "slink_Emerald_pinned.gba"
    companion.write_bytes(patched)
    overlay = lambda raw: hashlib.sha1(overlay_randomized("emerald", cartridges["clean"], raw)).hexdigest()  # noqa: E731
    run = duo.DuoRun("admit_randomized_emerald", SimpleNamespace(game="gen3_emerald", lane="e-rand-test"))
    run._pydec_note = lambda _: None
    run._gen3_companion_rom = lambda title: companion.relative_to(tmp_path).as_posix()
    run._prepare_gen3_rand()
    got = run._rand_facts
    assert got["a"]["sha1"] == overlay(cartridges["a"])
    assert got["b"]["sha1"] == overlay(cartridges["b"])
    assert got["companion_b"]["sha1"] == hashlib.sha1(patched).hexdigest()
    assert got["a"]["content_fingerprint"] != got["b"]["content_fingerprint"]
    assert got["forbidden_a"]["sha1"] == overlay(cartridges["widest"])
    assert run._rand_inputs["clean_b"]["expect_refused"] is True
    assert got["equivalent_a"]["sha1"] not in (got["clean_a"]["sha1"], got["companion_b"]["sha1"])
    assert got["equivalent_a"]["payload"] == got["clean_a"]["payload"]
    assert json.loads(Path(run.data_dir, "rom_contract.json").read_text()) == duo.gen3_rand_contract(got)


def test_emerald_anchor_preflight_checks_the_emerald_pack(cartridges):
    for raw in cartridges.values():
        assert duo.gen3_rand_site_problems(raw, "emerald") == []
    signals = json.loads((ROOT / "data/games/gen3_emerald/engine_signals.json").read_text())
    site = signals["titles"]["emerald"]["artifacts"]["clean"]["sites"]["battle_begin"]
    bad = bytearray(cartridges["a"])
    bad[site["rom_offset"]] ^= 1
    assert any("battle_begin" in error for error in duo.gen3_rand_site_problems(bad, "emerald"))
    assert duo.gen3_rand_site_problems(cartridges["a"], "emerald") == []


@pytest.fixture
def live_projection(tmp_path, facts):
    from server.server import SLinkServer

    server = SLinkServer(data_dir=str(tmp_path))
    server.state.rom_type, server.state.artifact_kind = "emerald", "rand"
    for side in ("a", "b"):
        server.connected_players[side] = {"rom_type": "emerald"}
        server.player_area_id[side] = "route_102"
        server._ingest_rom_content(side, facts[side]["payload"])
    return duo.gen3_rand_status_probe(server, {})["gen3_rand_probe"]


@pytest.mark.parametrize("fault", ("swapped", "retail", "level", "missing"))
def test_emerald_nearby_trainer_oracle_positive_negative_restored(live_projection, facts, fault):
    retail = json.loads((ROOT / "data/games/gen3_emerald/emerald_trainers.json").read_text())["trainers"]
    def check(probes):
        return duo.gen3_rand_panel_problems(probes, facts, retail, expected_area="route_102")
    assert check(live_projection) == []
    bad = copy.deepcopy(live_projection)
    tid = next(iter(bad["a"]["briefs"]))
    if fault == "swapped":
        bad["a"]["briefs"] = copy.deepcopy(bad["b"]["briefs"])
    elif fault == "retail":
        bad["a"]["briefs"][tid]["party"] = retail[tid]["party"]
    elif fault == "level":
        bad["a"]["briefs"][tid]["party"][0]["level"] += 1
    else:
        bad["a"]["briefs"].pop(tid)
    assert check(bad)
    assert check(live_projection) == []


def test_emerald_admission_requires_the_live_encounter_projection(live_projection, facts):
    status = {"gen3_rand_probe": live_projection, "gen3_rand_effective_kind": "rand",
              "gen3_rand_identity_errors": {}, "players": {
                  side: {"connected": True, "admission": "admitted",
                         "admission_reason": "cartridge matches the contract"} for side in ("a", "b")}}
    hellos = {side: {"artifact_kind": "rand", "rom_type": "emerald", "rom_sha1": facts[side]["sha1"],
                     "rom_content": facts[side]["payload"]} for side in ("a", "b")}
    assert duo.gen3_rand_admission_problems("pair", status, hellos, facts) == []
    del status["gen3_rand_probe"]
    assert any("encounter" in p for p in duo.gen3_rand_admission_problems("pair", status, hellos, facts))


def test_emerald_encounter_oracle_does_not_trust_the_shared_decoder(live_projection, facts):
    altered = copy.deepcopy(facts)
    altered["a"]["tables"]["wild_encounters"][(0, 17)][0]["land"]["mons"][0]["min_level"] = 99
    live_projection["a"]["encounters"]["Grass"][0]["min_level"] = 99
    assert any("OWN ROM" in p for p in duo.gen3_rand_encounter_problems(live_projection, altered))


@pytest.mark.parametrize("fault", ("swapped", "retail", "rate", "level", "missing", "area"))
def test_emerald_encounters_are_checked_against_independent_rom_bytes(live_projection, facts, fault):
    def check(probes):
        return duo.gen3_rand_encounter_problems(probes, facts)
    assert check(live_projection) == []
    bad = copy.deepcopy(live_projection)
    if fault == "swapped":
        bad["a"]["encounters"] = copy.deepcopy(bad["b"]["encounters"])
    elif fault == "retail":
        from server.adapters.gen3_frlge import Gen3Adapter
        retail = Gen3Adapter(rom_type="emerald")
        retail.use_rom_encounters(retail.ingest_rom_content(facts["clean"]["payload"]))
        bad["a"]["encounters"] = retail.encounter_table("route_102")
    elif fault in ("rate", "level"):
        bad["a"]["encounters"]["Grass"][0]["rate" if fault == "rate" else "min_level"] += 1
    elif fault == "missing":
        bad["a"]["encounters"] = None
    else:
        bad["a"]["encounter_area"] = "route_103"
    assert check(bad)
    assert check(live_projection) == []
