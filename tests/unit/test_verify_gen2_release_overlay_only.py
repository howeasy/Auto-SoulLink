"""Overlay-only release policy (2026-10-02); MODEL trees, never physical receipts."""
import hashlib
import json

import pytest

from tests.unit.test_verify_gen2_release_lanes import (
    _fake_duo,
    _green_tree,
    _lf_sha,
    _row,
    _write_doc,
    gate,
)


def test_overlay_proofs_pass_without_clean_proofs_or_fresh_clean_stamps(tmp_path):
    doc = _green_tree(tmp_path)
    stamp = {"schema": "gen2-code-digest-v1", "digest": "a" * 64, "dirty": [], "commit": "MODEL"}
    for row in doc["requirements"]:
        if row["axes"].get("artifact_kind") != "overlay":
            row["proofs"] = []
            continue
        entry = row["proofs"][0]["receipts"]["pydec"]
        path = tmp_path / entry["path"]
        path.write_text(path.read_text() + "CODE_DIGEST " + json.dumps(stamp) + "\n")
        entry["sha256"] = _lf_sha(path)
    _write_doc(tmp_path, doc)
    assert gate.duo_matrix_errors(tmp_path, _fake_duo()) == []
    assert gate.stale_errors(tmp_path, head="a" * 64) == []
    _row(doc, "duo.gold.silver.overlay")["proofs"] = []
    _write_doc(tmp_path, doc)
    assert gate.duo_matrix_errors(tmp_path, _fake_duo()) == [
        "duo.gold.silver.overlay/link: no receipt registered (an empty proof is a release blocker)"]


def test_clean_gate_history_does_not_require_a_current_stamp(tmp_path):
    path = tmp_path / gate.NEW_GATES
    path.parent.mkdir()
    path.write_text(json.dumps({"requirements": [{"id": "history", "axes": {
        "kind": "engine_sites", "artifact_kind": "clean"}, "proofs": [{"receipts": {
            "receipt": {"path": "missing-clean-history.json"}}}]}]}))
    assert gate.stale_errors(tmp_path, head="a" * 64) == []


def test_fixtures_cli_selects_overlay_qualification_namespace(monkeypatch):
    calls = []
    monkeypatch.setattr(gate, "fixtures_errors", lambda **kw: calls.append(kw) or [])
    assert gate.main(["--fixtures"]) == 0
    assert calls == [{"artifact_kind": "overlay"}]


def test_all_thirteen_overlay_qualification_rows_are_required(tmp_path):
    path = tmp_path / gate.NEW_GATES
    path.parent.mkdir()
    path.write_text(json.dumps({"requirements": []}))
    errors = gate.new_gates_errors(tmp_path, kinds={"qualification"})
    assert len(errors) == 13
    assert all("missing required overlay qualification" in e for e in errors)


def test_live_gate_existence_requires_overlay_axis_even_with_clean_rows(tmp_path):
    path = tmp_path / gate.NEW_GATES
    path.parent.mkdir()
    rows = [{"id": kind + title, "axes": {"kind": kind, "title": title, "artifact_kind": "clean"},
             "proofs": []} for kind in gate.LIVE_GATE_KINDS for title in gate.TITLES]
    path.write_text(json.dumps({"requirements": rows}))
    errors = gate.live_gates_errors(tmp_path)
    assert len([e for e in errors if "no overlay row" in e]) == 12


@pytest.mark.parametrize("missing", [None, "engine_sites", "qualification", "inspect_run", "duo"])
def test_release_aggregate_uses_overlay_proofs_and_ignores_broken_clean_history(tmp_path, monkeypatch, missing):
    """MODEL proof routing with the existing model duo oracle and injected fixture/U1/U2 validators.

    All other receipt, identity, stamp and packet checks execute normally. This
    proves release composition, not a cartridge PASS or validator correctness.
    """
    from tests.unit.test_verify_gen2_release_lanes import (
        _LEDGER,
        _SIGNED,
        REPO,
        _attestation,
        _live_gates_tree,
        _pairs_tree,
    )
    doc, duo = _pairs_tree(tmp_path, monkeypatch)
    gates = _live_gates_tree(tmp_path)
    stamp = {"schema": "gen2-code-digest-v1", "digest": "a" * 64, "dirty": [], "commit": "MODEL"}
    base = "tests/fixtures/gen2/receipts/overlay/"

    def add(rid, axes, receipt, filename):
        path = tmp_path / (base + filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**receipt, "code_digest": stamp}))
        gates["requirements"].append({"id": rid, "axes": {**axes, "artifact_kind": "overlay"},
            "proofs": [{"receipts": {"receipt": {"path": base + filename, "sha256": _lf_sha(path)}}}]})

    for title in gate.TITLES:
        identity = gate._execution_identity(tmp_path, title, "overlay")
        panel = next(r for r in gates["requirements"] if r["axes"] == {
            "kind": "panel_gate", "title": title, "artifact_kind": "overlay"})
        receipt = json.loads((tmp_path / panel["proofs"][0]["receipts"]["receipt"]["path"]).read_text())
        receipt.update(schema="gen2-phone-gate-v2", cases={name: {
            "result": "PASS", "step_at": 1, "ring": {"frame": 3, "caller": 0}} for name in gate.PHONE_GATE_CASES})
        receipt["cases"]["save"]["extra"] = {"armed_at_save": 1, "sram_primary": 0, "sram_backup": 0, "sram_changed_bytes": 1}
        receipt["cases"]["native"]["extra"] = {"native_ring": {"caller": 1, "frame": 2}}
        receipt["cases"]["named_map_change"]["extra"] = {"staged_before_crossing": True, "wipes": 1, "restaged": True}
        add("phone." + title, {"kind": "phone_gate", "title": title}, receipt, title + ".phone_gate.json")
        for kind in ("engine_sites", "write_window"):
            add(kind + "." + title, {"kind": kind, "title": title}, {"MODEL": True}, title + "." + kind + ".json")
    for name in gate.OVERLAY_QUALIFICATIONS:
        raw = (REPO / f"tests/fixtures/gen2/{name}.SaveRAM").read_bytes()
        (tmp_path / f"tests/fixtures/gen2/{name}.SaveRAM").write_bytes(raw)
        identity = gate._execution_identity(tmp_path, name.split("_")[0], "overlay")
        report = {"passed": True, "fixtures": [{"name": name, "passed": True,
            "provenance": {"rom_sha1": identity["rom_sha1"]},
            "artifacts": {"fixture": {"sha256": hashlib.sha256(raw).hexdigest()}}}]}
        add(name, {"kind": "qualification", "fixture": name}, report, name + ".qualification.json")
    attest = _attestation(artifacts={t: {k: v for k, v in gate._execution_identity(tmp_path, t, "overlay").items()
                                       if k != "base_sha1"} for t in gate.TITLES})
    add("inspect", {"kind": "inspect_run"}, attest, "live_new_gates.inspect_run.json")
    for row in gates["requirements"]:
        entry = row["proofs"][0]["receipts"]["receipt"]
        path = tmp_path / entry["path"]
        body = json.loads(path.read_text())
        body["code_digest"] = stamp
        path.write_text(json.dumps(body))
        entry["sha256"] = _lf_sha(path)
    for row in doc["requirements"]:
        if row["axes"].get("artifact_kind") != "overlay":
            row["proofs"] = [{"scenario": "link", "receipts": {"pydec": {"path": "MISSING-CLEAN"}}}]
            continue
        for proof in row["proofs"]:
            path = tmp_path / (base + row["id"] + proof["scenario"] + ".txt")
            path.write_text("CODE_DIGEST " + json.dumps(stamp) + "\n")
            proof["receipts"] = {"pydec": {"path": path.relative_to(tmp_path).as_posix(), "sha256": _lf_sha(path)}}
    gates["requirements"].append({"id": "history", "axes": {"artifact_kind": "clean"},
        "proofs": [{"receipts": {"receipt": {"path": "MISSING-CLEAN"}}}]})
    if missing == "duo":
        _row(doc, "duo.gold.silver.overlay")["proofs"].pop()
    elif missing:
        next(r for r in gates["requirements"] if r["axes"]["kind"] == missing)["proofs"] = []
    _write_doc(tmp_path, doc)
    (tmp_path / gate.NEW_GATES).write_text(json.dumps(gates))
    # A real-format G4 packet around the model receipt tree.
    for rel in ("data/gen2_sources.lock.json", "data/gen2/build_provenance.json"):
        (tmp_path / rel).write_bytes((REPO / rel).read_bytes())
    provenance = json.loads((tmp_path / "data/gen2/overlay_provenance.json").read_text())
    shipped = []
    for out in provenance["outputs"].values():
        rel = out["ups"]["file"]
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((REPO / rel).read_bytes())
        shipped.append(path.name)
    grant = gate._published_grant(tmp_path, provenance)
    for title in gate.TITLES:
        out = provenance["outputs"]["poke" + title]
        (tmp_path / f"data/gen2/{title}_slink.map").write_bytes((REPO / f"data/gen2/{title}_slink.map").read_bytes())
        row = {"kind": "overlay", "selection": "SELECTED", "status": "ADMITTED", "sha1": out["sha1"], "ups": out["ups"],
               "binding_sha256": gate._execution_identity(tmp_path, title, "overlay")["binding_sha256"],
               "runtime_gate": {"id": "G4", "state": "ADMITTED", "grant_fingerprint": grant}}
        (tmp_path / f"data/games/gen2_{title}/admission.json").write_text(json.dumps({"artifacts": [row]}))
    (tmp_path / "docs/gen2").mkdir(parents=True)
    (tmp_path / "docs/gen2/PLAN.md").write_text(_LEDGER.format(g4=_SIGNED))
    # C-5 receipts are installed only at the freeze (FREEZE_RUNBOOK item 9); this test is about overlay proofs.
    monkeypatch.setattr(gate, "c5_gate_errors", lambda root=None, head=None: [])
    fixtures = gate.fixtures_errors
    monkeypatch.setattr(gate, "fixtures_errors", lambda root, *, artifact_kind: fixtures(
        root, names=gate.OVERLAY_QUALIFICATIONS, artifact_kind=artifact_kind,
        identity=lambda name, raw, repo: 1, witness=lambda *_: None))
    def validate(kind, title, receipt, artifact):
        assert artifact == "overlay" and receipt["MODEL"] is True
        return True, None
    errors = gate.release_evidence_errors(tmp_path, duo=duo, receipt_validate=validate,
                                          release_ups=shipped, head="a" * 64)
    assert bool(errors) == (missing is not None), errors
    assert not any("history" in e or "MISSING-CLEAN" in e for e in errors)
