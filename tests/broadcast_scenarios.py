"""Representative presentation data; never a generation readiness claim."""

import json
from pathlib import Path

from tests.ui_support import hydrate_capture

VARIANTS = {"gen2": ("Gold", "Crystal"), "gen4": ("heartgold", "platinum"),
            "gen5": ("pokemon_black", "pokemon_black_2")}


def capability_scenario(game, directory):
    capture = json.loads((Path(__file__).parent / "fixtures/ui/source/gen3.json").read_text(encoding="utf-8"))
    for pid, variant in zip(("a", "b"), VARIANTS[game], strict=True):
        capture["players"][pid].update(rom_type=variant, connected=False, trainer_name="Example " + pid.upper())
    capture["recent_events"] = []
    server = hydrate_capture(capture, directory)
    server._run_name = game.upper() + " capability sample — no live admission"
    return server
