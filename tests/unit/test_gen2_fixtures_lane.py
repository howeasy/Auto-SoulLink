"""verify_gen2_release.py --fixtures (BINDING P3b.2): PLAYED with a pinned receipt, or SYNTH with an O-33
disclosure, and nothing else. Synthetic receipts here are MODEL, never cartridge evidence."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import verify_gen2_release as gate  # noqa: E402

PLAYED = b"PLAYED-BASE-" * 8
FIELDS = [{"symbol": "wStepCount", "offset": 0, "wram": 1, "size": 1, "primary": 2, "backup": 3,
           "old_hex": "00", "new_hex": "7f"}]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(name, raw, *, repo):
    """Stands in for qualified_identity(): the receipt must bind THESE bytes."""
    receipt = json.loads((repo / "tests/fixtures/gen2/receipts" / f"{name}.qualification.json").read_text("utf-8"))
    if receipt["fixture_sha256"] != _sha(raw):
        raise AssertionError(f"{name}: staged fixture bytes differ from the qualified candidate")
    return 1


def _rebuild(title, base, edits, *, root, base_name):
    return base + edits["tail"].encode(), {"fields": FIELDS}


def _witness(root, title, raw):
    return "fails the strict checksum/marker/copy witness" if raw.startswith(b"BAD") else None


def _tree(tmp_path, *, synth=True):
    fixtures = tmp_path / "tests/fixtures/gen2"
    (fixtures / "receipts").mkdir(parents=True)
    (fixtures / "crystal_town.SaveRAM").write_bytes(PLAYED)
    receipt = json.dumps({"fixture_sha256": _sha(PLAYED)}).encode()
    (fixtures / "receipts/crystal_town.qualification.json").write_bytes(receipt)
    doc = {"requirements": [{"id": "q", "axes": {"kind": "qualification", "fixture": "crystal_town"},
                             "proofs": [{"receipts": {"receipt": {
                                 "path": "tests/fixtures/gen2/receipts/crystal_town.qualification.json",
                                 "sha256": _sha(receipt)}}}]}]}
    (tmp_path / gate.NEW_GATES).write_text(json.dumps(doc), encoding="utf-8")
    if synth:
        built = PLAYED + b"grass"
        (fixtures / "crystal_synth_grass.SaveRAM").write_bytes(built)
        _disclose(tmp_path, {"schema": gate.SYNTH_SCHEMA, "builder": "tools/gen2_synth_fixtures.py",
                             "title": "crystal", "base_fixture": "crystal_town", "base_sha256": _sha(PLAYED),
                             "sha256": _sha(built), "edits": {"tail": "grass"}, "fields": FIELDS,
                             "source_facts": ["engine/overworld/events.asm CountStep"], "checksums": "restored"})
    return tmp_path


def _disclose(root, disclosure):
    path = root / "tests/fixtures/gen2/crystal_synth_grass.synth.json"
    path.write_text(json.dumps(disclosure), encoding="utf-8")


def _errors(root, names=("crystal_town", "crystal_synth_grass")):
    return gate.fixtures_errors(root, names=set(names), identity=_identity, witness=_witness, rebuild=_rebuild)


def _edit(root, name, **changes):
    path = root / "tests/fixtures/gen2" / f"{name}.synth.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(changes)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_played_plus_disclosed_synth_is_the_only_green(tmp_path):
    assert _errors(_tree(tmp_path)) == []


def test_an_empty_inventory_is_not_a_pass(tmp_path):
    assert gate.fixtures_errors(_tree(tmp_path), names=set(), identity=_identity, witness=_witness,
                                rebuild=_rebuild) != []


def test_a_referenced_fixture_that_is_missing_is_red(tmp_path):
    errors = _errors(_tree(tmp_path), names=("crystal_town", "crystal_synth_grass", "gold_battle"))
    assert errors == ["gold_battle: tests/fixtures/gen2/gold_battle.SaveRAM missing"]


def test_an_undisclosed_fixture_is_red(tmp_path):
    root = _tree(tmp_path)
    (root / "tests/fixtures/gen2/gold_town.SaveRAM").write_bytes(PLAYED)
    errors = _errors(root, names=("crystal_town", "gold_town"))
    assert len(errors) == 1 and errors[0].startswith("gold_town: undisclosed")


def test_played_bytes_edited_after_qualification_are_stale(tmp_path):
    root = _tree(tmp_path, synth=False)
    (root / "tests/fixtures/gen2/crystal_town.SaveRAM").write_bytes(PLAYED + b"!")
    assert any("staged fixture bytes differ" in e for e in _errors(root, names=("crystal_town",)))


def test_an_edited_played_receipt_breaks_its_pin(tmp_path):
    root = _tree(tmp_path, synth=False)
    (root / "tests/fixtures/gen2/receipts/crystal_town.qualification.json").write_text(
        json.dumps({"fixture_sha256": _sha(PLAYED), "note": "edited"}), encoding="utf-8")
    assert any("sha256 differs from its pin" in e for e in _errors(root, names=("crystal_town",)))


def test_a_played_pin_to_another_receipt_path_is_red(tmp_path):
    root = _tree(tmp_path, synth=False)
    doc = json.loads((root / gate.NEW_GATES).read_text(encoding="utf-8"))
    doc["requirements"][0]["proofs"][0]["receipts"]["receipt"]["path"] = "tests/elsewhere.json"
    (root / gate.NEW_GATES).write_text(json.dumps(doc), encoding="utf-8")
    assert any("no sha256-pinned qualification receipt" in e for e in _errors(root, names=("crystal_town",)))


def test_checksum_witness_failure_is_red_even_when_qualified(tmp_path):
    root = _tree(tmp_path, synth=False)
    (root / "tests/fixtures/gen2/crystal_town.SaveRAM").write_bytes(b"BAD" + PLAYED)
    (root / "tests/fixtures/gen2/receipts/crystal_town.qualification.json").write_text("{}", encoding="utf-8")
    assert any("checksum" in e for e in _errors(root, names=("crystal_town",)))


@pytest.mark.parametrize(("changes", "want"), [
    ({"schema": "gen2-synth-disclosure-v0"}, "is not a gen2-synth-disclosure-v1"),
    ({"builder": "hand-edited"}, "is not a gen2-synth-disclosure-v1"),
    ({"title": "gold"}, "is not a gen2-synth-disclosure-v1"),
    ({"sha256": "0" * 64}, "does not cover the committed bytes"),
    ({"fields": []}, "lists no changed fields"),
    ({"fields": [{"symbol": "wStepCount"}]}, "lists no changed fields"),
    ({"source_facts": []}, "names no edits or source facts"),
    ({"base_fixture": "crystal_synth_grass"}, "is not a PLAYED, qualified fixture"),
    ({"base_fixture": "gold_town"}, "is not a PLAYED, qualified fixture"),
    ({"base_sha256": "0" * 64}, "differ from the disclosed base_sha256"),
    ({"edits": {"tail": "kyle"}}, "does not reproduce the file"),
])
def test_an_invalid_synth_disclosure_is_red(tmp_path, changes, want):
    root = _tree(tmp_path)
    _edit(root, "crystal_synth_grass", **changes)
    errors = _errors(root)
    assert any(e.startswith("crystal_synth_grass: ") and want in e for e in errors), errors


def test_a_synth_fixture_without_a_disclosure_is_undisclosed(tmp_path):
    root = _tree(tmp_path)
    (root / "tests/fixtures/gen2/crystal_synth_grass.synth.json").unlink()
    assert any(e.startswith("crystal_synth_grass: undisclosed") for e in _errors(root))


def test_a_synth_on_a_stale_played_base_is_red(tmp_path):
    root = _tree(tmp_path)
    (root / "tests/fixtures/gen2/receipts/crystal_town.qualification.json").write_text("{}", encoding="utf-8")
    errors = _errors(root)
    assert any(e.startswith("crystal_synth_grass: SYNTH base 'crystal_town'") for e in errors), errors


def test_the_real_checksum_witness_passes_a_committed_fixture_and_refuses_a_flipped_byte():
    """Known-positive control for the production witness, then its revert test."""
    raw = (REPO / "tests/fixtures/gen2/crystal_town.SaveRAM").read_bytes()
    assert gate._checksum_witness(REPO, "crystal", raw) is None
    flipped = bytearray(raw)
    flipped[0x2009] ^= 0xFF   # inside the primary sGameData span
    assert gate._checksum_witness(REPO, "crystal", bytes(flipped)) is not None
    assert gate._checksum_witness(REPO, "crystal", raw[:-1]) is not None


def test_a_single_cart_offset_field_is_a_valid_disclosure_shape(tmp_path):
    """The builder records checksum-style fields at one CartRAM offset ("cart"), not a primary/backup pair."""
    root = _tree(tmp_path)
    cart = {"symbol": "sChecksum", "offset": 0, "wram": None, "size": 2, "cart": 9, "old_hex": "0000", "new_hex": "beef"}

    def check(fields):
        _edit(root, "crystal_synth_grass", fields=fields)
        return gate.fixtures_errors(root, names={"crystal_town", "crystal_synth_grass"}, identity=_identity,
                                    witness=_witness, rebuild=lambda t, b, e, **_k: (b + e["tail"].encode(),
                                                                                     {"fields": fields}))

    assert check([*FIELDS, cart]) == []
    assert check([{**cart, "primary": 1}]) != []


def test_committed_fixture_inventory_is_green():
    """Every Gen 2 fixture the release lanes stage is PLAYED (pinned full chain) or a valid O-33 SYNTH."""
    assert gate.fixtures_errors() == []
