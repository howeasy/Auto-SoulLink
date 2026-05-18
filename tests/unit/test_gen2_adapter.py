"""Tests for the Gen 2 Crystal adapter."""

import pytest
from server.adapters.gen2_crystal import Gen2CrystalAdapter


@pytest.fixture
def adapter():
    return Gen2CrystalAdapter()


# ── game_id ──────────────────────────────────────────────────────────────

def test_game_id(adapter):
    assert adapter.game_id == "gen2_crystal"


def test_adapter_instantiation():
    a = Gen2CrystalAdapter()
    assert a is not None
    assert a.game_id == "gen2_crystal"


# ── Gift areas ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("area_id", [
    "new_bark_town",     # Starter
    "goldenrod_city",    # Eevee from Bill / Game Corner
    "olivine_city",      # Shuckle from Kirk
    "dragons_den",       # Dratini from Elder
    "route_35",          # Kenya the Spearow
    "mt_mortar",         # Tyrogue from Kiyo
    "cianwood_city",     # Shuckle from Kirk
    "celadon_city",      # Eevee (Kanto gift)
    "gift",              # Fallback
])
def test_gift_areas_return_true(adapter, area_id):
    assert adapter.is_gift_area(area_id) is True


def test_gift_prefix_area(adapter):
    assert adapter.is_gift_area("gift_something") is True


def test_gift_prefix_area_2(adapter):
    assert adapter.is_gift_area("gift_odd_egg") is True


@pytest.mark.parametrize("area_id", [
    "route_29",
    "route_34",          # daycare area, NOT gift — wild captures here use normal flow
    "dark_cave",
    "sprout_tower",
    "ilex_forest",
    "union_cave",
])
def test_non_gift_areas_return_false(adapter, area_id):
    assert adapter.is_gift_area(area_id) is False


# ── Daycare areas (Phase 1d) ────────────────────────────────────────────

def test_route_34_is_daycare(adapter):
    """Route 34 hosts the Day-Care Man — bred eggs and the Odd Egg both originate here."""
    assert adapter.is_daycare_area("route_34") is True


@pytest.mark.parametrize("area_id", [
    "new_bark_town",
    "goldenrod_city",
    "route_30",          # Mystery Egg from Mr. Pokemon — NOT daycare (egg=gift)
    "route_29",
    "ilex_forest",
])
def test_non_daycare_areas_return_false(adapter, area_id):
    assert adapter.is_daycare_area(area_id) is False


# ── Key validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "ABCD:1234:01",
    "0000:0000:FB",
    "FFFF:FFFF:01",
    "abcd:1234:01",      # lowercase hex is valid
    "A5F3:EF01:9A",
    "1111:2222:0A",
    "DEAD:BEEF:FF",
])
def test_valid_keys(adapter, key):
    assert adapter.is_valid_mon_key(key) is True


@pytest.mark.parametrize("key,reason", [
    ("", "empty string"),
    ("ABCD:1234", "too few colons / missing species"),
    ("ABCD1234:01", "missing middle colon"),
    ("GGGG:1234:01", "non-hex chars in DVs"),
    ("ABCD:ZZZZ:01", "non-hex chars in OTID"),
    ("ABCD:1234:GG", "non-hex chars in species"),
    ("ABCD:1234:999", "species index too long"),
    ("ABCDE:1234:01", "DV too long"),
    ("ABC:1234:01", "DV too short"),
    ("ABCD:12345:01", "OTID too long"),
    ("ABCD:123:01", "OTID too short"),
])
def test_invalid_keys(adapter, key, reason):
    assert adapter.is_valid_mon_key(key) is False, reason


# ── parse_ot_id ──────────────────────────────────────────────────────────

def test_parse_ot_id_normal(adapter):
    assert adapter.parse_ot_id("ABCD:1234:01") == "1234"


def test_parse_ot_id_hex(adapter):
    assert adapter.parse_ot_id("0000:ABCD:FF") == "ABCD"


def test_parse_ot_id_invalid_key(adapter):
    assert adapter.parse_ot_id("nocolon") == ""


def test_parse_ot_id_empty(adapter):
    assert adapter.parse_ot_id("") == ""


# ── is_shiny ─────────────────────────────────────────────────────────────
# Shiny requires: Def=A(10), Spd=A(10), Spc=A(10), Atk∈{2,3,6,7,A,B,E,F}
# Key format DDDD where D1=Atk, D2=Def, D3=Spd, D4=Spc

@pytest.mark.parametrize("key,expected,reason", [
    # Shiny cases: Def=A, Spd=A, Spc=A, Atk in {2,3,6,7,A,B,E,F}
    ("2AAA:1234:01", True,  "Atk=2, all others A"),
    ("3AAA:1234:01", True,  "Atk=3"),
    ("6AAA:1234:01", True,  "Atk=6"),
    ("7AAA:1234:01", True,  "Atk=7"),
    ("AAAA:1234:01", True,  "Atk=A(10)"),
    ("BAAA:1234:01", True,  "Atk=B(11)"),
    ("EAAA:1234:01", True,  "Atk=E(14)"),
    ("FAAA:1234:01", True,  "Atk=F(15)"),
    # Not shiny: Atk not in valid set
    ("0AAA:1234:01", False, "Atk=0, not in valid set"),
    ("1AAA:1234:01", False, "Atk=1"),
    ("4AAA:1234:01", False, "Atk=4"),
    ("5AAA:1234:01", False, "Atk=5"),
    ("8AAA:1234:01", False, "Atk=8"),
    ("9AAA:1234:01", False, "Atk=9"),
    ("CAAA:1234:01", False, "Atk=C(12)"),
    ("DAAA:1234:01", False, "Atk=D(13)"),
    # Not shiny: Def/Spd/Spc not 10(A)
    ("A9AA:1234:01", False, "Def=9, not 10"),
    ("AA9A:1234:01", False, "Spd=9, not 10"),
    ("AAA9:1234:01", False, "Spc=9, not 10"),
    ("ABAA:1234:01", False, "Def=B(11), not 10"),
    # All zeros — not shiny
    ("0000:0000:01", False, "all zero DVs"),
])
def test_is_shiny(adapter, key, expected, reason):
    assert adapter.is_shiny(key) is expected, reason


def test_is_shiny_invalid_key(adapter):
    assert adapter.is_shiny("bad") is False


# ── gender_from_key ──────────────────────────────────────────────────────
# Gen 2 gender: Atk DV (first hex digit) vs floor(ratio / 16)
# female if atk_dv <= threshold

class TestGenderFromKey:
    """Gender derivation from DVs and species gender ratio."""

    def test_genderless_magnemite(self, adapter):
        # Magnemite (81): ratio=255 → genderless
        assert adapter.gender_from_key("AAAA:1234:51", 81) == "genderless"

    def test_genderless_unown(self, adapter):
        # Unown (201): ratio=255 → genderless
        assert adapter.gender_from_key("5555:1234:C9", 201) == "genderless"

    def test_always_male_tauros(self, adapter):
        # Tauros (128): ratio=0 → always male regardless of Atk DV
        assert adapter.gender_from_key("0000:1234:80", 128) == "male"
        assert adapter.gender_from_key("FFFF:1234:80", 128) == "male"

    def test_always_female_miltank(self, adapter):
        # Miltank (241): ratio=254 → always female regardless of Atk DV
        assert adapter.gender_from_key("FFFF:1234:F1", 241) == "female"
        assert adapter.gender_from_key("0000:1234:F1", 241) == "female"

    def test_50_50_species_female(self, adapter):
        # Pichu (172): ratio=127 → threshold=7 → Atk 0-7 = female
        assert adapter.gender_from_key("0AAA:1234:AC", 172) == "female"  # Atk=0
        assert adapter.gender_from_key("7AAA:1234:AC", 172) == "female"  # Atk=7 (boundary)

    def test_50_50_species_male(self, adapter):
        # Pichu (172): ratio=127 → threshold=7 → Atk 8-15 = male
        assert adapter.gender_from_key("8AAA:1234:AC", 172) == "male"   # Atk=8 (boundary)
        assert adapter.gender_from_key("FAAA:1234:AC", 172) == "male"   # Atk=F(15)

    def test_12_5_percent_female_starter(self, adapter):
        # Chikorita (152): ratio=31 → threshold=1 → Atk 0-1 = female
        assert adapter.gender_from_key("0AAA:1234:98", 152) == "female"  # Atk=0
        assert adapter.gender_from_key("1AAA:1234:98", 152) == "female"  # Atk=1 (boundary)
        assert adapter.gender_from_key("2AAA:1234:98", 152) == "male"   # Atk=2 (just over)
        assert adapter.gender_from_key("FAAA:1234:98", 152) == "male"   # Atk=F

    def test_75_percent_female_clefairy(self, adapter):
        # Clefairy (35): ratio=191 → threshold=11 → Atk 0-11 = female, 12-15 = male
        assert adapter.gender_from_key("0AAA:1234:23", 35) == "female"  # Atk=0
        assert adapter.gender_from_key("BAAA:1234:23", 35) == "female"  # Atk=B(11) boundary
        assert adapter.gender_from_key("CAAA:1234:23", 35) == "male"   # Atk=C(12) just over
        assert adapter.gender_from_key("FAAA:1234:23", 35) == "male"   # Atk=F

    def test_empty_key(self, adapter):
        assert adapter.gender_from_key("", 25) == ""

    def test_zero_species(self, adapter):
        assert adapter.gender_from_key("AAAA:1234:01", 0) == ""


# ── gender_symbol ────────────────────────────────────────────────────────

def test_gender_symbol_male(adapter):
    assert adapter.gender_symbol("male") == "♂"


def test_gender_symbol_female(adapter):
    assert adapter.gender_symbol("female") == "♀"


def test_gender_symbol_genderless(adapter):
    assert adapter.gender_symbol("genderless") == ""


def test_gender_symbol_unknown(adapter):
    assert adapter.gender_symbol("unknown") == ""


# ── species_name ─────────────────────────────────────────────────────────

def test_species_name_bulbasaur(adapter):
    assert adapter.species_name(1) == "Bulbasaur"


def test_species_name_chikorita(adapter):
    assert adapter.species_name(152) == "Chikorita"


def test_species_name_celebi(adapter):
    assert adapter.species_name(251) == "Celebi"


def test_species_name_lugia(adapter):
    assert adapter.species_name(249) == "Lugia"


def test_species_name_unknown_zero(adapter):
    assert adapter.species_name(0) == "#0"


def test_species_name_unknown_high(adapter):
    assert adapter.species_name(999) == "#999"


# ── evo_family ───────────────────────────────────────────────────────────

def test_evo_family_chikorita_line(adapter):
    base = adapter.evo_family(152)
    assert adapter.evo_family(153) == base  # Bayleef
    assert adapter.evo_family(154) == base  # Meganium


def test_evo_family_crobat_zubat(adapter):
    # Crobat (169) evolves from Golbat (42) which evolves from Zubat (41)
    base = adapter.evo_family(41)
    assert adapter.evo_family(42) == base   # Golbat
    assert adapter.evo_family(169) == base  # Crobat


def test_evo_family_eevee_gen2_evos(adapter):
    base = adapter.evo_family(133)
    assert adapter.evo_family(196) == base  # Espeon
    assert adapter.evo_family(197) == base  # Umbreon
    # Gen 1 evolutions should also match
    assert adapter.evo_family(134) == base  # Vaporeon
    assert adapter.evo_family(135) == base  # Jolteon
    assert adapter.evo_family(136) == base  # Flareon


def test_evo_family_pichu_pikachu(adapter):
    base = adapter.evo_family(25)  # Pikachu
    assert adapter.evo_family(172) == base  # Pichu (baby)
    assert adapter.evo_family(26) == base   # Raichu


def test_evo_family_single_stage_unown(adapter):
    assert adapter.evo_family(201) == 201  # Unown


def test_evo_family_single_stage_heracross(adapter):
    assert adapter.evo_family(214) == 214  # Heracross (single in Gen 2)


# ── species_types ────────────────────────────────────────────────────────
# Gen 2 type IDs: Normal=0, Fighting=1, Flying=2, Poison=3, Ground=4,
# Rock=5, Bug=7, Ghost=8, Steel=9, Fire=20, Water=21, Grass=22,
# Electric=23, Psychic=24, Ice=25, Dragon=26, Dark=27

def test_species_types_chikorita(adapter):
    # Grass monotype
    assert adapter.species_types(152) == (22, 22)


def test_species_types_magnemite_gen2(adapter):
    # Gen 2: Electric/Steel (changed from Gen 1 Electric-only)
    assert adapter.species_types(81) == (23, 9)


def test_species_types_umbreon(adapter):
    # Dark monotype (new type)
    assert adapter.species_types(197) == (27, 27)


def test_species_types_steelix(adapter):
    # Steel/Ground (new type combo)
    assert adapter.species_types(208) == (9, 4)


def test_species_types_celebi(adapter):
    # Psychic/Grass
    assert adapter.species_types(251) == (24, 22)


def test_species_types_unknown_species(adapter):
    assert adapter.species_types(99999) is None


# ── type_name ────────────────────────────────────────────────────────────

def test_type_name_normal(adapter):
    assert adapter.type_name(0) == "Normal"


def test_type_name_dark(adapter):
    assert adapter.type_name(27) == "Dark"


def test_type_name_steel(adapter):
    assert adapter.type_name(9) == "Steel"


def test_type_name_fire(adapter):
    assert adapter.type_name(20) == "Fire"


def test_type_name_dragon(adapter):
    assert adapter.type_name(26) == "Dragon"


def test_type_name_unknown(adapter):
    result = adapter.type_name(0xFF)
    assert "Type #" in result


# ── sprite_html ──────────────────────────────────────────────────────────

def test_sprite_html_chikorita(adapter):
    html = adapter.sprite_html(152)
    assert "generation-ii/crystal/transparent/152.png" in html
    assert "overflow:hidden" in html
    assert "pixelated" in html


def test_sprite_html_zero(adapter):
    assert adapter.sprite_html(0) == ""


def test_sprite_html_negative(adapter):
    assert adapter.sprite_html(-1) == ""


def test_sprite_html_above_251(adapter):
    assert adapter.sprite_html(252) == ""


# ── ability_name / ability_description ───────────────────────────────────

def test_ability_name_always_empty(adapter):
    assert adapter.ability_name(1) == ""
    assert adapter.ability_name(0) == ""
    assert adapter.ability_name(999) == ""


def test_ability_description_always_empty(adapter):
    assert adapter.ability_description(1) == ""
    assert adapter.ability_description(0) == ""


# ── item_name ────────────────────────────────────────────────────────────

def test_item_name_master_ball(adapter):
    assert adapter.item_name(1) == "Master Ball"


def test_item_name_poke_ball(adapter):
    # Crystal item ID 5 = Poke Ball (per item_names.json)
    assert adapter.item_name(5) == "Poke Ball"


def test_item_name_zero(adapter):
    assert adapter.item_name(0) == ""


def test_item_name_unknown(adapter):
    result = adapter.item_name(9999)
    assert "Item #" in result


# ── area_display_name ────────────────────────────────────────────────────

def test_area_display_name_fallback(adapter):
    name = adapter.area_display_name("unknown_area_xyz")
    assert name == "Unknown Area Xyz"


def test_area_display_name_known_route(adapter):
    name = adapter.area_display_name("route_29")
    assert name  # non-empty


# ── ability_name species_id parameter is ignored ─────────────────────────────

def test_ability_name_species_id_ignored(adapter):
    """Gen 2 has no abilities; species_id must not change the empty-string result."""
    assert adapter.ability_name(1, species_id=999) == adapter.ability_name(1)
    assert adapter.ability_name(1, species_id=999) == ""


# ── to_national_dex ──────────────────────────────────────────────────────

def test_to_national_dex_passthrough(adapter):
    assert adapter.to_national_dex(1) == 1
    assert adapter.to_national_dex(152) == 152
    assert adapter.to_national_dex(251) == 251


def test_to_national_dex_zero(adapter):
    assert adapter.to_national_dex(0) == 0


def test_to_national_dex_boundary(adapter):
    assert adapter.to_national_dex(100) == 100


# ── form_sprite_id ───────────────────────────────────────────────────────

def test_form_sprite_id_always_none(adapter):
    assert adapter.form_sprite_id(152) is None
    assert adapter.form_sprite_id(201) is None  # Unown forms are cosmetic
    assert adapter.form_sprite_id(1) is None


# ── trainer_info ─────────────────────────────────────────────────────────

def test_trainer_info_returns_empty(adapter):
    assert adapter.trainer_info(1) == ("", "")
    assert adapter.trainer_info(999) == ("", "")


# ── Phase 3: Move data ───────────────────────────────────────────────────

def test_move_name_pound(adapter):
    assert adapter.move_name(1) == "Pound"


def test_move_name_thunderbolt(adapter):
    assert adapter.move_name(85) == "Thunderbolt"


def test_move_name_unknown(adapter):
    assert adapter.move_name(0) == ""
    assert adapter.move_name(9999) == ""


def test_move_data_gen2_karate_chop_is_fighting(adapter):
    """Gen 2 fixed Karate Chop's type from Normal (Gen 1 bug) to Fighting."""
    m = adapter.move_data(2)
    assert m["name"] == "Karate Chop"
    assert m["type_name"] == "Fighting"
    assert m["power"] == 50


def test_move_data_gen2_bite_is_dark(adapter):
    """Gen 2 added Dark and reclassified Bite from Normal → Dark."""
    m = adapter.move_data(44)
    assert m["type_name"] == "Dark"
    assert m["split"] == 1  # Special (Dark is special-side in Gen 2)


def test_move_data_thunderbolt(adapter):
    m = adapter.move_data(85)
    assert m["name"] == "Thunderbolt"
    assert m["type_name"] == "Electric"
    assert m["power"] == 95
    assert m["accuracy"] == 100
    assert m["pp"] == 15
    assert m["split"] == 1  # Special
    assert m["effect_chance"] == 10


def test_move_data_status_move(adapter):
    """Sleep Powder (id=79) is a status move."""
    m = adapter.move_data(79)
    assert m["split"] == 2
    assert m["power"] == 0


def test_move_data_unknown(adapter):
    assert adapter.move_data(0) is None
    assert adapter.move_data(9999) is None


def test_move_data_struggle(adapter):
    """Struggle is move 165 in Gen 2 (same id as Gen 1 since added Gen 2 moves come after)."""
    m = adapter.move_data(165)
    assert m["name"] == "Struggle"


def test_move_data_gen2_only_move(adapter):
    """Crunch (Gen 2 only, id=242) — special Dark move."""
    m = adapter.move_data(242)
    assert m["name"] == "Crunch"
    assert m["type_name"] == "Dark"
    assert m["power"] == 80


def test_move_data_count(adapter):
    """All 251 Gen 2 moves should be loaded."""
    valid = sum(1 for i in range(1, 252) if adapter.move_data(i) is not None)
    assert valid == 251


# ── Phase 6: Encounter tables ────────────────────────────────────────────

def test_encounter_table_route_29(adapter):
    enc = adapter.encounter_table("route_29")
    assert enc is not None
    # Gen 2 has time-of-day variants
    assert "Morn" in enc
    assert "Day" in enc
    assert "Nite" in enc


def test_encounter_table_route_29_has_sentret(adapter):
    enc = adapter.encounter_table("route_29")
    morn = {e["name"] for e in enc["Morn"]}
    assert "Sentret" in morn


def test_encounter_table_nite_has_hoothoot(adapter):
    """Hoothoot is a night-only encounter on Route 29/30/31."""
    enc = adapter.encounter_table("route_29")
    nite = {e["name"] for e in enc["Nite"]}
    assert "Hoothoot" in nite


def test_encounter_table_unknown_area(adapter):
    assert adapter.encounter_table("nonexistent_area") is None


def test_encounter_table_entry_schema(adapter):
    enc = adapter.encounter_table("route_29")
    for method, entries in enc.items():
        for entry in entries:
            assert "species_id" in entry
            assert "name" in entry
            assert "rate" in entry
            assert "min_level" in entry
            assert "max_level" in entry


# ── Registry ─────────────────────────────────────────────────────────────

def test_adapter_registered():
    from server.adapters import get_adapter
    a = get_adapter("gen2_crystal")
    assert a.game_id == "gen2_crystal"


def test_adapter_registered_returns_instance():
    from server.adapters import get_adapter
    a = get_adapter("gen2_crystal")
    assert isinstance(a, Gen2CrystalAdapter)


# ══════════════════════════════════════════════════════════════════════════
# SoulLinkState integration tests with Gen 2 adapter
# ══════════════════════════════════════════════════════════════════════════

from server.state import SoulLinkState


def _make_gen2_state(tmp_path, monkeypatch):
    """Create a SoulLinkState with Gen 2 adapter for integration tests."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter())
    state.pokeballs_obtained = {"a": True, "b": True}
    return state


def test_integration_capture_linking(tmp_path, monkeypatch):
    """A captures on route_29, B captures on route_29 → link formed."""
    state = _make_gen2_state(tmp_path, monkeypatch)

    state.handle_event("a", {"event": "area_enter", "area_id": "route_29"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:98",
                             "area_id": "route_29", "species": 152,
                             "nickname": "CHIKORITA", "level": 5})
    state.handle_event("b", {"event": "area_enter", "area_id": "route_29"})
    state.handle_event("b", {"event": "capture", "key": "B2C1:5678:9B",
                             "area_id": "route_29", "species": 155,
                             "nickname": "CYNDAQUIL", "level": 5})

    link = next((l for l in state.links if l.area_id == "route_29"), None)
    assert link is not None
    assert link.a.key == "A5F3:1234:98"
    assert link.b.key == "B2C1:5678:9B"


def test_integration_faint_propagation(tmp_path, monkeypatch):
    """Faint A's mon → force_faint queued for B's partner."""
    state = _make_gen2_state(tmp_path, monkeypatch)

    state.handle_event("a", {"event": "area_enter", "area_id": "route_29"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:98",
                             "area_id": "route_29", "species": 152,
                             "nickname": "CHIKORITA", "level": 5})
    state.handle_event("b", {"event": "area_enter", "area_id": "route_29"})
    state.handle_event("b", {"event": "capture", "key": "B2C1:5678:9B",
                             "area_id": "route_29", "species": 155,
                             "nickname": "CYNDAQUIL", "level": 5})

    state.handle_event("a", {"event": "faint", "key": "A5F3:1234:98"})

    cmds = state.handle_event("b", {"event": "tick"})
    assert any(c["cmd"] == "force_faint" and c["key"] == "B2C1:5678:9B" for c in cmds)


def test_integration_dead_zone(tmp_path, monkeypatch):
    """A captures on area, B sends no_catch → dead_zone."""
    state = _make_gen2_state(tmp_path, monkeypatch)

    state.handle_event("a", {"event": "area_enter", "area_id": "dark_cave"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:29",
                             "area_id": "dark_cave", "species": 41,
                             "nickname": "ZUBAT", "level": 4})
    state.handle_event("b", {"event": "area_enter", "area_id": "dark_cave"})
    state.handle_event("b", {"event": "no_catch", "area_id": "dark_cave"})

    assert state.area_states.get("dark_cave") == "dead_zone"


def test_integration_gift_area_no_pokeballs(tmp_path, monkeypatch):
    """Capture on new_bark_town (gift area) doesn't activate pokeballs_obtained."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter())
    state.pokeballs_obtained = {"a": False, "b": False}

    state.handle_event("a", {"event": "area_enter", "area_id": "new_bark_town"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:98",
                             "area_id": "new_bark_town", "species": 152,
                             "nickname": "CHIKORITA", "level": 5})

    assert state.pokeballs_obtained["a"] is False


def test_integration_gender_lock_rejects_same_gender(tmp_path, monkeypatch):
    """Gender lock rejects link when both mons are male."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter(), gender_lock=True)
    state.pokeballs_obtained = {"a": True, "b": True}

    # Pichu (172): ratio=127, threshold=7. Atk=F → male (non-shiny: Def!=A)
    state.handle_event("a", {"event": "area_enter", "area_id": "route_29"})
    state.handle_event("a", {"event": "capture", "key": "F555:1234:AC",
                             "area_id": "route_29", "species_id": 172, "level": 5})

    # Another male Pichu for player B (non-shiny)
    state.handle_event("b", {"event": "area_enter", "area_id": "route_29"})
    cmds = state.handle_event("b", {"event": "capture", "key": "F555:5678:AC",
                                    "area_id": "route_29", "species_id": 172, "level": 5})

    # Should get force_faint (gender clause violation)
    has_faint = any(c.get("cmd") == "force_faint" for c in cmds)
    # Link should NOT form as alive
    alive_links = [l for l in state.links if l.area_id == "route_29" and l.status.value == "alive"]
    assert has_faint or len(alive_links) == 0


def test_integration_gender_lock_allows_opposite(tmp_path, monkeypatch):
    """Gender lock allows link when mons are opposite gender."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter(), gender_lock=True)
    state.pokeballs_obtained = {"a": True, "b": True}

    # Pichu (172): ratio=127, threshold=7. Atk=8 → male (non-shiny: Def!=A)
    state.handle_event("a", {"event": "area_enter", "area_id": "route_29"})
    state.handle_event("a", {"event": "capture", "key": "8555:1234:AC",
                             "area_id": "route_29", "species_id": 172, "level": 5})

    # Female Pichu: Atk=0 → female (non-shiny: Def!=A)
    state.handle_event("b", {"event": "area_enter", "area_id": "route_29"})
    state.handle_event("b", {"event": "capture", "key": "0555:5678:AC",
                             "area_id": "route_29", "species_id": 172, "level": 5})

    # Link should form
    link = next((l for l in state.links if l.area_id == "route_29"), None)
    assert link is not None
    assert link.status.value == "alive"


def test_integration_identity_lock(tmp_path, monkeypatch):
    """Player identity lock works with Gen 2 key format."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter())
    state.pokeballs_obtained = {"a": True, "b": True}

    # First hello locks player A's OT ID
    state.handle_event("a", {
        "event": "hello",
        "party": [{"key": "A5F3:1234:98", "hp": 50, "maxHP": 50, "level": 10}],
        "has_pokeballs": True, "area_id": "route_29", "trainer_name": "GOLD"
    })

    # Hello with DIFFERENT OT ID → rejected
    cmds = state.handle_event("a", {
        "event": "hello",
        "party": [{"key": "C3D4:5678:98", "hp": 50, "maxHP": 50, "level": 10}],
        "has_pokeballs": True, "area_id": "route_29", "trainer_name": "SILVER"
    })
    assert any(c.get("cmd") == "hud_show" and "WRONG SAVE" in c.get("text", "") for c in cmds)


# ══════════════════════════════════════════════════════════════════════════
# Phase 1d: Egg-gift classification (mirrors Gen 3 commit be648eb)
# ══════════════════════════════════════════════════════════════════════════

def _has_cmd(cmds, cmd_name, key=None):
    for c in cmds:
        if c.get("cmd") == cmd_name and (key is None or c.get("key") == key):
            return True
    return False


def test_egg_capture_on_route_30_treated_as_gift(tmp_path, monkeypatch):
    """Mystery Egg from Mr. Pokemon on Route 30: is_egg=True + non-daycare area → gift.
    Bypasses Pokéball gate and skips quarantine."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter())
    state.party_size = {"a": 1, "b": 0}  # A already has a starter

    cmds = state.handle_event("a", {
        "event": "capture", "key": "A5F3:1234:98",
        "area_id": "route_30", "species_id": 175,  # Togepi (Mystery Egg hatches into Togepi)
        "level": 1, "is_egg": True,
    })
    # Egg from non-daycare area is gift-like — no pokéball gate flip, no quarantine.
    assert not state.pokeballs_obtained.get("a"), \
        "Mystery Egg from Mr. Pokemon must not activate the Pokéball gate"
    assert not _has_cmd(cmds, "box_mon", "A5F3:1234:98"), \
        "Mystery Egg must not be quarantined to box"


def test_egg_capture_on_route_34_not_treated_as_gift(tmp_path, monkeypatch):
    """Daycare-bred egg picked up at Route 34: is_egg=True + daycare area → normal capture.
    Pokéball gate activates and quarantine applies (player must have full progression)."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter())
    state.party_size = {"a": 2, "b": 0}  # A has multiple mons, daycare egg goes to box

    cmds = state.handle_event("a", {
        "event": "capture", "key": "B2C1:5678:9B",
        "area_id": "route_34", "species_id": 172,  # Pichu (common bred result)
        "level": 1, "is_egg": True,
    })
    assert state.pokeballs_obtained.get("a"), \
        "Daycare egg must activate the Pokéball gate"
    assert _has_cmd(cmds, "box_mon", "B2C1:5678:9B"), \
        "Daycare egg must be quarantined like a normal capture"


def test_capture_without_is_egg_field_unchanged(tmp_path, monkeypatch):
    """Old clients (no is_egg field) keep working — defaults to False, normal capture flow."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter())
    state.party_size = {"a": 2, "b": 0}

    cmds = state.handle_event("a", {
        "event": "capture", "key": "C0DE:0001:0F",
        "area_id": "route_29", "species_id": 16, "level": 5,
        # no is_egg field
    })
    assert state.pokeballs_obtained.get("a")
    assert _has_cmd(cmds, "box_mon", "C0DE:0001:0F")


def test_wild_capture_on_route_34_no_longer_treated_as_gift(tmp_path, monkeypatch):
    """Regression test for Phase 1d: previously route_34 was in _GIFT_AREAS which
    treated every wild capture there as a gift. After fix, Route 34 is a daycare,
    so wild captures (no is_egg flag) go through normal flow."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen2CrystalAdapter())
    state.party_size = {"a": 2, "b": 0}

    cmds = state.handle_event("a", {
        "event": "capture", "key": "F00D:0002:13",
        "area_id": "route_34", "species_id": 19,  # Rattata
        "level": 8,
        # no is_egg — this is a wild capture in Route 34 grass
    })
    assert state.pokeballs_obtained.get("a"), \
        "Wild capture on Route 34 must activate the Pokéball gate"
    assert _has_cmd(cmds, "box_mon", "F00D:0002:13"), \
        "Wild capture on Route 34 must be quarantined like any other route"


# ── Memorial box ─────────────────────────────────────────────────────────


def test_memorial_box_index_is_box_14(adapter):
    """Gen 2 C/G/S has 14 PC boxes; memorial = last box (0-indexed 13).

    Pairs with depositMemorialMon in lua/memory_gb.lua which writes to SRAM
    CartRAM offset 0x79E0, and the Gen 2 client's build_box_snapshot which
    emits memorial entries with box=13.
    """
    assert adapter.memorial_box_index == 13
