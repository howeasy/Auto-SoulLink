"""What a player's cartridge can do, as flat facts a template can switch on.

Today's UI explains generation differences in tooltip prose -- "Gen 3 only", "has no
effect on Gen 1" -- and prose cannot hide a column: the Ability column still renders,
empty, beside a cartridge that predates abilities. Every value here is READ FROM THE
ADAPTER, never asserted, so a page asks `caps.abilities` rather than "is this RR".

Keyed per CARTRIDGE, not per generation: Explode Mode and the native info panel come from
the companion patch, so `firered` and `firered_rr` answer differently through the same
adapter class. That is why this takes the constructed adapter and its rom_type, and why the
server calls it through `adapter_for(pid)`.

Held items are deliberately NOT a capability. No adapter answers that question -- asking
whether it knows any item names measures the bag, which Gen 1 has, and not the held-item
slot, which Gen 1 lacks. A consumer decides that column from the data it was given.

`tools/gen_ui_capabilities.py` writes this same function's answers out for every
rom_type the server routes, so the mockup fixtures cannot drift from the payload.
"""
from __future__ import annotations


def ui_capabilities(adapter, rom_type: str) -> dict:
    return {
        "game_id": adapter.game_id,
        "abilities": adapter.supports_abilities(),
        "explode_mode": adapter.supports_explode_mode(),
        "info_panel": adapter.supports_info_panel(),
        "info_panel_width": adapter.info_panel_width(),
        "stat_stage_labels": adapter.stat_stage_labels(),
        "mons_per_box": adapter.mons_per_box,
        "memorial_box_index": adapter.memorial_box_index,
        "party_blob_size": adapter.party_blob_size(),
        "badges": [slug for _, slug in adapter.gym_badge_slugs(rom_type)],
    }
