#!/usr/bin/env python3
"""Generate data/games/gen3_{frlg,rr}/write_checkpoint.json from the pinned pret .sym + the ROMs.

The Gen 3 overworld write checkpoint is the Gen 1 idea (lua/gen1_write_safety.lua,
data/games/gen1_rby/write_checkpoint.json) carried to GBA: a SOURCE predicate that admits a
host write only while no member of the writer inventory (docs/gen3_write_checkpoint.md) can be
in progress.  Nothing here is an observation -- every address is a symbol from
data/gen3/pret/*.sym (pret/pokefirered c75f3523, provenance.json) and every ROM anchor is
sliced from the admitted ROM at that symbol.

Radical Red ships no symbols, so each FRLG fact is re-derived from the RR binary before it is
allowed into the RR pack:

  * a code symbol is VERIFIED when the whole FR function body is byte-identical at the same
    address in both RR ROMs (clean 4.1 base and the SLink companion build);
  * a data symbol is VERIFIED when the literal-pool word(s) that hold its address inside a
    named FR witness function still hold the same address at the same offsets in both RR ROMs
    (this survives a patched instruction in the witness -- e.g. the companion's hook inside
    CallCallbacks -- because only the pool word is asserted).

An RR entry that fails its check is NOT emitted; it is reported here and listed as UNVERIFIED
in docs/gen3_write_checkpoint.md.  Fail-closed: a missing fact is a missing predicate, never a
guessed one.

    python tools/gen_gen3_write_checkpoint.py            # rewrite both packs
    python tools/gen_gen3_write_checkpoint.py --check    # exit 1 if a committed file is stale
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYM_DIR = ROOT / "data" / "gen3" / "pret"
VERSION = "gen3-overworld-v1"
ROM_BASE = 0x08000000

# (pack, title, kind) -> (path, sha1).  Duplicated from tools/pin_gen3_site.py ROM_SPECS on
# purpose: that file is a different P2 lease.  Fold the two together once both have landed.
ROMS = {
    ("gen3_frlg", "firered", "clean"): (
        pathlib.Path("E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba"),
        "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"),
    ("gen3_frlg", "leafgreen", "clean"): (
        pathlib.Path("E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba"),
        "574fa542ffebb14be69902d1d36f1ec0a4afd71e"),
    ("gen3_rr", "radical_red", "clean"): (
        pathlib.Path("E:/Google Drive/SLink/Pokemon - Radical Red.gba"),
        "964f951a0fdaf209e4ea1344883ef0d557bb3a80"),
    ("gen3_rr", "radical_red", "companion"): (
        ROOT / "patch" / "build" / "slink_RR.gba",
        "b7d1e0756fcc66575878affc8f7b95c45386bb1c"),
}

# pack -> {title: (sym file, kinds...)}.  RR reads the FireRed symbols and proves each one
# against its own ROMs; emerald / firered_ap are not admitted (PLAN s0) and get no checkpoint.
PACKS = {
    "gen3_frlg": {"firered": ("pokefirered.sym", ("clean",)),
                  "leafgreen": ("pokeleafgreen.sym", ("clean",))},
    "gen3_rr": {"radical_red": ("pokefirered.sym", ("clean", "companion"))},
}

# name -> (symbol, offset into it, length or None = the symbol's own size)
ANCHORS = {
    "cb2_overworld": ("CB2_Overworld", 0, None),
    "cb1_overworld": ("CB1_Overworld", 0, None),
    "run_tasks": ("RunTasks", 0, None),
    # the per-frame exec site the P1 probe measured (docs/gen3/probes/hooks_*_2026-09-21.txt
    # REGISTER frame addr=0x0800051A): CallCallbacks' `bl RunHelpSystemCallback`.
    "frame_control": ("CallCallbacks", 0x0A, 8),
    "try_saving_data": ("TrySavingData", 0, None),
}

# name -> (symbol, offset, width, mask, expect).  mask None = compare the whole read.
PREDICATES = {
    # gMain.callback1 / .callback2 (include/main.h: +0x000, +0x004); expect is the Thumb pointer
    "callback1": ("gMain", 0x000, 4, None, "CB1_Overworld"),
    "callback2": ("gMain", 0x004, 4, None, "CB2_Overworld"),
    # struct Main +0x439 bitfield: bit0 oamLoadDisabled, bit1 inBattle
    "in_battle": ("gMain", 0x439, 1, 0x02, 0),
    # struct PaletteFadeControl +4 bitfield, active is bit 31 -> byte +7 bit 7
    "palette_fade_active": ("gPaletteFade", 0x007, 1, 0x80, 0),
    # src/script.c: field controls are locked for the whole life of a script
    "field_controls_locked": ("sLockFieldControls", 0, 1, None, 0),
    # src/script.c CONTEXT_RUNNING=0, CONTEXT_WAITING=1, CONTEXT_SHUTDOWN=2
    "script_context_status": ("sGlobalScriptContextStatus", 0, 1, None, 2),
    # src/start_menu.c: non-NULL for the whole save dialog FSM, which is what calls TrySavingData
    "save_dialog_cb": ("sSaveDialogCB", 0, 4, None, 0),
    # src/save.c Task_LinkFullSave sets this for the duration of the link full save
    "soft_reset_disabled": ("gSoftResetDisabled", 0, 1, None, 0),
    "link_callback": ("gLinkCallback", 0, 4, None, 0),
    "link_transferring": ("gLinkTransferringData", 0, 1, None, 0),
    # src/link.c:421 CloseLink / :410 OpenLink clear it; :540 (cable) and link_rfu_2.c:1879,2065
    # (wireless) set it once the partner's player data is in -- non-zero for a whole link session.
    # NOT gWirelessCommType: that is the transport selector (0 cable, 1 RFU), set by the title
    # menu's adapter probe (main_menu.c:573 -> link.c:243-261) and sticky (CloseLink leaves it),
    # so it is 1 for the whole session on hardware with the adapter (receipt
    # docs/gen3/probes/checkpoint_fr_parcel_lineage_2026-09-22.txt).  The pre-exchange window is
    # link_callback + callback1 + the task allow-list.
    "link_players_received": ("gReceivedRemoteLinkPlayers", 0, 1, None, 0),
}

# data symbol -> the FR function whose literal pool pins it (used only to prove RR)
WITNESS = {
    "gMain": "CallCallbacks",
    "gTasks": "RunTasks",
    "gPaletteFade": "CB2_Overworld",
    "sLockFieldControls": "ArePlayerFieldControlsLocked",
    "sGlobalScriptContextStatus": "ScriptContext_IsEnabled",
    "sSaveDialogCB": "RunSaveDialogCB",
    "gSoftResetDisabled": "AgbMain",
    "gLinkTransferringData": "AgbMain",
    "gLinkCallback": "ClearLinkCallback",
    "gReceivedRemoteLinkPlayers": "CloseLink",
}

# Every task that is legitimately running while the player just stands in the overworld:
# SetUpFieldTasks (src/field_tasks.c:84-94) and StartWeather (src/field_weather.c:146-170),
# both reached from Overworld resume (src/overworld.c:2118-2121, 2444-2446).  Task_WeatherInit
# is deliberately absent: it is the transient that becomes Task_WeatherMain, and an in-flight
# initialiser is not an idle frame.
ALLOWED_TASKS = ("Task_RunPerStepCallback", "Task_RunTimeBasedEvents", "Task_WeatherMain")

# include/task.h: struct Task { TaskFunc func; bool8 isActive; u8 prev, next, priority; s16 data[16]; }
TASK_STRUCT_SIZE = 0x28
TASK_COUNT = 16

# The frame-end "parked CPU" clause is per title: one R15 range + CPSR mode + T bit.
#
# FRLG idles in ROM, not the BIOS: AgbMain ends every frame in WaitForVBlank (pret/pokefirered
# c75f3523 src/main.c:216 the call, :462-468 the body -- a busy-wait on gMain.intrCheck), so the
# range is that symbol's whole body from the title's own .sym, System mode (0x1F), Thumb.  FR
# census (docs/gen3/probes/census_fr_overworld_2026-09-21.txt): 1707/1800 frame ends at R15
# 0x080008AC..0x080008B4, mode 0x1F, T=1.  The other 93 landed in the BIOS IRQ vector (R15=0x1C,
# mode 0x12, T=0) and are refused on purpose -- the next parked frame admits.  LG has no census,
# so its block carries no observed_pc.
PARKED_SYMBOL = "WaitForVBlank"
FRLG_CENSUS = {"firered": (0x080008AC, "docs/gen3/probes/census_fr_overworld_2026-09-21.txt")}
# RR (CFRU) parks in the BIOS instead (docs/gen3/probes/census_rr_overworld_2026-09-21.txt):
# 1800/1800 frames at R15=0x000001C4 with CPSR mode 0x1F (System) and T=0.
RR_CPU = {"mode": 0x1F, "thumb": 0, "pc_min": 0x00000000, "pc_max": 0x00003FFF,
          "observed_pc": 0x000001C4,
          "census": "docs/gen3/probes/census_rr_overworld_2026-09-21.txt"}


def cpu_clause(title: str, syms, is_rr: bool) -> dict:
    if is_rr:
        return dict(RR_CPU)
    if PARKED_SYMBOL not in syms:
        raise SystemExit(f"{title}: missing parked-CPU symbol {PARKED_SYMBOL}")
    addr, size = syms[PARKED_SYMBOL]
    cpu = {"mode": 0x1F, "thumb": 1, "pc_min": addr, "pc_max": addr + size - 1,
           "symbol": PARKED_SYMBOL}
    if title in FRLG_CENSUS:
        pc, census = FRLG_CENSUS[title]
        if not addr <= pc < addr + size:
            raise SystemExit(f"{title}: census PC {pc:#010x} is outside {PARKED_SYMBOL}")
        cpu.update(observed_pc=pc, census=census)
    return cpu

# RR relocates the save blocks; these come from the admitted pack profile, not from a symbol.
RR_POINTERS = {"gSaveBlock1Ptr": "SB1_PTR_ADDR", "gSaveBlock2Ptr": "SB2_PTR_ADDR"}


def parse_sym(path: pathlib.Path) -> dict[str, tuple[int, int]]:
    """`address l/g size name` -> {name: (address, size)}; the first spelling wins."""
    out: dict[str, tuple[int, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1] in ("l", "g"):
            out.setdefault(parts[3], (int(parts[0], 16), int(parts[2], 16)))
    if not out:
        raise SystemExit(f"{path}: no symbols parsed")
    return out


def load_rom(pack: str, title: str, kind: str) -> bytes:
    path, sha1 = ROMS[(pack, title, kind)]
    if not path.exists():
        raise SystemExit(f"ROM not present at {path}")
    rom = path.read_bytes()
    if hashlib.sha1(rom).hexdigest() != sha1:
        raise SystemExit(f"{path}: sha1 differs from the pinned dump")
    return rom


def body(rom: bytes, address: int, length: int) -> bytes:
    off = address - ROM_BASE
    if off < 0 or off + length > len(rom):
        raise SystemExit(f"{address:#010x}+{length} is outside the ROM")
    return rom[off:off + length]


def pool_offsets(blob: bytes, word: int) -> list[int]:
    """Word-aligned offsets inside blob whose little-endian u32 equals word."""
    return [i for i in range(0, len(blob) - 3, 4) if struct.unpack_from("<I", blob, i)[0] == word]


def verify_code(syms, roms: dict[str, bytes], name: str) -> bool:
    """The FR body of `name` is byte-identical at the same address in every RR ROM."""
    addr, size = syms[name]
    if not size:
        raise SystemExit(f"{name}: zero-size symbol cannot be byte-verified")
    want = body(roms["_fr"], addr, size)
    return all(body(rom, addr, size) == want for key, rom in roms.items() if key != "_fr")


def verify_data(syms, roms: dict[str, bytes], name: str) -> bool:
    """The literal-pool words that pin `name` inside its witness are unchanged in every RR ROM."""
    witness = WITNESS.get(name)
    if witness is None:
        return False
    waddr, wsize = syms[witness]
    fr = body(roms["_fr"], waddr, wsize)
    offs = pool_offsets(fr, syms[name][0])
    if not offs:
        raise SystemExit(f"{name} is not in {witness}'s literal pool -- witness table is wrong")
    return all(all(body(rom, waddr + o, 4) == fr[o:o + 4] for o in offs)
               for key, rom in roms.items() if key != "_fr")


def build_title(pack: str, title: str, sym_file: str, kinds: tuple[str, ...]) -> tuple[dict, list[str]]:
    syms = parse_sym(SYM_DIR / sym_file)
    roms = {kind: load_rom(pack, title, kind) for kind in kinds}
    is_rr = pack == "gen3_rr"
    unverified: list[str] = []
    if is_rr:
        # every RR fact is proven against the RR binaries, with FireRed as the reference body
        roms["_fr"] = load_rom("gen3_frlg", "firered", "clean")

    def ok_code(name: str) -> bool:
        if not is_rr or verify_code(syms, roms, name):
            return True
        unverified.append(f"code {name} @ {syms[name][0]:#010x}")
        return False

    def ok_data(name: str) -> bool:
        if not is_rr or verify_data(syms, roms, name):
            return True
        unverified.append(f"data {name} @ {syms[name][0]:#010x}")
        return False

    anchors = {}
    for key, (symbol, offset, length) in ANCHORS.items():
        addr, size = syms[symbol]
        length = size if length is None else length
        # frame_control is the companion's own hook slot: its bytes differ per build, so the
        # symbol is proven through gMain's pool word instead of a whole-body comparison.
        proven = ok_data("gMain") if key == "frame_control" else ok_code(symbol)
        if not proven:
            continue
        anchors[key] = {
            "symbol": symbol, "address": addr, "rom_offset": addr - ROM_BASE + offset,
            "length": length,
            "expected_hex": {kind: body(rom, addr + offset, length).hex().upper()
                             for kind, rom in roms.items() if kind != "_fr"},
        }

    predicates = {}
    for key, (symbol, offset, width, mask, expect) in PREDICATES.items():
        if not ok_data(symbol):
            continue
        entry = {"symbol": symbol, "address": syms[symbol][0], "offset": offset, "width": width}
        if mask is not None:
            entry["mask"] = mask
        if isinstance(expect, str):
            if not ok_code(expect):
                continue
            entry["expect_symbol"] = expect
            entry["expect"] = syms[expect][0] | 1  # Thumb pointer, as gMain stores it
        else:
            entry["expect"] = expect
        predicates[key] = entry

    allowed = {}
    for name in ALLOWED_TASKS:
        if ok_code(name):
            allowed[name] = syms[name][0]

    out = {
        "version": VERSION,
        "sym": sym_file,
        "anchors": anchors,
        "predicates": predicates,
        "tasks": {"symbol": "gTasks", "struct_size": TASK_STRUCT_SIZE, "count": TASK_COUNT,
                  "func_offset": 0, "is_active_offset": 4,
                  "allowed_overworld_tasks": allowed},
        "cpu": cpu_clause(title, syms, is_rr),
        "pointers": {},
    }
    if ok_data("gTasks"):
        out["tasks"]["address"] = syms["gTasks"][0]
    else:  # fail-closed: no task base, no allow-list
        out["tasks"]["allowed_overworld_tasks"] = {}

    if is_rr:
        profile = json.loads((ROOT / "data" / "games" / pack / "profile.json").read_text("utf-8"))
        ram = profile["titles"][title]["ram"]
        for name, field in RR_POINTERS.items():
            if ram.get(field) is not None:
                out["pointers"][name] = {"address": ram[field], "source": f"profile.ram.{field}"}
        # RR (CFRU) has no gPokemonStoragePtr: storage sits at a fixed EWRAM base.
        if ram.get("POKEMON_STORAGE_BASE") is not None:
            out["pointers"]["pokemon_storage_base"] = {
                "address": ram["POKEMON_STORAGE_BASE"], "source": "profile.ram.POKEMON_STORAGE_BASE"}
    else:
        for name in ("gSaveBlock1Ptr", "gSaveBlock2Ptr", "gPokemonStoragePtr"):
            out["pointers"][name] = {"symbol": name, "address": syms[name][0], "source": sym_file}
    return out, unverified


def build(pack: str) -> tuple[dict, list[str]]:
    out, unverified = {}, []
    for title, (sym_file, kinds) in PACKS[pack].items():
        out[title], bad = build_title(pack, title, sym_file, kinds)
        unverified += [f"{title}: {row}" for row in bad]
    return out, unverified


def out_path(pack: str) -> pathlib.Path:
    return ROOT / "data" / "games" / pack / "write_checkpoint.json"


def render(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if a committed file is stale")
    args = ap.parse_args()
    rc = 0
    for pack in PACKS:
        target, unverified = build(pack)
        text = render(target)
        path = out_path(pack)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                print(f"{path.relative_to(ROOT)} is stale; run tools/gen_gen3_write_checkpoint.py",
                      file=sys.stderr)
                rc = 1
            else:
                print(f"{path.relative_to(ROOT)} is current")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT)}: " + ", ".join(
                f"{t} {len(v['anchors'])} anchors, {len(v['predicates'])} predicates, "
                f"{len(v['tasks']['allowed_overworld_tasks'])} tasks" for t, v in target.items()))
        for row in unverified:
            print(f"  UNVERIFIED (not emitted) {row}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
