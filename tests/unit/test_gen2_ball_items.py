"""Which item IDs count as a Poké Ball in Gen 2?

`hasPokeballs()` is the Nuzlocke gate: until it returns true, SLink enforces no rule at all.
It walks the Balls pocket and matches each entry against the profile's `ball_item_ids`.

Every Gen 2 profile listed the Apricorn balls at 0xA9-0xAF. Those IDs are SUN_STONE,
POLKADOT_BOW, ITEM_AB, UP_GRADE, BERRY, GOLD_BERRY and SQUIRTBOTTLE; the real Apricorn balls
are 0x9D/0x9F/0xA0/0xA1/0xA4/0xA5/0xA6, and Park Ball is 0xB1 rather than 0xB2.

That could not produce a FALSE POSITIVE — the Balls pocket only ever holds balls — so it
produced silence instead: a player carrying only balls Kurt made read as carrying none, the
gate never opened, and no Soul Link rule was enforced for the rest of the run. Nothing in the
suite would have gone red.

TWO CHECKS, ON PURPOSE. `test_ball_ids_are_exactly_the_ball_pocket` is the real oracle and
derives the answer from pret, but pret is a gitignored cache, so it skips on a clean clone.
`test_the_wrong_apricorn_block_is_gone` needs nothing and pins this specific regression, so
the bug cannot come back unnoticed on a machine without the cache.
"""
import os
import re

import pytest

lupa = pytest.importorskip("lupa")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRET = os.path.join(REPO, ".cache", "pret")

# What the profiles used to say, and what those IDs really are. Named so a failure message
# explains itself rather than just printing two hex sets.
WRONG_IDS = {0xA9: "SUN_STONE", 0xAA: "POLKADOT_BOW", 0xAB: "ITEM_AB", 0xAC: "UP_GRADE",
             0xAD: "BERRY", 0xAE: "GOLD_BERRY", 0xAF: "SQUIRTBOTTLE", 0xB2: "not PARK_BALL"}


def _profiles():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("print = function() end")
    path = os.path.join(REPO, "lua", "games", "gen2_crystal.lua").replace("\\", "/")
    return lua.eval(f'dofile("{path}")').PROFILES


def _profile_ball_ids():
    out = {}
    for name, prof in _profiles().items():
        ids = prof.ball_item_ids
        assert ids, f"profile {name} declares no ball_item_ids"
        out[name] = {int(v) for v in dict(ids).values()}
    return out


def _ball_pocket_from_pret(repo):
    """The item IDs pret files in the BALL pocket — the game's own answer.

    attributes.asm row N describes item N+1: the table opens at MASTER_BALL, not at NO_ITEM.
    Getting that off by one is what makes a naive parse claim BRIGHTPOWDER is a ball.
    """
    names, val = [], None
    with open(os.path.join(repo, "constants", "item_constants.asm"), encoding="utf-8") as f:
        for ln in f:
            if re.match(r"\s*const_def\s*$", ln):
                val = 0
                continue
            m = re.match(r"\s*const_def\s+\$?([0-9A-Fa-f]+)", ln)
            if m:
                val = int(m.group(1), 16)
                continue
            m = re.match(r"\s*const\s+([A-Z_0-9]+)", ln)
            if m and val is not None:
                names.append((val, m.group(1)))
                val += 1

    with open(os.path.join(repo, "data", "items", "attributes.asm"), encoding="utf-8") as f:
        rows = re.findall(r"item_attribute\s+([^\n;]+)", f.read())
    assert len(rows) >= 250, f"attributes.asm parsed to {len(rows)} rows — format changed?"

    # Row i -> item id i+1. Guard the shift with a known anchor rather than trusting it.
    by_id = {i + 1: r for i, r in enumerate(rows)}
    id_to_name = dict(names)
    pocket = {i for i, r in by_id.items() if r.split(",")[4].strip() == "BALL"}
    assert id_to_name.get(0x05) == "POKE_BALL" and 0x05 in pocket, (
        "the row->id shift is wrong: 0x05 should be POKE_BALL and in the BALL pocket")
    assert 0xA3 not in pocket, (
        "LIGHT_BALL (0xA3) came out in the BALL pocket — the shift is off by one again")
    return pocket


@pytest.mark.parametrize("game", ("pokecrystal", "pokegold"))
def test_ball_ids_are_exactly_the_ball_pocket(game):
    """The profiles must agree with the game, in both directions.

    A missing ID silently disables the Nuzlocke gate; an extra one arms it on something that
    is not a ball. Neither is visible from the UI.
    """
    repo = os.path.join(PRET, game)
    if not os.path.isdir(repo):
        pytest.skip(f"{game} not cloned — run tools/build_pret_syms.py")
    expected = _ball_pocket_from_pret(repo)
    for name, ids in _profile_ball_ids().items():
        assert ids == expected, (
            f"profile {name}: missing {sorted(hex(i) for i in expected - ids)}, "
            f"extra {sorted(hex(i) for i in ids - expected)} "
            f"(vs {game}'s BALL pocket)")


def test_the_wrong_apricorn_block_is_gone():
    """No pret needed. The exact IDs that were wrong, and why each is not a ball."""
    for name, ids in _profile_ball_ids().items():
        bad = sorted(ids & set(WRONG_IDS))
        assert not bad, (
            f"profile {name} lists non-ball items as balls: "
            + ", ".join(f"{i:#04x} ({WRONG_IDS[i]})" for i in bad))


def test_the_real_apricorn_balls_are_present():
    """The other half: dropping the block entirely would pass the test above."""
    required = {0x05: "POKE_BALL", 0x9D: "HEAVY_BALL", 0xA1: "FAST_BALL", 0xB1: "PARK_BALL"}
    for name, ids in _profile_ball_ids().items():
        missing = sorted(set(required) - ids)
        assert not missing, (
            f"profile {name} does not recognise "
            + ", ".join(f"{i:#04x} ({required[i]})" for i in missing)
            + " — a player holding only these reads as having no balls, so the Nuzlocke "
              "gate never opens")


def test_light_ball_is_not_a_ball():
    """The one entry a name-based list gets wrong: LIGHT_BALL is Pikachu's held item."""
    for name, ids in _profile_ball_ids().items():
        assert 0xA3 not in ids, f"profile {name} treats LIGHT_BALL (0xA3) as a Poké Ball"
