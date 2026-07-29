"""Gen 1 test scripts must not hardcode addresses that Yellow shifts.

WHY. Yellow moves nearly all of WRAM down by one byte. Anything that writes a Red/Blue
address as a literal therefore reads the WRONG byte on Yellow — silently, because the
neighbouring byte is usually a plausible-looking value.

This is not hypothetical. `scenario_gen1_playthrough.lua` hardcoded Red's addresses and, run
against Yellow, reported the Poké Ball count as 255 (it was reading into the next item slot)
and the current map as 0x0E instead of 0x0C (reading wCurMap+1). The second one sent me
chasing a nonexistent "the Yellow fixture is on Route 3" problem for a while, complete with a
check of pret's map constants, before the real cause turned out to be the instrument.

The rule this enforces: read addresses from the loaded profile (`M.SOMETHING_ADDR`), never as
a literal. The set of banned literals is derived from the profiles themselves, so it stays
correct as addresses change, and addresses that genuinely do NOT shift (wCurrentMenuItem
0xCC26, wMaxMenuItem 0xCC28, wJoyIgnore 0xCD6B) are allowed automatically because red and
yellow agree on them.
"""
import glob
import os
import re

import pytest

lupa = pytest.importorskip("lupa")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The one script whose literals ARE the point. test_gen1_ap_gate.lua exists to check the
# loaded profile against addresses derived independently of it, so reading them from
# `M.SOMETHING_ADDR` would make it compare the profile with itself and pass unconditionally.
# It is also the only Gen 1 gate that cannot run on Yellow: Yellow has no upstream
# Archipelago world, and gen1_rby.detect_variant() returns "yellow" without ever consulting
# the seed slot, so the Red/Blue literals below can never be applied to a Yellow cartridge.
ORACLE_SCRIPTS = {"test_gen1_ap_gate.lua"}

# Scripts that drive a real cartridge and are (or could be) run against more than one variant.
SCRIPTS = sorted(
    p for p in (
        glob.glob(os.path.join(REPO, "lua", "tests", "duo", "scenario_gen1_*.lua"))
        # gen1_hunt.lua is not a scenario, but the scenarios delegate every cartridge read to
        # it — leaving it out would let the literals simply move one file over.
        + glob.glob(os.path.join(REPO, "lua", "tests", "duo", "gen1_*.lua"))
        + glob.glob(os.path.join(REPO, "lua", "tests", "test_gen1_*_gate.lua"))
    ) if os.path.basename(p) not in ORACLE_SCRIPTS
)

HEX = re.compile(r"0x[0-9A-Fa-f]{4}")


def _strip_lua_comments(src: str) -> str:
    """Drop --[[ ]] blocks and -- line comments.

    An address quoted in a comment to explain a pret symbol is documentation, not a read.
    """
    src = re.sub(r"--\[\[.*?\]\]", "", src, flags=re.S)
    return re.sub(r"--[^\n]*", "", src)


@pytest.fixture(scope="module")
def shifted_addresses():
    """Every address that differs between the red and yellow profiles, as a set of ints."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("print = function() end")
    path = os.path.join(REPO, "lua", "games", "gen1_rby.lua").replace("\\", "/")
    G = lua.eval(f'dofile("{path}")')

    def flat(profile):
        out = {}
        for k, v in profile.items():
            if isinstance(v, int) and 0xC000 <= v <= 0xDFFF:
                out[k] = v
        return out

    red, yellow = flat(G.PROFILES["red"]), flat(G.PROFILES["yellow"])
    shifted = {}
    for k, rv in red.items():
        yv = yellow.get(k)
        if yv is not None and yv != rv:
            shifted[rv] = k
    assert len(shifted) > 20, (
        f"expected many shifted Gen 1 addresses, found {len(shifted)} — the profile "
        f"introspection is probably broken, which would make this test vacuous")
    return shifted


def test_scripts_exist():
    assert SCRIPTS, "no Gen 1 cartridge-driving scripts found — this test would be vacuous"


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: os.path.basename(p))
def test_no_yellow_shifted_literals(path, shifted_addresses):
    with open(path, encoding="utf-8") as f:
        src = _strip_lua_comments(f.read())
    offenders = []
    for m in HEX.finditer(src):
        addr = int(m.group(0), 16)
        name = shifted_addresses.get(addr)
        if name:
            line = src[: m.start()].count("\n") + 1
            offenders.append(f"  line {line}: {m.group(0)} is Red/Blue's {name}; "
                             f"Yellow shifts it — read M.{name} from the profile instead")
    assert not offenders, (
        f"{os.path.basename(path)} hardcodes {len(offenders)} address(es) that Yellow "
        f"shifts, so it reads the wrong byte there:\n" + "\n".join(offenders))
