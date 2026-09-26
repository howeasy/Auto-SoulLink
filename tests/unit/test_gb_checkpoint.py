"""Shared GB checkpoint mechanism over explicit synthetic facts; MODEL only."""

from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


class Checkpoint:
    def __init__(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.module = self.lua.eval("dofile")((ROOT / "lua/gb_checkpoint.lua").as_posix())
        self.memory = {("ROM", 0x12010): 0xCD, ("ROM", 0x12011): 0x34,
                       ("ROM", 0x12012): 0x12, ("System Bus", 0xC100): 0x34,
                       ("System Bus", 0xC101): 0x12, ("System Bus", 0xC102): 0x78,
                       ("System Bus", 0xC103): 0x56}
        self.reads = []
        self.registers = {"PC": 0x6010, "SP": 0xC100}
        self.domains = ["ROM", "System Bus"]
        self.spec = {
            "domains": {"ROM": {"first": 0, "limit": 0x20000},
                        "System Bus": {"first": 0, "limit": 0x10000}},
            "anchors": [{"domain": "ROM", "address": 0x12010, "expected_hex": "CD3412"}],
            "pc": 0x6010,
            "stack": {"domain": "System Bus", "minimum_sp": 0xC000,
                      "exclusive_end": 0xC200, "read_bytes": 4,
                      "words": [{"offset": 0, "values": [0x1234]},
                                {"offset": 2, "values": [0x5678, 0x567B]}]},
        }
        self.io = self.lua.table(read_u8=self.read, register=lambda name: self.registers.get(name),
                                 domains=lambda: self.lua.table_from(self.domains))
        self.predicate = self.lua.eval("function() return true end")

    def read(self, address, domain):
        self.reads.append((domain, int(address)))
        return self.memory.get((domain, int(address)))

    def check(self):
        return self.module.check(self.lua.table_from(self.spec, recursive=True), self.io, self.predicate)


def test_banked_flat_anchor_and_exact_little_endian_words_pass_without_stack_scan():
    checkpoint = Checkpoint()
    assert checkpoint.check()[0] is True
    assert [address for domain, address in checkpoint.reads if domain == "System Bus"] == [
        0xC100, 0xC101, 0xC102, 0xC103,
    ]


def test_every_attempt_rechecks_anchors_and_can_reacquire():
    checkpoint = Checkpoint()
    assert checkpoint.check()[0] is True
    checkpoint.memory["ROM", 0x12011] ^= 1
    assert checkpoint.check()[0] is False
    checkpoint.memory["ROM", 0x12011] ^= 1
    assert checkpoint.check()[0] is True


@pytest.mark.parametrize("fault", ["pc", "caller", "resume", "sp_low", "sp_end", "domain", "byte", "predicate"])
def test_unavailable_or_mismatched_checkpoint_refuses(fault):
    checkpoint = Checkpoint()
    if fault == "pc":
        checkpoint.registers["PC"] += 1
    elif fault in ("caller", "resume"):
        checkpoint.memory["System Bus", 0xC102 if fault == "caller" else 0xC100] ^= 1
    elif fault == "sp_low":
        checkpoint.registers["SP"] = 0xBFFF
    elif fault == "sp_end":
        checkpoint.registers["SP"] = 0xC1FD
    elif fault == "domain":
        checkpoint.domains.remove("ROM")
    elif fault == "byte":
        checkpoint.memory["System Bus", 0xC101] = None
    else:
        checkpoint.predicate = checkpoint.lua.eval("function() return false, 'owner busy' end")
    assert checkpoint.check()[0] is False
    if fault.startswith("sp_"):
        assert not any(domain == "System Bus" for domain, _address in checkpoint.reads)


@pytest.mark.parametrize("fault", ["empty_hex", "odd_hex", "bad_hex", "empty_anchors",
                                  "empty_words", "sparse_words", "missing_bounds", "wide_word"])
def test_malformed_contract_never_becomes_vacuous_acceptance(fault):
    checkpoint = Checkpoint()
    if fault.endswith("hex"):
        checkpoint.spec["anchors"][0]["expected_hex"] = {
            "empty_hex": "", "odd_hex": "C", "bad_hex": "GG",
        }[fault]
    elif fault == "empty_anchors":
        checkpoint.spec["anchors"] = []
    elif fault == "empty_words":
        checkpoint.spec["stack"]["words"] = []
    elif fault == "sparse_words":
        checkpoint.spec["stack"]["words"] = {1: {"offset": 0, "values": [0x1234]},
                                               3: {"offset": 2, "values": [0x5678]}}
    elif fault == "missing_bounds":
        del checkpoint.spec["domains"]["ROM"]
    else:
        checkpoint.spec["stack"]["words"][0]["values"] = [0x11234]
    assert checkpoint.check()[0] is False


def test_predicate_errors_and_nonboolean_success_fail_closed():
    checkpoint = Checkpoint()
    for body in ("error('unavailable owner')", "return 1", "return nil"):
        checkpoint.predicate = checkpoint.lua.eval(f"function() {body} end")
        assert checkpoint.check()[0] is False
