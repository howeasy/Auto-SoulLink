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
#
# C4-UR (owner ruling PLAN s0 "Writes inside Pokemon Centers"): every Center 1F's ON_RESUME is
# CableClub_OnResume -> special InitUnionRoom (data/scripts/cable_club.inc:1120-1122), which
# leaves the rev-0 Union Room *background* set running: Task_InitUnionRoom (src/union_room.c:
# 3515-3604, parks in state 3 forever), Task_SearchForChildOrParent (:3714-3745) and
# Task_UnionRoomListen (src/link_rfu_2.c:505-564, via :2727-2742).  None of them, nor anything
# they reach, names gPlayerParty/gPlayerPartyCount/gPokemonStoragePtr or a save/flash routine;
# their save-block access is read-only (link_rfu_3.c:850-873, :1178-1192, link_rfu_2.c:2151-2154).
# Every step out of "background only" creates a task that stays OFF this list (Task_PlayerExchange
# /Chat link_rfu_2.c:539-559, Task_TryConnectToUnionRoomParent :2519, Task_RunUnionRoom
# union_room.c:2579-2584, Task_StartActivity, Task_TryBecomeLinkLeader/Task_TryJoinLinkGroup)
# or trips a predicate (gReceivedRemoteLinkPlayers, callback1/2, script lock).
CENTER_UNION_ROOM_TASKS = ("Task_InitUnionRoom", "Task_SearchForChildOrParent", "Task_UnionRoomListen")
ALLOWED_TASKS = ("Task_RunPerStepCallback", "Task_RunTimeBasedEvents", "Task_WeatherMain") \
    + CENTER_UNION_ROOM_TASKS
ALLOWED_TASKS_SOURCE = ("pret c75f3523: src/field_tasks.c:84-94, src/field_weather.c:146-170; "
                        "Center 1F Union Room background (C4-UR): data/scripts/cable_club.inc:1120-1122, "
                        "src/union_room.c:3515-3604,3714-3745, src/link_rfu_2.c:505-564,2727-2742; "
                        "RR: FR body byte-identical at the same address in every RR ROM")

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

# ── the RR save-block pointers, read out of the ROM's own setter (card C3-33) ─────────────────
# pret/pokefirered c75f3523 src/load_save.c:69-83 SetSaveBlocksPointers stores &<object> + offset
# into three IWRAM pointer variables.  The *address* of the function is the FireRed symbol (RR is
# an FR rebuild and keeps it there), but no pointer address is taken from the symbol table: the
# pool words are read out of the body after it is signature-checked, so a build that moved or
# reshaped the setter fails closed instead of shipping an address nobody verified.
#
# The old client's radical_red profile ships 0x03003840 / 0x03003838 for these two, which is
# neither of them: those addresses are a literal-pool constant (`&gSaveBlock1` / `&gSaveBlock2`)
# inside IntrMain_Buffer, the DMA'd copy of the intr_main blob at ROM 0x08000248.  They read
# correctly on today's RR only because its offset is fixed at 0, so the constant equals the live
# pointer; nothing enforces that, and it cannot be a pack's evidence.
SETTER_SYMBOL = "SetSaveBlocksPointers"
# ROM file 0x4C058: push {r4,r5,lr}; ldr r4,[pc,#0x30]; ldr r5,[r4]; bl Random
SETTER_PREFIX = bytes.fromhex("30b50c4c2568f8f733ff")
SETTER_BODY = 0x34          # the body; its six-word literal pool starts here (ROM file 0x4C08C)
SETTER_OFFSET_AT = 0x0A
# `movs r1,#0` twice, where vanilla FR has `movs r1,#0x7C; ands r1,r0` (load_save.c:75).  RR's
# save-block offset is therefore always 0: the pointer values never move, while the legacy
# 0x03003840 alias inside IntrMain_Buffer would not move with them if they did
# (docs/gen3/research/checkpoint_unreached_states.md §4).
SETTER_OFFSET_BYTES = bytes.fromhex("00210021")
# EWRAM object -> the pointer variable the setter stores its address into.  The three objects are
# the pool's EWRAM words; docs/gen3/research/rr_save_layout.md:55-68 validates them against the
# bytes the real save file has at those bases.
SAVEBLOCK_BASES = {0x0202552C: "gSaveBlock1Ptr", 0x02024588: "gSaveBlock2Ptr",
                   0x02029314: "gPokemonStoragePtr"}
SAVEBLOCK_POINTERS = ("gSaveBlock1Ptr", "gSaveBlock2Ptr", "gPokemonStoragePtr")
IWRAM_RANGE = (0x03000000, 0x03008000)
POOL_SOURCE = "rom:SetSaveBlocksPointers pool"


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


PLAYER_CONTROLLER_OBJ = "src/battle_controller_player.o"


def text_span(map_path: pathlib.Path, obj: str) -> tuple[int, int]:
    """The [start, end) of obj's .text in a pret linker map."""
    for line in map_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == ".text" and parts[3] == obj:
            start = int(parts[1], 16)
            return start, start + int(parts[2], 16)
    raise SystemExit(f"{map_path}: no .text for {obj}")


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


def setter_pairs(address: int, code: bytes, rom: bytes) -> list[tuple[int, int]]:
    """[(pointer variable, &object)] for every store in a SetSaveBlocksPointers body.

    Only the three instruction forms this body uses are decoded -- the Thumb short literal load
    (`ldr rN,[pc,#imm8]`), the three-register add (`adds rD,rA,rB`) and the zero-offset short
    store (`str rM,[rN]`) -- and a 32-bit `bl` is stepped over whole.  The caller
    signature-checks the body first, so an unrecognised form cannot quietly mis-pair; a store
    whose registers do not resolve to two pool words is dropped, and the caller requires all
    three pairs to be present.
    """
    reg: dict[int, int] = {}            # register -> the literal word it carries
    out: list[tuple[int, int]] = []
    at = 0
    while at + 1 < len(code):
        op = int.from_bytes(code[at:at + 2], "little")
        if op & 0xF800 == 0xF000:                                   # first half of a 32-bit bl
            at += 4
            continue
        if 0x4800 <= op <= 0x4FFF:                                  # ldr rN,[pc,#imm8*4]
            n, imm = (op >> 8) & 7, (op & 0xFF) * 4
            word_at = ((address + at + 4) & ~3) + imm
            reg[n] = struct.unpack_from("<I", rom, word_at - ROM_BASE)[0]
        elif op & 0xF800 == 0x1800:                                 # adds rD,rA,rB
            d, a, b = op & 7, op >> 3 & 7, op >> 6 & 7
            if a in reg:
                reg[d] = reg[a]
            elif b in reg:
                reg[d] = reg[b]
            else:
                reg.pop(d, None)
        elif op & 0xF800 == 0x6000 and ((op >> 6) & 0x1F) == 0:      # str rM,[rN]
            n, m = (op >> 3) & 7, op & 7
            if n in reg and m in reg:
                out.append((reg[n], reg[m]))
        at += 2
    return out


def rr_saveblock_pointers(syms: dict[str, tuple[int, int]], rom: bytes) -> dict[str, int]:
    """{gSaveBlock*Ptr: IWRAM address} for RR, read out of the setter's literal pool.

    Named SystemExit -- never a guess -- when the ROM is not the pinned RR build: the setter's
    address comes from the pret .sym, so a build that moved or reshaped it, or that restored the
    relocation mask, invalidates every pointer address this pack names and has to be re-pinned
    by hand.
    """
    address, _size = syms[SETTER_SYMBOL]
    code = body(rom, address, SETTER_BODY)
    if code[:len(SETTER_PREFIX)] != SETTER_PREFIX:
        raise SystemExit(
            f"rr_saveblock_pointers: {SETTER_SYMBOL} at {address:#010x} is not the pinned body "
            f"(got {code[:len(SETTER_PREFIX)].hex()}, expected {SETTER_PREFIX.hex()}); the RR "
            f"save-block pointers must be re-pinned before regenerating")
    offset = code[SETTER_OFFSET_AT:SETTER_OFFSET_AT + 4]
    if offset != SETTER_OFFSET_BYTES:
        raise SystemExit(
            f"rr_saveblock_pointers: {SETTER_SYMBOL} at {address:#010x} no longer fixes the "
            f"save-block offset to 0 at +{SETTER_OFFSET_AT:#x} (got {offset.hex()}, expected "
            f"{SETTER_OFFSET_BYTES.hex()}): the pointer values would relocate on every battle "
            f"start and map load, and the legacy 0x03003840 alias would not follow them")
    out: dict[str, int] = {}
    for variable, base in setter_pairs(address, code, rom):
        name = SAVEBLOCK_BASES.get(base)
        if name is None or not IWRAM_RANGE[0] <= variable < IWRAM_RANGE[1]:
            raise SystemExit(
                f"rr_saveblock_pointers: {SETTER_SYMBOL} at {address:#010x} stores "
                f"{variable:#010x} <- {base:#010x}, which is not a save-block pointer")
        out[name] = variable
    missing = [name for name in SAVEBLOCK_POINTERS if name not in out]
    if missing:
        raise SystemExit(
            f"rr_saveblock_pointers: {SETTER_SYMBOL} at {address:#010x} yielded {sorted(out)}; "
            f"the setter no longer names {missing}")
    return out


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
                  "allowed_overworld_tasks": allowed, "source": ALLOWED_TASKS_SOURCE},
        "cpu": cpu_clause(title, syms, is_rr),
        "pointers": {},
    }
    if ok_data("gTasks"):
        out["tasks"]["address"] = syms["gTasks"][0]
    else:  # fail-closed: no task base, no allow-list
        out["tasks"]["allowed_overworld_tasks"] = {}

    profile = json.loads((ROOT / "data" / "games" / pack / "profile.json").read_text("utf-8"))
    out["battle"], battle_dropped = battle_block(title, syms, is_rr, profile)
    unverified += [f"battle {row}" for row in battle_dropped]
    if not is_rr:  # four HandleInputChooseAction spellings; parse_sym must have kept the player's
        lo, hi = text_span(SYM_DIR / sym_file.replace(".sym", ".map"), PLAYER_CONTROLLER_OBJ)
        if not lo <= syms["HandleInputChooseAction"][0] < hi:
            raise SystemExit(f"{title}: HandleInputChooseAction is not {PLAYER_CONTROLLER_OBJ}'s")
    if is_rr:
        native = native_block(profile)
        if native is not None:
            out["native"] = native
    out["sound"] = sound_block(syms, is_rr)

    if is_rr:
        ram = profile["titles"][title]["ram"]
        # Card C3-33: the three pointers come out of the ROM's own setter, not out of the old
        # client's legacy profile (whose 0x03003840/0x03003838 are literal-pool constants inside
        # IntrMain_Buffer).  Both RR artifacts must agree -- the companion patch is additive.
        derived = rr_saveblock_pointers(syms, roms["clean"])
        for kind, rom in roms.items():
            if kind != "_fr" and rr_saveblock_pointers(syms, rom) != derived:
                raise SystemExit(f"{title}/{kind}: the save-block pointers differ from the clean ROM")
        for name in SAVEBLOCK_POINTERS:
            out["pointers"][name] = {"address": derived[name], "source": POOL_SOURCE}
        # RR (CFRU) keeps box storage in a fixed EWRAM struct as well as behind the pointer; the
        # struct base stays a separate fact for the reads layer's cross-check.
        if ram.get("POKEMON_STORAGE_BASE") is not None:
            out["pointers"]["pokemon_storage_base"] = {
                "address": ram["POKEMON_STORAGE_BASE"], "source": "profile.ram.POKEMON_STORAGE_BASE"}
        # The setter itself, byte-pinned per artifact.  safety.lua re-reads every anchor's bytes
        # from the running ROM, so a build that moved the setter -- or that restored the
        # relocation mask -- is refused at runtime as well as here.
        setter_addr, setter_size = syms[SETTER_SYMBOL]
        out["anchors"]["saveblocks_setter"] = {
            "symbol": SETTER_SYMBOL, "address": setter_addr,
            "rom_offset": setter_addr - ROM_BASE, "length": setter_size,
            "expected_hex": {kind: body(rom, setter_addr, setter_size).hex().upper()
                             for kind, rom in roms.items() if kind != "_fr"},
        }
    else:
        for name in ("gSaveBlock1Ptr", "gSaveBlock2Ptr", "gPokemonStoragePtr"):
            out["pointers"][name] = {"symbol": name, "address": syms[name][0], "source": sym_file}
    return out, unverified


# ── C4-B2: the battle / native / sound blocks ────────────────────────────────────────────────
# The overworld block above stays the G3-signed predicate.  These are the *additional* reason
# sets the design (docs/gen3/research/battle_write_predicate.md) specifies.  Every emitted value
# carries a source: FR/LG from the title's own .sym, RR from RR-PROD facts only (the profile's
# ram keys and the old client's constants) -- a FireRed sym address is never asserted for RR.
#
# compare semantics (safety.lua evaluates them):
#   eq       value == expect                (mask applied first when given)
#   eq_symbol  the symbol's address | 1     (a Thumb function pointer, as gMain stores them)
#   nonzero  value ~= 0
#   lt       value <  value_field           (the commit guard; indexed by args.battler)

# C4-BW: the input wait is NOT exec-idle. STATE_BEFORE_ACTION_CHOSEN emits CHOOSE_ACTION and
# MarkBattlerForControllerExec(0) sets bit 0 (pret battle_main.c:3133-3135, battle_util.c:185-191);
# only PlayerBufferExecCompleted clears it, once the player has CHOSEN (battle_controller_player.c
# :186-200). "flags == 0" admitted only the frame after a committed choice -- the choice already in
# gBattleBufferB, possibly a SWITCH into the mon being zeroed -- and never the parked menu (live
# linked_faint_active_gen3 r3, 123c6c45: a bench force_faint held 99 s on this clause).
# The window is the parked menu itself: exactly battler 0's input exec pending (the opponent AI
# completes inside its own frame; in doubles battler 2 is only asked after battler 0 reaches
# STATE_WAIT_ACTION_CONFIRMED, battle_main.c:3110-3113, so flags == 1 is battler 0's menu only), and
# battler 0's controller is the PLAYER's HandleInputChooseAction. That pin also refuses the
# HandleChooseActionAfterDma3 draw frames, the move/target submenus, the bag and party menus, and
# the Safari / Oak-old-man / Pokedude controllers (Teachy TV swaps gPlayerParty: teachy_tv.c:1178).
BATTLE_CLAUSES_FRLG = (
    ("battle_main_func", "gBattleMainFunc", 0, 4, None, "eq_symbol", "HandleTurnActionSelectionState"),
    ("battle_comm_0", "gBattleCommunication", 0, 1, None, "eq", 1),
    ("battle_exec_flags_input", "gBattleControllerExecFlags", 0, 4, None, "eq", 1),
    ("battle_input_controller", "gBattlerControllerFuncs", 0, 4, None, "eq_symbol", "HandleInputChooseAction"),
    ("battle_not_link", "gBattleTypeFlags", 0, 4, 0x02, "eq", 0),
    ("battle_engine_loaded", "gBattleMons", 0x2C, 2, None, "nonzero", None),
    ("battle_outcome_open", "gBattleOutcome", 0, 1, None, "eq", 0),
)
BATTLE_CLAUSES_RR = (
    # (name, profile.ram key, offset, width, mask, compare, expect)
    # The expect for battle_main_func is a ROM pin, not a FireRed sym value: CFRU's
    # HandleTurnActionSelectionState is byte-anchored at 0x08014041 (profile.rom
    # HANDLE_TURN_ACTION_SELECTION_ADDR; the expanded code at file 0x1070626/28 loads the pools
    # 0x03004F84 / 0x08014041 and stores the callback).  Read, never retyped.
    ("battle_main_func", "BATTLE_MAIN_FUNC_ADDR", 0, 4, None, "eq_rom", "HANDLE_TURN_ACTION_SELECTION_ADDR"),
    ("battle_comm_0", "BATTLE_COMM_ADDR", 0, 1, None, "eq", 1),
    ("battle_exec_flags_idle", "BATTLE_CONTROLLER_EXEC_FLAGS_ADDR", 0, 4, None, "eq", 0),
    ("battle_not_link", "BATTLE_TYPE_ADDR", 0, 4, 0x02, "eq", 0),
    ("battle_engine_loaded", "BATTLE_MONS_ADDR", 0x2C, 2, None, "nonzero", None),
    ("battle_outcome_open", "BATTLE_OUTCOME_ADDR", 0, 1, None, "eq", 0),
)
# Both RR callback and controller-exec word are now ROM-pinned in profile.json.
BATTLE_DROPPED_RR = ()
BATTLE_COMMIT_GUARD = {"symbol": "gBattleCommunication", "offset": 0, "width": 1, "compare": "lt",
                       "value": 3, "indexed_by": "battler"}
BATTLE_COMMIT_GUARD_RR = {"symbol": "BATTLE_COMM_ADDR", "offset": 0, "width": 1, "compare": "lt",
                          "value": 3, "indexed_by": "battler"}
BATTLE_SOURCE_FRLG = "pokefirered.sym/pokeleafgreen.sym (data address); pret src/battle_main.c"
BATTLE_SOURCE_RR = "profile.ram.%s (old client production path)"

# The companion arena, from profile.native (addresses) + patch/src/ADDRESSES.md:59-77 (sizes).
# safety.lua checks every native write lands inside one of these spans.
NATIVE_ARENA = (
    ("BASE", 64, "mailbox ABI v1"),
    ("SW", 8, "SwapState"),
    ("GH", 44, "GhostState"),
    ("CALC_OFF", 1, "SLINK_CALC_OFF"),
    ("TEXT_BUF", 256, "SLINK_TEXT_BUF"),
    ("BLOB_BUF", 600, "SLINK_BLOB_BUF"),
    ("MENU_BUF", 112, "SLINK_MENU_BUF"),
    ("BATTLE_NOTIF", 8, "BattleNotif"),
    ("GHOST_PAL_BUF", 32, "GHOST_PAL_BUF"),
    ("EVR", 52, "EvRing"),
    ("INFO", 264, "SlinkInfo"),
)
NATIVE_LAYOUT = {"opcode_off": 6, "status_off": 10, "busy": 1, "abi_off": 4,
                 "info_drawn_off": 1, "info_ack_off": 2}
NATIVE_SOURCE = "profile.native + patch/src/ADDRESSES.md:59-77"

# m4a: the exact fields the old client's M.playSE pokes (lua/memory_gba.lua:2003-2055).  The
# clause set is {the driver is up (ident magic), the player/track are in IWRAM}; no save or
# transition clause is needed -- a Lua write lands between frames, so the engine cannot observe a
# half-written player, and the ISR skips a player whose ident is the lock value by design
# (pret include/gba/m4a_internal.h:185-188, src/m4a.c:50-66,209-215).
SOUND_FIELDS = (
    ("songHeader", 0x00, 4), ("status", 0x04, 4), ("trackCount", 0x08, 1),
    ("priority", 0x09, 1), ("clock", 0x0C, 4), ("tracks", 0x2C, 4), ("ident", 0x34, 4),
    ("flags", 0x00, 4, "track"), ("bendRange", 0x0F, 1, "track"), ("volX", 0x13, 1, "track"),
    ("lfoSpeed", 0x19, 1, "track"), ("chan", 0x20, 4, "track"), ("cmdPtr", 0x40, 4, "track"),
)
SOUND_CONSTANTS = {"sound_info_ptr": "SOUND_INFO_PTR", "sound_info": "gSoundInfo",
                   "player_se1": "gMPlayInfo_SE1", "ident_magic": 0x68736D53,
                   "player_head_off": 0x24, "player_next_off": 0x3C,
                   "iwram_min": 0x03000000, "iwram_max": 0x03008000}
SOUND_SOURCE_FRLG = "pokefirered.sym/pokeleafgreen.sym; pret include/gba/m4a_internal.h"
SOUND_SOURCE_RR = "old client lua/memory_gba.lua:1945-1996 (SOUND_INFO_PTR + the linked-list walk)"


def battle_block(title: str, syms, is_rr: bool, profile: dict | None) -> tuple[dict, list[str]]:
    dropped: list[str] = []
    clauses = []
    if is_rr:
        ram = (profile or {}).get("titles", {}).get(title, {}).get("ram", {})
        for name, key, offset, width, mask, compare, expect in BATTLE_CLAUSES_RR:
            if ram.get(key) is None:
                dropped.append(f"{name}: profile.ram.{key} absent")
                continue
            entry = {"name": name, "symbol": key, "address": ram[key], "offset": offset,
                     "width": width, "compare": compare,
                     "source": BATTLE_SOURCE_RR % key}
            if key == "BATTLE_CONTROLLER_EXEC_FLAGS_ADDR":
                entry["source"] = f"profile.ram.{key}; " + profile["titles"][title]["_src"][f"ram.{key}"]
            if mask is not None:
                entry["mask"] = mask
            if compare == "eq_rom":
                rom_key = expect
                value = (profile or {}).get("titles", {}).get(title, {}).get("rom", {}).get(rom_key)
                if value is None:
                    dropped.append(f"{name}: profile.rom.{rom_key} absent")
                    continue
                entry["expect_symbol"] = rom_key
                entry["expect"] = value
                entry["source"] = f"profile.ram.{key} + profile.rom.{rom_key} (CFRU code pin)"
            elif expect is not None:
                entry["expect"] = expect
            clauses.append(entry)
        guard = dict(BATTLE_COMMIT_GUARD_RR)
        guard["address"] = ram.get("BATTLE_COMM_ADDR")
        guard["source"] = BATTLE_SOURCE_RR % "BATTLE_COMM_ADDR"
        dropped += list(BATTLE_DROPPED_RR)
    else:
        for name, symbol, offset, width, mask, compare, expect in BATTLE_CLAUSES_FRLG:
            entry = {"name": name, "symbol": symbol, "address": syms[symbol][0], "offset": offset,
                     "width": width, "compare": compare, "source": BATTLE_SOURCE_FRLG}
            if mask is not None:
                entry["mask"] = mask
            if compare == "eq_symbol":
                entry["expect_symbol"] = expect
                entry["expect"] = syms[expect][0] | 1
            elif expect is not None:
                entry["expect"] = expect
            clauses.append(entry)
        guard = dict(BATTLE_COMMIT_GUARD)
        guard["address"] = syms["gBattleCommunication"][0]
        guard["source"] = BATTLE_SOURCE_FRLG
    return {"version": "gen3-battle-v1", "clauses": clauses, "commit_guard": guard}, dropped


def native_block(profile: dict | None) -> dict | None:
    if not profile or not isinstance(profile.get("native"), dict):
        return None
    nat = profile["native"]
    spans = []
    for key, size, what in NATIVE_ARENA:
        if nat.get(key) is None:
            continue
        spans.append({"key": key, "start": nat[key], "size": size, "what": what})
    entry = {"version": "gen3-native-v1", "base": nat.get("BASE"), "sig": nat.get("SIG"),
             "abi": nat.get("ABI"), "info": nat.get("INFO"), "spans": spans, "source": NATIVE_SOURCE}
    entry.update(NATIVE_LAYOUT)
    return entry


def sound_block(syms, is_rr: bool) -> dict:
    constants = dict(SOUND_CONSTANTS)
    out = {"version": "gen3-sound-v1",
           "ident_magic": constants["ident_magic"], "tracks_off": 0x2C,
           "player_head_off": constants["player_head_off"],
           "player_next_off": constants["player_next_off"],
           "iwram_min": constants["iwram_min"], "iwram_max": constants["iwram_max"],
           "ident_off": 0x34, "track0_off": 0x00,
           "fields": [{"name": n, "offset": o, "size": s, "on": (t[0] if t else "player")}
                      for row in SOUND_FIELDS for n, o, s, *t in [row]],
           "source": SOUND_SOURCE_RR if is_rr else SOUND_SOURCE_FRLG}
    if not is_rr:
        for key in ("sound_info_ptr", "sound_info", "player_se1"):
            symbol = constants[key]
            if symbol in syms:
                out[key] = {"symbol": symbol, "address": syms[symbol][0], "source": "sym"}
    return out


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
