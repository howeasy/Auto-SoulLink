#!/usr/bin/env python3
"""Generate the Gen 4 G1 profile packs (HGSS, hg-engine, Platinum bind) from pinned inputs.

    python tools/gen_gen4_pack.py hgss            # data/games/gen4_hgss/profile.json
    python tools/gen_gen4_pack.py hge             # data/games/gen4_hge/profile.json
    python tools/gen_gen4_pack.py pt              # data/games/gen4_pt/profile.json (bind only)
    python tools/gen_gen4_pack.py <mode> --check  # regenerate in memory, diff against the commit

Input paths default to tools/gen4_pins.default_locations(); override with --path KEY=PATH or the
environment variable SLINK_GEN4_<KEY> (KEY upper-case, e.g. SLINK_GEN4_HEARTGOLD_HGE).

Exit codes: 0 ok, 1 FAIL (present-but-wrong input, validation failure, drift), 2 SKIP (an input
is absent; the message names the artifact).

Why this is not a Gen 3 style address-database scrape:
  * Symbols come from pret's published xMAP linker maps. The owning image of every symbol is the
    xMAP section it sits in (`# .main`, `# .OVY_12`, `# .field` ...), never an address lookup:
    several overlays (and hge's expanded ARM9) share RAM addresses.
  * Site bytes are read from the ROM image named by that declaration, and the whole extent must
    lie inside it (the historical offline resolver chose ARM9 first and read padding).
  * Every ROM / map / export is hashed and compared with data/gen4_sources.lock.json first.

Evidence classes in the emitted JSON are SOURCE (pret / hg-engine source at a pinned commit),
FILE (bytes of a pinned artifact) and OPEN (null + a reason in `open`). Nothing is PHYSICAL.
"""
from __future__ import annotations

import argparse
import copy
import csv
import difflib
import functools
import hashlib
import io
import json
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
try:
    from tools import gen4_pins
except ImportError:  # run as a script: tools/ is sys.path[0], the repo root is not
    sys.path.insert(0, str(REPO))
    from tools import gen4_pins

GENERATOR = "tools/gen_gen4_pack.py"
LOCK_PATH = REPO / "data" / "gen4_sources.lock.json"
SCHEMA = "gen4-profile-v1"
OUT = {
    "hgss": REPO / "data" / "games" / "gen4_hgss" / "profile.json",
    "hge": REPO / "data" / "games" / "gen4_hge" / "profile.json",
    "pt": REPO / "data" / "games" / "gen4_pt" / "profile.json",
}
ARM9_BASE = 0x02000000
EXTENT_MAX = 16  # register_hex extent = min(16, symbol size), never below 4
EXIT_OK, EXIT_FAIL, EXIT_SKIP = 0, 1, 2


class Skip(Exception):
    """A required input is absent (exit 2)."""


class Fail(Exception):
    """A present input is wrong, or the generated pack is inconsistent (exit 1)."""


# --------------------------------------------------------------------------------------------
# Inputs and identity
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Inputs:
    paths: dict[str, Path]  # keys: gen4_pins ROM / asset / source-checkout keys
    lock: Path = LOCK_PATH


def default_inputs(overrides: dict[str, str] | None = None) -> Inputs:
    """Paths from gen4_pins.default_locations(), then SLINK_GEN4_<KEY> env, then CLI overrides."""
    loc = gen4_pins.default_locations()
    paths = {**loc.roms, **loc.assets, **loc.sources}  # sources back the source-derived profile blocks (profile.bag)
    for key in list(paths):
        env = os.environ.get("SLINK_GEN4_" + key.upper())
        if env:
            paths[key] = Path(env)
    for key, value in (overrides or {}).items():
        if key not in paths:
            raise Fail(f"unknown input key {key!r}; known: {', '.join(sorted(paths))}")
        paths[key] = Path(value)
    return Inputs(paths)


def need(inputs: Inputs, key: str) -> Path:
    path = inputs.paths[key]
    if not path.is_file():
        raise Skip(f"absent input {key}: {path}")
    return path


def load_lock(inputs: Inputs) -> dict:
    if not inputs.lock.is_file():
        raise Skip(f"absent input lock file: {inputs.lock}")
    return json.loads(inputs.lock.read_text(encoding="utf-8"))


@functools.cache
def _digest(path: str, mtime_size: tuple) -> dict:
    return gen4_pins.digest_file(Path(path), ("sha1", "md5", "sha256"))


def digest(path: Path) -> dict:
    st = path.stat()
    return _digest(str(path), (st.st_mtime_ns, st.st_size))


def verify_rom(inputs: Inputs, lock: dict, key: str) -> dict:
    """Hash the ROM and compare sha1/md5/sha256/size/header with the lock. Mismatch = FAIL."""
    path = need(inputs, key)
    pin = lock["artifacts"][key]
    got = digest(path)
    header = gen4_pins.nds_header_code(path)
    for field in ("sha1", "md5", "sha256", "size_bytes"):
        if got[field] != pin[field]:
            raise Fail(f"ROM {key} {field} mismatch: {got[field]} != locked {pin[field]} ({path})")
    if header != pin["header_code"]:
        raise Fail(f"ROM {key} header {header} != locked {pin['header_code']}")
    return {"sha1": got["sha1"], "md5": got["md5"], "sha256": got["sha256"],
            "size_bytes": got["size_bytes"], "header_code": header}


def verify_asset(inputs: Inputs, lock: dict, key: str) -> dict:
    path = need(inputs, key)
    pin = lock["assets"][key]
    got = digest(path)
    if got["sha256"] != pin["sha256"] or got["size_bytes"] != pin["size_bytes"]:
        raise Fail(f"asset {key} identity mismatch vs lock ({path})")
    row = {"sha256": got["sha256"], "size_bytes": got["size_bytes"]}
    if "source_commit" in pin:
        row["source_commit"] = pin["source_commit"]
    if "qualification" in pin:
        row["qualification"] = pin["qualification"]
    return row


# --------------------------------------------------------------------------------------------
# xMAP parser: symbol -> owning image from section context
# --------------------------------------------------------------------------------------------
_HDR = re.compile(r"^# (\.\S+)\s*$")
_ID = re.compile(r"^#>([0-9A-Fa-f]{8})\s+SDK_OVERLAY_(\S+)_ID\b")
_START = re.compile(r"^#>([0-9A-Fa-f]{8})\s+SDK_OVERLAY\.(\S+)\.START\b")
_END = re.compile(r"^#>([0-9A-Fa-f]{8})\s+SDK_STATIC_END\b")
_SYM = re.compile(r"^  ([0-9A-F]{8}) ([0-9A-F]{8}) (\.\w+)\s+(.*?)\t\((.*)\)\s*$")
_MAPPING = {"$t": "thumb", "$a": "arm", "$d": "data"}


@dataclass(frozen=True)
class Sym:
    name: str
    address: int
    size: int
    section: str
    obj: str
    image: str  # arm9 | arm9_itcm | arm9_dtcm | ov<N>


class XMap:
    """Parsed pret xMAP. `syms` has real symbols only; mapping symbols feed `mode()`."""

    def __init__(self, text: str):
        self.syms: dict[str, list[Sym]] = {}
        self.overlay_start: dict[str, int] = {}  # image -> START
        self.static_end: int | None = None
        self._mapping: dict[tuple[str, str], list[tuple[int, str]]] = {}
        self._parse(text)

    def _parse(self, text: str) -> None:
        ids: dict[str, int] = {}
        image = None
        block = None
        for line in text.splitlines():
            m = _HDR.match(line)
            if m:
                block = m.group(1)[1:]
                base = block[:-4] if block.endswith(".bss") else block
                if base == "main":
                    image = "arm9"
                elif base in ("ITCM", "DTCM"):
                    image = "arm9_" + base.lower()
                elif base in ids:
                    image = f"ov{ids[base]}"
                else:
                    mo = re.fullmatch(r"OVY_(\d+)", base)
                    image = f"ov{mo.group(1)}" if mo else None
                continue
            m = _ID.match(line)
            if m and block and not block.endswith(".bss"):
                ids[m.group(2)] = int(m.group(1), 16)
                if m.group(2) == block:
                    image = f"ov{ids[block]}"
                continue
            m = _START.match(line)
            if m and m.group(2) in ids:
                self.overlay_start[f"ov{ids[m.group(2)]}"] = int(m.group(1), 16)
                continue
            m = _END.match(line)
            if m:
                self.static_end = int(m.group(1), 16)
                continue
            m = _SYM.match(line)
            if not m or image is None:
                continue
            addr, size, section, name, obj = int(m.group(1), 16), int(m.group(2), 16), m.group(3), m.group(4), m.group(5)
            if name in _MAPPING:
                self._mapping.setdefault((image, obj), []).append((addr, name))
            elif not name.startswith((".", "$")):
                self.syms.setdefault(name, []).append(Sym(name, addr, size, section, obj, image))

    def lookup(self, name: str) -> Sym:
        found = self.syms.get(name, [])
        if not found:
            raise Fail(f"symbol {name} not in xMAP")
        if len({(s.address, s.image) for s in found}) > 1:
            raise Fail(f"symbol {name} is ambiguous in xMAP: {[(hex(s.address), s.image) for s in found]}")
        return found[0]

    def mode(self, sym: Sym) -> str | None:
        """thumb/arm from the `$t`/`$a` mapping symbol governing the address (same object)."""
        if sym.section != ".text":
            return None
        best = None
        for addr, kind in self._mapping.get((sym.image, sym.obj), []):
            if addr <= sym.address and (best is None or addr > best[0] or (addr == best[0] and kind != "$d")):
                best = (addr, kind)
        if best is None or _MAPPING[best[1]] == "data":
            raise Fail(f"cannot determine Thumb/ARM for {sym.name} @{sym.address:#010x} (no $t/$a mapping symbol)")
        return _MAPPING[best[1]]

    def names_with_addresses(self) -> dict[str, tuple]:
        return {n: tuple(sorted((s.address, s.image) for s in v)) for n, v in self.syms.items()}


@functools.cache
def _xmap(path: str, mtime_size: tuple) -> XMap:
    return XMap(Path(path).read_text(encoding="utf-8", errors="replace"))


def load_xmap(path: Path) -> XMap:
    st = path.stat()
    return _xmap(str(path), (st.st_mtime_ns, st.st_size))


# --------------------------------------------------------------------------------------------
# ROM images, addressed by declared identity (never by address alone)
# --------------------------------------------------------------------------------------------
ARM9_BYTES_NOTE = ("ARM9 bytes: HG/SS = ndspy loadArm9().sections[0] (the DECOMPRESSED static image, RAM base 0x02000000; never the "
                   "compressed raw rom.arm9); hge = the raw uncompressed rom.arm9")


class Images:
    """Byte access to one ROM's ARM9 static image and overlays. Resolution is by image name."""

    def __init__(self, arm9_base: int, arm9: bytes, overlays: dict[int, tuple[int, bytes, int]]):
        self.arm9_base = arm9_base
        self.arm9 = bytes(arm9)
        self.overlays = {i: (ram, bytes(data), bss) for i, (ram, data, bss) in overlays.items()}

    @classmethod
    def from_rom(cls, path: Path, raw_arm9: bool = False) -> Images:
        import ndspy.rom
        rom = ndspy.rom.NintendoDSRom.fromFile(str(path))
        if raw_arm9:  # hge: stored uncompressed; ndspy's compression detector false-positives on it
            base, data = rom.arm9RamAddress, bytes(rom.arm9)
        else:
            sec = rom.loadArm9().sections[0]
            base, data = sec.ramAddress, bytes(sec.data)
        if base != ARM9_BASE:
            raise Fail(f"{path}: ARM9 RAM base {base:#x} != {ARM9_BASE:#x}")
        ovs = {i: (o.ramAddress, o.data, o.bssSize) for i, o in rom.loadArm9Overlays().items()}
        return cls(base, data, ovs)

    def _span(self, image: str) -> tuple[int, bytes]:
        if image == "arm9":
            return self.arm9_base, self.arm9
        m = re.fullmatch(r"ov(\d+)", image)
        if not m or int(m.group(1)) not in self.overlays:
            raise Fail(f"unknown image {image!r}")
        ram, data, _ = self.overlays[int(m.group(1))]
        return ram, data

    def read(self, image: str, addr: int, n: int) -> bytes:
        base, data = self._span(image)
        if not (base <= addr and addr + n <= base + len(data)):
            raise Fail(f"{image} does not contain {addr:#010x}+{n:#x} "
                       f"(image {base:#010x}..{base + len(data):#010x})")
        return data[addr - base:addr - base + n]

    def collisions(self, image: str, addr: int, n: int) -> list[str]:
        """Other images whose bytes overlap [addr, addr+n): why residency must be checked."""
        hits = []
        for name, (base, data) in [("arm9", (self.arm9_base, self.arm9))] + [
                (f"ov{i}", (ram, d)) for i, (ram, d, _) in self.overlays.items()]:
            if name != image and base < addr + n and addr < base + len(data):
                hits.append(name)
        return sorted(hits, key=lambda s: (s != "arm9", int(s[2:]) if s != "arm9" else 0))

    def overlay_table(self) -> dict[str, dict]:
        return {str(i): {"ram": ram, "size": len(data), "bss": bss}
                for i, (ram, data, bss) in sorted(self.overlays.items())}


@functools.cache
def _images(path: str, mtime_size: tuple, raw: bool) -> Images:
    return Images.from_rom(Path(path), raw)


def load_images(path: Path, raw_arm9: bool = False) -> Images:
    st = path.stat()
    return _images(str(path), (st.st_mtime_ns, st.st_size), raw_arm9)


def overlay_id(image: str) -> int | None:
    return int(image[2:]) if image.startswith("ov") else None


# --------------------------------------------------------------------------------------------
# Site and symbol specifications
# --------------------------------------------------------------------------------------------
# (site id, symbol, phase, role, hge expectation, source/reason)
# phase: always | battle | pc | field | probe.  hge expectation: KEPT = bytes at the vanilla
# address are identical in the hge image (declared image); REPLACED = entry clobbered, the pack
# carries the build's replacement; ANY = recorded, not asserted.
SITE_SPECS = [
    ("per_frame_arm", "OS_WaitIrq", "probe", "G1 row a: per-frame ARM site (600/600 hits)", "KEPT"),
    ("per_frame_thumb", "VBlankCB_DmaTasksFramecounter", "probe", "G1 row a: per-frame Thumb site (600/600)", "KEPT"),
    ("half_rate_thumb", "Main_RunOverlayManager", "probe", "G1 row a: Thumb site hit every other frame (300/600)", "KEPT"),
    ("idle_halt_arm", "OS_Halt", "probe", "G1 row m: idle-thread halt; the frame-end PC is parked here", "KEPT"),
    ("never_executed", "DoSoftReset", "probe", "G1 row a negative control: never executes", "KEPT"),
    ("load_overlay_entry", "HandleLoadOverlay", "probe", "G1 row b/c: vanilla overlay load entry", "REPLACED"),
    ("unload_overlay_entry", "UnloadOverlayByID", "probe", "G1 row c: vanilla overlay unload entry", "REPLACED"),
    ("load_overlay_normal", "LoadOverlayNormal", "probe", "static funnel under every load type", "KEPT"),
    ("load_overlay_noinit", "LoadOverlayNoInit", "probe", "static funnel under every load type", "KEPT"),
    ("load_overlay_noinit_async", "LoadOverlayNoInitAsync", "probe",
     "static funnel; hge extension and ov129 loads (loadType 2) reach it without the entry", "KEPT"),
    ("menu_only_ov74", "MainMenuApp_Main", "probe", "G1 row b: menu-only overlay (ov74) site", "ANY"),
    ("battle_faint_cmd", "BtlCmd_TryFaintMon", "battle", "faint script command (ov12)", "REPLACED"),
    ("battle_start_ov12", "ov12_02238A68", "battle", "one-per-battle wake-up (r0=BattleSystem*, r1=BattleSetup*)", "ANY"),
    ("battle_controller_try_faint", "TryFaintMon", "battle", "controller turn-end replacement/loss sweep (ov12)", "ANY"),
    ("battle_exit_arm9", "Battle_Exit", "battle", "native closing-frame exit before manager deletion", "KEPT"),
    ("battle_outcome_copy", "ov12_0223843C", "battle", "stores the battle outcome into BattleSetup.winFlag", "ANY"),
    ("encounter_result", "Encounter_GetResult", "battle", "copies winFlag into VAR_BATTLE_RESULT", "KEPT"),
    ("blackout", "Task_Blackout", "battle", "whiteout task (battle loss path)", "KEPT"),
    ("party_add_mon", "Party_AddMon", "battle", "catch store into party (also gifts/eggs/trades)", "KEPT"),
    ("pc_place_first_in_box", "PCStorage_PlaceMonInBoxFirstEmptySlot", "pc",
     "party-full catch path and PC placement", "REPLACED"),
    ("pc_place_first_any_box", "PCStorage_PlaceMonInFirstEmptySlotInAnyBox", "pc", "placement into any box", "REPLACED"),
    ("pc_place_by_index_pair", "PCStorage_PlaceMonInBoxByIndexPair", "pc", "UI placement at a slot", "ANY"),
    ("pc_swap_by_index_pair", "PCStorage_SwapMonsInBoxByIndexPair", "pc", "PC move/swap", "REPLACED"),
    ("pc_delete_by_index_pair", "PCStorage_DeleteBoxMonByIndexPair", "pc", "PC release", "REPLACED"),
    ("save_write_finish", "Save_WriteManFinish", "field", "save settled", "REPLACED"),
]
# HG vs SS bytes may differ only for these (ov74 differs between titles per sources_and_symbols.md).
TITLE_VARIANT_OK = {"menu_only_ov74"}

SYMBOL_NAMES = [
    "sSaveDataPtr", "sFieldSysPtr", "sOverlayRegions", "gSystem", "sRTCWork",
    "SaveData_Get", "SaveArray_Get",
    "HandleLoadOverlay", "UnloadOverlayByID", "LoadOverlayNormal", "LoadOverlayNoInit",
    "LoadOverlayNoInitAsync", "GetLoadedOverlaysInRegion",
    "Main_RunOverlayManager", "OS_WaitIrq", "OS_Halt", "VBlankCB_DmaTasksFramecounter", "DoSoftReset",
    "Task_Blackout", "Encounter_GetResult", "Task_StartEncounter", "sub_0205239C",
    "SetupAndStartWildBattle", "SetupAndStartTrainerBattle", "FieldSystem_TaskIsRunning",
    "FieldSystem_IsPlayerMovementAllowed",
    "Party_AddMon", "GetMonData", "SetMonData", "GiveMon", "ScrCmd_GiveMon", "ScrCmd_GiveEgg",
    "Task_HatchEggInParty", "sub_02075A7C",
    "PCStorage_PlaceMonInBoxFirstEmptySlot", "PCStorage_PlaceMonInFirstEmptySlotInAnyBox",
    "PCStorage_PlaceMonInBoxByIndexPair", "PCStorage_SwapMonsInBoxByIndexPair",
    "PCStorage_DeleteBoxMonByIndexPair", "PCStorage_SetBoxModified",
    "Save_WriteManFinish", "Save_WriteFileAsync",
    "BtlCmd_TryFaintMon", "BtlCmd_PlayFaintAnimation", "TryFaintMon", "RunBattleScript",
    "Battle_Exit", "BattleSystem_GetPartyMon", "ov12_02238A68", "ov12_0223843C",
    "MainMenuApp_Main", "MainMenuApp_Init", "OS_DisableInterrupts", "NitroMain",
]

# Platinum names differ; roles are mapped here (platinum_bind.md, platform.md).
PT_SYMBOLS = {
    "sSaveDataPtr": "sSaveDataPtr", "gSystem": "gSystem", "overlay_table": "Unk_021BF370",
    "overlay_load": "Overlay_LoadByID", "overlay_unload": "Overlay_UnloadByID",
    "party_add_mon": "Party_AddPokemon", "irq_wait": "OS_WaitIrq", "idle_halt": "OS_Halt",
    "faint_cmd": "BtlCmd_TryFaintMon", "field_system_ptr": "sFieldSystem", "save_data_get": "SaveData_Ptr",
    "rtc_work": "sRTCState",
}


def extent_for(size: int) -> int:
    return max(4, min(EXTENT_MAX, size))


def fire_hex(register_hex: str) -> str:
    """The callback's `val`: the four site bytes as a little-endian u32, 8 lowercase hex digits."""
    return f"{int.from_bytes(bytes.fromhex(register_hex)[:4], 'little'):08x}"


# --------------------------------------------------------------------------------------------
# Thumb redirect decoding (hge entry stubs) and hge export parsing
# --------------------------------------------------------------------------------------------
def decode_redirect(addr: int, entry: bytes) -> dict | None:
    """Where does a clobbered Thumb entry jump? `ldr rN,[pc,#0]; bx rN` trampoline or a stub BL."""
    if len(entry) >= 8:
        h0, h1 = int.from_bytes(entry[0:2], "little"), int.from_bytes(entry[2:4], "little")
        if h0 & 0xF800 == 0x4800 and h1 == 0x4700 | (((h0 >> 8) & 7) << 3):
            lit = ((addr + 4) & ~3) + (h0 & 0xFF) * 4 - addr
            if lit >= 0 and lit + 4 <= len(entry):
                value = int.from_bytes(entry[lit:lit + 4], "little")
                return {"kind": "ldr_bx_trampoline", "target": value & ~1, "thumb": bool(value & 1)}
    for off in range(0, min(len(entry), 0x1C) - 3, 2):
        h0, h1 = int.from_bytes(entry[off:off + 2], "little"), int.from_bytes(entry[off + 2:off + 4], "little")
        if h0 & 0xF800 == 0xF000 and h1 & 0xF800 == 0xF800:
            imm = ((h0 & 0x7FF) << 12) | ((h1 & 0x7FF) << 1)
            if imm & 0x400000:
                imm -= 0x800000
            return {"kind": "bl_stub", "target": (addr + off + 4 + imm) & 0xFFFFFFFF, "thumb": True}
    return None


def parse_offsets_ini(text: str) -> dict[str, int]:
    out = {}
    for line in text.splitlines():
        m = re.fullmatch(r"(\S+):\s+([0-9A-Fa-f]{8})\s*", line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


def parse_nm(text: str) -> dict[str, tuple[str, int]]:
    """`## build/<unit>` sections of `addr T name`; name -> (unit, address)."""
    out, unit = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            unit = line[3:].strip()
            continue
        m = re.fullmatch(r"([0-9a-f]{8}) [Tt] (\S+)\s*", line)
        if m and unit:
            out[m.group(2)] = (unit, int(m.group(1), 16))
    return out


def parse_rom_gen_ld(text: str) -> dict[str, int]:
    out = {}
    for line in text.splitlines():
        m = re.fullmatch(r"([A-Za-z_]\w*)\s*=\s*(0x[0-9a-fA-F]+)\s*;\s*", line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


# nm section -> overlay id (hg-engine include/constants/file.h:125-127, overlays.mk build units)
HGE_NM_UNITS = {"build/linked.o": 129, "build/battle_linked.o": 130, "build/field_linked.o": 131}


# --------------------------------------------------------------------------------------------
# Vanilla (xMAP-driven) symbol and site tables
# --------------------------------------------------------------------------------------------
def symbol_row(xm: XMap, name: str) -> dict:
    s = xm.lookup(name)
    return {"address": s.address, "address_hex": f"{s.address:#010x}", "size": s.size, "image": s.image,
            "section": s.section, "mode": xm.mode(s), "object": s.obj}


def check_symbol_in_image(row: dict, name: str, images: Images, xm: XMap) -> None:
    """Code/data symbols must sit inside the declared image's file bytes (.bss is RAM only)."""
    if row["section"] == ".bss" or row["image"] in ("arm9_itcm", "arm9_dtcm"):
        return
    n = max(row["size"], 1)
    images.read(row["image"], row["address"], n)
    if row["image"] == "arm9" and xm.static_end is not None and row["address"] + n > xm.static_end:
        raise Fail(f"{name} extends past the static ARM9 end {xm.static_end:#x}")


def vanilla_sites(xm: XMap, images: Images, only: list | None = None) -> dict[str, dict]:
    sites = {}
    for site_id, symbol, phase, role, _expect in (only or SITE_SPECS):
        s = xm.lookup(symbol)
        mode = xm.mode(s)
        n = extent_for(s.size)
        reg = images.read(s.image, s.address, n).hex()
        sites[site_id] = {
            "symbol": symbol, "address": s.address, "address_hex": f"{s.address:#010x}",
            "image": s.image, "overlay_id": overlay_id(s.image), "phase": phase, "role": role,
            "extent": n, "register_hex": reg, "fire_hex": fire_hex(reg),
            "mode": mode, "mode_evidence": "xMAP $t/$a mapping symbol at the symbol address",
            "section": s.section, "symbol_size": s.size,
            "collides_with": images.collisions(s.image, s.address, n),
        }
    if "battle_exit_arm9" in sites:
        check = template_check(xm, images, "gOverlayTemplate_Battle", 12)
        exit_site = sites["battle_exit_arm9"]
        if exit_site["address"] != check["exit"] & ~1:
            raise Fail("Battle_Exit xMAP symbol differs from battle template exit")
        exit_site["source"] = f"SOURCE {PRET_HG} src/launch_application.c:174-176 (returns TRUE); src/overlay_manager.c:65-70; src/field_system.c:171-175"
        exit_site["template_exit_evidence"] = check
    return sites


# --------------------------------------------------------------------------------------------
# Validation: re-read every site from the declared image (also the mutation target of the tests)
# --------------------------------------------------------------------------------------------
def validate_sites(sites: dict[str, dict], images: Images, label: str) -> list[str]:
    errs = []
    for sid, s in sorted(sites.items()):
        where = f"{label}:{sid}"
        try:
            reg = bytes.fromhex(s["register_hex"])
        except (ValueError, KeyError):
            errs.append(f"{where}: register_hex is not hex")
            continue
        if s.get("extent") != len(reg) or len(reg) < 4:
            errs.append(f"{where}: extent {s.get('extent')} != register_hex bytes {len(reg)} (>=4)")
            continue
        fh = s.get("fire_hex", "")
        if not re.fullmatch(r"[0-9a-f]{8}", fh) or fh != fire_hex(s["register_hex"]):
            errs.append(f"{where}: fire_hex {fh!r} is not exactly the four site bytes as a little-endian u32")
        if s.get("mode") not in ("thumb", "arm"):
            errs.append(f"{where}: mode {s.get('mode')!r}")
        elif s["mode"] == "thumb" and s["address"] & 1 or s["mode"] == "arm" and s["address"] & 3:
            errs.append(f"{where}: address {s['address']:#x} is misaligned for {s['mode']}")
        if s.get("overlay_id") != overlay_id(s.get("image", "")):
            errs.append(f"{where}: overlay_id {s.get('overlay_id')} does not match image {s.get('image')}")
        try:
            real = images.read(s["image"], s["address"], len(reg))
        except Fail as exc:
            errs.append(f"{where}: {exc}")
            continue
        if real != reg:
            errs.append(f"{where}: register_hex differs from the declared image {s['image']} "
                        f"(file {real.hex()} vs pack {s['register_hex']})")
        if s["mode"] == "arm" and (int.from_bytes(reg[:4], "little") >> 28) not in (0xE, 0xF):
            errs.append(f"{where}: ARM site's first word has no AL/unconditional condition code")
    return errs


def validate_hg_ss(hg: dict, ss: dict) -> list[str]:
    """Gameplay symbols and sites must be identical for HG and SS."""
    errs = []
    for name in sorted(set(hg["symbols"]) | set(ss["symbols"])):
        a, b = hg["symbols"].get(name), ss["symbols"].get(name)
        if a is None or b is None:
            errs.append(f"symbol {name} present in only one title")
        elif {k: a[k] for k in ("address", "size", "image", "section", "mode")} != \
                {k: b[k] for k in ("address", "size", "image", "section", "mode")}:
            errs.append(f"symbol {name} differs between HG ({a['address']:#x} {a['image']}) "
                        f"and SS ({b['address']:#x} {b['image']})")
    for sid in sorted(set(hg["sites"]) | set(ss["sites"])):
        a, b = hg["sites"].get(sid), ss["sites"].get(sid)
        if a is None or b is None:
            errs.append(f"site {sid} present in only one title")
        elif sid in TITLE_VARIANT_OK:
            if a["address"] != b["address"] or a["image"] != b["image"]:
                errs.append(f"site {sid} address/image differs between HG and SS")
        elif (a["address"], a["image"], a["register_hex"]) != (b["address"], b["image"], b["register_hex"]):
            errs.append(f"site {sid} differs between HG and SS "
                        f"({a['address']:#x}/{a['image']}/{a['register_hex']} vs "
                        f"{b['address']:#x}/{b['image']}/{b['register_hex']})")
    for ov, row in hg["overlays"].items():
        other = ss["overlays"].get(ov)
        if other is None or other["ram"] != row["ram"]:
            errs.append(f"overlay {ov} RAM address differs between HG and SS")
    return errs


def check_xmap_vs_rom(xm: XMap, images: Images, label: str) -> None:
    """Independent instrument check: the map's overlay STARTs and static end match the ROM."""
    for image, start in xm.overlay_start.items():
        oid = overlay_id(image)
        if oid not in images.overlays:
            raise Fail(f"{label}: xMAP overlay {image} is not in the ROM overlay table")
        if images.overlays[oid][0] != start:
            raise Fail(f"{label}: xMAP {image} START {start:#x} != ROM {images.overlays[oid][0]:#x}")
    if xm.static_end is not None and xm.static_end - ARM9_BASE != len(images.arm9):
        raise Fail(f"{label}: xMAP static end {xm.static_end:#x} != ARM9 static image size {len(images.arm9):#x}")


def compare_title_maps(hg: XMap, ss: XMap) -> dict:
    a, b = hg.names_with_addresses(), ss.names_with_addresses()
    common = set(a) & set(b)
    diff = sorted(n for n in common if a[n] != b[n])
    entries = {(s.name, s.address, s.image, s.obj) for m in (hg, ss) for v in m.syms.values() for s in v}
    in_hg = {(s.name, s.address, s.image, s.obj) for v in hg.syms.values() for s in v}
    in_ss = {(s.name, s.address, s.image, s.obj) for v in ss.syms.values() for s in v}
    odd = (in_hg ^ in_ss) & entries
    by_image: dict[str, int] = {}
    several: list[str] = []  # a name defined in two images (file-local statics) is attributed to each image it differs in
    for n in diff:
        images = sorted({img for _, img in a[n]} | {img for _, img in b[n]})
        several += [n] if len(images) > 1 else []
        for image in images:
            by_image[image] = by_image.get(image, 0) + 1
    return {"hg_symbols": len(a), "ss_symbols": len(b), "common_names": len(common),
            "only_in_hg": len(set(a) - set(b)), "only_in_ss": len(set(b) - set(a)),
            "address_differs": len(diff), "differing_names_by_image": dict(sorted(by_image.items())),
            "differing_names_in_several_images": several, "differing_name_image_pairs": sum(by_image.values()),
            "differing_objects": sorted({e[3].strip() for e in odd})}


# --------------------------------------------------------------------------------------------
# Static profile facts (SOURCE / FILE, each with its evidence)
# --------------------------------------------------------------------------------------------
PRET_HG = "pret/pokeheartgold@ad7a3afa0cfc144fe6837c410cb95b2727217f54"
HGE_SRC = "hg-engine fork@fc517576498305ecb5f5e1de44681c6e3822361b"
PRET_PT = "pret/pokeplatinum@c248fb3f8cc9934ded800e489567c5c0eeee92eb"


# --------------------------------------------------------------------------------------------
# The save-array bag: the balls pocket (the Nuzlocke gate's "does the player hold a Poké Ball")
# --------------------------------------------------------------------------------------------
# Every number is PARSED from the pinned source clone, never typed in here. The two builds ship the
# same struct under two spellings (pret `Bag`/`ItemSlot` in include/bag_types_def.h + include/item.h;
# the fork's `BAG_DATA`/`ITEM_SLOT` in include/bag.h) and the fork gates its wider pockets behind
# ITEM_POCKET_EXPANSION, so the counts are read from the branch its own include/config.h enables.
# Offsets are relative to the bag save ARRAY base (save.array_ids.bag), never to the general block.
BAG_SOURCE = {
    "hgss": ("pokeheartgold_citation", "pret/pokeheartgold",
             {"struct": "include/bag_types_def.h", "slot": "include/item.h",
              "counts": "include/constants/items.h", "pockets": "files/itemtool/itemdata/item_data.csv"}),
    "hge": ("hg_engine_fork", "hg-engine fork",
            {"struct": "include/bag.h", "counts": "include/constants/item.h",
             "pockets": "data/itemdata/itemdata.c", "config": "include/config.h"}),
}
BAG_POCKET = "POCKET_BALLS"


def _c_int(text: str, defs: dict[str, str], stack: tuple = ()) -> int:
    """A C integer expression over #define'd integer constants (digits, + - * ( ) only)."""
    def sub(m):
        if m[0] in stack:
            raise Fail(f"cyclic integer macro {m[0]}")
        if m[0] not in defs:
            raise Fail(f"cannot evaluate {text!r}: unknown macro {m[0]}")
        return str(_c_int(defs[m[0]], defs, stack + (m[0],)))
    expr = re.sub(r"\b[A-Za-z_]\w*\b", sub, text)
    if not re.fullmatch(r"[0-9+\-*() ]+", expr):
        raise Fail(f"cannot evaluate {text!r} (resolves to {expr!r})")
    return int(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 -- charset-checked above: digits + - * ( )


def _c_defines(text: str) -> dict[str, str]:
    return {m[1]: m[2].strip() for m in re.finditer(r"^#define (\w+)[ \t]+([^\n]*?)[ \t]*(?://[^\n]*)?$", text, re.M)}


def _struct_body(text: str, struct: str) -> str:
    m = re.search(r"typedef struct " + struct + r"\s*\{(.*?)\}\s*\w+;", re.sub(r"//[^\n]*", "", text), re.S)
    if not m:
        raise Fail(f"typedef struct {struct} not found")
    return m[1]


def _item_slot(text: str, struct: str) -> tuple[int, dict[str, tuple[int, int]]]:
    """(size, {field: (offset, width)}) of the item slot struct, in declaration order."""
    out, off = {}, 0
    for width, name, count in re.findall(r"\b(u8|u16|u32)\s+(\w+)\s*(?:\[\s*(\d+)\s*\])?\s*;", _struct_body(text, struct)):
        n = int(count) if count else 1
        w = {"u8": 1, "u16": 2, "u32": 4}[width]
        out[name] = (off, w * n)
        off += w * n
    if not out:
        raise Fail(f"struct {struct} has no scalar fields")
    return off, out


def _bag_counts(text: str, gated: bool) -> dict[str, int]:
    """NUM_BAG_* pocket sizes. The fork's live in `#ifdef ITEM_POCKET_EXPANSION`; take that branch, but
    resolve every macro against the WHOLE header (NUM_BAG_ITEMS names NUM_MEGA_STONES, defined elsewhere)."""
    defs = _c_defines(text)
    body = text
    if gated:
        body = next((m[1] for m in re.finditer(r"#ifdef ITEM_POCKET_EXPANSION(.*?)#else(.*?)#endif", text, re.S)
                     if "NUM_BAG_BALLS" in m[1]), None)
        if body is None:
            raise Fail("the fork's NUM_BAG_* block is no longer guarded by ITEM_POCKET_EXPANSION")
    local = _c_defines(body)
    counts = {n: _c_int(v, defs) for n, v in local.items() if n.startswith("NUM_BAG_")}
    if not counts:
        raise Fail("no NUM_BAG_* pocket sizes found")
    return counts


def _csv_pocket_items(text: str, pocket: str) -> list[str]:
    """Item constant names whose `fieldPocket` column is `pocket` (pret files/itemtool item_data.csv)."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or "fieldPocket" not in rows[0]:
        raise Fail("item_data.csv has no fieldPocket column")
    col = rows[0].index("fieldPocket")
    return [row[0] for row in rows[1:] if len(row) > col and row[col] == pocket]


def _c_pocket_items(text: str, pocket: str) -> list[str]:
    """Item constant names whose `itemdata.c` block sets `.fieldPocket = <pocket>` (the fork)."""
    blocks = re.split(r"^\[([A-Z0-9_]+)\] =", text, flags=re.M)
    # split yields [preamble, name1, body1, name2, body2, ...]: the pocket lives in the BODY half
    return [blocks[i] for i in range(1, len(blocks) - 1, 2) if re.search(r"\.fieldPocket\s*=\s*" + pocket + r"\b", blocks[i + 1])]


def bag_profile(build: str, inputs: Inputs, array_id: int) -> tuple[dict | None, str]:
    """profile.bag, or (None, reason) when the pinned source clone is not on this machine."""
    key, repo, rels = BAG_SOURCE[build]
    src = inputs.paths[key]
    if not src.is_dir():
        return None, (f"absent {key} clone {src}; profile.bag is null and the client's has_pokeballs seam stays "
                      "unwired rather than guessing a pocket")
    try:
        head, clean = gen4_pins.git_identity(src)
    except Exception as exc:  # noqa: BLE001 -- any git failure means it is not the pinned checkout
        raise Fail(f"cannot read git state of {key} clone {src}: {exc}") from exc
    if head != gen4_pins.SOURCE_COMMITS[key] or not clean:
        raise Fail(f"{key} clone {src} is at {head} (clean={clean}); pin {gen4_pins.SOURCE_COMMITS[key]} needs a clean tree")
    text = {rel: (src / rel).read_text(encoding="utf-8", errors="replace") for rel in sorted(set(rels.values()))}

    gated = build == "hge"
    if gated and not re.search(r"^#define ITEM_POCKET_EXPANSION\s*$", text[rels["config"]], re.M):
        raise Fail("the fork no longer enables ITEM_POCKET_EXPANSION; the pocket counts would be the #else branch")
    counts = _bag_counts(text[rels["counts"]], gated)
    slot_size, slot_fields = _item_slot(text[rels["struct"] if gated else rels["slot"]], "ItemSlot")
    fields = re.findall(r"^\s*(?:ItemSlot|ITEM_SLOT)\s+(\w+)\[([A-Z0-9_]+)\]\s*;", text[rels["struct"]], re.M)
    if not fields or "balls" not in dict(fields):
        raise Fail(f"{rels['struct']} declares no `balls` pocket array")
    layout, off = {}, 0
    for field, const in fields:
        if const not in counts:
            raise Fail(f"bag pocket {field} is sized by {const}, which the counts header does not define")
        layout[field] = {"off": off, "count": counts[const], "count_const": const}
        off += counts[const] * slot_size
    total = off + 4  # + the struct's trailing `u16 registeredItems[2]`, outside every pocket array
    if total > 0x10000:
        raise Fail(f"the parsed bag is {total} B, larger than one save array slot")

    pockets = _csv_pocket_items(text[rels["pockets"]], BAG_POCKET) if not gated else _c_pocket_items(text[rels["pockets"]], BAG_POCKET)
    id_defs = _c_defines(text[rels["counts"]])
    missing = sorted(n for n in pockets if n not in id_defs)
    if missing:
        raise Fail(f"ball item(s) with no id constant in {rels['counts']}: {', '.join(missing)}")
    ball_ids = sorted(_c_int(id_defs[n], id_defs) for n in pockets)
    balls = layout["balls"]
    before = ", ".join(f"{field}[{layout[field]['count_const']}]" for field, _ in fields[:[f for f, _ in fields].index("balls")])
    cite = HGE_SRC if gated else PRET_HG
    slot_rel = rels["struct"] if gated else rels["slot"]
    evidence = {
        "balls_pocket_off": f"SOURCE {cite} {rels['struct']} (pocket order {', '.join(f for f, _ in fields)}); "
                            f"the balls pocket follows {before}; each slot is {slot_size} B "
                            f"({slot_rel}, struct ItemSlot), so the offset is the sum of the preceding slot counts x {slot_size}",
        "ball_slot_size": f"SOURCE {cite} {slot_rel} (struct ItemSlot: "
                          f"{' + '.join(f'{name} {size} B' for name, (_o, size) in slot_fields.items())})",
        "ball_slot_count": f"SOURCE {cite} {rels['counts']} ({balls['count_const']})",
        "ball_ids": f"SOURCE {cite} {rels['pockets']} (every item whose fieldPocket is {BAG_POCKET}) "
                     f"+ {rels['counts']} (the id constants)",
    }
    return {
        "array_id": array_id,
        "array_id_note": "the bag save array; profile.save.array_ids.bag carries the same number",
        "base": "bag_array",
        "balls_pocket_off": balls["off"],
        "balls_pocket_off_hex": f"{balls['off']:#06x}",
        "ball_slot_size": slot_size,
        "ball_slot_count": counts["NUM_BAG_BALLS"],
        "ball_ids": ball_ids,
        "slot_fields": {name: {"off": o, "size": w} for name, (o, w) in slot_fields.items()},
        "pocket_layout": layout,
        "has_pokeballs": "any slot at balls_pocket_off + i*ball_slot_size (0 <= i < ball_slot_count) whose "
                         "u16 id at +0 is in ball_ids has u16 quantity at +2 > 0",
        "note": (f"{len(ball_ids)} item ids live in the balls pocket and {counts['NUM_BAG_BALLS']} slots hold them; "
                 f"the pocket holds one stack per id, so ids beyond the slot count cannot be carried"
                 if len(ball_ids) > counts["NUM_BAG_BALLS"] else
                 f"{len(ball_ids)} item ids share {counts['NUM_BAG_BALLS']} balls-pocket slots (one stack per id)"),
        "evidence": evidence,
        "source": {
            "repo": repo, "commit": head,
            "inputs": {rel: hashlib.sha256((src / rel).read_bytes()).hexdigest() for rel in sorted(set(rels.values()))},
        },
    }, ""


def save_geometry(page_max: int, evidence: str, runtime: str) -> dict:
    """SaveData geometry derived from the C struct (4 u32, dynamic_region, u32, 42 headers, 2 specs)."""
    region = page_max * 0x1000
    counter = 0x10 + region
    headers = counter + 4
    return {
        "evidence": evidence, "runtime_confirmation": runtime,
        "dynamic_region_off": 0x10, "dynamic_region_size": region,
        "save_counter_off": counter, "array_headers_off": headers,
        "array_header_count": 42, "array_header_size": 0x10,
        "array_header_fields": {"id": 0, "size": 4, "offset": 8, "crc": 0xC, "slot": 0xE},
        "array_addr": "SaveData + dynamic_region_off + u32[SaveData + array_headers_off + id*array_header_size + 8]",
        "slot_specs_off": headers + 42 * 0x10, "slot_spec_count": 2, "slot_spec_size": 0xC,
        "slot_spec_fields": {"id": 0, "first_page": 1, "num_pages": 2, "offset": 4, "size": 8},
        "chunk_footer": {
            "addr": "SaveData + dynamic_region_off + spec.offset + spec.size - 0x10", "size": 0x10,
            "fields": {"count": 0, "size": 4, "magic": 8, "slot": 0xC, "crc": 0xE},
            "magic": 0x20060623, "valid_when": "magic == 0x20060623 and footer.size == spec.size and footer.slot == slot index",
        },
        "slots": {"general": 0, "pc": 1},
        "array_ids": {"sysinfo": 0, "playerdata": 1, "party": 2, "bag": 3, "local_field_data": 5, "pcstorage": 41},
    }


HGSS_TRAINER = {
    "evidence": f"{PRET_HG} include/player_data.h:12-32; FILE: owner HG save (general+0x64 profile, +0x60 array)",
    "array_id": 1, "profile_off_in_array": 4,
    "name_off": 0, "name_chars": 8, "name_terminator": 0xFFFF,
    "id_off": 0x10, "id_evidence": "FILE (TID 26310 / SID 29888 on the owner HG save)",
    "money_off": 0x14, "gender_off": 0x18, "language_off": 0x19,
    "johto_badges_off": 0x1A, "johto_badges_evidence": "SOURCE (struct order; both badge bytes read 0 on the FILE save)",
    "version_off": 0x1C, "version_evidence": "FILE (7 = VERSION_HEARTGOLD); SS value 8 is SOURCE only (include/config.h:9-10)",
    "kanto_badges_off": 0x1F,
    "kanto_badges_evidence": "SOURCE: johto 0x1A, avatar 0x1B, version 0x1C, flags 0x1D, dummy 0x1E, kanto 0x1F; "
                             "earlier research notes said 0x1E (miscounted the dummy byte)",
    "version_values": {"heartgold": 7, "soulsilver": 8},
    "identity": {
        "general_off_of_profile": 0x64,
        "general_off_evidence": "FILE (HG save: array 1 at general+0x60); runtime reads the array header, this is a cross-check",
        "id_general_off": 0x74, "id_is": "u32: TID in the low half, SID in the high half",
    },
}

HGE_TRAINER = {
    **HGSS_TRAINER,
    "evidence": f"{HGE_SRC} (PlayerProfile unchanged: no hook touches it); FILE: owner hge save OOO sha1 13d56589 "
                "(general+0x60 array, +0x64 profile): name OOO, TID 630 / SID 62679, money 3000, version 7",
    "id_evidence": "FILE (TID 630 / SID 62679 on the owner hge save OOO, via codec.parse_save(img,'hge').player())",
    "version_evidence": "FILE (7 = VERSION_HEARTGOLD on the owner hge save OOO)",
    "identity": {"general_off_of_profile": 0x64,
                 "general_off_evidence": "FILE (hge save OOO: profile at general+0x64, same as the HG save)",
                 "id_general_off": 0x74, "id_is": "u32: TID in the low half, SID in the high half"},
}
PT_TRAINER = {
    "evidence": f"{PRET_PT} include/save_player.h:9-16 (PlayerSave: options u16 + 2 pad, then TrainerInfo @+4), "
                "include/trainer_info.h:9-21 (name[8] u16, id u32 @0x10, money u32 @0x14, gender/language/badgeMask/"
                "appearance/gameCode u8 @0x18..0x1C); src/save_player.c:27-31; FILE: owner Pt save pt_TTT_44361 "
                "(array at general+0x64, profile +0x68): TTT, TID 44361 / SID 13120, money 3500, gameCode 12",
    "array_id": 1, "profile_off_in_array": 4, "name_off": 0, "name_chars": 8, "name_terminator": 0xFFFF,
    "id_off": 0x10, "id_evidence": "FILE (TID 44361 / SID 13120 on the owner Pt save)",
    "money_off": 0x14, "gender_off": 0x18, "language_off": 0x19,
    "badge_mask_off": 0x1A, "badge_mask_evidence": "SOURCE (TrainerInfo.badgeMask, ONE u8 of 8 Sinnoh badges; "
                                                   "no johto/kanto pair, so reads.badges has no Pt shape)",
    "appearance_off": 0x1B, "version_off": 0x1C,
    "version_evidence": "FILE (gameCode 12 = VERSION_PLATINUM on the owner Pt save; "
                        f"{PRET_PT} include/constants/versions.h:17)",
    "version_values": {"platinum": 12},
    "identity": {"general_off_of_profile": 0x68,
                 "general_off_evidence": "FILE (Pt save: PlayerSave array at general+0x64, TrainerInfo +4)",
                 "id_general_off": 0x78, "id_is": "u32: TID in the low half, SID in the high half"},
}
# Location {mapId, warpId, x, y|z, direction}: 5 x s32 = 20 bytes, first member of the local-field array.
LOCATION_SIZE = 20
LOCATION_OFFS = {"map_off": 0, "warp_off": 4, "x_off": 8, "y_off": 12, "dir_off": 16}
HGSS_LOCATION = {
    "array_id": 5, **LOCATION_OFFS, "struct_size": LOCATION_SIZE,
    "evidence": f"SOURCE {PRET_HG} include/field_types_def.h:10-16 (Location: 5 x int), src/save_local_field_data.c:13-27 "
                "(LocalFieldData.currentPosition is the first member), include/constants/save_arrays.h:13 "
                "(SAVE_LOCAL_FIELD_DATA = 5)",
    "file_cross_check": {"general_off_of_array": 0x1234,
                         "evidence": "FILE: owner HG save: Location (60,-1,695,397,1) at general+0x1234; the five-Location "
                                     "block repeats at +0x14.. and +0x50 (struct order current, entrance, previous, dynamicWarp, "
                                     "specialSpawn: src/save_local_field_data.c:13-19)"},
}
HGE_LOCATION = {
    **HGSS_LOCATION,
    "evidence": f"SOURCE {HGE_SRC} include/pokemon.h:569-575 (Location: mapId, warpId, x, z, direction; 20 bytes), array id "
                "as vanilla (save arrays are not renumbered)",
    "file_cross_check": {"general_off_of_array": 0x1424,
                         "evidence": "FILE: owner hge save OOO: Location (60,-1,685,396,1) at general+0x1424 (HG is "
                                     "+0x1234: hge's earlier arrays are larger); runtime reads the array header, this is "
                                     "a cross-check only"},
}
# ---- SYNTH `place`: where the flags / vars / map objects / avatar state sit in the general block ---------------
# SAVE_FLAGS = SaveVarsFlags {u16 vars[0x170]; u8 flags[2912/8]} = 0x44C bytes; SAVE_MAP_OBJECTS = 64 SavedMapObject of
# 0x50 bytes; PlayerSaveData sits in LocalFieldData after cameraType.  The arrays are laid out back to back by
# SaveData_InitSubstructs, each ((sizeFunc() + 3) & ~3) + 4 bytes (src/save.c:733-768), so an offset is the sum of the
# earlier arrays; the gen4_codec oracle does not read any of this, the SYNTH tool does.
FIELD_SAVE_SRC = (f"SOURCE {PRET_HG} src/save.c:733-768 (SaveData_InitSubstructs / GetSaveChunkSizePlusCRC: each array "
                  "((size+3)&~3)+4 bytes in id order), include/constants/save_arrays.h:5-47")
HGSS_FIELD_SAVE = {
    "vars": {
        "array_id": 4, "general_off": 0xDE4, "count": 0x170, "stride": 2, "base_id": 0x4000,
        "evidence": f"{FIELD_SAVE_SRC}; include/save_vars_flags.h:9-12 (SaveVarsFlags: u16 vars[NUM_VARS] first), "
                    "include/constants/vars.h:4,384 (VAR_BASE 0x4000, NUM_VARS 0x170), src/save_vars_flags.c:57-60 "
                    "(var id - 0x4000 indexes vars[])",
        "evidence_class": "SOURCE+FILE",
        "file_cross_check": "FILE: Bag 0x644 + 0x7A0 (= 1948 + 4, 486 slots * 4 + registered) = 0xDE4, vars 0x2E0 + flags 0x16C "
                            "+ CRC = 0x44C + 4 closes exactly on the FILE-verified LocalFieldData 0x1234 (owner HG save); the "
                            "owner HG save holds VAR 0x4030 = 155 at general+0xDE4+0x60 and VAR 0x4035 = 56150",
    },
    "flags": {
        "array_id": 4, "general_off": 0xDE4 + 0x170 * 2, "count": 2912, "bytes": 364, "temp_flag_base": 0x4000,
        "evidence": f"{FIELD_SAVE_SRC}; include/constants/flags.h:2223-2226 (NUM_FLAGS 2912, NUM_TEMP_FLAGS 64, "
                    "TEMP_FLAG_BASE 0x4000), src/save_vars_flags.c:45-54 (flag id 0 is a no-op; id < 0x4000 is flags[id/8] "
                    "bit id%8; ids >= 0x4000 are RAM-only temp flags, never saved)",
        "evidence_class": "SOURCE+FILE",
    },
    "map_objects": {
        "array_id": 10, "general_off": 0x2348, "count": 64, "stride": 0x50, "active_mask": 1,
        "fields": {"flags": 0x00, "objId": 0x08, "movement": 0x09, "initialFacing": 0x0C, "currentFacing": 0x0D,
                   "mapId": 0x10, "initialX": 0x20, "initialY": 0x22, "initialZ": 0x24,
                   "currentX": 0x26, "currentY": 0x28, "currentZ": 0x2A, "vecY": 0x2C},
        "height_to_vecY_shift": 15,
        "height_evidence": f"SOURCE {PRET_HG} src/map_object.c:639-641 (currentY = (vecY >> 3) / FX32_ONE, so vecY = currentY * 8 * "
                           "0x1000 = currentY << 15), :494-496 (the restore copies vecY from the save), :520-535 (only x/z are "
                           "recomputed), :600-610 and :816-828 (nothing else re-derives Y); FILE: every active object in the 4 owner "
                           "saves holds currentY 2 with vecY 0x10000 (one height only, so the relation is confirmed at a single point)",
        "evidence": f"SOURCE {PRET_HG} include/map_object.h:6-33 (SavedMapObject, 0x50 bytes), :119 (MAPOBJECTFLAG_ACTIVE = 1), "
                    "src/save_local_field_data.c:30-32 (SavedMapObjectList: 64 subs), src/map_object.c:395-425 "
                    "(active objects are written from index 0, the rest zeroed; restore has no map filter); the array offset is "
                    "summed from src/save.c:733-768 over arrays 5-9: LocalFieldData 0x1234 + 0x84 "
                    "(LocalFieldData 0x80 + CRC) + 0x344 (Pokedex) + 0x1E4 (Daycare) + 0x884 (PalPad) + 0x2E4 (Misc) = 0x2348",
        "evidence_class": "SOURCE+FILE",
        "file_cross_check": "FILE: the summed offset equals the measured one: in the owner HG and SS saves entry 0 at general+0x2348 "
                            "is the player (flags 0x2000e431, objId 0xFF, movement 1, currentX/Y/Z = Location x,2,z) and its fields "
                            "sit at the SavedMapObject offsets above",
    },
    "player_state": {
        "player_off_in_local_field": 0x6C, "state_off_in_local_field": 0x70, "state_width": 4,
        "evidence": f"SOURCE {PRET_HG} src/save_local_field_data.c:13-28 (LocalFieldData.player after cameraType, u32-aligned), "
                    "include/player_avatar.h:20-24 (PlayerSaveData {u16 hasRunningShoes, u16 runningShoesLock, s32 state})",
        "evidence_class": "SOURCE (FILE: owner saves hold 0 = walking at this offset)",
    },
    "sealing": "only the sector footer CRC (src/save.c:304-348) covers these arrays; no per-array CRC is maintained",
}
HGE_FIELD_SAVE = {
    "vars": {
        **HGSS_FIELD_SAVE["vars"], "general_off": 0xFD4,
        "evidence": f"{FIELD_SAVE_SRC}, with hge's expanded Bag (+0x1F0 = 124 slots * 4: items +80, key +42, balls +2 = vanilla "
                    "0xDE4 + 0x1F0); NUM_VARS/NUM_FLAGS are not redefined by hg-engine",
        "evidence_class": "DERIVED+FILE",
        "file_cross_check": "DERIVED from vanilla counts + the hge bag growth; closes on the FILE-verified LocalFieldData 0x1424 "
                            "(0xFD4 + 0x44C + 4); FILE structure match: the owner hge saves hold the same VAR 0x4030 = 155 and "
                            "VAR 0x4035 = 56150 at general+0xFD4+0x60 / +0x6A as the owner HG save at +0xDE4. Not read from a "
                            "documented hge array table",
    },
    "flags": {
        **HGSS_FIELD_SAVE["flags"], "general_off": 0xFD4 + 0x170 * 2,
        "evidence": f"{FIELD_SAVE_SRC}, shifted by hge's expanded Bag as for vars",
        "evidence_class": "DERIVED+FILE",
        "file_cross_check": "DERIVED; closes on FILE LocalFieldData 0x1424; the owner hge flag bytes match the owner HG pattern "
                            "(flags byte 13 = 0x04 in both)",
    },
    "map_objects": {
        **HGSS_FIELD_SAVE["map_objects"], "general_off": 0x2CC0,
        "evidence": HGSS_FIELD_SAVE["map_objects"]["evidence"] + "; for hge the vanilla sum is 0x2348 - 0x1234 + 0x1424 = 0x2538 "
                    "but the measured offset is 0x2CC0: +0x788 of hge growth in arrays 6-9 that is NOT explained here",
        "evidence_class": "DERIVED+FILE",
        "file_cross_check": "FILE: in both owner hge saves (OOO, JIII) entry 0 at general+0x2CC0 is the player (flags 0x2000e431, "
                            "objId 0xFF, movement 1, currentX/Z = Location x,z); SavedMapObject layout assumed vanilla "
                            "(only the fields above were read); the +0x788 is measured, not decoded",
    },
    "player_state": {**HGSS_FIELD_SAVE["player_state"],
                     "evidence": HGSS_FIELD_SAVE["player_state"]["evidence"] + "; hge LocalFieldData layout assumed vanilla "
                                 "(its Location block repeats at the vanilla +0x14/+0x50 strides in the owner hge save)"},
    "sealing": HGSS_FIELD_SAVE["sealing"],
}
PT_LOCATION = {
    "array_id": 11, **LOCATION_OFFS, "struct_size": LOCATION_SIZE, "y_field": "z",
    "evidence": f"SOURCE {PRET_PT} include/location.h:18-24 (Location: mapHeaderID, warpId, x, z, faceDirection), "
                "include/field_overworld_state.h:13-14 (FieldOverworldState.player is the first member), "
                "src/field_overworld_state.c:42-45, include/constants/savedata/save_table.h:23 "
                "(SAVE_TABLE_ENTRY_FIELD_OVERWORLD_STATE = 11)",
    "file_cross_check": {"general_off_of_array": 0x1280,
                         "evidence": "FILE: owner Pt save pt_TTT_44361: Location (411,-1,116,886,1) at general+0x1280 with "
                                     "entrance/previous at +0x14/+0x28 and exit at +0x50, matching the struct order "
                                     "player, entrance, previous, special, exit"},
}

PKM_BASE = {"box_size": 0x88, "party_size": 0xEC, "exp_bits": 32, "ability_msb": None, "party_hp_width": 2}
BATTLE_BASE = {"ctx_off": 0x30, "mons_off": 0x2D40, "mon_size": 0xC0, "selected_off": 0x219C, "hp_off": 0x4C,
               "hp_width": 4, "hp_signed": True, "ability_off": 0x27, "ability_width": 1}


_FS = f"{PRET_HG} include/field_system.h"
_ASM_SAVE = "asm/overlay_01_021F6830.s"
# probe_field: FieldSystem / FieldSystemUnkSub0 / save-driver SysTask offsets for the G1 probe and the checkpoint.
# Each value is (offset, evidence class, citation). SOURCE = header/C only; ASM = also corroborated by an asm access.
SAVE_STATE_SEMANTICS = {
    "width": 1, "type": "u8", "location": "SysTask.data[1], data = u32[save_driver_task + save_driver_data_off]",
    "values": {"0": "init (ov01_021F68DC stores 0 at creation)", "1": "idle: the only value that accepts a save request",
               "2": "requested (ov01_021F6A9C stores 2 and the request id)"},
    "evidence": f"{PRET_HG} {_ASM_SAVE}:124-137 (create: strb data[1]=0), :365-374 (request accepted only if ldrb [data,#1]==1, then "
                "strb #2), :431-436 (ov01_021F6B10 returns ldrb [data,#1]); 3-7 are the fade/run/finish states "
                "(checkpoint.md section 3), not decoded here",
}
PROBE_FIELD = {
    "sub": (0x00, "SOURCE", f"{_FS}:113 (FieldSystem.unk0 = FieldSystemUnkSub0*); src/field_system.c:89-96"),
    "save": (0x0C, "ASM", f"{_FS}:116 (saveData); asm/overlay_01_021E6880.s:375 (ldr r0,[r4,#0xc]; bl SaveArray_Party_Get); "
                          "src/overlay_124.c:26"),
    "task": (0x10, "SOURCE", f"{_FS}:117 (taskman); src/task.c:70-72 (FieldSystem_TaskIsRunning = taskman != NULL)"),
    "live": (0x6C, "ASM", f"{_FS}:137 (unk6C, BOOL); asm/overlay_01_021E5900.s:292 (str r0,[r4,#0x6c] = TRUE, read at :356); "
                          "src/field_system.c:95,199-201"),
    "launched_app": (0x04, "SOURCE", f"{_FS}:81 (FieldSystemUnkSub0.unk4 = launched app OverlayManager*, sub-relative); "
                                     "src/field_system.c:123-125 (sub_0203DFA4 = unk0->unk4 != NULL), :127-133 (LaunchApplication)"),
    "field_app": (0x00, "SOURCE", f"{_FS}:80 (FieldSystemUnkSub0.unk0 = field app OverlayManager*, sub-relative); "
                                  "src/field_system.c:97 (set by FieldSystem_LoadFieldOverlayInternal), :115-117 (sub_0203DF7C = unk0->unk0 != NULL)"),
    "paused": (0x08, "SOURCE", f"{_FS}:82 (FieldSystemUnkSub0.isPaused, BOOL, sub-relative); src/field_system.c:96,145,199-201,284-289"),
    "save_driver": (0xD8, "ASM", f"{_FS}:168 (unk_D8 = SysTask*; struct order and the 0xE4 followMon comment corroborate); "
                                 f"{_ASM_SAVE}:91-92 (add r4,#0xd8; str r0,[r4] after ov01_021F68DC creates the task)"),
    "save_state": (0x01, "ASM", f"{PRET_HG} {_ASM_SAVE}:124-137 (ov01_021F68DC: data[0]=mode, data[1]=state=0), :365-374 (ov01_021F6A9C accepts a "
                                f"request only when ldrb [data,#1]==1, then strb #2), :431-436 (ov01_021F6B10 returns [data,#1]); "
                                "offset is inside SysTask.data, so read data = u32[save_driver_task + save_driver_data_off]",
                   SAVE_STATE_SEMANTICS),
}
PROBE_FIELD_EXTRA = {
    "save_driver_data_off": (0x10, "SOURCE", f"{PRET_HG} include/sys_task.h:10-18 (SysTask: queue 0, prev 4, next 8, priority 0xC, "
                                             "data 0x10); src/sys_task.c:160-162 (SysTask_GetData returns task->data)"),
}
PROBE_FIELD_CAVEATS = [
    "fs+0xD8 is NULL until the save driver exists; guard before reading data",
    "src/application/view_photo.c:149-155 also uses fieldSystem->unk_D8 as a different SysTask while the photo viewer runs: "
    "read the state byte only when no application is launched (launched_app == 0)",
    "state byte meaning: 0 init, 1 idle (accepts a request), 2 requested, 3-7 fade/run/finish (checkpoint.md section 3)",
]
PROBE_WRONG_WRITE = (
    0x6E,
    f"SOURCE ({PRET_HG}): gSystem+0x6E is compiler padding between softResetDisabled (u8 @0x6C) and unk70 (BOOL @0x70) "
    "(include/system.h:50-58). No C writer exists: src/system.c, src/main.c, src/intro_movie.c, src/title_screen.c write only "
    "named fields, nothing takes &gSystem or clears the struct. A windowed scan of all 520 `ldr rN,=gSystem` sites in asm/*.s found "
    "no access (read or write) at any gSystem offset >= 0x60 except simulatedInputs @0x5C. The scan is heuristic, not an "
    "exhaustive dataflow proof; the .bss byte is zero from boot. hg-engine adds no gSystem write (src/save.c:759 is commented out).",
)


def probe_field_blocks(build: str, hge_checks: dict | None = None) -> dict:
    """profile.probe_field (+ evidence) for hgss, hge (vanilla offsets, hge-checked) and the shared system facts."""
    fields = {**{k: v[0] for k, v in PROBE_FIELD.items()}, **{k: v[0] for k, v in PROBE_FIELD_EXTRA.items()}}
    evidence = {k: {"class": v[1], "cite": v[2], **({"semantics": v[3]} if len(v) > 3 else {})}
                for k, v in {**PROBE_FIELD, **PROBE_FIELD_EXTRA}.items()}
    if build == "hge":
        if hge_checks is None:
            raise Fail("hge probe_field needs the FILE identity checks (hge_field_checks)")
        keep = {"save": f"{HGE_SRC} include/pokemon.h:592-596 (FieldSystem.savedata @0xc)",
                "task": f"{HGE_SRC} include/pokemon.h:592-597 (FieldSystem.taskman @0x10)"}
        proj = (f"vanilla prefix preserved; hge extends FieldSystem to 0x128: {HGE_SRC} include/pokemon.h:592-619 declares the same "
                "offsets at 0x8/0xC/0x10/0x14/0x20/0x3C/0x40/0xE4; FILE: FieldSystem_New allocates 0x128 and differs from vanilla only "
                "inside the declared windows (the heap-size shifter and the StoreFieldSysPtr hook), the launch/overlay-manager/"
                "field-main/save-driver code is byte-identical, and every FieldSystem-level probe_field offset lies below the "
                "preserved prefix 0xE4 (checked, profile.probe_field_hge_checks); vanilla: ")
        for k in list(fields):
            if k in keep:
                evidence[k] = {"class": "SOURCE", "cite": keep[k] + "; same offset as pokeheartgold " + evidence[k]["cite"].split(";")[0]}
            else:
                evidence[k] = {**evidence[k], "class": "SOURCE_PROJECTION", "cite": proj + evidence[k]["cite"]}
    return {
        "probe_field": fields, "probe_field_evidence": evidence, "probe_field_caveats": PROBE_FIELD_CAVEATS,
        "probe_wrong_write_offset": PROBE_WRONG_WRITE[0], "probe_wrong_write_offset_evidence": PROBE_WRONG_WRITE[1],
        **({"probe_field_hge_checks": hge_checks} if build == "hge" else {}),
    }


def hgss_profile(xm: XMap, build: str = "hgss", hge_checks: dict | None = None) -> dict:
    return {
        "save_ptr": {"symbol": "sSaveDataPtr", "address": xm.lookup("sSaveDataPtr").address, "width": 4,
                     "evidence": "xMAP; the archived 0x02111880 chain is a different global (rejected by provenance)"},
        "fieldsys_ptr": {"symbol": "sFieldSysPtr", "address": xm.lookup("sFieldSysPtr").address, "width": 4,
                         "save_data_off": 0x0C,
                         "evidence": f"xMAP; {PRET_HG} include/field_system.h (saveData at +0x0C; probe row h agreement)"},
        "system": {"symbol": "gSystem", "address": xm.lookup("gSystem").address, "vblank_counter_off": 0x2C, "frame_counter_off": 0x30,
                   "address_evidence": f"xMAP gSystem (the same symbol row as title.symbols.gSystem); {PRET_HG} {S_GSYSTEM} defines it",
                   "evidence": f"{PRET_HG} include/system.h:21-57 (vblankCounter @0x2C, frameCounter @0x30); src/main.c:113-124,173 "
                               "increments vblankCounter once per main-loop frame (frameCounter is the per-VBlank count, "
                               "src/system.c:24); MEASURED +1 per frame at +0x2C (platform.md)"},
        "save": save_geometry(35, f"SOURCE {PRET_HG} include/save.h:65-85, include/constants/save_arrays.h:50-51",
                              "OPEN: PHYSICAL read at G1 row h / G2 (FILE-measured only: dynamic_region at SaveData+0x10)"),
        "party_off": {"value": 0x90, "base": "general_block", "count_off": 4, "max_off": 0, "mons_off": 8,
                      "array_id": 2,
                      "evidence": {"heartgold": "FILE (owner HG save: max=6 @+0x90, count @+0x94, mon @+0x98)",
                                   "soulsilver": "SOURCE only (same save code; no SS save yet, D4)"}},
        "pc": {"array_id": 41, "slot": "pc", "box_base": 0, "box_stride": 0x1000, "mon_stride": 0x88,
               "cur_box_off": 0x12000, "box_modified_flag_off": 0x12004,
               "box_names_off": 0x12008, "wallpapers_off": 0x122D8, "size": 0x122FC,
               "evidence": f"SOURCE {PRET_HG} include/pokemon_storage_system.h:12-28; PC block at SaveData+0xF710 FILE-weak",
               "box_modified_flag_evidence": box_flag_evidence("hgss", f"{PRET_HG} include/pokemon_storage_system.h:12-28 (0x12004)")},
        "box_modified_flag_off": 0x12004,
        "trainer": HGSS_TRAINER,
        "location": copy.deepcopy(HGSS_LOCATION),
        "field_save": copy.deepcopy(HGSS_FIELD_SAVE),
        "pkm": dict(PKM_BASE),
        "battle": dict(BATTLE_BASE),
        "boxes": 18, "mons_per_box": 30, "memorial_box": 17,
        **probe_field_blocks(build, hge_checks),
    }


def hgss_open() -> dict:
    return {
        "soulsilver_save_offsets": "no owner SS save (D4): party_off / trainer FILE evidence is HeartGold only",
        "array_footer": "SaveArrayFooter (per-array, include/save.h:28-34) location is not pinned; the chunk footer is the signature",
        "slot_spec_runtime_values": "slot offset/size values are read at runtime from saveSlotSpecs; measured HG FILE: general 0xF628, pc @0xF700 size 0x12310",
        "phase_first_event_coverage": "PHYSICAL first/last-event coverage per phase belongs to C1-1/C1-8",
        "battle_offsets_live_read": "battle offsets are SOURCE/asm-literal derived; a live read is a G1/G3 cell",
        **route_open(),
    }


def route_open() -> dict:
    return {
        "route_legs": "recipes are SOURCE/FILE only (no PHYSICAL run): button timing, the battle cycle and the save sequence are executed by "
                      "the C1-1 probe; per-leg `open` / `note` carry the caveats (X opens the menu, SAVE cell assumes the fully unlocked "
                      "menu and a cursor on cell 0, move-learn/evolution prompts, soft-reset NULL-base `until`)",
        "route_legs.battle_menu_ready": "no RAM predicate for 'the main/fight command menu is up' is pinned (BattleSystem.battleInput and "
                                        "BattleInput.curMenuId offsets are unresolved): battle legs verify only their end condition",
        "collision_pairs": "the shared-address pair is FILE/SOURCE; the PHYSICAL wrong-owner capture is observed by the C1-1 probe row b",
    }


# --------------------------------------------------------------------------------------------
# Phase tables (PLAN 4.2): activation predicates, producers, counts; coverage gaps stay OPEN
# --------------------------------------------------------------------------------------------
def phase_table(sites: dict[str, dict], build: str) -> dict:
    """`build` is hgss or hge. Counts are derived from the emitted sites."""
    def ids(phase: str) -> list[str]:
        return sorted(k for k, v in sites.items() if v["phase"] == phase)

    battle_owner = 130 if build == "hge" else 12
    return {
        "always": {
            "cap": 0, "candidate_sites": ids("always"), "site_count": len(ids("always")),
            "polled": ["overlay residency (sOverlayRegions) one frame late", "sFieldSysPtr chain / save driver idle",
                       "encounter-scoped outcome latch (setup winFlag kept across copy-back/blackout)"],
            "activation": None,
            "open": ["Task_Blackout hook only if the outcome latch cannot cover every loss path (PHYSICAL)"],
        },
        "battle": {
            "cap": 3, "target_max": 2, "candidate_sites": ids("battle"), "site_count": len(ids("battle")),
            "armed_set": None, "armed_set_note": "which candidates arm is fixed at G2 after producer coverage; G1 only needs the candidates",
            "owner_overlay": battle_owner,
            "activation": {
                "arm_when_any": [
                    {"kind": "overlay_resident", "id": battle_owner,
                     "note": "table observed one frame late; first battle event cannot precede residency"},
                    {"kind": "field_task_active", "note": "fs.taskman != NULL while an encounter task runs (setup before residency)"},
                ],
                "disarm_when_all": [
                    {"kind": "overlay_absent", "id": battle_owner},
                    {"kind": "events_drained", "note": "drain queued events before removing the registry"},
                    {"kind": "encounter_copy_back_done", "note": "checkpoint: no encounter task, outcome latch cleared once"},
                ],
                "status": "SOURCE_DESIGN",
            },
            "producers": [
                {"event": "faint (script)", "site": "battle_faint_cmd", "source": "battle_command.c:978-990"},
                {"event": "faint/replace (turn-end sweep)", "site": "battle_controller_try_faint",
                 "source": "battle_controller_player.c:1658-1669,3416-3619"},
                {"event": "catch store to party", "site": "party_add_mon", "source": "battle_command.c:7003"},
                {"event": "catch store to PC (party full)", "site": "pc_place_first_in_box", "source": "battle_command.c:7012-7027"},
                {"event": "battle start wake-up", "site": "battle_start_ov12", "source": "battle_pointer.md"},
                {"event": "outcome", "site": "battle_outcome_copy", "source": "asm overlay_12_022378C0.s:962-968"},
                {"event": "encounter result / whiteout", "sites": ["encounter_result", "blackout"],
                 "source": "encounter.c:102-107,369-375"},
            ],
            "open": ["a raw HP write is not known to run the faint command (C1-8 owns the seam)",
                     "no producer proof that these sites cover every battle write path (C1-1/C1-8 PHYSICAL)"],
        },
        "pc": {
            "cap": 2, "target_max": 2, "candidate_sites": ids("pc"), "site_count": len(ids("pc")),
            "armed_set": None, "armed_set_note": "which candidates arm is fixed at G2 after caller coverage",
            "owner_overlay": 129 if build == "hge" else None,
            "activation": {
                "arm_when_any": [
                    {"kind": "party_or_pc_application_resident", "note": "launched app (fs.unk0->unk4 != NULL) or overlay predicate"},
                    {"kind": "battle_phase_active", "note": "catch store reaches PC placement from ov12"},
                    {"kind": "field_task_active", "note": "script/gift/daycare callers run under a field task"},
                ],
                "disarm_when_all": [{"kind": "events_drained"}],
                "status": "SOURCE_DESIGN",
            },
            "producers": [
                {"event": "place in first box slot", "site": "pc_place_first_in_box"},
                {"event": "place in any box", "site": "pc_place_first_any_box"},
                {"event": "place at slot", "site": "pc_place_by_index_pair"},
                {"event": "swap/move", "site": "pc_swap_by_index_pair"},
                {"event": "release", "site": "pc_delete_by_index_pair"},
            ],
            "open": ["PC UI action handlers not located (engine_sites.md Open); model functions assumed to cover them",
                     "static ARM9 sites: application/caller coverage predicates are PHYSICAL cells"]
            if build == "hgss" else
            ["hge replaces 29 PCStorage_* functions in ov129 (resident from boot): no overlay trigger exists, "
             "caller predicates are PHYSICAL cells. Count = the 29 PCStorage_* rows of the fork's hooks table, "
             "hooks:433-461 under `#pc box expansion` (hooks:462 sub_02074128 is the one unnamed row in the block)"],
        },
        "field": {
            "cap": 0, "candidate_sites": ids("field"), "site_count": len(ids("field")),
            "polled": ["acquisitions/evolution by validated party/box diffs", "save settled via the save driver state"],
            "activation": None,
            "open": ["Save_WriteManFinish is a candidate only; save-driver polling is the target"],
        },
        "probe": {
            "cap": 4, "candidate_sites": ids("probe"), "site_count": len(ids("probe")),
            "activation": {"arm_when_any": [{"kind": "g1_probe"}]},
            "note": "G1 probe only; never armed in production. Register at most 4 at once (D6 fps curve).",
        },
    }


# --------------------------------------------------------------------------------------------
# G1 phase cases (probe row n): a bounded site subset, a pre-frame activation predicate, normal-input routes
# --------------------------------------------------------------------------------------------
# A case is NOT the production armed_set (that is chosen at G2). The probe registers `sites` through the phase registry and an
# independent always-on observer on `producer_site` (an unrouted raw register of the same address), then compares frames.
# Handles: sites + 1 observer <= PROBE_HANDLE_MAX. The probe (lua/tests/probe_gen4_hooks.lua, `e.id==case.producer_site`)
# only emits registry events for armed sites, so producer_site must be one of `sites`.
PROBE_HANDLE_MAX = 4
_P = "pokeheartgold@ad7a3afa"
BS, FIGHT, RUN, EXIT_LEG, RESET_LEG, BOOT = (
    "gen4_routes:battle_settled", "fight_until_enemy_faints", "run_from_wild", "exit_battle_to_overworld",
    "soft_reset_in_fight_menu", "boot_continue_to_overworld")
PC_LEGS = ("gen4_pc:reach_pc_terminal", "pc_open_storage", "pc_deposit_first_party_mon", "pc_withdraw_box_mon", "pc_exit_app")
_PC_FIXTURE = ("fixture: the SYNTH party2 saves and the route_pc* lane batteries (C:/slink/g4/route_pc, route_pc_ss, route_pc_hge) "
               "hold a boxed mon (party=1 boxed=1)")
_PC_ROUTED = ("OPEN: routed but the receipt is unsigned - tools/gen4_routes.py `pc` target (Cherrygrove PC stop: planned walk, "
              "pc_deposit() prologue in lua/tests/gen4_route_play.lua, native SAVE, cold reload; receipt kind route PC_DEPOSIT); "
              + _PC_FIXTURE + "; receipts are not signable until the bound landing re-run (cx-fbd330af)")
_PC_WITHDRAW_OPEN = ("OPEN: the withdraw leg is unrouted. " + _PC_FIXTURE + " and the PC route tooling exists (tools/gen4_routes.py), "
                     "but the toolbar node for WITHDRAW is unverified: of the ov14_021F8A40 toolbar ring, node 7 = STORE goes to "
                     "state 0xA9 and node 8 goes to state 0x97 then state 2, with no storage call found yet "
                     "(docs/gen4/G2_PRODUCER_PLAN.md 6b)")
# PHYSICAL measurement of the RAM box-modified flag (PCStorage word after cur_box): set by a deposit, cleared by the native SAVE,
# cleared on load; the saved battery keeps 1 (f426a76b; server/adapters/gen4_codec.py). An observation, not a G1 row i requirement
# (owner ruling 2026-10-02: row i is persistence-only).
_BOX_FLAG_LANE = {"hgss": "HG C:/slink/g4/route_pc/route_pc_leg4.log:16,25 and SS C:/slink/g4/route_pc_ss/route_pc_ss_leg7.log:16,25 (0x12004)",
                  "hge": "hge C:/slink/g4/route_pc_hge/route_pc_hge_leg7.log:16,25 (0x1e004)"}
_BOX_FLAG_SEMANTICS = ("RAM flag 0->1 at a deposit and 1->0 after a native SAVE (PCDIFF before_deposit/after_save), cleared on load; "
                       "the saved battery keeps 1. An observation, not a persistence requirement (G1 row i is persistence-only, "
                       "owner ruling 2026-10-02)")


def box_flag_evidence(kind: str, src: str) -> str:
    return f"PHYSICAL {_BOX_FLAG_LANE[kind]}: {_BOX_FLAG_SEMANTICS}; SOURCE projection {src}; server/adapters/gen4_codec.py"


ROUTE_LEGS = {
    BS: "EXISTS: tools/gen4_routes.py run + lua/tests/gen4_route_play.lua (CONTINUE with A/Start, planned walk to grass, wild "
        "encounter, settle on the FIGHT menu; C1-9 receipt route_leg2_battle_settled). The battle starts INSIDE this leg",
    FIGHT: "recipe_source (titles.<t>.route_legs): FIGHT, first move, A-mash through the text until the wild mon faints; not yet executed",
    RUN: "recipe_source (titles.<t>.route_legs): FIGHT menu -> RUN, A-mash, retry on a failed escape; not yet executed",
    EXIT_LEG: "recipe_source (titles.<t>.route_legs): A-mash until the encounter task ends (taskman == 0); not yet executed",
    RESET_LEG: f"recipe_source (titles.<t>.route_legs): hold Start+Select+L+R ({_P} src/main.c:101-104); not yet executed",
    BOOT: "EXISTS: lua/tests/probe_gen4_hooks.lua boot loop (CONTINUE with A/Start cadence until idle_field)",
    **dict.fromkeys(PC_LEGS, _PC_ROUTED),
    "pc_withdraw_box_mon": _PC_WITHDRAW_OPEN,
}
_LAUNCHED_APP_SRC = (
    f"{_P} src/field_system.c:127-133 (FieldSystem_LaunchApplication: fs->unk0->unk4 = OverlayManager_New), "
    "src/overlay_manager.c:5-18 (man->template = *template, so ovy_id lands at man+0xC), include/overlay_manager.h:11-25, "
    "include/field_system.h:79-82,113 (unk0 @fs+0; unk4 @sub0+4)")


def _entry(kind: str, caller: str, cite: str, covered_by: list[str], why: str | None = None) -> dict:
    row = {"kind": kind, "caller": caller, "cite": cite, "covered_by": covered_by}
    if why:
        row["why_open"] = why
    return row


_BTL = f"{_P} src/battle/battle_022378C0.c"
_SCRIPT = "files/battledata/script/subscript"
_NOROUTE = "no normal-input route in the inventory reaches this"
_OUTCOME_ASM = "asm/overlay_12_022378C0.s:962-968 (str [setup+0x14] = outcome flags & 0x3F); include/constants/battle.h:112-118"
BATTLE_SITE_CALLERS = {
    "battle_exit_arm9": [
        _entry("exit", "OverlayManager_Run state 3 calls Battle_Exit, then unloads and deletes the manager in the same call chain",
               f"{_P} src/launch_application.c:174-176; src/overlay_manager.c:65-70; src/field_system.c:171-175", [EXIT_LEG]),
    ],
    "battle_start_ov12": [
        _entry("direct", "ov12_0223A0D4 = Battle_Run state BSTATE_UNK_A_INIT (allocates the 0x2490 BattleSystem, then calls the site; "
                         "the only caller)", f"{_P} asm/overlay_12_022378C0.s:4282; {_BTL}:75-77", [BS]),
    ],
    "battle_faint_cmd": [
        _entry("dispatch", "RunBattleScript -> sBattleScriptCommandTable[cmd] (the table entry is the only reference to "
                           "BtlCmd_TryFaintMon; it runs on EVERY UpdateHp, zero HP or not)",
               f"{_P} asm/overlay_12_battle_command.s:354; src/battle/battle_command.c:86-96", [FIGHT]),
        _entry("script", "subscript_0002_UpdateHp via BattleControllerPlayer_HpCalc (ordinary move damage)",
               f"{_P} {_SCRIPT}/subscript_0002_UpdateHp.s:18; src/battle/battle_controller_player.c:2799,2802,2893", [FIGHT]),
        _entry("script", "subscript_0002_UpdateHp via Call BATTLE_SUBSCRIPT_UPDATE_HP from 43 other battle scripts (recoil, "
                         "poison/burn, weather, Future Sight, Pursuit, held-item and bag healing, ...)",
               f"{_P} grep BATTLE_SUBSCRIPT_UPDATE_HP files/battledata/script (43 files)", [], _NOROUTE),
        _entry("script", "subscript_0159_HealingWish", f"{_P} {_SCRIPT}/subscript_0159_HealingWish.s:10", [], _NOROUTE),
        _entry("script", "subscript_0261_LunarDance", f"{_P} {_SCRIPT}/subscript_0261_LunarDance.s:10", [], _NOROUTE),
    ],
    "battle_outcome_copy": [
        _entry("direct", "Battle_Run state BSTATE_BATTLE_MAIN after ov12_02238358 returns TRUE (the only caller)",
               f"{_BTL}:112-116", [FIGHT, RUN]),
        _entry("variant", "outcome WIN (1)", f"{_P} {_OUTCOME_ASM}", [FIGHT]),
        _entry("variant", "outcome PLAYER_FLED (5)", f"{_P} {_OUTCOME_ASM}", [RUN]),
        _entry("variant", "outcome LOSE (2) / DRAW (3) / MON_CAUGHT (4) / FOE_FLED (6)", f"{_P} {_OUTCOME_ASM}", [],
               "needs a lost, drawn, caught or foe-fled battle; " + _NOROUTE),
    ],
}
_ENC = f"{_P} src/encounter.c"
BATTLE_ACTIVATION = [
    _entry("launch", "Task_WildEncounter (wild grass/surf step encounter) -> CallTask_StartBattle -> Task_StartBattle -> Battle_LaunchApp",
           f"{_ENC}:365,68 <- sub_02050B08 <- src/field/encounter_check.c:261,315 (FieldSystem_PerformLandOrSurfEncounterCheck:214)",
           [BS]),
    *(_entry("launch", f"{name} -> CallTask_StartBattle -> Task_StartBattle -> Battle_LaunchApp", f"{_ENC}:{line}", [], _NOROUTE)
      for line, name in ((132, "Task_StartEncounter (trainer/scripted/legendary battles)"), (208, "Task_020508B8"),
                         (236, "Task_02050960"), (269, "Task_020509F0"), (419, "Task_SafariEncounter"),
                         (496, "Task_BugContestEncounter"), (595, "Task_PalParkEncounter"), (663, "Task_TutorialBattle"))),
    _entry("launch", "Frontier battles: Frontier_LaunchApplication(&gOverlayTemplate_Battle) uses frontierSystem->unk0, NOT "
                     "fs->unk0->unk4, so the launched-app predicate is never true", f"{_P} src/frontier/frontier_cmd_arcade.c:138",
           [], "outside the predicate; Battle Frontier is not a release scenario"),
]
BATTLE_EXIT = [
    _entry("exit", "Battle_Exit returns TRUE -> OverlayManager_Run unloads ov12 -> ppOverlayManager_RunFrame_DeleteIfFinished sets "
                   "unk4 = NULL (predicate falls)", f"{_P} src/overlay_manager.c:65-70; src/field_system.c:171-176,189-190", [EXIT_LEG]),
    _entry("reset", "DoSoftReset (no return) while the battle app is up",
           f"{_P} src/main.c:101-104,205-214", [RESET_LEG]),
    _entry("exit", "loss/whiteout: Task_WildEncounter jumps to Task_Blackout after the manager is gone",
           f"{_ENC}:373-375", [], _NOROUTE + " (needs a lost battle)"),
]
PC_SITE_CALLERS = {
    "pc_place_first_in_box": [
        _entry("direct", "ov14_021E62C8 (PC app; also calls the delete site)", f"{_P} asm/overlay_14.s:1268", PC_LEGS[2:3]),
        _entry("direct", "ov14_021E6318 (PC app)", f"{_P} asm/overlay_14.s:1319", PC_LEGS[2:3]),
        _entry("direct", "BATTLE_STATE catch store, party full (runs under the OVY_12 manager, not the PC predicate)",
               f"{_P} src/battle/battle_command.c:7025", [], "other phase predicate; needs a full-party catch"),
        _entry("direct", "PCStorage_PlaceMonInFirstEmptySlotInAnyBox (script gift scrcmd_12.c:68, bug contest "
                         "overlay_bug_contest.c:227; field task, no app predicate)", f"{_P} src/pokemon_storage_system.c:58",
               [], "other phase predicate (field task)"),
        _entry("direct", "ov70_02240A7C / ov70_02240B9C / ov70_022418A4 (OVY_70 app launched by sub_0203F844)",
               f"{_P} asm/overlay_70.s:18479,18601,20198", [], "other overlay predicate (14 != 70)"),
    ],
    "pc_delete_by_index_pair": [
        _entry("direct", "ov14_021E6100 (PC app)", f"{_P} asm/overlay_14.s:1046", PC_LEGS[3:4]),
        _entry("direct", "ov14_021E62C8 (PC app; also calls the first-empty site)", f"{_P} asm/overlay_14.s:1272", PC_LEGS[2:3]),
        _entry("direct", "ov70_022409C0 / ov70_022418A4 (OVY_70 app)", f"{_P} asm/overlay_70.s:18318,20186", [],
               "other overlay predicate (14 != 70)"),
        _entry("direct", "ov112_021EE628 (Pokewalker connect app)", f"{_P} asm/overlay_112.s:17489", [],
               "other overlay predicate (14 != 112)"),
    ],
}
PC_ACTIVATION = [
    _entry("launch", "ScrCmd_158 (PC terminal script) -> PCBox_LaunchApp -> FieldSystem_LaunchApplication",
           f"{_P} src/scrcmd_c.c:1987-1991; src/launch_application.c:406-408", list(PC_LEGS[:2])),
]
PC_EXIT = [_entry("exit", "PCBox_Exit returns TRUE -> manager deleted, unk4 = NULL", f"{_P} src/overlay_manager.c:65-70; "
                  "src/field_system.c:171-176,189-190", PC_LEGS[4:5])]
PHASE_EXCLUDED = {
    "battle": {
        "battle_controller_try_faint": f"turn-end replacement/loss sweep (static TryFaintMon, 6 callers at {_P} "
                                       "src/battle/battle_controller_player.c:828,1181,1575,3201,3365,3877); BtlCmd_TryFaintMon already "
                                       "covers script-driven HP events and the sweep seam is a C1-8 question, not needed to qualify the registry",
        "encounter_result": f"not on the wild-grass path: Task_WildEncounter ({_ENC}:349-399) reads setup->winFlag inline; "
                            f"Encounter_GetResult has 4 callers ({_ENC}:145,215,243,277: Task_StartEncounter and three "
                            "scripted-battle tasks) none reachable by the wild-grass route, and it runs after the manager is gone",
        "blackout": "needs a lost battle (no normal route) and runs under the field task after the manager is gone",
        "party_add_mon": f"fires before the battle (enemy party build, {_P} src/field/encounter_check.c:1355, OVY_2) and for "
                         "catches/gifts/eggs/trades; a catch needs Poke Balls (bag not measured on the owner saves) and no "
                         "battle-app predicate covers the pre-battle call",
    },
    "pc": {
        "pc_place_first_any_box": "callers are script/bug-contest acquisitions (scrcmd_12.c:68, overlay_bug_contest.c:227), not the PC UI",
        "pc_place_by_index_pair": "UI wrappers ov14_021E611C/ov14_021E61BC; cap 2 (the deposit/withdraw pair covers the PC app)",
        "pc_swap_by_index_pair": "UI wrapper ov14_021E637C (box-to-box move); cap 2",
    },
}


def template_check(xm: XMap, images: Images, prefix: str, want: int) -> dict:
    """FILE: the OverlayManagerTemplate in the declared ROM carries the ovy_id the predicate compares against."""
    names = sorted(n for n in xm.syms if re.fullmatch(re.escape(prefix) + r"(\$\d+)?", n))
    if len(names) != 1:
        raise Fail(f"expected exactly one xMAP symbol {prefix!r} (optionally $N), got {names}")
    s = xm.lookup(names[0])
    init, exec_, exit_, ovy = struct.unpack("<4I", images.read(s.image, s.address, 16))
    if ovy != want:
        raise Fail(f"{names[0]} ovy_id {ovy} != predicate value {want}")
    return {"symbol": names[0], "address": s.address, "image": s.image, "ovy_id_off": 12, "ovy_id": ovy,
            "init": init, "exec": exec_, "exit": exit_,
            "evidence": f"FILE: OverlayManagerTemplate {{init, exec, exit, ovy_id}} read from the declared ROM at the xMAP symbol "
                        f"(OVY_{want})"}


def _matrix(case_sites: list[str], table: dict, route: list[str], activation: list[dict], exits: list[dict]) -> dict:
    def mark(row: dict) -> dict:
        hit = [leg for leg in row["covered_by"] if leg in route]
        out = {k: v for k, v in row.items() if k != "why_open"}
        out["exercised_by_route"] = bool(hit)
        out["exercised_by"] = hit
        if not hit:
            out["why_open"] = row.get("why_open") or "covered only by a leg this case's route does not include: " + \
                              ", ".join(row["covered_by"])
        return out
    return {"sites": [{"site": sid, "callers": [mark(r) for r in table[sid]]} for sid in case_sites],
            "activation": [mark(r) for r in activation], "exit": [mark(r) for r in exits],
            "note": "exercised_by_route is a DESIGN claim (the route should reach the caller); each PHYSICAL receipt belongs to row n"}


def _open_from(matrix: dict) -> list[str]:
    rows = [(f"{s['site']}: {r['caller']}", r) for s in matrix["sites"] for r in s["callers"]]
    rows += [(f"activation: {r['caller']}", r) for r in matrix["activation"]] + [(f"exit: {r['caller']}", r) for r in matrix["exit"]]
    return [f"{label} - {r['why_open']}" for label, r in rows if not r["exercised_by_route"]]


def _case(name: str, phase: str, sites: list[str], producer: str, why: dict, predicate: dict, pred_notes: dict, check: dict,
          route: list[str], table: dict, activation: list[dict], exits: list[dict], status: str) -> dict:
    matrix = _matrix(sites, table, route, activation, exits)
    return {
        "name": name, "phase": phase, "status": status, "sites": sites, "producer_site": producer,
        "site_rationale": why, "predicate": predicate, **pred_notes, "predicate_file_check": check,
        "route": route, "route_status": {leg: ROUTE_LEGS[leg] for leg in route},
        "caller_matrix": matrix, "open": _open_from(matrix),
    }


def build_phase_cases(xm: XMap, images: Images, *, hge: bool = False) -> dict:
    """phase_cases (runnable shape), phase_cases_blocked (no fixture) and the excluded candidates with reasons."""
    fsp = xm.lookup("sFieldSysPtr")
    pred_battle = {"symbol": "sFieldSysPtr", "deref": [0x00, 0x04], "offset": 0x0C, "value": 12}
    pred_pc = {**pred_battle, "value": 14}
    battle_notes = {
        "source": _LAUNCHED_APP_SRC + "; src/launch_application.c:178-182 (gOverlayTemplate_Battle = {Battle_Init, Battle_Main, "
                  "Battle_Exit, OVY_12}), src/encounter.c:61-70 (Task_StartBattle is the only Battle_LaunchApp caller)",
        "predicate_chain": "fs = u32[sFieldSysPtr]; sub0 = u32[fs+0]; man = u32[sub0+4]; true when u32[man+0xC] == 12 (any null stops: false)",
        "precedes_first_event": [
            f"{_P} src/encounter.c:68 Task_StartBattle state 0 calls Battle_LaunchApp, which sets fs->unk0->unk4 = OverlayManager_New "
            "(src/field_system.c:132): the chain is true from that instruction on",
            f"{_P} src/overlay_manager.c:45-58: the first OverlayManager_Run call loads OVY_12 and runs Battle_Init (returns TRUE, "
            "static ARM9), so no OVY_12 site runs in that main-loop iteration",
            f"{_P} src/overlay_manager.c:59-64 + src/launch_application.c:167-172: Battle_Run (OVY_12) first runs one iteration later "
            f"(BSTATE_INIT), battle_start_ov12 two iterations later ({_BTL}:48-51,75-77); every iteration ends in OS_WaitIrq "
            "(src/main.c:122), so >= 2 frame boundaries separate the predicate from the first start event, and the pre-frame "
            "check arms before it. Faint events follow the battle intro scripts; outcome is at the end",
            "disarm: the manager is deleted after Battle_Exit (src/overlay_manager.c:65-70, src/field_system.c:171-176), which is "
            f"after battle_outcome_copy ({_BTL}:112-116 runs before BSTATE_END_INIT)"],
    }
    check_b = template_check(xm, images, "gOverlayTemplate_Battle", 12)
    check_p = template_check(xm, images, "sOverlayTemplate_PCBox", 14)
    sec = fsp.section
    why = {
        "battle_exit_arm9": "Battle_Exit returns TRUE before manager deletion: queued closing-frame event oracle",
        "battle_start_ov12": "one event per battle and the earliest OVY_12 site after the predicate: the strictest arm-timing witness",
        "battle_faint_cmd": "the single dispatch point of every scripted HP change/faint (the Soul Link signal); hge replaces it (ov130)",
        "battle_outcome_copy": "the only writer of the outcome into BattleSetup.winFlag and the last site before the manager is deleted: "
                               "the strictest disarm-timing witness",
    }
    three = ["battle_start_ov12", "battle_faint_cmd", "battle_outcome_copy"]
    two = ["battle_start_ov12", "battle_faint_cmd"]

    def battle(name, ids, producer, route, extra=None):
        c = _case(name, "battle", ids, producer, {k: why[k] for k in ids}, pred_battle, battle_notes, check_b, route,
                  BATTLE_SITE_CALLERS, BATTLE_ACTIVATION, BATTLE_EXIT, "ROUTE_LEGS_PARTLY_NEW")
        c.update(extra or {})
        return c

    fight = [BS, FIGHT, EXIT_LEG]
    cases = [
        battle("battle", three, "battle_faint_cmd", fight),
        battle("battle_arm", ["battle_start_ov12", "battle_outcome_copy"], "battle_start_ov12", [BS, RUN, EXIT_LEG]),
        battle("battle_disarm", ["battle_faint_cmd", "battle_outcome_copy"], "battle_outcome_copy", fight),
        battle("battle_close", ["battle_exit_arm9"], "battle_exit_arm9", [BS, RUN, EXIT_LEG], {
            "close_boundary": True,
            "close_oracle_source": f"{_P} src/launch_application.c:174-176; src/overlay_manager.c:65-70; src/field_system.c:171-175",
        }),
        battle("reset", two, "battle_start_ov12", [BS, RESET_LEG, BOOT], {
            "reset_note": f"DoSoftReset ({_P} src/main.c:205-214) restarts the program; sFieldSysPtr is {sec} (xMAP) so the "
                          "start-up zero-fill clears it; the stale-RAM window between the reset and that clear (the chain can still "
                          "read the dead heap) is the PHYSICAL question this case measures (live_after_close must be 0)"}),
    ]
    pc = _case("pc", "pc", ["pc_place_first_in_box", "pc_delete_by_index_pair"], "pc_place_first_in_box",
               {"pc_place_first_in_box": "deposit target (first free slot of the box) and the party-full acquisition store; static ARM9 on HG "
                                         "(the probe's static_pc), replaced into ov129 on hge",
                "pc_delete_by_index_pair": "withdraw/release removes a box mon: the opposite PC write"},
               pred_pc, {
                   "source": _LAUNCHED_APP_SRC + "; src/launch_application.c:406-408 (sOverlayTemplate_PCBox = {PCBox_Init, PCBox_Main, "
                             "PCBox_Exit, OVY_14}), src/scrcmd_c.c:1987-1991 (the only PCBox_LaunchApp caller)",
                   "predicate_chain": "as battle, true when u32[man+0xC] == 14",
                   "precedes_first_event": [
                       f"{_P} src/scrcmd_c.c:1991: PCBox_LaunchApp sets unk4; the first deposit/withdraw is a menu action in PCBox_Main "
                       "(ov14), many frames after the launch, so the arm precedes it with a wide margin",
                       "disarm: PCBox_Exit then manager delete (src/overlay_manager.c:65-70); the last PC write is a menu action before it"]},
               check_p, list(PC_LEGS), PC_SITE_CALLERS, PC_ACTIVATION, PC_EXIT, "BLOCKED_NO_FIXTURE")
    # Preserve the full paired-site caller inventory as OPEN; deposit does not exercise deletion/release.
    pc["name"] = "pc_withdraw_release"
    pc["blocked_reason"] = "OPEN: delete-by-index, WITHDRAW and RELEASE remain unqualified; " + _PC_WITHDRAW_OPEN
    for entry in pc["caller_matrix"]["sites"]:
        if entry["site"] == "pc_delete_by_index_pair":
            for caller in entry["callers"]:
                caller["exercised_by_route"] = False
                caller["exercised_by"] = []
                caller["why_open"] = caller.get("why_open") or "WITHDRAW/RELEASE route has not been qualified"
    pc["open"] = _open_from(pc["caller_matrix"])
    producer = "pc_place_arm9_entry" if hge else "pc_place_first_in_box"
    ids = [producer, "pc_place_first_in_box"] if hge else [producer]
    callers = copy.deepcopy(PC_SITE_CALLERS)
    if hge:
        callers[producer] = copy.deepcopy(callers["pc_place_first_in_box"])
    deposit_route = [leg for leg in PC_LEGS if leg != "pc_withdraw_box_mon"]
    deposit = _case("pc", "pc", ids, producer,
                    dict.fromkeys(ids, "native deposit; ARM9 entry/trampoline is the static-PC oracle, no withdraw claim"),
                    pred_pc, {key: pc[key] for key in ("source", "predicate_chain", "precedes_first_event")},
                    check_p, deposit_route, callers, PC_ACTIVATION, PC_EXIT, "ROUTE_LEGS_PARTLY_NEW")
    deposit["fixture_role"] = "pc_case"
    cases.append(deposit)
    return {"phase_cases": cases, "phase_cases_blocked": [pc], "phase_cases_excluded": copy.deepcopy(PHASE_EXCLUDED)}


def validate_phase_cases(title: dict) -> list[str]:
    """Pure check of a title's phase cases against its own symbols/sites/phases (mutation target of the tests)."""
    errs = []
    known, phases = set(title["symbols"]), title["phases"]
    pf = title["profile"].get("probe_field") or {}
    for case in [*title.get("phase_cases", []), *title.get("phase_cases_blocked", [])]:
        where = f"phase_case:{case.get('name')}"
        ph = phases.get(case.get("phase"))
        if ph is None:
            errs.append(f"{where}: unknown phase {case.get('phase')!r}")
            continue
        ids = case.get("sites") or []
        if not ids or len(set(ids)) != len(ids):
            errs.append(f"{where}: sites must be a non-empty list without duplicates")
        errs += [f"{where}: site {sid} is not a {case['phase']} candidate_site" for sid in ids if sid not in ph["candidate_sites"]]
        errs += [f"{where}: site {sid} is not in this title's site table" for sid in ids if sid not in title["sites"]]
        if len(ids) > ph["cap"]:
            errs.append(f"{where}: {len(ids)} sites exceed the {case['phase']} cap {ph['cap']}")
        if len(ids) + 1 > PROBE_HANDLE_MAX:
            errs.append(f"{where}: {len(ids)} sites + the oracle observer exceed {PROBE_HANDLE_MAX} handles")
        if case.get("producer_site") not in ids:
            errs.append(f"{where}: producer_site {case.get('producer_site')!r} must be one of sites "
                        "(the probe compares the always-on observer with the registry events of that site)")
        if case.get("phase") == "pc" and case.get("status") != "BLOCKED_NO_FIXTURE":
            producer = title["sites"].get(case.get("producer_site"), {})
            if producer.get("image") != "arm9" or producer.get("overlay_id") is not None:
                errs.append(f"{where}: static_pc producer must be an ARM9 site, never an overlay label")
            if case.get("fixture_role") != "pc_case":
                errs.append(f"{where}: dedicated pc_case fixture required")
        pred = case.get("predicate") or {}
        if pred.get("symbol") not in known:
            errs.append(f"{where}: predicate.symbol {pred.get('symbol')!r} is not a symbol of this title's xMAP")
        if not isinstance(pred.get("deref"), list) or not all(isinstance(o, int) for o in pred["deref"]):
            errs.append(f"{where}: predicate.deref must be a list of integer offsets")
        if not isinstance(pred.get("offset"), int):
            errs.append(f"{where}: predicate.offset must be an integer")
        if ("value" in pred) == ("nonzero" in pred):
            errs.append(f"{where}: predicate needs exactly one of value / nonzero")
        if pf and pred.get("deref") != [pf.get("sub"), pf.get("launched_app")]:
            errs.append(f"{where}: predicate.deref {pred.get('deref')} != probe_field [sub, launched_app] {[pf.get('sub'), pf.get('launched_app')]}")
        if pred.get("value") != (case.get("predicate_file_check") or {}).get("ovy_id"):
            errs.append(f"{where}: predicate.value {pred.get('value')} != the ROM template ovy_id")
        if not case.get("source") or not case.get("precedes_first_event"):
            errs.append(f"{where}: source and precedes_first_event citations are required")
        route = case.get("route") or []
        if not route or not all(isinstance(leg, str) and leg in case.get("route_status", {}) for leg in route):
            errs.append(f"{where}: route must be a non-empty list of named legs, each with a route_status")
        matrix = case.get("caller_matrix") or {}
        if [s["site"] for s in matrix.get("sites", [])] != ids:
            errs.append(f"{where}: caller_matrix.sites must list exactly the case sites in order")
        rows = [r for s in matrix.get("sites", []) for r in s["callers"]] + matrix.get("activation", []) + matrix.get("exit", [])
        gaps = [r for r in rows if not r.get("exercised_by_route")]
        if len(case.get("open", [])) != len(gaps) or any(not r.get("why_open") for r in gaps):
            errs.append(f"{where}: every caller the route does not exercise must carry why_open and appear once in open")
        if any(r.get("exercised_by_route") and not set(r["exercised_by"]) <= set(route) for r in rows):
            errs.append(f"{where}: a caller claims coverage by a leg that is not in the route")
    return errs


# --------------------------------------------------------------------------------------------
# Button-recipe route legs, the ROM-read UI geometry they derive from, and shared-address collision pairs (card C1-2c)
# --------------------------------------------------------------------------------------------
# A recipe is declarative: the probe presses `press` for `hold_frames`, waits `then_wait_frames`, runs the steps in order and
# repeats the cycle while `until` (the probe's phase-predicate shape) is false, for at most `max_frames`. Menu geometry is read
# from the ROM tables and the pret source, never from screenshots; every claim is SOURCE (pret@ad7a3afa), FILE (ROM bytes) or OPEN.
NDS_BUTTONS = ("A", "B", "X", "Y", "Start", "Select", "Up", "Down", "Left", "Right", "L", "R")  # BizHawk NDS joypad names
ROUTE_MAX_FRAMES = 12000  # lua/tests/probe_gen4_hooks.lua play_route bound
DIRS = ("Up", "Down", "Left", "Right")  # ov27_0225B404 direction order = neighbour-table group order
CITE_NEEDLES: list[tuple[str, int, str]] = []  # (path in pokeheartgold@ad7a3afa, first line, text that line must contain)


def _c(path: str, spec: str, needle: str) -> str:
    """A source reference 'path:lines' (relative to pokeheartgold@ad7a3afa) whose first line a test re-reads from the clone."""
    CITE_NEEDLES.append((path, int(spec.split("-")[0]), needle))
    return f"{path}:{spec}"


_BI = "src/battle/battle_input.c"
S_BI_MAIN_TBL = _c(_BI, "281-284", "sCursorArrayMainMenu")
S_BI_FIGHT_TBL = _c(_BI, "414-418", "sCursorArrayFightMenu")
S_BI_TOUCH = _c(_BI, "1656-1710", "BattleInput_CheckTouch")
S_BI_KEYCARRY = _c(_BI, "1253", "keyPressed = *a4")
S_BI_CURSOR = _c(_BI, "3676-3702", "BattleInput_CheckCursorInput")
S_BI_MAIN = _c(_BI, "3704-3776", "BattleInput_CursorMove_MainMenu")
S_BI_FIGHT = _c(_BI, "3836-3891", "BattleInput_CursorMove_FightMenu")
S_BI_KEY = _c(_BI, "4233-4325", "BattleCursor_CheckKeyInput")
S_MAIN_RESET = _c("src/main.c", "101-104", "heldKeysRaw")
S_DO_RESET = _c("src/main.c", "205-214", "DoSoftReset")
S_BTN_MODE = _c("src/system.c", "331-341", "ApplyButtonModeToInput")
S_FIELD_INPUT = _c("src/field_system.c", "210", "FieldInput_Update(&fieldInput")
S_X_OPENS = _c("asm/overlay_01_021E6880.s", "212-246", "_021E69F8")
S_OPEN_CALL = _c("asm/overlay_01_021E6880.s", "641", "StartMenu_Init")
S_SM_INIT = _c("src/start_menu.c", "214-232", "void StartMenu_Init")
S_SM_LISTS = _c("src/start_menu.c", "481-521", "StartMenu_BuildActionLists")
S_SM_CURSOR = _c("src/start_menu.c", "453-470", "Task_StartMenu_DrawCursor")
S_SM_INPUT = _c("src/start_menu.c", "562-587", "Task_StartMenu_HandleInput")
S_SM_KEY = _c("src/start_menu.c", "589-609", "StartMenu_HandleKeyInput")
S_SM_SAVE = _c("src/start_menu.c", "1124-1131", "Task_StartMenu_HandleSelection_Save")
S_PANEL_TABLE = _c("asm/overlay_01_021F6830.s", "730-739", "ov01_02206C60")
S_PANEL_CREATE = _c("asm/overlay_01_021F6830.s", "123-146", "ov01_021F68DC")
S_PANEL_SM = _c("asm/overlay_01_021F6830.s", "248-345", "ov01_021F69C0")
S_PANEL_REQ = _c("asm/overlay_01_021F6830.s", "362-380", "ov01_021F6A9C")
S_PANEL0_INIT = _c("asm/overlay_27.s", "7-60", "ov27_02259F80")
S_NAV_FN = _c("asm/overlay_27.s", "2441-2470", "ov27_0225B360")
S_NAV_KEYS = _c("asm/overlay_27.s", "2530-2610", "ov27_0225B404")
S_NAV_CELL = _c("asm/overlay_27.s", "4248-4276", "ov27_0225C170")
S_NAV_TBL = _c("asm/overlay_27.s", "6073-6101", "ov27_0225D0B4")
S_NAV_LAYOUT = _c("asm/overlay_27.s", "6038-6045", "ov27_0225CFC8")
S_TS_ENUM = _c("src/touch_save_app.c", "28-46", "enum TouchSaveApp_State")
S_TS_STRUCT = _c("src/touch_save_app.c", "49-70", "typedef struct TouchSaveAppData")
S_TS_INIT = _c("src/touch_save_app.c", "170-216", "ov30_0225D520")
S_TS_SAVE_CONF = _c("src/touch_save_app.c", "363-399", "TouchSaveApp_HandleSaveConfirmation")
S_TS_OVER_CONF = _c("src/touch_save_app.c", "401-420", "TouchSaveApp_HandleOverwriteConfirmation")
S_TS_CLOSE = _c("src/touch_save_app.c", "488-494", "TouchSaveApp_CloseApp")
S_YN_INIT = _c("src/yes_no_prompt.c", "75-95", "YesNoPrompt_InitFromTemplate_Internal")
S_YN_KEYS = _c("src/yes_no_prompt.c", "144-175", "YesNoPrompt_HandleButtonInput")
S_ENC_START = _c("src/encounter.c", "61-70", "Task_StartBattle")
S_FIELD_LOAD = _c("src/field_system.c", "93", "HandleLoadOverlay(FS_OVERLAY_ID(field)")
S_FIELD_UNLOAD = _c("src/field_system.c", "188", "UnloadOverlayByID(FS_OVERLAY_ID(field))")
S_TITLE_REG = _c("src/field_system.c", "81-85", "Field_AppExit")
S_BOOT_REG = _c("src/main.c", "77", "FS_OVERLAY_ID(intro_title)")
# structural offsets the predicates rely on (each re-read from the clone by the cite test)
S_OVLMGR = _c("include/overlay_manager.h", "20-28", "struct OverlayManager")
S_TASK_STRUCT = _c("include/task.h", "19-28", "struct TaskManager")
S_SM_STRUCT = _c("include/start_menu.h", "43-49", "StartMenuTaskData")
S_SYSTASK = _c("include/sys_task.h", "10-18", "struct SysTask")
S_PROBE_FIELD = [_c("include/field_system.h", "80", "unk0"), _c("include/field_system.h", "81", "unk4"),
                 _c("include/field_system.h", "82", "isPaused"), _c("include/field_system.h", "113", "unk0"),
                 _c("include/field_system.h", "116", "saveData"), _c("include/field_system.h", "117", "taskman"),
                 _c("include/field_system.h", "137", "unk6C"), _c("include/field_system.h", "168", "unk_D8"),
                 _c("src/field_system.c", "97", "OverlayManager_New"), _c("src/field_system.c", "115", "sub_0203DF7C"),
                 _c("src/field_system.c", "123", "sub_0203DFA4"), _c("src/field_system.c", "127", "FieldSystem_LaunchApplication")]

# BATTLE_BASE (asm-literal derived, battle_pointer.md): enemy battler 1 in singles, hp s32 at mons_off + 1*mon_size + hp_off
ENEMY_HP_OFF = BATTLE_BASE["mons_off"] + BATTLE_BASE["mon_size"] + BATTLE_BASE["hp_off"]
OVLMGR_DATA_OFF = 0x1C  # S_OVLMGR: template 0x10, exec_state, proc_state, args 0x18, data 0x1C
PANEL_TASK_OFF = 4  # panel-driver data +4 = the active panel's SysTask* (S_PANEL_CREATE / S_PANEL_REQ)
PANEL_CURSOR_OFF = 0x14  # S_NAV_KEYS: ldr r0,[r5,#0x14] = cursor cell; S_PANEL0_INIT: str r5,[r4,#0x10] = FieldSystem*
TS_STATE_OFF = 0x0C  # S_TS_STRUCT: unk0 0, bgConfig 4, task 8, state 0xC
TS_PROMPT, TS_CLOSE = 4, 15  # TouchSaveApp_State HANDLE_SAVE_CONFIRMATION / CLOSE (S_TS_ENUM)

EXPECT_MAIN_CURSOR = [[0, 0, 0], [1, 3, 2]]  # CURSOR_INPUT_FIGHT=0, BAG=1, POKEMON=2, RUN=3 (include/constants/battle_menu.h:116-121)
EXPECT_FIGHT_CURSOR = [[1, 2], [3, 4], [0, 0]]  # MOVE_1..MOVE_4 = 1..4, FIGHT_CANCEL = 0 (:127-132)
MAIN_NAMES = {0: "FIGHT", 1: "BAG", 2: "POKEMON", 3: "RUN"}
START_NAV = {"image": "ov27", "address": 0x0225D0B4, "cells": 7, "groups": 4, "candidates": 3}
START_LAYOUT = {"image": "ov27", "address": 0x0225CFC8, "variants": 7, "cells_per_variant": 8}
FULL_MENU_VARIANT = [0, 1, 2, 3, 4, 5, 6, 0x0D]  # layout row 0: every icon present; 0x0D = no icon
START_ICONS = ("POKEDEX", "POKEMON", "BAG", "POKEGEAR", "TRAINER_CARD", "SAVE", "OPTIONS")  # include/start_menu.h:11-18 order
UI_CODE = ("BattleInput_CheckTouch", "BattleInput_CheckCursorInput", "BattleInput_CursorMove_MainMenu",
           "BattleInput_CursorSave_MainMenu", "BattleInput_CursorMove_FightMenu", "BattleCursor_CheckKeyInput",
           "sCursorArrayMainMenu", "sCursorArrayFightMenu", "FieldInput_Update", "Task_StartMenu", "Task_StartMenu_HandleInput",
           "StartMenu_HandleKeyInput", "StartMenu_BuildActionLists", "ov27_0225B404", "ov27_0225B360", "ov27_0225C170",
           "ov01_021F68DC", "ov01_021F69C0", "ov01_021F6A9C", "ov01_021F6B00", "ov01_021F6B10", "ov30_0225D520", "ov30_0225D700",
           "TouchSaveApp_HandleSaveConfirmation", "TouchSaveApp_HandleOverwriteConfirmation", "YesNoPrompt_HandleButtonInput",
           "YesNoPrompt_HandleInput_Internal", "DoSoftReset")  # NitroMain (the reset-chord test) differs between HG, SS and hge: not listed


def _check_key(x: int, y: int, xmax: int, ymax: int, grid: list[list[int]], key: str) -> tuple[int, int]:
    """BattleCursor_CheckKeyInput (S_BI_KEY) with the table as moveData: clamp, and stay if the new cell holds the same input."""
    nx, ny = x, y
    if key == "Up":
        ny = max(ny - 1, 0)
    elif key == "Down":
        ny = min(ny + 1, ymax - 1)
    elif key == "Left":
        nx = max(nx - 1, 0)
    elif key == "Right":
        nx = min(nx + 1, xmax - 1)
    return (x, y) if grid[ny][nx] == grid[y][x] else (nx, ny)


def main_menu_step(main: list[list[int]], x: int, y: int, key: str) -> tuple[int, int]:
    """BattleInput_CursorMove_MainMenu (S_BI_MAIN): Up from RUN is a no-op branch; Left/Right on FIGHT jump to the bottom corners."""
    cur = main[y][x]
    if cur == 3 and key == "Up":
        return x, y
    nx, ny = _check_key(x, y, 3, 2, main, key)
    if (nx, ny) == (x, y) and cur == 0 and key in ("Left", "Right"):
        return (0, 1) if key == "Left" else (2, 1)
    return nx, ny


def _run(step, start: tuple[int, int], keys: list[str]) -> tuple[int, int]:
    pos = start
    for key in keys:
        pos = step(*pos, key)
    return pos


def start_menu_path(nav: list[list[list[int]]], src: int, dst: int) -> list[str] | None:
    """Shortest D-pad path between start-menu cells for a full menu (every cell enabled: the first neighbour candidate wins)."""
    seen, queue = {src: []}, [src]
    for cell in queue:
        if cell == dst:
            return seen[cell]
        for d, name in enumerate(DIRS):
            nxt = nav[cell][d][0]
            if nxt not in seen:
                seen[nxt] = seen[cell] + [name]
                queue.append(nxt)
    return None


def ui_geometry(xm: XMap, images: Images, other: Images, other_label: str) -> dict:
    """FILE: the cursor tables and the start-menu neighbour/layout tables, with the byte identity of the UI code vs another ROM."""
    main_sym, fight_sym = xm.lookup("sCursorArrayMainMenu"), xm.lookup("sCursorArrayFightMenu")
    main_raw, fight_raw = images.read(main_sym.image, main_sym.address, 6), images.read(fight_sym.image, fight_sym.address, 6)
    main = [list(main_raw[0:3]), list(main_raw[3:6])]
    fight = [list(fight_raw[0:2]), list(fight_raw[2:4]), list(fight_raw[4:6])]
    if main != EXPECT_MAIN_CURSOR or fight != EXPECT_FIGHT_CURSOR:
        raise Fail(f"battle cursor tables differ from the source ({main}, {fight})")
    # the recipes' D-pad sequences, re-derived on the ROM tables with the source's cursor logic from every start cell
    at = _run
    mstep = lambda x, y, k: main_menu_step(main, x, y, k)  # noqa: E731
    fstep = lambda x, y, k: _check_key(x, y, 2, 3, fight, k)  # noqa: E731
    mains = [(x, y) for y in range(2) for x in range(3)]
    if any(at(mstep, c, ["Left", "Left", "Up"]) != (0, 0) for c in mains):
        raise Fail("[Left, Left, Up] does not reach FIGHT from every main-menu cell")
    if any(main[y][x] != 3 for x, y in (at(mstep, c, ["Left", "Left", "Right"]) for c in mains)):
        raise Fail("[Left, Left, Right] does not reach RUN from every main-menu cell")
    if any(at(fstep, (x, y), ["Up", "Up", "Left"]) != (0, 0) for y in range(3) for x in range(2)):
        raise Fail("[Up, Up, Left] does not reach MOVE_1 from every fight-menu cell")
    n = START_NAV
    nav_raw = images.read(n["image"], n["address"], n["cells"] * n["groups"] * n["candidates"])
    nav = [[list(nav_raw[(c * 4 + d) * 3:(c * 4 + d) * 3 + 3]) for d in range(4)] for c in range(n["cells"])]
    lay = START_LAYOUT
    lay_raw = images.read(lay["image"], lay["address"], lay["variants"] * lay["cells_per_variant"])
    layout = [list(lay_raw[v * 8:v * 8 + 8]) for v in range(lay["variants"])]
    if layout[0] != FULL_MENU_VARIANT:
        raise Fail(f"start-menu layout variant 0 {layout[0]} is not the full menu")
    save_cell = FULL_MENU_VARIANT.index(START_ICONS.index("SAVE"))
    path = start_menu_path(nav, 0, save_cell)
    if path is None:
        raise Fail("the SAVE cell is unreachable in the start-menu neighbour table")
    identity = {}
    for name in UI_CODE:
        s = xm.lookup(name)
        a, b = images.read(s.image, s.address, s.size), other.read(s.image, s.address, s.size)
        if a != b:
            raise Fail(f"UI code {name} differs from {other_label}")
        identity[name] = {"image": s.image, "address": s.address, "size": s.size, "sha1": hashlib.sha1(a).hexdigest()}
    return {
        "battle_main_cursor": {"symbol": "sCursorArrayMainMenu", "image": main_sym.image, "address": main_sym.address, "cells": main,
                               "names": MAIN_NAMES, "evidence": f"FILE: ROM bytes [{ARM9_BYTES_NOTE} when image is arm9]; SOURCE {S_BI_MAIN_TBL} (row 0 = FIGHT x3, row 1 = BAG, RUN, POKEMON)"},
        "battle_fight_cursor": {"symbol": "sCursorArrayFightMenu", "image": fight_sym.image, "address": fight_sym.address, "cells": fight,
                                "names": {0: "CANCEL", 1: "MOVE_1", 2: "MOVE_2", 3: "MOVE_3", 4: "MOVE_4"},
                                "evidence": f"FILE: ROM bytes [{ARM9_BYTES_NOTE} when image is arm9]; SOURCE {S_BI_FIGHT_TBL}"},
        "battle_paths": {"to_FIGHT": ["Left", "Left", "Up"], "to_RUN": ["Left", "Left", "Right"], "fight_to_MOVE_1": ["Up", "Up", "Left"],
                         "evidence": "re-derived by the generator on the ROM tables with the source cursor logic from every start cell "
                                     f"(main_menu_step / _check_key mirror {S_BI_MAIN}, {S_BI_KEY}); the cursor start cell is not assumed"},
        "start_menu": {
            "neighbour_table": {**n, "dir_order": list(DIRS), "rows": nav, "address_hex": f"{n['address']:#010x}",
                                "evidence": f"FILE: ROM bytes [{ARM9_BYTES_NOTE} when image is arm9] at the pret asm label ({S_NAV_TBL}); lookup {S_NAV_FN}: for the pressed direction the first "
                                            "candidate whose cell is enabled wins; direction mapping Up/Down/Left/Right = 0/1/2/3 "
                                            f"({S_NAV_KEYS}, gSystem+0x48 = newKeys, include/system.h:40-48)"},
            "layout_rows": {**lay, "rows": layout, "address_hex": f"{lay['address']:#010x}", "none": 0x0D,
                            "evidence": f"FILE: ROM bytes [{ARM9_BYTES_NOTE} when image is arm9] ({S_NAV_LAYOUT}); row 0 is the full menu: cell c shows icon c"},
            "icon_order": list(START_ICONS),
            "action_of_cell": f"display index = rank of the cell among enabled cells ({S_NAV_CELL}); fs+0xD3 = that index; A selects "
                              f"selectionToAction[index] ({S_SM_KEY}, {S_SM_LISTS})",
            "cursor_to_save": {"from_cell": 0, "to_cell": save_cell, "path": path, "full_menu_only": True,
                               "evidence": "BFS over neighbour_table with every cell enabled; no word reaches SAVE from all start cells, so "
                                           "the leg's `until` verifies the landing cell"},
        },
        "code_identity": {"compared_with": other_label, "symbols": identity,
                          "evidence": "FILE: the full byte range of each UI function/table (xMAP size) is identical in this ROM and the "
                                      "compared ROM, so the pokeheartgold source read applies byte-for-byte; " + ARM9_BYTES_NOTE},
    }


def _step(press: list[str], hold: int, wait: int) -> dict:
    return {"press": press, "hold_frames": hold, "then_wait_frames": wait}


def _pred(deref: list[int], offset: int, **cond) -> dict:
    return {"symbol": "sFieldSysPtr", "deref": deref, "offset": offset, **cond}


def _leg(steps, until, max_frames, evidence, source, starts_from, note=None):
    return {"steps": steps, "until": until, "max_frames": max_frames, "route_status": "recipe_source", "evidence": evidence,
            "source": source, "open": None, "starts_from": starts_from, "note": note}


def _open_leg(reason: str) -> dict:
    return {"steps": [], "until": None, "max_frames": None, "route_status": "open", "evidence": "OPEN", "source": [], "open": reason,
            "starts_from": None, "note": None}


def build_route_legs(ui: dict, build: str) -> dict:
    """titles.<t>.{route_legs, route, persistence_route}: every leg a phase case / row i / row m names, with a recipe or an OPEN reason."""
    sub, launched, taskman = PROBE_FIELD["sub"][0], PROBE_FIELD["launched_app"][0], PROBE_FIELD["task"][0]
    data_off = PROBE_FIELD_EXTRA["save_driver_data_off"][0]
    save_app = [PROBE_FIELD["save_driver"][0], data_off, PANEL_TASK_OFF, data_off]  # fs -> panel driver -> active panel's SysTask data
    task_nonzero, task_zero = _pred([], taskman, nonzero=True), _pred([], taskman, zero=True)
    app_gone = _pred([sub], launched, zero=True)
    enemy_hp_zero = _pred([sub, launched, OVLMGR_DATA_OFF, BATTLE_BASE["ctx_off"]], ENEMY_HP_OFF, zero=True)
    sm = ui["start_menu"]["cursor_to_save"]
    battle_src = [S_BI_TOUCH, S_BI_CURSOR, S_BI_MAIN, S_BI_FIGHT, S_BI_KEY, S_BI_KEYCARRY, S_BI_MAIN_TBL, S_BI_FIGHT_TBL]
    paths = ui["battle_paths"]
    wake = _step(["X"], 2, 20)  # X is in BattleInput_CheckCursorInput's wake set and ignored by BattleCursor_CheckKeyInput
    mash = [_step(["A"], 2, 18) for _ in range(5)]
    battle_note = ("D-pad+A path EXISTS (BattleInput_CheckTouch falls through to BattleInput_CheckCursorInput when no touch hits): the "
                   "cursor starts disabled, the first of A/B/X/Y/D-pad is consumed to enable it (X is harmless afterwards), a key-driven "
                   "selection enables the next menu at once. No menu-ready RAM predicate is pinned (the BattleSystem.battleInput offset "
                   "is unresolved), so `until` is the end condition only and the cycle timing is a PHYSICAL cell")
    legs = {
        "fight_until_enemy_faints": _leg(
            # Row-o PHYSICAL input timing: A wakes, A opens FIGHT, A selects move 1.
            # This fight-to-faint loop still requires its own PHYSICAL replay.
            [_step(["A"], 3, 40), _step(["A"], 3, 50), _step(["A"], 3, 30),
             *[_step(["A"], 2, 44) for _ in range(6)]],
            # Budget (an operational timeout, not the criterion): the DIAGNOSTIC F:/slink-work/lanes/g4/diag-fight-hg-telemetry
            # met `until` at 3280 frames (Cyndaquil L5 vs Rattata L4, 5 hits, ~690-780 frames/turn, no misses). 6000 = 3280 +
            # three extra turns at ~780 (misses / low damage rolls). The old 3000 overran after the frame-1200 RNG shift.
            enemy_hp_zero, 6000, "SOURCE", [*battle_src, S_ENC_START],
            "wild battle settled on the main command menu (gen4_routes:battle_settled)",
            battle_note + "; until = BattleContext.battleMons[1].hp == 0 (singles: the enemy is battler 1; BATTLE_BASE offsets, "
            "asm-literal derived) and is only meaningful after battle_settled (hp is 0 before the party is copied)"),
        "run_from_wild": _leg(
            [wake, *[_step([k], 2, 6) for k in paths["to_RUN"]], _step(["A"], 2, 40), *mash],
            app_gone, 2400, "SOURCE", battle_src, "wild battle settled on the main command menu (gen4_routes:battle_settled)",
            battle_note + "; a failed escape returns to the menu with the cursor on RUN and the cycle retries; until = the launched-app "
            "OverlayManager is gone (sFieldSysPtr->unk0->unk4 == 0)"),
        "exit_battle_to_overworld": _leg(
            [_step(["A"], 2, 18)], task_zero, 3000, "SOURCE", [S_ENC_START, S_FIELD_INPUT],
            "enemy fainted (or escaped); battle text / exp / level-up boxes pending",
            "A-mash dismisses text; until = FieldSystem.taskman == 0 (the encounter task, which holds the field while the battle app "
            "runs, has ended). OPEN: A answers Yes on a move-learn / evolution prompt, so the fixture mon must not have a full moveset "
            "or an evolution due"),
        "soft_reset_in_fight_menu": _leg(
            [_step(["Start", "Select", "L", "R"], 10, 600)], _pred([], 0, zero=True), 900, "SOURCE", [S_MAIN_RESET, S_DO_RESET],
            "battle main command menu (any state: NitroMain tests heldKeysRaw every main-loop frame unless softResetDisabled)",
            "until reads sFieldSysPtr itself, which the start-up .bss clear zeroes: a NULL base must count as satisfying `zero` (the "
            "probe's active() returns false on a NULL link, so this one leg needs that exception). OPEN: the chord test is inline in "
            "NitroMain, whose bytes differ between HG, SS and hge, so it is read from the HG source only (DoSoftReset is byte-identical)"),
        "open_start_menu": _leg(
            [_step(["X"], 2, 30)], task_nonzero, 300, "SOURCE", [S_FIELD_INPUT, S_X_OPENS, S_OPEN_CALL, S_SM_INIT, S_BTN_MODE],
            "overworld idle (FieldSystem.taskman == 0, no launched app)",
            "X opens the HGSS menu (FieldInput_Update tests newKeys & 0x400, FieldInput_Process then calls StartMenu_Init); Start does "
            "nothing in the default button mode. OPEN: the owner save's Options.buttonMode is not decoded (BUTTONMODE_STARTEQUALSX "
            "would also accept Start); until = a field task exists (StartMenu_Init creates one)"),
        "start_menu_cursor_to_save": _leg(
            [_step([k], 2, 10) for k in sm["path"]], _pred(save_app, PANEL_CURSOR_OFF, value=sm["to_cell"]), 120, "FILE",
            [S_NAV_TBL, S_NAV_FN, S_NAV_KEYS, S_NAV_CELL, S_NAV_LAYOUT, S_PANEL0_INIT, S_PANEL_TABLE],
            f"start menu open, cursor on cell {sm['from_cell']} (Pokedex), fully unlocked menu",
            "path = BFS over the ROM neighbour table; until = panel cursor cell (panel data +0x14) == SAVE's cell, read through "
            "fs+0xD8 -> data -> +4 panel SysTask -> data. OPEN: (1) the cursor starts on the last used item (fs+0x90, start_menu.c:458-463), "
            "its writer is asm-only, so a non-zero start misses the cell and the leg times out instead of pressing A; (2) a menu without "
            "Pokedex/Pokemon/Bag/Pokegear uses another layout row (ui_geometry.start_menu.layout_rows) and that cell is not SAVE: the "
            "fixture must be the fully unlocked menu"),
        "start_menu_select_save": _leg(
            [_step(["A"], 2, 22)], _pred(save_app, TS_STATE_OFF, value=TS_PROMPT), 900, "SOURCE",
            [S_SM_KEY, S_SM_SAVE, S_PANEL_REQ, S_PANEL_SM, S_PANEL_TABLE, S_TS_INIT, S_TS_ENUM, S_TS_STRUCT],
            "start menu open, cursor on SAVE",
            "A runs StartMenu_HandleKeyInput -> Task_StartMenu_HandleSelection_Save -> panel-driver mode 1 (touch save app, ov30); until = "
            "TouchSaveAppData.state == HANDLE_SAVE_CONFIRMATION (4: the Yes/No prompt is up)"),
        "save_confirm_until_saved": _leg(
            [_step(["A"], 2, 22)], _pred(save_app, TS_STATE_OFF, value=TS_CLOSE), 2400, "SOURCE",
            [S_YN_INIT, S_YN_KEYS, S_TS_SAVE_CONF, S_TS_OVER_CONF, S_TS_CLOSE, S_TS_ENUM],
            "save Yes/No prompt up (touch save app state 4)",
            "the Yes/No prompt starts on Yes with keys (inTouchMode FALSE) so A confirms; a second prompt (state 7, overwrite) appears "
            "when a save file exists and the repeated A answers Yes again; A is ignored in every other state. until = state CLOSE (15), "
            "which lasts 30+ frames (TouchSaveApp_CloseApp) so `until` must be evaluated every frame. It is also reached by the "
            "NOT_MY_SAVE / SAVE_FAILED paths: row i's Save_WriteManFinish hit count is the success evidence"),
        "close_start_menu": _leg(
            [_step([], 0, 90), _step(["B"], 2, 40)], task_zero, 600, "SOURCE", [S_SM_INPUT, S_SM_SAVE],
            "start menu open (after a save the panel returns to the menu: Task_StartMenu_HandleInput)",
            "B (or X) closes the menu when no touch input is pending (start_menu.c:574-577); the leading wait lets the save panel finish "
            "returning; until = FieldSystem.taskman == 0"),
        "gen4_routes:battle_settled": _open_leg(
            "EXISTS as tools/gen4_routes.py + lua/tests/gen4_route_play.lua (CONTINUE, planned walk with per-tile RAM checks, wild "
            "encounter, settle on the main menu; C1-9 receipt route_leg2_battle_settled): a verified walk, not a fixed button recipe"),
        "boot_continue_to_overworld": _open_leg(
            "EXISTS as the boot loop in lua/tests/probe_gen4_hooks.lua (A/Start cadence until the compound idle_field predicate: taskman "
            "== 0, live != 0, no launched app); no single RAM predicate expresses it"),
        **dict.fromkeys(PC_LEGS, _open_leg(_PC_ROUTED)),
        "pc_withdraw_box_mon": _open_leg(_PC_WITHDRAW_OPEN),
    }
    if build == "hge":
        legs["fight_until_enemy_faints"]["note"] += ("; hge: the chain assumes hge's ServerInit leaves bs->ctx at +0x30 "
                                                      "(research R9), a PHYSICAL cell")
    return {
        "route_legs": legs,
        "route": ["gen4_routes:battle_settled", "fight_until_enemy_faints", "exit_battle_to_overworld", "open_start_menu", "close_start_menu"],
        "persistence_route": ["open_start_menu", "start_menu_cursor_to_save", "start_menu_select_save", "save_confirm_until_saved",
                              "close_start_menu"],
    }


def _predicate_errors(where: str, pred: object, known: set[str]) -> list[str]:
    if not isinstance(pred, dict):
        return [f"{where}: until must be a predicate object"]
    errs = []
    if pred.get("symbol") not in known:
        errs.append(f"{where}: until.symbol {pred.get('symbol')!r} is not a symbol of this title's xMAP")
    if not isinstance(pred.get("deref"), list) or not all(isinstance(o, int) and not isinstance(o, bool) for o in pred["deref"]):
        errs.append(f"{where}: until.deref must be a list of integer offsets")
    if not isinstance(pred.get("offset"), int) or isinstance(pred.get("offset"), bool):
        errs.append(f"{where}: until.offset must be an integer")
    conds = [k for k in ("value", "nonzero", "zero") if k in pred]
    if len(conds) != 1 or (conds[0] != "value" and pred[conds[0]] is not True):
        errs.append(f"{where}: until needs exactly one of value / nonzero:true / zero:true")
    return errs


def validate_route_legs(title: dict) -> list[str]:
    """Pure check of titles.<t>.route_legs / route / persistence_route against the title's own symbols and phase cases."""
    errs, legs, known = [], title.get("route_legs") or {}, set(title["symbols"])
    if not legs:
        return ["route_legs missing or empty"]
    for name, leg in legs.items():
        where = f"route_legs.{name}"
        status = leg.get("route_status")
        if status not in ("recipe_source", "open") or leg.get("evidence") not in ("SOURCE", "FILE", "OPEN"):
            errs.append(f"{where}: route_status must be recipe_source|open and evidence SOURCE|FILE|OPEN")
        if status == "open":
            if leg.get("steps") != [] or leg.get("until") is not None or not leg.get("open") or leg.get("evidence") != "OPEN":
                errs.append(f"{where}: an open leg keeps steps [], until null, evidence OPEN and a reason")
            continue
        steps = leg.get("steps")
        if not isinstance(steps, list) or not steps:
            errs.append(f"{where}: a recipe needs steps")
            steps = []
        cycle = 0
        for i, st in enumerate(steps):
            press = st.get("press")
            if not isinstance(press, list) or any(b not in NDS_BUTTONS for b in press) or len(set(press)) != len(press):
                errs.append(f"{where}.steps[{i}]: press must be distinct BizHawk NDS buttons {NDS_BUTTONS}")
            hold, wait = st.get("hold_frames"), st.get("then_wait_frames")
            if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (hold, wait)) or not (hold or wait):
                errs.append(f"{where}.steps[{i}]: hold_frames / then_wait_frames must be non-negative integers, not both 0")
                continue
            if press and not hold:
                errs.append(f"{where}.steps[{i}]: a press needs hold_frames >= 1")
            cycle += hold + wait
        errs += _predicate_errors(where, leg.get("until"), known)
        mf = leg.get("max_frames")
        if not isinstance(mf, int) or isinstance(mf, bool) or not (0 < mf <= ROUTE_MAX_FRAMES):
            errs.append(f"{where}: max_frames must be a bounded integer in 1..{ROUTE_MAX_FRAMES}")
        elif cycle > mf:
            errs.append(f"{where}: one cycle ({cycle} frames) exceeds max_frames {mf}")
        if not leg.get("source") or leg.get("open") is not None:
            errs.append(f"{where}: a recipe carries source citations and open null")
    named = {"route": title.get("route"), "persistence_route": title.get("persistence_route")}
    for case in [*title.get("phase_cases", []), *title.get("phase_cases_blocked", [])]:
        named[f"phase_case:{case['name']}.route"] = case.get("route")
    for where, route in named.items():
        if not route or not isinstance(route, list):
            errs.append(f"{where}: must be a non-empty list of leg names")
            continue
        errs += [f"{where}: leg {leg!r} is not in route_legs" for leg in route if leg not in legs]
    return errs


# Symbols from different images at ONE cpu address: a capture must be attributed to the image that is resident at that moment
COLLISION_SPECS = [{
    "name": "field_vblank_vs_title_init",
    "sites": [("field_vblank_ov1", "FieldMap_VBlankCallback", "ov1 (field overlay): the field's per-frame VBlank callback"),
              ("title_init_ov60", "TitleScreen_Init", "ov60 (intro_title overlay): title-screen init")],
}]


def collision_pairs(xm: XMap, images: Images, build: str, vanilla: Images | None = None) -> list[dict]:
    out = []
    for spec in COLLISION_SPECS:
        rows = vanilla_sites(xm, images, [(sid, sym, "probe", role, "ANY") for sid, sym, role in spec["sites"]])
        first, second = (rows[sid] for sid, _, _ in spec["sites"])
        if first["address"] != second["address"] or first["image"] == second["image"] or first["fire_hex"] == second["fire_hex"]:
            raise Fail(f"{spec['name']}: expected one address in two images with different first words")
        errs = validate_sites(rows, images, spec["name"])
        if errs:
            raise Fail("; ".join(errs))
        if vanilla is not None:  # hge: the shared-address claim is only inherited if the bytes really equal vanilla
            base = vanilla_sites(xm, vanilla, [(sid, sym, "probe", role, "ANY") for sid, sym, role in spec["sites"]])
            if any(base[sid]["register_hex"] != rows[sid]["register_hex"] for sid in rows):
                raise Fail(f"{spec['name']}: hge bytes differ from vanilla at the shared address")
        pair = {
            "name": spec["name"], "address": first["address"], "address_hex": first["address_hex"], "sites": rows,
            "resident_when": {
                spec["sites"][0][0]: {"overlay_id": first["overlay_id"], "when": (
                    "from the field overlay load (FieldSystem_LoadFieldOverlayInternal) through every launched app, battle included, "
                    "until the field overlay is unloaded when the field app exits"),
                    "evidence": [S_FIELD_LOAD, S_FIELD_UNLOAD, "xMAP SDK_OVERLAY_field_ID = 0x1 (heartgoldus.xMAP:53316)"]},
                spec["sites"][1][0]: {"overlay_id": second["overlay_id"], "when": (
                    "only while the intro_title main overlay runs: after a soft reset / power-on (NitroMain registers the intro movie, "
                    "whose app goes on to the title screen) and after the field app exits (Field_AppExit); never during the field or a battle"),
                    "evidence": [S_BOOT_REG, S_TITLE_REG, "xMAP SDK_OVERLAY_intro_title_ID = 0x3C (heartgoldus.xMAP:135346)"]},
            },
            "exclusive": "ov1 and ov60 are main-overlay images loaded to the same RAM base (FILE: overlays[1].ram == overlays[60].ram): at "
                         "most one is resident, the other's bytes are not at this address",
            "wrong_owner_capture": f"registering {spec['sites'][1][0]} while the field runs (or {spec['sites'][0][0]} at the title) fires at "
                                   "the same CPU address with the OTHER image's word: fire_hex differs, so a capture that checks residency "
                                   "and fire_hex rejects it",
            "evidence": "FILE: both symbols from the xMAP (heartgoldus.xMAP:53320 and :135351; soulsilverus.xMAP has the same lines), "
                        "bytes read from each declared image; the two first words differ",
            "open": [],
        }
        if build == "hge":
            pad = images.read("arm9", first["address"], first["extent"])
            pair["hge_note"] = ("FILE: ov1 and ov60 hold the same bytes as vanilla at the shared address; `collides_with` also lists arm9 "
                                "because the hge raw ARM9 file is padded to 0x2477C8 (hge writes its overlay-2 hooks into base/arm9.bin, "
                                "docs/gen4/research/hg_engine.md:149); the arm9 bytes at the shared address are " +
                                ("all zero padding, not a third owner" if not any(pad) else "NOT zero: a third owner"))
            if any(pad):
                pair["open"].append("hge raw ARM9 holds non-zero bytes at the shared address: the residency of a third image is unresolved")
        out.append(pair)
    return out


def validate_collision_pairs(title: dict) -> list[str]:
    errs, pairs = [], title.get("collision_pairs") or []
    if not pairs:
        return ["collision_pairs missing or empty"]
    for pair in pairs:
        where = f"collision_pair:{pair.get('name')}"
        sites = list((pair.get("sites") or {}).values())
        if len(sites) < 2:
            errs.append(f"{where}: needs at least two sites")
            continue
        if len({s["address"] for s in sites}) != 1 or any(s["address"] != pair.get("address") for s in sites):
            errs.append(f"{where}: sites must share one address (the pair's address)")
        if len({s["image"] for s in sites}) != len(sites):
            errs.append(f"{where}: sites must live in different images")
        if len({s["fire_hex"] for s in sites}) != len(sites):
            errs.append(f"{where}: first words must differ, or a wrong-owner capture is indistinguishable")
        if set(pair.get("resident_when") or {}) != set(pair["sites"]):
            errs.append(f"{where}: resident_when must name every site")
        for sid, s in pair["sites"].items():
            ov = title["overlays"].get(str(s.get("overlay_id")))
            if ov is None or not (ov["ram"] <= s["address"] and s["address"] + s["extent"] <= ov["ram"] + ov["size"]):
                errs.append(f"{where}: site {sid} is not inside overlay {s.get('overlay_id')}'s RAM span")
    return errs


# --------------------------------------------------------------------------------------------
# Pack builders
# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------
# Battle block, battle enums, admission anchors, diagnostic sites (card C1-2d)
# --------------------------------------------------------------------------------------------
# Every value carries SOURCE / ASM / FILE evidence with a citation; an unknown is null with its reason in `open`. Citations into
# the three source trees are registered so a test re-reads the first line of each from the pinned clone (CITE_NEEDLES: pokeheartgold,
# CITE_NEEDLES_HGE: the hg-engine fork, CITE_NEEDLES_PT: pokeplatinum).
CITE_NEEDLES_HGE: list[tuple[str, int, str]] = []  # (path in the hg-engine fork @fc517576, first line, text that line must contain)
CITE_NEEDLES_PT: list[tuple[str, int, str]] = []  # (path in pokeplatinum @c248fb3f, first line, text that line must contain)


def _cite(bucket: list, path: str, spec: str, needle: str) -> str:
    bucket.append((path, int(spec.split("-")[0]), needle))
    return f"{path}:{spec}"


def _ch(path: str, spec: str, needle: str) -> str:
    return _cite(CITE_NEEDLES_HGE, path, spec, needle)


def _cp(path: str, spec: str, needle: str) -> str:
    return _cite(CITE_NEEDLES_PT, path, spec, needle)


_BH, _CB = "include/battle/battle.h", "include/constants/battle.h"
_ASM12 = "asm/overlay_12_022378C0.s"
S_GSYSTEM = _c("src/system.c", "10", "struct System gSystem")
S_BS_MGR_ALLOC = _c(_ASM12, "4268", "=0x00002490")
S_BS_STRUCT = _c(_BH, "527-540", "struct BattleSystem {")
S_BS_TYPE, S_BS_CTX = _c(_BH, "539", "u32 battleType"), _c(_BH, "540", "BattleContext *ctx")
S_BS_OUTCOME = _c(_BH, "605", "u8 battleOutcomeFlag")
S_BS_OUTCOME_ASM = _c(_ASM12, "964-968", "ldrb r3, [r4, r1]")  # ldrb [bs+0x2414+0xC]; mov r1,#0x3f; and; str [setup+0x14]
S_BS_OUTCOME_LIT = _c(_ASM12, "857", "=0x00002420")
S_BS_CTX_ASM = _c(_ASM12, "1802", "str r0, [r4, #0x30]")
S_CTX_STATUS = _c(_BH, "359", "u32 battleStatus")
S_CTX_SEL = _c(_BH, "383", "u8 selectedMonIndex")
S_CTX_MONS = _c(_BH, "394", "BattleMon battleMons")
S_CTX_SEL_ASM = _c("asm/overlay_10_trainer_ai.s", "2148", "=0x0000219C")
S_CTX_STATUS_ASM = _c("asm/overlay_10_trainer_ai.s", "6922", "=0x0000213C")
S_CTX_MONS_ASM = _c("asm/overlay_12_battle_controller.s", "341", "=0x00002DBE")  # 0x2D40 + BattleMon.gender 0x7E
S_MON_STRUCT = _c(_BH, "207-266", "typedef struct BattleMon {")
S_MON = {k: _c(_BH, str(n), needle) for k, (n, needle) in {
    "species": (208, "u16 species"), "moves": (214, "u16 moves[MAX_MON_MOVES]"), "pp": (243, "u8 movePPCur[MAX_MON_MOVES]"),
    "ability": (230, "u8 ability"), "level": (245, "u8 level"), "hp": (248, "s32 hp"),
    "max_hp": (249, "u32 maxHp"), "personality": (252, "u32 personality"), "otid": (255, "u32 otid")}.items()}
S_BATTLER_MAX = _c(_CB, "10", "BATTLER_MAX")
S_OUTCOMES = _c(_CB, "112-118", "BATTLE_OUTCOME_NONE")
S_RESULTS = _c(_CB, "122-130", "BATTLE_RESULT_WIN")
S_TYPES = _c(_CB, "133-148", "BATTLE_TYPE_NONE")
S_FAINTED, S_FAINTED_SHIFT = _c(_CB, "520", "BATTLE_STATUS_FAINTED"), _c(_CB, "523", "BATTLE_STATUS_FAINTED_SHIFT")
S_ENC_WILD_TYPES = _c("src/encounter.c", "137", "BATTLE_TYPE_ROAMER")
S_ENC_TRAINER_TYPES = _c("src/encounter.c", "696-716", "SetupAndStartTrainerBattle")

H_BS_TYPE, H_BS_CTX = _ch("include/battle.h", "1586", "u32 battleType"), _ch("include/battle.h", "1587", "struct BattleStruct *sp")
H_CTX_MONS, H_CTX_SEL = _ch("include/battle.h", "1403", "battlemon[CLIENT_MAX]"), _ch("include/battle.h", "1392", "sel_mons_no[CLIENT_MAX]")
H_CTX_STATUS = _ch("include/battle.h", "1365", "server_status_flag")
H_MON_STRUCT = _ch("include/battle.h", "859", "struct BattlePokemon")
H_MON = {k: _ch("include/battle.h", str(n), needle) for k, (n, needle) in {
    "species": (860, "u16 species"), "moves": (866, "u16 move[4]"), "pp": (900, "u8 pp[4]"), "level": (902, "u8 level"), "hp": (905, "s32 hp"), "max_hp": (906, "u32 maxhp"),
    "personality": (909, "u32 personal_rnd"), "otid": (912, "u32 id_no"), "ability": (914, "u16 ability")}.items()}
H_CLIENT_MAX = _ch("include/battle.h", "14", "CLIENT_MAX 4")
H_FAINTED, H_FAINTED_SHIFT = _ch("include/battle.h", "614", "BATTLE_STATUS_FAINTED"), _ch("include/battle.h", "617", "BATTLE_STATUS_FAINTED_SHIFT")
H_TYPES = _ch("include/battle.h", "159-172", "BATTLE_TYPE_SINGLE")
H_OUTCOMES = _ch("include/battle_controller_player.h", "7-13", "BATTLE_OUTCOME_NONE")

P_TYPES, P_RESULTS = _cp("include/constants/battle.h", "24-37", "BATTLE_TYPE_SINGLES"), _cp("include/constants/battle.h", "72-80", "BATTLE_RESULT_WIN")
P_SYSTEM = _cp("include/system.h", "30-66", "typedef struct System {")
P_VBLANK = _cp("include/system.h", "42", "u32 vblankCounter")
P_VBLANK_INC = _cp("src/main.c", "138", "gSystem.vblankCounter++")

_PHYS_HG = "docs/gen4/research/battle_faint_seam.md"
# PHYSICAL corroboration (heap addresses of one run; NOT values to match against, and never pack inputs).
BATTLE_PHYSICAL = {
    "heartgold": [
        {"commit": "89b957d1", "ctx": 0x022C32D8, "fs": 0x022A01EC,
         "what": "zero-hook chain sFieldSysPtr -> unk0 -> unk4 -> man+0x1C -> bs+0x30 acquired live, wild PIDGEY L2 at the FIGHT menu"},
        {"commit": "a15b7d74", "doc": f"{_PHYS_HG} section 9",
         "what": "live HG: both HP copies written at ctx+0x2D40+0xC0*b+0x4C (4 bytes), FAINTED bit set at ctx+0x213C and consumed by "
                 "TryFaintMon, game result byte bs+0x2420 == 2 (LOSE)"},
    ],
    "soulsilver": [],
    "heartgold_hge": [
        {"commit": "89b957d1", "ctx": 0x022D38A4, "fs": 0x022AC208,
         "what": "zero-hook chain acquired live on the pinned hge build, wild PIDGEY L3 at the FIGHT menu, battleMons[0] = Cyndaquil"},
        {"commit": "0f75c938", "doc": f"{_PHYS_HG} section 10",
         "what": "live hge: both HP copies + FAINTED bit via the command-9 seam, bs+0x2420 == 2 (LOSE), save HP 0 at HealParty entry"},
    ],
}

# The BattleSystem accessors whose whole bodies pin three offsets in the ROM bytes (FILE): `ldr r0,[r0,#imm]; bx lr` (Thumb).
BATTLE_ACCESSORS = (
    ("BattleSystem_GetBattleType", "c06a7047", "ldr r0,[r0,#0x2c]; bx lr", "type_off", 0x2C),
    ("BattleSystem_GetBattleContext", "006b7047", "ldr r0,[r0,#0x30]; bx lr", "ctx_off", 0x30),
    ("BattleSystem_GetBattleOutcomeFlags", "0149405c7047c04620240000",
     "ldr r1,[pc,#4]; ldrb r0,[r0,r1]; bx lr; nop; .word 0x2420", "outcome_off", 0x2420),
)
OUTCOME_STORE_SEQ = bytes.fromhex("635c3f21283219407961")  # ldrb r3,[r4,r1]; movs r1,#0x3f; adds r2,#0x28; ands r1,r3; str r1,[r7,#0x14]


def battle_file_checks(xm: XMap, images: Images) -> dict:
    """FILE: each accessor body in the declared ROM image is the expected Thumb sequence (HG==SS and hge-identical by construction)."""
    out = {}
    for sym, want, decodes, field, value in BATTLE_ACCESSORS:
        s = xm.lookup(sym)
        got = images.read(s.image, s.address, s.size).hex()
        if got != want:
            raise Fail(f"{sym} bytes {got} != the pinned accessor {want}: {field} {value:#x} is no longer ROM-proven")
        out[sym] = {"symbol": sym, "address": s.address, "image": s.image, "bytes": got, "decodes_as": decodes,
                    "field": field, "value": value, "bytes_source": ARM9_BYTES_NOTE if s.image == "arm9" else f"decompressed {s.image}"}
    return out


def hge_battle_checks(xm: XMap, hg: Images, hge: Images) -> dict:
    """FILE: the hge image keeps the accessors and the outcome store (vanilla ov12_0223843C differs only in one hooked window)."""
    out = {"accessors_identical": {}}
    for sym, *_ in BATTLE_ACCESSORS:
        s = xm.lookup(sym)
        if hge.read(s.image, s.address, s.size) != hg.read(s.image, s.address, s.size):
            raise Fail(f"hge {sym} differs from vanilla: its battle offset is no longer a projection")
        out["accessors_identical"][sym] = True
    s = xm.lookup("ov12_0223843C")
    a, b = hg.read(s.image, s.address, s.size), hge.read(s.image, s.address, s.size)
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    k = a.find(OUTCOME_STORE_SEQ)
    if k < 0 or b[k:k + len(OUTCOME_STORE_SEQ)] != OUTCOME_STORE_SEQ or any(k <= d < k + len(OUTCOME_STORE_SEQ) for d in diff):
        raise Fail("hge changed the BattleSystem outcome store (ldrb [bs+0x2420]; and #0x3f; str [setup+0x14])")
    if struct.pack("<I", 0x2420) not in b:
        raise Fail("hge ov12_0223843C lost the 0x2420 literal")
    return {**out, "outcome_store": {
        "symbol": "ov12_0223843C", "function_address": s.address, "store_address": s.address + k, "bytes": OUTCOME_STORE_SEQ.hex(),
        "identical_in_hge": True, "literal_0x2420_present": True,
        "function_differs_at": sorted({s.address + d for d in diff}),
        "note": "the function differs from vanilla only at the listed hooked bytes, away from the store"},
        "evidence": f"FILE: vanilla xMAP symbol bytes compared in the hge image (declared image); {ARM9_BYTES_NOTE}"}


def _ev(cls: str, *parts: str) -> dict:
    return {"class": cls, "cite": "; ".join(parts)}


def battle_owners() -> dict:
    """{field: (owning struct, citation)}: the battle fields live in different structs (BattleSystem holds a pointer to the BattleContext
    that holds the battlers), so the offset of each is relative to ITS owner, not to one flat base. Layout: pokeheartgold battle.h."""
    bs, ctx, mon = f"{_BH}:527 (struct BattleSystem)", f"{_BH}:279-437 (struct BattleContext)", f"{_BH}:207-266 (struct BattleMon)"
    own = {
        "man_data_off": ("OverlayManager", S_OVLMGR),
        "ctx_off": ("BattleSystem", f"{bs}; BattleSystem.ctx -> BattleContext {S_BS_CTX}"),
        "type_off": ("BattleSystem", f"{bs}; {S_BS_TYPE}"),
        "outcome_off": ("BattleSystem", f"{bs}; {S_BS_OUTCOME}; the 0x2420 comes from the BattleSystem_GetBattleOutcomeFlags accessor literal "
                                        "(profile.battle_file_checks, FILE-checked in the ROM), not from the source header"),
        "outcome_mask": ("BattleSystem", f"{bs}; battleOutcomeFlag masked into BattleSetup.winFlag"),
        "template_off": ("OverlayManagerTemplate", S_OVLMGR), "template_id": ("OverlayManagerTemplate", S_OVLMGR),
        "mons_off": ("BattleContext", f"{ctx}; {S_CTX_MONS}"),
        "mon_size": ("BattleMon", mon),
        "max_battlers": ("constant", "CLIENT_MAX / BATTLER_MAX = 4 (the length of the BattleContext per-battler arrays)"),
        "selected_off": ("BattleContext", f"{ctx}; {S_CTX_SEL}"),
        "fainted_flag_off": ("BattleContext", f"{ctx}; {S_CTX_STATUS}"),
        "fainted_flag_shift": ("BattleContext", f"{ctx}; {S_CTX_STATUS}"), "fainted_flag_mask": ("BattleContext", f"{ctx}; {S_CTX_STATUS}"),
        "hp_off": ("BattleMon", f"{mon}; {S_MON['hp']}"), "hp_width": ("BattleMon", f"{mon}; {S_MON['hp']} (s32)"),
        "hp_signed": ("BattleMon", f"{mon}; {S_MON['hp']} (s32)"),
    }
    for key in ("species_off", "level_off", "moves_off", "pp_off", "max_hp_off", "personality_off", "otid_off", "ability_off", "ability_width"):
        own[key] = ("BattleMon", mon)
    return own


def battle_evidence(build: str, template: dict) -> dict:
    """{field: {class, cite}} for profile.battle. build = hgss (HG and SS: same ROM code, asserted) | hge."""
    hge = build == "hge"

    def R(hge_ref: str, hg_ref: str) -> str:
        return f"{HGE_SRC} {hge_ref}" if hge else f"{PRET_HG} {hg_ref}"

    file_acc = ("FILE: profile.battle_file_checks (accessor body in the ROM" + (", byte-identical in hge)" if hge else ")")
                + f" [{ARM9_BYTES_NOTE}]")
    ovl = (f"FILE: OverlayManagerTemplate.ovy_id read from the ROM at {template['symbol']} (phase_cases[].predicate_file_check); "
           f"{PRET_HG} {S_OVLMGR}: the template is embedded at offset 0, ovy_id is its 4th word (+0x0C)")

    def mon(key: str) -> dict:
        return _ev("SOURCE", R(f"{H_MON_STRUCT} / {H_MON[key]} (explicit offset comment)",
                               f"{S_MON_STRUCT} / {S_MON[key]} (field order; offset hand-counted and equal to the hge comment)"))

    hp_ref = R(H_MON["hp"], S_MON["hp"])
    ev = {
        "man_data_off": _ev("ASM", f"{PRET_HG} {S_OVLMGR} (template 0x10, exec_state 0x10, proc_state 0x14, args 0x18, data 0x1C)",
                            f"{S_BS_MGR_ALLOC} (OverlayManager_CreateAndGetData(man, 0x2490, HEAP_ID_BATTLE) allocates the BattleSystem into manager->data)",
                            "docs/gen4/research/battle_pointer.md"),
        "ctx_off": _ev("FILE", file_acc + " BattleSystem_GetBattleContext = ldr r0,[r0,#0x30]", R(H_BS_CTX, S_BS_CTX),
                       f"{PRET_HG} {S_BS_CTX_ASM} (BattleContext_New result stored at bs+0x30)"),
        "type_off": _ev("FILE", file_acc + " BattleSystem_GetBattleType = ldr r0,[r0,#0x2c]", R(H_BS_TYPE, S_BS_TYPE)),
        "outcome_off": _ev("FILE", file_acc + " BattleSystem_GetBattleOutcomeFlags = ldrb r0,[r0,#0x2420 literal]",
                           f"{PRET_HG} {S_BS_OUTCOME} (BattleSystem.battleOutcomeFlag, u8); {S_BS_OUTCOME_LIT}"),
        "outcome_mask": _ev("FILE" if hge else "ASM",
                            f"{PRET_HG} {S_BS_OUTCOME_ASM} (the outcome copy stores byte & 0x3F into BattleSetup.winFlag)",
                            f"{PRET_HG} {S_RESULTS} (BATTLE_RESULT_TRY_FLEE_WAIT 0x40 and TRY_FLEE 0x80 are transient flag bits above the 0x3F result bits)"
                            + ("; hge: profile.battle_hge_checks.outcome_store (the same bytes, FILE)" if hge else "")),
        "template_off": _ev("FILE", ovl), "template_id": _ev("FILE", ovl),
        "max_battlers": _ev("SOURCE", R(H_CLIENT_MAX + " (CLIENT_MAX 4)", S_BATTLER_MAX + " (BATTLER_MAX 4); BattleContext arrays are [4]")),
        "mons_off": _ev("ASM", R(H_CTX_MONS + " (`/*0x2D40*/ battlemon[CLIENT_MAX]`, explicit)", S_CTX_MONS + " (BattleContext.battleMons)"),
                        f"{PRET_HG} {S_CTX_MONS_ASM} (literal 0x2DBE = 0x2D40 + BattleMon.gender 0x7E)",
                        "docs/gen4/research/battle_pointer.md (asm-literal-derived; not 0x2D4C, which is moves[0])"),
        "mon_size": _ev("SOURCE", R(H_CTX_MONS + " (`// 0xc0`)", S_MON_STRUCT + " (sizeof(BattleMon) = 0xC0, equal to the hge `// 0xc0` and battle_pointer.md)"),
                        "PHYSICAL: battler 1 read and written at +0xC0 live (profile.battle_physical)"),
        "selected_off": _ev("ASM", R(H_CTX_SEL + " (`/*0x219C*/ sel_mons_no`, explicit)", S_CTX_SEL),
                            f"{PRET_HG} {S_CTX_SEL_ASM} (literal 0x219C, ldrb)"),
        "species_off": mon("species"), "level_off": mon("level"), "moves_off": mon("moves"), "pp_off": mon("pp"), "hp_off": mon("hp"), "max_hp_off": mon("max_hp"),
        "personality_off": mon("personality"), "otid_off": mon("otid"),
        "hp_width": _ev("SOURCE", hp_ref + " (s32: all four bytes are the value, a 2-byte write leaves a stale high half)",
                        "docs/gen4/research/battle_faint.md"),
        "hp_signed": _ev("SOURCE", hp_ref + " (s32)"),
        "fainted_flag_off": _ev("ASM", R(H_CTX_STATUS + " (`/*0x213C*/ server_status_flag // battleStatus`)", S_CTX_STATUS + " (BattleContext.battleStatus, u32)"),
                                f"{PRET_HG} {S_CTX_STATUS_ASM} (literal 0x213C)"),
        "fainted_flag_shift": _ev("SOURCE", R(H_FAINTED_SHIFT, S_FAINTED_SHIFT) + " (BATTLE_STATUS_FAINTED_SHIFT 24: battler b fainting = bit 24+b)"),
        "fainted_flag_mask": _ev("SOURCE", R(H_FAINTED, S_FAINTED) + " (BATTLE_STATUS_FAINTED = 15 << 24)"),
        "ability_off": _ev("SOURCE", f"{HGE_SRC} {H_MON['ability']} (u16 ability at 0x7A, moved from 0x27)") if hge
        else _ev("SOURCE", f"{PRET_HG} {S_MON['ability']} (u8 ability at 0x27)"),
        "ability_width": _ev("SOURCE", f"{HGE_SRC} {H_MON['ability']} (u16)") if hge else _ev("SOURCE", f"{PRET_HG} {S_MON['ability']} (u8)"),
    }
    for key, (owner, cite) in battle_owners().items():
        ev[key]["owner"] = {"struct": owner, "cite": f"{PRET_HG} {cite}"}
    if hge:
        for key in ("man_data_off", "mons_off", "mon_size", "selected_off"):
            ev[key]["note"] = ("SOURCE_PROJECTION onto hge where the fork declares no offset; hge allocates its own BattleStruct but keeps "
                               "the vanilla OverlayManager code; PHYSICAL: profile.battle_physical")
        ev["outcome_off"]["note"] = "ROM accessor byte-identical in hge; PHYSICAL: result byte 2 at bs+0x2420 observed on the pinned hge build"
    return ev


def battle_values(template: dict, build: str) -> dict:
    return {
        "man_data_off": 0x1C, "ctx_off": 0x30, "type_off": 0x2C, "outcome_off": 0x2420, "outcome_mask": 0x3F,
        "template_off": template["ovy_id_off"], "template_id": template["ovy_id"], "max_battlers": 4,
        "mons_off": 0x2D40, "mon_size": 0xC0, "selected_off": 0x219C,
        "species_off": 0, "level_off": 0x34, "moves_off": 0x0C, "pp_off": 0x2C, "hp_off": 0x4C, "hp_width": 4, "hp_signed": True, "max_hp_off": 0x50,
        "personality_off": 0x68, "otid_off": 0x74,
        "fainted_flag_off": 0x213C, "fainted_flag_shift": 24, "fainted_flag_mask": 0x0F000000,
        "ability_off": 0x7A if build == "hge" else 0x27, "ability_width": 2 if build == "hge" else 1,
    }


# ---- battle.d7: the in-battle linked-faint seam (lua/gen4/client.lua D7; docs/gen4/research/battle_faint_seam.md) ----------
# The typed constants below are the PHYSICAL-proven values (lua/tests/probe_gen4_battle_faint.lua L.* / SEAMS, doc sections 9-13a);
# the generator FAILS if the ROM bytes disagree, so a wrong value can never be emitted as FILE-proven.
D7_OV, D7_CMD_VANILLA, D7_CMD_HGE = "ov12", 11, 9
D7_SEAM_PIN_HEX = "f8b582b0"      # probe ufce.pin 0xB082B5F8 little-endian: the 4 bytes the bus-exec hook registers on
D7_HGE_ENTRY = 0x022494DD         # hge ROM dispatch word for command 9 (Thumb bit set): trampoline at 0x022494DC (doc section 10)
D7_HGE_TRAMPOLINE_HEX = "004a1047"  # hge dispatch target bytes: halfwords 0x4a00 0x4710 = `ldr r2,[pc]; bx r2`, little-endian file order
# ov12_0224D540 (offset, halfword): +0x4A `movs r1,#0x4f`, +0x4C `ldr r0,[sp,#0x1c]`, +0x4E `lsls r1,r1,#2` (4f << 2 == 0x13C),
# +0x50 `ldr r2,[r0,r1]`, then +0x54 `bics r2,r0` (r0 = #1 from +0x52) and +0x58 `str r2,[r0,r1]` (r0 reloaded at +0x56): the literal,
# the indexed load AND the store that clears bit 0 = `ctx->unk_13C[battlerId] &= ~1` (src/battle/battle_controller_player.c:3424).
# The base register being the BattleContext is SOURCE + PHYSICAL (the probe reads ctx + 0x13C), not a byte fact.
D7_REPL_PIN = ((0x4A, 0x214F), (0x4C, 0x9807), (0x4E, 0x0089), (0x50, 0x5842), (0x54, 0x4382), (0x58, 0x5042))
S_CMD_ENUM = _c("include/constants/battle.h", "596-609", "typedef enum ControllerCommand")
S_CMD_TABLE_UFCE = _c("src/battle/battle_controller_player.c", "109", "CONTROLLER_COMMAND_UPDATE_FIELD_CONDITION_EXTRA")
S_CMD_DISPATCH = _c("src/battle/battle_controller_player.c", "166", "sPlayerBattleCommands[ctx->command]")
S_CTX_CMD = _c(_BH, "282", "ControllerCommand command;")
S_BS_PARTY = _c(_BH, "548", "Party *trainerParty[4]")
S_CTX_REPL = _c(_BH, "341", "u32 unk_13C[4]")
S_PARTY_HP = _c("include/pokemon_types_def.h", "203", "u16 hp;")
H_CMD_ENUM = _ch("include/battle.h", "1092", "typedef enum ControllerCommand")
H_CMD_FIELD_COND = _ch("include/battle.h", "1102", "CONTROLLER_COMMAND_UPDATE_FIELD_CONDITION,")
H_CTX_CMD = _ch("include/battle.h", "1283", "int server_seq_no")
H_BS_PARTY = _ch("include/battle.h", "1595", "struct Party *trainerParty[4]")
H_CTX_REPL = _ch("include/battle.h", "1345", "client_status[CLIENT_MAX]")
H_PARTY_HP = _ch("include/pokemon.h", "345", "u16 hp")


def d7_file_checks(xm: XMap, images: Images, build: str, vanilla: Images | None = None) -> dict:
    """FILE: the D7 seam and the replacement-flag offset, read from the ROM image and compared with the typed PHYSICAL constants.
    build hgss: dispatch entry 11 == UpdateFieldConditionExtra|1 and the 4 pin bytes there; hge: entry 9 (Thumb word) equals the typed
    value AND the vanilla ROM's, and its target bytes equal the proven trampoline. d7_values emits addr + pin_hex from these
    FILE reads for EVERY build; the client never reads the pin from RAM (it would sample an in-flight async ov12 load)."""
    tbl = xm.lookup("sPlayerBattleCommands")
    if tbl.image != D7_OV:
        raise Fail(f"sPlayerBattleCommands is in {tbl.image}, not {D7_OV}")
    cmd = D7_CMD_HGE if build == "hge" else D7_CMD_VANILLA
    word = struct.unpack("<I", images.read(D7_OV, tbl.address + 4 * cmd, 4))[0]
    addr = word & ~1
    out = {"table": {"symbol": "sPlayerBattleCommands", "address": tbl.address, "image": D7_OV, "cmd": cmd, "entry_word": word,
                     "entry_address": addr, "bytes_source": f"decompressed {D7_OV}"}}
    if not word & 1:
        raise Fail(f"D7 dispatch entry {cmd} word {word:#x} is not a Thumb address")
    pin = images.read(D7_OV, addr, 4).hex()
    out["pin_bytes"] = {"address": addr, "image": D7_OV, "bytes": pin, "decodes_as": ("hge trampoline `ldr r2,[pc]; bx r2` (halfwords 0x4a00 0x4710, little-endian file order)" if build == "hge"
                                                                 else "Thumb prologue halfwords, little-endian file order")}
    if build == "hge":
        if vanilla is None or struct.unpack("<I", vanilla.read(D7_OV, tbl.address + 4 * cmd, 4))[0] != word:
            raise Fail(f"hge dispatch entry {cmd} differs from the vanilla ROM's: the seam is no longer the shared ov12 command")
        if word != D7_HGE_ENTRY:
            raise Fail(f"hge dispatch entry {cmd} is {word:#010x}, not the PHYSICAL-proven {D7_HGE_ENTRY:#010x}")
        if pin != D7_HGE_TRAMPOLINE_HEX:
            raise Fail(f"hge dispatch target bytes {pin} at {addr:#x} != the trampoline {D7_HGE_TRAMPOLINE_HEX} (ldr r2,[pc]; bx r2)")
        out["table"]["identical_in_vanilla"] = True
    else:
        fn = xm.lookup("BattleControllerPlayer_UpdateFieldConditionExtra")
        if (fn.image, fn.address) != (D7_OV, addr):
            raise Fail(f"dispatch entry {cmd} {word:#x} is not BattleControllerPlayer_UpdateFieldConditionExtra {fn.address:#x}")
        if pin != D7_SEAM_PIN_HEX:
            raise Fail(f"ROM bytes {pin} at {addr:#x} != the PHYSICAL-proven seam pin {D7_SEAM_PIN_HEX}")
    d540 = xm.lookup("ov12_0224D540")
    offs, want = [o for o, _ in D7_REPL_PIN], [h for _, h in D7_REPL_PIN]
    got = [struct.unpack("<H", images.read(D7_OV, d540.address + o, 2))[0] for o in offs]
    if got != want or (want[0] & 0xFF) << 2 != 0x13C:
        raise Fail(f"ov12_0224D540 replacement-flag halfwords {[hex(x) for x in got]} != the proven "
                   "movs r1,#0x4f / ldr r0,[sp,#0x1c] / lsls r1,r1,#2 / ldr r2,[r0,r1] / bics r2,r0 / str r2,[r0,r1]")
    out["repl_flag"] = {"symbol": "ov12_0224D540", "function_address": d540.address, "image": D7_OV, "movs_at": d540.address + offs[0],
                        "lsls_at": d540.address + offs[2], "halfword_offsets": offs, "halfwords": [f"{x:#06x}" for x in got],
                        "decodes_as": "movs r1,#0x4f ; ldr r0,[sp,#0x1c] ; lsls r1,r1,#2 ; ldr r2,[r0,r1] ; (movs r0,#1) ; bics r2,r0 ; "
                                      "(ldr r0,[sp,#0x1c]) ; str r2,[r0,r1]  (0x4f << 2 = 0x13C; a read-modify-write clearing bit 0; the "
                                      "base register is the BattleContext by SOURCE + PHYSICAL, not by these bytes)", "value": 0x13C,
                        "bytes_source": f"decompressed {D7_OV}"}
    return out


def d7_values(checks: dict, build: str) -> dict:
    # FILE-proven on every build (d7_checks: the entry word and the target bytes read from the decompressed image).
    # The client must never mint its expected pin from RAM: during an async ov12 load the range still holds the
    # previous overlay's bytes, and a pin read from them would "confirm" them (residency contract).
    seam = {"cmd": checks["table"]["cmd"], "overlay_id": overlay_id(D7_OV),
            "addr": checks["table"]["entry_address"], "pin_hex": checks["pin_bytes"]["bytes"]}
    if build == "hge":
        seam["table"] = checks["table"]["address"]
    return {"seam": seam, "ctx_cmd_off": 0x08, "bs_party_off": 0x68, "party_hp_off": 0x8E, "repl_flag_off": checks["repl_flag"]["value"]}


def d7_evidence(build: str, title: str) -> dict:
    """{field: {class, cite, physical, owner}} per D7 field. class = the strongest proof (FILE > SOURCE); `physical` names the live
    receipt (docs/gen4/research/battle_faint_seam.md) or says why there is none (SS)."""
    hge = build == "hge"
    src = HGE_SRC if hge else PRET_HG
    if title == "soulsilver":
        phys = ("none: no SoulSilver run; HG==SS bytes at the seam, the dispatch table and ov12_0224D540 are FILE-compared in the SS ROM "
                "(profile.battle_d7_file_checks); the offsets are struct layout shared by the two ROMs")
    elif hge:
        phys = (f"PHYSICAL: {_PHYS_HG} sections 10, 13 (hge build cb2dc435; cmd 9 seam hit r15 0x022494E0, receipt "
                "heartgold_hge_seam_ufce_bit_p2_201513; four p2 rows PASS)")
    else:
        phys = (f"PHYSICAL: {_PHYS_HG} sections 9, 13a (receipt heartgold_seam_ufce_bit_p2_201242: cmd 11 hit r15 0x0224A710; "
                "four p2 rows PASS)")

    def ref(hge_ref: str, hg_ref: str) -> str:
        return f"{src} {hge_ref if hge else hg_ref}"

    def own(struct_name: str, cite: str) -> dict:
        return {"struct": struct_name, "cite": cite}  # cite comes from ref(), which already carries the repository id

    seam_file = ("FILE: profile.battle_d7_file_checks.table (the hge ROM's own dispatch word for the command, equal to the vanilla "
                 "ROM's; the client derives the address from it at first use; the table is in ov12)" if hge else
                 "FILE: profile.battle_d7_file_checks (ov12 ROM bytes: dispatch entry 11 == UpdateFieldConditionExtra|1; the 4 bytes "
                 "at that address are the typed PHYSICAL pin)")
    fields = {
        "seam.cmd": {"class": "FILE", "cite": "; ".join([seam_file, ref(H_CMD_ENUM + " / " + H_CMD_FIELD_COND,
                                                                           S_CMD_ENUM + " / " + S_CMD_TABLE_UFCE)]),
                     "physical": phys, "owner": own("sPlayerBattleCommands", ref(H_CMD_FIELD_COND, S_CMD_TABLE_UFCE))},
        "seam.overlay_id": {"class": "FILE", "cite": f"FILE: the xMAP symbols sPlayerBattleCommands and UpdateFieldConditionExtra sit in {D7_OV}; "
                            "overlay id 12 is also read from gOverlayTemplate_Battle (profile.battle.template_id)", "physical": phys,
                            "owner": own("sPlayerBattleCommands", ref(H_CMD_ENUM, S_CMD_DISPATCH))},
        "ctx_cmd_off": {"class": "SOURCE", "cite": ref(H_CTX_CMD + " (`/*0x8*/ int server_seq_no`, explicit)",
                                                       S_CTX_CMD + " (BattleContext.command after two u8[4] = 0x08; the dispatch indexes the table "
                                                       "with it, " + S_CMD_DISPATCH + ")"),
                        "physical": phys, "owner": own("BattleContext", ref(H_CTX_CMD, S_CTX_CMD))},
        "bs_party_off": {"class": "SOURCE", "cite": ref(H_BS_PARTY + " (hand-counted from sp at 0x30: opponentData[4] 0x34, maxBattlers 0x44, "
                                                        "playerProfile[4] 0x48, bag/bagCursor/pokedex/storage 0x58-0x64, trainerParty 0x68; "
                                                        "equals battle_faint_seam.md section 5)",
                                                        S_BS_PARTY + " (hand-counted from ctx at 0x30, same layout)"),
                         "physical": phys, "owner": own("BattleSystem", ref(H_BS_PARTY, S_BS_PARTY))},
        "party_hp_off": {"class": "SOURCE", "cite": ref(H_PARTY_HP + " (`/* 0x08E */ u16 hp`, explicit, PartyPokemon tail)",
                                                        S_PARTY_HP + " (`/* 0x08E */`, explicit)"),
                         "physical": phys, "owner": own("PartyPokemon", ref(H_PARTY_HP, S_PARTY_HP))},
        "repl_flag_off": {"class": "FILE", "cite": "; ".join([
            "FILE: profile.battle_d7_file_checks.repl_flag (ov12_0224D540 `movs r1,#0x4f ; ldr r0,[sp,#0x1c] ; lsls r1,r1,#2 ; ldr r2,[r0,r1] ; "
            "bics r2,r0 ; str r2,[r0,r1]` = a read-modify-write at ctx-relative 0x13C clearing bit 0, i.e. `ctx->unk_13C[b] &= ~1`; "
            "the base register being the BattleContext is SOURCE + PHYSICAL"
            + (", ROM-identical in hge)" if hge else ")"),
            ref(H_CTX_REPL + " (`/*0x13C*/ client_status[CLIENT_MAX]`, explicit; bit0 = replacement needed)",
                S_CTX_REPL + " (BattleContext.unk_13C[4])")]),
                          "physical": phys, "owner": own("BattleContext", ref(H_CTX_REPL, S_CTX_REPL))},
    }
    return {"fields": fields, "class": "FILE",
            "cite": "per-field evidence in `fields` (seam FILE-checked in the ROM; offsets SOURCE or FILE; a PHYSICAL receipt reference per field)",
            "owner": {"struct": "per field (see fields[*].owner)", "cite": f"{PRET_HG} {S_CMD_DISPATCH}"}}


# ---- battle enums (poll_events cfg: outcomes / trainer_mask / exempt_mask) ------------------------
OUTCOME_CODES = {"none": 0, "win": 1, "lose": 2, "draw": 3, "caught": 4, "player_fled": 5, "foe_fled": 6}
EXEMPT_ROLES = ("link", "multi", "tag", "safari", "frontier", "pal_park", "tutorial", "bug_contest", "debug")
_PIN_AI = ("a partner or AI-controlled side. HGSS wild/trainer battles with a follower are DOUBLES|MULTI|AI, "
           "src/encounter.c:705 and src/field/encounter_check.c:280, so they are already exempt through MULTI; AI alone is not a rule change")
BATTLE_TYPE_TABLES = {
    "hgss": {
        "bits": {"BATTLE_TYPE_TRAINER": 1 << 0, "BATTLE_TYPE_DOUBLES": 1 << 1, "BATTLE_TYPE_LINK": 1 << 2, "BATTLE_TYPE_MULTI": 1 << 3,
                 "BATTLE_TYPE_TAG": 1 << 4, "BATTLE_TYPE_SAFARI": 1 << 5, "BATTLE_TYPE_AI": 1 << 6, "BATTLE_TYPE_FRONTIER": 1 << 7,
                 "BATTLE_TYPE_ROAMER": 1 << 8, "BATTLE_TYPE_PAL_PARK": 1 << 9, "BATTLE_TYPE_TUTORIAL": 1 << 10, "BATTLE_TYPE_11": 1 << 11,
                 "BATTLE_TYPE_BUG_CONTEST": 1 << 12, "BATTLE_TYPE_13": 1 << 13, "BATTLE_TYPE_DEBUG": 1 << 31},
        "trainer": "BATTLE_TYPE_TRAINER",
        "exempt": {"link": "BATTLE_TYPE_LINK", "multi": "BATTLE_TYPE_MULTI", "tag": "BATTLE_TYPE_TAG", "safari": "BATTLE_TYPE_SAFARI",
                   "frontier": "BATTLE_TYPE_FRONTIER", "pal_park": "BATTLE_TYPE_PAL_PARK", "tutorial": "BATTLE_TYPE_TUTORIAL",
                   "bug_contest": "BATTLE_TYPE_BUG_CONTEST", "debug": "BATTLE_TYPE_DEBUG"},
        "not_exempt": {
            "BATTLE_TYPE_TRAINER": "the trainer bit itself: trainer_mask",
            "BATTLE_TYPE_DOUBLES": "a layout, not a rule change (a double wild battle is DOUBLES|MULTI|AI and exempt through MULTI)",
            "BATTLE_TYPE_AI": _PIN_AI,
            "BATTLE_TYPE_ROAMER": "a roaming wild battle is an ordinary catchable overworld encounter (src/encounter.c:137,864 treat it like BATTLE_TYPE_NONE)",
            "BATTLE_TYPE_11": "a SetupAndStartTrainerBattle option set on single trainer battles (src/encounter.c:712): still a trainer battle",
            "BATTLE_TYPE_13": "a modifier read only next to FRONTIER / a special trainer id (battle_input.c:4555, battle_system.c:1368), never alone",
        },
        "consts_src": S_TYPES, "outcome_names": {k: f"BATTLE_OUTCOME_{v}" for k, v in {
            "none": "NONE", "win": "WIN", "lose": "LOSE", "draw": "DRAW", "caught": "MON_CAUGHT", "player_fled": "PLAYER_FLED",
            "foe_fled": "FOE_FLED"}.items()},
        "outcome_cite": f"{PRET_HG} {S_OUTCOMES}; the byte is the BATTLE_RESULT_* flags (same numbers, {S_RESULTS}) masked to 0x3F",
        "types_cite": f"{PRET_HG} {S_TYPES}; {S_ENC_WILD_TYPES}; {S_ENC_TRAINER_TYPES}",
    },
    "hge": {
        "bits": {"BATTLE_TYPE_SINGLE": 0x00, "BATTLE_TYPE_TRAINER": 0x01, "BATTLE_TYPE_DOUBLE": 0x02, "BATTLE_TYPE_WIRELESS": 0x04,
                 "BATTLE_TYPE_MULTI": 0x08, "BATTLE_TYPE_TAG": 0x10, "BATTLE_TYPE_SAFARI": 0x20, "BATTLE_TYPE_NPC_MULTI": 0x40,
                 "BATTLE_TYPE_BATTLE_TOWER": 0x80, "BATTLE_TYPE_ROAMER": 0x100, "BATTLE_TYPE_PAL_PARK": 0x200,
                 "BATTLE_TYPE_CATCHING_DEMO": 0x400, "BATTLE_TYPE_CAN_LOSE": 0x800, "BATTLE_TYPE_BUG_CONTEST": 0x1000},
        "trainer": "BATTLE_TYPE_TRAINER",
        "exempt": {"link": "BATTLE_TYPE_WIRELESS", "multi": "BATTLE_TYPE_MULTI", "tag": "BATTLE_TYPE_TAG", "safari": "BATTLE_TYPE_SAFARI",
                   "frontier": "BATTLE_TYPE_BATTLE_TOWER", "pal_park": "BATTLE_TYPE_PAL_PARK", "tutorial": "BATTLE_TYPE_CATCHING_DEMO",
                   "bug_contest": "BATTLE_TYPE_BUG_CONTEST"},
        "not_exempt": {
            "BATTLE_TYPE_SINGLE": "0: no bit",
            "BATTLE_TYPE_TRAINER": "the trainer bit itself: trainer_mask",
            "BATTLE_TYPE_DOUBLE": "a layout, not a rule change",
            "BATTLE_TYPE_NPC_MULTI": "the vanilla AI bit (0x40): " + _PIN_AI,
            "BATTLE_TYPE_ROAMER": "a roaming wild battle is an ordinary catchable overworld encounter",
            "BATTLE_TYPE_CAN_LOSE": "the vanilla BATTLE_TYPE_11 bit (0x800): a trainer-battle option; still a trainer battle",
        },
        "consts_src": H_TYPES, "outcome_names": {k: f"BATTLE_OUTCOME_{v}" for k, v in {
            "none": "NONE", "win": "WIN", "lose": "LOSE", "draw": "DRAW", "caught": "MON_CAUGHT", "player_fled": "PLAYER_FLED",
            "foe_fled": "FOE_FLED"}.items()},
        "outcome_cite": f"{HGE_SRC} {H_OUTCOMES} (the vanilla values; hge keeps the 0x3F outcome store, profile.battle_hge_checks)",
        "types_cite": f"{HGE_SRC} {H_TYPES}: the same bit values as vanilla under hge's own names",
    },
    "pt": {
        "bits": {"BATTLE_TYPE_SINGLES": 0, "BATTLE_TYPE_TRAINER": 1 << 0, "BATTLE_TYPE_DOUBLES": 1 << 1, "BATTLE_TYPE_LINK": 1 << 2,
                 "BATTLE_TYPE_2vs2": 1 << 3, "BATTLE_TYPE_TAG": 1 << 4, "BATTLE_TYPE_SAFARI": 1 << 5, "BATTLE_TYPE_AI": 1 << 6,
                 "BATTLE_TYPE_FRONTIER": 1 << 7, "BATTLE_TYPE_ROAMER": 1 << 8, "BATTLE_TYPE_PAL_PARK": 1 << 9,
                 "BATTLE_TYPE_CATCH_TUTORIAL": 1 << 10, "BATTLE_TYPE_DEBUG": 1 << 31},
        "trainer": "BATTLE_TYPE_TRAINER",
        "exempt": {"link": "BATTLE_TYPE_LINK", "multi": "BATTLE_TYPE_2vs2", "tag": "BATTLE_TYPE_TAG", "safari": "BATTLE_TYPE_SAFARI",
                   "frontier": "BATTLE_TYPE_FRONTIER", "pal_park": "BATTLE_TYPE_PAL_PARK", "tutorial": "BATTLE_TYPE_CATCH_TUTORIAL",
                   "debug": "BATTLE_TYPE_DEBUG"},
        "not_exempt": {
            "BATTLE_TYPE_SINGLES": "0: no bit",
            "BATTLE_TYPE_TRAINER": "the trainer bit itself: trainer_mask",
            "BATTLE_TYPE_DOUBLES": "a layout, not a rule change",
            "BATTLE_TYPE_AI": "a partner or AI-controlled side (BATTLE_TYPE_AI_PARTNER = DOUBLES|2vs2|AI is exempt through 2vs2)",
            "BATTLE_TYPE_ROAMER": "a roaming wild battle is an ordinary catchable overworld encounter",
        },
        "consts_src": P_TYPES, "outcome_names": {k: f"BATTLE_RESULT_{v}" for k, v in {
            "win": "WIN", "lose": "LOSE", "draw": "DRAW", "caught": "CAPTURED_MON", "player_fled": "PLAYER_FLED",
            "foe_fled": "ENEMY_FLED"}.items()} | {"none": "BATTLE_IN_PROGRESS"},
        "outcome_cite": f"{PRET_PT} {P_RESULTS} (BATTLE_RESULT_* flags: WIN 1, LOSE 2, CAPTURED_MON 4; DRAW/PLAYER_FLED/ENEMY_FLED are their ORs)",
        "types_cite": f"{PRET_PT} {P_TYPES} (no bug-catching-contest type in Platinum)",
    },
}


def battle_enums(build: str) -> dict:
    """profile.battle_enums: the poll_events cfg values (outcomes / trainer_mask / exempt_mask), derived from the per-title bit tables."""
    t = BATTLE_TYPE_TABLES[build]
    bits, exempt = t["bits"], t["exempt"]
    covered = set(exempt.values()) | set(t["not_exempt"])
    if covered != set(bits):
        raise Fail(f"battle_enums {build}: every battle-type constant must be exempt or explained; unclassified: "
                   f"{sorted(set(bits) ^ covered)}")
    if not set(exempt) <= set(EXEMPT_ROLES) or len(set(exempt.values())) != len(exempt):
        raise Fail(f"battle_enums {build}: exempt roles {sorted(exempt)} are not distinct known roles")
    mask = 0
    for const in exempt.values():
        mask |= bits[const]
    if bits[t["trainer"]] != 1 or mask & 1:
        raise Fail(f"battle_enums {build}: the trainer bit must be 1 and outside the exempt mask")
    return {
        "outcomes": dict(OUTCOME_CODES), "outcome_consts": dict(t["outcome_names"]),
        "outcome_encoding": "the battle result byte at bs+battle.outcome_off, masked with battle.outcome_mask (0x3F); numeric codes "
                            "are identical for BATTLE_OUTCOME_* and BATTLE_RESULT_*",
        "trainer_mask": bits[t["trainer"]], "trainer_const": t["trainer"],
        "exempt_mask": mask, "no_catch_mask": mask,
        "no_catch_mask_note": "same value as exempt_mask under the name lua/gen4/poll_events.lua cfg.no_catch_mask uses",
        "exempt_roles": dict(exempt), "type_bits": dict(bits), "not_exempt": dict(t["not_exempt"]),
        "evidence": {"outcomes": t["outcome_cite"], "battle_types": t["types_cite"]},
    }


# ---- admission anchors (vanilla HG/SS ARM9 bytes the hge ROM must not match) -----------------------
HGE_HOOK_SITE = 0x02000CD0  # armips/asm/syntheticoverlay.s:8 `.org 0x02000CD0 // branch from Main(), run once` (bl load_arm9_expansion)
ADMISSION_ANCHOR_SPECS = (
    # name, address or (symbol, offset), length, hge differs here
    ("nitromain_hge_hook_site", HGE_HOOK_SITE, 16, True),
    ("nitromain_entry", ("NitroMain", 0), 16, False),
    ("nitromain_after_hook", HGE_HOOK_SITE + 0x10, 16, False),
)


def admission_anchors(xm: XMap, images: Images) -> list[dict]:
    """FILE: the vanilla static-ARM9 bytes entry.lua compares with RAM (decompressed ndspy arm9, RAM base 0x02000000)."""
    main = xm.lookup("NitroMain")
    rows = []
    for name, where, n, differs in ADMISSION_ANCHOR_SPECS:
        addr = xm.lookup(where[0]).address + where[1] if isinstance(where, tuple) else where
        if not (main.address <= addr and addr + n <= main.address + main.size):
            raise Fail(f"admission anchor {name} {addr:#x}+{n} is outside NitroMain {main.address:#x}+{main.size:#x}")
        rows.append({
            "name": name, "address": addr, "address_hex": f"{addr:#010x}", "image": "arm9", "length": n,
            "hex": images.read("arm9", addr, n).hex(), "hge_differs": differs,
            "evidence": f"FILE: decompressed static ARM9 of the pinned ROM (inside xMAP NitroMain {main.address:#010x}+{main.size:#x}, main.o); {ARM9_BYTES_NOTE}"
                        + (f"; SOURCE {HGE_SRC} armips/asm/syntheticoverlay.s:8 (hge patches Main() here)" if differs else "")})
    return rows


def hge_admission_check(hg: Images, hge: Images, anchors: list[dict], hook_target: int) -> dict:
    """The hge ROM must NOT show the vanilla bytes at the discriminating anchor (else entry.lua's anchors prove nothing). FAIL otherwise."""
    row = next(a for a in anchors if a["hge_differs"])
    mine = hge.read("arm9", row["address"], row["length"])
    if mine.hex() == row["hex"]:
        raise Fail(f"the hge ROM shows the vanilla bytes at {row['address']:#x}: the Main() hook anchor cannot tell hge from vanilla")
    redirect = decode_redirect(row["address"], mine)
    if redirect is None or redirect["target"] != hook_target:
        raise Fail(f"hge bytes at {row['address']:#x} are not a call to load_arm9_expansion {hook_target:#x}: {redirect}")
    others = {a["name"]: hge.read("arm9", a["address"], a["length"]).hex() == a["hex"] for a in anchors if not a["hge_differs"]}
    return {"address": row["address"], "address_hex": row["address_hex"], "length": row["length"], "vanilla_hex": row["hex"],
            "hge_hex": mine.hex(), "differs": True, "hge_hook": redirect, "other_anchors_same_in_hge": others,
            "evidence": f"FILE: the pinned hge ROM raw rom.arm9 (vanilla_hex is ndspy loadArm9().sections[0], decompressed); SOURCE {HGE_SRC} armips/asm/syntheticoverlay.s:8-10 (bl load_arm9_expansion at "
                        "the Main() site) and :15 (the .area at 0x02110334)"}


# ---- diagnostic sites (performance characterization only; never armed in production) -------------
DIAGNOSTIC_SPECS = [
    ("hot_disable_interrupts", "OS_DisableInterrupts", "diagnostic",
     "HOT: NitroSDK critical-section entry, fires many times per frame (perf cost of an exec hook per call)", "KEPT"),
    ("hot_idle_halt", "OS_Halt", "diagnostic",
     "idle-thread halt, once per halt entry: the G1 row m frame-end PC (0x020D3F64) is the ARM pipeline PC of its `mcr` (OS_Halt+4, +8), "
     "not a fetchable address; the hook is the entry", "KEPT"),
]


def diagnostic_sites(xm: XMap, images: Images, hge: Images | None = None) -> dict[str, dict]:
    rows = vanilla_sites(xm, images, DIAGNOSTIC_SPECS)
    for sid, r in rows.items():
        if r["mode"] != "arm" or r["image"] != "arm9":
            raise Fail(f"diagnostic site {sid} must be a static ARM9 ARM function, got {r['image']}/{r['mode']}")
        if hge is not None:
            if hge.read(r["image"], r["address"], r["extent"]).hex() != r["register_hex"]:
                raise Fail(f"hge diagnostic site {sid} differs from vanilla at {r['address']:#x}")
            r["hge_status"] = "KEPT"
    rows["hot_idle_halt"]["sampled_pc"] = 0x020D3F64
    rows["hot_idle_halt"]["sampled_pc_evidence"] = (
        "docs/gen4/research/platform.md:102 (G1 row m: frame-end PC 0x020D3F64, 300/600 overworld, 120/120 party; C1-1 receipt 600/600): "
        "OS_Halt is 0xC bytes (xMAP), its `mcr p15` halt instruction is at +4, and a halted ARM core reads PC = instruction + 8")
    return rows


def validate_diagnostic_sites(title: dict, images: Images) -> list[str]:
    """Diagnostic rows are real image bytes and are NOT production: never a site id, a phase candidate or a phase-case site."""
    diag = title.get("diagnostic_sites") or {}
    errs = validate_sites(diag, images, "diagnostic")
    for sid, r in diag.items():
        if r.get("phase") != "diagnostic":
            errs.append(f"diagnostic:{sid}: phase must be 'diagnostic'")
        if sid in title["sites"]:
            errs.append(f"diagnostic:{sid}: also a production site id")
        for pname, ph in title["phases"].items():
            if sid in ph.get("candidate_sites", []):
                errs.append(f"diagnostic:{sid}: listed as a {pname} candidate_site")
        for case in [*title.get("phase_cases", []), *title.get("phase_cases_blocked", [])]:
            if sid in (case.get("sites") or []) or case.get("producer_site") == sid:
                errs.append(f"diagnostic:{sid}: used by phase case {case.get('name')}")
    return errs


def battle_profile(build: str, title: str, xm: XMap, images: Images, hge_vs: Images | None = None) -> dict:
    """The profile keys the card adds: battle (+ evidence, FILE checks, physical corroboration) and battle_enums."""
    template = template_check(xm, images, "gOverlayTemplate_Battle", 12)
    d7_checks = d7_file_checks(xm, images, build, hge_vs)
    out = {
        "battle": {**battle_values(template, build), "d7": d7_values(d7_checks, build)},
        "battle_evidence": {**battle_evidence(build, template), "d7": d7_evidence(build, title)},
        "battle_d7_file_checks": d7_checks, "battle_file_checks": battle_file_checks(xm, images), "battle_enums": battle_enums("hge" if build == "hge" else "hgss"),
        "battle_physical": copy.deepcopy(BATTLE_PHYSICAL[title]),
    }
    if hge_vs is not None:  # build == hge: `images` is the hge image, `hge_vs` the vanilla baseline
        out["battle_hge_checks"] = hge_battle_checks(xm, hge_vs, images)
    return out


def lock_provenance(inputs: Inputs) -> dict:
    return {"path": "data/gen4_sources.lock.json", "sha256": hashlib.sha256(inputs.lock.read_bytes()).hexdigest()}


# --------------------------------------------------------------------------------------------
# profile.rtc: the game's cached RTC work struct (card C1-2e)
# --------------------------------------------------------------------------------------------
# NitroSDK RTCDate = {u32 year, month, day; RTCWeek week} (16 bytes), RTCTime = {u32 hour, minute, second} (12). The work struct caches
# the host RTC: every >10 frames it re-reads into date_async/time_async and the callback copies them into date/time.
S_RTC_API_DATE = _c("lib/include/nitro/rtc/ARM9/api.h", "29", "typedef struct RTCDate")
S_RTC_API_TIME = _c("lib/include/nitro/rtc/ARM9/api.h", "36", "typedef struct RTCTime")
S_RTC_WORK = _c("src/gf_rtc.c", "7-20", "struct GFRtcWork {")
S_RTC_WORK_DATE, S_RTC_WORK_TIME = _c("src/gf_rtc.c", "12", "RTCDate date;"), _c("src/gf_rtc.c", "13", "RTCTime time;")
S_RTC_WORK_SYM = _c("src/gf_rtc.c", "22", "struct GFRtcWork sRTCWork;")
S_RTC_UPDATE = _c("src/gf_rtc.c", "45-50", "GF_RTC_UpdateOnFrame")
H_RTC_DATE = _ch("include/rtc.h", "33", "struct RTCDate {")
H_RTC_TIME = _ch("include/rtc.h", "40", "struct RTCTime {")
P_RTC_STATE = _cp("src/rtc.c", "9-18", "typedef struct {")
P_RTC_STATE_DATE, P_RTC_STATE_TIME = _cp("src/rtc.c", "14", "RTCDate date;"), _cp("src/rtc.c", "15", "RTCTime time;")
P_RTC_STATE_SYM = _cp("src/rtc.c", "23", "static RTCState sRTCState;")
P_RTC_UPDATE = _cp("src/rtc.c", "35-47", "void UpdateRTC(void)")
RTC_DATE_SIZE, RTC_TIME_SIZE = 16, 12
_RTC_CADENCE = ("the cached copy refreshes every 11 frames when no read is in flight (the counter must exceed 10) and later when one is "
                "(the counter does not advance while a read is in flight)")
HG_RTC_CAVEAT = ("date/time are a CACHE of the host RTC: GF_RTC_UpdateOnFrame re-reads into the async pair (date_async/time_async) when "
                 "getDateTimeLock is clear and ++getDateTimeSleep > 10, and the callback copies the pair over date/time and clears the lock; "
                 f"{_RTC_CADENCE}, so a pin written only to date/time is clobbered; pin the host RTC or rewrite each frame. "
                 "The time the game returns is `frozenTime` (+0x4C) while frozenTimeState (+0x48) == 3 (photo state), else `time`; "
                 "the date has no frozen override.")
PT_RTC_CAVEAT = ("date/time are a CACHE of the host RTC: UpdateRTC returns while readInProgress is set, else increments framesSinceRead "
                 "and, when it exceeds 10, zeroes it and starts an async read into the pair tempDate/tempTime; GetTimeCallback copies that pair "
                 f"over date/time and clears readInProgress; {_RTC_CADENCE}, so a pin written only to date/time is clobbered; pin the host RTC "
                 "or rewrite each frame.")
# (field, size) in declaration order, enums and BOOL are 4 bytes; offsets and the total are derived, then checked against the xMAP size.
HG_RTC_FIELDS = (("getDateTimeSuccess", 4), ("getDateTimeLock", 4), ("getDateTimeSleep", 4), ("getDateTimeErrorCode", 4),
                 ("date", RTC_DATE_SIZE), ("time", RTC_TIME_SIZE), ("date_async", RTC_DATE_SIZE), ("time_async", RTC_TIME_SIZE),
                 ("frozenTimeState", 4), ("frozenTime", RTC_TIME_SIZE))
# Platinum RTCState (pokeplatinum src/rtc.c:9-18) is a differently named twin of the first 8 fields and has NO frozen-time pair.
PT_RTC_FIELDS = (("valid", 4), ("readInProgress", 4), ("framesSinceRead", 4), ("status", 4),
                 ("date", RTC_DATE_SIZE), ("time", RTC_TIME_SIZE), ("tempDate", RTC_DATE_SIZE), ("tempTime", RTC_TIME_SIZE))
# role -> field name per layout: the async pair the refresh writes, and the lock/counter that gate the refresh
RTC_ROLES = {"hgss": {"async_date": "date_async", "async_time": "time_async", "lock": "getDateTimeLock", "counter": "getDateTimeSleep"},
             "pt": {"async_date": "tempDate", "async_time": "tempTime", "lock": "readInProgress", "counter": "framesSinceRead"}}
RTC_READERS = {"hgss": ("GF_RTC_CopyDate", "GF_RTC_CopyTime"), "pt": ("GetCurrentDate", "RTC_GetCurrentTime")}


def _rtc_offsets(fields: tuple) -> tuple[dict, int]:
    offs, at = {}, 0
    for name, size in fields:
        offs[name], at = at, at + size
    return offs, at


def _pool_offsets(images: Images, fn: Sym, base: int, size: int) -> set[int]:
    """Offsets into the work struct that a function's literal pool addresses (aligned words inside [base, base + size))."""
    code = images.read(fn.image, fn.address, fn.size)
    words = (int.from_bytes(code[k:k + 4], "little") for k in range(0, len(code) - 3, 4))
    return {w - base for w in words if base <= w < base + size}


def rtc_file_checks(xm: XMap, images: Images, build: str, base: int, date_off: int, time_off: int, size: int) -> dict:
    """FILE: the ROM readers' literal pools address work+date_off (the date copier) and work+time_off (the time copier)."""
    out = {}
    for fn_name, field, off in zip(RTC_READERS[build], ("date_off", "time_off"), (date_off, time_off), strict=True):
        fn = xm.lookup(fn_name)
        got = _pool_offsets(images, fn, base, size)
        if off not in got:
            raise Fail(f"{fn_name} literal pool addresses work offsets {sorted(got)}; {field} {off:#x} is not ROM-proven")
        out[fn_name] = {"address": fn.address, "image": fn.image, "pool_offsets": sorted(got), "proves": field,
                        "bytes_source": ARM9_BYTES_NOTE if fn.image == "arm9" else f"decompressed {fn.image}"}
    return out


RTC_HGE_IDENTICAL = (*RTC_READERS["hgss"], "GF_RTC_GetDateTime_Callback", "GF_RTC_UpdateOnFrame")


def rtc_hge_identity(xm: XMap, hge: Images, vanilla: Images) -> dict:
    """FILE: the four RTC reader/refresh functions, compared byte-for-byte: decompressed HG ARM9 (vanilla) vs the raw hge rom.arm9."""
    rows = {}
    for fn_name in RTC_HGE_IDENTICAL:
        fn = xm.lookup(fn_name)
        a, b = vanilla.read(fn.image, fn.address, fn.size), hge.read(fn.image, fn.address, fn.size)
        if a != b:
            raise Fail(f"hge changed {fn_name}: the vanilla sRTCWork layout is no longer a projection")
        rows[fn_name] = {"address": fn.address, "size": fn.size, "image": fn.image, "identical": True,
                         "sha256": hashlib.sha256(a).hexdigest()}
    return rows


def rtc_profile(xm: XMap, images: Images, build: str, vanilla: Images | None = None) -> dict:
    """build = hgss (HG and SS) | hge (vanilla layout, FILE-checked against the hge image) | pt (RTCState, a differently named twin)."""
    pt = build == "pt"
    sym_name = "sRTCState" if pt else "sRTCWork"
    offs, total = _rtc_offsets(PT_RTC_FIELDS if pt else HG_RTC_FIELDS)
    roles = RTC_ROLES["pt" if pt else "hgss"]
    row = symbol_row(xm, sym_name)
    if total != row["size"]:
        raise Fail(f"RTC work layout {total:#x} != xMAP {sym_name} size {row['size']:#x}: the date/time offsets are unproven")
    checks = rtc_file_checks(xm, images, "pt" if pt else "hgss", row["address"], offs["date"], offs["time"], total)
    if pt:
        source = (f"SOURCE {PRET_PT} {P_RTC_STATE} (RTCState: 4 words, then date {P_RTC_STATE_DATE}, time {P_RTC_STATE_TIME}, "
                  f"tempDate, tempTime); {P_RTC_STATE_SYM}; RTCDate/RTCTime layouts are the NitroSDK structs ({PRET_HG} {S_RTC_API_DATE}, "
                  f"{S_RTC_API_TIME}; pokeplatinum ships no SDK header); FILE: computed size {total:#x} equals the xMAP {sym_name} size, "
                  "the readers' literal pools address +0x10 and +0x20")
    else:
        source = (f"SOURCE {PRET_HG} {S_RTC_WORK} (GFRtcWork: 4 words, then date {S_RTC_WORK_DATE}, time {S_RTC_WORK_TIME}, date_async, "
                  f"time_async, frozenTimeState, frozenTime), {S_RTC_WORK_SYM}; RTCDate {S_RTC_API_DATE} / RTCTime {S_RTC_API_TIME}; "
                  f"FILE: computed size {total:#x} equals the xMAP {sym_name} size, the readers' literal pools address +0x10 and +0x20")
    out = {
        "symbol": sym_name, "address": row["address"], "work_size": total,
        "date_off": offs["date"], "date_size": RTC_DATE_SIZE, "time_off": offs["time"], "time_size": RTC_TIME_SIZE,
        "date_fields": {"year": 0, "month": 4, "day": 8, "week": 12}, "time_fields": {"hour": 0, "minute": 4, "second": 8},
        "async_date_off": offs[roles["async_date"]], "async_time_off": offs[roles["async_time"]],
        # the names behind the *_off keys (HGSS date_async/time_async, Platinum tempDate/tempTime) and the refresh gate
        "async_names": {"date": roles["async_date"], "time": roles["async_time"]},
        "refresh_gate": {"lock_field": roles["lock"], "lock_off": offs[roles["lock"]],
                         "counter_field": roles["counter"], "counter_off": offs[roles["counter"]], "counter_threshold": 10},
        "source": source, "evidence": "SOURCE + FILE", "file_checks": checks, "bytes_source": ARM9_BYTES_NOTE,
        "caveat": (PT_RTC_CAVEAT if pt else HG_RTC_CAVEAT) + f" Refresh loop: {P_RTC_UPDATE if pt else S_RTC_UPDATE}",
    }
    if not pt:
        out.update(frozen_state_off=offs["frozenTimeState"], frozen_time_off=offs["frozenTime"])
    if build == "hge":
        if vanilla is None:
            raise Fail("hge RTC check needs the vanilla image")
        ident = rtc_hge_identity(xm, images, vanilla)
        out["hge_checks"] = {"identical_to_vanilla": list(ident), "compared": ident,
                             "method": "FILE: the four reader/refresh functions at their xMAP addresses, compared byte-for-byte (sha256 recorded): "
                                       "the DECOMPRESSED HG ARM9 (ndspy loadArm9().sections[0]) against the hge RAW rom.arm9; "
                                       "all four are byte-identical",
                             "source": f"{HGE_SRC} {H_RTC_DATE}, {H_RTC_TIME} (hg-engine declares the same RTCDate/RTCTime and defines "
                                       "no work struct of its own; the symbol keeps its vanilla address and 88-byte size)"}
    return out


def bag_array_id() -> int:
    """The bag save-array id, read from save_geometry so profile.bag can never drift from profile.save."""
    return save_geometry(35, "", "")["array_ids"]["bag"]


def title_block(xm: XMap, images: Images, rom: dict, admission: str, label: str, other: Images, other_label: str,
                bag: dict | None = None, bag_open: str = "") -> dict:
    check_xmap_vs_rom(xm, images, label)
    symbols = {}
    for name in SYMBOL_NAMES:
        symbols[name] = symbol_row(xm, name)
        check_symbol_in_image(symbols[name], name, images, xm)
    ovr = xm.lookup("sOverlayRegions")
    if ovr.size != 3 * 8 * 8:
        raise Fail(f"{label}: sOverlayRegions size {ovr.size:#x} != 3 regions x 8 x 8 bytes")
    sites = vanilla_sites(xm, images)
    ui = ui_geometry(xm, images, other, other_label)
    profile = hgss_profile(xm)
    profile.update(battle_profile("hgss", label, xm, images))
    profile["rtc"] = rtc_profile(xm, images, "hgss")
    profile["bag"] = bag
    open_ = hgss_open()
    if bag_open:
        open_["bag"] = bag_open
    return {
        "rom": {k: rom[k] for k in ("sha1", "md5", "header_code")},
        "admission": admission,
        "symbols": symbols, "sites": sites,
        "overlays": images.overlay_table(),
        "overlay_table": {"symbol": "sOverlayRegions", "address": ovr.address, "regions": 3, "per_region": 8,
                          "entry_size": 8, "id_off": 0, "active_off": 4},
        "profile": profile,
        "admission_anchors": admission_anchors(xm, images),
        "diagnostic_sites": diagnostic_sites(xm, images),
        "phases": phase_table(sites, "hgss"),
        **build_phase_cases(xm, images),
        "ui_geometry": ui,
        **build_route_legs(ui, "hgss"),
        "collision_pairs": collision_pairs(xm, images, "hgss"),
        "open": open_,
    }


SCHEMA_NOTES = {
    "bag": "profile.bag: the save-array bag's balls pocket, for the Nuzlocke gate. array_id is the same number as "
           "profile.save.array_ids.bag; every offset is relative to that ARRAY's base (base: bag_array), never to the general "
           "block. balls_pocket_off + i*ball_slot_size (0 <= i < ball_slot_count) addresses slot i; each slot is a u16 id at +0 "
           "and a u16 quantity at +2 (slot_fields). ball_ids is every item id whose pocket is POCKET_BALLS, so has_pokeballs = "
           "some such slot has an id in ball_ids and a quantity > 0. pocket_layout carries every pocket's offset and slot count. "
           "Every value is parsed from the pinned source clone at the pin (source.commit + per-input sha256s); a missing clone "
           "emits null with the reason in open.bag, never a guess.",
    "address": "integers; address_hex is the same value for humans",
    "image": "arm9 (static main only) or ov<N>; sites are resolved from this image, never from the address alone. Byte source: HG/SS "
             "'arm9' bytes are ndspy's DECOMPRESSED loadArm9().sections[0] (ARM9 static image, RAM base 0x02000000); hge 'arm9' bytes are "
             "the RAW uncompressed rom.arm9 (hge stores it uncompressed; the raw file is padded to 0x2477C8, so `collides_with` of an hge "
             "site can list arm9 where the arm9 bytes are zero padding); 'ov<N>' bytes are the decompressed overlay N from the ROM overlay table",
    "register_hex": "full extent bytes read from the declared image (extent = min(16, symbol size), >=4)",
    "fire_hex": "8 hex digits: int.from_bytes(register_hex[:4],'little') — the callback's unsigned `val` word",
    "hge_status": "hge sites: KEPT = the extent bytes are identical to vanilla in the declared image (not a whole-function claim); "
                  "REPLACED = vanilla entry clobbered, the site is the exported replacement; SOURCE_ONLY = address from hge source",
    "phases": "candidate_sites are the G1 candidates; cap/target_max are the plan's per-phase budgets; armed_set is chosen at G2",
    "mode": "thumb|arm from the xMAP $t/$a mapping symbol (hgss/pt) or the stub/linker evidence recorded in mode_evidence (hge)",
    "collides_with": "other images whose bytes share this address range: residency + byte checks are mandatory",
    "overlays": "ROM overlay table; size is the decompressed byte length, bss is separate",
    "evidence_classes": "SOURCE (pinned source), FILE (pinned artifact bytes), OPEN (null + reason in `open`); nothing here is PHYSICAL. "
                        "probe_field_evidence also uses ASM (asm-corroborated SOURCE) and SOURCE_PROJECTION (hge: vanilla layout, FILE-checked)",
    "location": "profile.location: array-relative Location offsets {array_id, map_off, warp_off, x_off, y_off, dir_off} of 5 x s32 "
                "(struct_size 20); file_cross_check.general_off_of_array is the FILE position of that array in the general block (a "
                "cross-check, the runtime reads the array header)",
    "field_save": "profile.field_save (HG/SS + hge only; Pt OPEN): general-block offsets for the SYNTH `place` kind: vars[] (base id 0x4000), "
                  "flags[] bitmap (id 0 = no-op, ids >= 0x4000 temp/never saved), the 64 SavedMapObject list (stride 0x50) and "
                  "PlayerSaveData.state. Each block carries evidence_class SOURCE / FILE / DERIVED; the gen4_codec oracle reads none of it",
    "phase_cases": "titles.<t>.phase_cases[] are G1 qualification cases, NOT the production armed_set: sites (a subset of the phase's "
                   "candidate_sites within its cap; sites + 1 oracle observer <= 4 handles), producer_site (one of sites; the probe "
                   "compares an independent always-on observer of the same address with the registry events), predicate "
                   "{symbol, deref[], offset, value|nonzero} evaluated before each frame, route (named legs, status in route_status) and "
                   "caller_matrix (exercised_by_route is a design claim; every unexercised caller is listed in open). "
                   "phase_cases_blocked[] has the same shape but no fixture; phase_cases_excluded[phase][site] says why a candidate is not selected",
    "route_legs": "titles.<t>.route_legs{leg: {steps, until, max_frames, route_status, evidence, source, open, starts_from, note}}: "
                  "declarative button recipes. steps = [{press:[buttons], hold_frames, then_wait_frames}] run in order and the cycle repeats "
                  "while `until` is false, for at most max_frames; `until` = {symbol, deref[], offset, value|nonzero:true|zero:true} in the "
                  "phase-predicate shape (u32 read at deref-chain + offset) and must be evaluated every frame; route_status recipe_source "
                  "(derived from the pinned source/ROM tables) | open (steps [], until null, reason in `open`); evidence SOURCE|FILE|OPEN; "
                  "source = 'path:lines' in pokeheartgold@ad7a3afa (a test re-reads each first line from the clone); `note`/`starts_from` "
                  "are free text. Button names are exactly BizHawk's NDS joypad names: A B X Y Start Select Up Down Left Right L R "
                  "(the lua/tests/gen4_route_play.lua and probe play_route spelling). titles.<t>.route (rows b/m: battle + menu) and "
                  "persistence_route (row i: native SAVE) are lists of leg names; every phase_cases[].route name also exists in route_legs",
    "ui_geometry": "titles.<t>.ui_geometry: FILE-read battle cursor tables, start-menu neighbour/layout tables and the derived D-pad paths; "
                   "code_identity lists the UI functions whose full bytes are identical to the compared ROM (HG<->SS, hge<->HG)",
    "collision_pairs": "titles.<t>.collision_pairs[]: symbols from different images at ONE cpu address, each a full site row (image, "
                       "register_hex, fire_hex) plus resident_when per site: a capture must be attributed by residency, and the first words differ",
    "comparison": "address_differs counts distinct names whose address differs between HG and SS; differing_names_by_image attributes a name "
                  "to each image it differs in, so it sums to differing_name_image_pairs = address_differs + the names listed in "
                  "differing_names_in_several_images (file-local statics defined in two images)",
    "admission": "titles.<t>.admission is how lua/gen4/entry.lua treats the title: the lock status string for HG/SS (G0_IDENTITY_ONLY: a "
                 "pinned md5/sha1 hit AND the static-ARM9 anchors, so an hge ROM can never pass as vanilla); HASH_ONLY for hge (a pinned "
                 "md5/sha1 hit, no anchors: its arm9 entries are redirected); BIND_ONLY_NOT_ADMITTED for Platinum (refused by name). The "
                 "top-level artifact_status is the G0 ledger status from the sources lock, a different (release-process) fact, and is not "
                 "what the Lua client reads. Both the md5 and the sha1 of every title are pinned (BizHawk getromhash() is the md5 for "
                 "gamedb ROMs and the sha1 for the rest)",
    "admission_anchors": "HG/SS titles.<t>.admission_anchors[] = {name, address, image arm9, length, hex, hge_differs, evidence}: FILE bytes of "
                         "the vanilla static ARM9 (decompressed) that entry.lua compares with RAM (it reads only address + hex). The "
                         "`nitromain_hge_hook_site` row (0x02000CD0, hg-engine's Main() hook, armips/asm/syntheticoverlay.s:8) is the one hge "
                         "overwrites; hge titles.<t>.admission_check records the hge bytes there and the generator FAILS if they equal vanilla "
                         "or are not a call to load_arm9_expansion",
    "battle": "profile.battle: the zero-hook battle chain and BattleMon layout (lua/gen4/reads.lua R.battle; ability_* is the one HG/hge "
              "difference). bs = u32[man + man_data_off]; ctx = u32[bs + ctx_off]; btype = u32[bs + type_off]; result = u8[bs + outcome_off] "
              "& outcome_mask; man + template_off == template_id; battler b = ctx + mons_off + b*mon_size, selected slot u8[ctx + selected_off "
              "+ b] (6 = none), hp is s32 (all four bytes); FAINTED for battler b = bit (fainted_flag_shift + b) of u32[ctx + fainted_flag_off] "
              "(fainted_flag_mask covers the four). profile.battle_evidence gives class + citation per key (FILE ROM bytes / ASM / SOURCE) and `owner` {struct, cite}: the struct each offset is relative to (BattleSystem / BattleContext / BattleMon / OverlayManager), since the table mixes them; "
              "battle_file_checks are the ROM accessor bodies, battle_hge_checks the hge identity facts, battle_physical the live heap "
              "addresses seen (corroboration only, never match targets). battle.d7 = the D7 in-battle linked-faint seam read by lua/gen4/client.lua: "
              "seam {cmd, overlay_id, addr + pin_hex (HG/SS) | table (hge: the ROM dispatch word for cmd, client reads the pin live)}, ctx_cmd_off (u32 "
              "BattleContext.command), bs_party_off (BattleSystem.trainerParty[]), party_hp_off (PartyPokemon.hp), repl_flag_off (BattleContext "
              "replacement flag u32[ctx + off + 4*b] & 1); evidence in battle_evidence.d7.fields (class + cite + PHYSICAL receipt per field) and "
              "battle_d7_file_checks (the ROM bytes). Platinum: battle is null, reason in open",
    "battle_enums": "profile.battle_enums: outcomes (win 1 ... foe_fled 6, none 0), trainer_mask (BATTLE_TYPE_TRAINER = 1) and exempt_mask (= "
                    "no_catch_mask, the cfg name lua/gen4/poll_events.lua uses): link, multi, tag, safari, frontier, pal_park, tutorial, "
                    "bug_contest (not in Platinum), debug. type_bits is the full constant table, not_exempt says why each remaining bit is not exempt",
    "system": "profile.system: symbol, address (the gSystem RAM address, also title.symbols.gSystem, so the checkpoint needs no symbol table), "
              "vblank_counter_off, frame_counter_off. Platinum's offsets are derived from the struct and size-checked against the xMAP",
    "rtc": "profile.rtc (card C1-2e): the game's cached RTC work struct (symbol sRTCWork; Platinum sRTCState): symbol, address, work_size, "
           "date_off/date_size (RTCDate: u32 year, month, day, week) and time_off/time_size (RTCTime: u32 hour, minute, second), the async "
           "pair the refresh loop writes (async_date_off/async_time_off; async_names gives the field names: HGSS date_async/time_async, Platinum "
           "tempDate/tempTime), refresh_gate (lock/counter field names + offsets: getDateTimeLock/getDateTimeSleep, Platinum "
           "readInProgress/framesSinceRead; the refresh fires when counter > counter_threshold and no read is in flight), "
           "frozen_state_off/frozen_time_off (HGSS/hge only: the returned time is frozenTime while frozenTimeState == 3), source (citations), "
           "file_checks (ROM reader literal pools; bytes_source = which ARM9 bytes were read), hge_checks (hge only: the four functions' "
           "byte identity, decompressed HG ARM9 vs raw hge ARM9, sha256 per function), caveat",
    "diagnostic_sites": "titles.<t>.diagnostic_sites{id: site row}: HOT exec sites for performance characterization ONLY (how much an exec hook "
                        "per call costs). Never armed in production: not in `sites`, not a phase candidate and not in any phase_case (checked by "
                        "the generator and a test)",
    "pkm.hidden_ability": "hge only: {block, byte_off, bit, mask} of the hidden-ability flag; a table (not true) so a consumer that "
                          "tests == true stays off until it implements the located bit",
}


def build_hgss(inputs: Inputs) -> dict:
    lock = load_lock(inputs)
    titles, xms, imgs, roms, maps = {}, {}, {}, {}, {}
    for title in ("heartgold", "soulsilver"):
        roms[title] = verify_rom(inputs, lock, title)
        maps[title] = verify_asset(inputs, lock, title + "_xmap")
    bag, bag_open = bag_profile("hgss", inputs, bag_array_id())
    for title in titles_order():
        xms[title] = load_xmap(inputs.paths[title + "_xmap"])
        imgs[title] = load_images(inputs.paths[title])
        other = "soulsilver" if title == "heartgold" else "heartgold"
        titles[title] = title_block(xms[title], imgs[title], roms[title], lock["artifacts"][title]["admission"], title,
                                    load_images(inputs.paths[other]), other, bag=bag, bag_open=bag_open)
    errs = validate_hg_ss(titles["heartgold"], titles["soulsilver"])
    if titles["heartgold"]["diagnostic_sites"] != titles["soulsilver"]["diagnostic_sites"]:
        errs.append("diagnostic_sites differ between HG and SS")
    for t in titles_order():
        errs += (validate_sites(titles[t]["sites"], imgs[t], t) + validate_phase_cases(titles[t]) + validate_route_legs(titles[t])
                 + validate_collision_pairs(titles[t]) + validate_diagnostic_sites(titles[t], imgs[t]))
    if errs:
        raise Fail("; ".join(errs))
    return {
        "schema": SCHEMA, "pack": "gen4_hgss", "generator": GENERATOR,
        "provenance": {
            "lock": lock_provenance(inputs),
            "xmaps": {t: {"path": f".cache/gen4/xmap/{t_xmap_name(t)}", **maps[t]} for t in titles_order()},
            "roms": {t: roms[t] for t in titles_order()},
            "sources": {"pokeheartgold_citation": lock["sources"]["pokeheartgold_citation"]["commit"],
                        "pokeheartgold_xmap": lock["sources"]["pokeheartgold_xmap"]["commit"]},
            "notes": ["Symbols are the published CI xMAPs; sizes and addresses describe the sha1-pinned retail ROMs.",
                      "HG==SS is asserted for every emitted symbol and gameplay site (menu_only_ov74 bytes may differ per title)."],
        },
        "schema_notes": SCHEMA_NOTES,
        "comparison": compare_title_maps(xms["heartgold"], xms["soulsilver"]),
        "titles": titles,
    }


def titles_order() -> tuple[str, str]:
    return ("heartgold", "soulsilver")


def t_xmap_name(title: str) -> str:
    return {"heartgold": "heartgoldus.xMAP", "soulsilver": "soulsilverus.xMAP", "platinum": "platinumus.xMAP"}[title]


# ---- hg-engine ---------------------------------------------------------------------------
HGE_SOURCE_SITES = [
    # id, symbol, address, image, phase, role, mode, required prefix (instrument check), evidence
    ("hge_load_arm9_expansion", "load_arm9_expansion", 0x02110334, "arm9", "probe",
     "hge-only loader that loads ov129 from Main(); enters vanilla HandleLoadOverlay+8, bypassing the entry",
     "thumb", "04b5",
     "SOURCE armips/asm/syntheticoverlay.s:15-37 (.thumb, .area at 0x02110334); not in the cached exports"),
]


def hge_extra_symbols(hge_ld: dict, nm: dict, offsets: dict, names: list[str]) -> dict:
    out = {}
    for name in names:
        if name in offsets:
            unit, nm_addr = nm.get(name, (None, None))
            if nm_addr is not None and nm_addr != offsets[name]:
                raise Fail(f"hge export mismatch for {name}: offsets.ini {offsets[name]:#x} vs nm {nm_addr:#x}")
            out[name] = {"address": offsets[name], "address_hex": f"{offsets[name]:#010x}", "unit": unit,
                         "ld_value": hge_ld.get(name)}
    return out


def hge_mode(name: str, ld: dict, redirect: dict | None) -> tuple[str, str]:
    if name in ld:
        return ("thumb" if ld[name] & 1 else "arm"), "rom_gen.ld value (bit 0 = Thumb)"
    if redirect is not None and redirect.get("kind") == "ldr_bx_trampoline":
        return ("thumb" if redirect["thumb"] else "arm"), "vanilla-entry trampoline literal bit 0"
    raise Fail(f"cannot determine Thumb/ARM for hge replacement {name} (not in rom_gen.ld, no trampoline literal)")


# Vanilla functions the hge FieldSystem/launcher/battle/PC/save-driver chain runs; each must be byte-identical in the hge image.
HGE_IDENTICAL_FUNCS = (
    "FieldSystem_LaunchApplication", "FieldSystem_Main", "Field_AppExec", "ppOverlayManager_RunFrame_DeleteIfFinished",
    "FieldSystem_RunTaskFrame", "OverlayManager_New", "OverlayManager_Run", "OverlayManager_Delete",
    "Battle_LaunchApp", "Battle_Main", "Battle_Init", "Battle_Exit", "Battle_Run", "Task_StartBattle", "PCBox_LaunchApp",
    "sub_02050B08", "Task_WildEncounter", "ov01_021F68DC", "ov01_021F6A9C", "ov01_021F6B10",
    "ov01_021F54AC",  # the `mov r0,#1; str r0,[r4,#0x6c]` (probe_field.live TRUE) writer, asm/overlay_01_021F4704.s:1809-1842
)
# FieldSystem_New is the one hooked function: hge doubles the FIELD3 heap (one shifter byte) and hooks StoreFieldSysPtr.
HGE_FSNEW_WINDOWS = ((0x0203DFF4, 0x0203DFF5), (0x0203E028, 0x0203E030))
FS_SIZE = 0x128
# hge extends FieldSystem 0x128 but declares/preserves the vanilla prefix up to followMon @0xE4 (include/pokemon.h:612, vanilla
# include/field_system.h:171).  The FieldSystem-level probe_field offsets are only valid on hge while they sit below it.
HGE_FS_PREFIX_END = 0xE4
# probe_field keys that are NOT FieldSystem offsets: FieldSystemUnkSub0-relative (the struct at fs+0 via `sub`), SysTask.data-relative
# (save_state) or SysTask-relative (save_driver_data_off).  Every other key, including any added later, is FieldSystem-level.
NON_FS_PROBE_KEYS = ("launched_app", "field_app", "paused", "save_state", "save_driver_data_off")


def hge_field_checks(xm: XMap, hg: Images, hge: Images) -> dict:
    """FILE facts that make the vanilla FieldSystem layout applicable to hge (the fork declares only part of the struct)."""
    funcs = []
    for name in HGE_IDENTICAL_FUNCS:
        s = xm.lookup(name)
        if hg.read(s.image, s.address, s.size) != hge.read(s.image, s.address, s.size):
            raise Fail(f"hge changed {name} ({s.image} {s.address:#x}); the vanilla FieldSystem projection is no longer valid")
        funcs.append({"symbol": name, "image": s.image, "address": s.address, "size": s.size})
    fn = xm.lookup("FieldSystem_New")
    a, b = hg.read("arm9", fn.address, fn.size), hge.read("arm9", fn.address, fn.size)
    diff = [fn.address + i for i in range(fn.size) if a[i] != b[i]]
    if not diff or any(not any(lo <= d < hi for lo, hi in HGE_FSNEW_WINDOWS) for d in diff):
        raise Fail(f"hge FieldSystem_New differs outside the declared windows: {[hex(d) for d in diff]}")
    halfwords = struct.unpack_from("<HHH", hge.read("arm9", fn.address + 0x26, 6))
    if halfwords[0] != 0x214A or halfwords[2] != 0x0089:  # movs r1,#0x4a ; adds r0,r5,#0 ; lsls r1,r1,#2
        raise Fail("hge FieldSystem_New allocation literal moved (expected movs r1,#0x4a; lsls r1,r1,#2)")
    alloc = (halfwords[0] & 0xFF) << 2
    if alloc != FS_SIZE:
        raise Fail(f"hge FieldSystem_New allocates {alloc:#x}, not the declared {FS_SIZE:#x}")
    fs_level = {k: v[0] for k, v in {**PROBE_FIELD, **PROBE_FIELD_EXTRA}.items() if k not in NON_FS_PROBE_KEYS}
    if not NON_FS_PROBE_KEYS or set(NON_FS_PROBE_KEYS) - {*PROBE_FIELD, *PROBE_FIELD_EXTRA} or len(fs_level) < 4:
        raise Fail("NON_FS_PROBE_KEYS no longer names probe_field keys (the FieldSystem-level set would be wrong)")
    top = max(fs_level.values())
    if top >= HGE_FS_PREFIX_END:
        raise Fail(f"a FieldSystem-level probe_field offset {top:#x} reaches the part of hge FieldSystem that is not the preserved "
                   f"prefix (< {HGE_FS_PREFIX_END:#x}); the vanilla projection no longer holds")
    return {
        "evidence": f"FILE: vanilla xMAP symbol extents compared byte-for-byte in the hge image (declared image per symbol); {ARM9_BYTES_NOTE}",
        "functions_byte_identical": funcs,
        "preserved_prefix": {"end": HGE_FS_PREFIX_END, "probe_field_keys": sorted(fs_level), "non_fieldsystem_keys": list(NON_FS_PROBE_KEYS),
                             "max_probe_field_offset": top,
                             "evidence": f"{HGE_SRC} include/pokemon.h:612 (followMon @0xE4), size {FS_SIZE:#x}; vanilla "
                                         "include/field_system.h:171; the checked invariant is max(offset) < end"},
        "field_system_new": {
            "symbol": "FieldSystem_New", "address": fn.address, "size": fn.size, "alloc_size": alloc,
            "alloc_evidence": f"movs r1,#0x4a; lsls r1,r1,#2 at FieldSystem_New+0x26 (hge); fork header size {FS_SIZE:#x} "
                              f"({HGE_SRC} include/pokemon.h:619)",
            "differs_in": [[lo, hi] for lo, hi in HGE_FSNEW_WINDOWS],
            "differs_explained": "0x0203DFF4: Heap_Create size shifter (lsls r2,r1,#9 -> #0xa: field heap 3 doubled, no layout "
                                 "change); 0x0203E028+8: StoreFieldSysPtr hook (hooks:293) stores the extra gFieldSysPtr then "
                                 "re-executes the replaced vanilla instructions; the vanilla stores around it are unchanged",
            "actual_diff_addresses": diff,
        },
    }


# hidden-ability flag: MON_DATA_RESERVED_113 = vanilla MON_DATA_UNUSED_113 = PokemonDataBlockB.unused1 (a 2-bit field at
# byte 0x19 bits 6-7); hge's DUMMY_P2_1_HIDDEN_ABILITY_MASK 0x01 is bit 0 OF THAT FIELD = byte 0x19 bit 6 (mask 0x40).
HGE_HA_GET = (0x0206EA50, "707e0006840f")  # ldrb r0,[r6,#0x19]; lsls r0,r0,#0x18; lsrs r4,r0,#0x1e (GetBoxMonDataInternal)
HGE_HA_SET = (0x0206F220, "697ec02014b0814320788007000e08436876")  # ldrb r1,[r5,#0x19]; movs r0,#0xc0; ...; strb r0,[r5,#0x19]


def hge_hidden_ability(hg: Images, hge: Images) -> dict:
    for label, (addr, want) in (("get", HGE_HA_GET), ("set", HGE_HA_SET)):
        n = len(want) // 2
        got = hge.read("arm9", addr, n)
        if got.hex() != want or hg.read("arm9", addr, n) != got:
            raise Fail(f"hge MON_DATA_UNUSED_113 {label} code at {addr:#x} is not the vanilla 2-bit field accessor ({got.hex()})")
    return {
        "block": "B", "byte_off": 0x19, "field_bits": [6, 7], "bit": 6, "mask": 0x40,
        "evidence": f"SOURCE {HGE_SRC} include/pokemon.h:21-23,57-58 (DUMMY_P2_1_HIDDEN_ABILITY_MASK 0x01 of MON_DATA_RESERVED_113, "
                    f"a 2-bit field), include/pokemon.h:265-266 (HGSS_shinyLeaves:6 then unk_19_6:2 at block B +0x19); "
                    f"{PRET_HG} src/pokemon.c:728-730,1190-1192 (UNUSED_113 = blockB->unused1); FILE: GetBoxMonDataInternal "
                    "0x0206EA50 = ldrb [r,#0x19]; lsls #0x18; lsrs #0x1e (bits 6-7) and SetBoxMonDataInternal 0x0206F220 "
                    "clears 0xC0 / inserts (v&3)<<6, byte-identical in the HG and hge ROMs",
        "note": "the research notes say 'block B +0x19 bit 0'; that is bit 0 of the 2-bit field, i.e. byte bit 6 (0x40). "
                "Bit 0 of the byte is HGSS_shinyLeaves (Leaf Crown), NOT the hidden-ability flag",
    }


def build_hge(inputs: Inputs) -> dict:
    lock = load_lock(inputs)
    hge_rom = verify_rom(inputs, lock, "heartgold_hge")
    hg_rom = verify_rom(inputs, lock, "heartgold")
    maps = {"heartgold": verify_asset(inputs, lock, "heartgold_xmap")}
    exports = {k: verify_asset(inputs, lock, k) for k in ("hge_offsets", "hge_rom_gen_ld", "hge_nm_all")}
    xm = load_xmap(inputs.paths["heartgold_xmap"])
    hg_img = load_images(inputs.paths["heartgold"])
    hge_img = load_images(inputs.paths["heartgold_hge"], raw_arm9=True)
    check_xmap_vs_rom(xm, hg_img, "heartgold")
    offsets = parse_offsets_ini(inputs.paths["hge_offsets"].read_text(encoding="utf-8"))
    nm = parse_nm(inputs.paths["hge_nm_all"].read_text(encoding="utf-8"))
    ld = parse_rom_gen_ld(inputs.paths["hge_rom_gen_ld"].read_text(encoding="utf-8"))

    sites: dict[str, dict] = {}
    for site_id, symbol, phase, role, expect in SITE_SPECS:
        van = vanilla_sites(xm, hg_img, [(site_id, symbol, phase, role, expect)])[site_id]
        n = van["extent"]
        hge_bytes = hge_img.read(van["image"], van["address"], n).hex()
        status = "KEPT" if hge_bytes == van["register_hex"] else "CHANGED"
        if expect == "KEPT" and status != "KEPT":
            raise Fail(f"hge site {site_id} ({symbol}) expected KEPT but differs from vanilla at {van['address']:#x}")
        if expect == "REPLACED" and status != "CHANGED":
            raise Fail(f"hge site {site_id} ({symbol}) expected REPLACED but is byte-identical to vanilla")
        if status == "KEPT":
            row = dict(van)
            row["hge_status"] = "KEPT"
            row["mode_evidence"] = "xMAP $t/$a mapping symbol (vanilla), bytes identical in hge"
            sites[site_id] = row
            continue
        if symbol not in offsets:
            raise Fail(f"hge replaced {symbol} has no offsets.ini entry")
        unit, nm_addr = nm.get(symbol, (None, None))
        if nm_addr is not None and nm_addr != offsets[symbol]:
            raise Fail(f"hge export mismatch for {symbol}: offsets.ini {offsets[symbol]:#x} vs nm {nm_addr:#x}")
        if unit not in HGE_NM_UNITS:
            raise Fail(f"hge replacement {symbol} unit {unit!r} has no declared overlay")
        oid = HGE_NM_UNITS[unit]
        image = f"ov{oid}"
        addr = offsets[symbol]
        entry = hge_img.read(van["image"], van["address"], van["extent"])
        redirect = decode_redirect(van["address"], hge_img.read(van["image"], van["address"], 0x1C))
        if redirect is not None and redirect["target"] != addr:
            raise Fail(f"hge {symbol}: vanilla-entry redirect {redirect['target']:#x} != exported replacement {addr:#x}")
        mode, evidence = hge_mode(symbol, ld, redirect)
        reg = hge_img.read(image, addr, EXTENT_MAX).hex()
        sites[site_id] = {
            "symbol": symbol, "address": addr, "address_hex": f"{addr:#010x}", "image": image, "overlay_id": oid,
            "phase": phase, "role": role, "extent": EXTENT_MAX, "register_hex": reg, "fire_hex": fire_hex(reg),
            "mode": mode, "mode_evidence": evidence, "section": ".text", "hge_status": "REPLACED",
            "collides_with": hge_img.collisions(image, addr, EXTENT_MAX),
            "replaces": {
                "vanilla_address": van["address"], "vanilla_image": van["image"],
                "vanilla_entry_hex": entry.hex(), "vanilla_register_hex": van["register_hex"],
                "redirect": redirect,
                "redirect_evidence": "decoded from the hge entry bytes" if redirect else
                "OPEN: entry is not a plain trampoline/stub; address from offsets.ini + nm_all only",
            },
            "export_unit": unit,
        }
    replacement = sites["pc_place_first_in_box"]
    rep = replacement["replaces"]
    if rep["vanilla_image"] != "arm9" or not rep["redirect"] or rep["redirect"]["target"] != replacement["address"]:
        raise Fail("PC placement ARM9 trampoline does not target the pinned hge replacement")
    pin = rep["vanilla_entry_hex"]
    sites["pc_place_arm9_entry"] = {
        "symbol": replacement["symbol"], "address": rep["vanilla_address"],
        "address_hex": f"{rep['vanilla_address']:#010x}", "image": "arm9", "overlay_id": None,
        "phase": "pc", "role": "probe static ARM9 placement trampoline; native PC deposit",
        "extent": len(bytes.fromhex(pin)), "register_hex": pin, "fire_hex": fire_hex(pin),
        "mode": "thumb", "mode_evidence": "FILE decoded ldr/bx Thumb trampoline at vanilla xMAP entry",
        "section": ".text", "hge_status": "TRAMPOLINE", "redirect": copy.deepcopy(rep["redirect"]),
        "source": f"SOURCE {PRET_HG} src/pokemon_storage_system.c:70-88; SOURCE hg-engine hooks:436; FILE hge replacement entry redirect",
        "collides_with": hge_img.collisions("arm9", rep["vanilla_address"], len(bytes.fromhex(pin))),
    }
    for site_id, symbol, addr, image, phase, role, mode, prefix, evid in HGE_SOURCE_SITES:
        reg = hge_img.read(image, addr, EXTENT_MAX).hex()
        if not reg.startswith(prefix):
            raise Fail(f"hge source site {symbol} @{addr:#x}: bytes {reg} do not start with {prefix} (wrong address?)")
        sites[site_id] = {
            "symbol": symbol, "address": addr, "address_hex": f"{addr:#010x}", "image": image,
            "overlay_id": overlay_id(image), "phase": phase, "role": role, "extent": EXTENT_MAX,
            "register_hex": reg, "fire_hex": fire_hex(reg), "mode": mode, "section": ".text",
            "mode_evidence": f"{evid}; first halfword {prefix} = push {{r2,lr}}", "hge_status": "SOURCE_ONLY",
            "collides_with": hge_img.collisions(image, addr, EXTENT_MAX),
        }

    symbols = {}
    for name in SYMBOL_NAMES:
        row = symbol_row(xm, name)
        check_symbol_in_image(row, name, hg_img, xm)
        if row["section"] == ".text" and row["image"] == "arm9":
            n = extent_for(row["size"])
            row["hge_status"] = "KEPT" if hge_img.read("arm9", row["address"], n) == hg_img.read("arm9", row["address"], n) else "CHANGED"
        symbols[name] = row
    replacement_names = [s["symbol"] for s in sites.values() if s.get("hge_status") == "REPLACED"]
    replacements = hge_extra_symbols(ld, nm, offsets, replacement_names + ["HandleLoadOverlay", "UnloadOverlayByID"])
    for name, row in replacements.items():
        if name in symbols and symbols[name].get("address") == row["address"]:
            raise Fail(f"hge replacement {name} equals the vanilla address; not a replacement")
        row["image"] = f"ov{HGE_NM_UNITS[row['unit']]}" if row["unit"] in HGE_NM_UNITS else None
    # hge-only source sites have no xMAP row; the probe validator resolves every site through title.symbols.
    for _, symbol, addr, image, _, _, mode, _, evid in HGE_SOURCE_SITES:
        if symbol in symbols:
            raise Fail(f"hge source site symbol {symbol} collides with a vanilla symbol")
        symbols[symbol] = {"address": addr, "address_hex": f"{addr:#010x}", "image": image, "mode": mode,
                           "section": ".text", "size": None, "object": None, "hge_status": "SOURCE_ONLY", "evidence": evid}
    ovr = xm.lookup("sOverlayRegions")
    errs = validate_sites(sites, hge_img, "hge")
    if errs:
        raise Fail("; ".join(errs))

    field_checks = hge_field_checks(xm, hg_img, hge_img)
    profile = hgss_profile(xm, "hge", field_checks)
    profile["save"] = save_geometry(
        0x2F, f"SOURCE {HGE_SRC} include/constants/save.h:16-24 (SAVE_PAGE_MAX 0x2F; OFFSET_saveSlotSpecs 0x2F2B4), include/save.h:264-284",
        "OPEN: not read from a live hge SaveData (G2); allocation is hooked (SaveData_New)")
    if profile["save"]["slot_specs_off"] != 0x2F2B4:
        raise Fail("derived hge slot_specs_off disagrees with the source constant OFFSET_saveSlotSpecs 0x2F2B4")
    profile["system"]["evidence"] += f"; {HGE_SRC} include/system.h:8-48 declares the identical struct"
    profile["rtc"] = rtc_profile(xm, hge_img, "hge", hg_img)
    profile["party_off"] = {
        "value": 0x90, "base": "general_block", "count_off": 4, "max_off": 0, "mons_off": 8, "array_id": 2,
        "evidence": {"heartgold_hge": "FILE (owner hge save OOO sha1 13d56589, C:/slink/g4/saves/hge_a_OOO_630.SaveRAM: max=6 @+0x90, "
                                      "count=1 @+0x94, Cyndaquil species 155 via codec.parse_save(img,'hge').party())",
                     "rejected_candidate": "general+0xCAB4 also passed the empty-save header scan, but on the populated save it "
                                           "holds (7, 0): not a party header (max != 6)"}}
    profile["box_modified_flag_off"] = 0x1E004
    profile["pc"] = {"array_id": 41, "slot": "pc", "box_base": 0, "box_stride": 0x1000, "mon_stride": 0x88,
                     "cur_box_off": None, "box_modified_flag_off": 0x1E004,
                     "box_modified_flag_evidence": box_flag_evidence(
                         "hge", f"PCStorage+0x1E004 (0x1000*30+4, {HGE_SRC} include/pokemon_storage_system.h:50-59)"),
                     "evidence": f"SOURCE {HGE_SRC} include/constants/save.h:26 (NUM_PC_BOXES 30); PC block at bank+0x10000 size 0x1E4FC FILE"}
    profile["trainer"] = copy.deepcopy(HGE_TRAINER)
    profile["location"] = copy.deepcopy(HGE_LOCATION)
    profile["field_save"] = copy.deepcopy(HGE_FIELD_SAVE)
    profile["pkm"] = {**PKM_BASE, "exp_bits": 21, "hidden_ability": hge_hidden_ability(hg_img, hge_img),
                      "ability_msb": {"word_block": "A", "word_off": 8, "bit": 31, "low_byte_block": "A",
                                      "low_byte_off": 0xD,
                                      "evidence": f"SOURCE {HGE_SRC} include/pokemon.h:226-232 (exp:21, unused:10, abilityMSB:1)"}}
    profile.update(battle_profile("hge", "heartgold_hge", xm, hge_img, hg_img))
    profile["boxes"], profile["mons_per_box"], profile["memorial_box"] = 30, 30, 29
    profile["bag"], bag_open = bag_profile("hge", inputs, profile["save"]["array_ids"]["bag"])

    open_ = {
        "pc.cur_box_off": "source projection 0x1E000 only; G2",
        "hge_internal_overlay_loads": (
            "hge's own loads of ov129 (from load_arm9_expansion, entering vanilla HandleLoadOverlay+8) and of the linked "
            "extensions 130/131 (a goto loop inside the replacement HandleLoadOverlay, src/overlay.c:102-215) never re-enter the "
            "vanilla entry. All reach LoadOverlayNoInitAsync(0, id) (loadType 2): sites load_overlay_noinit_async (kept, static "
            "ARM9) and hge_load_arm9_expansion are pinned; full coverage would need all three LoadOverlay* funnels "
            "(over the 4-hook budget with anything else), so residency stays table-polled. PHYSICAL coverage is a C1-1 cell"),
        "fresh_build_association": "cached exports are the pinned file hashes, not proof they came from a fresh build of this ROM "
                                   "(lock pending hge_fresh_build_export_association)",
        "probe_field": "hge declares only FieldSystem.savedata/taskman (include/pokemon.h:592-597); the other offsets are the vanilla "
                       "ones (class SOURCE_PROJECTION: fork layout identical where declared, FieldSystem_New and the launch/"
                       "overlay-manager/save-driver code byte-identical, profile.probe_field_hge_checks); a G1 PHYSICAL cell",
        "pkm.hidden_ability_decode": "pack carries the field location (byte 0x19 bit 6, mask 0x40); lua/gen4/pk4.lua:180 reads bit 0 "
                                     "of that byte (the HGSS Leaf Crown bit), so reads.lua must keep hidden_ability off until "
                                     "pk4.lua is corrected",
        "pc_swap_redirect": "see sites.pc_swap_by_index_pair.replaces.redirect_evidence",
        "hge_save_geometry_live": "SaveData geometry is source-derived; live read is G2",
        **{k: v for k, v in hgss_open().items() if k in ("phase_first_event_coverage", "battle_offsets_live_read")},
        **route_open(),
        "battle_hge_effects": "hge faint is replaced in ov130; offsets are shared with vanilla but the active-faint mechanism "
                              "and copy-back are C1-8 cells (battle_pointer.md Open)",
    }
    if bag_open:
        open_["bag"] = bag_open
    title = {
        "rom": {k: hge_rom[k] for k in ("sha1", "md5", "header_code")},
        "admission": "HASH_ONLY",
        "admission_check": hge_admission_check(hg_img, hge_img, admission_anchors(xm, hg_img), HGE_SOURCE_SITES[0][2]),
        "diagnostic_sites": diagnostic_sites(xm, hg_img, hge_img),
        "symbols": symbols, "hge_replacements": replacements, "sites": sites,
        "overlays": hge_img.overlay_table(),
        "overlay_table": {"symbol": "sOverlayRegions", "address": ovr.address, "regions": 3, "per_region": 8,
                          "entry_size": 8, "id_off": 0, "active_off": 4,
                          "evidence": "never patched by hge (rom.ld:552 / platform.md); per_region = MAX_ACTIVE_OVERLAYS 8"},
        "profile": profile, "phases": phase_table(sites, "hge"), **build_phase_cases(xm, hge_img, hge=True), "open": open_,
    }
    ui = ui_geometry(xm, hge_img, hg_img, "heartgold (vanilla)")
    title.update({"ui_geometry": ui, **build_route_legs(ui, "hge"), "collision_pairs": collision_pairs(xm, hge_img, "hge", hg_img)})
    title["phase_cases_hge_note"] = (
        "same predicate and site ids as HG: Battle_LaunchApp/Battle_Run/PCBox_LaunchApp and the OverlayManager code are byte-identical "
        "in the hge image (profile.probe_field_hge_checks) and the templates carry the same ovy_id; battle_faint_cmd and the pc_* "
        "sites are the hge REPLACEMENT addresses (ov130 / ov129). Whether hge keeps the vanilla battle scripts and the PC UI callers "
        "is a G1 PHYSICAL cell")
    errs = (validate_phase_cases(title) + validate_route_legs(title) + validate_collision_pairs(title)
            + validate_diagnostic_sites(title, hge_img))
    if errs:
        raise Fail("; ".join(errs))
    return {
        "schema": SCHEMA, "pack": "gen4_hge", "generator": GENERATOR, "artifact_status": "RECORDED_NOT_ADMITTED",
        "provenance": {
            "lock": lock_provenance(inputs),
            "roms": {"heartgold_hge": hge_rom, "heartgold_vanilla_baseline": hg_rom},
            "hge_build": {"rom_sha1": hge_rom["sha1"], "exports": exports,
                          "source_commit": lock["sources"]["hg_engine_fork"]["commit"],
                          "note": "cached exports are RECORDED_EXPORT_FILE_ONLY: not a fresh build association"},
            "xmaps": {"heartgold": {"path": ".cache/gen4/xmap/heartgoldus.xMAP", **maps["heartgold"]}},
            "notes": ["Vanilla addresses/images come from the HG xMAP; kept sites are asserted byte-identical in the hge image.",
                      "Replacement addresses come from offsets.ini, cross-checked against nm_all.txt, rom_gen.ld and the vanilla entry redirect."],
        },
        "schema_notes": SCHEMA_NOTES,
        "titles": {"heartgold_hge": title},
    }


# ---- Platinum ----------------------------------------------------------------------------
def pt_profile() -> dict:
    page_max, body_off = 32, 0x14
    body = page_max * 0x1000
    counters = body_off + body  # globalCounter
    page_info = (counters + 4 + 2 * 4 + 2 + 3) & ~3  # blockCounters[2] u32, blockOffsets[2] u8, align 4
    block_info = page_info + 38 * 0x10  # SavePageInfo pageInfo[SAVE_TABLE_ENTRY_MAX]; SaveBlockInfo is 4-aligned (u32 members)
    return {
        "save_ptr": {"symbol": "sSaveDataPtr", "width": 4},
        "fieldsys_ptr": {"symbol": "sFieldSystem", "width": 4, "save_data_off": 0x0C, "process_manager_off": 0,
                         "evidence": f"SOURCE {PRET_PT} include/field/field_system.h:76-82 (processManager, unk_04, bgConfig, saveData)"},
        "save": {
            "evidence": f"SOURCE {PRET_PT} include/savedata.h:7-62, include/constants/savedata/save_table.h:65-66",
            "runtime_confirmation": "OPEN: no Platinum emulator work in this release (D3)",
            "body_off": body_off, "body_size": body,
            "table": "pageInfo", "table_off": page_info, "entry_size": 0x10, "field_off": 8,
            "entry_fields": {"page_id": 0, "size": 4, "location": 8, "checksum": 0xC, "block_id": 0xE},
            "entry_count": 38,
            "array_addr": "SaveData + body_off + u32[SaveData + table_off + id*entry_size + field_off]",
            "array_ids": {"system": 0, "player": 1, "party": 2, "bag": 3, "field_player_state": 6,
                          "field_overworld_state": 11, "pc_boxes": 37},
            "array_ids_note": "pc_boxes counted from the SaveTableEntryID enum (SAVE_TABLE_ENTRY_PC_BOXES = 37, MAX = 38); "
                              "platinum_bind.md says 38, which is SAVE_TABLE_ENTRY_MAX",
            "footer": {"fields": {"save_counter": 0, "block_counter": 4, "size": 8, "signature": 0xC, "block_id": 0x10,
                                  "checksum": 0x12},
                       "signature": 0x20060623, "size": 0x14, "block_count": 2, "blocks": {"normal": 0, "boxes": 1},
                       "addr": "SaveData + body_off + blockInfo[b].offset + blockInfo[b].size - size",
                       "valid_when": "signature == 0x20060623 and footer.size == blockInfo[b].size and footer.block_id == b",
                       "evidence": f"SOURCE {PRET_PT} include/savedata.h:7-14 (differs from HGSS: extra blockCounter + blockID), "
                                   "src/savedata.c:313-325,327-350,361-373 (SaveBlockFooter_Ptr / _Validate / _Set: the footer sits in "
                                   "the RAM body at the end of each block); FILE: owner Pt save pt_TTT_44361 general block ends with a "
                                   "0x14-byte footer (counter 1, blockCounter 1, size 0xCF2C = the block length, signature, blockID 0); "
                                   "RAM address is SOURCE only (no Platinum emulator work, D3)"},
            "block_info": {"table_off": block_info, "entry_count": 2, "entry_size": 0xC,
                           "entry_fields": {"block_id": 0, "sector_start": 1, "sectors_in_use": 2, "offset": 4, "size": 8},
                           "evidence": f"SOURCE {PRET_PT} include/savedata.h:17-23,59-60 (SaveBlockInfo; SaveData order: pageInfo "
                                       "then blockInfo), src/savedata.c:852-870 (offset = running sum of block sizes, size = entries "
                                       "+ footer); the 0x20284 start follows from the same struct layout as table_off"},
        },
        "party_off": {"value": 0x98, "base": "general_block", "count_off": 4, "max_off": 0, "mons_off": 8, "array_id": 2,
                      "evidence": {"platinum": f"FILE (owner Pt save pt_TTT_44361: max=6 @+0x98, count=1 @+0x9C, Turtwig species 387 "
                                               f"at +0xA0 via codec.parse_save(img,'pt')); SOURCE {PRET_PT} include/party.h:11-15 "
                                               "(Party: capacity, currentCount, pokemon[6])"}},
        "trainer": copy.deepcopy(PT_TRAINER),
        "location": copy.deepcopy(PT_LOCATION),
        "pc": {"array_id": 37, "box_base": 4, "box_stride": 0xFF0, "mon_stride": 0x88, "cur_box_off": 0,
               "boxes": 18, "mons_per_box": 30, "modified_flag_off": None,
               "evidence": f"SOURCE {PRET_PT} include/pc_boxes.h:18-24 (u32 currentBoxID, then boxMons[18][30], no pad)"},
        "dirty": {"modified_flag_off": None,
                  "full_save_flag": {"base": "SaveData", "off": 0x0C, "width": 4,
                                     "evidence": f"SOURCE {PRET_PT} include/savedata.h:50-57 (fullSaveRequired, src/savedata.c:251-254)"}},
        "pkm": {"box_size": 0x88, "party_size": 0xEC, "exp_bits": 32, "ability_msb": None, "party_hp_width": 2,
                "ball_off_block_d": 0x1B, "block_d_0x1E": "unused in Platinum (HGSS ball/mood)"},
        "boxes": 18, "mons_per_box": 30, "memorial_box": None,
        "battle": None, "battle_enums": battle_enums("pt"),
        "probe_field": None, "probe_wrong_write_offset": None,
        "system": {"symbol": "gSystem", "vblank_counter_off": None},
        "idle": {"taskman_clause": "NOT valid (+0x10 is a transient FieldTask*)",
                 "app_clause": "FieldSystem_IsRunningApplication = processManager(+0x00)->parent/child"},
    }


# pokeplatinum include/system.h:30-66 `struct System`, in declaration order up to frameCounter (every slot a 4-byte pointer/u32).
PT_SYSTEM_HEAD = ("vblankCallback", "vblankCallbackData", "hblankCallback", "hblankCallbackData", "dummyCallback_10", "dummyCallback_14",
                  "mainTaskMgr", "vBlankTaskMgr", "postVBlankTaskMgr", "printTaskMgr", "unused_28", "vblankCounter", "frameCounter")
# ...then buttonMode, 3 Raw u32, 3 held/pressed/repeatable u32, 3 autorepeat ints (10 words); 4 x u16 touch; 4 x u8; inhibitReset + padding_69[3];
# BOOL showTitleScreenIntro; u32 *heapCanary: the sizeof is cross-checked against the xMAP gSystem size (0x74).
PT_SYSTEM_TAIL_BYTES = 4 * 10 + 4 * 2 + 4 + 4 + 4 + 4


def pt_system(gsys: dict) -> dict:
    offs = {name: 4 * i for i, name in enumerate(PT_SYSTEM_HEAD)}
    size = 4 * len(PT_SYSTEM_HEAD) + PT_SYSTEM_TAIL_BYTES
    if size != gsys["size"]:
        raise Fail(f"Platinum System layout {size:#x} != xMAP gSystem size {gsys['size']:#x}: the vblankCounter offset is unproven")
    return {
        "symbol": "gSystem", "address": gsys["address"], "vblank_counter_off": offs["vblankCounter"],
        "frame_counter_off": offs["frameCounter"],
        "address_evidence": "xMAP gSystem (the same symbol row as title.symbols.gSystem)",
        "evidence": f"SOURCE {PRET_PT} {P_SYSTEM} (struct System: 11 four-byte callback/pointer slots, then vblankCounter {P_VBLANK}, then "
                    f"frameCounter); FILE: the struct's computed size {size:#x} equals the xMAP gSystem size; {P_VBLANK_INC} "
                    "(main loop increments vblankCounter). PHYSICAL: none (no Platinum emulator work, D3)"}


def pt_open() -> dict:
    return {
        "probe_field": "bind-only and structurally different: Platinum has no FieldSystemUnkSub0 (launched-app / field-app / isPaused cells) and "
                       "no HGSS save-driver SysTask; its application state is FieldProcessManager parent/child (offsets not established, "
                       "platinum_bind.md) and taskman is a transient FieldTask*. The HGSS probe_field keys have no Platinum counterpart to fill",
        "probe_wrong_write_offset": "no Platinum gSystem padding-byte audit (the struct layout is derived for system.vblank_counter_off only)",
        "memorial_box": "bind-only: no Platinum Soul Link box policy exists; not guessed",
        "battle": "Platinum battle context offsets are not established (BattleContext/BattleMon have no offset annotations or accessor pins "
                  "in pokeplatinum, and a hand-counted layout of those nested structs was not attempted); do not derive from HGSS. "
                  "profile.battle_enums IS filled: the constants are plain bit values in include/constants/battle.h. "
                  "profile.battle.d7 (the in-battle linked-faint seam) is therefore ABSENT, OPEN: Platinum is a bind-check only",
        "pc.modified_flag_off": "Platinum has no per-box modified flag; the dirty clause is the whole-save fullSaveRequired flag",
        "process_manager_parent_child_offsets": "offsets of parent/child inside FieldProcessManager not established (platinum_bind.md)",
        "codec": "no populated Platinum save (local save is blank): codec bind cell is OPEN (D3)",
        "sites": "bind-only pack pins no execute sites; symbols and the overlay table only",
        "save.footer.runtime": "RAM footer address (block_info + footer.addr) is SOURCE only; lua/gen4/reads.lua still uses a structural "
                               "page-table check for Platinum until it consumes save.footer / save.block_info",
        "trainer.badges": "TrainerInfo has one badgeMask byte (8 Sinnoh badges): trainer.badge_mask_off, no johto/kanto pair",
        "pt_pack_not_runtime": "a generated profile does not prove every module reusable (platinum_bind.md evidence limits)",
        "route_legs": "bind-only: no Platinum probe route, button recipe or UI geometry was derived (pokeplatinum menus differ; D3)",
        "collision_pairs": "bind-only: no Platinum shared-address pair was derived (FieldMap_VBlankCallback is not in the Platinum xMAP)",
    }


def build_pt(inputs: Inputs) -> dict:
    lock = load_lock(inputs)
    rom = verify_rom(inputs, lock, "platinum")
    xmap_row = verify_asset(inputs, lock, "platinum_xmap")
    xm = load_xmap(inputs.paths["platinum_xmap"])
    images = load_images(inputs.paths["platinum"])
    check_xmap_vs_rom(xm, images, "platinum")
    symbols = {}
    for role, name in PT_SYMBOLS.items():
        row = symbol_row(xm, name)
        check_symbol_in_image(row, name, images, xm)
        row["role"] = role
        symbols[name] = row
    table = symbols[PT_SYMBOLS["overlay_table"]]
    if table["size"] != 0xC0:
        raise Fail(f"Platinum overlay table size {table['size']:#x} != 0xC0")
    profile = pt_profile()
    profile["system"] = pt_system(symbols["gSystem"])
    profile["rtc"] = rtc_profile(xm, images, "pt")
    profile["save_ptr"]["address"] = symbols["sSaveDataPtr"]["address"]
    profile["fieldsys_ptr"]["address"] = symbols["sFieldSystem"]["address"]
    return {
        "schema": SCHEMA, "pack": "gen4_pt", "generator": GENERATOR, "artifact_status": "BIND_ONLY_NOT_ADMITTED",
        "provenance": {
            "lock": lock_provenance(inputs),
            "roms": {"platinum": rom},
            "xmaps": {"platinum": {"path": ".cache/gen4/xmap/platinumus.xMAP", **xmap_row}},
            "sources": {"pokeplatinum_citation": lock["sources"]["pokeplatinum_citation"]["commit"],
                        "pokeplatinum_xmap": lock["sources"]["pokeplatinum_xmap"]["commit"]},
            "notes": ["Platinum names differ from HGSS; PT_SYMBOLS maps roles to names.",
                      "Bind-only: source schema feasibility, not runtime support (D3)."],
        },
        "schema_notes": SCHEMA_NOTES,
        "titles": {"platinum": {
            "rom": {k: rom[k] for k in ("sha1", "md5", "header_code")},
            "admission": "BIND_ONLY_NOT_ADMITTED",
            "symbols": symbols, "sites": {},
            "overlays": images.overlay_table(),
            "overlay_table": {"symbol": PT_SYMBOLS["overlay_table"], "address": table["address"], "regions": 3,
                              "per_region": 8, "entry_size": 8, "id_off": 0, "active_off": 4,
                              "evidence": f"{PRET_PT} src/game_overlay.c:13-32 (same {{id,active}} shape; size 0xC0 checked)"},
            "profile": profile, "phases": {}, "open": pt_open(),
        }},
    }


BUILDERS = {"hgss": build_hgss, "hge": build_hge, "pt": build_pt}


def render(pack: dict) -> str:
    return json.dumps(pack, indent=2, sort_keys=True) + "\n"


def generate(mode: str, inputs: Inputs) -> str:
    return render(BUILDERS[mode](inputs))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=sorted(BUILDERS))
    ap.add_argument("--check", action="store_true", help="diff in-memory regeneration against the committed JSON")
    ap.add_argument("--out", type=Path, help="write somewhere else (default: the pack path)")
    ap.add_argument("--path", action="append", default=[], metavar="KEY=PATH",
                    help="override an input path (keys: heartgold soulsilver heartgold_hge platinum *_xmap hge_offsets ...)")
    args = ap.parse_args(argv)
    try:
        overrides = dict(p.split("=", 1) for p in args.path)
        text = generate(args.mode, default_inputs(overrides))
    except Skip as exc:
        print(f"SKIP gen4 {args.mode}: {exc}", file=sys.stderr)
        return EXIT_SKIP
    except Fail as exc:
        print(f"FAIL gen4 {args.mode}: {exc}", file=sys.stderr)
        return EXIT_FAIL
    target = args.out or OUT[args.mode]
    if args.check:
        have = target.read_text(encoding="utf-8") if target.is_file() else ""
        if have == text:
            print(f"OK gen4 {args.mode}: {target.relative_to(REPO) if target.is_relative_to(REPO) else target} is current")
            return EXIT_OK
        diff = difflib.unified_diff(have.splitlines(), text.splitlines(), "committed", "regenerated", lineterm="", n=1)
        print("\n".join(list(diff)[:60]), file=sys.stderr)
        print(f"FAIL gen4 {args.mode}: committed pack drifted from its inputs", file=sys.stderr)
        return EXIT_FAIL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
