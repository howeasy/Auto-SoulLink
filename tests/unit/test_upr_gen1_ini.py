"""The UPR fork's pureRGB entries (tools/gen_upr_gen1_ini.py, data/purergb/upr_pure_entries.ini).

No Java here. The committed INI is the artefact the fork ships; these tests pin what the
generator promised (docs/purergb/PLAN.md §6 M5 "INI corrections") and audit its key set
against the keys the fork's Gen1RomHandler reads. The regeneration check needs the three
pinned pure ROMs and skips without them.
"""
from __future__ import annotations

import json
import os
import pathlib
import re

import pytest

import tools.upr_write_domain_diff as udd
from tools import gen_upr_gen1_ini as gen
from tools.upr_write_domain_diff import load_entry

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_INI = pathlib.Path(_REPO, "data", "purergb", "upr_pure_entries.ini")
_FORK = os.path.join(_REPO, ".cache", "slink-upr")
_ROMS = os.path.join(_REPO, ".cache", "purergb")
_OVERLAY_ROMS = os.path.join(_REPO, ".cache", "purergb-overlay")
TITLES = ("purered", "pureblue", "puregreen")
OVERLAY_SECTIONS = {t + "_overlay": f"{gen.TITLES[t]} overlay (U)" for t in TITLES}


@pytest.fixture
def overlay_entries(monkeypatch):
    """load_entry() for the `<title>_overlay` sections (upr_write_domain_diff.SECTION may
    not know them yet)."""
    for key, section in OVERLAY_SECTIONS.items():
        monkeypatch.setitem(udd.SECTION, key, section)
    return lambda title: load_entry(title + "_overlay", _INI)


def _flatten(v):
    if isinstance(v, list) and v and isinstance(v[0], tuple):
        return [o for sp, lv in v for o in sp + lv]
    return v if isinstance(v, list) else [v]

# Every key the fork's Gen1RomHandler reads through romEntry.getValue / hasValue /
# arrayEntries / tweakFiles (grep of .cache/slink-upr at 4.6.1-slink1; the test below
# re-derives it whenever the fork checkout is present).
HANDLER_KEYS = {
    "BWXPTweak", "BaseStatsEntrySize", "CanChangeStarterText", "CanChangeTrainerText",
    "CatchingTutorialMonOffset", "CopyStaticPokemon", "CopyTMText", "CritRateTweak",
    "ExtraTrainerMovesTableOffset", "GoodRodMonsOcean", "GoodRodOffset", "GoodRodPairCount",
    "GymLeaderMovesTableOffset", "HiddenItemRoutine", "HiddenItemRoutineEntries",
    "InternalPokemonCount", "IntroCryOffset", "IntroPokemonOffset", "ItemNameCount",
    "ItemNamesOffset", "LosslessMode", "MapAddresses", "MapBanks", "MapNameInternalRowSize",
    "MapNameTableOffset", "MewStatsOffset", "MonPaletteIndicesOffset", "MoveCount",
    "MoveDataOffset", "MoveNamesOffset", "NameTablesArePointerTables", "NonDexSpecies",
    "OldRodOffset", "OldRodOffsets", "PCPotionOffset", "PatchPokedex", "PikachuEvoJumpOffset",
    "PikachuHappinessCheckOffset", "PokedexOrder", "PokedexRamOffset",
    "PokemonMovesetsDataSize", "PokemonMovesetsExtraSpaceOffset", "PokemonMovesetsTableOffset",
    "PokemonNamesLength", "PokemonNamesOffset", "PokemonStatsOffset", "SGBPalettesOffset",
    "SpecialMapList", "SpecialMapPointerTable", "StarterOffsets", "StarterOffsets1",
    "StarterOffsets2", "StarterOffsets3", "StarterPokedexBranchOffset",
    "StarterPokedexOffOffset", "StarterPokedexOnOffset", "StarterTextOffsets",
    "StaticPokemonSupport", "SuperRodTableOffset", "TMMovesOffset", "TextDelayFunctionOffset",
    "TradeNameLength", "TradeTableOffset", "TradeTableSize", "TradesUnused",
    "TrainerClassCount", "TrainerClassNamesOffsets", "TrainerDataClassCounts",
    "TrainerDataTableOffset", "TrainerRecordGrammars", "TrainerTaggingDisabled",
    "TypeEffectivenessOffset", "WildPokemonTableOffset", "XAccNerfTweak",
}
# Keys a pure entry leaves out ON PURPOSE (each reason is in the generator's FIXED_KEYS
# comment); the fork treats absence as "no such site".
DELIBERATELY_ABSENT = {
    "IntroPokemonOffset": "no intro site; absence stops the rom[0] write",
    "IntroCryOffset": "no intro site",
    "TextDelayFunctionOffset": "tweak site; lossless entries offer no tweak",
    "PCPotionOffset": "tweak site",
    "PikachuEvoJumpOffset": "tweak site (Yellow)",
    "PikachuHappinessCheckOffset": "Yellow only",
    "CatchingTutorialMonOffset": "tweak site",
    "PatchPokedex": "code injection on starter randomization",
    "StarterPokedexOnOffset": "PatchPokedex helper",
    "StarterPokedexOffOffset": "PatchPokedex helper",
    "StarterPokedexBranchOffset": "PatchPokedex helper",
    "PokedexRamOffset": "PatchPokedex helper",
    "CanChangeStarterText": "text injection",
    "StarterTextOffsets": "text injection",
    "CanChangeTrainerText": "text injection",
    "MonPaletteIndicesOffset": "mascot image only (GUI)",
    "SGBPalettesOffset": "mascot image only (GUI)",
    "BWXPTweak": "vanilla IPS tweak",
    "XAccNerfTweak": "vanilla IPS tweak",
    "CritRateTweak": "vanilla IPS tweak",
    "CopyStaticPokemon": "CopyFrom helper; pure entries are complete",
    "CopyTMText": "CopyFrom helper",
    "StarterOffsets": "the handler builds StarterOffsets1..3 from this prefix",
}


def _sections() -> dict[str, str]:
    text = _INI.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^\[([\w ]+?) \(U\)\]\n(.*?)(?=^\[|\Z)", text, re.S | re.M):
        out[m.group(1).lower().replace(" ", "_")] = m.group(2)
    return out


def _keys(section: str) -> set[str]:
    keys = set()
    for line in section.splitlines():
        line = line.split("//", 1)[0].strip()
        if "=" in line:
            keys.add(line.split("=", 1)[0])
    return keys


def test_all_three_titles_are_present_with_their_admitted_crcs():
    adm = json.loads(pathlib.Path(_REPO, "data", "games", "gen1_purergb", "admission.json").read_text(encoding="utf-8"))
    by_title = {v["title"]: v for v in adm.values() if v["kind"] == "clean"}
    for title in TITLES:
        e = load_entry(title, _INI)
        assert e["CRCInHeader"] == int(by_title[title]["header_crc"], 16)
        assert e["CRC32"] == by_title[title]["crc32"]
        assert e["LosslessMode"] == 1


def test_the_three_overlay_builds_have_their_own_entries(overlay_entries):
    """Review cx-795d1423 #3: the SLink companion overlay carries its own header CRC; without
    an exact-CRC entry Gen1RomHandler's generic fallback would pick the VANILLA Red/Blue
    offsets. Only symbol-backed offsets in the shifted banks (0/1/3) may differ from the
    clean entry; RAM-independent keys and the statics are identical."""
    adm = json.loads(pathlib.Path(_REPO, "data", "games", "gen1_purergb", "admission_overlay.json").read_text(encoding="utf-8"))
    by_title = {v["title"]: v for v in adm.values() if v["kind"] == "overlay"}
    assert set(_sections()) == set(TITLES) | set(OVERLAY_SECTIONS)
    for title in TITLES:
        clean, ov = load_entry(title, _INI), overlay_entries(title)
        assert ov["CRCInHeader"] == int(by_title[title]["header_crc"], 16) != clean["CRCInHeader"]
        assert ov["CRC32"] == by_title[title]["crc32"]
        assert set(ov) == set(clean)
        differing = {k for k in clean if clean[k] != ov[k]}
        assert differing, "the overlay entry must carry its own (shifted) offsets"
        for k in differing - {"CRCInHeader", "CRC32"}:
            for a, b in zip(_flatten(clean[k]), _flatten(ov[k]), strict=True):
                assert a == b or ((a >> 14) in (0, 1, 3) and (a >> 14) == (b >> 14)), f"{title}.{k}: {a:#x} -> {b:#x}"
        assert ov["statics"] == clean["statics"]
    e = overlay_entries("purered")
    assert e["CRCInHeader"] == 0xD3B7 and e["OldRodOffsets"] == [0xDEF8, 0xDEFD]


def test_starter_sites_include_the_hall_of_fame_ball_hide_branch(overlay_entries):
    """Review cx-795d1423 #4: HallOfFame.asm compares wPlayerStarter against STARTER1/2 to
    pick which of Oak's balls to hide postgame; a randomized starter needs those operands
    rewritten too. Symbol-relative, so the overlay (bank 0 shifted) resolves them as well."""
    for title in TITLES:
        for e in (load_entry(title, _INI), overlay_entries(title)):
            assert 0x5A503 in e["StarterOffsets1"] and 0x5A509 in e["StarterOffsets2"]
            assert len(e["StarterOffsets1"]) == len(e["StarterOffsets2"]) == 6 and len(e["StarterOffsets3"]) == 3
    assert load_entry("purered", _INI)["StarterOffsets1"][3] == 0x13E4          # StarterToPartyID+3, clean
    assert overlay_entries("purered")["StarterOffsets1"][3] == 0x13EA           # bank 0 shifted by 6 in the overlay


def test_every_handler_key_is_present_or_deliberately_absent():
    for name, body in _sections().items():
        present = _keys(body)
        missing = HANDLER_KEYS - present - set(DELIBERATELY_ABSENT)
        assert not missing, f"{name}: keys the handler reads but the entry neither sets nor excuses: {sorted(missing)}"
        leaked = present & set(DELIBERATELY_ABSENT)
        assert not leaked, f"{name}: keys marked deliberately absent are present: {sorted(leaked)}"


@pytest.mark.skipif(not os.path.isdir(_FORK), reason="fork checkout not present")
def test_handler_key_list_matches_the_fork_source():
    src = pathlib.Path(_FORK, "src", "com", "dabomstew", "pkrandom", "romhandlers",
                       "Gen1RomHandler.java").read_text(encoding="utf-8")
    found = set(re.findall(
        r'(?:getValue|hasValue|arrayEntries\.(?:get|containsKey)|tweakFiles\.get)\("([A-Za-z0-9]+)"', src))
    assert found == HANDLER_KEYS, {"only_in_fork": sorted(found - HANDLER_KEYS),
                                   "only_in_test": sorted(HANDLER_KEYS - found)}


def test_the_six_corrections_are_applied():
    """PLAN.md §6 M5 'INI corrections from the 2026-09-18 fact-check'."""
    e = load_entry("purered", _INI)
    assert "WildPokemonTableOffset" in e and "WildDataPointers" not in e          # (1)
    assert "TradeTableOffset" in e and "TradeMons" not in e
    assert e["MapBanks"] == 0xC23B and e["MapAddresses"] == 0x1A7                # (2)
    # (3) re-measured: the repackable block ends where BaseStats starts (same section)
    assert e["PokemonMovesetsDataSize"] == e["PokemonStatsOffset"] - (e["PokemonMovesetsTableOffset"] + 380)
    assert e["PokemonMovesetsDataSize"] == 0x9F4
    # (4) raw immediates per title: MissingNo's static shifts by one byte per title
    missingno = {t: [s for s in load_entry(t, _INI)["statics"] if 0x759D0 <= s[0][0] <= 0x759D8]
                 for t in TITLES}
    assert [missingno[t][0][0][0] for t in TITLES] == [0x759D5, 0x759D6, 0x759D7]
    assert [missingno[t][0][1][0] for t in TITLES] == [0x759D0, 0x759D1, 0x759D2]
    # (5) double-encoded statics are one record with several sites
    zapdos = [s for s in e["statics"] if 0x1AB63 in s[0]]
    assert len(zapdos) == 1 and set(zapdos[0][0]) == {0x1AC2D, 0x1EDAE, 0x1AB63}
    moltres = [s for s in e["statics"] if 0x4B730 in s[0]]
    assert len(moltres) == 1 and set(moltres[0][0]) == {0x4B730, 0x516C3}
    # (6) OldRodOffset is the first `lb bc` site, and both sites are listed
    assert e["OldRodOffset"] == 0xDEEA and e["OldRodOffsets"] == [0xDEEA, 0xDEEF]
    # class counts from trainers.json: 57 entries, index 0 = UPR's pad, JR_TRAINER_M = 10
    counts = e["TrainerDataClassCounts"]
    assert len(counts) == 57 and counts[0] == 0 and counts[5] == 10 and sum(counts) == 492
    assert e["TrainerClassCount"] == 56


def test_hidden_item_entry_points_shift_per_title():
    """Bank $1D code sits one byte later in Blue and two in Green — the one symbol-backed
    key family that is NOT title-identical, which is why the entries are generated per
    title rather than copied."""
    for i, t in enumerate(TITLES):
        e = load_entry(t, _INI)
        assert e["HiddenItemRoutine"] == 0x77352 + i
        assert e["HiddenItemRoutineEntries"] == [0x77352 + i, 0x7735A + i, 0x77362 + i, 0x7736A + i]


def test_non_dex_species_are_the_thirteen_opaque_ids():
    e = load_entry("purered", _INI)
    assert e["NonDexSpecies"] == [0x1F, 0x32, 0x34, 0x38, 0x56, 0x5E, 0x73, 0x86, 0x92, 0xAC, 0xAE, 0xAF, 0xB5]
    assert e["BaseStatsEntrySize"] == 35
    assert e["MewStatsOffset"] == e["PokemonStatsOffset"] + 150 * 35


@pytest.mark.skipif(not all(os.path.isfile(os.path.join(d, f"poke{t[4:]}.gbc"))
                            for d in (_ROMS, _OVERLAY_ROMS) for t in TITLES),
                    reason="pinned pure / overlay ROMs not present")
def test_the_committed_ini_is_what_the_generator_produces():
    assert gen.generate(pathlib.Path(_ROMS), pathlib.Path(_OVERLAY_ROMS)) == _INI.read_text(encoding="utf-8")
