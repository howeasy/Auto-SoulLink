"""Private filesystem/configuration and PID-scoped primitives for emulator gates.

Preparation is separate from execution. Nothing here discovers a user's newest
save, rewrites their emulator configuration, or kills processes by image name.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any


class SandboxError(ValueError):
    """An input or output cannot be isolated or attributed safely."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def child_path(root: Path, relative: str) -> Path:
    """Reject traversal on either host's path syntax, and reject symlink escapes."""
    normalized = relative.replace("\\", "/")
    if (not normalized or normalized.startswith("/") or PureWindowsPath(relative).drive
            or any(part in ("", ".", "..") for part in normalized.split("/"))):
        raise SandboxError(f"Unsafe relative path: {relative!r}")
    base = root.resolve()
    target = (base / normalized).resolve()
    if target == base or base not in target.parents:
        raise SandboxError(f"Path escapes root: {relative!r}")
    return target


def identity(path: Path) -> dict[str, Any]:
    source = path.resolve(strict=True)
    if not source.is_file():
        raise SandboxError(f"Required regular file missing: {path}")
    data = source.read_bytes()
    return {"path": str(source), "sha256": digest(data), "size_bytes": len(data)}


def verify_identity(item: dict[str, Any]) -> None:
    actual = identity(Path(item["path"]))
    if actual["sha256"] != item["sha256"] or actual["size_bytes"] != item["size_bytes"]:
        raise SandboxError(f"Immutable input changed: {item['path']}")


def copy_verified(source: Path, destination: Path) -> dict[str, Any]:
    original = identity(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(Path(original["path"]).read_bytes())
    copied = identity(destination)
    verify_identity(original)
    if copied["sha256"] != original["sha256"]:
        raise SandboxError(f"Source changed during copy: {source}")
    return {"original": original, "copy": copied}


def create_instance_root(output_root: Path, run_id: str, player: str, protected_roots: list[Path]) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id):
        raise SandboxError("run_id must be 1-64 ASCII letters/digits/underscores/hyphens")
    if player not in ("a", "b"):
        raise SandboxError("player must be a or b")
    output = output_root.resolve()
    for protected in protected_roots:
        resolved = protected.resolve()
        if output == resolved or resolved in output.parents:
            raise SandboxError(f"Output root is inside protected input root: {resolved}")
    output.mkdir(parents=True, exist_ok=True)
    root = child_path(output, f"{run_id}_{player}")
    root.mkdir(exist_ok=False)  # A previous run's files can never supply a verdict.
    return root


def isolated_config(base: dict[str, Any], root: Path, core: str) -> dict[str, Any]:
    """Retain emulator settings but remove saved tools/loads and rebase every path."""
    if not isinstance(base, dict):
        raise SandboxError("Base emulator config must be a JSON object")
    cfg = copy.deepcopy(base)
    paths = cfg.get("PathEntries", {}).get("Paths")
    if not isinstance(paths, list) or not paths:
        raise SandboxError("Config has no supported PathEntries.Paths array")
    required = {"Base", "ROM", "Save RAM", "Savestates", "Screenshots", "Cheats"}
    found = {row.get("Type") for row in paths if isinstance(row, dict) and row.get("System") == "GBA"}
    if not required <= found:
        raise SandboxError(f"Missing GBA path entries: {sorted(required - found)}")

    # These maps may contain saved script sessions, external tool activation, or
    # captured file paths. A gate starts none of the user's saved tools.
    for key in ("CommonToolSettings", "CustomToolSettings", "TrustedExtTools",
                "ToolDialogSettings", "FirmwareUserSpecifications"):
        cfg[key] = {}
    cfg["Cheats"] = {"DisableOnLoad": True, "LoadFileByGame": False, "AutoSaveOnClose": False}

    def scrub(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                scrub(item)
        elif isinstance(value, dict):
            for key in list(value):
                item, lower = value[key], key.lower()
                if lower.startswith("recent"):
                    value[key] = ({"recentlist": [], "MAX_RECENT_FILES": 0,
                                   "AutoLoad": False, "Frozen": True} if isinstance(item, dict) else [])
                elif "autoload" in lower or lower.startswith("loadlast"):
                    value[key] = False
                elif ((lower.startswith("last") and ("path" in lower or "file" in lower))
                      or (isinstance(item, str) and re.search(r"\.(lua|luases|wch|cht|bk2|tasproj)$", item, re.I))):
                    value[key] = ""
                else:
                    scrub(item)

    scrub(cfg)
    directories = {"Base": "gba", "ROM": "rom", "Save RAM": "gba/saveram",
                   "Savestates": "gba/state", "Screenshots": "gba/screenshots", "Cheats": "gba/cheats"}
    for index, entry in enumerate(paths):
        if not isinstance(entry, dict) or not isinstance(entry.get("Type"), str):
            raise SandboxError("Malformed config path entry")
        relative = directories.get(entry["Type"]) if entry.get("System") == "GBA" else None
        private = child_path(root, relative or f"other_paths/p{index}")
        private.mkdir(parents=True, exist_ok=True)
        entry["Path"] = private.as_posix()
    cfg["PreferredCores"] = dict(cfg.get("PreferredCores") or {}, GBA=core)
    cfg["Rewind"] = dict(cfg.get("Rewind") or {}, Enabled=False)
    cfg.update({"AutoLoadLastSaveSlot": False, "AutosaveSaveRAM": False,
                "SingleInstanceMode": False,
                "UseRecentForRoms": False, "LastRomPath": child_path(root, "rom").as_posix(),
                "SoundEnabled": False, "SoundEnabledNormal": False, "SoundEnabledRWFF": False,
                "SoundVolume": 0, "RunInBackground": True, "AcceptBackgroundInput": False,
                "AcceptBackgroundInputControllerOnly": False,
                "SpeedPercent": 100, "SpeedPercentAlternate": 100, "FrameSkip": 0,
                "Unthrottled": False, "TurboSeek": False, "ClockThrottle": True,
                "SaveWindowPosition": False, "MainWindowMaximized": False,
                "MainWindowPosition": "-32000, -32000"})
    return cfg


def database_saveram_name(rom: bytes, database_dir: Path, staged_stem: str = "rrgate") -> dict[str, Any]:
    """Use explicit database files; unknown ROMs use a simple, unchanged stem."""
    files = sorted(database_dir.resolve(strict=True).glob("*.txt"))
    if not files:
        raise SandboxError("Explicit game database directory contains no text databases")
    sha1 = hashlib.sha1(rom).hexdigest().upper()
    matches = set()
    inputs = []
    for path in files:
        inputs.append(identity(path))
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            fields = line.split("\t")
            if fields and fields[0].upper() == sha1:
                if len(fields) < 4 or fields[3] != "GBA":
                    raise SandboxError("ROM database match has an unsupported record shape/system")
                matches.add(fields[2])
    if len(matches) > 1:
        raise SandboxError("Conflicting game database names for the selected ROM")
    name = next(iter(matches)) if matches else staged_stem
    if not name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith((".", " ")):
        raise SandboxError("Game name needs unverified filesystem normalization; use isolated discovery first")
    return {"game_name": name, "filename": name + ".SaveRAM", "in_database": bool(matches),
            "rom_sha1": sha1, "database_inputs": inputs,
            "method": "exact_sha1_database" if matches else "unchanged_ascii_staged_stem"}


def hidden_process_kwargs(platform: str | None = None) -> dict[str, Any]:
    if (platform or os.name) != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return {"startupinfo": startup, "creationflags": subprocess.CREATE_NO_WINDOW}


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created: float


def capture_owned_tree(root: ProcessIdentity, process_api=None) -> list[ProcessIdentity]:
    """Capture only descendants of the exact process this runner started."""
    if process_api is None:
        import psutil as process_api
    try:
        process = process_api.Process(root.pid)
        if process.create_time() != root.created:
            raise SandboxError("Emulator PID was reused; refusing process-tree traversal")
        children = process.children(recursive=True)
        return [ProcessIdentity(child.pid, child.create_time()) for child in children] + [root]
    except process_api.NoSuchProcess:
        return []


def terminate_owned(owned: list[ProcessIdentity], process_api=None, timeout: float = 5) -> list[int]:
    """Terminate saved exact PID/create-time pairs only; never enumerate by name."""
    if process_api is None:
        import psutil as process_api
    stopped = []
    for item in owned:
        try:
            process = process_api.Process(item.pid)
            if process.create_time() != item.created:
                continue
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except process_api.TimeoutExpired:
                fresh = process_api.Process(item.pid)
                if fresh.create_time() != item.created:
                    continue
                fresh.kill()
                fresh.wait(timeout=timeout)
            stopped.append(item.pid)
        except process_api.NoSuchProcess:
            continue
    return stopped
