"""R-1 / R-2, occupied box slots: the Lua reader and the Python codec on the SAME bytes.

`docs/gen3_requirements.md` R-1 and R-2 both carry a ◐ in the P column — "only empty
slots have been compared live (box 0 dumped all zero)" / "Compressed box: box 0 dumped
all zero, so no occupied slot has been compared live". This file closes the part of that
gap a committed fixture can close, and says plainly which part it cannot: no emulator
runs here, so the *live* receipt is still open.

What is closed is the model side of the same claim. A real party mon is taken out of a
committed battery save, planted in box 0 slot 0, and decoded twice — once through
`lua/gen3/reads.lua` inside the production `Entry.build` graph, once through
`server/adapters/gen3_codec.py` — and the two must agree field for field *and* with the
party record the bytes came from. `tests/unit/test_gen3_reads.py` compared empty slots
against the same oracle; `::test_vanilla_read_box_follows_the_relocated_storage_pointer`
plants occupied vanilla slots, but from an RR party mon the oracle re-encoded, so no
committed vanilla party record had ever been read back out of a box slot.

The two titles are different formats and no layout fact crosses between them:

* vanilla FRLG — 80-byte `BoxPokemon`; the 48-byte secure block is XOR'd with
  `personality ^ otId`, the four 12-byte substructs sit in the order
  `SUBSTRUCT_ORDER[personality % 24]` (pret `src/pokemon.c` GetSubstruct), and the u16
  `CalculateBoxMonChecksum` value lives at +0x1C. Codec: `_encode_mon` /
  `_decode_mon`, `server/adapters/gen3_codec.py:237-313`.
* Radical Red — 58-byte CFRU `CompressedPokemon` expanded to the 80-byte form by
  `expand_compressed_box_mon` (`gen3_codec.py:332-357`, field map transcribed from
  `archive/gen3-old-client:lua/memory_gba.lua:1037-1104`); fixed substruct order, no
  encryption, and **no checksum at all** — CFRU leaves +0x1C zero and never validates it
  (`docs/gen3/research/rr_save_layout.md` §6).

A box record cannot carry the party-only tail (`include/pokemon.h:128-141`), so the
comparison runs over the fields both record types share and asserts the tail is absent.
"""
from __future__ import annotations

from functools import cache

import pytest

from server.adapters import gen3_codec as codec
from tests.unit.gen3_world import compress_box_mon, key_of
from tests.unit.test_gen3_entry import FIXTURES, World, lua_to_py
from tests.unit.test_gen3_reads import RAW_PAIRS, assert_same_mon, place_box

FR_PARTY_SAV = FIXTURES / "firered_party_town.sav"
RR_SAV = FIXTURES / "rr_town.sav"

# include/pokemon.h:128-141 — the fields that only exist after the 80-byte BoxPokemon.
PARTY_TAIL = ("status", "level", "mail", "hp", "max_hp", "attack", "defense", "speed",
              "sp_attack", "sp_defense")

# The six record fields R-1/R-2 name; the mon key is asserted separately, below.
NAMED_FIELDS = ("species", "personality", "ot_id", "nickname", "experience", "moves")

# What `expand_compressed_box_mon` cannot put back (gen3_codec.py:336-357, one offset per
# claim). Vanilla loses none of these: the whole 48-byte secure block is stored.
RR_LOSSY = ("pp", "contest", "unknown", "ribbons", "growth_filler")


@cache
def fr_image() -> bytes:
    return FR_PARTY_SAV.read_bytes()

@cache
def rr_image() -> bytes:
    return RR_SAV.read_bytes()


def fr_party_raw(slot: int = 0) -> bytes:
    sb1 = codec.parse_flash(fr_image())["sb1"]
    start = codec.SB1_PARTY_OFFSET + slot * codec.PARTY_MON_SIZE
    return sb1[start:start + codec.PARTY_MON_SIZE]


def fr_source(slot: int = 0) -> dict:
    """The party mon under test, decoded by the oracle off the committed battery save."""
    return codec.decode_party_mon(fr_party_raw(slot))


def rr_source() -> dict:
    """Same for Radical Red: the fixture's one Treecko (test_gen3_rr_save_layout.py:75)."""
    return codec.rr_party_from_save(rr_image())[0]


def _same_value(mon: dict, name: str):
    """One field, normalised. `name` is always the Python spelling (it is taken from the
    party decode); the Lua table spells the same two byte-strings `RAW_PAIRS[name]`
    (reads.lua:254,259)."""
    if name in RAW_PAIRS:
        return bytes(mon[name] if name in mon else mon[RAW_PAIRS[name]])
    return mon[name]


def assert_matches_party(box_mon: dict, party_mon: dict, lossy=()) -> list[str]:
    """Every field the two record types share must be equal; the party tail must be absent."""
    # the two raw name fields are spelled differently on the Lua side (RAW_PAIRS); they are
    # compared below through _same_value, not counted as party-only
    only_party = set(party_mon) - set(box_mon) - {k for k, lua in RAW_PAIRS.items() if lua in box_mon}
    assert set(PARTY_TAIL) <= only_party, \
        f"a box record must not carry the party tail: {only_party}"
    # `checksum_ok` is the one non-tail field a box record may lack, and only on RR, where
    # CFRU has no checksum to verify at all (reads.lua:266-268).
    assert only_party - set(PARTY_TAIL) == ({"checksum_ok"}
                                             if party_mon["checksum_ok"] is None else set())
    shared = sorted(k for k in party_mon if (k in box_mon or RAW_PAIRS.get(k) in box_mon) and k not in set(lossy))
    assert "species" in shared and "personality" in shared
    for name in shared:
        assert _same_value(box_mon, name) == _same_value(party_mon, name), name
    return shared


def _pad(records: list[bytes], stride: int) -> list[bytes]:
    assert len(records) <= codec.MONS_PER_BOX
    return records + [bytes(stride)] * (codec.MONS_PER_BOX - len(records))


def plant_vanilla(world, records: list[bytes], box_index: int = 0, offset: int = 0) -> list:
    """Box `box_index` at a relocated storage base, with `records` in slots 0..n."""
    place_box(world, offset, box_index=box_index, records=_pad(records, codec.BOX_MON_SIZE))
    return lua_to_py(world.parts.reads.read_box(box_index))


def plant_rr(world, records: list[bytes], box_index: int = 0) -> list:
    """Box `box_index` at the pack's own CFRU base, with `records` in slots 0..n."""
    derived = world.profile["derived"]
    assert derived["CFRU_BOX_BASES"] == list(codec.RR_BOX_BASES), \
        "the planted address must be Radical Red's, not the vanilla storage base"
    world.poke(derived["CFRU_BOX_BASES"][box_index], b"".join(_pad(records, codec.COMPRESSED_MON_SIZE)))
    return lua_to_py(world.parts.reads.read_box(box_index))


def flip(record: bytes, offset: int) -> bytes:
    out = bytearray(record)
    out[offset] ^= 0xFF
    return bytes(out)


# ── vanilla FRLG: 80-byte BoxPokemon, encrypted, permuted, checksummed ──────────────────

@pytest.mark.parametrize("offset", (0, 64))
def test_a_vanilla_fixture_party_mon_agrees_field_for_field_in_an_occupied_box_slot(offset):
    """The R-1 claim, on real bytes: read the same planted slot through both decoders.

    `offset` is the SetSaveBlocksPointers relocation (pret `src/load_save.c:75`,
    `Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)`), so 0 and 64 are both reachable and
    neither may be the static base by accident.
    """
    world = World(pack="gen3_frlg", title="firered")
    assert sorted(m["species"] for m in codec.party_from_save(fr_image())) == [7, 16], \
        "firered_party_town.sav: starter Squirtle (7) + Route 1 Pidgey (16), fixtures README"

    source = fr_source()
    assert source["checksum_ok"] is True, "the fixture's own party record must be checksum-clean"

    record = codec.encode_box_mon(source, rr=False)
    assert len(record) == codec.BOX_MON_SIZE
    assert codec.decode_box_mon(record)["checksum_ok"] is True

    box = plant_vanilla(world, [record], offset=offset)
    assert len(box) == codec.MONS_PER_BOX
    got = box[0]
    assert got["slot"] == 0 and got["box_index"] == 0 and got["box"] is True
    # The record really is in slot 0 and nowhere else — the empty neighbours prove the
    # stride, not just the first slot's contents.
    assert [m["species"] for m in box[1:]] == [0] * (codec.MONS_PER_BOX - 1)

    # 1. the two decoders, same bytes
    assert_same_mon(got, codec.decode_box_mon(record))
    # 2. both, against the party record the bytes came from
    shared = assert_matches_party(got, source)
    for name in NAMED_FIELDS:
        assert got[name] == source[name], name
    assert "checksum_ok" in shared and got["checksum_ok"] is True
    # 3. the mon key, spelled by Lua and by Python
    lua_key = str(world.parts.reads.key(
        world.parts.reads.decode_box_mon(world.lua.table(*record))))
    assert lua_key == key_of(source["personality"], source["ot_id"])


def test_the_vanilla_box_encoder_is_exactly_the_party_records_first_80_bytes():
    """pret `CreateBoxMonFromMon` copies the BoxPokemon half verbatim; this is the codec
    half of that claim, on the fixture: encode(decode(raw)) == raw[:80], byte for byte.

    It holds because the decoder exposes all 80 bytes — every substruct byte, the
    checksum and `unknown` — and because the fixture's own stored checksum already equals
    the sum over its own plaintext (asserted above, and the only other precondition:
    `_encode_mon` recomputes the checksum, `gen3_codec.py:306`)."""
    source = fr_source()
    assert source["checksum_ok"] is True
    assert codec.encode_box_mon(source, rr=False) == fr_party_raw()[:codec.BOX_MON_SIZE]


def test_every_substruct_permutation_agrees_in_occupied_vanilla_box_slots():
    """`personality % 24` picks where each substruct sits; both decoders carry their own
    copy of the 24-row table (`gen3_codec.py:61-68` vs `lua/gen3/reads.lua:48-53`). A
    single wrong row would only show up for the residue that uses it, so all 24 are
    planted — one per slot of a single box, read in one `read_box` call."""
    world = World(pack="gen3_frlg", title="firered")
    base = fr_source()
    records = []
    for residue in range(24):
        mon = dict(base, personality=residue)
        raw = codec.encode_box_mon(mon, rr=False)
        assert codec.decode_box_mon(raw)["personality"] == residue
        records.append(raw)

    box = plant_vanilla(world, records)
    for residue, got in enumerate(box[:24]):
        raw = records[residue]
        assert got["species"] == base["species"], residue
        assert got["personality"] == residue
        assert got["checksum_ok"] is True, residue
        assert_same_mon(got, codec.decode_box_mon(raw))
    assert [m["species"] for m in box[24:]] == [0] * 6


def test_a_vanilla_secure_byte_flip_is_caught_by_the_checksum_in_both_decoders():
    """Negative control, inside the encrypted block: flip one plaintext byte of the
    Growth substruct (species) and both decoders must report the record as corrupt.

    They do NOT disagree with each other — they are byte-identical transforms of the same
    input, so a single-byte flip moves them together. `checksum_ok` is the only witness,
    in both implementations, and neither refuses to return a mon."""
    world = World(pack="gen3_frlg", title="firered")
    source = fr_source()
    record = codec.encode_box_mon(source, rr=False)
    growth = codec.SUBSTRUCT_ORDER[source["personality"] % 24][0]
    bad = flip(record, codec.SECURE_OFFSET + growth * codec.SUBSTRUCT_SIZE)

    good_box = plant_vanilla(world, [record])[0]
    bad_box = plant_vanilla(world, [bad])[0]
    assert bad_box["checksum_ok"] is False and codec.decode_box_mon(bad)["checksum_ok"] is False
    assert good_box["checksum_ok"] is True
    assert bad_box["species"] != good_box["species"], "the flip must reach a decoded field"
    assert bad_box["personality"] == good_box["personality"], "identity is in the clear header"
    assert_same_mon(bad_box, codec.decode_box_mon(bad))


def test_a_vanilla_checksum_field_flip_changes_only_the_verdict_in_both_decoders():
    """Negative control, outside the encrypted block: +0x1C is the stored u16
    (CalculateBoxMonChecksum, pret `src/pokemon.c`). Corrupting it leaves the plaintext —
    and therefore every decoded field — untouched, so `checksum_ok` is the whole difference.
    That is the narrowest statement of what the checksum is for."""
    world = World(pack="gen3_frlg", title="firered")
    record = codec.encode_box_mon(fr_source(), rr=False)
    bad = flip(record, 0x1C)

    good_box = plant_vanilla(world, [record])[0]
    bad_box = plant_vanilla(world, [bad])[0]
    assert bad_box["checksum_ok"] is False and codec.decode_box_mon(bad)["checksum_ok"] is False
    assert bad_box["checksum"] != good_box["checksum"]
    assert {k: v for k, v in bad_box.items() if k not in ("checksum", "checksum_ok")} \
        == {k: v for k, v in good_box.items() if k not in ("checksum", "checksum_ok")}


# ── Radical Red: 58-byte CFRU CompressedPokemon, expanded, never checksummed ────────────

def test_an_rr_fixture_party_mon_agrees_field_for_field_in_a_compressed_box_slot():
    """The R-2 claim on real bytes, through the 0x3A format this title actually stores."""
    world = World(pack="gen3_rr", title="radical_red")
    source = rr_source()
    assert source["species"] == 277, "the fixture's one party mon (rr_save_layout.md §6)"

    record = compress_box_mon(codec.encode_box_mon(source, rr=True))
    assert len(record) == codec.COMPRESSED_MON_SIZE
    expanded = codec.expand_compressed_box_mon(record)

    box = plant_rr(world, [record])
    assert len(box) == codec.MONS_PER_BOX
    got = box[0]
    assert got["slot"] == 0 and got["box_index"] == 0 and got["box"] is True
    assert [m["species"] for m in box[1:]] == [0] * (codec.MONS_PER_BOX - 1)

    # 1. the two decoders, same expanded bytes
    assert_same_mon(got, codec.decode_box_mon(expanded, rr=True))
    # 2. both, against the party record the bytes came from, over what 0x3A can carry
    assert_matches_party(got, source, lossy=RR_LOSSY)
    for name in NAMED_FIELDS:
        assert got[name] == source[name], name
    # 3. the mon key, spelled by Lua and by Python
    lua_key = str(world.parts.reads.key(
        world.parts.reads.decode_box_mon(world.lua.table(*expanded))))
    assert lua_key == key_of(source["personality"], source["ot_id"])


def test_the_rr_compressed_box_record_drops_exactly_the_fields_cfru_does_not_store():
    """The lossy set above is not a convenience: pin each loss, offset by offset.

    PP (+0x34..0x37), the contest block (+0x3E..0x43), the growth pad (+0x2B), the
    stored checksum/`unknown` (+0x1C..0x1F) and the low three ribbon bytes
    (+0x4C..0x4E) are not in the 58-byte record, and expansion leaves them zero — except
    +0x4F, where RR's own builder sets bit 31 (`gen3_codec.py:356`, ROM
    0x090B696A..76). The identity fields and all four moves do survive the 10-bit move
    packing, which is why they are the ones R-2 names."""
    world = World(pack="gen3_rr", title="radical_red")
    source = rr_source()
    got = plant_rr(world, [compress_box_mon(codec.encode_box_mon(source, rr=True))])[0]

    assert got["pp"] == [0, 0, 0, 0] and got["contest"] == [0] * 6
    assert got["unknown"] == 0 and got["checksum"] == 0
    assert got["ribbons"] == 0x80000000
    # growth_filler is the little-endian u16 at +0x2A..0x2B; the codec copies +0x20..0x2A
    # (gen3_codec.expand_compressed_box_mon), so +0x2A (the low byte) survives and +0x2B is zero
    assert got["growth_filler"] >> 8 == 0, "+0x2B is not stored"
    assert got["growth_filler"] & 0x00FF == source["growth_filler"] & 0x00FF, \
        "+0x2A, the low half of growth_filler, does survive"
    assert "checksum_ok" not in got, "CFRU has no BoxPokemon checksum to report on"
    assert max(source["moves"]) <= 0x3FF, "four moves packed 10 bits each fit by construction"
    assert got["moves"] == source["moves"]


def test_an_rr_compressed_byte_flip_is_silently_decoded_by_both_decoders():
    """Negative control for the title that has no checksum. Flip the species byte of the
    compressed record (+0x1C is the Growth substruct there) and the slot still decodes:
    both implementations return a mon, they agree with each other exactly, there is no
    `checksum_ok` to go false, and the mon key is unchanged because identity lives in the
    clear header the flip did not touch. Nothing in `read_box` can tell the difference —
    the only witness for a corrupted RR box record is the flash sector checksum upstream
    (`qualify_flash`), and `read_box` reads RAM, not flash."""
    world = World(pack="gen3_rr", title="radical_red")
    source = rr_source()
    record = compress_box_mon(codec.encode_box_mon(source, rr=True))
    bad = flip(record, 0x1C)

    good_box = plant_rr(world, [record])[0]
    bad_slots = plant_rr(world, [bad])
    assert len(bad_slots) == codec.MONS_PER_BOX, "read_box must not refuse the box"
    bad_box = bad_slots[0]
    assert "checksum_ok" not in bad_box
    assert bad_box["species"] != good_box["species"], "the flip must reach a decoded field"
    assert bad_box["personality"] == source["personality"] and bad_box["ot_id"] == source["ot_id"]
    assert str(world.parts.reads.key(
        world.parts.reads.decode_box_mon(world.lua.table(*codec.expand_compressed_box_mon(bad))))) \
        == key_of(source["personality"], source["ot_id"])
    assert_same_mon(bad_box, codec.decode_box_mon(codec.expand_compressed_box_mon(bad), rr=True))
