"""Gen1PureRGBAdapter contract, checked against the pure data pack directly.

Mirrors the vanilla contract tests' spirit (facts from the pack, not from memory) without
duplicating them: this file exercises the ADAPTER surface (server/adapters/gen1_purergb.py)
against data/games/gen1_purergb/*.json, which tests/unit/test_gen1_purergb_species.py and
friends already validate as generated-correctly. What this file checks is that the adapter
reads those files the way the platform's rules/presentation layers expect.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.adapters import _ROM_TYPE_TO_GAME_ID, available_game_ids, get_adapter
from server.adapters.gen1_purergb import Gen1PureRGBAdapter

DATA = Path(__file__).resolve().parents[2] / "data" / "games" / "gen1_purergb"


def _json(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Override the repository's disk-writing state fixture in this read-only suite."""
    yield


@pytest.fixture(params=["PureRed", "PureBlue", "PureGreen"])
def adapter(request) -> Gen1PureRGBAdapter:
    return get_adapter("gen1_purergb", rom_type=request.param)


# ── registration ─────────────────────────────────────────────────────────────────────────
def test_every_rom_type_to_game_id_row_resolves_to_a_registered_adapter():
    for rom_type, game_id in _ROM_TYPE_TO_GAME_ID.items():
        assert game_id in available_game_ids(), (rom_type, game_id)


def test_the_three_pure_rom_types_route_to_gen1_purergb():
    for rom_type in ("PureRed", "PureBlue", "PureGreen", "purered", "pureblue", "puregreen"):
        assert _ROM_TYPE_TO_GAME_ID[rom_type] == "gen1_purergb"


def test_unknown_variant_raises_instead_of_defaulting():
    with pytest.raises(ValueError):
        Gen1PureRGBAdapter(rom_type="PureYellow")
    # A genuinely absent (or falsy) rom_type is allowed to default to PureRed, matching
    # Gen1Adapter's own rule; only a NAMED, unrecognised variant must fail closed.
    assert Gen1PureRGBAdapter().game_id == "gen1_purergb"
    assert Gen1PureRGBAdapter(rom_type="").game_id == "gen1_purergb"


def test_game_id(adapter):
    assert adapter.game_id == "gen1_purergb"


# ── species / types / evolutions ─────────────────────────────────────────────────────────
def test_floating_magneton_types_are_electric_floating(adapter):
    # docs/purergb/research/p3/server_literals_bbcd037.md's own example: internal id 56
    # (Floating Magneton, a form of Magneton) is typed [23, 18] = Electric/Floating.
    assert adapter.species_types(56) == (23, 18)


def test_missingno_is_a_species_not_a_hole(adapter):
    # Internal id 181 ($B5) is dex 0 but a real, catchable, complete-record species —
    # never treated as "no species" (to_national_dex returning 0 is a real dex number).
    assert adapter.to_national_dex(181) == 0
    assert adapter.species_name(181) == "Missingno."
    assert adapter.species_types(181) is not None


def test_ordinary_species_keep_vanillas_display_name(adapter):
    species = _json("species_index.json")["species"]
    bulbasaur_id = next(int(k) for k, v in species.items()
                        if v["classification"] == "ordinary" and v["dex"] == 1)
    assert adapter.species_name(bulbasaur_id) == "Bulbasaur"


def test_evo_family_of_a_form_resolves_through_base_species(adapter):
    # Floating Magneton (56) is a form of Magneton (54, its own family's representative).
    assert adapter.evo_family(56) == adapter.evo_family(54)
    assert adapter.evo_family(54) == 54


def test_evo_family_composes(adapter):
    # A family lookup must be a fixed point: evo_family(evo_family(x)) == evo_family(x),
    # the same invariant the vanilla adapter's docstring names.
    for species_id in range(1, 191):
        fam = adapter.evo_family(species_id)
        assert adapter.evo_family(fam) == fam, species_id


def test_missingno_and_unused_slots_are_their_own_family(adapter):
    assert adapter.evo_family(181) == 181


# ── trainers ─────────────────────────────────────────────────────────────────────────────
def test_rival_trainer_ids(adapter):
    assert adapter.rival_trainer_ids() == {221, 237, 238}


def test_trainer_info_for_a_generic_class(adapter):
    name, cls = adapter.trainer_info(198)  # YOUNGSTER
    assert cls == "Youngster"


def test_trainer_info_for_a_rival_slot_has_no_fixed_name(adapter):
    name, cls = adapter.trainer_info(221)
    assert name == ""
    assert cls == "Rival"


def test_trainer_info_for_an_unknown_id_is_blank(adapter):
    assert adapter.trainer_info(9999) == ("", "")


# ── statics / gift areas ─────────────────────────────────────────────────────────────────
def test_missingno_static_site_is_a_gift_area_with_dex_zero(adapter):
    # map 107 -> internal 181 (MISSINGNO, dex 0): the static namespace must admit dex 0
    # rather than treating it as "not a species" (PLAN.md §11.2 trap: _STATIC_ID's \d+).
    assert adapter.is_gift_area("static_107_0")
    assert adapter.is_fixed_species_gift("static_107_0")
    assert "MISSINGNO." in adapter.area_display_name("static_107_0")


def test_a_random_area_is_not_a_gift_area(adapter):
    assert not adapter.is_gift_area("route_1")
    assert not adapter.is_gift_area("static_999_150")


def test_area_display_name_for_an_ordinary_area(adapter):
    assert adapter.area_display_name("pallet_town") == "Pallet Town"


# ── items / moves ────────────────────────────────────────────────────────────────────────
def test_item_name_hyper_ball_replaces_town_map_at_5(adapter):
    # pureRGB's item $05 is HYPER_BALL, unlike vanilla's TOWN_MAP.
    assert adapter.item_name(5) == "Hyper Ball"


def test_item_name_of_zero_is_blank(adapter):
    assert adapter.item_name(0) == ""


def test_move_data_pound(adapter):
    data = adapter.move_data(1)
    assert data["name"] == "Pound"
    assert data["type_name"] == "Normal"
    assert data["power"] == 40


def test_move_data_unknown_is_none(adapter):
    assert adapter.move_data(999) is None


# ── encounters ───────────────────────────────────────────────────────────────────────────
def test_encounter_table_species_ids_are_already_internal(adapter):
    """encounter_tables.json declares species_id_space "internal" — unlike vanilla's
    NatDex-keyed file, encounter_table() must NOT run these through natdex_to_internal."""
    raw = _json("encounter_tables.json")
    assert raw["species_id_space"] == "internal"
    variant = adapter._variant
    area_id, methods = next((a, m) for a, m in raw[variant].items() if "Grass" in m or "Water" in m)
    method = "Grass" if "Grass" in methods else "Water"
    expected = methods[method]
    got = adapter.encounter_table(area_id)[method]
    assert got == expected


def test_encounter_table_missing_area_is_none(adapter):
    assert adapter.encounter_table("not_a_real_area") is None


# ── geometry / capabilities (inherited from Gen1Adapter, PLAN.md §4 row 4) ────────────────
def test_party_blob_geometry_is_unchanged(adapter):
    assert adapter.party_blob_size() == 66
    assert adapter.mons_per_box == 20
    assert adapter.memorial_box_index == 11


def test_no_native_ui_until_the_overlay_lands(adapter):
    assert adapter.supports_info_panel() is False
    assert adapter.native_trade_ui() is False
    assert adapter.info_panel_width() == 0


def test_no_gender_or_shiny_mechanic(adapter):
    assert adapter.gender_from_key("x", 1) == ""
    assert adapter.is_shiny("x") is False


def test_validate_party_blob_accepts_a_missingno_mon(adapter):
    from server.adapters import gen1_codec

    mon = {
        "species": 181, "hp": 255, "box_level": 5, "status": 0, "catch_rate": 3,
        "ot_id": 1, "exp": 100, "types": [8, 0], "moves": [1, 2, 3, 4],
        "stat_exp": {"hp": 0, "atk": 0, "def": 0, "spd": 0, "spc": 0},
        "dvs": gen1_codec._dv_parts(0), "pp": [10, 10, 10, 10], "pp_ups": [0, 0, 0, 0],
        "level": 5, "box": False,
        "max_hp": 100, "atk": 50, "def": 50, "spd": 50, "spc": 50,
    }
    blob = gen1_codec.encode_party_mon(mon) + gen1_codec.encode_name("A") + gen1_codec.encode_name("B")
    assert adapter.validate_party_blob(blob) is True


def test_validate_party_blob_rejects_wrong_length(adapter):
    assert adapter.validate_party_blob(b"\x00" * 10) is False


# ── ROM-content ingestion (a client-reported payload, no ROM file needed) ────────────────
def test_ingest_rom_content_reports_internal_ids_not_national_dex(adapter):
    grass = bytes([20] + [5, 153] * 10) + bytes([0])  # ten slots of internal id 153 (Bulbasaur)
    payload = {"variant": adapter._variant, "wild": {"1": grass.hex()},
               "old_rod": bytes([133, 10, 157, 10]).hex(),
               "good_rod": bytes([16, 157, 16, 71, 16, 133, 18, 71]).hex(),
               "good_rod_ocean": bytes([16, 92, 16, 133, 16, 23, 16, 24]).hex()}
    tables = adapter.ingest_rom_content(payload)
    area = next(iter(tables))
    entry = tables[area]["Grass"][0]
    assert entry["species_id"] == 153          # internal id, unconverted
    assert entry["name"] == "Bulbasaur"


def test_ingest_rom_content_uses_the_pure_packs_own_floor_labels(adapter):
    floor_labels = _json("floor_labels.json")
    labeled_map = next(int(k) for k in floor_labels)
    area_map = _json("area_map.json")
    area_id = area_map[str(labeled_map)]["area_id"]
    grass = bytes([20] + [5, 153] * 10) + bytes([0])
    payload = {"variant": adapter._variant, "wild": {str(labeled_map): grass.hex()}}
    tables = adapter.ingest_rom_content(payload)
    method = next(iter(tables[area_id]))
    assert method.endswith(floor_labels[str(labeled_map)])


def test_rom_content_fingerprint_is_stable_and_reproducible(adapter):
    payload = {"variant": adapter._variant,
               "wild": {"1": (bytes([20] + [5, 153] * 10) + bytes([0])).hex()},
               "old_rod": "", "good_rod": "", "good_rod_ocean": ""}
    assert adapter.rom_content_fingerprint(payload) == adapter.rom_content_fingerprint(payload)
