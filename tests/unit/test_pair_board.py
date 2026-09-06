import copy

import pytest

from server.board import health, project_board
from server.status_payload import empty_status_payload


def pair_status():
    data = empty_status_payload()
    for pid, key in (("a", "A"), ("b", "B")):
        data["players"][pid].update(rom_type="firered_rr", connected=True, trainer_name=pid.upper(), party_keys=[key],
                                    party_details={key: {"species_id": 25, "species_name": "Pikachu", "nickname": key,
                                                        "hp": 40, "maxHP": 100, "level": 10, "active": True}})
    data["links"] = [{"area_id": "route_1", "area_display": "Route 1", "a_key": "A", "b_key": "B", "status": "alive",
                      "a_nickname": "A", "b_nickname": "B", "a_species_name": "Pikachu", "b_species_name": "Pikachu"}]
    data["area_states"] = {"route_1": "linked"}
    return data


def test_board_membership_uses_party_keys_instead_of_stale_details_cache():
    data = pair_status()
    data["players"]["b"]["party_keys"] = []
    data["players"]["b"]["pc_boxes"] = [{"key": "B", "species_name": "Pikachu", "box": 1, "slot": 3}]
    row = project_board(data)["rows"][0]
    assert row["zone"] == "split" and row["b"]["where"] == "box"
    assert not row["b"]["show_hp"] and not row["b"]["health"]["known"]
    data["players"]["b"]["pc_boxes"] = []
    assert project_board(data)["rows"][0]["zone"] == "linked"


@pytest.mark.parametrize("hp,maximum,risky,percent", [(346, 1000, True, 35), (35, 100, False, 35), (0, 100, True, 0), (70, 200, False, 35)])
def test_pair_risk_uses_weaker_raw_ratio_before_display_rounding(hp, maximum, risky, percent):
    data = pair_status()
    data["players"]["a"]["party_details"]["A"].update(hp=hp, maxHP=maximum)
    row = project_board(data)["rows"][0]
    assert row["at_risk"] is risky and row["risk_percent"] == percent


@pytest.mark.parametrize("hp,maximum,color", [(501, 1000, "high"), (50, 100, "mid"), (201, 1000, "mid"), (20, 100, "low")])
def test_hp_color_boundaries_use_raw_ratios(hp, maximum, color):
    assert health({"hp": hp, "maxHP": maximum})["color"] == color


@pytest.mark.parametrize("mon", [{}, {"hp": 1}, {"hp": None, "maxHP": 100}, {"hp": 1, "maxHP": 0}, {"hp": float("nan"), "maxHP": 100}, {"hp": True, "maxHP": 100}])
def test_unknown_hp_is_never_projected_as_zero(mon):
    value = health(mon)
    assert not value["known"] and value["percent"] is None and value["hp"] is None


def test_stopped_runs_only_show_persisted_links_without_now_or_telemetry():
    data = pair_status()
    data["players"]["a"]["capabilities"]["native_sounds"].update(ready=True, effective=True)
    data["players"]["a"]["battle_state"] = {"in_battle": True, "enemy_party": [{"species_name": "Foe"}]}
    result = project_board(data, running=False)
    assert not result["running"] and result["status"] is None
    assert result["rows"][0]["zone"] == "linked"
    assert result["players"]["a"]["capabilities"]["native_sounds"]["ready"] is None
    assert result["players"]["a"]["capabilities"]["native_sounds"]["effective"] is None
    assert all(not player["battle"] and not player["observed"] and not player["foes"] for player in result["players"].values())
    for pid in ("a", "b"):
        mon = result["rows"][0][pid]
        assert mon["where"] is None and not mon["active"] and not mon["show_hp"]
        assert not mon["health"]["known"]


def test_disconnected_players_keep_labeled_last_observations():
    data = pair_status()
    data["players"]["a"].update(connected=False, last_seen_age=20)
    result = project_board(data)
    assert "last observation" in result["players"]["a"]["connection"]
    assert result["rows"][0]["a"]["last_observation"]
    assert result["rows"][0]["a"]["health"]["hp"] == 40


def test_unlinked_active_members_and_failed_caught_halves_are_retained():
    data = pair_status()
    data["players"]["a"]["party_keys"].append("SOLO")
    data["players"]["a"]["party_details"]["SOLO"] = {"active": True, "nickname": "Solo", "hp": 3, "maxHP": 10}
    data["players"]["a"]["battle_state"]["in_battle"] = True
    data["pending_captures"] = {"route_2": {"b": {"key": "CAUGHT", "nickname": "Caught", "species_name": "Pidgey"}}}
    data["area_states"]["route_2"] = "dead_zone"
    result = project_board(data)
    solo = next(row for row in result["rows"] if row["zone"] == "unlinked")
    failed = next(row for row in result["rows"] if row["area"] == "route_2")
    assert solo["a"]["key"] == "SOLO" and solo["a"]["active"] and solo["b"] is None
    assert failed["zone"] == "fallen" and failed["b"]["key"] == "CAUGHT" and failed["a"] is None


def test_doubles_keep_the_full_opposing_side_with_the_fighting_owner():
    data = pair_status()
    foes = [{"key": "foe-1", "active": True}, {"key": "foe-2", "active": True}, {"key": "foe-3", "active": False}]
    data["players"]["b"]["battle_state"] = {"in_battle": True, "is_doubles": True, "enemy_party": foes}
    data["players"]["b"]["party_keys"].append("SECOND")
    data["players"]["b"]["party_details"]["SECOND"] = {"active": True, "nickname": "Second"}
    result = project_board(data)
    for row in result["rows"]:
        if row["b"] and row["b"]["active"]:
            assert row["b"]["foes"] == foes
    assert result["rows"][0]["a"]["at_stake"] and not result["rows"][0]["a"]["foes"]


def test_projection_is_detached_and_empty_run_does_not_invent_observations():
    source = pair_status()
    before = copy.deepcopy(source)
    result = project_board(source)
    result["rows"][0]["a"]["nickname"] = "changed"
    assert source == before
    empty = project_board(empty_status_payload())
    assert not empty["rows"] and all(not player["observed"] for player in empty["players"].values())


def test_unknown_partner_hp_does_not_become_a_known_pair_percentage():
    data = pair_status()
    data["players"]["a"]["party_details"]["A"]["hp"] = None
    row = project_board(data)["rows"][0]
    assert row["risk_unknown"] and row["risk_percent"] is None and not row["at_risk"]
    data["players"]["b"]["party_details"]["B"]["hp"] = 10
    row = project_board(data)["rows"][0]
    assert row["at_risk"] and row["risk_percent"] is None


def test_mon_identity_survives_zone_changes_and_is_scoped_by_run_and_player():
    data = pair_status()
    first = project_board(data, run_id="one")["rows"][0]
    data["players"]["a"]["party_keys"] = []
    data["players"]["a"]["pc_boxes"] = [{"key": "A"}]
    moved = project_board(data, run_id="one")["rows"][0]
    assert first["a"]["id"] == moved["a"]["id"] and first["id"] == moved["id"]
    assert project_board(data, run_id="two")["rows"][0]["a"]["id"] != moved["a"]["id"]


def test_board_context_is_detached_from_runtime_caches(tmp_path):
    import json

    from server.board import build_board_context, render_board
    from tests.dashboard_scenarios import dashboard_scenario

    server = dashboard_scenario("gen3", tmp_path / "isolated")
    context = build_board_context(server)
    before = render_board(context)
    serialized = json.dumps(context)
    server.party_details.clear()
    server.pc_boxes.clear()
    server.state.links.clear()
    assert render_board(context) == before and json.dumps(context) == serialized


def test_stopped_render_has_no_now_hp_or_battle_elements(tmp_path):
    from server.board import build_board_context, render_board
    from tests.dashboard_scenarios import dashboard_scenario
    from tests.html_contract import Document

    server = dashboard_scenario("gen3", tmp_path / "isolated")
    dom = Document(render_board(build_board_context(server, running=False)))
    assert not [node for node in dom.root.descendants() if "data-now-player" in node.attrs or "data-foe-owner" in node.attrs]
    assert not [node for node in dom.root.descendants() if node.attrs.get("role") == "progressbar"]
    assert any(node.attrs.get("data-zone") == "linked" for node in dom.root.descendants())
