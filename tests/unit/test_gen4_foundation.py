"""Gen 4 pairing foundations: the registry rows G3a added (docs/gen4/PLAN.md §4.5).

BEFORE this registry change `_ROM_TYPE_TO_FOUNDATION` had NO Gen 4 rows at all, and
`foundation_for_rom_type` fell back to the game_id -- so `heartgold`, `soulsilver`,
`heartgold_hge`, `platinum`, `hgss` and `renegade_platinum` ALL derived the foundation
`gen4_hgsspt` and any two of them paired. The rows below make the foundation the LAYOUT
(`gen4_hgss` for HG/SS, `gen4_hge` for the hg-engine fork) and make Platinum unrouted.

Foundation equality is the pairing lock (`_mixed_games_error`, server/server.py). Two
consequences are deliberately NOT settled here and belong to a later card (PLAN §4.5 row 2):

  * HG↔HG and SS↔SS still share `gen4_hgss`, so same-title pairs are still admitted by
    the foundation lock. Only the exact-title relation HG↔SS / hge↔hge will refuse them.
  * Nothing here makes the retired Platinum spellings safe to route: they have no runtime,
    so they are deleted rather than refused (see the two RED sections below).
"""
from __future__ import annotations

import os

import pytest

from server.adapters import (
    _ROM_TYPE_TO_FOUNDATION,
    _ROM_TYPE_TO_GAME_ID,
    adapter_class_for_rom_type,
    foundation_for_rom_type,
    game_id_for_rom_type,
    unrouted_rom_type_reason,
    variant_label,
)

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# The three Gen 4 rom_types the clients send, and what each must resolve to. `game_id` is
# the ADAPTER (one class serves all Gen 4); `foundation` is the pack/layout that pairs.
GEN4 = {
    "heartgold": ("gen4_hgsspt", "gen4_hgss"),
    "soulsilver": ("gen4_hgsspt", "gen4_hgss"),
    "heartgold_hge": ("gen4_hgsspt", "gen4_hge"),
}

# Retired spellings. Platinum is bind-only data (data/games/gen4_pt/profile.json,
# `titles.platinum.admission: BIND_ONLY_NOT_ADMITTED`, `profile.memorial_box: null`,
# `sites: {}`) and there is no Renegade Platinum runtime, so routing either would admit a
# pair the adapter cannot serve.
RETIRED_GEN4 = ("platinum", "hgss", "renegade_platinum")


# ── the rows themselves ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rom_type", sorted(GEN4))
def test_every_gen4_rom_type_routes_to_its_game_id_and_its_foundation(rom_type):
    game_id, foundation = GEN4[rom_type]
    assert game_id_for_rom_type(rom_type) == game_id
    assert foundation_for_rom_type(rom_type) == foundation
    assert adapter_class_for_rom_type(rom_type) is not None


def test_hgss_shares_one_foundations_and_hge_has_its_own():
    """HG and SS are the same Johto/Kanto pack; hg-engine is a different save layout."""
    assert foundation_for_rom_type("heartgold") == foundation_for_rom_type("soulsilver")
    assert foundation_for_rom_type("heartgold") == "gen4_hgss"
    assert foundation_for_rom_type("heartgold_hge") == "gen4_hge"
    assert foundation_for_rom_type("heartgold") != foundation_for_rom_type("heartgold_hge")


def test_heartgold_hge_routes_instead_of_being_refused():
    """The OPEN this card closed: hge had no `_ROM_TYPE_TO_GAME_ID` row, so it derived
    None and `protocol_schema.validate_event` refused its hello as 'not one the server
    routes' (tests/unit/protocol_schema.py:254-256)."""
    assert game_id_for_rom_type("heartgold_hge") == "gen4_hgsspt"
    assert foundation_for_rom_type("heartgold_hge") == "gen4_hge"
    assert variant_label("heartgold_hge") == "HeartGold (hg-engine)"


def test_one_game_id_serves_gen4_but_the_foundations_still_separate_the_layouts():
    """The Gen 3 invariant, restated for Gen 4: same adapter class, different foundations."""
    classes = {adapter_class_for_rom_type(rt) for rt in GEN4}
    assert len(classes) == 1 and classes.pop() is not None
    assert {foundation_for_rom_type(rt) for rt in GEN4} == {"gen4_hgss", "gen4_hge"}


# ── the retired spellings ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rom_type", RETIRED_GEN4)
def test_the_retired_gen4_spellings_do_not_route(rom_type):
    """Deleting the row is what refuses the hello: `server.py:1716` rejects any rom_type
    `game_id_for_rom_type` answers None for, with this reason."""
    assert rom_type not in _ROM_TYPE_TO_GAME_ID
    assert rom_type not in _ROM_TYPE_TO_FOUNDATION
    assert game_id_for_rom_type(rom_type) is None
    assert foundation_for_rom_type(rom_type) is None
    assert adapter_class_for_rom_type(rom_type) is None
    assert unrouted_rom_type_reason(rom_type) == "not a game this server routes"


def test_platinum_can_no_longer_reach_heartgold_through_the_adapter():
    """The pairing lock compares derived foundations, so an unrouted Platinum can never
    reach it -- not as the game_id fallback (`gen4_hgsspt`) HG used to derive, and not by
    name-matching either. Before this card HG and Platinum derived the SAME string."""
    assert foundation_for_rom_type("heartgold") == "gen4_hgss"
    assert foundation_for_rom_type("platinum") != foundation_for_rom_type("heartgold")


# ── the silent-fallback hazard (the reason the Gen 4 rows exist) ────────────────────────────────

def test_no_gen4_rom_type_rides_the_game_id_fallback():
    """`foundation_for_rom_type` answers `_ROM_TYPE_TO_FOUNDATION.get(rom_type, game_id)`,
    so a missing row is SILENT and wrong the moment a generation shares one game_id across
    layouts. Gen 4 is that generation, so every Gen 4 rom_type must carry an explicit row;
    this fails for a future Gen 4 title added to `_ROM_TYPE_TO_GAME_ID` without one."""
    gen4 = {rt: gid for rt, gid in _ROM_TYPE_TO_GAME_ID.items() if gid.startswith("gen4")}
    assert gen4 == {rt: gid for rt, (gid, _) in GEN4.items()}
    missing = sorted(rt for rt in gen4 if rt not in _ROM_TYPE_TO_FOUNDATION)
    assert not missing, f"these Gen 4 rom_types would silently derive {gen4[missing[0]]}: {missing}"


def test_the_rom_types_that_still_ride_the_game_id_fallback_are_exactly_gen1_and_gen5():
    """The fallback cannot be removed while this set is non-empty, and it cannot be left
    silently for a new rom_type either. Pinning the set makes either change loud.

    Gen 1 and Gen 5 are safe on the fallback because their game_id IS their layout
    (gen1_rby vs gen1_purergb are separate packs; Gen 5 has one pack and one layout)."""
    fallback = sorted(rt for rt in _ROM_TYPE_TO_GAME_ID if rt not in _ROM_TYPE_TO_FOUNDATION)
    assert fallback == sorted([
        "Red", "Blue", "Yellow", "red", "blue", "yellow", "red_ap", "blue_ap",
        "PureRed", "PureBlue", "PureGreen", "purered", "pureblue", "puregreen",
        "pokemon_black", "pokemon_white", "pokemon_black_2", "pokemon_white_2",
        "polished_crystal",  # one Polished pack and one layout: its game_id IS its layout (gen2_polished)
    ])


@pytest.mark.parametrize("rom_type", sorted(GEN4))
def test_every_gen4_foundation_names_a_pack_on_disk(rom_type):
    """A foundation is a data pack, not an id: `gen4_hgsspt` is the adapter and has no
    profile.json, so a foundation that resolved to it would be unpinned by this check."""
    foundation = foundation_for_rom_type(rom_type)
    assert foundation != game_id_for_rom_type(rom_type), "the fallback answered; add a row"
    profile = os.path.join(_REPO, "data", "games", foundation, "profile.json")
    assert os.path.isfile(profile), f"{foundation} has no data pack profile: {profile}"


# ── RED controls: the assertions above are load-bearing ─────────────────────────────────────────

@pytest.mark.parametrize("rom_type", RETIRED_GEN4)
def test_readmitting_a_retired_gen4_spelling_would_restore_routing(monkeypatch, rom_type):
    """Re-add the row exactly as it was before this card and routing comes back -- so the
    retirement assertions above would go red, not quietly keep passing."""
    monkeypatch.setitem(_ROM_TYPE_TO_GAME_ID, rom_type, "gen4_hgsspt")
    assert game_id_for_rom_type(rom_type) == "gen4_hgsspt"
    # No foundation row exists for it, so the game_id fallback answers with the ADAPTER id
    # -- a string no pack is named after.
    # ...and that one answer is not a pack at all (data/games/gen4_hgsspt/ carries no
    # profile.json -- the adapter id is never a foundation). Two readmitted spellings would
    # then derive the same foundation and the pairing lock would ADMIT the pair, where
    # Platinum's pack has a null memorial_box and no sites and fails at the first
    # PC/memorial write instead of at the door. Hence delete the rows, do not refuse them.
    assert foundation_for_rom_type(rom_type) == "gen4_hgsspt"
    gen4 = {rt for rt, gid in _ROM_TYPE_TO_GAME_ID.items() if gid.startswith("gen4")}
    assert sorted(rt for rt in gen4 if rt not in _ROM_TYPE_TO_FOUNDATION) == [rom_type], \
        "the no-Gen-4-fallback invariant above is load-bearing"


def test_readmitting_both_platinum_aliases_would_make_them_pairable(monkeypatch):
    """The concrete harm of the fallback, shown by mutation: with both rows back, Pt and RP
    derive one foundation and the lock cannot tell them apart."""
    for rom_type in ("platinum", "renegade_platinum"):
        monkeypatch.setitem(_ROM_TYPE_TO_GAME_ID, rom_type, "gen4_hgsspt")
    assert foundation_for_rom_type("platinum") == foundation_for_rom_type("renegade_platinum")
    # ...while HG keeps its own foundation, so the pair that must never form still cannot.
    assert foundation_for_rom_type("platinum") != foundation_for_rom_type("heartgold")


def test_dropping_the_gen4_foundation_rows_would_make_every_gen4_title_pairable(monkeypatch):
    """The other direction: without the rows, the game_id fallback collapses HG, SS and hge
    onto `gen4_hgsspt` and the lock admits every Gen 4 combination."""
    for rom_type in GEN4:
        monkeypatch.delitem(_ROM_TYPE_TO_FOUNDATION, rom_type)
    derived = {foundation_for_rom_type(rt) for rt in GEN4}
    assert derived == {"gen4_hgsspt"}
    assert len(derived) == 1, "one foundation means every Gen 4 title pairs with every other"
