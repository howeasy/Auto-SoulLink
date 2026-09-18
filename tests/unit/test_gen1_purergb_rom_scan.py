"""gen1_rom_scan's pureRGB support: admission-first identify(), the 35-byte/151-record
base stats shape, and the pure fishing walkers — checked against the built ROMs where
available, and skipped (never faked) where they are not.

The clean dumps this needs:
  - purered/pureblue/puregreen.gbc, built from pureRGB 7e7a4653 (see
    docs/purergb/PLAN.md M0/P1) — path taken from SLINK_PURERGB_ROMS or the location named
    in the P3b brief; skipped when absent.
  - the vanilla Red dump already checked into the repo root, used for the header-collision
    control: PureRed and vanilla Red share the header title "POKEMON RED", so identify()
    must tell them apart by sha1, not by header.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from server.adapters import _ROM_TYPE_TO_GAME_ID, available_game_ids
from server.adapters.gen1_rom_scan import (
    RomScanError,
    build_encounter_tables,
    identify,
    parse_client_content,
    scan_base_stats,
    scan_fishing,
    scan_wild,
)

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data" / "games" / "gen1_purergb"

# The P3b brief's own path, plus an env override for a different checkout.
_PURE_ROM_DIRS = [
    os.environ.get("SLINK_PURERGB_ROMS", ""),
    r"C:/Users/howar/AppData/Local/Temp/claude/E--Google-Drive-SLink--claude-worktrees-"
    r"recursing-hopper-86c382/27f97123-cfa0-473c-aed8-f288963eedeb/scratchpad/purergb",
]
_PURE_ROM_NAMES = {"purered": "pokered.gbc", "pureblue": "pokeblue.gbc", "puregreen": "pokegreen.gbc"}
_VANILLA_RED = REPO / "Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb"


def _find_pure_rom(title: str) -> str | None:
    name = _PURE_ROM_NAMES[title]
    for d in _PURE_ROM_DIRS:
        if d and os.path.isfile(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


def _pure_rom(title: str) -> bytes:
    path = _find_pure_rom(title)
    if not path:
        pytest.skip(f"no built pureRGB ROM for {title} — set SLINK_PURERGB_ROMS")
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture(params=["purered", "pureblue", "puregreen"])
def pure_rom(request) -> tuple[str, bytes]:
    return request.param, _pure_rom(request.param)


# ── identification ───────────────────────────────────────────────────────────────────────
def test_identify_labels_a_pure_rom_by_title(pure_rom):
    title, rom = pure_rom
    ident = identify(rom)
    assert ident["foundation"] == "gen1_purergb"
    assert ident["variant"] == title
    assert ident["clean"] is True


def test_identify_matches_the_admission_table_sha1(pure_rom):
    title, rom = pure_rom
    admission = json.loads((DATA / "admission.json").read_text(encoding="utf-8"))
    sha1 = hashlib.sha1(rom).hexdigest()
    assert sha1 in admission
    assert admission[sha1]["title"] == title
    assert identify(rom)["sha1"] == sha1


def test_identify_tells_a_vanilla_red_dump_from_a_pure_one_despite_the_same_header():
    """PureRed and vanilla Red share the header title "POKEMON RED" — the header-collision
    case docs/purergb/PLAN.md §11.2 trap 7 names. identify() must use the admission sha1
    table FIRST, not the header, or a pure ROM would be silently scanned as vanilla."""
    if not _VANILLA_RED.is_file():
        pytest.skip(f"vanilla clean Red dump absent: {_VANILLA_RED}")
    with open(_VANILLA_RED, "rb") as f:
        vanilla = f.read()
    ident = identify(vanilla)
    assert ident["foundation"] == "gen1_rby"
    assert ident["variant"] == "red"
    assert ident["clean"] is True

    pure = _pure_rom("purered")
    pure_ident = identify(pure)
    assert pure_ident["foundation"] == "gen1_purergb"
    assert pure_ident["sha1"] != ident["sha1"]


def test_identify_rejects_the_wrong_size():
    with pytest.raises(RomScanError):
        identify(b"\x00" * 10)


# ── base stats ───────────────────────────────────────────────────────────────────────────
def test_scan_base_stats_151_records_at_stride_35(pure_rom):
    _title, rom = pure_rom
    profile = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))
    derived = profile["titles"]["purered"]["derived"]
    assert derived["base_stats_stride"] == 35

    stats = scan_base_stats(rom)
    assert len(stats) == 151
    assert set(stats) == set(range(1, 152))
    # Bulbasaur, cross-checked against species_index.json's own stats_source: BaseStats:0.
    species = json.loads((DATA / "species_index.json").read_text(encoding="utf-8"))["species"]
    bulba = next(v for v in species.values() if v["dex"] == 1 and v["classification"] == "ordinary")
    assert stats[1]["hp"] == bulba["stats"]["hp"]
    assert stats[1]["attack"] == bulba["stats"]["atk"]
    assert stats[1]["type1"], stats[1]["type2"] == tuple(bulba["types"])


def test_scan_base_stats_has_no_separate_mew_record_but_still_gets_151(pure_rom):
    """PLAN.md §11.2 trap 5: pureRGB has NO MewBaseStats symbol at all; this must reach
    151 records (Mew inline as record 150) from profile.derived, not from a "MewBaseStats
    absent" coincidence that happens to also give 151 for the wrong reason."""
    title, rom = pure_rom
    from server.adapters.gen1_rom_scan import _pure_syms

    syms = _pure_syms(title)
    assert "MewBaseStats" not in syms
    stats = scan_base_stats(rom)
    assert stats[151]["hp"] == 100  # Mew, per docs/purergb/PLAN.md §11.2 A13 sample record


# ── wild / fishing ───────────────────────────────────────────────────────────────────────
def test_scan_wild_reproduces_a_shipped_grass_table(pure_rom):
    title, rom = pure_rom
    area_map = json.loads((DATA / "area_map.json").read_text(encoding="utf-8"))
    area_by_map = {int(k): v["area_id"] for k, v in area_map.items()}
    shipped = json.loads((DATA / "encounter_tables.json").read_text(encoding="utf-8"))[title]

    wild = scan_wild(rom)
    # Cross-check one map directly (map 0 = Pallet Town has no wild table; pick a map with
    # one instead) rather than the full encounter-table pipeline, which is exercised by
    # the adapter test and tools/gen_gen1_encounters.py's own contract test.
    assert wild, "scan_wild found no encounter maps at all"
    checked = 0
    for map_id, area_id in area_by_map.items():
        rec = wild.get(map_id)
        if not rec or not rec.get("grass"):
            continue
        shipped_grass = shipped.get(area_id, {}).get("Grass")
        if shipped_grass is None:
            continue
        species_here = {slot["species_index"] for slot in rec["grass"]["slots"]}
        shipped_species = {e["species_id"] for e in shipped_grass}
        if species_here == shipped_species:
            checked += 1
    assert checked > 0, "no grass table matched the shipped file by species set"


def test_scan_fishing_old_rod_is_the_50_50_choice(pure_rom):
    _title, rom = pure_rom
    fish = scan_fishing(rom)
    assert len(fish["old_rod"]) == 2
    assert {e["species_index"] for e in fish["old_rod"]} == {133, 157}  # Magikarp, Goldeen
    assert all(e["level"] == 10 for e in fish["old_rod"])


def test_scan_fishing_good_rod_has_four_entries_plus_an_ocean_table(pure_rom):
    _title, rom = pure_rom
    fish = scan_fishing(rom)
    assert len(fish["good_rod"]) == 4
    assert len(fish["good_rod_ocean"]) == 4
    assert fish["good_rod"] != fish["good_rod_ocean"]


def test_scan_fishing_super_rod_reuses_the_rb_format_unchanged(pure_rom):
    _title, rom = pure_rom
    fish = scan_fishing(rom)
    assert fish["super_rod"], "expected at least one super rod map"


# ── client-reported content (no ROM needed) ─────────────────────────────────────────────
def test_parse_client_content_accepts_a_pure_variant():
    grass = bytes([20] + [5, 153] * 10) + bytes([0])  # rate 20, ten (level 5, id 153) slots
    payload = {"variant": "purered", "wild": {"1": grass.hex()},
               "old_rod": bytes([133, 10, 157, 10]).hex(),
               "good_rod": bytes([16, 157, 16, 71, 16, 133, 18, 71]).hex(),
               "good_rod_ocean": bytes([16, 92, 16, 133, 16, 23, 16, 24]).hex()}
    content = parse_client_content(payload)
    assert content["variant"] == "purered"
    assert content["wild"][1]["grass"]["slots"][0]["species_index"] == 153
    assert len(content["fishing"]["old_rod"]) == 2
    assert len(content["fishing"]["good_rod"]) == 4
    assert len(content["fishing"]["good_rod_ocean"]) == 4


def test_parse_client_content_rejects_an_unknown_variant():
    with pytest.raises(RomScanError):
        parse_client_content({"variant": "puregarbage", "wild": {"1": "1400"}})


def test_parse_client_content_still_takes_vanillas_exact_old_good_rod_byte_counts():
    """Regression pin: vanilla's fixed 2-byte Old Rod / 4-byte Good Rod payloads must
    keep parsing to exactly 1 / 2 entries after generalising the pair count for pureRGB."""
    payload = {"variant": "red", "wild": {"1": bytes([20] + [5, 19] * 10 + [0]).hex()},
               "old_rod": bytes([129, 5]).hex(), "good_rod": bytes([10, 118, 20, 129]).hex()}
    content = parse_client_content(payload)
    assert len(content["fishing"]["old_rod"]) == 1
    assert len(content["fishing"]["good_rod"]) == 2
    assert "good_rod_ocean" not in content["fishing"]


def test_build_encounter_tables_uses_the_callers_floor_labels_not_vanillas():
    """A foundation whose maps are renumbered must not have vanilla's floor_labels.json
    silently applied to its own map ids (docs/purergb/PLAN.md §11.2 A13/W1)."""
    content = {"wild": {7: {"grass": {"rate": 20, "slots": [
        {"level": 5, "species_index": 1}] * 10}, "water": None}}, "fishing": {}}
    tables = build_encounter_tables(content, {7: "some_area"}, {1: 1}, str,
                                    floor_labels={"7": " CUSTOM_FLOOR"})
    assert "Grass CUSTOM_FLOOR" in tables["some_area"]
    # The default (no floor_labels kwarg) keeps reading vanilla's own file, unchanged.
    default_tables = build_encounter_tables(content, {7: "some_area"}, {1: 1}, str)
    assert "Grass CUSTOM_FLOOR" not in default_tables.get("some_area", {})


# ── registry consistency ─────────────────────────────────────────────────────────────────
def test_available_game_ids_covers_every_capability_generator_rom_type():
    from tools.gen_ui_capabilities import ROM_TYPES

    assert set(ROM_TYPES) == set(_ROM_TYPE_TO_GAME_ID)
    for rom_type in ROM_TYPES:
        assert _ROM_TYPE_TO_GAME_ID[rom_type] in available_game_ids()
