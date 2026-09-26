"""lua/gen3/run.lua must enforce the SAME admission policy as the launcher (lua/slink.lua),
not just Entry.admit's raw hash/anchors/header verdict.

The duo harness (lua/tests/duo/duo_gen3_main.lua) dofiles lua/gen3/run.lua directly, bypassing
lua/slink.lua's Entry.ROUTED / admitted_by check entirely -- so before Entry.admit_routed
existed, the duo evidence never actually proved the launcher's refusal of a header-only
admission or an unrouted pack (independent review OMP cx-dbabbd62). This drives the real
lua/gen3/run.lua under lupa with BizHawk's globals stubbed (the RUN_HOST idiom from
tests/unit/test_gen2_client.py::test_run_lua_exposes_the_production_client_only_for_an_admitted_cartridge
/ tests/unit/test_gen2_release_bundle_boot.py), asserting run.lua refuses by the SAME reason
Entry.admit_routed gives, and SLINK_GEN3_CLIENT is never set.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute run.lua")

REPO = Path(__file__).resolve().parents[2]
RUN_LUA = REPO / "lua" / "gen3" / "run.lua"

sys.path.insert(0, str(REPO / "tests" / "unit"))
from test_gen3_entry import seed_rom, sites_of  # noqa: E402  (reuse the real anchor synthesis)


def _run(rom: dict[int, int], rom_hash: str, drop_pack: str | None = None):
    """dofile the real lua/gen3/run.lua with BizHawk stubbed. `drop_pack`, when set, loads the
    REAL lua/gen3/entry.lua and then clears that one pack from its Entry.ROUTED table before
    handing it back -- a temp-root copy would also need a temp copy of every data/games/* pack
    file Entry.admission_table/artifacts read, so mutating the loaded module in place (the same
    global-dofile-interception idiom test_slink_route.py uses for its OWN real targets) gets the
    same effect without duplicating the pack tree.

    Returns (SLINK_GEN3_CLIENT, logs).
    """
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    logs: list[str] = []
    real_dofile = g.dofile

    def fake_dofile(path):
        module = real_dofile(path)
        if drop_pack and str(path).replace("\\", "/").endswith("/lua/gen3/entry.lua"):
            module.ROUTED[drop_pack] = False
        return module

    g.dofile = fake_dofile
    g.memory = lua.table_from({
        "read_u8": lambda a, d=None: rom.get(int(a), 0) if d == "ROM" else 0,
        "read_u16_le": lambda a, d=None: 0,
        "read_u32_le": lambda a, d=None: 0,
        "write_u8": lambda *a: None,
    })
    g.emu = lua.table_from({"framecount": lambda: 1, "getregister": lambda name: 0})
    g.event = lua.table_from({
        "on_bus_exec": lambda fn, addr, name: name,
        "onframeend": lambda fn: None,
        "onexit": lambda fn: None,
        "unregisterbyid": lambda hid: True,
    })
    g.console = lua.table_from({"log": lambda t: logs.append(str(t))})
    g.gameinfo = lua.table_from({"getromhash": lambda: rom_hash})
    lua.execute('package.loaded.connector = {init=function()end,send=function()end,'
                'receive=function()end,pump=function()end,connected=function()return false end}')
    lua.execute('package.loaded.hud = {init=function()end,render=function()end,show=function()end}')
    g.SLINK_GEN3_CLIENT = "stale"
    real_dofile(str(RUN_LUA))
    return g.SLINK_GEN3_CLIENT, logs


def test_a_header_only_admission_is_refused_naming_the_pinned_cartridge_rule():
    """Case 1: an unknown-hash BPEE build with no matching anchors admits by header alone
    (admitted_by == "header") -- Entry.admit_routed must refuse it, and run.lua must actually
    ask admit_routed, not the bare Entry.admit (which would return this same admission as a
    truthy hit and let Entry.build run on an unpinned cartridge)."""
    rom = seed_rom({}, header_code="BPEE")
    client, logs = _run(rom, rom_hash="f" * 40)
    assert client == "stale"
    assert any("not a pinned cartridge" in line for line in logs), logs


def test_a_pack_dropped_from_routed_is_refused_even_when_anchors_admit_it():
    """Case 2: a synthetic ROM whose anchors admit it as gen3_frlg/firered/clean (unknown hash,
    same synthesis as test_gen3_entry.py's test_admission_by_anchors_when_the_hash_is_unknown),
    but with gen3_frlg cleared from Entry.ROUTED. Entry.admit alone would happily return this
    admission; only admit_routed's own ROUTED check refuses it."""
    rom = seed_rom(sites_of("gen3_frlg", "firered", "clean"), header_code="BPRE")
    client, logs = _run(rom, rom_hash="0" * 40, drop_pack="gen3_frlg")
    assert client == "stale"
    assert any("gen3_frlg" in line and "not yet routed" in line for line in logs), logs
