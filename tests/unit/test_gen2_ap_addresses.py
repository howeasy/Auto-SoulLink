"""AP Crystal's profile must agree with what Archipelago itself declares.

The `crystal_ap` profile used to inherit EVERY address from vanilla Crystal through a
metatable, on the stated assumption that the fork "uses the same RAM layout as vanilla — only
the ROM title differs". That is false, and it is falsifiable without ever booting a ROM: the
shipped `pokemon_crystal.apworld` carries its own `ram_addresses` table, and diffing it
against vanilla shows four different deltas in both directions.

This is the same bug Gen 1's `red_ap` had (+88 / -18 / +216), and it fails in the worst
possible way — quietly, reading a neighbouring byte that holds a plausible value.

WHAT THIS TEST CAN AND CANNOT DO. The apworld declares only five vanilla symbols, and there
is no public fork repo to build a full symbol set from, so `tools/build_pret_syms.py` cannot
do for AP Crystal what it does for `alchav_pokered`. These tests therefore pin the five
provable addresses and assert that the profile is still *flagged* as unverified. They do not,
and must not, be read as evidence that AP Crystal works.

The apworld is read at test time rather than having its numbers copied into Python, so an AP
upgrade that moves an address fails here instead of silently disagreeing with the profile.
"""
import json
import os
import zipfile

import pytest

lupa = pytest.importorskip("lupa")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APWORLD = r"C:\ProgramData\Archipelago\custom_worlds\pokemon_crystal.apworld"
WRAM_BASE = 0xC000


def _profiles():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("print = function() end")
    path = os.path.join(REPO, "lua", "games", "gen2_crystal.lua").replace("\\", "/")
    return lua.eval(f'dofile("{path}")').PROFILES


@pytest.fixture(scope="module")
def ap_ram():
    """Archipelago's own declared RAM addresses, in System Bus space."""
    if not os.path.exists(APWORLD):
        pytest.skip(f"pokemon_crystal.apworld not installed at {APWORLD}")
    with zipfile.ZipFile(APWORLD) as z:
        data = json.loads(z.read("pokemon_crystal/data/data.json"))
    ram = data.get("ram_addresses") or {}
    assert len(ram) >= 10, f"apworld declared only {len(ram)} ram_addresses — format changed?"
    return {k: v + WRAM_BASE for k, v in ram.items()}


@pytest.fixture(scope="module")
def vanilla():
    with open(os.path.join(REPO, "data", "pret_syms.json"), encoding="utf-8") as f:
        return json.load(f)["pokecrystal"]


def test_the_fork_really_does_relocate_wram(ap_ram, vanilla):
    """The premise. If this ever passes with a single delta of 0, inheriting becomes correct
    and the overrides below should be deleted rather than maintained."""
    deltas = {
        name: ap_ram[name] - vanilla[name]
        for name in ap_ram
        if not name.startswith("wArchipelago") and name in vanilla
    }
    assert deltas, "no shared symbols between the apworld table and vanilla — cannot compare"
    assert set(deltas.values()) != {0}, (
        "AP Crystal now matches vanilla exactly; the crystal_ap overrides are obsolete")
    # Recorded in the failure message so a future change shows its work.
    assert len(set(deltas.values())) > 1, f"expected non-uniform relocation, got {deltas}"


def test_map_addresses_match_archipelagos_own_table(ap_ram):
    """The two the profile actually uses. A wrong map address breaks area resolution, which
    breaks encounter linking — the rule SLink exists for."""
    ap = _profiles()["crystal_ap"]
    assert ap_ram["wMapGroup"] == ap.MAP_GROUP_ADDR, (
        f"crystal_ap MAP_GROUP_ADDR is {ap.MAP_GROUP_ADDR:#06x}, Archipelago declares "
        f"{ap_ram['wMapGroup']:#06x}")
    assert ap_ram["wMapNumber"] == ap.MAP_NUMBER_ADDR, (
        f"crystal_ap MAP_NUMBER_ADDR is {ap.MAP_NUMBER_ADDR:#06x}, Archipelago declares "
        f"{ap_ram['wMapNumber']:#06x}")


def test_map_addresses_are_not_vanillas(vanilla):
    """The specific regression: inheriting vanilla's map addresses."""
    ap = _profiles()["crystal_ap"]
    assert vanilla["wMapGroup"] != ap.MAP_GROUP_ADDR, (
        "crystal_ap is serving vanilla's wMapGroup — the metatable inheritance is back")


def test_recorded_known_addresses_match_the_apworld(ap_ram):
    """The three fork addresses the profile has no key for yet are still pinned, so whoever
    adds those keys starts from verified values."""
    known = dict(_profiles()["crystal_ap"].ap_known_addresses or {})
    assert known, "ap_known_addresses disappeared from the crystal_ap profile"
    for name, addr in known.items():
        assert name in ap_ram, f"{name} is no longer in the apworld table"
        assert int(addr) == ap_ram[name], (
            f"{name}: profile records {int(addr):#06x}, Archipelago declares {ap_ram[name]:#06x}")


def test_ap_profile_is_still_flagged_unverified():
    """Most crystal_ap addresses are inherited and unproven. Removing this flag is a claim
    that someone verified them — which requires a live gate on a generated AP ROM, not a
    metatable."""
    ap = _profiles()["crystal_ap"]
    assert ap.ap_addresses_unverified is True, (
        "crystal_ap no longer declares its addresses unverified. If AP Crystal has actually "
        "been gated on hardware, delete this test and say so in the docs; do not just drop "
        "the flag.")
