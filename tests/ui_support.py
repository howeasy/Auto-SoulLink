"""Hydrate isolated presentation state from archived captures, never a live run.

This is rendering evidence only. Captures do not contain command outboxes,
admission proofs or durable receipts; none are reconstructed or fabricated.
"""

import copy
import json
from collections import deque
from pathlib import Path

from server.adapters import game_id_for_rom_type, get_adapter
from server.server import SLinkServer
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo

DERIVED_FIELDS = {"sprite_html", "sprite_src", "species_name", "ability_name", "move_details"}


def _raw(mon):
    return {key: copy.deepcopy(value) for key, value in mon.items() if key not in DERIVED_FIELDS}


def _gen1_keys(capture):
    """Correct old mock-key suffixes using the actual cartridge index table."""
    index = json.loads((Path(__file__).resolve().parents[1] / "data/games/gen1_rby/species_index.json").read_text())
    internal = {int(dex): int(number) for number, dex in index["index_to_national"].items()}
    keys = {}

    def remember(key, species):
        if key and species in internal:
            keys[key] = key.rsplit(":", 1)[0] + f":{internal[species]:02X}"

    for row in capture["links"]:
        for player in ("a", "b"):
            remember(row.get(player + "_key"), row.get(player + "_species"))
    for player in capture["players"].values():
        for key, mon in player["party_details"].items():
            remember(key, mon.get("species_id"))
        for mon in player["pc_boxes"] + player["battle_state"].get("enemy_party", []):
            remember(mon.get("key"), mon.get("species_id"))
    for pending in capture["pending_captures"].values():
        for mon in pending.values():
            remember(mon.get("key"), mon.get("species"))

    def replace(value):
        if isinstance(value, dict):
            return {keys.get(key, key): replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return keys.get(value, value) if isinstance(value, str) else value

    return replace(capture)


def hydrate_capture(capture: dict, data_dir: Path) -> SLinkServer:
    """Build a complete legacy rendering context in a caller-owned empty directory."""
    data_dir = Path(data_dir)
    if data_dir.exists() and any(data_dir.iterdir()):
        raise ValueError("UI fixture hydration requires an empty isolated directory")
    data_dir.mkdir(parents=True, exist_ok=True)
    capture = copy.deepcopy(capture)
    variant = capture["players"]["a"]["rom_type"]
    game_id = game_id_for_rom_type(variant)
    if game_id is None:
        raise ValueError(f"unknown cartridge in UI capture: {variant}")
    if game_id == "gen1_rby":
        capture = _gen1_keys(capture)
    srv = SLinkServer(data_dir=str(data_dir))
    state = srv.state
    srv.adapter = state.adapter = get_adapter(game_id, is_rr=variant.endswith("_rr"), rom_type=variant)
    state.rom_type = variant
    for name, value in capture["rules"].items():
        setattr(state, name, value)
    kills = {entry["area_id"]: entry for entry in capture["killfeed"]}
    for row in capture["links"]:
        halves = [MonInfo(key=row[pid + "_key"], species=row[pid + "_species"],
                          nickname=row[pid + "_nickname"], level=row[pid + "_level"],
                          is_shiny=row.get(pid + "_shiny", False)) if row.get(pid + "_key") else None
                  for pid in ("a", "b")]
        death = kills.get(row["area_id"], {})
        entry = LinkEntry(row["area_id"], *halves, LinkStatus(row["status"]),
                          killed_at=death.get("killed_at"), cause=death.get("cause", ""),
                          killer=copy.deepcopy(death.get("killer")),
                          initiating_player=death.get("initiating_player", ""))
        for pid in ("a", "b"):
            if row.get(pid + "_enc_species"):
                setattr(entry, "encounter_" + pid, MonInfo("", species=row[pid + "_enc_species"],
                                                        level=row.get(pid + "_enc_level", 0)))
        state.links.append(entry)
        state._index_entry(entry)
    state.area_states = {area: AreaStatus(value) for area, value in capture["area_states"].items()}
    state.pending_captures = {area: {pid: MonInfo(**{key: mon[key] for key in ("key", "species", "nickname", "level")})
                                   for pid, mon in pending.items()}
                              for area, pending in capture["pending_captures"].items()}
    for pid, player in capture["players"].items():
        rom = player["rom_type"]
        srv._player_adapters[pid] = get_adapter(game_id_for_rom_type(rom), is_rr=rom.endswith("_rr"), rom_type=rom)
        srv.connected_players[pid] = {key: player[key] for key in ("connected", "rom_type", "last_event", "last_seen")}
        # No receipt timestamp/admission evidence is available in these historic
        # inputs. The current serializer reports age unknown and contract_pending.
        srv.player_area[pid] = player["current_area"]
        srv.player_area_id[pid] = player["current_area_id"]
        srv.player_ball_count[pid] = player["ball_count"]
        srv.player_badges[pid] = player["badges"]
        srv.player_kanto_badges[pid] = player["kanto_badges"]
        srv.trainer_name[pid] = state.trainer_names[pid] = player["trainer_name"]
        state.pokeballs_obtained[pid] = player["nuzlocke_active"]
        state.party_keys[pid] = set(player["party_keys"])
        srv.party_details[pid] = {key: _raw(mon) for key, mon in player["party_details"].items()}
        srv.pc_boxes[pid] = [_raw(mon) for mon in player["pc_boxes"]]
        srv.battle_state[pid] = copy.deepcopy(player["battle_state"])
        srv.battle_state[pid]["enemy_party"] = [_raw(mon) for mon in player["battle_state"].get("enemy_party", [])]
        for key, mon in srv.party_details[pid].items():
            srv._cache_mon_info(key, mon)
            state.mon_stats[key] = copy.deepcopy(mon)
        for mon in srv.pc_boxes[pid]:
            srv._cache_mon_info(mon["key"], mon)
        state.bonus_keys[pid] = set(capture["bonus_keys"][pid])
        state.pending_bonus[pid] = deque(capture["pending_bonus"][pid])
    state.run_over = capture["run_over"]
    state.attempts_count = capture["attempts_count"]
    srv._recent_events = deque(copy.deepcopy(capture["recent_events"]), maxlen=200)

    def no_mutations(*args, **kwargs):
        raise AssertionError("rendering a UI fixture attempted a state mutation")

    state._save = no_mutations
    state.handle_event = no_mutations
    return srv
