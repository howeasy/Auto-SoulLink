"""The fixture lane's oracle: `tools/gen1_fixtures.py --qualify`, tested with no emulator.

tests/fixtures/gen1/*.SaveRAM are what the physical Gen 1 lanes boot from, so a fixture that
is not a real, consistent save silently weakens every test downstream of it. `qualify()` is
the check, and this file pins the state it currently finds: all seven fixtures (the four R/B
saves, yellow_town, yellow_battle and red_town_ot2) were regenerated from scripted play
(Bulbasaur/Charmander/Pikachu, level 5) and must stay clean. LEGACY is empty -- kept as the
mechanism for any future fixture that lands byte-written ahead of a real rebuild.

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
_CLEAN = ("red_town", "blue_town", "red_battle", "blue_battle", "red_town_ot2", "yellow_town",
          "yellow_battle")
_LEGACY = ()
_ALL = _CLEAN + _LEGACY

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


@pytest.mark.parametrize("name", _CLEAN)
def test_regenerated_fixtures_qualify_clean(name):
    """These came out of scripted play; any problem here is a regression, not debris."""
    sram, rom = _load(name)
    assert fixtures.qualify(sram, rom) == [], (
        f"{name} no longer qualifies — it was regenerated from real play and must stay clean")


def test_the_legacy_set_is_empty():
    assert not fixtures.LEGACY


def test_a_blank_saveram_is_reported_not_raised():
    """All-zero bytes: no checksum, no decodable party block, and neither may raise."""
    _, rom = _load("red_town")           # any real dump; skips when the dumps are absent
    problems = fixtures.qualify(bytes(0x8000), rom)
    assert any("checksum" in p for p in problems), problems
    assert any("no party mon" in p for p in problems), problems


def test_the_sweep_prints_one_line_per_fixture_and_exits_zero(capsys):
    """The subcommand itself: 7 OK, 0 LEGACY, exit 0 on the committed set."""
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
    assert sum(": OK " in line for line in lines) == len(_CLEAN), lines
    assert sum(": LEGACY " in line for line in lines) == len(_LEGACY), lines
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


# ── stored stats lag their stat exp (H-8) ────────────────────────────────────────────────
# GainExperience adds the beaten foe's base stats into the winner's stat exp after EVERY
# battle (engine/battle/experience.asm:25-51) but only calls CalcStats on the branch where the
# level actually changed (:159-161 -> :187). A mon that fought on after its last level-up
# therefore stores stats BELOW a recompute from its current stat exp, by a point or two at low
# levels. rival_swap_new hit exactly that (slot 0 levelled 5->6 mid-battle, then beat the
# second mon: stored atk already carried its stat-exp point, stored spd did not), so the band
# is [recompute(stat exp 0), recompute(stat exp now)] and nothing wider.


def _with_party_mon(sram: bytes, slot: int, edit) -> bytes:
    """`sram` with party mon `slot` passed through `edit` and the main checksum redone."""
    image = bytearray(sram)
    at = codec.SRAM_LAYOUT["sPartyData"] + codec.PARTY_LAYOUT["mons"] + slot * codec.PARTY_MON_SIZE
    mon = codec.decode_party_mon(bytes(image[at:at + codec.PARTY_MON_SIZE]))
    edit(mon)
    image[at:at + codec.PARTY_MON_SIZE] = codec.encode_party_mon(mon)
    image[codec.SRAM_LAYOUT["sMainDataCheckSum"]] = codec.sav_checksum(
        image[codec.SRAM_LAYOUT["sPlayerName"]:codec.SRAM_LAYOUT["sMainDataCheckSum"]])
    return bytes(image)


def test_stat_exp_accrued_without_a_level_up_still_qualifies():
    """Green: max the stat exp, touch no stored stat. The engine would not have recalculated."""
    sram, rom = _load("red_town")
    grown = _with_party_mon(sram, 0, lambda m: m["stat_exp"].update(
        dict.fromkeys(m["stat_exp"], 0xFFFF)))

    notes: list[str] = []
    assert fixtures.qualify(grown, rom, notes) == [], (
        "a mon that gained stat exp without levelling was refused; the band is too tight")
    assert notes, "the tolerated lag was accepted silently — the PYDEC line would not name it"
    assert all("within [" in n and "stat exp accrued" in n for n in notes), notes


def test_a_stored_stat_outside_the_band_still_fails():
    """Red, both ends: below recompute(0) and above recompute(current) are still refusals."""
    sram, rom = _load("red_town")
    below = _with_party_mon(sram, 0, lambda m: m.update(spd=m["spd"] - 1))
    assert any("spd" in p and "outside" in p for p in fixtures.qualify(below, rom)), (
        "a stat one point below its stat-exp-0 recompute qualified clean")

    # Stat exp stays 0 here, so the band is the single stored value: one point up is above it.
    over = _with_party_mon(sram, 0, lambda m: m.update(spd=m["spd"] + 1))
    assert any("spd" in p and "outside" in p for p in fixtures.qualify(over, rom)), (
        "a stat above the recompute from its own stat exp qualified clean")


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
