"""Read-only pair-board projection using authoritative party membership."""

import copy
import hashlib
import math

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from server.adapters import game_id_for_rom_type, variant_label
from server.html_render import move_table_html, stat_stages_html, status_icon_html
from server.templating import TEMPLATES_DIR
from server.ui_projection import health

_ENVIRONMENT = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(["html", "xml", "j2"]))


def render_board(context):
    return _ENVIRONMENT.get_template("board.html").render(context)

ZONES = (("party", "In party"), ("pending", "Pending link"), ("split", "Split"),
         ("boxed", "Boxed"), ("unlinked", "Unlinked"), ("linked", "Linked"), ("fallen", "Fallen"))
OPTION_LABELS = {"species_lock": "Species clause", "gender_lock": "Gender clause", "type_lock": "Type clause",
                 "explode_mode": "Explode mode", "rival_team_swap": "Rival team swap",
                 "overworld_presence": "Partner in the overworld", "native_messages": "In-game messages",
                 "native_sounds": "In-game sounds", "battle_calc": "Battle calculator", "pc_trade_npc": "PC trade helper"}
FAMILIES = {"gen1_rby": "Red / Blue / Yellow", "gen2_crystal": "Gold / Silver / Crystal",
            "gen3_frlge": "FireRed / LeafGreen / Emerald", "gen4_hgsspt": "HeartGold / SoulSilver / Platinum",
            "gen5_bw": "Black / White / Black 2 / White 2"}


def _id(kind, *values):
    value = "\0".join(str(item) for item in values)
    return kind + "-" + hashlib.sha256(value.encode()).hexdigest()[:20]


def project_board(status, *, run_id="standalone", running=True):
    """Project supplied observations; no inferred party locations for stopped runs.

    Sprite HTML is a trusted presentation-adapter field, never client text.
    All other strings remain ordinary text for template autoescaping.
    """
    data = copy.deepcopy(status)
    players, party, boxes = {}, {}, {}
    for pid in ("a", "b"):
        source = data["players"][pid]
        keys = source.get("party_keys", []) if running else []
        party[pid] = {key: source.get("party_details", {}).get(key, {}) for key in keys}
        boxes[pid] = {mon["key"]: mon for mon in source.get("pc_boxes", []) if mon.get("key")} if running else {}
        rom = source.get("rom_type")
        recognized = isinstance(rom, str) and game_id_for_rom_type(rom) is not None
        observed = running and (recognized or bool(keys) or bool(boxes[pid]))
        age = source.get("last_seen_age") if running else None
        stale = running and age is not None and age >= 10
        connection = ("Stopped" if not running else ("Connection is stale · waiting for game" if stale else "Waiting for game") if not observed else
                      "Connection rejected" if source.get("admission") == "rejected" else
                      "Disconnected · last observation" if not source.get("connected") else
                      "Last observation is stale" if age is not None and age >= 10 else "Connected")
        battle = source.get("battle_state", {}) if running else {}
        capabilities = copy.deepcopy(source.get("capabilities", {}))
        if not running:
            for capability in capabilities.values():
                capability["ready"] = capability["effective"] = None
                if capability.get("supported") is not False:
                    capability["reason"] = "Runtime availability is unknown while this run is stopped."
        players[pid] = {"pid": pid, "name": source.get("trainer_name") or "Player " + pid.upper(),
                        "cartridge": variant_label(rom) if recognized else "Cartridge not recorded" if not running else "Waiting for game",
                        "observed": observed, "connected": running and bool(source.get("connected")), "connection": connection,
                        "age": age, "stale": stale,
                        "admission": source.get("admission"), "admission_reason": source.get("admission_reason", ""),
                        "identity_error": source.get("identity_error", ""), "capabilities": capabilities,
                        "area": source.get("current_area_display", "") if observed else "", "area_id": source.get("current_area_id", "") if observed else "",
                        "balls": source.get("ball_count") if observed else None,
                        "nuzlocke_active": source.get("nuzlocke_active", False),
                        "badges": source.get("badges") if observed else None, "queued": source.get("queued", 0) if running else None,
                        "battle": bool(battle.get("in_battle")), "doubles": bool(battle.get("is_doubles")),
                        "foes": copy.deepcopy(battle.get("enemy_party", [])),
                        "opponent": " ".join(filter(None, [battle.get("opponent_class", ""), battle.get("opponent_name", "")])) if battle.get("is_trainer_battle") else "Wild encounter",
                        "unplaced_battle": False}

    def half(pid, key, stored=None):
        if not key:
            return None
        stored = stored or {}
        location = "party" if key in party[pid] else "box" if key in boxes[pid] else None
        observation = party[pid].get(key, {}) if location == "party" else boxes[pid].get(key, {}) if location == "box" else {}
        result = {**stored, **observation, "key": key, "pid": pid, "where": location,
                  "id": _id("mon", run_id, pid, key), "health": health(observation) if location == "party" else health({}),
                  "active": location == "party" and players[pid]["battle"] and bool(observation.get("active")),
                  "show_hp": location == "party", "at_stake": False, "foes": [],
                  "last_observation": not players[pid]["connected"] or players[pid]["stale"],
                  "nickname": observation.get("nickname") or stored.get("nickname", ""),
                  "species_name": observation.get("species_name") or stored.get("species_name") or "Unknown Pokémon",
                  "sprite_html": observation.get("sprite_html") or stored.get("sprite_html", ""),
                  "level": observation.get("level") or stored.get("level"),
                  "ability_name": observation.get("ability_name", ""), "held_item_name": observation.get("held_item_name", "")}
        return result

    rows, used = [], {pid: set() for pid in ("a", "b")}
    deaths = {entry["area_id"]: entry for entry in data.get("killfeed", [])}
    areas = data.get("area_states", {})
    for link in data.get("links", []):
        area = link["area_id"]
        row = {"area": area, "area_name": link.get("area_display") or area, "status": link.get("status", "unknown"),
               "id": _id("pair", run_id, area, link.get("a_key"), link.get("b_key")), "death": deaths.get(area), "at_risk": False}
        for pid in ("a", "b"):
            key = link.get(pid + "_key")
            stored = {"nickname": link.get(pid + "_nickname", ""), "species_name": link.get(pid + "_species_name", ""),
                      "sprite_html": link.get(pid + "_sprite_html", ""), "species_id": link.get(pid + "_species", 0),
                      "level": link.get(pid + "_level"), "shiny": link.get(pid + "_shiny", False)}
            row[pid] = half(pid, key, stored)
            if key:
                used[pid].add(key)
        dead = row["status"] in ("dead", "memorial", "dead_zone") or areas.get(area) == "dead_zone"
        if dead:
            row["zone"] = "fallen"
            if areas.get(area) == "dead_zone":
                row["status"] = "dead_zone"
            for mon in (row["a"], row["b"]):
                if mon:
                    mon.update(active=False, show_hp=False)
        elif not running:
            row["zone"] = "linked"
        elif not row["a"] or not row["b"]:
            row["zone"] = "pending"
        else:
            locations = (row["a"]["where"], row["b"]["where"])
            row["zone"] = ("party" if locations == ("party", "party") else "boxed" if locations == ("box", "box")
                           else "split" if set(locations) == {"party", "box"} else "linked")
        ratios = [mon["health"]["ratio"] for mon in (row["a"], row["b"]) if mon and mon["show_hp"] and mon["health"]["known"]]
        row["risk_unknown"] = row["zone"] == "party" and len(ratios) < 2
        row["risk_percent"] = math.floor(min(ratios) * 100 + .5) if len(ratios) == 2 else None
        row["at_risk"] = row["zone"] == "party" and bool(ratios) and min(ratios) < .35
        rows.append(row)

    # A failed encounter can retain a caught half even without a complete link.
    for area, captures in sorted(data.get("pending_captures", {}).items()):
        row = {"area": area, "area_name": area, "status": "pending", "zone": "pending" if running else "linked",
               "id": _id("capture", run_id, area, *(captures.get(pid, {}).get("key") for pid in ("a", "b"))),
               "death": deaths.get(area), "at_risk": False, "risk_percent": None}
        for pid in ("a", "b"):
            capture = captures.get(pid)
            key = capture.get("key") if capture else None
            row[pid] = half(pid, key, capture) if key and key not in used[pid] else None
            if row[pid]:
                used[pid].add(key)
        if not row["a"] and not row["b"]:
            continue
        if areas.get(area) == "dead_zone":
            row.update(zone="fallen", status="dead_zone")
            for mon in (row["a"], row["b"]):
                if mon:
                    mon.update(active=False, show_hp=False)
        rows.append(row)
    represented = {row["area"] for row in rows}
    for area, state in sorted(areas.items()):
        if state == "dead_zone" and area not in represented:
            rows.append({"area": area, "area_name": area, "status": "dead_zone", "zone": "fallen", "a": None, "b": None,
                         "id": _id("failed", run_id, area), "death": deaths.get(area), "at_risk": False, "risk_percent": None})
    if running:
        for pid in ("a", "b"):
            for key in dict.fromkeys([*party[pid], *boxes[pid]]):
                if key in used[pid]:
                    continue
                mon = half(pid, key)
                rows.append({"id": _id("unlinked", run_id, pid, key), "area": "", "area_name": "Unlinked", "status": "unlinked", "zone": "unlinked",
                             "a": mon if pid == "a" else None, "b": mon if pid == "b" else None,
                             "death": None, "at_risk": False, "risk_percent": None})
    for row in rows:
        for pid, other in (("a", "b"), ("b", "a")):
            mon = row[pid]
            if not mon:
                continue
            mon["at_stake"] = bool(row[other] and row[other]["active"])
            if mon["active"]:
                mon["foes"] = copy.deepcopy(players[pid]["foes"])
    for pid in ("a", "b"):
        players[pid]["unplaced_battle"] = players[pid]["battle"] and not any(row[pid] and row[pid]["active"] for row in rows)
    return {"run_id": run_id, "running": running, "players": players, "rows": rows,
            "zones": [{"key": key, "name": name, "rows": [row for row in rows if row["zone"] == key]} for key, name in ZONES
                      if any(row["zone"] == key for row in rows)], "save_failed": data.get("save_failed", ""),
            "run_over": data.get("run_over", False), "attempts": data.get("attempts_count", 0),
            "events": data.get("recent_events", []) if running else [], "rules": data.get("rules", {}), "status": data if running else None}


def build_board_context(server, *, running=True):
    from server.server import _age_label

    run_id = server._run_id or "standalone"
    data = server._build_status_dict()
    for pid in ("a", "b"):
        adapter = server.adapter_for(pid)
        for mon in data["players"][pid].get("battle_state", {}).get("enemy_party", []):
            mon["sprite_html"] = adapter.sprite_html(mon.get("species_id", 0), mon.get("form", 0))
    result = project_board(data, run_id=run_id, running=running)
    for pid, player in result["players"].items():
        adapter = server.adapter_for(pid)
        player["age_label"] = _age_label(player["age"])
        player["widgets"] = Markup(server._encounter_html(player["area_id"], pid, key_prefix=f"board:{run_id}:") if player["observed"] else "")
        player["trainers"] = Markup(server._trainer_panel_html(player["area_id"], pid, key_prefix=f"board:{run_id}:",
                                        highest_party_level=max((m.get("level", 0) or 0 for m in data["players"][pid]["party_details"].values()), default=0))
                                    if player["observed"] else "")
        badge_mask = (player["badges"] or 0) | ((data["players"][pid].get("kanto_badges") or 0) << 8)
        rom_type = data["players"][pid].get("rom_type", "")
        player["badge_slots"] = [{"name": name, "earned": bool(badge_mask & (1 << index))}
                                  for index, (_, name) in enumerate(adapter.gym_badge_slugs(rom_type if isinstance(rom_type, str) else ""))]
        player["badge_count"] = sum(badge["earned"] for badge in player["badge_slots"])
    for row in result["rows"]:
        if row["area"]:
            row["area_name"] = server._area_display(row["area"])
        for pid in ("a", "b"):
            mon = row[pid]
            if not mon:
                continue
            adapter = server.adapter_for(pid)
            mon["sprite_html"] = Markup(mon["sprite_html"])
            mon["moves_html"] = Markup(move_table_html(mon.get("move_details", []), mon_key=f"board:{run_id}:{pid}:{mon['key']}", is_box=mon["where"] == "box")) if running else ""
            mon["status_html"] = Markup(status_icon_html(mon.get("status_cond", 0))) if mon["show_hp"] else ""
            mon["stages_html"] = Markup(stat_stages_html(mon.get("stat_stages"), adapter.stat_stage_labels())) if mon["active"] else ""
            for index, foe in enumerate(mon["foes"]):
                foe["sprite_html"] = Markup(foe["sprite_html"])
                foe["health"] = health(foe)
                foe["moves_html"] = Markup(move_table_html(foe.get("move_details", []), mon_key=f"board:{run_id}:{pid}:{mon['key']}:foe:{index}"))
                foe["status_html"] = Markup(status_icon_html(foe.get("status_cond", 0)))
                foe["stages_html"] = Markup(stat_stages_html(foe.get("stat_stages"), adapter.stat_stage_labels())) if foe.get("active") else ""
    for pid, player in result["players"].items():
        adapter = server.adapter_for(pid)
        for index, foe in enumerate(player["foes"]):
            foe["sprite_html"] = Markup(foe.get("sprite_html", ""))
            foe["health"] = health(foe)
            foe["moves_html"] = Markup(move_table_html(foe.get("move_details", []), mon_key=f"board:{run_id}:{pid}:unplaced:foe:{index}"))
            foe["status_html"] = Markup(status_icon_html(foe.get("status_cond", 0)))
            foe["stages_html"] = Markup(stat_stages_html(foe.get("stat_stages"), adapter.stat_stage_labels())) if foe.get("active") else ""
    facts = server.read_runtime_facts()
    result.update(page_title="Soul Link — " + (server._run_name or "Run"), run_name=server._run_name or "Soul Link",
                  game_family=FAMILIES.get(server.adapter.game_id, "Game family not recorded"),
                  theme="default", body_class="slink-board", default_font="jersey", sidebar_assets=False,
                  is_stream=False, hide_chrome=False, view="board", board_url="/",
                  debug_operations=facts["operations"]["http"],
                  options=[{"key": key, "name": label, "requested": data["rules"].get(key)} for key, label in OPTION_LABELS.items()])
    return result
