"""The Manager must not tell a Gen 1 player that a feature needs a ROM patch it doesn't.

Explode Mode and Rival Swap once sat under a heading that said "These need the companion
ROM patch applied to BOTH players' games". That is true on Gen 3, where gEnemyParty is
encrypted and checksummed, and false on Gen 1, where the enemy party is plaintext at a
fixed address and the move choice is a plain RAM write — both are live-tested that way by
the `rivalswap` and `explode_g1` duo scenarios.

The New-run form now names the game family up front and greys what that family cannot
honour, with the reason on the option. That knowledge is one table, `OPTION_SUPPORT`, read
through `option_support()`; these tests pin that its answers stay accurate.
"""
from __future__ import annotations

import pytest

from server.manager import GAMES, OPTIONS, new_run_form, option_support

GEN1 = ["red", "blue"]
RR = ["firered_rr", "firered_rr"]


@pytest.mark.parametrize("key", ["explode_mode", "rival_team_swap"])
def test_the_no_patch_generations_are_allowed_and_say_so(key):
    """These two work on an unmodified Gen 1 cartridge and the form has to say so."""
    s = option_support(key, GEN1)
    assert s["ok"], s
    assert "no patch" in s["why"].lower(), s


@pytest.mark.parametrize("key", ["overworld_presence", "native_messages",
                                 "battle_calc", "pc_trade_npc"])
def test_the_radical_red_only_features_are_greyed_elsewhere(key):
    """The other half of the same honesty: a Gen 1 player switching these on gets nothing,
    so they cannot be switched on."""
    assert not option_support(key, GEN1)["ok"]
    assert option_support(key, RR)["ok"]


def test_native_sounds_is_a_gen1_red_blue_feature_now():
    """The Red/Blue companion patch plays notifications on the main thread (slink.asm
    SlinkSfxService); the pureRGB overlay does not carry that service yet and says so."""
    assert option_support("native_sounds", GEN1)["ok"]
    assert option_support("native_sounds", RR)["ok"]
    pure = option_support("native_sounds", ["purered", "pureblue"])
    assert not pure["ok"] and "overlay" in pure["why"], pure


def test_the_gender_clause_cannot_be_chosen_on_gen1():
    """Gen 1 has no gender at all, so the clause is not merely unlikely to fire — it
    cannot. Leaving it silently inert is how a player concludes the rules are broken."""
    s = option_support("gender_lock", GEN1)
    assert not s["ok"] and "never fire" in s["why"], s
    assert option_support("gender_lock", RR)["ok"]


def test_a_mixed_pair_takes_the_stricter_answer():
    """A soul link is symmetric: if either cartridge cannot honour an option, the run
    cannot."""
    assert not option_support("battle_calc", ["firered_rr", "red"])["ok"]


def test_an_unnamed_game_forbids_nothing():
    """Detect-on-connect: nothing is known to be impossible yet."""
    assert all(option_support(k, [""])["ok"] for k in OPTIONS)


def test_the_form_table_covers_every_family_and_option():
    form = new_run_form()
    assert set(form["support"]) == {k for k, _, _ in GAMES}
    for family in form["support"].values():
        assert set(family) == set(OPTIONS)
        assert all({"ok", "why"} <= set(v) for v in family.values())
