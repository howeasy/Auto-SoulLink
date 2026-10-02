"""Disclosed fifth usable record for the native PC negative release chain."""
import hashlib
import json
from pathlib import Path

import pytest

from tools import gen3_fixtures as f

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/gen3"
KIND = "pc_negative_chain_synth"
FILE = FIXTURES / f"exp_{KIND}.sav"


def _records(body):
    c = f.codec
    parsed = c.parse_flash(body, title=c.TITLE_EXPANSION)
    count, start = c._TITLE_PARTY_OFFSETS[c.TITLE_EXPANSION]
    party = [parsed["sb1"][start + i * c.PARTY_MON_SIZE:start + (i + 1) * c.PARTY_MON_SIZE]
             for i in range(parsed["sb1"][count])]
    boxes = [parsed["storage"][c.BOX_DATA_OFFSET + i * c.BOX_MON_SIZE:
                                c.BOX_DATA_OFFSET + (i + 1) * c.BOX_MON_SIZE]
             for i in range(c.BOXES_PER_STORE * c.MONS_PER_BOX)]
    return parsed, party, boxes


def test_missing_chain_fixture_and_builder_are_registered():
    assert hasattr(f, "build_exp_pc_negative_chain_seed"), "chain fixture builder absent"
    assert FILE.is_file(), "chain fixture absent"
    assert f.exp_kind_of(FILE) == KIND and KIND in f.EXP_KINDS


def test_one_new_usable_identity_preserves_every_old_record_exactly():
    seed = (FIXTURES / "exp_pc.sav").read_bytes()
    raw = f.build_exp_pc_negative_chain_seed(seed)
    before, old_party, old_boxes = _records(seed)
    after, new_party, new_boxes = _records(raw)
    assert old_party == new_party
    assert all(old == new for slot, (old, new) in enumerate(zip(old_boxes, new_boxes)) if slot != 2)
    assert old_boxes[2] == bytes(f.codec.BOX_MON_SIZE) and new_boxes[2] != old_boxes[2]
    expected = bytearray(before["storage"])
    at = f.codec.BOX_DATA_OFFSET + 2 * f.codec.BOX_MON_SIZE
    expected[at:at + f.codec.BOX_MON_SIZE] = new_boxes[2]
    assert bytes(expected) == after["storage"]
    party = f.codec.party_from_save(raw, title=f.codec.TITLE_EXPANSION, layout=f._record_layout(f.codec.TITLE_EXPANSION))
    boxes = f.codec.boxes_from_save(raw, title=f.codec.TITLE_EXPANSION, layout=f._record_layout(f.codec.TITLE_EXPANSION))
    owned = party + [m for row in boxes for m in row if m["personality"] or m["ot_id"]]
    assert len(owned) == len({(m["personality"], m["ot_id"]) for m in owned}) == 5
    assert all(m["checksum_ok"] and not m["is_egg"] and not m["is_bad_egg"] and m["species"] for m in owned)
    assert all(m["hp"] > 0 for m in party)


def test_raw_and_native_hashes_have_separate_manifest_roles():
    manifest = json.loads((FIXTURES / "exp_pc_negative_chain_synth_manifest.json").read_text())
    seed = (ROOT / manifest["seed"]).read_bytes()
    raw = f.build_exp_pc_negative_chain_seed(seed)
    assert hashlib.sha256(seed).hexdigest() == manifest["seed_sha256"]
    assert hashlib.sha256(raw).hexdigest() == manifest["raw_sha256"]
    assert manifest["initial_usable"] == 5 and manifest["release_chain_usable"] == [5, 4, 3, 3, 2]
    assert manifest["qualification_status"] in ("PENDING", "NATIVE_CONTINUE_SAVE_ONLY")
    saved = FILE.read_bytes()
    if manifest["qualification_status"] == "PENDING":
        assert manifest["sha256"] is None
        assert saved == raw  # not a native-save qualification claim
    else:
        assert hashlib.sha256(saved).hexdigest() == manifest["sha256"]
        assert f.exp_fixture_problems(saved, KIND) == []
        assert f.boot_check_verdict(f.qualify_one(raw, rr=False, title=f.codec.TITLE_EXPANSION),
                                  f.qualify_one(saved, rr=False, title=f.codec.TITLE_EXPANSION)) == (True, [])


def test_builder_refuses_an_occupied_extra_slot():
    raw = f.build_exp_pc_negative_chain_seed((FIXTURES / "exp_pc.sav").read_bytes())
    with pytest.raises(ValueError, match="slot 2"):
        f.build_exp_pc_negative_chain_seed(raw)


@pytest.mark.parametrize("fault", ("missing_extra", "duplicate_extra", "old_party_hp"))
def test_strict_qualifier_refuses_record_drift_after_modeled_save_controls(fault):
    raw = f.build_exp_pc_negative_chain_seed((FIXTURES / "exp_pc.sav").read_bytes())
    assert any("CONTINUE_GAME_WARP" in p for p in f.exp_fixture_problems(raw, KIND))
    c = f.codec
    parsed = c.parse_flash(raw, title=c.TITLE_EXPANSION)
    sb1, sb2, storage = bytearray(parsed["sb1"]), bytearray(parsed["sb2"]), bytearray(parsed["storage"])
    sb2[9] &= ~1  # MODEL only: test semantic refusal independently of the physical SAVE signer.
    model = f.exp_write_slot({"sb1": bytes(sb1), "sb2": bytes(sb2), "storage": bytes(storage)},
                             counter=parsed["counter"] + 1)
    assert f.exp_fixture_problems(model, KIND) == []
    at = c.BOX_DATA_OFFSET + 2 * c.BOX_MON_SIZE
    if fault == "missing_extra":
        storage[at:at + c.BOX_MON_SIZE] = bytes(c.BOX_MON_SIZE)
    elif fault == "duplicate_extra":
        storage[at:at + c.BOX_MON_SIZE] = storage[c.BOX_DATA_OFFSET:c.BOX_DATA_OFFSET + c.BOX_MON_SIZE]
    else:
        party_start = c._TITLE_PARTY_OFFSETS[c.TITLE_EXPANSION][1]
        sb1[party_start + 0x56:party_start + 0x58] = bytes(2)
    changed = f.exp_write_slot({"sb1": bytes(sb1), "sb2": bytes(sb2), "storage": bytes(storage)},
                              counter=parsed["counter"] + 1)
    assert f.exp_fixture_problems(changed, KIND)
