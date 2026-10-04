"""Assemble the real companion and exercise its emitted code (MODEL, not PHYSICAL)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def pinned_repo(name):
    """The pinned decomp clone .cache/gen2-build/<name>; an ABSENT clone is the named skip Gen 1's gate
    allows (tests/conftest.py). These MODEL checks assemble against it with rgbasm in a subprocess, where
    a missing include surfaces as assembler text, not an exception the conftest hook could classify."""
    repo = ROOT / ".cache/gen2-build" / name
    if not repo.is_dir():
        pytest.skip(f"{name} not cloned: {repo}")
    return repo


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
PHONE_TARGETS = ("SpecialCallOnlyWhenOutside", "SpecialCallWhereverYouAre", "ElmPhoneCallerScript",
                 "BikeShopPhoneCallerScript", "MomPhoneLectureScript")
PHONE_NAMES = ("wScriptRunning", "wLinkMode", "wPokegearFlags", "wSpecialPhoneCallID", *PHONE_TARGETS,
               # PHONE-NAMES: the staged record, the name buffers and the header hook's natives
               "wUnusedMapBuffer", "wUnusedMapBufferEnd", "wStringBuffer1", "wStringBuffer3",
               "wStringBuffer4", "wStringBuffer5", "wScriptVar", "wNamedObjectIndex", "wCallerContact",
               "GetPokemonName", "PlaceString", "FarCall")
VERSION_NAMES = ("SetUpMenu", "PlaceString", "FarCall", "wTilemap")


def native_symbols(title, path=None):
    rows = {}
    path = path or ROOT / "data/gen2" / f"{title}_slink.sym"
    for line in path.read_text().splitlines():
        if line and not line.startswith(";") and ":" in line.split()[0]:
            location, name = line.split()
            bank, address = location.split(":")
            rows[name] = (int(bank, 16), int(address, 16))
    return rows


def caller_name_stub(title):
    """The native GetCallerName as the builder leaves it: jp + nop, .SlinkTrainer, .NotTrainer."""
    native = native_symbols(title, ROOT / "data/gen2" / f"poke{title}.sym")
    start, not_trainer = native["GetCallerName"][1], native["GetCallerName.NotTrainer"][1]
    return (f'SECTION "Native GetCallerName", ROMX[${start:04x}], BANK[$24]\n'
            "GetCallerName::\n\tjp SlinkPhoneCallerName\n\tnop\n.SlinkTrainer::\n\tret\n"
            f"\tds {not_trainer - start - 5}\n.NotTrainer::\n\tret\n")


def assemble(tmp_path, title, extra="", *, panel=False, panel_dir=None, sfx=False, phone=False, trade=False,
             version=None):
    crystal = title == "crystal"
    include = tmp_path / "engine/slink"
    include.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "patch/gb/slink_abi.inc", include / "slink_abi.inc")
    panel_source = panel_dir or ROOT / "patch/gen2/src"
    native = native_symbols(title) if panel or sfx or phone or version else {}
    names = (*PANEL_NAMES,) if panel else ()
    if sfx:
        names += SFX_NAMES
    if phone:
        names += PHONE_NAMES
    if version:
        names += VERSION_NAMES
    names = tuple(dict.fromkeys(names))
    panel_defs = "".join(
        (f'SECTION "Native {name}", ROMX[${native[name][1]:04x}], BANK[${native[name][0]:x}]\n{name}::\nret\n'
         if name in PHONE_TARGETS else
         f'SECTION "Native {name}", ROM0[${native[name][1]:04x}]\n{name}::\nret\n'
         if name in ("CheckSFX", "PlaySFX", "InitSound", "DelayFrames")
         else f"DEF {name} EQU ${native[name][1]:04x}\n") for name in names)
    prelude = ""
    if panel or sfx or phone or version:
        repo = pinned_repo("pokecrystal" if crystal else "pokegold")
        prelude = f'INCLUDE "{repo.as_posix()}/includes.asm"\n'
    source = tmp_path / "probe.asm"
    source.write_text(
        ("" if crystal else f"DEF _{title.upper()} EQU 1\n")
        + prelude + panel_defs
        + f"DEF hVBlankCounter EQU ${0xFF9B if crystal else 0xFF9D:04x}\n"
        + f"DEF wVBlankOccurred EQU ${0xCFB3 if crystal else 0xCEEA:04x}\n"
        + f"DEF hROMBank EQU ${0xFF9D if crystal else 0xFF9F:04x}\n"
        + ("" if panel or sfx or phone or version else 'DEF rROMB EQU $2000\nCHARMAP "S", $92\nCHARMAP "L", $8b\nCHARMAP "N", $8d\nCHARMAP "K", $8a\n')
        + 'SECTION "Bankswitch", ROM0[$10]\nBankswitch::\n'
        + "ldh [hROMBank], a\nld [rROMB], a\nret\n"
        + f'INCLUDE "patch/gen2/src/slink_mailbox_{"crystal" if crystal else "goldsilver"}.asm"\n'
        + 'INCLUDE "patch/gb/slink_abi.inc"\n'
        + (f'INCLUDE "{panel_source.as_posix()}/panel_flags.asm"\n' if panel else "")
        + ("DEF SLINK_SFX_ENABLED EQU 1\n" if sfx else "")
        + ("DEF SLINK_TRADE_ENABLED EQU 1\n" if trade else "")
        + ('INCLUDE "patch/gen2/src/phone_flags.asm"\n' if phone else "")
        + 'INCLUDE "patch/gen2/src/slink.asm"\n'
        + (f'INCLUDE "{panel_source.as_posix()}/panel.asm"\n' if panel else "")
        + ('INCLUDE "patch/gen2/src/sfx.asm"\n' if sfx else "")
        + ('INCLUDE "patch/gen2/src/phone.asm"\n' + caller_name_stub(title) if phone else "")
        + (f'DEF SLINK_BUILD_VERSION EQUS "{version}"\nINCLUDE "patch/gen2/src/version.asm"\n'
           if version else "")
        + ('SECTION "Trade capability probe", ROMX, BANK[SLINK_SERVICE_BANK]\nSlinkTradeDispatch:: ret\n'
           if trade else "") + extra,
        encoding="utf-8")
    obj, rom, sym = (tmp_path / name for name in ("probe.o", "probe.gb", "probe.sym"))
    result = subprocess.run([rgbds("rgbasm"), "-I", str(tmp_path) + "/",
                             *(["-I", str(repo) + "/"] if panel or sfx or phone or version else []),
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
    trade = {"MAGIC_0": 0x53, "MAGIC_1": 0x4c, "MAGIC_2": 0x54, "MAGIC_3": 0x31,
             "VERSION": 1, "CMD_QUERY": 1, "CMD_OFFER": 2, "CMD_PROMPT": 3,
             "CMD_APPLY": 5, "CMD_DONE": 7, "CMD_RELEASE": 8}
    checks += [f"ASSERT SLINK_TRADE_{key} == {value}" for key, value in trade.items()]
    checks += ["ASSERT SLINK_ABI_VERSION == 3", "ASSERT SLINK_CORE_SIZE == 14",
               "ASSERT SLINK_TRADE_LEASE_SIZE == 16", "ASSERT SLINK_PUBLIC_SIZE == 30",
               "ASSERT SLINK_CAP_SFX == 1", "ASSERT SLINK_CAP_PANEL == 2",
               "ASSERT SLINK_CAP_SFX_NOTIFY == 4", "ASSERT SLINK_CAP_PHONE == 8", "ASSERT SLINK_CAP_TRADE == 16",
               "ASSERT SLINK_OFS_PHONE_REQUEST == 32", "ASSERT SLINK_OFS_PHONE_ARMED == 33"]
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
        self.far_returns = []   # rst FarCall: (caller bank, return pc), resumed at pc 0xFFFE

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

    def run(self, symbol, address=None):
        self.push(0xFFFF)
        self.pc = self.symbols[symbol][1] if address is None else address
        for _ in range(10000):
            if self.pc == 0xFFFF:
                return
            if self.pc == 0xFFFE:
                self.bank, self.pc = self.far_returns.pop()
                self.ram[self.bank_address] = self.bank
                continue
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
            elif op in (0x3E, 0x06, 0x16, 0x0E):
                self.r[{0x3E: "a", 0x06: "b", 0x16: "d", 0x0E: "c"}[op]] = self.fetch()
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
            elif op in (0x47, 0x4F, 0x78, 0x79, 0x5F, 0x54, 0x5D):
                dst, src = {0x47: ("b", "a"), 0x4F: ("c", "a"), 0x54: ("d", "h"), 0x5D: ("e", "l"),
                            0x78: ("a", "b"), 0x79: ("a", "c"), 0x5F: ("e", "a")}[op]
                self.r[dst] = self.r[src]
            elif op in (0x1A, 0x2A):
                pair = "de" if op == 0x1A else "hl"
                address = self.r[pair[0]] << 8 | self.r[pair[1]]
                self.r["a"] = self.read(address)
                if op == 0x2A:
                    address = (address + 1) & 65535
                    self.r["h"], self.r["l"] = address >> 8, address & 255
            elif op == 0x13:
                de = ((self.r["d"] << 8 | self.r["e"]) + 1) & 65535
                self.r["d"], self.r["e"] = de >> 8, de & 255
            elif op == 0xB0:
                self.r["a"] |= self.r["b"]
                self.r["f"] = 0x80 if self.r["a"] == 0 else 0
            elif op == 0x37:
                self.r["f"] = (self.r["f"] & 0x80) | 0x10
            elif op == 0x3F:
                self.r["f"] = (self.r["f"] & 0x90) ^ 0x10
            elif op in (0xD8, 0xD0):
                if bool(self.r["f"] & 0x10) == (op == 0xD8):
                    self.pc = self.pop()
            elif op == 0xCF:
                # home/farcall.asm FarCall_hl: call a:hl, restore the bank, keep bc/de/f
                self.push(0xFFFE)
                self.far_returns.append((self.bank, self.pc))
                self.bank = self.r["a"]
                self.ram[self.bank_address] = self.bank
                self.pc = self.r["h"] << 8 | self.r["l"]
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
            elif op in (0x3C, 0x05, 0x3D, 0x0D):
                reg, delta = {0x3C: ("a", 1), 0x05: ("b", -1), 0x3D: ("a", -1), 0x0D: ("c", -1)}[op]
                self.r[reg] = (self.r[reg] + delta) & 255
                self.r["f"] = (self.r["f"] & 0x10) | (0x80 if self.r[reg] == 0 else 0)
            elif op == 0xB8:
                value = self.r["a"] - self.r["b"]
                self.r["f"] = (0x80 if value == 0 else 0) | (0x10 if value < 0 else 0)
            elif op in (0x91, 0x81, 0xCE, 0xFE, 0xC6):
                operand = self.fetch() if op in (0xCE, 0xFE, 0xC6) else self.r["c"]
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
            elif op in (0xC3, 0xC2, 0xCA, 0xD2, 0xDA):
                address = self.word()
                take = {0xC3: True, 0xC2: not self.r["f"] & 0x80, 0xCA: bool(self.r["f"] & 0x80),
                        0xD2: not self.r["f"] & 0x10, 0xDA: bool(self.r["f"] & 0x10)}[op]
                if take:
                    if self.helper(address):
                        self.pc = self.pop()  # native tail call returns to this routine's caller
                    else:
                        self.pc = address
            elif op == 0xC9:
                self.pc = self.pop()
            elif op == 0xC8:
                if self.r["f"] & 0x80:
                    self.pc = self.pop()
            elif op == 0xCB:
                ext = self.fetch()
                assert ext == 0x57, f"unsupported CB opcode {ext:02x}"  # BIT 2,A
                self.r["f"] = (self.r["f"] & 0x10) | 0x20 | (0x80 if not self.r["a"] & 4 else 0)
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
    pinned = pinned_repo(repo_name)
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


PHONE_FACTS = ('SECTION "Phone MODEL facts", ROMX, BANK[SLINK_SERVICE_BANK]\n'
               'SlinkPhoneModelFacts::\n'
               'db readmem_command, loadmem_command, ifequal_command, ifnotequal_command, '
               'writetext_command, specialphonecall_command, end_command, SPECIALCALL_ROBBED, SLINK_CAP_PHONE, '
               'callasm_command, TX_RAM\n')


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def compiled_phone(request, tmp_path_factory):
    title = request.param
    return title, *assemble(tmp_path_factory.mktemp("phone-" + title), title, PHONE_FACTS, phone=True, sfx=True)


class PhoneMachine(SfxMachine):
    """+ GetPokemonName (a synthetic 1..10-glyph name per species) and PlaceString, recorded."""

    def __init__(self, compiled):
        super().__init__(compiled)
        self.placed = []
        self.native_paths = []

    @staticmethod
    def species_name(species):
        return bytes(0x80 + (species + i) % 26 for i in range(species % 10 + 1)) + b"\x50"

    def helper(self, address):
        if address == self.native["GetPokemonName"][1]:
            species = self.ram[self.native["wNamedObjectIndex"][1]]
            out = self.native["wStringBuffer1"][1]
            name = self.species_name(species)
            self.ram[out:out + len(name)] = name
            self.r["d"], self.r["e"] = out >> 8, out & 255
            self.r["b"] = self.r["c"] = 0  # native CopyBytes consumes bc
        elif address == self.native["PlaceString"][1]:
            de, text = self.r["d"] << 8 | self.r["e"], bytearray()
            while not text or text[-1] != 0x50:
                text.append(self.read(de + len(text)))
            self.placed.append((self.r["h"] << 8 | self.r["l"], bytes(text)))
        elif address in (self.symbols.get("GetCallerName.SlinkTrainer", (0, -1))[1],
                         self.symbols.get("GetCallerName.NotTrainer", (0, -1))[1]):
            self.native_paths.append(address)
        else:
            return super().helper(address)
        return True


def phone_machine(compiled):
    machine = PhoneMachine(compiled)
    machine.ram[machine.native["wPokegearFlags"][1]] = 4
    machine.ram[0xFF70] = 1  # rWBK / rSVBK, physical WRAM bank 1.
    return machine


def phone_word(machine, value=None):
    address = machine.native["wSpecialPhoneCallID"][1]
    if value is not None:
        machine.ram[address:address + 2] = value.to_bytes(2, "little")
    return int.from_bytes(machine.ram[address:address + 2], "little")


def rom_slice(compiled, symbol, count):
    _, rom, symbols = compiled
    bank, address = symbols[symbol]
    offset = bank * 0x4000 + address - 0x4000 if bank else address
    return rom[offset:offset + count]


def test_phone_compiled_native_story_survives_accepted_request(compiled_phone):
    machine = phone_machine(compiled_phone)
    robbed = rom_slice(compiled_phone, "SlinkPhoneModelFacts", 9)[7]
    phone_word(machine, robbed)
    machine.ram[machine.mailbox + 32] = 1
    machine.bridge()
    assert phone_word(machine) == robbed
    assert machine.ram[machine.mailbox + 32:machine.mailbox + 34] == bytes([0, 1])
    phone_word(machine, 0)
    machine.bridge()
    assert phone_word(machine) == 9


@pytest.mark.parametrize("guard", ["wScriptRunning", "wLinkMode", "card"])
@pytest.mark.parametrize("pending", [9, 1, 0x0109])
def test_phone_compiled_withdraws_only_owned_word(compiled_phone, guard, pending):
    machine = phone_machine(compiled_phone)
    phone_word(machine, pending)
    machine.ram[machine.mailbox + 33] = 2
    if guard == "card":
        machine.ram[machine.native["wPokegearFlags"][1]] = 0
    else:
        machine.ram[machine.native[guard][1]] = 1
    machine.bridge()
    assert phone_word(machine) == (0 if pending & 255 == 9 else pending)
    assert machine.ram[machine.mailbox + 33] == 2


@pytest.mark.parametrize("pending", [0, 9, 0x0100, 0x0109, 3])
def test_phone_compiled_invalid_request_ack_and_foreign_padding(compiled_phone, pending):
    machine = phone_machine(compiled_phone)
    phone_word(machine, pending)
    machine.ram[machine.mailbox + 32] = 7
    machine.bridge()
    assert machine.ram[machine.mailbox + 32:machine.mailbox + 34] == bytes(2)
    assert phone_word(machine) == (0 if pending & 255 == 9 else pending)


def test_phone_compiled_wrong_wram_bank_has_no_phone_writes(compiled_phone, tmp_path):
    title = compiled_phone[0]
    machine = phone_machine((title, *assemble(tmp_path, title, phone=True)))
    machine.bank = machine.symbols["SlinkPhoneService"][0]
    machine.ram[0xFF70] = 5
    machine.ram[machine.mailbox + 32] = 1
    phone_word(machine, 9)
    before = bytes(machine.ram)
    machine.run("SlinkPhoneService")
    assert machine.ram[:0xDFE0] == before[:0xDFE0]
    assert machine.ram[0xDFFE:] == before[0xDFFE:]
    assert set(machine.written) <= {0xDFFC, 0xDFFD}  # only the MODEL call return address


@pytest.mark.parametrize("pending", [0x0100, 0x0102])
def test_phone_compiled_valid_request_preserves_foreign_high_padding(compiled_phone, pending):
    machine = phone_machine(compiled_phone)
    phone_word(machine, pending)
    machine.ram[machine.mailbox + 32] = 2
    machine.bridge()
    assert phone_word(machine) == pending
    assert machine.ram[machine.mailbox + 32:machine.mailbox + 34] == bytes([0, 2])


@pytest.mark.parametrize("pending,armed,posted,want,retained", [
    (9, 0, 0, 0, 0), (10, 0, 0, 0, 0), (255, 0, 0, 0, 0), (9, 7, 0, 0, 0),
    (9, 1, 0, 9, 1), (0x109, 2, 0, 9, 2), (10, 0, 3, 9, 3), (2, 255, 0, 2, 0)])
def test_phone_compiled_scrubs_contaminated_reserved_ids(compiled_phone, pending, armed, posted, want, retained):
    machine = phone_machine(compiled_phone)
    phone_word(machine, pending)
    machine.ram[machine.mailbox + 32:machine.mailbox + 34] = bytes([posted, armed])
    machine.bridge()
    assert phone_word(machine) == want
    assert machine.ram[machine.mailbox + 32:machine.mailbox + 34] == bytes([0, retained])


def test_phone_compiled_tail_calls_sfx_once_without_stack_growth(compiled_phone, tmp_path):
    machine = phone_machine(compiled_phone)
    machine.request(1)
    machine.ram[machine.mailbox + 32] = 1
    registers = dict(machine.r)
    machine.bridge()
    plain = SfxMachine((machine.title, *assemble(tmp_path, machine.title, sfx=True)))
    plain.request(1)
    plain.bridge()
    assert machine.played == plain.played == [1]
    assert machine.lowest_sp == plain.lowest_sp
    assert machine.r == {**registers, "a": 1} and machine.sp == 0xDFFE
    assert machine.ram[machine.mailbox + 8] == 13
    assert plain.ram[plain.mailbox + 8] == 5


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_phone_only_build_advertises_only_phone(tmp_path, title):
    machine = Machine((title, *assemble(tmp_path, title, phone=True)))
    machine.bridge()
    assert machine.ram[machine.mailbox + 8] == 8


def test_phone_table_preserves_all_native_rows_and_banked_script(compiled_phone):
    title, _, symbols = compiled_phone
    row = native_symbols(title, ROOT / "data/gen2" / f"poke{title}.sym")
    repo = pinned_repo("pokecrystal" if title == "crystal" else "pokegold")
    native = (repo / f"poke{title}.gbc").read_bytes()
    bank, address = row["SpecialPhoneCallList"]
    offset = bank * 0x4000 + address - 0x4000
    table = rom_slice(compiled_phone, "SlinkSpecialPhoneCallList", 54)
    assert table[:48] == native[offset:offset + 48]
    assert symbols["SlinkSpecialCallCondition"][0] == 0x24   # PHONE-NAMES F1: sets the header marker
    condition = symbols["SlinkSpecialCallCondition"][1]
    script_bank, script = symbols["SlinkPhoneCallScript"]
    assert table[48:] == condition.to_bytes(2, "little") + bytes([0, script_bank]) + script.to_bytes(2, "little")


def execute_phone_script(machine):
    # Native macro values C/G macros/scripts/events.asm; loadmem does not change
    # wScriptVar (C scripting.asm:1450-1475, G:1356-1381).
    special, end = (0x9C, 0x91) if machine.title == "crystal" else (0x9B, 0x90)
    assert rom_slice((machine.title, machine.rom, machine.symbols), "SlinkPhoneModelFacts", 7) == bytes([0x19, 0x1B, 6, 7, 0x4C, special, end])
    assert rom_slice((machine.title, machine.rom, machine.symbols), "SlinkPhoneModelFacts", 11)[9] == 0x0E
    machine.bank, machine.pc = machine.symbols["SlinkPhoneCallScript"]
    value, text = 0, None
    for _ in range(40):
        op = machine.fetch()
        if op == 0x19:
            value = machine.read(machine.word())
        elif op == 0x0E:  # callasm: a far asm call; the routine leaves its result in wScriptVar
            bank, address = machine.fetch(), machine.word()
            script_bank, script_pc = machine.bank, machine.pc
            machine.bank = bank
            machine.run(None, address)
            machine.bank, machine.pc = script_bank, script_pc
            value = machine.read(machine.native["wScriptVar"][1])
        elif op == 0x1B:
            address = machine.word()
            machine.write(address, machine.fetch())
        elif op in (6, 7):
            expected, target = machine.fetch(), machine.word()
            if (value == expected) == (op == 6):
                machine.pc = target
        elif op == special:
            call = machine.word()
            address = machine.native["wSpecialPhoneCallID"][1]
            machine.write(address, call & 255)
            machine.write(address + 1, call >> 8)
        elif op == 0x4C:
            assert text is None, "script selected more than one text"
            text = machine.word()
        elif op == end:
            assert text is not None
            return text
        else:
            raise AssertionError(f"unmodeled phone script opcode {op:02x}")
    raise AssertionError("phone script exceeded instruction bound")


@pytest.mark.parametrize("armed", [0, 1, 2, 3, 7])
@pytest.mark.parametrize("pending", [9, 2, 0x0109])
def test_phone_script_compiled_delivery_and_native_story_preservation(compiled_phone, armed, pending):
    machine = phone_machine(compiled_phone)
    phone_word(machine, pending)
    machine.ram[machine.mailbox + 32:machine.mailbox + 34] = bytes([3, armed])
    before = bytes(machine.ram)
    text = execute_phone_script(machine)
    expected = {1: "Fallen", 2: "DeadZone", 3: "FirstLink"}.get(armed, "Static")
    assert text == machine.symbols[f"SlinkPhone{expected}Text"][1]
    assert machine.ram[machine.mailbox + 32:machine.mailbox + 34] == bytes([3, 0])
    assert phone_word(machine) == (0 if pending == 9 else pending)
    allowed = {machine.mailbox + 33, machine.native["wScriptVar"][1], *range(0xDF00, 0xE000)}  # + callasm
    if pending == 9:
        allowed.update(range(machine.native["wSpecialPhoneCallID"][1], machine.native["wSpecialPhoneCallID"][1] + 2))
    assert {index for index, (old, new) in enumerate(zip(before, machine.ram, strict=True)) if old != new} <= allowed


def phone_text_widths(compiled, name, symbols=None):
    """Tiles per line. TX_START strings and TX_RAM (PHONE-NAMES: the trainer buffer 7 tiles, a mon
    name buffer 10); any other text command fails."""
    data = rom_slice(compiled, name, 512)
    ram = {} if symbols is None else {symbols["wStringBuffer5"][1]: 7, symbols["wStringBuffer3"][1]: 10,
                                      symbols["wStringBuffer4"][1]: 10}
    widths, width, pos = [], 0, 0
    while pos < len(data):
        command, pos = data[pos], pos + 1
        if command == 0x01:
            address, pos = data[pos] | data[pos + 1] << 8, pos + 2
            assert address in ram, f"TX_RAM from an unmodelled buffer {address:04x}"
            width += ram[address]
            continue
        assert command == 0, f"unexpected text command {command:02x}"
        for byte in data[pos:]:
            pos += 1
            if byte == 0x50:
                break  # end of this TX_START string; the next text command follows
            if byte in (0x4E, 0x4F, 0x51, 0x55, 0x57):
                widths.append(width)
                width = 0
                if byte == 0x57:
                    return widths
            elif byte == 0x52:
                width += 7  # native <PLAYER>, maximum name without its terminator
            elif byte == 0x54:
                width += 4  # native # -> POKé
            else:
                assert byte >= 0x60, f"unexpected text command/substitution {byte:02x}"
                width += 1  # every encoded glyph, including apostrophe ligatures, is one tile
    raise AssertionError("text has no bounded native DONE terminator")


def test_phone_compiled_text_widths_fit_native_box(compiled_phone):
    native = native_symbols(compiled_phone[0])
    for name in ("Fallen", "DeadZone", "FirstLink", "Static", "NamedFallen", "NamedFirstLink"):
        widths = phone_text_widths(compiled_phone, f"SlinkPhone{name}Text", native)
        assert widths and all(0 < width <= 18 for width in widths), (name, widths)


def test_phone_named_text_width_parser_catches_an_unknown_ram_buffer(compiled_phone):
    native = native_symbols(compiled_phone[0])
    title, rom, symbols = compiled_phone
    rom = bytearray(rom)
    bank, address = symbols["SlinkPhoneNamedFallenText"]
    start = bank * 0x4000 + address - 0x4000
    assert rom[start] == 0x01
    rom[start + 1] ^= 1   # TX_RAM from wStringBuffer5 +- 1: no longer a bounded name buffer
    with pytest.raises(AssertionError, match="TX_RAM"):
        phone_text_widths((title, bytes(rom), symbols), "SlinkPhoneNamedFallenText", native)


# -- PHONE-NAMES: the staged record, the named texts and the caller-name header -----------------

TRAINER = bytes([0x81, 0x8E, 0x81]) + b"\x50" * 5          # "BOB"
NICK = bytes([0x8F, 0x88, 0x83, 0x86, 0x84]) + b"\x50" * 6  # "PIDGE"
HEADER, NONCE, ARMED_NONCE = 34, 35, 36   # phone.asm SLINK_OFS_PHONE_HEADER / _NONCE / _ARMED_NONCE


def record(event, caller=16, receiver=19, trainer=TRAINER, nick=NICK, nonce=7, cookie=0xA6):
    return bytes([event, caller, receiver]) + trainer + nick + bytes([nonce, cookie])


def stage(machine, data):
    base = machine.native["wUnusedMapBuffer"][1]
    assert machine.native["wUnusedMapBufferEnd"][1] - base == len(data) == 24
    machine.ram[base:base + 24] = data


def arm(machine, event, nonce=7):
    """The service accepted request `event` with the host's nonce (ARMED, the ROM's copy of the nonce)."""
    machine.ram[machine.mailbox + 33] = event
    machine.ram[machine.mailbox + ARMED_NONCE] = nonce


def ring(machine):
    """The ninth special-call row's condition: the SLink call is starting (sets the header marker)."""
    machine.bank = 0x24
    machine.r["f"] = 0
    machine.run("SlinkSpecialCallCondition")
    assert machine.r["f"] & 0x10, "the condition must let the call ring (carry)"


def string_at(machine, name):
    address = machine.native[name][1]
    return bytes(machine.ram[address:machine.ram.index(0x50, address) + 1])


@pytest.mark.parametrize("armed,named", [(1, "NamedFallen"), (3, "NamedFirstLink")])
@pytest.mark.parametrize("nick", [NICK, b"\x50" * 11])
def test_phone_named_call_stages_the_names(compiled_phone, armed, named, nick):
    machine = phone_machine(compiled_phone)
    arm(machine, armed)
    ring(machine)
    stage(machine, record(armed, nick=nick))
    before = bytes(machine.ram)
    assert execute_phone_script(machine) == machine.symbols[f"SlinkPhone{named}Text"][1]
    assert machine.ram[machine.mailbox + 33] == 0 and machine.ram[machine.mailbox + HEADER] == 0
    assert string_at(machine, "wStringBuffer5") == b"\x81\x8e\x81\x50"
    assert string_at(machine, "wStringBuffer3") == (NICK[:6] if nick == NICK else PhoneMachine.species_name(16))
    assert string_at(machine, "wStringBuffer4") == PhoneMachine.species_name(19)
    cookie = machine.native["wUnusedMapBuffer"][1] + 23
    assert machine.ram[cookie] == 0, "a record is single-use: the ROM zeroes its cookie"
    buffers = set()
    for name in ("wStringBuffer1", "wStringBuffer3", "wStringBuffer4", "wStringBuffer5"):
        buffers.update(range(machine.native[name][1], machine.native[name][1] + 19))
    allowed = buffers | {machine.mailbox + 33, machine.mailbox + HEADER, cookie, machine.native["wScriptVar"][1],
                         machine.native["wNamedObjectIndex"][1], *range(0xDF00, 0xE000)}
    assert {i for i, (old, new) in enumerate(zip(before, machine.ram, strict=True)) if old != new} <= allowed


BAD_RECORDS = {
    "cookie": dict(cookie=0xA5), "nonce": dict(nonce=8), "caller_species0": dict(caller=0),
    "receiver_species252": dict(receiver=252), "empty_trainer": dict(trainer=b"\x50" * 8),
    "trainer_unterminated": dict(trainer=bytes([0x81] * 8)), "trainer_control": dict(trainer=b"\x52" + b"\x50" * 7),
    "nick_unterminated": dict(nick=bytes([0x8F] * 11)), "nick_control": dict(nick=b"\x81\x4f" + b"\x50" * 9),
}


@pytest.mark.parametrize("fault", [*BAD_RECORDS, "event", "wiped", "bare_post"])
@pytest.mark.parametrize("armed", [1, 3])
def test_phone_invalid_record_keeps_the_fixed_text(compiled_phone, fault, armed):
    machine = phone_machine(compiled_phone)
    arm(machine, armed, nonce=0 if fault == "bare_post" else 7)
    ring(machine)
    stage(machine, bytes(24) if fault == "wiped" else record(4 - armed if fault == "event" else armed,
                                                            **BAD_RECORDS.get(fault, {})))
    fixed = {1: "Fallen", 3: "FirstLink"}[armed]
    assert execute_phone_script(machine) == machine.symbols[f"SlinkPhone{fixed}Text"][1]


def test_phone_an_old_record_and_a_bare_post_ring_the_fixed_text(compiled_phone):
    """F2: a valid record from an earlier request (even the old reserved-0 layout) is never reused by a
    request that carried no nonce (a names=nil host): the service moves the host nonce, 0 here."""
    machine = phone_machine(compiled_phone)
    for nonce in (7, 0):
        stage(machine, record(1, nonce=nonce))
        machine.ram[machine.mailbox + 32] = 1        # a bare post: +35 NONCE never written
        machine.bridge()
        assert machine.ram[machine.mailbox + 33] == 1 and machine.ram[machine.mailbox + ARMED_NONCE] == 0
        ring(machine)
        assert execute_phone_script(machine) == machine.symbols["SlinkPhoneFallenText"][1]


def test_phone_service_moves_the_host_nonce_at_ack(compiled_phone):
    machine = phone_machine(compiled_phone)
    machine.ram[machine.mailbox + NONCE] = 9
    machine.ram[machine.mailbox + 32] = 3
    machine.bridge()
    assert machine.ram[machine.mailbox + 32:machine.mailbox + 37] == bytes([0, 3, 0, 0, 9])


def test_phone_dead_zone_keeps_its_body_with_a_valid_record(compiled_phone):
    machine = phone_machine(compiled_phone)
    arm(machine, 2)
    ring(machine)
    stage(machine, record(2))
    assert execute_phone_script(machine) == machine.symbols["SlinkPhoneDeadZoneText"][1]
    assert machine.ram[machine.native["wUnusedMapBuffer"][1] + 23] == 0


def caller_header(machine, *, contact=0, trainer_class=0, script=None):
    """Run the bank-$24 GetCallerName hook as Phone_TextboxWithName (or a Pokegear row) calls it."""
    bank, address = script or machine.symbols["SlinkPhoneCallScript"]
    at = machine.native["wCallerContact"][1] + 9  # PHONE_CONTACT_SCRIPT2_BANK
    machine.ram[at:at + 3] = bytes([bank, address & 255, address >> 8])
    machine.r.update(b=contact, c=trainer_class, h=0xC4, l=0xB7)
    machine.bank = 0x24
    machine.run("SlinkPhoneCallerName")
    assert machine.bank == 0x24 and machine.sp == 0xDFFE


@pytest.mark.parametrize("armed", [1, 2, 3])
def test_phone_header_names_the_partner_without_a_colon(compiled_phone, armed):
    machine = phone_machine(compiled_phone)
    arm(machine, armed)
    ring(machine)
    assert machine.ram[machine.mailbox + HEADER] == armed
    stage(machine, record(armed))
    caller_header(machine)
    assert machine.placed == [(0xC4B7, b"\x81\x8e\x81\x50")] and machine.native_paths == []


def test_phone_pokegear_empty_row_after_a_named_call_shows_dashes(compiled_phone):
    """F1: Pokegear draws an empty PHONE_00 row through GetCallerClassAndName. After a delivered named call
    (wCallerContact still points at SlinkPhoneCallScript) and a second call that is ARMED but never rang,
    the row is native "----------", even with a valid record for the armed call."""
    machine = phone_machine(compiled_phone)
    arm(machine, 1)
    ring(machine)
    stage(machine, record(1))
    execute_phone_script(machine)                 # call 1 rang and was delivered
    arm(machine, 3, nonce=8)                      # call 2: accepted, withdrawn (never rang)
    stage(machine, record(3, nonce=8))
    machine.placed.clear()
    caller_header(machine)                        # the stale pointer is still resident
    assert machine.placed == [] and machine.native_paths == [machine.symbols["GetCallerName.NotTrainer"][1]]


def test_phone_service_clears_the_header_marker_when_nothing_is_armed(compiled_phone):
    machine = phone_machine(compiled_phone)
    machine.ram[machine.mailbox + HEADER] = 1
    machine.bridge()
    assert machine.ram[machine.mailbox + HEADER] == 0


@pytest.mark.parametrize("fault", ["trainer_class", "contact", "script", "armed", "record", "late_record",
                                   "no_ring", "other_call"])
def test_phone_header_is_native_for_anything_else(compiled_phone, fault):
    machine = phone_machine(compiled_phone)
    arm(machine, 1)
    if fault != "no_ring":
        ring(machine)
    if fault == "armed":
        machine.ram[machine.mailbox + 33] = 0
    if fault == "other_call":
        machine.ram[machine.mailbox + HEADER] = 2   # the marker names another call than the ARMED one
    # late_record: the check fails at the nickname, after it has used b and c (FarCall returns the callee's bc)
    stage(machine, record(1, cookie=0 if fault == "record" else 0xA6,
                          nick=bytes([0x8F] * 11) if fault == "late_record" else NICK))
    bank, address = machine.symbols["SlinkPhoneCallScript"]
    caller_header(machine, contact=int(fault == "contact"), trainer_class=int(fault == "trainer_class"),
                  script=(bank, address + 1) if fault == "script" else None)
    trainer, not_trainer = (machine.symbols[f"GetCallerName.{n}"][1] for n in ("SlinkTrainer", "NotTrainer"))
    assert machine.placed == []
    assert machine.native_paths == [trainer if fault == "trainer_class" else not_trainer]
    assert (machine.r["b"], machine.r["c"], machine.r["h"], machine.r["l"]) == (
        int(fault == "contact"), int(fault == "trainer_class"), 0xC4, 0xB7)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_version_prints_before_the_native_menu(tmp_path, title):
    machine = PhoneMachine((title, *assemble(tmp_path, title, version="v1.2.3", phone=True)))
    setup, place = machine.native["SetUpMenu"][1], machine.native["PlaceString"][1]
    order, helper = [], machine.helper
    machine.helper = lambda a: (order.append(a) if a in (setup, place) else None) or helper(a) or a == setup
    machine.run("SlinkMainMenuBridge")
    assert order == [place, setup]
    tilemap = machine.native["wTilemap"][1]
    [(coord, text)] = machine.placed
    assert coord == tilemap + 10 * 20 + 1
    charmap = {c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 0x80)}
    charmap |= {c: i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz", 0xA0)}
    assert text == bytes([*(charmap[c] for c in "SoulLink"), 0x7F, 0xB5, 0xF7, 0xE8, 0xF8, 0xE8, 0xF9, 0x50])
    assert machine.bank == 7 and machine.sp == 0xDFFE


@pytest.mark.parametrize("mutation", ["native_call", "wram_bank", "invalid_request", "script_armed", "text_width"])
def test_phone_compiled_mutations_are_detected(compiled_phone, mutation):
    machine = phone_machine(compiled_phone)
    rom = bytearray(machine.rom)
    bank, address = machine.symbols["SlinkPhoneService"]
    start = bank * 0x4000 + address - 0x4000
    end = bank * 0x4000 + machine.symbols["SlinkPhoneServiceEnd"][1] - 0x4000
    if mutation == "native_call":
        address = machine.native["wSpecialPhoneCallID"][1]
        pos = rom.index(bytes([0xFA, address & 255, address >> 8, 0xA7, 0x20]), start, end)
        rom[pos + 4:pos + 6] = bytes(2)
        phone_word(machine, 1)
        machine.ram[machine.mailbox + 32] = 1
    elif mutation in ("wram_bank", "invalid_request"):
        pos = (rom.index(bytes([0xFE, 2]), start, end) if mutation == "wram_bank"
               else rom.index(bytes([0x78, 0xFE, 4]), start, end) + 1)
        rom[pos + 1] = 8
        machine.ram[machine.mailbox + 32] = 1 if mutation == "wram_bank" else 7
        if mutation == "wram_bank":
            machine.ram[0xFF70] = 5
    elif mutation == "script_armed":
        bank, address = machine.symbols["SlinkPhoneCallScript"]
        start = bank * 0x4000 + address - 0x4000
        target = machine.mailbox + 33
        pos = rom.index(bytes([0x1B, target & 255, target >> 8, 0]), start)
        rom[pos + 1:pos + 3] = (target - 1).to_bytes(2, "little")
        machine.ram[machine.mailbox + 33] = 1
    else:
        bank, address = machine.symbols["SlinkPhoneFirstLinkText"]
        start = bank * 0x4000 + address - 0x4000
        rom[start + 1] = 0x52  # a second maximum PLAYER substitution overflows the first line
    machine.rom = bytes(rom)
    with pytest.raises(AssertionError):
        if mutation == "script_armed":
            execute_phone_script(machine)
            assert machine.ram[machine.mailbox + 33] == 0
        elif mutation == "text_width":
            assert max(phone_text_widths((machine.title, machine.rom, machine.symbols), "SlinkPhoneFirstLinkText")) <= 18
        else:
            machine.bridge()
            if mutation == "native_call":
                assert phone_word(machine) == 1
            elif mutation == "wram_bank":
                assert machine.ram[machine.mailbox + 32] == 1
            else:
                assert machine.ram[machine.mailbox + 33] == 0


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
@pytest.mark.parametrize("trade", [False, True])
@pytest.mark.parametrize("other_features", [False, True])
def test_trade_capability_requires_build_flag(tmp_path, title, trade, other_features):
    # Only the advertisement is isolated here; the real dispatcher/FSM runs
    # in test_gen2_trade_service rather than being claimed from this RET spy.
    compiled = (title, *assemble(tmp_path, title, trade=trade, panel=other_features,
                                phone=other_features, sfx=other_features))
    machine = SfxMachine(compiled) if other_features else Machine(compiled)
    machine.bridge()
    assert machine.ram[machine.mailbox + 8] == (15 if other_features else 0) | (16 if trade else 0)


@pytest.mark.parametrize("mutation", ["cookie", "species_bound", "header_script", "header_gate"])
def test_phone_names_mutations_are_detected(compiled_phone, mutation):
    title, rom, symbols = compiled_phone
    rom = bytearray(rom)

    def find(symbol, pattern):
        bank, address = symbols[symbol]
        start = bank * 0x4000 + address - 0x4000
        return rom.index(pattern, start, start + 256)

    if mutation == "cookie":
        rom[find("SlinkPhoneCheckRecord", bytes([0xFE, 0xA6])) + 1] = 0xA5
    elif mutation == "species_bound":
        rom[find("SlinkPhonePrepareCall", bytes([0xFE, 252])) + 1] = 253
    elif mutation == "header_script":
        high = symbols["SlinkPhoneCallScript"][1] >> 8
        rom[find("SlinkPhoneCallerNameService", bytes([0xFE, high])) + 1] ^= 1
    else:
        rom[find("SlinkPhoneCallerName", bytes([0x79, 0xB0])) + 1] = 0xA7  # or b -> and a: any contact
    with pytest.raises(AssertionError):
        if mutation == "cookie":
            test_phone_named_call_stages_the_names((title, bytes(rom), symbols), 1, "NamedFallen", NICK)
        elif mutation == "species_bound":
            test_phone_invalid_record_keeps_the_fixed_text((title, bytes(rom), symbols), "receiver_species252", 1)
        elif mutation == "header_script":
            test_phone_header_names_the_partner_without_a_colon((title, bytes(rom), symbols), 1)
        else:
            test_phone_header_is_native_for_anything_else((title, bytes(rom), symbols), "contact")
