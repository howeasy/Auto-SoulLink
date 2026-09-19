"""Lane isolation for `tools/e2e_duo.py`, and the pureRGB pairing row (P3b-e).

Two DuoRuns in ONE process must share no generated stub, no BizHawk config copy, no SaveRAM
directory and no window position — docs/purergb/research/p3/harness_literals_bbcd037.md table 3.
The stub is the worst of them: it bakes SLINK_PORT, so a collision makes the loser's emulator talk
to the winner's server, and the config copy carries that instance's SaveRAM directory and the window
pin. The receipts stay per scenario+instance ON PURPOSE (the admission scenarios write those names
themselves), which is stated here so a future lane id refactor knows it was a decision.

No emulator: `launch_instance` runs with `subprocess.Popen` recorded and BUILD pointed at a tmp dir.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import e2e_duo as duo  # noqa: E402
import gen1_playthrough as g1  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_lane_registry(monkeypatch):
    """The lane ordinal is process state; a fresh table keeps each test's expectation local."""
    monkeypatch.setattr(duo, "_LANE_ORDINAL", {})


def _args(**overrides) -> argparse.Namespace:
    base = {"game": "gen1_new", "lane": None, "scenario": "link_new", "idle_jitter": 0}
    base.update(overrides)
    return argparse.Namespace(**base)


def _run(monkeypatch, tmp_path, **overrides):
    """A DuoRun that writes everything under tmp_path and launches nothing."""
    monkeypatch.setattr(duo, "BUILD", str(tmp_path))
    monkeypatch.setattr(duo, "BIZHAWK_CONFIG", str(_config_file(tmp_path)))
    launched = []
    monkeypatch.setattr(duo.subprocess, "Popen", lambda argv, **kw: launched.append(argv))
    run = duo.DuoRun("link_new", _args(**overrides), attempt=1)
    run.launched = launched
    return run


def _config_file(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(json.dumps({
        "SoundEnabled": True,
        "MainWindowPosition": "1200, -1300",
        "CoreSyncSettings": {"BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy": {}},
        # write_run_config refuses to redirect SaveRAM without these rows (it would let two
        # instances of one cartridge share a file), so a stand-in config must carry them.
        "PathEntries": {"Paths": [
            {"System": system, "Type": "Save RAM", "Path": ""}
            for system in ("GB_GBC_SGB", "GBL")
        ]},
    }), encoding="utf-8")
    return path


def _launch_both(run):
    for inst in ("a", "b"):
        run.launch_instance(inst, seed=False)
    return run.launched


def test_two_runs_in_one_process_share_no_stub_config_or_window(monkeypatch, tmp_path):
    """The lane id keys the generated stub and the config copy; the window moves with it."""
    # One run at a time: each `_run` installs its own Popen recorder, so a run's launches have to
    # happen while its patch is the active one.
    one = _run(monkeypatch, tmp_path)
    _launch_both(one)
    two = _run(monkeypatch, tmp_path)
    _launch_both(two)

    def _named(argv, flag, inst, ext):
        return next(a for a in argv if a.startswith(flag) and a.endswith(f"_{inst}.{ext}"))

    for inst in ("a", "b"):
        index = 0 if inst == "a" else 1
        a_stub = _named(one.launched[index], "--lua=", inst, "lua")
        b_stub = _named(two.launched[index], "--lua=", inst, "lua")
        a_cfg = _named(one.launched[index], "--config=", inst, "ini")
        b_cfg = _named(two.launched[index], "--config=", inst, "ini")
        assert a_stub != b_stub, (inst, a_stub)
        assert a_cfg != b_cfg, (inst, a_cfg)
        assert str(one.lane) in a_stub and str(two.lane) in b_stub

    positions = []
    for run in (one, two):
        for inst in ("a", "b"):
            with open(os.path.join(str(tmp_path), f"duo_cfg_{run.lane}_{inst}.ini"),
                      encoding="utf-8-sig") as handle:
                positions.append(json.load(handle)["MainWindowPosition"])
    assert len(set(positions)) == 2, positions          # one slot per lane, both instances aligned


def test_two_runs_keep_separate_saveram_directories(monkeypatch, tmp_path):
    one = _run(monkeypatch, tmp_path)
    two = _run(monkeypatch, tmp_path)
    assert one._saveram_dir("a") != two._saveram_dir("a")
    assert one._saveram_dir("a") != one._saveram_dir("b")
    for run in (one, two):
        for inst in ("a", "b"):
            assert str(run.lane) in run._saveram_dir(inst)


def test_a_lane_keeps_the_receipt_names_it_always_had(monkeypatch, tmp_path):
    """Receipts and go-files are per scenario+instance BY DESIGN: the admission scenarios write
    those exact names (`e2e_admit_randomized_new_{a,b}_result.txt` in test_e2e_duo_admission.py),
    and every launch removes its own receipt first, so a lane cannot inherit a stale verdict.
    Two lanes on the SAME scenario would still race on them — see the module docstring."""
    run = _run(monkeypatch, tmp_path)
    assert run._result_path("a") == os.path.join(str(tmp_path), "e2e_link_new_a_result.txt")
    assert run._phase_result_path("a", "reconnect") == os.path.join(
        str(tmp_path), "e2e_link_new_a_reconnect_result.txt")
    assert run.go_files["a"] == os.path.join(str(tmp_path), "duo_go_link_new_a.txt")


def test_the_lane_id_defaults_to_the_free_port_and_can_be_named(monkeypatch, tmp_path):
    default = _run(monkeypatch, tmp_path)
    assert default.lane == str(default.tcp_port)
    named = _run(monkeypatch, tmp_path, lane="pure-a")
    assert named.lane == "pure-a" and named.lane_index != default.lane_index


def test_the_window_offset_leaves_lane_zero_and_primary_alone(monkeypatch, tmp_path):
    monkeypatch.setenv("SLINK_EMU_WINDOW", "1200,-1300")
    first = _run(monkeypatch, tmp_path, lane="lane-zero")
    assert first.lane_index == 0
    assert first._lane_window() is None                  # lane 0 is what write_run_config wrote
    second = _run(monkeypatch, tmp_path, lane="lane-one")
    assert second.lane_index == 1
    assert second._lane_window() == f"{1200 + duo._LANE_WINDOW_STEP}, -1300"
    monkeypatch.setenv("SLINK_EMU_WINDOW", "primary")
    assert second._lane_window() is None


# ── the pureRGB pairing row ─────────────────────────────────────────────────────────────────────


def test_the_pure_pairing_row_names_the_staged_builds_and_its_fixtures():
    row = duo.GAMES["gen1_pure"]
    assert row["main"] == duo.GAMES["gen1_new"]["main"]      # same driver, same scenarios
    assert row["game"] == "gen1_new"                         # the scenario registry selects on this
    assert row["uses_savestate"] is False
    assert row["fixture"] == {"a": "purered", "b": "pureblue"}
    for inst, key in row["fixture"].items():
        assert g1.is_purergb(key), key
        assert row["rom"][inst] == os.path.join("patch", "build", f"gen1_{key}.gbc").replace("\\", "/")
        assert g1.fixture_path(key, "town").endswith(f"{key}_town.SaveRAM")


def test_the_runner_stages_a_battery_boot_rom_through_its_play_module():
    """`_rom_for` is what the launch line uses: for the vanilla rows it returns the GAMES path
    (staged_rom resolves the same string), and for a pure row it stages from the source lock."""
    run = duo.DuoRun("link_new", _args(game="gen1_pure"), attempt=1)
    try:
        assert run._rom_for("a") == "patch/build/gen1_purered.gbc"
    except FileNotFoundError as exc:
        pytest.skip(f"pureRGB builds not staged here: {exc}")


def test_a_scenario_that_stages_its_own_rom_wins(monkeypatch, tmp_path):
    run = _run(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "_admit_roms",
                        {"a": "patch/build/e2e_admit_randomized_new/a.gb",
                         "b": "patch/build/gen1_blue.gb"}, raising=False)
    assert run._rom_for("a") == "patch/build/e2e_admit_randomized_new/a.gb"
    assert run._rom_for("b") == "patch/build/gen1_blue.gb"


# ── the pureRGB companion OVERLAY pairing row (PLAN M3/P4) ────────────────────────────────────────


def test_the_overlay_pairing_row_reuses_the_clean_pure_fixture_and_overrides_the_trade_key():
    row = duo.GAMES["gen1_pure_overlay"]
    assert row["main"] == duo.GAMES["gen1_new"]["main"]
    assert row["game"] == "gen1_new"
    assert row["not_yet"] == ()                              # M3: every scenario runs here
    assert row["uses_savestate"] is False
    assert row["fixture"] == {"a": "purered", "b": "pureblue"}   # A4: the clean pure fixture
    assert row["patched_saves_override"] == {"a": "purered_overlay", "b": "pureblue_overlay"}
    for key in row["fixture"].values():
        assert g1.is_purergb(key) and not g1.is_purergb_overlay(key)
    for key in row["patched_saves_override"].values():
        assert g1.is_purergb_overlay(key)


def test_the_overlay_row_runs_all_18_scenarios_including_the_three_trade_ones():
    all_ = duo.scenarios_for("gen1_pure_overlay")
    clean = duo.scenarios_for("gen1_pure")
    assert set(all_) - set(clean) == {"trade_new", "trade_decline_new", "explode_new"}
    assert len(all_) == 18


def test_a_trade_scenario_on_the_overlay_row_stages_the_overlay_cartridge_not_the_vanilla_one(monkeypatch):
    """trade_new's SCENARIO dict hardcodes `patched_saves` to the vanilla red_patched/
    blue_patched keys (it predates any second foundation); `_patch_key`/`_rom_for` must read the
    overlay row's own `patched_saves_override` instead -- the whole mechanism that lets the three
    trade scenarios run here without touching SCENARIOS at all."""
    run = duo.DuoRun("trade_new", _args(game="gen1_pure_overlay", scenario="trade_new"), attempt=1)
    assert run._patch_key("a") == "purered_overlay"
    assert run._patch_key("b") == "pureblue_overlay"
    monkeypatch.setattr(g1, "staged_rom", lambda key: f"STAGED:{key}")
    assert run._rom_for("a") == "STAGED:purered_overlay"
    assert run._rom_for("b") == "STAGED:pureblue_overlay"


def test_a_non_trade_scenario_on_the_overlay_row_stages_the_clean_pure_cartridge(monkeypatch):
    """link_new carries no `patched_saves`, so the override never applies: A4 says the clean and
    overlay cartridges are behaviourally identical outside native trade, so the rules-only
    scenarios stage the SAME clean build gen1_pure does."""
    run = duo.DuoRun("link_new", _args(game="gen1_pure_overlay"), attempt=1)
    assert run._patch_key("a") is None
    try:
        assert run._rom_for("a") == "patch/build/gen1_purered.gbc"
    except FileNotFoundError as exc:
        pytest.skip(f"pureRGB builds not staged here: {exc}")
