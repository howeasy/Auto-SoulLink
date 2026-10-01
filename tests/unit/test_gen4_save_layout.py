"""Falsifiers for the flash-save half of server/adapters/gen4_codec.py.

Real-save tests follow tests/TESTING.md: an ABSENT save skips with a reason naming it, a
PRESENT save whose content contradicts the pinned expectations FAILS.  The synthetic controls
need no files.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from server.adapters import gen4_codec as codec

HGSS, HGE, PT = (codec.PROFILES[k] for k in ("hgss", "hge", "pt"))
SAVE_DIR = Path("E:/Howard/Bizhawk/NDS/SaveRAM")


# ---------------------------------------------------------------------------
# Synthetic saves (built here from the footer description, not through the codec's scanner)
# ---------------------------------------------------------------------------
def footer(profile, count, size, slot, crc, block_counter=0) -> bytes:
    if profile.name == "pt":
        return struct.pack(profile.footer_fmt, count, block_counter, size, codec.SAVE_CHUNK_MAGIC, slot, crc)
    return struct.pack(profile.footer_fmt, count, size, codec.SAVE_CHUNK_MAGIC, slot, crc)


def block(profile, body: bytes, size: int, count: int, slot: int) -> bytes:
    """``size`` bytes: body zero-padded, then the footer with the CRC over everything before it."""
    fsz = profile.footer_size
    data = body.ljust(size - fsz, b"\0")
    return data + footer(profile, count, size, slot, codec.crc16_ccitt(data))


def bank_bytes(profile, gen_count, pc_count, *, gen_body=b"", pc_body=b"", gen_size=0xF628,
               pc_at=0xF700, pc_size=0x12310) -> bytes:
    out = bytearray(codec.BANK_SIZE)
    out[:gen_size] = block(profile, gen_body, gen_size, gen_count, 0)
    out[pc_at : pc_at + pc_size] = block(profile, pc_body, pc_size, pc_count, 1)
    return bytes(out)


def image(bank0: bytes | None, bank1: bytes | None) -> bytes:
    blank = b"\xff" * codec.BANK_SIZE
    return (bank0 or blank) + (bank1 or blank)


def party_body(profile, species_level_hp=((155, 5, 20),)) -> bytes:
    """A general-block body holding a party at the profile's offset."""
    body = bytearray(profile.party_off + 8 + 6 * codec.PARTY_MON_SIZE)
    struct.pack_into("<II", body, profile.party_off, 6, len(species_level_hp))
    for i, (sp, lv, hp) in enumerate(species_level_hp):
        plain = bytearray(codec.PARTY_MON_SIZE)
        struct.pack_into("<I", plain, 0, 0x1000 + i)
        struct.pack_into("<HHI", plain, 8, sp, 0, 0x74C066C6)
        struct.pack_into("<BxHH", plain, 0x8C, lv, hp, hp)
        off = profile.party_off + 8 + i * codec.PARTY_MON_SIZE
        body[off : off + codec.PARTY_MON_SIZE] = codec.encrypt_party(bytes(plain))
    return bytes(body)


def flip(img: bytes, off: int) -> bytes:
    b = bytearray(img)
    b[off] ^= 0x40
    return bytes(b)


def test_valid_bank_parses_and_party_decodes():
    save = codec.parse_save(image(None, bank_bytes(HGSS, 3, 3, gen_body=party_body(HGSS))), "hgss")
    assert (save.bank, save.counter, len(save.general), len(save.pc)) == (1, 3, 0xF628, 0x12310)
    assert save.blocks[(1, 1)].start == 0x40000 + 0xF700 and save.fallback == ""
    (mon,) = save.party()
    assert (mon["species"], mon["level"], mon["hp"], mon["max_hp"]) == (155, 5, 20, 20)


def test_newest_counter_wins_and_older_bank_is_not_returned():
    img = image(bank_bytes(HGSS, 7, 7), bank_bytes(HGSS, 6, 6))
    assert codec.parse_save(img, "hgss").bank == 0
    img = image(bank_bytes(HGSS, 6, 6), bank_bytes(HGSS, 7, 7))
    assert codec.parse_save(img, "hgss").bank == 1


@pytest.mark.parametrize(("c0", "c1", "winner"), [
    (0xFFFFFFFF, 0, 1),            # (-1, 0): 0 is newer after the wrap
    (0, 0xFFFFFFFF, 0),            # (0, -1)
    (0xFFFFFFFE, 0xFFFFFFFF, 1),   # ordinary numeric
    (1, 0xFFFFFFFF, 1),            # numeric: only the exact (0,-1) pair is special
])
def test_counter_wrap(c0, c1, winner):
    img = image(bank_bytes(HGSS, c0, c0), bank_bytes(HGSS, c1, c1))
    assert codec.parse_save(img, "hgss").bank == winner


def test_equal_counters_are_ambiguous():
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.parse_save(image(bank_bytes(HGSS, 4, 4), bank_bytes(HGSS, 4, 4)), "hgss")
    assert exc.value.reason == "ambiguous"


def test_torn_newest_bank_falls_back_with_reason():
    good, newer = bank_bytes(HGSS, 4, 4), bank_bytes(HGSS, 5, 5)
    for torn_at, where in ((0x10, "general"), (0xF700 + 0x10, "pc")):   # a body byte of each block
        save = codec.parse_save(image(good, flip(newer, torn_at)), "hgss")
        assert save.bank == 0 and save.counter == 4
        assert save.fallback == f"bank1: torn:{where}:crc", torn_at


def test_torn_only_bank_is_refused_not_decoded():
    for torn_at in (0x10, 0xF700 + 0x10):
        with pytest.raises(codec.Gen4CodecError) as exc:
            codec.parse_save(image(None, flip(bank_bytes(HGSS, 1, 1), torn_at)), "hgss")
        assert exc.value.reason == "no_usable_bank" and "torn" in str(exc.value)


def test_general_pc_counter_disagreement_is_refused():
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.parse_save(image(None, bank_bytes(HGSS, 5, 4)), "hgss")
    assert exc.value.reason == "no_usable_bank" and "general_pc_disagree" in str(exc.value)
    # a disagreeing NEWER bank must not shadow a coherent older one
    save = codec.parse_save(image(bank_bytes(HGSS, 3, 3), bank_bytes(HGSS, 5, 4)), "hgss")
    assert save.bank == 0 and "general_pc_disagree" in save.fallback


def test_blank_and_wrongly_sized_images_refused():
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.parse_save(image(None, None), "hgss")
    assert exc.value.reason == "no_save"
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.parse_save(b"\xff" * 0x40000, "hgss")
    assert exc.value.reason == "size"


def test_two_valid_footers_for_one_slot_are_refused_as_duplicate():
    b = bytearray(bank_bytes(HGSS, 2, 2, pc_at=0xF700, pc_size=0x1000))
    b[0x20000 : 0x21000] = block(HGSS, b"", 0x1000, 2, 1)       # a second CRC-valid PC block
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.parse_save(image(None, bytes(b)), "hgss")
    assert exc.value.reason == "no_usable_bank" and "duplicate" in str(exc.value)


def test_footer_with_wrong_geometry_does_not_count():
    # A PC footer that claims a start before the general block's end / unaligned is not valid.
    b = bytearray(bank_bytes(HGSS, 2, 2, pc_at=0xF700 + 0x10, pc_size=0x1000))   # not 0x100-aligned
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.parse_save(image(None, bytes(b)), "hgss")
    assert exc.value.reason == "no_usable_bank" and "geometry" in str(exc.value)


def test_geometry_comes_from_the_footers_not_the_profile():
    big = bank_bytes(HGE, 9, 9, gen_size=0xFFA0, pc_at=0x10000, pc_size=0x1E4FC)
    save = codec.parse_save(image(big, None), "hge")
    assert (len(save.general), len(save.pc), save.blocks[(0, 1)].start) == (0xFFA0, 0x1E4FC, 0x10000)


def test_pc_boxes_decode_and_corruption_is_named():
    plain = bytearray(codec.BOX_MON_SIZE)
    struct.pack_into("<IHH", plain, 0, 0x2468, 0, 0)
    struct.pack_into("<HHII", plain, 8, 25, 0, 0x11110000 | 7, 0)
    pc = bytearray(HGSS.names_off + 18 * HGSS.names_stride)
    slot_off = 3 * HGSS.box_stride + 5 * codec.BOX_MON_SIZE                # box 3, slot 5
    pc[slot_off : slot_off + codec.BOX_MON_SIZE] = codec.encrypt_box(bytes(plain))
    struct.pack_into("<I", pc, HGSS.cur_box_off, 3)
    struct.pack_into("<I", pc, HGSS.modified_off, 0b1000)
    pc[HGSS.names_off : HGSS.names_off + 40] = struct.pack("<20H", *codec.encode_name("Stash", 20))
    img = image(None, bank_bytes(HGSS, 1, 1, pc_body=bytes(pc)))
    save = codec.parse_save(img, "hgss")
    boxes = save.boxes()
    assert len(boxes) == 18 and boxes[0]["name"] == "Stash" and boxes[0]["mons"] == {}
    assert list(boxes[3]["mons"]) == [5] and boxes[3]["mons"][5]["species"] == 25
    assert save.pc_meta() == {"box_count": 18, "cur_box": 3, "modified": 8}
    pc[slot_off + 0x20] ^= 0xFF                                            # corrupt that record
    bad = codec.parse_save(image(None, bank_bytes(HGSS, 1, 1, pc_body=bytes(pc))), "hgss")
    with pytest.raises(codec.Gen4CodecError, match="box 3 slot 5"):
        bad.boxes()


def test_platinum_footer_has_block_counter_and_unknown_offsets_stay_unknown():
    # Same save, Pt footer {count, blockCounter, size, magic, blockID, crc}: 0x14 bytes.
    assert PT.footer_size == 0x14 and PT.magic_off == 12 and HGSS.footer_size == 0x10
    img = image(bank_bytes(PT, 2, 2, gen_size=0x1000, pc_at=0x1000, pc_size=0x2000), None)
    save = codec.parse_save(img, "pt")
    assert (save.bank, save.counter, len(save.pc)) == (0, 2, 0x2000)
    with pytest.raises(codec.Gen4CodecError) as exc:
        save.party()
    assert exc.value.reason == "party_offset_unknown"
    assert PT.modified_off is None and PT.box_stride == 0xFF0 and PT.cur_box_off == 0
    with pytest.raises(codec.Gen4CodecError) as exc:
        save.player()
    assert exc.value.reason == "player_offset_unknown"
    # a Pt-footer save is not an HGSS-footer save: the magic sits at a different footer offset
    with pytest.raises(codec.Gen4CodecError):
        codec.parse_save(img, "hgss")


# ---------------------------------------------------------------------------
# Real saves
# ---------------------------------------------------------------------------
def real_save(env: str, default: str | None, what: str) -> bytes:
    raw = os.environ.get(env) or (str(SAVE_DIR / default) if default else None)
    if not raw:
        pytest.skip(f"{what} not provisioned: set {env}")
    path = Path(raw)
    if not path.is_file():
        pytest.skip(f"{what} not found: {path} (override with {env})")
    return path.read_bytes()


@pytest.fixture(scope="module")
def hg_image() -> bytes:
    return real_save("SLINK_GEN4_HG_SAVE", "Pokemon - HeartGold Version (USA).SaveRAM",
                     "HeartGold battery save")


@pytest.fixture(scope="module")
def hge_image() -> bytes:
    return real_save("SLINK_GEN4_HGE_SAVE", "patched hge ap.SaveRAM", "hg-engine battery save")


def test_real_hg_save_geometry_and_party(hg_image):
    save = codec.parse_save(hg_image, "hgss")
    assert (save.bank, save.counter, save.fallback) == (1, 1, "")
    g, p = save.blocks[(1, 0)], save.blocks[(1, 1)]
    assert (g.start, g.size, g.state) == (0x40000, 0xF628, "valid")
    assert (p.start, p.size, p.state) == (0x40000 + 0xF700, 0x12310, "valid")
    assert save.blocks[(0, 0)].state == save.blocks[(0, 1)].state == "absent"
    (mon,) = save.party()
    assert (mon["species"], mon["level"], mon["hp"], mon["max_hp"]) == (155, 5, 20, 20)
    assert (mon["tid"], mon["sid"], mon["ot_name"]) == (26310, 29888, "SPLERM")
    assert mon["key"] == f"{mon['pid']:08X}:74C066C6" and mon["tail_plausible"]
    assert mon["origin_game"] == codec.VERSION_HEARTGOLD and mon["ability"] and mon["moves"][0]


def test_real_hg_save_player_profile_and_empty_pc(hg_image):
    save = codec.parse_save(hg_image, "hgss")
    me = save.player()
    assert (me["name"], me["tid"], me["sid"], me["money"], me["version"]) == ("SPLERM", 26310, 29888, 3000, 7)
    assert (me["gender"], me["language"], me["johto_badges"], me["kanto_badges"]) == (1, 2, 0, 0)
    assert sum(len(b["mons"]) for b in save.boxes()) == 0 and save.pc_meta()["cur_box"] == 0


def test_real_hg_party_record_reencrypts_byte_for_byte_and_refuses_a_flip(hg_image):
    save = codec.parse_save(hg_image, "hgss")
    raw = save.general[HGSS.party_off + 8 : HGSS.party_off + 8 + codec.PARTY_MON_SIZE]
    assert codec.encrypt_party(codec.decrypt_party(raw)) == raw
    bad = bytearray(raw)
    bad[0x30] ^= 0x01
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.decode_party_mon(bytes(bad), HGSS)
    assert exc.value.reason == "checksum"


def test_real_hg_save_torn_copy_is_refused(hg_image):
    for off in (0x40000 + 0x100, 0x40000 + 0xF700 + 0x100):
        with pytest.raises(codec.Gen4CodecError) as exc:
            codec.parse_save(flip(hg_image, off), "hgss")
        assert exc.value.reason == "no_usable_bank"


def test_real_hge_save_geometry_boxes_and_empty_party(hge_image):
    save = codec.parse_save(hge_image, "hge")
    assert save.bank == 1 and save.fallback == ""
    g, p = save.blocks[(1, 0)], save.blocks[(1, 1)]
    assert (g.size, g.state, p.start - 0x40000, p.size, p.state) == (0xFFA0, "valid", 0x10000, 0x1E4FC, "valid")
    assert save.party() == []                                    # empty save: cannot confirm party_off
    boxes = save.boxes()
    assert [b["name"] for b in boxes] == [f"Box {i}" for i in range(1, 31)]
    assert all(not b["mons"] for b in boxes) and save.pc_meta()["cur_box"] == 0
    me = save.player()
    assert me["money"] == 3000 and me["version"] == 7


def test_real_platinum_save_decode():
    img = real_save("SLINK_GEN4_PT_SAVE", None, "Platinum battery save (the local AutoSaveRAM is blank 0xFF)")
    save = codec.parse_save(img, "pt")
    assert save.pc and save.general


def test_local_blank_platinum_save_is_refused_not_decoded():
    img = real_save("SLINK_GEN4_PT_BLANK", "Pokemon - Platinum Version (USA).AutoSaveRAM.SaveRAM",
                    "blank Platinum AutoSaveRAM")
    if set(img) != {0xFF}:
        pytest.skip("the local Platinum AutoSaveRAM is no longer blank; point SLINK_GEN4_PT_SAVE at it")
    with pytest.raises(codec.Gen4CodecError) as exc:
        codec.parse_save(img, "pt")
    assert exc.value.reason == "no_save"
