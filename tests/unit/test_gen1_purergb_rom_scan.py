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
    str(REPO / ".cache" / "purergb"),
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


# ── artifact kinds (A3 / A5): overlay by sha1, randomized by anchors ───────────────────────
def _overlay_rom(title: str) -> bytes:
    """The shipped UPS over the clean ROM, as the overlay tests build it."""
    import sys
    sys.path.insert(0, str(REPO / "patch" / "tools"))
    from make_ups import ups_apply
    admission_overlay = json.loads((DATA / "admission_overlay.json").read_text(encoding="utf-8"))
    ups = next(REPO / r["ups"] for r in admission_overlay.values() if r["title"] == title)
    return ups_apply(_pure_rom(title), ups.read_bytes())


def _randomized(rom: bytes, title: str) -> bytes:
    """Data tables changed, code untouched: what the fork's output looks like to identify()."""
    profile = json.loads((DATA / "profile.json").read_text(encoding="utf-8"))
    wild = profile["titles"][title]["rom"]["WildDataPointers"]["flat"]
    out = bytearray(rom)
    for i in range(0x200, 0x240):
        out[wild + i] ^= 0x5A
    return bytes(out)


def test_identify_names_the_overlay_artifact_with_its_clean_base(pure_rom):
    title, clean = pure_rom
    ident = identify(_overlay_rom(title))
    assert (ident["foundation"], ident["variant"], ident["kind"]) == ("gen1_purergb", title, "overlay")
    assert ident["clean"] is False and ident["pinned"] is True
    assert ident["clean_sha1"] == hashlib.sha1(clean).hexdigest()
    clean_ident = identify(clean)
    assert clean_ident["kind"] == "clean" and clean_ident["pinned"] is True


def test_identify_names_the_base_kind_of_a_randomized_artifact(pure_rom):
    title, clean = pure_rom
    rand = identify(_randomized(clean, title))
    assert (rand["kind"], rand["clean"], rand["pinned"]) == ("rand", False, False)
    assert rand["clean_sha1"] == hashlib.sha1(clean).hexdigest()
    overlay = _overlay_rom(title)
    rand_ov = identify(_randomized(overlay, title))
    assert (rand_ov["kind"], rand_ov["clean"], rand_ov["pinned"]) == ("rand_overlay", False, False)
    assert rand_ov["clean_sha1"] == hashlib.sha1(overlay).hexdigest()


def test_the_overlay_is_scanned_with_its_own_relocated_symbols(pure_rom):
    """GoodRodMons/ItemUseOldRod move in the overlay build; the clean symbols would read
    code as a fishing table."""
    title, clean = pure_rom
    overlay = _overlay_rom(title)
    assert scan_fishing(overlay) == scan_fishing(clean)
    assert scan_wild(overlay) == scan_wild(clean)
    assert scan_fishing(_randomized(overlay, title)) == scan_fishing(clean)


def test_a_vanilla_dump_reports_kind_clean_and_pinned():
    if not _VANILLA_RED.is_file():
        pytest.skip(f"vanilla clean Red dump absent: {_VANILLA_RED}")
    ident = identify(_VANILLA_RED.read_bytes())
    assert ident["kind"] == "clean" and ident["pinned"] is True


# ── the pipeline takes an overlay as a pinned source (A5) ─────────────────────────────────
def test_preflight_and_content_check_accept_an_overlay_source(tmp_path):
    from server.upr_pipeline import UprPipelineError, _check_content, jar_is_fork, preflight
    from tests.conftest import find_upr_jar
    jar = find_upr_jar()
    if not jar or not jar_is_fork(jar):
        pytest.skip("the SLink fork jar (4.6.1-slink1) is not present")
    clean = _pure_rom("purered")
    overlay = _overlay_rom("purered")
    src = tmp_path / "overlay.gbc"
    src.write_bytes(overlay)
    pre = preflight(jar, {"a": str(src)})
    assert pre["roms"]["a"]["kind"] == "overlay" and "overlay" in pre["roms"]["a"]["title"]
    assert pre["roms"]["a"]["clean"] is True, "a pinned overlay is a source the pipeline may start from"
    rand_src = tmp_path / "rand.gbc"
    rand_src.write_bytes(_randomized(clean, "purered"))
    assert preflight(jar, {"a": str(rand_src)})["roms"]["a"]["clean"] is False
    # a randomized overlay output from the overlay source passes; a rand output does not
    out = tmp_path / "out.gbc"
    out.write_bytes(_randomized(overlay, "purered"))
    _check_content(str(src), str(out))
    out.write_bytes(_randomized(clean, "purered"))
    with pytest.raises(UprPipelineError, match="rand artifact but the source was overlay"):
        _check_content(str(src), str(out))
    with pytest.raises(UprPipelineError, match="not a clean dump"):
        _check_content(str(rand_src), str(out))


def test_identify_refuses_a_pure_rom_whose_engine_site_changed(pure_rom):
    """Review cx-6aacc4f1 #3: a randomized artifact is admitted by anchors; a pure ROM matching
    NEITHER base kind's anchors has a code byte changed and must not be reported as `rand`
    against the clean base (the pipeline would then contract a ROM the Lua gate refuses)."""
    from server.adapters.gen1_rom_scan import RomScanError
    title, clean = pure_rom
    sites = json.loads((DATA / "engine_signals.json").read_text(encoding="utf-8"))
    site = sites["titles"][title]["sites"]["add_party_mon"]
    broken = bytearray(_randomized(clean, title))
    broken[site["rom_offset"]] ^= 0xFF
    with pytest.raises(RomScanError, match="modified engine site"):
        identify(bytes(broken))
