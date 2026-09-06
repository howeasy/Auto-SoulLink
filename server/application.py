"""Shared presentation context for the three application destinations."""

from server import runtime_boundary
from server.overlay_catalog import build_index_context
from server.patcher import DEFAULT_TARGET, TARGETS
from server.templating import resolve_theme


def compatibility_location(request, target):
    path, separator, fragment = target.partition("#")
    query = request.raw_path.partition("?")[2]
    if query:
        path += ("&" if "?" in path else "?") + query
    return path + (separator + fragment if separator else "")


def destination_context(request, destination, *, manager=False, run=None):
    tab = request.query.get("tab", "overlays")
    if tab not in ("overlays", "obs", "twitch"):
        tab = "overlays"
    if destination != "broadcast":
        tab = None
    run_id = run["run_id"] if run else None
    base = "/runs/" + run_id if manager and run_id else ""
    result = {"page_title": "Soul Link — " + destination.capitalize(), "theme": resolve_theme(request),
              "destination": destination, "tab": tab, "manager": manager, "selected_run": run,
              "run_base": base, "run_id": run_id, "run_name": run.get("name", "") if run else "",
              "running": bool(run and run.get("status") == "running"), "body_class": "slink-board",
              "default_font": "jersey", "sidebar_assets": False, "hide_chrome": False, "is_stream": False,
              "status": None, "debug_operations": {},
              "application_state": {"manager": manager, "run_id": run_id, "destination": destination, "tab": tab}}
    if destination == "broadcast":
        gallery = build_index_context(request)
        for key in ("families", "overlays", "overlays_json", "layout_labels_json", "default_filters_on_json", "all_filters_json"):
            result[key] = gallery[key]
    else:
        target = TARGETS.get(request.query.get("game"), TARGETS[DEFAULT_TARGET])
        result.update(target=target, targets=list(TARGETS.values()), base_rom_md5=target["base_md5"],
                      patched_rom_md5=target["patched_md5"], randomizer_availability=runtime_boundary.randomization_decision())
    return result
