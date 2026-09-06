"""Detached data for the equivalent dashboard templates.

The builder reads the runtime once per response. Templates receive only data and
explicitly trusted existing widget output, never a server, state object or adapter.
"""

import copy
import json
import re
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from server.adapters import variant_label
from server.html_render import move_table_html, stat_stages_html, status_icon_html, type_badges_html
from server.pokemon_data import GENDER_SYMBOL
from server.templating import TEMPLATES_DIR

_ENVIRONMENT = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(["html", "xml", "j2"]))


def render_dashboard(context):
    """Render a previously built context without access to the runtime."""
    return _ENVIRONMENT.get_template("dashboard.html").render(context)

ROM_LABELS = {
    "firered": "FireRed", "leafgreen": "LeafGreen", "firered_ap": "FireRed (AP)",
    "leafgreen_ap": "LeafGreen (AP)", "firered_rr": "FireRed (Radical Red)",
    "heartgold": "HeartGold", "soulsilver": "SoulSilver", "platinum": "Platinum", "hgss": "HGSS",
    "red": "Red", "blue": "Blue", "yellow": "Yellow", "Red": "Red", "Blue": "Blue", "Yellow": "Yellow",
}
GYM_BADGES = (("#a0a0a0", "Boulder Badge"), ("#4488ff", "Cascade Badge"),
              ("#ffcc00", "Thunder Badge"), ("#44cc44", "Rainbow Badge"),
              ("#cc44cc", "Soul Badge"), ("#ff6688", "Marsh Badge"),
              ("#ff4400", "Volcano Badge"), ("#88cc44", "Earth Badge"))
RULE_BADGES = (("species_lock", "dna", "Species Clause"), ("gender_lock", "gender", "Gender Clause"),
               ("type_lock", "type", "Type Clause"), ("explode_mode", "explode", "Explode Mode"),
               ("rival_team_swap", "rival-swap", "Rival Team Swap"),
               ("overworld_presence", "presence", "Overworld Presence"))
STATUS_SORT = {"pending_a": "0", "pending_b": "0", "pending_both": "0", "alive": "1",
               "linked": "1", "dead": "2", "dead_zone": "3", "memorial": "4"}


def build_dashboard_context(server):
    # Shared legacy utilities remain import-compatible during extraction.
    from server.server import STALE_AFTER_SECS, _age_label, _nature_from_key

    data = server._build_status_dict()
    state, adapter = server.state, server.adapter
    has_abilities = bool(adapter and adapter.supports_abilities())
    players = data["players"]
    pending = {pid: {mon["key"]: area for area, captures in data["pending_captures"].items()
                     for owner, mon in captures.items() if owner == pid} for pid in ("a", "b")}
    memorial_keys = {mon.key for entry in state.links if entry.status.value in ("memorial", "dead")
                     for mon in (entry.a, entry.b) if mon and mon.key}
    for keys in state.pending_memorials.values():
        memorial_keys.update(keys)
    memorial_indices = server._memorial_box_indices()

    def label(key, nickname, species, gender="", shiny=False):
        return {"nickname": nickname or "", "species": adapter.species_name(species) if species else "",
                "gender": gender, "gender_symbol": GENDER_SYMBOL.get(gender, ""), "shiny": shiny,
                "fallback": (key or "")[:8] + "…"}

    def types(species):
        return Markup(type_badges_html(species, adapter=adapter))

    def hp_cell(detail, *, enemy=False):
        hp = detail.get("hp", 0) if enemy else int(detail.get("hp", 0) or 0)
        maximum = detail.get("maxHP", 1) if enemy else int(detail.get("maxHP", 0) or 0)
        percent = max(0, min(100, int(hp / maximum * 100))) if maximum else 0
        return {"kind": "hp", "hp": hp, "maximum": maximum, "percent": percent,
                "class": "hp-high" if percent > 50 else "hp-mid" if percent > 20 else "hp-low",
                "status_html": Markup(status_icon_html(detail.get("status_cond", 0))),
                "stages_html": Markup(stat_stages_html(detail.get("stat_stages"), adapter.stat_stage_labels())
                                      if detail.get("active") else "")}

    def ability(detail, *, resolve=False):
        number = detail.get("ability_id", 0)
        name = adapter.ability_name(number, detail.get("species_id", 0)) if resolve and number else detail.get("ability_name", "")
        return {"name": name, "description": adapter.ability_description(number) if number else ""}

    def mon_cell(detail, link, side, key, *, prefix="", boxed=False, partner=None, split=False):
        link = link or {}
        nickname = detail.get("nickname") or link.get(side + "_nickname") or "???"
        species = detail.get("species_id") or link.get(side + "_species_id") or 0
        gender = detail.get("gender") or adapter.gender_from_key(key, species)
        entry = state._key_index.get(key)
        mon = (entry.a if side == "a" else entry.b) if entry else None
        shiny = key in state.bonus_keys.get(side, set()) or bool(mon and mon.is_shiny)
        return {"side": side, "mirror": side == "b" and not split, "missing": False,
                "label": label(key, nickname, species, gender, shiny), "active": detail.get("active", False),
                "sprite_html": Markup(detail.get("sprite_html") or link.get(side + "_sprite_html") or server._get_sprite_html(species)),
                "level": detail.get("level") or link.get(side + "_level") or 0,
                "types_html": types(species) if not split else "", "partner": partner,
                "item": adapter.item_name(detail.get("held_item_id", 0)),
                "ability": ability(detail) if has_abilities and not split else None,
                "moves_html": Markup(move_table_html(detail.get("move_details", []), mon_key=prefix + key, is_box=boxed))}

    def box_level(box):
        if box.get("level"):
            return box["level"]
        key = box.get("key", "")
        if not key:
            return 0
        cached = state.mon_stats.get(key)
        if cached and cached.get("level"):
            return cached["level"]
        entry = state._key_index.get(key)
        if entry:
            mon = entry.a if entry.a and entry.a.key == key else entry.b
            if mon and mon.level:
                return mon.level
        for pid in ("a", "b"):
            detail = server.party_details.get(pid, {}).get(key)
            if detail and detail.get("level"):
                return detail["level"]
        return (server._mon_cache.get(key) or {}).get("level") or 0

    def partner(pid, key, *, boxed=False):
        entry = state._key_index.get(key)
        other = "b" if pid == "a" else "a"
        if entry:
            mon = entry.b if pid == "a" else entry.a
            result = {"class": entry.status.value, "kind": "absent", "text": "—", "hp": None}
            if mon:
                nickname = mon.nickname
                detail = server.party_details.get(other, {}).get(mon.key)
                if detail and detail.get("nickname"):
                    nickname = detail["nickname"]
                else:
                    nickname = next((box["nickname"] for box in server.pc_boxes.get(other, [])
                                     if box.get("key") == mon.key and box.get("nickname")), nickname)
                result.update(kind="mon", label=label(mon.key, nickname, mon.species,
                              adapter.gender_from_key(mon.key, mon.species), mon.is_shiny))
                if detail and not boxed and int(detail.get("maxHP", 0) or 0):
                    result["hp"] = hp_cell(detail)
                    result["token"] = adapter.status_token(int(detail.get("status_cond", 0) or 0))
            return result
        area = pending[pid].get(key)
        if area:
            return {"class": "pending_b", "kind": "pending", "name": players[other].get("trainer_name") or other.upper(),
                    "area": adapter.area_display_name(area)}
        if key in data.get("bonus_keys", {}).get(pid, []):
            return {"class": "alive", "kind": "shiny"}
        return {"class": "dim", "kind": "absent", "text": "—" if boxed else "unlinked"}

    def battle(pid):
        player = players[pid]
        observation = player.get("battle_state", {})
        if not observation.get("in_battle"):
            return None
        trainer = observation.get("is_trainer_battle", False)
        title = "Trainer Battle" if trainer else "Wild Battle"
        opponent = observation.get("opponent_name", "") if trainer else ""
        category = observation.get("opponent_class", "") if trainer else ""
        if opponent or category:
            title = "vs " + (category + " " + opponent if category and opponent else opponent or category)
        area = player.get("current_area_id", "")
        new_encounter = (not trainer and player.get("nuzlocke_active", False) and bool(area)
                         and data["area_states"].get(area, "unseen") not in ("linked", "dead_zone")
                         and pid not in data["pending_captures"].get(area, {}))
        foes = []
        for index, enemy in enumerate(observation.get("enemy_party", [])):
            species = enemy.get("species_id", 0)
            foes.append({"key": enemy.get("key", f"foe-{index}"), "name": adapter.species_name(species) if species else "?",
                         "level": enemy.get("level", 0), "hp": hp_cell(enemy, enemy=True),
                         "class": "fainted" if enemy.get("hp", 0) == 0 else "active-foe" if enemy.get("active") else "",
                         "active": enemy.get("active", False), "ability": ability(enemy, resolve=True),
                         "item": adapter.item_name(enemy.get("held_item_id", 0)) if enemy.get("held_item_id") else "",
                         "sprite_html": Markup(server._get_sprite_html(species)), "types_html": types(species),
                         "moves": {prefix: Markup(move_table_html(enemy.get("move_details", []), mon_key=f"{prefix}enemy:{pid}:{index}"))
                                   for prefix in ("", "lp:")}})
        calc = None
        if state.is_rr:
            party = [(key, player.get("party_details", {}).get(key, {})) for key in player.get("party_keys", [])]
            chosen = next(((key, detail) for key, detail in party if detail.get("active") and detail.get("hp", 0) > 0),
                          next(((key, detail) for key, detail in party if detail.get("hp", 0) > 0), None))
            enemies = observation.get("enemy_party", [])
            defender = next((mon for mon in enemies if mon.get("active")), next((mon for mon in enemies if mon.get("hp", 0) > 0), None))
            if chosen and defender:
                key, attacker = chosen
                attacker_species, defender_species = attacker.get("species_id", 0), defender.get("species_id", 0)
                trainer_key = f"{category} {opponent}" if trainer and category and opponent else ""
                calc = {"in-battle": "1", "trainer-key": trainer_key, "is-trainer": "1" if trainer_key else "0",
                        "player-species": adapter.species_name(attacker_species) if attacker_species else "",
                        "player-level": attacker.get("level", 0), "player-nature": _nature_from_key(key),
                        "player-ability": attacker.get("ability_name", ""), "player-item": adapter.item_name(attacker.get("held_item_id", 0)),
                        "player-moves": json.dumps([move["name"] for move in attacker.get("move_details", []) if move.get("name")][:4]),
                        "enemy-species": adapter.species_name(defender_species) if defender_species else "",
                        "enemy-level": defender.get("level", 0),
                        "enemy-hp-pct": max(0, min(100, int(defender.get("hp", 0) / max(defender.get("maxHP", 1), 1) * 100)))}
        return {"title": title, "new_encounter": new_encounter, "doubles": observation.get("is_doubles"), "foes": foes, "calc": calc}

    cards = {}
    safe_run = re.sub(r"[^\w-]", "_", server._run_name or server._run_id or "SLink").strip("_") or "SLink"
    for pid, player in players.items():
        area = adapter.area_display_name(player.get("current_area_id") or player["current_area"])
        high = max((detail.get("level", 0) or 0 for key in player["party_keys"]
                    if isinstance((detail := player["party_details"].get(key, {})).get("level", 0) or 0, int)), default=0)
        card = {**player, "pid": pid, "name": player.get("trainer_name") or "Player " + pid.upper(),
                "rom_label": str(ROM_LABELS.get(player["rom_type"], player["rom_type"])), "area": area,
                "bonus_count": len(state.pending_bonus.get(pid, [])), "ball_class": "yes" if player["ball_count"] > 0 else "warn",
                "age_label": _age_label(player.get("last_seen_age")),
                "stale": player.get("last_seen_age") is not None and player["last_seen_age"] >= STALE_AFTER_SECS,
                "launcher_name": f"slink_{safe_run}_{pid}.lua", "battle": battle(pid),
                "badges_display": [{"color": color, "name": name, "earned": bool(player.get("badges", 0) & (1 << index))}
                                   for index, (color, name) in enumerate(GYM_BADGES)],
                "widgets": {prefix: {"encounters": Markup(server._encounter_html(player.get("current_area_id") or "", pid, key_prefix=prefix)),
                                      "trainers": Markup(server._trainer_panel_html(player.get("current_area_id") or "", pid, key_prefix=prefix, highest_party_level=high))}
                            for prefix in ("", "lp:")}, "party_rows": [], "box_rows": []}
        for key in player["party_keys"]:
            detail = player["party_details"].get(key, {})
            card["party_rows"].append({"key": key, "class": "fainted" if detail.get("hp", 1) == 0 else "active-mon" if detail.get("active") else "",
                                       "mon": mon_cell(detail, None, pid, key, partner=partner(pid, key), split=True),
                                       "hp": hp_cell(detail), "types_html": types(detail.get("species_id", 0)), "ability": ability(detail)})
        for box in player.get("pc_boxes", []):
            if box.get("key", "") in memorial_keys or (adapter.memorial_box_index >= 0 and box.get("box") in memorial_indices):
                continue
            key = box.get("key", "")
            card["box_rows"].append({"key": key, "box": box.get("box", 0) + 1, "slot": box.get("slot", 0) + 1,
                                     "mon": mon_cell({**box, "level": box_level(box)}, None, pid, key, boxed=True,
                                                     partner=partner(pid, key, boxed=True), split=True),
                                     "types_html": types(box.get("species_id", 0)), "ability": ability(box, resolve=True)})
        cards[pid] = card

    party_keys = {pid: set(player["party_keys"]) for pid, player in players.items()}
    box_maps = {pid: {box.get("key"): box for box in player["pc_boxes"]
                      if box.get("key") and box.get("key") not in memorial_keys and box.get("box") not in memorial_indices}
                for pid, player in players.items()}
    pairs, box_pairs = [], []
    for link in data["links"]:
        if link["status"] == "memorial":
            continue
        both_party = all(link.get(pid + "_key", "") in party_keys[pid] for pid in ("a", "b"))
        if not both_party and not any(link.get(pid + "_key", "") in party_keys[pid] or link.get(pid + "_key") in box_maps[pid] for pid in ("a", "b")):
            continue
        row = {"area": link.get("area_display") or link.get("area_id") or "", "class": "lp-row" if both_party else "lp-row lp-box-row"}
        fainted = []
        for pid in ("a", "b"):
            key = link.get(pid + "_key", "")
            if key in party_keys[pid]:
                detail = players[pid]["party_details"].get(key) or {}
                row[pid] = {"mon": mon_cell(detail, link, pid, key, prefix="lp:" if both_party else "lpbx:"), "location": hp_cell(detail)}
                fainted.append(int(detail.get("hp", 1) or 0) == 0)
            elif box := box_maps[pid].get(key):
                row[pid] = {"mon": mon_cell({**box, "level": box_level(box)}, link, pid, key, prefix="lpbx:", boxed=True),
                            "location": {"kind": "box", "box": box.get("box", 0) + 1, "slot": box.get("slot", 0) + 1}}
            else:
                row[pid] = {"mon": {"missing": True, "mirror": pid == "b"}, "location": {"kind": "absent"}}
        if both_party and all(fainted):
            row["class"] += " lp-fnt"
        (pairs if both_party else box_pairs).append(row)

    def cause(kill):
        if not kill:
            return None
        kind, killer = kill.get("cause", ""), kill.get("killer") or {}
        text, icon = "", ""
        if kind == "battle":
            species = killer.get("species", 0)
            if species:
                if killer.get("is_trainer") and killer.get("trainer_name"):
                    owner = ((killer.get("trainer_class", "") + " ") if killer.get("trainer_class") else "") + killer["trainer_name"]
                    prefix = owner + "'s"
                else:
                    prefix = "Trainer's" if killer.get("is_trainer") else "Wild"
                text = prefix + " " + adapter.species_name(species)
            else:
                text = "Fainted in battle"
            icon = "swords"
        elif kind in ("dead_zone", "whiteout"):
            initiator = kill.get("initiating_player", "")
            name = players[initiator].get("trainer_name") or initiator.upper() if initiator else "?"
            text = name + (" missed" if kind == "dead_zone" else " whited out")
            icon = "ban" if kind == "dead_zone" else "skull"
        return {"class": "kf-" + kind, "text": text, "icon": icon}

    def catch_cell(key, nickname, species, shiny=False):
        return {"kind": "mon", "sprite_html": Markup(server._get_sprite_html(species)),
                "label": label(key, nickname, species, adapter.gender_from_key(key, species), shiny)}

    kills = {kill["area_id"]: kill for kill in data["killfeed"]}
    encounters = []
    for link in data["links"]:
        status, area = link["status"], link["area_id"]
        dead_zone = status in ("dead", "dead_zone") and data["area_states"].get(area, "") == "dead_zone"
        row = {"area": area, "class": "dead_zone" if dead_zone else status, "sort": 0 if status == "alive" else 1,
               "status": {"kind": "linked" if status == "alive" else "dead_zone" if dead_zone else status,
                          "memorial": status == "memorial", "cause": cause(kills.get(area)), "pending": None}}
        for pid in ("a", "b"):
            key, species = link.get(pid + "_key"), link.get(pid + "_species", 0)
            row[pid] = catch_cell(key, link.get(pid + "_nickname", ""), species, link.get(pid + "_shiny", False)) if key else (
                {"kind": "failed", "name": adapter.species_name(link[pid + "_enc_species"])} if link.get(pid + "_enc_species")
                else {"kind": "empty", "text": "— no catch"})
        encounters.append(row)
    covered = {row["area"] for row in encounters}
    for area, captures in sorted(data["pending_captures"].items()):
        if area in covered:
            continue
        status = data["area_states"].get(area, "unseen")
        progress = {}
        row = {"area": area, "class": status, "sort": -1}
        for pid, entered in (("a", ("pending_b", "pending_both")), ("b", ("pending_a", "pending_both"))):
            mon = captures.get(pid)
            row[pid] = catch_cell(mon["key"], mon.get("nickname", ""), mon.get("species", 0)) if mon else {"kind": "empty", "text": "waiting…"}
            progress[pid] = "caught" if mon else "entered" if status in entered else "none"
        row["status"] = {"pending": progress}
        encounters.append(row)
        covered.add(area)
    for area, status in sorted(data["area_states"].items()):
        if area in covered or status == "unseen":
            continue
        progress = {"pending_b": {"a": "entered", "b": "none"}, "pending_a": {"a": "none", "b": "entered"},
                    "pending_both": {"a": "entered", "b": "entered"}}.get(status)
        encounters.append({"area": area, "class": status, "sort": -1 if "pending" in status else 2,
                           "a": {"kind": "empty", "text": "—"}, "b": {"kind": "empty", "text": "—"},
                           "status": {"kind": status, "pending": progress, "orphan": True,
                                      "cause": cause(kills.get(area)) if status == "dead_zone" else None}})
    encounters.sort(key=lambda row: (row["sort"], row["area"]))
    for row in encounters:
        row.update(area_display=server._area_display(row["area"]), sort_value=STATUS_SORT.get(row["class"], "9"), bonus=row["area"].startswith("_bonus_"))
    counts = {"alive": sum(row["class"] == "alive" for row in encounters),
              "dead": sum(row["class"] in ("dead", "dead_zone", "memorial") for row in encounters),
              "pending": sum("pending" in row["class"] for row in encounters),
              "pending_a": sum(row["class"] in ("pending_a", "pending_both") for row in encounters),
              "pending_b": sum(row["class"] in ("pending_b", "pending_both") for row in encounters)}
    events = []
    for event in data["recent_events"]:
        raw = event.get("ts", "")
        try:
            stamp = datetime.fromisoformat(raw).strftime("%I:%M:%S %p").lstrip("0")
        except (ValueError, AttributeError):
            stamp = raw[-8:]
        pid = event.get("player", "")
        events.append({"time": stamp, "player": server.trainer_name.get(pid, "") or pid.upper(),
                       "type": event.get("type", "hello"), "text": event.get("text", "")})
    phase = ("game_over", "Game over") if state.run_over else ("pre", "Waiting for Pokéballs") if not all(state.pokeballs_obtained.get(pid) for pid in ("a", "b")) else ("running", "Run in progress")
    return copy.deepcopy({"players": cards, "has_abilities": has_abilities, "save_failed": data["save_failed"],
                          "run_over": data["run_over"], "rules": [{"icon": icon, "name": name} for key, icon, name in RULE_BADGES if getattr(state, key)],
                          "pairs": pairs, "box_pairs": box_pairs, "encounters": encounters, "counts": counts,
                          "encounter_names": {pid: players[pid].get("trainer_name") or pid.upper() for pid in ("a", "b")}, "events": events,
                          "page_title": " — ".join(filter(None, ["Pokémon Soul Link Tracker", variant_label(state.rom_type) if state.rom_type else "", server._run_name])),
                          "concise_title": " — ".join(filter(None, [variant_label(state.rom_type) if state.rom_type else "", server._run_name])) or "Soul Link",
                          "phase_slug": phase[0], "phase_label": phase[1], "attempts_count": state.attempts_count or 0,
                          "alive_links": sum(link["status"] == "alive" for link in data["links"]),
                          "dead_links": sum(link["status"] in ("dead", "memorial") for link in data["links"]),
                          "sidebar_html": Markup(server._build_sidebar_html("status")), "sidebar_assets": False,
                          "theme": "default", "body_class": "slink-dashboard", "is_stream": False, "hide_chrome": False})
