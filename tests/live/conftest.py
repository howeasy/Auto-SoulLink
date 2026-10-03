"""tests/live session hooks: the live-new-gates run attestation (RELEASE-LANES 09765fed).

R-1/R-2/R-3/R-4/R-5g have no receipt of their own, so a SLINK_LIVE=1 run of tests/live/test_gen2_new_gates.py writes
one gen2-live-new-gates-attestation-v1 record from this session's own outcome counts, CODE_DIGEST stamped:

    tests/fixtures/gen2/receipts/live_new_gates.inspect_run.json

verify_gen2_release._inspect_run_row_errors judges it: a PASS for every title and passes only (a skip, deselect,
xfail or error is not a pass). It is written on FAIL too, so a failed run can never leave an older PASS standing.
SLINK_GEN2_NO_ATTEST=1 (tools/verify_gen2_release.py's live-new-gates lane) runs the gates without writing it: only the
final sweep's gate/inspect_run cell attests, so a verification run never unpins the committed record.

OVERLAY (SLINK_GEN2_ARTIFACT=overlay, docs/gen2/OVERLAY_ADMISSION.md D4): the same run on the overlay cartridges writes
tests/fixtures/gen2/receipts/overlay/live_new_gates.inspect_run.json instead, additionally recording each title's
{kind, rom_sha1, binding_sha256} from the HASHED staged overlay (never from the env); the clean file is never touched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NEW_GATES = "tests/live/test_gen2_new_gates.py"
ATTESTATION = "tests/fixtures/gen2/receipts/live_new_gates.inspect_run.json"
OVERLAY_ATTESTATION = "tests/fixtures/gen2/receipts/overlay/live_new_gates.inspect_run.json"
COUNTS = ("passed", "failed", "skipped", "errors", "xfailed", "xpassed", "deselected")
_run = {"counts": dict.fromkeys(COUNTS, 0), "titles": {}, "seen": False}


def _ours(nodeid):
    return nodeid.replace("\\", "/").startswith(NEW_GATES)


def outcome(report):
    """The pytest summary bucket of one report phase, or None when the phase adds nothing."""
    if report.skipped:
        return "xfailed" if hasattr(report, "wasxfail") else "skipped"
    if report.failed:
        return "failed" if report.when == "call" else "errors"
    if report.when == "call":
        return "xpassed" if hasattr(report, "wasxfail") else "passed"
    return None


def pytest_deselected(items):
    _run["counts"]["deselected"] += sum(_ours(item.nodeid) for item in items)


def pytest_runtest_logreport(report):
    if not _ours(report.nodeid):
        return
    _run["seen"] = True
    bucket = outcome(report)
    if bucket is None:
        return
    _run["counts"][bucket] += 1
    # the inspect gate is parametrized by fixture name, <title>_<target>[...]; a non-fixture test counts for none
    fixture = report.nodeid.rpartition("[")[2].rstrip("]") if "[" in report.nodeid else ""
    title = fixture.split("_")[0]
    if title in ("crystal", "gold", "silver"):
        ok = bucket == "passed" and _run["titles"].get(title, "PASS") == "PASS"
        _run["titles"][title] = "PASS" if ok else "FAIL"


def attestation(counts, titles, stamp, identities=None):
    from tools.verify_gen2_release import INSPECT_RUN_IDS, INSPECT_RUN_SCHEMA

    clean = counts["passed"] > 0 and all(counts[key] == 0 for key in COUNTS if key != "passed")
    every = all(titles.get(title) == "PASS" for title in ("crystal", "gold", "silver"))
    record = {"schema": INSPECT_RUN_SCHEMA, "result": "PASS" if clean and every else "FAIL", "evidence_level": "PHYSICAL",
              "test": NEW_GATES, "requirement_ids": list(INSPECT_RUN_IDS), "titles": dict(sorted(titles.items())),
              "pytest": dict(counts), "code_digest": stamp}
    if identities is not None:   # overlay only: the hashed staged artifact per title (clean records stay byte-identical)
        record["artifacts"] = dict(sorted(identities.items()))
    return record


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("SLINK_LIVE") != "1" or not _run["seen"] or os.environ.get("SLINK_GEN2_NO_ATTEST") == "1":
        return   # SLINK_GEN2_NO_ATTEST: verify_gen2_release's live-new-gates lane re-proves without re-attesting
    from tests.live import test_gen2_new_gates as live

    overlay = live.KIND == "overlay"
    identities = {title: {key: live.identity(title)[key] for key in ("kind", "rom_sha1", "binding_sha256")}
                  for title in ("crystal", "gold", "silver")} if overlay else None
    record = attestation(_run["counts"], _run["titles"], live.code_stamp(), identities)
    out = REPO / (OVERLAY_ATTESTATION if overlay else ATTESTATION)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
