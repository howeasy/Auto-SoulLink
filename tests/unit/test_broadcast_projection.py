import copy

import pytest

from server.broadcast_presets import PRESETS, default_controls
from server.broadcast_projection import build_broadcast_context
from tests.dashboard_scenarios import dashboard_scenario


@pytest.mark.parametrize("game", ["gen3", "gen1"])
def test_every_preset_projects_detached_data_with_explicit_player_identity(tmp_path, game):
    server = dashboard_scenario(game, tmp_path / game)
    before = copy.deepcopy(server.state.to_document())
    for preset in PRESETS:
        context = build_broadcast_context(server, preset, ["a", "b"], default_controls(preset))
        assert [player["pid"] for player in context["players"]] == ["a", "b"]
        assert context["players"][0]["name"] == "Alice"
        for player in context["players"]:
            assert {mon["key"] for mon in player["mons"]} == server.state.party_keys[player["pid"]]
            assert all(mon["pid"] == player["pid"] for mon in player["mons"] + player["enemies"])
        context["players"][0]["mons"].clear()
        assert server.state.to_document() == before


def test_unknown_hp_disconnected_observations_and_doubles_remain_distinct(tmp_path):
    server = dashboard_scenario("doubles", tmp_path / "doubles")
    server.connected_players["a"]["connected"] = False
    for mon in server.party_details["a"].values():
        mon.pop("hp", None)
        mon.pop("maxHP", None)
    context = build_broadcast_context(server, "enemy-focus", ["a", "b"], {})
    a, b = context["players"]
    assert a["connection"] == "Disconnected · last observation"
    assert all(not mon["health"]["known"] for mon in a["mons"])
    assert a["doubles"] and b["doubles"] and len(a["active_enemies"]) == 2
    for mon in server.battle_state["a"]["enemy_party"]:
        mon["active"] = False
    result = build_broadcast_context(server, "enemy-focus", ["a"], {})
    assert result["players"][0]["active_enemies"] == []  # no invented opponent targeting
    assert len(result["players"][0]["enemies"]) >= 2


def test_boxed_links_require_observed_box_membership_and_party_keeps_unlinked_mons(tmp_path):
    server = dashboard_scenario("split", tmp_path / "split")
    result = build_broadcast_context(server, "boxed-links", ["a", "b"], {})
    assert result["pairs"] and all(row["zone"] in ("boxed", "split") for row in result["pairs"])
    party = build_broadcast_context(server, "party", ["a"], {})
    assert any(mon["name"] == "Solo" for mon in party["players"][0]["mons"])


def test_event_filters_can_explicitly_hide_all_events(tmp_path):
    from types import SimpleNamespace
    from server.broadcast_render import legacy_configuration
    request = SimpleNamespace(query={"filter": "   "}, cookies={}, headers={})
    assert legacy_configuration(request, "events")["controls"]["filter"] is None
    server = dashboard_scenario("gen3", tmp_path / "gen3")
    assert build_broadcast_context(server, "events", ["a", "b"], {"filter": None})["events"]
    assert not build_broadcast_context(server, "events", ["a", "b"], {"filter": []})["events"]
    result = build_broadcast_context(server, "ticker", ["a", "b"], {"filter": ["capture"]})
    assert all(event["type"] == "capture" for event in result["events"])


@pytest.mark.parametrize("game,badges", [("gen2", (16, 16)), ("gen4", (16, 8)), ("gen5", (8, 8))])
def test_representative_capabilities_preserve_cartridge_badges_without_live_claims(tmp_path, game, badges):
    from tests.broadcast_scenarios import capability_scenario
    server = capability_scenario(game, tmp_path / game)
    for preset in PRESETS:
        context = build_broadcast_context(server, preset, ["a", "b"], default_controls(preset))
        assert "no live admission" in context["run_name"]
        assert tuple(len(player["badges"]) for player in context["players"]) == badges
        assert all(not player["connected"] and "last observation" in player["connection"] for player in context["players"])


def test_encounter_tracker_last_pair_follows_link_order_not_board_zones(tmp_path):
    server = dashboard_scenario("gen3", tmp_path / "gen3")
    result = build_broadcast_context(server, "encounters", ["a", "b"], {})
    last = server._build_status_dict()["links"][-1]
    assert result["last_pair"]["area"] == last["area_id"]
    assert all(result["last_pair"][pid]["key"] == last[pid + "_key"] for pid in ("a", "b"))
