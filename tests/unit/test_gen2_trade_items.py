"""Real RGBDS item predicate, executed as bounded instruction MODEL (no emulator)."""

import json

import pytest

from tests.unit.test_gen2_companion_abi import ROOT, Machine, assemble
from tools.gen2_source_data import load_context
from tools.gen_gen2_items import build


@pytest.fixture(scope="module", params=["crystal", "gold", "silver"])
def compiled_items(request, tmp_path_factory):
    title = request.param
    pack = json.loads((ROOT / f"data/games/gen2_{title}/items.json").read_text())
    # Reparse pinned native constants, MailItems and all attributes; build also
    # verifies their compiled ROM bytes. The checked-in pack is not its own oracle.
    assert build(load_context(title)) == pack
    expected = [True] + [not (row["placeholder"] or row["key_item"] or row["permissions"] & 0x80 or row["mail"])
                         for row in (pack["items"][str(item)] for item in range(1, 255))] + [False]
    temp = tmp_path_factory.mktemp(f"trade-items-{title}")
    rom, symbols = assemble(temp, title, 'INCLUDE "patch/gen2/src/trade_items.asm"\n')
    return (title, rom, symbols), expected, pack


class ItemMachine(Machine):
    """Only this predicate's actual emitted opcodes; unknown instructions refuse."""

    def item_allowed(self, item):
        bank, self.pc = self.symbols["SlinkTradeItemAllowed"]
        self.bank = bank
        self.ram[self.bank_address] = bank
        self.r["a"] = item
        before = dict(self.r)
        old_sp = self.sp
        self.push(0xFFFF)
        for _ in range(32):
            if self.pc == 0xFFFF:
                assert self.sp == old_sp
                assert all(self.r[r] == before[r] for r in "bcdehl")
                assert self.bank == bank and self.ram[self.bank_address] == bank
                assert set(self.written) <= set(range(old_sp - 6, old_sp))
                return not bool(self.r["f"] & 0x10)
            op = self.fetch()
            if op in (0xD5, 0xE5):
                hi, lo = {0xD5: "de", 0xE5: "hl"}[op]
                self.push(self.r[hi] << 8 | self.r[lo])
            elif op in (0xD1, 0xE1):
                hi, lo = {0xD1: "de", 0xE1: "hl"}[op]
                value = self.pop()
                self.r[hi], self.r[lo] = value >> 8, value & 255
            elif op == 0x5F:
                self.r["e"] = self.r["a"]
            elif op == 0x16:
                self.r["d"] = self.fetch()
            elif op == 0x21:
                value = self.word()
                self.r["h"], self.r["l"] = value >> 8, value & 255
            elif op == 0x19:
                value = (self.r["h"] << 8 | self.r["l"]) + (self.r["d"] << 8 | self.r["e"])
                self.r["h"], self.r["l"] = (value >> 8) & 255, value & 255
                self.r["f"] = self.r["f"] & 0x80 | (0x10 if value > 65535 else 0)
            elif op == 0x7E:
                self.r["a"] = self.read(self.r["h"] << 8 | self.r["l"])
            elif op == 0xFE:
                other = self.fetch()
                a = self.r["a"]
                self.r["f"] = 0x40 | (0x80 if a == other else 0) | (0x10 if a < other else 0) | (0x20 if (a & 15) < (other & 15) else 0)
            elif op == 0xC9:
                self.pc = self.pop()
            else:
                raise AssertionError(f"unsupported item-predicate opcode {op:02x}")
        raise AssertionError("item predicate exceeded instruction budget")


@pytest.mark.parametrize("carry", [0, 0x10])
def test_compiled_item_predicate_matches_every_native_item(compiled_items, carry):
    compiled, expected, _ = compiled_items
    for item in range(256):
        machine = ItemMachine(compiled)
        machine.r["f"] = 0xE0 | carry
        assert machine.item_allowed(item) == expected[item], f"{compiled[0]} item {item:02x}"


def test_compiled_item_table_has_exact_coverage_and_bank(compiled_items):
    compiled, expected, pack = compiled_items
    title, rom, symbols = compiled
    bank, address = symbols["SlinkTradeAllowedItems"]
    assert bank == (0x75 if title == "crystal" else 0x13)
    assert symbols["SlinkTradeAllowedItemsEnd"] == (bank, address + 256)
    start = bank * 0x4000 + address - 0x4000
    assert rom[start:start + 256] == bytes(expected)
    assert sum(expected) == 184 and expected[0] and not expected[255]
    assert all(not expected[item] for item in pack["mail_ids"])


@pytest.mark.parametrize("item", [0, 1, 0x19, 0x9E, 0xF3, 0xFF])
def test_compiled_membership_mutation_is_detected(compiled_items, item):
    compiled, expected, _ = compiled_items
    machine = ItemMachine(compiled)
    bank, address = machine.symbols["SlinkTradeAllowedItems"]
    rom = bytearray(machine.rom)
    rom[bank * 0x4000 + address - 0x4000 + item] ^= 1
    machine.rom = bytes(rom)
    assert machine.item_allowed(item) != expected[item]
