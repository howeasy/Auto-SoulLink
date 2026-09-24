"""Native-call spies around the compiled Gen 2 commit helper: MODEL, not PHYSICAL."""

import pytest

from tests.unit.test_gen2_companion_abi import native_symbols
from tests.unit.test_gen2_trade_service import TradeMachine, assemble_trade

CONTROLS = ("wLinkMode", "wForceEvolution", "wCurPartyMon", "wPokemonWithdrawDepositParameter",
            "wCurTradePartyMon", "wCurOTTradePartyMon", "wJumptableIndex", "wTradeDialog",
            "wStateFlags", "wSpriteUpdatesEnabled")


class CommitSpies:
    """Native game routines are explicit spies; unexpected calls fail closed."""

    def addr(self, name):
        return self.native[name][1]

    def get(self, name):
        return self.ram[self.addr(name)]

    def put(self, name, value):
        self.ram[self.addr(name)] = value

    def word_pair(self, hi, lo):
        return self.r[hi] << 8 | self.r[lo]

    def set_word_pair(self, hi, lo, value):
        self.r[hi], self.r[lo] = value >> 8, value & 255

    def prepare_case(self, *, slot=1, role=0, count=3, fault=None, egg=False):
        self.native = native_symbols(self.title)
        self.slot, self.role, self.initial_count, self.fault = slot, role, count, fault
        self.calls = []
        for index, name in enumerate(CONTROLS):
            self.put(name, 0x40 + index)
        self.put("wLinkMode", 0)
        self.put("wForceEvolution", 0)
        self.put("wStateFlags", 0)
        self.put("wSpriteUpdatesEnabled", 1)
        self.put("wPartyCount", count)
        for index in range(count):
            self.ram[self.addr("wPartySpecies") + index] = index + 1
            base = self.addr("wPartyMon1Species") + index * 48
            self.ram[base:base + 48] = bytes([index + 1]) * 48
            for name in ("wPartyMonOTs", "wPartyMonNicknames"):
                base = self.addr(name) + index * 11
                self.ram[base:base + 11] = bytes([0x80 + index]) * 10 + b"\x50"
        self.ram[self.addr("wPartySpecies") + count] = 0xFF
        self.put("wOTPartyCount", 1)
        self.put("wOTPartySpecies", 0xFD if egg else 67)
        self.ram[self.addr("wOTPartySpecies") + 1] = 0xFF
        self.ram[self.addr("wOTPartyMon1Species"):self.addr("wOTPartyMon1Species") + 48] = bytes([67]) * 48
        for name, value in (("wPlayerName", 0x89), ("wOTPlayerName", 0x90),
                            ("wOTPartyMonOTs", 0x91), ("wOTPartyMonNicknames", 0x92)):
            self.ram[self.addr(name):self.addr(name) + 11] = bytes([value]) * 10 + b"\x50"
        self.sram_open = False
        mail = self.addr("sPartyMail")
        for index in range(6):  # each member's mail message is its own marker byte
            self.ram[mail + index * 0x2F:mail + (index + 1) * 0x2F] = bytes([0xC0 + index]) * 0x2F
        self.mail_before = bytes(self.ram[mail:mail + 6 * 0x2F])
        self.r.update(a=slot, b=role, c=0xA2, d=0xB3, e=0xC4, h=0xD5, l=0xE6)
        self.before_regs = {name: self.r[name] for name in "bcdehl"}
        self.before_controls = {name: self.get(name) for name in CONTROLS}

    def spy(self, name):
        if name == "CopyBytes":
            source, dest, size = self.word_pair("h", "l"), self.word_pair("d", "e"), self.word_pair("b", "c")
            self.ram[dest:dest + size] = self.ram[source:source + size]
            self.set_word_pair("h", "l", source + size)
            self.set_word_pair("d", "e", dest + size)
            self.set_word_pair("b", "c", 0)
        elif name == "SkipNames":
            self.set_word_pair("h", "l", self.word_pair("h", "l") + self.r["a"] * 11)
        elif name == "AddNTimes":
            self.set_word_pair("h", "l", self.word_pair("h", "l") + self.r["a"] * self.word_pair("b", "c"))
        elif name == "OpenSRAM":
            assert self.r["a"] == self.native["sPartyMail"][0]
            self.sram_open = True
        elif name == "CloseSRAM":
            self.sram_open = False
        elif name == "GetPartyLocation":
            self.set_word_pair("h", "l", self.word_pair("h", "l") + self.r["a"] * 48)
        elif name == "GetCaughtGender":
            assert self.word_pair("b", "c") in (self.addr("wPartyMon1Species") + self.slot * 48,
                                            self.addr("wOTPartyMon1Species"))
            self.r["c"] = 1
        elif name == "RemoveMonFromPartyOrBox":
            # MINOR-1: linked removal leaves sPartyMail alone (move_mon.asm .finish)
            assert self.get("wLinkMode") == 2
            assert self.get("wPokemonWithdrawDepositParameter") == 0
            assert self.get("wCurPartyMon") == self.slot
            self.calls.append(name)
            assert bytes(self.ram[self.addr("sPartyMail"):self.addr("sPartyMail") + 6 * 0x2F]) == self.mail_before
            if self.fault == "remove_nochange":
                return True
            count = self.get("wPartyCount")
            for field, width in (("wPartySpecies", 1), ("wPartyMon1Species", 48),
                                 ("wPartyMonOTs", 11), ("wPartyMonNicknames", 11)):
                start = self.addr(field) + self.slot * width
                size = (count - self.slot - 1) * width
                self.ram[start:start + size] = self.ram[start + width:start + width + size]
            self.put("wPartyCount", count - 1)
            self.ram[self.addr("wPartySpecies") + count - 1] = 0xFF
        elif name in ("TradeAnimation", "TradeAnimationPlayer2"):
            assert name == ("TradeAnimation" if self.role == 0 else "TradeAnimationPlayer2")
            assert self.get("wPlayerTrademonSpecies") == self.slot + 1
            assert self.get("wOTTrademonSpecies") == self.get("wOTPartySpecies")
            for target, source in (("wPlayerTrademonSenderName", "wPlayerName"),
                                   ("wOTTrademonSenderName", "wOTPlayerName")):
                assert self.ram[self.addr(target):self.addr(target) + 11] == self.ram[self.addr(source):self.addr(source) + 11]
            self.calls.append(name)
            self.put("wJumptableIndex", 0x12)
            self.put("wTradeDialog", 0x34)
        elif name == "AddTempmonToParty":
            assert self.get("wCurPartyMon") == 0, "incoming OT name index must be zero"
            assert self.get("wCurPartySpecies") == self.get("wOTPartySpecies")
            self.calls.append(name)
            if self.fault == "append_carry":
                self.r["f"] |= 0x10
                return True
            self.r["f"] &= ~0x10
            if self.fault == "append_nochange":
                return True
            count = self.get("wPartyCount")
            for target, source, width in (("wPartyMon1Species", "wTempMonSpecies", 48),
                                          ("wPartyMonOTs", "wOTPartyMonOTs", 11),
                                          ("wPartyMonNicknames", "wOTPartyMonNicknames", 11)):
                destination = self.addr(target) + count * width
                self.ram[destination:destination + width] = self.ram[self.addr(source):self.addr(source) + width]
            self.ram[self.addr("wPartySpecies") + count] = self.get("wCurPartySpecies")
            self.ram[self.addr("wPartySpecies") + count + 1] = 0xFF
            self.put("wPartyCount", count + 1)
            if self.fault == "append_wrong_list":
                self.ram[self.addr("wPartySpecies") + count] ^= 1
            if self.fault == "append_wrong_struct":
                self.ram[self.addr("wPartyMon1Species") + count * 48] ^= 1
        elif name == "EvolvePokemon":
            assert self.get("wLinkMode") == 2 and self.get("wForceEvolution") == 1
            assert self.get("wCurPartyMon") == self.initial_count - 1
            self.calls.append(name)
            if self.fault == "evolution_count":
                self.put("wPartyCount", self.initial_count - 1)
        elif name == "SaveAfterLinkTrade":
            assert self.calls[-1] == "EvolvePokemon"
            assert self.get("wPartyCount") == self.initial_count
            assert not self.sram_open
            mail = self.addr("sPartyMail")
            want = bytearray(self.mail_before)
            moved = (self.initial_count - 1 - self.slot) * 0x2F
            want[self.slot * 0x2F:self.slot * 0x2F + moved] = self.mail_before[(self.slot + 1) * 0x2F:
                                                                             (self.slot + 1) * 0x2F + moved]
            assert bytes(self.ram[mail:mail + 6 * 0x2F]) == bytes(want), "mail shifted only just before the save"
            self.calls.append(name)
        elif name == "BackupGSBallFlag":
            assert self.title == "crystal" and self.calls[-1] == "SaveAfterLinkTrade"
            self.calls.append(name)
        elif name in ("DisableSpriteUpdates", "ClearTilemap", "LoadFontsBattleExtra", "GetSGBLayout",
                       "RestartMapMusic", "ReturnToMapWithSpeechTextbox"):
            if name == "DisableSpriteUpdates":
                self.put("wSpriteUpdatesEnabled", 0)
            elif name == "ReturnToMapWithSpeechTextbox":
                self.put("wSpriteUpdatesEnabled", 1)
        else:
            raise AssertionError(f"unexpected native call: {name}")
        return True

    def verify_restored(self):
        assert {name: self.r[name] for name in "bcdehl"} == self.before_regs
        assert {name: self.get(name) for name in CONTROLS} == self.before_controls
        assert self.sp == 0xDFFE


class CommitMachine(CommitSpies, TradeMachine):
    def native_call(self, name):
        return self.spy(name)


@pytest.fixture(scope="module", params=("crystal", "gold", "silver"))
def compiled(request, tmp_path_factory):
    return assemble_trade(tmp_path_factory.mktemp(f"commit-{request.param}"), request.param,
                          source_files=["trade_commit.asm"], stub_names=())


@pytest.mark.parametrize("role", [0, 1])
@pytest.mark.parametrize("slot,count", [(0, 1), (1, 3), (5, 6)])
@pytest.mark.parametrize("egg", [False, True])
def test_native_commit_sequence_and_controls(compiled, role, slot, count, egg):
    machine = CommitMachine(compiled)
    machine.prepare_case(slot=slot, role=role, count=count, egg=egg)
    machine.run("SlinkTradeCommit")
    assert machine.r["a"] == 0
    assert machine.calls == ["RemoveMonFromPartyOrBox",
                             "TradeAnimation" if role == 0 else "TradeAnimationPlayer2",
                             "AddTempmonToParty", "EvolvePokemon", "SaveAfterLinkTrade"] + (
                                 ["BackupGSBallFlag"] if machine.title == "crystal" else [])
    machine.verify_restored()


@pytest.mark.parametrize("fault", ["remove_nochange", "append_carry", "append_nochange",
                                   "append_wrong_list", "append_wrong_struct", "evolution_count"])
def test_native_postcondition_failure_is_uncertain_and_never_saved(compiled, fault):
    machine = CommitMachine(compiled)
    machine.prepare_case(fault=fault)
    machine.run("SlinkTradeCommit")
    assert machine.r["a"] == 2
    assert "SaveAfterLinkTrade" not in machine.calls
    if fault not in ("evolution_count",):
        assert "EvolvePokemon" not in machine.calls
    machine.verify_restored()


@pytest.mark.parametrize("slot,count,role,ot_count", [(0, 0, 0, 1), (3, 3, 0, 1),
                                                     (0, 3, 2, 1), (0, 3, 0, 2)])
def test_invalid_commit_entry_has_no_native_mutation(compiled, slot, count, role, ot_count):
    machine = CommitMachine(compiled)
    machine.prepare_case(slot=slot, count=count, role=role)
    machine.put("wOTPartyCount", ot_count)
    machine.run("SlinkTradeCommit")
    assert machine.r["a"] == 2 and machine.calls == []
    machine.verify_restored()


@pytest.mark.parametrize("mutation", ["unlinked_remove", "unchecked_list", "save_before_evolve", "register_restore"])
def test_compiled_commit_mutants_fail_native_contract(compiled, mutation):
    machine = CommitMachine(compiled)
    machine.prepare_case(fault="append_wrong_list" if mutation == "unchecked_list" else None)
    rom = bytearray(machine.rom)
    bank, address = machine.symbols["SlinkTradeCommit"]
    start = bank * 0x4000 + address - 0x4000
    end = bank * 0x4000 + machine.symbols["SlinkTradeCommitEnd"][1] - 0x4000
    if mutation == "unlinked_remove":
        address = machine.addr("wLinkMode")
        position = rom.index(bytes([0x3E, 2, 0xEA, address & 255, address >> 8]), start, end)
        rom[position + 1] = 0  # the old unlinked removal: native RemoveMon shifts SRAM mail early
    elif mutation == "unchecked_list":
        address = machine.addr("wOTPartySpecies")
        position = rom.index(bytes([0xFA, address & 255, address >> 8, 0xBE, 0xC2]), start, end)
        rom[position + 4:position + 7] = bytes(3)
    elif mutation == "save_before_evolve":
        bank, address = machine.native["EvolvePokemon"]
        position = rom.index(bytes([0x3E, bank, 0x21, address & 255, address >> 8, 0xCF]), start, end)
        bank, address = machine.native["SaveAfterLinkTrade"]
        rom[position + 1] = bank
        rom[position + 3:position + 5] = address.to_bytes(2, "little")
    else:
        position = rom.index(bytes([0xE1, 0xD1, 0xC1, 0x3E, 0, 0xC8]), start, end)
        rom[position + 2] = 0xD1
    machine.rom = bytes(rom)
    with pytest.raises(AssertionError):
        machine.run("SlinkTradeCommit")
        assert machine.r["a"] == (2 if mutation == "unchecked_list" else 0)
        machine.verify_restored()
