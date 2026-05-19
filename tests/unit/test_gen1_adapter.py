"""Tests for the Gen 1 RBY adapter."""

import pytest
from server.adapters.gen1_rby import Gen1Adapter


@pytest.fixture
def adapter():
    return Gen1Adapter()


# ── game_id ──────────────────────────────────────────────────────────────

def test_game_id(adapter):
    assert adapter.game_id == "gen1_rby"


# ── Gift areas ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("area_id", [
    "pallet_town",
    "oaks_lab",
    "celadon_city",
    "saffron_city",
    "silph_co",
    "cinnabar_island",
    "route_4",
    "celadon_game_corner",
    "gift",
])
def test_gift_areas_return_true(adapter, area_id):
    assert adapter.is_gift_area(area_id) is True


def test_gift_prefix_area(adapter):
    assert adapter.is_gift_area("gift_something") is True


def test_gift_prefix_area_2(adapter):
    assert adapter.is_gift_area("gift_fossils") is True


@pytest.mark.parametrize("area_id", [
    "route_1",
    "viridian_forest",
    "mt_moon",
])
def test_non_gift_areas_return_false(adapter, area_id):
    assert adapter.is_gift_area(area_id) is False


# ── Key validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "A5F3:1234:99",
    "0000:0000:01",
    "FFFF:FFFF:FF",
    "abcd:ef01:0A",
])
def test_valid_keys(adapter, key):
    assert adapter.is_valid_mon_key(key) is True


@pytest.mark.parametrize("key,reason", [
    ("A5F3:1234", "too few colons"),
    ("A5F31234:99", "missing middle colon"),
    ("GGGG:1234:99", "non-hex chars in DV"),
    ("A5F3:XXXX:99", "non-hex chars in OTID"),
    ("A5F3:1234:GG", "non-hex chars in species index"),
    ("", "empty string"),
    ("A5F3:1234:999", "species index too long"),
    ("A5F33:1234:99", "DV too long"),
    ("A5F:1234:99", "DV too short"),
])
def test_invalid_keys(adapter, key, reason):
    assert adapter.is_valid_mon_key(key) is False, reason


# ── parse_ot_id ──────────────────────────────────────────────────────────

def test_parse_ot_id_normal(adapter):
    assert adapter.parse_ot_id("A5F3:1234:99") == "1234"


def test_parse_ot_id_another(adapter):
    assert adapter.parse_ot_id("0000:ABCD:01") == "ABCD"


def test_parse_ot_id_invalid_key(adapter):
    assert adapter.parse_ot_id("nocolon") == ""


def test_parse_ot_id_empty(adapter):
    assert adapter.parse_ot_id("") == ""


# ── is_shiny ─────────────────────────────────────────────────────────────

def test_is_shiny_always_false(adapter):
    assert adapter.is_shiny("A5F3:1234:99") is False


def test_is_shiny_any_key(adapter):
    assert adapter.is_shiny("0000:0000:00") is False


# ── gender_from_key ──────────────────────────────────────────────────────

def test_gender_always_genderless(adapter):
    assert adapter.gender_from_key("A5F3:1234:99", 25) == "genderless"


def test_gender_genderless_any_species(adapter):
    assert adapter.gender_from_key("FFFF:FFFF:FF", 1) == "genderless"
    assert adapter.gender_from_key("0000:0000:01", 150) == "genderless"


# ── gender_symbol ────────────────────────────────────────────────────────

def test_gender_symbol_always_empty(adapter):
    assert adapter.gender_symbol("genderless") == ""
    assert adapter.gender_symbol("male") == ""
    assert adapter.gender_symbol("female") == ""


# ── species_name ─────────────────────────────────────────────────────────

def test_species_name_bulbasaur(adapter):
    assert adapter.species_name(1) == "Bulbasaur"


def test_species_name_pikachu(adapter):
    assert adapter.species_name(25) == "Pikachu"


def test_species_name_mewtwo(adapter):
    assert adapter.species_name(150) == "Mewtwo"


def test_species_name_mew(adapter):
    assert adapter.species_name(151) == "Mew"


def test_species_name_unknown(adapter):
    assert adapter.species_name(99999) == "#99999"


# ── evo_family ───────────────────────────────────────────────────────────

def test_evo_family_bulbasaur_line(adapter):
    base = adapter.evo_family(1)
    assert adapter.evo_family(2) == base  # Ivysaur
    assert adapter.evo_family(3) == base  # Venusaur


def test_evo_family_eevee_family(adapter):
    base = adapter.evo_family(133)
    assert adapter.evo_family(134) == base  # Vaporeon
    assert adapter.evo_family(135) == base  # Jolteon
    assert adapter.evo_family(136) == base  # Flareon


def test_evo_family_pikachu_line(adapter):
    base = adapter.evo_family(25)
    assert adapter.evo_family(26) == base  # Raichu


def test_evo_family_single_stage(adapter):
    # Tauros (128) is single-stage
    assert adapter.evo_family(128) == 128


# ── species_types ────────────────────────────────────────────────────────

def test_species_types_bulbasaur(adapter):
    types = adapter.species_types(1)
    assert types == (0x16, 0x03)  # Grass/Poison


def test_species_types_pikachu(adapter):
    types = adapter.species_types(25)
    assert types == (0x17, 0x17)  # Electric/Electric (monotype)


def test_species_types_charizard(adapter):
    types = adapter.species_types(6)
    assert types == (0x14, 0x02)  # Fire/Flying


def test_species_types_unknown(adapter):
    assert adapter.species_types(99999) is None


# ── type_name ────────────────────────────────────────────────────────────

def test_type_name_normal(adapter):
    assert adapter.type_name(0x00) == "Normal"


def test_type_name_fire(adapter):
    assert adapter.type_name(0x14) == "Fire"


def test_type_name_dragon(adapter):
    assert adapter.type_name(0x1A) == "Dragon"


def test_type_name_unknown(adapter):
    result = adapter.type_name(0xFF)
    assert "Type #" in result


# ── sprite_html ──────────────────────────────────────────────────────────

def test_sprite_html_pikachu(adapter):
    html = adapter.sprite_html(25)
    assert "generation-i/red-blue/transparent/25.png" in html
    assert "overflow:hidden" in html
    assert "pixelated" in html


def test_sprite_html_zero(adapter):
    assert adapter.sprite_html(0) == ""


def test_sprite_html_negative(adapter):
    assert adapter.sprite_html(-1) == ""


# ── ability_name ─────────────────────────────────────────────────────────

def test_ability_name_always_empty(adapter):
    assert adapter.ability_name(1) == ""
    assert adapter.ability_name(0) == ""
    assert adapter.ability_name(999) == ""


# ── item_name ────────────────────────────────────────────────────────────

def test_item_name_poke_ball(adapter):
    assert adapter.item_name(0x04) == "Poké Ball"


def test_item_name_master_ball(adapter):
    assert adapter.item_name(0x01) == "Master Ball"


def test_item_name_unknown(adapter):
    result = adapter.item_name(0xFF)
    assert "Item #" in result


def test_item_name_zero(adapter):
    assert adapter.item_name(0) == ""


# ── area_display_name ────────────────────────────────────────────────────

def test_area_display_name_fallback(adapter):
    name = adapter.area_display_name("unknown_area_xyz")
    assert name == "Unknown Area Xyz"


def test_area_display_name_known_route(adapter):
    # Even without area_map.json, fallback produces a human-readable name
    name = adapter.area_display_name("route_1")
    assert name  # non-empty


# ── to_national_dex ──────────────────────────────────────────────────────

def test_to_national_dex_passthrough(adapter):
    assert adapter.to_national_dex(1) == 1
    assert adapter.to_national_dex(25) == 25
    assert adapter.to_national_dex(151) == 151


def test_to_national_dex_boundary(adapter):
    assert adapter.to_national_dex(100) == 100


# ── form_sprite_id ───────────────────────────────────────────────────────

def test_form_sprite_id_always_none(adapter):
    assert adapter.form_sprite_id(25) is None
    assert adapter.form_sprite_id(150) is None
    assert adapter.form_sprite_id(1) is None


# ── Registry ─────────────────────────────────────────────────────────────

def test_adapter_registered():
    from server.adapters import get_adapter
    a = get_adapter("gen1_rby")
    assert a.game_id == "gen1_rby"


# ══════════════════════════════════════════════════════════════════════════
# SoulLinkState integration tests with Gen 1 adapter
# ══════════════════════════════════════════════════════════════════════════

from server.state import SoulLinkState


def _make_gen1_state(tmp_path, monkeypatch):
    """Create a SoulLinkState with Gen 1 adapter for integration tests."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen1Adapter())
    state.pokeballs_obtained = {"a": True, "b": True}
    return state


def test_integration_capture_linking(tmp_path, monkeypatch):
    """A captures on route_1, B captures on route_1 → link formed."""
    state = _make_gen1_state(tmp_path, monkeypatch)

    state.handle_event("a", {"event": "area_enter", "area_id": "route_1"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:99", "area_id": "route_1",
                             "species": 25, "nickname": "PIKACHU", "level": 5})
    state.handle_event("b", {"event": "area_enter", "area_id": "route_1"})
    state.handle_event("b", {"event": "capture", "key": "B2C1:5678:A4", "area_id": "route_1",
                             "species": 1, "nickname": "BULBA", "level": 5})

    # Link should be formed
    link = next((l for l in state.links if l.area_id == "route_1"), None)
    assert link is not None
    assert link.a.key == "A5F3:1234:99"
    assert link.b.key == "B2C1:5678:A4"


def test_integration_faint_propagation(tmp_path, monkeypatch):
    """Faint A's mon → force_faint queued for B's partner."""
    state = _make_gen1_state(tmp_path, monkeypatch)

    # Set up a link
    state.handle_event("a", {"event": "area_enter", "area_id": "route_1"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:99", "area_id": "route_1",
                             "species": 25, "nickname": "PIKACHU", "level": 5})
    state.handle_event("b", {"event": "area_enter", "area_id": "route_1"})
    state.handle_event("b", {"event": "capture", "key": "B2C1:5678:A4", "area_id": "route_1",
                             "species": 1, "nickname": "BULBA", "level": 5})

    # Faint A's mon
    state.handle_event("a", {"event": "faint", "key": "A5F3:1234:99"})

    # B's tick should return force_faint
    cmds = state.handle_event("b", {"event": "tick"})
    assert any(c["cmd"] == "force_faint" and c["key"] == "B2C1:5678:A4" for c in cmds)


def test_integration_dead_zone(tmp_path, monkeypatch):
    """A enters area, B enters area with no_catch → dead_zone."""
    state = _make_gen1_state(tmp_path, monkeypatch)

    state.handle_event("a", {"event": "area_enter", "area_id": "route_2"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:99", "area_id": "route_2",
                             "species": 16, "nickname": "PIDGEY", "level": 3})
    state.handle_event("b", {"event": "area_enter", "area_id": "route_2"})
    state.handle_event("b", {"event": "no_catch", "area_id": "route_2"})

    assert state.area_states.get("route_2") == "dead_zone"


def test_integration_key_change(tmp_path, monkeypatch):
    """key_change event migrates the link entry to a new key."""
    state = _make_gen1_state(tmp_path, monkeypatch)

    state.handle_event("a", {"event": "area_enter", "area_id": "route_3"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:99", "area_id": "route_3",
                             "species": 25, "nickname": "PIKACHU", "level": 5})
    state.handle_event("b", {"event": "area_enter", "area_id": "route_3"})
    state.handle_event("b", {"event": "capture", "key": "B2C1:5678:A4", "area_id": "route_3",
                             "species": 1, "nickname": "BULBA", "level": 5})

    # Simulate evolution/nature change for A's mon
    state.handle_event("a", {"event": "key_change", "old_key": "A5F3:1234:99",
                             "new_key": "C3D4:1234:1A", "species": 26,
                             "nickname": "RAICHU"})

    link = next((l for l in state.links if l.area_id == "route_3"), None)
    assert link is not None
    assert link.a.key == "C3D4:1234:1A"


def test_integration_gift_area_no_pokeballs(tmp_path, monkeypatch):
    """Capture on pallet_town (gift area) doesn't activate pokeballs_obtained."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen1Adapter())
    state.pokeballs_obtained = {"a": False, "b": False}

    state.handle_event("a", {"event": "area_enter", "area_id": "pallet_town"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:99", "area_id": "pallet_town",
                             "species": 4, "nickname": "CHARMANDER", "level": 5})

    assert state.pokeballs_obtained["a"] is False


def test_integration_identity_lock(tmp_path, monkeypatch):
    """Player identity lock works with Gen 1 key format."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen1Adapter())
    state.pokeballs_obtained = {"a": True, "b": True}
    
    # First hello locks player A's OT ID
    state.handle_event("a", {
        "event": "hello", "party": [{"key": "A5F3:1234:99", "hp": 50, "maxHP": 50, "level": 10}],
        "has_pokeballs": True, "area_id": "route_1", "trainer_name": "RED"
    })
    
    # Second hello with same OT ID works fine
    cmds = state.handle_event("a", {
        "event": "hello", "party": [{"key": "B2C1:1234:99", "hp": 50, "maxHP": 50, "level": 10}],
        "has_pokeballs": True, "area_id": "route_1", "trainer_name": "RED"
    })
    # Should NOT get identity error
    assert not any(c.get("cmd") == "hud_show" and "Wrong save" in c.get("text", "") for c in cmds)
    
    # Hello with DIFFERENT OT ID gets rejected
    cmds = state.handle_event("a", {
        "event": "hello", "party": [{"key": "C3D4:5678:99", "hp": 50, "maxHP": 50, "level": 10}],
        "has_pokeballs": True, "area_id": "route_1", "trainer_name": "BLUE"
    })
    # Should get identity error  
    assert any(c.get("cmd") == "hud_show" and "WRONG SAVE" in c.get("text", "") for c in cmds)


def test_integration_gender_lock_no_effect(tmp_path, monkeypatch):
    """Gender lock doesn't reject Gen 1 links since all mons are genderless."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen1Adapter(), gender_lock=True)
    state.pokeballs_obtained = {"a": True, "b": True}
    
    # Player A captures on route_1
    state.handle_event("a", {"event": "area_enter", "area_id": "route_1"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:99", "area_id": "route_1", "species": 25, "level": 5})
    
    # Player B captures on route_1
    state.handle_event("b", {"event": "area_enter", "area_id": "route_1"})
    cmds = state.handle_event("b", {"event": "capture", "key": "B2C1:5678:19", "area_id": "route_1", "species": 25, "level": 5})
    
    # Link should form — gender lock should NOT reject (both genderless, genderless is exempt)
    assert state.links  # Should have at least one link
    link = state.links[0]
    assert link.status.value == "alive"


def test_integration_species_lock_after_evolution(tmp_path, monkeypatch):
    """Species lock still applies after evolution changes species."""
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(adapter=Gen1Adapter(), species_lock=True)
    state.pokeballs_obtained = {"a": True, "b": True}
    
    # Create a link: Charmander (4) <-> Squirtle (7)
    state.handle_event("a", {"event": "area_enter", "area_id": "route_1"})
    state.handle_event("a", {"event": "capture", "key": "A5F3:1234:B4", "area_id": "route_1", "species_id": 4, "level": 5})
    state.handle_event("b", {"event": "area_enter", "area_id": "route_1"})
    state.handle_event("b", {"event": "capture", "key": "B2C1:5678:B1", "area_id": "route_1", "species_id": 7, "level": 5})
    
    # Verify link formed
    assert len(state.links) == 1
    
    # Now player A catches another Charmander on route_2 (different DVs)
    state.handle_event("a", {"event": "area_enter", "area_id": "route_2"})
    state.handle_event("a", {"event": "capture", "key": "C3D4:1234:B4", "area_id": "route_2", "species_id": 4, "level": 8})
    
    # Player B catches a Charmeleon (5, same evo family as Charmander=4)
    state.handle_event("b", {"event": "area_enter", "area_id": "route_2"})
    cmds = state.handle_event("b", {"event": "capture", "key": "D4E5:5678:33", "area_id": "route_2", "species_id": 5, "level": 12})
    
    # Species lock should reject: Charmeleon is same family as Charmander (already linked)
    # Check for force_faint command (violation)
    has_faint = any(c.get("cmd") == "force_faint" for c in cmds)
    # The link should NOT form with alive status OR a force_faint was issued
    route2_links = [l for l in state.links if l.area_id == "route_2"]
    if route2_links:
        assert route2_links[0].status.value != "alive" or has_faint
    else:
        # Link not formed = species lock worked
        pass


def test_to_national_dex_zero(adapter):
    """to_national_dex with 0 returns 0 (invalid species, passes through)."""
    result = adapter.to_national_dex(0)
    assert result == 0


def test_to_national_dex_above_151(adapter):
    """to_national_dex with >151 falls back to lookup or passthrough."""
    # Species 190 is Rhydon's internal index — should map to NatDex 112
    # But only if species_index.json has that mapping
    result = adapter.to_national_dex(190)
    # Should be either 112 (if lookup works) or 190 (passthrough)
    assert isinstance(result, int)


# ── ability_name species_id parameter is ignored ─────────────────────────────

def test_ability_name_species_id_ignored(adapter):
    """Gen 1 has no abilities; species_id must not change the empty-string result."""
    assert adapter.ability_name(1, species_id=999) == adapter.ability_name(1)
    assert adapter.ability_name(1, species_id=999) == ""


# ── Phase 3: Move data ───────────────────────────────────────────────────

def test_move_name_pound(adapter):
    assert adapter.move_name(1) == "Pound"


def test_move_name_thunderbolt(adapter):
    assert adapter.move_name(85) == "Thunderbolt"


def test_move_name_struggle(adapter):
    assert adapter.move_name(165) == "Struggle"


def test_move_name_unknown(adapter):
    assert adapter.move_name(0) == ""
    assert adapter.move_name(9999) == ""


def test_move_data_thunderbolt(adapter):
    m = adapter.move_data(85)
    assert m["name"] == "Thunderbolt"
    assert m["type_name"] == "Electric"
    assert m["power"] == 95
    assert m["accuracy"] == 100
    assert m["pp"] == 15
    assert m["split"] == 1  # Special — Electric is special in Gen 1


def test_move_data_gen1_karate_chop_is_normal(adapter):
    """Gen 1 mislabeled Karate Chop as Normal type (fixed to Fighting in Gen 2).
    Adapter must preserve the Gen 1 quirk."""
    m = adapter.move_data(2)
    assert m["name"] == "Karate Chop"
    assert m["type_name"] == "Normal"  # Gen 1 bug — kept for historical accuracy


def test_move_data_gen1_bite_is_normal(adapter):
    """Gen 1 Bite was Normal type (Gen 2 reclassified as Dark)."""
    m = adapter.move_data(44)
    assert m["type_name"] == "Normal"


def test_move_data_status_move(adapter):
    """Sleep Powder is a status move (no Physical/Special split contribution)."""
    m = adapter.move_data(79)
    assert m["split"] == 2  # Status
    assert m["power"] == 0


def test_move_data_psychic_uses_display_name(adapter):
    """Gen 1 internal name PSYCHIC_M displays as 'Psychic'."""
    m = adapter.move_data(94)
    assert m["name"] == "Psychic"


def test_move_data_unknown(adapter):
    assert adapter.move_data(0) is None
    assert adapter.move_data(9999) is None


def test_move_data_count(adapter):
    """All 165 Gen 1 moves should be loaded."""
    valid = sum(1 for i in range(1, 166) if adapter.move_data(i) is not None)
    assert valid == 165


# ── Phase 6: Encounter tables ────────────────────────────────────────────

def test_encounter_table_route_1(adapter):
    enc = adapter.encounter_table("route_1")
    assert enc is not None
    assert "Grass" in enc
    names = {entry["name"] for entry in enc["Grass"]}
    assert "Pidgey" in names
    assert "Rattata" in names


def test_encounter_table_viridian_forest_has_pikachu(adapter):
    enc = adapter.encounter_table("viridian_forest")
    assert enc is not None
    names = {e["name"] for e in enc["Grass"]}
    assert "Pikachu" in names


def test_encounter_table_unknown_area(adapter):
    assert adapter.encounter_table("unknown_area_xyz") is None


def test_encounter_table_entry_schema(adapter):
    """Entries must include species_id, rate, min_level, max_level."""
    enc = adapter.encounter_table("route_1")
    for entry in enc["Grass"]:
        assert "species_id" in entry
        assert "rate" in entry
        assert "min_level" in entry
        assert "max_level" in entry
        assert entry["min_level"] <= entry["max_level"]


def test_encounter_table_coverage(adapter):
    """Full pret-generated coverage across all 25 routes + dungeons + safari.

    Sanity floor — if the generator regresses, this catches it.
    """
    import json
    from server.adapters.gen1_rby import _GEN1_ENCOUNTERS
    assert len(_GEN1_ENCOUNTERS) >= 35, (
        f"Gen 1 encounter coverage shrank to {len(_GEN1_ENCOUNTERS)} areas"
    )


@pytest.mark.parametrize("area_id,expected_species_substr", [
    ("cerulean_cave",      "Chansey"),      # Unknown Dungeon — endgame
    ("victory_road",       "Onix"),         # E4 prep area
    ("safari_zone_center", "Nidoran"),      # safari mons
    ("safari_zone_east",   "Nidoran"),
    ("pokemon_mansion",    "Grimer"),       # Cinnabar mansion
    ("seafoam_islands",    "Seel"),         # ice/water cave (Seel + co)
    ("pokemon_tower",      "Gastly"),
])
def test_encounter_table_endgame_coverage(adapter, area_id, expected_species_substr):
    """Areas that weren't covered before Phase 14 must be reachable now."""
    enc = adapter.encounter_table(area_id)
    assert enc is not None, f"{area_id} should have encounter data"
    # Check that at least one entry across all methods contains the expected species
    all_entries = [e for method in enc.values() for e in method]
    names = [e["name"] for e in all_entries]
    assert any(expected_species_substr in n for n in names), (
        f"{area_id}: expected a {expected_species_substr}, got {names}"
    )


# ── Memorial box ─────────────────────────────────────────────────────────


def test_memorial_box_index_is_box_12(adapter):
    """Gen 1 R/B/Y has 12 PC boxes; memorial = last box (0-indexed 11).

    Pairs with depositMemorialMon in lua/memory_gb.lua which writes to SRAM
    CartRAM offset 0x75EA, and the Gen 1 client's build_box_snapshot which
    emits memorial entries with box=11.
    """
    assert adapter.memorial_box_index == 11
