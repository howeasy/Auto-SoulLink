"""The Polished 53-byte `trademon` codec and the two load-bearing ROM anchors of the SLink trade port.

Three things are pinned here, all of them things docs/polished/TRADE.md left open or got wrong:

1. the struct is 53 bytes, from the built sym (wPlayerTrademon 00:c51c .. wPlayerTrademonEnd 00:c551),
   and encode_trademon/decode_trademon are exact inverses;
2. the receptionist anchor: the Trade object event's two-byte script pointer, read off the release
   ROM, so a port that rewrites it can prove it rewrote only those two bytes;
3. the idle-overworld dispatch fingerprint the coordinator measured live
   (docs/polished/LIVE_RESULTS.md, Run 1 Stage 4 / Run 2 Stage B phase 1), re-derived from the release
   ROM's own bytes rather than copied from the prose.

Nothing here needs an emulator or a built overlay: the anchors are read from the pinned release ROM.
"""
from __future__ import annotations

import pathlib

import pytest

from server.adapters import polished_codec as C

ROOT = pathlib.Path(__file__).resolve().parents[2]
SYM = ROOT / "data" / "polished" / "polishedcrystal.sym"
RELEASE = pathlib.Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
needs_rom = pytest.mark.skipif(not RELEASE.exists(), reason="pinned release ROM not cached")


def _symbols() -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for line in SYM.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and ":" in parts[0] and len(parts[0]) == 7:
            bank, addr = parts[0].split(":")
            out[parts[1]] = (int(bank, 16), int(addr, 16))
    return out


def _flat(symbols: dict[str, tuple[int, int]], name: str) -> int:
    bank, addr = symbols[name]
    return addr if bank == 0 else bank * 0x4000 + addr - 0x4000


def _mon(**over) -> dict:
    """A decoded mon, built to encode_party_mon's own contract so the test cannot drift from the
    codec it exercises."""
    dvs = {"hp": 14, "attack": 13, "defense": 12, "speed": 11,
           "special_attack": 10, "special_defense": 9}
    base = {
        "species_id": 25, "form": 0, "gender": "male", "is_egg": False, "shiny": False,
        "ability_slot": 1, "nature": 7, "held_item": 4, "moves": [33, 45, 0, 0],
        "ot_id": 0xD1C2, "exp": 100000, "evs": dict.fromkeys(C.STAT_NAMES, 0), "dvs": dvs,
        "pp": [35, 35, 0, 0], "pp_ups": [0, 0, 0, 0], "happiness": 70, "pokerus": 0,
        "caught_data": 0x24, "caught_level": 5, "caught_location": 0, "level": 42,
        "status": 0, "unused": 0, "hp": 41, "max_hp": 42,
        "stats": dict.fromkeys(C.STAT_NAMES[1:], 100),
        "dv_bytes": int.from_bytes(C.encode_dvs(dvs), "big"),
        "ot_raw_hex": (b"Aaaaaaa" + bytes([C.TERMINATOR]) + bytes(3)).hex(),
        "nickname_raw_hex": (b"Pikachu" + bytes([C.TERMINATOR]) * 4).hex(),
    }
    base.update(over)
    return base


def _refuse(call, *args, **kwargs):
    with pytest.raises(ValueError):
        call(*args, **kwargs)


# ── 1. the struct ─────────────────────────────────────────────────────────────

def test_trademon_is_53_bytes_from_the_sym():
    symbols = _symbols()
    assert symbols["wPlayerTrademon"] == (0, 0xC51C)
    assert symbols["wPlayerTrademonEnd"] == (0, 0xC551)
    assert C.TRADEMON_SIZE == 53 == symbols["wPlayerTrademonEnd"][1] - symbols["wPlayerTrademon"][1]
    assert symbols["wOTTrademonEnd"][1] - symbols["wOTTrademon"][1] == 53


def test_trademon_field_offsets_match_the_sym():
    """Every field's WRAM address is the struct base plus its documented offset. This is what fails
    if the macro and the ROM ever disagree."""
    symbols = _symbols()
    base = symbols["wPlayerTrademon"][1]
    for name, offset in C.TRADEMON.items():
        address = symbols[f"wPlayerTrademon{name}"][1]
        assert address == base + offset, f"{name}: sym {address:#06x} vs {base:#06x}+{offset}"


def test_every_trademon_field_span_is_inside_the_struct():
    """The three name fields are 11 bytes each whatever the player-name length is. An OT-name span
    written as `OTName..ID` instead of `OTName..OTName+11` overruns into the DV bytes -- and because
    a bytearray slice assignment resizes, that silently produced a 48-byte struct here."""
    buf = bytearray(C.TRADEMON_SIZE)
    for name in ("SpeciesName", "SenderName", "OTName", "Nickname"):
        start = C.TRADEMON[name]
        end = start + C.TRADEMON_NAME_SIZE
        assert end <= C.TRADEMON_SIZE, name
        buf[start:end] = bytes(C.TRADEMON_NAME_SIZE)
    assert len(buf) == C.TRADEMON_SIZE
    # the real span boundaries, as the encoder writes them
    assert C.TRADEMON["SpeciesName"] + C.TRADEMON_NAME_SIZE == C.TRADEMON["Nickname"]
    assert C.TRADEMON["Nickname"] + C.TRADEMON_NAME_SIZE == C.TRADEMON["SenderName"]
    assert C.TRADEMON["SenderName"] + C.TRADEMON_NAME_SIZE == C.TRADEMON["OTName"]
    assert C.TRADEMON["OTName"] + C.TRADEMON_NAME_SIZE == C.TRADEMON["HPAtkDV"]


def test_trademon_round_trips_every_field():
    mon = _mon()
    raw = C.encode_trademon(mon, species_name_raw=b"Pikachu" + bytes(4),
                            sender_name_raw=b"Blue" + bytes(7))
    assert len(raw) == C.TRADEMON_SIZE
    back = C.decode_trademon(raw)
    for field in ("species_id", "form", "gender", "is_egg", "shiny", "ability_slot", "nature",
                  "ot_id", "caught_data", "dvs", "dv_bytes"):
        assert back[field] == mon[field], field
    assert bytes.fromhex(back["species_name_raw_hex"]) == b"Pikachu" + bytes(4)
    assert bytes.fromhex(back["sender_name_raw_hex"]) == b"Blue" + bytes(7)


@pytest.mark.parametrize("species,form,ext", [(25, 0, 0), (265, 0, 1), (9, 3, 0)])
def test_nine_bit_species_survives_the_trademon(species, form, ext):
    """The 9-bit species is the LOW byte plus bit 5 of the form byte. A species above 0xFF must not
    be silently truncated -- that is the bug the vanilla one-byte species checks carried."""
    raw = C.encode_trademon(_mon(species_id=species, form=form))
    assert raw[C.TRADEMON["Species"]] == species & 0xFF
    assert bool(raw[C.TRADEMON["Form"]] & C.EXTSPECIES_MASK) is bool(ext)
    assert C.decode_trademon(raw)["species_id"] == species


def test_trademon_carries_the_third_dv_byte():
    """Vanilla copied TWO DV bytes; Polished's struct has three. A two-byte copy would leave
    SatSdfDV stale, so the third must be written and must land where the sym says."""
    raw = C.encode_trademon(_mon())
    span = slice(C.TRADEMON["HPAtkDV"], C.TRADEMON["SatSdfDV"] + 1)
    assert raw[span] == C.encode_dvs(_mon()["dvs"])
    assert len(raw[span]) == 3


def test_trademon_from_party_blob_matches_the_direct_encode():
    """The send path the client uses: a 70-byte wire blob -> 53 bytes. It must equal encoding the
    blob's decoded mon directly, or the two paths can disagree about what is on the wire."""
    blob = C.encode_party_blob(_mon())
    assert C.trademon_from_party_blob(blob) == C.encode_trademon(C.decode_party_blob(blob))


def test_decoded_trademon_keys_identically_to_the_source_mon():
    """The identity key must not change because a mon travelled as a trademon: a trade is a change
    of owner, not of identity."""
    mon = _mon(shiny=True, gender="female", form=2)
    back = C.decode_trademon(C.encode_trademon(mon))
    assert C.key(back) == C.key(mon)


def test_trademon_names_can_come_from_text():
    raw = C.encode_trademon(_mon(species_name="Pikachu", sender_name="Blue"))
    assert C.decode_trademon(raw)["species_name"] == "Pikachu"
    assert C.decode_trademon(raw)["sender_name"] == "Blue"


# ── red controls (state-changing inputs must be refused, not silently accepted) ─

def test_red_trademon_rejects_a_52_byte_struct():
    """The vanilla Crystal size. Accepting it would read CaughtData out of the ID's low byte."""
    _refuse(C.decode_trademon, bytes(52))


def test_red_trademon_rejects_a_54_byte_struct():
    _refuse(C.decode_trademon, bytes(54))


@pytest.mark.parametrize("size", [C.BLOB_SIZE - 1, C.BLOB_SIZE + 1])
def test_red_trademon_rejects_a_mis_sized_blob(size):
    _refuse(C.trademon_from_party_blob, bytes(size))


@pytest.mark.parametrize("species", [0, 0x200, 0x1FFFF])
def test_red_trademon_rejects_a_species_outside_nine_bits(species):
    _refuse(C.encode_trademon, _mon(species_id=species))


def test_red_trademon_rejects_contradictory_dv_fields():
    """dv_bytes is derived from dvs; if both are present and disagree the mon is ambiguous."""
    _refuse(C.encode_trademon, _mon(dv_bytes=0x000000))


def test_red_trademon_rejects_a_missing_or_unknown_gender():
    mon = _mon()
    del mon["gender"]
    _refuse(C.encode_trademon, mon)
    _refuse(C.encode_trademon, _mon(gender="genderless"))


def test_red_trademon_rejects_a_short_name_field():
    _refuse(C.encode_trademon, _mon(), species_name_raw=b"Pika")


def test_red_trademon_rejects_an_out_of_range_form():
    _refuse(C.encode_trademon, _mon(form=32))


def test_red_trademon_rejects_an_out_of_range_nature():
    _refuse(C.encode_trademon, _mon(nature=32))


# ── 2. the receptionist anchor ────────────────────────────────────────────────

@needs_rom
def test_receptionist_anchor_is_one_unique_two_byte_pointer():
    """The Trade receptionist is `object_event ... OBJECTTYPE_SCRIPT, 0, LinkReceptionistScript_Trade,
    -1` (maps/PokeCenter2F.asm:21). Its script pointer is the two bytes in the object event. There
    must be exactly ONE such pointer in bank $24, or a port that rewrites it corrupts something."""
    rom = RELEASE.read_bytes()
    symbols = _symbols()
    assert symbols["LinkReceptionistScript_Trade"] == (0x24, 0x7601)
    want = symbols["LinkReceptionistScript_Trade"][1].to_bytes(2, "little")
    lo, hi = 0x24 * 0x4000, 0x25 * 0x4000
    hits, at = [], lo
    while True:
        at = rom.find(want, at, hi)
        if at < 0:
            break
        hits.append(at)
        at += 1
    assert len(hits) == 1, f"expected one $7601 pointer in bank $24, found {[hex(h) for h in hits]}"


@needs_rom
def test_the_two_receptionist_anchors_are_separate_pointers():
    """Guards the rewrite against its neighbour: two receptionists share one object-event struct,
    so confusing them would send the battle receptionist into the trade flow."""
    rom = RELEASE.read_bytes()
    symbols = _symbols()
    trade = symbols["LinkReceptionistScript_Trade"][1].to_bytes(2, "little")
    battle = symbols["LinkReceptionistScript_Battle"][1].to_bytes(2, "little")
    assert trade != battle
    for want in (trade, battle):
        hits, at = [], 0x24 * 0x4000
        while True:
            at = rom.find(want, at, 0x25 * 0x4000)
            if at < 0:
                break
            hits.append(at)
            at += 1
        assert len(hits) == 1, (want.hex(), [hex(h) for h in hits])


# ── 3. the dispatch fingerprint ───────────────────────────────────────────────

@needs_rom
def test_idle_overworld_fingerprint_is_the_measured_chain():
    """A `SlinkTradeDispatch` equivalent sees, one call deeper than the bridge probe,
    OverworldLoop.loop+9 -> HandleMap+0x15 -> NextOverworldFrame+0x3D -> DelayFrame+3. Every word is
    re-derived here from the ROM bytes and the sym, not copied from the prose: the doc's chain is
    only usable if the call really is where it says."""
    rom = RELEASE.read_bytes()
    symbols = _symbols()
    assert symbols["DelayFrame"] == (0, 0x0DA8)
    nowf = _flat(symbols, "NextOverworldFrame")
    call_site = rom.index(b"\xcc\xa8\x0d", nowf, nowf + 0x40)
    assert call_site + 3 == nowf + 0x3D
    tail = [(symbols["OverworldLoop.loop"][1] + 9, symbols["OverworldLoop.loop"][0]),
            (symbols["HandleMap"][1] + 0x15, symbols["HandleMap"][0]),
            (symbols["NextOverworldFrame"][1] + 0x3D, symbols["NextOverworldFrame"][0]),
            (symbols["DelayFrame"][1] + 3, 0)]
    assert tail == [(0x50E2, 0x25), (0x516B, 0x25), (0x51C2, 0x25), (0x0DAB, 0)]


@needs_rom
def test_the_scripts_context_tail_is_the_other_measured_one():
    """Inside a script the tail is ScriptEvents.loop+9 / HandleMap+9 / OverworldLoop.loop+9 /
    FarCall+4 -- NOT the idle-overworld HandleMap+0x15, which sits two bytes deeper. A dispatch
    that used the idle constants anywhere inside the receptionist script would never fire, which is
    the failure TRADE.md 8.3 predicted when it found no `call DelayFrames`."""
    symbols = _symbols()
    assert (symbols["ScriptEvents.loop"][1] + 9, symbols["ScriptEvents.loop"][0]) == (0x62B5, 0x25)
    assert (symbols["HandleMap"][1] + 9, symbols["HandleMap"][0]) == (0x515F, 0x25)
    assert (symbols["HandleMap"][1] + 0x15, symbols["HandleMap"][0]) == (0x516B, 0x25)


@needs_rom
def test_far_call_and_the_script_helpers_resolve_to_the_words_the_measurement_named():
    """The word below the script tail is the engine's own FarCall frame: `FarCall+4` is a
    `jp _ReturnFarCall`, which is why $0014 and $2698 appear on every stack the coordinator read."""
    symbols = _symbols()
    rom = RELEASE.read_bytes()
    assert symbols["FarCall"] == (0, 0x0010)
    # FarCall+4 is the `jp _ReturnFarCall` the measurement saw as the word $0014 on every stack.
    assert rom[0x14:0x17] == b"\xc3\x98\x26"                     # jp $2698, at FarCall+4
    assert symbols["_ReturnFarCall"] == (0, 0x2698)


@needs_rom
def test_handle_map_calls_two_distinct_places_so_the_two_tails_are_not_one_value():
    """`HandleMap+9` and `HandleMap+0x15` are different return addresses into the same routine. That
    difference is the whole reason the fingerprint has to name one window and refuse the other."""
    rom = RELEASE.read_bytes()
    handle_map = _flat(_symbols(), "HandleMap")
    assert rom[handle_map:handle_map + 3] == b"\xcd\xc8\x51"       # HandleMap: call MapObjects
    assert rom[handle_map + 3:handle_map + 6] == b"\xcd\x5e\x62"   # HandleMap: call MapEvents
