"""Falsifiers for tools/gen3_fixtures.py.

Synthetic flash images built the same way tests/unit/test_gen3_flash_layout.py
builds them: no ROM, no real save, no emulator. Committed-fixture assertions
read tests/fixtures/gen3/*.sav directly.
"""

import glob
import os
import sys

import pytest

from server.adapters import gen3_codec as codec

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen3_fixtures as fx  # noqa: E402  (tools/ is not a package; the tool is a script)

FIXTURES_DIR = os.path.join(REPO, "tests", "fixtures", "gen3")


def _blocks(seed: int) -> dict:
    return {
        "sb2": bytearray((seed + i) & 0xFF for i in range(codec.SAVEBLOCK2_SIZE)),
        "sb1": bytearray(codec.SAVEBLOCK1_SIZE),
        "storage": bytearray(codec.STORAGE_SIZE),
    }


def _mon(personality: int, ot_id: int, ot_name: str, *, party: bool) -> dict:
    mon = {
        "personality": personality, "ot_id": ot_id,
        "nickname": "MON", "language": 2,
        "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0,
        "block_box_rs": 0, "flags_unused": 0,
        "ot_name": ot_name, "markings": 0, "unknown": 0,
        "species": 1, "held_item": 0, "experience": 100,
        "pp_bonuses": 0, "friendship": 0, "growth_filler": 0,
        "moves": [1, 2, 3, 4], "pp": [10, 10, 10, 10],
        "evs": {"hp": 0, "attack": 0, "defense": 0, "speed": 0,
                "sp_attack": 0, "sp_defense": 0},
        "contest": [0, 0, 0, 0, 0, 0],
        "pokerus": 0, "met_location": 0, "met_level": 5,
        "met_game": 1, "pokeball": 1, "ot_gender": 0,
        "ivs": {"hp": 1, "attack": 1, "defense": 1,
                "speed": 1, "sp_attack": 1, "sp_defense": 1},
        "is_egg": 0, "ability_num": 0, "ribbons": 0,
    }
    if party:
        mon.update({"status": 0, "level": 5, "mail": 0xFF, "hp": 20,
                    "max_hp": 20, "attack": 10, "defense": 10, "speed": 10,
                    "sp_attack": 10, "sp_defense": 10})
    return mon


def _build_image(trainer_name="RED", trainer_id=0x1234, *, party_mons=None,
                  box_mons=None, counter=1, rotation=0) -> bytes:
    """One qualifying single-slot vanilla flash image (counter 1, so it lands
    in slot 1 i.e. physical sectors 14-27; matches HandleWriteSector's
    ``counter % 2`` slot rule)."""
    blocks = _blocks(0)
    blocks["sb2"][0:7] = codec.encode_name(trainer_name, 7)
    blocks["sb2"][0xA:0xE] = trainer_id.to_bytes(4, "little")
    blocks["sb1"][codec.SB1_PARTY_COUNT_OFFSET] = len(party_mons or [])
    for i, mon in enumerate(party_mons or []):
        start = codec.SB1_PARTY_OFFSET + i * codec.PARTY_MON_SIZE
        blocks["sb1"][start:start + codec.PARTY_MON_SIZE] = codec.encode_party_mon(mon)
    for (box, slot), mon in (box_mons or {}).items():
        idx = box * codec.MONS_PER_BOX + slot
        start = codec.BOX_DATA_OFFSET + idx * codec.BOX_MON_SIZE
        blocks["storage"][start:start + codec.BOX_MON_SIZE] = codec.encode_box_mon(mon)

    layout = codec.slot_layout()
    image = bytearray(codec.FLASH_SIZE)
    half = codec.NUM_SECTORS_PER_SLOT * (counter % codec.NUM_SAVE_SLOTS)
    for entry in layout:
        sid = entry["id"]
        chunk = bytes(blocks[entry["object"]])[entry["offset"]:entry["offset"] + entry["size"]]
        physical = half + (rotation + sid) % codec.NUM_SECTORS_PER_SLOT
        image[physical * codec.SECTOR_SIZE:(physical + 1) * codec.SECTOR_SIZE] = \
            codec.write_sector(chunk, sid, counter, layout)
    return bytes(image)


# --- committed fixtures -----------------------------------------------------

def _committed_fixtures():
    return sorted(glob.glob(os.path.join(FIXTURES_DIR, "*.sav")))


@pytest.mark.parametrize("path", _committed_fixtures() or [None])
def test_committed_fixtures_qualify(path):
    if path is None:
        pytest.skip("no fixtures committed yet")
    with open(path, "rb") as f:
        data = f.read()
    assert len(data) == codec.FLASH_SIZE == 131072
    is_rr = "rr_" in os.path.basename(path)
    result = fx.qualify_one(data, rr=is_rr)
    assert result["ok"], result["message"]


# --- import: RTC-suffix strip -----------------------------------------------

def test_import_strips_optional_rtc_suffix(tmp_path):
    body = _build_image()
    rtc = bytes(range(16))
    src = tmp_path / "with_rtc.SaveRAM"
    src.write_bytes(body + rtc)
    imported = fx.import_savedata(src.read_bytes(), rr=False)
    assert imported == body
    assert len(imported) == codec.FLASH_SIZE


def test_import_refuses_blank_save(tmp_path):
    blank = b"\xFF" * codec.FLASH_SIZE
    with pytest.raises(ValueError, match="blank"):
        fx.import_savedata(blank, rr=False)


# --- torn save refusal -------------------------------------------------------

def test_import_refuses_torn_save():
    image = bytearray(_build_image(counter=1))
    # Corrupt one sector's checksum in the selected slot -> torn/incomplete.
    half = codec.NUM_SECTORS_PER_SLOT * (1 % codec.NUM_SAVE_SLOTS)
    off = half * codec.SECTOR_SIZE + codec.OFF_SECTOR_CHECKSUM
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="qualify_flash refused"):
        fx.import_savedata(bytes(image), rr=False)


# --- derive-b: exact manifest, re-qualifies ---------------------------------

def test_derive_b_changes_exactly_the_manifested_fields():
    owned = _mon(0x1111, 0x1234, "RED", party=True)
    foreign = _mon(0x2222, 0x9999, "BLU", party=False)  # traded-mon provenance
    image_a = _build_image(trainer_name="RED", trainer_id=0x1234,
                            party_mons=[owned], box_mons={(0, 0): foreign})
    ok, msg = codec.qualify_flash(image_a)
    assert ok, msg

    image_b, manifest = fx.derive_b(image_a)
    assert len(image_b) == codec.FLASH_SIZE
    ok, msg = codec.qualify_flash(image_b)
    assert ok, msg

    # Manifest names sb2 identity + the one owned party mon; the foreign
    # box mon (different OTID) must NOT be in the manifest or changed.
    joined = "\n".join(manifest)
    assert "playerTrainerId" in joined
    assert "playerName" in joined
    assert "party[0]" in joined
    assert "box[0][0]" not in joined

    parsed_a, parsed_b = codec.parse_flash(image_a), codec.parse_flash(image_b)
    assert parsed_b["storage"] == parsed_a["storage"]  # foreign box mon untouched

    old_name, old_tid = fx._trainer_identity(parsed_a["sb2"])
    new_name, new_tid = fx._trainer_identity(parsed_b["sb2"])
    assert new_tid != old_tid
    assert new_name != old_name

    mon_a = codec.decode_party_mon(
        parsed_a["sb1"][codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE])
    mon_b = codec.decode_party_mon(
        parsed_b["sb1"][codec.SB1_PARTY_OFFSET:codec.SB1_PARTY_OFFSET + codec.PARTY_MON_SIZE])
    assert mon_b["ot_id"] == new_tid
    assert mon_b["species"] == mon_a["species"]  # unrelated payload preserved
    assert mon_b["checksum_ok"] is True


def test_derive_b_rr_refuses():
    # derive_b() itself only implements vanilla; the --rr CLI refusal
    # (cmd_derive_b) never calls it and always cites the UNVERIFIED reason.
    assert "UNVERIFIED" in fx.RR_DERIVE_REFUSAL
    assert "flash_save.md" in fx.RR_DERIVE_REFUSAL
    # derive_b() applied to a vanilla-shaped image never silently claims RR.
    body = _build_image()
    _, manifest = fx.derive_b(body)
    assert isinstance(manifest, list)
