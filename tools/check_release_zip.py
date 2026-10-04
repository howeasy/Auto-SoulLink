#!/usr/bin/env python3
"""Release-zip hygiene gate (card C4-ZIPCHK, from the C4-ZIP audit of G4 item 5).

    python tools/check_release_zip.py <zip> [--rev HEAD] [--repo DIR] [--no-manifest]

Why it exists: the audit's first export silently reused a stale tree and produced a zip whose
lua/gen3/client.lua was 226 lines shorter than the commit's, and nothing could see it. A zip
that downloads correctly and ships the wrong client is the failure that matters, so this gate
compares the artifact against the commit, member by member.

Checks
  1. BLOB EQUALITY. Every member that tools/make_release.py copies out of the repo must equal
     `git show <rev>:<path>`, CRLF-normalized. Two allowances, both of them make_release's own:
     PLAYER_SETUP.md is generated inline (`_PLAYER_SETUP_MD`), and a launcher script may differ
     only in its SLINK_HOST / SLINK_PORT / SLINK_PLAYER lines (`patch_launcher`, used when
     --host/--port/--player are given).
  2. NO EXTRAS / NOTHING MISSING. With --manifest (the default) the member set must equal the
     manifest's, so a dev-only file fails by name even before the pattern check below. Members
     that are optional by construction (the LuaSocket DLL, the companion patch) may be absent.
  3. NO DEV-ONLY PATHS. tests/, .cache/, patch/build/, *.counter, *.baton, *.born, __pycache__,
     *.sav.
  4. GEN 3 FRLG CLOSURE. The 23 files the shipped lua/slink.lua -> gen3/entry.lua -> run.lua
     route opens for a FireRed/LeafGreen cartridge (traced in the C4-ZIP audit) must all be
     present. The list is also required to be a subset of the manifest, so a manifest edit that
     drops a closure file fails here instead of at boot.

Exit code 0 = PASS, 1 = FAIL. `--no-manifest` keeps checks 1, 3 and 4 and drops the
completeness half of 2 -- it is what the unit test drives, and it is also the right mode for
inspecting a partial or hand-made zip.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── The Gen 3 FRLG load closure (C4-ZIP audit, cx-39772f46) ──────────────────────────────────
# Traced from lua/slink.lua:101/:110/:139 -> lua/gen3/run.lua:15-17/:57 -> lua/gen3/entry.lua's
# L(...) calls (:262-382) and Entry.PACK_FILES (:79-104), plus what those modules require:
# connector -> socket -> the LuaSocket DLL. Keep this the ONE place the closure is written down.
GEN3_FRLG_CLOSURE = (
    "lua/slink.lua",
    "lua/json_codec.lua",
    "lua/gen3/entry.lua",
    "lua/gen3/run.lua",
    "lua/connector.lua",
    "lua/socket.lua",
    "lua/x64/socket-windows-5-4.dll",
    "lua/hud.lua",
    "lua/gen3/reads.lua",
    "lua/gen3/signals.lua",
    "lua/gen3/safety.lua",
    "lua/gen3/writes.lua",
    "lua/gen3/boxes.lua",
    "lua/gen3/native.lua",
    "lua/gen3/client.lua",
    "lua/core/session.lua",
    "lua/core/identity.lua",
    "lua/core/deferred.lua",
    "data/games/gen3_frlg/profile.json",
    "data/games/gen3_frlg/engine_signals.json",
    "data/games/gen3_frlg/write_checkpoint.json",
    "data/games/gen3_frlge/area_map.json",
    "data/games/gen3_frlge/gen3_frlge_locations.lua",
)

DEV_ONLY_PATTERNS = (
    re.compile(r"(^|/)tests/"),
    re.compile(r"(^|/)\.cache(/|$)"),
    re.compile(r"(^|/)patch/build(/|$)"),
    re.compile(r"\.(counter|baton|born)$"),
    re.compile(r"(^|/)__pycache__(/|$)"),
    re.compile(r"\.sav$"),
)

# patch_launcher rewrites exactly these three assignment lines.
_SLINK_ASSIGNMENT = re.compile(rb"^(SLINK_(?:HOST|PORT|PLAYER)\s*=\s*).*$", re.MULTILINE)


def _norm(data: bytes) -> bytes:
    """CRLF-normalize: the zip is built from a checkout whose autocrlf may differ from the blob."""
    return data.replace(b"\r\n", b"\n")


def _mask_launcher(data: bytes) -> bytes:
    return _SLINK_ASSIGNMENT.sub(rb"\1<patched>", _norm(data))


def load_manifest(repo: Path):
    """Import tools/make_release.py for its manifest lists (it has a __main__ guard)."""
    path = repo / "tools" / "make_release.py"
    spec = importlib.util.spec_from_file_location("slink_make_release", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def expected_members(m) -> tuple[dict[str, str], set[str], set[str]]:
    """(member -> repo-relative source, generated members, optional members)."""
    exp: dict[str, str] = {}
    generated = {"PLAYER_SETUP.md"}
    optional: set[str] = set()

    def add(member: str, source: str, *, opt: bool = False) -> None:
        exp[member] = source
        if opt:
            optional.add(member)

    for f in m._LICENSE_FILES:
        add(f, f)
    for f in getattr(m, "_DATA_EXTRA", []):
        add(f, f)
    # Walk make_release's ONE tree table: a lua/<dir> list the checker does not name here makes a
    # real zip fail "member is not in make_release's manifest" (the lua/gen2/* failure at a9ad03d3).
    for sub, files in m._MANIFEST_TREES.items():
        for f in files:
            rel = m._lua_rel(sub, f)
            add(rel, rel)
    for f in m._LUA_X64_OPTIONAL:
        add(f"lua/x64/{f}", f"lua/x64/{f}", opt=True)
    for gen, files in m._DATA_GAME_LUA.items():
        for f in files:
            add(f"data/games/{gen}/{f}", f"data/games/{gen}/{f}")
    # Companion members exist only with --with-patch/--rom; when present they are still blobs.
    add("companion/SLink-RR.ups", m._COMPANION_UPS, opt=True)
    # Gen 2's overlay UPS ship only once that title's overlay row is ADMITTED (make_release.overlay_state),
    # so they are allowed members here, never required ones.
    for f in m._GB_COMPANION_UPS + tuple(m._GEN2_OVERLAY_UPS.values()):
        add(f"companion/{f}", f"patch/dist/{f}", opt=True)
    add("companion/COMPANION_PATCH.md", m._COMPANION_README, opt=True)
    # A bundled pre-patched ROM is a gitignored build artifact: nothing to compare it to.
    optional.add(f"companion/{m._COMPANION_ROM_ARCNAME}")
    return exp, generated, optional


def _blob(repo: Path, rev: str, path: str) -> bytes | None:
    proc = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=repo, capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def _members(zip_path: Path) -> tuple[dict[str, bytes], str | None]:
    """member name (prefix stripped) -> bytes, plus the prefix that was stripped."""
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        prefix = ""
        if names:
            head = names[0].split("/", 1)
            if len(head) == 2 and all(n.startswith(head[0] + "/") for n in names):
                prefix = head[0] + "/"
        return {n[len(prefix):]: zf.read(n) for n in names}, prefix or None


def check_zip(zip_path: Path, rev: str = "HEAD", repo: Path = REPO_ROOT,
              require_manifest: bool = True) -> tuple[list[str], list[str], int]:
    """Returns (failures, notes, member count). Empty failures == PASS."""
    failures: list[str] = []
    notes: list[str] = []
    manifest = load_manifest(repo)
    exp, generated, optional = expected_members(manifest)
    members, prefix = _members(zip_path)

    if prefix:
        notes.append(f"prefix {prefix!r} stripped from every member")
    else:
        notes.append("no single top-level folder in the zip")

    # ── 3. dev-only paths (named before the manifest check so the message is specific) ────────
    for name in sorted(members):
        for pattern in DEV_ONLY_PATTERNS:
            if pattern.search(name):
                failures.append(f"dev-only member present: {name} (matched {pattern.pattern})")
                break

    # ── 1. blob equality ─────────────────────────────────────────────────────────────────────
    for name in sorted(members):
        if name in generated:
            continue
        source = exp.get(name)
        if source is None:
            if name not in optional:
                failures.append(f"member is not in make_release's manifest: {name}")
            continue
        blob = _blob(repo, rev, source)
        if blob is None:
            failures.append(f"{name}: no blob at {rev}:{source}")
            continue
        got = members[name]
        if _norm(got) == _norm(blob):
            continue
        if Path(name).name in manifest._LAUNCHER_SCRIPTS and \
                _mask_launcher(got) == _mask_launcher(blob):
            notes.append(f"{name}: differs only in its SLINK_* lines (built with --host/--port/--player)")
            continue
        failures.append(
            f"{name}: content differs from {rev}:{source} "
            f"(member {len(got)} B, blob {len(blob)} B, "
            f"md5 {hashlib.md5(_norm(got)).hexdigest()[:8]} vs {hashlib.md5(_norm(blob)).hexdigest()[:8]})")

    # ── 2. completeness ──────────────────────────────────────────────────────────────────────
    if require_manifest:
        for name in sorted(set(exp) | generated):
            if name not in members and name not in optional:
                failures.append(f"missing member: {name}")

    # ── 4. the Gen 3 FRLG closure ────────────────────────────────────────────────────────────
    for name in GEN3_FRLG_CLOSURE:
        if name not in members:
            failures.append(f"Gen 3 FRLG closure file missing from the zip: {name}")
        if name not in exp:
            failures.append(f"closure file is not in make_release's manifest: {name} "
                            f"(a manifest edit would drop it from the release)")

    return failures, notes, len(members)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("zip", type=Path, help="the built SLink-player-*.zip")
    ap.add_argument("--rev", default="HEAD", help="git rev the zip was built from (default HEAD)")
    ap.add_argument("--repo", type=Path, default=REPO_ROOT, help="repository to read blobs from")
    ap.add_argument("--no-manifest", action="store_true",
                    help="do not require every manifest member to be present (subset zips)")
    args = ap.parse_args(argv)

    if not args.zip.exists():
        print(f"FAIL: no such zip: {args.zip}", file=sys.stderr)
        return 1

    failures, notes, count = check_zip(args.zip, rev=args.rev, repo=args.repo,
                                       require_manifest=not args.no_manifest)
    print(f"check_release_zip: {args.zip.name}  rev={args.rev}  members={count}  "
          f"mode={'manifest' if not args.no_manifest else 'subset'}")
    for note in notes:
        print(f"  note: {note}")
    for failure in failures:
        print(f"  FAIL: {failure}")
    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        return 1
    print(f"PASS: {count} members, all blobs equal, no dev-only paths, "
          f"{len(GEN3_FRLG_CLOSURE)}/{len(GEN3_FRLG_CLOSURE)} closure files present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
