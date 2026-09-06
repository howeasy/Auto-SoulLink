"""Detached manager presentation, including strictly persisted stopped runs."""

from markupsafe import Markup

from server.adapters import get_adapter, game_id_for_rom_type
from server.board import FAMILIES, OPTION_LABELS, project_board
from server.run_proxy import prefix_html, run_base
from server.status_payload import empty_status_payload

SAFE_HTML = frozenset(("sprite_html", "moves_html", "status_html", "stages_html", "widgets", "trainers"))


def trusted_context(value, base):
    """Restore only adapter/widget fields from our registered loopback server.

    Never call this on client input, run registry strings, or a saved document.
    JSON duplicates row references, so traverse zones and rows independently.
    """
    if isinstance(value, list):
        return [trusted_context(item, base) for item in value]
    if isinstance(value, dict):
        return {key: Markup(prefix_html(item, base)) if key in SAFE_HTML and isinstance(item, str)
                else trusted_context(item, base) for key, item in value.items()}
    return value


def shell_context(run=None):
    return {"page_title": "Soul Link", "body_class": "slink-board", "default_font": "jersey",
            "sidebar_assets": False, "is_stream": False, "hide_chrome": False,
            "manager": True, "run_base": run_base(run["run_id"]) if run else "", "selected_run": run,
            "running": bool(run and run.get("status") == "running"), "debug_operations": {}}


def stopped_context(run, saved):
    data = empty_status_payload()
    document = saved.get("document") or {}
    game_id = document.get("game_id") or game_id_for_rom_type(document.get("rom_type", ""))
    try:
        adapter = get_adapter(game_id)
    except KeyError:
        adapter = None
    # A run-wide historical ROM value is insufficient evidence for each player's
    # cartridge. Only explicit bindings may supply those labels while stopped.
    for pid, player in data["players"].items():
        player.update(rom_type=run.get("cartridges", {}).get(pid, {}).get("variant"),
                      trainer_name=document.get("trainer_names", {}).get(pid, ""), admission=None)
    data.update(rules=document.get("rules") or {key: run.get(key) for key in OPTION_LABELS},
                area_states=document.get("area_states", {}), run_over=document.get("run_over", False),
                attempts_count=document.get("attempts_count", 0))

    def display(mon):
        if not mon:
            return None
        species = mon.get("species", 0)
        return {"key": mon["key"], "nickname": mon.get("nickname", ""), "species_id": species,
                "species_name": adapter.species_name(species) if adapter else "Unknown Pokémon",
                "sprite_html": Markup(adapter.sprite_html(species)) if adapter else "",
                "level": mon.get("level"), "shiny": mon.get("is_shiny", False)}

    for entry in document.get("links", []):
        link = {"area_id": entry["area_id"], "status": entry.get("status")}
        for pid in ("a", "b"):
            mon = display(entry.get(pid))
            if mon:
                link.update({pid + "_" + name: value for name, value in mon.items()})
                link[pid + "_species"] = mon["species_id"]
        data["links"].append(link)
        if entry.get("killed_at"):
            data["killfeed"].append({key: entry.get(key) for key in ("area_id", "cause", "killer")})
    data["pending_captures"] = {area: {pid: display(mon) for pid, mon in captures.items()}
                                 for area, captures in document.get("pending_captures", {}).items()}
    context = project_board(data, run_id=run["run_id"], running=False)
    context.update(shell_context(run), running=False, run_name=run.get("name") or run["run_id"],
                   page_title="Soul Link — " + (run.get("name") or run["run_id"]),
                   game_family=FAMILIES.get(game_id or run.get("game_family"), "Game family not recorded"),
                   saved_unavailable=saved.get("reason_code") if not saved.get("available") else None,
                   options=[{"key": key, "name": label, "requested": data["rules"].get(key)} for key, label in OPTION_LABELS.items()])
    return context
