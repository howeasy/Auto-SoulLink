"""Presentation consumes independent backend facts and per-player adapters."""

import copy

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer
from server.state import LinkEntry, LinkStatus, MonInfo
from server.ui_projection import move_details, player_capabilities


def facts(**changes):
    return {"declared_cartridge": {"rom_type": "firered_rr"},
            "adapter": {"supports_abilities": True, "supports_info_panel": True,
                        "supports_explode_mode": False, "has_rival_trainers": True},
            "feature_gates": {"panel": False, "explode_mode": False, "rival_team_swap": True},
            "feature_readiness": None, **changes}


def test_capability_dimensions_remain_independent_and_detached():
    source = facts(feature_readiness={"rival_team_swap": False})
    before = copy.deepcopy(source)
    result = player_capabilities(source, {"explode_mode": True, "rival_team_swap": False})
    assert result["explode_mode"]["supported"] is False
    assert result["explode_mode"]["requested"] is True
    assert result["explode_mode"]["ready"] is None
    assert result["rival_team_swap"]["requested"] is False
    assert result["rival_team_swap"]["ready"] is False
    assert result["rival_team_swap"]["effective"] is True
    assert "requested" not in result["abilities"]
    result["info_panel"]["supported"] = False
    assert source == before


@pytest.mark.parametrize("rom_type", [None, "?", "unknown-cartridge", 42])
def test_unknown_identity_does_not_become_default_generation_support(rom_type):
    result = player_capabilities(facts(declared_cartridge={"rom_type": rom_type}), {"battle_calc": True})
    assert all(row["supported"] is None and row["effective"] is None and row["ready"] is None for row in result.values())
    assert result["battle_calc"]["requested"] is True


def test_verified_patch_facts_override_adapter_potential_without_aliasing_features():
    result = player_capabilities(facts(verified_cartridge={"capabilities": {"panel": False, "sfx": False}}), {})
    assert result["info_panel"]["supported"] is False
    assert result["native_sounds"]["supported"] is False
    assert result["native_messages"]["supported"] is None
    assert result["overworld_presence"]["effective"] is None
    assert result["rival_team_swap"]["supported"] is True


def test_non_boolean_gate_values_remain_unknown():
    result = player_capabilities(facts(feature_gates={"panel": 1}), {"explode_mode": "yes"})
    assert result["info_panel"]["effective"] is None
    assert result["explode_mode"]["requested"] is None


def test_rejected_identity_preserves_authoritative_explanation():
    reason = "Unrecognized cartridge identity; load a supported game and send HELLO again."
    result = player_capabilities(facts(declared_cartridge={}, admission={"state": "rejected", "reason": reason}), {})
    assert all(row["reason"] == reason and row["effective"] is None for row in result.values())


@pytest.mark.parametrize("rom_type", ["crystal", "heartgold", "pokemon_black"])
def test_other_generation_adapter_facts_do_not_claim_live_readiness(tmp_path, rom_type):
    from server.adapters import game_id_for_rom_type, get_adapter

    srv = SLinkServer(data_dir=str(tmp_path))
    srv._player_adapters["a"] = get_adapter(game_id_for_rom_type(rom_type), rom_type=rom_type)
    srv.connected_players["a"] = {"rom_type": rom_type, "connected": False}
    data = srv._build_status_dict()["players"]["a"]
    assert data["rom_type"] == rom_type and data["last_seen_age"] is None
    assert all(feature["ready"] is None for feature in data["capabilities"].values())
    assert data["capabilities"]["abilities"]["supported"] is (rom_type != "crystal")


def test_projection_recomputes_observation_age_and_preserves_identity_and_pending_work(tmp_path, monkeypatch):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.connected_players["a"] = {"rom_type": "firered", "connected": False, "last_seen_ts": 1000.0}
    srv.admission["a"] = {"state": "rejected", "reason": "Save identity does not match."}
    srv.state.identity_error["a"] = "The bound trainer differs."
    srv.state.queued_commands["a"].append({"cmd": "force_faint", "key": "pending"})
    before = copy.deepcopy(srv.state.to_document())
    monkeypatch.setattr("server.server.time.time", lambda: 1010.0)
    first = srv._build_status_dict()["players"]["a"]
    monkeypatch.setattr("server.server.time.time", lambda: 1025.0)
    second = srv._build_status_dict()["players"]["a"]
    assert (first["last_seen_age"], second["last_seen_age"]) == (10, 25)
    assert second["admission_reason"] == "Save identity does not match."
    assert second["identity_error"] == "The bound trainer differs." and second["queued"] == 1
    assert srv.state.to_document() == before


def test_move_enrichment_copies_adapter_data_and_preserves_pp_inputs():
    shared = {"name": "Move", "pp": 20}

    class Adapter(Gen3Adapter):
        def move_data(self, move):
            return shared

    mon = {"moves": [1], "pp": [3], "pp_bonuses": 2}
    original = copy.deepcopy(mon)
    assert move_details(Adapter(), mon) == [{"name": "Move", "pp": 28, "current_pp": 3}]
    assert move_details(Adapter(), mon, boxed=True) == [{"name": "Move", "pp": 20, "current_pp": 20}]
    assert mon == original and shared == {"name": "Move", "pp": 20}


def test_gen1_display_pp_matches_its_existing_codec_for_all_moves_and_ups():
    from server.adapters.gen1_rby import Gen1Adapter
    from server.gen1_party_codec import PartyCodec

    adapter, codec = Gen1Adapter(), PartyCodec("red")
    for move in range(1, 166):
        for ups in range(4):
            base_pp = codec.profile["move_pp"][str(move)]
            assert adapter.max_move_pp(base_pp, ups) == codec.max_pp(move, ups)
    assert adapter.max_move_pp(40, 3) == 61


def test_status_enrichment_uses_each_players_adapter_and_preserves_raw_caches(tmp_path):
    class TaggedAdapter(Gen3Adapter):
        def __init__(self, tag):
            super().__init__()
            self.tag = tag

        def species_name(self, species):
            return f"{self.tag}-species-{species}"

        def sprite_html(self, species, form=0):
            return f'<img data-owner="{self.tag}" data-species="{species}">'

        def item_name(self, item):
            return f"{self.tag}-item-{item}"

        def move_data(self, move):
            return {"name": f"{self.tag}-move-{move}", "pp": 20}

    srv = SLinkServer(data_dir=str(tmp_path))
    for pid in ("a", "b"):
        srv._player_adapters[pid] = TaggedAdapter(pid)
        srv.connected_players[pid] = {"rom_type": "firered", "connected": True}
        srv.party_details[pid] = {pid: {"species_id": 1, "level": 5, "hp": 20, "maxHP": 20,
                                       "held_item_id": 3, "moves": [33], "pp": [4]}}
        srv.state.party_keys[pid] = {pid}
        srv.pc_boxes[pid] = [{"key": pid + "-box", "species_id": 2, "held_item_id": 4, "moves": [33]}]
        srv.battle_state[pid]["enemy_party"] = [{"species_id": 3, "moves": [33]}]
    link = LinkEntry("route_1", MonInfo("a", species=1), MonInfo("b", species=1), LinkStatus.ALIVE,
                     killed_at="2026-09-06T00:00:00", killer={"species": 7}, initiating_player="b")
    srv.state.links.append(link)
    srv.state._index_entry(link)
    srv.state.pending_captures["route_2"] = {"b": MonInfo("pending", species=4)}
    before = copy.deepcopy((srv.party_details, srv.pc_boxes, srv.battle_state))
    data = srv._build_status_dict()
    for pid in ("a", "b"):
        row = data["players"][pid]
        mon = row["party_details"][pid]
        assert mon["key"] == pid
        assert mon["species_name"] == f"{pid}-species-1"
        assert mon["held_item_name"] == f"{pid}-item-3"
        assert mon["move_details"][0]["name"] == f"{pid}-move-33"
        assert row["pc_boxes"][0]["held_item_name"] == f"{pid}-item-4"
        assert row["battle_state"]["enemy_party"][0]["species_name"] == f"{pid}-species-3"
        assert data["links"][0][pid + "_species_name"] == f"{pid}-species-1"
    pending = data["pending_captures"]["route_2"]["b"]
    assert pending["species_name"] == "b-species-4" and 'data-owner="b"' in pending["sprite_html"]
    assert data["killfeed"][0]["killer"]["species_name"] == "b-species-7"
    assert (srv.party_details, srv.pc_boxes, srv.battle_state) == before
