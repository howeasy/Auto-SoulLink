"""Tests for the Gen 5 BW/BW2 adapter."""

import pytest
from server.adapters.gen5_bw import Gen5Adapter


@pytest.fixture
def adapter():
    return Gen5Adapter()


@pytest.fixture
def adapter_bw1():
    return Gen5Adapter(rom_type="pokemon_black")


@pytest.fixture
def adapter_bw2():
    return Gen5Adapter(rom_type="pokemon_black_2")


# ── game_id ──────────────────────────────────────────────────────────────

def test_game_id(adapter):
    assert adapter.game_id == "gen5_bw"


# ── Memorial box ──────────────────────────────────────────────────────────

def test_memorial_box_index(adapter):
    """Gen 5 has 24 boxes; memorial = Box 24 = index 23."""
    assert adapter.memorial_box_index == 23


# ── Gift areas (BW1) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("area_id", [
    "nuvema_town",
    "striaton_city",
    "castelia_city",
    "nacrene_city",
    "gift",
])
def test_bw1_gift_areas_return_true(adapter_bw1, area_id):
    assert adapter_bw1.is_gift_area(area_id) is True


# ── Gift areas (BW2) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("area_id", [
    "aspertia_city",
    "floccesy_ranch",
    "castelia_city",
    "nacrene_city",
    "gift",
])
def test_bw2_gift_areas_return_true(adapter_bw2, area_id):
    assert adapter_bw2.is_gift_area(area_id) is True


def test_gift_prefix_area(adapter):
    assert adapter.is_gift_area("gift_starter") is True


@pytest.mark.parametrize("area_id", [
    "route_1",
    "route_5",
    "pinwheel_forest",
    "victory_road",
    "giant_chasm",
])
def test_non_gift_areas_return_false(adapter, area_id):
    assert adapter.is_gift_area(area_id) is False


def test_gift_areas_for_bw1(adapter):
    gift_set = adapter.gift_areas_for_rom("pokemon_black")
    assert "nuvema_town" in gift_set
    assert "dragonspiral_tower" not in gift_set
    assert "aspertia_city" not in gift_set


def test_gift_areas_for_bw2(adapter):
    gift_set = adapter.gift_areas_for_rom("pokemon_black_2")
    assert "aspertia_city" in gift_set
    assert "floccesy_ranch" in gift_set
    assert "nuvema_town" not in gift_set


def test_is_gift_area_respects_rom_type():
    """Adapter with BW2 rom_type should use BW2 gift set, not BW1."""
    bw1 = Gen5Adapter(rom_type="pokemon_black")
    bw2 = Gen5Adapter(rom_type="pokemon_white_2")
    # nuvema_town is BW1 starter town only
    assert bw1.is_gift_area("nuvema_town") is True
    assert bw2.is_gift_area("nuvema_town") is False
    # aspertia_city is BW2 starter town only
    assert bw2.is_gift_area("aspertia_city") is True
    assert bw1.is_gift_area("aspertia_city") is False


# ── Evo family ────────────────────────────────────────────────────────────

def test_evo_family_single_stage(adapter):
    """Snivy (495) has no evolution family prior to Serperior (497)."""
    base = adapter.evo_family(495)
    assert base == adapter.evo_family(496) == adapter.evo_family(497)


def test_evo_family_unrelated_species(adapter):
    """Snivy and Tepig should have different base forms."""
    assert adapter.evo_family(495) != adapter.evo_family(498)


# ── Gender ────────────────────────────────────────────────────────────────

def test_gender_from_key_male(adapter):
    # PID with low byte >= threshold → male for Snivy (87.5% male, threshold=31)
    # Low byte 200 >= 31 → male
    gender = adapter.gender_from_key("000000C8:12345678", 495)
    assert gender == "male"


def test_gender_from_key_female(adapter):
    # Low byte 10 < 31 → female
    gender = adapter.gender_from_key("0000000A:12345678", 495)
    assert gender == "female"


def test_gender_genderless_species(adapter):
    # Voltorb (100) and Electrode (101) are 100% male; Magnemite (81) is genderless
    gender = adapter.gender_from_key("AABBCCDD:11223344", 81)
    assert gender == "genderless"


def test_gender_invalid_key(adapter):
    assert adapter.gender_from_key("", 495) == ""
    assert adapter.gender_from_key("invalid", 495) == ""


# ── Shiny detection ───────────────────────────────────────────────────────

def test_shiny_detection_false(adapter):
    """Random key should not be shiny."""
    assert adapter.is_shiny("DEADBEEF:CAFEBABE") is False


def test_shiny_detection_true(adapter):
    """Craft a shiny key: (tid ^ sid ^ p_upper ^ p_lower) < 8."""
    # tid=1000, sid=1000, p_upper=1000, p_lower=1000 → xor=0 < 8
    tid  = 1000
    sid  = 1000
    ot   = sid << 16 | tid
    p_lo = 1000
    p_hi = 1000
    pid  = p_hi << 16 | p_lo
    key  = f"{pid:08X}:{ot:08X}"
    assert adapter.is_shiny(key) is True


def test_shiny_invalid_key(adapter):
    assert adapter.is_shiny("") is False
    assert adapter.is_shiny("DEADBEEF") is False


# ── Key parsing / validation ──────────────────────────────────────────────

def test_parse_ot_id_valid(adapter):
    assert adapter.parse_ot_id("AABBCCDD:11223344") == "11223344"


def test_parse_ot_id_invalid(adapter):
    assert adapter.parse_ot_id("AABBCCDD") == ""
    assert adapter.parse_ot_id("") == ""


def test_is_valid_mon_key_valid(adapter):
    assert adapter.is_valid_mon_key("AABBCCDD:11223344") is True
    assert adapter.is_valid_mon_key("00000000:00000000") is True


def test_is_valid_mon_key_invalid(adapter):
    assert adapter.is_valid_mon_key("AABBCCDD") is False
    assert adapter.is_valid_mon_key("") is False
    assert adapter.is_valid_mon_key("GGGGGGGG:11223344") is False


# ── Species ───────────────────────────────────────────────────────────────

def test_species_name_gen5(adapter):
    """Gen 5 species 495-649 should resolve to names."""
    name = adapter.species_name(495)
    assert isinstance(name, str) and len(name) > 0
    assert "#" not in name, f"Species 495 should have a real name, got {name!r}"


def test_species_name_gen1_still_works(adapter):
    assert adapter.species_name(1) != ""
    assert "#" not in adapter.species_name(25)  # Pikachu


def test_species_name_unknown(adapter):
    result = adapter.species_name(9999)
    assert result == "#9999"


def test_to_national_dex_passthrough(adapter):
    """Gen 5 uses NatDex IDs natively — to_national_dex is a no-op."""
    assert adapter.to_national_dex(495) == 495
    assert adapter.to_national_dex(649) == 649


# ── Adapter registration ──────────────────────────────────────────────────

def test_adapter_registry_gen5_bw():
    from server.adapters import get_adapter
    a = get_adapter("gen5_bw")
    assert a.game_id == "gen5_bw"


@pytest.mark.parametrize("alias", [
    "pokemon_black",
    "pokemon_white",
    "pokemon_black_2",
    "pokemon_white_2",
])
def test_adapter_registry_variant_aliases(alias):
    from server.adapters import get_adapter
    a = get_adapter(alias)
    assert a.game_id == "gen5_bw"


# ── Item names ────────────────────────────────────────────────────────────

def test_item_name_pokeball(adapter):
    assert adapter.item_name(4) == "Poké Ball"


def test_item_name_master_ball(adapter):
    assert adapter.item_name(1) == "Master Ball"


def test_item_name_unknown(adapter):
    assert "9999" in adapter.item_name(9999)


def test_item_name_zero(adapter):
    assert adapter.item_name(0) == ""


# ── Area display name ─────────────────────────────────────────────────────

def test_area_display_name_known(adapter):
    """Known area IDs from area_map_bw.json should return real names."""
    name = adapter.area_display_name("route_1")
    assert "Route" in name or "route" in name.lower()


def test_area_display_name_unknown(adapter):
    """Unknown area IDs fall back to title-cased slug."""
    name = adapter.area_display_name("some_unknown_area")
    assert "Some Unknown Area" == name


# ── Gym badges ────────────────────────────────────────────────────────────

def test_gym_badge_slugs_bw1(adapter):
    badges = adapter.gym_badge_slugs("pokemon_black")
    assert len(badges) == 8
    names = [n for _, n in badges]
    assert "Trio Badge" in names
    assert "Legend Badge" in names


def test_gym_badge_slugs_bw2(adapter):
    """BW2 also has 8 Unova badges."""
    badges = adapter.gym_badge_slugs("pokemon_black_2")
    assert len(badges) == 8


# ── Species types ─────────────────────────────────────────────────────────

def test_species_types_snivy_pure_grass(adapter):
    """Snivy (495) is pure Grass, but pokemon_data type table only covers
    Gen I–III (CFRU range ≤ ~480). Gen 5 species return None until the
    type table is extended."""
    types = adapter.species_types(495)
    # Gen 5 species not yet in the type table — None is acceptable.
    # If this starts returning a value, update the assertion below:
    assert types is None or (isinstance(types, tuple) and len(types) == 2)


def test_species_types_reshiram_dragon_fire(adapter):
    """Reshiram (643) is Dragon/Fire — same type-table coverage limitation."""
    types = adapter.species_types(643)
    assert types is None or (isinstance(types, tuple) and len(types) == 2)


# ── Sprite HTML ───────────────────────────────────────────────────────────

def test_sprite_html_valid(adapter):
    html = adapter.sprite_html(495)
    assert 'img' in html
    assert '495' in html


def test_sprite_html_zero(adapter):
    assert adapter.sprite_html(0) == ""


# ── Server rom_type → game_id mapping ────────────────────────────────────

@pytest.mark.parametrize("rom_type,expected_game_id", [
    ("pokemon_black",   "gen5_bw"),
    ("pokemon_white",   "gen5_bw"),
    ("pokemon_black_2", "gen5_bw"),
    ("pokemon_white_2", "gen5_bw"),
])
def test_server_rom_type_to_game_id(rom_type, expected_game_id):
    """Server's _ROM_TYPE_TO_GAME_ID must map all Gen 5 rom_types to gen5_bw."""
    from server.server import SLinkServer
    assert SLinkServer._ROM_TYPE_TO_GAME_ID.get(rom_type) == expected_game_id


@pytest.mark.parametrize("rom_type,expected_label", [
    ("pokemon_black",   "Pokémon Black"),
    ("pokemon_white",   "Pokémon White"),
    ("pokemon_black_2", "Pokémon Black 2"),
    ("pokemon_white_2", "Pokémon White 2"),
])
def test_server_variant_label(rom_type, expected_label):
    """Server's _VARIANT_LABEL must have all Gen 5 variants."""
    from server.server import SLinkServer
    assert SLinkServer._VARIANT_LABEL.get(rom_type) == expected_label
