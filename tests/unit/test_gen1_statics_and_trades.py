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

Both predicates are transcribed from the decomp, and this file re-derives them rather than
trusting the Lua.
"""
from __future__ import annotations

import os
import re

import pytest

lupa = pytest.importorskip("lupa")

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


@pytest.fixture(scope="module")
def game():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("print = function() end")
    path = os.path.join(_REPO, "lua", "games", "gen1_rby.lua").replace("\\", "/")
    return lua.eval(f'dofile("{path}")')


@pytest.fixture(scope="module")
def client_src():
    with open(os.path.join(_REPO, "lua", "clients", "gen1_rby_client.lua"),
              encoding="utf-8") as f:
        return f.read()


# ── statics ──────────────────────────────────────────────────────────────────────────

def test_the_predicate_matches_initbattle(game):
    """InitBattle: `ld a,[wCurOpponent] / and a / jr z, DetermineWildOpponent` — zero means
    roll from the wild table, non-zero means a script set this battle up. InitBattleCommon
    then splits species from trainer at OPP_ID_OFFSET (200)."""
    assert game.is_static_battle(0) is False, "0 is a random encounter, not a static"
    assert game.is_static_battle(143) is True, "Snorlax is a scripted species"
    assert game.is_static_battle(199) is True
    assert game.is_static_battle(200) is False, "200+ is a TRAINER class, not a wild mon"
    assert game.is_static_battle(225) is False
    assert game.is_static_battle(None) is False


def test_the_decomp_still_says_zero_means_random():
    """If InitBattle ever stops branching on wCurOpponent, this predicate is wrong and the
    statics silently start consuming routes again."""
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


def test_two_snorlax_are_two_encounters(game):
    """Route 12 and Route 16 both have one. Keying on species alone would merge them into
    a single event, so catching one would resolve the other."""
    assert game.static_area_id(71, 143) != game.static_area_id(78, 143)


def test_the_same_static_is_one_encounter_for_both_players(game):
    """The other half: two players meeting the same scripted mon on the same map are
    meeting the SAME event, which is what lets them pair."""
    assert game.static_area_id(71, 143) == game.static_area_id(71, 143)
    assert game.static_area_id(71, 143) == "static_71_143"


def test_a_static_is_not_a_gift_area(game):
    """The plan's wording: statics get their own areas under NORMAL rules. Marking them
    gifts would exempt them from the clauses and stop them dead-zoning at all."""
    assert game.is_gift_area(game.static_area_id(71, 143)) is False


def test_the_client_resolves_a_static_to_its_own_area(client_src):
    assert "battle_static_area" in client_src
    assert "local area = battle_static_area or last_area_id" in client_src, (
        "a caught static must land in its own area, or catching Snorlax consumes Route 12")
    assert "local battle_area_id = battle_static_area or battle_area_id" in client_src, (
        "a failed static must dead-zone its own area, not the route's")


# ── in-game trades ───────────────────────────────────────────────────────────────────

def test_the_client_distinguishes_a_trade_from_an_evolution(client_src):
    """Evolution keeps DVs and OT and changes only species — the first nine characters of
    DDDD:TTTT:II are invariant. A trade changes all three."""
    assert "on_npc_trade" in client_src
    assert 'reason = "npc_trade"' in client_src
    m = re.search(r"if prev_inv == cur_inv then\s*\n\s*on_evolution", client_src)
    assert m, "the evolution branch must still require the invariant to match"


def test_a_trade_is_told_apart_from_slink_s_own_writes(client_src):
    """The server writes partner mons into party slots too, and those also carry a foreign
    OT. Without excluding them, a sync would be reported as a trade."""
    assert "sync_written_keys[cur.key]" in client_src
    assert 'cur.key:sub(6, 9) ~= my_ot' in client_src, (
        "a trade is identified by the incoming mon having someone else's OT id")


def test_the_server_migrates_every_structure_on_a_key_change():
    """The half that already existed. If any of these stopped migrating, a traded mon would
    keep its link while its stats, party membership or pending memorial stayed behind."""
    with open(os.path.join(_REPO, "server", "state.py"), encoding="utf-8") as f:
        src = f.read()
    body = src[src.index("def _handle_key_change"):]
    body = body[:body.index("\n    def ", 10)]
    for structure in ("_key_index", "pending_captures", "party_keys", "mon_stats",
                      "bonus_keys", "pending_memorials"):
        assert structure in body, f"{structure} is no longer migrated on a key change"
