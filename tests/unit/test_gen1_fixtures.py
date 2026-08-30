"""Where the Gen 1 duo fixtures actually stand, decoded from the battery saves.

A comment in the duo suite claimed the Yellow battery save "came out on Route 3", and on
that basis three scenarios -- playthrough, deadzone and dupes, the only ones that PLAY --
were skipped on the Yellow pairing. The claim was wrong, and it entered with the commit
that fixed Yellow's WRAM-shift bugs, which is the tell: it was read off the wrong byte.

Offset derivation, from the decomps rather than from the repo:
    sram.asm "Save Data" starts with `ds $598`, then sPlayerName (NAME_LENGTH = 11), then
    sMainData, which begins at wMainDataStart = wPokedexOwned. wCurMap - wPokedexOwned is
    0x67 in both pokered and pokeyellow, so wCurMap lands at 0x2000 + 0x598 + 11 + 0x67.

Pinning the decoded values means a regenerated fixture that lands somewhere else fails
here, with the map id, instead of silently making a duo scenario untestable.
"""
from __future__ import annotations

import os

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_FIXTURES = os.path.join(_REPO, "tests", "fixtures", "gen1")

CUR_MAP = 0x2000 + 0x598 + 11 + 0x67       # = 0x260A
CUR_Y, CUR_X = CUR_MAP + 3, CUR_MAP + 4    # wYCoord / wXCoord follow wCurMap

ROUTE_1, PALLET_TOWN = 0x0C, 0x00


def _save(rom: str, kind: str) -> bytes:
    path = os.path.join(_FIXTURES, f"{rom}_{kind}.SaveRAM")
    if not os.path.exists(path):
        pytest.skip(f"{os.path.basename(path)} not present (fixtures are gitignored)")
    return open(path, "rb").read()


@pytest.mark.parametrize("rom", ["red", "blue", "yellow"])
def test_every_battle_fixture_is_on_route_1(rom):
    """The premise SAME_MAP_ONLY denied. Soul Link pairs by area, so the three playing
    scenarios need both cartridges on one encounter map -- and all three titles are."""
    save = _save(rom, "battle")
    assert save[CUR_MAP] == ROUTE_1, (
        f"{rom} battle fixture is on map 0x{save[CUR_MAP]:02X}, not Route 1 (0x0C) — "
        f"the playing duo scenarios have no shared encounter area")


@pytest.mark.parametrize("rom", ["red", "blue", "yellow"])
def test_every_battle_fixture_stands_on_the_same_tile(rom):
    """Not merely the same map: the same tile. The scenarios' walk budgets and the
    Route 1 / Pallet boundary crossing are written against (10, 35)."""
    save = _save(rom, "battle")
    assert (save[CUR_X], save[CUR_Y]) == (10, 35), \
        f"{rom} battle fixture is at ({save[CUR_X]}, {save[CUR_Y]}), expected (10, 35)"


@pytest.mark.parametrize("rom", ["red", "blue", "yellow"])
def test_every_town_fixture_is_on_encounter_free_ground(rom):
    """Pallet Town has no wild table, which is what makes it safe for the gates that
    walk: an encounter mid-walk would end the proof rather than fail it."""
    save = _save(rom, "town")
    assert save[CUR_MAP] == PALLET_TOWN, \
        f"{rom} town fixture is on map 0x{save[CUR_MAP]:02X}, not Pallet Town (0x00)"


def test_the_offset_is_not_reading_a_constant():
    """Control. Every assertion above would pass on a byte that happened to read 0x0C
    everywhere; the town fixtures reading a DIFFERENT value at the same offset is what
    shows the offset tracks the map."""
    battle = _save("red", "battle")
    town = _save("red", "town")
    assert battle[CUR_MAP] != town[CUR_MAP], \
        "battle and town fixtures decode to the same map — the offset is probably wrong"
