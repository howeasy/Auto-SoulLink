"""tests/unit/test_verify_polished_release.py — the fail-closed rules of the Polished RC verifier.

`tools/verify_gen2_release.py` is the Gen 2 manifest and is off limits here: Polished Crystal is
a SOLO title, and `tests/unit/test_polished_release_guards.py` pins that manifest's TITLES and
DUO_PAIRS to vanilla. `tools/verify_polished_release.py` is the separate lane, and these tests
are about its RULES, not about Polished working:

  * a LIVE item with no receipt is red, and so is a receipt whose schema is wrong;
  * a receipt whose ROM does not bind to the overlay published today is red, and says both hashes;
  * a receipt whose evidence bytes do not hash to what it claims is red — tampering, not staleness;
  * a receipt whose evidence file cannot be reached at all is ALSO red: an unverifiable
    transcription is not evidence;
  * a SOURCE command that exits non-zero is red, whatever it printed;
  * a MODEL file with no passing test is red: did not run is not passed;
  * an OPEN obligation is red until it is CLOSED, closing it needs a LIVE item that PASSes, and
    `blocking_rc: false` is no bypass;
  * the `required_ids` census, the unreachable jar, partial runs, the LIVE receipt census
    (scenario, expected PASS checks, provenance sha256) and the COMPUTED code digest are all
    fail-closed;
  * an OPEN item whose Manager option now reads ok=True is a disagreement, not a completion.

Every RED CONTROL test below APPLIES its mutation, asserts the verifier goes red, and REVERTS.
A control that never mutated anything proves nothing.

Run:  python -m pytest tests/unit/test_verify_polished_release.py -q
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import verify_polished_release as verifier  # noqa: E402

CODE = "lua/code.lua"               # the one file the fake tree's code digest covers
ROM = "a" * 40                     # the overlay this fake tree publishes
OTHER_ROM = "b" * 40                # an overlay that was published before
EVIDENCE = "RESULT: PASS fake (0 checks failed) frame 1\n"


def _receipt(root: pathlib.Path, *, rom: str = ROM, name: str = "r.json",
             evidence: pathlib.Path | None = None, grade: str = "DEV") -> tuple[pathlib.Path, dict]:
    if evidence is None:
        evidence = root / "lane" / "result.txt"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(EVIDENCE, encoding="utf-8")
    doc = {
        "schema": verifier.RECEIPT_SCHEMA,
        "grade": grade,
        "scenario_id": "fake/scenario",
        "date": "2026-10-04",
        "lane": str(root / "lane"),
        "evidence_file": str(evidence),
        "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        "rom_sha1_executed": rom,
        "overlay_provenance_sha256": hashlib.sha256(
            (root / "data" / "polished" / "overlay_provenance.json").read_bytes()).hexdigest(),
        "code_digest": verifier.compute_code_digest(root, [CODE]),
        "synth": ["none"],
        "checks": [{"name": "run verdict", "result": "PASS", "observed": "RESULT: PASS"}],
    }
    path = root / "tests" / "fixtures" / "polished" / "receipts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path, doc


def _manifest(root: pathlib.Path, items: list[dict], open_items: list[dict] | None = None,
              **doc_over) -> pathlib.Path:
    """A synthetic manifest whose census lists exactly what it declares, unless overridden."""
    path = root / "tests" / "polished_release_requirements.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": verifier.MANIFEST_SCHEMA,
        "required_ids": [i["id"] for i in items] + [i["id"] for i in open_items or []],
        "code_digest_files": [CODE],
        "items": items,
        "open": open_items or [],
    }
    doc.update(doc_over)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def _root(tmp_path: pathlib.Path, items, open_items=None, **doc_over) -> tuple[pathlib.Path, pathlib.Path]:
    root = tmp_path / "repo"
    (root / "data" / "polished").mkdir(parents=True, exist_ok=True)
    (root / "data" / "polished" / "overlay_provenance.json").write_text(
        json.dumps({"output": {"sha1": ROM, "md5": "0" * 32}}), encoding="utf-8")
    (root / CODE).parent.mkdir(parents=True, exist_ok=True)
    (root / CODE).write_text("return 1\n", encoding="utf-8")
    return root, _manifest(root, items, open_items, **doc_over)


def _live_item(**over) -> dict:
    item = {"id": "LIVE-FAKE", "kind": "LIVE", "description": "a fake live cell",
            "receipt": "tests/fixtures/polished/receipts/r.json",
            "expect_scenario": "fake/scenario", "expect_checks": ["run verdict"]}
    item.update(over)
    return item


def _row(rows, rid="LIVE-FAKE"):
    return next(r for r in rows if r.id == rid)


def _reasons(row) -> str:
    return " | ".join(row.reasons)


# ─────────────────────────────────────────────── happy path


def test_a_bound_receipt_passes(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    rows, errs = verifier.verify(root, manifest)
    assert errs == []
    assert _row(rows).ok, _reasons(_row(rows))


def test_an_open_obligation_blocks_the_rc(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()], [{
        "id": "OPEN-THING", "kind": "OPEN", "status": "OPEN", "blocking_rc": True,
        "description": "not landed", "blocker": "no implementation"}])
    _receipt(root)
    rows, _ = verifier.verify(root, manifest)
    row = _row(rows, "OPEN-THING")
    assert not row.ok and "OPEN: no implementation" in _reasons(row)


# ─────────────────────────────────────────────── receipt presence and shape


def test_a_missing_receipt_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])          # no receipt written
    rows, _ = verifier.verify(root, manifest)
    assert "missing receipt: tests/fixtures/polished/receipts/r.json" in _reasons(_row(rows))


@pytest.mark.parametrize("mutate,expect", [
    (lambda d: d.update(schema="polished-live-receipt-v2"), "schema is"),
    (lambda d: d.pop("evidence_sha256"), "missing field 'evidence_sha256'"),
    (lambda d: d.update(evidence_sha256="nothex"), "is not 64 lowercase hex chars"),
    (lambda d: d.update(rom_sha1_executed="xyz"), "is not a sha1"),
    (lambda d: d.update(synth="none"), "field 'synth' is str"),
    (lambda d: d.update(checks=[]), "checks is empty"),
    (lambda d: d.update(checks=[{"name": "x"}]), "needs 'name' and 'result'"),
    (lambda d: d.update(checks=[{"name": "x", "result": "MAYBE"}]), "is not PASS/FAIL/INFO"),
])
def test_a_bad_schema_is_red(tmp_path, mutate, expect):
    root, manifest = _root(tmp_path, [_live_item()])
    _, doc = _receipt(root)
    mutate(doc)
    (root / "tests/fixtures/polished/receipts/r.json").write_text(
        json.dumps(doc, indent=2), encoding="utf-8")
    rows, _ = verifier.verify(root, manifest)
    assert "bad schema" in _reasons(_row(rows)) and expect in _reasons(_row(rows))


def test_a_receipt_may_not_promote_itself_to_physical(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _, doc = _receipt(root, grade="PHYSICAL")
    (root / "tests/fixtures/polished/receipts/r.json").write_text(
        json.dumps(doc, indent=2), encoding="utf-8")
    rows, _ = verifier.verify(root, manifest)
    assert "grade is 'PHYSICAL'" in _reasons(_row(rows))


def test_a_receipt_recording_a_failed_check_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _, doc = _receipt(root)
    doc["checks"].append({"name": "the census followed the battle end", "result": "FAIL",
                          "observed": "frozen at generation 2"})
    (root / "tests/fixtures/polished/receipts/r.json").write_text(
        json.dumps(doc, indent=2), encoding="utf-8")
    rows, _ = verifier.verify(root, manifest)
    assert "receipt records a FAIL check" in _reasons(_row(rows))


# ─────────────────────────────────────────────── the ROM binding


def test_a_receipt_from_another_overlay_is_stale_and_names_both_hashes(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root, rom=OTHER_ROM)
    rows, _ = verifier.verify(root, manifest)
    reasons = _reasons(_row(rows))
    assert "STALE" in reasons and OTHER_ROM in reasons and ROM in reasons


def test_a_randomized_cartridge_binds_on_the_overlay_it_came_from(tmp_path):
    cartridge = "c" * 40
    root, manifest = _root(tmp_path, [_live_item(bind="source")])
    path, doc = _receipt(root, rom=cartridge)
    doc["source_overlay_sha1"] = ROM
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    rows, _ = verifier.verify(root, manifest)
    assert _row(rows).ok, _reasons(_row(rows))


def test_a_source_bound_item_without_the_source_sha_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item(bind="source")])
    _receipt(root, rom="c" * 40)                            # no source_overlay_sha1
    rows, _ = verifier.verify(root, manifest)
    assert "needs a source_overlay_sha1" in _reasons(_row(rows))


def test_a_receipt_naming_a_moved_provenance_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    path, doc = _receipt(root)
    doc["overlay_provenance_sha256"] = "d" * 64
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    rows, _ = verifier.verify(root, manifest)
    assert "overlay_provenance_sha256" in _reasons(_row(rows))


# ─────────────────────────────────────────────── the evidence bytes


def test_tampered_evidence_bytes_are_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    evidence = root / "lane" / "result.txt"
    evidence.write_text(EVIDENCE + "[ok] something that never ran\n", encoding="utf-8")
    rows, _ = verifier.verify(root, manifest)
    reasons = _reasons(_row(rows))
    assert "evidence sha256 mismatch" in reasons and "lanes" not in reasons.split(":")[0]


def test_unreachable_evidence_is_red_not_silently_accepted(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    path, doc = _receipt(root)
    evidence = pathlib.Path(doc["evidence_file"])
    evidence.unlink()
    rows, _ = verifier.verify(root, manifest)
    assert "evidence file not reachable" in _reasons(_row(rows))


# ─────────────────────────────────────────────── SOURCE and BUILD commands


@pytest.mark.parametrize("exit_code,expect_pass", [(0, True), (1, False), (3, False)])
def test_a_source_command_passes_only_on_exit_zero(tmp_path, exit_code, expect_pass):
    root, manifest = _root(tmp_path, [{
        "id": "SRC-FAKE", "kind": "SOURCE", "description": "a command that decides for itself",
        "command": ["$PY", "-c", f"print('drift detected'); raise SystemExit({exit_code})"],
        "timeout": 120}])
    rows, _ = verifier.verify(root, manifest)
    row = _row(rows, "SRC-FAKE")
    assert row.ok is expect_pass, _reasons(row)


def test_a_missing_tool_is_red_without_running_anything(tmp_path):
    root, manifest = _root(tmp_path, [{
        "id": "SRC-GONE", "kind": "SOURCE", "description": "a tool that is not there",
        "command": ["$PY", "tools/does_not_exist.py", "--check"]}])
    rows, _ = verifier.verify(root, manifest)
    assert "missing tool: tools/does_not_exist.py" in _reasons(_row(rows, "SRC-GONE"))


def test_a_command_that_times_out_is_red(tmp_path):
    root, manifest = _root(tmp_path, [{
        "id": "SRC-SLOW", "kind": "SOURCE", "description": "a build that never finishes",
        "command": ["$PY", "-c", "import time; time.sleep(30)"], "timeout": 2}])
    rows, _ = verifier.verify(root, manifest)
    reasons = _reasons(_row(rows, "SRC-SLOW"))
    assert "timed out" in reasons and "did not run is not a pass" in reasons


# ─────────────────────────────────────────────── MODEL


def _pytest_tree(root: pathlib.Path, body: str) -> str:
    path = root / "tests" / "unit" / "test_fake_lane.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return "tests/unit/test_fake_lane.py"


def test_a_model_item_runs_one_pytest_per_file(tmp_path):
    root, _ = _root(tmp_path, [])
    files = [_pytest_tree(root, "def test_ok():\n    assert 1 == 1\n")]
    manifest = _manifest(root, [{"id": "MODEL-FAKE", "kind": "MODEL",
                                 "description": "one green file", "files": files}])
    rows, _ = verifier.verify(root, manifest)
    row = _row(rows, "MODEL-FAKE")
    assert row.ok, _reasons(row)
    assert row.detail == "1/1 files green"


def test_a_model_file_that_only_skips_is_red(tmp_path):
    root, _ = _root(tmp_path, [])
    files = [_pytest_tree(root, "import pytest\n\n\n@pytest.mark.skip(reason='later')\n"
                             "def test_skipped():\n    assert True\n")]
    manifest = _manifest(root, [{"id": "MODEL-FAKE", "kind": "MODEL",
                                 "description": "a file whose only test is skipped",
                                 "files": files}])
    rows, _ = verifier.verify(root, manifest)
    reasons = _reasons(_row(rows, "MODEL-FAKE"))
    assert "is not a pass" in reasons and "1 skipped" in reasons


def test_a_model_item_with_a_missing_file_is_red(tmp_path):
    root, manifest = _root(tmp_path, [{
        "id": "MODEL-FAKE", "kind": "MODEL", "description": "a file that does not exist",
        "files": ["tests/unit/test_never_written.py"]}])
    rows, _ = verifier.verify(root, manifest)
    assert "tests/unit/test_never_written.py: MISSING" in _reasons(_row(rows, "MODEL-FAKE"))


# ─────────────────────────────────────────────── OPEN bookkeeping


def test_closing_an_open_item_needs_a_closed_by(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()], [{
        "id": "OPEN-THING", "kind": "OPEN", "status": "CLOSED", "blocking_rc": True,
        "description": "landed"}])
    _receipt(root)
    _, errs = verifier.verify(root, manifest)
    assert any("closed_by None must name a LIVE item" in e for e in errs)
    assert "CLOSED without a closed_by" in _reasons(verifier.check_open(
        {"id": "X", "kind": "OPEN", "status": "CLOSED"}, root))


def test_a_closed_open_item_closed_by_a_passing_live_item_passes(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()], [{
        "id": "OPEN-THING", "kind": "OPEN", "status": "CLOSED", "blocking_rc": True,
        "description": "landed", "closed_by": "LIVE-FAKE"}])
    _receipt(root)
    rows, errs = verifier.verify(root, manifest)
    assert errs == []
    assert _row(rows, "OPEN-THING").ok, _reasons(_row(rows, "OPEN-THING"))


def test_a_free_text_closed_by_is_no_longer_enough(tmp_path):
    """OLD FALSE-GREEN: any truthy closed_by string closed the item. Now it must be a LIVE id."""
    root, manifest = _root(tmp_path, [_live_item()], [{
        "id": "OPEN-THING", "kind": "OPEN", "status": "CLOSED", "description": "landed",
        "closed_by": "owner 2026-10-04: reviewed"}])
    _receipt(root)
    rows, errs = verifier.verify(root, manifest)
    assert any("must name a LIVE item id" in e for e in errs) and rows == []
    # and the row-level rule agrees when the manifest check is bypassed
    row = verifier.check_open({"id": "X", "kind": "OPEN", "status": "CLOSED",
                               "closed_by": "owner 2026-10-04: reviewed"}, root)
    assert not row.ok and "PASSes in this run" in _reasons(row)


def test_closed_by_a_live_item_that_is_red_is_red(tmp_path):
    """The named LIVE item exists but has no receipt: the closure has nothing behind it."""
    root, manifest = _root(tmp_path, [_live_item()], [{
        "id": "OPEN-THING", "kind": "OPEN", "status": "CLOSED", "description": "landed",
        "closed_by": "LIVE-FAKE"}])                                     # no receipt written
    rows, errs = verifier.verify(root, manifest)
    assert errs == [] and not _row(rows).ok
    assert "PASSes in this run" in _reasons(_row(rows, "OPEN-THING"))


def test_closed_by_a_live_item_outside_the_run_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()], [{
        "id": "OPEN-THING", "kind": "OPEN", "status": "CLOSED", "description": "landed",
        "closed_by": "LIVE-FAKE"}])
    _receipt(root)
    rows, _ = verifier.verify(root, manifest, only=frozenset({"OPEN-THING"}))
    assert "PASSes in this run" in _reasons(_row(rows, "OPEN-THING"))


@pytest.mark.parametrize("value", [False, 0, None, "no"])
def test_blocking_rc_is_not_a_bypass(tmp_path, value):
    """OLD FALSE-GREEN: status OPEN + blocking_rc false returned PASS."""
    item = {"id": "OPEN-THING", "kind": "OPEN", "status": "OPEN", "blocking_rc": value,
            "description": "not landed", "blocker": "nope"}
    assert not verifier.check_open(item, tmp_path).ok                # the row itself is red
    root, manifest = _root(tmp_path, [_live_item()], [item])
    _receipt(root)
    rows, errs = verifier.verify(root, manifest)
    assert any("blocking_rc must be true or absent" in e for e in errs) and rows == []


def test_an_open_item_without_blocking_rc_is_still_red(tmp_path):
    row = verifier.check_open({"id": "X", "kind": "OPEN", "status": "OPEN", "description": "d"},
                              tmp_path)
    assert not row.ok and "OPEN:" in _reasons(row)


def test_an_open_item_bound_to_a_manager_option_that_reads_ok_is_red(tmp_path, monkeypatch):
    """The disagreement rule: a Manager row flipped to ok while the item still reads OPEN."""
    import server.manager as manager

    root, manifest = _root(tmp_path, [_live_item()], [{
        "id": "OPEN-THING", "kind": "OPEN", "status": "OPEN", "blocking_rc": True,
        "description": "landed", "blocker": "nope", "manager_options": ["explode_mode"]}])
    _receipt(root)
    rows, _ = verifier.verify(root, manifest)               # the real OPTION_SUPPORT refuses it
    row = _row(rows, "OPEN-THING/manager")
    assert row.ok and row.detail == "OPEN-THING: still refused by explode_mode"

    monkeypatch.setitem(manager.OPTION_SUPPORT["explode_mode"], "gen2_polished",
                        {"ok": True, "why": ""})
    rows, _ = verifier.verify(root, manifest)
    assert "reads ok=True" in _reasons(_row(rows, "OPEN-THING/manager"))


def test_an_open_item_bound_to_an_option_with_no_polished_row_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()], [{
        "id": "OPEN-THING", "kind": "OPEN", "status": "OPEN", "blocking_rc": True,
        "description": "landed", "blocker": "nope", "manager_options": ["overworld_presence"]}])
    _receipt(root)
    rows, _ = verifier.verify(root, manifest)
    assert "has no gen2_polished row" in _reasons(_row(rows, "OPEN-THING/manager"))


# ─────────────────────────────────────────────── manifest declarations


def test_an_unknown_only_id_is_reported(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    _, errs = verifier.verify(root, manifest, only=frozenset({"LIVE-NOPE"}))
    assert any("unknown id" in e for e in errs)


@pytest.mark.parametrize("item,expect", [
    ({"id": "X-1", "kind": "LIVE", "description": "d"},
     "LIVE needs a receipt"),
    ({"id": "X-1", "kind": "SOURCE", "description": "d"},
     "SOURCE needs a command"),
    ({"id": "X-1", "kind": "MODEL", "description": "d"},
     "MODEL needs files"),
    ({"id": "X-1", "kind": "MANAGER", "description": "d", "check": "nope"},
     "unknown manager check"),
    ({"id": "X-1", "kind": "OPEN", "description": "d"},
     "OPEN items belong in the 'open' list"),
    ({"id": "X-1", "kind": "WAT", "description": "d"},
     "is not one of"),
    ({"id": "", "kind": "SOURCE", "description": "d", "command": ["true"]},
     "is missing 'id'"),
    ({"id": "X-1", "kind": "SOURCE", "description": "", "command": ["true"]},
     "is missing 'description'"),
])
def test_manifest_declaration_errors(item, expect):
    errs = verifier.manifest_errors({"schema": verifier.MANIFEST_SCHEMA, "items": [item]})
    assert any(expect in e for e in errs), errs


def test_duplicate_ids_are_a_manifest_error():
    item = {"id": "X-1", "kind": "SOURCE", "description": "d", "command": ["true"]}
    errs = verifier.manifest_errors({"schema": verifier.MANIFEST_SCHEMA, "items": [item, dict(item)]})
    assert any("duplicate id" in e for e in errs)


def test_a_manifest_with_the_wrong_schema_string_is_refused(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema": "something-else", "items": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest schema"):
        verifier.load_manifest(path)
    doc = json.loads((REPO / verifier.MANIFEST).read_text(encoding="utf-8"))
    assert doc["schema"] == verifier.MANIFEST_SCHEMA


# ─────────────────────────────────────────────── the shipped artefacts


def test_the_shipped_manifest_and_receipts_are_wellformed():
    """A verifier whose own artefacts are malformed is worse than no verifier."""
    manifest = verifier.load_manifest(REPO / verifier.MANIFEST)
    assert verifier.manifest_errors(manifest) == []
    receipts = sorted((REPO / manifest["receipts_dir"]).glob("*.json"))
    assert receipts, "no committed receipts"
    for path in receipts:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert verifier.receipt_schema_errors(doc) == [], f"{path.name}"
        assert doc["grade"] == "DEV", f"{path.name} claims a grade other than DEV"


def test_every_live_item_points_at_a_committed_receipt():
    manifest = verifier.load_manifest(REPO / verifier.MANIFEST)
    live = [i for i in manifest["items"] if i["kind"] == "LIVE"]
    assert live
    for item in live:
        assert (REPO / item["receipt"]).is_file(), item["id"]


def test_every_open_item_blocks_the_rc():
    manifest = verifier.load_manifest(REPO / verifier.MANIFEST)
    opens = manifest["open"]
    live_ids = {i["id"] for i in manifest["items"] if i["kind"] == "LIVE"}
    assert opens
    for item in opens:
        assert item["status"] in ("OPEN", "CLOSED"), item["id"]
        assert item["blocking_rc"] is True, item["id"]
        assert item.get("blocker"), item["id"]
        if item["status"] == "CLOSED":                  # a closure names the LIVE row that closes it
            assert item.get("closed_by") in live_ids, item["id"]


# ─────────────────────────────────────────────── RED CONTROLS
# Each one APPLIES the mutation, asserts red, and REVERTS.


def test_red_control_promoting_a_receipt_to_physical(tmp_path):
    """RED CONTROL: set grade to PHYSICAL in the receipt. The verifier must go red, then recover."""
    root, manifest = _root(tmp_path, [_live_item()])
    path, _ = _receipt(root)
    original = path.read_text(encoding="utf-8")
    try:
        doc = json.loads(original)
        doc["grade"] = "PHYSICAL"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        rows, _ = verifier.verify(root, manifest)
        assert not _row(rows).ok
    finally:
        path.write_text(original, encoding="utf-8")
    rows, _ = verifier.verify(root, manifest)
    assert _row(rows).ok, _reasons(_row(rows))


def test_red_control_editing_evidence_under_the_receipt(tmp_path):
    """RED CONTROL: append a fake passing line to the evidence file. Red, then revert."""
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    evidence = root / "lane" / "result.txt"
    original = evidence.read_bytes()
    try:
        evidence.write_bytes(original + b"[ok] a check that never ran\n")
        rows, _ = verifier.verify(root, manifest)
        assert "evidence sha256 mismatch" in _reasons(_row(rows))
    finally:
        evidence.write_bytes(original)
    rows, _ = verifier.verify(root, manifest)
    assert _row(rows).ok, _reasons(_row(rows))


def test_red_control_deleting_a_committed_receipt(tmp_path):
    """RED CONTROL: delete the receipt file. Red, then restore it byte for byte."""
    root, manifest = _root(tmp_path, [_live_item()])
    path, _ = _receipt(root)
    original = path.read_bytes()
    try:
        path.unlink()
        rows, _ = verifier.verify(root, manifest)
        assert "missing receipt" in _reasons(_row(rows))
    finally:
        path.write_bytes(original)
    rows, _ = verifier.verify(root, manifest)
    assert _row(rows).ok, _reasons(_row(rows))


def test_red_control_moving_the_published_overlay_sha(tmp_path):
    """RED CONTROL: republish a different overlay. A live cell that ran the old one goes red."""
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)                                                    # bound to the published ROM
    assert _row(verifier.verify(root, manifest)[0]).ok
    provenance = root / "data" / "polished" / "overlay_provenance.json"
    original = provenance.read_text(encoding="utf-8")
    try:
        provenance.write_text(json.dumps({"output": {"sha1": OTHER_ROM, "md5": "0" * 32}}),
                              encoding="utf-8")
        rows, _ = verifier.verify(root, manifest)
        reasons = _reasons(_row(rows))
        assert "STALE" in reasons and ROM in reasons and OTHER_ROM in reasons
    finally:
        provenance.write_text(original, encoding="utf-8")
    assert _row(verifier.verify(root, manifest)[0]).ok


# ─────────────────────────────────────────────── CLOSED FALSE-GREEN PATHS
# Each test below fails on the verifier as it stood before the hardening.


def _put(path: pathlib.Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _open_item(rid: str = "OPEN-THING") -> dict:
    return {"id": rid, "kind": "OPEN", "status": "OPEN", "blocking_rc": True,
            "description": "not landed", "blocker": "no implementation"}


# (2) the obligation census


def test_census_a_deleted_open_list_is_a_manifest_error(tmp_path):
    """OLD FALSE-GREEN: an empty `open` list passed declaration validation."""
    root, manifest = _root(tmp_path, [_live_item()], [_open_item()])
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["open"] = []
    _put(manifest, doc)
    rows, errs = verifier.verify(root, manifest)
    assert rows == [] and any("required id 'OPEN-THING' is absent" in e for e in errs)


def test_census_a_deleted_item_is_a_manifest_error(tmp_path):
    second = _live_item(id="LIVE-SECOND")
    root, manifest = _root(tmp_path, [_live_item(), second])
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["items"].remove(second)
    _put(manifest, doc)
    _, errs = verifier.verify(root, manifest)
    assert any("required id 'LIVE-SECOND' is absent" in e for e in errs)


def test_census_an_unlisted_id_must_be_added_on_purpose(tmp_path):
    root, manifest = _root(tmp_path, [_live_item(), _live_item(id="LIVE-NEW")],
                           required_ids=["LIVE-FAKE"])
    _, errs = verifier.verify(root, manifest)
    assert any("id 'LIVE-NEW' is not in required_ids" in e for e in errs)


@pytest.mark.parametrize("value", [None, [], "LIVE-FAKE"])
def test_census_a_missing_or_empty_required_ids_is_a_manifest_error(tmp_path, value):
    root, manifest = _root(tmp_path, [_live_item()], required_ids=value)
    _, errs = verifier.verify(root, manifest)
    assert any("required_ids must be a non-empty list" in e for e in errs)


# (3) the jar


def test_an_unreachable_pinned_jar_is_red(tmp_path, monkeypatch):
    """OLD FALSE-GREEN: the jar pin returned True when the jar file could not be reached."""
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "data" / "upr_jars.json").write_text(
        json.dumps({"patches 0001-0021": "e" * 64}), encoding="utf-8")
    monkeypatch.setattr(verifier, "JAR_PATH", tmp_path / "no" / "such.jar")
    ok, detail = verifier._jar_pin(root)
    assert not ok
    assert "jar not reachable: the byte pin cannot be verified" in detail


def test_a_jar_that_hashes_wrong_is_still_red(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "data" / "upr_jars.json").write_text(
        json.dumps({"patches 0001-0021": "e" * 64}), encoding="utf-8")
    jar = tmp_path / "x.jar"
    jar.write_bytes(b"not the pinned jar")
    monkeypatch.setattr(verifier, "JAR_PATH", jar)
    ok, detail = verifier._jar_pin(root)
    assert not ok and "the file hashes" in detail


# (4) partial runs


def _main(capsys, root, manifest, *args):
    code = verifier.main(["--root", str(root), "--manifest", str(manifest), *args])
    return code, capsys.readouterr()


def test_a_complete_green_run_exits_zero_and_is_complete(tmp_path, capsys):
    """The positive control for the partial-run rules."""
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    code, out = _main(capsys, root, manifest, "--json")
    assert code == 0 and json.loads(out.out)["complete"] is True
    code, out = _main(capsys, root, manifest)
    assert code == 0 and "GATE PASSED" in out.out and "PARTIAL" not in out.out


def test_only_is_a_partial_run_and_never_exits_zero(tmp_path, capsys):
    """OLD FALSE-GREEN: --only on a green item exited 0."""
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    code, out = _main(capsys, root, manifest, "--only", "LIVE-FAKE")
    assert code == 3 and "PARTIAL RUN: NOT A RELEASE VERDICT" in out.out


def test_no_release_is_a_partial_run_and_never_exits_zero(tmp_path, capsys):
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    code, out = _main(capsys, root, manifest, "--no-release")
    assert code == 3 and "PARTIAL RUN: NOT A RELEASE VERDICT" in out.out


def test_a_partial_json_run_says_complete_false(tmp_path, capsys):
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    for flag in (["--only", "LIVE-FAKE"], ["--no-release"]):
        code, out = _main(capsys, root, manifest, "--json", *flag)
        assert code == 3 and json.loads(out.out)["complete"] is False
        assert "PARTIAL RUN: NOT A RELEASE VERDICT" in out.err


def test_a_partial_run_that_is_red_still_exits_nonzero(tmp_path, capsys):
    root, manifest = _root(tmp_path, [_live_item()])                    # no receipt
    code, _ = _main(capsys, root, manifest, "--only", "LIVE-FAKE")
    assert code == 1


def test_list_is_marked_not_a_verdict(tmp_path, capsys):
    root, manifest = _root(tmp_path, [_live_item()])
    code, out = _main(capsys, root, manifest, "--list")
    assert code == 0 and "not a verdict" in out.out


# (5) the LIVE receipt census and the computed code digest


def _write_receipt(root, mutate) -> None:
    path, doc = _receipt(root)
    mutate(doc)
    _put(path, doc)


def test_an_info_only_receipt_is_red(tmp_path):
    """OLD FALSE-GREEN: a receipt whose checks were all INFO passed."""
    root, manifest = _root(tmp_path, [_live_item()])
    _write_receipt(root, lambda d: d.update(checks=[{"name": "run verdict", "result": "INFO"}]))
    rows, _ = verifier.verify(root, manifest)
    reasons = _reasons(_row(rows))
    assert "INFO-only" in reasons and "expected check 'run verdict' is not recorded as PASS" in reasons


def test_a_missing_expected_check_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item(expect_checks=["run verdict", "the real claim"])])
    _receipt(root)
    rows, _ = verifier.verify(root, manifest)
    assert "expected check 'the real claim' is not recorded as PASS" in _reasons(_row(rows))


def test_an_expected_check_recorded_only_as_info_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item(expect_checks=["run verdict", "the real claim"])])
    _write_receipt(root, lambda d: d["checks"].append({"name": "the real claim", "result": "INFO"}))
    rows, _ = verifier.verify(root, manifest)
    assert "'the real claim' is not recorded as PASS" in _reasons(_row(rows))


def test_a_receipt_for_another_scenario_is_red(tmp_path):
    """OLD FALSE-GREEN: any scenario_id was accepted."""
    root, manifest = _root(tmp_path, [_live_item(expect_scenario="live/the-one-we-need")])
    _receipt(root)
    rows, _ = verifier.verify(root, manifest)
    assert "scenario_id 'fake/scenario' is not the expected 'live/the-one-we-need'" in _reasons(_row(rows))


@pytest.mark.parametrize("key,errtext", [("expect_scenario", "needs an expect_scenario"),
                                         ("expect_checks", "non-empty expect_checks")])
def test_a_live_item_must_declare_what_it_expects(tmp_path, key, errtext):
    item = _live_item()
    item.pop(key)
    root, manifest = _root(tmp_path, [item])
    rows, errs = verifier.verify(root, manifest)
    assert rows == [] and any(errtext in e for e in errs)


@pytest.mark.parametrize("value", [None, "UNRECORDED", "", "nothex"])
def test_a_receipt_without_a_provenance_sha256_is_red(tmp_path, value):
    """OLD FALSE-GREEN: a missing / null / UNRECORDED provenance sha256 was skipped."""
    root, manifest = _root(tmp_path, [_live_item()])
    _write_receipt(root, lambda d: d.update(overlay_provenance_sha256=value))
    rows, _ = verifier.verify(root, manifest)
    assert "must record the sha256 of the provenance" in _reasons(_row(rows))


def test_a_receipt_with_no_provenance_field_at_all_is_red(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _write_receipt(root, lambda d: d.pop("overlay_provenance_sha256"))
    rows, _ = verifier.verify(root, manifest)
    assert "must record the sha256 of the provenance" in _reasons(_row(rows))


@pytest.mark.parametrize("value", ["UNRECORDED", "f" * 64])
def test_a_code_digest_the_verifier_did_not_compute_is_red(tmp_path, value):
    """OLD FALSE-GREEN: code_digest was a free string (UNRECORDED passed)."""
    root, manifest = _root(tmp_path, [_live_item()])
    _write_receipt(root, lambda d: d.update(code_digest=value))
    rows, _ = verifier.verify(root, manifest)
    assert "STALE: code_digest" in _reasons(_row(rows))


def test_changing_a_digested_file_makes_the_receipt_stale_and_reverting_heals_it(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    code = root / CODE
    original = code.read_bytes()
    assert _row(verifier.verify(root, manifest)[0]).ok
    try:
        code.write_bytes(original + b"-- a change after the run\n")
        assert "STALE: code_digest" in _reasons(_row(verifier.verify(root, manifest)[0]))
    finally:
        code.write_bytes(original)
    assert _row(verifier.verify(root, manifest)[0]).ok


def test_the_code_digest_ignores_line_endings(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()])
    _receipt(root)
    (root / CODE).write_bytes(b"return 1\r\n")                           # same text, CRLF
    assert _row(verifier.verify(root, manifest)[0]).ok


def test_a_code_digest_pattern_matching_nothing_is_a_manifest_error(tmp_path):
    root, manifest = _root(tmp_path, [_live_item()], code_digest_files=["lua/none_*.lua"])
    rows, errs = verifier.verify(root, manifest)
    assert rows == [] and any("matches no file" in e for e in errs)


def test_the_code_digest_covers_every_matched_file_in_sorted_path_order(tmp_path):
    (tmp_path / "lua").mkdir()
    (tmp_path / "lua" / "b.lua").write_bytes(b"B")
    (tmp_path / "lua" / "a.lua").write_bytes(b"A")
    expect = hashlib.sha256(b"lua/a.lua\0A\0lua/b.lua\0B\0").hexdigest()
    assert verifier.compute_code_digest(tmp_path, ["lua/b.lua", "lua/*.lua"]) == expect


# (6) closure receipts: see the closed_by tests above


# the shipped manifest


def test_the_shipped_census_lists_every_declared_obligation():
    doc = verifier.load_manifest(REPO / verifier.MANIFEST)
    declared = [i["id"] for i in doc["items"]] + [i["id"] for i in doc["open"]]
    assert sorted(doc["required_ids"]) == sorted(declared)
    for key in ("items", "open"):                                       # RED CONTROL: drop one
        mutated = json.loads(json.dumps(doc))
        mutated[key].pop()
        assert any("is absent" in e for e in verifier.manifest_errors(mutated)), key


def test_every_shipped_live_item_declares_its_scenario_and_checks():
    doc = verifier.load_manifest(REPO / verifier.MANIFEST)
    for item in (i for i in doc["items"] if i["kind"] == "LIVE"):
        receipt = json.loads((REPO / item["receipt"]).read_text(encoding="utf-8"))
        assert item["expect_scenario"] == receipt["scenario_id"], item["id"]
        assert item["expect_checks"], item["id"]
