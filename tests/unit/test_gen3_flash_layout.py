"""Falsifiers for the flash-save half of server/adapters/gen3_codec.py.

The images here are synthetic 128 KiB buffers built by this file: no ROM,
no real save, no emulator.  The layout claims they pin come from
pret/pokefirered c75f352304d529f6ba92d4f74b9cf8b5c3810788 and from
docs/gen3/research/flash_save.md §1-§3.
"""

import pytest

from server.adapters import gen3_codec as codec

C = codec


def _blocks(seed: int) -> dict[str, bytes]:
    """Three distinguishable save objects; every byte depends on `seed`."""
    return {
        "sb2": bytes((seed + i) & 0xFF for i in range(C.SAVEBLOCK2_SIZE)),
        "sb1": bytes((seed + 2 * i) & 0xFF for i in range(C.SAVEBLOCK1_SIZE)),
        "storage": bytes((seed + 3 * i) & 0xFF for i in range(C.STORAGE_SIZE)),
    }


def _write_half(image: bytearray, counter: int, blocks: dict[str, bytes],
                rotation: int = 0, layout=None) -> None:
    """Place one full 14-section slot the way HandleWriteSector does:
    physical = ((rotation + id) % 14) + 14 * (counter % 2)
    (src/save.c#L167-L195)."""
    layout = layout or C.slot_layout()
    half = C.NUM_SECTORS_PER_SLOT * (counter % C.NUM_SAVE_SLOTS)
    for entry in layout:
        sid = entry["id"]
        chunk = blocks[entry["object"]][entry["offset"]:
                                        entry["offset"] + entry["size"]]
        physical = half + (rotation + sid) % C.NUM_SECTORS_PER_SLOT
        image[physical * C.SECTOR_SIZE:(physical + 1) * C.SECTOR_SIZE] = \
            C.write_sector(chunk, sid, counter, layout)


def _image(*halves, rtc: bytes = b"") -> bytes:
    """halves: (counter, blocks[, rotation]) tuples."""
    image = bytearray(C.FLASH_SIZE)
    for half in halves:
        _write_half(image, half[0], half[1], *(half[2:]))
    return bytes(image) + rtc


def _sector_slice(image: bytes, index: int) -> bytearray:
    return bytearray(image[index * C.SECTOR_SIZE:(index + 1) * C.SECTOR_SIZE])


def _put_sector(image: bytes, index: int, raw: bytes) -> bytes:
    out = bytearray(image)
    out[index * C.SECTOR_SIZE:(index + 1) * C.SECTOR_SIZE] = raw
    return bytes(out)


# --- Geometry ---------------------------------------------------------------

def test_sector_geometry_constants():
    # include/save.h#L6-L30.
    assert C.SECTOR_DATA_SIZE + C.SECTOR_FOOTER_SIZE == C.SECTOR_SIZE == 0x1000
    assert C.SECTORS_COUNT * C.SECTOR_SIZE == C.FLASH_SIZE == 0x20000
    assert C.NUM_SECTORS_PER_SLOT == 14 and C.NUM_SAVE_SLOTS == 2
    assert C.SECTOR_SIGNATURE == 0x08012025
    # Footer offsets derived from struct SaveSector (include/save.h#L63-L71).
    assert (C.OFF_SECTOR_ID, C.OFF_SECTOR_CHECKSUM,
            C.OFF_SECTOR_SIGNATURE, C.OFF_SECTOR_COUNTER) == \
        (0x0FF4, 0x0FF6, 0x0FF8, 0x0FFC)


def test_vanilla_chunk_table():
    """flash_save.md §1, derived from src/save.c#L43-L72 with 0xF80 chunks."""
    expected = [
        (0, "sb2", 0x0000, 0x0F24),
        (1, "sb1", 0x0000, 0x0F80), (2, "sb1", 0x0F80, 0x0F80),
        (3, "sb1", 0x1F00, 0x0F80), (4, "sb1", 0x2E80, 0x0EE8),
        (5, "storage", 0x0000, 0x0F80), (6, "storage", 0x0F80, 0x0F80),
        (7, "storage", 0x1F00, 0x0F80), (8, "storage", 0x2E80, 0x0F80),
        (9, "storage", 0x3E00, 0x0F80), (10, "storage", 0x4D80, 0x0F80),
        (11, "storage", 0x5D00, 0x0F80), (12, "storage", 0x6C80, 0x0F80),
        (13, "storage", 0x7C00, 0x07D0),
    ]
    got = [(e["id"], e["object"], e["offset"], e["size"])
           for e in C.slot_layout()]
    assert got == expected
    assert all(e["size"] <= C.SECTOR_DATA_SIZE for e in C.slot_layout())


def test_cfru_chunk_table_variant():
    """flash_save.md §3: CFRU uses 0xFF0 chunks, so the split boundaries move
    while the object extents stay F24/3D68/83D0.  UPSTREAM CFRU, not a
    qualified RR 4.1 fact."""
    expected = [
        (0, "sb2", 0x0000, 0x0F24),
        (1, "sb1", 0x0000, 0x0FF0), (2, "sb1", 0x0FF0, 0x0FF0),
        (3, "sb1", 0x1FE0, 0x0FF0), (4, "sb1", 0x2FD0, 0x0D98),
        (5, "storage", 0x0000, 0x0FF0), (6, "storage", 0x0FF0, 0x0FF0),
        (7, "storage", 0x1FE0, 0x0FF0), (8, "storage", 0x2FD0, 0x0FF0),
        (9, "storage", 0x3FC0, 0x0FF0), (10, "storage", 0x4FB0, 0x0FF0),
        (11, "storage", 0x5FA0, 0x0FF0), (12, "storage", 0x6F90, 0x0FF0),
        (13, "storage", 0x7F80, 0x0450),
    ]
    got = [(e["id"], e["object"], e["offset"], e["size"])
           for e in C.slot_layout(C.CHUNK_SIZE_CFRU)]
    assert got == expected


def test_object_sizes_cover_their_sections():
    for layout in (C.slot_layout(), C.slot_layout(C.CHUNK_SIZE_CFRU)):
        for name, total in (("sb2", C.SAVEBLOCK2_SIZE),
                            ("sb1", C.SAVEBLOCK1_SIZE),
                            ("storage", C.STORAGE_SIZE)):
            parts = [e for e in layout if e["object"] == name]
            assert parts[0]["offset"] == 0
            assert parts[-1]["offset"] + parts[-1]["size"] == total
    # include/pokemon_storage_system.h#L44-L50: boxes are 4-aligned, and
    # boxNames land exactly at 0x8344.
    assert C.BOX_DATA_OFFSET + C.BOXES_PER_STORE * C.MONS_PER_BOX * \
        C.BOX_MON_SIZE == C.BOX_NAMES_OFFSET


# --- Checksum ---------------------------------------------------------------

def test_sector_checksum_folds_the_u32_sum():
    """src/save.c#L614-L628."""
    assert C.sector_checksum(b"\x00" * 16, 16) == 0
    # A single word, no fold needed.
    assert C.sector_checksum((0x1234).to_bytes(4, "little") + b"\x00" * 12, 16) \
        == 0x1234
    # The fold: a u32 sum of 0x00023456 returns (0x0002 + 0x3456) = 0x3458.
    assert C.sector_checksum((0x00023456).to_bytes(4, "little") + b"\x00" * 12,
                             16) == 0x3458
    # The accumulator wraps at u32 before folding: 0xFFFFFFFF + 2 -> 1.
    data = (0xFFFFFFFF).to_bytes(4, "little") + (2).to_bytes(4, "little")
    assert C.sector_checksum(data, 8) == 1


def test_checksum_uses_the_section_size_not_the_sector():
    """Bytes past the section's chunk size must not enter the checksum."""
    layout = C.slot_layout()
    raw = bytearray(C.write_sector(b"\x11" * 0x0F24, 0, 7, layout))
    stored = int.from_bytes(raw[C.OFF_SECTOR_CHECKSUM:C.OFF_SECTOR_CHECKSUM + 2],
                            "little")
    raw[0x0F30] = 0xFF          # inside the sector, past SaveBlock2's 0xF24
    assert C.sector_checksum(bytes(raw), layout[0]["size"]) == stored


def test_write_sector_footer_placement():
    layout = C.slot_layout()
    raw = C.write_sector(b"\xAB" * 0x0F24, 0, 0x01020304, layout)
    assert len(raw) == C.SECTOR_SIZE
    assert raw[0x0F23] == 0xAB and raw[0x0F24] == 0x00
    assert int.from_bytes(raw[0x0FF4:0x0FF6], "little") == 0
    assert int.from_bytes(raw[0x0FF8:0x0FFC], "little") == C.SECTOR_SIGNATURE
    assert int.from_bytes(raw[0x0FFC:0x1000], "little") == 0x01020304


# --- Slot selection ---------------------------------------------------------

def test_single_slot_parses_and_qualifies():
    blocks = _blocks(1)
    image = _image((4, blocks))
    parsed = C.parse_flash(image)
    assert parsed["status_name"] == "OK"
    assert parsed["counter"] == 4 and parsed["slot"] == 0
    assert parsed["sb2"] == blocks["sb2"]
    assert parsed["sb1"] == blocks["sb1"]
    assert parsed["storage"] == blocks["storage"]
    assert C.qualify_flash(image) == (True, "ok")


def test_rotation_is_learned_from_section_zero():
    image = _image((4, _blocks(1), 5))
    parsed = C.parse_flash(image)
    assert parsed["rotation"] == 5
    assert parsed["sb1"] == _blocks(1)["sb1"]
    assert C.qualify_flash(image)[0] is True


def test_higher_counter_wins():
    old, new = _blocks(1), _blocks(200)
    image = _image((4, old), (5, new))
    parsed = C.parse_flash(image)
    assert parsed["counter"] == 5 and parsed["slot"] == 1
    assert parsed["sb1"] == new["sb1"]
    assert C.qualify_flash(image) == (True, "ok")


def test_counter_wrap_prefers_zero_over_ffffffff():
    """src/save.c#L534-L543: the explicit FFFFFFFF/0 pair selects 0."""
    wrapped, fresh = _blocks(1), _blocks(200)
    image = _image((0xFFFFFFFF, wrapped), (0, fresh))
    parsed = C.parse_flash(image)
    assert parsed["counter"] == 0 and parsed["slot"] == 0
    assert parsed["sb1"] == fresh["sb1"]


def test_counter_tie_keeps_slot_one():
    """src/save.c#L546-L549: a numeric tie falls through to slot 1's counter."""
    a, b = _blocks(1), _blocks(200)
    image = bytearray(C.FLASH_SIZE)
    _write_half(image, 4, a)
    # Force the second physical half to carry the same counter.
    layout = C.slot_layout()
    for entry in layout:
        chunk = b[entry["object"]][entry["offset"]:entry["offset"] + entry["size"]]
        physical = C.NUM_SECTORS_PER_SLOT + entry["id"]
        image[physical * C.SECTOR_SIZE:(physical + 1) * C.SECTOR_SIZE] = \
            C.write_sector(chunk, entry["id"], 4, layout)
    parsed = C.parse_flash(bytes(image))
    assert parsed["counter"] == 4 and parsed["slot"] == 0
    assert parsed["sb1"] == a["sb1"]


def test_empty_image_is_empty_not_ok():
    parsed = C.parse_flash(bytes(C.FLASH_SIZE))
    assert parsed["status_name"] == "EMPTY"
    ok, reason = C.qualify_flash(bytes(C.FLASH_SIZE))
    assert ok is False and "signature" in reason


# --- Strict refusals --------------------------------------------------------

def test_torn_save_mixed_counters_is_refused():
    image = _image((4, _blocks(1)))
    raw = _sector_slice(image, 3)
    raw[C.OFF_SECTOR_COUNTER:C.OFF_SECTOR_COUNTER + 4] = (3).to_bytes(4, "little")
    torn = _put_sector(image, 3, bytes(raw))
    ok, reason = C.qualify_flash(torn)
    assert ok is False and "torn" in reason
    # The game's own loader still recovers it: recovery and qualification differ.
    assert C.parse_flash(torn)["status_name"] == "OK"


def test_missing_sector_is_refused():
    image = _image((4, _blocks(1)))
    gutted = _put_sector(image, 7, bytes(C.SECTOR_SIZE))
    ok, reason = C.qualify_flash(gutted)
    assert ok is False and "signature" in reason
    assert C.parse_flash(gutted)["status_name"] != "OK"


def test_duplicate_section_id_is_refused():
    image = _image((0, _blocks(1)))
    raw = _sector_slice(image, 6)
    layout = C.slot_layout()
    # Re-label sector 6 as id 5 and re-checksum so only the duplicate is wrong.
    raw[C.OFF_SECTOR_ID:C.OFF_SECTOR_ID + 2] = (5).to_bytes(2, "little")
    raw[C.OFF_SECTOR_CHECKSUM:C.OFF_SECTOR_CHECKSUM + 2] = \
        C.sector_checksum(bytes(raw), layout[5]["size"]).to_bytes(2, "little")
    dup = _put_sector(image, 6, bytes(raw))
    ok, reason = C.qualify_flash(dup)
    assert ok is False and "duplicate" in reason and "missing [6]" in reason


def test_bad_checksum_is_refused():
    image = _image((4, _blocks(1)))
    raw = _sector_slice(image, 2)
    raw[0x10] ^= 0xFF
    bad = _put_sector(image, 2, bytes(raw))
    ok, reason = C.qualify_flash(bad)
    assert ok is False and "checksum" in reason


def test_out_of_range_section_id_is_refused():
    image = _image((4, _blocks(1)))
    raw = _sector_slice(image, 1)
    raw[C.OFF_SECTOR_ID:C.OFF_SECTOR_ID + 2] = (99).to_bytes(2, "little")
    bogus = _put_sector(image, 1, bytes(raw))
    ok, reason = C.qualify_flash(bogus)
    assert ok is False
    assert "out-of-range" in reason or "checksum" in reason or "missing" in reason
    # And parse_flash must not index the layout out of bounds.
    C.parse_flash(bogus)


def test_one_good_slot_beside_a_damaged_one_is_refused():
    image = bytearray(_image((4, _blocks(1)), (5, _blocks(200))))
    # Damage one sector of the newer slot: status drops to ERROR.
    image[(C.NUM_SECTORS_PER_SLOT + 2) * C.SECTOR_SIZE + 0x20] ^= 0xFF
    ok, reason = C.qualify_flash(bytes(image))
    assert ok is False and ("checksum" in reason or "ERROR" in reason)


# --- RTC suffix and lengths -------------------------------------------------

def test_optional_rtc_suffix_is_split_not_assumed():
    """flash_save.md §2: 16 bytes of mGBA RTC state, present only for
    real-time configurations -- never subtracted unconditionally."""
    blocks = _blocks(1)
    rtc = bytes(range(0x10))
    assert C.split_rtc(_image((4, blocks))) == (_image((4, blocks)), b"")
    body, suffix = C.split_rtc(_image((4, blocks), rtc=rtc))
    assert len(body) == C.FLASH_SIZE and suffix == rtc
    parsed = C.parse_flash(_image((4, blocks), rtc=rtc))
    assert parsed["rtc"] == rtc and parsed["sb1"] == blocks["sb1"]
    assert C.qualify_flash(_image((4, blocks), rtc=rtc)) == (True, "ok")


@pytest.mark.parametrize("length", [0, 0x10000, 0x20008, 0x20011, 0x30000])
def test_other_lengths_are_refused_not_guessed(length):
    with pytest.raises(ValueError):
        C.split_rtc(bytes(length))
    ok, reason = C.qualify_flash(bytes(length))
    assert ok is False and "length" in reason


# --- Save-level extraction --------------------------------------------------

def _party_mon(personality: int) -> dict:
    return {
        "personality": personality, "ot_id": 0x11223344,
        "nickname": "PIKA", "language": 2,
        "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0,
        "block_box_rs": 0, "flags_unused": 0,
        "ot_name": "RED", "markings": 0, "unknown": 0,
        "species": 25, "held_item": 0, "experience": 1000,
        "pp_bonuses": 0, "friendship": 70, "growth_filler": 0,
        "moves": [84, 45, 86, 0], "pp": [30, 40, 20, 0],
        "evs": {"hp": 0, "attack": 0, "defense": 0,
                "speed": 0, "sp_attack": 0, "sp_defense": 0},
        "contest": [0] * 6,
        "pokerus": 0, "met_location": 1, "met_level": 5,
        "met_game": 4, "pokeball": 4, "ot_gender": 0,
        "ivs": {"hp": 10, "attack": 11, "defense": 12,
                "speed": 13, "sp_attack": 14, "sp_defense": 15},
        "is_egg": 0, "ability_num": 0, "ribbons": 0,
        "status": 0, "level": 12, "mail": 0xFF, "hp": 30, "max_hp": 33,
        "attack": 18, "defense": 14, "speed": 25, "sp_attack": 16,
        "sp_defense": 15,
    }


def test_party_and_boxes_round_trip_through_a_synthetic_save():
    sb1 = bytearray(C.SAVEBLOCK1_SIZE)
    sb1[C.SB1_PARTY_COUNT_OFFSET] = 2
    for slot in range(2):
        start = C.SB1_PARTY_OFFSET + slot * C.PARTY_MON_SIZE
        sb1[start:start + C.PARTY_MON_SIZE] = \
            codec.encode_party_mon(_party_mon(0x18000 + slot))

    boxed = dict(_party_mon(0x18007))
    boxed["species"] = 151
    storage = bytearray(C.STORAGE_SIZE)
    where = C.BOX_DATA_OFFSET + (3 * C.MONS_PER_BOX + 7) * C.BOX_MON_SIZE
    storage[where:where + C.BOX_MON_SIZE] = codec.encode_box_mon(boxed)

    image = _image((6, {"sb2": bytes(C.SAVEBLOCK2_SIZE),
                        "sb1": bytes(sb1), "storage": bytes(storage)}))
    party = codec.party_from_save(image)
    assert [m["species"] for m in party] == [25, 25]
    assert [m["personality"] for m in party] == [0x18000, 0x18001]
    assert all(m["checksum_ok"] for m in party)

    boxes = codec.boxes_from_save(image)
    assert len(boxes) == C.BOXES_PER_STORE
    assert all(len(b) == C.MONS_PER_BOX for b in boxes)
    assert boxes[3][7]["species"] == 151
    assert boxes[3][7]["checksum_ok"] is True
    assert boxes[3][6]["has_species"] == 0


def test_rr_save_extraction_is_refused_with_a_citation():
    image = _image((4, _blocks(1)))
    for call in (codec.party_from_save, codec.boxes_from_save):
        with pytest.raises(NotImplementedError) as excinfo:
            call(image, rr=True)
        assert "flash_save.md" in str(excinfo.value)
        assert "UNVERIFIED" in str(excinfo.value)
