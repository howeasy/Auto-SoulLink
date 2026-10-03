#!/usr/bin/env python3
"""Gen 4 (NDS / melonDS in BizHawk 2.11.1) lane plumbing: a per-run private BizHawk config,
short non-Drive lane paths, and hash-verified ROM/save staging. Unit-level only; it never
launches an emulator.

    python tools/gen4_fixtures.py config   --lane L --initial-time 2010-01-01T12:00:00
    python tools/gen4_fixtures.py stage    --lane L --rom X.nds [--save S.SaveRAM]
    python tools/gen4_fixtures.py check-duo A.SaveRAM B.SaveRAM

Exit codes: 0 ok, 1 FAIL (present but wrong), 2 SKIP (an input is absent, named).
Facts: docs/gen4/research/platform.md 'Configuration'; save layout pk4_and_save.md.
"""

from __future__ import annotations

import argparse
import binascii
import copy
import datetime
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.gen1_playthrough import disable_rewind  # noqa: E402

LOCK = REPO / "data" / "gen4_sources.lock.json"
BIZHAWK_CONFIG = Path("E:/Howard/Bizhawk/config.ini")


def lane_root() -> Path:
    # ponytail: local until the shared tools/slink_space.py work_root('lanes') lands; then delegate to it.
    return Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "lanes" / "g4"


LANE_ROOT = lane_root()
NDS_CORE = "BizHawk.Emulation.Cores.Consoles.Nintendo.NDS.NDS"
MAX_PATH_GUARD = 240  # BizHawk save writes fail silently near MAX_PATH 260

# BizHawk names the battery after its gamedb name for known ROMs, after the ROM basename
# otherwise (the hge build). Keyed by the pinned ROM sha1 (data/gen4_sources.lock.json).
GAMEDB_SAVERAM = {
    "4fcded0e2713dc03929845de631d0932ea2b5a37": "Pokemon - HeartGold Version (USA)",
    "f8dc38ea20c17541a43b58c5e6d18c1732c7e582": "Pokemon - SoulSilver Version (USA)",
    "ce81046eda7d232513069519cb2085349896dec7": "Pokemon - Platinum Version (USA)",
}
# longest sibling BizHawk writes next to a battery (autosave backup)
_SUFFIXES = (".SaveRAM", ".AutoSaveRAM.SaveRAM", ".AutoSaveRAM.SaveRAM.bak")


class RomAbsent(FileNotFoundError):
    """An input is absent: a named SKIP, not a failure."""


class FixtureError(ValueError):
    """An input is present but wrong (or a guard tripped): FAIL."""


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def locked_roms(lock: Path = LOCK) -> dict[str, str]:
    """{sha1: artifact key} for every pinned ROM."""
    arts = json.loads(Path(lock).read_text(encoding="utf-8"))["artifacts"]
    return {a["sha1"]: k for k, a in arts.items() if a.get("role") == "rom"}


def lane_dir(lane: str, root: Path = LANE_ROOT) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", lane):
        raise FixtureError(f"lane name {lane!r} must be 1-24 chars of [A-Za-z0-9_-]")
    return Path(root) / lane


def saveram_name(rom_sha1: str, rom_basename: str | None = None) -> str:
    """The battery file name BizHawk will use for this ROM."""
    if rom_sha1 in GAMEDB_SAVERAM:
        return GAMEDB_SAVERAM[rom_sha1] + ".SaveRAM"
    if not rom_basename:
        raise FixtureError(f"ROM {rom_sha1} is not a gamedb title: rom_basename is required")
    return Path(rom_basename).stem + ".SaveRAM"


def check_saveram_path(saveram_dir: Path | str, name: str) -> None:
    """Refuse when the longest file BizHawk may write there nears MAX_PATH."""
    base = name[: -len(".SaveRAM")]
    worst = max(len(f"{str(saveram_dir).replace(chr(92), '/')}/{base}{s}") for s in _SUFFIXES)
    worst = max(worst, len(f"{saveram_dir}/{name}"))
    if worst >= MAX_PATH_GUARD:
        raise FixtureError(f"SaveRAM path would be {worst} chars (limit {MAX_PATH_GUARD - 1}): "
                           f"use a shorter lane root/name; BizHawk save writes fail silently "
                           f"near MAX_PATH 260")


PACE_1X = {"Unthrottled": False, "ClockThrottle": True, "SpeedPercent": 100, "FrameSkip": 0,
            "AutoMinimizeSkipping": False, "VSyncThrottle": False, "SuperHawkThrottle": False}


def write_nds_run_config(base_config, out_path, *, initial_time: str, lane_saveram_dir,
                         saveram_name_hint: str | None = None, pace_1x: bool = False) -> dict:
    """Write a per-run BizHawk config (JSON) and return it. `base_config` is a path or a dict
    and is never mutated; the NDS Save RAM entry and the melonDS sync settings must already
    exist there (BizHawk's schema changed otherwise): silently not redirecting would let a
    run overwrite the developer's own batteries. `pace_1x` pins real-time pacing for performance
    receipts: the owner's base config inherits Unthrottled=true and FrameSkip=4, which turn a
    frameadvance loop into an unpaced capacity run."""
    try:
        datetime.datetime.strptime(initial_time, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise FixtureError(f"initial_time {initial_time!r} must be ISO YYYY-MM-DDTHH:MM:SS") from exc
    saveram_dir = str(lane_saveram_dir).replace("\\", "/")
    # guard against the longest known name unless the caller knows the exact one
    names = [saveram_name_hint] if saveram_name_hint else [n + ".SaveRAM" for n in GAMEDB_SAVERAM.values()]
    for name in names:
        check_saveram_path(saveram_dir, name)
    if isinstance(base_config, dict):
        cfg = copy.deepcopy(base_config)
    else:
        if Path(base_config).resolve() == Path(out_path).resolve():
            raise FixtureError("out_path is the base config: refusing to overwrite it")
        with open(base_config, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    entries = [e for e in (cfg.get("PathEntries") or {}).get("Paths") or []
               if e.get("Type") == "Save RAM" and e.get("System") == "NDS"]
    if not entries:
        raise FixtureError("no NDS 'Save RAM' entry in PathEntries.Paths of the base config; "
                           "refusing to run without redirecting the battery")
    sync = (cfg.get("CoreSyncSettings") or {}).get(NDS_CORE)
    if not isinstance(sync, dict):
        raise FixtureError(f"base config has no CoreSyncSettings[{NDS_CORE!r}]; run melonDS once "
                           f"in this BizHawk so the settings exist")
    for e in entries:
        e["Path"] = saveram_dir
    # states/screenshots too: the shared ./NDS/State holds the owner's own QuickSave slots
    lane = Path(saveram_dir).parent
    for kind, sub_dir in (("Savestates", "State"), ("Screenshots", "Screenshots")):
        hits = [e for e in cfg["PathEntries"]["Paths"]
                if e.get("Type") == kind and e.get("System") == "NDS"]
        if not hits:
            raise FixtureError(f"no NDS {kind!r} entry in PathEntries.Paths of the base config; "
                               f"refusing to share the developer's {kind} dir")
        for e in hits:
            e["Path"] = (lane / sub_dir).as_posix()
    sync.update(EnableJIT=False, UseRealTime=False, InitialTime=initial_time)
    disable_rewind(cfg)
    for key in ("SoundEnabled", "SoundEnabledNormal", "SoundEnabledRWFF"):
        cfg[key] = False
    cfg["SoundVolume"] = 0
    if pace_1x:
        missing = [k for k in PACE_1X if k not in cfg]
        if missing:  # a renamed key would silently leave the run unpaced
            raise FixtureError(f"base config lacks pacing keys {missing}: cannot pin 1x")
        cfg.update(PACE_1X)
    Path(saveram_dir).mkdir(parents=True, exist_ok=True)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def stage_rom(rom_path, lane_dir_: Path, lock: Path = LOCK) -> Path:
    """Copy a ROM to <lane>/rom/<basename> and verify its hash against the lock. Absent ->
    RomAbsent (names it); present but not a pinned ROM, or a bad copy -> FixtureError."""
    rom = Path(rom_path)
    if not rom.is_file():
        raise RomAbsent(f"ROM absent: {rom}")
    digest = sha1_of(rom)
    pinned = locked_roms(lock)
    if digest not in pinned:
        raise FixtureError(f"ROM {rom} sha1 {digest} is not a pinned Gen 4 ROM "
                           f"({', '.join(sorted(pinned.values()))})")
    dst = Path(lane_dir_) / "rom" / rom.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(rom, dst)
    if sha1_of(dst) != digest:
        raise FixtureError(f"staged ROM copy {dst} does not match the source hash")
    return dst


def stage_save(save_path, lane_dir_: Path, rom_sha1: str, *, rom_basename: str | None = None) -> Path:
    """Copy a battery save into <lane>/SaveRAM under the name BizHawk will look for. The
    source is only read; the copy's hash is verified."""
    src = Path(save_path)
    if not src.is_file():
        raise RomAbsent(f"save absent: {src}")
    name = saveram_name(rom_sha1, rom_basename)
    sdir = Path(lane_dir_) / "SaveRAM"
    check_saveram_path(sdir, name)
    sdir.mkdir(parents=True, exist_ok=True)
    dst = sdir / name
    shutil.copyfile(src, dst)
    if sha1_of(dst) != sha1_of(src):
        raise FixtureError(f"staged save copy {dst} does not match the source hash")
    return dst


# --- minimal HGSS PlayerProfile reader (independent of server/adapters) -----------------------
_MAGIC = 0x20060623
_BANKS = (0x00000, 0x40000)


def _general_block(data: bytes, bank: int) -> tuple[int, bytes] | None:
    """(count, block) of the bank's general block, or None when absent / CRC-bad."""
    for pos in range(0x10, 0x20000, 4):
        o = bank + pos - 0x10
        if o + 0x10 > len(data):
            break
        count, size, magic, slot, crc = struct.unpack_from("<IIIHH", data, o)
        if magic == _MAGIC and slot == 0 and size == pos and o + 0x10 == bank + size:
            if binascii.crc_hqx(data[bank:bank + size - 0x10], 0xFFFF) != crc:
                return None
            return count, data[bank:bank + size]
    return None


def hgss_identity(data: bytes) -> dict:
    """OT name bytes + TID/SID of the newest bank's PlayerProfile (general+0x64)."""
    found = [b for b in (_general_block(data, bank) for bank in _BANKS) if b]
    if not found:
        raise FixtureError("no valid HGSS general block (footer magic/CRC) in either bank")
    # ponytail: serial-number compare; the game's wrap rule for count 0xFFFFFFFF -> 0 is the same
    count, block = found[0]
    for c, b in found[1:]:
        if (c - count) & 0xFFFFFFFF < 0x80000000 and c != count:
            count, block = c, b
    p = 0x64
    (id32,) = struct.unpack_from("<I", block, p + 0x10)
    name = block[p:p + 16]
    for i in range(0, 16, 2):  # stop at the 0xFFFF terminator: buffer tails are not identity
        if name[i:i + 2] == b"\xff\xff":
            name = name[:i]
            break
    return {"name_raw": name.hex(), "tid": id32 & 0xFFFF, "sid": id32 >> 16,
            "count": count}


def check_duo_inputs(save_a, save_b) -> tuple[dict, dict]:
    """Both saves' identities; FixtureError when they share OT + TID + SID (hge<->hge duo
    needs two distinct trainers, plan D15)."""
    ids = []
    for s in (save_a, save_b):
        p = Path(s)
        if not p.is_file():
            raise RomAbsent(f"save absent: {p}")
        ids.append(hgss_identity(p.read_bytes()))
    a, b = ids
    if all(a[k] == b[k] for k in ("name_raw", "tid", "sid")):
        raise FixtureError(f"duo saves share one trainer (TID {a['tid']} SID {a['sid']} "
                           f"OT {a['name_raw']}): the peers would be indistinguishable")
    return a, b


# --- own-PID EmuHawk helpers (never an image-name kill) ---------------------------------------
def our_emuhawk_pids(processes: list[dict], lane_dir_: Path | str) -> list[int]:
    """EmuHawk processes whose command line names a path under THIS lane dir. The lane dir is
    required (an empty one would match everything). `processes` is Get-CimInstance
    Win32_Process rows: [{"ProcessId": int, "CommandLine": str|None}]."""
    base = str(lane_dir_).replace("\\", "/").rstrip("/").lower()
    if not base:
        raise ValueError("lane_dir is required")
    needle = base + "/"
    return [p["ProcessId"] for p in processes
            if needle in (p.get("CommandLine") or "").replace("\\", "/").lower()]


def _emuhawk_processes() -> list[dict]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='EmuHawk.exe'\" | "
         "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=15).stdout.strip()
    data = json.loads(out) if out else []
    return [data] if isinstance(data, dict) else data


def kill_our_emuhawk(lane_dir_: Path | str) -> None:
    """Kill this lane's EmuHawk PIDs only; waits (bounded) for them to exit. Raises
    FixtureError when a PID survives or the process list cannot be read: an orphan could
    still hold the lane's SaveRAM."""
    try:
        for pid in our_emuhawk_pids(_emuhawk_processes(), lane_dir_):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        for _ in range(20):
            left = our_emuhawk_pids(_emuhawk_processes(), lane_dir_)
            if not left:
                return
            time.sleep(0.5)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise FixtureError(f"could not confirm lane EmuHawk exit: {exc}") from exc
    raise FixtureError(f"lane EmuHawk PIDs survived taskkill: {left}")


# --- CLI -------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("config", help="write <lane>/bizhawk.ini")
    c.add_argument("--lane", required=True)
    c.add_argument("--initial-time", required=True, help="ISO, e.g. 2010-01-01T12:00:00")
    c.add_argument("--base", default=str(BIZHAWK_CONFIG))
    c.add_argument("--lane-root", default=str(LANE_ROOT))
    s = sub.add_parser("stage", help="stage ROM (+ save) into the lane")
    s.add_argument("--lane", required=True)
    s.add_argument("--rom", required=True)
    s.add_argument("--save")
    s.add_argument("--lane-root", default=str(LANE_ROOT))
    d = sub.add_parser("check-duo", help="refuse two saves with identical OT/TID/SID")
    d.add_argument("save_a")
    d.add_argument("save_b")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "config":
            lane = lane_dir(a.lane, Path(a.lane_root))
            out = lane / "bizhawk.ini"
            write_nds_run_config(a.base, out, initial_time=a.initial_time,
                                 lane_saveram_dir=lane / "SaveRAM")
            print(f"wrote {out}")
        elif a.cmd == "stage":
            lane = lane_dir(a.lane, Path(a.lane_root))
            rom = stage_rom(a.rom, lane)
            print(f"staged ROM {rom}")
            if a.save:
                print(f"staged save {stage_save(a.save, lane, sha1_of(rom), rom_basename=rom.name)}")
        else:
            x, y = check_duo_inputs(a.save_a, a.save_b)
            print(f"distinct: A tid={x['tid']} sid={x['sid']}  B tid={y['tid']} sid={y['sid']}")
    except RomAbsent as exc:
        print(f"SKIP: {exc}", file=sys.stderr)
        return 2
    except (FixtureError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
