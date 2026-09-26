"""Execute RGBDS-built held-foreground preimage routines (MODEL, no emulator)."""

import pytest

from tests.unit.test_gen2_companion_abi import Machine, assemble, native_symbols

NAMES = ("wPartyCount", "wPartySpecies", "wPartyMon1", "wPartyMonOTs", "wPartyMonNicknames",
         "wOTPartyMon2", "wOTPartyMonOTs", "wOTPartyMonNicknames")


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def compiled(request, tmp_path_factory):
    native = native_symbols(request.param)
    definitions = "".join(f"DEF {name} EQU ${native[name][1]:04x}\n" for name in NAMES)
    definitions += "DEF PARTYMON_STRUCT_LENGTH EQU 48\nDEF NAME_LENGTH EQU 11\nDEF MON_NAME_LENGTH EQU 11\nDEF PARTY_LENGTH EQU 6\nDEF EGG EQU $fd\n"
    rom, symbols = assemble(tmp_path_factory.mktemp(request.param), request.param,
        definitions + 'INCLUDE "patch/gen2/src/trade_snapshot.asm"\n')
    return request.param, rom, {**symbols, **{name: native[name] for name in NAMES}}


class SnapshotMachine(Machine):
    """Only instructions emitted here; no interrupts/timing or native hooks are modeled."""

    def run(self, symbol):
        self.bank, self.pc = self.symbols[symbol]
        self.push(0xffff)
        for _ in range(5000):
            if self.pc == 0xffff:
                return
            op = self.fetch()
            hl = self.r["h"] << 8 | self.r["l"]
            de = self.r["d"] << 8 | self.r["e"]
            if op == 0:
                pass
            elif op in (0xc5, 0xd5, 0xe5, 0xc1, 0xd1, 0xe1):
                hi, lo = {0xc5: "bc", 0xd5: "de", 0xe5: "hl", 0xc1: "bc", 0xd1: "de", 0xe1: "hl"}[op]
                if op & 4:
                    self.push(self.r[hi] << 8 | self.r[lo])
                else:
                    value = self.pop()
                    self.r[hi], self.r[lo] = value >> 8, value & 255
            elif op in (0x0e, 0x16):
                self.r["c" if op == 0x0e else "d"] = self.fetch()
            elif op in (0x11, 0x21):
                value = self.word()
                hi, lo = "de" if op == 0x11 else "hl"
                self.r[hi], self.r[lo] = value >> 8, value & 255
            elif op in (0x13, 0x23):
                hi, lo = "de" if op == 0x13 else "hl"
                value = ((self.r[hi] << 8 | self.r[lo]) + 1) & 65535
                self.r[hi], self.r[lo] = value >> 8, value & 255
            elif op == 0x19:
                value = hl + de
                self.r["h"], self.r["l"] = (value >> 8) & 255, value & 255
                self.r["f"] = (self.r["f"] & 0x80) | (0x10 if value > 65535 else 0)
            elif op in (0x1a, 0x7e, 0x2a, 0xfa):
                self.r["a"] = self.read(de if op == 0x1a else self.word() if op == 0xfa else hl)
                if op == 0x2a:
                    value = (hl + 1) & 65535
                    self.r["h"], self.r["l"] = value >> 8, value & 255
            elif op == 0x12:
                self.write(de, self.r["a"])
            elif op in (0x47, 0x4f, 0x58, 0x78):
                dst, src = {0x47: "ba", 0x4f: "ca", 0x58: "eb", 0x78: "ab"}[op]
                self.r[dst] = self.r[src]
            elif op in (0xfe, 0xbe, 0xb8, 0xb9):
                operand = self.fetch() if op == 0xfe else self.read(hl) if op == 0xbe else self.r["b" if op == 0xb8 else "c"]
                value = self.r["a"] - operand
                self.r["f"] = 0x40 | (0x80 if value == 0 else 0) | (0x10 if value < 0 else 0)
            elif op == 0xa7:
                self.r["f"] = 0x20 | (0x80 if self.r["a"] == 0 else 0)
            elif op in (0x0d, 0x3d):
                reg = "c" if op == 0x0d else "a"
                self.r[reg] = (self.r[reg] - 1) & 255
                self.r["f"] = (self.r["f"] & 0x10) | 0x40 | (0x80 if self.r[reg] == 0 else 0)
            elif op == 0x37:
                self.r["f"] = (self.r["f"] & 0x80) | 0x10
            elif op in (0x20, 0x28, 0x30, 0x38):
                offset = self.fetch()
                flag = 0x80 if op in (0x20, 0x28) else 0x10
                take = bool(self.r["f"] & flag) == (op in (0x28, 0x38))
                if take:
                    self.pc += offset if offset < 128 else offset - 256
            elif op == 0xcd:
                target = self.word()
                self.push(self.pc)
                self.pc = target
            elif op == 0xc9 or op == 0xc8 and self.r["f"] & 0x80:
                self.pc = self.pop()
            elif op != 0xc8:
                raise AssertionError(f"unsupported opcode {op:02x} at {self.pc - 1:04x}")
        raise AssertionError("snapshot routine exceeded instruction budget")


def setup(compiled):
    m = SnapshotMachine(compiled)
    address = {name: pair[1] for name, pair in m.symbols.items() if name in NAMES}
    m.ram[:] = b"\xa5" * 65536
    m.ram[address["wPartyCount"]] = 6
    for slot in range(6):
        m.ram[address["wPartySpecies"] + slot] = slot + 1
        for name, size in (("wPartyMon1", 48), ("wPartyMonOTs", 11), ("wPartyMonNicknames", 11)):
            start = address[name] + slot * size
            m.ram[start:start + size] = bytes((slot + i + 1) % 256 for i in range(size))
    return m, address


def spans(address, slot):
    return [(address["wPartyMon1"] + slot * 48, address["wOTPartyMon2"], 48),
            (address["wPartyMonOTs"] + slot * 11, address["wOTPartyMonOTs"] + 11, 11),
            (address["wPartyMonNicknames"] + slot * 11, address["wOTPartyMonNicknames"] + 11, 11)]


def call(m, symbol, slot):
    regs = {key: m.r[key] for key in "bcdehl"}
    m.r["a"] = slot
    m.run(symbol)
    assert {key: m.r[key] for key in "bcdehl"} == regs
    assert m.sp == 0xdffe
    return bool(m.r["f"] & 0x10)


@pytest.mark.parametrize("slot", range(6))
def test_snapshot_copies_exactly_selected_record_and_leaves_incoming_untouched(compiled, slot):
    m, a = setup(compiled)
    before = bytearray(m.ram)
    assert not call(m, "SlinkTradeSnapshot", slot)
    for source, target, size in spans(a, slot):
        before[target:target + size] = before[source:source + size]
    assert m.ram[:0xdfe0] == before[:0xdfe0]
    assert m.ram[0xdffe:] == before[0xdffe:]
    assert not call(m, "SlinkTradeValidateSnapshot", slot)


@pytest.mark.parametrize("byte", range(70))
def test_snapshot_refuses_each_live_preimage_byte_mutation(compiled, byte):
    m, a = setup(compiled)
    assert not call(m, "SlinkTradeSnapshot", 2)
    addresses = [source + index for source, target, size in spans(a, 2) for index in range(size)]
    m.ram[addresses[byte]] ^= 1
    before = bytes(m.ram)
    assert call(m, "SlinkTradeValidateSnapshot", 2)
    assert m.ram[:0xdfe0] == before[:0xdfe0]


@pytest.mark.parametrize("count,slot", ((0, 0), (7, 0), (255, 0), (1, 1), (6, 6), (6, 255)))
@pytest.mark.parametrize("symbol", ("SlinkTradeSnapshot", "SlinkTradeValidateSnapshot"))
def test_snapshot_bounds_refuse_without_wram_changes(compiled, count, slot, symbol):
    m, a = setup(compiled)
    m.ram[a["wPartyCount"]] = count
    before = bytes(m.ram)
    assert call(m, symbol, slot)
    assert m.ram[:0xdfe0] == before[:0xdfe0]


def test_snapshot_wrong_slot_species_drift_egg_and_release(compiled):
    m, a = setup(compiled)
    assert not call(m, "SlinkTradeSnapshot", 1)
    assert call(m, "SlinkTradeValidateSnapshot", 2)
    m.ram[a["wPartySpecies"] + 1] = 99
    assert call(m, "SlinkTradeValidateSnapshot", 1)
    m.ram[a["wPartySpecies"] + 1] = 0xfd
    assert not call(m, "SlinkTradeValidateSnapshot", 1)
    before = bytes(m.ram)
    call(m, "SlinkTradeReleaseSnapshot", 1)
    assert m.ram[:0xdfe0] == before[:0xdfe0]
