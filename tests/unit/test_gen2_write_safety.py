"""Generated Gen 2 source predicate over held synthetic observations; never runtime authority."""

import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class Candidate:
    def __init__(self, title="crystal"):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.pack = json.loads((ROOT / f"data/games/gen2_{title}/write_checkpoint.json").read_text())
        self.data = self.pack["titles"][title]
        self.primary = self.data["primary"]
        self.memory, self.reads = {}, []
        self.epoch, self.admitted, self.unowned = 1, True, True
        self.rom_bank = self.primary["execution_before"]["bank"]
        self.wram_bank = 1
        self.registers = {"PC": self.primary["execution_before"]["pc"],
                          "SP": self.primary["caller_stack"]["minimum_sp"] + 16}
        for anchor in self.primary["anchors"].values():
            for offset, value in enumerate(bytes.fromhex(anchor["expected_hex"])):
                self.memory["ROM", anchor["rom_offset"] + offset] = value
                self.memory["System Bus", anchor["address"] + offset] = value
        for word in self.primary["caller_stack"]["required_words"]:
            address = self.registers["SP"] + word["offset_from_sp"]
            self.memory["System Bus", address] = word["value"] & 255
            self.memory["System Bus", address + 1] = word["value"] >> 8
        for condition in self.primary["state_predicates"]:
            self.memory["System Bus", condition["address"]] = condition["value"]
        owner = self.primary["ownership_requirements"]
        self.memory["System Bus", owner["rom_bank_shadow"]["address"]] = self.rom_bank
        self.memory["System Bus", owner["wram_bank_register"]["address"]] = 1
        self.memory["System Bus", owner["serial_control"]["address"]] = 0
        self.io = self.lua.table(read_u8=self.read, domains=lambda: self.lua.table("ROM", "System Bus"),
                                 domain_size=lambda _name: 0x200000,
                                 register=lambda name: self.registers.get(name))
        self.ownership = self.lua.table(
            capture=lambda: self.epoch, valid=lambda held: held == self.epoch,
            admitted=lambda selected, sha: self.admitted and selected == title and sha == self.pack["source"]["rom_sha1"],
            no_conflicting_owner=lambda: self.unowned, mapped_rom_bank=lambda: self.rom_bank,
            effective_wram_bank=lambda: self.wram_bank,
        )
        self.module = self.lua.eval("dofile")((ROOT / "lua/gen2_write_safety.lua").as_posix())
        self.evaluator = self.lua.eval("dofile")((ROOT / "lua/gb_checkpoint.lua").as_posix())
        self.title = title

    def read(self, address, domain):
        self.reads.append((domain, int(address)))
        return self.memory.get((domain, int(address)))

    def binder(self):
        return self.module.new(self.lua.table_from(self.pack, recursive=True), self.title,
                               self.io, self.evaluator, self.ownership)

    def inspect(self):
        binder = self.binder()
        return binder.inspect_candidate(binder)


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_matching_source_candidate_never_grants_runtime_writes(title):
    candidate = Candidate(title)
    report = candidate.inspect()
    assert report.candidate_match is True, report.reason
    assert report.runtime_authorized is False and report.physical_status == "OPEN"
    binder = candidate.binder()
    assert binder.check(binder)[0] is False
    candidate.data["runtime_authorized"] = True
    assert candidate.inspect().candidate_match is False
    binder = candidate.binder()
    assert binder.check(binder)[0] is False


@pytest.mark.parametrize("symbol", ["wMapStatus", "wMapEventStatus", "wScriptRunning", "wScriptMode",
    "wScriptFlags", "wScriptStackSize", "wJoypadDisable", "wGameLogicPaused", "wInputType",
    "wBattleMode", "wStateFlags", "hMapEntryMethod", "wLinkMode", "hSerialConnectionStatus", "wSavedAtLeastOnce"])
def test_every_game_state_ownership_predicate_is_required(symbol):
    candidate = Candidate()
    condition = next(row for row in candidate.primary["state_predicates"] if row["symbol"] == symbol)
    candidate.memory["System Bus", condition["address"]] ^= condition["mask"]
    report = candidate.inspect()
    assert report.candidate_match is False and symbol in report.reason


@pytest.mark.parametrize("fault", ["rom", "mapped_anchor", "caller", "pc", "rom_bank", "wram_bank",
                                  "serial", "identity", "owner", "missing_predicate", "epoch"])
def test_stale_or_unavailable_same_hold_evidence_refuses(fault):
    candidate = Candidate()
    primary = candidate.primary
    if fault in ("rom", "mapped_anchor"):
        anchor = primary["anchors"]["ow_player_input"]
        key = ("ROM", anchor["rom_offset"]) if fault == "rom" else ("System Bus", anchor["address"])
        candidate.memory[key] ^= 1
    elif fault == "caller":
        candidate.memory["System Bus", candidate.registers["SP"]] ^= 1
    elif fault == "pc":
        candidate.registers["PC"] += 1
    elif fault == "rom_bank":
        candidate.rom_bank += 1
    elif fault == "wram_bank":
        candidate.wram_bank = 2
    elif fault == "serial":
        candidate.memory["System Bus", primary["ownership_requirements"]["serial_control"]["address"]] = 128
    elif fault == "identity":
        candidate.admitted = False
    elif fault == "owner":
        candidate.unowned = False
    elif fault == "missing_predicate":
        primary["state_predicates"].pop()
    else:
        def read_and_reset(address, domain):
            candidate.epoch += 1
            return candidate.read(address, domain)
        candidate.io.read_u8 = read_and_reset
    assert candidate.inspect().candidate_match is False


def test_no_gen1_irq_resume_or_two_word_stack_is_inherited():
    candidate = Candidate("gold")
    assert candidate.inspect().candidate_match is True
    stack_reads = [address for domain, address in candidate.reads
                   if domain == "System Bus" and candidate.registers["SP"] <= address < candidate.registers["SP"] + 4]
    assert stack_reads == [candidate.registers["SP"], candidate.registers["SP"] + 1]
    candidate.registers["PC"] = 0x40
    assert candidate.inspect().candidate_match is False


@pytest.mark.parametrize("shape", ["sparse", "named", "zero", "empty"])
def test_caller_word_conversion_never_silently_drops_malformed_entries(shape):
    candidate = Candidate()
    assert candidate.inspect().candidate_match is True
    word = candidate.primary["caller_stack"]["required_words"][0]
    wrong = {**word, "value": word["value"] ^ 1}
    words = {1: word, 3: wrong} if shape == "sparse" else (
        {1: word, "extra": wrong} if shape == "named" else ({0: wrong, 1: word} if shape == "zero" else {})
    )
    candidate.primary["caller_stack"]["required_words"] = words
    report = candidate.inspect()
    assert report.candidate_match is False and "caller words" in report.reason
    assert report.runtime_authorized is False
