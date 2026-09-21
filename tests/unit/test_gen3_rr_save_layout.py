"""Radical Red 4.1 flash-save layout (gen3-P2-C2-8).

The receipts, the verbatim ROM tables and the †UNVERIFIED list live in
docs/gen3/research/rr_save_layout.md.  These tests assert the two things that
can be checked without a ROM: the real RR battery save decodes the way the
pinned layout predicts, and a synthetic image built from ``RR_CHUNK_TABLE``
round-trips through every one of the four places RR hides boxes in.
"""

from pathlib import Path

import pytest

from server.adapters import gen3_codec as C

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gen3" / "rr_town.sav"


@pytest.fixture(scope="module")
def rr_save() -> bytes:
    return FIXTURE.read_bytes()


# --------------------------------------------------------------------------
# The table itself.
# --------------------------------------------------------------------------
def test_rr_chunk_table_is_the_cfru_macro():
    """ROM 0x09148BF0 is byte-for-byte what SAVEBLOCK_CHUNK(0xFF0) produces."""
    derived = [(e["offset"], e["size"]) for e in C.rr_slot_layout()]
    assert derived == list(C.RR_CHUNK_TABLE)
    assert [e["object"] for e in C.rr_slot_layout()] == \
        ["sb2"] + ["sb1"] * 4 + ["storage"] * 9


def test_rr_parasite_pieces_fill_each_section_up_to_the_footer():
    table = dict(enumerate(C.RR_CHUNK_TABLE))
    for sid, piece in C.RR_PARASITE_PIECES.items():
        assert table[sid][1] + piece == C.CHUNK_SIZE_CFRU
    assert sum(C.RR_PARASITE_PIECES.values()) == C.RR_PARASITE_SIZE


def test_rr_box_bases_land_in_exactly_four_regions():
    """19 boxes in storage, 2 in SaveBlock1, 1 in SaveBlock2, 3 in the
    extension -- rr_save_layout.md §3."""
    spans = {
        "sb2": (C.RR_SAVEBLOCK2_ADDR, C.SAVEBLOCK2_SIZE),
        "sb1": (C.RR_SAVEBLOCK1_ADDR, C.SAVEBLOCK1_SIZE),
        "storage": (C.RR_STORAGE_ADDR, C.STORAGE_SIZE),
        "ext": (C.RR_EXT_ADDR, C.RR_EXT_SIZE),
    }
    where = []
    for base in C.RR_BOX_BASES:
        hit = [name for name, (start, size) in spans.items()
               if start <= base and base + C.RR_BOX_STRIDE <= start + size]
        assert len(hit) == 1, f"box at 0x{base:08X} -> {hit}"
        where.append(hit[0])
    assert where == ["storage"] * 19 + ["ext"] * 3 + ["sb1"] * 2 + ["sb2"]
    # Boxes 1-19 exactly fill storage[0x0004 .. 0x8128).
    assert C.RR_BOX_BASES[0] - C.RR_STORAGE_ADDR == C.BOX_DATA_OFFSET
    assert C.RR_BOX_BASES[18] + C.RR_BOX_STRIDE - C.RR_STORAGE_ADDR == 0x8128
    # Box 20 straddles the sector 30 -> 31 boundary.
    box20 = C.RR_BOX_BASES[19] - C.RR_EXT_ADDR
    assert box20 < C.CHUNK_SIZE_CFRU < box20 + C.RR_BOX_STRIDE


# --------------------------------------------------------------------------
# The real RR battery save.
# --------------------------------------------------------------------------
def test_real_rr_save_qualifies_only_under_the_cfru_table(rr_save):
    assert C.qualify_flash(rr_save, cfru=True) == (True, "ok")
    ok, why = C.qualify_flash(rr_save, cfru=False)
    assert not ok and "checksum" in why


def test_real_rr_save_party_is_the_qualify_reported_treecko(rr_save):
    party = C.rr_party_from_save(rr_save)
    assert len(party) == 1
    mon = party[0]
    assert (mon["species"], mon["level"]) == (277, 6)
    assert mon["nickname"] == "Treecko"
    assert mon["ot_name"] == "B"
    assert mon["ot_id"] == 0x2BDDC8BF
    assert mon["personality"] == 0xEBEF11DA
    assert mon["moves"] == [1, 43, 71, 0]
    assert mon["pp"] == [35, 30, 25, 35]
    assert all(v == 31 for v in mon["ivs"].values())
    # CFRU never fills the BoxPokemon checksum, so there is nothing to verify.
    assert mon["checksum"] == 0 and mon["checksum_ok"] is None


def test_real_rr_save_carries_twentyfive_box_names_and_wallpapers(rr_save):
    """The only non-zero bytes in the whole storage object are the two name
    runs and the two wallpaper runs -- rr_save_layout.md §3."""
    storage = C.parse_flash(rr_save, cfru=True)["storage"]
    names = [C.decode_name(storage[o:o + 9])
             for o in range(0x82E1, 0x82E1 + 25 * 9, 9)]
    assert names == [f"Box{n}" for n in range(25, 14, -1)] \
        + [f"Box{n}" for n in range(1, 15)]
    assert storage[0x8128:0x8133] == bytes(
        [0x0C, 0x0D, 0x00, 0x01, 0x00, 0x01, 0x04, 0x05, 0x04, 0x05, 0x08])
    assert storage[0x83C2:0x83D0] == bytes(
        [0x00, 0x01, 0x00, 0x01, 0x04, 0x05, 0x04, 0x05,
         0x08, 0x09, 0x08, 0x09, 0x0C, 0x0D])
    # Nothing else in the 0x83D0 object is set: the 0x8340 bytes of box
    # records really are empty, which is why §7 still lists them UNVERIFIED.
    assert not any(storage[:0x8128]), "box records are not empty"
    assert not any(storage[0x8133:0x82E1]), "unexpected bytes before the names"


def test_real_rr_save_boxes_are_all_empty(rr_save):
    boxes = C.rr_boxes_from_save(rr_save)
    assert len(boxes) == 25
    assert all(len(box) == 30 for box in boxes)
    assert all(mon["species"] == 0 for box in boxes for mon in box)


def test_real_rr_save_parasite_is_outside_the_checksummed_chunk(rr_save):
    """Sections 4 and 13 carry bytes past their chunk size, and their stored
    checksum still verifies over the chunk size alone -- §4."""
    body, _ = C.split_rtc(rr_save)
    layout = C.rr_slot_layout()
    seen = 0
    for index in range(C.SECTORS_COUNT):
        sector = C.read_sector(body, index, layout)
        if not sector["signature_ok"] or sector["id"] not in (4, 13):
            continue
        seen += 1
        size = layout[sector["id"]]["size"]
        raw = body[index * C.SECTOR_SIZE:(index + 1) * C.SECTOR_SIZE]
        assert sector["checksum_ok"], f"sector {index} id {sector['id']}"
        assert any(raw[size:C.CHUNK_SIZE_CFRU]), "expected parasite bytes"
        assert raw[C.CHUNK_SIZE_CFRU:C.OFF_SECTOR_ID] == b"\0\0\0\0"
    assert seen == 4          # both slots, ids 4 and 13


def test_real_rr_save_uses_sectors_30_31_and_never_28_29(rr_save):
    body, _ = C.split_rtc(rr_save)
    for index in (28, 29):
        assert body[index * C.SECTOR_SIZE:(index + 1) * C.SECTOR_SIZE] \
            == b"\xff" * C.SECTOR_SIZE, "HOF sector was written"
    for index in C.RR_EXT_SECTORS:
        raw = body[index * C.SECTOR_SIZE:(index + 1) * C.SECTOR_SIZE]
        assert 0xFF not in raw, "extension sector looks erased, not written"
        assert raw[C.OFF_SECTOR_ID:] == bytes(12), "extension has a footer"


# --------------------------------------------------------------------------
# Synthetic round trip through all four hiding places.
# --------------------------------------------------------------------------
def _compressed(species: int, personality: int, ot_id: int) -> bytes:
    """A minimal CFRU CompressedPokemon: header + species in Growth."""
    raw = bytearray(C.COMPRESSED_MON_SIZE)
    raw[0x00:0x04] = personality.to_bytes(4, "little")
    raw[0x04:0x08] = ot_id.to_bytes(4, "little")
    raw[0x08:0x12] = C.encode_name("Rr", C.NICKNAME_LEN)
    raw[0x12] = 2                      # language
    raw[0x13] = 0x02                   # hasSpecies
    raw[0x14:0x1B] = C.encode_name("B", C.OT_NAME_LEN)
    raw[0x1C:0x1E] = species.to_bytes(2, "little")
    return bytes(raw)


def _build_rr_image(sb2: bytes, sb1: bytes, storage: bytes, ext: bytes,
                    counter: int = 2, rotation: int = 0) -> bytes:
    """Write an RR slot the way the game does: RR_CHUNK_TABLE chunks into
    ((rotation+id) % 14) + 14*(counter % 2), extension verbatim into 30/31."""
    layout = C.rr_slot_layout()
    body = bytearray(b"\xff" * C.FLASH_SIZE)
    source = {"sb2": sb2, "sb1": sb1, "storage": storage}
    for sid, entry in enumerate(layout):
        chunk = source[entry["object"]][
            entry["offset"]:entry["offset"] + entry["size"]]
        index = ((rotation + sid) % 14) + 14 * (counter % 2)
        body[index * C.SECTOR_SIZE:(index + 1) * C.SECTOR_SIZE] = \
            C.write_sector(chunk, sid, counter, layout)
    for n, index in enumerate(C.RR_EXT_SECTORS):
        body[index * C.SECTOR_SIZE:(index + 1) * C.SECTOR_SIZE] = \
            ext[n * C.CHUNK_SIZE_CFRU:(n + 1) * C.CHUNK_SIZE_CFRU] \
            .ljust(C.SECTOR_SIZE, b"\0")
    return bytes(body)


PROBES = (
    (0, 0, 0x0111),       # box 1, slot 0   -> storage
    (18, 29, 0x0222),     # box 19, slot 29 -> storage, the last one in
    (19, 21, 0x0333),     # box 20, slot 21 -> STRADDLES sector 30 -> 31
    (21, 7, 0x0444),      # box 22          -> sector 31
    (23, 29, 0x0555),     # box 24, slot 29 -> SaveBlock1
    (24, 29, 0x0666),     # box 25, slot 29 -> SaveBlock2
)


def test_synthetic_rr_image_round_trips_every_box_region():
    blocks = {C.RR_SAVEBLOCK2_ADDR: bytearray(C.SAVEBLOCK2_SIZE),
              C.RR_SAVEBLOCK1_ADDR: bytearray(C.SAVEBLOCK1_SIZE),
              C.RR_STORAGE_ADDR: bytearray(C.STORAGE_SIZE),
              C.RR_EXT_ADDR: bytearray(C.RR_EXT_SIZE)}
    sb1 = blocks[C.RR_SAVEBLOCK1_ADDR]
    sb1[C.SB1_PARTY_COUNT_OFFSET] = 1
    sb1[C.SB1_PARTY_OFFSET:C.SB1_PARTY_OFFSET + C.PARTY_MON_SIZE] = \
        C.expand_compressed_box_mon(_compressed(277, 0xDEADBEEF, 0x2BDDC8BF)) \
        + bytes(C.PARTY_MON_SIZE - C.BOX_MON_SIZE)
    sb1[C.SB1_PARTY_OFFSET + 0x54] = 6      # party-tail level

    for box, slot, species in PROBES:
        addr = C.RR_BOX_BASES[box] + slot * C.COMPRESSED_MON_SIZE
        base = max(b for b in blocks if b <= addr)
        off = addr - base
        blocks[base][off:off + C.COMPRESSED_MON_SIZE] = \
            _compressed(species, 0x1000 + box, 0x2BDDC8BF)

    image = _build_rr_image(bytes(blocks[C.RR_SAVEBLOCK2_ADDR]),
                            bytes(sb1),
                            bytes(blocks[C.RR_STORAGE_ADDR]),
                            bytes(blocks[C.RR_EXT_ADDR]),
                            counter=2, rotation=5)
    assert C.qualify_flash(image, cfru=True) == (True, "ok")

    party = C.rr_party_from_save(image)
    assert len(party) == 1
    assert (party[0]["species"], party[0]["level"]) == (277, 6)
    assert party[0]["nickname"] == "Rr"

    boxes = C.rr_boxes_from_save(image)
    found = {(b, s): mon["species"]
             for b, box in enumerate(boxes)
             for s, mon in enumerate(box) if mon["species"]}
    assert found == {(box, slot): species for box, slot, species in PROBES}


def test_synthetic_rr_image_keeps_the_tail_of_every_0xff0_chunk():
    """Falsifier for truncating CFRU chunks at the vanilla 0xF80 data area:
    SaveBlock1 +0xFB0 lives in the last 0x70 bytes of section id 1."""
    sb1 = bytearray(C.SAVEBLOCK1_SIZE)
    sb1[0xFB0:0xFB4] = b"tail"
    image = _build_rr_image(bytes(C.SAVEBLOCK2_SIZE), bytes(sb1),
                            bytes(C.STORAGE_SIZE), bytes(C.RR_EXT_SIZE))
    assert C.parse_flash(image, cfru=True)["sb1"][0xFB0:0xFB4] == b"tail"


def test_rr_boxes_refuse_an_erased_extension():
    image = bytearray(_build_rr_image(
        bytes(C.SAVEBLOCK2_SIZE), bytes(C.SAVEBLOCK1_SIZE),
        bytes(C.STORAGE_SIZE), bytes(C.RR_EXT_SIZE)))
    for index in C.RR_EXT_SECTORS:
        image[index * C.SECTOR_SIZE:(index + 1) * C.SECTOR_SIZE] = \
            b"\xff" * C.SECTOR_SIZE
    with pytest.raises(ValueError) as excinfo:
        C.rr_boxes_from_save(bytes(image))
    assert "30/31" in str(excinfo.value)
    # The party lives in SaveBlock1, so it is still readable.
    assert C.rr_party_from_save(bytes(image)) == []
