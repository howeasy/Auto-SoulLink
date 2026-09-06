"""Detached shared broadcast data; never dispatches or changes game state."""

import copy
import hashlib

from markupsafe import Markup

from server.board import project_board
from server.html_render import stat_stages_html
from server.ui_projection import health


def _identity(*parts):
    return "broadcast-" + hashlib.sha256("\0".join(map(str, parts)).encode()).hexdigest()[:20]


def build_broadcast_context(server, preset, selected, controls):
    data = server._build_status_dict()
    run_id = server._run_id or "standalone"
    board = project_board(data, run_id=run_id)
    players = []

    def mon(raw, pid, key, *, show_hp=True):
        adapter = server.adapter_for(pid)
        species = raw.get("species_id", raw.get("species", 0))
        value = health(raw) if show_hp else health({})
        return {"id": _identity(run_id, pid, key), "key": key, "pid": pid,
                "name": raw.get("nickname") or raw.get("species_name") or "Unknown Pokémon",
                "species_name": raw.get("species_name") or (adapter.species_name(species) if species else ""),
                "sprite_html": Markup(raw.get("sprite_html") or (adapter.sprite_html(species, raw.get("form", 0)) if species else "")),
                "level": raw.get("level"), "health": value, "show_hp": show_hp,
                "status_cond": raw.get("status_cond", 0), "held_item_name": raw.get("held_item_name", ""),
                "ability_name": raw.get("ability_name", ""), "active": bool(raw.get("active")),
                "moves": copy.deepcopy(raw.get("move_details", [])),
                "stages_html": Markup(stat_stages_html(raw.get("stat_stages"), adapter.stat_stage_labels())) if raw.get("active") else ""}

    for pid in selected:
        source = data["players"][pid]
        player = board["players"][pid]
        adapter = server.adapter_for(pid)
        party = [mon(source["party_details"].get(key, {}), pid, key) for key in source.get("party_keys", [])]
        battle = source.get("battle_state", {})
        enemies = [mon(raw, pid, "enemy:" + str(index)) for index, raw in enumerate(battle.get("enemy_party", []))] if battle.get("in_battle") else []
        badge_mask = (source.get("badges") or 0) | ((source.get("kanto_badges") or 0) << 8)
        badges = [{"slug": slug, "name": label, "earned": bool(badge_mask & (1 << index))}
                  for index, (slug, label) in enumerate(adapter.gym_badge_slugs(source.get("rom_type") or ""))]
        table = source.get("encounter_table") or {}
        methods = []
        for method, entries in table.items():
            rows = []
            for index, entry in enumerate(entries):
                raw = {**entry, "species_name": entry.get("name") or entry.get("species_name")}
                rows.append({**mon(raw, pid, f"encounter:{method}:{index}", show_hp=False),
                             "rate": entry.get("rate"), "minimum": entry.get("min_level"), "maximum": entry.get("max_level")})
            methods.append({"name": method, "entries": rows})
        players.append({"pid": pid, "name": player["name"], "cartridge": player["cartridge"],
            "connection": player["connection"], "connected": player["connected"], "age": player["age"],
            "stale": player["stale"], "observed": player["observed"], "area": player["area"],
            "mons": party, "active_mons": [item for item in party if item["active"]],
            "enemies": enemies, "active_enemies": [item for item in enemies if item["active"]],
            "in_battle": bool(battle.get("in_battle")), "is_trainer": bool(battle.get("is_trainer_battle")),
            "doubles": bool(battle.get("is_doubles")), "opponent": player["opponent"],
            "badges": badges, "methods": methods})

    rows = []
    for pair in board["rows"]:
        row = {key: copy.deepcopy(pair[key]) for key in ("id", "area", "area_name", "status", "zone", "at_risk")}
        row["area_name"] = server._area_display(pair["area"]) if pair["area"] else pair["area_name"]
        row["a"] = mon(pair["a"], "a", pair["a"]["key"], show_hp=pair["a"]["show_hp"]) if pair["a"] else None
        row["b"] = mon(pair["b"], "b", pair["b"]["key"], show_hp=pair["b"]["show_hp"]) if pair["b"] else None
        rows.append(row)
    if preset == "linked-party":
        pairs = [row for row in rows if row["zone"] == "party"]
    elif preset == "boxed-links":
        pairs = [row for row in rows if row["zone"] in ("boxed", "split")]
    elif preset == "stream-memorial":
        pairs = [row for row in rows if row["zone"] == "fallen"]
    else:
        pairs = [row for row in rows if row["zone"] != "unlinked"]
    area_a, area_b = (data["players"][pid].get("current_area_id", "") for pid in ("a", "b"))
    focus_area = area_a or area_b
    if preset == "area-encounter":
        pairs = [row for row in rows if row["area"] == focus_area]
    filters = controls.get("filter")
    events = []
    for index, event in enumerate(data.get("recent_events", [])[:16]):
        if filters is not None and event.get("type") not in filters:
            continue
        pid = event.get("player") if event.get("player") in ("a", "b") else None
        events.append({"id": _identity(run_id, event.get("ts"), pid, event.get("type"), event.get("text"), index),
                       "time": server._format_event_ts(event.get("ts")), "pid": pid,
                       "who": board["players"][pid]["name"] if pid in ("a", "b") else "Run",
                       "text": event.get("text") or event.get("type") or "", "type": event.get("type", "")})
    states = list(data.get("area_states", {}).values())
    links = data.get("links", [])
    last = links[-1] if links else None
    last_pair = next((row for row in rows if last and row["area"] == last.get("area_id")
                      and all((row[pid] or {}).get("key") == last.get(pid + "_key") for pid in ("a", "b"))), None)
    return {"preset": preset, "players": players, "pairs": pairs, "events": events,
            "last_pair": last_pair,
            "attempts": data.get("attempts_count", 0), "alive": sum(link.get("status") == "alive" for link in links),
            "dead": sum(link.get("status") in ("dead", "memorial") for link in links),
            "encounters": len(links),
            "shinies": sum(bool(link.get("a_shiny") or link.get("b_shiny")) for link in links) + sum(len(data.get("bonus_keys", {}).get(pid, [])) for pid in ("a", "b")),
            "areas": {"linked": states.count("linked"), "failed": states.count("dead_zone"), "pending": sum(value.startswith("pending") for value in states)},
            "area": server._area_display(focus_area) if focus_area else "", "area_state": data.get("area_states", {}).get(focus_area, "unseen"),
            "run_id": run_id, "run_name": server._run_name or "Soul Link", "availability": "live", "controls": copy.deepcopy(controls)}
