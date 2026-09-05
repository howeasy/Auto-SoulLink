"""Emit what each generation's adapter can actually do, for the UI to switch on.

Today's UI explains generation differences in tooltip prose -- "Gen 3 only", "has no
effect on Gen 1". That does not scale past two generations, and prose cannot hide a
column: the Ability column still renders, empty, beside a cartridge that predates
abilities. The adapters already answer every one of these questions; this writes their
answers out so a page can hide the panel instead of captioning it.

Every value here is READ FROM AN ADAPTER, never asserted. A predicate that a given
checkout does not have yet (the Gen 1 work adds several) is reported as null rather
than guessed, so a stale fixture reads as "unknown" instead of as a confident lie.

Held items are deliberately NOT reported. No adapter answers that question -- asking
whether it knows any item names measures the bag, which Gen 1 has, and not the held-item
slot, which Gen 1 lacks. A consumer should decide that column from the data it was given:
if no mon in the payload carries a held_item_id, there is nothing for the column to show.

    python tools/gen_ui_capabilities.py > server/static/mockups/fixtures/capabilities.json
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.adapters import game_id_for_rom_type, get_adapter  # noqa: E402

# The rom_types to report on, keyed by the label the UI shows. Capabilities are a
# property of the CARTRIDGE, not of the generation: Gen 3's Explode Mode and native info
# panel both come from the Radical Red companion patch, so vanilla FireRed and RR answer
# differently through the same adapter class. Probing `get_adapter(game_id)` with no
# rom_type asks a default-constructed instance, which answers "no" to both and would have
# shipped a fixture claiming RR cannot explode.
ROM_TYPES = [
    "red",
    "crystal",
    "firered",
    "firered_rr",
    "heartgold",
    "pokemon_black",
]

# Adapter members the UI switches on. Each is (json key, member name, kind) where kind
# says how to read it: a plain attribute, a no-argument call, or a call taking rom_type.
PROBES = [
    ("abilities", "supports_abilities", "call"),
    ("explode_mode", "supports_explode_mode", "call"),
    ("info_panel", "supports_info_panel", "call"),
    ("info_panel_width", "info_panel_width", "call"),
    ("stat_stage_labels", "stat_stage_labels", "call"),
    ("mons_per_box", "mons_per_box", "attr"),
    ("memorial_box_index", "memorial_box_index", "attr"),
    ("party_blob_size", "party_blob_size", "call"),
]


def probe(adapter, name: str, kind: str):
    """Read one capability, or None when this checkout's adapter cannot answer.

    None is load-bearing: it means "this predicate does not exist here yet", which a
    consumer must render as unknown. Collapsing it to False would claim the feature is
    unsupported, and that is a different -- and wrong -- statement.
    """
    member = getattr(adapter, name, None)
    if member is None:
        return None
    try:
        return member() if kind == "call" else member
    except Exception:
        return None


def main() -> int:
    out = {}
    for rom_type in ROM_TYPES:
        game_id = game_id_for_rom_type(rom_type)
        adapter = get_adapter(game_id, is_rr=rom_type.endswith("_rr"), rom_type=rom_type)
        caps = {key: probe(adapter, name, kind) for key, name, kind in PROBES}
        caps["game_id"] = game_id
        caps["badges"] = [slug for _, slug in adapter.gym_badge_slugs(rom_type)]
        out[rom_type] = caps
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
