"""Exercise the actual HELLO/tick projection call sites and their admission order."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

from server.server import SLinkServer


def party():
    return [{"key": "12345678:11111111", "species_id": 1, "nickname": "LEAD", "level": 10,
             "hp": 17, "maxHP": 30, "held_item": 44, "ability": 65,
             "moves": [1, 2, 3, 4], "pp": [5, 6, 7, 8], "slot": 2, "active": True,
             "status_cond": 8, "stat_stages": [8, 6, 5, 6, 6, 6, 6]}]


def legacy_hello(snapshot):
    return {"event": "hello", "rom_type": "firered", "player": "a", "trainer_name": "ALICE",
            "ot_id": "11111111", "party": snapshot, "in_battle": True}


def test_real_hello_and_tick_share_snapshot_fields_and_keep_state_dispatch_order(tmp_path, monkeypatch):
    srv = SLinkServer(data_dir=str(tmp_path))
    monkeypatch.setattr(srv, "_player_has_panel", lambda _: False)
    srv.party_details["a"] = {"prior": {"hp": 9}}
    original = srv.state.handle_event
    seen = []

    def dispatch(player, message, **kwargs):
        seen.append((message["event"], copy.deepcopy(srv.party_details[player])))
        return original(player, message, **kwargs)

    monkeypatch.setattr(srv.state, "handle_event", dispatch)
    incoming = party()
    commands = srv._dispatch("a", legacy_hello(incoming))
    assert any(c["cmd"] == "config" for c in commands)
    first = copy.deepcopy(srv.party_details["a"])
    detail = first[incoming[0]["key"]]
    assert detail["stat_stages"] == incoming[0]["stat_stages"]
    assert detail["held_item_id"] == 44 and detail["ability_id"] == 65
    assert detail["moves"] == [1, 2, 3, 4] and detail["pp"] == [5, 6, 7, 8]
    assert detail["slot"] == 2 and detail["active"] is True and detail["status_cond"] == 8
    srv._dispatch("a", {"event": "tick", "party": copy.deepcopy(incoming)})
    assert srv.party_details["a"] == first
    assert seen == [("hello", {"prior": {"hp": 9}}), ("tick", first)]
    # Every later tick replaces the snapshot; stages do not linger when absent.
    del incoming[0]["stat_stages"]
    incoming[0]["hp"] = 5
    srv._dispatch("a", {"event": "tick", "party": incoming})
    assert srv.party_details["a"][incoming[0]["key"]]["stat_stages"] is None
    assert seen[-1][1][incoming[0]["key"]]["stat_stages"] is None
    assert seen[-1][1][incoming[0]["key"]]["hp"] == 5


def test_snapshot_uses_recipient_adapter_and_preserves_existing_defaults_and_alias_precedence(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    gender = Mock(return_value="recipient-gender")
    srv._player_adapters["b"] = SimpleNamespace(gender_from_key=gender, calc_stats=Mock(return_value=None))
    incoming = [{"key": ""}, {"key": "K", "held_item": 99, "held_item_id": 0, "ability": 88, "ability_id": 0}]
    before, rules, cache = copy.deepcopy(incoming), copy.deepcopy((srv.state.links, srv.state.area_states)), copy.deepcopy(srv._mon_cache)
    result = srv._party_snapshot("b", incoming)
    assert set(result) == {"K"}
    assert result["K"] == {"level": 0, "hp": 1, "maxHP": 1, "nickname": "", "species_id": 0,
                           "held_item_id": 0, "ability_id": 0, "gender": "recipient-gender",
                           "moves": [], "pp": [], "slot": 1, "active": False, "status_cond": 0,
                           "stat_stages": None, "calc_stats": None}
    gender.assert_called_once_with("K", 0)
    assert incoming == before and (srv.state.links, srv.state.area_states) == rules and srv._mon_cache == cache


def test_tick_with_omitted_party_retains_display_and_empty_party_clears_it(tmp_path, monkeypatch):
    srv = SLinkServer(data_dir=str(tmp_path))
    monkeypatch.setattr(srv, "_player_has_panel", lambda _: False)
    srv._dispatch("a", legacy_hello(party()))
    before = copy.deepcopy(srv.party_details["a"])
    srv._dispatch("a", {"event": "tick"})
    assert srv.party_details["a"] == before
    srv._dispatch("a", {"event": "tick", "party": []})
    assert srv.party_details["a"] == {}


def test_hello_persists_mon_stats_for_the_party_it_just_cached(tmp_path, monkeypatch):
    """Q-2: the mon_stats written by _cache_mon_info in the hello handler's party
    loop must actually reach links.json, not just live in memory until some later
    save happens to catch it."""
    srv = SLinkServer(data_dir=str(tmp_path))
    monkeypatch.setattr(srv, "_player_has_panel", lambda _: False)
    key = party()[0]["key"]
    srv._dispatch("a", legacy_hello(party()))
    saved = json.loads((tmp_path / "links.json").read_text())
    assert key in saved["mon_stats"]
    assert saved["mon_stats"][key]["level"] == 10
    assert saved["mon_stats"][key]["maxHP"] == 30


def test_rejected_hello_never_constructs_or_publishes_a_new_party_snapshot(tmp_path, monkeypatch):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv._dispatch("a", legacy_hello(party()))
    before = copy.deepcopy(srv.party_details)
    projection = Mock(side_effect=AssertionError("rejected identity reached projection"))
    monkeypatch.setattr(srv, "_party_snapshot", projection)
    bad = legacy_hello([])
    bad["ot_id"] = "22222222"
    srv._dispatch("a", bad)
    assert srv.state.identity_error["a"] and srv.party_details == before
    projection.assert_not_called()

