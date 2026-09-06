"""Isolated extraction scenarios; no sockets, persistence or admission claims."""

import copy
import json
from pathlib import Path

from server.server import SLinkServer
from tests.ui_support import hydrate_capture

SCENARIOS = ("empty", "gen3", "gen1", "warnings", "split", "doubles", "hp_boundaries")
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
        srv.connected_players["a"].update(connected=False, last_seen_ts=CLOCK - 71)
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
    return srv
