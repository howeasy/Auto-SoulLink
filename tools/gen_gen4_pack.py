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
import difflib
import functools
import hashlib
import json
import os
import re
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
    paths: dict[str, Path]  # keys: gen4_pins ROM/asset keys
    lock: Path = LOCK_PATH


def default_inputs(overrides: dict[str, str] | None = None) -> Inputs:
    """Paths from gen4_pins.default_locations(), then SLINK_GEN4_<KEY> env, then CLI overrides."""
    loc = gen4_pins.default_locations()
    paths = {**loc.roms, **loc.assets}
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
    "BattleSystem_GetPartyMon", "ov12_02238A68", "ov12_0223843C",
    "MainMenuApp_Main", "MainMenuApp_Init",
]

# Platinum names differ; roles are mapped here (platinum_bind.md, platform.md).
PT_SYMBOLS = {
    "sSaveDataPtr": "sSaveDataPtr", "gSystem": "gSystem", "overlay_table": "Unk_021BF370",
    "overlay_load": "Overlay_LoadByID", "overlay_unload": "Overlay_UnloadByID",
    "party_add_mon": "Party_AddPokemon", "irq_wait": "OS_WaitIrq", "idle_halt": "OS_Halt",
    "faint_cmd": "BtlCmd_TryFaintMon", "field_system_ptr": "sFieldSystem", "save_data_get": "SaveData_Ptr",
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
    for n in diff:
        for image in sorted({img for _, img in a[n]} | {img for _, img in b[n]}):
            by_image[image] = by_image.get(image, 0) + 1
    return {"hg_symbols": len(a), "ss_symbols": len(b), "common_names": len(common),
            "only_in_hg": len(set(a) - set(b)), "only_in_ss": len(set(b) - set(a)),
            "address_differs": len(diff), "differing_names_by_image": dict(sorted(by_image.items())),
            "differing_objects": sorted({e[3].strip() for e in odd})}


# --------------------------------------------------------------------------------------------
# Static profile facts (SOURCE / FILE, each with its evidence)
# --------------------------------------------------------------------------------------------
PRET_HG = "pret/pokeheartgold@ad7a3afa0cfc144fe6837c410cb95b2727217f54"
HGE_SRC = "hg-engine fork@fc517576498305ecb5f5e1de44681c6e3822361b"
PRET_PT = "pret/pokeplatinum@c248fb3f8cc9934ded800e489567c5c0eeee92eb"


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

PKM_BASE = {"box_size": 0x88, "party_size": 0xEC, "exp_bits": 32, "ability_msb": None, "party_hp_width": 2}
BATTLE_BASE = {"ctx_off": 0x30, "mons_off": 0x2D40, "mon_size": 0xC0, "selected_off": 0x219C, "hp_off": 0x4C,
               "hp_width": 4, "hp_signed": True, "ability_off": 0x27, "ability_width": 1}


_FS = f"{PRET_HG} include/field_system.h"
_ASM_SAVE = "asm/overlay_01_021F6830.s"
# probe_field: FieldSystem / FieldSystemUnkSub0 / save-driver SysTask offsets for the G1 probe and the checkpoint.
# Each value is (offset, evidence class, citation). SOURCE = header/C only; ASM = also corroborated by an asm access.
PROBE_FIELD = {
    "sub": (0x00, "SOURCE", f"{_FS}:113 (FieldSystem.unk0 = FieldSystemUnkSub0*); src/field_system.c:89-96"),
    "save": (0x0C, "ASM", f"{_FS}:116 (saveData); asm/overlay_01_021E6880.s:375 (ldr r0,[r4,#0xc]; bl SaveArray_Party_Get); "
                          "src/overlay_124.c:26"),
    "task": (0x10, "SOURCE", f"{_FS}:117 (taskman); src/task.c:70-72 (FieldSystem_TaskIsRunning = taskman != NULL)"),
    "live": (0x6C, "ASM", f"{_FS}:137 (unk6C, BOOL); asm/overlay_01_021E5900.s:292 (str r0,[r4,#0x6c] = TRUE, read at :356); "
                          "src/field_system.c:95,199-201"),
    "launched_app": (0x04, "SOURCE", f"{_FS}:80 (FieldSystemUnkSub0.unk4 = launched app OverlayManager*, sub-relative); "
                                     "src/field_system.c:117-133 (LaunchApplication, sub_0203DFA4)"),
    "field_app": (0x00, "SOURCE", f"{_FS}:79-80 (FieldSystemUnkSub0.unk0 = field app OverlayManager*, sub-relative); "
                                  "src/field_system.c:97 (non-NULL for the whole field session, sub_0203DF7C)"),
    "paused": (0x08, "SOURCE", f"{_FS}:82 (FieldSystemUnkSub0.isPaused, BOOL, sub-relative); src/field_system.c:96,145,199-201,284-289"),
    "save_driver": (0xD8, "ASM", f"{_FS}:168 (unk_D8 = SysTask*; struct order and the 0xE4 followMon comment corroborate); "
                                 f"{_ASM_SAVE}:91 (add r4,#0xd8; str r0,[r4] after ov01_021F68DC creates the task)"),
    "save_state": (0x01, "ASM", f"{PRET_HG} {_ASM_SAVE}:124-137 (ov01_021F68DC: data[0]=mode, data[1]=state=0), :363-377 (ov01_021F6A9C accepts a "
                                f"request only when ldrb [data,#1]==1), :431-436 (ov01_021F6B10 returns [data,#1]); "
                                "offset is inside SysTask.data, so read data = u32[save_driver_task + save_driver_data_off]"),
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


def probe_field_blocks(build: str) -> dict:
    """profile.probe_field (+ evidence) for hgss, hge (only the header-verified fields) and the shared system facts."""
    fields = {**{k: v[0] for k, v in PROBE_FIELD.items()}, **{k: v[0] for k, v in PROBE_FIELD_EXTRA.items()}}
    evidence = {k: {"class": v[1], "cite": v[2]} for k, v in {**PROBE_FIELD, **PROBE_FIELD_EXTRA}.items()}
    if build == "hge":
        keep = {"save": f"{HGE_SRC} include/pokemon.h:592-596 (FieldSystem.savedata @0xc)",
                "task": f"{HGE_SRC} include/pokemon.h:592-597 (FieldSystem.taskman @0x10)"}
        for k in list(fields):
            if k in keep:
                evidence[k] = {"class": "SOURCE", "cite": keep[k] + "; same offset as pokeheartgold " + evidence[k]["cite"].split(";")[0]}
            else:
                fields[k] = None
                evidence[k] = {"class": "OPEN", "cite": "hg-engine's FieldSystem header declares only savedata/taskman/followMon "
                                                         "(include/pokemon.h:592-615); the vanilla offset is expected (code unhooked) "
                                                         "but not source-verified for hge; G1 measures it"}
    return {
        "probe_field": fields, "probe_field_evidence": evidence, "probe_field_caveats": PROBE_FIELD_CAVEATS,
        "probe_wrong_write_offset": PROBE_WRONG_WRITE[0], "probe_wrong_write_offset_evidence": PROBE_WRONG_WRITE[1],
    }


def hgss_profile(xm: XMap, build: str = "hgss") -> dict:
    return {
        "save_ptr": {"symbol": "sSaveDataPtr", "address": xm.lookup("sSaveDataPtr").address, "width": 4,
                     "evidence": "xMAP; the archived 0x02111880 chain is a different global (rejected by provenance)"},
        "fieldsys_ptr": {"symbol": "sFieldSysPtr", "address": xm.lookup("sFieldSysPtr").address, "width": 4,
                         "save_data_off": 0x0C,
                         "evidence": f"xMAP; {PRET_HG} include/field_system.h (saveData at +0x0C; probe row h agreement)"},
        "system": {"symbol": "gSystem", "vblank_counter_off": 0x2C, "frame_counter_off": 0x30,
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
               "evidence": f"SOURCE {PRET_HG} include/pokemon_storage_system.h:12-28; PC block at SaveData+0xF710 FILE-weak"},
        "box_modified_flag_off": 0x12004,
        "trainer": HGSS_TRAINER,
        "pkm": dict(PKM_BASE),
        "battle": dict(BATTLE_BASE),
        "boxes": 18, "mons_per_box": 30, "memorial_box": 17,
        **probe_field_blocks(build),
    }


def hgss_open() -> dict:
    return {
        "soulsilver_save_offsets": "no owner SS save (D4): party_off / trainer FILE evidence is HeartGold only",
        "array_footer": "SaveArrayFooter (per-array, include/save.h:28-34) location is not pinned; the chunk footer is the signature",
        "slot_spec_runtime_values": "slot offset/size values are read at runtime from saveSlotSpecs; measured HG FILE: general 0xF628, pc @0xF700 size 0x12310",
        "phase_first_event_coverage": "PHYSICAL first/last-event coverage per phase belongs to C1-1/C1-8",
        "battle_offsets_live_read": "battle offsets are SOURCE/asm-literal derived; a live read is a G1/G3 cell",
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
            ["hge replaces 25 PC functions in ov129 (resident from boot): no overlay trigger exists, "
             "caller predicates are PHYSICAL cells"],
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
# Pack builders
# --------------------------------------------------------------------------------------------
def lock_provenance(inputs: Inputs) -> dict:
    return {"path": "data/gen4_sources.lock.json", "sha256": hashlib.sha256(inputs.lock.read_bytes()).hexdigest()}


def title_block(xm: XMap, images: Images, rom: dict, admission: str, label: str) -> dict:
    check_xmap_vs_rom(xm, images, label)
    symbols = {}
    for name in SYMBOL_NAMES:
        symbols[name] = symbol_row(xm, name)
        check_symbol_in_image(symbols[name], name, images, xm)
    ovr = xm.lookup("sOverlayRegions")
    if ovr.size != 3 * 8 * 8:
        raise Fail(f"{label}: sOverlayRegions size {ovr.size:#x} != 3 regions x 8 x 8 bytes")
    sites = vanilla_sites(xm, images)
    return {
        "rom": {k: rom[k] for k in ("sha1", "md5", "header_code")},
        "admission": admission,
        "symbols": symbols, "sites": sites,
        "overlays": images.overlay_table(),
        "overlay_table": {"symbol": "sOverlayRegions", "address": ovr.address, "regions": 3, "per_region": 8,
                          "entry_size": 8, "id_off": 0, "active_off": 4},
        "profile": hgss_profile(xm),
        "phases": phase_table(sites, "hgss"),
        "open": hgss_open(),
    }


SCHEMA_NOTES = {
    "address": "integers; address_hex is the same value for humans",
    "image": "arm9 (static main only) or ov<N>; sites are resolved from this image, never from the address alone",
    "register_hex": "full extent bytes read from the declared image (extent = min(16, symbol size), >=4)",
    "fire_hex": "8 hex digits: int.from_bytes(register_hex[:4],'little') — the callback's unsigned `val` word",
    "hge_status": "hge sites: KEPT = the extent bytes are identical to vanilla in the declared image (not a whole-function claim); "
                  "REPLACED = vanilla entry clobbered, the site is the exported replacement; SOURCE_ONLY = address from hge source",
    "phases": "candidate_sites are the G1 candidates; cap/target_max are the plan's per-phase budgets; armed_set is chosen at G2",
    "mode": "thumb|arm from the xMAP $t/$a mapping symbol (hgss/pt) or the stub/linker evidence recorded in mode_evidence (hge)",
    "collides_with": "other images whose bytes share this address range: residency + byte checks are mandatory",
    "overlays": "ROM overlay table; size is the decompressed byte length, bss is separate",
    "evidence_classes": "SOURCE (pinned source), FILE (pinned artifact bytes), OPEN (null + reason in `open`); nothing here is PHYSICAL",
}


def build_hgss(inputs: Inputs) -> dict:
    lock = load_lock(inputs)
    titles, xms, imgs, roms, maps = {}, {}, {}, {}, {}
    for title in ("heartgold", "soulsilver"):
        roms[title] = verify_rom(inputs, lock, title)
        maps[title] = verify_asset(inputs, lock, title + "_xmap")
    for title in titles_order():
        xms[title] = load_xmap(inputs.paths[title + "_xmap"])
        imgs[title] = load_images(inputs.paths[title])
        titles[title] = title_block(xms[title], imgs[title], roms[title], lock["artifacts"][title]["admission"], title)
    errs = validate_hg_ss(titles["heartgold"], titles["soulsilver"])
    for t in titles_order():
        errs += validate_sites(titles[t]["sites"], imgs[t], t)
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
    ovr = xm.lookup("sOverlayRegions")
    errs = validate_sites(sites, hge_img, "hge")
    if errs:
        raise Fail("; ".join(errs))

    profile = hgss_profile(xm, "hge")
    profile["save"] = save_geometry(
        0x2F, f"SOURCE {HGE_SRC} include/constants/save.h:16-24 (SAVE_PAGE_MAX 0x2F; OFFSET_saveSlotSpecs 0x2F2B4), include/save.h:264-284",
        "OPEN: not read from a live hge SaveData (G2); allocation is hooked (SaveData_New)")
    if profile["save"]["slot_specs_off"] != 0x2F2B4:
        raise Fail("derived hge slot_specs_off disagrees with the source constant OFFSET_saveSlotSpecs 0x2F2B4")
    profile["system"]["evidence"] += f"; {HGE_SRC} include/system.h:8-48 declares the identical struct"
    profile["party_off"] = None
    profile["box_modified_flag_off"] = None
    profile["pc"] = {"array_id": 41, "slot": "pc", "box_base": 0, "box_stride": 0x1000, "mon_stride": 0x88,
                     "cur_box_off": None, "box_modified_flag_off": None,
                     "evidence": f"SOURCE {HGE_SRC} include/constants/save.h:26 (NUM_PC_BOXES 30); PC block at bank+0x10000 size 0x1E4FC FILE"}
    profile["trainer"] = None
    profile["pkm"] = {**PKM_BASE, "exp_bits": 21,
                      "ability_msb": {"word_block": "A", "word_off": 8, "bit": 31, "low_byte_block": "A",
                                      "low_byte_off": 0xD,
                                      "evidence": f"SOURCE {HGE_SRC} include/pokemon.h:226-232 (exp:21, unused:10, abilityMSB:1)"}}
    profile["battle"] = {**BATTLE_BASE, "ability_off": 0x7A, "ability_width": 2}
    profile["boxes"], profile["mons_per_box"], profile["memorial_box"] = 30, 30, 29

    open_ = {
        "party_off": "two plausible party headers on the empty hge save (+0x90, +0xCAB4); a populated-mon decode is a G2 cell. "
                     "Source projection favours +0x90, not unique FILE evidence",
        "box_modified_flag_off": "G2 measures it (mutation/save/reload). SOURCE projection is PCStorage+0x1E004 "
                                 "(0x1000*30+4, include/pokemon_storage_system.h:50-59); not a PHYSICAL receipt",
        "pc.cur_box_off": "source projection 0x1E000 only; G2",
        "trainer": "hge PlayerProfile layout not verified against the hge source/save; reuse of the vanilla offsets is unproven",
        "hge_internal_overlay_loads": (
            "hge's own loads of ov129 (from load_arm9_expansion, entering vanilla HandleLoadOverlay+8) and of the linked "
            "extensions 130/131 (a goto loop inside the replacement HandleLoadOverlay, src/overlay.c:102-215) never re-enter the "
            "vanilla entry. All reach LoadOverlayNoInitAsync(0, id) (loadType 2): sites load_overlay_noinit_async (kept, static "
            "ARM9) and hge_load_arm9_expansion are pinned; full coverage would need all three LoadOverlay* funnels "
            "(over the 4-hook budget with anything else), so residency stays table-polled. PHYSICAL coverage is a C1-1 cell"),
        "fresh_build_association": "cached exports are the pinned file hashes, not proof they came from a fresh build of this ROM "
                                   "(lock pending hge_fresh_build_export_association)",
        "probe_field": "hge declares only FieldSystem.savedata/taskman (include/pokemon.h:592-597); sub/live/launched_app/field_app/"
                       "paused/save_driver/save_state are null until measured (G1) or sourced",
        "pc_swap_redirect": "see sites.pc_swap_by_index_pair.replaces.redirect_evidence",
        "hge_save_geometry_live": "SaveData geometry is source-derived; live read is G2",
        **{k: v for k, v in hgss_open().items() if k in ("phase_first_event_coverage", "battle_offsets_live_read")},
        "battle_hge_effects": "hge faint is replaced in ov130; offsets are shared with vanilla but the active-faint mechanism "
                              "and copy-back are C1-8 cells (battle_pointer.md Open)",
    }
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
        "titles": {"heartgold_hge": {
            "rom": {k: hge_rom[k] for k in ("sha1", "md5", "header_code")},
            "admission": "RECORDED_NOT_ADMITTED",
            "symbols": symbols, "hge_replacements": replacements, "sites": sites,
            "overlays": hge_img.overlay_table(),
            "overlay_table": {"symbol": "sOverlayRegions", "address": ovr.address, "regions": 3, "per_region": 8,
                              "entry_size": 8, "id_off": 0, "active_off": 4,
                              "evidence": "never patched by hge (rom.ld:552 / platform.md); per_region = MAX_ACTIVE_OVERLAYS 8"},
            "profile": profile, "phases": phase_table(sites, "hge"), "open": open_,
        }},
    }


# ---- Platinum ----------------------------------------------------------------------------
def pt_profile() -> dict:
    page_max, body_off = 32, 0x14
    body = page_max * 0x1000
    counters = body_off + body  # globalCounter
    page_info = (counters + 4 + 2 * 4 + 2 + 3) & ~3  # blockCounters[2] u32, blockOffsets[2] u8, align 4
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
                       "signature": 0x20060623,
                       "evidence": f"SOURCE {PRET_PT} include/savedata.h:7-14 (differs from HGSS: extra blockCounter + blockID)"},
        },
        "pc": {"array_id": 37, "box_base": 4, "box_stride": 0xFF0, "mon_stride": 0x88, "cur_box_off": 0,
               "boxes": 18, "mons_per_box": 30, "modified_flag_off": None,
               "evidence": f"SOURCE {PRET_PT} include/pc_boxes.h:18-24 (u32 currentBoxID, then boxMons[18][30], no pad)"},
        "dirty": {"modified_flag_off": None,
                  "full_save_flag": {"base": "SaveData", "off": 0x0C, "width": 4,
                                     "evidence": f"SOURCE {PRET_PT} include/savedata.h:50-57 (fullSaveRequired, src/savedata.c:251-254)"}},
        "pkm": {"box_size": 0x88, "party_size": 0xEC, "exp_bits": 32, "ability_msb": None, "party_hp_width": 2,
                "ball_off_block_d": 0x1B, "block_d_0x1E": "unused in Platinum (HGSS ball/mood)"},
        "boxes": 18, "mons_per_box": 30, "memorial_box": None,
        "battle": None,
        "probe_field": None, "probe_wrong_write_offset": None,
        "system": {"symbol": "gSystem", "vblank_counter_off": None},
        "idle": {"taskman_clause": "NOT valid (+0x10 is a transient FieldTask*)",
                 "app_clause": "FieldSystem_IsRunningApplication = processManager(+0x00)->parent/child"},
    }


def pt_open() -> dict:
    return {
        "probe_field": "bind-only: Platinum FieldSystem probe offsets (processManager parent/child, save driver) are not established",
        "probe_wrong_write_offset": "no Platinum gSystem layout was audited",
        "system.vblank_counter_off": "Platinum gSystem layout not verified here (xMAP gSystem is 0x74 bytes vs HGSS 0x78)",
        "memorial_box": "bind-only: no Platinum Soul Link box policy exists; not guessed",
        "battle": "Platinum battle context offsets are not established; do not derive from HGSS",
        "pc.modified_flag_off": "Platinum has no per-box modified flag; the dirty clause is the whole-save fullSaveRequired flag",
        "process_manager_parent_child_offsets": "offsets of parent/child inside FieldProcessManager not established (platinum_bind.md)",
        "codec": "no populated Platinum save (local save is blank): codec bind cell is OPEN (D3)",
        "sites": "bind-only pack pins no execute sites; symbols and the overlay table only",
        "pt_pack_not_runtime": "a generated profile does not prove every module reusable (platinum_bind.md evidence limits)",
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
