"""Gen 1 policy rebind over synthetic pack-shaped checkpoints; MODEL only."""

import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class Checkpoint:
    def __init__(self, title="red"):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        pure = title.startswith("pure")
        pack = "gen1_purergb" if pure else "gen1_rby"
        self.profile = json.loads((ROOT / f"data/games/{pack}/write_checkpoint.json").read_text())[title]
        self.p = p = self.profile["write_safe"]
        self.rom = bytearray(0x4000)
        self.bus = bytearray(0x10000)
        self.registers = {"PC": p["irq_vector"], "SP": p["stack_min"], "WRAM BANK": 1}
        if pure:
            anchors = [(p[key], bytes.fromhex(value)) for key, value in p["expected_hex"].items()]
            resume, caller = p["delay_frame_resume"], p["overworld_return"]
        else:
            def transfer(opcode, address):
                return bytes([opcode, address & 255, address >> 8])
            anchors = [(p["irq_vector"], transfer(0xC3, p["vblank_entry"])),
                       (p["delay_frame"], bytes([0x3E, 1, 0xE0, p["vblank_flag"] & 255,
                                                0x76, 0xF0, p["vblank_flag"] & 255, 0xA7])),
                       (p["overworld_loop"], transfer(0xCD, p["delay_frame"])),
                       (p["overworld_loop_less_delay"], transfer(0xCD, p["delay_frame"]))]
            resume, caller = p["delay_frame"] + 5, p["overworld_loop"] + 3
        for address, data in anchors:
            self.rom[address:address + len(data)] = data
        sp = self.registers["SP"]
        self.bus[sp:sp + 4] = resume.to_bytes(2, "little") + caller.to_bytes(2, "little")
        self.bus[p["vblank_flag"]] = 1
        self.bus[p["serial_status"]] = p["disconnected_serial"]
        self.io = self.lua.table(read_u8=self.read, register=lambda name: self.registers.get(name),
                                 domains=lambda: self.lua.table("ROM", "System Bus"))
        self.module = self.lua.eval("dofile")((ROOT / "lua/gen1_write_safety.lua").as_posix())
        evaluator = self.lua.eval("dofile")((ROOT / "lua/gb_checkpoint.lua").as_posix())
        self.bound = self.module.new(evaluator)

    def read(self, address, domain):
        return (self.rom if domain == "ROM" else self.bus)[int(address)]

    def check(self, legacy=False):
        module = self.module if legacy else self.bound
        return module.check(self.lua.table_from(self.profile, recursive=True), self.io)


@pytest.mark.parametrize("title", ["red", "blue", "yellow", "purered", "pureblue", "puregreen"])
def test_explicit_and_legacy_bindings_preserve_both_game_checkpoint_shapes(title):
    checkpoint = Checkpoint(title)
    assert checkpoint.check() == (True, "verified overworld checkpoint")
    assert checkpoint.check(legacy=True) == (True, "verified overworld checkpoint")
    checkpoint.rom[checkpoint.p["irq_vector"]] ^= 1
    assert checkpoint.check()[0] is False
    assert checkpoint.check(legacy=True)[0] is False


@pytest.mark.parametrize("field", ["BATTLE_FLAG_ADDR", "JOY_IGNORE_ADDR", "FONT_LOADED_ADDR"])
def test_gen1_state_policy_stays_in_the_game_binder(field):
    checkpoint = Checkpoint()
    checkpoint.bus[checkpoint.profile[field]] = 1
    assert checkpoint.check()[0] is False


def test_gen1_font_bit_and_alternate_caller_keep_existing_behavior():
    checkpoint = Checkpoint()
    checkpoint.bus[checkpoint.profile["FONT_LOADED_ADDR"]] = 2
    sp = checkpoint.registers["SP"]
    checkpoint.bus[sp + 2:sp + 4] = (checkpoint.p["overworld_loop_less_delay"] + 3).to_bytes(2, "little")
    assert checkpoint.check()[0] is True


@pytest.mark.parametrize("title,field", [("red", "link_state"), ("red", "entering_cable_club"),
                                      ("yellow", "printer_open"), ("purered", "delay_frame_bank")])
def test_serial_printer_and_pure_bank_refusals_are_preserved(title, field):
    checkpoint = Checkpoint(title)
    checkpoint.bus[checkpoint.p[field]] = 1
    assert checkpoint.check()[0] is False


def test_pure_wram_bank_and_caller_are_both_required():
    checkpoint = Checkpoint("puregreen")
    for bank in (0, 1):
        checkpoint.registers["WRAM BANK"] = bank
        assert checkpoint.check()[0] is True
    checkpoint.registers["WRAM BANK"] = 2
    assert checkpoint.check()[0] is False
    checkpoint.registers["WRAM BANK"] = 1
    checkpoint.bus[checkpoint.registers["SP"] + 2] ^= 1
    assert checkpoint.check()[0] is False


def test_injected_evaluator_is_required_and_controls_the_result():
    checkpoint = Checkpoint()
    with pytest.raises(LuaError, match="shared GB evaluator"):
        checkpoint.module.new(None)
    refused = checkpoint.lua.eval("{check=function() return false, 'shared refusal' end}")
    checkpoint.bound = checkpoint.module.new(refused)
    assert checkpoint.check() == (False, "shared refusal")
