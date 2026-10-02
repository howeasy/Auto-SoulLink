"""Gen 4 receipt identity: committed dependency bytes, title and ROM, independent of HEAD.

Source HEAD is provenance only. A full module manifest travels with the receipt;
its deterministic, kind-specific digest is the evidence surface. Legacy receipts
with only a subset of dependencies are STALE. No function repins ROMs or rewrites
receipts. ``committed=False`` is an explicit MODEL-test seam, never used live.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "probe": "lua/tests/probe_gen4_hooks.lua",
    "faint": "lua/tests/probe_gen4_battle_faint.lua",
    "route": "lua/tests/gen4_route_play.lua",
    "catch": "lua/tests/probe_gen4_catch.lua",
    "perf": "lua/tests/perf_gen4.lua",
}
PACKS = {"heartgold": "gen4_hgss", "soulsilver": "gen4_hgss", "heartgold_hge": "gen4_hge"}
COMMON = ("tools/gen4_evidence.py", "lua/json_codec.lua", "lua/hook_registry.lua")
PYTHON = {
    "probe": ("tests/live/test_gen4_probe_gates.py", "lua/tests/gen4_route_play.lua", "tools/gen4_routes.py", "tools/gen4_fixtures.py", "tools/gen4_pins.py", "server/adapters/gen4_codec.py"),
    "faint": ("tests/live/test_gen4_battle_faint.py", "tools/gen4_fixtures.py", "tools/gen4_pins.py"),
    "route": ("tools/gen4_routes.py", "tools/gen4_fixtures.py", "tools/gen4_pins.py", "server/adapters/gen4_codec.py"),
    "catch": ("tests/live/test_gen4_catch.py", "tools/gen4_routes.py", "tools/gen4_fixtures.py", "tools/gen4_pins.py", "server/adapters/gen4_codec.py"),
    "perf": ("tests/live/test_gen4_perf.py", "lua/socket.lua", "lua/tests/probe_gen4_hooks.lua", "tools/gen4_fixtures.py", "tools/gen4_pins.py"),
}


class StaleEvidenceError(AssertionError):
    """Present evidence cannot qualify against the requested evidence surface."""


def dependencies(kind: str, title: str, *, repo: Path = REPO) -> tuple[str, ...]:
    if kind not in SCRIPTS or title not in PACKS:
        raise StaleEvidenceError(f"STALE unsupported receipt kind/title: {kind}/{title}")
    paths = {*COMMON, SCRIPTS[kind], *PYTHON[kind], f"data/games/{PACKS[title]}/profile.json"}
    # Preserve the route/catch producer's existing two-pack coverage.
    if kind in {"route", "catch"}:
        paths.update(f"data/games/{pack}/profile.json" for pack in ("gen4_hgss", "gen4_hge"))
    for folder in ("lua/gen4", "lua/nds"):
        paths.update(p.relative_to(repo).as_posix() for p in (repo / folder).rglob("*.lua") if p.is_file())
    return tuple(sorted(paths))


def surface_hash(kind: str, files: dict[str, str]) -> str:
    raw = json.dumps({"schema": "gen4-evidence-v1", "kind": kind, "files": files}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def snapshot(kind: str, title: str, *, repo: Path = REPO, committed: bool = True) -> dict:
    """Freeze a run's dependency set BEFORE execution; refuse uncommitted inputs."""
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() if committed else "MODEL"
    files = {}
    for relative in dependencies(kind, title, repo=repo):
        path = repo / relative
        if not path.is_file():
            raise StaleEvidenceError(f"STALE dependency absent: {relative}")
        current = path.read_bytes()
        if committed:
            try:
                blob = subprocess.check_output(["git", "show", f"{head}:{relative}"], cwd=repo, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as exc:
                raise StaleEvidenceError(f"STALE uncommitted dependency: {relative}") from exc
            if current.replace(b"\r\n", b"\n") != blob.replace(b"\r\n", b"\n"):
                raise StaleEvidenceError(f"STALE uncommitted dependency: {relative}")
        files[relative] = hashlib.sha256(current).hexdigest()
    script, profile = SCRIPTS[kind], f"data/games/{PACKS[title]}/profile.json"
    return {"receipt_kind": kind, "surface_sha256": surface_hash(kind, files), "module_sha256": files,
            "script": script, "script_sha256": files[script], "profile_sha256": files[profile],
            "source_head": head, "title": title}


def bind(payload: dict, expected: dict, *, title: str, rom_sha1: str) -> None:
    """Validate surface, ROM and title; source_head intentionally does not participate.

    The faint Lua producer already echoes the full module map. Its aggregate hash
    can therefore be derived without modifying that independently leased script.
    An explicitly supplied aggregate/kind must agree with the derived identity.
    """
    if payload.get("title") != title:
        raise StaleEvidenceError("STALE title: receipt belongs to another title")
    if not isinstance(payload.get("rom_sha1"), str) or payload["rom_sha1"].lower() != rom_sha1.lower():
        raise StaleEvidenceError("STALE rom_sha1: receipt belongs to another ROM")
    kind = expected["receipt_kind"]
    files = payload.get("module_sha256")
    if not isinstance(files, dict) or files != expected["module_sha256"]:
        changed = sorted(set(expected["module_sha256"]) ^ set(files or {})) if isinstance(files, dict) else []
        if isinstance(files, dict):
            changed += sorted(k for k in set(files) & set(expected["module_sha256"]) if files[k] != expected["module_sha256"][k])
        raise StaleEvidenceError(f"STALE module_sha256: evidence dependency set changed or is incomplete: {changed}")
    derived = surface_hash(kind, files)
    if derived != expected["surface_sha256"] or payload.get("surface_sha256", derived) != derived:
        raise StaleEvidenceError("STALE surface_sha256: evidence surface changed")
    if payload.get("receipt_kind", kind) != kind:
        raise StaleEvidenceError("STALE receipt_kind: wrong producer surface")
    for key in ("script_sha256", "profile_sha256"):
        if payload.get(key) != expected[key]:
            raise StaleEvidenceError(f"STALE {key}: receipt differs from the evidence surface")
    if "script" in payload and payload["script"] != expected["script"]:
        raise StaleEvidenceError("STALE script: wrong receipt producer")


def verify(payload: dict, kind: str, title: str, rom_sha1: str, *, repo: Path = REPO) -> None:
    bind(payload, snapshot(kind, title, repo=repo), title=title, rom_sha1=rom_sha1)
