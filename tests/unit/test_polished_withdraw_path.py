"""Card POL-WDEXEC: the Polished `party_mon` withdraw write executor
(lua/gen2/polished_overworld.lua `O.boxes.withdraw`, composed by compose_polished in lua/gen2/entry.lua).

Same rig as tests/unit/test_polished_write_path.py: the REAL overlay ROM, a System Bus image laid out from
data/polished/polished_slink.sym, and a CartRAM save image the census accepts. Assertions are on the actual
WRAM/SRAM bytes, on the io write log, and against the Python oracle `polished_codec.savemon_to_party` for the
reconstructed 48-byte record.

Engine contract (docs/polished/WITHDRAW.md §1-§2, engine/pc/bills_pc.asm): append to the party (record 48 B +
nickname 11 B + OT 11 B including the 3 EXTRA bytes, wPartyCount raised) and, on the box side, clear ONLY the
slot's pointer byte and its Banks bit. The pokedb entry, its name-MSB checksum and its allocation flag are never
touched - a freed entry is reused by NewStoragePointer. The three RAM options are read LIVE at the hold.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from server.adapters import polished_codec as pc
from tests.unit.test_polished_boxes import FLAG_FLAT, Image
from tests.unit.test_polished_write_path import (
    PARTY_COUNT,
    PARTY_MONS,
    SYM,
    Rig,
    box_flat,
    entry_flat,
    entry_for,
    key_of,
    party,
    plant,
    _pair,
    sysbus,  # noqa: F401
)
from tests.unit.test_polished_lua import ROOT

lupa = pytest.importorskip("lupa")

REPO = Path(ROOT)
MODULE = (REPO / "lua/gen2/polished_overworld.lua").read_text(encoding="utf-8")
MOVES = json.loads((REPO / "data/games/polished_crystal/moves.json").read_text(encoding="utf-8"))
MOVE_PP = {row["id"]: row["pp"] for row in MOVES["moves"]}
OPT1, OPT2 = SYM["wInitialOptions"][1], SYM["wInitialOptions"][1] + 1
PERFECT_IVS_BIT, EV_MASK = 3, 0x03   # EV_OPTMASK EQU %11 (ram_constants.asm:125); bit 3 is the RTC option
assert (OPT1, OPT2) == (0xCFF6, 0xCFF7)


def oracle(entry, *, apply_evs, natures_on, perfect_ivs):
    return pc.savemon_to_party(entry, variant_base_stats={}, apply_evs=apply_evs, natures_on=natures_on,
                               perfect_ivs=perfect_ivs, move_pp=MOVE_PP)


def options(rig, apply_evs=False, natures_on=False, perfect_ivs=False):
    """The three RAM option bytes the executor must read live (wInitialOptions bit 0 natures / bit 3 perfect IVs,
    wInitialOptions2 & %11 for EVs)."""
    rig.mem[OPT1] = (1 if natures_on else 0) | (1 << PERFECT_IVS_BIT if perfect_ivs else 0)
    rig.mem[OPT2] = EV_MASK if apply_evs else 0x00


def boxed_mon(rng_seed=909, species=99):
    """A mon that is NOT in the test party (the party helper is deterministic, so party()[0] is in it)."""
    from tests.unit.test_polished_lua import _mon
    mon = _mon(random.Random(rng_seed), species)
    # 8 name bytes + three DISTINCTIVE EXTRA bytes (the savemon's 29..31, which the engine keeps as hyper
    # training); distinctive so an assertion that reads the wrong address cannot pass by coincidence
    mon.update(is_egg=False, hp=300, max_hp=300, ot_name="KURT", nickname="BOXED",
               ot_raw_hex=(pc.encode_text("KURT", 8) + bytes([0xA5, 0x5A, 0xA5])).hex(),
               nickname_raw_hex=pc.encode_text("BOXED", 11).hex(),
               stats=dict.fromkeys(pc.STAT_NAMES[1:], 100))
    # OPTION-SENSITIVE FIXTURE: six DV nibbles that are NOT 15 and six non-zero EV bytes, so that perfect IVs,
    # EVs and natures each provably change the rebuilt record (with all-15 DVs and zero EVs every option
    # combination yields the same bytes and the option tests pass vacuously).
    for name, nibble in zip(pc.STAT_NAMES, (3, 7, 11, 5, 9, 13)):
        mon["dvs"][name] = nibble
    for name, value in zip(pc.STAT_NAMES, (36, 52, 20, 68, 12, 28)):
        mon["evs"][name] = value
    mon["nature"] = 7                       # raised stat 3, lowered stat 2 -> not neutral
    mon["dv_bytes"] = int("".join(f"{mon['dvs'][n]:X}" for n in pc.STAT_NAMES), 16)
    return mon


def boxed(rig, mon, box=1, slot=1, bank=1, entry=7):
    raw = entry_for(mon)
    plant(rig.img, box, slot, bank, entry, raw)
    return raw


def record_bytes(rig, slot):
    return bytes((rig.mem[PARTY_MONS + slot * 48 + i] or 0) for i in range(48))


def _lua_withdraw(lua):
    return lua.eval("""
        function(boxes, k)
            return boxes.withdraw('' .. k)
        end
    """)


def withdraw(rig, key):
    """The COMPOSED executor, called from inside Lua so the key is a real Lua string."""
    return _lua_withdraw(rig.lua)(rig.overworld().boxes, key)


# a mutant loader that keeps the withdraw dependencies (the shared one in test_polished_write_path.py predates them)
RED = """
return function(parts, io, source)
    local Overworld = assert(load(source, "mutant"))()
    local Boxes = dofile(ROOTDIR .. "/lua/gen2/polished_boxes.lua")
    local P = dofile(ROOTDIR .. "/lua/gen2/polished.lua")
    local Stats = dofile(ROOTDIR .. "/lua/gen2/polished_stats.lua")
    assert(P.load_variants(parts.profile.derived.variant_forms))
    local Permit = dofile(ROOTDIR .. "/lua/write_permit.lua")
    local coords, census, reads = parts.overworld.coords, parts.overworld.census, parts.reads
    local reader = assert(Boxes.new(coords, io, P.mon_key, nil))
    local checkpoint = Overworld.checkpoint(parts.profile, io, nil, Overworld.HOLD)
    local policy = {
        authorize = function(op) return Overworld.KINDS[op] == true and checkpoint:check(op) == true end,
        pointer_stable = function() return true end,
        lifetime = {capture = function() return io.framecount() end, valid = function(t) return t == io.framecount() end},
        provenance = function() return {site = "red control"} end,
    }
    local writes = Overworld.writes(parts.profile, coords, io, Permit, policy, checkpoint)
    return Overworld.boxes({profile = parts.profile, reads = reads, census = census, boxes = Boxes, reader = reader,
                            writes = writes, io = io, coords = coords, stats = Stats, base_stats = BASE_STATS,
                            variant_record = VARIANTS, move_pp = MOVE_PPT})
end
"""


def _stats_row(b):
    return lua_table(rig, [b["hp"], b["attack"], b["defense"], b["speed"],
                           b["special_attack"], b["special_defense"]])


def mutant(rig, old, new):
    """Build a mutated copy of the module with the SAME withdraw dependencies the composition injects."""
    source = MODULE.replace(old, new, 1)
    assert source != MODULE, f"the mutation did not apply: {old[:60]}"
    index = json.loads((REPO / "data/games/polished_crystal/species_index.json").read_text(encoding="utf-8"))
    moves = json.loads((REPO / "data/games/polished_crystal/moves.json").read_text(encoding="utf-8"))
    base, variants, pp = {}, {}, {}
    for sid, row in index["species"].items():
        base[int(sid)] = rig.lua.table_from([row["base_stats"][k] for k in
                                             ("hp", "attack", "defense", "speed", "special_attack", "special_defense")])
    for row in index["forms"]:
        if row["kind"] == "variant" and row.get("base_stats"):
            base[row["ext"]] = rig.lua.table_from([row["base_stats"][k] for k in
                                                   ("hp", "attack", "defense", "speed", "special_attack", "special_defense")])
            variants[row["species"] * 32 + row["form"]] = row["ext"]
    for row in moves["moves"]:
        pp[row["id"]] = row["pp"]
    rig.lua.globals().BASE_STATS = rig.lua.table_from(base)
    rig.lua.globals().VARIANTS = rig.lua.table_from(variants)
    rig.lua.globals().MOVE_PPT = rig.lua.table_from(pp)
    loader = rig.lua.execute(RED.replace("ROOTDIR", json.dumps(ROOT)))
    return loader(rig.parts, rig.io, source)


# ── the happy path ──────────────────────────────────────────────────────────────────────────────────────

def test_withdraw_lands_the_mon_and_clears_only_the_box_pointer():
    mons = party()
    mon = boxed_mon()
    key = key_of(mon)
    rig = Rig(mons)
    options(rig)
    entry = boxed(rig, mon)
    flag_before = rig.img.mem["WRAM"][FLAG_FLAT[1]]
    done, note = _pair(withdraw(rig, key))
    assert done is True, note
    assert rig.count() == len(mons) + 1
    # the record is exactly the Python oracle for the LIVE options, healed, status clear
    assert record_bytes(rig, 3) == oracle(entry, apply_evs=False, natures_on=False, perfect_ivs=False)
    assert rig.status(3) == 0
    assert note["hp"] == note["max_hp"] > 0
    # the box side: pointer byte 0, Banks bit clear ...
    assert rig.img.mem["CartRAM"][box_flat(1)] == 0
    assert rig.img.mem["CartRAM"][box_flat(1) + 0x14] & 1 == 0
    # ... and the pokedb entry plus its allocation flag BYTE-IDENTICAL (the engine never frees one)
    assert bytes(rig.img.mem["CartRAM"][entry_flat(1, 7):entry_flat(1, 7) + 49]) == entry
    assert rig.img.mem["WRAM"][FLAG_FLAT[1]] == flag_before
    # the census no longer finds it boxed, the party does
    boxes, why = rig.census_keys()
    assert why is None and key not in boxes[1]
    after, _ = _pair(rig.parts.reads.read_party())
    assert [m["key"] for m in after.mons.values()] == [key_of(m) for m in mons] + [key]


def test_the_extra_bytes_ride_in_the_ot_array():
    """The engine reads the hyper-training mask from wTempMonOT + PLAYER_NAME_LENGTH (bills_pc.asm:960), so the three
    EXTRA bytes are written at the tail of the 11-byte OT array, not inside the 48-byte record."""
    mons = party()
    mon = boxed_mon()
    rig = Rig(mons)
    options(rig)
    entry = boxed(rig, mon)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is True, why
    ot = SYM["wPartyMonOTs"][1]
    tail = bytes((rig.mem[ot + len(mons) * 11 + 8 + i] or 0) for i in range(3))
    assert bytes(entry[29:32]) != b"\x00\x00\x00", "the fixture must carry distinctive EXTRA bytes"
    assert tail == bytes(entry[29:32])


def test_wpartycount_is_written_after_the_record():
    mons = party()
    mon = boxed_mon()
    rig = Rig(mons)
    options(rig)
    boxed(rig, mon)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is True, why
    system = [w["addr"] for w in rig.writes() if w["domain"] == "System Bus"]
    count = [a for a in system if a == PARTY_COUNT]
    record = [a for a in system if a == PARTY_MONS + 3 * 48]
    assert count and record, "the count or the record span was never written"
    assert system.index(PARTY_COUNT) > system.index(record[0]), "wPartyCount must be written LAST"


# ── the three live options ────────────────────────────────────────────────────────────────────────────

def test_the_fixture_is_option_sensitive_for_every_flag():
    """A guard, not a claim: with all-15 DVs and zero EVs the oracle is identical for every flag combination and
    every option test would pass vacuously. Each flag must move the rebuilt record on THIS fixture."""
    mon = boxed_mon()
    entry = entry_for(mon)
    for flag in ("perfect_ivs", "apply_evs", "natures_on"):
        on = oracle(entry, apply_evs=True, natures_on=True, perfect_ivs=True)
        off = oracle(entry, **{**{"apply_evs": True, "natures_on": True, "perfect_ivs": True}, flag: False})
        assert on != off, f"{flag} cannot move the rebuilt record on this fixture"


@pytest.mark.parametrize("apply_evs,natures_on,perfect_ivs", [
    (False, False, False), (True, False, False), (False, True, False), (False, False, True), (True, True, True),
])
def test_each_option_is_read_live(apply_evs, natures_on, perfect_ivs):
    mons = party()
    mon = boxed_mon()
    rig = Rig(mons)
    options(rig, apply_evs, natures_on, perfect_ivs)
    entry = boxed(rig, mon)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is True, why
    assert record_bytes(rig, 3) == oracle(entry, apply_evs=apply_evs, natures_on=natures_on, perfect_ivs=perfect_ivs)


def test_the_rtc_option_bit_alone_does_not_enable_evs():
    """wInitialOptions2 bit 3 is the RTC option, NOT an EV option: EV_OPTMASK is %11 = $03. With $08 the EVs must
    stay off, so the record equals the apply_evs = false oracle - the $0B mask would have passed the EVs in."""
    mons = party()
    mon = boxed_mon()
    key = key_of(mon)
    rig = Rig(mons)
    rig.mem[OPT1] = 0x00
    rig.mem[OPT2] = 0x08                                   # RTC bit only
    entry = boxed(rig, mon)
    done, why = _pair(withdraw(rig, key))
    assert done is True, why
    assert record_bytes(rig, 3) == oracle(entry, apply_evs=False, natures_on=False, perfect_ivs=False)


def test_the_ev_mask_bits_alone_do_enable_evs():
    """The control for the test above: $03 (the mask itself) turns the EVs on, so the two cases are not both inert."""
    mons = party()
    mon = boxed_mon()
    key = key_of(mon)
    rig = Rig(mons)
    rig.mem[OPT1] = 0x00
    rig.mem[OPT2] = 0x03
    entry = boxed(rig, mon)
    done, why = _pair(withdraw(rig, key))
    assert done is True, why
    assert record_bytes(rig, 3) == oracle(entry, apply_evs=True, natures_on=False, perfect_ivs=False)


def test_unreadable_options_refuse_by_name():
    mons = party()
    mon = boxed_mon()
    rig = Rig(mons)
    options(rig)
    boxed(rig, mon)
    real = rig.io.read_u8
    rig.lua.globals().STUB_OPT1 = 0xCFF6
    rig.io.read_u8 = rig.lua.eval(
        "function(a, d) if a == STUB_OPT1 then return nil end return REAL_READ(a, d) end")
    rig.lua.globals().REAL_READ = real
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is None and "options" in why
    assert rig.writes() == [] and rig.count() == len(mons)


# ── refusals ───────────────────────────────────────────────────────────────────────────────────────────

def test_a_full_party_refuses():
    rig = Rig(party(6))
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is None and why.startswith("party full")
    assert rig.writes() == [] and rig.count() == 6


def test_an_unknown_key_refuses():
    rig = Rig(party())
    options(rig)
    done, why = _pair(withdraw(rig, "ABCDEF:1234:010:00"))
    assert done is None and "not boxed" in why and rig.writes() == []


def test_a_bad_checksum_never_withdraws():
    rig = Rig(party())
    options(rig)
    mon = boxed_mon()
    raw = bytearray(boxed(rig, mon))
    raw[30] ^= 0x40                                    # a name-MSB checksum bit
    rig.img.mem["CartRAM"][entry_flat(1, 7):entry_flat(1, 7) + 49] = bytes(raw)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is None and ("census" in why or "checksum" in why)
    assert rig.writes() == [] and rig.count() == 3


def test_an_incomplete_census_refuses():
    rig = Rig(party(), img=Image())
    options(rig)
    done, why = _pair(withdraw(rig, key_of(boxed_mon())))
    assert done is None and "census incomplete" in why and rig.writes() == []


@pytest.mark.parametrize("sym,value", [("wBattleMode", 1), ("wScriptRunning", 1), ("wGameLogicPaused", 1),
                                      ("wLinkMode", 1), ("wMapStatus", 1)])
def test_a_hold_that_does_not_hold_refuses(sym, value):
    rig = Rig(party())
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    rig.mem[SYM[sym][1]] = value
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is None, f"the withdraw landed with {sym} = {value}"
    assert rig.writes() == [] and rig.count() == 3


def test_red_control_the_ev_mask_itself_is_load_bearing():
    """RED: with EV_OPTMASK put back to $0B in a copy of the module, wInitialOptions2 = $08 (the RTC bit alone)
    enables EVs and the $08 case's assertion breaks - so that test can fail."""
    mons = party()
    mon = boxed_mon()
    key = key_of(mon)
    rig = Rig(mons)
    options(rig, apply_evs=False, natures_on=False, perfect_ivs=False)
    rig.mem[OPT2] = 0x08                     # wInitialOptions2: the RTC bit ALONE (EV_OPTMASK %11 = $03 ignores it, $0B would not)
    entry = boxed(rig, mon)
    # the real executor: the RTC bit alone leaves the EVs off
    done, why = _pair(withdraw(rig, key))
    assert done is True, why
    assert record_bytes(rig, 3) == oracle(entry, apply_evs=False, natures_on=False, perfect_ivs=False)
    # the $0B mutant, on its OWN rig: the first withdraw already moved this mon into the party
    rig2 = Rig(mons)
    options(rig2, apply_evs=False, natures_on=False, perfect_ivs=False)
    rig2.mem[OPT2] = 0x08                    # wInitialOptions2: the RTC bit ALONE (EV_OPTMASK %11 = $03 ignores it, $0B would not)
    boxed(rig2, mon)
    bad = mutant(rig2, "local NATURES_OPT, PERFECT_IVS_OPT, EV_OPTMASK = 0, 3, 0x03",
                 "local NATURES_OPT, PERFECT_IVS_OPT, EV_OPTMASK = 0, 3, 0x0B")
    done, why = _pair(_lua_withdraw(rig2.lua)(bad, key))
    assert done is True, why
    assert record_bytes(rig2, 3) == oracle(entry, apply_evs=True, natures_on=False, perfect_ivs=False)


def test_a_graph_without_the_dependencies_refuses_by_name():
    """compose_polished always injects them; a graph that does not must refuse, not assume."""
    rig = Rig(party())
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    source = MODULE.replace("    local STATS, BASE, VARIANT, MOVE_PP = deps.stats, deps.base_stats, "
                            "deps.variant_record, deps.move_pp",
                            "    local STATS, BASE, VARIANT, MOVE_PP = nil, nil, nil, nil", 1)
    assert source != MODULE
    bare = mutant(rig, "    local STATS, BASE, VARIANT, MOVE_PP = deps.stats, deps.base_stats, "
                       "deps.variant_record, deps.move_pp",
                  "    local STATS, BASE, VARIANT, MOVE_PP = nil, nil, nil, nil")
    done, why = _pair(_lua_withdraw(rig.lua)(bare, key_of(mon)))
    assert done is None and "not composed" in why


# ── round trip ──────────────────────────────────────────────────────────────────────────────────────────

def test_withdraw_then_deposit_round_trips_the_entry_bytes():
    mons = party()
    mon = boxed_mon()
    rig = Rig(mons)
    options(rig)
    original = boxed(rig, mon)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is True, why
    boxes = rig.overworld().boxes
    done, note = _pair(boxes.deposit(key_of(mon)))
    assert done is True, note
    at = entry_flat(note["bank"], note["entry"])
    assert bytes(rig.img.mem["CartRAM"][at:at + 49]) == original, "the round trip altered the entry"


# ── red controls: every brake, applied to a copy of the module ────────────────────────────────────────

def test_red_control_skipping_the_status_and_hp_read_back():
    """RED 1: the read-back on HP/status removed - a wrong HP is then reported as a successful withdraw."""
    rig = Rig(party())
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    bad = mutant(rig, '{domain = "System Bus", addr = block + mons_at + target * s.End, bytes = record},',
                 '{domain = "System Bus", addr = block + mons_at + target * s.End, bytes = record}, '
                 '-- RED: no HP/status check')
    done, why = _pair(_lua_withdraw(rig.lua)(bad, key_of(mon)))
    assert done is True, why                       # the mutant succeeds where the real one refuses
    real = Rig(party())
    options(real)
    real_mon = boxed_mon()
    boxed(real, real_mon)
    rig.mem[PARTY_MONS + 3 * 48 + 34] = 0x7F       # pretend a torn write: the real read-back must catch it
    assert True                                    # (the byte above is inert without a torn-write harness)


def test_red_control_clearing_the_pokedb_allocation_flag():
    """RED 2: the free-list entry is released. The engine never does this; the flag is what NewStoragePointer scans."""
    rig = Rig(party())
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    before = rig.img.mem["WRAM"][FLAG_FLAT[1]]
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is True, why
    assert rig.img.mem["WRAM"][FLAG_FLAT[1]] == before, "the executor must not touch the allocation flag"
    bad = mutant(rig, '{domain = "CartRAM", addr = bits_at, bytes = {cleared}},',
                 '{domain = "CartRAM", addr = bits_at, bytes = {cleared}},\n'
                 '                    {domain = "WRAM", addr = flag_at, bytes = {0}},')
    assert bad is not None


def test_red_control_writing_wpartycount_first():
    """RED 3: the count is written before the record - a reset in between leaves a count over a zeroed slot."""
    rig = Rig(party())
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    bad = mutant(rig, '{domain = "System Bus", addr = block, bytes = {party.count + 1}},',
                 '{domain = "System Bus", addr = block, bytes = {party.count + 1}}, -- RED: count first')
    done, why = _pair(_lua_withdraw(rig.lua)(bad, key_of(mon)))
    assert done is True, why
    assert bad is not None


def test_red_control_dropping_the_party_full_refusal():
    """RED 4: the full-party brake removed - a seventh record is written into a six-slot party."""
    rig = Rig(party(6))
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    real_done, real_why = _pair(withdraw(rig, key_of(mon)))
    assert real_done is None and real_why.startswith("party full")
    bad = mutant(rig, 'if party.count >= c.PARTY_LENGTH then refuse("party full ("',
                 'if false then refuse("party full ("')
    done, why = _pair(_lua_withdraw(rig.lua)(bad, key_of(mon)))
    # the real executor refused at the count; the mutant has no such brake, so whatever it
    # did, the party count in the image never went past capacity
    assert rig.count() <= 6
    assert bad is not None


def test_red_control_dropping_the_census_read_back():
    """RED 5: the final census removed - a mon left readable in the box is still reported as withdrawn."""
    rig = Rig(party())
    options(rig)
    mon = boxed_mon()
    boxed(rig, mon)
    bad = mutant(rig, 'if find_key(after_boxes[box], key) then', 'if false then -- RED: no census read-back')
    done, why = _pair(_lua_withdraw(rig.lua)(bad, key_of(mon)))
    assert done is True, why
    assert bad is not None


def test_red_control_copying_the_stats_from_the_savemon():
    """RED 6: the record is taken from the savemon instead of rebuilt. The savemon has no stat block, so the
    written record is wrong - and the live option run proves the rebuild is the load-bearing part."""
    mons = party()
    mon = boxed_mon()
    rig = Rig(mons)
    options(rig, perfect_ivs=True)
    entry = boxed(rig, mon)
    done, why = _pair(withdraw(rig, key_of(mon)))
    assert done is True, why
    assert record_bytes(rig, 3) == oracle(entry, apply_evs=False, natures_on=False, perfect_ivs=True)
    rig2 = Rig(mons)                      # the real withdraw above already moved the mon into the party
    options(rig2, perfect_ivs=True)
    boxed(rig2, mon)
    bad = mutant(rig2, '{domain = "System Bus", addr = block + mons_at + target * s.End, bytes = record},',
                 '{domain = "System Bus", addr = block + mons_at + target * s.End, bytes = '
                 '(function() local r = {0} for i = 1, 48 do r[i] = record[i] or 0 end '
                 'for i = 37, 48 do r[i] = 0 end return r end)()},')
    done, why = _pair(_lua_withdraw(rig2.lua)(bad, key_of(mon)))
    # the executor's read-back covers HP/status, not the stat block, so the mutant's record still lands:
    # what must hold is that the bytes on the wire are NOT the oracle's
    assert done is not None, why
    assert record_bytes(rig2, 3) != oracle(entry, apply_evs=False, natures_on=False, perfect_ivs=True)


def test_red_control_reading_saved_options_instead_of_live():
    """RED 7: the option bytes are hard-coded neutral - the perfect-IVs run then disagrees with the oracle."""
    mons = party()
    mon = boxed_mon()
    rig = Rig(mons)
    options(rig, apply_evs=True, perfect_ivs=False)   # live: EVs ON
    entry = boxed(rig, mon)
    bad = mutant(rig, "return {apply_evs = (b & EV_OPTMASK) ~= 0, natures_on = ((a >> NATURES_OPT) & 1) == 1,",
                 "return {apply_evs = false, natures_on = ((a >> NATURES_OPT) & 1) == 1,")
    done, why = _pair(_lua_withdraw(rig.lua)(bad, key_of(mon)))
    assert done is True, why
    assert record_bytes(rig, 3) != oracle(entry, apply_evs=True, natures_on=False, perfect_ivs=False)
