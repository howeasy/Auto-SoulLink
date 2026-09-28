"""lua/gen3/client.lua: the three death banners name a mon, never a PID:OTID.

Several server death paths can send `nickname: <nick> or ""` (server/state.py),
and a decoded record may have an empty or space-only nickname. Lua treats "" as
truthy, so a blank command nickname could mask the record's valid name and blank
the banner. The first non-blank candidate now wins; a nameless mon gets generic
text. The raw-key arm was unreachable for a valid decoded mon.

Driven through the PRODUCTION lua/gen3/entry.lua build by tests/unit/gen3_world.py: each case
lands a real force_faint / force_explode and reads the banner off the injected hud seam, so
this is the client's behaviour rather than its source text.
"""
from __future__ import annotations

import pytest

from tests.unit.gen3_world import World, key_of, mon_record

OT = 0x0000ABCD
A, B = 0x11111111, 0x22222222
KA, KB = key_of(A, OT), key_of(B, OT)
FOE = mon_record(0x77777777, 0x1234, species=19, level=3)

NO_NAME = "Your Pokemon"          # what the banner says when no name is available
PARTY_HP_OFF = 0x56               # struct Pokemon.hp (pret/pokefirered include/pokemon.h)
BATTLER_HP, BATTLER_PP = 0x28, 0x24   # struct BattlePokemon.hp / moves[0].pp


def live(own, frames=60, target="a"):
    """A connected client past its first validation, both halves alive.

    `own` names the half each case kills; the other half has a distinct name.
    """
    w = World()
    w.set_party([mon_record(A, OT, species=4, nickname=own if target == "a" else "ANCHOR"),
                 mon_record(B, OT, species=5, nickname=own if target == "b" else "BOLT")])
    w.step_to(frames)
    assert w.client.writes_enabled is True
    return w


def banners(w, mark):
    return [h for h in w.hud if h[0] == "show" and mark in h[1]]


def bench_ko(w, nickname):
    """force_faint on the BENCH half: the plan lands immediately and the " KO'd" banner fires."""
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    cmd = {"cmd": "force_faint", "key": KB}
    if nickname is not None:
        cmd["nickname"] = nickname
    w.command(**cmd)
    w.step()
    assert w.party_hp(1) == 0 and w.party_hp(0) == 20, "the HP write landed on the keyed mon only"
    return w


def perish_ko(w, nickname):
    """force_faint on the ACTIVE half: the Perish commit, then the ENGINE's own KO is the
    " fainted" banner (pret battle_script_commands.c:1861 zeroes gBattleMons AND the party)."""
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    cmd = {"cmd": "force_faint", "key": KA}
    if nickname is not None:
        cmd["nickname"] = nickname
    w.command(**cmd)
    w.step(30)                                       # ticks see the battler alive meanwhile
    w.poke_int(w.ram["BATTLE_MONS_ADDR"] + BATTLER_HP, 0, 2)
    w.poke_int(w.party_base() + PARTY_HP_OFF, 0, 2)
    w.fire("faint")
    w.step()
    assert w.client.battle_pending_count(w.client) == 0
    return w


def explode_ko(w, nickname):
    """force_explode whose Explosion lands: PP dropped (it ran) and the user at 0 HP is BOOM!."""
    w.battle_ok = True
    w.enter_battle([FOE], active=(0,))
    w.poke_int(w.ram["BATTLE_MONS_ADDR"] + BATTLER_HP, 20, 2)
    cmd = {"cmd": "force_explode", "key": KA}
    if nickname is not None:
        cmd["nickname"] = nickname
    w.command(**cmd)
    w.step(1)                                        # the menu skip commits (comm = STANDBY)
    w.step(30)                                       # ticks see the battler alive meanwhile
    w.poke_int(w.ram["BATTLE_MONS_ADDR"] + BATTLER_PP, 4, 1)     # Explosion's PP dropped
    w.poke_int(w.ram["BATTLE_MONS_ADDR"] + BATTLER_HP, 0, 2)     # the user fainted
    w.step()
    assert w.client.battle_pending_count(w.client) == 0
    return w


# ── "!! <name> KO'd": a bench half ──────────────────────────────────────────────────────

@pytest.mark.parametrize(("wire", "own", "expected"), [
    ("SPARKY", "BOLT", "!! SPARKY KO'd"),      # the server's name for this command wins
    ("", "BOLT", "!! BOLT KO'd"),              # "" is truthy in Lua: it used to blank the banner
    ("   ", "BOLT", "!! BOLT KO'd"),           # and a blank name hid the record's own
    (None, "BOLT", "!! BOLT KO'd"),            # an absent field already fell through
    ("", "", f"!! {NO_NAME} KO'd"),            # nothing to name it by: say so, print no key
    (None, "", f"!! {NO_NAME} KO'd"),
])
def test_the_ko_banner_names_the_mon_or_says_it_has_no_name(wire, own, expected):
    w = bench_ko(live(own, target="b"), wire)
    [row] = banners(w, "KO'd")
    assert row[1] == expected
    assert row[2:] == (255, 80, 80, 360), "the alarm colour and dwell are unchanged"
    assert KA not in row[1] and KB not in row[1] and KA[:8] not in row[1]


# ── "!! <name> fainted": the engine's Perish KO of the active half ──────────────────────

@pytest.mark.parametrize(("wire", "own", "expected"), [
    ("SPARKY", "BOLT", "!! SPARKY fainted"),
    ("", "BOLT", "!! BOLT fainted"),
    ("   ", "BOLT", "!! BOLT fainted"),
    (None, "BOLT", "!! BOLT fainted"),
    ("", "", f"!! {NO_NAME} fainted"),
    (None, "", f"!! {NO_NAME} fainted"),
])
def test_the_fainted_banner_names_the_mon_or_says_it_has_no_name(wire, own, expected):
    w = perish_ko(live(own), wire)
    [row] = banners(w, "fainted")
    assert row[1] == expected
    assert row[2:] == (255, 80, 80, 360)
    assert KA not in row[1] and KB not in row[1] and KA[:8] not in row[1]


# ── "!! <name> BOOM!": Explode Mode's landed Explosion ─────────────────────────────────

@pytest.mark.parametrize(("wire", "own", "expected"), [
    ("SPARKY", "BOLT", "!! BOLT BOOM!"),        # this site never read the command's name, and
    ("", "BOLT", "!! BOLT BOOM!"),              # still does not: the record is its only source
    (None, "BOLT", "!! BOLT BOOM!"),
    ("", "", f"!! {NO_NAME} BOOM!"),
    (None, "", f"!! {NO_NAME} BOOM!"),
])
def test_the_boom_banner_names_the_mon_or_says_it_has_no_name(wire, own, expected):
    w = explode_ko(live(own), wire)
    [row] = banners(w, "BOOM!")
    assert row[1] == expected
    assert row[2:] == (255, 80, 80, 360)
    assert KA not in row[1] and KB not in row[1] and KA[:8] not in row[1]


# ── the key stays where it belongs ─────────────────────────────────────────────────────

def test_a_nameless_banner_and_the_full_key_reach_different_audiences():
    """The banner is the only place a name is dropped. The protocol and the log keep the
    PID:OTID the whole client identifies the mon by, and the engine's faint is still the
    engine's (the Perish commit marked it commanded)."""
    w = perish_ko(live(""), "")
    [row] = banners(w, "fainted")
    assert row[1] == f"!! {NO_NAME} fainted"
    assert w.events("faint") == [], "the commanded engine faint is not echoed"
    assert any("force_faint: Perish commit" in line and line.endswith(KA) for line in w.logs), w.logs
