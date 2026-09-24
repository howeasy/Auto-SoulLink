"""RGBDS-compiled trade-frame primitives: MODEL byte effects, not hardware timing."""

import pytest

from tests.unit.test_gen2_companion_abi import Machine, assemble


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def compiled(request, tmp_path_factory):
    return request.param, *assemble(tmp_path_factory.mktemp(request.param), request.param,
        'INCLUDE "patch/gen2/src/trade_frame.asm"\n')


class TradeMachine(Machine):
    """Execute only the emitted primitive instructions; unknown bytes fail closed."""

    def run(self, symbol):
        self.bank, self.pc = self.symbols[symbol]
        self.push(0xffff)
        for _ in range(300):
            if self.pc == 0xffff:
                return
            op = self.fetch()
            if op == 0:
                pass
            elif op in (0xc5, 0xd5, 0xe5, 0xc1, 0xd1, 0xe1):
                hi, lo = {0xc5: "bc", 0xd5: "de", 0xe5: "hl",
                          0xc1: "bc", 0xd1: "de", 0xe1: "hl"}[op]
                if op & 4:
                    self.push(self.r[hi] << 8 | self.r[lo])
                else:
                    value = self.pop()
                    self.r[hi], self.r[lo] = value >> 8, value & 255
            elif op in (0x06, 0x0e):
                self.r["b" if op == 0x06 else "c"] = self.fetch()
            elif op == 0x11:
                value = self.word()
                self.r["d"], self.r["e"] = value >> 8, value & 255
            elif op in (0x13, 0x23):
                hi, lo = "de" if op == 0x13 else "hl"
                value = ((self.r[hi] << 8 | self.r[lo]) + 1) & 65535
                self.r[hi], self.r[lo] = value >> 8, value & 255
            elif op in (0x1a, 0xfa):
                self.r["a"] = self.read(self.r["d"] << 8 | self.r["e"] if op == 0x1a else self.word())
            elif op == 0xea:
                self.write(self.word(), self.r["a"])
            elif op in (0xfe, 0xbe):
                operand = self.fetch() if op == 0xfe else self.read(self.r["h"] << 8 | self.r["l"])
                value = self.r["a"] - operand
                self.r["f"] = 0x40 | (0x80 if value == 0 else 0) | (0x10 if value < 0 else 0)
            elif op in (0xaf, 0xa7, 0xb0):
                if op == 0xaf:
                    self.r["a"] = 0
                elif op == 0xb0:
                    self.r["a"] |= self.r["b"]
                self.r["f"] = (0x80 if self.r["a"] == 0 else 0) | (0x20 if op == 0xa7 else 0)
            elif op == 0x0d:
                self.r["c"] = (self.r["c"] - 1) & 255
                self.r["f"] = (self.r["f"] & 0x10) | 0x40 | (0x80 if self.r["c"] == 0 else 0)
            elif op == 0x37:
                self.r["f"] = (self.r["f"] & 0x80) | 0x10
            elif op in (0x20, 0x28):
                offset = self.fetch()
                take = bool(self.r["f"] & 0x80) == (op == 0x28)
                if take:
                    self.pc += offset if offset < 128 else offset - 256
            elif op in (0x47, 0x78):
                dst, src = ("b", "a") if op == 0x47 else ("a", "b")
                self.r[dst] = self.r[src]
            elif op == 0xc9:
                self.pc = self.pop()
            else:
                raise AssertionError(f"unsupported opcode {op:02x} at {self.pc - 1:04x}")
        raise AssertionError("trade primitive exceeded instruction bound")


def machine_for(compiled):
    machine = TradeMachine(compiled)
    frame = machine.mailbox + 14
    machine.ram[frame:frame + 16] = b"SLT1\x01" + bytes(range(5, 16))
    return machine, frame


def check_unchanged(machine, before, registers):
    assert {key: machine.r[key] for key in "bcdehl"} == registers
    assert machine.sp == 0xdffe
    assert machine.ram[:0xdff0] == before[:0xdff0]
    assert machine.ram[0xdffe:] == before[0xdffe:]


@pytest.mark.parametrize("bad", (None, 0, 1, 2, 3, 4))
def test_compiled_header_checks_every_magic_and_version_byte(compiled, bad):
    machine, frame = machine_for(compiled)
    if bad is not None:
        machine.ram[frame + bad] ^= 1
    before, registers = bytes(machine.ram), {key: machine.r[key] for key in "bcdehl"}
    machine.run("SlinkTradeCheckHeader")
    assert bool(machine.r["f"] & 0x10) is (bad is not None)
    check_unchanged(machine, before, registers)


@pytest.mark.parametrize("token", (b"\x01\x02\x03\x04", b"\x01\0\0\0", b"\0\x01\0\0", b"\0\0\x01\0", b"\0\0\0\x01", bytes(4)))
@pytest.mark.parametrize("bad", (None, 0, 1, 2, 3))
def test_compiled_token_requires_all_four_equal_and_nonzero(compiled, token, bad):
    machine, frame = machine_for(compiled)
    machine.r["h"], machine.r["l"] = 0xd8, 0x10
    machine.ram[0xd810:0xd814] = token
    machine.ram[frame + 12:frame + 16] = token
    if bad is not None:
        machine.ram[frame + 12 + bad] ^= 1
    before, registers = bytes(machine.ram), {key: machine.r[key] for key in "bcdehl"}
    machine.run("SlinkTradeCheckToken")
    assert bool(machine.r["f"] & 0x10) is (bad is not None or not any(token))
    check_unchanged(machine, before, registers)


def test_compiled_close_only_clears_command_available_and_mask(compiled):
    machine, frame = machine_for(compiled)
    before = bytearray(machine.ram)
    for offset in (5, 10, 11):
        before[frame + offset] = 0
    registers = {key: machine.r[key] for key in "bcdehl"}
    machine.run("SlinkTradeClose")
    check_unchanged(machine, before, registers)
    assert {address for address in machine.written if address < 0xdff0} == {frame + 5, frame + 10, frame + 11}
