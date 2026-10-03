"""The UI mockup fixtures must keep describing the payload the server actually sends.

The fixtures under tests/fixtures/ui/ were captured from a running server
(see docs/historical/ui_mockup_brief.md §7) so the mockups design against a real payload rather than
an imagined one. That only holds while the payload does not move underneath them: a
mockup built on a stale fixture is a mockup of a product that does not exist, and nothing
else in the suite would notice, because no shipped code reads these files.

These tests are that notice. They are deliberately structural -- they pin the SHAPE, not
the values, because the values are a snapshot of one mock run and are expected to differ.
"""

from __future__ import annotations

import json
import os

import pytest

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "ui",
)

STATUS_FIXTURES = ["gen3.json", "gen1.json"]


def _load(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def live_status(tmp_path_factory) -> dict:
    """A status dict from a real, freshly-built server -- the contract to compare against."""
    from server.server import SLinkServer

    # A tmp data dir on purpose: data_dir=None falls back to the repo's LIVE data/links.json, and the
    # autouse isolate_data_dir (tests/conftest.py) is function-scoped, so it cannot cover this module-scoped
    # fixture. A leftover run's rom_type then changes the adapter and adds keys (e.g. trade_recovery).
    srv = SLinkServer(data_dir=str(tmp_path_factory.mktemp("mockup_status")))
    return srv._build_status_dict()


@pytest.mark.parametrize("name", STATUS_FIXTURES)
def test_top_level_keys_match_build_status_dict(name, live_status):
    """A key added to or removed from _build_status_dict must reach the fixtures.

    Equality, not a subset check: a fixture carrying a key the server no longer emits is
    just as misleading as one missing a key the server added -- the mockup would be
    rendering a field that will never arrive.
    """
    assert set(_load(name)) == set(live_status), (
        f"{name} no longer matches _build_status_dict. Regenerate it: see "
        "docs/historical/ui_mockup_brief.md §7."
    )


@pytest.mark.parametrize("name", STATUS_FIXTURES)
def test_player_keys_match(name, live_status):
    fixture = _load(name)
    for pid in ("a", "b"):
        assert set(fixture["players"][pid]) == set(live_status["players"][pid]), (
            f"{name} players.{pid} no longer matches _build_status_dict."
        )


@pytest.mark.parametrize("name", STATUS_FIXTURES)
def test_party_entries_carry_the_enriched_fields(name):
    """_build_status_dict enriches each party mon beyond what the client sent.

    The mockups render species_name, sprite_html and move_details directly. A fixture
    captured before enrichment -- from raw state rather than from /api/status -- would
    still have the right top-level keys while every party row rendered blank.
    """
    fixture = _load(name)
    for pid in ("a", "b"):
        details = fixture["players"][pid]["party_details"]
        assert details, f"{name} players.{pid} has an empty party; the mockups need one."
        for key, mon in details.items():
            for field in ("species_name", "sprite_html", "move_details", "item_name"):
                assert field in mon, f"{name} players.{pid}.party_details[{key}] lacks {field}"
            assert mon["species_name"], f"{name} players.{pid}.party_details[{key}] unnamed"
            # The key is the dict key; a value that does not repeat it strands every
            # consumer that iterates values (the mockup lost its whole partner column).
            assert mon.get("key") == key, f"{name} players.{pid}.party_details[{key}] lacks key"
    for area, sides in fixture["pending_captures"].items():
        for pid, mon in sides.items():
            assert mon.get("sprite_html"), f"{name} pending_captures[{area}].{pid} has no sprite"


@pytest.mark.parametrize("name", STATUS_FIXTURES)
def test_player_capabilities_come_from_the_shared_probe(name):
    """`players.{pid}.capabilities` and capabilities.json[rom_type] are the same function's
    answers; a fixture where they disagree was captured against a different adapter."""
    fixture, caps = _load(name), _load("capabilities.json")
    for pid in ("a", "b"):
        p = fixture["players"][pid]
        assert p["capabilities"] == caps[p["rom_type"]], f"{name} players.{pid}.capabilities drifted"


@pytest.mark.parametrize("name", STATUS_FIXTURES)
def test_fixtures_are_populated_enough_to_show_layout_bugs(name):
    """An empty panel hides its own layout bugs, so every panel must have something in it.

    Boxes are called out because they were the gap that prompted this: the mock injector
    never sent pc_boxes, so every box-facing surface rendered empty and looked fine.
    """
    f = _load(name)
    assert len(f["links"]) >= 4, "too few links to lay out a links table"
    assert f["killfeed"], "no deaths, so the memorial renders empty"
    assert f["recent_events"], "no events, so the feed renders empty"
    assert any(f["players"][p]["pc_boxes"] for p in "ab"), "no boxed mons on either side"
    assert any(f["players"][p]["battle_state"].get("in_battle") for p in "ab"), (
        "nobody is in battle, so the battle panel never renders"
    )


@pytest.mark.parametrize("name", STATUS_FIXTURES)
def test_both_players_have_their_own_populated_encounter_table(name):
    """Encounter data is per player, and the fixtures have to show that.

    Two randomized cartridges do not share one table, so this is the payload's clearest
    per-player claim -- and it only lands if BOTH sides are populated and they DIFFER. A
    player parked somewhere with no wild encounters leaves that panel empty, which reads
    as missing data rather than as the point being made.
    """
    f = _load(name)
    tables = {}
    for pid in ("a", "b"):
        t = f["players"][pid]["encounter_table"] or {}
        assert t, (
            f"{name} players.{pid} has no encounter table -- move that player to an area "
            "that has wild encounters (see _final_areas in tools/inject_full_mocks.py)."
        )
        tables[pid] = t
    assert f["players"]["a"]["current_area_id"] != f["players"]["b"]["current_area_id"], (
        f"{name} has both players in the same area, so the per-player tables are identical "
        "and demonstrate nothing."
    )


def test_capabilities_cover_every_rom_type_the_status_fixtures_use():
    """Both players' cartridges must resolve, not just player A's.

    The two halves of a Soul Link are different VERSIONS of the same game (red/blue), so a
    capabilities file holding one of the pair leaves the other player with no capabilities
    at all. That does not fail loudly -- it renders as player B quietly losing their
    Ability column, which reads as a layout bug rather than as missing data.
    """
    caps = _load("capabilities.json")
    for name in STATUS_FIXTURES:
        status = _load(name)
        for pid in ("a", "b"):
            rom_type = status["players"][pid]["rom_type"]
            assert rom_type in caps, (
                f"{name} players.{pid} is on rom_type {rom_type!r}, which capabilities.json "
                "does not describe. Regenerate: python tools/gen_ui_capabilities.py"
            )


def test_capabilities_cover_every_routable_rom_type():
    """The generator enumerates the routing table, so the fixture should too."""
    from server.adapters import _ROM_TYPE_TO_GAME_ID

    assert set(_load("capabilities.json")) == set(_ROM_TYPE_TO_GAME_ID), (
        "capabilities.json is out of step with the adapter routing table. "
        "Regenerate: python tools/gen_ui_capabilities.py"
    )


def test_capabilities_distinguish_cartridges_within_one_generation():
    """Capability is a property of the cartridge, not of the generation.

    The native info panel remains RR-only, while the bound vanilla titles also implement
    Explode. A default adapter must not erase the remaining per-cartridge distinction.
    """
    caps = _load("capabilities.json")
    for title in ("firered", "leafgreen", "emerald"):
        assert caps[title]["explode_mode"] is True
    assert caps["firered_rr"]["explode_mode"] is True
    assert caps["firered"]["info_panel"] is True
    assert caps["firered_rr"]["info_panel"] is True
    # Gen 1 needs no patch at all for Explode Mode -- the headline Gen 1 claim the
    # mockups make, and the one most likely to be quietly wrong.
    assert caps["red"]["explode_mode"] is True
    assert caps["red"]["abilities"] is False


def test_capabilities_fixture_is_what_the_generator_emits():
    """The fixture is generated (tools/gen_ui_capabilities.py), never hand-edited, so it must BE
    the generator's output. The other checks only compare it with the status mockups, which went
    stale alongside it: the gen2_gsc rename left game_id gen2_crystal, 30 mons/box and gym-order
    Johto badges in here, and nothing noticed (Emerald lane, 2026-09-26)."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = subprocess.run([sys.executable, os.path.join(root, "tools", "gen_ui_capabilities.py")], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == _load("capabilities.json"), \
        "tests/fixtures/ui/capabilities.json drifted: python tools/gen_ui_capabilities.py > it"
