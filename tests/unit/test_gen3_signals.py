"""gen3-P3-C3-1 (MODEL): lua/gen3/signals.lua — site load check, the fire-time
callback-address assertion, the bounded queue, registration hygiene, and the static
write-sink / BizHawk-global leak scan over lua/gen3/.

Everything is driven through the production `Entry.build` graph (the World harness in
test_gen3_entry.py), never by poking signals.lua directly.
"""
from __future__ import annotations

import re

import lupa
import pytest

from tests.unit.test_gen3_entry import (
    GEN3_LUA,
    REPO,
    World,
    lua_to_py,
    seed_rom,
    sites_of,
)

SITES = sites_of("gen3_rr", "radical_red", "clean")


def status(world):
    return lua_to_py(world.parts.signals.status(world.parts.signals))


def drain(world):
    return lua_to_py(world.parts.signals.drain(world.parts.signals))


def test_every_site_is_registered_at_address_plus_capture_offset():
    world = World()
    assert len(world.hooks) == len(SITES)
    for kind, site in SITES.items():
        _, addr = world.hooks[f"SLink-gen3-{kind}"]
        assert addr == site["address"] + site.get("capture_offset", 0)
    assert status(world)["registered"] == len(SITES)


def test_a_fire_queues_the_recorded_cpu_state():
    world = World()
    world.frame = 4242
    world.regs.update({"R15": 0x0800051C, "CPSR": 0x6000003F, "R13": 0x03007F10})
    site = SITES["save"]
    world.poke(site["address"], bytes.fromhex(site["expected_hex"]))
    world.fire("save")

    signal = drain(world)[0]
    assert signal["kind"] == "save"
    assert signal["frame"] == 4242
    assert signal["address"] == site["address"] + site.get("capture_offset", 0)
    assert signal["callback_address"] == signal["address"]
    # raw R15 is the NEXT instruction inside the hook: recorded, never the identity test
    assert signal["raw_r15"] == 0x0800051C
    assert signal["cpsr"] == 0x6000003F and signal["thumb"] == 1
    assert signal["sp"] == 0x03007F10
    assert signal["mode"] == site["mode"]
    # the generic point is exactly the registers the site lists
    assert set(signal["point"]) == set(site["point"])
    assert drain(world) == []


def test_a_callback_at_the_wrong_address_is_rejected_and_counted():
    world = World()
    site = SITES["save"]
    world.poke(site["address"], bytes.fromhex(site["expected_hex"]))
    world.fire("save", address=site["address"] + 2)
    assert drain(world) == []
    counters = status(world)
    assert counters["rejected"] == 1
    assert counters.get("failed") is None, "a foreign callback is dropped, not a build failure"
    world.fire("save")
    assert len(drain(world)) == 1


def test_a_bus_recheck_mismatch_fails_the_signal_set():
    world = World()
    site = SITES["save"]
    world.poke(site["address"], bytes.fromhex(site["expected_hex"]))
    world.bus[site["address"]] ^= 0xFF
    world.fire("save")
    assert drain(world) == []
    assert "differ at fire time" in status(world)["failed"]


def test_the_queue_is_bounded():
    world = World()
    site = SITES["save"]
    world.poke(site["address"], bytes.fromhex(site["expected_hex"]))
    bound = int(world.lua.eval(
        f'dofile("{(GEN3_LUA / "signals.lua").as_posix()}")').MAX_PENDING)
    for _ in range(bound + 3):
        world.fire("save")
    counters = status(world)
    assert counters["pending"] == bound
    assert counters["dropped"] >= 1
    assert "buffer full" in counters["failed"]


def test_an_on_fire_handler_runs_inside_the_hook():
    seen = []
    world = World(on_fire=None)
    site = SITES["save"]
    world.poke(site["address"], bytes.fromhex(site["expected_hex"]))
    # rebuild with a handler now that the world exists
    handlers = world.lua.table(save=lambda signal: seen.append(int(signal["frame"])))
    world.registered.clear()
    _, parts = world.Entry.build(world.deps(on_fire=handlers))
    world.parts = parts
    world.frame = 7
    world.fire("save")
    assert seen == [7]
    assert status(world).get("handler_error") is None


def test_a_failing_on_fire_handler_is_recorded_not_raised():
    world = World(build=False)
    site = SITES["save"]
    world.poke(site["address"], bytes.fromhex(site["expected_hex"]))

    def boom(_signal):
        raise RuntimeError("handler exploded")

    _, world.parts = world.Entry.build(world.deps(on_fire=world.lua.table(save=boom)))
    world.fire("save")
    assert len(drain(world)) == 1, "the signal is still queued"
    assert "save:" in status(world)["handler_error"]


def test_a_null_guid_registration_refuses_and_unregisters_what_it_took():
    world = World(build=False)
    world.id_hook = lambda index: ("{00000000-0000-0000-0000-000000000000}"
                                   if index == 3 else f"id-{index:04d}")
    with pytest.raises(lupa.LuaError, match="engine signal registration failed"):
        world.Entry.build(world.deps())
    assert len(world.registered) == 4
    assert world.unregistered == [f"id-{i:04d}" for i in range(3)]


def test_close_unregisters_every_hook():
    world = World()
    world.parts.signals.close(world.parts.signals)
    assert sorted(world.unregistered) == sorted(world.registered)
    site = SITES["save"]
    world.poke(site["address"], bytes.fromhex(site["expected_hex"]))
    world.fire("save")
    assert drain(world) == [], "a closed signal set queues nothing"


def test_the_load_check_reads_the_rom_not_the_bus():
    """The bus is empty in this world; only the ROM table carries the site bytes, and the
    build still succeeds — the load-time anchor is a ROM read."""
    world = World(rom=seed_rom(SITES), build=False)
    world.bus.clear()
    _, parts = world.Entry.build(world.deps())
    assert parts.signals is not None


# ── static leak scan ─────────────────────────────────────────────────────────────────
# PLAN §5.7: writes.lua is the ONLY file under lua/gen3/ allowed to reach a write sink;
# `writes.log` alone cannot prove ownership because a bypass through memory.write_* leaves
# no log entry. The BizHawk-global half of the rule covers the modules this card owns; a
# bootstrap (run.lua / shadow_run.lua) is what BUILDS the io/ev tables, so it is exempt by
# name, exactly as lua/gen1/entry.lua's `bizhawk_deps` is.
# A call on the armed `writes` object is the gate itself, not a raw sink (boxes.lua routes
# every PC move through `io.writes:write_bytes`); any other write_* call is a leak.
WRITE_SINKS = re.compile(r"memory\s*\.\s*write|(?<!writes)[:.]\s*write_(?:u8|u16|u32|bytes)\s*\(")
BIZHAWK_GLOBALS = re.compile(
    r"(?<![\w.])(memory|emu|event|joypad|gui|client|console|savestate|userdata)\s*\.")
MODULES = ("entry.lua", "reads.lua", "signals.lua")
BOOTSTRAPS = ("run.lua", "shadow_run.lua")


def _code(path):
    """The file with -- comments and quoted strings removed, so a citation cannot trip."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("--", 1)[0]
        line = re.sub(r'"[^"]*"|\'[^\']*\'', '""', line)
        out.append(line)
    return "\n".join(out)


def test_no_write_sink_outside_writes_lua():
    offenders = {}
    for path in sorted(GEN3_LUA.glob("*.lua")):
        if path.name == "writes.lua" or path.name in BOOTSTRAPS:
            continue
        hits = WRITE_SINKS.findall(_code(path))
        if hits:
            offenders[path.name] = hits
    assert offenders == {}, f"write sinks outside lua/gen3/writes.lua: {offenders}"


def test_no_bizhawk_globals_in_the_gen3_modules():
    offenders = {}
    for name in MODULES:
        path = GEN3_LUA / name
        hits = BIZHAWK_GLOBALS.findall(_code(path))
        if hits:
            offenders[name] = sorted(set(hits))
    assert offenders == {}, (
        f"BizHawk globals in lua/gen3 modules: {offenders}; everything arrives via deps "
        f"(bootstraps {BOOTSTRAPS} are the exemption)")


def test_no_literal_gba_addresses_in_the_gen3_modules():
    """Every game address comes from the pack JSON. The only hex literals allowed in these
    modules are struct geometry, bit masks and the two GBA cartridge-header offsets — never
    an 0x08xxxxxx ROM or 0x02/0x03xxxxxx RAM address."""
    pattern = re.compile(r"0x0[238][0-9A-Fa-f]{6}")
    for name in MODULES:
        hits = pattern.findall(_code(GEN3_LUA / name))
        assert hits == [], f"literal GBA address in lua/gen3/{name}: {hits}"


def test_the_leak_scan_would_catch_a_planted_sink(tmp_path):
    """A known-positive control: the scan is only worth running if it fails on a real
    offender."""
    planted = tmp_path / "leaky.lua"
    planted.write_text("local x = memory.write_u8(0x02000000, 1)\n", encoding="utf-8")
    code = _code(planted)
    assert WRITE_SINKS.search(code)
    assert BIZHAWK_GLOBALS.search(code)
    assert re.search(r"0x0[238][0-9A-Fa-f]{6}", code)
    assert REPO.exists()
