"""R-2's known-positive control: the oracle must rebuild the cartridge's own party records.

The MODEL leg of R-2 (docs/gen1_requirements.md): every party mon in the committed 32 KiB
battery saves must have its five stored stats and its level reproduced EXACTLY by the
Python oracle, driven by nothing but the saved bytes and the ROM's own base-stats record.
The fixtures are raw saves, so this needs no emulator and no Lua -- and that is the point:
the codec's own test vectors are hand-built, these bytes came out of the game.

THE STATS LEG CLOSES ON ALL SIX FIXTURES. THE LEVEL LEG CANNOT, and that is a finding
rather than a threshold to lower: every record stores exp 0 against a level byte of 5.
pret's AddPartyMon derives exp FROM the level (engine/pokemon/add_mon.asm:202-207:
`ld a, [wCurEnemyLevel] ... callfar CalcExperience`), so a real level-5 mon holds that
level's threshold, not zero -- these saves were written by a harness that set the level
byte directly. The oracle then correctly reports what the bytes say:
CalcLevelFromExperience (engine/pokemon/experience.asm:6-27) starts its loop at level 2,
and on the medium-slow curve the level-2 threshold is already 9, so exp 0 is level 1.
Both the odd input and the oracle's faithful answer are pinned below so neither can drift
unnoticed; the level oracle is still exercised positively through the exp it would have
been given.
"""
from __future__ import annotations

import copy
import os

import pytest

from server.adapters import gen1_codec as codec
from server.adapters.gen1_rom_scan import scan_base_stats

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_FIXTURES = os.path.join(_REPO, "tests", "fixtures", "gen1")
_SAVES = ("red_town", "blue_town", "yellow_town", "red_battle", "blue_battle", "yellow_battle")
_ROM_FILES = {"red": "gen1_red.gb", "blue": "gen1_blue.gb", "yellow": "gen1_yellow.gbc"}
STATS = ("max_hp", "atk", "def", "spd", "spc")
# All six saves here were regenerated from scripted play (F-6); none is legacy. Kept as the
# mechanism for any future fixture that lands byte-written ahead of a real rebuild.
LEGACY_FIXTURES = set()
_base_stats_cache: dict[str, dict] = {}


def _base_stats(title: str) -> dict:
    """The cartridge's own base-stats table, keyed by national dex."""
    if title not in _base_stats_cache:
        path = os.path.join(_REPO, "patch", "build", _ROM_FILES[title])
        if not os.path.exists(path):
            pytest.skip(f"{os.path.basename(path)} not present — no cartridge to read")
        with open(path, "rb") as f:
            _base_stats_cache[title] = scan_base_stats(f.read())
    return _base_stats_cache[title]


def _party(name: str) -> list[dict]:
    """The party block of one battery save, decoded exactly as the client would."""
    path = os.path.join(_FIXTURES, f"{name}.SaveRAM")
    if not os.path.exists(path):
        pytest.skip(f"{name}.SaveRAM not present")
    with open(path, "rb") as f:
        sram = f.read()
    assert len(sram) == codec.SRAM_SIZE, f"{name}: {len(sram)} bytes, expected 32 KiB"
    start = codec.SRAM_LAYOUT["sPartyData"]
    return codec.decode_party(sram[start:start + codec.PARTY_LAYOUT["size"]])


def _entry(name: str, mon: dict) -> tuple[int, dict]:
    """(national dex, base-stats record) for a mon, from the ROM it was played on."""
    dex = codec.internal_to_natdex(mon["species"])
    stats = _base_stats(name.split("_")[0])
    assert dex in stats, (
        f"{name}: internal index {mon['species']} maps to dex {dex}, which the ROM scan "
        f"does not carry")
    return dex, stats[dex]


@pytest.mark.parametrize("name", _SAVES)
def test_party_stats_recompute_from_the_cartridge(name):
    """Stats must match field-for-field; the level byte is pinned as observed (see module)."""
    party = _party(name)
    assert len(party) == 1, f"{name}: {len(party)} party mons, expected the single starter"

    for mon in party:
        dex, entry = _entry(name, mon)
        stored = {k: mon[k] for k in STATS}
        got = codec.recompute_stats(mon, entry)
        assert got == stored, (
            f"{name} dex {dex} level {mon['level']}: recomputed {got} != stored {stored}")
        if name in LEGACY_FIXTURES:
            # Written byte-by-byte by the old tool: level 5 with exp 0, which the engine would
            # call level 1. Pinned, not skipped, until tools/gen1_fixtures.py replaces them
            # (Yellow needs its own route: its intro is not the R/B lab route).
            assert (mon["level"], mon["exp"]) == (5, 0), (
                f"{name}: legacy fixture changed; drop it from LEGACY_FIXTURES")
        else:
            # A real save (tools/gen1_fixtures.py, scripted play): the level byte is what the
            # engine derives from exp on this curve (engine/pokemon/experience.asm) and exp is
            # exactly what add_mon.asm:202-207 stored for a fresh starter of that level.
            assert codec.level_from_exp(entry["growth_rate"], mon["exp"]) == mon["level"], (
                f"{name} dex {dex}: exp {mon['exp']} is not level {mon['level']} on curve {entry['growth_rate']}")
            assert mon["exp"] == codec.exp_for_level(entry["growth_rate"], mon["level"]), (
                f"{name} dex {dex}: a fresh starter carries exactly exp_for_level")


@pytest.mark.parametrize("name", _SAVES)
def test_a_perturbed_dv_nibble_stops_the_recompute(name):
    """Without this, the equality above could pass on a function that ignores its inputs."""
    mon = _party(name)[0]
    _, entry = _entry(name, mon)
    stored = {k: mon[k] for k in STATS}
    assert codec.recompute_stats(mon, entry) == stored, "the control is already broken"

    broken = copy.deepcopy(mon)
    broken["dvs"]["atk"] ^= 8                 # one nibble, its high bit
    after = codec.recompute_stats(broken, entry)
    assert after != stored, "recompute_stats ignored a DV change — the equality is vacuous"
    assert after["atk"] != stored["atk"], "the perturbation never reached the attack stat"
