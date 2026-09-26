"""Pinned-source byte-oracle controls; synthetic buffers are MODEL, not played saves."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from server.adapters import gen2_codec as codec

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def layout(request):
    return codec.for_foundation(request.param, root=ROOT)


def party_record():
    raw = bytearray(48)
    raw[0:8] = bytes([25, 143, 33, 45, 0, 0, 0x12, 0x34])
    raw[8:11] = bytes.fromhex("012345")
    raw[11:21] = bytes.fromhex("00010004000900100100")
    raw[21:23] = bytes.fromhex("face")
    raw[23:27] = bytes([0xC5, 0x82, 0, 0])
    raw[27:32] = bytes([220, 0x23, 0xA5, 0xC1, 50])
    raw[32:38] = bytes.fromhex("085a00320064")
    raw[38:48] = bytes.fromhex("00780079007a007b007c")
    return bytes(raw)


def test_record_endianness_dvs_pp_and_unknown_bytes(layout):
    raw = party_record()
    mon = codec.decode_party_mon(raw, layout, species_marker=25)
    assert mon["ot_id"] == 0x1234 and mon["exp"] == 0x12345
    assert mon["dv_word"] == 0xFACE
    assert mon["dvs"] == {"attack": 15, "defense": 10, "speed": 12, "special": 14, "hp": 8}
    assert mon["stat_exp"]["special"] == 256
    assert mon["pp"] == [5, 2, 0, 0] and mon["pp_ups"] == [3, 2, 0, 0]
    assert mon["hp"] == 50 and mon["max_hp"] == 100
    assert mon["stats"]["special_attack"] == 123 and mon["stats"]["special_defense"] == 124
    assert mon["aux_bytes_hex"] == "a5c1"
    assert codec.encode_party_mon(mon, layout) == raw
    mon["species_id"] = 26
    encoded = codec.encode_party_mon(mon, layout)
    assert encoded[0] == 26 and encoded[33] == 0x5A


def test_egg_marker_is_not_the_record_species_and_full_key_changes_on_evolution(layout):
    mon = codec.decode_party_mon(party_record(), layout, species_marker=253)
    assert mon["is_egg"] and mon["species_id"] == 25 and mon["species_marker"] == 253
    evolved = {**mon, "species_id": 26}
    assert codec.key(mon) == "FACE:1234:19"
    assert codec.key(evolved) == "FACE:1234:1A"
    assert codec.key(mon) != codec.key(evolved)
    assert codec.key({**mon, "unown_form": 7}) == codec.key(mon)
    with pytest.raises(ValueError):
        codec.decode_party_mon(party_record(), layout, species_marker=26)
    bad = bytearray(party_record())
    bad[0] = 253
    with pytest.raises(ValueError):
        codec.decode_party_mon(bytes(bad), layout, species_marker=253)


def test_seventy_byte_blob_retains_names_and_requires_injected_decoder(layout):
    ot = bytes.fromhex("808150aabbccddeeff0001")
    nick = bytes.fromhex("8283500102030405060708")
    blob = party_record() + ot + nick
    mon = codec.decode_party_blob(blob, layout, species_marker=25)
    assert mon["ot_raw_hex"] == ot.hex() and mon["nickname_raw_hex"] == nick.hex()
    assert "nickname" not in mon
    calls = []
    decoded = codec.decode_party_blob(blob, layout, species_marker=25,
                                     name_decoder=lambda raw: calls.append(raw) or "NAME")
    assert calls == [ot, nick] and decoded["nickname"] == decoded["ot_name"] == "NAME"
    assert codec.encode_party_blob(mon, layout) == blob
    for invalid in (blob[:-1], blob + b"\0"):
        with pytest.raises(ValueError):
            codec.decode_party_blob(invalid, layout, species_marker=25)


def test_box_record_has_no_party_hp_or_status(layout):
    raw = party_record()[:32]
    mon = codec.decode_box_mon(raw, layout, species_marker=25)
    assert "hp" not in mon and "status" not in mon
    assert codec.encode_box_mon(mon, layout) == raw
    with pytest.raises(ValueError):
        codec.decode_box_mon(party_record(), layout, species_marker=25)


@pytest.mark.parametrize("kind", ["party", "box", "blob"])
def test_standalone_records_cannot_infer_egg_status_without_list_marker(layout, kind):
    raw = party_record()
    if kind == "party":
        decode = codec.decode_party_mon
    elif kind == "box":
        decode, raw = codec.decode_box_mon, raw[:32]
    else:
        decode, raw = codec.decode_party_blob, raw + bytes(22)
    for kwargs in ({}, {"species_marker": None}):
        with pytest.raises(ValueError, match="species_marker"):
            decode(raw, layout, **kwargs)
    ordinary = decode(raw, layout, species_marker=25)
    egg = decode(raw, layout, species_marker=253)
    assert ordinary["is_egg"] is False and ordinary["species_marker"] == 25
    assert egg["is_egg"] is True and egg["species_id"] == 25


def box_buffer(layout, count=1):
    raw = bytearray(layout.box_size)
    raw[0] = count
    raw[1] = 253
    raw[count + 1] = 255
    raw[22:54] = party_record()[:32]
    raw[662:673] = b"\x80\x50" + b"\0" * 9
    raw[882:893] = b"\x81\x50" + b"\0" * 9
    return bytes(raw)


def test_box_count_terminator_and_names(layout):
    raw = box_buffer(layout)
    box = codec.decode_box(raw, layout)
    assert box["count"] == 1 and box["mons"][0]["is_egg"]
    assert box["mons"][0]["ot_raw_hex"].startswith("8050")
    assert codec.encode_box(box, layout) == raw
    for offset, value in ((0, 21), (2, 0), (1, 254)):
        bad = bytearray(raw)
        bad[offset] = value
        with pytest.raises(ValueError):
            codec.decode_box(bytes(bad), layout)


@pytest.mark.parametrize("stat_exp,normal,hp", [(0, 135, 240), (10, 136, 241), (65535, 198, 303)])
def test_named_stat_vectors_dv_doubled_and_ceiling_root(stat_exp, normal, hp):
    assert codec.calc_stat(50, 15, stat_exp, 100) == normal
    assert codec.calc_stat(50, 15, stat_exp, 100, is_hp=True) == hp


def test_special_outputs_share_inputs_and_have_distinct_bases():
    bases = {"hp": 250, "attack": 5, "defense": 5, "speed": 50,
             "special_attack": 35, "special_defense": 105}
    dvs = {"attack": 15, "defense": 10, "speed": 12, "special": 10}
    exp = dict.fromkeys(("hp", "attack", "defense", "speed", "special"), 0)
    result = codec.calc_stats(bases, dvs, exp, 50)
    assert result["special_attack"] == 50 and result["special_defense"] == 120
    assert codec.calc_stat(50, 15, 65535, 100, use_stat_exp=False) == 135
    for invalid in (-1, 65536):
        with pytest.raises(ValueError):
            codec.calc_stat(50, 15, invalid, 100)


def valid_save(layout):
    raw = bytearray(0x8000)
    for n, region in enumerate(layout.regions, 1):
        payload = bytes([n]) * region.length
        raw[region.primary:region.primary + region.length] = payload
        raw[region.backup:region.backup + region.length] = payload
    for copy_name in ("primary", "backup"):
        for address, value in layout.markers[copy_name]:
            raw[address] = value
        value = codec.sav_checksum(bytes(raw), layout, copy_name)
        address = layout.checksum_offsets[copy_name]
        raw[address:address + 2] = value.to_bytes(2, "little")
    return bytes(raw)


def test_strict_checksums_and_game_recovery_are_different(layout):
    raw = valid_save(layout)
    assert codec.strict_checksum_witness(raw, layout)["valid"]
    assert codec.game_menu_candidate(raw, layout) == "primary"
    assert codec.game_recovery_view(raw, layout)["selected_copy"] == "primary"
    for damaged, selected in (("primary", "backup"), ("backup", "primary")):
        bad = bytearray(raw)
        bad[layout.checksum_offsets[damaged]] ^= 1
        report = codec.strict_checksum_witness(bytes(bad), layout)
        assert not report["valid"]
        view = codec.game_recovery_view(bytes(bad), layout)
        assert view["selected_copy"] == selected
        assert view["regions"]["pokemon"] == bytes([len(layout.regions)]) * layout.regions[-1].length
    bad = bytearray(raw)
    for offset in layout.checksum_offsets.values():
        bad[offset] ^= 1
    with pytest.raises(ValueError, match="both"):
        codec.game_recovery_view(bytes(bad), layout)


def test_menu_markers_do_not_become_checksum_or_durability_proof(layout):
    raw = bytearray(valid_save(layout))
    raw[layout.markers["primary"][0][0]] ^= 1
    assert codec.game_menu_candidate(bytes(raw), layout) == "backup"
    assert codec.game_recovery_view(bytes(raw), layout)["selected_copy"] == "primary"
    assert not codec.strict_checksum_witness(bytes(raw), layout)["valid"]


def test_different_valid_copies_are_not_strict_same_save_witness(layout):
    raw = bytearray(valid_save(layout))
    raw[layout.regions[0].backup] ^= 1
    value = codec.sav_checksum(bytes(raw), layout, "backup")
    start = layout.checksum_offsets["backup"]
    raw[start:start + 2] = value.to_bytes(2, "little")
    report = codec.strict_checksum_witness(bytes(raw), layout)
    assert report["primary"]["checksum_valid"] and report["backup"]["checksum_valid"]
    assert not report["valid"] and not report["copies_agree"]
    assert codec.game_recovery_view(bytes(raw), layout)["selected_copy"] == "primary"


def test_saved_party_projects_explicit_copy_and_names(layout):
    raw = bytearray(0x8000)
    region = next(region for region in layout.regions if region.name == "pokemon")
    block = bytearray(layout.addresses["wPartyMonNicknamesEnd"] - layout.addresses["wPartyCount"])
    block[0:3] = bytes([1, 253, 255])
    block[8:56] = party_record()
    block[296:307] = b"\x80\x50" + b"\0" * 9
    block[362:373] = b"\x81\x50" + b"\0" * 9
    for copy_name in ("primary", "backup"):
        start = getattr(region, copy_name)
        raw[start:start + len(block)] = block
        decoded = codec.decode_saved_party(bytes(raw), layout, copy_name=copy_name)
        assert decoded["count"] == 1 and decoded["mons"][0]["is_egg"]
        assert decoded["mons"][0]["nickname_raw_hex"].startswith("8150")
        assert decoded["mons"][0]["ot_id"] == 0x1234
    block[2] = 0
    with pytest.raises(ValueError, match="terminated"):
        codec.decode_party(bytes(block), layout)


def test_all_fourteen_boxes_are_structurally_checked_without_checksum_claim(layout):
    raw = bytearray(0x8000)
    for start, size in layout.storage_boxes:
        raw[start:start + size] = box_buffer(layout)
    boxes = codec.verify_boxes(bytes(raw), layout)
    assert len(boxes) == 14 and all(not box["checksummed"] for box in boxes)
    raw[layout.storage_boxes[-1][0]] = 21
    with pytest.raises(ValueError):
        codec.verify_boxes(bytes(raw), layout)


def test_every_backup_span_is_in_checksum_and_boxes_are_not(layout):
    raw = valid_save(layout)
    assert len(layout.checksum_spans["backup"]) == (1 if layout.title == "crystal" else 5)
    for offset, _length in layout.checksum_spans["backup"]:
        bad = bytearray(raw)
        bad[offset] ^= 1
        assert not codec.checksum_report(bytes(bad), layout)["backup"]["checksum_valid"]
    bad = bytearray(raw)
    bad[layout.storage_boxes[0][0] + 30] ^= 1
    report = codec.checksum_report(bytes(bad), layout)
    assert report["primary"]["checksum_valid"] and report["backup"]["checksum_valid"]
    assert report["boxes_checksummed"] is False
    assert not codec.strict_checksum_witness(raw + b"\0" * 22, layout)["valid"]


def test_profile_drift_or_missing_fact_refused(layout):
    profile = copy.deepcopy(layout.profile)
    del profile["titles"][layout.title]["constants"]["MON_DVS"]
    with pytest.raises(ValueError):
        codec.Gen2Layout.from_profile(profile, layout.title)


def test_experience_preserves_source_level_one_underflow():
    assert codec.exp_for_level(100, "GROWTH_MEDIUM_FAST") == 1000000
    assert codec.exp_for_level(100, "GROWTH_MEDIUM_SLOW") == 1059860
    assert codec.exp_for_level(1, "GROWTH_MEDIUM_SLOW") == 0xFFFFCA
    assert codec.level_from_exp(0, "GROWTH_MEDIUM_SLOW") == 1
    assert codec.level_from_exp(1250000, "GROWTH_SLOW") == 100
