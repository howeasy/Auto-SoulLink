"""Broadcast preset controls and legacy aliases, excluding the gallery entry."""

import copy
import re

from server.overlay_catalog import OVERLAYS, EVENT_FILTERS_DEFAULT_OFF, EVENT_FILTERS_DEFAULT_ON

PLAYER_PRESETS = frozenset(("party", "focus", "enemy-focus", "enemy-trainer", "badges", "enc-table"))
ALIASES = {}
PRESETS = {}
NAMES = {"party": "Party", "focus": "Active Pokémon", "enemy-focus": "Active opponents",
         "enemy-trainer": "Opponent team", "badges": "Gym badges", "enc-table": "Wild encounter table"}
EVENT_FILTERS = tuple(EVENT_FILTERS_DEFAULT_ON + EVENT_FILTERS_DEFAULT_OFF)

for overlay in OVERLAYS:
    slug = overlay["slug"]
    if slug == "all":
        continue
    base, dash, player = slug.rpartition("-")
    if base not in PLAYER_PRESETS or player not in ("a", "b"):
        base, player = slug, None
    ALIASES[slug] = {"preset": base, "players": [player] if player else ["a", "b"]}
    if base in PRESETS:
        continue
    sizes = []
    for description in overlay.get("sizes", []):
        match = re.search(r"(\d+)×(\d+)", description)
        if match:
            sizes.append({"label": description, "width": int(match[1]), "height": int(match[2])})
    PRESETS[base] = {"id": base, "name": NAMES.get(base, overlay["title"]), "family": overlay["family"],
        "description": overlay["desc"], "sizes": sizes, "layouts": list(overlay.get("layouts", [""])),
        "player_choices": [["a"], ["b"], ["a", "b"]] if player else [["a", "b"]],
        "controls": {key: list(overlay[key]) for key in ("speeds", "pauses") if key in overlay},
        "event_filters": list(EVENT_FILTERS) if base in ("events", "ticker") else []}


# Long pair histories retain readable text at legacy canvas sizes.
for _preset in ("links", "linked-party"):
    PRESETS[_preset]["controls"].update(speeds=["0.5", "1", "2"], pauses=["0", "1", "2", "4"])

def catalog():
    return [{**copy.deepcopy(preset), "defaults": default_controls(preset["id"])} for preset in PRESETS.values()]


def default_controls(preset):
    record = PRESETS[preset]
    controls = {}
    if "speeds" in record["controls"]:
        controls["speed"] = 1.0
    if "pauses" in record["controls"]:
        controls["pause"] = 2.0
    if record["event_filters"]:
        controls["filter"] = list(EVENT_FILTERS_DEFAULT_ON)
    return controls
