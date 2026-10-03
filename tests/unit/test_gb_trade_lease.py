"""P4.3c: lua/gb_trade_lease.lua, the GB trade-lease framing (SLT1 frame, QUERY/OFFER/PROMPT/APPLY/
DONE/RELEASE, visit-token + stale-token refusal, generation publication), under lupa.

Gen 1 behaviour through its binder (lua/gen1/trade_overlay.lua) stays pinned byte-for-byte by
test_gen1_trade_overlay.py. This file pins the CONTRACT: every binder input is explicit and
asserted, the Lua lease offsets equal patch/gb/slink_abi.inc, and both a Gen 1 binder and a Gen 2
(mailbox +14 lease) stub refuse a stale token.
"""
from __future__ import annotations

import pathlib

import lupa
import pytest

from server.adapters import gen1_codec
from tests.unit.test_gb_panel import _abi
from tests.unit.test_gen1_trade_overlay import Fake as Gen1Fake, _blob

REPO = pathlib.Path(__file__).resolve().parents[2]
LEASE = (REPO / "lua" / "gb_trade_lease.lua").as_posix()
GEN1 = REPO / "lua" / "gen1" / "trade_overlay.lua"
MAGIC = b"SLT1"
REQUIRED = ("lease", "party_capacity", "check", "stage")
MAILBOX = 0xCFD8  # Crystal (O-27 D1); only the +14 lease offset matters here


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Override the repository's disk-writing state fixture."""
    yield


class Gen2Stub:
    """A Gen 2-shaped binder: the lease lives in the mailbox at +SLINK_OFS_TRADE_LEASE."""

    def __init__(self, **drop):
        self.mem = bytearray(0x10000)
        self.writes: list[tuple[int, list[int]]] = []
        self.staged: list[tuple] = []
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.L = self.lua.eval(f'dofile("{LEASE}")')
        self.base = MAILBOX + self.L.OFF_LEASE
        io = self.lua.eval("function(u, r) return {read_u8=function(a) return u(a) end,"
                           " read_range=function(a, n) return r(a, n) end} end")(
            lambda a: self.mem[int(a)],
            lambda a, n: self.lua.table_from(list(self.mem[int(a):int(a) + int(n)])))
        w = self.lua.eval("function(rec) return {write_bytes=function(self, a, t) rec(a, t) end} end")(
            self._write)
        spec = {"lease": self.base, "party_capacity": 6,
                "check": self.lua.eval("function(payload) if payload ~= 'ok' then return 'bad payload' end end"),
                "stage": lambda payload, preimage: self.staged.append((payload, bytes(preimage.values())))}
        t = self.lua.table()
        for k, v in spec.items():
            if k not in drop:
                t[k] = v
        self.driver = self.L.new(t, io, w)

    def _write(self, addr, t):
        data = [int(t[i]) for i in range(1, len(t) + 1)]
        self.writes.append((int(addr), data))
        self.mem[int(addr):int(addr) + len(data)] = bytes(data)

    def call(self, name, *args):
        return getattr(self.driver, name)(self.driver, *args)

    def bytes(self, values):
        return self.lua.table_from(list(values))

    def frame(self):
        return bytes(self.mem[self.base:self.base + 16])

    def seed(self, raw):
        self.mem[self.base:self.base + 16] = raw


class Gen1Binder:
    """lua/gen1/trade_overlay.lua over the real writes.lua; lease = wSerialPartyMonsPatchList."""

    def __init__(self):
        self.f = Gen1Fake()
        self.f.arm()
        self.base = self.f.ram["wSerialPartyMonsPatchList"]
        self.mem = self.f.memory

    def call(self, name, *args):
        return self.f.call(name, *args)

    def bytes(self, values):
        return self.f.bytes(values)

    def frame(self):
        return self.f.overlay()

    def seed(self, raw):
        self.f.seed_overlay(raw)

    def arm(self, command, slot, token):
        f = self.f
        return f.call("arm", command, slot, f.bytes(_blob()),
                      f.bytes(gen1_codec.encode_name("PARTNER")), f.bytes(token))


def _stub_arm(s, command, slot, token):
    return s.call("arm", command, slot, s.bytes(token), "ok")


BINDERS = {"gen1": (Gen1Binder, lambda b, *a: b.arm(*a)), "gen2_stub": (Gen2Stub, _stub_arm)}


@pytest.mark.parametrize("missing", REQUIRED)
def test_binder_missing_any_required_input_asserts(missing):
    with pytest.raises(lupa.LuaError, match=rf"spec\.{missing} required"):
        Gen2Stub(**{missing: True})


def test_gen1_binder_is_built_on_the_shared_lease():
    src = GEN1.read_text(encoding="utf-8")
    assert "gb_trade_lease.lua" in src
    assert "0x53, 0x4C, 0x54, 0x31" not in src  # the frame magic lives only in the shared module


@pytest.mark.parametrize("which", BINDERS)
def test_query_offer_stale_token_is_refused(which):
    make, _ = BINDERS[which]
    b = make()
    token = bytes((9, 8, 7, 6))
    b.seed(MAGIC + bytes((1, 1, 29, 28, 0, 0, 0, 0, 0, 0, 0, 0)))
    assert b.call("poll_query")["gen"] == 29
    assert b.call("answer_query", 29, 0b001001, b.bytes(token)) is True
    assert b.frame()[7] == 29 and b.frame()[10:16] == bytes((1, 0b001001)) + token
    offer = MAGIC + bytes((1, 2, 30, 29, 255, 3, 0, 0))
    b.seed(offer + bytes((9, 8, 7, 5)))           # another visit's token
    assert b.call("poll_offer") is None
    assert b.call("answer_offer", 30, True)[0] is None
    b.seed(offer + token)
    assert dict(b.call("poll_offer").items()) == {"slot": 3, "gen": 30}
    assert b.call("answer_offer", 30, True) is True
    assert b.frame()[7:9] == bytes((30, 0))


@pytest.mark.parametrize("which", BINDERS)
def test_apply_publishes_generation_last_and_releases_only_its_own_completion(which):
    make, arm = BINDERS[which]
    b = make()
    b.seed(bytes(16))
    token = (4, 3, 2, 1)
    gen = arm(b, 5, 2, token)
    assert gen == 1
    assert b.frame() == MAGIC + bytes((1, 5, 1, 0, 255, 2, 1, 0)) + bytes(token)
    published = b.frame()
    assert (b.f.consume() if which == "gen1" else b.call("picked_up")) is True
    b.seed(published)  # the native publisher restores its retained stack frame before DONE
    # A completion under a different token (a stale lease) is not ours.
    b.mem[b.base + 5], b.mem[b.base + 8], b.mem[b.base + 7] = 7, 0, gen
    b.mem[b.base + 15] ^= 1
    assert b.call("poll_done") is None
    assert b.call("release", gen)[0] is None
    b.mem[b.base + 15] ^= 1
    assert b.call("poll_done")["result"] == 0
    assert b.call("release", (gen + 1) % 256)[0] is None
    assert b.call("release", gen) is True
    assert b.mem[b.base + 5] == 8


@pytest.mark.parametrize("which", BINDERS)
def test_zero_token_and_bad_command_refused_before_any_write(which):
    make, arm = BINDERS[which]
    b = make()
    before = bytes(b.mem)
    assert arm(b, 5, 0, (0, 0, 0, 0))[0] is None
    assert arm(b, 4, 0, (1, 0, 0, 0))[0] is None
    assert arm(b, 5, 6, (1, 0, 0, 0))[0] is None   # own slot >= party_capacity
    assert bytes(b.mem) == before


def test_gen2_stub_stages_payload_with_the_preimage_before_publishing():
    s = Gen2Stub()
    s.seed(bytes(range(16)))
    assert s.call("arm", 3, 0, s.bytes((1, 2, 3, 4)), "nope")[1] == "bad payload"
    assert not s.writes and not s.staged
    assert _stub_arm(s, 3, 0, (1, 2, 3, 4)) == 7
    assert s.staged == [("ok", bytes(range(16)))]
    assert [a for a, _ in s.writes] == [s.base, s.base + 6]


# -- Lua lease offsets == patch/gb/slink_abi.inc ---------------------------------------------

PAIRS = [("OFF_LEASE", "SLINK_OFS_TRADE_LEASE"), ("LEASE_SIZE", "SLINK_TRADE_LEASE_SIZE")]


def _abi_resolved():
    abi = _abi()
    # SLINK_OFS_TRADE_LEASE EQU SLINK_CORE_SIZE: resolve the one symbolic alias.
    with open(REPO / "patch" / "gb" / "slink_abi.inc", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split(";")[0].split()
            if len(parts) == 4 and parts[0] == "DEF" and parts[2] == "EQU" and parts[3] in abi:
                abi.setdefault(parts[1], abi[parts[3]])
    return abi


def _mismatches(L, abi):
    return [f"{lua} != {inc}" for lua, inc in PAIRS if L[lua] != abi.get(inc)]


def test_lease_offsets_equal_slink_abi_inc():
    L = lupa.LuaRuntime().eval(f'dofile("{LEASE}")')
    assert _mismatches(L, _abi_resolved()) == []


def test_lease_abi_probe_catches_a_drift():
    """Known-positive control: a shifted lease offset must be reported."""
    L = lupa.LuaRuntime().eval(f'dofile("{LEASE}")')
    abi = dict(_abi_resolved(), SLINK_OFS_TRADE_LEASE=15)
    assert _mismatches(L, abi) == ["OFF_LEASE != SLINK_OFS_TRADE_LEASE"]


def test_a_throwing_consumption_verifier_holds_native_work_instead_of_rearming():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lease = lua.eval("dofile")(LEASE)
    driver = lua.eval("""function(L)
        local t=L.new({lease=0xC000, party_capacity=6,
            check=function() end, stage=function() end,
            pickup=function() error("unreadable retained frame") end},
            {read_u8=function() return 0 end, read_range=function() return {} end},
            {write_bytes=function() error("must not write") end})
        t.phase="armed"; t.expected={}
        return t
    end""")(lease)
    result, why = driver.picked_up(driver, 0xDE80)
    assert result is None and "unreadable retained frame" in why
    assert driver.phase == "picked_up" and driver.pickup_error == why
    assert driver.clobbered(driver) is False


def test_entry_observation_is_reset_by_each_successful_arm():
    b = Gen1Binder()
    gen = b.arm(5, 0, (1, 2, 3, 4))
    assert gen == 1 and b.call("observe_entry") is True
    b.arm(5, 0, (4, 3, 2, 1))
    assert b.f.driver.entry_observed is False
    b.mem[b.base + 2] ^= 1
    assert b.call("clobbered") is True and b.f.driver.phase == "armed"


def test_owned_mailbox_does_not_acquire_the_borrowed_union_fallback():
    b = Gen2Stub()
    _stub_arm(b, 5, 0, (1, 2, 3, 4))
    assert b.call("observe_entry") is True
    b.mem[b.base + 2] ^= 1
    assert b.call("clobbered") is True and b.driver.phase == "armed"
