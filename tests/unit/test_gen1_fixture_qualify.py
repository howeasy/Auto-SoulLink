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

codec = fixtures.codec  # the tool imports the codec; the tests reconstruct save states with it

_FIXTURES = os.path.join(_REPO, "tests", "fixtures", "gen1")
_RB = ("red_town", "blue_town", "red_battle", "blue_battle", "red_town_ot2")
_YELLOW = ("yellow_town", "yellow_battle")
_ALL = _RB + _YELLOW

# The has-changed-boxes bit lives at sMainData + (wCurrentBoxNum - wMainDataStart)
# (gen1_codec.py:74-75), inside the main-data checksum's range.
_FLAG_BYTE = codec._CURRENT_BOX
_BOX_BANK_1 = codec.SRAM_LAYOUT["box_banks"][0]  # sBox1..sBox6, SRAM bank 2


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


# ── the box checksums (A0 item 7) ────────────────────────────────────────────────────────
# The active box lives in sCurBoxData and has NO checksum byte of its own: the game covers it
# with the main-data checksum (SaveCurrentBoxData recomputes sGameData..sGameDataEnd,
# engine/menus/save.asm:255-258, and LoadCurrentBoxData refuses the save before reading it,
# :96-105), which is what verify_bank1 already checks. The 12 boxes in SRAM banks 2/3 do have
# checksums — a whole-bank byte and one per box — and the game only ever writes them in
# CopyBoxToOrFromSRAM (:400-431), i.e. after the first ChangeBox sets the has-changed-boxes bit.
# Every fixture built by the scripted route never opened a PC, so its banks are untouched SRAM.


def _with_written_box_banks(sram: bytes) -> bytearray:
    """A copy of `sram` as a save looks once a PC box change has written the banks: the
    has-changed-boxes bit set, both bank checksums and all twelve box checksums recomputed the
    way CopyBoxToOrFromSRAM does, and the main-data checksum recomputed over its own range."""
    image = bytearray(sram)
    image[_FLAG_BYTE] |= codec._BOX_INITIALIZED
    for bank_index, start in enumerate(codec.SRAM_LAYOUT["box_banks"]):
        end = codec.SRAM_LAYOUT["all_boxes_checksums"][bank_index]
        for slot in range(6):
            offset = start + slot * codec.BOX_SIZE
            image[codec.SRAM_LAYOUT["individual_checksums"][bank_index] + slot] = (
                codec.sav_checksum(image[offset:offset + codec.BOX_SIZE]))
        image[end] = codec.sav_checksum(image[start:end])
    image[codec.SRAM_LAYOUT["sMainDataCheckSum"]] = codec.sav_checksum(
        image[codec.SRAM_LAYOUT["sPlayerName"]:codec.SRAM_LAYOUT["sMainDataCheckSum"]])
    return image


def test_a_flipped_byte_in_the_current_box_names_the_checksum_that_covers_it():
    sram, rom = _load("red_town")
    image = bytearray(sram)
    image[codec.SRAM_LAYOUT["sCurBoxData"] + 22] ^= 0x01  # inside sCurBoxData, past the terminator
    problems = fixtures.qualify(bytes(image), rom)
    assert problems, "a flipped byte in the current box qualified clean"
    assert any("box" in p and "checksum" in p for p in problems), (
        f"the refusal does not name the box or its checksum: {problems}")


def test_an_initialised_box_bank_must_carry_matching_checksums():
    sram, rom = _load("red_town")
    written = _with_written_box_banks(sram)
    assert fixtures.qualify(bytes(written), rom) == [], (
        "the flag and the banks the game writes alongside it must qualify clean")
    flipped = bytearray(written)
    flipped[_BOX_BANK_1 + 22] ^= 0x01  # inside sBox1
    problems = fixtures.qualify(bytes(flipped), rom)
    assert any("box 1 checksum" in p for p in problems), problems
    assert any("box bank 2 checksum" in p for p in problems), problems
    forged = bytearray(written)
    forged[codec.SRAM_LAYOUT["all_boxes_checksums"][0]] ^= 0x01  # the stored bank byte alone
    assert any("box bank 2 checksum" in p for p in fixtures.qualify(bytes(forged), rom))


def test_an_uninitialised_box_bank_is_not_a_checksum_failure():
    """The scripted fixtures never opened a PC: their banks read $FF and the game would not
    read them, so a stray byte there is not a corrupt save — and refusing it would refuse
    every fixture this route builds."""
    sram, rom = _load("red_town")
    assert fixtures.qualify(sram, rom) == []
    image = bytearray(sram)
    image[_BOX_BANK_1 + 22] ^= 0x01
    assert fixtures.qualify(bytes(image), rom) == []


def test_the_committed_ot2_fixture_has_a_second_trainer_id():
    """A1's wrong-save leg needs a Red save whose trainer ID is not the one scripted play
    produces by default. Deliberately NOT `_load`: a missing fixture has to fail here, not skip,
    until the coordinator builds tests/fixtures/gen1/red_town_ot2.SaveRAM on the lane."""
    with open(os.path.join(_FIXTURES, "red_town_ot2.SaveRAM"), "rb") as f:
        sram = f.read()
    ot = fixtures.saved_ot(sram, "red")
    assert ot != fixtures.DEFAULT_OT, (
        f"red_town_ot2.SaveRAM carries the default OT 0x{ot:04X} — rebuild it with "
        f"`python tools/gen1_fixtures.py red town_ot2 --title-idle 120` (240 or 360 if the "
        f"idle count is already taken)")
