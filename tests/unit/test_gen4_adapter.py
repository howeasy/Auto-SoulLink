"""Tests for the Gen 4 HGSS/Pt adapter."""

import pytest
from server.adapters.gen4_hgsspt import Gen4Adapter


@pytest.fixture
def adapter():
    return Gen4Adapter()


# ── game_id ──────────────────────────────────────────────────────────────

def test_game_id(adapter):
    assert adapter.game_id == "gen4_hgsspt"


# ── Gift areas ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("area_id", [
    "new_bark_town",
    "route_30",
    "ruins_of_alph",
    "dragons_den",
    "goldenrod_city",
    "mt_mortar",
    "cianwood_city",
    "ilex_forest",
    "route_35",
])
def test_gift_areas_return_true(adapter, area_id):
    assert adapter.is_gift_area(area_id) is True


def test_gift_fallback_area(adapter):
    assert adapter.is_gift_area("gift") is True


def test_gift_prefix_area(adapter):
    assert adapter.is_gift_area("gift_something") is True


@pytest.mark.parametrize("area_id", [
    "route_1",
    "route_29",
    "national_park",
    "dark_cave",
    "bell_tower",
])
def test_non_gift_areas_return_false(adapter, area_id):
    assert adapter.is_gift_area(area_id) is False


# ── Platinum gift areas ──────────────────────────────────────────────────

@pytest.mark.parametrize("area_id", [
    "twinleaf_town",   # Starter
    "sandgem_town",    # Town events
    "eterna_city",     # Togepi egg / Cleffa
    "hearthome_city",  # Eevee from Bebe
    "iron_island",     # Riolu egg from Riley
    "veilstone_city",  # Porygon
    "route_212",       # Togepi egg from Cynthia
    "pal_park",        # Pal Park migrations
])
def test_platinum_gift_areas_return_true(adapter, area_id):
    assert adapter.is_gift_area(area_id) is True


def test_platinum_non_gift_area(adapter):
    """A Sinnoh route should not be a gift area."""
    assert adapter.is_gift_area("route_201") is False


def test_hgss_gift_areas_unaffected_by_platinum(adapter):
    """HGSS gifts must still be recognised even after Platinum gifts were added."""
    hgss_gifts = [
        "new_bark_town", "route_30", "ruins_of_alph", "dragons_den",
        "goldenrod_city", "mt_mortar", "cianwood_city", "ilex_forest", "route_35",
    ]
    for area_id in hgss_gifts:
        assert adapter.is_gift_area(area_id) is True, f"HGSS gift area {area_id!r} broken"


# ── PID:OTID key parsing ────────────────────────────────────────────────

def test_parse_ot_id_normal(adapter):
    assert adapter.parse_ot_id("AABBCCDD:11223344") == "11223344"


def test_parse_ot_id_lowercase(adapter):
    assert adapter.parse_ot_id("aabbccdd:11223344") == "11223344"


def test_parse_ot_id_invalid_no_colon(adapter):
    assert adapter.parse_ot_id("AABBCCDD") == ""


def test_parse_ot_id_empty(adapter):
    assert adapter.parse_ot_id("") == ""


# ── is_shiny ─────────────────────────────────────────────────────────────

def test_is_shiny_known_shiny(adapter):
    # Craft a shiny: tid ^ sid ^ p_hi ^ p_lo == 0
    # PID = 0x00000000, OTID = 0x00000000 → xor = 0 < 8 → shiny
    assert adapter.is_shiny("00000000:00000000") is True


def test_is_shiny_known_non_shiny(adapter):
    # PID = 0xFFFF0000, OTID = 0x00000000 → 0 ^ 0 ^ FFFF ^ 0 = 0xFFFF → not shiny
    assert adapter.is_shiny("FFFF0000:00000000") is False


def test_is_shiny_crafted_shiny(adapter):
    # PID = 0x12345678, OTID = TID=0x1234, SID=0x5678
    # p_hi=0x1234, p_lo=0x5678, tid=0x5678, sid=0x1234 (otid stored as SID<<16|TID)
    # But otid as u32 = 0x12345678 → tid=0x5678, sid=0x1234
    # xor = 0x5678 ^ 0x1234 ^ 0x1234 ^ 0x5678 = 0 < 8 → shiny
    assert adapter.is_shiny("12345678:12345678") is True


def test_is_shiny_invalid_key(adapter):
    assert adapter.is_shiny("not_a_key") is False


# ── species_name ─────────────────────────────────────────────────────────

def test_species_name_turtwig(adapter):
    assert adapter.species_name(387) == "Turtwig"


def test_species_name_arceus(adapter):
    assert adapter.species_name(493) == "Arceus"


def test_species_name_pikachu(adapter):
    assert adapter.species_name(25) == "Pikachu"


def test_species_name_unknown(adapter):
    assert adapter.species_name(99999) == "#99999"


# ── evo_family ───────────────────────────────────────────────────────────

def test_evo_family_turtwig_line(adapter):
    base = adapter.evo_family(387)
    assert adapter.evo_family(388) == base  # Grotle
    assert adapter.evo_family(389) == base  # Torterra


# ── gender_from_key ──────────────────────────────────────────────────────

def test_gender_male(adapter):
    # Nidoran♂ (32): gender ratio 0 → 100% male
    assert adapter.gender_from_key("00000001:12345678", 32) == "male"


def test_gender_female(adapter):
    # Chansey (113): gender ratio 254 → 100% female
    assert adapter.gender_from_key("00000001:12345678", 113) == "female"


def test_gender_genderless(adapter):
    # Magnemite (81): gender ratio 255 → genderless
    assert adapter.gender_from_key("00000001:12345678", 81) == "genderless"


def test_gender_pid_dependent(adapter):
    # Bulbasaur (1): gender ratio 31 → male if PID_low >= 31
    assert adapter.gender_from_key("000000FF:12345678", 1) == "male"
    assert adapter.gender_from_key("00000000:12345678", 1) == "female"


# ── species_types ────────────────────────────────────────────────────────

def test_species_types_fire(adapter):
    # Charmander (4): Fire
    types = adapter.species_types(4)
    assert types is not None
    assert len(types) >= 1


def test_species_types_dual(adapter):
    # Charizard (6): Fire/Flying
    types = adapter.species_types(6)
    assert types is not None
    assert len(types) == 2


# ── area_display_name ────────────────────────────────────────────────────

def test_area_display_name_fallback(adapter):
    name = adapter.area_display_name("unknown_area_xyz")
    assert "unknown" in name.lower() or "xyz" in name.lower()


def test_area_display_name_known(adapter):
    # Should resolve from area_map_hgss.json
    name = adapter.area_display_name("route_1")
    assert name  # non-empty


def test_evo_family_single_stage(adapter):
    # Pachirisu (NatDex 417) is single-stage
    assert adapter.evo_family(417) == 417


def test_evo_family_pikachu_line(adapter):
    # Pichu (172) → Pikachu (25) → Raichu (26)
    base = adapter.evo_family(172)
    assert adapter.evo_family(25) == base
    assert adapter.evo_family(26) == base


# ── is_valid_mon_key ─────────────────────────────────────────────────────

def test_valid_key(adapter):
    assert adapter.is_valid_mon_key("AABBCCDD:11223344") is True


def test_valid_key_short(adapter):
    assert adapter.is_valid_mon_key("1:2") is True


def test_invalid_key_no_colon(adapter):
    assert adapter.is_valid_mon_key("AABBCCDD11223344") is False


def test_invalid_key_non_hex(adapter):
    assert adapter.is_valid_mon_key("GGGGGGGG:11223344") is False


def test_invalid_key_empty(adapter):
    assert adapter.is_valid_mon_key("") is False


def test_invalid_key_too_many_parts(adapter):
    assert adapter.is_valid_mon_key("AA:BB:CC") is False


# ── to_national_dex (identity) ───────────────────────────────────────────

def test_to_national_dex_identity(adapter):
    assert adapter.to_national_dex(387) == 387
    assert adapter.to_national_dex(493) == 493
    assert adapter.to_national_dex(1) == 1


# ── Presentation ─────────────────────────────────────────────────────────

def test_sprite_html_contains_species_id(adapter):
    html = adapter.sprite_html(25)
    assert "25.png" in html
    assert "<img" in html


def test_sprite_html_zero(adapter):
    assert adapter.sprite_html(0) == ""


def test_item_name(adapter):
    assert adapter.item_name(44) == "Guard Spec."
    assert adapter.item_name(0) == ""


def test_area_display_name_fallback(adapter):
    # dark_cave has a display name in the area map; test true fallback with unknown area
    assert adapter.area_display_name("unknown_forest") == "Unknown Forest"


def test_form_sprite_id_always_none(adapter):
    assert adapter.form_sprite_id(25) is None
    assert adapter.form_sprite_id(493) is None


# ── Registry ─────────────────────────────────────────────────────────────

def test_adapter_registered():
    from server.adapters import get_adapter
    a = get_adapter("gen4_hgsspt")
    assert a.game_id == "gen4_hgsspt"


# ── ability_name species_id parameter is ignored ─────────────────────────────

def test_ability_name_species_id_ignored(adapter):
    """Gen 4 adapter ignores species_id — result must be the same with or without it."""
    base = adapter.ability_name(1)
    with_species = adapter.ability_name(1, species_id=999)
    assert with_species == base

def test_ability_name_species_id_does_not_inject_cfru_override(adapter):
    """Gen 4 adapter must not return an RR-specific override name even when an override species_id is passed."""
    # (121, 50) is "Tangling Hair" in RR — Gen 4 must return the plain vanilla name instead
    name = adapter.ability_name(121, species_id=50)
    assert name != "Tangling Hair"
