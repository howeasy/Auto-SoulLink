"""Reject unsafe CPU contexts and missing evidence using real canonical ROM bytes.

The live gates independently obtain the positive CPU/stack states from actual
menu, battle, capture, save and map execution; these are mutation controls.
"""
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
ROMS = {
    "red": "Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
    "blue": "Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb",
    "yellow": "Pokemon - Yellow Version (USA, Europe).gbc",
}


def runtime(variant):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    game = lua.execute((ROOT / "lua/games/gen1_rby.lua").read_text(encoding="utf-8"))
    guard = lua.execute((ROOT / "lua/gen1_write_safety.lua").read_text(encoding="utf-8"))
    profile = game.PROFILES[variant]
    p = profile.write_safe
    rom = bytearray((ROOT / ROMS[variant]).read_bytes())
    bus = {p.vblank_flag: 1, p.serial_status: 255}
    registers = {"PC": 64, "SP": 0xDFFB}
    reads = []

    def read(address, domain):
        reads.append((address, domain))
        assert domain in ("ROM", "System Bus") and 0 <= address <= 65535
        return rom[address] if domain == "ROM" else bus.get(address, 0)

    for address, value in ((0xDFFB, p.delay_frame + 5), (0xDFFD, p.overworld_loop + 3)):
        bus[address], bus[address + 1] = value & 255, value >> 8
    io = lua.table_from({"domains": lambda: lua.table_from(["ROM", "System Bus"]),
                         "read_u8": read, "register": registers.get})
    return lua, guard, profile, io, bus, rom, registers, reads


@pytest.mark.parametrize("variant", ROMS)
def test_two_source_backed_main_loop_returns_are_accepted(variant):
    _, guard, profile, io, bus, _, _, _ = runtime(variant)
    for caller in (profile.write_safe.overworld_loop + 3, profile.write_safe.overworld_loop_less_delay + 3):
        bus[0xDFFD], bus[0xDFFE] = caller & 255, caller >> 8
        assert guard.check(profile, io)[0] is True


@pytest.mark.parametrize("variant", ROMS)
@pytest.mark.parametrize("field,value", [
    ("PC", 0), ("PC", 65), ("PC", 0x2024), ("PC", None),
    ("SP", 0xC000), ("SP", 0xDEFF), ("SP", 0xDFFD), ("SP", 0xFFFF),
    ("SP", -1), ("SP", 0xDFFB + .5), ("SP", "57339"), ("SP", None),
])
def test_wrong_or_unavailable_cpu_context_is_rejected(variant, field, value):
    _, guard, profile, io, _, _, registers, reads = runtime(variant)
    registers[field] = value
    assert guard.check(profile, io)[0] is False
    assert not any(domain == "System Bus" and 0xDF00 <= address <= 0xDFFF for address, domain in reads)


@pytest.mark.parametrize("variant", ROMS)
@pytest.mark.parametrize("word", [0, 1])
def test_a_menu_delayframe_or_other_interrupt_return_cannot_qualify(variant, word):
    _, guard, profile, io, bus, _, _, _ = runtime(variant)
    bus[0xDFFB + 2 * word] ^= 1
    assert guard.check(profile, io)[0] is False


@pytest.mark.parametrize("variant", ROMS)
@pytest.mark.parametrize("field,value", [
    ("BATTLE_FLAG_ADDR", 1), ("BATTLE_FLAG_ADDR", 2), ("BATTLE_FLAG_ADDR", 255),
    ("JOY_IGNORE_ADDR", 1), ("FONT_LOADED_ADDR", 1), ("FONT_LOADED_ADDR", 3),
    ("vblank_flag", 0), ("vblank_flag", 2), ("link_state", 1), ("link_state", 0x32),
    ("serial_status", 1), ("serial_status", 2), ("serial_status", 0), ("entering_cable_club", 1),
])
def test_busy_flags_override_an_apparently_valid_cpu_checkpoint(variant, field, value):
    _, guard, profile, io, bus, _, _, _ = runtime(variant)
    address = profile[field] if field.endswith("_ADDR") else profile.write_safe[field]
    bus[address] = value
    assert guard.check(profile, io)[0] is False


def test_yellow_printer_ownership_is_exclusive():
    _, guard, profile, io, bus, _, _, _ = runtime("yellow")
    bus[profile.write_safe.printer_open] = 1
    assert guard.check(profile, io)[0] is False


def test_yellow_never_reads_below_its_smaller_stack_allocation():
    _, guard, profile, io, _, _, registers, reads = runtime("yellow")
    registers["SP"] = 0xDF14
    assert guard.check(profile, io)[0] is False
    assert not any(domain == "System Bus" and 0xDF00 <= address <= 0xDFFF for address, domain in reads)


@pytest.mark.parametrize("variant", ROMS)
def test_every_rom_anchor_byte_is_required_and_rechecked_after_a_success(variant):
    _, guard, profile, io, _, rom, _, _ = runtime(variant)
    p = profile.write_safe
    anchors = [*range(p.irq_vector, p.irq_vector + 3), *range(p.delay_frame, p.delay_frame + 8),
               *range(p.overworld_loop, p.overworld_loop + 6)]
    assert guard.check(profile, io)[0] is True
    for address in anchors:
        rom[address] ^= 1
        assert guard.check(profile, io)[0] is False, hex(address)
        rom[address] ^= 1
        assert guard.check(profile, io)[0] is True


@pytest.mark.parametrize("failure", ["domains", "ROM", "System Bus", "read_u8", "register", "version", "profile"])
def test_no_api_or_evidence_failure_can_fall_back_to_flags(failure):
    lua, guard, profile, io, _, _, _, _ = runtime("red")
    if failure in ("ROM", "System Bus"):
        io.domains = lambda: lua.table_from([failure])
    elif failure in ("domains", "read_u8", "register"):
        io[failure] = lua.eval("function() error('unavailable API') end")
    elif failure == "version":
        profile.write_safe.version = "unknown"
    else:
        profile.write_safe = None
    safe, reason = guard.check(profile, io)
    assert safe is False and reason


@pytest.mark.parametrize("variant", ["red_ap", "blue_ap"])
def test_ap_has_no_new_checkpoint_and_preserves_its_existing_guard(variant):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        bus = {}; memory = {
            read_u8 = function(a) return bus[a] or 0 end,
            write_u8 = function() error('no writes allowed') end,
            getmemorydomainlist = function() return {'System Bus'} end,
        }; print = function() end
    """)
    game = lua.execute((ROOT / "lua/games/gen1_rby.lua").read_text(encoding="utf-8"))
    memory = lua.execute((ROOT / "lua/memory_gb.lua").read_text(encoding="utf-8"))
    memory.initProfile(game, variant)
    assert memory.profile.write_safe is None
    assert memory.isPartyWriteSafe()[0] is True
    lua.globals().bus[memory.FONT_LOADED_ADDR] = 1
    assert memory.isPartyWriteSafe()[0] is False
