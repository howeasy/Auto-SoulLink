"""X3: the expansion reference build's parked-CPU clause (lua/gen3/safety.lua) from live evidence.

Live, BizHawk 2.11.1 / mGBA HLE BIOS, ROM 28877d73 on exp_town.sav / exp_center.sav:
  docs/gen3_emerald/probes/census_exp_overworld_2026-09-27.txt -- no hook: 1800/1800 frame ends at
    R15 0x1F8, System mode, ARM, every one overworld-idle (task allow-list admitted);
  docs/gen3_emerald/probes/exp_cpu_irq_bios_2026-09-27.txt -- with the client's frame_control exec
    hook: 600/600 at the IRQ vector entry R15 0x1C, mode 0x12, ARM, R14_irq 0x1F8, i.e. the IRQ
    taken right after IntrWait's HALTCNT write (strb @0x1F0; VBlankIntrWait -> IntrWait, the
    expansion's inlined WaitForVBlank, src/main.c:422-437). BIOS bytes 0x1B4..0x20F equal the RR
    receipt's (docs/gen3/probes/rr_cpu_irq_bios_2026-09-24.txt).
Values re-typed here, not read from the pack.
"""
import json
from pathlib import Path

import pytest

from tests.unit.test_gen3_safety import World

ROOT = Path(__file__).resolve().parents[2]
EXP = "emerald_expansion_28877d73"
IRQ_CPSR, INTRWAIT_LR = 0x20000092, 0x1F8


def exp_pack():
    return json.loads((ROOT / "data/games/gen3_exp/28877d73/write_checkpoint.json").read_text())[EXP]


def world(r15, cpsr, r14=0xA4, pack=None):
    w = World(EXP, "clean", pack or exp_pack())
    g = w.lua.globals()
    g.cpu.R15, g.cpu.CPSR, g.cpu.R14 = r15, cpsr, r14
    return w


BUSY = 0x2000003F   # System mode, Thumb


def test_the_center_busy_wait_is_admitted():
    """Inside the Pokemon Center the build's WaitForVBlank takes its wireless branch: frames end
    in AgbMainLoop's inlined busy-wait (docs/gen3_emerald/probes/census_exp_center_2026-09-27.txt:
    R15 0x0817AB3A/3C/3E, System, Thumb; the same with the client's hook)."""
    for r15 in (0x0817AB3A, 0x0817AB3C, 0x0817AB3E):
        w = world(r15, BUSY)
        assert w.check() is True, (hex(r15), list(w.safety.last_clauses.values()))


def test_the_irq_entry_taken_from_intrwaits_halt_is_admitted():
    """Outdoors the build halts in the BIOS: with the client's hook every frame ends on the IRQ
    entry taken from IntrWait's HALTCNT write (exp_cpu_irq_bios_2026-09-27.txt)."""
    w = world(0x1C, IRQ_CPSR, INTRWAIT_LR)
    assert w.check() is True, list(w.safety.last_clauses.values())


@pytest.mark.parametrize("r14,r15,cpsr", [
    (0x1C4, 0x1C, IRQ_CPSR),              # RR's Halt return: not this build's idle
    (0x0800_0A1C, 0x1C, IRQ_CPSR),        # the IRQ interrupted game code
    (0x0817_AB3C, 0x1C, IRQ_CPSR),        # ... even the busy-wait (census 171/1800): next frame admits
    (0x1FC, 0x1C, IRQ_CPSR),              # later in the IntrWait loop
    (INTRWAIT_LR, 0x188, IRQ_CPSR),       # inside the handler, not at the vector entry
    (INTRWAIT_LR, 0x1C, 0x200000B2),      # IRQ mode but Thumb
    (0xA4, 0x1F8, 0x2000001F),            # the hookless System-mode BIOS park: the client always hooks
    (0xA4, 0x0817AB40, BUSY),             # past the busy-wait's exit branch
    (0xA4, 0x0817AB36, BUSY),             # before it (the gWirelessCommType test)
    (0xA4, 0x0817AB3A, 0x2000001F),       # the busy-wait's address in ARM state
])
def test_every_other_frame_end_is_refused(r14, r15, cpsr):
    w = world(r15, cpsr, r14)
    assert w.check() is False and list(w.safety.last_clauses.values()) == ["cpu"]


def test_the_irq_shape_is_bound_to_this_title():
    """The G5-CPU-HARDEN rule, extended by exactly one title: the same pack under another title
    (here vanilla Emerald's) gets no IRQ admission."""
    pack = exp_pack()
    pack["title"] = "emerald"
    w = world(0x1C, IRQ_CPSR, INTRWAIT_LR, pack)
    assert w.check() is False and list(w.safety.last_clauses.values()) == ["cpu"]


def test_the_busy_wait_range_holds_no_store():
    """Admitting a frame end inside the range is safe only if no instruction there writes memory:
    the ROM's own bytes (pinned by the pack's frame_control anchor, AgbMainLoop) disassemble to the
    load/test/branch loop and its exit branch."""
    import os

    capstone = pytest.importorskip("capstone")
    art = Path(os.environ.get("SLINK_EXPANSION_ARTIFACTS", ROOT / ".cache/expansion-output/reference"))
    if not (art / "pokeemerald.gba").is_file():
        pytest.skip("reference ROM absent")
    cpu = exp_pack()["cpu"]
    rom = (art / "pokeemerald.gba").read_bytes()
    lo, hi = cpu["pc_min"], cpu["pc_max"]
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    ops = [(i.address, i.mnemonic) for i in md.disasm(rom[lo - 0x08000000:hi + 1 - 0x08000000], lo)]
    assert [m for _, m in ops] == ["ldrh", "tst", "beq", "b"], ops
    anchor = exp_pack()["anchors"]["frame_control"]
    assert anchor["address"] <= lo and hi < anchor["address"] + anchor["length"]
