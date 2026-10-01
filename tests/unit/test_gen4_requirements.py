"""C0 Gen4 mapping controls; no gate lane, emulator, or behavioral pass is run."""
from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from tools import gen4_requirements as bindings


def source_inputs():
    """The policy documents are inputs independent of the checked-in map."""
    ledger = bindings.LEDGER.read_bytes()
    plan = bindings.PLAN.read_bytes()
    # This fixture exercises mapping while C0-2 independently produces the lock.
    lock = json.dumps({"schema_version": 1, "artifacts": {
        "heartgold": {"sha1": "4fcded0e2713dc03929845de631d0932ea2b5a37", "state": "PINNED"},
        "soulsilver": {"sha1": "f8dc38ea20c17541a43b58c5e6d18c1732c7e582", "state": "PINNED"},
        "heartgold_hge": {"sha1": "cb2dc435196d09c8c9209bf037240ed834f4cea1", "state": "PINNED"},
        "platinum": {"sha1": "ce81046eda7d232513069519cb2085349896dec7", "state": "PINNED"},
    }}).encode()
    return ledger, plan, lock


def test_mapping_is_complete_while_every_behavioral_layer_is_open():
    inputs = source_inputs()
    document = bindings.seed_document(*inputs)
    mapping = bindings.validate_document(document, *inputs, mode="mapping")
    closure = bindings.validate_document(document, *inputs, mode="closure")
    assert mapping["ok"] and mapping["mapping_complete"]
    assert not mapping["evidence_complete"]
    assert not closure["ok"] and closure["open"]["PHYSICAL"]
    assert all(row["evidence"][layer]["status"] == "OPEN"
               for row in document["rows"] for layer in row["required_layers"])
    assert any(row["id"] == "S-7:heartgold_hge" and "PHYSICAL" in row["required_layers"]
               for row in document["rows"])
    assert any(row["id"] == "S-8:heartgold_hge" and row["required_layers"] == ["SOURCE", "MODEL"]
               for row in document["rows"])
    assert any(row["id"] == "F-7:platinum" and row["required_layers"] == ["SOURCE", "MODEL"]
               for row in document["rows"])


@pytest.mark.parametrize("missing", ["W-2:heartgold", "G1-o:heartgold_hge", "D-10:ss_to_hg"])
def test_missing_row_or_direction_fails_mapping(missing):
    inputs = source_inputs()
    document = bindings.seed_document(*inputs)
    document["rows"] = [row for row in document["rows"] if row["id"] != missing]
    report = bindings.validate_document(document, *inputs)
    assert not report["ok"]
    assert any(missing in error for error in report["errors"])


def test_duplicate_or_unknown_check_is_refused():
    inputs = source_inputs()
    document = bindings.seed_document(*inputs)
    document["checks"].append(copy.deepcopy(document["checks"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        bindings.validate_document(document, *inputs)
    document["checks"].pop()
    document["checks"][0]["id"] = "gen4.unknown"
    with pytest.raises(ValueError, match="unknown"):
        bindings.validate_document(document, *inputs)


def test_hge_duo_has_two_distinct_fixture_slots():
    inputs = source_inputs()
    document = bindings.seed_document(*inputs)
    check = next(check for check in document["checks"]
                 if check["obligation_id"] == "D-3:hge_to_hge")
    assert check["side_artifacts"] == ["heartgold_hge", "heartgold_hge"]
    assert check["fixture_slots"] == ["hge_a", "hge_b"]
    check["fixture_slots"][1] = "hge_a"
    with pytest.raises(ValueError, match="binding"):
        bindings.validate_document(document, *inputs)


def test_physical_check_has_distinct_live_target_and_cannot_be_lowered():
    inputs = source_inputs()
    document = bindings.seed_document(*inputs)
    check = next(check for check in document["checks"]
                 if check["obligation_id"] == "W-2:heartgold")
    assert check["targets"]["SOURCE"].startswith("tests/unit/")
    assert check["targets"]["MODEL"].startswith("tests/unit/")
    assert check["targets"]["PHYSICAL"].startswith("tests/live/")
    physical = check["targets"].pop("PHYSICAL")
    with pytest.raises(ValueError, match="missing/lowered evidence target"):
        bindings.validate_document(document, *inputs)
    check["targets"]["PHYSICAL"] = physical.replace("tests/live/", "tests/unit/")
    with pytest.raises(ValueError, match="unit target cannot qualify PHYSICAL"):
        bindings.validate_document(document, *inputs)


def test_substituted_digest_and_open_artifact_cannot_bind():
    inputs = source_inputs()
    document = bindings.seed_document(*inputs)
    bad = copy.deepcopy(document)
    bad["rows"][0]["mapping"]["artifacts"] = {"heartgold": "f" * 40}
    with pytest.raises(ValueError, match="binding"):
        bindings.validate_document(bad, *inputs)
    lock = json.loads(inputs[2])
    lock["artifacts"]["soulsilver"]["state"] = "OPEN"
    with pytest.raises(ValueError, match="OPEN artifact"):
        bindings.validate_document(document, inputs[0], inputs[1], json.dumps(lock).encode())


@pytest.mark.parametrize("status", ["CLOSED", "ALLOWED_SKIP", "SKIPPED"])
def test_required_open_cannot_be_closed_or_waived_without_receipt(status):
    inputs = source_inputs()
    document = bindings.seed_document(*inputs)
    claim = document["rows"][0]["evidence"]["SOURCE"]
    claim["status"] = status
    report = bindings.validate_document(document, *inputs)
    assert not report["ok"]


def test_independent_ledger_and_probe_inventory_reject_drift():
    ledger, plan, lock = source_inputs()
    with pytest.raises(ValueError, match="ledger inventory"):
        bindings.seed_document(ledger.replace(b"| D-11 |", b"| D-12 |"), plan, lock)
    with pytest.raises(ValueError, match="physical policy"):
        bindings.seed_document(ledger.replace(b"N/A D3", b"OPEN"), plan, lock)
    with pytest.raises(ValueError, match="G1 a-o"):
        bindings.seed_document(ledger, plan.replace(b"| o in-battle write", b"| p in-battle write"), lock)


def test_checked_in_binding_uses_current_verified_lock():
    if not bindings.LOCK.exists():
        pytest.fail("C0-2 lock is absent; checked-in binding cannot be verified")
    assert bindings.MANIFEST.exists(), "Gen4 binding manifest is absent"
    raw = bindings.LEDGER.read_bytes(), bindings.PLAN.read_bytes(), bindings.LOCK.read_bytes()
    document = json.loads(bindings.MANIFEST.read_text(encoding="utf-8"))
    report = bindings.validate_document(document, *raw)
    assert report["ok"] and report["mapping_complete"] and not report["evidence_complete"]


def test_module_cli_mapping_and_closure_are_distinct(tmp_path):
    ledger, plan, lock = source_inputs()
    paths = [tmp_path / name for name in ("ledger.md", "plan.md", "lock.json", "bindings.json")]
    for path, raw in zip(paths[:3], (ledger, plan, lock), strict=True):
        path.write_bytes(raw)
    paths[3].write_text(json.dumps(bindings.seed_document(ledger, plan, lock)), encoding="utf-8")
    base = [sys.executable, "-m", "tools.gen4_requirements", "--ledger", str(paths[0]),
            "--plan", str(paths[1]), "--lock", str(paths[2]), "--manifest", str(paths[3])]
    mapping = subprocess.run([*base, "--mode", "mapping"], cwd=bindings.ROOT,
                             capture_output=True, text=True, check=False)
    closure = subprocess.run([*base, "--mode", "closure"], cwd=bindings.ROOT,
                             capture_output=True, text=True, check=False)
    assert mapping.returncode == 0 and json.loads(mapping.stdout)["mapping_complete"]
    assert closure.returncode == 1 and not json.loads(closure.stdout)["evidence_complete"]
