"""XR-1 falsifiers: profile-driven field masks and 12-character nicknames for
pokeemerald-expansion records (docs/gen3_emerald/REQUIREMENTS.md XR-1).

Verified against rh-hideout/pokeemerald-expansion tag ``expansion/1.17.0``
(commit ``e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7``):

- ``include/pokemon.h`` ``struct PokemonSubstruct0`` (Growth): the field
  order/widths below are exactly as declared there.  ``species:11`` and
  ``teraType:5`` share one u16 lane (offset 0); ``heldItem:10`` shares the
  next u16 lane with 6 unused bits (offset 2); ``experience:21`` shares a u32
  lane with the new ``nickname11:8`` (bits 21-28) and 3 unused bits (offset
  4); ``ppBonuses``/``friendship`` are untouched bytes (offsets 8/9);
  ``pokeball:6`` (moved out of Substruct3) shares a u16 lane with the new
  ``nickname12:8`` (bits 6-13) and 2 unused bits (offset 10).  Total: still
  12 bytes (NUM_SUBSTRUCT_BYTES is unchanged).
- ``struct PokemonSubstruct1`` (Attacks): ``move1..4:11`` each share their
  u16 lane (offsets 0/2/4/6) with an evolution-tracker or hyper-trained bit;
  still 12 bytes.
- ``struct BoxPokemon``: ``nickname[min(10, POKEMON_NAME_LENGTH)]`` is
  ``nickname[10]`` (``POKEMON_NAME_LENGTH`` is 12, ``min(10,12)==10``); the
  struct's total size is unchanged (still 80/100 bytes for Box/Party) because
  every new bitfield reuses bits the vanilla struct left unused (flags,
  markings, "unknown"/hpLost, growth_filler/pokeball) rather than growing it.
- ``src/pokemon.c`` ``GetBoxMonData3`` (``MON_DATA_NICKNAME`` case): copies
  the raw 10 bytes verbatim, then -- unless both ``nickname11`` and
  ``nickname12`` are 0 (treated as a vanilla, 10-char record) -- appends them
  as literal characters 11 and 12.
- ``src/pokemon.c`` ``GetBoxMonData3`` ``MON_DATA_SPECIES``/``HELD_ITEM``/
  ``MOVE1``-``MOVE4`` read straight off ``GetSubstruct0(boxMon)->species`` /
  ``->heldItem`` and ``GetSubstruct1(boxMon)->move1..4`` -- the same bitfield
  members above, so the masks below are exactly what the real game already
  applies via the C bitfield reads.
- ``sSubstructOffsets`` (pokemon.c) is byte-for-byte the table this codebase
  already carries as ``SUBSTRUCT_ORDER`` -- the four-substruct shuffle is
  unchanged by the expansion.

Everything here is synthetic (no ROM, no save, no emulator): the test hand-
builds one 100-byte party record with the exact bit layout above, including
deliberate garbage in every "new" bit lane, and checks that a profile-driven
mask/NICKNAME_EXTRA layout decodes the *masked* value while a vanilla
(no-layout) decode of the very same bytes stays exactly as it always has --
proving the feature is additive, not a behaviour change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec

# ── the verified expansion mask/nickname layout (XR-1) ──────────────────────
# Keys match what a pack's profile.derived block would carry (lua/gen3/reads.lua
# reads these same names out of profile.derived; this dict is the Python twin's
# "small layout object", per PLAN.md §2 decision 4).
EXPANSION_LAYOUT = {
    "MON_SPECIES_MASK": 0x7FF,   # species:11
    "MON_ITEM_MASK": 0x3FF,      # heldItem:10
    "MON_MOVE_MASK": 0x7FF,      # move1..4:11
    "NICKNAME_EXTRA": {
        "chars": [
            {"word_off": 4, "word_size": 4, "shift": 21, "width": 8},   # nickname11
            {"word_off": 10, "word_size": 2, "shift": 6, "width": 8},   # nickname12
        ],
    },
}


def _pack(fields: list[tuple[int, int]]) -> int:
    """LSB-first bitfield pack: [(value, width), ...] -> one int."""
    out, shift = 0, 0
    for value, width in fields:
        out |= (value & ((1 << width) - 1)) << shift
        shift += width
    return out


def _expansion_growth(species, tera_type, held_item, experience, nickname11,
                       pp_bonuses, friendship, pokeball, nickname12) -> bytes:
    """PokemonSubstruct0, 12 bytes, expansion bit layout (see module docstring).
    Every "unused" lane gets non-zero garbage to prove the mask is load-bearing."""
    word0 = _pack([(species, 11), (tera_type, 5)])
    word1 = _pack([(held_item, 10), (0x3F, 6)])            # 0x3F: garbage unused bits
    word2 = _pack([(experience, 21), (nickname11, 8), (0x5, 3)])  # 0x5: garbage unused bits
    word3 = _pack([(pokeball, 6), (nickname12, 8), (0x3, 2)])     # 0x3: garbage unused bits
    return (word0.to_bytes(2, "little") + word1.to_bytes(2, "little")
            + word2.to_bytes(4, "little") + bytes([pp_bonuses, friendship])
            + word3.to_bytes(2, "little"))


def _expansion_attacks(moves: list[int], pp: list[int]) -> bytes:
    """PokemonSubstruct1, 12 bytes. Garbage evolution-tracker bits in every
    move lane; PP bytes left clean (their hyper-trained bit is out of XR-1
    scope, see the report's open questions)."""
    trackers = [0x1F, 0x1F, 0x1F, 0x1F]     # garbage: proves the move mask is load-bearing
    words = b"".join(
        _pack([(moves[i], 11), (trackers[i], 5)]).to_bytes(2, "little")
        for i in range(4)
    )
    return words + bytes(pp)


def _vanilla_evs(evs: dict, contest: list[int]) -> bytes:
    return bytes([evs["hp"], evs["attack"], evs["defense"], evs["speed"],
                  evs["sp_attack"], evs["sp_defense"]]) + bytes(contest)


def _vanilla_misc(pokerus, met_location, met_level, met_game, extra4, ot_gender,
                   ivs: dict, is_egg, extra31, ribbons) -> bytes:
    met = _pack([(met_level, 7), (met_game, 4), (extra4, 4), (ot_gender, 1)])
    packed = _pack([
        (ivs["hp"], 5), (ivs["attack"], 5), (ivs["defense"], 5), (ivs["speed"], 5),
        (ivs["sp_attack"], 5), (ivs["sp_defense"], 5), (is_egg, 1), (extra31, 1),
    ])
    return (bytes([pokerus, met_location]) + met.to_bytes(2, "little")
            + packed.to_bytes(4, "little") + ribbons.to_bytes(4, "little"))


def _build_expansion_party_record() -> tuple[bytes, dict]:
    """One synthetic 100-byte party record in the pokeemerald-expansion bit
    layout, personality chosen so SUBSTRUCT_ORDER[0] == (0, 1, 2, 3) (identity
    placement -- growth/attacks/evs/misc land at their type's own position).
    Returns (raw_bytes, expected_masked_values)."""
    personality, ot_id = 0x18000, 0xDEADBEEF
    assert codec.SUBSTRUCT_ORDER[personality % 24] == (0, 1, 2, 3)

    expected = {
        "species": 999, "held_item": 900, "moves": [1500, 1501, 1502, 1503],
        "experience": 1_234_567, "nickname": "ABCDEFGHIJKL",
    }
    growth = _expansion_growth(
        species=expected["species"], tera_type=25, held_item=expected["held_item"],
        experience=expected["experience"], nickname11=codec.encode_name("K", 1)[0],
        pp_bonuses=0b11000000, friendship=128, pokeball=5,
        nickname12=codec.encode_name("L", 1)[0],
    )
    attacks = _expansion_attacks(expected["moves"], pp=[20, 20, 10, 5])
    evs = _vanilla_evs({"hp": 252, "attack": 128, "defense": 6, "speed": 64,
                         "sp_attack": 32, "sp_defense": 8}, contest=[1, 2, 3, 4, 5, 6])
    misc = _vanilla_misc(pokerus=0, met_location=88, met_level=37, met_game=4,
                          extra4=0, ot_gender=1,
                          ivs={"hp": 31, "attack": 30, "defense": 29, "speed": 28,
                               "sp_attack": 27, "sp_defense": 26},
                          is_egg=0, extra31=0, ribbons=0)

    plain_secure = growth + attacks + evs + misc
    assert len(plain_secure) == codec.SECURE_SIZE
    secure = codec._xor_words(plain_secure, personality ^ ot_id)
    checksum = codec.secure_checksum(plain_secure)

    nickname_raw10 = codec.encode_name("ABCDEFGHIJ", 10)
    ot_name = codec.encode_name("ASH", 7)
    raw = bytearray(codec.PARTY_MON_SIZE)
    raw[0x00:0x04] = personality.to_bytes(4, "little")
    raw[0x04:0x08] = ot_id.to_bytes(4, "little")
    raw[0x08:0x12] = nickname_raw10
    raw[0x12] = 2                    # language: English
    raw[0x13] = 1 << 1               # has_species
    raw[0x14:0x1B] = ot_name
    raw[0x1B] = 0x0A                 # markings
    raw[0x1C:0x1E] = checksum.to_bytes(2, "little")
    raw[0x1E:0x20] = (0).to_bytes(2, "little")
    raw[0x20:0x50] = secure
    # party tail
    raw[0x50:0x54] = (0).to_bytes(4, "little")   # status
    raw[0x54] = 50                                # level
    raw[0x55] = 0xFF                              # mail
    for off, value in ((0x56, 100), (0x58, 100), (0x5A, 50), (0x5C, 50),
                       (0x5E, 50), (0x60, 50), (0x62, 50)):
        raw[off:off + 2] = value.to_bytes(2, "little")
    assert len(raw) == codec.PARTY_MON_SIZE
    return bytes(raw), expected


# --- RED: masked decode is required for an expansion record ----------------

def test_masked_decode_recovers_expansion_fields():
    raw, expected = _build_expansion_party_record()
    decoded = codec.decode_party_mon_masked(raw, rr=False, layout=EXPANSION_LAYOUT)
    assert decoded["species"] == expected["species"]
    assert decoded["held_item"] == expected["held_item"]
    assert decoded["moves"] == expected["moves"]
    assert decoded["experience"] == expected["experience"]
    assert decoded["nickname"] == expected["nickname"]
    assert len(decoded["nickname_raw"]) == 12


def test_naive_vanilla_decode_of_the_same_bytes_is_polluted_by_the_new_bits():
    """Documents *why* XR-1 exists: decoding an expansion record with the
    vanilla (unmasked) path yields inflated species/item/move/experience and
    a 10-char nickname -- this is expected, unchanged vanilla behaviour, not
    a bug in decode_party_mon."""
    raw, expected = _build_expansion_party_record()
    naive = codec.decode_party_mon(raw)   # no layout: today's vanilla decode
    assert naive["species"] != expected["species"]
    assert naive["species"] > 0x7FF
    assert naive["held_item"] != expected["held_item"]
    assert naive["moves"] != expected["moves"]
    assert naive["experience"] != expected["experience"]
    assert len(naive["nickname_raw"]) == 10
    assert naive["nickname"] != expected["nickname"]


# --- vanilla inertness: layout=None / absent reproduces decode_party_mon ----

def test_masked_decoder_with_no_layout_matches_the_frozen_decoder_exactly():
    raw, _ = _build_expansion_party_record()
    assert codec.decode_party_mon_masked(raw, rr=False) == codec.decode_party_mon(raw, rr=False)
    assert codec.decode_party_mon_masked(raw, rr=False, layout={}) == codec.decode_party_mon(raw, rr=False)


def test_frozen_signature_untouched():
    """The calc lane's falsifier (test_gen3_codec_emerald.py) already pins
    this; repeated here because it is the load-bearing constraint for this
    card's whole design (a NEW function, never a new parameter on the old
    one)."""
    import inspect
    assert [p.name for p in inspect.signature(codec.decode_party_mon).parameters.values()] == ["raw", "rr"]
    assert [p.name for p in inspect.signature(codec.decode_box_mon).parameters.values()] == ["raw", "rr"]


# --- vanilla inertness across every committed fixture -----------------------

def test_every_committed_gen3_fixture_decodes_identically_with_and_without_the_masked_path():
    """XR-1 must not perturb a single existing vanilla/RR/Emerald fixture.
    Decode every party/box slot two ways -- the frozen decoder, and the new
    masked one with layout=None -- and require byte-for-byte-equal JSON.
    This is the card's "vanilla inertness" proof (step 3 of the brief)."""
    root = Path(__file__).resolve().parents[2]
    fixtures = sorted((root / "tests/fixtures/gen3").glob("*.sav"))
    assert fixtures, "no gen3 fixtures found"
    checked = 0
    for path in fixtures:
        image = path.read_bytes()
        rr = path.name.startswith("rr_")
        title = codec.TITLE_EMERALD if path.name.startswith("emerald_") else codec.TITLE_FRLG
        parsed = codec.parse_flash(image, cfru=rr, title=title)
        for block_name in ("sb1", "storage"):
            block = parsed.get(block_name)
            if not block:
                continue
            size = codec.PARTY_MON_SIZE if block_name == "sb1" else codec.BOX_MON_SIZE
            party = block_name == "sb1"
            for start in range(0, len(block) - size + 1, size):
                raw = bytes(block[start:start + size])
                if party:
                    old = codec.decode_party_mon(raw, rr=rr)
                    new = codec.decode_party_mon_masked(raw, rr=rr)
                else:
                    old = codec.decode_box_mon(raw, rr=rr)
                    new = codec.decode_box_mon_masked(raw, rr=rr)
                assert json.dumps(old, sort_keys=True, default=str) == \
                       json.dumps(new, sort_keys=True, default=str)
                checked += 1
    assert checked > 0, "no records decoded across the fixture set"


# --- Lua twin (reads.lua) ----------------------------------------------------

def test_lua_reads_decodes_the_same_expansion_record():
    lupa = pytest.importorskip("lupa")
    root = Path(__file__).resolve().parents[2]
    raw, expected = _build_expansion_party_record()

    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = runtime.execute((root / "lua/gen3/reads.lua").read_text(encoding="utf-8"))
    profile = {"ram": {}, "derived": dict(EXPANSION_LAYOUT)}
    reads = module.new(runtime.table_from(profile, recursive=True), runtime.table(
        read_u8=lambda *_: 0, read_u32=lambda *_: 0,
        read_bytes=lambda *_: runtime.table()))
    lua_mon = reads.decode_party_mon(runtime.table(*raw))

    assert lua_mon.species == expected["species"]
    assert lua_mon.held_item == expected["held_item"]
    assert list(lua_mon.moves.values()) == expected["moves"]
    assert lua_mon.experience == expected["experience"]
    assert lua_mon.nickname == expected["nickname"]


def test_lua_reads_is_inert_without_the_expansion_derived_keys():
    """The vanilla FR/LG/RR profiles carry none of derived.MON_*_MASK /
    NICKNAME_EXTRA, so lua/gen3/reads.lua must decode exactly as it did
    before this card on every such profile."""
    lupa = pytest.importorskip("lupa")
    root = Path(__file__).resolve().parents[2]
    profile = json.loads((root / "data/games/gen3_frlg/profile.json").read_text())["titles"]["firered"]
    assert "MON_SPECIES_MASK" not in profile["derived"]
    assert "NICKNAME_EXTRA" not in profile["derived"]

    image = (root / "tests/fixtures/gen3/firered_town.sav").read_bytes()
    sb1 = codec.parse_flash(image)["sb1"]
    py_expected = codec.party_from_save(image)

    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = runtime.execute((root / "lua/gen3/reads.lua").read_text(encoding="utf-8"))
    reads = module.new(runtime.table_from(profile, recursive=True), runtime.table(
        read_u8=lambda *_: 0, read_u32=lambda *_: 0,
        read_bytes=lambda *_: runtime.table()))
    for slot, py in enumerate(py_expected):
        start = codec.SB1_PARTY_OFFSET + slot * codec.PARTY_MON_SIZE
        lua = reads.decode_party_mon(runtime.table(*sb1[start:start + codec.PARTY_MON_SIZE]))
        for field in ("species", "held_item", "experience", "nickname"):
            assert lua[field] == py[field], field
        assert list(lua.moves.values()) == py["moves"]
