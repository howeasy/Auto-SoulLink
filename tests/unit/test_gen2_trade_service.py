"""RGBDS-compiled lease FSM with native call spies: MODEL, never physical proof."""

import re
import shutil
import subprocess

import pytest

from tests.unit.test_gen2_companion_abi import ROOT, Machine, native_symbols, rgbds


class Symbols(dict):
    pass


def assemble_trade(tmp_path, title, source_files=None, stub_names=None):
    if source_files is None:
        source_files = [f"trade_{name}.asm" for name in ("frame", "items", "snapshot", "service", "dispatch")]
    if stub_names is None:
        stub_names = ("SlinkTradeCommit",)
    pinned = ROOT / ".cache/gen2-build" / ("pokecrystal" if title == "crystal" else "pokegold")
    native = native_symbols(title, ROOT / "data/gen2" / f"poke{title}.sym")
    paths = [ROOT / "patch/gen2/src" / name for name in source_files]
    source_text = "\n".join(path.read_text() for path in paths)
    references = set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", source_text)) & set(native)
    references |= {"FarCall", "Predef"}
    predefs = set(re.findall(r"\bpredef(?:_jump)?\s+(\w+)", source_text))
    definitions = []
    calls = {}
    for name in sorted(references):
        bank, address = native[name]
        if address < 0x8000:
            calls.setdefault((bank, address), []).append(name)
        else:
            definitions.append(f"DEF {name} EQU ${address:04x}")
    for (bank, address), names in calls.items():
        section = f'ROMX[${address:04x}], BANK[${bank:x}]' if bank else f'ROM0[${address:04x}]'
        definitions.append(f'SECTION "Native {names[0]}", {section}\n' + "\n".join(name + "::" for name in names) + "\nret")
    predef_ids = {}
    if predefs:
        definitions.append(f'DEF PredefPointers EQU ${native["PredefPointers"][1]:04x}')
        for name in sorted(predefs):
            address = native[name + "Predef"][1]
            definitions.append(f"DEF {name}Predef EQU ${address:04x}")
            predef_ids[(address - native["PredefPointers"][1]) // 3] = name
    includes = tmp_path / "engine/slink"
    includes.mkdir(parents=True)
    shutil.copyfile(ROOT / "patch/gb/slink_abi.inc", includes / "slink_abi.inc")
    bank, mailbox, size = (0x75, 0xCFD8, 40) if title == "crystal" else (0x13, 0xC1D9, 39)
    text = ("" if title == "crystal" else f"DEF _{title.upper()} EQU 1\n")
    text += f'INCLUDE "{pinned.as_posix()}/includes.asm"\n'
    text += "\n".join(definitions) + "\n"
    text += f'DEF SLINK_SERVICE_BANK EQU ${bank:x}\nSECTION "Mailbox", WRAM0[${mailbox:04x}]\nwSlinkMailbox:: ds {size}\n'
    text += 'INCLUDE "engine/slink/slink_abi.inc"\n'
    text += "".join(f'INCLUDE "{path.as_posix()}"\n' for path in paths)
    for name in stub_names:
        text += f'SECTION "Spy {name}", ROMX, BANK[SLINK_SERVICE_BANK]\n{name}:: ret\n'
    probe, obj, rom, sym = (tmp_path / name for name in ("trade.asm", "trade.o", "trade.gb", "trade.sym"))
    probe.write_text(text)
    result = subprocess.run([rgbds("rgbasm"), "-I", str(tmp_path) + "/", "-I", str(pinned) + "/",
                             "-o", str(obj), str(probe)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([rgbds("rgblink"), "-o", str(rom), "-n", str(sym), str(obj)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    symbols = Symbols(native)
    symbols.update(native_symbols(title, sym))
    symbols.native_calls = {location: names[0] for location, names in calls.items()}
    for name in stub_names:
        symbols.native_calls[symbols[name]] = name
    symbols.predefs = predef_ids
    return title, rom.read_bytes(), symbols


class TradeMachine(Machine):
    """Bounded LR35902 subset for these assembled helpers; unmodeled calls/opcodes fail."""

    def address(self, name):
        return self.symbols[name][1]

    def pair(self, name):
        return self.sp if name == "sp" else self.r[name[0]] << 8 | self.r[name[1]]

    def set_pair(self, name, value):
        value &= 65535
        if name == "sp":
            self.sp = value
        else:
            self.r[name[0]], self.r[name[1]] = value >> 8, value & 255

    def reg(self, number, value=None):
        name = "bcdehl_a"[number]
        if value is None:
            return self.read(self.pair("hl")) if name == "_" else self.r[name]
        if name == "_":
            self.write(self.pair("hl"), value & 255)
        else:
            self.r[name] = value & 255

    def native_call(self, name):
        return False

    def invoke(self, address, bank=None):
        bank = (0 if address < 0x4000 else self.bank) if bank is None else bank
        name = self.symbols.native_calls.get((bank, address))
        if name == "FarCall":
            return self.invoke(self.pair("hl"), self.r["a"])
        if name == "Predef":
            name = self.symbols.predefs[self.r["a"]]
        self.push(self.pc)
        if name:
            if not self.native_call(name):
                raise AssertionError(f"unmodeled native call: {name}")
            self.pc = self.pop()
        else:
            assert bank == self.bank or bank == 0, "unmodeled ROM bank switch"
            self.pc = address

    def condition(self, index):
        return (not self.r["f"] & 0x80, bool(self.r["f"] & 0x80),
                not self.r["f"] & 0x10, bool(self.r["f"] & 0x10))[index]

    def run(self, symbol, budget=200000):
        old_pc, old_bank = self.pc, self.bank
        self.bank, self.pc = self.symbols[symbol]
        self.push(0xFFFF)
        for _ in range(budget):
            if self.pc == 0xFFFF:
                self.pc, self.bank = old_pc, old_bank
                return
            op = self.fetch()
            if op == 0:
                continue
            if 0x40 <= op <= 0x7F and op != 0x76:
                self.reg((op >> 3) & 7, self.reg(op & 7))
            elif op & 0xC7 == 0x06:
                self.reg((op >> 3) & 7, self.fetch())
            elif op in (0x01, 0x11, 0x21, 0x31):
                self.set_pair(("bc", "de", "hl", "sp")[op >> 4], self.word())
            elif op in (0x03, 0x13, 0x23, 0x33, 0x0B, 0x1B, 0x2B, 0x3B):
                pair = ("bc", "de", "hl", "sp")[op >> 4]
                self.set_pair(pair, self.pair(pair) + (1 if op & 8 == 0 else -1))
            elif op in (0x09, 0x19, 0x29, 0x39):
                left, right = self.pair("hl"), self.pair(("bc", "de", "hl", "sp")[op >> 4])
                self.set_pair("hl", left + right)
                self.r["f"] = self.r["f"] & 0x80 | (0x10 if left + right > 65535 else 0) | (0x20 if (left & 4095) + (right & 4095) > 4095 else 0)
            elif op & 0xC7 in (0x04, 0x05):
                reg = (op >> 3) & 7
                old, dec = self.reg(reg), bool(op & 1)
                value = (old + (-1 if dec else 1)) & 255
                self.reg(reg, value)
                self.r["f"] = self.r["f"] & 0x10 | (0x80 if value == 0 else 0) | (0x40 if dec else 0) | (0x20 if (old & 15) == (0 if dec else 15) else 0)
            elif op in (0x02, 0x12, 0x0A, 0x1A):
                address = self.pair("de" if op & 0x10 else "bc")
                if op & 8:
                    self.r["a"] = self.read(address)
                else:
                    self.write(address, self.r["a"])
            elif op in (0x22, 0x2A, 0x32, 0x3A):
                address = self.pair("hl")
                if op & 8:
                    self.r["a"] = self.read(address)
                else:
                    self.write(address, self.r["a"])
                self.set_pair("hl", address + (-1 if op & 0x10 else 1))
            elif op in (0xEA, 0xFA, 0xE0, 0xF0):
                address = self.word() if op & 0x0F else 0xFF00 + self.fetch()
                if op & 0x10:
                    self.r["a"] = self.read(address)
                else:
                    self.write(address, self.r["a"])
            elif 0x80 <= op <= 0xBF or op in (0xC6, 0xCE, 0xD6, 0xDE, 0xE6, 0xEE, 0xF6, 0xFE):
                operand = self.reg(op & 7) if op < 0xC0 else self.fetch()
                kind = (op >> 3) & 7
                a, carry = self.r["a"], bool(self.r["f"] & 0x10)
                if kind in (0, 1, 2, 3, 7):
                    sub = kind in (2, 3, 7)
                    extra = carry if kind in (1, 3) else 0
                    value = a + (-operand - extra if sub else operand + extra)
                    half = (a & 15) < (operand & 15) + extra if sub else (a & 15) + (operand & 15) + extra > 15
                    flags = (0x40 if sub else 0) | (0x20 if half else 0) | (0x10 if not 0 <= value <= 255 else 0)
                else:
                    value = (a & operand) if kind == 4 else (a ^ operand) if kind == 5 else (a | operand)
                    flags = 0x20 if kind == 4 else 0
                self.r["f"] = flags | (0x80 if value & 255 == 0 else 0)
                if kind != 7:
                    self.r["a"] = value & 255
            elif op in (0xC5, 0xD5, 0xE5, 0xF5, 0xC1, 0xD1, 0xE1, 0xF1):
                pair = ("bc", "de", "hl", "af")[(op >> 4) - 12]
                if op & 4:
                    self.push(self.pair(pair))
                else:
                    self.set_pair(pair, self.pop())
                    self.r["f"] &= 0xF0
            elif op in (0xE8, 0xF8):
                raw = self.fetch()
                value = self.sp + (raw if raw < 128 else raw - 256)
                self.r["f"] = (0x20 if (self.sp & 15) + (raw & 15) > 15 else 0) | (0x10 if (self.sp & 255) + raw > 255 else 0)
                self.set_pair("sp" if op == 0xE8 else "hl", value)
            elif op == 0x37:
                self.r["f"] = self.r["f"] & 0x80 | 0x10
            elif op in (0x18, 0x20, 0x28, 0x30, 0x38):
                offset = self.fetch()
                if op == 0x18 or self.condition((op - 0x20) // 8):
                    self.pc += offset if offset < 128 else offset - 256
            elif op in (0xC3, 0xC2, 0xCA, 0xD2, 0xDA):
                address = self.word()
                if op == 0xC3 or self.condition((op - 0xC2) // 8):
                    name = self.symbols.native_calls.get((0 if address < 0x4000 else self.bank, address))
                    if name:
                        if not self.native_call(name):
                            raise AssertionError(f"unmodeled native tail call: {name}")
                        self.pc = self.pop()
                    else:
                        self.pc = address
            elif op == 0xCD:
                self.invoke(self.word())
            elif op == 0xCF:
                self.invoke(8, 0)
            elif op in (0xC9, 0xC0, 0xC8, 0xD0, 0xD8):
                if op == 0xC9 or self.condition((op - 0xC0) // 8):
                    self.pc = self.pop()
            elif op == 0xCB:
                ext = self.fetch()
                reg, bit = ext & 7, (ext >> 3) & 7
                value = self.reg(reg)
                if 0x40 <= ext < 0x80:
                    self.r["f"] = self.r["f"] & 0x10 | 0x20 | (0x80 if not value & (1 << bit) else 0)
                elif ext >= 0x80:
                    self.reg(reg, value | (1 << bit) if ext >= 0xC0 else value & ~(1 << bit))
                elif ext & 0xF8 != 0x38:
                    raise AssertionError(f"unmodeled CB opcode {ext:02x}")
                else:
                    self.reg(reg, value >> 1)
                    self.r["f"] = (0x10 if value & 1 else 0) | (0x80 if value >> 1 == 0 else 0)
            else:
                raise AssertionError(f"unmodeled opcode {op:02x} at {self.pc - 1:04x}")
        raise AssertionError("trade MODEL instruction budget exhausted")


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def compiled(request, tmp_path_factory):
    return assemble_trade(tmp_path_factory.mktemp("trade-fsm-" + request.param), request.param)


def test_service_compiles_with_real_header_and_snapshot_helpers(compiled):
    for name in ("SlinkTradeEntry", "SlinkTradePromptEntry", "SlinkTradeDispatch", "SlinkTradeValidateSnapshot"):
        assert name in compiled[2]


class LeaseHost(TradeMachine):
    def __init__(self, compiled, fault=None):
        super().__init__(compiled)
        self.fault = fault
        self.frame = self.mailbox + 14
        self.delays, self.menus, self.commits, self.closes = 0, 0, [], 0
        self.offered, self.applied = False, False
        self.events = []
        self.responder, self.prompt_released, self.confirmations = False, False, 0
        self.token = bytes([0x12, 0x34, 0x56, 0x78])
        self.ram[self.address("wPartyCount")] = 2
        self.ram[self.address("wPartySpecies"):self.address("wPartySpecies") + 3] = bytes([158, 16, 255])
        for slot, species in enumerate((158, 16)):
            start = self.address("wPartyMon1") + slot * 48
            self.ram[start:start + 48] = bytes([species, 0]) + bytes(range(2, 48))
        for name in ("wPartyMonOTs", "wPartyMonNicknames", "wOTPartyMonOTs", "wOTPartyMonNicknames", "wOTPlayerName"):
            self.ram[self.address(name):self.address(name) + 11] = bytes([0x80] * 10 + [0x50])
        self.ram[self.address("wOTPartyCount")] = 1
        self.ram[self.address("wOTPartySpecies"):self.address("wOTPartySpecies") + 2] = bytes([19, 255])
        self.ram[self.address("wOTPartyMon1Species")] = 19
        self.ram[self.address("wOTPartyMon1Item")] = 0

    def native_call(self, name):
        if name == "AddNTimes":
            self.set_pair("hl", self.pair("hl") + self.r["a"] * self.pair("bc"))
        elif name == "SelectTradeOrDayCareMon":
            self.menus += 1
            self.ram[self.address("wCurPartyMon")] = 0
            self.r["f"] = 0x10 if self.fault == "menu_cancel" else 0
        elif name == "YesNoBox":
            self.confirmations += 1
            self.r["f"] = 0x10 if self.fault == "decline" else 0
            if self.fault == "ui_generation":
                self.ram[self.frame + 6] += 1
        elif name in ("PrintText", "OpenText"):
            pass
        elif name == "CloseText":
            self.closes += 1
        elif name == "JoyTextDelay":
            pass
        elif name == "DelayFrame":
            self.delays += 1
            self.host_step()
        elif name == "SlinkTradeCommit":
            self.commits.append((self.r["a"], self.r["b"]))
            if self.fault == "reentry":
                self.ram[self.frame + 5] = 3
                self.ram[self.frame + 6] = (self.ram[self.frame + 7] + 1) & 255
                self.run("SlinkTradeDispatch")
            self.r["a"] = 0
        else:
            return False
        return True

    def host_step(self):
        frame = self.ram[self.frame:self.frame + 16]
        command, generation, ack = frame[5:8]
        if command == 1 and generation != ack:
            self.events.append("QUERY")
            self.ram[self.frame + 10:self.frame + 12] = bytes([1, 3])
            self.ram[self.frame + 12:self.frame + 16] = self.token
            self.ram[self.frame + 7] = generation
            if self.fault == "query_unknown":
                self.ram[self.frame + 5] = 0x99
        elif command == 2 and not self.offered:
            self.events.append("OFFER")
            self.offered = True
            self.ram[self.frame + 8] = 0
            self.ram[self.frame + 7] = generation
        elif command == 2 and self.offered and not self.applied:
            if self.fault == "timeout":
                return
            if self.fault == "b_before_apply":
                self.ram[self.address("hJoyPressed")] = 2
                return
            self.events.append("APPLY")
            self.applied = True
            self.ram[self.frame + 5] = 0x99 if self.fault == "apply_unknown" else 5
            self.ram[self.frame + 6] = (generation + (2 if self.fault == "skip_generation" else 1)) & 255
            if self.fault and self.fault.startswith("token_"):
                self.ram[self.frame + 12 + int(self.fault[-1])] ^= 1
            elif self.fault == "slot":
                self.ram[self.frame + 9] = 1
            elif self.fault == "count":
                self.ram[self.address("wPartyCount")] = 3
            elif self.fault == "record":
                self.ram[self.address("wPartyMon1") + 7] ^= 1
            elif self.fault == "ot":
                self.ram[self.address("wPartyMonOTs")] ^= 1
            elif self.fault == "nickname":
                self.ram[self.address("wPartyMonNicknames")] ^= 1
            elif self.fault == "snapshot":
                self.ram[self.address("wOTPartyMon2") + 7] ^= 1
            elif self.fault == "bad_sender_name":
                self.ram[self.address("wOTPlayerName")] = 1
        elif command == 7:
            self.events.append("DONE" if self.commits else "DONE_PROMPT")
            assert self.commits or self.responder or self.ram[self.frame + 8] == 1
            self.events.append("RELEASE")
            self.ram[self.frame + 5] = 8
            self.prompt_released = True
        elif command == 8 and self.responder and self.prompt_released and not self.applied:
            self.events.append("APPLY")
            self.applied = True
            self.ram[self.frame + 5] = 5
            self.ram[self.frame + 6] = (generation + 1) & 255

    def enter(self):
        start = self.sp
        self.run("SlinkTradeEntry")
        assert self.sp == start
        assert self.ram[self.frame + 5] == 0
        assert self.ram[self.frame + 10:self.frame + 12] == bytes(2)

    def prepare_dispatch(self):
        self.responder = True
        self.ram[self.frame:self.frame + 16] = b"SLT1" + bytes([1, 3, 5, 4, 0, 0, 0, 0]) + self.token
        # run() adds the service return address at SP-2. Remaining entries are
        # the real bridge/DelayFrame/DelayFrames/NextOverworldFrame caller shape.
        start = self.sp - 2
        self.ram[start + 5] = self.symbols["NextOverworldFrame"][0]
        for offset, name, advance in ((12, "DelayFrame", 3), (14, "DelayFrames", 3), (16, "NextOverworldFrame", 9)):
            self.ram[start + offset:start + offset + 2] = (self.address(name) + advance).to_bytes(2, "little")
        self.ram[0xFF70] = 1  # rSVBK: native physical WRAM bank 1.
        self.ram[self.address("wMapStatus")] = 2  # pinned ram_constants.asm MAPSTATUS_HANDLE.
        return start


def test_compiled_query_offer_apply_done_release(compiled):
    machine = LeaseHost(compiled)
    machine.enter()
    assert machine.events == ["QUERY", "OFFER", "APPLY", "DONE", "RELEASE"]
    assert machine.commits == [(0, 0)]
    assert machine.ram[machine.frame + 8] == 0
    assert machine.ram[machine.frame + 12:machine.frame + 16] == machine.token


@pytest.mark.parametrize("fault", ["token_0", "token_1", "token_2", "token_3", "slot", "count", "record", "ot", "nickname",
                                  "snapshot", "b_before_apply", "timeout", "query_unknown", "apply_unknown", "skip_generation",
                                  "ui_generation", "bad_sender_name", "menu_cancel", "decline"])
def test_compiled_fsm_refuses_without_commit(compiled, fault):
    machine = LeaseHost(compiled, fault)
    machine.enter()
    assert machine.commits == []
    assert "DONE" not in machine.events
    if fault in ("slot", "count", "record", "ot", "nickname", "snapshot", "skip_generation", "bad_sender_name") or fault.startswith("token_"):
        assert machine.offered and machine.applied, "negative control never reached the APPLY boundary"


def test_compiled_nested_dispatch_during_commit_cannot_redispatch(compiled):
    machine = LeaseHost(compiled, "reentry")
    machine.enter()
    assert machine.commits == [(0, 0)]
    assert machine.menus == 1


def test_compiled_init_during_held_wait_closes_without_commit(compiled):
    class ResetHost(LeaseHost):
        def host_step(self):
            if self.offered and not self.applied:
                # Model the native Init lease clear at the held boundary, not
                # the complete hardware reset/CONTINUE path (a live obligation).
                self.events.append("INIT")
                self.run("SlinkTradeInit")
                return
            super().host_step()

    machine = ResetHost(compiled)
    start = machine.address("wPartyMon1")
    before = bytes(machine.ram[start:start + 96])
    machine.enter()
    assert machine.events == ["QUERY", "OFFER", "INIT"]
    assert machine.commits == []
    assert machine.ram[machine.frame:machine.frame + 16] == bytes(16)
    assert machine.ram[start:start + 96] == before


@pytest.mark.parametrize("responder", [False, True])
def test_compiled_shallow_wait_stack_budget(compiled, responder):
    """SOURCE + compiled local depth, not a physical/commit-stack witness.

    CONTINUE ancestry: C intro_menu:9,380,469 + main_menu:47,378-380;
    G intro_menu:291,349,855-886 + main_menu:44. Script suffix 22 bytes;
    responder includes the original idle-frame bridge/dispatcher ancestry.
    SFX maximum 26: audio/engine.asm:2557-2566,2293-2317,2760-2772.
    Normal IRQ 36: VBlank registers/call + _UpdateSound/FadeMusic/
    MusicFadeRestart/_InitSound/MusicOff (audio/engine.asm:204,652-654,61-67,12-16).
    Reset envelope 96: three suspended 14-byte IRQ/UpdateJoypad frames,
    18-byte reset wait, then one 36-byte Normal IRQ. Reset disables joypad
    recursion; its CGB palette fast path bounds the EI window (home/init:1-19,
    home/joypad:29-32,99-102; audio/engine:9-82; home/tilemap:168-201).
    Assumes pinned standalone CGB, no external serial/mobile activity. Only
    Normal-mode shallow waits qualify; native animation/evolution remain live gates.
    """
    class BudgetHost(LeaseHost):
        depths = None

        def native_call(self, name):
            if name == "DelayFrame" and not self.commits:
                self.depths.append(self.address("wStackTop") - self.sp)
            return super().native_call(name)

    machine = BudgetHost(compiled)
    machine.depths = []
    crystal = compiled[0] == "crystal"
    entry_depth = (46 if responder else 42) if crystal else (34 if responder else 30)
    machine.sp = machine.address("wStackTop") - entry_depth + 2  # run supplies the entry return
    if responder:
        machine.prepare_dispatch()
        machine.run("SlinkTradePromptEntry")
    else:
        machine.enter()
    assert machine.commits == [(0, int(responder))]
    # Native DelayFrame is a spy: include the patched call, bridge locals and
    # service return explicitly. Foreground SFX and IRQ bounds are source-derived.
    wait_depth = max(machine.depths) + 12
    assert wait_depth <= ((76 if responder else 74) if crystal else (64 if responder else 62))
    capacity = machine.address("wStackTop") - machine.address("wStackBottom")
    assert capacity == (255 if crystal else 252)
    assert capacity - wait_depth - 26 - 96 >= 32


@pytest.mark.parametrize("svbk", [0, 1])
def test_compiled_dispatcher_accepts_only_real_idle_caller(compiled, svbk):
    machine = LeaseHost(compiled)
    machine.prepare_dispatch()
    machine.ram[0xFF70] = svbk
    old_sp = machine.sp
    machine.run("SlinkTradeDispatch")
    assert machine.sp == old_sp
    assert machine.commits == [(0, 1)]
    assert machine.confirmations == 1 and machine.closes == 2
    assert machine.events == ["DONE_PROMPT", "RELEASE", "APPLY", "DONE", "RELEASE"]
    assert machine.ram[machine.frame + 5] == 0


@pytest.mark.parametrize("fault", ["bank", "delayframe", "delayframes", "overworld", "wScriptMode", "wBattleMode",
                                  "wLinkMode", "wGameLogicPaused", "hInMenu", "wram", "map", "acked", "header", "token"])
def test_compiled_dispatcher_rejects_false_or_unsafe_callers(compiled, fault):
    machine = LeaseHost(compiled)
    start = machine.prepare_dispatch()
    if fault in ("bank", "delayframe", "delayframes", "overworld"):
        offset = {"bank": 5, "delayframe": 12, "delayframes": 14, "overworld": 16}[fault]
        machine.ram[start + offset] ^= 1
    elif fault.startswith(("w", "h")) and fault not in ("wram", "header"):
        machine.ram[machine.address(fault)] = 1
    elif fault == "wram":
        machine.ram[0xFF70] = 2
    elif fault == "map":
        machine.ram[machine.address("wMapStatus")] = 1
    elif fault == "acked":
        machine.ram[machine.frame + 7] = machine.ram[machine.frame + 6]
    elif fault == "header":
        machine.ram[machine.frame] ^= 1
    else:
        machine.ram[machine.frame + 12:machine.frame + 16] = bytes(4)
    machine.run("SlinkTradeDispatch")
    assert machine.commits == [] and machine.confirmations == 0 and machine.closes == 0


@pytest.mark.parametrize("fault", ["decline", "ui_generation", "reentry"])
def test_compiled_responder_cleanup_and_nested_dispatch(compiled, fault):
    machine = LeaseHost(compiled, fault)
    machine.prepare_dispatch()
    machine.run("SlinkTradeDispatch")
    assert machine.confirmations == 1
    assert machine.closes == (2 if fault == "reentry" else 1)
    assert machine.commits == ([(0, 1)] if fault == "reentry" else [])


def test_compiled_apply_generation_wraps_ff_to_zero(compiled):
    machine = LeaseHost(compiled)
    machine.ram[machine.frame + 6] = 0xFD  # QUERY fe, accepted OFFER ff, APPLY 00.
    machine.enter()
    assert machine.commits == [(0, 0)]
    assert machine.ram[machine.frame + 6:machine.frame + 8] == bytes(2)


@pytest.mark.parametrize("count", [0, 7, 255])
def test_compiled_invalid_party_count_never_opens_native_menu(compiled, count):
    machine = LeaseHost(compiled)
    machine.ram[machine.address("wPartyCount")] = count
    machine.enter()
    assert machine.menus == 0 and not machine.commits


def test_compiled_non_normal_vblank_never_waits_or_commits(compiled):
    machine = LeaseHost(compiled)
    machine.ram[machine.address("hVBlank")] = 1
    machine.enter()
    assert machine.delays == machine.menus == 0 and not machine.commits


def test_compiled_init_clears_exact_lease(compiled):
    machine = LeaseHost(compiled)
    machine.ram[machine.mailbox:machine.mailbox + 40] = bytes([0xA5] * 40)
    machine.run("SlinkTradeInit")
    assert machine.ram[machine.frame:machine.frame + 16] == bytes(16)
    assert machine.ram[machine.mailbox:machine.frame] == bytes([0xA5] * 14)
    assert machine.ram[machine.frame + 16:machine.mailbox + 39] == bytes([0xA5] * 9)


@pytest.mark.parametrize("guard,fault", [("SlinkTradeCheckToken", "token_0"), ("SlinkTradeValidateSnapshot", "record")])
def test_compiled_guard_bypass_exposes_real_commit(compiled, guard, fault):
    machine = LeaseHost(compiled, fault)
    bank, address = machine.symbols[guard]
    start = bank * 0x4000 + address - 0x4000
    rom = bytearray(machine.rom)
    rom[start:start + 2] = bytes([0xAF, 0xC9])  # remove this guard: carry-clear return.
    machine.rom = bytes(rom)
    machine.enter()
    assert machine.commits == [(0, 0)], "refusal control did not depend on the compiled guard"


def test_compiled_dispatcher_bank_mutation_admits_wrong_caller(compiled):
    machine = LeaseHost(compiled)
    stack = machine.prepare_dispatch()
    machine.ram[stack + 5] ^= 1
    bank, address = machine.symbols["SlinkTradeDispatch"]
    start = bank * 0x4000 + address - 0x4000
    rom = bytearray(machine.rom)
    assert rom[start:start + 6] == bytes([0xF8, 5, 0x7E, 0xFE, 0x25, 0xC0])
    rom[start + 4] ^= 1
    machine.rom = bytes(rom)
    machine.run("SlinkTradeDispatch")
    assert machine.commits == [(0, 1)]
