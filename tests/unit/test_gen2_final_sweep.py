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
    assert sum(i.startswith("gate/") for i in ids) == 3 + 2 + 12 + 1
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
