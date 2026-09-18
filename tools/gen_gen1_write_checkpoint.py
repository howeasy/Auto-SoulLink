#!/usr/bin/env python3
"""Generate data/games/gen1_purergb/write_checkpoint.json from the pinned pureRGB .sym + source + ROMs.

The overworld write checkpoint (lua/gen1_write_safety.lua) admits a WRAM write only while the
main thread is parked in DelayFrame's `halt` from OverworldLoop. The vanilla file
(data/games/gen1_rby/write_checkpoint.json) is hand-pinned and not regenerated here; the
pureRGB file keeps its shape (per title: BATTLE_FLAG_ADDR / FONT_LOADED_ADDR / JOY_IGNORE_ADDR
+ write_safe{...}) and adds, under write_safe, the pure predicates (PLAN §11.2 A5):

    version                 "gen1-main-loop-purergb-v1" (the Lua branches on it)
    delay_frame_halt        DelayFrame.halt = DelayFrame+23      (`halt` / `nop`)
    delay_frame_resume      DelayFrame+24: the return address the VBlank IRQ pushes = [SP]
    delay_frame_rst         $0010 = `jp DelayFrame` (OverworldLoop reaches DelayFrame by `rst`)
    overworld_return        OverworldLoop+1 = OverworldLoopLessDelay: the only admissible [SP+2]
    delay_frame_bank        wDelayFrameBank, must read 0 at the halt
    wram_bank_register      rWBK ($FF70); its low 3 bits must be one of wram_banks
    wram_banks              [0, 1]
    expected_hex            ROM bytes at delay_frame_halt / overworld_loop / irq_vector /
                            delay_frame_rst, sliced from the built ROM after a shape check

Vanilla keys keep their meaning: irq_vector $0040 (PC at the checkpoint), vblank_entry (VBlank),
vblank_flag (hVBlankOccurred), delay_frame, overworld_loop, overworld_loop_less_delay, link_state
/ link_none, serial_status / disconnected_serial, entering_cable_club, stack_min / stack_end.

    python tools/gen_gen1_write_checkpoint.py            # rewrite
    python tools/gen_gen1_write_checkpoint.py --check    # exit 1 if the committed file is stale
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import gen1_foundation as F  # noqa: E402

FOUNDATION = "purergb"
OUT = F.data_dir(FOUNDATION) / "write_checkpoint.json"
VERSION = "gen1-main-loop-purergb-v1"
IRQ_VECTOR = 0x0040
RST_DELAY_FRAME = 0x0010
R_WBK = 0xFF70  # constants/hardware.inc `def rWBK equ $FF70`
HALT_OFFSET = 23  # DelayFrame.halt - DelayFrame, re-derived from the .sym below

SOURCE_ASSERTS = [
    ("home/vblank.asm", ".halt\n\thalt\n\tnop"),
    ("home/vblank.asm", "\tldh a, [hLoadedROMBank]\n\tld [wDelayFrameBank], a"),
    ("home/vblank.asm", "\txor a\n\tld [wDelayFrameBank], a"),
    ("home/overworld.asm", "OverworldLoop::\n\trst _DelayFrame\nOverworldLoopLessDelay::"),
    ("home/header.asm", 'SECTION "vblank", ROM0[$0040]\n\tjp VBlank'),
    ("home/header.asm", 'SECTION "rst10", ROM0[$0010]\n_DelayFrame::\n\tjp DelayFrame'),
    ("ram/wram.asm", "; the stack grows downward\n\tds $100 - 1\nwStack:: db"),
    ("constants/hardware.inc", "def rWBK equ $FF70"),
]


def _slice(rom: bytes, flat: int, want: bytes, what: str) -> str:
    got = rom[flat:flat + len(want)]
    if got != want:
        raise SystemExit(f"{what}: ROM bytes {got.hex().upper()} != {want.hex().upper()}")
    return got.hex().upper()


def build() -> dict:
    lock = F.lock(FOUNDATION)
    fnd = F.foundation(FOUNDATION)
    for rel, needle in SOURCE_ASSERTS:
        F.assert_source(FOUNDATION, rel, needle)
    out: dict = {}
    for title in fnd["titles"]:
        syms = F.parse_sym(F.sym_path(FOUNDATION, title))
        rom = F.rom_path(FOUNDATION, title).read_bytes()
        if hashlib.sha1(rom).hexdigest() != lock["outputs"][pathlib.Path(fnd["titles"][title][1]).stem]["sha1"]:
            raise SystemExit(f"{title}: built ROM sha1 differs from the lock")
        a = {n: syms[n][1] for n in ("DelayFrame", "DelayFrame.halt", "OverworldLoop", "OverworldLoopLessDelay",
                                     "VBlank", "hVBlankOccurred", "wDelayFrameBank", "wIsInBattle", "wJoyIgnore",
                                     "wFontLoaded", "wLinkState", "hSerialConnectionStatus", "wEnteringCableClub",
                                     "wStack", "GBCSetCPU2xSpeed", "_DelayFrame")}
        if a["DelayFrame.halt"] != a["DelayFrame"] + HALT_OFFSET:
            raise SystemExit(f"{title}: DelayFrame.halt is not DelayFrame+{HALT_OFFSET}")
        if a["OverworldLoopLessDelay"] != a["OverworldLoop"] + 1 or a["_DelayFrame"] != RST_DELAY_FRAME:
            raise SystemExit(f"{title}: OverworldLoop / rst $10 layout changed")
        lo, hi = a["hVBlankOccurred"] & 0xFF, a["hVBlankOccurred"] >> 8
        if hi != 0xFF:
            raise SystemExit(f"{title}: hVBlankOccurred is not in HRAM")
        # halt; nop; ldh a,[hVBlankOccurred]; and a; jr nz,.halt (-7); ret
        halt_hex = _slice(rom, a["DelayFrame.halt"], bytes((0x76, 0x00, 0xF0, lo, 0xA7, 0x20, 0xF9, 0xC9)),
                          f"{title}: DelayFrame.halt")
        # rst _DelayFrame; callfar GBCSetCPU2xSpeed = ld hl,addr; ld b,bank; rst _Bankswitch
        bank2x, addr2x = syms["GBCSetCPU2xSpeed"]
        ow_hex = _slice(rom, a["OverworldLoop"], bytes((0xD7, 0x21, addr2x & 0xFF, addr2x >> 8, 0x06, bank2x, 0xC7)),
                        f"{title}: OverworldLoop")
        irq_hex = _slice(rom, IRQ_VECTOR, bytes((0xC3, a["VBlank"] & 0xFF, a["VBlank"] >> 8)), f"{title}: $0040")
        rst_hex = _slice(rom, RST_DELAY_FRAME, bytes((0xC3, a["DelayFrame"] & 0xFF, a["DelayFrame"] >> 8)),
                         f"{title}: $0010")
        out[title] = {
            "BATTLE_FLAG_ADDR": a["wIsInBattle"],
            "FONT_LOADED_ADDR": a["wFontLoaded"],
            "JOY_IGNORE_ADDR": a["wJoyIgnore"],
            "write_safe": {
                "version": VERSION,
                "irq_vector": IRQ_VECTOR,
                "vblank_entry": a["VBlank"],
                "vblank_flag": a["hVBlankOccurred"],
                "delay_frame": a["DelayFrame"],
                "delay_frame_halt": a["DelayFrame.halt"],
                "delay_frame_resume": a["DelayFrame.halt"] + 1,
                "delay_frame_rst": RST_DELAY_FRAME,
                "delay_frame_bank": a["wDelayFrameBank"],
                "overworld_loop": a["OverworldLoop"],
                "overworld_loop_less_delay": a["OverworldLoopLessDelay"],
                "overworld_return": a["OverworldLoop"] + 1,
                "wram_bank_register": R_WBK,
                "wram_banks": [0, 1],
                "link_state": a["wLinkState"],
                "link_none": 0,
                "serial_status": a["hSerialConnectionStatus"],
                "disconnected_serial": 0xFF,
                "entering_cable_club": a["wEnteringCableClub"],
                "stack_min": a["wStack"] - 0xFF,  # `ds $100 - 1` then `wStack:: db`: the stack grows down into it
                "stack_end": a["wStack"],
                "expected_hex": {"delay_frame_halt": halt_hex, "overworld_loop": ow_hex,
                                 "irq_vector": irq_hex, "delay_frame_rst": rst_hex},
            },
        }
    return out


def render(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = ap.parse_args()
    text = render(build())
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(REPO)} is stale; run tools/gen_gen1_write_checkpoint.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(REPO)} is current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    ws = json.loads(text)
    print(f"wrote {OUT.relative_to(REPO)}: " + ", ".join(
        f"{t} DelayFrame.halt={v['write_safe']['delay_frame_halt']:#06x}" for t, v in ws.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
