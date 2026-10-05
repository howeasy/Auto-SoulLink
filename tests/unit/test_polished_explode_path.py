"""Card POL-EXPLODE: the Polished explode (W-3) / rival-swap (W-4) CLIENT path.

lua/gen2/polished_explode.lua is the one writer the shared client gets (a facade over the overworld writer and
polished_writes.lua), polished_overworld.lua O.battle_checkpoint is its battle hold, and compose_polished
(lua/gen2/entry.lua) wires both plus p.battle_hold. Same rig as test_polished_write_path.py: the REAL overlay ROM
(patch/dist/SLink-Polished.ups over the pinned release), a System Bus image laid out from
data/polished/polished_slink.sym, frame-driven client; assertions are on the actual bytes and the io write log.

Proved here:
  * the three battle sites are byte sequences that occur ONCE in bank 0F of the executed overlay ROM (D7 00 alone
    occurs 4x: the negative control), and every address, routine bound, operand and coordinate is re-derived
    from the .sym and the write_checkpoint pack, not taken from the module under test
  * the fabricated p.battle_hold shape the client reads (no wPlayerSubStatus5, no transformed_bit) and the third
    io hook, SLink-gen2-battle-hold at 0f:416A
  * an explode lands only at the hold, in the polished_writes order (move slot, PP read-modify-write, party mirror,
    wCurPlayerMove LAST), touches nothing outside its declared ranges, and a wrong bank or a patched byte writes
    nothing; out-of-battle / link / native save / backup save / unarmed refuse
  * faint_active_battler refuses by name; an in-battle faint stays queued and lands at the overworld checkpoint
    after the battle
  * the rival path: trainer_battle_start is announced from writes.sym, replace_rival_team answers "unsupported"
    (the two blockers are pinned), and write_enemy_party through the facade lands at the real gate state and
    refuses at the poll state
  * six RED CONTROLS, each a source mutation of the real module over the SAME rig, in the order: facade sym,
    snapshot stamping, permit bounds, bank guard, byte re-check, predicate fact

NOT proved (no cartridge, no live run): that BizHawk's exec hook sees 0f:416A as an instruction start, and every
rival write on a running Polished ROM. The path stays DEV_OVERLAY_PREDICATE_HOLD.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.adapters import polished_codec as pc
from tests.unit.test_polished_boxes import Image
from tests.unit.test_polished_client import _entry, _pair
from tests.unit.test_polished_lua import ROOT
from tests.unit.test_polished_write_path import (
    HARNESS,
    SAVING_FLAT,
    SYM,
    Rig,
    key_of,
    live_mon,
    overlay,
    party,
    seal_save,
    sysbus,
)

lupa = pytest.importorskip("lupa")

REPO = Path(ROOT)
LUA = REPO / "lua/gen2"
RECORD, NAME, MON_NAME = 48, 11, 11
PARTY_MONS = SYM["wPartyMons"][1]
EXPLOSION = next(m["id"] for m in json.loads((REPO / "data/games/polished_crystal/moves.json").read_text(
    encoding="utf-8"))["moves"] if m["constant"] == "EXPLOSION")
FRAME_BANK = 0x0F


def flat(bank: int, pc_: int) -> int:
    return bank * 0x4000 + pc_ - 0x4000


# bank 0F, pc, bytes, the routine's own .sym label and the label that follows it
SITES = {
    "explode": (0x416A, "cd3542", "BattleTurn", "SafariBattleTurn"),
    "rival_gate": (0x47DD, "218bd2", "SendInUserPkmn", "SetParticipant"),
    "trainer_ready": (0x7271, "d7004007", "InitEnemy", "ExitBattle"),
}


def bank_f(rom: bytes) -> bytes:
    return rom[FRAME_BANK * 0x4000:(FRAME_BANK + 1) * 0x4000]


def addr(label: str, offset: int = 0) -> int:
    return SYM[label][1] + offset


# ── the sites: unique in the EXECUTED overlay ROM, re-derived from the .sym ──────────────────────────────────

def test_the_battle_sites_occur_once_in_bank_0f_of_the_executed_overlay_rom():
    rom = overlay()[1]
    bank = bank_f(rom)
    for name, (pc_, hexed, routine, after) in SITES.items():
        want = bytes.fromhex(hexed)
        assert bank.count(want) == 1, f"{name}: {hexed} is not unique in bank 0F"
        assert rom[flat(FRAME_BANK, pc_):flat(FRAME_BANK, pc_) + len(want)] == want, name
        lo, hi = SYM[routine][1], SYM[after][1]
        assert SYM[routine][0] == SYM[after][0] == FRAME_BANK
        assert lo <= pc_ and pc_ + len(want) <= hi, f"{name} is not inside {routine}"
        assert rom[flat(FRAME_BANK, lo):flat(FRAME_BANK, hi)].count(want) == 1, f"{name} not unique in {routine}"
    # NEGATIVE CONTROL: the 2-byte head of trainer_ready is NOT unique, which is why the 4-byte sequence is the pin
    assert bank.count(bytes.fromhex("d700")) == 4


def test_the_site_operands_are_the_sym_labels():
    rom = overlay()[1]
    at = flat(FRAME_BANK, SITES["explode"][0])
    assert rom[at] == 0xCD and int.from_bytes(rom[at + 1:at + 3], "little") == SYM["DetermineMoveOrder"][1]
    at = flat(FRAME_BANK, SITES["rival_gate"][0])
    assert rom[at] == 0x21 and int.from_bytes(rom[at + 1:at + 3], "little") == SYM["wOTPartyMons"][1]


def lua_module(name: str):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.eval(f'dofile("{ROOT}/lua/gen2/{name}")')


def test_the_module_sites_equal_the_derived_ones_and_the_pack():
    _, over = lua_module("polished_overworld.lua")
    pack = json.loads((REPO / "data/games/polished_crystal/write_checkpoint.json").read_text(encoding="utf-8"))
    hold = pack["titles"]["polished_crystal"]["battle_hold"]
    for name, (pc_, hexed, routine, after) in SITES.items():
        site = over.BATTLE_SITES[name]
        assert (site["bank"], site["pc"]) == (FRAME_BANK, pc_)
        assert bytes(site["bytes"].values()).hex() == hexed
        assert (site["routine"], site["routine_start"], site["routine_end"]) == (routine, SYM[routine][1], SYM[after][1])
    assert (hold["execution_before"]["bank"], hold["execution_before"]["pc"]) == (FRAME_BANK, 0x416A)
    assert hold["execution_before"]["expected_hex"] == "cd3542"
    assert (hold["rival_swap_gate"]["bank"], hold["rival_swap_gate"]["pc"]) == (FRAME_BANK, 0x47DD)


def test_the_facade_coordinates_are_the_sym():
    _, explode = lua_module("polished_explode.lua")
    _, writes = lua_module("polished_writes.lua")
    labels = [writes.COORDS[i] for i in range(1, len(writes.COORDS) + 1)]
    assert len(labels) == 16
    for label in labels:
        assert tuple(explode.COORDS[label].values()) == SYM[label], label
    for label, target in explode.TARGETS.items():
        assert (target["bank"], target["address"]) == SYM[label] and target["width"] == 1, label
    profile = json.loads((REPO / "data/games/polished_crystal/profile.json").read_text(encoding="utf-8"))["titles"]["polished"]
    for label in labels:                      # wherever the generated profile carries a label it must agree
        if label in profile["ram"]:
            assert (profile["ram_bank"][label], profile["ram"][label]) == SYM[label], label


# ── the rig: the composed client, a battle image, a mutable source seam ──────────────────────────────────────

HARNESS_HOOKS = HARNESS.replace(
    "function io.on_bus_exec(fn, addr, name) log.hooks[#log.hooks + 1] = name return #log.hooks end",
    "function io.on_bus_exec(fn, addr, name) log.hooks[#log.hooks + 1] = name\n"
    "        log.hook_at = log.hook_at or {} log.hook_at[name] = addr return #log.hooks end")
assert HARNESS_HOOKS != HARNESS

OVERRIDE = """
local real_dofile = dofile
function dofile(path)
    local source = SLINK_OVERRIDES[path:match("lua/gen2/[%w_]+%.lua$") or ""]
    if source then return assert(load(source, "=mutant"))() end
    return real_dofile(path)
end
"""


class BattleRig(Rig):
    """Rig, with the exec-hook addresses recorded and any lua/gen2 module replaceable by a mutated source."""

    def __init__(self, mons, rom=None, overrides=None):
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.mem = self.lua.table_from(sysbus(mons))
        self.img = seal_save(Image())
        deps, self.io, self.log = self.lua.execute(HARNESS_HOOKS.replace("ROOTDIR", json.dumps(ROOT)))(
            rom if rom is not None else overlay()[1], self.mem, self.img)
        if overrides:
            self.lua.globals().SLINK_OVERRIDES = self.lua.table_from(overrides)
            self.lua.execute(OVERRIDE)
        self.parts, why = _pair(_entry(self.lua).build(deps))
        assert why is None, why
        self.client = self.parts.client
        self.lua.globals().SLINK_PARTS = self.parts
        self.client.start(self.client)

    def put(self, label, value, offset=0):
        self.mem[addr(label, offset)] = value

    def get(self, label, offset=0):
        return self.mem[addr(label, offset)] or 0

    def lines(self):
        return list(self.log["lines"].values())


def enter_battle(rig, mons, *, mode=1, slot=0, move=2, action=0, hold=True):
    """A solo battle image: the mode, the active battler and its battle struct, the committed move."""
    rig.put("wBattleMode", mode)
    rig.put("wLinkMode", 0)
    rig.put("wGameLogicPaused", 0)
    rig.put("hROMBank", FRAME_BANK if hold else 0x25)
    rig.put("wCurBattleMon", slot)
    rig.put("wCurMoveNum", move)
    rig.put("wBattlePlayerAction", action)
    rig.put("wBattleMonSpecies", mons[slot]["species_id"] & 0xFF)
    for i in range(4):
        rig.put("wBattleMonMoves", 0x20 + i, i)
        rig.put("wBattleMonPP", 0xC0 | (5 + i), i)
    rig.put("wCurPlayerMove", 0x20 + move)


def ready(mons=None, **kwargs):
    mons = mons or party()
    rig = BattleRig(mons, rom=kwargs.pop("rom", None), overrides=kwargs.pop("overrides", None))
    assert rig.arm_writes(), "the client never enabled its writes"
    enter_battle(rig, mons, **kwargs)
    return rig, mons


def order(rig, cmd, mons, slot=0, **extra):
    rig.client.handle_command(rig.client, rig.lua.table_from({"cmd": cmd, "key": key_of(mons[slot]),
                                                              "nickname": "BOOM", **extra}))


def at_hold(rig):
    rig.client.at_battle_hold(rig.client)


def lcall(rig, fn, *args):
    return _pair(rig.lua.eval("function(f, ...) return pcall(f, ...) end")(fn, *args))


def snapshot(rig, **fields):
    base = {"mode": 1, "link_mode": 0, "active_slot": 0, "player_action": 0}
    base.update(fields)
    return rig.lua.table_from(base)


def direct_explode(rig, slot=0, **fields):
    """arm + explode through the facade, exactly as client.at_battle_hold does; (ok, why) and always disarmed."""
    writes = rig.parts.battle.writes
    ok, why = lcall(rig, writes.arm, writes, "battle_hold")
    if ok:
        ok, why = lcall(rig, writes.explode_active_battler, writes, slot, snapshot(rig, **fields))
    writes.disarm(writes)
    return ok, why


# ── composition: the fabricated hold shape and the third hook ────────────────────────────────────────────────

def test_the_composed_battle_hold_has_the_shape_the_client_reads():
    rig = BattleRig(party())
    hold = rig.parts.battle.hold
    assert (hold.execution_before.bank, hold.execution_before.pc) == (FRAME_BANK, 0x416A)
    assert (hold.rival_swap_gate.bank, hold.rival_swap_gate.pc) == (FRAME_BANK, 0x47DD)
    targets = {k: (v.bank, v.address, v.width) for k, v in hold.write.targets.items()}
    assert targets == {"wBattleMonSpecies": (*SYM["wBattleMonSpecies"], 1),
                       "wBattlePlayerAction": (*SYM["wBattlePlayerAction"], 1)}
    assert "wPlayerSubStatus5" not in targets and hold.transformed_bit is None       # does not exist in Polished
    assert rig.parts.battle.checkpoint.qualification == "DEV_OVERLAY_PREDICATE_HOLD"
    assert dict(rig.parts.battle.writes.sym.wCurOTMon) == {1: 0, 2: 0xC4DD}
    assert dict(rig.parts.battle.writes.sym.wBattlePlayerAction) == {1: 1, 2: 0xD0F4}
    assert rig.client.battle_hook is not None
    assert rig.log["hook_at"]["SLink-gen2-battle-hold"] == 0x416A
    assert rig.parts.overworld.writes.armed is None and rig.parts.battle.writes.armed is None


def test_the_battle_kinds_are_not_the_overworld_kinds():
    rig = BattleRig(party())
    over, battle = rig.parts.overworld.checkpoint, rig.parts.battle.checkpoint
    assert _pair(over.check(over, "battle_faint"))[0] is False
    assert _pair(battle.check(battle, "party_hp"))[0] is False
    assert _pair(over.check(over, "party_hp"))[0] is True       # the overworld hold is unchanged


# ── an explode lands only at the hold ───────────────────────────────────────────────────────────────────────

def test_an_explode_waits_for_the_hold_and_lands_in_the_writers_order():
    rig, mons = ready()
    before_pp = rig.mem[PARTY_MONS + 22 + 2] or 0
    order(rig, "force_explode", mons)
    assert len(rig.client.pending_battle_writes) == 1
    rig.frame(5)
    assert rig.writes() == [], "an explode was written outside the hold"
    at_hold(rig)
    move = 2
    assert rig.get("wBattleMonMoves", move) == EXPLOSION
    assert rig.get("wBattleMonPP", move) == 0xC1                          # (0xC7 & 0xC0) | 1: the PP Ups survive
    assert rig.mem[PARTY_MONS + 2 + move] == EXPLOSION                    # the party mirror (slot 0)
    assert rig.mem[PARTY_MONS + 22 + move] == (before_pp & 0xC0) | 1
    assert rig.get("wCurPlayerMove") == EXPLOSION
    writes = rig.writes()
    assert len(writes) == 5 and writes[-1]["addr"] == addr("wCurPlayerMove"), "wCurPlayerMove must be written LAST"
    herb, herb_end = addr("wMirrorHerbPendingBoosts"), addr("wOTPartyMons")
    declared = [(addr("wBattleMonMoves"), addr("wBattleMonMoves") + 4), (addr("wBattleMonPP"), addr("wBattleMonPP") + 4),
                (addr("wCurPlayerMove"), addr("wCurPlayerMove") + 1),
                (PARTY_MONS + 2, PARTY_MONS + 6), (PARTY_MONS + 22, PARTY_MONS + 26)]
    for w in writes:
        assert w["domain"] == "System Bus" and any(lo <= w["addr"] < hi for lo, hi in declared), w
        assert not herb <= w["addr"] < herb_end
    assert rig.parts.battle.writes.armed is None and rig.parts.overworld.writes.armed is None


def test_a_committed_item_or_switch_is_not_an_explode():
    """wBattlePlayerAction != USEMOVE: the turn is spent, so the client takes the faint branch, which refuses."""
    rig, mons = ready(action=1)
    order(rig, "force_explode", mons)
    at_hold(rig)
    assert rig.writes() == [] and rig.get("wBattleMonMoves", 2) == 0x22


def test_the_wrong_bank_writes_nothing():
    rig, mons = ready(hold=False)                                          # hROMBank = 0x25
    order(rig, "force_explode", mons)
    at_hold(rig)
    assert rig.writes() == [] and len(rig.client.pending_battle_writes) == 1
    ok, why = direct_explode(rig)
    assert ok is False and "not at the BattleTurn hold" in why and rig.writes() == []


def test_a_patched_hold_byte_writes_nothing():
    patched = bytearray(overlay()[1])
    patched[flat(FRAME_BANK, 0x416A)] = 0x00
    rig, mons = ready(rom=bytes(patched))
    order(rig, "force_explode", mons)
    at_hold(rig)
    assert rig.writes() == [] and rig.get("wCurPlayerMove") == 0x22
    ok, why = direct_explode(rig)
    assert ok is False and "hold site bytes differ" in why and rig.writes() == []


@pytest.mark.parametrize("label,value,why", [
    ("wBattleMode", 0, "not in a battle"),
    ("wBattleMode", 3, "not in a battle"),
    ("wLinkMode", 1, "link cable"),
    ("wGameLogicPaused", 1, "native save"),
])
def test_a_hold_that_does_not_hold_refuses(label, value, why):
    rig, mons = ready()
    rig.put(label, value)
    ok, got = direct_explode(rig)
    assert ok is False and "write refused at arm" in got and why in got
    order(rig, "force_explode", mons)
    at_hold(rig)
    assert rig.writes() == [] and rig.get("wCurPlayerMove") == 0x22


def test_a_backup_save_refuses():
    rig, _ = ready()
    rig.img.mem["CartRAM"][SAVING_FLAT] = 1
    ok, why = direct_explode(rig)
    assert ok is False and "backup save in progress" in why and rig.writes() == []


def test_an_unarmed_writer_and_a_linked_snapshot_refuse():
    rig, _ = ready()
    writes = rig.parts.battle.writes
    ok, why = lcall(rig, writes.explode_active_battler, writes, 0, snapshot(rig))
    assert ok is False and "not armed" in why and rig.writes() == []
    ok, why = direct_explode(rig, link_mode=1)                             # a lying snapshot: link_mode, not the byte
    assert ok is False and "linked or unknown battle context" in why and rig.writes() == []
    ok, why = direct_explode(rig, player_action=1)
    assert ok is False and "committed move" in why and rig.writes() == []
    ok, why = direct_explode(rig, active_slot=1)
    assert ok is False and "not the active battler" in why and rig.writes() == []


def test_an_unknown_armed_reason_is_refused():
    rig, _ = ready()
    writes = rig.parts.battle.writes
    ok, why = lcall(rig, writes.arm, writes, "battle_bench")
    assert ok is False and "no composed Polished write" in why and writes.armed is None


# ── faints: refused by name, handed to the overworld checkpoint ──────────────────────────────────────────────

def test_faint_active_battler_refuses_by_name():
    rig, _ = ready()
    writes = rig.parts.battle.writes
    ok, why = lcall(rig, writes.faint_active_battler, writes, 0, snapshot(rig))
    assert ok is False and "not composed on Polished" in why and "USEITEM" in why and rig.writes() == []


def test_an_in_battle_faint_stays_queued_then_lands_at_the_overworld_checkpoint():
    rig, mons = ready()
    order(rig, "force_faint", mons)
    at_hold(rig)
    assert rig.hp(0) == 300 and rig.writes() == [] and len(rig.client.pending_battle_writes) == 1
    assert any("not composed on Polished" in line for line in rig.lines())
    rig.put("wBattleMode", 0)                                              # the battle ends ...
    rig.put("hROMBank", 0x25)
    rig.frame(3)                                                           # ... handed over, and the overworld hold lands it
    assert len(rig.client.pending_battle_writes) == 0
    assert rig.hp(0) == 0 and rig.status(0) == 0 and rig.hp(1) == 300


def test_a_bench_faint_in_battle_is_refused_not_landed():
    rig, mons = ready()
    order(rig, "force_faint", mons, slot=1)
    at_hold(rig)
    assert rig.hp(1) == 300 and rig.writes() == []
    assert rig.parts.battle.writes.armed is None and rig.parts.overworld.writes.armed is None


# ── the rival path ──────────────────────────────────────────────────────────────────────────────────────────

TRAINER = (0x1B, 3)                                                       # wOtherTrainerClass, wOtherTrainerID


def trainer_window(rig, mons):
    enter_battle(rig, mons, mode=2)
    rig.put("wOtherTrainerClass", TRAINER[0])
    rig.put("wOtherTrainerID", TRAINER[1])
    rig.put("wCurOTMon", 0xFF)                                             # InitEnemyTrainer until the first send-out


def test_a_trainer_battle_is_announced_from_the_facade_sym():
    rig, mons = ready()
    trainer_window(rig, mons)
    rig.frame(3)
    starts = rig.sent("trainer_battle_start")
    assert [m["trainer_id"] for m in starts] == [TRAINER[0] * 256 + TRAINER[1]]


def test_replace_rival_team_is_unsupported_and_the_blockers_are_pinned():
    rig, mons = ready()
    trainer_window(rig, mons)
    rig.frame(3)
    tid = TRAINER[0] * 256 + TRAINER[1]
    rig.client.handle_command(rig.client, rig.lua.table_from({"cmd": "replace_rival_team", "trainer_id": tid,
                                                              "blobs_hex": rig.lua.table_from(["00" * 70])}))
    rig.frame(2)
    assert [m["error"] for m in rig.sent("rival_team_replaced")] == ["unsupported"] and rig.writes() == []
    # blocker 1: the client decodes a blob with constants the generated Polished profile does not carry
    constants = json.loads((REPO / "data/games/polished_crystal/profile.json").read_text(
        encoding="utf-8"))["titles"]["polished"]["constants"]
    assert not {"PARTYMON_STRUCT_LENGTH", "MON_HP", "MON_SPECIES"} & set(constants)


def enemy_mons(lua, count=2):
    mons = []
    for i in range(count):
        mon = live_mon(__import__("random").Random(900 + i), 150 + i, hp=200, ot="RIVAL", nick=f"FOE{i}")
        mons.append(lua.table_from({
            "record": lua.table_from(list(pc.encode_party_mon(mon))),
            "ot": lua.table_from(list(pc.encode_text("RIVAL", 8) + bytes(3))),
            "nick": lua.table_from(list(pc.encode_text(f"FOE{i}", 11)))}))
    return mons


def rival_write(rig, count, cur):
    writes = rig.parts.battle.writes
    ok, why = lcall(rig, writes.arm, writes, "rival_swap")
    if ok:
        ok, why = lcall(rig, writes.write_enemy_party, writes, rig.lua.table_from(enemy_mons(rig.lua, count)),
                        rig.lua.table_from({"mode": 2, "link_mode": 0, "cur_ot_mon": cur}))
    writes.disarm(writes)
    return ok, why


def test_the_facade_writes_the_enemy_party_at_the_real_gate_state_and_never_the_herb_byte():
    rig, mons = ready()
    enter_battle(rig, mons, mode=2)
    rig.put("wCurOTMon", 0)
    rig.put("wCurPartyMon", 0)
    rig.put("wMirrorHerbPendingBoosts", 0x5A)
    ok, why = rival_write(rig, 2, 0)
    assert ok is True, why
    assert rig.get("wOTPartyCount") == 2 and rig.get("wMirrorHerbPendingBoosts") == 0x5A
    species = [rig.get("wOTPartyMons", RECORD * i) for i in range(2)]
    assert species == [150 & 0xFF, 151 & 0xFF]
    herb, herb_end = addr("wMirrorHerbPendingBoosts"), addr("wOTPartyMons")
    assert rig.writes() and not any(herb <= w["addr"] < herb_end for w in rig.writes())
    assert all(addr("wOTPartyCount") <= w["addr"] < addr("wOTPartyDataEnd") for w in rig.writes())


def test_the_poll_state_cannot_land_a_rival_write_blocker_two():
    """rival_tick polls at a frame end while wCurOTMon == 0xFF; write_enemy_party refuses cur outside the NEW
    party. This pins WHY p.rival_swap is not composed: the write is only valid at 0f:47DD."""
    rig, mons = ready()
    enter_battle(rig, mons, mode=2)
    rig.put("wCurOTMon", 0xFF)
    rig.put("wCurPartyMon", 0xFF)
    ok, why = rival_write(rig, 2, 0xFF)
    assert ok is False and "outside the new party" in why and rig.writes() == []
    rig.put("wCurOTMon", 0)
    rig.put("wCurPartyMon", 0)
    ok, why = rival_write(rig, 2, 1)                                       # a snapshot that disagrees with the bytes
    assert ok is False and "stale snapshot" in why and rig.writes() == []


# ── RED CONTROLS: each brake removed from the REAL module, same rig, same image ──────────────────────────────

EXPLODE = (LUA / "polished_explode.lua").read_text(encoding="utf-8")
OVER = (LUA / "polished_overworld.lua").read_text(encoding="utf-8")
WRITES = (LUA / "polished_writes.lua").read_text(encoding="utf-8")


def mutate(source, old, new):
    assert source.count(old) == 1, f"mutation anchor not unique: {old!r}"
    return source.replace(old, new)


def mutant(path, source):
    return {f"lua/gen2/{path}": source}


def exploded(rig):
    return rig.get("wCurPlayerMove") == EXPLOSION


def test_red_1_without_the_facade_sym_no_trainer_battle_is_announced():
    rig, mons = ready()
    trainer_window(rig, mons)
    rig.frame(3)
    assert len(rig.sent("trainer_battle_start")) == 1                      # the composed control
    source = mutate(EXPLODE, "{sym = sym, qualification", "{qualification")
    rig, mons = ready(overrides=mutant("polished_explode.lua", source))
    assert rig.parts.battle.writes.sym is None
    trainer_window(rig, mons)
    rig.frame(3)
    assert rig.sent("trainer_battle_start") == [], "writes.sym is not load-bearing"


def test_red_2_without_the_snapshot_stamp_every_write_refuses():
    rig, mons = ready()
    order(rig, "force_explode", mons)
    at_hold(rig)
    assert exploded(rig)                                                   # the composed control lands
    source = mutate(EXPLODE, "        out.bank, out.pc = site.bank, site.pc\n", "")
    rig, mons = ready(overrides=mutant("polished_explode.lua", source))
    order(rig, "force_explode", mons)
    at_hold(rig)
    assert not exploded(rig) and rig.writes() == [], "the stamp is not load-bearing"
    assert any("snapshot not taken at the battle_hold PC" in line for line in rig.lines())
    rig = ready(overrides=mutant("polished_explode.lua", source))[0]
    rig.put("wMirrorHerbPendingBoosts", 0)
    ok, why = direct_explode(rig)                                          # and the rival write refuses the same way
    assert ok is False and "snapshot not taken" in why


DRIFT = ('{domain="System Bus", addr=at.wCurPlayerMove, bytes={x}},',
         '{domain="System Bus", addr=at.wMirrorHerbPendingBoosts, bytes={x}},')
OPEN_BOUNDS = (("return not touches_herb(addr, n) and declared(reason, addr, n) ~= nil", "return true"),
               ("return r ~= nil and io.bank_valid(r[3], addr, n) == true", "return true"))


def test_red_3_an_open_permit_lets_a_drifted_write_hit_the_herb_byte():
    """A writer that drifted onto wMirrorHerbPendingBoosts: the real permit refuses the whole batch (nothing
    lands); with the bounds opened the byte is written."""
    drifted = mutate(WRITES, *DRIFT)
    rig, mons = ready(overrides=mutant("polished_writes.lua", drifted))
    ok, why = direct_explode(rig)
    assert ok is False and "write refused" in why and rig.get("wMirrorHerbPendingBoosts") == 0 and rig.writes() == []
    opened = drifted
    for old, new in OPEN_BOUNDS:
        opened = mutate(opened, old, new)
    rig, mons = ready(overrides=mutant("polished_writes.lua", opened))
    ok, why = direct_explode(rig)
    assert ok is True, why
    assert rig.get("wMirrorHerbPendingBoosts") == EXPLOSION, "the permit bounds are not load-bearing"


def test_red_4_without_the_bank_guard_a_write_lands_outside_the_hold_bank():
    rig, _ = ready(hold=False)
    ok, why = direct_explode(rig)
    assert ok is False and not exploded(rig)                               # the composed control refuses
    source = mutate(OVER, "if hold_bank ~= sites[want.at].bank then", "if false then")
    rig, _ = ready(hold=False, overrides=mutant("polished_overworld.lua", source))
    ok, why = direct_explode(rig)
    assert ok is True and exploded(rig), "the bank guard is not load-bearing"


def test_red_5_without_the_byte_recheck_a_patched_rom_takes_the_write():
    patched = bytearray(overlay()[1])
    patched[flat(FRAME_BANK, 0x416A)] = 0x00
    rig, _ = ready(rom=bytes(patched))
    ok, why = direct_explode(rig)
    assert ok is False and not exploded(rig)                               # the composed control refuses
    source = mutate(OVER, "if seen ~= expected then", "if false then")
    rig, _ = ready(rom=bytes(patched), overrides=mutant("polished_overworld.lua", source))
    ok, why = direct_explode(rig)
    assert ok is True and exploded(rig), "the byte re-check is not load-bearing"


def test_red_6_without_the_link_fact_a_linked_battle_takes_the_write():
    rig, _ = ready()
    rig.put("wLinkMode", 1)
    ok, why = direct_explode(rig)                                          # the snapshot says 0, the byte says 1
    assert ok is False and not exploded(rig)                               # the composed control refuses
    source = mutate(OVER, 'if observed.wLinkMode ~= 0 then return refuse("link cable active (wLinkMode)") end', "")
    rig, _ = ready(overrides=mutant("polished_overworld.lua", source))
    rig.put("wLinkMode", 1)
    ok, why = direct_explode(rig)
    assert ok is True and exploded(rig), "the link predicate is not load-bearing"


CLIENT = (LUA / "client.lua").read_text(encoding="utf-8")


def test_red_7_without_the_release_poll_an_in_battle_death_never_lands():
    """Polished binds no battle_end signal, so only release_battle_writes hands a refused in-battle faint to the
    overworld checkpoint; with it disabled the death stays queued after the battle (a lost Soul Link death)."""
    source = mutate(CLIENT, "if not p.battle_release_poll or #self.pending_battle_writes == 0 then return end",
                    "if true then return end")
    rig, mons = ready(overrides=mutant("client.lua", source))
    order(rig, "force_faint", mons)
    at_hold(rig)
    rig.put("wBattleMode", 0)
    rig.put("hROMBank", 0x25)
    rig.frame(5)
    assert rig.hp(0) == 300 and len(rig.client.pending_battle_writes) == 1, "the release poll is not load-bearing"
