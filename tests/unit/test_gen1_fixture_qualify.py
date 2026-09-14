"""The fixture lane's oracle: `tools/gen1_fixtures.py --qualify`, tested with no emulator.

tests/fixtures/gen1/*.SaveRAM are what the physical Gen 1 lanes boot from, so a fixture that
is not a real, consistent save silently weakens every test downstream of it. `qualify()` is
the check, and this file pins the state it currently finds: the four R/B fixtures were
regenerated from scripted play today (Bulbasaur/Charmander, level 5, exp 135) and must stay
clean; Yellow's two still hold the old harness' bytes (level byte written directly, exp 0)
and are allowed as LEGACY only because the tool names them individually.

The blank-save case is here because it is the shape a truncated or uninitialised fixture
takes, and it used to raise out of `decode_party` rather than be reported.
"""
from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))

import gen1_fixtures as fixtures  # noqa: E402  (tools/ is not a package; the tool is a script)

_FIXTURES = os.path.join(_REPO, "tests", "fixtures", "gen1")
_RB = ("red_town", "blue_town", "red_battle", "blue_battle")
_YELLOW = ("yellow_town", "yellow_battle")
_ALL = _RB + _YELLOW


def _load(name: str) -> tuple[bytes, bytes]:
    sram_path = os.path.join(_FIXTURES, f"{name}.SaveRAM")
    if not os.path.exists(sram_path):
        pytest.skip(f"{name}.SaveRAM not present")
    title = name.split("_")[0]
    rom_rel = fixtures.DUMP.get(title)
    assert rom_rel is not None, f"the tool maps no dump for {title}"
    rom_path = os.path.join(_REPO, rom_rel)
    if not os.path.exists(rom_path):
        pytest.skip(f"{os.path.basename(rom_path)} not present — no cartridge to scan")
    with open(sram_path, "rb") as f:
        sram = f.read()
    with open(rom_path, "rb") as f:
        return sram, f.read()


@pytest.mark.parametrize("name", _RB)
def test_regenerated_fixtures_qualify_clean(name):
    """These four came out of scripted play; any problem here is a regression, not debris."""
    sram, rom = _load(name)
    assert fixtures.qualify(sram, rom) == [], (
        f"{name} no longer qualifies — it was regenerated from real play and must stay clean")


@pytest.mark.parametrize("name", _YELLOW)
def test_yellow_fixtures_are_legacy_and_nothing_else(name):
    sram, rom = _load(name)
    problems = fixtures.qualify(sram, rom)
    assert len(problems) == 1, f"{name}: expected only the exp artefact, got {problems}"
    assert "exp 0" in problems[0], problems[0]
    assert name in fixtures.LEGACY, f"{name} is not named LEGACY in the tool"
    assert fixtures.is_legacy_artefact(problems), "the artefact detector does not see it"


def test_the_legacy_set_names_exactly_the_two_yellow_fixtures():
    assert {"yellow_town", "yellow_battle"} == fixtures.LEGACY


def test_a_blank_saveram_is_reported_not_raised():
    """All-zero bytes: no checksum, no decodable party block, and neither may raise."""
    _, rom = _load("red_town")           # any real dump; skips when the dumps are absent
    problems = fixtures.qualify(bytes(0x8000), rom)
    assert any("checksum" in p for p in problems), problems
    assert any("no party mon" in p for p in problems), problems


def test_the_sweep_prints_one_line_per_fixture_and_exits_zero(capsys):
    """The subcommand itself: 4 OK, 2 LEGACY, exit 0 on the committed set."""
    for name in _ALL:
        if not os.path.exists(os.path.join(_FIXTURES, f"{name}.SaveRAM")):
            pytest.skip(f"{name}.SaveRAM not present")
    for title, rel in fixtures.DUMP.items():
        if not os.path.exists(os.path.join(_REPO, rel)):
            pytest.skip(f"{rel} not present — the sweep would report NO-ROM for {title}")

    code = fixtures.qualify_all()
    lines = capsys.readouterr().out.strip().splitlines()
    assert code == 0, f"the sweep refused a committed fixture: {lines}"
    assert len(lines) == len(_ALL), lines
    assert sum(": OK " in line for line in lines) == len(_RB), lines
    assert sum(": LEGACY " in line for line in lines) == len(_YELLOW), lines
    for line in lines:
        assert line.startswith(_ALL), f"unexpected line: {line!r}"
