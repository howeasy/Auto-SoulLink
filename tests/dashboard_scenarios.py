"""Isolated extraction scenarios; no sockets, persistence or admission claims."""

import copy
import json
import time
from pathlib import Path

from server.server import SLinkServer
from tests.ui_support import hydrate_capture

SCENARIOS = ("empty", "gen3", "gen1", "warnings", "split", "doubles", "hp_boundaries",
             "stopped", "disconnected", "stale", "rejected", "unknown_hp", "persisted")
CLOCK = 1000000.0
SOURCE = Path(__file__).parent / "fixtures/ui/source"


def dashboard_scenario(name, directory):
    if name == "empty":
        return SLinkServer(data_dir=str(directory))
    game = "gen1" if name == "gen1" else "gen3"
    srv = hydrate_capture(json.loads((SOURCE / f"{game}.json").read_text(encoding="utf-8")), directory)
    if name == "warnings":
        srv.state.save_failed = 'Disk <busy> & "locked"'
        srv.state.run_over = True
        srv.state.identity_error["b"] = 'Wrong save <identity> & "trainer"'
        srv.connected_players["a"].update(connected=False, last_seen_ts=time.time() - 71)
        srv.trainer_name["a"] = '<Alice & "friend">'
        srv.state.species_lock = srv.state.gender_lock = srv.state.type_lock = True
    elif name == "split":
        key = sorted(srv.state.party_keys["b"])[0]
        srv.state.party_keys["b"].remove(key)
        srv.pc_boxes["b"].append({**copy.deepcopy(srv.party_details["b"][key]), "key": key, "box": 2, "slot": 6})
        key = "UNLINKED:fixture"
        srv.state.party_keys["a"].add(key)
        srv.party_details["a"][key] = {"species_id": 25, "nickname": "Solo", "level": 8, "hp": 7, "maxHP": 19}
    elif name == "doubles":
        srv.battle_state["a"] = copy.deepcopy(srv.battle_state["b"])
        for pid in ("a", "b"):
            battle = srv.battle_state[pid]
            battle["is_doubles"] = True
            battle["is_trainer_battle"] = True
            battle["opponent_name"] = 'Rival <One>'
            battle["opponent_class"] = 'Ace & Partner'
            foe = copy.deepcopy(battle["enemy_party"][0])
            foe.update(key="foe-second", species_id=19, hp=20, maxHP=31, active=True)
            battle["enemy_party"].append(foe)
            battle["enemy_party"][0]["stat_stages"] = [7, 6, 6, 8, 9, 6, 6]
    elif name == "hp_boundaries":
        for pid in ("a", "b"):
            for hp, mon in zip((0, 20, 35, 50, 51, 100), srv.party_details[pid].values(), strict=True):
                mon.update(hp=hp, maxHP=100, status_cond=0x08, stat_stages=[7, 6, 6, 8, 9, 6, 6])
    elif name == "stopped":
        from server.board import build_board_context
        srv._build_board_context = lambda: build_board_context(srv, running=False)
    elif name in ("disconnected", "stale"):
        srv.connected_players["a"].update(connected=name == "stale", last_seen_ts=time.time() - 20)
    elif name == "rejected":
        srv.admission["a"] = {"state": "rejected", "reason": 'Use the assigned cartridge <A> & its bound save.'}
    elif name == "unknown_hp":
        for mon in srv.party_details["b"].values():
            mon.pop("hp", None)
            mon.pop("maxHP", None)
    elif name == "persisted":
        srv.connected_players.clear()
        srv._mon_cache.clear()
        srv.state.mon_stats.clear()
        for pid in ("a", "b"):
            srv.state.party_keys[pid].clear()
            srv.party_details[pid].clear()
            srv.pc_boxes[pid].clear()
            srv.battle_state[pid] = {"in_battle": False, "enemy_party": []}
    return srv
