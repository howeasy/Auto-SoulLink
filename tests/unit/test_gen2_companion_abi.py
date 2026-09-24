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


PANEL_NAMES = ("GetSGBLayout", "ClearBGPalettes", "ClearTilemap", "ByteFill", "PlaceString",
               "WaitBGMap2", "WaitBGMap", "SetDefaultBGPAndOBP", "DelayFrame", "JoyTextDelay",
               "hInMenu", "hBGMapMode", "hJoyDown", "hJoyPressed", "wAttrmap", "wTilemap")
SFX_NAMES = ("CheckSFX", "PlaySFX", "InitSound", "DelayFrames", "wMusicFade", "wAudioEnd")


def native_symbols(title, path=None):
    rows = {}
    path = path or ROOT / "data/gen2" / f"{title}_slink.sym"
    for line in path.read_text().splitlines():
        if line and not line.startswith(";") and ":" in line.split()[0]:
            location, name = line.split()
            bank, address = location.split(":")
            rows[name] = (int(bank, 16), int(address, 16))
    return rows


def assemble(tmp_path, title, extra="", *, panel=False, panel_dir=None, sfx=False):
    crystal = title == "crystal"
    include = tmp_path / "engine/slink"
    include.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "patch/gb/slink_abi.inc", include / "slink_abi.inc")
    panel_source = panel_dir or ROOT / "patch/gen2/src"
    native = native_symbols(title) if panel or sfx else {}
    names = (*PANEL_NAMES,) if panel else ()
    if sfx:
        names += SFX_NAMES
    panel_defs = "".join(
        (f'SECTION "Native {name}", ROM0[${native[name][1]:04x}]\n{name}::\nret\n'
         if name in ("CheckSFX", "PlaySFX", "InitSound", "DelayFrames")
         else f"DEF {name} EQU ${native[name][1]:04x}\n") for name in names)
    prelude = ""
    if panel or sfx:
        repo = ROOT / ".cache/gen2-build" / ("pokecrystal" if crystal else "pokegold")
        prelude = f'INCLUDE "{repo.as_posix()}/includes.asm"\n'
    source = tmp_path / "probe.asm"
    source.write_text(
        ("" if crystal else f"DEF _{title.upper()} EQU 1\n")
        + prelude + panel_defs
        + f"DEF hVBlankCounter EQU ${0xFF9B if crystal else 0xFF9D:04x}\n"
        + f"DEF wVBlankOccurred EQU ${0xCFB3 if crystal else 0xCEEA:04x}\n"
        + f"DEF hROMBank EQU ${0xFF9D if crystal else 0xFF9F:04x}\n"
        + ("" if panel or sfx else 'DEF rROMB EQU $2000\nCHARMAP "S", $92\nCHARMAP "L", $8b\nCHARMAP "N", $8d\nCHARMAP "K", $8a\n')
        + 'SECTION "Bankswitch", ROM0[$10]\nBankswitch::\n'
        + "ldh [hROMBank], a\nld [rROMB], a\nret\n"
        + f'INCLUDE "patch/gen2/src/slink_mailbox_{"crystal" if crystal else "goldsilver"}.asm"\n'
        + 'INCLUDE "patch/gb/slink_abi.inc"\n'
        + (f'INCLUDE "{panel_source.as_posix()}/panel_flags.asm"\n' if panel else "")
        + ("DEF SLINK_SFX_ENABLED EQU 1\n" if sfx else "")
        + 'INCLUDE "patch/gen2/src/slink.asm"\n'
        + (f'INCLUDE "{panel_source.as_posix()}/panel.asm"\n' if panel else "")
        + ('INCLUDE "patch/gen2/src/sfx.asm"\n' if sfx else "") + extra,
        encoding="utf-8")
    obj, rom, sym = (tmp_path / name for name in ("probe.o", "probe.gb", "probe.sym"))
    result = subprocess.run([rgbds("rgbasm"), "-I", str(tmp_path) + "/",
                             *(["-I", str(repo) + "/"] if panel or sfx else []),
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
        self.mailbox_flag_samples = []
        self.clear_vblank_on_mailbox = False
        self.lowest_sp = self.sp

    def read(self, address):
        if address < 0x4000:
            return self.rom[address]
        if address < 0x8000:
            return self.rom[self.bank * 0x4000 + address - 0x4000]
        return self.ram[address]

    def write(self, address, value):
        if self.mailbox <= address < self.mailbox + 39:
            occurred = 0xCFB3 if self.title == "crystal" else 0xCEEA
            self.mailbox_flag_samples.append(self.ram[occurred])
            if self.clear_vblank_on_mailbox and len(self.mailbox_flag_samples) == 1:
                self.ram[occurred] = 0  # model one VBlank servicing the already-armed wait
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
        self.lowest_sp = min(self.lowest_sp, self.sp)
        self.write(self.sp, value & 255)
        self.write(self.sp + 1, value >> 8)

    def pop(self):
        value = self.read(self.sp) | self.read(self.sp + 1) << 8
        self.sp += 2
        return value

    def bridge(self):
        self.run("SlinkDelayFrameBridge")

    def helper(self, address):
        return False

    def run(self, symbol):
        self.push(0xFFFF)
        self.pc = self.symbols[symbol][1]
        for _ in range(10000):
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
            elif op in (0x3E, 0x06, 0x16):
                self.r[{0x3E: "a", 0x06: "b", 0x16: "d"}[op]] = self.fetch()
            elif op in (0x21, 0x01, 0x11):
                value = self.word()
                hi, lo = {0x21: "hl", 0x01: "bc", 0x11: "de"}[op]
                self.r[hi], self.r[lo] = value >> 8, value & 255
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
            elif op in (0x47, 0x4F, 0x78, 0x79, 0x5F):
                dst, src = {0x47: ("b", "a"), 0x4F: ("c", "a"),
                            0x78: ("a", "b"), 0x79: ("a", "c"), 0x5F: ("e", "a")}[op]
                self.r[dst] = self.r[src]
            elif op == 0x5E:
                self.r["e"] = self.read(self.r["h"] << 8 | self.r["l"])
            elif op == 0x19:
                value = (self.r["h"] << 8 | self.r["l"]) + (self.r["d"] << 8 | self.r["e"])
                self.r["h"], self.r["l"] = (value >> 8) & 255, value & 255
                self.r["f"] = (self.r["f"] & 0x80) | (0x10 if value > 65535 else 0)
            elif op == 0xAF:
                self.r["a"], self.r["f"] = 0, 0x80
            elif op == 0xA7:
                self.r["f"] = 0x80 if self.r["a"] == 0 else 0
            elif op == 0xE6:
                self.r["a"] &= self.fetch()
                self.r["f"] = 0x80 if self.r["a"] == 0 else 0
            elif op in (0x3C, 0x05, 0x3D):
                reg, delta = {0x3C: ("a", 1), 0x05: ("b", -1), 0x3D: ("a", -1)}[op]
                self.r[reg] = (self.r[reg] + delta) & 255
                self.r["f"] = (self.r["f"] & 0x10) | (0x80 if self.r[reg] == 0 else 0)
            elif op == 0xB8:
                value = self.r["a"] - self.r["b"]
                self.r["f"] = (0x80 if value == 0 else 0) | (0x10 if value < 0 else 0)
            elif op in (0x91, 0x81, 0xCE, 0xFE):
                operand = self.fetch() if op in (0xCE, 0xFE) else self.r["c"]
                subtract = op in (0x91, 0xFE)
                value = self.r["a"] + (-operand if subtract else operand)
                if op == 0xCE:
                    value += bool(self.r["f"] & 0x10)
                self.r["f"] = (0x80 if value & 255 == 0 else 0) | (0x10 if value < 0 or value > 255 else 0)
                if op != 0xFE:
                    self.r["a"] = value & 255
            elif op in (0x18, 0x28, 0x20, 0x38, 0x30):
                offset = self.fetch()
                take = {0x18: True, 0x28: bool(self.r["f"] & 0x80),
                        0x20: not self.r["f"] & 0x80, 0x38: bool(self.r["f"] & 0x10),
                        0x30: not self.r["f"] & 0x10}[op]
                if take:
                    self.pc += offset if offset < 128 else offset - 256
            elif op in (0xCD, 0xD7):
                address = self.word() if op == 0xCD else 0x10
                if self.helper(address):
                    continue
                self.push(self.pc)
                self.pc = address
            elif op == 0xC3:
                address = self.word()
                if self.helper(address):
                    self.pc = self.pop()  # native tail call returns to this routine's caller
                else:
                    self.pc = address
            elif op == 0xC9:
                self.pc = self.pop()
            elif op == 0xC8:
                if self.r["f"] & 0x80:
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


def test_flag_armed_before_service(compiled):
    machine = Machine(compiled)
    start = machine.symbols["SlinkDelayFrameBridge"][1]
    end = machine.symbols["SlinkDelayFrameBridgeEnd"][1]
    bridge = machine.rom[start:end]
    occurred = 0xCFB3 if machine.title == "crystal" else 0xCEEA
    store = bytes([0x3E, 1, 0xEA, occurred & 255, occurred >> 8])
    assert bridge.index(store) < bridge.index(b"\xcd\x00\x40")
    machine.bridge()
    assert machine.mailbox_flag_samples[0] == 1
    # Return address + eight bridge-local bytes + deepest CALL/RST; no IRQ model.
    assert machine.lowest_sp == 0xDFFE - 12


def test_vblank_during_service_is_not_rearmed(compiled):
    machine = Machine(compiled)
    machine.clear_vblank_on_mailbox = True
    machine.bridge()
    assert machine.mailbox_flag_samples[0] == 1
    occurred = 0xCFB3 if machine.title == "crystal" else 0xCEEA
    assert machine.ram[occurred] == 0


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


@pytest.fixture(params=["crystal", "gold", "silver"])
def compiled_panel(request, tmp_path):
    return request.param, *assemble(tmp_path, request.param, panel=True)


def test_panel_caps_are_enabled_only_with_panel_overlay(compiled_panel):
    machine = Machine(compiled_panel)
    machine.bridge()
    assert machine.ram[machine.mailbox + 8] == 2


class PanelMachine(Machine):
    """Native UI helpers are intercepted; this is sequencing/state MODEL evidence only."""

    def __init__(self, compiled, *, buttons=(1, 1), host=True):
        super().__init__(compiled)
        self.native = native_symbols(self.title)
        self.helpers = {self.native[name][1]: name for name in PANEL_NAMES if name[0].isupper()}
        self.bank = self.symbols["SlinkPanel"][0]
        self.ram[self.bank_address] = self.bank
        self.buttons = buttons
        self.host = host
        self.frames = 0
        self.observed_closed = False
        self.hidden = True  # handler has called FadeToMenu
        self.transferred = False
        self.input_reads = 0
        self.events = []
        self.pages = []
        self.ram[self.address("hInMenu")] = 7
        self.ram[self.mailbox + 9] = 1  # hostile stale state must be explicitly closed

    def address(self, name):
        return self.native[name][1]

    def tick(self, count=1):
        for _ in range(count):
            self.frames += 1
            state = self.ram[self.mailbox + 9]
            if state == 0:
                self.observed_closed = True
            if state == 1 and self.host and self.observed_closed:
                assert self.hidden, "host painted on a visible panel"
                page = self.ram[self.mailbox + 10]
                self.ram[self.address("wTilemap"):self.address("wTilemap") + 360] = bytes([0x80 + page]) * 360
                self.events.append("host_tiles")
                self.ram[self.address("wAttrmap"):self.address("wAttrmap") + 360] = bytes(360)
                self.events.append("host_attrs")
                self.ram[self.mailbox + 11] = 2
                self.ram[self.mailbox + 9] = 2
                self.events.append("host_staged")

    def helper(self, address):
        name = self.helpers.get(address)
        if name is None:
            return False
        self.events.append(name)
        if name == "GetSGBLayout":
            self.tick(4)  # native CGB Diploma ApplyAttrmap waits four LCD frames
        elif name == "ClearBGPalettes":
            self.hidden, self.transferred = True, False
            self.tick(4)
        elif name == "ClearTilemap":
            start = self.address("wTilemap")
            self.ram[start:start + 360] = bytes([0x7F]) * 360
            self.tick(4)
        elif name == "ByteFill":
            start = self.r["h"] << 8 | self.r["l"]
            count = self.r["b"] << 8 | self.r["c"]
            assert start == self.address("wAttrmap") and count == 360
            self.ram[start:start + count] = bytes([self.r["a"]]) * count
        elif name == "PlaceString":
            # Native glyph rendering is outside this model; pointer/content boundary checked.
            src = self.r["d"] << 8 | self.r["e"]
            text = []
            for i in range(32):
                value = self.read(src + i)
                if value == 0x50:
                    break
                text.append(value)
            else:
                raise AssertionError("fallback string has no native terminator")
            dst = self.r["h"] << 8 | self.r["l"]
            assert self.address("wTilemap") <= dst < self.address("wTilemap") + 360
            self.ram[dst:dst + len(text)] = bytes(text)
        elif name == "DelayFrame":
            self.tick()
        elif name in ("WaitBGMap", "WaitBGMap2"):
            assert self.hidden and self.ram[self.mailbox + 9] in (0, 2)
            self.transferred = name == "WaitBGMap2"
            self.tick(8 if self.transferred else 4)
        elif name == "SetDefaultBGPAndOBP":
            assert self.transferred, "palette revealed without CGB attribute+tile transfer"
            assert self.ram[self.mailbox + 9] in (0, 2), "visible fallback still permits host writes"
            self.hidden = False
            self.pages.append(self.ram[self.mailbox + 10])
            self.input_reads = 0
        elif name == "JoyTextDelay":
            assert not self.hidden
            self.input_reads += 1
            key = 0 if self.input_reads == 1 else self.buttons[len(self.pages) - 1]
            self.ram[self.address("hJoyDown")] = key
            self.ram[self.address("hJoyPressed")] = key
            self.r.update(a=0xED, b=0xD2, c=0xF7)  # clobber: caller must read input AFTER call
        else:
            raise AssertionError(f"unexpected helper {name}")
        return True


def check_panel(machine, expected_pages):
    machine.run("SlinkPanel")
    assert machine.pages == expected_pages
    assert machine.ram[machine.mailbox + 9:machine.mailbox + 12] == bytes(3)
    assert machine.ram[machine.address("hInMenu")] == 7
    assert machine.sp == 0xDFFE
    allowed = {machine.mailbox + 9, machine.mailbox + 10, machine.mailbox + 11,
               machine.address("hInMenu"), machine.address("hBGMapMode")}
    assert set(machine.written) <= allowed | set(range(0xDFE0, 0xDFFE))
    if machine.host:
        assert machine.observed_closed
        assert machine.events.count("host_staged") == len(expected_pages)
        for position, name in enumerate(machine.events):
            if name == "host_staged":
                assert machine.events[position - 2:position] == ["host_tiles", "host_attrs"]


def test_compiled_panel_stages_two_pages_then_a_closes(compiled_panel):
    check_panel(PanelMachine(compiled_panel), [0, 1])


@pytest.mark.parametrize("button", [2, 8])
def test_compiled_panel_b_or_start_closes_first_page(compiled_panel, button):
    check_panel(PanelMachine(compiled_panel, buttons=(button,)), [0])


def test_compiled_panel_timeout_closes_lease_before_reveal(compiled_panel):
    machine = PanelMachine(compiled_panel, buttons=(1,), host=False)
    check_panel(machine, [0])
    assert machine.events.count("DelayFrame") == 92  # ninety polls plus release/press
    assert "host_staged" not in machine.events


@pytest.mark.parametrize("mutation", ["no_attrs", "timeout_open", "no_closed"])
def test_compiled_panel_mutations_are_refused(compiled_panel, mutation):
    machine = PanelMachine(compiled_panel, buttons=(1,), host=mutation != "timeout_open")
    rom = bytearray(machine.rom)
    bank, address = machine.symbols["SlinkPanel"]
    start = bank * 0x4000 + address - 0x4000
    if mutation == "no_attrs":
        old = machine.address("WaitBGMap2")
        pos = rom.index(bytes([0xCD, old & 255, old >> 8]), start)
        new = machine.address("WaitBGMap")
        rom[pos + 1:pos + 3] = new.to_bytes(2, "little")
    elif mutation == "timeout_open":
        ready = bank * 0x4000 + machine.symbols["SlinkPanel.ready"][1] - 0x4000
        assert rom[ready - 3] == 0xEA
        rom[ready - 3:ready] = bytes(3)
    else:
        state = machine.mailbox + 9
        pos = rom.index(bytes([0xEA, state & 255, state >> 8]), start)
        rom[pos:pos + 3] = bytes(3)
    machine.rom = bytes(rom)
    with pytest.raises(AssertionError):
        check_panel(machine, [0])


class SfxMachine(Machine):
    """Native audio APIs intercepted: dispatch and state assertions, never audible proof."""

    def __init__(self, compiled, *, busy=False, fade=0):
        super().__init__(compiled)
        self.native = native_symbols(self.title)
        self.busy = busy
        self.ram[self.native["wMusicFade"][1]] = fade
        self.played = []
        self.resets = 0
        self.reset_waits = []

    def helper(self, address):
        if address == self.native["CheckSFX"][1]:
            self.r["a"] = 0xD7
            self.r["f"] = 0x10 if self.busy else 0
        elif address == self.native["PlaySFX"][1]:
            self.played.append(self.r["d"] << 8 | self.r["e"])
        elif address == self.native["InitSound"][1]:
            self.resets += 1
        elif address == self.native["DelayFrames"][1]:
            self.reset_waits.append((dict(self.r), self.state()))
            assert self.r["c"] == 32 and self.state() == (0, 0xFF, 0)
            # Native DelayFrames consumes C and clobbers AF. The bridge promises
            # argument preservation BEFORE this call, not preservation afterward.
            self.r.update(a=0, f=0xC0, c=0)
        else:
            return False
        return True

    def request(self, code):
        self.ram[self.mailbox + 7] = code

    def state(self):
        return tuple(self.ram[self.mailbox + offset] for offset in (7, 12, 13))

    def visit(self):
        before = dict(self.r)
        self.written = []
        self.bridge()
        assert self.r == {**before, "a": 1}, "SFX service changed caller registers/flags"
        assert self.bank == 7 and self.ram[self.bank_address] == 7
        assert self.sp == 0xDFFE
        occurred = 0xCFB3 if self.title == "crystal" else 0xCEEA
        allowed = set(range(self.mailbox, self.mailbox + 9)) | {
            self.mailbox + 12, self.mailbox + 13, self.mailbox + 30, self.mailbox + 31,
            self.bank_address, occurred, 0x2000}
        assert set(self.written) <= allowed | set(range(0xDFD0, 0xDFFE))


@pytest.fixture(params=["crystal", "gold", "silver"])
def compiled_sfx(request, tmp_path):
    return request.param, *assemble(tmp_path, request.param, sfx=True)


@pytest.mark.parametrize("code,sound", [(1, 0x01), (2, 0x19), (3, 0x24), (4, 0x08)])
def test_sfx_compiled_semantic_dispatch_once(compiled_sfx, code, sound):
    machine = SfxMachine(compiled_sfx)
    machine.request(code)
    machine.visit()
    assert machine.played == [sound]
    assert machine.state() == (0, 0, 0)
    assert machine.ram[machine.mailbox + 8] == 5
    machine.visit()
    assert machine.played == [sound]


@pytest.mark.parametrize("busy,fade", [(False, 1), (False, 0x80), (True, 0)])
def test_sfx_compiled_holds_then_consumes_when_free(compiled_sfx, busy, fade):
    machine = SfxMachine(compiled_sfx, busy=busy, fade=fade)
    machine.request(2)
    machine.visit()
    assert machine.state() == (2, 1, 1)
    assert machine.played == []
    machine.busy = False
    machine.ram[machine.native["wMusicFade"][1]] = 0
    machine.visit()
    assert machine.played == [0x19]
    assert machine.state() == (0, 0, 0)


@pytest.mark.parametrize("busy,fade", [(True, 0), (False, 1)])
def test_sfx_compiled_frozen_clock_expires_on_visit_240(compiled_sfx, busy, fade):
    machine = SfxMachine(compiled_sfx, busy=busy, fade=fade)
    machine.request(3)
    for count in range(1, 240):
        machine.visit()
        assert machine.state() == (3, 1, count)
        assert machine.played == []
    machine.visit()
    assert machine.played == [0x24]
    assert machine.state() == (0, 0, 0)
    machine.visit()
    assert machine.played == [0x24]


@pytest.mark.parametrize("age", [239, 240, 255])
def test_sfx_compiled_hold_count_never_wraps(compiled_sfx, age):
    machine = SfxMachine(compiled_sfx, busy=True)
    machine.request(1)
    machine.ram[machine.mailbox + 12:machine.mailbox + 14] = bytes([1, age])
    machine.visit()
    assert machine.state() == (0, 0, 0)
    assert machine.played == [0x01]


@pytest.mark.parametrize("code", [0, 5, 0xFF])
def test_sfx_compiled_invalid_or_cancelled_request_clears_hold(compiled_sfx, code):
    machine = SfxMachine(compiled_sfx)
    machine.ram[machine.mailbox + 12:machine.mailbox + 14] = bytes([1, 31])
    machine.request(code)
    machine.visit()
    assert machine.state() == (0, 0, 0)
    assert machine.played == []


def test_sfx_compiled_reset_drops_reposts_until_native_clear(compiled_sfx):
    machine = SfxMachine(compiled_sfx)
    machine.request(1)
    machine.ram[machine.mailbox + 12:machine.mailbox + 14] = bytes([1, 37])
    machine.r["c"] = 32
    registers = dict(machine.r)
    machine.run("SlinkResetSoundBridge")
    assert machine.resets == 0  # InitSound is called once by native Reset, not this bridge
    assert machine.reset_waits == [(registers, (0, 0xFF, 0))]
    assert machine.r == {**registers, "a": 0, "f": 0xC0, "c": 0} and machine.bank == 7
    assert machine.state() == (0, 0xFF, 0)
    for visit in range(32):
        machine.request(visit % 5)  # includes empty visits: those must retain the latch too
        machine.visit()
        assert machine.state() == (0, 0xFF, 0)
        assert machine.played == []
    machine.ram[machine.mailbox:machine.mailbox + 32] = bytes(32)
    machine.request(4)
    machine.visit()
    assert machine.played == [0x08]


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_panel_and_sfx_compiled_capabilities_combine(tmp_path, title):
    machine = SfxMachine((title, *assemble(tmp_path, title, panel=True, sfx=True)))
    machine.visit()
    assert machine.ram[machine.mailbox + 8] == 7


@pytest.mark.parametrize("mutation", ["mapping", "fade", "busy", "expiry", "reset_latch", "de"])
def test_sfx_compiled_mutants_cannot_pass(compiled_sfx, mutation):
    machine = SfxMachine(compiled_sfx, busy=mutation == "busy", fade=1 if mutation == "fade" else 0)
    rom = bytearray(machine.rom)
    bank, address = machine.symbols["SlinkSfxService"]
    start = bank * 0x4000 + address - 0x4000
    end = bank * 0x4000 + machine.symbols["SlinkSfxServiceEnd"][1] - 0x4000
    if mutation == "mapping":
        table = bank * 0x4000 + machine.symbols["SlinkSfxService.sounds"][1] - 0x4000
        rom[table] = 0x19
    elif mutation == "fade":
        fade_address = machine.native["wMusicFade"][1]
        pos = rom.index(bytes([0xFA, fade_address & 255, fade_address >> 8, 0xA7, 0x20]), start, end)
        rom[pos + 4:pos + 6] = bytes(2)
    elif mutation == "busy":
        check = machine.native["CheckSFX"][1]
        pos = rom.index(bytes([0xCD, check & 255, check >> 8]), start, end)
        rom[pos:pos + 3] = bytes(3)
    elif mutation == "expiry":
        pos = rom.index(bytes([0xFE, 239]), start, end)
        rom[pos + 1] = 255
    elif mutation == "reset_latch":
        pos = rom.index(bytes([0xFE, 0xFF]), start, end)
        rom[pos + 1] = 0xFE
    else:
        pos = rom.index(bytes([0xD5]), start, end)
        rom[pos] = 0
        pos = rom.index(bytes([0xD1]), start, end)
        rom[pos] = 0
    machine.rom = bytes(rom)
    with pytest.raises(AssertionError):
        if mutation == "reset_latch":
            machine.r["c"] = 32
            machine.run("SlinkResetSoundBridge")
            machine.request(1)
            machine.visit()
            assert machine.played == [] and machine.state() == (0, 0xFF, 0)
        elif mutation == "expiry":
            machine.busy = True
            machine.request(1)
            for _ in range(240):
                machine.visit()
            assert machine.played == [0x01] and machine.state() == (0, 0, 0)
        else:
            machine.request(1)
            machine.visit()
            if mutation in ("fade", "busy"):
                assert machine.played == [] and machine.state() == (1, 1, 1)
            else:
                assert machine.played == [0x01] and machine.state() == (0, 0, 0)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_compiled_reset_keeps_admission_prefix_and_hooks_only_wait(tmp_path, title):
    from tools import build_gen2_companion as builder

    repo_name = "pokecrystal" if title == "crystal" else "pokegold"
    pinned = ROOT / ".cache/gen2-build" / repo_name
    original = (pinned / "home/init.asm").read_text()
    checkout = tmp_path / "source"
    (checkout / "home").mkdir(parents=True)
    (checkout / "home/init.asm").write_text(original)
    _, modified = builder._reset_sound_text(checkout, repo_name)
    before = original.split("_Start::", 1)[0]
    after = modified.split("_Start::", 1)[0]
    assert "\tcall InitSound\n" in after
    assert "\tld c, 32\n\tcall SlinkResetSoundBridge\n" in after
    assert after.replace("call SlinkResetSoundBridge", "call DelayFrames") == before
    symbols = native_symbols(title, pinned / f"poke{title}.sym")
    extra = "".join(f"DEF {name} EQU ${symbols[name][1]:04x}\n"
                    for name in ("hMapAnims", "wJoypadDisable", "ClearPalettes", "Init"))
    extra += f'SECTION "Native Reset", ROM0[${symbols["Reset"][1]:04x}]\n' + after
    rom, linked = assemble(tmp_path, title, extra, sfx=True)
    start = linked["Reset"][1]
    clean = (pinned / f"poke{title}.gbc").read_bytes()
    expected = bytes.fromhex("f3cd4e3b" if title == "crystal" else "cd4f3daf")
    assert clean[start:start + 4] == expected
    assert rom[start:start + 4] == clean[start:start + 4]
