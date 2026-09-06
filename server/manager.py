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
import copy
import html
import json
import logging
import os
import re
import shutil
import signal
import sys
import uuid
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

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

import aiohttp_jinja2

from server.adapters import variant_label
from server.board import FAMILIES, OPTION_LABELS
from server.manager_board import shell_context, stopped_context, trusted_context
from server.manager_obs import ManagerOBSMixin
from server.obs_arbitration import OBSConfigError
from server.run_proxy import allowed, relay, run_base, upstream
from server import runtime_boundary
from server.http_safety import csrf_protection, local_operator, theme_cache
from server.json_files import atomic_write_json
from server.lua_literals import lua_comment, lua_string
from server.overlay_catalog import build_index_context as _build_stream_index_context
from server.status_payload import empty_status_payload
from server.templating import resolve_theme, setup_templating


def _json_for_script(obj) -> str:
    """json.dumps, safe to embed directly in a <script> element.

    `<`, `>` and `&` become unicode escapes: still valid JSON, still the same string
    once parsed, but no longer able to close the script element they sit inside.
    """
    return (json.dumps(obj)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))

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

# Schema-compatible empty /api/status returned when no run is active.
_EMPTY_STATUS: dict = empty_status_payload()


# ── Registry helpers ────────────────────────────────────────────────────────

class RegistryError(RuntimeError):
    """The registry must be repaired before the Manager can change runs."""


@web.middleware
async def registry_errors(request: web.Request, handler):
    """Surface a damaged registry without replacing it or hiding every run."""
    try:
        return await handler(request)
    except RegistryError as exc:
        message = str(exc) + ". Restore or repair registry.json, then retry."
        if request.path.startswith("/api/"):
            return web.json_response({"ok": False, "error": message}, status=503,
                                     headers={"Cache-Control": "no-store"})
        return web.Response(
            text="<!doctype html><title>Run registry unavailable</title>"
                 "<h1>Run registry unavailable</h1><p>" + html.escape(message) + "</p>",
            status=503, content_type="text/html", headers={"Cache-Control": "no-store"},
        )


@web.middleware
async def finish_mutations(request, handler):
    """Disconnecting a browser cannot strand a spawned child before registry commit."""
    if request.method != "POST":
        return await handler(request)
    task = asyncio.create_task(handler(request))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


@web.middleware
async def api_errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException as error:
        if error.status >= 400 and (request.path.startswith("/api/") or
                                    request.path.startswith("/runs/") and "/api/" in request.path):
            return web.json_response({"ok": False, "error": error.text}, status=error.status)
        raise


def _registry_runs(document) -> list[dict]:
    if not isinstance(document, dict) or not isinstance(document.get("runs"), list):
        raise ValueError("expected an object containing a runs list")
    runs = document["runs"]
    seen = set()
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("run_id"), str) or not run["run_id"]:
            raise ValueError("every run must have a non-empty run_id")
        if run["run_id"] in seen:
            raise ValueError("duplicate run_id")
        seen.add(run["run_id"])
    return runs


def _load_registry() -> list[dict]:
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return _registry_runs(json.load(f))
    except FileNotFoundError:
        return []
    except (ValueError, OSError) as exc:
        message = f"Run registry could not be read; preserved {REGISTRY_PATH}: {exc}"
        log.error(message)
        raise RegistryError(message) from exc


def _save_registry(runs: list[dict]):
    # A file may have become unreadable since the caller's last load (including
    # across a subprocess await). Never replace that evidence with a fresh list.
    _load_registry()
    document = {"runs": runs}
    _registry_runs(document)
    atomic_write_json(REGISTRY_PATH, document)


def _find_run(runs: list[dict], run_id: str) -> dict | None:
    for r in runs:
        if r["run_id"] == run_id:
            return r
    return None


def _run_directory(run_id: str) -> Path:
    """Resolve only a direct registered-run directory, including junction checks."""
    if not isinstance(run_id, str) or not run_id or run_id in (".", "..") or any(char in run_id for char in "/\\\x00"):
        raise web.HTTPBadRequest(text="Invalid run identifier")
    root = Path(MANAGER_DIR).resolve()
    target = (root / run_id).resolve()
    if target.parent != root:
        raise web.HTTPBadRequest(text="Run directory is outside the registry")
    return target


def _locked_run(handler):
    """Keep same-run lifecycle and binding actions ordered across awaits."""
    @wraps(handler)
    async def locked(self, request):
        async with self._run_lock(request.match_info["run_id"]):
            return await handler(self, request)
    return locked


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

SLINK_HOST   = {host}
SLINK_PORT   = {tcp_port}
SLINK_PLAYER = "{player}"

-- Config file lives next to this launcher and caches the project root path.
local _launcher_dir = ((debug.getinfo(1, "S") or {{}}).source or ""):match("@(.+[\\\\/])") or ""
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
        run_name=lua_comment(str(run.get("name") or run["run_id"])),
        player_upper=player.upper(),
        host=lua_string(host),
        tcp_port=run["tcp_port"],
        player=player,
    )


# ── Subprocess management ───────────────────────────────────────────────────

def _is_alive(pid: int | None) -> bool:
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
        "--http-host", "127.0.0.1",
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
    if run.get("explode_mode"):
        cmd.append("--explode-mode")
    if run.get("rival_team_swap"):
        cmd.append("--rival-team-swap")
    if run.get("overworld_presence"):
        cmd.append("--overworld-presence")
    if run.get("native_messages"):
        cmd.append("--native-messages")
    if run.get("native_sounds"):
        cmd.append("--native-sounds")
    # Every registry entry has carried a `verbose` key since the first release, but nothing
    # ever passed it through — a per-run DEBUG log was silently impossible from the manager.
    if run.get("verbose"):
        cmd.append("--verbose")
    # battle_calc / pc_trade_npc default ON — the CLI flags are the inverse (--no-*).
    if not run.get("battle_calc", True):
        cmd.append("--no-battle-calc")
    if not run.get("pc_trade_npc", True):
        cmd.append("--no-pc-trade-npc")
    # Keep the child's stderr. It used to go to DEVNULL, so a run that died on startup — a taken
    # port, a bad ROM path, a stack trace — vanished without trace and the Manager just showed it
    # as stopped.
    _spawn_log = os.path.join(data_dir, "spawn.log")
    try:
        # The child inherits its own handle during process creation.
        _errf = open(_spawn_log, "ab", buffering=0)   # noqa: SIM115
    except OSError:
        _errf = asyncio.subprocess.DEVNULL
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=_errf,
            # Detach from our process group so CTRL-C on the manager doesn't kill runs
            creationflags=0x00000008 if sys.platform == "win32" else 0,  # DETACHED_PROCESS on Windows
        )
    finally:
        if _errf != asyncio.subprocess.DEVNULL:
            _errf.close()
    log.info(f"Spawned run {run['run_id']} (PID {proc.pid}) TCP={run['tcp_port']} HTTP={run['http_port']}")
    return proc.pid


def _kill_run(pid: int, *, process=None):
    """Kill a server.py subprocess by PID."""
    if not _is_alive(pid):
        return
    try:
        if PSUTIL_AVAILABLE:
            p = process if process is not None else psutil.Process(pid)
            p.terminate()
            try:
                p.wait(timeout=5)
            except psutil.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
        else:
            os.kill(pid, signal.SIGTERM if hasattr(signal, "SIGTERM") else signal.CTRL_C_EVENT)
    except Exception as e:
        log.warning(f"Could not kill PID {pid}: {e}")
        raise web.HTTPServiceUnavailable(text="The run process could not be stopped; its registry state was retained") from e


def _stop_owned_run(run):
    """A recycled PID is not evidence that this is still our run process."""
    pid = run.get("pid")
    if not pid or not _is_alive(pid):
        return
    if not PSUTIL_AVAILABLE:
        raise web.HTTPServiceUnavailable(text="Process ownership cannot be checked. Install psutil before stopping this run.")
    try:
        process = psutil.Process(pid)
        command = process.cmdline()
        index = command.index("--data-dir")
        owned_directory = Path(command[index + 1]).resolve() == _run_directory(run["run_id"])
        module = command.index("-m")
        owned_module = command[module + 1] == "server.server"
        if not owned_directory or not owned_module:
            raise ValueError("different process")
    except psutil.NoSuchProcess:
        return
    except (psutil.Error, ValueError, IndexError, OSError) as error:
        raise web.HTTPConflict(text="The recorded PID does not identify this run. No process was stopped.") from error
    _kill_run(pid, process=process)


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
            ctime = datetime.fromtimestamp(entry.stat().st_ctime, tz=UTC).isoformat()
        except OSError:
            ctime = datetime.now(UTC).isoformat()

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
            "explode_mode": bool(rules.get("explode_mode", False)),
            "rival_team_swap": bool(rules.get("rival_team_swap", False)),
            "overworld_presence": bool(rules.get("overworld_presence", False)),
            "native_messages": bool(rules.get("native_messages", False)),
            "native_sounds": bool(rules.get("native_sounds", False)),
            "battle_calc": bool(rules.get("battle_calc", True)),
            "pc_trade_npc": bool(rules.get("pc_trade_npc", True)),
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
    "running":  '<span class="badge running"><span class="badge-dot"></span> running</span>',
    "stopped":  '<span class="badge stopped"><span class="badge-dot"></span> stopped</span>',
    "archived": '<span class="badge archived"><span class="badge-dot"></span> archived</span>',
}


class RunManager(ManagerOBSMixin):
    def __init__(self, bind_host: str, manager_port: int = MANAGER_HTTP_PORT):
        self.bind_host = bind_host
        self.manager_port = manager_port
        self._stream_pin_id: str | None = None  # run_id pinned for stream overlays
        self._registry_lock = asyncio.Lock()
        self._run_locks: dict[str, asyncio.Lock] = {}
        self._saved_cache = {}
        self._registry_cache = None
        self._registry_signature = None
        self.initialize_obs(MANAGER_DIR)

    def _signature(self):
        try:
            stat = os.stat(REGISTRY_PATH)
            return (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise RegistryError(f"Run registry could not be inspected; preserved {REGISTRY_PATH}: {error}") from error

    def _run_lock(self, run_id):
        return self._run_locks.setdefault(run_id, asyncio.Lock())

    async def _mutate_registry(self, update):
        """Reload and merge after awaited work; never publish a stale snapshot."""
        async with self._registry_lock:
            runs = _load_registry()
            result = update(runs)
            _save_registry(runs)
            self._registry_cache = copy.deepcopy(runs)
            self._registry_signature = self._signature()
            return copy.deepcopy(result)

    async def initialize(self):
        # Orphan discovery belongs to startup, not every board/source poll.
        async with self._registry_lock:
            try:
                runs = _load_registry()
                if _reconcile(runs):
                    _save_registry(runs)
                self._registry_cache = copy.deepcopy(runs)
                self._registry_signature = self._signature()
            except RegistryError:
                # Keep HTTP available so the existing 503 repair message can be shown.
                self._registry_cache = None

    async def _start_registered_run(self, run_id):
        run = _find_run(self._get(), run_id)
        if run is None:
            raise web.HTTPNotFound(text="Run not found")
        if run.get("status") == "archived":
            raise web.HTTPBadRequest(text="Archived runs cannot be started")
        if run.get("status") == "running" and _is_alive(run.get("pid")):
            return run
        pid = await _spawn_run(run, self.bind_host, manager_port=self.manager_port)

        def record(runs):
            current = _find_run(runs, run_id)
            if current is None:
                raise web.HTTPNotFound(text="Run was removed while starting")
            if current.get("status") == "archived" or any(current.get(key) != run.get(key) for key in ("tcp_port", "http_port")):
                raise web.HTTPConflict(text="Run configuration changed while starting; the new process was stopped")
            current.update(status="running", pid=pid)
            current.pop("last_error", None)
            return current

        try:
            return await self._mutate_registry(record)
        except Exception:
            await asyncio.to_thread(_kill_run, pid)
            raise

    async def _stop_registered_run(self, run_id, status):
        run = _find_run(self._get(), run_id)
        if run is None:
            raise web.HTTPNotFound(text="Run not found")
        if run.get("pid") and _is_alive(run["pid"]):
            await asyncio.to_thread(_stop_owned_run, run)

        def record(runs):
            current = _find_run(runs, run_id)
            if current is None:
                raise web.HTTPNotFound(text="Run was removed while stopping")
            current.update(status=status, pid=None)
            return current

        return await self._mutate_registry(record)

    def _get(self) -> list[dict]:
        signature = self._signature()
        if self._registry_cache is None or signature != self._registry_signature:
            self._registry_cache = _load_registry()
            self._registry_signature = signature
        runs = copy.deepcopy(self._registry_cache)
        # This is a read projection. Only serialized mutation paths write the registry.
        for run in runs:
            if run.get("status") == "running" and not _is_alive(run.get("pid")):
                run.update(status="stopped", pid=None)
        return runs

    def _active_stream_run(self) -> dict | None:
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

    def _shell(self, request, run=None):
        context = shell_context(run)
        if run:
            context.pop("debug_operations", None)
            context.pop("page_title", None)
        context.update(theme=resolve_theme(request), runs=self._get(),
                       families=FAMILIES, option_labels=OPTION_LABELS,
                       local_setup=local_operator(request))
        return context

    async def handle_index(self, request):
        return aiohttp_jinja2.render_template("manager.html", request, self._shell(request))

    async def handle_application(self, request, run=None):
        from server.application import destination_context
        destination = "tools" if request.path.endswith("/tools") else "broadcast"
        context = self._shell(request, run)
        context.update(destination_context(request, destination, manager=True, run=run))
        return aiohttp_jinja2.render_template(destination + ".html", request, context)

    async def _saved_board(self, run):
        directory = _run_directory(run["run_id"])
        def signature():
            try:
                stat = (directory / "links.json").stat()
                link = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
            except FileNotFoundError:
                link = None
            try:
                modified = directory.stat().st_mtime_ns
            except FileNotFoundError:
                modified = None
            return link, modified
        key = signature()
        cached = self._saved_cache.get(run["run_id"])
        if not cached or cached[0] != key:
            saved = await asyncio.to_thread(self.read_saved_run, run["run_id"])
            self._saved_cache[run["run_id"]] = (key, saved)
        else:
            saved = cached[1]
        return stopped_context(run, saved)

    async def handle_run_board(self, request, run):
        if run.get("status") == "running":
            try:
                async with request.app["proxy_session"].get(
                    upstream(run) + "/_ui/board-context", timeout=aiohttp.ClientTimeout(total=5),
                    allow_redirects=False,
                ) as response:
                    response.raise_for_status()
                    document = await response.json()
                    if document.get("schema") != 1 or document.get("run_id") != run["run_id"]:
                        raise ValueError("Run presentation identity does not match")
                    context = trusted_context(document["context"], run_base(run["run_id"]))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
                context = await self._saved_board(run)
                context["run_unavailable"] = True
        else:
            context = await self._saved_board(run)
        running = context["running"]
        context.update(self._shell(request, run), running=running,
                       view="setup" if request.query.get("view") == "setup" else "board",
                       board_url=str(request.rel_url))
        # A stopped/unreachable run must also disable drawer operations outside
        # the refresh target. board.js reads this fact on every response.
        return aiohttp_jinja2.render_template("board.html", request, context)

    async def handle_run_route(self, request):
        run_id = request.match_info["run_id"]
        base = run_base(run_id)
        run = _find_run(self._get(), run_id)
        if run is None:
            raise web.HTTPNotFound(text="Run not found. No other run has been selected.")
        if "tail" not in request.match_info:
            raise web.HTTPPermanentRedirect(base + "/" + ("?" + request.raw_path.partition("?")[2] if "?" in request.raw_path else ""))
        path = "/" + request.match_info["tail"]
        if not allowed(request.method, path):
            raise web.HTTPNotFound()
        if path == "/":
            return await self.handle_run_board(request, run)
        if path in ("/broadcast", "/tools"):
            return await self.handle_application(request, run)
        if path in ("/launcher/a", "/launcher/b"):
            return self._launcher_response(request, run, path[-1])
        if run.get("status") != "running":
            raise web.HTTPServiceUnavailable(text="This run is stopped. No other run has been selected.")
        return await relay(request, run, path, base=base)

    def _augment_for_template(self, run: dict) -> dict:
        """Registry-only rail labels; live telemetry is fetched for the selected run."""
        result = dict(run)
        result["created_short"] = (run.get("created_at") or "")[:16].replace("T", " ")
        result["safe_name"] = re.sub(r"[^\w-]", "_", run.get("name") or run["run_id"]).strip("_") or run["run_id"]
        result["game_label"] = run.get("game_family", "")
        result["last_event"] = None
        return result

    async def handle_list(self, request: web.Request) -> web.Response:
        return web.json_response({"runs": self._get()})

    async def handle_new(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "Expected an object"}, status=400)
        name = str(body.get("name", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "name is required"}, status=400)
        run_id = "run_" + uuid.uuid4().hex

        def create(runs):
            tcp_port, http_port = _next_ports(runs)
            used_http = {run["http_port"] for run in runs} | {self.manager_port, MANAGER_HTTP_PORT}
            while http_port in used_http:
                http_port += 1
            run = {"run_id": run_id, "name": name, "created_at": datetime.now(UTC).isoformat(),
                   "tcp_port": tcp_port, "http_port": http_port, "status": "stopped", "pid": None,
                   "game_family": str(body.get("game_family", ""))}
            for key in ("species_lock", "gender_lock", "type_lock", "explode_mode", "rival_team_swap",
                        "overworld_presence", "native_messages", "native_sounds", "verbose", "battle_calc", "pc_trade_npc"):
                run[key] = bool(body.get(key, key in ("battle_calc", "pc_trade_npc")))
            _run_directory(run_id).mkdir(parents=True, exist_ok=True)
            _write_run_meta(run)
            runs.append(run)
            return run

        run = await self._mutate_registry(create)
        if body.get("auto_start", True):
            async with self._run_lock(run_id):
                try:
                    run = await self._start_registered_run(run_id)
                except RegistryError:
                    raise
                except Exception as error:
                    log.error("Failed to auto-start run %s: %s", run_id, error)
                    error_message = str(error)
                    def record_error(runs):
                        current = _find_run(runs, run_id)
                        current["last_error"] = error_message
                        return current
                    run = await self._mutate_registry(record_error)
        return web.json_response({"ok": True, "run": run})

    @_locked_run
    async def handle_start(self, request: web.Request) -> web.Response:
        try:
            run = await self._start_registered_run(request.match_info["run_id"])
        except web.HTTPException as error:
            return web.json_response({"ok": False, "error": error.text}, status=error.status)
        except RegistryError:
            raise
        except Exception as error:
            return web.json_response({"ok": False, "error": str(error)}, status=500)
        return web.json_response({"ok": True, "pid": run["pid"]})

    @_locked_run
    async def handle_stop(self, request: web.Request) -> web.Response:
        try:
            await self._stop_registered_run(request.match_info["run_id"], "stopped")
        except web.HTTPException as error:
            return web.json_response({"ok": False, "error": error.text}, status=error.status)
        return web.json_response({"ok": True})

    @_locked_run
    async def handle_archive(self, request: web.Request) -> web.Response:
        try:
            await self._stop_registered_run(request.match_info["run_id"], "archived")
        except web.HTTPException as error:
            return web.json_response({"ok": False, "error": error.text}, status=error.status)
        return web.json_response({"ok": True})

    @_locked_run
    async def handle_delete(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        run = _find_run(self._get(), run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        if run.get("pid") and _is_alive(run["pid"]):
            await asyncio.to_thread(_stop_owned_run, run)
        directory = _run_directory(run_id)
        if directory.exists():
            await asyncio.to_thread(shutil.rmtree, directory)
        def remove(runs):
            runs[:] = [current for current in runs if current["run_id"] != run_id]
        await self._mutate_registry(remove)
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
        return self._launcher_response(request, run, player)

    def _launcher_response(self, request, run, player):
        from urllib.parse import urlsplit
        run_id = run["run_id"]
        # Derive connect host from the Host header (strip port)
        host_header = request.host or "127.0.0.1"
        connect_host = urlsplit("http://" + host_header).hostname or "127.0.0.1"
        content = _build_launcher(run, player, connect_host)
        safe_name = re.sub(r'[^\w-]', '_', run.get("name") or run_id).strip('_') or run_id
        filename = f"slink_{safe_name}_{player}.lua"
        return web.Response(
            text=content,
            content_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @_locked_run
    async def handle_cartridges(self, request: web.Request) -> web.Response:
        """Bind each RBY player to an inspected local cartridge before admission."""
        from pathlib import Path

        from server.gen1_admission import AdmissionError, clean_contract, write_contract

        if not local_operator(request):
            return web.json_response({"ok": False, "error": "Open this page on the server computer using localhost to choose local files."}, status=403)
        run_id = request.match_info["run_id"]
        run = _find_run(self._get(), run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"rom_a", "rom_b"}:
                raise AdmissionError("provide rom_a and rom_b local file paths")
            contract = await asyncio.to_thread(clean_contract, {"a": body["rom_a"], "b": body["rom_b"]})
            write_contract(_run_directory(run_id) / "rom_contract.json", contract)
            def record(runs):
                current = _find_run(runs, run_id)
                if current is None:
                    raise RegistryError("Run disappeared while binding cartridges")
                current["cartridges"] = contract["players"]
                return current
            run = await self._mutate_registry(record)
        except (AdmissionError, ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except OSError as exc:
            return web.json_response({"ok": False, "error": f"cartridge setup could not be saved: {exc}"}, status=500)
        return web.json_response({"ok": True, "cartridges": run["cartridges"]})

    def read_saved_run(self, run_id: str) -> dict:
        """Read-only source for stopped-run summaries; never starts/restores a run."""
        from pathlib import Path
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", run_id):
            raise ValueError("invalid run identifier")
        directory = (Path(MANAGER_DIR) / run_id).resolve()
        if not directory.is_relative_to(Path(MANAGER_DIR).resolve()):
            raise ValueError("run directory leaves manager storage")
        return runtime_boundary.read_saved_run(directory)

    @staticmethod
    def randomization_availability() -> dict:
        return runtime_boundary.randomization_decision()

    # ── Randomized ROM pairs ───────────────────────────────────────────────────

    @_locked_run
    async def handle_randomize(self, request: web.Request) -> web.Response:
        """Keep verified randomized publication closed until its owner publishes it."""
        if not local_operator(request):
            return web.json_response({"ok": False, "error": "Local setup requires localhost on the server computer."}, status=403)
        run_id = request.match_info["run_id"]
        run = _find_run(self._get(), run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        if run.get("cartridges"):
            return web.json_response({"ok": False, "error": "this run is already bound to cartridges; use a new run"}, status=400)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
        jar = str(body.get("jar", "")).strip() or os.environ.get("SLINK_UPR_JAR", "")
        settings = str(body.get("settings", "")).strip()
        rom_a = str(body.get("rom_a", "")).strip()
        rom_b = str(body.get("rom_b", "")).strip()
        missing = [n for n, v in (("jar", jar), ("settings", settings),
                                  ("rom_a", rom_a), ("rom_b", rom_b)) if not v]
        if missing:
            return web.json_response(
                {"ok": False, "error": f"missing: {', '.join(missing)}"}, status=400)

        availability = self.randomization_availability()
        if not availability["available"]:
            return web.json_response({"ok": False, "error": availability["reason"],
                "reason_code": availability["reason_code"], "available": False}, status=409)

        return web.json_response({"ok": False, "available": False,
            "error": "The verified publisher has not been connected.",
            "reason_code": "verified_publisher_unavailable"}, status=409)

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
        from server.application import compatibility_location
        raise web.HTTPFound(compatibility_location(request, '/broadcast?tab=overlays'))
        from server.chrome import build_sidebar_html
        ctx = _build_stream_index_context(request)
        # Manager itself is the host of this page — pass manager_port=None so
        # the Manager nav item doesn't link back to itself.
        ctx["sidebar_html"] = build_sidebar_html("stream", tcp_port=None, manager_port=None)
        return aiohttp_jinja2.render_template("stream_index.html", request, ctx)

    async def handle_stream_overlay_proxy(self, request: web.Request) -> web.Response:
        """GET /stream/{name} (and /stream/{name}/fragment) on the manager —
        proxy through to the active run's overlay so the gallery preview iframe
        and OBS browser sources can target a stable manager URL regardless of
        which run is currently pinned. The fragment variant is required because
        every overlay's `_base.html` polls `fragment_url = /stream/{slug}/fragment`
        via HTMX every 2 s — without the fragment route, the initial paint shows
        but the page never updates.

        If no run is active, return a friendly 404 instead of 500.
        """
        name = request.match_info["name"]
        # The fragment route reuses this handler; aiohttp's match_info exposes
        # the suffix path (empty for the page route, "/fragment" for the poll).
        suffix = "/fragment" if request.match_info.get("suffix") else ""
        active = self._active_stream_run()
        if active is None:
            return web.Response(
                status=404,
                content_type="text/html",
                text=(
                    "<!DOCTYPE html><html><body style=\"font-family:'Pixelify Sans',monospace;"
                    "background:#070910;color:#e6e6e6;padding:2em;text-align:center\">"
                    "<h2 style=\"color:#f8a020\">No active run</h2>"
                    "<p>Pin a running run on <a href=\"/\" style=\"color:#6af\">the manager</a> "
                    "to serve overlays here.</p></body></html>"
                ),
            )
        return await relay(request, active, f"/stream/{name}{suffix}")

    # ── API proxy endpoints (relay to active run) ──────────────────────────────

    async def handle_proxy_status(self, request: web.Request) -> web.Response:
        """GET /api/status — proxy to the active run or return empty status."""
        active = self._active_stream_run()
        if active is None:
            return web.json_response(empty_status_payload())
        url = f"http://127.0.0.1:{active['http_port']}/api/status"
        try:
            async with request.app["proxy_session"].get(
                url, timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                data = await resp.json(content_type=None)
                return web.json_response(data)
        except Exception as e:
            log.debug(f"Proxy /api/status → run {active['run_id']} failed: {e}")
            return web.json_response(empty_status_payload())

    async def handle_run_live(self, request: web.Request) -> web.Response:
        """GET /api/runs/{run_id}/live — same-origin proxy to a specific run's
        /api/status JSON.  Used by the manager detail-pane's compact live-status
        panel so the browser doesn't hit cross-origin CORS against the run's
        port.  Returns 404 if the run is unknown/stopped, 504 on timeout."""
        run_id = request.match_info.get("run_id", "")
        runs = _load_registry()
        run = next((r for r in runs if r["run_id"] == run_id), None)
        if run is None or run.get("status") != "running" or not run.get("http_port"):
            return web.json_response({"error": "run not running"}, status=404)
        url = f"http://127.0.0.1:{run['http_port']}/api/status"
        try:
            async with request.app["proxy_session"].get(
                url, timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                data = await resp.json(content_type=None)
                return web.json_response(data)
        except TimeoutError:
            return web.json_response({"error": "timeout"}, status=504)
        except Exception as e:
            log.debug(f"Proxy /api/runs/{run_id}/live failed: {e}")
            return web.json_response({"error": str(e)}, status=502)

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

def build_app(manager):
    app = web.Application(middlewares=[csrf_protection, theme_cache, registry_errors, api_errors, finish_mutations], handler_args={"handler_cancellation": True})
    setup_templating(app)

    app.router.add_get("/api/obs/status", manager.handle_global_obs_status)
    app.router.add_post("/api/obs/config", manager.handle_global_obs_config)
    app.router.add_get("/api/obs/scenes/{player}", manager.handle_global_obs_scenes)
    app.router.add_post("/api/obs/resume", manager.handle_global_obs_resume)
    app.router.add_post("/api/obs/test", manager.handle_global_obs_test)
    app.router.add_post("/_internal/obs/events", manager.handle_obs_events)

    # Run-management routes
    app.router.add_get("/", manager.handle_index)
    app.router.add_get("/broadcast", manager.handle_application)
    app.router.add_get("/tools", manager.handle_application)
    app.router.add_route("GET", "/runs/{run_id}", manager.handle_run_route)
    app.router.add_route("HEAD", "/runs/{run_id}", manager.handle_run_route)
    app.router.add_get("/runs/{run_id}/{tail:.*}", manager.handle_run_route)
    app.router.add_post("/runs/{run_id}/{tail:.*}", manager.handle_run_route)
    app.router.add_get("/api/runs",                   manager.handle_list)
    app.router.add_post("/api/runs/new",              manager.handle_new)
    app.router.add_post("/api/runs/{run_id}/start",   manager.handle_start)
    app.router.add_post("/api/runs/{run_id}/stop",    manager.handle_stop)
    app.router.add_post("/api/runs/{run_id}/archive", manager.handle_archive)
    app.router.add_post("/api/runs/{run_id}/delete",  manager.handle_delete)
    app.router.add_get("/api/runs/{run_id}/launcher/{player}", manager.handle_launcher)
    app.router.add_post("/api/runs/{run_id}/randomize", manager.handle_randomize)
    app.router.add_post("/api/runs/{run_id}/cartridges", manager.handle_cartridges)
    app.router.add_get("/api/runs/{run_id}/live",     manager.handle_run_live)

    # Stream pin API
    app.router.add_get("/api/stream/pin",  manager.handle_stream_pin_status)
    app.router.add_post("/api/stream/pin", manager.handle_stream_pin)

    # Stream overlay gallery — fixed at manager port 8090. The /stream/{name}
    # proxy relays to the active run's HTTP port so OBS browser sources can
    # bookmark a stable URL even if the pinned run changes.
    app.router.add_get("/stream",                          manager.handle_stream_index)
    app.router.add_get("/stream/",                         manager.handle_stream_index)
    app.router.add_get("/stream/{name}",                   manager.handle_stream_overlay_proxy)
    # Fragment route — the per-run overlays' HTMX bodies poll this every 2 s
    # via `fragment_url = /stream/{slug}/fragment`. Without it the manager
    # returns 404 on every poll, and the overlay never updates after first paint.
    app.router.add_get("/stream/{name}/{suffix:fragment}", manager.handle_stream_overlay_proxy)

    # API proxy — relays to the active (pinned or latest) run
    app.router.add_get("/api/status",         manager.handle_proxy_status)
    app.router.add_post("/api/attempts",      manager.handle_proxy_attempts)

    # Companion ROM patcher — global setup tool, reachable from the manager too.
    # The manager hosts the page itself, so manager_port=None (Manager nav item
    # would dead-link to self) and tcp_port=None (not tied to a run).
    from server.chrome import build_sidebar_html
    from server.patcher import setup_patcher_routes
    setup_patcher_routes(
        app,
        lambda active: build_sidebar_html(active, tcp_port=None, manager_port=None),
    )

    # Lifecycle: shared aiohttp ClientSession for proxy requests
    async def _startup(app: web.Application) -> None:
        await manager.initialize()
        app["proxy_session"] = aiohttp.ClientSession()
        manager._http_session = app["proxy_session"]
        if manager._registry_cache is not None:
            try:
                await manager.obs.import_legacy([Path(MANAGER_DIR).parent / "obs_config.json"])
            except OBSConfigError:
                pass  # preserved storage error is visible on Broadcast


    async def _cleanup(app: web.Application) -> None:
        await manager.obs.close()
        session = app.get("proxy_session")
        if session and not session.closed:
            await session.close()

    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)

    return app


async def main(host: str, port: int):
    manager = RunManager(bind_host=host, manager_port=port)
    app = build_app(manager)
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
