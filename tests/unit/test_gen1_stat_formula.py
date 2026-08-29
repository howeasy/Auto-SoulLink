"""Gen 1's stat formula, cross-checked over ground the fixtures cannot reach.

lua/tests/test_gen1_stat_rebuild.lua is the authoritative check: it recomputes every party
mon's stats and requires the GAME's own stored values to match, which is real ground truth.
But every committed fixture holds a single level-5 mon with ZERO stat exp, so that gate
exercises neither the ceil(sqrt(statexp)) term nor level scaling. Passing it says less than
it looks like it says, and this file exists to say so and to cover the rest.

WHAT THIS IS AND IS NOT. The Python below is an INDEPENDENT transcription of CalcStat
(home/move_mon.asm) compared against the Lua implementation over levels 1-100, all DV
combinations and stat exp across its whole range. That catches arithmetic mistakes --
rounding, the /4 truncation, the integer ceil-sqrt, the HP-vs-other branch, the 999 cap.
It CANNOT catch a misreading of the assembly shared by both, which is why the live gate
remains the primary control rather than this.
"""
from __future__ import annotations

import math
import os
import random

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the Gen 1 game module")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FIELDS = ("hp", "attack", "defense", "speed", "special")


@pytest.fixture(scope="module")
def game():
    """Load lua/games/gen1_rby.lua with just enough of BizHawk to satisfy it."""
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = rt.globals()
    g.memory = rt.table_from({
        "getmemorydomainlist": lambda: rt.table_from([]),
        "read_u8": lambda *_a: None,
    })
    g.console = rt.table_from({"log": lambda *_a: None})
    g.SLINK_ROOT = _REPO
    with open(os.path.join(_REPO, "lua", "games", "gen1_rby.lua"), encoding="utf-8") as f:
        module = rt.execute(f.read())
    # The runtime travels with the module: lupa refuses to mix objects across runtimes, so
    # every table handed to Lua has to be built by THIS one.
    return rt, module


# ── an independent transcription of CalcStat ─────────────────────────────────────────────
def _ceil_sqrt(n: int) -> int:
    """The engine's loop: smallest b >= 1 with b*b >= n, capped at 255.

    Written with math.isqrt rather than the Lua's float sqrt plus correction, so the two
    agree only if both are right.
    """
    if n <= 0:
        return 1
    b = math.isqrt(n)
    if b * b < n:
        b += 1
    return min(max(b, 1), 255)


def _ivs(dv_word: int) -> dict[str, int]:
    hi, lo = (dv_word >> 8) & 0xFF, dv_word & 0xFF
    atk, dfn = hi >> 4, hi & 0xF
    spd, spc = lo >> 4, lo & 0xF
    return {"attack": atk, "defense": dfn, "speed": spd, "special": spc,
            "hp": ((atk & 1) << 3) | ((dfn & 1) << 2) | ((spd & 1) << 1) | (spc & 1)}


def calc_stats(base: dict[str, int], level: int, dv_word: int,
               stat_exp: dict[str, int]) -> dict[str, int]:
    ivs = _ivs(dv_word)
    out = {}
    for f in FIELDS:
        core = ((base[f] + ivs[f]) * 2 + _ceil_sqrt(stat_exp.get(f, 0)) // 4) * level
        stat = core // 100
        stat += (level + 10) if f == "hp" else 5
        out[f] = min(stat, 999)
    return out


def _lua_calc(game, base, level, dv, exp):
    rt, module = game
    got = module.calcStats(rt.table_from(base), level, dv, rt.table_from(exp))
    return {f: got[f] for f in FIELDS}


# ── the cross-check ──────────────────────────────────────────────────────────────────────
def test_the_dv_split_matches(game):
    """byte0 = (Atk<<4)|Def, byte1 = (Spd<<4)|Spc, and HP is built from their low bits."""
    for dv in (0x0000, 0xFFFF, 0x9999, 0x1234, 0xABCD):
        got = game[1].splitDVs(dv)
        want = _ivs(dv)
        assert {f: got[f] for f in FIELDS} == want, f"dv=0x{dv:04X}"


def test_hp_iv_is_assembled_from_the_other_four(game):
    """Gen 1 does not store an HP IV; CalcStat builds it from four low bits."""
    assert game[1].splitDVs(0xFFFF)["hp"] == 15
    assert game[1].splitDVs(0x0000)["hp"] == 0
    # Atk=1 (odd) only -> bit 3 set.
    assert game[1].splitDVs(0x1000)["hp"] == 8


@pytest.mark.parametrize("level", [1, 2, 5, 25, 50, 75, 99, 100])
def test_levels_the_fixtures_never_reach(game, level):
    base = {"hp": 45, "attack": 49, "defense": 49, "speed": 45, "special": 65}
    exp = dict.fromkeys(FIELDS, 0)
    assert _lua_calc(game, base, level, 0x9999, exp) == calc_stats(base, level, 0x9999, exp)


@pytest.mark.parametrize("value", [0, 1, 2, 3, 15, 16, 17, 255, 256, 257,
                                   65024, 65025, 65535])
def test_the_stat_exp_term_including_its_boundaries(game, value):
    """The term is floor(ceil(sqrt(exp)) / 4), so perfect squares and the 255 cap are where
    an off-by-one hides. 65025 is 255^2; 65535 is the maximum a stat-exp word can hold."""
    base = {"hp": 100, "attack": 100, "defense": 100, "speed": 100, "special": 100}
    exp = dict.fromkeys(FIELDS, value)
    assert _lua_calc(game, base, 50, 0xFFFF, exp) == calc_stats(base, 50, 0xFFFF, exp)


def test_the_999_cap_is_unreachable_with_legal_inputs(game):
    """MAX_STAT_VALUE is dead code for any real Pokemon, and this pins that.

    Maxing everything the game can store -- base stat 255, DV 15, stat exp 65535, level
    100 -- yields 608 for a normal stat and 713 for HP, both well under 999. The clamp is
    kept because the engine has it and matching the engine is the whole contract, but a
    test that claimed to exercise it would be claiming something false.
    """
    base = dict.fromkeys(FIELDS, 255)
    exp = dict.fromkeys(FIELDS, 65535)
    got = _lua_calc(game, base, 100, 0xFFFF, exp)
    assert got == calc_stats(base, 100, 0xFFFF, exp)
    assert got["attack"] == 608 and got["hp"] == 713, got
    assert max(got.values()) < 999


def test_a_broad_random_sample(game):
    """Deterministic seed: a flake here would be a real disagreement, not noise."""
    rng = random.Random(20260823)
    for _ in range(300):
        base = {f: rng.randint(1, 255) for f in FIELDS}
        exp = {f: rng.randint(0, 65535) for f in FIELDS}
        level = rng.randint(1, 100)
        dv = rng.randint(0, 0xFFFF)
        assert _lua_calc(game, base, level, dv, exp) == calc_stats(base, level, dv, exp), (
            f"base={base} level={level} dv=0x{dv:04X} exp={exp}")


@pytest.mark.parametrize("level", [0, 101, -1])
def test_an_impossible_level_is_refused_rather_than_computed(game, level):
    base = dict.fromkeys(FIELDS, 50)
    rt, module = game
    assert module.calcStats(rt.table_from(base), level, 0, None) is None


def test_the_stat_exp_term_only_shows_up_where_the_division_lets_it(game):
    """floor(ceil(sqrt(exp)) / 4) is added INSIDE a product that is then divided by 100,
    so small amounts of stat exp are invisible at low levels.

    At level 50 a term of +1 adds 50 to a numerator that then floors by 100 -- no change.
    At level 100 the same +1 adds 100 and moves the stat by exactly one. Pinning both stops
    a future reader "fixing" the rounding to make low-level stat exp visible.
    """
    base = dict.fromkeys(FIELDS, 50)
    zero50 = _lua_calc(game, base, 50, 0x0000, dict.fromkeys(FIELDS, 0))
    assert _lua_calc(game, base, 50, 0x0000, dict.fromkeys(FIELDS, 16)) == zero50

    zero100 = _lua_calc(game, base, 100, 0x0000, dict.fromkeys(FIELDS, 0))
    got100 = _lua_calc(game, base, 100, 0x0000, dict.fromkeys(FIELDS, 16))
    assert got100["attack"] == zero100["attack"] + 1, (got100, zero100)
