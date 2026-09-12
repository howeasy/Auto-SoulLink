"""tools/gen1_battle_fixture.py builds disclosed two-mon fixtures without touching the originals."""
from __future__ import annotations

import hashlib
import json

import pytest

from server.gen1_party_codec import PartyCodec
from tools import gen1_battle_fixture as tool

VARIANTS = ("red", "blue", "yellow")


def engine_checksum(data, start, end):
    # engine/menus/save.asm CalcCheckSum (pokered 298-310, pokeyellow 281-293):
    # d = 0; loop: d += [hl++] (8-bit); result = cpl d. Stored at sMainDataCheckSum.
    total = 0
    for value in data[start:end]:
        total = (total + value) & 0xFF
    return total ^ 0xFF


def built(tmp_path, variant):
    tool.main(["build", "--variant", variant, "--out", str(tmp_path)])
    save = (tmp_path / f"{variant}_battle.SaveRAM").read_bytes()
    manifest = json.loads((tmp_path / f"{variant}_battle.manifest.json").read_text(encoding="utf-8"))
    return save, manifest


@pytest.mark.parametrize("variant", VARIANTS)
def test_fixture_is_sram_sized_with_engine_checksum(tmp_path, variant):
    save, manifest = built(tmp_path, variant)
    o = manifest["offsets"]
    assert len(save) == 32768
    assert save[o["checksum"]] == engine_checksum(save, o["game_data"], o["game_data_end"])
    assert manifest["checksum"] == {"offset": 0x3523, "covers": [0x2598, 0x3523], "value": save[0x3523],
                                    "algorithm": manifest["checksum"]["algorithm"]}


@pytest.mark.parametrize("variant", VARIANTS)
def test_only_documented_ranges_changed_and_original_untouched(tmp_path, variant):
    source = tool.FIXTURES / f"{variant}_battle.SaveRAM"
    before = source.read_bytes()
    save, manifest = built(tmp_path, variant)
    assert source.read_bytes() == before
    assert manifest["source"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert manifest["output"]["sha256"] == hashlib.sha256(save).hexdigest()
    covered = {i for r in manifest["changed_ranges"] for i in range(r["start"], r["end"])}
    changed = {i for i in range(32768) if save[i] != before[i]}
    assert changed <= covered
    labels = {r["label"] for r in manifest["changed_ranges"]}
    assert {"wPartyCount", "wPartySpecies[1..2]", "wPartyMon2", "wPartyMon2OT", "wPartyMon2Nick",
            "wNumBagItems", "sMainDataCheckSum", "slot0_experience_floor"} <= labels
    for r in manifest["changed_ranges"]:
        assert save[r["start"]:r["end"]].hex().upper() == r["after_hex"]
        assert before[r["start"]:r["end"]].hex().upper() == r["before_hex"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_codec_decodes_two_mons_with_expected_keys(tmp_path, variant):
    save, manifest = built(tmp_path, variant)
    o = manifest["offsets"]
    codec = PartyCodec(variant)
    blobs = [tool.slot_blob(save, o, slot) for slot in range(2)]
    mons = codec.validate_party(blobs, species_list=save[o["party_species"]:o["party_species"] + 7])
    assert save[o["party_count"]] == 2
    assert [mon.species_index for mon in mons] == [0xB1, 0x4C]
    assert [mon.level for mon in mons] == [5, 5]
    ditto = mons[1]
    ot_id = int.from_bytes(save[o["player_id"]:o["player_id"] + 2], "big")
    assert ditto.key == f"ABCD:{ot_id:04X}:4C" == manifest["party"]["keys"][1]
    assert ditto.moves == (0x90, 0, 0, 0) and ditto.pp == (10, 0, 0, 0)
    assert ditto.hp == ditto.max_hp and ditto.status == 0 and ditto.box_level == 5
    assert ditto.ot_name == save[o["player_name"]:o["player_name"] + 11]
    assert ditto.nickname[:6] == bytes((0x83, 0x88, 0x93, 0x93, 0x8E, 0x50))
    assert manifest["party"]["added"][0]["party_struct_hex"] == blobs[1][:44].hex().upper()


@pytest.mark.parametrize("variant", VARIANTS)
def test_potion_appended_and_no_battles_bit_left_alone(tmp_path, variant):
    save, manifest = built(tmp_path, variant)
    o = manifest["offsets"]
    count = save[o["num_bag_items"]]
    bag = save[o["bag_items"]:o["bag_items"] + 2 * count + 1]
    assert count == 2 and bag[-3:] == bytes((0x14, 1, 0xFF))
    flags = manifest["status_flags4"]
    assert flags["offset"] == 0x29DA and flags["value"] == save[0x29DA] == 0x10
    assert not any(r["start"] <= 0x29DA < r["end"] for r in manifest["changed_ranges"])


def test_check_mode_is_idempotent_and_detects_drift(tmp_path):
    built(tmp_path, "red")
    tool.main(["build", "--variant", "red", "--out", str(tmp_path), "--check"])
    path = tmp_path / "red_battle.SaveRAM"
    data = bytearray(path.read_bytes())
    data[0x2F60] ^= 1
    path.write_bytes(data)
    with pytest.raises(SystemExit, match="drift"):
        tool.main(["build", "--variant", "red", "--out", str(tmp_path), "--check"])
