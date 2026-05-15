"""Quick sanity test for submit_fired priority resolution."""
import asyncio
import sys
from unittest.mock import MagicMock, patch


def make_controller(triggers):
    with patch.dict("sys.modules", {"simpleobsws": MagicMock()}):
        from server.obs_controller import OBSController  # noqa: PLC0415

    ctrl = OBSController.__new__(OBSController)
    ctrl._config = {"enabled": True, "triggers": triggers}
    ctrl._queues = {"a": asyncio.Queue(maxsize=1), "b": asyncio.Queue(maxsize=1)}
    ctrl._workers = {}
    ctrl._reconnect_tasks = {}
    ctrl._clients = {}
    ctrl._status = {}
    return ctrl


def test_highest_priority_rule_wins():
    """When battle_start_new (idx 0) + wild_battle_start (idx 1) + battle_start (idx 2) all fire,
    only battle_start_new scene should be delivered."""
    triggers = [
        {"id": "t1", "event": "battle_start_new", "player_filter": "any", "target": "own", "scene": "NEW ENCOUNTER"},
        {"id": "t2", "event": "wild_battle_start", "player_filter": "any", "target": "own", "scene": "WILD BATTLE"},
        {"id": "t3", "event": "battle_start", "player_filter": "any", "target": "own", "scene": "BATTLE"},
    ]
    ctrl = make_controller(triggers)
    fired = [
        ("battle_start", "a", {}),
        ("wild_battle_start", "a", {}),
        ("battle_start_new", "a", {}),
    ]
    ctrl.submit_fired(fired)
    scene = ctrl._queues["a"].get_nowait()
    assert scene == "NEW ENCOUNTER", f"Expected 'NEW ENCOUNTER', got '{scene}'"


def test_lower_priority_wins_when_higher_not_fired():
    triggers = [
        {"id": "t1", "event": "battle_start_new", "player_filter": "any", "target": "own", "scene": "NEW ENCOUNTER"},
        {"id": "t2", "event": "wild_battle_start", "player_filter": "any", "target": "own", "scene": "WILD BATTLE"},
        {"id": "t3", "event": "battle_start", "player_filter": "any", "target": "own", "scene": "BATTLE"},
    ]
    ctrl = make_controller(triggers)
    fired = [
        ("battle_start", "a", {}),
        ("wild_battle_start", "a", {}),
        # battle_start_new NOT fired
    ]
    ctrl.submit_fired(fired)
    scene = ctrl._queues["a"].get_nowait()
    assert scene == "WILD BATTLE", f"Expected 'WILD BATTLE', got '{scene}'"


def test_both_players_resolved_independently():
    triggers = [
        {"id": "t1", "event": "faint", "player_filter": "a", "target": "a", "scene": "A DEATH"},
        {"id": "t2", "event": "link_death", "player_filter": "b", "target": "b", "scene": "B DEATH"},
        {"id": "t3", "event": "battle_start", "player_filter": "any", "target": "both", "scene": "BATTLE"},
    ]
    ctrl = make_controller(triggers)
    fired = [
        ("faint", "a", {}),
        ("link_death", "b", {}),
        ("battle_start", "a", {}),
    ]
    ctrl.submit_fired(fired)
    scene_a = ctrl._queues["a"].get_nowait()
    scene_b = ctrl._queues["b"].get_nowait()
    assert scene_a == "A DEATH", f"Got '{scene_a}'"
    assert scene_b == "B DEATH", f"Got '{scene_b}'"


def test_area_filter_respected():
    triggers = [
        {"id": "t1", "event": "area_enter", "player_filter": "any", "target": "own",
         "scene": "VIRIDIAN", "area_id_filter": "viridian_city"},
        {"id": "t2", "event": "area_enter", "player_filter": "any", "target": "own",
         "scene": "OTHER AREA", "area_id_filter": ""},
    ]
    ctrl = make_controller(triggers)
    fired = [("area_enter", "a", {"area_id": "route_1"})]
    ctrl.submit_fired(fired)
    scene = ctrl._queues["a"].get_nowait()
    assert scene == "OTHER AREA", f"Got '{scene}'"


if __name__ == "__main__":
    test_highest_priority_rule_wins()
    test_lower_priority_wins_when_higher_not_fired()
    test_both_players_resolved_independently()
    test_area_filter_respected()
    print("All OBS priority tests passed.")
