"""The Gen 1 ROM symbol table must describe the ROMs we actually run.

`data/pret_rom_syms.json` carries ~12.5k ROM-space labels per game, fetched from pret's
`symbols` branch (CI-built from a byte-identical ROM) rather than built locally. That
removes the need for GNU make and a host C compiler, but it moves the risk: symbols built
against a different ROM revision would be confidently, silently wrong, and a companion
patch hooks absolute ROM offsets.

So each entry records the sha1 of the ROM its symbols describe, and these tests check the
artifact is coherent and — when the cartridge dumps are present — that the hashes match.
ROMs are gitignored, so the hash check skips rather than fails when they are absent.

Regenerate with: python tools/build_pret_syms.py --rom-syms
"""
import hashlib
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYMS_PATH = os.path.join(REPO, "data", "pret_rom_syms.json")

# game key -> the cartridge dump filename at the repo root
ROM_FILES = {
    "pokered": "Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
    "pokeblue": "Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb",
    "pokeyellow": "Pokemon - Yellow Version (USA, Europe).gbc",
}

# Routines a Gen 1 companion patch would hook. Present in all three games; if pret ever
# renames one, the patch build must be revisited rather than silently miss its hook.
REQUIRED_SYMBOLS = ("VBlank", "TrackPlayTime", "Bankswitch", "OverworldLoop",
                    "PrintText", "PlaySound", "DisplayStartMenu")


@pytest.fixture(scope="module")
def syms():
    if not os.path.exists(SYMS_PATH):
        pytest.skip("data/pret_rom_syms.json missing — "
                    "run `python tools/build_pret_syms.py --rom-syms`")
    with open(SYMS_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_all_three_games_present(syms):
    assert set(syms) == set(ROM_FILES), f"expected {sorted(ROM_FILES)}, got {sorted(syms)}"


@pytest.mark.parametrize("game", sorted(ROM_FILES))
def test_symbol_table_is_populated(syms, game):
    entry = syms[game]
    assert entry["rom_sha1"], f"{game} has no rom_sha1 — cannot be validated against a ROM"
    assert len(entry["rom_sha1"]) == 40, f"{game} rom_sha1 is not a sha1: {entry['rom_sha1']!r}"
    assert len(entry["symbols"]) > 10000, \
        f"{game} has only {len(entry['symbols'])} ROM symbols — fetch likely truncated"


@pytest.mark.parametrize("game", sorted(ROM_FILES))
def test_required_hook_symbols_exist(syms, game):
    missing = [s for s in REQUIRED_SYMBOLS if s not in syms[game]["symbols"]]
    assert not missing, f"{game} is missing hook symbols {missing} — pret may have renamed them"


@pytest.mark.parametrize("game", sorted(ROM_FILES))
def test_symbols_match_the_rom_on_disk(syms, game):
    """The whole safety property of using prebuilt symbols."""
    rom = os.path.join(REPO, ROM_FILES[game])
    if not os.path.exists(rom):
        pytest.skip(f"{ROM_FILES[game]} not present (ROMs are gitignored)")
    with open(rom, "rb") as f:
        actual = hashlib.sha1(f.read()).hexdigest()
    assert actual == syms[game]["rom_sha1"], (
        f"{game}: symbols were built for ROM sha1 {syms[game]['rom_sha1']}, but the ROM on "
        f"disk is {actual}. Every ROM offset in the table is suspect for this dump."
    )


def test_red_and_blue_are_not_the_same_table(syms):
    """Red and Blue share a decomp but not a layout — 490 shared labels sit at different
    addresses. One table serving both would put a patch hook in the wrong place."""
    red, blue = syms["pokered"]["symbols"], syms["pokeblue"]["symbols"]
    moved = sum(1 for k in red if k in blue and red[k] != blue[k])
    assert moved > 100, f"only {moved} symbols differ between Red and Blue — same table twice?"
