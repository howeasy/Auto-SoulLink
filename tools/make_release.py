#!/usr/bin/env python3
"""
tools/make_release.py — Build a player-facing SLink release package.

Creates dist/SLink-player-<version>.zip containing only the files a
non-hosting player needs to run SLink in BizHawk:
  - lua/   (clients, shared modules, area tables — no tests)
  - data/games/<gen>/*.lua  (area/location tables loaded via _proj_root path)
  - PLAYER_SETUP.md

The server (Python), test suite, code-generation tools, and server-only
JSON data files are intentionally excluded.

Usage:
    python tools/make_release.py
    python tools/make_release.py --version 1.2.3
    python tools/make_release.py --version 1.2.3 --out dist/
    python tools/make_release.py --host 192.168.1.10 --port 54321 --player b

The optional --host/--port/--player flags bake connection settings directly
into the launcher scripts (slink_gen*.lua) as a convenience. The recommended
flow is for players to download a pre-configured launcher from the host's
status page instead.
"""

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

# ── Root of the SLink project ──────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Generators to run before packaging ────────────────────────────────────────
# These produce the area/location .lua files that live in lua/ and data/games/
# and are not committed to the repo.
GENERATORS: list[tuple[str, str]] = [
    ("tools/gen_gen1_area_map.py", "Gen 1 RBY area tables"),
    ("tools/gen_gen2_area_map.py", "Gen 2 Crystal area tables"),
    ("tools/gen_area_map.py",      "Gen 3 FRLGE area tables"),
    ("tools/gen_gen4_area_map.py", "Gen 4 HGSS/Platinum area tables"),
    ("tools/gen_gen5_area_map.py", "Gen 5 BW/BW2 area tables"),
]

# ── File manifests ────────────────────────────────────────────────────────────
# All entries are required; build fails if any are missing.

# lua/ root level
_LUA_ROOT = [
    "slink.lua",
    "slink_gen1.lua",
    "slink_gen2.lua",
    "slink_gen3.lua",
    "slink_gen4.lua",
    "slink_gen5.lua",
    "connector.lua",
    "game_detect.lua",
    "hud.lua",
    "memory_gb.lua",
    "memory_gba.lua",
    "memory_nds.lua",
    "socket.lua",
    # Gen 2 area tables live in lua/ (loaded via _lua_root)
    "gen2_crystal_areas.lua",
    "gen2_crystal_locations.lua",
    # Gen 3/4/5 area tables live in data/games/<gen>/ (loaded via _proj_root)
]

# lua/clients/
_LUA_CLIENTS = [
    "gen1_rby_client.lua",
    "gen2_crystal_client.lua",
    "gen3_frlge_client.lua",
    "gen4_hgsspt_client.lua",
    "gen5_bw_client.lua",
]

# lua/games/
_LUA_GAMES = [
    "gen1_rby.lua",
    "gen2_crystal.lua",
    "gen3_frlge.lua",
    "gen4_hgsspt.lua",
    "gen5_bw.lua",
]

# data/games/<gen>/ — Lua tables loaded at runtime via _proj_root path.
# Only .lua files; JSON data is server-only and never loaded by clients.
_DATA_GAME_LUA: dict[str, list[str]] = {
    "gen1_rby": [
        "gen1_rby_areas.lua",
        "gen1_rby_locations.lua",
    ],
    "gen3_frlge": [
        "gen3_frlge_areas.lua",
        "gen3_frlge_locations.lua",
    ],
    "gen4_hgsspt": [
        "gen4_hgsspt_areas.lua",
        "gen4_hgsspt_areas_pt.lua",
        "gen4_hgsspt_locations.lua",
        "gen4_hgsspt_locations_pt.lua",
    ],
    "gen5_bw": [
        "gen5_bw_areas.lua",
        "gen5_bw_locations.lua",
    ],
}

# lua/x64/ — DLL optional (present on dev machine, excluded from git)
_LUA_X64_OPTIONAL = ["socket-windows-5-4.dll"]

# Launcher scripts (relative to lua/) whose SLINK_* lines get patched
_LAUNCHER_SCRIPTS: set[str] = {
    "slink_gen1.lua",
    "slink_gen2.lua",
    "slink_gen3.lua",
    "slink_gen4.lua",
    "slink_gen5.lua",
}

# ── Player setup guide ────────────────────────────────────────────────────────

_PLAYER_SETUP_MD = """\
# SLink — Player Setup Guide

This package contains everything you need to play a Soul Link Nuzlocke with
SLink in BizHawk. You do **not** need Python — the host handles the server.

---

## What you need

| Requirement | Detail |
|---|---|
| BizHawk 2.9+ | https://github.com/TASEmulators/BizHawk/releases |
| Your ROM | Gen 1 (Red/Blue/Yellow), Gen 2 (Crystal), Gen 3 (FireRed/LeafGreen/Radical Red), Gen 4 (HeartGold/SoulSilver/Platinum), Gen 5 (Black/White/Black 2/White 2) |
| LuaSocket DLL | Already in `lua/x64/`. If missing, see the note below. |
| Launcher script | Download from your host's status page (one click — see Step 1). |

---

## Step 1 — Download your launcher from the host

Your host will share their **status page URL**, which looks like:

```
http://<host-ip>:8080/
```

> **Note:** The URL must use the host's actual LAN/WAN IP address, not
> `127.0.0.1` or `localhost` — those only work on the host's own machine.

On the status page, click the **download button** for your player slot
(Player A or Player B). This gives you a `.lua` file pre-configured with
the correct server address, port, and player ID.

**Save that file into this folder** — the same folder that contains `lua/`
and `data/`. For example:

```
SLink-player-v1.0.0/
├── slink_MyRun_a.lua   ← place the downloaded launcher here
├── lua/
└── data/
```

---

## Step 2 — Load in BizHawk

1. Open BizHawk and load your save file.
2. Open **Tools → Lua Console**.
3. Click **Open Script** and select the launcher `.lua` file you downloaded.
4. The console will print:

   ```
   [SLink] TCP connected to <host>:<port>
   ```

   If it prints `TCP connecting… (non-blocking)` briefly first, that is
   normal — it connects within a second or two.

> **Important:** Load your save file *before* opening the Lua script.
> The script validates save data at startup. If the save isn't loaded yet,
> writes are disabled until validation passes (it retries automatically).

---

## If the LuaSocket DLL is missing

The file `lua/x64/socket-windows-5-4.dll` is required. If it is absent,
copy it from your [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases)
installation:

```
<Archipelago folder>\\data\\lua\\x64\\socket-windows-5-4.dll
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `module 'socket' not found` | `socket-windows-5-4.dll` is missing from `lua/x64/`. See above. |
| `TCP connect failed` / retrying | Server is not running, or IP/port is wrong. Ask host to verify. |
| Connected but nothing happens | Check with host that your player slot (A or B) is not already taken. |
| Writes disabled / validation failed | Load your save file **before** the Lua script. |
| `Wrong save!` on screen | You loaded a different save file than the one registered for your slot. |
| Folder picker appears | Put the launcher `.lua` file inside the extracted `SLink-player-*` folder, next to `lua/`. |

---

## What SLink does automatically

- **Links encounters by area** — your first catch on a route is permanently
  paired with your partner's first catch on the same route.
- **Propagates faints** — when your linked partner faints, so does yours.
- **Dead zones** — if either player fails to catch on a route, both lose
  that slot. Neither linked mon can be used.
- **Memorial box** — dead pairs are moved to a dedicated box after the
  battle ends.

You play normally. SLink enforces the rules for you.
"""

# ── Helpers ────────────────────────────────────────────────────────────────────

def run_generators() -> None:
    """Run area-map generators to ensure data/games/ lua files are up to date."""
    print("Running area-map generators...")
    for rel_script, desc in GENERATORS:
        script = REPO_ROOT / rel_script
        print(f"  {desc}  ({rel_script})")
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(script)],
            cwd=REPO_ROOT,
        )
        if result.returncode != 0:
            print(f"    ERROR: generator failed (exit {result.returncode})", file=sys.stderr)
            sys.exit(1)
    print()


def patch_launcher(content: str, host: str | None, port: int | None, player: str | None) -> str:
    """Rewrite SLINK_HOST / SLINK_PORT / SLINK_PLAYER assignments in a launcher."""
    if host is not None:
        content = re.sub(r'^(SLINK_HOST\s*=\s*)"[^"]*"', rf'\1"{host}"',
                         content, flags=re.MULTILINE)
    if port is not None:
        content = re.sub(r'^(SLINK_PORT\s*=\s*)\d+', rf'\g<1>{port}',
                         content, flags=re.MULTILINE)
    if player is not None:
        content = re.sub(r'^(SLINK_PLAYER\s*=\s*)"[^"]*"', rf'\1"{player}"',
                         content, flags=re.MULTILINE)
    return content


def build_release(
    version: str,
    out_dir: Path,
    host: str | None = None,
    port: int | None = None,
    player: str | None = None,
    skip_generators: bool = False,
) -> Path:
    zip_name = f"SLink-player-{version}.zip"
    zip_path = out_dir / zip_name
    prefix   = f"SLink-player-{version}/"
    do_patch = bool(host or port or player)

    # ── Generate area tables ───────────────────────────────────────────────────
    if not skip_generators:
        run_generators()

    # ── Pre-flight: verify all required files exist ───────────────────────────
    required: list[Path] = (
        [REPO_ROOT / "lua" / f for f in _LUA_ROOT]
        + [REPO_ROOT / "lua" / "clients" / f for f in _LUA_CLIENTS]
        + [REPO_ROOT / "lua" / "games" / f for f in _LUA_GAMES]
        + [
            REPO_ROOT / "data" / "games" / gen / f
            for gen, files in _DATA_GAME_LUA.items()
            for f in files
        ]
    )
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print("ERROR — missing required source files:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        sys.exit(1)

    # ── Optional: DLL ─────────────────────────────────────────────────────────
    dll_warnings: list[str] = []
    dll_files: list[Path] = []
    for fname in _LUA_X64_OPTIONAL:
        p = REPO_ROOT / "lua" / "x64" / fname
        if p.exists():
            dll_files.append(p)
        else:
            dll_warnings.append(
                f"  lua/x64/{fname} — not found; player must obtain it from Archipelago"
            )

    # ── Build zip ─────────────────────────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Building {zip_path} ...")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(prefix + "PLAYER_SETUP.md", _PLAYER_SETUP_MD)

        for fname in _LUA_ROOT:
            src = REPO_ROOT / "lua" / fname
            arc = prefix + f"lua/{fname}"
            if do_patch and fname in _LAUNCHER_SCRIPTS:
                zf.writestr(arc, patch_launcher(src.read_text("utf-8"), host, port, player))
                print(f"  [patched] {arc}")
            else:
                zf.write(src, arc)
                print(f"  [added]   {arc}")

        for fname in _LUA_CLIENTS:
            zf.write(REPO_ROOT / "lua" / "clients" / fname, prefix + f"lua/clients/{fname}")
            print(f"  [added]   {prefix}lua/clients/{fname}")

        for fname in _LUA_GAMES:
            zf.write(REPO_ROOT / "lua" / "games" / fname, prefix + f"lua/games/{fname}")
            print(f"  [added]   {prefix}lua/games/{fname}")

        for p in dll_files:
            zf.write(p, prefix + f"lua/x64/{p.name}")
            print(f"  [added]   {prefix}lua/x64/{p.name}")

        for gen, files in _DATA_GAME_LUA.items():
            for fname in files:
                zf.write(
                    REPO_ROOT / "data" / "games" / gen / fname,
                    prefix + f"data/games/{gen}/{fname}",
                )
                print(f"  [added]   {prefix}data/games/{gen}/{fname}")

    size_kb = zip_path.stat().st_size // 1024
    print(f"\nDone — {zip_path.name}  ({size_kb} KB)")

    if dll_warnings:
        print("\nWarnings (non-fatal):")
        for w in dll_warnings:
            print(w)

    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SLink player release package.")
    parser.add_argument("--version", default="dev", help="Version string (default: dev)")
    parser.add_argument("--out", default=str(REPO_ROOT / "dist"),
                        help="Output directory (default: dist/)")
    parser.add_argument("--host",   metavar="HOST",
                        help="Server IP to bake into launcher scripts")
    parser.add_argument("--port",   metavar="PORT", type=int,
                        help="Server TCP port to bake into launcher scripts")
    parser.add_argument("--player", metavar="PLAYER", choices=["a", "b"],
                        help='Player slot to bake into launcher scripts: "a" or "b"')
    parser.add_argument("--skip-generators", action="store_true",
                        help="Skip running area-map generators")
    args = parser.parse_args()

    build_release(
        version=args.version,
        out_dir=Path(args.out),
        host=args.host,
        port=args.port,
        player=args.player,
        skip_generators=args.skip_generators,
    )


if __name__ == "__main__":
    main()
