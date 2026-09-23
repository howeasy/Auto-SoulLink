"""Assemble the real companion and exercise its emitted code (MODEL, not PHYSICAL)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def rgbds(name):
    suffix = ".exe" if os.name == "nt" else ""
    candidates = [Path(os.environ.get("SLINK_RGBDS_BIN", ".")) / (name + suffix),
                  ROOT / ".cache/build-tools/rgbds-v1.0.3/bin" / (name + suffix)]
    found = shutil.which(name)
    if found:
        candidates.insert(0, Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    pytest.skip("RGBDS compiler required for companion assembly MODEL checks")


def assemble(tmp_path, title, extra=""):
    crystal = title == "crystal"
    include = tmp_path / "engine/slink"
    include.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "patch/gb/slink_abi.inc", include / "slink_abi.inc")
    source = tmp_path / "probe.asm"
    source.write_text(
        ("" if crystal else f"DEF _{title.upper()} EQU 1\n")
        + f"DEF hVBlankCounter EQU ${0xFF9B if crystal else 0xFF9D:04x}\n"
        + f"DEF wVBlankOccurred EQU ${0xCFB3 if crystal else 0xCEEA:04x}\n"
        + f"DEF hROMBank EQU ${0xFF9D if crystal else 0xFF9F:04x}\nDEF rROMB EQU $2000\n"
        + 'CHARMAP "S", $92\nCHARMAP "L", $8b\nCHARMAP "N", $8d\nCHARMAP "K", $8a\n'
        + 'SECTION "Bankswitch", ROM0[$10]\nBankswitch::\n'
        + "ldh [hROMBank], a\nld [rROMB], a\nret\n"
        + f'INCLUDE "patch/gen2/src/slink_mailbox_{"crystal" if crystal else "goldsilver"}.asm"\n'
        + 'INCLUDE "patch/gb/slink_abi.inc"\n'
        + 'INCLUDE "patch/gen2/src/slink.asm"\n' + extra,
        encoding="utf-8")
    obj, rom, sym = (tmp_path / name for name in ("probe.o", "probe.gb", "probe.sym"))
    result = subprocess.run([rgbds("rgbasm"), "-I", str(tmp_path) + "/",
                             "-I", str(ROOT) + "/", "-o", str(obj),
                             str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([rgbds("rgblink"), "-o", str(rom), "-n", str(sym), str(obj)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    symbols = {}
    for line in sym.read_text().splitlines():
        if line and not line.startswith(";"):
            location, name = line.split()
            bank, address = location.split(":")
            symbols[name] = (int(bank, 16), int(address, 16))
    return rom.read_bytes(), symbols


@pytest.fixture(params=["crystal", "gold", "silver"])
def compiled(request, tmp_path):
    return request.param, *assemble(tmp_path, request.param)


def test_real_assembly_preserves_shared_abi(tmp_path):
    expected = {"VERSION": 4, "FRAME_COUNTER": 5, "SFX_REQUEST": 7, "CAPS": 8,
                "PANEL_STATE": 9, "PANEL_PAGE": 10, "PANEL_PAGES": 11,
                "SFX_HOLD": 12, "SFX_HOLD_AT": 13, "TRADE_LEASE": 14}
    checks = [f"ASSERT SLINK_OFS_{key} == {value}" for key, value in expected.items()]
    checks += ["ASSERT SLINK_ABI_VERSION == 3", "ASSERT SLINK_CORE_SIZE == 14",
               "ASSERT SLINK_TRADE_LEASE_SIZE == 16", "ASSERT SLINK_PUBLIC_SIZE == 30",
               "ASSERT SLINK_CAP_SFX == 1", "ASSERT SLINK_CAP_PANEL == 2",
               "ASSERT SLINK_CAP_SFX_NOTIFY == 4"]
    checks += [f"ASSERT SLINK_BEACON_{i} == {value}" for i, value in enumerate(b"SLNK")]
    assemble(tmp_path, "crystal", "\n".join(checks) + "\n")


def test_real_assembly_locations(compiled):
    title, rom, symbols = compiled
    assert symbols["wSlinkMailbox"] == (0, 0xCFD8 if title == "crystal" else 0xC1D9)
    assert symbols["SlinkDelayFrameBridge"] == (0, 0x63)
    assert symbols["SlinkService"] == (0x75 if title == "crystal" else 0x13, 0x4000)
    # Existing RST Bankswitch convention is used, not a new interrupt hook.
    assert rom[0x40:0x43] == bytes(3)


class Machine:
    """Only the emitted skeleton's instruction set; unknown instructions fail closed.

    No timing, interrupts or hardware emulation: this checks byte-level state effects.
    """

    def __init__(self, compiled):
        self.title, self.rom, self.symbols = compiled
        self.r = {"a": 0xD3, "f": 0xB0, "b": 0x82, "c": 0x17,
                  "d": 0xA9, "e": 0x42, "h": 0x91, "l": 0x37}
        self.ram = bytearray(65536)
        self.bank = 7
        self.bank_address = 0xFF9D if self.title == "crystal" else 0xFF9F
        self.ram[self.bank_address] = self.bank
        self.clock = 0xFF9B if self.title == "crystal" else 0xFF9D
        self.mailbox = self.symbols["wSlinkMailbox"][1]
        self.sp = 0xDFFE
        self.pc = 0
        self.written = []

    def read(self, address):
        if address < 0x4000:
            return self.rom[address]
        if address < 0x8000:
            return self.rom[self.bank * 0x4000 + address - 0x4000]
        return self.ram[address]

    def write(self, address, value):
        if address == 0x2000:
            self.bank = value
        else:
            self.ram[address] = value
        self.written.append(address)

    def fetch(self):
        value = self.read(self.pc)
        self.pc += 1
        return value

    def word(self):
        low = self.fetch()
        return low | self.fetch() << 8

    def push(self, value):
        self.sp -= 2
        self.write(self.sp, value & 255)
        self.write(self.sp + 1, value >> 8)

    def pop(self):
        value = self.read(self.sp) | self.read(self.sp + 1) << 8
        self.sp += 2
        return value

    def bridge(self):
        self.push(0xFFFF)
        self.pc = self.symbols["SlinkDelayFrameBridge"][1]
        for _ in range(256):
            if self.pc == 0xFFFF:
                return
            op = self.fetch()
            if op == 0x00:
                pass
            elif op in (0xF5, 0xC5, 0xD5, 0xE5):
                hi, lo = {0xF5: "af", 0xC5: "bc", 0xD5: "de", 0xE5: "hl"}[op]
                self.push(self.r[hi] << 8 | self.r[lo])
            elif op in (0xF1, 0xC1, 0xD1, 0xE1):
                hi, lo = {0xF1: "af", 0xC1: "bc", 0xD1: "de", 0xE1: "hl"}[op]
                value = self.pop()
                self.r[hi], self.r[lo] = value >> 8, value & 255
            elif op == 0x3E:
                self.r["a"] = self.fetch()
            elif op == 0x21:
                value = self.word()
                self.r["h"], self.r["l"] = value >> 8, value & 255
            elif op in (0x77, 0x22):
                hl = self.r["h"] << 8 | self.r["l"]
                self.write(hl, self.r["a"])
                if op == 0x22:
                    hl = (hl + 1) & 65535
                    self.r["h"], self.r["l"] = hl >> 8, hl & 255
            elif op in (0xE0, 0xEA):
                self.write(0xFF00 + self.fetch() if op == 0xE0 else self.word(), self.r["a"])
            elif op in (0xF0, 0xFA):
                self.r["a"] = self.read(0xFF00 + self.fetch() if op == 0xF0 else self.word())
            elif op in (0x47, 0x4F, 0x78):
                dst, src = {0x47: ("b", "a"), 0x4F: ("c", "a"), 0x78: ("a", "b")}[op]
                self.r[dst] = self.r[src]
            elif op == 0xAF:
                self.r["a"], self.r["f"] = 0, 0x80
            elif op in (0x91, 0x81, 0xCE, 0xFE):
                operand = self.fetch() if op in (0xCE, 0xFE) else self.r["c"]
                subtract = op in (0x91, 0xFE)
                value = self.r["a"] + (-operand if subtract else operand)
                if op == 0xCE:
                    value += bool(self.r["f"] & 0x10)
                self.r["f"] = (0x80 if value & 255 == 0 else 0) | (0x10 if value < 0 or value > 255 else 0)
                if op != 0xFE:
                    self.r["a"] = value & 255
            elif op in (0x18, 0x28):
                offset = self.fetch()
                if op == 0x18 or self.r["f"] & 0x80:
                    self.pc += offset if offset < 128 else offset - 256
            elif op in (0xCD, 0xD7):
                address = self.word() if op == 0xCD else 0x10
                self.push(self.pc)
                self.pc = address
            elif op == 0xC9:
                self.pc = self.pop()
            else:
                raise AssertionError(f"unsupported opcode {op:02x} at {self.pc - 1:04x}")
        raise AssertionError("companion did not return in bounded instruction budget")

    def count(self):
        return int.from_bytes(self.ram[self.mailbox + 5:self.mailbox + 7], "little")


def check_first_call(machine):
    base = machine.mailbox
    machine.ram[base:base + 40] = bytes(range(40))
    before = bytes(machine.ram[base:base + 40])
    registers = dict(machine.r)
    machine.ram[machine.clock] = 253
    machine.bridge()
    assert machine.ram[base:base + 5] == b"SLNK\x03"
    assert machine.ram[base + 8] == 0
    assert machine.count() == 0
    assert machine.ram[base + 30:base + 32] == bytes([253, 0xA5])
    assert machine.ram[base + 7] == before[7]
    assert machine.ram[base + 9:base + 30] == before[9:30]
    assert machine.ram[base + 32:base + 39] == before[32:39]
    assert machine.r == {**registers, "a": 1}
    assert machine.bank == 7 and machine.ram[machine.bank_address] == 7
    assert machine.sp == 0xDFFE
    occurred = 0xCFB3 if machine.title == "crystal" else 0xCEEA
    assert machine.ram[occurred] == 1
    allowed = set(range(base, base + 7)) | {base + 8, base + 30, base + 31,
                                            occurred, machine.bank_address, 0x2000}
    assert set(machine.written) <= allowed | set(range(0xDFE0, 0xDFFE))


def test_emitted_bridge_preserves_caller_and_host_fields(compiled):
    check_first_call(Machine(compiled))


def test_emitted_counter_wrap_repeat_and_native_reset(compiled):
    machine = Machine(compiled)
    check_first_call(machine)
    machine.ram[machine.clock] = 2
    machine.bridge()
    assert machine.count() == 5
    machine.bridge()
    assert machine.count() == 5  # two service visits in one frame are not two frames
    machine.ram[machine.mailbox + 5:machine.mailbox + 7] = b"\xff\xff"
    machine.ram[machine.clock] = 3
    machine.bridge()
    assert machine.count() == 0
    machine.ram[machine.mailbox:machine.mailbox + 39] = bytes(39)  # native WRAM0 reset
    machine.ram[machine.clock] = 87
    machine.bridge()
    assert machine.count() == 0
    assert machine.ram[machine.mailbox + 30] == 87


@pytest.mark.parametrize("mutation", ["return_only", "bad_beacon", "bank_restore", "caps", "vblank_flag"])
def test_emitted_negative_controls(compiled, mutation):
    machine = Machine(compiled)
    rom = bytearray(machine.rom)
    bank, address = machine.symbols["SlinkService"]
    start = bank * 0x4000 + address - 0x4000
    if mutation == "return_only":
        rom[start] = 0xC9
    elif mutation == "bad_beacon":
        # ld hl, mailbox; ld a, $53. Change the compiled literal, not the expected value.
        assert rom[start + 3:start + 5] == b"\x3e\x53"
        rom[start + 4] = 0x92
    elif mutation == "caps":
        pattern = bytes([0xAF, 0xEA, (machine.mailbox + 8) & 255, (machine.mailbox + 8) >> 8])
        pos = rom.index(pattern, start)
        rom[pos] = 0x78  # ld a,b instead of xor a: advertise unsupported capability
    elif mutation == "vblank_flag":
        occurred = 0xCFB3 if machine.title == "crystal" else 0xCEEA
        start = machine.symbols["SlinkDelayFrameBridge"][1]
        end = machine.symbols["SlinkDelayFrameBridgeEnd"][1]
        store = bytes([0xEA, occurred & 255, occurred >> 8])
        pos = rom.index(store, start, end)
        rom[pos:pos + 3] = bytes(3)  # omit the displaced flag write, keeping register effects
    else:
        start = machine.symbols["SlinkDelayFrameBridge"][1]
        pos = rom.index(b"\xf1\xd7", start)
        rom[pos + 1] = 0xC9  # fail to restore bank and unwind caller stack
    machine.rom = bytes(rom)
    with pytest.raises(AssertionError):
        check_first_call(machine)
