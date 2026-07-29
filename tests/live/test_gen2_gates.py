"""The Gen 2 headless gates, as pytest.

    SLINK_LIVE=1 pytest tests/live/test_gen2_gates.py -q

Gen 2 had unit tests, a Lua client and broader static data than Gen 1 — Gold/Silver profiles,
gender ratios, item names, 179 adapter tests — and had never executed against a running
cartridge. Everything the static suite could not see was wrong: Gold, Silver and AP Crystal
routed to the Gen 3 adapter, `party_blob_size()` inherited 0 so every Gen 2 party blob was
discarded, no profile declared `stats_offset` so every box deposit dropped the stat block,
and the Apricorn ball IDs pointed at SUN_STONE and friends, which left the Nuzlocke gate shut
for anyone carrying balls Kurt made. `pytest` was green throughout.

ONE CARTRIDGE. Crystal. Gold and Silver are supported for correctness — routing, profile
keys, per-variant addresses, all checked against pret by tools/verify_profile_addresses.py —
but there are no dumps to run them against, and a live matrix entry that silently skips reads
exactly like one that passes. Archipelago Crystal is in the same position for a different
reason: the fork has no public repo, so only five of its addresses are provable and its
profile is still flagged unverified.

Skipped, never hung, when a prerequisite is missing: no EmuHawk, no dump (gitignored), or no
fixture.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen2_playthrough as play  # noqa: E402
from run_gb_gate import run_gate  # noqa: E402

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1",
                       reason="live Gen 2 gates only run with SLINK_LIVE=1 (spawns EmuHawk)"),
]

# gate script -> which fixture it needs. There is only a `town` fixture; see
# lua/tests/gen2_playthrough.lua for why Gen 2 has no grass one.
GATES = {
    "lua/tests/test_gen2_memory_gate.lua": "town",
    # Everything that MUTATES a cartridge: force_faint, deposit, withdraw, memorial burial.
    "lua/tests/test_gen2_writes_gate.lua": "town",
}
ROMS = ("crystal",)


@pytest.fixture(scope="session")
def emuhawk():
    from gen1_playthrough import EMUHAWK
    if not os.path.exists(EMUHAWK):
        pytest.skip(f"EmuHawk not found at {EMUHAWK}")
    return EMUHAWK


@pytest.mark.parametrize("gate", sorted(GATES))
@pytest.mark.parametrize("rom", ROMS)
def test_gen2_gate(gate, rom, emuhawk):
    if not os.path.exists(os.path.join(REPO, play.ROMS[rom])):
        pytest.skip(f"{play.ROMS[rom]} not present (ROMs are gitignored)")
    target = GATES[gate]
    fixture = play.fixture_path(rom, target)
    if not os.path.exists(fixture):
        pytest.skip("missing fixture — build with `python tools/gen2_playthrough.py`")

    passed, result_path, text = run_gate(gate, rom_key=rom, target=target,
                                         timeout=300, quiet=True)
    assert passed, (f"{os.path.basename(gate)} on {rom}/{target} did not PASS\n"
                    f"result: {result_path}\n{text[-3000:]}")
