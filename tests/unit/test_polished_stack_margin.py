"""Measured bank-$7E stack budgets, using the existing assembled-byte SM83 rigs.

Native FarCall executes from the cartridge, rather than using its synthetic
scratch-depth model. Native UI, DelayFrame, animation, evolution and save traps
remain the existing rigs' seams: their interiors and a live interrupt workload
are NOT measured here. These are entry-relative model budgets, not a live ROM
stack-safety certificate. C5 authorization is changed only in the machine image.

Stack: polished_slink.sym wStackBottom=$C000, wStackTop=$C0FF;
Polished ram/wram0.asm:1-8 allocates $100 bytes; engine/init.asm:53-54
sets SP to wStack=$C0FF, leaving 255 descending bytes. Interrupt reserve: 12 bytes =
VBlank hardware PC (2) + push hl/de/bc/af (8; home/vblank.asm:9-13) + a
possible timer hardware PC (2). Timer pushes zero software bytes and is disabled
(home/header.asm:135-138); reserve its PC anyway because VBlank enables IME
(home/vblank.asm:190-196). Interrupt callees, LCD/serial and native trap
interiors are outside that reserve and remain unmeasured.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.unit import (
    polished_sm83 as cpu,
    test_polished_trade_commit as commit,
    test_polished_trade_dispatch as dispatch,
    test_polished_trade_responder as responder,
    test_polished_trade_service as proposer,
)

INTERRUPT_RESERVE = 12
# Pins measured on overlay at integration 7f56228b5, with native FarCall:
# entry SP excludes the caller's two-byte return slot; minima are recorded below.
PINS = {"proposer": 37, "responder": 32, "commit": 60, "dispatcher": 36}
# Observed entry/min SP: proposer C0FD/C0D8, responder C0FD/C0DD,
# C5 C0BE/C082 (existing rig's service context), dispatcher C0FD/C0D9.
# Red control: two temporary PUSH/POP pairs at C5's CopyBytes call changed
# its depth to 64; the 60-byte pin failed. No injection remains in this test.


@pytest.fixture(scope="module")
def env():
    for path in (proposer.RELEASE, proposer.OVERLAY_SYM, proposer.CLEAN_SYM):
        if not path.is_file():
            pytest.skip(f"stack measurement input absent: {path}")
    # A missing/bad patch, obsolete symbol, or broken machine is a failure.
    return proposer.Env(
        proposer.ups_apply(proposer.RELEASE.read_bytes(), proposer.UPS.read_bytes()),
        proposer._symbols(proposer.OVERLAY_SYM),
        proposer._symbols(proposer.CLEAN_SYM),
    )


@dataclass
class Measurement:
    entry_sp: int
    min_sp: int
    chain: tuple[str, ...]

    @property
    def depth(self):
        return self.entry_sp - self.min_sp


def instrument(monkeypatch, env, *, special=False, enable_commit=False):
    """Wrap the missing high-water/call-chain hook without changing shared rigs."""
    measurements = []
    base = cpu.SM83
    symbols = {}
    for name, (bank, addr) in env.sym.items():
        if addr < 0x8000 and "." not in name:
            symbols.setdefault(bank, {})[addr] = name

    def symbol(bank, pc):
        bank = 0 if pc < 0x4000 else bank
        entries = symbols.get(bank, {})
        candidates = [addr for addr in entries if addr <= pc]
        assert candidates, f"no symbol for {bank:02x}:{pc:04x}"
        return entries[max(candidates)]

    class Measured(base):
        def __init__(self, *args, **kwargs):
            kwargs["farcall"] = "native"
            super().__init__(*args, **kwargs)
            self.calls = []
            self.peak_chain = ()
            self.root = ""
            if enable_commit:
                assert env.sym["SlinkTradeCommitEnabled"] == (0x7E, 0x573B)
                assert env.rom[env.flat("SlinkTradeCommitEnabled")] == 0
                image = bytearray(self.mem.rom)
                image[env.flat("SlinkTradeCommitEnabled")] = 1
                self.mem.rom = bytes(image)

        def _call(self, target):
            caller = symbol(self.bank, self.mem.ipc)
            super()._call(target)
            self.calls.append((self.sp, caller, symbol(self.bank, target)))

        def _x3(self, op, y, z):
            caller = symbol(self.bank, self.mem.ipc)
            fallthrough = self.pc + 2
            before = self.sp
            super()._x3(op, y, z)
            # Named JP tail calls keep their caller's return slot. Record them
            # as logical frames without pretending they consumed stack bytes.
            if op in (0xC3, 0xC2, 0xCA, 0xD2, 0xDA) and self.pc != fallthrough and self.sp == before:
                bank = 0 if self.pc < 0x4000 else self.bank
                target = symbols.get(bank, {}).get(self.pc)
                if target is not None and target != caller:
                    self.calls.append((self.sp - 1, caller, target))

        def _do_ret(self):
            at = self.sp
            super()._do_ret()
            self.calls = [frame for frame in self.calls if frame[0] > at]

        def _dip(self, sp):
            old = self._max_depth
            super()._dip(sp)
            if self._max_depth > old:
                names = [self.root]
                for _, caller, target in self.calls:
                    for name in (caller, target):
                        if names[-1] != name:
                            names.append(name)
                current = symbol(self.bank, self.mem.ipc)
                if names[-1] != current and (not self.calls or current != self.calls[-1][1]):
                    names.append(current)
                self.peak_chain = tuple(names)

        def call_routine(self, addr, regs=None, sp=None, **kwargs):
            if special and addr == env.a("SlinkTradeEntry"):
                pointer = env.flat("SpecialsPointers") + 3 * 3
                assert env.rom[pointer:pointer + 3] == bytes((0x7E, 0x10, 0x44))
                addr = env.a("Special")
                kwargs["bank"] = env.sym["Special"][0]
                regs = {**(regs or {}), "de": 3}
                self.poke(proposer.HROMBANK, kwargs["bank"])
                self.poke(env.a("wChosenCableClubRoom"), 1)
            self.root = symbol(kwargs.get("bank", self.bank), addr)
            entry = (cpu.DEFAULT_SP if sp is None else sp) - 2
            result = super().call_routine(addr, regs, sp, **kwargs)
            measurements.append(Measurement(entry, result.min_sp, self.peak_chain))
            assert result.sp_delta == 0
            return result

    # proposer/responder import the same file under the short module name;
    # commit/dispatcher use the package name. Patch both, then restore via pytest.
    for module in (cpu, proposer.S, responder.S, dispatch.sm, commit.S):
        monkeypatch.setattr(module, "SM83", Measured)
        monkeypatch.setattr(module, "DEFAULT_SP", env.a("wStackTop"))
    monkeypatch.setattr(dispatch, "ENTRY_SP", env.a("wStackTop"))
    monkeypatch.setattr(dispatch, "SENT_SP", env.a("wStackTop") - 2)
    return measurements


def assert_margin(path, measurements, env):
    assert measurements, f"{path} never ran"
    peak = max(measurements, key=lambda m: m.depth)
    bottom, top = env.a("wStackBottom"), env.a("wStackTop")
    assert (bottom, top) == (0xC000, 0xC0FF)
    # Include the entry's existing caller/return context, not just the new depth.
    headroom = peak.min_sp - bottom - INTERRUPT_RESERVE
    print(f"{path}: entry={peak.entry_sp:04x} min={peak.min_sp:04x} "
          f"depth={peak.depth} pin={PINS[path]} headroom={headroom} "
          f"runs={len(measurements)} chain={' -> '.join(peak.chain)}")
    assert peak.depth <= PINS[path], f"{path} stack grew: {peak.depth} > {PINS[path]}: {peak.chain}"
    assert headroom >= 0, f"{path} exhausted native stack after interrupt reserve"


@pytest.mark.parametrize("path", tuple(PINS))
def test_native_stack_margin(path, env, monkeypatch):
    measurements = instrument(monkeypatch, env, special=path == "proposer", enable_commit=path == "commit")
    if path == "proposer":
        # Start at Special and consume SpecialsPointers entry 3, through the
        # timeout gate, QUERY, OFFER, APPLY and RELEASE waits. Full-party boundary.
        for count, slot in ((1, 0), (4, 2), (6, 5)):
            rig = proposer.Rig(env, party=count, own=slot)
            run = rig.run(proposer.host_happy(mask=1 << slot))
            assert run.events == "QOADC" and run.host.done_result == 1
        for host, kwargs in ((None, {}), (proposer.host_happy(), {"yesno": False}),
                             (proposer.host_apply_at(None), {})):
            run = proposer.Rig(env).run(host, **kwargs)
            assert run.events.endswith("C")
    elif path == "responder":
        assert env.sym["SlinkTradePromptEntry"] == (0x7E, 0x4780)
        for name, scenario in responder.SCENARIOS.items():
            if name not in ("via_dispatcher", "reentry", "stack_balance"):
                scenario(env)
    elif path == "commit":
        assert env.sym["SlinkTradeCommit"] == (0x7E, 0x5300)
        for count, slot in ((1, 0), (6, 0), (6, 2), (6, 5), (4, 1)):
            for role in (0, 1):
                rig = commit.Rig(env, count=count, slot=slot, role=role)
                result = rig.run()
                assert result.a == 0 and "ForceGameSave" in rig.events
                rig.invariant(result)
        for fault in ("identity", "animation-staging", "evolution-count", "evolution-identity",
                      "save-carry", "save-missing", "save-postimage", "save-checksum", "save-phase"):
            rig = commit.Rig(env, fault=fault)
            result = rig.run()
            assert result.a == (1 if fault == "identity" else 2)
            rig.invariant(result)
    else:
        assert env.sym["SlinkTradeDispatch"] == (0x7E, 0x4700)
        world = dispatch.World(env.rom, env.sym)
        for state, stack, expected in ((None, world.stack(p5=0x24), False),
                                       ({**world.state(), world.cmd_at: 1}, None, False),
                                       (None, None, True)):
            _, _, calls = world.run(state, stack)
            assert bool(calls) is expected
        # The dispatcher pin includes the real responder, not only its trap.
        run = responder.Rig(env).run(responder.host_consent(), via_dispatch=True)
        assert run.events == "ADADC" and run.info[1]["o8"] == 0
    assert_margin(path, measurements, env)
