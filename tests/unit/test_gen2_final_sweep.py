"""tools/gen2_final_sweep.py: the cell list and the receipt naming, no emulator."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import gen2_final_sweep as sweep  # noqa: E402


def test_every_release_cell_is_listed_once():
    ids = [c["id"] for c in sweep.cells()]
    assert len(ids) == len(set(ids))
    assert sum("/gen2_trade_" in i for i in ids) == 21
    assert sum(i.startswith("gate/") for i in ids) == 3 + 2 + 15 + 1
    assert {"gen2_new/gen2_faint_active_trainer", "gen2_gold_silver/gen2_faint_active_trainer", "gate/w6/silver",
            "gate/inspect_run"} <= set(ids)
    assert "gen2_crystal_gold/gen2_faint_active_trainer" not in ids


def test_duo_outputs_take_the_committed_receipt_names(tmp_path):
    build = tmp_path / "lane/patch/build"
    build.mkdir(parents=True)
    for suffix in ("a_result.txt", "pydec_result.txt", "a_witness.SaveRAM", "a_attempt1_result.txt", "a_link_save.SaveRAM"):
        (build / f"e2e_gen2_faint_s31_{suffix}").write_bytes(b"x\r\n")
    cell = {"scenario": "gen2_faint", "pair": "gs"}
    got = sweep.collect_duo(cell, "s31", tmp_path / "lane", tmp_path / "out")
    root = "tests/fixtures/gen2/receipts/duo_faint_gs_"
    assert sorted(got) == [root + "a_result.txt", root + "a_witness.SaveRAM", root + "pydec_result.txt"]
    assert got[root + "a_result.txt"] != got[root + "a_witness.SaveRAM"]   # LF-normalized text only


def test_pin_installs_pass_receipts_repins_in_place_and_adds_the_inspect_row(tmp_path):
    repo, out = tmp_path / "repo", tmp_path / "out"
    rel, bad = "tests/fixtures/gen2/receipts/duo_link_cc_a_result.txt", "tests/fixtures/gen2/receipts/x_result.txt"
    for path in (rel, bad, sweep.ATTESTATION):
        (out / "receipts" / path).parent.mkdir(parents=True, exist_ok=True)
        (out / "receipts" / path).write_text("new\n", encoding="utf-8")
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
    release = '{\n  "proofs": [{"a": {\n    "path": "' + rel + '",\n    "sha256": "' + "0" * 64 + '"\n  }}]\n}\n'
    (repo / sweep.PIN_FILES[0]).write_text(release, encoding="utf-8")
    (repo / sweep.PIN_FILES[1]).write_text('{\n  "requirements": [\n    {"id": "x"}\n  ]\n}\n', encoding="utf-8")
    cells = [{"ok": True, "receipts": {rel: "a" * 64, sweep.ATTESTATION: "b" * 64}},
             {"ok": False, "receipts": {bad: "c" * 64}}]
    (out / "summary.json").write_text(json.dumps({"cells": cells}), encoding="utf-8")
    assert sweep.pin(out, root=repo) == []
    assert (repo / sweep.PIN_FILES[0]).read_text(encoding="utf-8") == release.replace("0" * 64, "a" * 64)
    rows = json.loads((repo / sweep.PIN_FILES[1]).read_text(encoding="utf-8"))["requirements"]
    assert rows[-1]["axes"]["kind"] == "inspect_run"
    assert rows[-1]["proofs"][0]["receipts"]["receipt"] == {"path": sweep.ATTESTATION, "sha256": "b" * 64}
    assert (repo / rel).read_text(encoding="utf-8") == "new\n" and not (repo / bad).exists()   # FAIL cells stay out


@pytest.mark.parametrize("counts,titles,ok", [
    ({}, dict.fromkeys(("crystal", "gold", "silver"), "PASS"), True),
    ({"skipped": 1}, dict.fromkeys(("crystal", "gold", "silver"), "PASS"), False),
    ({}, {"crystal": "PASS", "gold": "PASS"}, False),
])
def test_the_attestation_the_live_conftest_writes_is_what_the_verifier_accepts(counts, titles, ok):
    from tests.live import conftest
    from tools import verify_gen2_release as gate

    record = conftest.attestation({**dict.fromkeys(conftest.COUNTS, 0), "passed": 13, **counts}, titles,
                                  {"schema": "gen2-code-digest-v1"})
    assert (record["result"] == "PASS") is ok and (gate._inspect_run_row_errors(record) == []) is ok
    assert record["code_digest"] == {"schema": "gen2-code-digest-v1"}


def test_live_conftest_buckets_like_pytest():
    from types import SimpleNamespace as R

    from tests.live.conftest import outcome

    assert outcome(R(skipped=False, failed=False, when="call")) == "passed"
    assert outcome(R(skipped=True, failed=False, when="setup")) == "skipped"
    assert outcome(R(skipped=False, failed=True, when="setup")) == "errors"
    assert outcome(R(skipped=False, failed=True, when="call")) == "failed"
    assert outcome(R(skipped=True, failed=False, when="call", wasxfail="")) == "xfailed"
    assert outcome(R(skipped=False, failed=False, when="teardown")) is None


def test_a_cell_stops_at_its_first_failing_command_and_keeps_each_gate_result(tmp_path, monkeypatch):
    lane, log = tmp_path / "lane", tmp_path / "logs/gate__engine_sites__gold.log"
    (lane / "patch/build").mkdir(parents=True)
    log.parent.mkdir()
    calls = []

    def fake_run(cmd, cwd, timeout, path):
        calls.append(cmd)
        (cwd / "patch/build/gen2_frame_align_result.txt").write_text(f"trace of {cmd[0]}", encoding="utf-8")
        return {"first": 1, "second": 0}[cmd[0]]

    monkeypatch.setattr(sweep, "run", fake_run)
    assert sweep.run_commands([["first"], ["second"]], lane, 60, log) == [1]
    assert calls == [["first"]]   # the second command never overwrites the failing trace
    kept = log.with_name("gate__engine_sites__gold.cmd1.gen2_frame_align_result.txt")
    assert kept.read_text(encoding="utf-8") == "trace of first"


def test_only_rng_stalls_earn_the_one_retry():
    for text in ("RESULT: FAIL (hunt ended out-of-balls)",
                 "RESULT: FAIL (poison route failed: the trainer battle ended without a poisoned party mon)",
                 "[FAIL] poison_faint did not fire after the previous expected site"):
        assert sweep.RNG_STALL.search(text), text
    for text in ("trade: stack canary is not a real push", "no memorialize ack for the released partner X",
                 "wave-c: b: a rebuilt mon is not at full HP", "LostBattle ran (a whiteout)"):
        assert not sweep.RNG_STALL.search(text), text


def test_pin_gives_the_reconnect_initial_phase_the_committed_a_name(tmp_path):
    repo, out = tmp_path / "repo", tmp_path / "out"
    stem = "tests/fixtures/gen2/receipts/duo_reconnect_cc_"
    for suffix, text in (("a_result.txt", "wrong_save relaunch\n"), ("a_initial_result.txt", "initial phase\n")):
        (out / "receipts" / (stem + suffix)).parent.mkdir(parents=True, exist_ok=True)
        (out / "receipts" / (stem + suffix)).write_text(text, encoding="utf-8")
    (repo / stem).parent.mkdir(parents=True)
    (repo / sweep.PIN_FILES[0]).parent.mkdir(parents=True, exist_ok=True)
    (repo / sweep.PIN_FILES[0]).write_text(
        '{"a": {"path": "' + stem + 'a_result.txt", "sha256": "' + "0" * 64 + '"}}\n', encoding="utf-8")
    (repo / sweep.PIN_FILES[1]).write_text('{\n  "requirements": [\n  ]\n}\n', encoding="utf-8")
    cells = [{"ok": True, "receipts": {stem + "a_result.txt": "1" * 64, stem + "a_initial_result.txt": "2" * 64}}]
    (out / "summary.json").write_text(json.dumps({"cells": cells}), encoding="utf-8")
    assert sweep.pin(out, root=repo) == []
    assert (repo / (stem + "a_result.txt")).read_text(encoding="utf-8") == "initial phase\n"
    assert not (repo / (stem + "a_initial_result.txt")).exists()
    assert '"sha256": "' + "2" * 64 + '"' in (repo / sweep.PIN_FILES[0]).read_text(encoding="utf-8")


def test_only_the_sweep_attests_a_verification_lane_run_never_does(tmp_path, monkeypatch):
    from tests.live import conftest
    from tools import verify_gen2_release as gate

    lane = next(lane for lane in gate.LANES if lane.name == "live-new-gates")
    assert lane.env.get("SLINK_GEN2_NO_ATTEST") == "1" and lane.env.get("SLINK_LIVE") == "1"
    monkeypatch.setattr(conftest, "REPO", tmp_path)
    (tmp_path / sweep.ATTESTATION).parent.mkdir(parents=True)
    monkeypatch.setitem(conftest._run, "seen", True)
    monkeypatch.setenv("SLINK_LIVE", "1")
    monkeypatch.setenv("SLINK_GEN2_NO_ATTEST", "1")
    conftest.pytest_sessionfinish(None, 0)
    assert not (tmp_path / sweep.ATTESTATION).exists()   # the lane re-proves, the pin stays
    seen = {}
    monkeypatch.setattr(sweep.subprocess, "Popen", lambda cmd, cwd, env, stdout, stderr: seen.update(env) or
                        type("P", (), {"wait": lambda self, timeout: 0})())
    sweep.run(["x"], tmp_path, 1, tmp_path / "run.log")
    assert "SLINK_GEN2_NO_ATTEST" not in seen and seen["SLINK_LIVE"] == "1"   # the sweep's cell attests
