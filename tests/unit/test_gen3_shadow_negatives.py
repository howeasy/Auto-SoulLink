"""Expected-zero receipt checks, including mutations and shared normalization."""
from __future__ import annotations

import json

import pytest

from tools.gen3_shadow_negatives import DEFAULT_MANIFEST, REPO, check_manifest, load_manifest, main


def manifest(tmp_path, kind="faint", scope="observer"):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": 1, "receipts": [{
        "file": "receipt.log", "artifact": "test", "scope": scope,
        "why": "synthetic:1: controlled test", "must_not": [
            {"kind": kind, "why": "synthetic:1: this operation is forbidden"}],
    }]}), encoding="utf-8")
    return path


def test_forbidden_kind_fails_and_reports_positives(tmp_path, capsys):
    path = manifest(tmp_path)
    (tmp_path / "receipt.log").write_text(
        "SHADOW t=1 frame=10 kind=faint key=x\n", encoding="utf-8")
    report = check_manifest(path, tmp_path)
    assert not report["passed"]
    assert report["receipts"][0]["positives"] == {"faint": 1}
    assert main([str(path), "--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "EXPECTED-ZERO FAIL" in output
    assert "faint count=1" in output
    assert "SUMMARY FAIL receipts=1 checks=1 passed=0 failed=1" in output


def test_missing_file_fails(tmp_path):
    report = check_manifest(manifest(tmp_path), tmp_path)
    assert not report["passed"]
    assert report["receipts"][0]["errors"]
    assert not report["receipts"][0]["rows"][0]["passed"]


@pytest.mark.parametrize("raw", ["pc_deposit", "pc_release_begin"])
def test_raw_pc_sites_cannot_escape_semantic_negative(tmp_path, raw):
    path = manifest(tmp_path, "pc_move")
    (tmp_path / "receipt.log").write_text(
        f"SHADOW t=1 frame=10 kind={raw} key=x\n", encoding="utf-8")
    row = check_manifest(path, tmp_path)["receipts"][0]["rows"][0]
    assert not row["passed"]
    assert row["count"] == 1


def test_nonforbidden_positive_passes(tmp_path, capsys):
    path = manifest(tmp_path)
    (tmp_path / "receipt.log").write_text(
        "SHADOW t=1 frame=10 kind=save key=\n", encoding="utf-8")
    assert main([str(path), "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["receipts"][0]["positives"] == {"save": 1}


def test_malformed_record_fails(tmp_path):
    path = manifest(tmp_path)
    (tmp_path / "receipt.log").write_text("SHADOW kind=faint\n", encoding="utf-8")
    assert not check_manifest(path, tmp_path)["passed"]


def test_predicate_log_cannot_hide_liveness_line(tmp_path):
    path = manifest(tmp_path, scope="log_format_only")
    (tmp_path / "receipt.log").write_text(
        "SHADOW t=1 frame=1 kind=frame_control key=\n", encoding="utf-8")
    assert not check_manifest(path, tmp_path)["passed"]


def test_invalid_manifest_fails(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"schema": 1, "receipts": []}', encoding="utf-8")
    assert main([str(path)]) == 1
    assert "nonempty receipts" in capsys.readouterr().out


def test_real_manifest_against_committed_receipts():
    entries = load_manifest(DEFAULT_MANIFEST)
    missing = [entry["file"] for entry in entries if not (REPO / entry["file"]).is_file()]
    assert not missing, "committed receipt absent in this checkout: " + ", ".join(missing)
    report = check_manifest(DEFAULT_MANIFEST)
    assert report["passed"], report
    assert report["summary"] == {"receipts": 10, "checks": 79, "passed": 79, "failed": 0}
    assert all(row["count"] == 0 for result in report["receipts"] for row in result["rows"])
    by_file = {result["file"]: result["positives"] for result in report["receipts"]}
    assert by_file["docs/gen3/probes/shadow_rr_play_r5d_pc_ops_2026-09-21.shadow.log"] == {
        "pc_move": 4, "save": 1,
    }
    assert by_file["docs/gen3/probes/shadow_fr_play_run17_2026-09-21.shadow.log"] == {
        "battle_begin": 8, "battle_end": 7, "map_load": 8, "mon_given": 1,
    }
    assert by_file["docs/gen3/probes/shadow_rr_play_r5_2026-09-21.shadow.log"] == {
        "battle_begin": 4, "battle_end": 7, "capture_wild": 1, "faint": 6, "map_load": 1, "mon_given": 1, "whiteout": 1,
    }
    assert by_file["docs/gen3/probes/shadow_rr_faint_2026-09-21.txt"] == {
        "battle_begin": 4, "battle_end": 5, "faint": 5, "map_load": 1, "whiteout": 1,
    }
    assert by_file["docs/gen3/probes/shadow_fr_play_2026-09-21.txt"] == {
        "map_load": 1,
    }
    assert by_file["docs/gen3/probes/shadow_rr_play_r6_pc_release_2026-09-22.shadow.log"] == {
        "pc_move": 5, "save": 1,
    }
    assert by_file["docs/gen3/probes/shadow_fr_play_run18_2026-09-21.shadow.log"] == {
        "battle_begin": 8, "battle_end": 8, "faint": 1, "map_load": 8, "mon_given": 1, "whiteout": 1,
    }
    assert by_file["docs/gen3/probes/shadow_fr_play_run19_2026-09-22.shadow.log"] == {
        "battle_begin": 2, "battle_end": 2, "faint": 1, "map_load": 1, "whiteout": 1,
    }


def test_empty_observer_receipt_fails(tmp_path):
    """Verify that empty observer receipts produce an error."""
    path = manifest(tmp_path)
    (tmp_path / "receipt.log").write_text("", encoding="utf-8")
    report = check_manifest(path, tmp_path)
    assert not report["passed"]
    assert report["receipts"][0]["errors"]
    assert "observer receipt must contain SHADOW records" in report["receipts"][0]["errors"][0]


def test_stdout_matches_committed_report(capsys):
    report_path = REPO / "docs/gen3/probes/negatives_report_2026-09-22.txt"
    assert report_path.is_file(), "committed report must exist"
    expected = report_path.read_text(encoding="utf-8")
    assert main([str(DEFAULT_MANIFEST)]) == 0
    actual = capsys.readouterr().out
    assert actual == expected, "stdout does not match committed report"
