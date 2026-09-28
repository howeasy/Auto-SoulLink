"""XR-1/XR-2 falsifiers: profile-driven field masks and 12-character nicknames
for pokeemerald-expansion records (docs/gen3_emerald/REQUIREMENTS.md XR-1; XR-2
is review cx-fcdc11c5's accepted findings F1-F9 against XR-1's b40153c4).

Verified against rh-hideout/pokeemerald-expansion tag ``expansion/1.17.0``
(commit ``e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7``); see
tests/fixtures/gen3/expansion_layout_e8bd1cd7.json's ``_cites`` block for the
exact ``include/pokemon.h`` line ranges backing every key below, and
docs/gen3_emerald/research/expansion_record_layout.md for the full field
inventory (decoded / refused / NOT handled).

Everything here is synthetic (no ROM, no save, no emulator): the test hand-
builds one 100-byte party record with the exact bit layout above, including
deliberate garbage in every "new" bit lane, and checks that a profile-driven
layout decodes the *masked/relocated* value while a vanilla (no-layout)
decode of the very same bytes stays exactly as it always has -- proving the
feature is additive, not a behaviour change.
"""

from __future__ import annotations

import json
import subprocess
import types
from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec

_ROOT = Path(__file__).resolve().parents[2]
_LUA_READS = _ROOT / "lua/gen3/reads.lua"

# ── the verified expansion layout (XR-1/XR-2), single source of truth (F3) ──
# Keys match what a pack's profile.derived block would carry (lua/gen3/reads.lua
# reads these same names out of profile.derived). The real pack will be
# generated from X1-PROBE's compiler facts (data/games/gen3_exp/<build>/
# facts.json, claude/gen3-emerald-x1); this JSON fixture is the test twin.
EXPANSION_LAYOUT = json.loads(
    (_ROOT / "tests/fixtures/gen3/expansion_layout_e8bd1cd7.json").read_text()
)["layout"]


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
    move lane; each PP byte gets a garbage hyperTrained* bit at bit 7
    (pp1..4:7 + hyperTrained*:1, include/pokemon.h#L160-167)."""
    trackers = [0x1F, 0x1F, 0x1F, 0x1F]     # garbage: proves the move mask is load-bearing
    words = b"".join(
        _pack([(moves[i], 11), (trackers[i], 5)]).to_bytes(2, "little")
        for i in range(4)
    )
    pp_bytes = bytes((value & 0x7F) | 0x80 for value in pp)  # garbage hyperTrained bit
    return words + pp_bytes


def _vanilla_evs(evs: dict, contest: list[int]) -> bytes:
    return bytes([evs["hp"], evs["attack"], evs["defense"], evs["speed"],
                  evs["sp_attack"], evs["sp_defense"]]) + bytes(contest)


def _expansion_misc(pokerus, met_location, met_level, met_game, dynamax_garbage, ot_gender,
                     ivs: dict, is_egg, gigantamax_garbage, ability_num) -> bytes:
    """PokemonSubstruct3, 12 bytes. ``dynamax_garbage`` sits where vanilla's
    pokeball nibble used to be (pokeball moved to Growth; that slot is now
    dynamaxLevel, #L192) and ``gigantamax_garbage`` sits where vanilla's
    ability_num bit used to be (bit31 of the IVs word is now gigantamaxFactor,
    #L201) -- both prove POKEBALL_FIELD/ABILITY_NUM_FIELD are load-bearing by
    being garbage that must NOT leak into the masked "pokeball"/"ability_num"
    output. ``ability_num`` (2 bits) is packed into the ribbons u32 at bits
    29-30 (#L221), the field's real expansion location."""
    met = _pack([(met_level, 7), (met_game, 4), (dynamax_garbage, 4), (ot_gender, 1)])
    packed = _pack([
        (ivs["hp"], 5), (ivs["attack"], 5), (ivs["defense"], 5), (ivs["speed"], 5),
        (ivs["sp_attack"], 5), (ivs["sp_defense"], 5), (is_egg, 1), (gigantamax_garbage, 1),
    ])
    ribbons_word = _pack([(0, 29), (ability_num, 2), (0, 1)])  # ribbons flags unused here
    return (bytes([pokerus, met_location]) + met.to_bytes(2, "little")
            + packed.to_bytes(4, "little") + ribbons_word.to_bytes(4, "little"))


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
        "pokeball": 5, "ability_num": 2, "pp": [20, 20, 10, 5],
        "markings": 0x0A, "shiny_modifier": 1,
    }
    growth = _expansion_growth(
        species=expected["species"], tera_type=25, held_item=expected["held_item"],
        experience=expected["experience"], nickname11=codec.encode_name("K", 1)[0],
        pp_bonuses=0b11000000, friendship=128, pokeball=expected["pokeball"],
        nickname12=codec.encode_name("L", 1)[0],
    )
    attacks = _expansion_attacks(expected["moves"], pp=expected["pp"])
    evs = _vanilla_evs({"hp": 252, "attack": 128, "defense": 6, "speed": 64,
                         "sp_attack": 32, "sp_defense": 8}, contest=[1, 2, 3, 4, 5, 6])
    misc = _expansion_misc(pokerus=0, met_location=88, met_level=37, met_game=4,
                            dynamax_garbage=9, ot_gender=1,
                            ivs={"hp": 31, "attack": 30, "defense": 29, "speed": 28,
                                 "sp_attack": 27, "sp_defense": 26},
                            is_egg=0, gigantamax_garbage=1, ability_num=expected["ability_num"])

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
    raw[0x1B] = expected["markings"] | 0x30   # garbage compressedStatus nibble (#L272-273)
    raw[0x1C:0x1E] = checksum.to_bytes(2, "little")
    unknown = (100 & 0x3FFF) | (expected["shiny_modifier"] << 14)  # hpLost:14 + shinyModifier:1
    raw[0x1E:0x20] = unknown.to_bytes(2, "little")
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


def _lua_reads(derived: dict):
    """A fresh lua/gen3/reads.lua module instance over ``derived``. Raises
    lupa.LuaError if R.new refuses the layout."""
    lupa = pytest.importorskip("lupa")
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = runtime.execute(_LUA_READS.read_text(encoding="utf-8"))
    profile = {"ram": {}, "derived": dict(derived)}
    return runtime, module.new(runtime.table_from(profile, recursive=True), runtime.table(
        read_u8=lambda *_: 0, read_u32=lambda *_: 0,
        read_bytes=lambda *_: runtime.table()))


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
    # XR-2 F5: relocated/masked fields.
    assert decoded["pokeball"] == expected["pokeball"]
    assert decoded["ability_num"] == expected["ability_num"]
    assert decoded["pp"] == expected["pp"]
    assert decoded["markings"] == expected["markings"]
    assert decoded["shiny_modifier"] == expected["shiny_modifier"]


def test_naive_vanilla_decode_of_the_same_bytes_is_polluted_by_the_new_bits():
    """Documents *why* XR-1/XR-2 exist: decoding an expansion record with the
    vanilla (unmasked) path yields inflated/relocated fields -- this is
    expected, unchanged vanilla behaviour, not a bug in decode_party_mon."""
    raw, expected = _build_expansion_party_record()
    naive = codec.decode_party_mon(raw)   # no layout: today's vanilla decode
    assert naive["species"] != expected["species"]
    assert naive["species"] > 0x7FF
    assert naive["held_item"] != expected["held_item"]
    assert naive["moves"] != expected["moves"]
    assert naive["experience"] != expected["experience"]
    assert len(naive["nickname_raw"]) == 10
    assert naive["nickname"] != expected["nickname"]
    assert naive["pokeball"] != expected["pokeball"]         # reads dynamaxLevel garbage
    assert naive["ability_num"] != expected["ability_num"]   # reads gigantamaxFactor garbage
    assert naive["pp"] != expected["pp"]                     # hyperTrained bits leak in
    assert naive["markings"] != expected["markings"]         # compressedStatus nibble leaks in
    assert "shiny_modifier" not in naive


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


# --- F2: EXPERIENCE_MASK is a first-class key, not inferred from NICKNAME_EXTRA

def test_experience_mask_applies_even_without_nickname_extra():
    raw, expected = _build_expansion_party_record()
    layout = {k: v for k, v in EXPANSION_LAYOUT.items() if k != "NICKNAME_EXTRA"}
    decoded = codec.decode_party_mon_masked(raw, layout=layout)
    assert decoded["experience"] == expected["experience"]


def test_experience_is_polluted_when_only_nickname_extra_is_present_without_the_mask():
    """RED-by-design: before F2, EXPERIENCE_MASK was inferred from a
    NICKNAME_EXTRA char at word_off 4; now that it is a first-class key,
    NICKNAME_EXTRA alone (without EXPERIENCE_MASK) must NOT mask experience --
    the nickname11 bits leak into it, same as any other un-masked field."""
    raw, expected = _build_expansion_party_record()
    layout = {k: v for k, v in EXPANSION_LAYOUT.items() if k != "EXPERIENCE_MASK"}
    decoded = codec.decode_party_mon_masked(raw, layout=layout)
    assert decoded["experience"] != expected["experience"]
    assert decoded["nickname"] == expected["nickname"]  # NICKNAME_EXTRA itself still works


# --- F1: the encoder is not layout-aware and must refuse, not corrupt ------

def test_encode_refuses_a_12_byte_nickname_instead_of_corrupting_the_record():
    raw, _ = _build_expansion_party_record()
    decoded = codec.decode_party_mon_masked(raw, layout=EXPANSION_LAYOUT)
    assert len(decoded["nickname_raw"]) == 12
    with pytest.raises(ValueError, match="expansion nickname"):
        codec.encode_party_mon(decoded)
    with pytest.raises(ValueError, match="expansion nickname"):
        codec.encode_box_mon(decoded)


def test_encode_still_round_trips_a_vanilla_10_byte_nickname():
    raw, _ = _build_expansion_party_record()
    vanilla = codec.decode_party_mon(raw)  # no layout: 10-byte nickname_raw
    assert len(vanilla["nickname_raw"]) == 10
    assert codec.encode_party_mon(vanilla) == raw  # unchanged round-trip contract


# --- F9: a zero mask is a config bug, refuse it, do not silently default ---

@pytest.mark.parametrize("key", ["MON_SPECIES_MASK", "MON_ITEM_MASK", "MON_MOVE_MASK",
                                  "EXPERIENCE_MASK", "PP_MASK", "MARKINGS_MASK"])
def test_zero_mask_is_refused_by_python(key):
    with pytest.raises(ValueError, match=key):
        codec.decode_party_mon_masked(b"\x00" * codec.PARTY_MON_SIZE, layout={key: 0})


def test_zero_mask_is_refused_by_lua():
    with pytest.raises(Exception, match="MON_SPECIES_MASK"):
        _lua_reads({"MON_SPECIES_MASK": 0})


# --- F6: a malformed NICKNAME_EXTRA is refused by both twins, not KeyError/tolerated

def test_malformed_nickname_extra_is_refused_by_python_not_a_keyerror():
    with pytest.raises(ValueError, match="NICKNAME_EXTRA"):
        codec.decode_party_mon_masked(b"\x00" * codec.PARTY_MON_SIZE, layout={"NICKNAME_EXTRA": {}})
    with pytest.raises(ValueError, match="NICKNAME_EXTRA"):
        codec.decode_party_mon_masked(b"\x00" * codec.PARTY_MON_SIZE,
                                       layout={"NICKNAME_EXTRA": {"chars": "not-a-list"}})


def test_malformed_nickname_extra_is_refused_by_lua_not_silently_tolerated():
    with pytest.raises(Exception, match="NICKNAME_EXTRA"):
        _lua_reads({"NICKNAME_EXTRA": {}})


# --- F7: a bad word_off/word_size/shift/width is refused before any byte read

@pytest.mark.parametrize("field_key,bad_field", [
    ("POKEBALL_FIELD", {"word_off": 20, "word_size": 2, "shift": 0, "width": 6}),   # off-end
    ("ABILITY_NUM_FIELD", {"word_off": 8, "word_size": 4, "shift": 30, "width": 4}),  # overflows word
    ("POKEBALL_FIELD", {"word_off": 10, "word_size": 3, "shift": 0, "width": 6}),   # bad word_size
])
def test_bad_bitfield_layout_is_refused_by_python_before_any_byte_is_read(field_key, bad_field):
    with pytest.raises(ValueError, match=field_key):
        codec.decode_party_mon_masked(b"\x00" * codec.PARTY_MON_SIZE, layout={field_key: bad_field})


def test_bad_bitfield_layout_is_refused_by_lua_not_a_nil_shift_crash():
    bad = {"POKEBALL_FIELD": {"word_off": 20, "word_size": 2, "shift": 0, "width": 6}}
    with pytest.raises(Exception, match="POKEBALL_FIELD"):
        _lua_reads(bad)


def test_bad_nickname_extra_char_bitfield_is_refused():
    bad = {"NICKNAME_EXTRA": {"chars": [{"word_off": 11, "word_size": 4, "shift": 0, "width": 8}]}}
    with pytest.raises(ValueError, match="NICKNAME_EXTRA.chars"):
        codec.decode_party_mon_masked(b"\x00" * codec.PARTY_MON_SIZE, layout=bad)
    with pytest.raises(Exception, match="NICKNAME_EXTRA.chars"):
        _lua_reads(bad)


# --- F5 mutation checks: relocated fields are load-bearing, not decorative --

def test_pokeball_field_mutation_a_wrong_shift_decodes_the_wrong_ball():
    raw, expected = _build_expansion_party_record()
    wrong = dict(EXPANSION_LAYOUT)
    wrong["POKEBALL_FIELD"] = {"word_off": 10, "word_size": 2, "shift": 1, "width": 6}
    decoded = codec.decode_party_mon_masked(raw, layout=wrong)
    assert decoded["pokeball"] != expected["pokeball"]


def test_ability_num_field_mutation_a_wrong_word_off_decodes_garbage():
    raw, expected = _build_expansion_party_record()
    wrong = dict(EXPANSION_LAYOUT)
    wrong["ABILITY_NUM_FIELD"] = {"word_off": 4, "word_size": 4, "shift": 29, "width": 2}
    decoded = codec.decode_party_mon_masked(raw, layout=wrong)
    assert decoded["ability_num"] != expected["ability_num"]


def test_pp_mask_mutation_a_wide_mask_lets_the_hypertrained_bit_through():
    raw, expected = _build_expansion_party_record()
    wrong = dict(EXPANSION_LAYOUT)
    wrong["PP_MASK"] = 0xFF
    decoded = codec.decode_party_mon_masked(raw, layout=wrong)
    assert decoded["pp"] != expected["pp"]


def test_markings_mask_mutation_a_wide_mask_lets_compressed_status_through():
    raw, expected = _build_expansion_party_record()
    wrong = dict(EXPANSION_LAYOUT)
    wrong["MARKINGS_MASK"] = 0xFF
    decoded = codec.decode_party_mon_masked(raw, layout=wrong)
    assert decoded["markings"] != expected["markings"]


def test_shiny_modifier_field_mutation_a_wrong_shift_reads_the_wrong_bit():
    raw, expected = _build_expansion_party_record()
    wrong = dict(EXPANSION_LAYOUT)
    wrong["SHINY_MODIFIER_FIELD"] = {"shift": 13, "width": 1}
    decoded = codec.decode_party_mon_masked(raw, layout=wrong)
    assert decoded["shiny_modifier"] != expected["shiny_modifier"]


# --- F4: real inertness proof -- pin the pre-XR-1 decoder, not a tautology --

def _load_pre_xr1_codec() -> types.ModuleType:
    """The codec exactly as it stood before XR-1 (commit 798b6c80, the merge
    just before b40153c4), loaded as an independent module via ``git show``
    (the same technique the predecessor used to spot-check XR-1; see
    tests/unit/test_check_release_zip.py for the established pattern of
    reading a historical blob this way)."""
    proc = subprocess.run(["git", "show", "798b6c80:server/adapters/gen3_codec.py"],
                           cwd=_ROOT, capture_output=True, text=True, check=True)
    module = types.ModuleType("gen3_codec_pre_xr1")
    exec(compile(proc.stdout, "gen3_codec_pre_xr1.py", "exec"), module.__dict__)
    return module


def test_xr1_and_xr2_do_not_perturb_the_pre_expansion_decoder_on_any_committed_fixture():
    """XR-2 F4: the prior version of this test (masked(layout=None) ==
    unmasked) was tautological -- both call sites run the exact same code, so
    it could never go red. The real inertness claim is that XR-1/XR-2 did not
    change what the ALWAYS-vanilla decode_party_mon/decode_box_mon produce.
    Prove that by diffing against the codec as it stood immediately before
    XR-1 (commit 798b6c80) across every committed fixture record."""
    old = _load_pre_xr1_codec()
    fixtures = sorted((_ROOT / "tests/fixtures/gen3").glob("*.sav"))
    assert fixtures, "no gen3 fixtures found"
    checked = 0
    for path in fixtures:
        image = path.read_bytes()
        rr = path.name.startswith("rr_")
        title = codec.TITLE_EMERALD if path.name.startswith("emerald_") else codec.TITLE_FRLG
        parsed = codec.parse_flash(image, cfru=rr, title=title)
        old_parsed = old.parse_flash(image, cfru=rr, title=title)
        for block_name, size, decode_new, decode_old in (
            ("sb1", codec.PARTY_MON_SIZE, codec.decode_party_mon, old.decode_party_mon),
            ("storage", codec.BOX_MON_SIZE, codec.decode_box_mon, old.decode_box_mon),
        ):
            block, old_block = parsed.get(block_name), old_parsed.get(block_name)
            if not block:
                continue
            assert bytes(block) == bytes(old_block)  # same disk layout, sanity
            for start in range(0, len(block) - size + 1, size):
                raw = bytes(block[start:start + size])
                new_json = json.dumps(decode_new(raw, rr=rr), sort_keys=True, default=str)
                old_json = json.dumps(decode_old(raw, rr=rr), sort_keys=True, default=str)
                assert new_json == old_json
                checked += 1
    assert checked > 0, "no records decoded across the fixture set"


# --- Lua twin (reads.lua) ----------------------------------------------------

def test_lua_reads_decodes_the_same_expansion_record():
    raw, expected = _build_expansion_party_record()
    runtime, reads = _lua_reads(EXPANSION_LAYOUT)
    lua_mon = reads.decode_party_mon(runtime.table(*raw))

    assert lua_mon.species == expected["species"]
    assert lua_mon.held_item == expected["held_item"]
    assert list(lua_mon.moves.values()) == expected["moves"]
    assert lua_mon.experience == expected["experience"]
    assert lua_mon.nickname == expected["nickname"]
    assert lua_mon.pokeball == expected["pokeball"]
    assert lua_mon.ability_num == expected["ability_num"]
    assert list(lua_mon.pp.values()) == expected["pp"]
    assert lua_mon.markings == expected["markings"]
    assert lua_mon.shiny_modifier == expected["shiny_modifier"]


def test_lua_reads_is_inert_without_the_expansion_derived_keys():
    """The vanilla FR/LG/RR profiles carry none of derived.MON_*_MASK /
    NICKNAME_EXTRA, so lua/gen3/reads.lua must decode exactly as it did
    before this card on every such profile."""
    lupa = pytest.importorskip("lupa")
    profile = json.loads((_ROOT / "data/games/gen3_frlg/profile.json").read_text())["titles"]["firered"]
    assert "MON_SPECIES_MASK" not in profile["derived"]
    assert "NICKNAME_EXTRA" not in profile["derived"]

    image = (_ROOT / "tests/fixtures/gen3/firered_town.sav").read_bytes()
    sb1 = codec.parse_flash(image)["sb1"]
    py_expected = codec.party_from_save(image)

    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = runtime.execute(_LUA_READS.read_text(encoding="utf-8"))
    reads = module.new(runtime.table_from(profile, recursive=True), runtime.table(
        read_u8=lambda *_: 0, read_u32=lambda *_: 0,
        read_bytes=lambda *_: runtime.table()))
    for slot, py in enumerate(py_expected):
        start = codec.SB1_PARTY_OFFSET + slot * codec.PARTY_MON_SIZE
        lua = reads.decode_party_mon(runtime.table(*sb1[start:start + codec.PARTY_MON_SIZE]))
        for field in ("species", "held_item", "experience", "nickname", "pokeball",
                      "ability_num", "markings"):
            assert lua[field] == py[field], field
        assert list(lua.moves.values()) == py["moves"]
        assert list(lua.pp.values()) == py["pp"]


# --- X2: the SHIPPED gen3_exp profile drives both decoders -------------------

def _shipped_exp_derived() -> dict:
    """data/games/gen3_exp/28877d73/profile.json's derived block: what Entry.build hands
    lua/gen3/reads.lua on the reference build (not the test twin above)."""
    pack = json.loads((_ROOT / "data/games/gen3_exp/28877d73/profile.json").read_text())
    return pack["titles"]["emerald_expansion_28877d73"]["derived"]


def test_shipped_exp_profile_carries_every_layout_key_reads_lua_consumes():
    derived = _shipped_exp_derived()
    assert set(EXPANSION_LAYOUT) <= set(derived)
    # the pre-X2 facts-shaped keys no decoder reads are gone (one representation, not two)
    assert "NICKNAME11_FIELD" not in derived and "NICKNAME12_FIELD" not in derived


def test_lua_reads_decodes_an_expansion_record_through_the_shipped_profile():
    raw, expected = _build_expansion_party_record()
    runtime, reads = _lua_reads(_shipped_exp_derived())
    lua_mon = reads.decode_party_mon(runtime.table(*raw))
    assert lua_mon.species == expected["species"]
    assert lua_mon.held_item == expected["held_item"]
    assert list(lua_mon.moves.values()) == expected["moves"]
    assert lua_mon.experience == expected["experience"]
    assert lua_mon.nickname == expected["nickname"]
    assert lua_mon.pokeball == expected["pokeball"]
    assert lua_mon.ability_num == expected["ability_num"]
    assert list(lua_mon.pp.values()) == expected["pp"]
    assert lua_mon.markings == expected["markings"]
    assert lua_mon.shiny_modifier == expected["shiny_modifier"]


def test_python_masked_decode_through_the_shipped_profile_matches():
    raw, expected = _build_expansion_party_record()
    layout = {k: v for k, v in _shipped_exp_derived().items() if k in EXPANSION_LAYOUT}
    decoded = codec.decode_party_mon_masked(raw, rr=False, layout=layout)
    for field in ("species", "held_item", "moves", "experience", "nickname", "pokeball",
                  "ability_num", "pp", "markings", "shiny_modifier"):
        assert decoded[field] == expected[field], field
