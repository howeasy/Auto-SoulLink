"""The Manager must not tell a Gen 1 player that a feature needs a ROM patch it doesn't.

Explode Mode and Rival Swap sat under a heading that said "These need the companion ROM
patch applied to BOTH players' games", with a "Get patch" link beside them. That is true on
Gen 3, where gEnemyParty is encrypted and checksummed, and false on Gen 1, where the enemy
party is plaintext at a fixed address and the move choice is a plain RAM write — both are
live-tested that way by the `rivalswap` and `explode_g1` duo scenarios.

A player reading that would either apply a patch they did not need or, worse, conclude the
feature was unavailable to them.

There is deliberately no run-creation game picker to gate on: the generation is only known
when a client connects. So the fix is accurate labelling rather than invented gating, and
what these tests pin is that the labels stay accurate.
"""
from __future__ import annotations

import os
import re

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


@pytest.fixture(scope="module")
def html():
    with open(os.path.join(_REPO, "server", "templates", "manager.html"), encoding="utf-8") as f:
        return f.read()


def _tip_for(html: str, model: str) -> str:
    """The data-tip on the label wrapping a given x-model checkbox."""
    m = re.search(r'<label data-tip="([^"]*)"[^>]*>\s*<input[^>]*x-model="newOpts\.'
                  + re.escape(model) + r'"', html, re.S)
    assert m, f"no labelled checkbox found for {model}"
    return m.group(1)


def test_the_section_no_longer_claims_a_patch_is_always_required(html):
    assert 'data-tip="These need the companion ROM patch applied to BOTH players\' games."' \
        not in html, "the blanket ROM-patch claim is back; it is false on Gen 1"


@pytest.mark.parametrize("model", ["explode_mode", "rival_team_swap"])
def test_the_no_patch_generations_are_named(html, model):
    """These two work on an unmodified Gen 1 cartridge and the UI has to say so."""
    tip = _tip_for(html, model)
    assert "Gen 1" in tip and "no patch" in tip.lower(), tip


@pytest.mark.parametrize("model", ["overworld_presence", "native_messages", "native_sounds",
                                   "battle_calc", "pc_trade_npc"])
def test_the_gen3_only_features_say_so(html, model):
    """The other half of the same honesty: these genuinely are Gen 3 only, and a Gen 1
    player switching them on gets nothing."""
    assert "Gen 3 only" in _tip_for(html, model), _tip_for(html, model)


def test_the_gender_clause_warns_it_cannot_fire_on_gen1(html):
    """Gen 1 has no gender at all, so the clause is not merely unlikely to fire — it
    cannot. Leaving it silently inert is how a player concludes the rules are broken."""
    tip = _tip_for(html, "gender_lock")
    assert "Gen 1" in tip and "never fire" in tip, tip


def test_the_sound_option_explains_why_gen1_has_none(html):
    """Not just 'unsupported': the reason is a measured property of the audio engine, and
    someone will ask."""
    assert "re-enters a non-reentrant" in _tip_for(html, "native_sounds")
