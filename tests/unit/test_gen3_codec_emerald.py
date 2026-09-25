"""Falsifiers for the Emerald additions to server/adapters/gen3_codec.py
(E1-CODEC).

Two independent SOURCE controls, plus a synthetic round-trip and a pin on
the frozen damage-calc contract:

(a) HEADER control: struct GFRomHeader (pret/pokeemerald src/rom_header_gf.c
    #L18-L90 at c65e93f2) is read straight out of the owner's ROM at file
    offset 0x100.  This test computes the struct's byte offsets ITSELF
    (ARM EABI alignment: u32/pointer fields need 4-byte alignment, u8
    fields don't) rather than importing them from gen3_codec.py, so a
    codec constant that silently drifted from the real struct would not
    also make this control pass.
(b) A synthetic Emerald flash image (this file's own encoder, mirroring
    tests/unit/test_gen3_flash_layout.py's FR/LG pattern) round-trips
    through the codec's title="emerald" party/box decoders.
(c) tests/unit/test_gen3_codec.py and test_gen3_flash_layout.py stay green
    unchanged (run alongside this file; no title="emerald" default changed
    any FR/LG/RR call site).
"""

from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec

C = codec

ROM_PATH = Path("E:/Google Drive/SLink/Pokemon - Emerald Version (USA, Europe).gba")
ROM_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"   # pret rom.sha1, PLAN.md §0


def _load_rom() -> bytes:
    if not ROM_PATH.exists():
        pytest.skip("local Emerald ROM absent")
    data = ROM_PATH.read_bytes()
    import hashlib
    if hashlib.sha1(data).hexdigest() != ROM_SHA1:
        pytest.skip("ROM present but sha1 does not match the pinned Emerald ROM")
    return data


# --- (a) HEADER control ------------------------------------------------------

def test_gf_header_matches_the_codecs_emerald_save_constants():
    """struct GFRomHeader, field by field, ARM EABI alignment (src/rom_header_gf.c#L18-L90):

    u32 version, language;            +0x00, +0x04
    u8  gameName[32];                 +0x08 .. +0x28
    10x pointer (4B each):            +0x28 .. +0x50
    9x  u32 (flags..pokedexCount):    +0x50 .. +0x74
    4x  u8  (name lengths):           +0x74 .. +0x78
    13x u8  (unk5..unk17):            +0x78 .. +0x85
    -> next field is u32, realign 0x85 up to 0x88 (4-byte align)
    u32 saveBlock2Size                +0x88
    u32 saveBlock1Size                +0x8C
    u32 partyCountOffset              +0x90
    u32 partyOffset                   +0x94

    This offset walk is independent of gen3_codec.py; only the final
    asserted values are compared against it.
    """
    rom = _load_rom()
    base = 0x100

    def u32(off):
        return int.from_bytes(rom[base + off:base + off + 4], "little")

    assert rom[base + 0x08:base + 0x08 + 24] == b"pokemon emerald version\x00"
    assert u32(0x50) == 0x1270          # flagsOffset  (SaveBlock1.flags)
    assert u32(0x54) == 0x139C          # varsOffset   (SaveBlock1.vars)
    assert u32(0x88) == codec.SAVEBLOCK2_SIZE_EMERALD
    assert u32(0x8C) == codec.SAVEBLOCK1_SIZE_EMERALD
    assert u32(0x90) == codec.SB1_PARTY_COUNT_OFFSET_EMERALD
    assert u32(0x94) == codec.SB1_PARTY_OFFSET_EMERALD
    # Sanity anchor unrelated to save layout, so a struct-offset slip in the
    # walk above (rather than a genuine constant error) would show up here too.
    assert u32(0x58) == 0x18            # pokedexOffset (SaveBlock2.pokedex)


def test_emerald_save_sizes_differ_from_frlg_as_the_plan_predicts():
    """docs/gen3_emerald/research/facts_2026-09-25.md §A3: SB2 0xF2C (FR
    0xF24), SB1 0x3D88 (FR 0x3D68); party moved from +0x34/+0x38 to
    +0x234/+0x238."""
    assert codec.SAVEBLOCK2_SIZE_EMERALD == 0x0F2C != codec.SAVEBLOCK2_SIZE
    assert codec.SAVEBLOCK1_SIZE_EMERALD == 0x3D88 != codec.SAVEBLOCK1_SIZE
    assert (codec.SB1_PARTY_COUNT_OFFSET_EMERALD, codec.SB1_PARTY_OFFSET_EMERALD) == (0x234, 0x238)
    assert (codec.SB1_PARTY_COUNT_OFFSET, codec.SB1_PARTY_OFFSET) == (0x34, 0x38)


# --- (b) Synthetic Emerald flash round-trip ----------------------------------

def _write_half(image: bytearray, counter: int, blocks: dict[str, bytes],
                layout: list[dict]) -> None:
    half = C.NUM_SECTORS_PER_SLOT * (counter % C.NUM_SAVE_SLOTS)
    for entry in layout:
        sid = entry["id"]
        chunk = blocks[entry["object"]][entry["offset"]:entry["offset"] + entry["size"]]
        physical = half + sid
        image[physical * C.SECTOR_SIZE:(physical + 1) * C.SECTOR_SIZE] = \
            C.write_sector(chunk, sid, counter, layout)


def _party_mon(personality: int, species: int) -> dict:
    return {
        "personality": personality, "ot_id": 0x11223344,
        "nickname": "TREECKO", "language": 2,
        "is_bad_egg": 0, "has_species": 1, "is_egg_flag": 0,
        "block_box_rs": 0, "flags_unused": 0,
        "ot_name": "MAY", "markings": 0, "unknown": 0,
        "species": species, "held_item": 0, "experience": 1000,
        "pp_bonuses": 0, "friendship": 70, "growth_filler": 0,
        "moves": [33, 45, 0, 0], "pp": [35, 40, 0, 0],
        "evs": {"hp": 0, "attack": 0, "defense": 0,
                "speed": 0, "sp_attack": 0, "sp_defense": 0},
        "contest": [0] * 6,
        "pokerus": 0, "met_location": 1, "met_level": 5,
        "met_game": 5, "pokeball": 4, "ot_gender": 1,
        "ivs": {"hp": 10, "attack": 11, "defense": 12,
                "speed": 13, "sp_attack": 14, "sp_defense": 15},
        "is_egg": 0, "ability_num": 0, "ribbons": 0,
        "status": 0, "level": 5, "mail": 0xFF, "hp": 16, "max_hp": 16,
        "attack": 10, "defense": 9, "speed": 12, "sp_attack": 8, "sp_defense": 8,
    }


def test_synthetic_emerald_flash_round_trips_party_and_a_box_mon():
    layout = C.slot_layout(title="emerald")

    sb1 = bytearray(codec.SAVEBLOCK1_SIZE_EMERALD)
    sb1[codec.SB1_PARTY_COUNT_OFFSET_EMERALD] = 1
    start = codec.SB1_PARTY_OFFSET_EMERALD
    sb1[start:start + C.PARTY_MON_SIZE] = codec.encode_party_mon(_party_mon(0x18000, 252))

    boxed = _party_mon(0x18007, 258)
    storage = bytearray(C.STORAGE_SIZE)
    where = C.BOX_DATA_OFFSET + (2 * C.MONS_PER_BOX + 4) * C.BOX_MON_SIZE
    storage[where:where + C.BOX_MON_SIZE] = codec.encode_box_mon(boxed)

    blocks = {"sb2": bytes(codec.SAVEBLOCK2_SIZE_EMERALD), "sb1": bytes(sb1),
              "storage": bytes(storage)}
    image = bytearray(C.FLASH_SIZE)
    _write_half(image, 3, blocks, layout)
    image = bytes(image)

    assert C.qualify_flash(image, title="emerald") == (True, "ok")
    parsed = C.parse_flash(image, title="emerald")
    assert parsed["sb1"] == blocks["sb1"]
    assert parsed["sb2"] == blocks["sb2"]

    party = codec.party_from_save(image, title="emerald")
    assert len(party) == 1
    assert party[0]["species"] == 252
    assert party[0]["personality"] == 0x18000
    assert party[0]["checksum_ok"] is True

    boxes = codec.boxes_from_save(image, title="emerald")
    assert len(boxes) == C.BOXES_PER_STORE
    assert boxes[2][4]["species"] == 258
    assert boxes[2][4]["checksum_ok"] is True
    assert boxes[2][3]["has_species"] == 0


def test_emerald_title_defaults_do_not_change_frlg_call_sites():
    """The title parameter is additive: every existing FR/LG/RR call, with no
    title kwarg, keeps using the FR/LG sizes (this pins the default)."""
    assert C.slot_layout() == C.slot_layout(title="frlg")
    assert C.slot_layout(title="frlg") != C.slot_layout(title="emerald")


def test_sector_rotation_control_matches_frlg_pattern_at_emerald_sizes():
    """Same rotation/counter selection control as
    test_gen3_flash_layout.test_rotation_is_learned_from_section_zero, at
    Emerald's SaveBlock sizes -- the rotation math is size-independent."""
    layout = C.slot_layout(title="emerald")
    sb1 = bytearray(codec.SAVEBLOCK1_SIZE_EMERALD)
    sb1[codec.SB1_PARTY_COUNT_OFFSET_EMERALD] = 0
    blocks = {"sb2": bytes(codec.SAVEBLOCK2_SIZE_EMERALD), "sb1": bytes(sb1),
              "storage": bytes(C.STORAGE_SIZE)}
    image = bytearray(C.FLASH_SIZE)
    rotation = 5
    half = 0
    for entry in layout:
        sid = entry["id"]
        chunk = blocks[entry["object"]][entry["offset"]:entry["offset"] + entry["size"]]
        physical = half + (rotation + sid) % C.NUM_SECTORS_PER_SLOT
        image[physical * C.SECTOR_SIZE:(physical + 1) * C.SECTOR_SIZE] = \
            C.write_sector(chunk, sid, 4, layout)
    parsed = C.parse_flash(bytes(image), title="emerald")
    assert parsed["rotation"] == rotation
    assert parsed["status_name"] == "OK"
    assert parsed["sb1"] == blocks["sb1"]


# --- Damage-calc lane contract: frozen, pinned here per coordinator note ----

def test_decode_party_mon_signature_and_frozen_keys():
    """Coordinator note (damage-calc lane, E1-CODEC): decode_party_mon(raw,
    rr=False), the ivs/evs dict keys, and the party-tail keys must not move.
    This is additive-only: it asserts the CURRENT (unchanged) contract."""
    import inspect
    sig = inspect.signature(codec.decode_party_mon)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["raw", "rr"]
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[1].default is False
    # Call with the keyword form the calc lane depends on.
    mon = _party_mon(0x18000, 252)
    raw = codec.encode_party_mon(mon)
    decoded = codec.decode_party_mon(raw, rr=False)
    assert set(decoded["ivs"]) == {"hp", "attack", "defense", "speed", "sp_attack", "sp_defense"}
    assert set(decoded["evs"]) == {"hp", "attack", "defense", "speed", "sp_attack", "sp_defense"}
    for key in ("max_hp", "attack", "defense", "speed", "sp_attack", "sp_defense"):
        assert key in decoded
