"""Polished Crystal Explode Mode (W-3) and Rival Team Swap (W-4) writers, lua/gen2/polished_writes.lua.

SOURCE/MODEL only: lupa over a synthetic 64 KiB WRAM image laid out from data/polished/polishedcrystal.sym.
Whether Explosion fires and the rival sends the partner's team out is a live gate's job, never these.
Spec: docs/polished/EXPLODE_RIVAL.md §6-§10; offsets docs/polished/RAM.md §2.1/§2.3/§2.4.
Fixtures are polished_codec.encode_party_mon records. Two red-control mutants (a write into
wMirrorHerbPendingBoosts; the PP write without its read-modify-write) must each fail these checks.
"""

import json
import random
import re
import sys
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server.adapters import polished_codec as codec  # noqa: E402

MODULE = ROOT / "lua/gen2/polished_writes.lua"
EXPLOSION = 0x99
HOLD = json.loads((ROOT / "data/games/polished_crystal/write_checkpoint.json").read_text())[
    "titles"]["polished_crystal"]["battle_hold"]
SIGNALS = json.loads((ROOT / "data/games/polished_crystal/engine_signals.json").read_text())


def sym(name):
    out = {}
    for line in (ROOT / "data/polished" / name).read_text().splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{2}):([0-9a-fA-F]{4}) (\S+)", line.strip())
        if m:
            out.setdefault(m[3], (int(m[1], 16), int(m[2], 16)))
    return out


SYM = sym("polishedcrystal.sym")
A = {label: addr for label, (_, addr) in SYM.items()}
LABELS = list(LuaRuntime().eval("dofile")(MODULE.as_posix()).COORDS.values())


def profile():
    party = {f: A["wPartyMon1" + f] - A["wPartyMon1"] for f in ("Species", "Moves", "Form", "PP", "HP", "End")}
    battle = {f: A["wBattleMon" + f] - A["wBattleMon"] for f in ("Moves", "PP")}
    return {"title": "polished", "artifact": "polishedcrystal", "rom_sha1": SIGNALS["source"]["rom_sha1"],
            "constants": {"PARTY_LENGTH": 6, "NUM_MOVES": 4, "NAME_LENGTH": 11, "MON_NAME_LENGTH": 11,
                          "TRAINER_BATTLE": 2, "EXTSPECIES_MASK": codec.EXTSPECIES_MASK,
                          "IS_EGG_MASK": codec.IS_EGG_MASK},
            "structs": {"party": party, "battle": battle}}


class World:
    """Synthetic WRAM: WRAM0 $C000-$CFFF and WRAMX bank 1 $D000-$DFFF never overlap, so one image."""

    def __init__(self, source=None):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        rng = random.Random(0x5EED)
        self.memory = bytearray(rng.randrange(256) for _ in range(65536))
        self.writes = []
        self.state = self.lua.table(epoch=1, authorized=True)
        permit = self.lua.eval("dofile")((ROOT / "lua/write_permit.lua").as_posix())
        module = self.lua.execute(source) if source else self.lua.eval("dofile")(MODULE.as_posix())
        io = self.lua.eval("""function(emit, peek)
            return {write_u8=function(a, v, d) return emit(a, v, d) end,
                    read_u8=function(a, d) return peek(a, d) end,
                    bank_valid=function(b, a, n) return true end}
        end""")(self.emit, self.peek)
        policy = self.lua.eval("""function(state)
            return {authorize=function() return state.authorized end,
                    pointer_stable=function() return true end,
                    lifetime={capture=function() return state.epoch end,
                              valid=function(token) return token == state.epoch end},
                    provenance=function() return {site='MODEL polished hold'} end}
        end""")(self.state)
        coords = {label: list(SYM[label]) for label in LABELS}
        self.binder = module.new(self.lua.table_from(profile(), recursive=True),
                                 self.lua.table_from(coords, recursive=True), io, permit, policy,
                                 self.lua.table_from(HOLD, recursive=True))
        # the battle the snapshots describe: 3 mons, slot 1 active, its move 2 chosen (USEMOVE)
        self.memory[A["wPartyCount"]] = 3
        self.memory[A["wCurBattleMon"]], self.memory[A["wCurMoveNum"]] = 1, 2
        self.memory[A["wBattlePlayerAction"]] = 0
        self.memory[A["wBattleMonPP"] + 2] = 0xC5            # 3 PP Ups, 5 PP
        self.memory[A["wPartyMons"] + 48 + 22 + 2] = 0x87    # 2 PP Ups, 7 PP
        self.memory[A["wCurOTMon"]] = self.memory[A["wCurPartyMon"]] = 0

    def emit(self, address, value, domain):
        assert domain == "System Bus"
        self.memory[int(address)] = int(value)
        self.writes.append((int(address), int(value)))

    def peek(self, address, domain):
        assert domain == "System Bus"
        return self.memory[int(address)]

    def call(self, name, *args):
        return self.binder[name](self.binder, *args)

    def explode_snapshot(self, **over):
        fields = {"link_mode": 0, "bank": HOLD["execution_before"]["bank"], "pc": HOLD["execution_before"]["pc"],
                  "player_action": 0, "active_slot": 1, "move_num": 2}
        fields.update(over)
        return self.lua.table(**fields)

    def rival_snapshot(self, **over):
        fields = {"link_mode": 0, "mode": 2, "bank": HOLD["rival_swap_gate"]["bank"],
                  "pc": HOLD["rival_swap_gate"]["pc"], "cur_ot_mon": 0}
        fields.update(over)
        return self.lua.table(**fields)

    def mons(self, records):
        return self.lua.table_from([{"record": list(r), "ot": list(o), "nick": list(n)} for r, o, n in records],
                                   recursive=True)


def diff(before, after):
    return {i: after[i] for i in range(65536) if before[i] != after[i]}


def mon(species, *, hp=30, form=0, pp=(10, 20, 30, 5), pp_ups=(0, 1, 2, 3), is_egg=False):
    return codec.encode_party_mon({
        "species_id": species, "gender": "male", "is_egg": is_egg, "form": form, "shiny": False,
        "ability_slot": 0, "nature": 0, "held_item": 0, "moves": [1, 2, 3, 4], "ot_id": 0x1234, "exp": 1000,
        "evs": dict.fromkeys(codec.STAT_NAMES, 0), "dvs": dict.fromkeys(codec.STAT_NAMES, 15),
        "pp": list(pp), "pp_ups": list(pp_ups), "happiness": 70, "pokerus": 0, "caught_data": 0,
        "caught_level": 5, "caught_location": 0, "level": 20, "status": 0, "unused": 0, "hp": hp, "max_hp": 50,
        "stats": dict.fromkeys(codec.STAT_NAMES[1:], 40)})


def party(*records):
    return [(r, bytes([0x80 + i] + [0x53] * 7 + [0, 0, 0]), bytes([0x90 + i] + [0x53] * 10))
            for i, r in enumerate(records)]


# ── the checks every mutant must fail ────────────────────────────────────────────────────────────


def check_explode(world):
    before = bytes(world.memory)
    world.call("arm", "battle_hold")
    world.call("explode_active_battler", 1, world.explode_snapshot())
    world.call("disarm")
    party_base = A["wPartyMons"] + 48
    expected = [(A["wBattleMonMoves"] + 2, EXPLOSION), (A["wBattleMonPP"] + 2, 0xC1),
                (party_base + 2 + 2, EXPLOSION), (party_base + 22 + 2, 0x81), (A["wCurPlayerMove"], EXPLOSION)]
    assert world.writes == expected                       # wCurPlayerMove LAST (EXPLODE_RIVAL.md §9.1)
    assert diff(before, world.memory) == {a: v for a, v in expected if before[a] != v}


def check_rival(world):
    records = party(mon(25), mon(0x10F, form=3), mon(150, hp=0))
    payload = b"".join(r for r, _, _ in records), b"".join(o for _, o, _ in records), b"".join(n for *_, n in records)
    before = bytes(world.memory)
    world.call("arm", "rival_swap")
    world.call("write_enemy_party", world.mons(records), world.rival_snapshot())
    world.call("disarm")
    herb = range(A["wMirrorHerbPendingBoosts"], A["wOTPartyMons"])
    assert len(herb) == 7 and bytes(world.memory[herb.start:herb.stop]) == before[herb.start:herb.stop]
    expected = {A["wOTPartyCount"]: 3}
    for base, blob in zip((A["wOTPartyMons"], A["wOTPartyMonOTs"], A["wOTPartyMonNicknames"]), payload, strict=True):
        expected.update({base + i: v for i, v in enumerate(blob)})
    assert diff(before, world.memory) == {a: v for a, v in expected.items() if before[a] != v}
    # species is 9-bit + form, exactly as the codec writes it; the record decodes back
    second = bytes(world.memory[A["wOTPartyMons"] + 48:A["wOTPartyMons"] + 96])
    assert (codec.decode_party_mon(second)["species_id"], codec.decode_party_mon(second)["form"]) == (0x10F, 3)


# ── coordinates ──────────────────────────────────────────────────────────────────────────────────


def test_coords_agree_between_clean_and_overlay_sym_and_match_the_spec():
    overlay = sym("polished_slink.sym")
    assert {label: SYM[label] for label in LABELS} == {label: overlay[label] for label in LABELS}
    assert SYM["wCurPlayerMove"] == (0, 0xC540) and SYM["wMirrorHerbPendingBoosts"] == (1, 0xD284)
    assert (SYM["wOTPartyCount"], SYM["wOTPartyMons"], SYM["wOTPartyMonOTs"], SYM["wOTPartyMonNicknames"]) == (
        (1, 0xD283), (1, 0xD28B), (1, 0xD3AB), (1, 0xD3ED))
    assert (HOLD["execution_before"]["bank"], HOLD["execution_before"]["pc"]) == (0x0F, 0x416A)
    assert (HOLD["rival_swap_gate"]["bank"], HOLD["rival_swap_gate"]["pc"]) == (0x0F, 0x47DD)


def test_a_coords_table_overlapping_mirror_herb_is_refused_at_construction():
    lua = LuaRuntime(unpack_returned_tuples=True)
    module = lua.eval("dofile")(MODULE.as_posix())
    coords = {label: list(SYM[label]) for label in LABELS}
    coords["wCurPlayerMove"] = [1, A["wMirrorHerbPendingBoosts"] + 2]   # a declared range inside the herb gap
    with pytest.raises(LuaError, match="intersects wMirrorHerbPendingBoosts"):
        module.new(lua.table_from(profile(), recursive=True), lua.table_from(coords, recursive=True),
                   lua.eval("{write_u8=function() end, read_u8=function() end, bank_valid=function() end}"),
                   lua.eval("dofile")((ROOT / "lua/write_permit.lua").as_posix()),
                   lua.eval("{authorize=function() end, pointer_stable=function() end, provenance=function() end,"
                            " lifetime={capture=function() end, valid=function() end}}"),
                   lua.table_from(HOLD, recursive=True))


# ── W-3 Explode ──────────────────────────────────────────────────────────────────────────────────


def test_explode_writes_the_move_pp_with_pp_ups_kept_the_mirror_and_wcurplayermove_last():
    check_explode(World())


@pytest.mark.parametrize("arm,slot,over,poke,match", [
    (None, 1, {}, None, "battle_hold gate not armed"),
    ("rival_swap", 1, {}, None, "battle_hold gate not armed"),
    ("battle_hold", 1, {"pc": HOLD["rival_swap_gate"]["pc"]}, None, "PC"),
    ("battle_hold", 1, {"link_mode": 1}, None, "linked"),
    ("battle_hold", 1, {"player_action": 2}, None, "committed move"),
    ("battle_hold", 1, {}, ("wCurMoveNum", 0), "stale snapshot"),
    ("battle_hold", 1, {}, ("wCurBattleMon", 0), "stale snapshot"),
    ("battle_hold", 1, {}, ("wBattlePlayerAction", 1), "stale snapshot"),
    ("battle_hold", 6, {"active_slot": 6}, None, "battler slot invalid"),
    ("battle_hold", 3, {"active_slot": 3}, None, "battler slot invalid"),   # wPartyCount = 3
    ("battle_hold", 0, {}, None, "not the active battler"),
    ("battle_hold", 1, {"move_num": 4}, None, "move slot invalid"),
])
def test_explode_refusals_write_nothing(arm, slot, over, poke, match):
    world = World()
    if poke:
        world.memory[A[poke[0]]] = poke[1]
    before = bytes(world.memory)
    if arm:
        world.call("arm", arm)
    with pytest.raises(LuaError, match=match):
        world.call("explode_active_battler", slot, world.explode_snapshot(**over))
    assert world.memory == before and world.writes == []
    assert world.binder.armed is None                     # a refusal disarms (write_permit guard)


# ── W-4 Rival swap ───────────────────────────────────────────────────────────────────────────────


def test_rival_writes_only_the_declared_ranges_and_never_mirror_herb():
    check_rival(World())


@pytest.mark.parametrize("arm,records,over,poke,match", [
    (None, party(mon(25)), {}, None, "rival_swap gate not armed"),
    ("battle_hold", party(mon(25)), {}, None, "rival_swap gate not armed"),
    ("rival_swap", party(mon(25)), {"pc": HOLD["execution_before"]["pc"]}, None, "PC"),
    ("rival_swap", party(mon(25)), {"mode": 1}, None, "not a trainer battle"),
    ("rival_swap", party(mon(25)), {"link_mode": 1}, None, "linked"),
    ("rival_swap", party(*[mon(25)] * 7), {}, None, "count must be 1..6"),
    ("rival_swap", [], {}, None, "count must be 1..6"),
    ("rival_swap", [(mon(25)[:47], b"\x80" * 11, b"\x90" * 11)], {}, None, "record must be 48 bytes"),
    ("rival_swap", [(mon(25), b"\x80" * 8, b"\x90" * 11)], {}, None, "ot must be 11 bytes"),
    ("rival_swap", party(mon(25)), {}, ("wCurOTMon", 1), "stale snapshot"),
    ("rival_swap", party(mon(25)), {}, ("wCurPartyMon", 1), "stale snapshot"),
    ("rival_swap", party(mon(25)), {"cur_ot_mon": 1}, ("wCurOTMon", 1), "outside the new party"),
    ("rival_swap", party(mon(25, hp=0), mon(26)), {}, None, "sent out next and has no HP"),
    ("rival_swap", party(mon(25, is_egg=True)), {}, None, "egg"),
])
def test_rival_refusals_write_nothing(arm, records, over, poke, match):
    world = World()
    if poke:
        world.memory[A[poke[0]]] = poke[1]
    before = bytes(world.memory)
    if arm:
        world.call("arm", arm)
    with pytest.raises(LuaError, match=match):
        world.call("write_enemy_party", world.mons(records), world.rival_snapshot(**over))
    assert world.memory == before and world.writes == []


# ── red controls ─────────────────────────────────────────────────────────────────────────────────


def mutate(*edits):
    source = MODULE.read_text(encoding="utf-8")
    for old, new in edits:
        assert source.count(old) == 1, old              # a mutant that applies nowhere proves nothing
        source = source.replace(old, new)
    return source


HERB_WRITE = ('{domain="System Bus", addr=at.wOTPartyCount, bytes={count}}',
              '{domain="System Bus", addr=at.wOTPartyCount, bytes={count, 0}}')
HERB_GUARD = (("return not touches_herb(addr, n) and declared(reason, addr, n) ~= nil", "return true"),
              ("return r ~= nil and io.bank_valid(r[3], addr, n) == true", "return true"))
NO_PP_RMW = ("return (read(label, offset) & 0xC0) | 1 end", "return 1 end")


def test_red_control_a_write_into_mirror_herb_is_refused_by_the_bounds():
    with pytest.raises(LuaError, match="outside domain bounds"):
        check_rival(World(mutate(HERB_WRITE)))


def test_red_control_an_unguarded_write_into_mirror_herb_fails_the_diff():
    with pytest.raises(AssertionError):
        check_rival(World(mutate(HERB_WRITE, *HERB_GUARD)))


def test_red_control_dropping_the_pp_read_modify_write_fails_the_explode_check():
    with pytest.raises(AssertionError):
        check_explode(World(mutate(NO_PP_RMW)))
