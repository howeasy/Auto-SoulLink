"""
server/manager.py — SLink Run Manager

Standalone aiohttp process (default port 8090) that manages named Soul Link
runs, each running as its own server.py subprocess with an isolated data dir.

Usage:
    python -m server.manager
    python -m server.manager --host 127.0.0.1 --port 8090

Registry:  data/runs/registry.json
Run dirs:  data/runs/<run_id>/links.json
           data/runs/<run_id>/memorial.json
"""

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import aiohttp
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    print("ERROR: aiohttp required. Run: pip install aiohttp", file=sys.stderr)
    sys.exit(1)

from server.stream_overlays import (
    _stream_overlay_page,
    _STREAM_INDEX_HTML,
    _STREAM_PARTY_JS,
    _STREAM_LINKS_JS,
    _STREAM_LINKED_PARTY_JS,
    _STREAM_BOXED_LINKS_JS,
    _STREAM_DEATHS_JS,
    _STREAM_ATTEMPTS_JS,
    _STREAM_AREAS_JS,
    _STREAM_EVENTS_JS,
    _STREAM_BADGES_JS,
    _STREAM_ENCOUNTERS_JS,
    _STREAM_MEMORIAL_JS,
    _STREAM_TICKER_JS,
    _STREAM_FOCUS_JS,
    _STREAM_AREA_ENCOUNTER_JS,
    _STREAM_ENC_TABLE_JS,
    _STREAM_ENEMY_FOCUS_JS,
    _STREAM_ENEMY_TRAINER_JS,
)

log = logging.getLogger("slink.manager")

# ── Paths ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
MANAGER_DIR  = os.path.join(PROJECT_ROOT, "data", "runs")
REGISTRY_PATH = os.path.join(MANAGER_DIR, "registry.json")

# Reserved port for the manager itself
MANAGER_HTTP_PORT = 8090
# Port ranges for spawned runs
TCP_PORT_BASE  = 54321
HTTP_PORT_BASE = 8081   # 8090 reserved for manager


# ── Stream overlay dispatch table ───────────────────────────────────────────
# Single handler covers all overlays.
# Each entry: overlay_path_name → (page title, JS constant, player or None)
_OVERLAY_PAGES: dict[str, tuple[str, str, Optional[str]]] = {
    "party-a":          ("Player A Party",    _STREAM_PARTY_JS,          "a"),
    "party-b":          ("Player B Party",    _STREAM_PARTY_JS,          "b"),
    "links":            ("Linked Pairs",      _STREAM_LINKS_JS,          None),
    "linked-party":     ("Linked Party",      _STREAM_LINKED_PARTY_JS,   None),
    "boxed-links":      ("Boxed Links",       _STREAM_BOXED_LINKS_JS,    None),
    "deaths":           ("Death Counter",     _STREAM_DEATHS_JS,         None),
    "attempts":         ("Attempts Counter",  _STREAM_ATTEMPTS_JS,       None),
    "areas":            ("Area Tracker",      _STREAM_AREAS_JS,          None),
    "events":           ("Event Feed",        _STREAM_EVENTS_JS,         None),
    "badges-a":         ("Gym Badges A",      _STREAM_BADGES_JS,         "a"),
    "badges-b":         ("Gym Badges B",      _STREAM_BADGES_JS,         "b"),
    "encounters":       ("Encounter Tracker", _STREAM_ENCOUNTERS_JS,     None),
    "stream-memorial":  ("Memorial Scroll",   _STREAM_MEMORIAL_JS,       None),
    "ticker":           ("Event Ticker",      _STREAM_TICKER_JS,         None),
    "focus-a":          ("Focus A",           _STREAM_FOCUS_JS,          "a"),
    "focus-b":          ("Focus B",           _STREAM_FOCUS_JS,          "b"),
    "area-encounter":   ("Area Encounter",    _STREAM_AREA_ENCOUNTER_JS, None),
    "enc-table-a":      ("Encounter Table A", _STREAM_ENC_TABLE_JS,      "a"),
    "enc-table-b":      ("Encounter Table B", _STREAM_ENC_TABLE_JS,      "b"),
    "enemy-focus-a":    ("Enemy Focus A",     _STREAM_ENEMY_FOCUS_JS,    "a"),
    "enemy-focus-b":    ("Enemy Focus B",     _STREAM_ENEMY_FOCUS_JS,    "b"),
    "enemy-trainer-a":  ("Enemy Trainer A",   _STREAM_ENEMY_TRAINER_JS,  "a"),
    "enemy-trainer-b":  ("Enemy Trainer B",   _STREAM_ENEMY_TRAINER_JS,  "b"),
}

# Schema-compatible empty /api/status returned when no run is active.
_EMPTY_STATUS: dict = {
    "players": {
        "a": {"connected": False, "status": "disconnected", "area": "", "ball_count": 0,
              "last_event": "", "last_event_ts": "", "party": [], "nuzlocke_active": False,
              "trainer_name": "", "identity_error": None},
        "b": {"connected": False, "status": "disconnected", "area": "", "ball_count": 0,
              "last_event": "", "last_event_ts": "", "party": [], "nuzlocke_active": False,
              "trainer_name": "", "identity_error": None},
    },
    "links": [],
    "area_states": {},
    "pending_captures": {},
    "recent_events": [],
    "killfeed": [],
    "party_details": {"a": [], "b": []},
    "badge_slugs": {"a": [], "b": []},
    "attempts_count": 0,
    "rules": {},
    "rom_type": "",
    "run_name": "",
}


# ── Registry helpers ────────────────────────────────────────────────────────

def _load_registry() -> list[dict]:
    if not os.path.exists(REGISTRY_PATH):
        return []
    try:
        with open(REGISTRY_PATH) as f:
            return json.load(f).get("runs", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_registry(runs: list[dict]):
    os.makedirs(MANAGER_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump({"runs": runs}, f, indent=2)


def _find_run(runs: list[dict], run_id: str) -> Optional[dict]:
    for r in runs:
        if r["run_id"] == run_id:
            return r
    return None


def _next_ports(runs: list[dict]) -> tuple[int, int]:
    """Return the next available (tcp_port, http_port) pair."""
    used_tcp  = {r["tcp_port"]  for r in runs}
    used_http = {r["http_port"] for r in runs}
    tcp = TCP_PORT_BASE
    while tcp in used_tcp:
        tcp += 1
    http = HTTP_PORT_BASE
    while http in used_http or http == MANAGER_HTTP_PORT:
        http += 1
    return tcp, http


# ── Launcher script generation (dynamic — served via HTTP) ──────────────────

_LAUNCHER_TEMPLATE = """\
-- Auto-generated by SLink Run Manager - {run_name}
-- Player {player_upper}: load this script in BizHawk Lua Console
-- This file can be loaded from any location (Desktop, Downloads, etc.)
--
-- Override: set SLINK_ROOT to skip auto-detection entirely:
local SLINK_ROOT = nil  -- e.g. "C:/SLink/"

SLINK_HOST   = "{host}"
SLINK_PORT   = {tcp_port}
SLINK_PLAYER = "{player}"

-- Config file lives next to this launcher and caches the project root path.
local _launcher_dir = ((debug.getinfo(1, "S") or {{}}).source or ""):match("@(.+[\\/])") or ""
local _cfg_path = _launcher_dir .. "slink_path.cfg"

local function _valid_root(path)
    if not path or path == "" or path == "nil" then return false end
    local f = io.open(path .. "lua/slink.lua", "r")
    if f then f:close(); return true end
    return false
end

-- 1. Load cached path from config file
if not SLINK_ROOT then
    local f = io.open(_cfg_path, "r")
    if f then
        local cached = f:read("*l"); f:close()
        if _valid_root(cached) then SLINK_ROOT = cached end
    end
end

-- 2. Auto-detect: search from this script's directory upward for lua/slink.lua
if not SLINK_ROOT then
    local dir = _launcher_dir
    for _, rel in ipairs({{"", "../", "../../", "../../../"}}) do
        if _valid_root(dir .. rel) then SLINK_ROOT = dir .. rel; break end
    end
end

-- 3. Fallback: show modern folder picker (OpenFileDialog trick)
if not SLINK_ROOT then
    luanet.load_assembly("System.Windows.Forms")
    local OFD = luanet.import_type("System.Windows.Forms.OpenFileDialog")
    local Path = luanet.import_type("System.IO.Path")
    local DR = luanet.import_type("System.Windows.Forms.DialogResult")
    local dlg = OFD()
    dlg.Title = "Select the SLink project folder (contains lua/ and server/)"
    dlg.ValidateNames = false
    dlg.CheckFileExists = false
    dlg.CheckPathExists = true
    dlg.FileName = "Select This Folder"
    local result = dlg:ShowDialog()
    if result == DR.OK then
        local path = Path.GetDirectoryName(dlg.FileName)
        if path and tostring(path) ~= "" then
            SLINK_ROOT = tostring(path):gsub("\\\\", "/") .. "/"
        end
    end
end

if not SLINK_ROOT then
    error("[SLink] No project folder selected — cannot start.", 2)
end

-- Save path for next run
local f = io.open(_cfg_path, "w")
if f then f:write(SLINK_ROOT); f:close() end

dofile(SLINK_ROOT .. "lua/slink.lua")
"""


def _build_launcher(run: dict, player: str, host: str) -> str:
    """Return launcher Lua source with the given connect host."""
    return _LAUNCHER_TEMPLATE.format(
        run_name=run.get("name") or run["run_id"],
        player_upper=player.upper(),
        host=host,
        tcp_port=run["tcp_port"],
        player=player,
    )


# ── Subprocess management ───────────────────────────────────────────────────

def _is_alive(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    if PSUTIL_AVAILABLE:
        return psutil.pid_exists(pid)
    # Fallback: send signal 0 (works on Unix; on Windows psutil is strongly preferred)
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


async def _spawn_run(run: dict, host: str, manager_port: int = 0) -> int:
    """Start a server.py subprocess for the given run. Returns the new PID."""
    data_dir = os.path.join(MANAGER_DIR, run["run_id"])
    os.makedirs(data_dir, exist_ok=True)
    cmd = [
        sys.executable, "-m", "server.server",
        "--host",      host,
        "--port",      str(run["tcp_port"]),
        "--http-port", str(run["http_port"]),
        "--data-dir",  data_dir,
        "--run-id",    run["run_id"],
        "--run-name",  run.get("name", ""),
    ]
    if manager_port:
        cmd += ["--manager-port", str(manager_port)]
    if run.get("species_lock"):
        cmd.append("--species-clause")
    if run.get("gender_lock"):
        cmd.append("--gender-clause")
    if run.get("type_lock"):
        cmd.append("--type-clause")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        # Detach from our process group so CTRL-C on the manager doesn't kill runs
        creationflags=0x00000008 if sys.platform == "win32" else 0,  # DETACHED_PROCESS on Windows
    )
    log.info(f"Spawned run {run['run_id']} (PID {proc.pid}) TCP={run['tcp_port']} HTTP={run['http_port']}")
    return proc.pid


def _kill_run(pid: int):
    """Kill a server.py subprocess by PID."""
    if not _is_alive(pid):
        return
    try:
        if PSUTIL_AVAILABLE:
            p = psutil.Process(pid)
            p.terminate()
            try:
                p.wait(timeout=5)
            except psutil.TimeoutExpired:
                p.kill()
        else:
            os.kill(pid, signal.SIGTERM if hasattr(signal, "SIGTERM") else signal.CTRL_C_EVENT)
    except Exception as e:
        log.warning(f"Could not kill PID {pid}: {e}")


# ── Health check — reconcile registry with actual process table ─────────────

def _write_run_meta(run: dict):
    """Persist run name/timestamps to run_meta.json so orphan detection can restore them."""
    meta_path = os.path.join(MANAGER_DIR, run["run_id"], "run_meta.json")
    try:
        with open(meta_path, "w") as f:
            json.dump({
                "name":       run.get("name", ""),
                "created_at": run.get("created_at", ""),
            }, f)
    except OSError as e:
        log.warning(f"Could not write run_meta.json for {run['run_id']}: {e}")


def _adopt_orphans(runs: list[dict]) -> bool:
    """
    Scan data/runs/ for subdirectories not in the registry and add them as
    stopped runs.  Returns True if any runs were adopted.

    Priority for metadata:
      1. run_meta.json  — written by the manager at creation time
      2. links.json     — written by server.py; contains rom_type / trainer_names / rules
      3. directory name / ctime fallback
    """
    if not os.path.isdir(MANAGER_DIR):
        return False
    known_ids = {r["run_id"] for r in runs}
    changed = False
    try:
        entries = sorted(os.scandir(MANAGER_DIR), key=lambda e: e.name)
    except OSError:
        return False

    for entry in entries:
        if not entry.is_dir():
            continue
        run_id = entry.name
        if run_id in known_ids:
            continue

        links_path = os.path.join(entry.path, "links.json")
        meta_path  = os.path.join(entry.path, "run_meta.json")

        # Need at least a links.json to treat this as a real run directory
        if not os.path.exists(links_path):
            continue

        # --- derive creation time ---
        try:
            ctime = datetime.fromtimestamp(entry.stat().st_ctime, tz=timezone.utc).isoformat()
        except OSError:
            ctime = datetime.now(timezone.utc).isoformat()

        # --- derive name ---
        name = run_id  # fallback
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                name   = meta.get("name") or run_id
                ctime  = meta.get("created_at") or ctime
            except (json.JSONDecodeError, OSError):
                pass
        else:
            # Try to build a readable name from links.json
            try:
                with open(links_path) as f:
                    ldata = json.load(f)
                rom = ldata.get("rom_type", "")
                tnames = ldata.get("trainer_names") or {}
                parts = [v for v in [tnames.get("a"), tnames.get("b")] if v]
                if parts:
                    name = " & ".join(parts)
                    if rom:
                        name = f"{name} ({rom})"
                elif rom:
                    name = f"{run_id} ({rom})"
            except (json.JSONDecodeError, OSError):
                pass

        # --- derive rules ---
        rules = {}
        try:
            with open(links_path) as f:
                rules = json.load(f).get("rules", {})
        except (json.JSONDecodeError, OSError):
            pass

        tcp_port, http_port = _next_ports(runs)
        run = {
            "run_id":       run_id,
            "name":         name,
            "created_at":   ctime,
            "tcp_port":     tcp_port,
            "http_port":    http_port,
            "status":       "stopped",
            "pid":          None,
            "species_lock": bool(rules.get("species_lock", False)),
            "gender_lock":  bool(rules.get("gender_lock", False)),
            "type_lock":    bool(rules.get("type_lock", False)),
        }
        runs.append(run)
        known_ids.add(run_id)  # avoid port collision across multiple orphans
        log.info(f"Adopted orphan run directory: {run_id} (name={name!r})")
        changed = True

    return changed


def _reconcile(runs: list[dict]) -> bool:
    """Check live processes; update status for dead ones. Adopt orphan dirs. Returns True if any changed."""
    changed = False
    for run in runs:
        if run["status"] == "running" and not _is_alive(run.get("pid")):
            run["status"] = "stopped"
            run["pid"] = None
            changed = True
    if _adopt_orphans(runs):
        changed = True
    return changed


# ── HTML UI ─────────────────────────────────────────────────────────────────

_STATUS_BADGE = {
    "running":  '<span class="badge running">🟢 running</span>',
    "stopped":  '<span class="badge stopped">⚫ stopped</span>',
    "archived": '<span class="badge archived">📦 archived</span>',
}

def _render_cards(runs: list[dict], host: str) -> str:
    cards = ""
    for run in sorted(runs, key=lambda r: r["created_at"], reverse=True):
        rid    = run["run_id"]
        name   = run.get("name") or rid
        status = run.get("status", "stopped")
        badge  = _STATUS_BADGE.get(status, status)
        created = run.get("created_at", "")[:16].replace("T", " ")
        tcp    = run.get("tcp_port", "?")
        http   = run.get("http_port", "?")
        status_url_js = f"'//' + window.location.hostname + ':{http}'"
        lock_badges = ""
        if run.get("species_lock"):
            lock_badges += '<span class="lock-badge">🧬 Species</span>'
        if run.get("gender_lock"):
            lock_badges += '<span class="lock-badge">⚥ Gender</span>'
        if run.get("type_lock"):
            lock_badges += '<span class="lock-badge">🔮 Type</span>'

        # Read game/rom_type from the run's links.json
        game_badge = ""
        links_path = os.path.join(MANAGER_DIR, rid, "links.json")
        try:
            with open(links_path) as f:
                rom_type = json.load(f).get("rom_type", "")
            if rom_type:
                display_game = rom_type.replace("_", " ").title()
                game_badge = f'<span class="game-badge">🎮 {display_game}</span>'
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            pass

        # Read last event from the run's events.json
        last_event_html = ""
        events_path = os.path.join(MANAGER_DIR, rid, "events.json")
        try:
            with open(events_path) as f:
                evts = json.load(f)
            if evts:
                ev = evts[0]  # most recent (saved newest-first)
                ev_ts   = ev.get("ts", "")[-8:]
                ev_p    = ev.get("player", "").upper()
                ev_text = ev.get("text", "")
                last_event_html = (
                    f'<div class="last-event">'
                    f'<span class="ev-ts">{ev_ts}</span> '
                    f'<b>{ev_p}</b> {ev_text}'
                    f'</div>'
                )
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            pass

        btn_start   = f'<button class="btn start"   onclick="act(\'{rid}\',\'start\')">▶ Start</button>'   if status == "stopped"  else ""
        btn_stop    = f'<button class="btn stop"    onclick="act(\'{rid}\',\'stop\')">■ Stop</button>'     if status == "running"  else ""
        btn_archive = f'<button class="btn archive" onclick="archive_run(\'{rid}\',\'{name.replace(chr(39), chr(92)+chr(39))}\')">📦 Archive</button>' if status != "archived" else ""
        btn_delete  = f'<button class="btn delete"  onclick="del_run(\'{rid}\',\'{name.replace(chr(39), chr(92)+chr(39))}\')">🗑️ Delete</button>'
        btn_view    = f'<a class="btn view" href="#" onclick="window.open({status_url_js});return false" target="_blank">🔗 Status</a>'
        btn_pin     = (f'<button class="btn pin" title="Pin as stream overlay source" '
                       f'onclick="pinRun(\'{rid}\')">📌 Stream</button>') if status == "running" else ""

        launcher_html = ""
        if status != "archived":
            safe_name = re.sub(r'[^\w-]', '_', name).strip('_') or rid
            launcher_html = f'''<div class="launcher-info">📜 BizHawk scripts:
              <a class="btn launcher" href="/api/runs/{rid}/launcher/a" download="slink_{safe_name}_a.lua">⬇ Player A</a>
              <a class="btn launcher" href="/api/runs/{rid}/launcher/b" download="slink_{safe_name}_b.lua">⬇ Player B</a>
            </div>'''

        cards += f"""
        <div class="card {status}">
          <div class="card-header">
            <span class="run-name">{name}</span>
            {badge}
          </div>
          <div class="card-meta">
            <span>Created: {created}</span>
            <span>TCP: {tcp}</span>
            <span>HTTP: {http}</span>
            {game_badge}
            {lock_badges}
          </div>
          {launcher_html}
          {last_event_html}
          <div class="card-actions">
            {btn_start}{btn_stop}{btn_archive}{btn_delete}{btn_view}{btn_pin}
          </div>
        </div>"""
    return cards or '<p style="color:var(--muted)">No runs yet. Create one above.</p>'


def _render_html(runs: list[dict], host: str) -> str:
    cards = _render_cards(runs, host)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Soul Link Run Manager</title>
<style>
  :root {{
    --bg: #1a1a2e; --panel: #16213e; --border: #0f3460;
    --green: #4ade80; --red: #f87171; --yellow: #fbbf24;
    --text: #e2e8f0; --muted: #94a3b8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; padding: 24px; }}
  h1 {{ color: var(--green); margin-bottom: 20px; font-size: 1.6rem; }}
  .new-run {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
              padding: 16px; margin-bottom: 24px; display: flex; gap: 10px; align-items: center; }}
  .new-run input {{ flex: 1; background: #0d1b2a; border: 1px solid var(--border);
                    color: var(--text); padding: 8px 12px; border-radius: 6px; font-size: 0.95rem; }}
  .new-run input:focus {{ outline: 2px solid var(--green); }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }}
  .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
  .card.running {{ border-color: #166534; }}
  .card.archived {{ opacity: 0.6; }}
  .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
  .run-name {{ font-size: 1.05rem; font-weight: 600; }}
  .badge {{ font-size: 0.8rem; padding: 2px 8px; border-radius: 12px; background: #1e293b; }}
  .badge.running {{ color: var(--green); }}
  .badge.stopped {{ color: var(--muted); }}
  .badge.archived {{ color: var(--yellow); }}
  .card-meta {{ font-size: 0.82rem; color: var(--muted); display: flex; gap: 14px; margin-bottom: 12px; }}
  .launcher-info {{ font-size: 0.82rem; color: var(--muted); margin-bottom: 10px; display: flex; gap: 8px; align-items: center; }}
  .btn.launcher {{ background: #1a2744; color: #93c5fd; padding: 4px 10px; font-size: 0.78rem; text-decoration: none; }}
  .card-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .btn {{ padding: 6px 14px; border-radius: 6px; border: none; cursor: pointer;
          font-size: 0.84rem; font-weight: 500; text-decoration: none; display: inline-block; }}
  .btn.start   {{ background: #166534; color: var(--green); }}
  .btn.stop    {{ background: #7f1d1d; color: var(--red); }}
  .btn.archive {{ background: #451a03; color: var(--yellow); }}
  .btn.delete  {{ background: #4a0000; color: #ff6b6b; }}
  .btn.view    {{ background: #1e3a5f; color: #60a5fa; }}
  .btn:hover   {{ filter: brightness(1.2); }}
  .btn.new     {{ background: #166534; color: var(--green); padding: 8px 18px; white-space: nowrap; }}
  .lock-badge  {{ font-size: 0.78rem; padding: 2px 7px; border-radius: 10px; background: #1e3a5f; color: #60a5fa; }}
  .game-badge  {{ font-size: 0.78rem; padding: 2px 7px; border-radius: 10px; background: #1e3f2f; color: #6ee7b7; }}
  .lock-opts   {{ display: flex; gap: 14px; align-items: center; font-size: 0.9rem; color: var(--muted); }}
  .lock-opts label {{ cursor: pointer; display: flex; align-items: center; gap: 4px; }}
  .last-event  {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .last-event .ev-ts {{ color: #555; }}
  .stream-banner {{ background: #0d1b2a; border: 1px solid #1e3a5f; border-radius: 8px; padding: 10px 16px;
                    margin-bottom: 20px; display: flex; align-items: center; gap: 14px; font-size: 0.88rem; color: var(--muted); }}
  .stream-banner a {{ color: #6af; font-weight: 600; text-decoration: none; }}
  .stream-banner a:hover {{ text-decoration: underline; }}
  .stream-banner .stream-port {{ color: #4f4; font-family: monospace; }}
  .btn.pin     {{ background: #2a1a3e; color: #c084fc; border: 1px solid #7c3aed; }}
  .btn.pin.active {{ background: #4c1d95; color: #e9d5ff; }}
  footer {{ margin-top: 32px; color: var(--muted); font-size: 0.78rem; text-align: center; }}
</style>
</head>
<body>
<h1>🔗 Soul Link Run Manager</h1>

<div class="stream-banner">
  🎬 <strong>Stream Overlays</strong> — always on port <span class="stream-port">{MANAGER_HTTP_PORT}</span>:
  &nbsp;<a href="/stream" target="_blank">Open Stream Gallery ↗</a>
  &nbsp;·&nbsp; Point OBS browser sources to <code>http://localhost:{MANAGER_HTTP_PORT}/stream/party-a</code> etc. — port never changes.
  <span id="stream-active" style="margin-left:auto;font-size:0.8rem"></span>
</div>

<div class="new-run">
  <input type="text" id="rname" placeholder="Run name (e.g. Randomizer Run #1)" />
  <div class="lock-opts">
    <label><input type="checkbox" id="species_lock" /> 🧬 Species Clause</label>
    <label><input type="checkbox" id="gender_lock" /> ⚥ Gender Clause</label>
    <label><input type="checkbox" id="type_lock" /> 🔮 Type Clause</label>
  </div>
  <button class="btn new" onclick="newRun()">＋ New Run</button>
</div>

<div class="cards">{cards or '<p style="color:var(--muted)">No runs yet. Create one above.</p>'}</div>

<footer>Auto-refreshes cards every 10 s &nbsp;·&nbsp; Manager on port {MANAGER_HTTP_PORT}</footer>

<script>
async function refreshCards() {{
  try {{
    const res = await fetch('/api/runs/cards');
    if (res.ok) document.querySelector('.cards').innerHTML = await res.text();
  }} catch (_) {{}}
  await refreshStreamPin();
}}
setInterval(refreshCards, 10000);

async function refreshStreamPin() {{
  try {{
    const r = await fetch('/api/stream/pin');
    const j = await r.json();
    const el = document.getElementById('stream-active');
    if (el) el.textContent = j.active_run_name ? `▶ Active: ${{j.active_run_name}}${{j.pinned ? ' 📌' : ''}}` : '';
  }} catch (_) {{}}
}}
refreshStreamPin();

async function pinRun(runId) {{
  const r = await fetch('/api/stream/pin', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{run_id:runId}})}});
  const j = await r.json();
  if (!j.ok) alert(j.error || 'Error');
  else {{ await refreshStreamPin(); location.reload(); }}
}}

async function act(runId, action) {{
  const res = await fetch(`/api/runs/${{runId}}/${{action}}`, {{method:'POST'}});
  const j = await res.json();
  if (!j.ok) alert(j.error || 'Error');
  else location.reload();
}}
async function archive_run(runId, name) {{
  if (!confirm(`Archive run "${{name}}"?\\n\\nThis will stop the server. The run data will be preserved but the run cannot be restarted.`)) return;
  const res = await fetch(`/api/runs/${{runId}}/archive`, {{method:'POST'}});
  const j = await res.json();
  if (!j.ok) alert(j.error || 'Error');
  else location.reload();
}}
async function del_run(runId, name) {{
  if (!confirm(`Delete run "${{name}}"?\\n\\nThis will stop the server and permanently delete all run data (links, memorial, etc).`)) return;
  const res = await fetch(`/api/runs/${{runId}}/delete`, {{method:'POST'}});
  const j = await res.json();
  if (!j.ok) alert(j.error || 'Error');
  else location.reload();
}}
async function newRun() {{
  const name = document.getElementById('rname').value.trim();
  const species_lock = document.getElementById('species_lock').checked;
  const gender_lock = document.getElementById('gender_lock').checked;
  const type_lock = document.getElementById('type_lock').checked;
  if (!name) {{ alert('Enter a run name'); return; }}
  const res = await fetch('/api/runs/new', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{name, species_lock, gender_lock, type_lock}})
  }});
  const j = await res.json();
  if (!j.ok) alert(j.error || 'Error');
  else location.reload();
}}
</script>
</body>
</html>"""


# ── Request handlers ────────────────────────────────────────────────────────

class RunManager:
    def __init__(self, bind_host: str, manager_port: int = MANAGER_HTTP_PORT):
        self.bind_host = bind_host
        self.manager_port = manager_port
        self._stream_pin_id: Optional[str] = None  # run_id pinned for stream overlays

    def _get(self) -> list[dict]:
        runs = _load_registry()
        if _reconcile(runs):
            _save_registry(runs)
        return runs

    def _active_stream_run(self) -> Optional[dict]:
        """Return the run that stream overlays should proxy to.

        Priority:
        1. Explicitly pinned run (if still running and alive).
        2. Most recently started running run (latest created_at).
        Returns None if no run is running.
        """
        runs = self._get()
        running = [r for r in runs if r.get("status") == "running" and _is_alive(r.get("pid"))]
        if not running:
            return None
        if self._stream_pin_id:
            for r in running:
                if r["run_id"] == self._stream_pin_id:
                    return r
            # Pinned run stopped — clear pin, fall through to auto
            self._stream_pin_id = None
        return max(running, key=lambda r: r.get("created_at", ""))

    async def handle_index(self, request: web.Request) -> web.Response:
        runs = self._get()
        html = _render_html(runs, self.bind_host)
        return web.Response(text=html, content_type="text/html")

    async def handle_cards(self, request: web.Request) -> web.Response:
        runs = self._get()
        return web.Response(text=_render_cards(runs, self.bind_host), content_type="text/html")

    async def handle_list(self, request: web.Request) -> web.Response:
        return web.json_response({"runs": self._get()})

    async def handle_new(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        name = str(body.get("name", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "name is required"}, status=400)

        runs = _load_registry()
        run_id = "run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        # Handle collision (unlikely but possible)
        existing_ids = {r["run_id"] for r in runs}
        suffix = 0
        base_id = run_id
        while run_id in existing_ids:
            suffix += 1
            run_id = f"{base_id}_{suffix}"

        tcp_port, http_port = _next_ports(runs)
        run = {
            "run_id":     run_id,
            "name":       name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tcp_port":   tcp_port,
            "http_port":  http_port,
            "status":     "stopped",
            "pid":        None,
            "species_lock": bool(body.get("species_lock", False)),
            "gender_lock":  bool(body.get("gender_lock", False)),
            "type_lock":    bool(body.get("type_lock", False)),
        }
        # Create data directory immediately
        os.makedirs(os.path.join(MANAGER_DIR, run_id), exist_ok=True)
        _write_run_meta(run)
        runs.append(run)
        _save_registry(runs)

        # Auto-start
        try:
            pid = await _spawn_run(run, self.bind_host if self.bind_host != "0.0.0.0" else "0.0.0.0",
                                   manager_port=self.manager_port)
            run["status"] = "running"
            run["pid"] = pid
            _save_registry(runs)
        except Exception as e:
            log.error(f"Failed to auto-start run {run_id}: {e}")

        return web.json_response({"ok": True, "run": run})

    async def handle_start(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        if run["status"] == "archived":
            return web.json_response({"ok": False, "error": "Archived runs cannot be started"}, status=400)
        if run["status"] == "running" and _is_alive(run.get("pid")):
            return web.json_response({"ok": True, "message": "Already running"})
        try:
            pid = await _spawn_run(run, self.bind_host if self.bind_host != "0.0.0.0" else "0.0.0.0",
                                   manager_port=self.manager_port)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        run["status"] = "running"
        run["pid"] = pid
        _save_registry(runs)
        return web.json_response({"ok": True, "pid": pid})

    async def handle_stop(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        pid = run.get("pid")
        if pid:
            _kill_run(pid)
        run["status"] = "stopped"
        run["pid"] = None
        _save_registry(runs)
        return web.json_response({"ok": True})

    async def handle_archive(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        pid = run.get("pid")
        if pid and _is_alive(pid):
            _kill_run(pid)
        run["status"] = "archived"
        run["pid"] = None
        _save_registry(runs)
        return web.json_response({"ok": True})

    async def handle_delete(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        # Stop the process if running
        pid = run.get("pid")
        if pid and _is_alive(pid):
            _kill_run(pid)
        # Remove data directory
        data_dir = os.path.join(MANAGER_DIR, run_id)
        if os.path.isdir(data_dir):
            shutil.rmtree(data_dir, ignore_errors=True)
            log.info(f"Deleted data directory for run {run_id}")
        # Remove from registry
        runs = [r for r in runs if r["run_id"] != run_id]
        _save_registry(runs)
        log.info(f"Deleted run {run_id}")
        return web.json_response({"ok": True})

    async def handle_launcher(self, request: web.Request) -> web.Response:
        """Serve a launcher .lua file with the connect host derived from the request."""
        run_id = request.match_info["run_id"]
        player = request.match_info["player"]
        if player not in ("a", "b"):
            return web.json_response({"ok": False, "error": "player must be 'a' or 'b'"}, status=400)
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        # Derive connect host from the Host header (strip port)
        host_header = request.host or "127.0.0.1"
        connect_host = host_header.split(":")[0] or "127.0.0.1"
        content = _build_launcher(run, player, connect_host)
        safe_name = re.sub(r'[^\w-]', '_', run.get("name") or run_id).strip('_') or run_id
        filename = f"slink_{safe_name}_{player}.lua"
        return web.Response(
            text=content,
            content_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Stream pin ─────────────────────────────────────────────────────────────

    async def handle_stream_pin(self, request: web.Request) -> web.Response:
        """POST /api/stream/pin — pin a run as the stream overlay target."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        run_id = body.get("run_id") or None
        if run_id is not None:
            runs = _load_registry()
            if not any(r["run_id"] == run_id for r in runs):
                return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        self._stream_pin_id = run_id
        log.info(f"Stream overlay pin set to: {run_id!r}")
        active = self._active_stream_run()
        return web.json_response({
            "ok": True,
            "pinned": run_id,
            "active_run_id": active["run_id"] if active else None,
        })

    async def handle_stream_pin_status(self, request: web.Request) -> web.Response:
        """GET /api/stream/pin — return current pin and active run."""
        active = self._active_stream_run()
        return web.json_response({
            "pinned": self._stream_pin_id,
            "active_run_id": active["run_id"] if active else None,
            "active_run_name": active.get("name") if active else None,
        })

    # ── Stream overlay pages (served at fixed manager port 8090) ───────────────

    async def handle_stream_index(self, request: web.Request) -> web.Response:
        return web.Response(text=_STREAM_INDEX_HTML, content_type="text/html")

    async def handle_stream_overlay(self, request: web.Request) -> web.Response:
        """Single handler for all /stream/{name} overlay pages."""
        name = request.match_info["name"]
        entry = _OVERLAY_PAGES.get(name)
        if entry is None:
            raise web.HTTPNotFound()
        title, js, player = entry
        if player:
            js = js.replace("%PLAYER%", player)
        return web.Response(text=_stream_overlay_page(title, js), content_type="text/html")

    # ── API proxy endpoints (relay to active run) ──────────────────────────────

    async def handle_proxy_status(self, request: web.Request) -> web.Response:
        """GET /api/status — proxy to the active run or return empty status."""
        active = self._active_stream_run()
        if active is None:
            return web.json_response(_EMPTY_STATUS)
        url = f"http://127.0.0.1:{active['http_port']}/api/status"
        try:
            async with request.app["proxy_session"].get(
                url, timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                data = await resp.json(content_type=None)
                return web.json_response(data)
        except Exception as e:
            log.debug(f"Proxy /api/status → run {active['run_id']} failed: {e}")
            return web.json_response(_EMPTY_STATUS)

    async def handle_proxy_events(self, request: web.Request) -> web.StreamResponse:
        """GET /api/events — SSE ping stream that triggers overlay re-renders."""
        response = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })
        await response.prepare(request)
        try:
            await response.write(b"retry: 3000\n\n")
            while True:
                await response.write(b"event: ping\ndata:\n\n")
                await asyncio.sleep(1.5)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception as e:
            log.debug(f"SSE /api/events closed: {e}")
        return response

    async def handle_proxy_attempts(self, request: web.Request) -> web.Response:
        """POST /api/attempts — proxy to the active run."""
        active = self._active_stream_run()
        if active is None:
            return web.json_response({"ok": False, "error": "No active run"}, status=503)
        url = f"http://127.0.0.1:{active['http_port']}/api/attempts"
        try:
            body = await request.read()
            async with request.app["proxy_session"].post(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                data = await resp.json(content_type=None)
                return web.json_response(data, status=resp.status)
        except Exception as e:
            log.debug(f"Proxy /api/attempts failed: {e}")
            return web.json_response({"ok": False, "error": "proxy_failed"}, status=503)


# ── Entry point ─────────────────────────────────────────────────────────────

async def main(host: str, port: int):
    manager = RunManager(bind_host=host, manager_port=port)
    app = web.Application()

    # Run-management routes
    app.router.add_get("/",                           manager.handle_index)
    app.router.add_get("/api/runs",                   manager.handle_list)
    app.router.add_get("/api/runs/cards",             manager.handle_cards)
    app.router.add_post("/api/runs/new",              manager.handle_new)
    app.router.add_post("/api/runs/{run_id}/start",   manager.handle_start)
    app.router.add_post("/api/runs/{run_id}/stop",    manager.handle_stop)
    app.router.add_post("/api/runs/{run_id}/archive", manager.handle_archive)
    app.router.add_post("/api/runs/{run_id}/delete",  manager.handle_delete)
    app.router.add_get("/api/runs/{run_id}/launcher/{player}", manager.handle_launcher)

    # Stream pin API
    app.router.add_get("/api/stream/pin",  manager.handle_stream_pin_status)
    app.router.add_post("/api/stream/pin", manager.handle_stream_pin)

    # Stream overlay pages — fixed at manager port 8090
    app.router.add_get("/stream",         manager.handle_stream_index)
    app.router.add_get("/stream/",        manager.handle_stream_index)
    app.router.add_get("/stream/{name}",  manager.handle_stream_overlay)

    # API proxy — relays to the active (pinned or latest) run
    app.router.add_get("/api/status",         manager.handle_proxy_status)
    app.router.add_get("/api/events",         manager.handle_proxy_events)
    app.router.add_post("/api/attempts",      manager.handle_proxy_attempts)

    # Lifecycle: shared aiohttp ClientSession for proxy requests
    async def _startup(app: web.Application) -> None:
        app["proxy_session"] = aiohttp.ClientSession()

    async def _cleanup(app: web.Application) -> None:
        session = app.get("proxy_session")
        if session and not session.closed:
            await session.close()

    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    display = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
    log.info(f"SLink Manager running at http://{display}:{port}/")
    log.info(f"Stream overlays at http://{display}:{port}/stream (fixed port — safe for OBS)")

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="SLink Run Manager")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=MANAGER_HTTP_PORT,
                        help=f"Manager HTTP port (default: {MANAGER_HTTP_PORT})")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
