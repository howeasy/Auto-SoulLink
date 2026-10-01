"""Gen 2 Explode Mode (W-3) and Rival Team Swap (W-4) at Gen 1 parity (owner 2026-09-26).

SOURCE/MODEL only: lupa over lua/gen2/writes.lua and the Entry graph (candidate, plus one production
battle-hold case behind the shipped receipts). That Explosion actually fires, and that the rival sends the
partner's team out, is the live gates' job, never inferred from these.

Facts: EXPLOSION = $99 (C/G constants/move_constants.asm:161); RIVAL1 = 9, RIVAL2 = $2A (C
constants/trainer_constants.asm:55,454 / G:51,424); every address from data/gen2/<artifact>.sym.
"""

import re
import sys
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server.adapters.gen2_gsc import Gen2GSCAdapter  # noqa: E402
from tests.unit.test_gen2_client import (  # noqa: E402
    World as ClientWorld,
    action,
    battle_hold,
    battle_hp,
    codec_key,
    hold_ram,
    in_battle,
    mon,
    production,
    production_battle_hold,
)
from tests.unit.test_gen2_writes import World as WritesWorld  # noqa: E402

TITLES = ("crystal", "gold", "silver")
ARTIFACT = {"crystal": "pokecrystal", "gold": "pokegold", "silver": "pokesilver"}
OVERLAY = {"crystal": "crystal_slink", "gold": "gold_slink", "silver": "silver_slink"}
EXPLOSION = 0x99
RIVAL = 9 * 256 + 1           # RIVAL1, instance 1 (the Cherrygrove battle)


def sym(artifact):
    """{symbol: (bank, address)} from a pinned .sym file."""
    out = {}
    for line in (ROOT / "data/gen2" / f"{artifact}.sym").read_text().splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{2}):([0-9a-fA-F]{4}) (\S+)", line.strip())
        if m:
            out[m[3]] = (int(m[1], 16), int(m[2], 16))
    return out


SYM = {title: sym(ARTIFACT[title]) for title in TITLES}


def record(species, hp=30):
    raw = bytearray(48)
    raw[0], raw[31] = species, 20
    raw[34:36] = hp.to_bytes(2, "big")
    raw[36:38] = (50).to_bytes(2, "big")
    return raw


def blob(species, hp=30):
    """The 70-byte party transfer blob: record, OT name, nickname (lua/gen2/wire.lua party_blob_hex)."""
    return bytes(record(species, hp)) + bytes([0x80] + [0x50] * 10) + bytes([0x81] + [0x50] * 10)


# ── the SYM facts the generated profile does not carry ───────────────────────────────────────────


@pytest.mark.parametrize("title", TITLES)
def test_lua_sym_facts_match_the_pinned_clean_and_overlay_sym_files(title):
    lua = LuaRuntime(unpack_returned_tuples=True)
    rows = lua.eval("dofile")((ROOT / "lua/gen2/writes.lua").as_posix()).SYM[title]
    names = sorted(rows.keys())
    assert names == ["wCurOTMon", "wCurPlayerMove", "wOTPartyCount", "wOTPartyDataEnd"]
    for artifact in (ARTIFACT[title], OVERLAY[title]):
        table = sym(artifact)
        for name in names:
            assert (rows[name][1], rows[name][2]) == table[name], (artifact, name)
    # the geometry W-4 writes: count, species list + $FF, 6 x 48 records, 6 x 11 OT names, 6 x 11 nicknames
    table = SYM[title]
    count = table["wOTPartyCount"][1]
    assert table["wOTPartySpecies"][1] == count + 1 and table["wOTPartyMons"][1] == count + 8
    assert table["wOTPartyMonOTs"][1] == count + 8 + 6 * 48
    assert table["wOTPartyMonNicknames"][1] == count + 8 + 6 * 48 + 66
    assert table["wOTPartyDataEnd"][1] == count + 8 + 6 * 48 + 132


# ── W-3 writes ───────────────────────────────────────────────────────────────────────────────────


def explode_snapshot(world, **over):
    fields = {"mode": 1, "active_slot": 1, "battle_type": 0, "link_mode": 0, "player_action": 0}
    fields.update(over)
    return world.lua.table(**fields)


@pytest.mark.parametrize("title", TITLES)
def test_explode_writes_four_explosions_pp1_and_mirror_then_the_chosen_move_last(title):
    world = WritesWorld(title, battle=True)
    ram, base = world.profile["ram"], world.profile["ram"]["wPartyMons"] + 48
    world.call("arm", "battle_hold")
    world.call("explode_active_battler", 1, explode_snapshot(world))
    expected = ([(ram["wBattleMonMoves"] + i, EXPLOSION) for i in range(4)]
                + [(ram["wBattleMonPP"] + i, 1) for i in range(4)]
                + [(base + 2 + i, EXPLOSION) for i in range(4)]
                + [(base + 23 + i, 1) for i in range(4)]
                + [(SYM[title]["wCurPlayerMove"][1], EXPLOSION)])
    assert [(a, v) for a, v, _ in world.writes] == expected
    # HP is left to the engine: EFFECT_SELFDESTRUCT faints the user (C/G data/moves/moves.asm:169)
    assert world.memory[base + 34] == 0xA5 and world.memory[ram["wBattleMonHP"]] == 0xA5


@pytest.mark.parametrize("reason,over,match", [
    ("overworld", {}, "only inside the battle hold"),
    ("battle_hold", {"player_action": 1}, "committed move"),     # USEITEM: the turn is spent
    ("battle_hold", {"player_action": 2}, "committed move"),     # SWITCH
    ("battle_hold", {"active_slot": 0}, "not the active battler"),
    ("battle_hold", {"link_mode": 1}, "linked"),
])
def test_explode_refuses_before_the_first_byte(reason, over, match):
    world = WritesWorld(battle=True)
    world.call("arm", reason)
    with pytest.raises(LuaError, match=match):
        world.call("explode_active_battler", 1, explode_snapshot(world, **over))
    assert world.writes == []


# ── W-4 writes ───────────────────────────────────────────────────────────────────────────────────


def lua_mons(world, mons):
    return world.lua.table_from([{"record": list(record(s, hp)), "ot": [0x80] + [0x50] * 10,
                                  "nick": [0x81] + [0x50] * 10} for s, hp in mons], recursive=True)


def rival_snapshot(world, **over):
    fields = {"mode": 2, "link_mode": 0, "cur_ot_mon": 0xFF}
    fields.update(over)
    return world.lua.table(**fields)


@pytest.mark.parametrize("title", TITLES)
def test_enemy_party_is_written_in_the_read_trainer_party_shape(title):
    world = WritesWorld(title)
    table = SYM[title]
    world.call("arm", "rival_swap")
    world.call("write_enemy_party", lua_mons(world, [(155, 30), (152, 0)]), rival_snapshot(world))
    mem, count = world.memory, table["wOTPartyCount"][1]
    assert list(mem[count:count + 4]) == [2, 155, 152, 0xFF]
    mons = table["wOTPartyMons"][1]
    assert bytes(mem[mons:mons + 96]) == bytes(record(155)) + bytes(record(152, 0))
    ots, nicks = table["wOTPartyMonOTs"][1], table["wOTPartyMonNicknames"][1]
    assert list(mem[ots:ots + 2]) == [0x80, 0x50] and list(mem[nicks + 11:nicks + 13]) == [0x81, 0x50]
    assert mem[mons + 96] == 0xA5 and mem[ots + 22] == 0xA5          # slots 3..6 untouched
    assert all(bank == 1 for bank, _, _ in world.bank_checks)       # WRAMX bank 1 only


@pytest.mark.parametrize("over,mons,match", [
    ({"cur_ot_mon": 0}, [(155, 30)], "already sent a mon out"),
    ({"mode": 1}, [(155, 30)], "not a trainer battle"),
    ({"link_mode": 1}, [(155, 30)], "linked"),
    ({}, [(155, 0), (152, 30)], "enemy mon 1 has no HP"),            # DoBattle's unbounded first-alive scan
    ({}, [(155, 30)] * 7, "count must be 1..6"),
    ({}, [(155, 30), (0, 30)], "species outside"),
])
def test_enemy_party_refuses_the_whole_payload_before_the_first_byte(over, mons, match):
    world = WritesWorld()
    world.call("arm", "rival_swap")
    with pytest.raises(LuaError, match=match):
        world.call("write_enemy_party", lua_mons(world, mons), rival_snapshot(world, **over))
    assert world.writes == []


def test_a_bad_byte_in_the_last_mon_refuses_before_the_first_mon_lands():
    world = WritesWorld()
    mons = lua_mons(world, [(155, 30), (152, 30), (158, 30)])
    mons[3].nick[11] = 256
    world.call("arm", "rival_swap")
    with pytest.raises(LuaError, match="out of range"):
        world.call("write_enemy_party", mons, rival_snapshot(world))
    assert world.writes == []


def test_enemy_party_needs_the_rival_swap_window():
    world = WritesWorld()
    world.call("arm", "battle_hold")
    with pytest.raises(LuaError, match="rival swap window"):
        world.call("write_enemy_party", lua_mons(world, [(155, 30)]), rival_snapshot(world))
    assert world.writes == []


# ── adapter: the packed trainer id ───────────────────────────────────────────────────────────────


def test_every_title_names_the_same_21_rival_ids_so_a_cross_title_run_agrees():
    sets = {title: Gen2GSCAdapter(title).rival_trainer_ids() for title in TITLES}
    expected = {9 * 256 + i for i in range(1, 16)} | {0x2A * 256 + i for i in range(1, 7)}
    assert all(ids == expected for ids in sets.values()), sets
    for title in TITLES:
        assert Gen2GSCAdapter(title).supports_explode_mode() is True
        assert Gen2GSCAdapter(title).trainer_info(RIVAL) == ("", "Rival")


# ── client: W-3 at the battle hold ───────────────────────────────────────────────────────────────


def cur_player_move(world):
    return world.io.read_u8(SYM[world.title]["wCurPlayerMove"][1])


def test_force_explode_turns_the_committed_move_into_explosion_at_the_battle_hold():
    world = ClientWorld()
    active, bench = mon(), mon(species=172, dvs=0x3AAA)
    in_battle(world, [active, bench])                                # wBattlePlayerAction = USEMOVE
    world.reply({"cmd": "force_explode", "key": codec_key(active), "nickname": "PIKA"})
    world.frames(3)
    assert world.written() == []                                     # waits for the hold
    battle_hold(world)
    moves = world.profile["ram"]["wBattleMonMoves"]
    assert [world.io.read_u8(moves + i) for i in range(4)] == [EXPLOSION] * 4
    assert cur_player_move(world) == EXPLOSION
    assert world.written()[-1][0] == SYM["crystal"]["wCurPlayerMove"][1]     # the chosen move LAST
    assert battle_hp(world) == 30 and world.hp_of(0) == (30, 0)     # the engine faints it, not us
    assert "show:!! PIKA KO'd" in world.shown()
    # Explosion's self-KO: the engine zeroes the party record, then HandlePlayerMonFaint (the echo)
    world.emu.poke("System Bus", world.profile["ram"]["wPartyMon1"] + 34, world.lua.table_from([0, 0]))
    world.fire("battle_faint")
    world.frames(2)
    assert world.sent("faint") == []
    assert any("faint echo of a commanded death" in line for line in world.logs.values())


@pytest.mark.parametrize("spent", [1, 2])                           # USEITEM, SWITCH
def test_force_explode_after_an_item_or_switch_is_the_plain_faint(spent):
    world = ClientWorld()
    active = mon()
    in_battle(world, [active, mon(species=172, dvs=0x3AAA)])
    world.emu.poke("System Bus", hold_ram(world, "wBattlePlayerAction"), world.lua.table_from([spent]))
    world.reply({"cmd": "force_explode", "key": codec_key(active)})
    world.frames(2)
    battle_hold(world)
    assert battle_hp(world) == 0 and world.hp_of(0) == (0, 0) and action(world) == 1
    assert cur_player_move(world) != EXPLOSION


def test_force_explode_on_a_bench_mon_is_the_plain_faint():
    world = ClientWorld()
    active, bench = mon(), mon(species=172, dvs=0x3AAA)
    in_battle(world, [active, bench])
    world.reply({"cmd": "force_explode", "key": codec_key(bench)})
    world.frames(2)
    battle_hold(world)
    assert world.hp_of(1) == (0, 0) and battle_hp(world) == 30
    assert EXPLOSION not in [v for _, v, _ in world.written()]


def test_a_failed_explosion_is_re_zeroed_at_the_next_battle_hold():
    """Asleep/frozen/full paralysis: DoTurn's CheckTurn ends the turn before selfdestruct; dead stays dead."""
    world = ClientWorld()
    active = mon()
    in_battle(world, [active, mon(species=172, dvs=0x3AAA)])
    world.reply({"cmd": "force_explode", "key": codec_key(active)})
    world.frames(2)
    battle_hold(world)
    assert battle_hp(world) == 30                                    # the move never ran
    world.frames(2)
    battle_hold(world)
    assert battle_hp(world) == 0 and world.hp_of(0) == (0, 0)


def test_production_explode_lands_only_inside_the_battle_hold():
    world = production()
    active = mon()
    world.party([active, mon(species=172, dvs=0x3AAA)])
    world.hello()
    world.frames(60)
    world.field("wBattleMode", 1)
    world.field("wCurBattleMon", 0)
    world.emu.poke("System Bus", hold_ram(world, "wBattleMonSpecies"), world.lua.table_from([active["species"]]))
    world.emu.poke("System Bus", hold_ram(world, "wBattleMonHP"), world.lua.table_from([0, 30]))
    world.emu.poke("System Bus", hold_ram(world, "wBattlePlayerAction"), world.lua.table_from([0]))
    world.reply({"cmd": "force_explode", "key": codec_key(active)})
    world.frames(3)
    assert production_battle_hold(world, caller=False) == 1          # another caller: refused
    assert world.written() == []
    production_battle_hold(world)
    assert cur_player_move(world) == EXPLOSION and battle_hp(world) == 30
    assert {r["site"] for r in world.parts.writes.log.values()} == {"lua/gen2/entry.lua production"}


# ── client: W-4 rival window ─────────────────────────────────────────────────────────────────────


def rival_battle(world, cls=9, inst=1, link=0):
    """InitEnemyTrainer returned: trainer mode, the (class, instance) pair, wCurOTMon = $FF."""
    world.party([mon()])
    world.hello()
    world.frames(60)
    world.field("wLinkMode", link)
    world.field("wOtherTrainerClass", cls)
    world.field("wOtherTrainerID", inst)
    world.field("wBattleMode", 2)
    set_cur_ot_mon(world, 0xFF)
    world.frames(1)


def set_cur_ot_mon(world, value):
    world.emu.poke("System Bus", SYM[world.title]["wCurOTMon"][1], world.lua.table_from([value]))


def swap(world, *blobs, trainer_id=RIVAL):
    world.reply({"cmd": "replace_rival_team", "trainer_id": trainer_id, "n": len(blobs),
                 "blobs_hex": [b if isinstance(b, str) else b.hex() for b in blobs], "source": "auto"})
    world.frames(1)
    return world.sent("rival_team_replaced")


def ot_party(world):
    count = SYM[world.title]["wOTPartyCount"][1]
    n = world.io.read_u8(count)
    return [world.io.read_u8(count + 1 + i) for i in range(n + 1)]


@pytest.mark.parametrize("title", TITLES)
def test_a_trainer_battle_is_announced_once_with_the_packed_id(title):
    world = ClientWorld(title)
    rival_battle(world)
    world.frames(5)
    assert [m["trainer_id"] for m in world.sent("trainer_battle_start")] == [RIVAL]
    assert Gen2GSCAdapter(title).trainer_info(RIVAL)[1] == "Rival"


def test_the_rival_party_is_replaced_living_first_before_the_send_out():
    world = ClientWorld()
    rival_battle(world)
    acks = swap(world, blob(152, hp=0), blob(155))
    assert acks[-1]["species_ids"] == [155, 152] and "error" not in acks[-1]
    assert ot_party(world) == [155, 152, 0xFF]
    assert swap(world, blob(158))[-1]["error"] == "already_applied"
    assert ot_party(world) == [155, 152, 0xFF]


def test_a_reply_after_the_send_out_is_late_and_moves_nothing():
    world = ClientWorld()
    rival_battle(world)
    set_cur_ot_mon(world, 0)                                         # LoadEnemyMon stored wCurOTMon
    world.frames(1)
    before = len(world.written())
    assert swap(world, blob(155))[-1]["error"] == "late_reply"
    assert len(world.written()) == before


def test_a_parked_reply_is_answered_late_when_the_window_shuts():
    world = ClientWorld()
    rival_battle(world)
    world.checkpoint_ok = False                                      # no writable battle frame yet
    assert swap(world, blob(155)) == []                              # parked
    set_cur_ot_mon(world, 0)
    world.frames(1)
    assert world.sent("rival_team_replaced")[-1]["error"] == "late_reply"
    assert ot_party(world)[0] != 155


@pytest.mark.parametrize("hexes,trainer_id,error", [
    (["zz"], RIVAL, "bad_blob_length"),
    ([blob(155).hex()[:-2]], RIVAL, "bad_blob_length"),
    ([], RIVAL, "bad_blob_count"),
    ([blob(155).hex()], 1 * 256 + 1, "not_in_battle"),               # Falkner is not this battle
])
def test_a_bad_or_foreign_reply_is_answered_at_once(hexes, trainer_id, error):
    world = ClientWorld()
    rival_battle(world)
    before = len(world.written())
    assert swap(world, *hexes, trainer_id=trainer_id)[-1]["error"] == error
    assert len(world.written()) == before


def test_a_link_battle_is_never_announced():
    world = ClientWorld()
    rival_battle(world, link=4)
    world.frames(3)
    assert world.sent("trainer_battle_start") == []
