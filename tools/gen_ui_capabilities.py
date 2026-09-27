"""Emit what each generation's adapter can actually do, for the UI to switch on.

Today's UI explains generation differences in tooltip prose -- "Gen 3 only", "has no
effect on Gen 1". That does not scale past two generations, and prose cannot hide a
column: the Ability column still renders, empty, beside a cartridge that predates
abilities. The adapters already answer every one of these questions; this writes their
answers out so a page can hide the panel instead of captioning it.

Every value here is READ FROM AN ADAPTER, never asserted -- through the same
`server.ui_capabilities.ui_capabilities` the status payload uses, so this fixture and
`players.{pid}.capabilities` cannot disagree.

Held items are deliberately NOT reported. No adapter answers that question -- asking
whether it knows any item names measures the bag, which Gen 1 has, and not the held-item
slot, which Gen 1 lacks. A consumer should decide that column from the data it was given:
if no mon in the payload carries a held_item_id, there is nothing for the column to show.

    python tools/gen_ui_capabilities.py > tests/fixtures/ui/capabilities.json
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.adapters import _ROM_TYPE_TO_GAME_ID, get_adapter  # noqa: E402
from server.ui_capabilities import ui_capabilities  # noqa: E402

# EVERY rom_type the server will accept, taken from the routing table itself rather than
# from a list kept here by hand. A curated list is one Soul Link run away from being
# wrong: the two players are on different VERSIONS of the same game, so a fixture holding
# "firered_rr" and not "leafgreen_rr" gives player B no capabilities at all -- which shows
# up as player B mysteriously losing their Ability column, and reads as a layout bug
# rather than as missing data.
#
# Capability is a property of the CARTRIDGE: the native info panel is still RR-only,
# while Explode Mode also binds vanilla FR/LG/E. Those cartridges therefore still
# answer differently through the same adapter class. Probing
# `get_adapter(game_id)` with no rom_type asks a default-constructed instance, which
# answers "no" to both and would ship a fixture claiming RR cannot explode.
ROM_TYPES = sorted(_ROM_TYPE_TO_GAME_ID)

def main() -> int:
    out = {}
    for rom_type in ROM_TYPES:
        game_id = _ROM_TYPE_TO_GAME_ID[rom_type]
        adapter = get_adapter(game_id, is_rr=rom_type.endswith("_rr"), rom_type=rom_type)
        out[rom_type] = ui_capabilities(adapter, rom_type)
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
