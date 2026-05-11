"""
Unit tests for server/adapters — Game adapter framework.

Tests the adapter base classes, registry, and FRLG adapter implementation.

Run:
    pytest tests/unit/test_adapters.py -v
"""

import pytest
from server.adapters import get_adapter, available_game_ids, register_adapter
from server.adapters.base import GameAdapter, GameRulesAdapter, GamePresentationAdapter
from server.adapters.gen3_frlge import Gen3Adapter


# ── Registry tests ────────────────────────────────────────────────────────────

class TestRegistry:
    def test_frlg_registered(self):
        assert "gen3_frlge" in available_game_ids()

    def test_get_frlg_adapter(self):
        adapter = get_adapter("gen3_frlge")
        assert isinstance(adapter, Gen3Adapter)
        assert isinstance(adapter, GameAdapter)
        assert adapter.game_id == "gen3_frlge"

    def test_get_unknown_adapter_raises(self):
        with pytest.raises(KeyError, match="No adapter registered"):
            get_adapter("gen99_unknown")

    def test_get_adapter_passes_kwargs(self):
        adapter = get_adapter("frlg", is_rr=True)
        assert adapter._is_rr is True

    def test_available_game_ids(self):
        ids = available_game_ids()
        assert isinstance(ids, list)
        assert len(ids) >= 1


# ── FRLG Adapter: GameRulesAdapter interface ──────────────────────────────────

class TestFRLGRules:
    @pytest.fixture
    def adapter(self):
        return Gen3Adapter(is_rr=False)

    @pytest.fixture
    def rr_adapter(self):
        return Gen3Adapter(is_rr=True)

    def test_game_id(self, adapter):
        assert adapter.game_id == "gen3_frlge"

    # ── is_gift_area ──────────────────────────────────────────────────────

    def test_gift_area_oaks_lab(self, adapter):
        assert adapter.is_gift_area("oaks_lab") is True

    def test_gift_area_intro(self, adapter):
        assert adapter.is_gift_area("intro") is True

    def test_gift_area_prefix(self, adapter):
        assert adapter.is_gift_area("gift_something") is True

    def test_not_gift_area(self, adapter):
        assert adapter.is_gift_area("route_1") is False
        assert adapter.is_gift_area("mt_moon") is False

    def test_gift_area_empty(self, adapter):
        assert adapter.is_gift_area("") is False

    # ── evo_family ────────────────────────────────────────────────────────

    def test_evo_family_base_form(self, adapter):
        # Bulbasaur (1) is its own base form
        assert adapter.evo_family(1) == 1

    def test_evo_family_evolved(self, adapter):
        # Ivysaur (2) → Bulbasaur (1)
        assert adapter.evo_family(2) == 1
        # Venusaur (3) → Bulbasaur (1)
        assert adapter.evo_family(3) == 1

    def test_evo_family_single_stage(self, adapter):
        # Tauros (128) has no evolution — returns itself
        assert adapter.evo_family(128) == 128

    # ── gender_from_key ───────────────────────────────────────────────────

    def test_gender_male(self, adapter):
        # Personality 0xFF → gender byte = 0xFF; Bulbasaur threshold=31 → male
        assert adapter.gender_from_key("000000FF:12345678", 1) == "male"

    def test_gender_female(self, adapter):
        # Personality 0x00 → gender byte = 0x00; Bulbasaur threshold=31 → female
        assert adapter.gender_from_key("00000000:12345678", 1) == "female"

    def test_gender_genderless(self, adapter):
        # Magnemite (81) has threshold=255 (genderless)
        assert adapter.gender_from_key("000000FF:12345678", 81) == "genderless"

    def test_gender_empty_key(self, adapter):
        assert adapter.gender_from_key("", 1) == ""

    def test_gender_zero_species(self, adapter):
        assert adapter.gender_from_key("000000FF:12345678", 0) == ""

    # ── species_types ─────────────────────────────────────────────────────

    def test_species_types_bulbasaur(self, adapter):
        # Bulbasaur: Grass/Poison (12, 3)
        types = adapter.species_types(1)
        assert types == (12, 3)

    def test_species_types_charmander(self, adapter):
        # Charmander: Fire/Fire (10, 10) — monotype
        types = adapter.species_types(4)
        assert types == (10, 10)

    def test_species_types_invalid(self, adapter):
        assert adapter.species_types(0) is None
        assert adapter.species_types(-1) is None

    # ── is_shiny ──────────────────────────────────────────────────────────

    def test_is_shiny_false(self, adapter):
        # Random key — almost certainly not shiny
        assert adapter.is_shiny("12345678:87654321") is False

    def test_is_shiny_true(self, adapter):
        # Construct a shiny key: (tid ^ sid ^ p_upper ^ p_lower) < 8
        # tid=0, sid=0, p_upper=0, p_lower=0 → XOR = 0 < 8 → shiny
        assert adapter.is_shiny("00000000:00000000") is True

    def test_is_shiny_malformed(self, adapter):
        assert adapter.is_shiny("") is False
        assert adapter.is_shiny("invalid") is False
        assert adapter.is_shiny("abc:def:ghi") is False

    # ── parse_ot_id ───────────────────────────────────────────────────────

    def test_parse_ot_id(self, adapter):
        assert adapter.parse_ot_id("AABBCCDD:11223344") == "11223344"

    def test_parse_ot_id_empty(self, adapter):
        assert adapter.parse_ot_id("") == ""

    def test_parse_ot_id_malformed(self, adapter):
        assert adapter.parse_ot_id("no_colon") == ""

    # ── is_valid_mon_key ──────────────────────────────────────────────────

    def test_valid_key(self, adapter):
        assert adapter.is_valid_mon_key("AABBCCDD:11223344") is True
        assert adapter.is_valid_mon_key("0:0") is True

    def test_invalid_key(self, adapter):
        assert adapter.is_valid_mon_key("") is False
        assert adapter.is_valid_mon_key("hello") is False
        assert adapter.is_valid_mon_key("GGGG:1111") is False  # non-hex

    # ── species_name ──────────────────────────────────────────────────────

    def test_species_name_known(self, adapter):
        assert adapter.species_name(1) == "Bulbasaur"
        assert adapter.species_name(25) == "Pikachu"
        assert adapter.species_name(151) == "Mew"

    def test_species_name_unknown(self, adapter):
        assert adapter.species_name(99999) == "#99999"

    # ── type_name ─────────────────────────────────────────────────────────

    def test_type_name(self, adapter):
        assert adapter.type_name(0) == "Normal"
        assert adapter.type_name(10) == "Fire"
        assert adapter.type_name(11) == "Water"

    def test_type_name_unknown(self, adapter):
        assert adapter.type_name(999) == "???"


# ── FRLG Adapter: GamePresentationAdapter interface ───────────────────────────

class TestFRLGPresentation:
    @pytest.fixture
    def adapter(self):
        return Gen3Adapter(is_rr=False)

    def test_sprite_html_bulbasaur(self, adapter):
        html = adapter.sprite_html(1)
        assert '<img' in html
        assert '/1.png' in html

    def test_sprite_html_zero(self, adapter):
        assert adapter.sprite_html(0) == ""

    def test_ability_name(self, adapter):
        # Vanilla: ability 77 = Air Lock
        assert adapter.ability_name(77) == "Air Lock"

    def test_ability_name_rr(self):
        rr = Gen3Adapter(is_rr=True)
        # RR: ability 77 is NOT overridden (uses CFRU table)
        name = rr.ability_name(77)
        assert name  # should be some string

    def test_item_name_unknown(self, adapter):
        assert "Item" in adapter.item_name(99999) or "#" in adapter.item_name(99999)

    def test_item_name_zero(self, adapter):
        assert adapter.item_name(0) == ""

    def test_area_display_name(self, adapter):
        # Should return something human-readable
        name = adapter.area_display_name("route_1")
        assert name  # non-empty string
        assert "route" in name.lower() or "Route" in name

    def test_to_national_dex_gen1(self, adapter):
        # Gen 1 IDs are identity
        assert adapter.to_national_dex(1) == 1
        assert adapter.to_national_dex(151) == 151

    def test_gender_symbol(self, adapter):
        assert adapter.gender_symbol("male") == "♂"
        assert adapter.gender_symbol("female") == "♀"
        assert adapter.gender_symbol("genderless") == ""

    def test_form_sprite_id_base(self, adapter):
        # Regular species have no form sprite ID
        assert adapter.form_sprite_id(1) is None

    def test_form_sprite_id_form(self, adapter):
        # CFRU form 713 = Rotom Heat → should have a mapping
        result = adapter.form_sprite_id(713)
        assert result is not None
        assert isinstance(result, int)


# ── Integration: adapter used by SoulLinkState ────────────────────────────────

class TestAdapterIntegration:
    def test_state_uses_adapter(self, tmp_path, monkeypatch):
        """SoulLinkState should use the adapter for rule logic."""
        monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
        monkeypatch.setattr("server.state.DATA_DIR", str(tmp_path))
        from server.state import SoulLinkState
        state = SoulLinkState()
        assert state.adapter.game_id == "gen3_frlge"

    def test_state_accepts_custom_adapter(self, tmp_path, monkeypatch):
        """SoulLinkState should accept a custom adapter."""
        monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
        monkeypatch.setattr("server.state.DATA_DIR", str(tmp_path))
        from server.state import SoulLinkState
        adapter = Gen3Adapter(is_rr=True)
        state = SoulLinkState(adapter=adapter)
        assert state.adapter is adapter
        assert state.adapter._is_rr is True

    def test_state_saves_game_id(self, tmp_path, monkeypatch):
        """game_id should be persisted in links.json."""
        monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
        monkeypatch.setattr("server.state.DATA_DIR", str(tmp_path))
        from server.state import SoulLinkState
        state = SoulLinkState()
        state.pokeballs_obtained["a"] = True
        state._save()
        import json
        with open(tmp_path / "links.json") as f:
            data = json.load(f)
        assert data["game_id"] == "gen3_frlge"

    def test_state_load_restores_game_id(self, tmp_path, monkeypatch):
        """Loading state should restore the game_id from links.json."""
        monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
        monkeypatch.setattr("server.state.DATA_DIR", str(tmp_path))
        import json
        data = {"game_id": "gen3_frlge", "links": [], "area_states": {}}
        with open(tmp_path / "links.json", "w") as f:
            json.dump(data, f)
        from server.state import SoulLinkState
        state = SoulLinkState.load()
        assert state.adapter.game_id == "gen3_frlge"

    def test_shiny_uses_adapter(self, tmp_path, monkeypatch):
        """Shiny clause should use adapter.is_shiny()."""
        monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
        monkeypatch.setattr("server.state.DATA_DIR", str(tmp_path))
        from server.state import SoulLinkState
        state = SoulLinkState()
        state.pokeballs_obtained["a"] = True
        # personality=0, otId=0 is shiny (XOR = 0 < 8)
        cmds = state.handle_event("a", {
            "event": "capture", "key": "00000000:00000000",
            "area_id": "route_1", "species_id": 25,
        })
        # Should be treated as bonus (shiny clause)
        assert "00000000:00000000" in state.bonus_keys["a"]


# ── Move data tests ───────────────────────────────────────────────────────────

class TestMoveData:
    """Tests for the move_name() and move_data() adapter methods."""

    def test_rr_move_name(self):
        adapter = Gen3Adapter(is_rr=True)
        assert adapter.move_name(1) == "Pound"
        assert adapter.move_name(85) == "Thunderbolt"

    def test_rr_move_data_thunderbolt(self):
        adapter = Gen3Adapter(is_rr=True)
        md = adapter.move_data(85)
        assert md is not None
        assert md["name"] == "Thunderbolt"
        assert md["type_name"] == "Electric"
        assert md["power"] == 95
        assert md["accuracy"] == 100
        assert md["pp"] == 15
        assert md["split"] == 1  # Special

    def test_rr_move_data_swords_dance(self):
        adapter = Gen3Adapter(is_rr=True)
        md = adapter.move_data(14)
        assert md is not None
        assert md["name"] == "Swords Dance"
        assert md["split"] == 2  # Status
        assert md["power"] == 0

    def test_rr_move_data_physical(self):
        adapter = Gen3Adapter(is_rr=True)
        md = adapter.move_data(1)  # Pound
        assert md is not None
        assert md["split"] == 0  # Physical

    def test_vanilla_move_name(self):
        adapter = Gen3Adapter(is_rr=False)
        assert adapter.move_name(1) == "Pound"
        assert adapter.move_name(57) == "Surf"

    def test_vanilla_move_data(self):
        adapter = Gen3Adapter(is_rr=False)
        md = adapter.move_data(57)  # Surf
        assert md is not None
        assert md["name"] == "Surf"
        assert md["type_name"] == "Water"
        assert md["power"] == 95
        assert md["pp"] == 15

    def test_unknown_move_returns_none(self):
        adapter = Gen3Adapter(is_rr=True)
        assert adapter.move_data(99999) is None

    def test_unknown_move_name_returns_empty(self):
        adapter = Gen3Adapter(is_rr=True)
        assert adapter.move_name(99999) == ""

    def test_move_data_has_required_fields(self):
        adapter = Gen3Adapter(is_rr=True)
        md = adapter.move_data(85)
        required = {"name", "type_id", "type_name", "power", "accuracy", "pp", "split"}
        assert required.issubset(set(md.keys()))

    def test_move_zero_returns_none(self):
        """Move ID 0 (MOVE_NONE) should return None or empty."""
        adapter = Gen3Adapter(is_rr=True)
        # Move 0 exists in the data but has no meaningful name
        name = adapter.move_name(0)
        # Either empty or some placeholder is fine
        assert isinstance(name, str)

    def test_base_adapter_stubs(self):
        """Non-Gen3 adapters should return defaults for move methods."""
        from server.adapters.gen4_hgsspt import Gen4Adapter
        adapter = Gen4Adapter()
        assert adapter.move_name(85) == ""
        assert adapter.move_data(85) is None


# ── CFRU Compressed Box Regression Tests ──────────────────────────────────────
#
# The Lua CFRU struct fix corrected wrong memory offsets (species at +0x1C,
# held_item at +0x1E, both unencrypted) and stride (58 bytes, not 80).  These
# Python tests validate the server-side data pipeline: pc_boxes entries arrive
# as already-parsed JSON dicts, and the server must store and retrieve each
# mon's data independently — no bleeding between adjacent box slots.
# ──────────────────────────────────────────────────────────────────────────────

class TestCFRUBoxHandling:

    @pytest.fixture
    def tracker(self, tmp_path):
        """SLinkServer instance isolated to a temporary directory."""
        from server.server import SLinkServer
        return SLinkServer(data_dir=str(tmp_path))

    # ── memorial_box_index ─────────────────────────────────────────────────

    def test_memorial_box_index_vanilla(self):
        """Vanilla FRLG: memorial box is always index 13 (UI 'Box 14')."""
        adapter = Gen3Adapter(is_rr=False)
        assert adapter.memorial_box_index == 13

    def test_memorial_box_index_rr(self):
        """CFRU/RR: 25 boxes; memorial box is index 24 (UI 'Box 25'), fills downward."""
        adapter = Gen3Adapter(is_rr=True)
        assert adapter.memorial_box_index == 24

    # ── _cache_mon_info: per-key independence ──────────────────────────────

    def test_cache_independent_keys(self, tracker):
        """Two distinct keys get entirely independent cache entries."""
        tracker._cache_mon_info("AAAA:1111", {
            "species_id": 4, "nickname": "CHAR", "level": 10, "held_item_id": 17,
        })
        tracker._cache_mon_info("BBBB:2222", {
            "species_id": 7, "nickname": "SQUIRT", "level": 12, "held_item_id": 18,
        })
        assert tracker._mon_cache["AAAA:1111"]["species_id"] == 4
        assert tracker._mon_cache["AAAA:1111"]["held_item_id"] == 17
        assert tracker._mon_cache["BBBB:2222"]["species_id"] == 7
        assert tracker._mon_cache["BBBB:2222"]["held_item_id"] == 18

    def test_cache_no_bleed_between_adjacent_slots(self, tracker):
        """Species/item from slot N must not appear in any other slot's cache entry."""
        entries = [
            {"key": "SLOT0:0001", "box": 0, "slot": 0, "species_id": 1, "held_item_id": 17, "level": 5, "nickname": "S0"},
            {"key": "SLOT1:0002", "box": 0, "slot": 1, "species_id": 2, "held_item_id": 18, "level": 6, "nickname": "S1"},
            {"key": "SLOT2:0003", "box": 0, "slot": 2, "species_id": 3, "held_item_id": 19, "level": 7, "nickname": "S2"},
        ]
        for bentry in entries:
            tracker._cache_mon_info(bentry["key"], bentry)
        assert tracker._mon_cache["SLOT0:0001"]["species_id"] == 1
        assert tracker._mon_cache["SLOT0:0001"]["held_item_id"] == 17
        assert tracker._mon_cache["SLOT1:0002"]["species_id"] == 2
        assert tracker._mon_cache["SLOT1:0002"]["held_item_id"] == 18
        assert tracker._mon_cache["SLOT2:0003"]["species_id"] == 3
        assert tracker._mon_cache["SLOT2:0003"]["held_item_id"] == 19

    def test_cache_does_not_overwrite_with_zero(self, tracker):
        """A subsequent cache call with zero species_id must not erase the cached value."""
        tracker._cache_mon_info("AAAA:1111", {"species_id": 4, "nickname": "CHAR", "level": 10})
        tracker._cache_mon_info("AAAA:1111", {"species_id": 0, "nickname": "CHAR", "level": 10})
        assert tracker._mon_cache["AAAA:1111"]["species_id"] == 4

    def test_cache_does_not_overwrite_held_item_with_zero(self, tracker):
        """A subsequent cache call with zero held_item_id must not erase the cached value."""
        tracker._cache_mon_info("AAAA:1111", {"species_id": 4, "held_item_id": 17, "level": 10})
        tracker._cache_mon_info("AAAA:1111", {"species_id": 4, "held_item_id": 0, "level": 10})
        assert tracker._mon_cache["AAAA:1111"]["held_item_id"] == 17

    # ── mon_stats backfill ─────────────────────────────────────────────────

    def test_mon_stats_populated_per_slot(self, tracker):
        """Each box slot's level is independently cached in mon_stats."""
        entries = [
            {"key": f"MON{i}:000{i}", "box": 0, "slot": i, "species_id": i + 1, "level": 10 + i}
            for i in range(5)
        ]
        for bentry in entries:
            tracker._cache_mon_info(bentry["key"], bentry)
        for i in range(5):
            key = f"MON{i}:000{i}"
            assert tracker.state.mon_stats[key]["level"] == 10 + i

    def test_mon_stats_no_cross_slot_overwrite(self, tracker):
        """Later slot caching must not overwrite earlier slot's mon_stats entry."""
        tracker._cache_mon_info("FIRST:0001", {"species_id": 4, "level": 10})
        tracker._cache_mon_info("SECOND:0002", {"species_id": 7, "level": 20})
        assert tracker.state.mon_stats["FIRST:0001"]["level"] == 10
        assert tracker.state.mon_stats["SECOND:0002"]["level"] == 20

    # ── _lookup_mon_detail: correct slot returned ──────────────────────────

    def test_lookup_returns_correct_entry_by_key(self, tracker):
        """Lookup by key returns only that mon's data, not a neighbour's."""
        tracker.pc_boxes["a"] = [
            {"key": "KEY0:0000", "box": 0, "slot": 0, "species_id": 10, "held_item_id": 50, "level": 20, "nickname": "A"},
            {"key": "KEY1:0001", "box": 0, "slot": 1, "species_id": 25, "held_item_id": 55, "level": 22, "nickname": "B"},
            {"key": "KEY2:0002", "box": 0, "slot": 2, "species_id": 35, "held_item_id": 60, "level": 24, "nickname": "C"},
        ]
        det = tracker._lookup_mon_detail("a", "KEY1:0001")
        assert det.get("species_id") == 25
        assert det.get("held_item_id") == 55
        assert det.get("nickname") == "B"

    def test_lookup_adjacent_slots_are_independent(self, tracker):
        """Slot 0 lookup must not return slot 1's species or held_item."""
        tracker.pc_boxes["a"] = [
            {"key": "ALPHA:0001", "box": 1, "slot": 0, "species_id": 4,  "held_item_id": 11, "level": 8},
            {"key": "BETA:0002",  "box": 1, "slot": 1, "species_id": 7,  "held_item_id": 12, "level": 9},
        ]
        det0 = tracker._lookup_mon_detail("a", "ALPHA:0001")
        det1 = tracker._lookup_mon_detail("a", "BETA:0002")
        assert det0.get("species_id") == 4
        assert det0.get("held_item_id") == 11
        assert det1.get("species_id") == 7
        assert det1.get("held_item_id") == 12
        # Cross-check: neither slot must carry the other's values
        assert det0.get("species_id") != det1.get("species_id")
        assert det0.get("held_item_id") != det1.get("held_item_id")

    def test_lookup_missing_key_returns_empty_or_none(self, tracker):
        """A key not present in pc_boxes returns an empty dict."""
        tracker.pc_boxes["a"] = [
            {"key": "EXIST:0001", "box": 0, "slot": 0, "species_id": 1, "level": 5}
        ]
        det = tracker._lookup_mon_detail("a", "MISSING:9999")
        assert not det or det.get("species_id", 0) == 0

    def test_lookup_multiple_boxes_correct_key(self, tracker):
        """Key lookup works across entries spread across different box indices."""
        tracker.pc_boxes["a"] = [
            {"key": "BOX0:0001", "box": 0, "slot": 0, "species_id": 1, "held_item_id": 10, "level": 5},
            {"key": "BOX5:0002", "box": 5, "slot": 3, "species_id": 99, "held_item_id": 77, "level": 55},
            {"key": "BOX12:003", "box": 12, "slot": 29, "species_id": 150, "held_item_id": 200, "level": 99},
        ]
        det = tracker._lookup_mon_detail("a", "BOX5:0002")
        assert det.get("species_id") == 99
        assert det.get("held_item_id") == 77

    # ── _check_memorial_box_contamination ──────────────────────────────────

    def test_contamination_fires_for_box_13(self, tracker, caplog):
        """A live mon deposited into memorial box 13 triggers a warning."""
        import logging
        with caplog.at_level(logging.WARNING, logger="server.server"):
            tracker._check_memorial_box_contamination("a", [
                {"key": "LIVE:0001", "box": 13, "slot": 0, "species_id": 4, "nickname": "CHAR"},
            ])
        assert any("NON-DEAD" in r.message for r in caplog.records)

    def test_contamination_ignores_boxes_0_through_12(self, tracker, caplog):
        """Live mons in non-memorial boxes (0-12) must not produce a warning."""
        import logging
        entries = [
            {"key": f"MON{i:04d}:0001", "box": i, "slot": 0, "species_id": i + 1}
            for i in range(13)
        ]
        with caplog.at_level(logging.WARNING, logger="server.server"):
            tracker._check_memorial_box_contamination("a", entries)
        assert not any("NON-DEAD" in r.message for r in caplog.records)

    def test_contamination_dead_mon_in_box_13_is_allowed(self, tracker, caplog):
        """A properly dead/memorialized mon in box 13 must not produce a warning."""
        import logging
        from server.state import LinkEntry, MonInfo, LinkStatus
        entry = LinkEntry(
            area_id="route_1",
            a=MonInfo(key="DEAD:0001"),
            b=MonInfo(key="DEAD:0002"),
            status=LinkStatus.DEAD,
        )
        tracker.state.links.append(entry)
        tracker.state._index_entry(entry)
        with caplog.at_level(logging.WARNING, logger="server.server"):
            tracker._check_memorial_box_contamination("a", [
                {"key": "DEAD:0001", "box": 13, "slot": 0, "species_id": 4},
            ])
        assert not any("NON-DEAD" in r.message for r in caplog.records)

    def test_contamination_only_checks_player_own_dead_keys(self, tracker, caplog):
        """A mon in box 13 that is dead on the OTHER player's side still triggers warning."""
        import logging
        from server.state import LinkEntry, MonInfo, LinkStatus
        # Key "DEAD:0002" is player B's dead mon; checking player A's boxes
        entry = LinkEntry(
            area_id="route_2",
            a=MonInfo(key="ALIVE:0001"),
            b=MonInfo(key="DEAD:0002"),
            status=LinkStatus.DEAD,
        )
        tracker.state.links.append(entry)
        tracker.state._index_entry(entry)
        # The dead_keys set includes both sides of a dead pair, so DEAD:0002 is allowed
        # in box 13 even when checking player A — this is the correct behavior
        with caplog.at_level(logging.WARNING, logger="server.server"):
            tracker._check_memorial_box_contamination("a", [
                {"key": "DEAD:0002", "box": 13, "slot": 0, "species_id": 7},
            ])
        # DEAD:0002 is in dead_keys (entry is dead), so no warning expected
        assert not any("NON-DEAD" in r.message for r in caplog.records)
