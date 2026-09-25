"""Two ruleset decisions, made explicit.

**A static does not consume its route's encounter.** Snorlax stands on Route 12, but it is
not what Route 12 offers: it is a fixed, one-off battle that happens to be there. Failing to
catch it used to dead-zone the route, spending its only encounter on a mon the wild table
never rolls. Statics now resolve their own area and are played under the ordinary rules
there — fail one and THAT is dead-zoned; catch it and that pairs.

**An in-game trade migrates the link.** A vanilla trade removes one of your mons and gives
you another. If the outgoing mon was half a pair, the pair follows the player rather than
being orphaned while the incoming mon is read as a fresh wild catch — which would also have
consumed the route's encounter.

P8-2b: the client-side halves are now proved behaviourally against the rewritten client by
tests/unit/test_gen1_client.py — `test_static_encounter_gets_its_own_area_id_not_the_map`
(a failed Snorlax dead-zones `static_23_143`, not the route) and
`test_enemy_party_build_and_npc_trade_do_not_look_like_captures` (the npc_trade signal owns
the change and it becomes a key_change with reason "npc_trade", never a capture). What is
left here is the pair of claims about the DECOMP that no behavioural test can make, and the
server-side migration those two rules both lean on.
"""
from __future__ import annotations

import os
import re

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _find_pret(name="pokered"):
    d = _REPO
    for _ in range(6):
        cand = os.path.join(d, ".cache", "pret", name)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(_REPO, ".cache", "pret", name)


# ── statics ──────────────────────────────────────────────────────────────────────────

def test_the_decomp_still_says_zero_means_random():
    """`ld a,[wCurOpponent] / and a / jr z, DetermineWildOpponent` — zero means roll from the
    wild table, non-zero means a script set this battle up. If InitBattle ever stops
    branching on wCurOpponent, the client's `pt.cur_opponent < 200` wild test is wrong and
    the statics silently start consuming routes again."""
    path = os.path.join(_find_pret(), "engine", "battle", "core.asm")
    if not os.path.exists(path):
        pytest.skip("pokered not cloned — run tools/build_pret_syms.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"InitBattle::\s*\n\s*ld a, \[wCurOpponent\]\s*\n\s*and a\s*\n\s*"
                  r"jr z, DetermineWildOpponent", src)
    assert m, "InitBattle no longer dispatches on wCurOpponent"


def test_the_field_is_cleared_at_battle_end():
    """Otherwise a static would poison the NEXT random encounter on the same route."""
    path = os.path.join(_find_pret(), "engine", "battle", "end_of_battle.asm")
    if not os.path.exists(path):
        pytest.skip("pokered not cloned")
    with open(path, encoding="utf-8") as f:
        assert "ld [wCurOpponent], a" in f.read()
