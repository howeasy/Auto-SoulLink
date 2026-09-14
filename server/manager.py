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
import hashlib
import html
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import sys
from datetime import UTC, datetime
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

from server import runtime_boundary
from server.adapters import variant_label
from server.http_safety import csrf_protection, theme_cache
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


_RUN_ID = re.compile(r"run_[0-9A-Za-z_]{1,64}")


def _resume_refusal(predecessor: dict | None) -> list[str] | None:
    """Registry-level reasons a predecessor cannot be resumed right now (the journal audit is separate)."""
    if predecessor is None:
        return ["predecessor run is not in the registry"]
    if predecessor.get("status") in ("starting", "running"):
        return ["predecessor run is starting or running in the registry; stop it first"]
    if predecessor.get("resumed_by"):
        return ["predecessor already resumed"]
    if predecessor.get("recovered_by"):
        return ["predecessor already recovered"]
    if _recovering_live(predecessor):
        return ["predecessor is being recovered; wait for it to finish or retry"]
    return None


def _refusal_body(predecessor: dict | None, reasons: list[str], details: dict | None = None) -> dict:
    """409 body: fixed reason strings; every interpolated fact lives in details."""
    details = dict(details or {})
    if predecessor and predecessor.get("resumed_by"):
        details["resumed_by"] = predecessor["resumed_by"]
    return {"ok": False, "error": "predecessor cannot be resumed", "reasons": reasons, "details": details}


# ── R5b: paired checkpoints (Manager side) ───────────────────────────────────────────────────

CHECKPOINT_RULE_KEYS = ("species_lock", "gender_lock", "type_lock", "explode_mode", "rival_team_swap",
                        "native_sounds", "pc_trade_npc")


def resume_record_from_checkpoint(run_id: str, manifest: dict, checkpoint) -> dict:
    """The ONE mapping from an R5b checkpoint to the resume contract `validate_resume` accepts.

    F5 (R5b-3b): only the legacy save_witness kind is recoverable here. A caller MUST refuse a
    manifest naming any other witness_kind (`_pretrade_checkpoint_error` below) before ever
    calling this — there is deliberately no native-pretrade mapping to fall back to.
    """
    required = {}
    for player in ("a", "b"):
        witness = manifest["players"][player]["witness"]
        if witness.get("witness_kind", "save_witness") != "save_witness":
            raise ValueError("recovery from a pretrade checkpoint is not enabled yet")
        required[player] = {"digest": witness["digest"], "projection": witness["projection"],
            "witness_index": witness["index"], "operation_id": witness["operation_id"]}
    return {"from_run": run_id, "required": required,
        "rules": json.loads(checkpoint.rules_bytes().decode("utf-8")),
        "contract_hash": manifest["contract_fingerprint"],
        "identities": json.loads(checkpoint.identity_bytes().decode("utf-8"))}


def _pretrade_checkpoint_error(manifest: dict) -> str | None:
    """F5: refuse before loading anything else if either player's archived witness is not the
    legacy save_witness kind (native-pretrade recovery is not enabled yet)."""
    for player in ("a", "b"):
        witness = manifest["players"][player]["witness"]
        if witness.get("witness_kind", "save_witness") != "save_witness":
            return "recovery from a pretrade checkpoint is not enabled yet"
    return None


def _checkpoint_binding_error(manifest: dict, entry: dict, run_spec: dict, run_id: str) -> str | None:
    """F2: the archive a recovery is about to trust must be the SAME one this run's own journal
    confirmed (not merely some checkpoint reachable from the store's current CURRENT pointer),
    minted for THIS run and its cartridge contract, under source files that have not drifted
    since. Four independent checks, each with its own message so a caller can tell which fired:
      1. manifest hash == the journal's own confirmed manifest_sha256 (belt-and-suspenders over
         PairedCheckpointStore.load's own chain verification).
      2. provenance identity == this run (registry_run_id) and its journal (run_id from the
         prepared-run spec) — a checkpoint minted for a different run must never bind here.
      3. contract_fingerprint == digest(this run's own contract) — fails fast; `create_runtime`
         would refuse the same mismatch later via `resume['contract_hash']`, but a dedicated
         check here means recovery never even stages a cartridge pair for a doomed resume
         (R5b-joint-protocol.md §3: "payload/source/contract-verified").
      4. source_fingerprint == digest(server_source_manifest(...)) computed RIGHT NOW, the exact
         computation `_build_intent`/`finalize_checkpoint` used to mint it — against a stand-in
         exposing only the two attributes `_client_source_files` reads (`native_trade`,
         `free_service`), since a stopped predecessor has no live Gen1Runtime to pass.
    """
    from types import SimpleNamespace

    from server import gen1_checkpoint_runtime
    from server.protocol import digest
    if gen1_checkpoint_runtime._manifest_sha256(manifest) != entry.get("manifest_sha256"):
        return "checkpoint manifest does not match the journal-confirmed hash"
    provenance = manifest.get("provenance") or {}
    if provenance.get("run_id") != run_spec.get("run_id") or provenance.get("registry_run_id") != run_id:
        return "checkpoint provenance does not match this run"
    if manifest.get("contract_fingerprint") != digest(run_spec.get("contract")):
        return "checkpoint contract fingerprint does not match this run"
    stand_in = SimpleNamespace(native_trade=bool(run_spec.get("native_trade", False)),
        free_service=bool(run_spec.get("free_service", False)))
    if manifest.get("source_fingerprint") != digest(gen1_checkpoint_runtime.server_source_manifest(stand_in)):
        return "checkpoint source fingerprint does not match the current server/client source"
    return None


def _stopped_journal_facts(run_directory) -> dict:
    """F1/F8: read-only facts about a STOPPED run's journal, opened exactly the way
    `gen1_run_resume.audit_predecessor` opens one (same FILENAME/schema/read_journal call) — but
    only the two checks recovery actually needs, an open trade and any outstanding command,
    plus the journal's final committed revision (for `discarded_through_revision`). Raises
    ValueError naming the reason, never re-implementing `audit_predecessor`'s own predicates:
    the exact same `active_trade`/`outcome IS NULL` expressions it uses, reused verbatim because
    gen1_run_resume.py has no standalone function for either one to import instead.

    `active_trade` alone is R5b joint-protocol.md §3's "pending-native-trade policy forbids
    rollback" check too: `trade_coordinator.py` sets it to the transaction identifier exactly
    while that transaction is non-terminal and clears it exactly when the transaction reaches a
    TERMINAL phase (:292,351,494) — `gen1_trade_recovery.transactions()`'s own consistency check
    enforces the converse (a non-terminal phase entry requires `active_trade == identifier`), so
    there is no reachable state where the phase table is open but `active_trade` is None. A
    second check against `transactions()`/`TERMINAL` would be unreachable dead code, not
    defense-in-depth.
    """
    import sqlite3

    from server.gen1_run_config import FILENAME, SCHEMA as RUN_SCHEMA
    from server.journal_reader import read_journal
    from server.protocol import decode_frame, digest
    directory = Path(run_directory).resolve()
    path = directory / FILENAME
    if not path.is_file() or not (directory / "runtime.sqlite3").is_file():
        raise ValueError("predecessor run directory has no prepared Gen 1 runtime")
    spec = decode_frame(path.read_bytes())
    if spec.get("schema") != RUN_SCHEMA:
        raise ValueError("predecessor is not a Gen 1 run")
    stored = read_journal(directory / spec["journal"], run_id=spec["run_id"], contract_hash=digest(spec["contract"]))
    document = stored.snapshot.state
    if document.get("active_trade") is not None:
        raise ValueError("predecessor has an open trade")
    db = sqlite3.connect((directory / spec["journal"]).as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=2.5)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        for player in ("a", "b"):
            if db.execute("SELECT 1 FROM commands WHERE player=? AND outcome IS NULL LIMIT 1", (player,)).fetchone():
                raise ValueError("predecessor has pending native commands")
        final_revision = db.execute("SELECT COALESCE(MAX(revision), 0) FROM events").fetchone()[0]
    finally:
        db.close()
    return {"spec": spec, "final_revision": final_revision}


async def _stage_recovered_cartridges(successor_dir: Path, predecessor_dir: Path, predecessor_run: dict, contract: dict, body: dict):
    """F4: rebuild the successor's OWN prepared pair from scratch — never `copytree` the
    predecessor's directory, so a recovered run never shares files with the run it discarded.

    A native predecessor's clean ROMs live only at whatever local path the caller supplied at
    creation time: `rom_contract.json` records the admitted contract (variant/hashes/
    capabilities), never a file path, and the Manager persists no such path either. So a native
    recovery's request body must carry fresh `rom_a`/`rom_b` (exactly like `handle_create_gen1`),
    checked against the predecessor's own admitted contract before they are trusted for anything.
    """
    from server.gen1_admission import clean_contract
    from server.protocol import canonical_json, decode_frame
    rom_a, rom_b = body.get("rom_a"), body.get("rom_b")
    if not isinstance(rom_a, str) or not isinstance(rom_b, str):
        raise ValueError("recovering a native run requires rom_a and rom_b in the request body")
    for value in (rom_a, rom_b):
        if not value.strip() or not Path(value).is_file():
            raise ValueError(f"cartridge file not found: {value}")
    admitted = await asyncio.to_thread(clean_contract, {"a": rom_a, "b": rom_b})
    predecessor_admitted = decode_frame((predecessor_dir / "rom_contract.json").read_bytes())
    if canonical_json(admitted) != canonical_json(predecessor_admitted):
        raise ValueError("recovery cartridges differ from the predecessor's admitted clean pair")
    if predecessor_run.get("fastest_text", False):
        from server.gen1_upr_pipeline import prepare_pair
        jar = os.environ.get("SLINK_UPR_JAR", "")
        if not jar:
            raise ValueError("SLINK_UPR_JAR is not set")
        settings = (predecessor_dir / "fastest-text.rnqs").read_bytes()
        (successor_dir / "fastest-text.rnqs").write_bytes(settings)
        await asyncio.to_thread(prepare_pair, jar, settings, {"a": rom_a, "b": rom_b},
            successor_dir / "prepared", seeds={"a": "123456789", "b": "987654321"})
    else:
        from server.gen1_prepared_cartridges import stage_canonical_pair
        await asyncio.to_thread(stage_canonical_pair, successor_dir / "prepared", {"a": rom_a, "b": rom_b})
    from server.gen1_prepared_cartridges import PreparedCartridges
    cartridges = await asyncio.to_thread(PreparedCartridges, successor_dir / "prepared")
    if canonical_json(cartridges.contract()) != canonical_json(contract):
        raise ValueError("recovered cartridge pair does not match the predecessor contract")
    return cartridges


def _confirmed_checkpoint_component(run_directory):
    """(component, error) for a STOPPED run's journal-confirmed checkpoint.

    R5b-1's module owns the cross-store reconciliation; a tree without it must still start the
    Manager, so the import is guarded and reported as unavailable rather than crashing.
    """
    try:
        from server import gen1_checkpoint_runtime
    except ImportError:   # pragma: no cover - present in this tree, guarded for older checkouts
        return None, "checkpoint runtime unavailable"
    return gen1_checkpoint_runtime.confirmed_checkpoints(run_directory), None


def _confirmed_entry(component):
    """The recoverable checkpoint entry, or None.

    R5b-joint-protocol.md §3: the `confirmed` field is authority on its own, regardless of the
    LATEST request's status — a later request may still be collecting/preparing (crashed
    mid-flight) or have been abandoned, and an earlier confirmed checkpoint must stay usable
    either way. A partial upload/preparing intent is never recovery authority: `confirmed` is
    populated only by `_confirm()`, never by `start()`/`_record_upload`'s "preparing" step, so
    dropping the `status == "confirmed"` filter never promotes an unconfirmed intent.
    """
    if not isinstance(component, dict):
        return None
    return component.get("confirmed") or None


def _run_directory(run_id: str):
    root = Path(MANAGER_DIR).resolve()
    directory = (root / run_id).resolve()
    return directory if directory.is_relative_to(root) else None


def _release(entry: dict, token: str, **fields) -> bool:
    """Apply a start's outcome ONLY while the entry still holds that start's reservation.

    False means another transition (timeout normalisation, stop/archive/delete, a newer start)
    already took the entry; the caller then owns nothing but its own spawned process."""
    if entry.get("starting_token") != token:
        return False
    _expire(entry, **fields)
    return True


def _expire(entry: dict, **fields) -> None:
    """A non-owner transition: drop any reservation so a late spawn's commit finds no token."""
    entry.pop("starting_token", None)
    entry.pop("starting_at", None)
    entry.update(fields)


def _starting_refusal() -> web.Response:
    return web.json_response({"ok": False, "error": "Run is starting; wait for the start to finish"}, status=409)


def _find_run(runs: list[dict], run_id: str) -> dict | None:
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


# ponytail: a start reservation (status "starting", no pid yet) is trusted for this long; past it a
# manager that died mid-spawn is assumed and the entry is normalised to stopped. A spawn slower than
# this ceiling is not a race: it loses its reservation (token cleared by whichever transition comes
# next) and its own commit then finds no token, kills the process it started and returns 409.
# Raise the constant if a spawn ever legitimately takes longer than two minutes.
STARTING_TIMEOUT = 120.0


def _reservation_live(run: dict) -> bool:
    """A starting entry still owned by an in-flight handle_start: token present and younger than the timeout."""
    if run.get("status") != "starting" or not run.get("starting_token"):
        return False
    try:
        started = datetime.fromisoformat(run["starting_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return (datetime.now(UTC) - started).total_seconds() < STARTING_TIMEOUT


def _recovering_live(run: dict) -> bool:
    """R5b-3b F3: a `recovering` reservation still owned by an in-flight handle_recover, on the
    same timeout as a start reservation — mirrors `_reservation_live` for the recovery lane."""
    recovering = run.get("recovering")
    if not isinstance(recovering, dict) or not recovering.get("token"):
        return False
    try:
        started = datetime.fromisoformat(recovering["at"])
    except (KeyError, TypeError, ValueError):
        return False
    return (datetime.now(UTC) - started).total_seconds() < STARTING_TIMEOUT


def _release_recovering(entry: dict, token: str) -> bool:
    """Drop a recovery reservation ONLY while it is still ours (mirrors `_release`)."""
    if (entry.get("recovering") or {}).get("token") != token:
        return False
    entry.pop("recovering", None)
    return True


def _reconcile(runs: list[dict]) -> bool:
    """Check live processes; update status for dead ones. Adopt orphan dirs. Returns True if any changed."""
    changed = False
    for run in runs:
        if run["status"] == "starting" and _reservation_live(run):
            continue
        if run["status"] in ("running", "starting") and not _is_alive(run.get("pid")):
            _expire(run, status="stopped", pid=None)
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


class RunManager:
    def __init__(self, bind_host: str, manager_port: int = MANAGER_HTTP_PORT):
        self.bind_host = bind_host
        self.manager_port = manager_port
        self._stream_pin_id: str | None = None  # run_id pinned for stream overlays
        # Every registry load-modify-save runs under this lock. Slow work (ROM admission, the resume
        # audit, runtime creation, subprocess spawn) stays outside it; the mutation reloads inside.
        self._registry_lock = asyncio.Lock()

    async def _update_run(self, run_id: str, mutate) -> dict | None:
        """Serialised load -> mutate(run) -> save of one entry, on a fresh load. None if unknown."""
        async with self._registry_lock:
            runs = _load_registry()
            run = _find_run(runs, run_id)
            if run is not None:
                mutate(run)
                _save_registry(runs)
            return run

    async def _get(self) -> list[dict]:
        async with self._registry_lock:
            runs = _load_registry()
            if _reconcile(runs):
                _save_registry(runs)
            return runs

    async def _active_stream_run(self) -> dict | None:
        """Return the run that stream overlays should proxy to.

        Priority:
        1. Explicitly pinned run (if still running and alive).
        2. Most recently started running run (latest created_at).
        Returns None if no run is running.
        """
        runs = await self._get()
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
        runs = await self._get()
        # Augment each run with display fields the master-detail template
        # expects (created_short, safe_name, game_label, last_event).
        augmented = [self._augment_for_template(r) for r in runs]
        return aiohttp_jinja2.render_template(
            "manager.html", request,
            {
                "page_title":   "Soul Link Run Manager",
                "theme":        resolve_theme(request),
                "is_stream":    False,
                "hide_chrome":  False,
                # ESCAPED, not just serialized. This lands inside a <script> block via
                # `| safe`, and json.dumps does not escape "<" -- so a run NAME containing
                # "</script>" closed the element and everything after it was parsed as
                # markup. Run names reach here from the API as well as the UI, so this is
                # stored XSS rather than a self-inflicted footgun. Escaping the three
                # characters that can end or open a tag keeps the JSON valid (they are
                # legal inside JS strings as unicode escapes) and inert as markup.
                "runs_json":    _json_for_script(augmented),
                "manager_port": self.manager_port,
            },
        )

    def _augment_for_template(self, run: dict) -> dict:
        """Add display strings to a run dict for the master-detail template.

        Avoids putting this logic in the JS so the initial page render has
        everything it needs without an extra round-trip.
        """
        rid = run["run_id"]
        r = dict(run)
        r["created_short"] = (run.get("created_at") or "")[:16].replace("T", " ")
        r["safe_name"] = re.sub(r"[^\w-]", "_", run.get("name") or rid).strip("_") or rid

        # Read game label from the run's links.json (best effort).
        links_path = os.path.join(MANAGER_DIR, rid, "links.json")
        try:
            with open(links_path) as f:
                rom_type = json.load(f).get("rom_type", "")
            # variant_label, not .title(): the latter renders gen1_rby as "Gen1 Rby".
            r["game_label"] = variant_label(rom_type) if rom_type else ""
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            r["game_label"] = ""

        # Read the most recent event (newest-first list) so the right pane
        # can surface it without an extra API call.
        events_path = os.path.join(MANAGER_DIR, rid, "events.json")
        r["last_event"] = None
        try:
            with open(events_path) as f:
                evts = json.load(f)
            if evts:
                ev = evts[0]
                r["last_event"] = {
                    "ts":     (ev.get("ts", "") or "")[-8:],
                    "player": (ev.get("player", "") or "").upper(),
                    "text":   ev.get("text", "") or "",
                }
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            pass
        return r

    async def handle_list(self, request: web.Request) -> web.Response:
        return web.json_response({"runs": await self._get()})

    async def handle_run(self, request: web.Request) -> web.Response:
        run = _find_run(await self._get(), request.match_info["run_id"])
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        return web.json_response({"ok": True, "run": run})

    async def handle_new(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        name = str(body.get("name", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "name is required"}, status=400)

        runs = _load_registry()
        run_id = "run_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
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
            "created_at": datetime.now(UTC).isoformat(),
            "tcp_port":   tcp_port,
            "http_port":  http_port,
            "status":     "stopped",
            "pid":        None,
            "species_lock": bool(body.get("species_lock", False)),
            "gender_lock":  bool(body.get("gender_lock", False)),
            "type_lock":    bool(body.get("type_lock", False)),
            "explode_mode": bool(body.get("explode_mode", False)),
            "rival_team_swap": bool(body.get("rival_team_swap", False)),
            "overworld_presence": bool(body.get("overworld_presence", False)),
            "native_messages": bool(body.get("native_messages", False)),
            "native_sounds": bool(body.get("native_sounds", False)),
            "battle_calc": bool(body.get("battle_calc", True)),
            "pc_trade_npc": bool(body.get("pc_trade_npc", True)),
            "verbose": bool(body.get("verbose", False)),
        }
        # Create data directory immediately
        os.makedirs(os.path.join(MANAGER_DIR, run_id), exist_ok=True)
        _write_run_meta(run)
        async with self._registry_lock:
            runs = _load_registry()
            runs.append(run)
            _save_registry(runs)

        # Auto-start
        try:
            pid = await _spawn_run(run, self.bind_host if self.bind_host != "0.0.0.0" else "0.0.0.0",
                                   manager_port=self.manager_port)
            run["status"] = "running"
            run["pid"] = pid
            await self._update_run(run_id, lambda entry: entry.update(status="running", pid=pid))
        except Exception as e:
            log.error(f"Failed to auto-start run {run_id}: {e}")

        return web.json_response({"ok": True, "run": run})

    async def handle_start(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        # Reserve the run under the lock BEFORE the spawn: a resume of this run (which needs it stopped)
        # sees "starting" and refuses; a run already resumed can never start again.
        async with self._registry_lock:
            runs = _load_registry()
            run = _find_run(runs, run_id)
            if run is None:
                return web.json_response({"ok": False, "error": "Run not found"}, status=404)
            if run["status"] == "archived":
                return web.json_response({"ok": False, "error": "Archived runs cannot be started"}, status=400)
            if run.get("resumed_by"):
                return web.json_response({"ok": False, "error": "This run was resumed; start its successor instead",
                                          "details": {"resumed_by": run["resumed_by"]}}, status=409)
            if run.get("recovered_by"):
                return web.json_response({"ok": False, "error": "This run was recovered; start its successor instead",
                                          "details": {"recovered_by": run["recovered_by"]}}, status=409)
            if _recovering_live(run):
                return web.json_response({"ok": False, "error": "This run is being recovered"}, status=409)
            if run["status"] == "running" and _is_alive(run.get("pid")):
                return web.json_response({"ok": True, "message": "Already running"})
            if _reservation_live(run):
                return web.json_response({"ok": False, "error": "Run is already starting"}, status=409)
            token = secrets.token_hex(16)
            run.update(status="starting", pid=None, starting_token=token, starting_at=datetime.now(UTC).isoformat())
            _save_registry(runs)
        try:
            pid = await _spawn_run(run, self.bind_host if self.bind_host != "0.0.0.0" else "0.0.0.0",
                                   manager_port=self.manager_port)
        except Exception as e:
            # Revert only our own reservation; an expired-and-replaced start owns nothing here.
            await self._update_run(run_id, lambda entry: _release(entry, token, status="stopped", pid=None))
            return web.json_response({"ok": False, "error": str(e)}, status=500)
        # Commit on a fresh load under the lock, and only if this reservation still stands: the run may
        # have been resumed (resumed_by) or re-reserved meanwhile; then the spawn is ours to kill.
        outcome = {}

        def commit(entry):
            if entry.get("starting_token") == token and not entry.get("resumed_by"):
                _release(entry, token, status="running", pid=pid)
                outcome["ok"] = True
        if await self._update_run(run_id, commit) is None:
            _kill_run(pid)
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        if not outcome:
            _kill_run(pid)
            return web.json_response({"ok": False, "error": "start superseded; the run was resumed or re-reserved meanwhile"},
                                     status=409)
        return web.json_response({"ok": True, "pid": pid})

    async def handle_stop(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        if _reservation_live(run):
            return _starting_refusal()
        pid = run.get("pid")
        if pid:
            _kill_run(pid)
        await self._update_run(run_id, lambda entry: _expire(entry, status="stopped", pid=None))
        return web.json_response({"ok": True})

    async def handle_archive(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        if _reservation_live(run):
            return _starting_refusal()
        pid = run.get("pid")
        if pid and _is_alive(pid):
            _kill_run(pid)
        await self._update_run(run_id, lambda entry: _expire(entry, status="archived", pid=None))
        return web.json_response({"ok": True})

    async def handle_delete(self, request: web.Request) -> web.Response:
        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        if _reservation_live(run):
            return _starting_refusal()
        # Stop the process if running
        pid = run.get("pid")
        if pid and _is_alive(pid):
            _kill_run(pid)
        # Remove data directory
        data_dir = os.path.join(MANAGER_DIR, run_id)
        if os.path.isdir(data_dir):
            shutil.rmtree(data_dir, onerror=lambda fn, path, exc: log.warning("delete %s: %s left behind: %s", run_id, path, exc[1]))
            log.info(f"Deleted data directory for run {run_id}")
        # Remove from registry
        async with self._registry_lock:
            runs = [r for r in _load_registry() if r["run_id"] != run_id]
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
        from server.gen1_run_config import read_bound_configuration
        from server.protocol_journal import JournalError
        try:
            prepared,cartridges = read_bound_configuration(os.path.join(MANAGER_DIR, run_id))
            if prepared is not None:
                from urllib.parse import urlsplit

                from server.gen1_launcher import build_configuration
                from server.runtime_launcher import render_launcher
                if not prepared.get('free_service',False):
                    raise JournalError('Manager cannot launch a held-service Gen1 run; create a new Gen1 run')
                connect_host = urlsplit("http://"+host_header).hostname or "127.0.0.1"
                configuration=build_configuration(prepared["run_id"],prepared["contract"],player,prepared_cartridges=cartridges,
                    initial_observations=prepared.get('initial_observations',False),
                    native_trade=prepared.get('native_trade',False),
                    free_service=prepared.get('free_service',False))
                content = render_launcher(configuration,
                    host=connect_host, port=run["tcp_port"], name=run.get("name") or run_id, resume=run.get("resume"))
                if getattr(request,'query',{}).get('bundle')=='1':
                    from server.bizhawk_launch import bundle
                    return web.Response(body=bundle(run_id=prepared['run_id'],player=player,profile='gambatte',
                        rom_sha1=configuration['cartridge']['final_rom_sha1'],launcher=content,resume=run.get("resume")),content_type='application/zip',
                        headers={'Content-Disposition':f'attachment; filename="slink_{player}_launch.zip"'})
            else:
                content = _build_launcher(run, player, connect_host)
        except (JournalError, ValueError, OSError) as error:
            return web.json_response({"ok": False, "error": str(error)}, status=409)
        safe_name = re.sub(r'[^\w-]', '_', run.get("name") or run_id).strip('_') or run_id
        filename = f"slink_{safe_name}_{player}{'_free' if prepared is not None else ''}.lua"
        return web.Response(
            text=content,
            content_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def handle_run_cartridge(self, request: web.Request) -> web.Response:
        """GET /api/runs/{run_id}/cartridge/{player} — the FINAL admitted cartridge bytes.

        Only a native run has one, and it comes from that run's own verified prepared pair
        (`PreparedCartridges` re-checks every hash when it opens), never from a caller-supplied
        path: the two machines are on different filesystems, so the bytes have to travel.
        """
        run_id = request.match_info.get("run_id", "")
        player = request.match_info.get("player", "")
        if player not in ("a", "b"):
            return web.json_response({"ok": False, "error": "unknown player"}, status=404)
        run = _find_run(_load_registry(), run_id)
        if run is None or not run.get("native_trade"):
            return web.json_response({"ok": False, "error": "this run has no downloadable cartridge"}, status=404)
        directory = _run_directory(run_id)
        if directory is None or not (directory / "prepared").is_dir():
            return web.json_response({"ok": False, "error": "this run has no prepared cartridge"}, status=404)
        from server.gen1_prepared_cartridges import PreparedCartridges
        try:
            cartridges = await asyncio.to_thread(PreparedCartridges, directory / "prepared")
            data = cartridges.rom(player)
        except Exception as problem:
            log.warning("prepared cartridge for %s/%s did not validate: %s", run_id, player, problem)
            return web.json_response({"ok": False, "error": "prepared cartridge unavailable"}, status=404)
        variant = (run.get("cartridges", {}).get(player) or {}).get("variant", "cartridge")
        return web.Response(body=data, content_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="slink_{variant}_{player}.gb"',
                     "X-SLink-ROM-SHA1": hashlib.sha1(data).hexdigest()})

    async def handle_create_gen1(self, request: web.Request) -> web.Response:
        """Prepare a fresh RBY runtime before starting its server process."""
        import sqlite3
        from pathlib import Path

        from server.gen1_admission import clean_contract, write_contract
        from server.gen1_run_config import create_runtime
        from server.protocol_journal import JournalError
        try:
            body=await request.json()
            if (not isinstance(body,dict) or not {'name','rom_a','rom_b'}<=set(body)
                    or set(body)-{'name','rom_a','rom_b','rules','start','native','fastest_text','resume_from'}
                    or not isinstance(body['name'],str) or not 1<=len(body['name'].strip())<=120
                    or any(ord(c)<32 for c in body['name'])
                    or type(body.get('start',True)) is not bool or type(body.get('native',False)) is not bool
                    or type(body.get('fastest_text',False)) is not bool
                    or not isinstance(body.get('resume_from',''),str)):
                raise ValueError('name, two cartridge paths and optional explicit rules/start/native/fastest_text/resume_from are required')
            if body.get('fastest_text',False) and not body.get('native',False):
                # Fastest text is a preset of the native path: it replaces the canonical companion
                # pair, so without native there is no prepared directory to hold it.
                raise ValueError('fastest_text requires native')
            for name in ('rom_a','rom_b'):
                # A mistyped path is the caller's error, not a server fault: name it and refuse
                # before admission, where FileNotFoundError used to surface as a 500.
                if not isinstance(body[name],str) or not body[name].strip() or not Path(body[name]).is_file():
                    raise ValueError(f'cartridge file not found: {body[name]}')
            # The user's cartridges are admitted as exact canonical CLEAN ROMs either way.
            admitted=await asyncio.to_thread(clean_contract,{'a':body['rom_a'],'b':body['rom_b']})
            contract=admitted
            runs=_load_registry();tcp_port,http_port=_next_ports(runs)
            resume=None
            if 'resume_from' in body:
                # Owner policy P2a: a resume is a NEW run seeded from a closed predecessor's audited journal.
                from server import gen1_run_resume
                if not _RUN_ID.fullmatch(body['resume_from']):
                    raise ValueError('resume_from must be a registry run id')
                predecessor=_find_run(runs,body['resume_from'])
                if predecessor is None:
                    return web.json_response({'ok':False,'error':'Run not found','reasons':['predecessor run is not in the registry']},status=404)
                refused=_resume_refusal(predecessor)
                details=None
                if refused is None:
                    root=Path(MANAGER_DIR).resolve()
                    predecessor_dir=(root/predecessor['run_id']).resolve()
                    if not predecessor_dir.is_relative_to(root):
                        raise ValueError('resume_from must name a run under the manager directory')
                    try:
                        audit=await asyncio.to_thread(gen1_run_resume.audit_predecessor,predecessor_dir,registry_entry=predecessor)
                    except Exception as error:
                        log.warning('resume audit of %s failed: %s',predecessor['run_id'],error)
                        refused=['predecessor audit failed']
                    else:
                        refused=None if audit.ok else list(audit.reasons)
                        details=audit.details
                        # The registry may have changed during the audit (a start, or another resume).
                        runs=_load_registry()
                        predecessor=_find_run(runs,body['resume_from'])
                        refused=refused or _resume_refusal(predecessor)
                if refused is not None:
                    return web.json_response(_refusal_body(predecessor,refused,details),status=409)
                if bool(body.get('fastest_text',False))!=bool(predecessor.get('fastest_text',False)):
                    # A resumed run must stay the predecessor's run: switching the prepared pair at
                    # resume time would silently change what the imported journal describes.
                    raise ValueError('resumed run must keep the predecessor fastest_text setting')
                resume=audit.resume_record()
            run_id='run_'+datetime.now(UTC).strftime('%Y%m%d_%H%M%S')+'_'+secrets.token_hex(3)
            directory=Path(MANAGER_DIR)/run_id
            cartridges=None
            if body.get('native',False):
                # Native trade: derive the canonical companion pair from those clean inputs inside the
                # run (hash-pinned to the installed catalog), and select it; the launcher then ships the
                # native manifest and the client boots the companion, not the clean ROM.
                from server.gen1_prepared_cartridges import PreparedCartridges, stage_canonical_pair
                directory.mkdir(parents=True,exist_ok=False)
                try:
                    if body.get('fastest_text',False):
                        # Fastest text: the same SLink policy pair, produced by UPR with its single
                        # fastest-text misc tweak and nothing else randomized. The settings the pair
                        # was built from stay in the run as evidence; the producer takes them as bytes.
                        from server.gen1_upr_pipeline import prepare_pair
                        from server.gen1_upr_policy import build_preset
                        jar=os.environ.get('SLINK_UPR_JAR','')
                        if not jar:
                            raise ValueError('SLINK_UPR_JAR is not set')
                        settings=build_preset({'currentMiscTweaks':8})
                        (directory/'fastest-text.rnqs').write_bytes(settings)
                        await asyncio.to_thread(prepare_pair,jar,settings,{'a':body['rom_a'],'b':body['rom_b']},
                            directory/'prepared',seeds={'a':'123456789','b':'987654321'})
                    else:
                        await asyncio.to_thread(stage_canonical_pair,directory/'prepared',{'a':body['rom_a'],'b':body['rom_b']})
                    cartridges=await asyncio.to_thread(PreparedCartridges,directory/'prepared')
                except Exception:
                    shutil.rmtree(directory,ignore_errors=True);raise   # no half-staged run directory survives
                contract=cartridges.contract()
            staged_here=cartridges is not None   # the native branch made this directory; the runtime has not adopted it yet
            try:
                runtime=create_runtime(directory,contract,rule_options=body.get('rules',{}),free_service=True,
                    prepared_cartridges=cartridges,native_trade=cartridges is not None,resume=resume)
                try:
                    rules=runtime.state().rules
                    settings={key:bool(getattr(rules,key)) for key in ('species_lock','gender_lock','type_lock','explode_mode',
                        'rival_team_swap','overworld_presence','native_messages','native_sounds','battle_calc','pc_trade_npc')}
                finally:runtime.close()
                write_contract(directory/'rom_contract.json',admitted)   # the user's admitted clean cartridges; the runtime binds the pair
                run={'run_id':run_id,'name':body['name'].strip(),'created_at':datetime.now(UTC).isoformat(),
                    'tcp_port':tcp_port,'http_port':http_port,'status':'stopped','pid':None,'cartridges':contract['players'],
                    'native_trade':cartridges is not None,'fastest_text':bool(body.get('fastest_text',False)),**settings}
                if resume is not None:
                    # The launch contract each client must meet (runtime_launcher/bizhawk_launch emit it per player);
                    # the imported rules state lives in the runtime journal, not the registry.
                    run['resume']={'from_run':resume['from_run'],'contract_hash':resume['contract_hash'],'required':resume['required']}
                _write_run_meta(run)
                async with self._registry_lock:   # the commit: fresh load, final predecessor check, one save
                    runs=_load_registry()
                    if resume is not None:
                        predecessor=_find_run(runs,resume['from_run'])
                        refused=_resume_refusal(predecessor)
                        if refused is not None:   # changed under the creation; the new directory must not survive
                            shutil.rmtree(directory,onerror=lambda fn,path,exc:log.warning('resume refusal cleanup left %s: %s',path,exc[1]))
                            return web.json_response(_refusal_body(predecessor,refused),status=409)
                        predecessor['resumed_by']=run_id
                    runs.append(run)
                    _save_registry(runs)
            except Exception:
                # Only this request's own directory: a failure before the registry commit must not
                # leave a half-built run behind, and the predecessor's directory is never touched.
                if staged_here:
                    shutil.rmtree(directory,ignore_errors=True)
                raise
            if body.get('start',True):
                run['pid']=await _spawn_run(run,self.bind_host,manager_port=self.manager_port)
                run['status']='running'
                await self._update_run(run_id,lambda entry:entry.update(status='running',pid=run['pid']))
        except (ValueError,TypeError,JournalError) as error:
            return web.json_response({'ok':False,'error':str(error)},status=400)
        except (RuntimeError,OSError,sqlite3.Error) as error:
            return web.json_response({'ok':False,'error':str(error)},status=500)
        return web.json_response({'ok':True,'run':run,'runtime_mode':'free_service',
            'native_trade':cartridges is not None})

    async def handle_cartridges(self, request: web.Request) -> web.Response:
        """Bind each RBY player to an inspected local cartridge before admission."""
        from pathlib import Path

        from server.gen1_admission import AdmissionError, clean_contract, write_contract

        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"rom_a", "rom_b"}:
                raise AdmissionError("provide rom_a and rom_b local file paths")
            contract = await asyncio.to_thread(clean_contract, {"a": body["rom_a"], "b": body["rom_b"]})
            write_contract(Path(MANAGER_DIR) / run_id / "rom_contract.json", contract)
            run["cartridges"] = contract["players"]
            await self._update_run(run_id, lambda entry: entry.update(cartridges=contract["players"]))
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

    async def handle_randomize(self, request: web.Request) -> web.Response:
        """POST /api/runs/{run_id}/randomize — build this run's pair of randomized ROMs.

        Everything the players need to trust the pair is decided here and recorded on the
        run: the settings file's hash, both seeds, both final ROM hashes and the scanned
        content hashes. None of it is recoverable from the ROMs afterwards -- UPR's CLI has
        no seed flag and writes the seed only to its log -- so if this step does not capture
        it, nothing can.

        Runs in a thread: the pipeline shells out to java twice and would otherwise block
        the manager's event loop for several seconds.
        """
        run_id = request.match_info["run_id"]
        runs = _load_registry()
        run = _find_run(runs, run_id)
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

        out_dir = os.path.join(MANAGER_DIR, run_id, "roms")
        from server.upr_pipeline import UprPipelineError, prepare_pair
        try:
            result = await asyncio.to_thread(
                prepare_pair, jar, settings, {"a": rom_a, "b": rom_b}, out_dir)
        except UprPipelineError as exc:
            # A refusal is the feature, not a crash: say exactly what was wrong so the user
            # can fix the settings or the ROMs rather than guessing.
            log.warning("randomize %s refused: %s", run_id, exc)
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:                      # noqa: BLE001
            log.exception("randomize %s failed", run_id)
            return web.json_response({"ok": False, "error": f"unexpected: {exc}"}, status=500)

        run["randomizer"] = {
            "upr_version": result["upr_version"],
            "settings_sha256": result["settings_sha256"],
            "categories": result["categories"],
            "created_at": datetime.now(UTC).isoformat(),
            "players": {
                p: {"seed": str(v["seed"]),      # 48-bit; a string so no JS float rounds it
                    "rom_sha1": v["sha1"],
                    "source_sha1": v["source_sha1"],
                    "content_hash": v["content_hash"],
                    "output": v["output"]}
                for p, v in result["players"].items()
            },
        }
        await self._update_run(run_id, lambda entry: entry.update(randomizer=run["randomizer"]))
        _write_run_meta(run)
        # The server process learns about the contract through the run directory, which is
        # the only thing the two already share (--data-dir). Written as its own file rather
        # than folded into links.json so a run that is reset or rolled back keeps the
        # contract: the ROMs did not change just because the links did.
        contract = {
            "upr_version": result["upr_version"],
            "settings_sha256": result["settings_sha256"],
            "categories": result["categories"],
            "players": {p: {"fingerprint": v["fingerprint"], "seed": str(v["seed"]),
                            "rom_sha1": v["sha1"]}
                        for p, v in result["players"].items()},
        }
        try:
            with open(os.path.join(MANAGER_DIR, run_id, "rom_contract.json"), "w") as f:
                json.dump(contract, f, indent=2)
        except OSError as exc:
            log.warning("could not write rom_contract.json for %s: %s", run_id, exc)
        return web.json_response({"ok": True, "randomizer": run["randomizer"]})

    # ── Stream pin ─────────────────────────────────────────────────────────────

    async def handle_stream_pin(self, request: web.Request) -> web.Response:
        """POST /api/stream/pin — pin a run as the stream overlay target."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        run_id = body.get("run_id") or None
        if run_id is not None:
            run = _find_run(await self._get(), run_id)
            if run is None:
                return web.json_response({"ok": False, "error": "Run not found"}, status=404)
            # A stopped or dead run can never serve an overlay: _active_stream_run would drop
            # the pin on its next call, so accepting it here would answer 200 with a pin that
            # no longer exists. Refuse instead of reporting a phantom.
            if run.get("status") != "running" or not _is_alive(run.get("pid")):
                return web.json_response({"ok": False, "error": "Run is not running"}, status=409)
        self._stream_pin_id = run_id
        log.info(f"Stream overlay pin set to: {run_id!r}")
        active = await self._active_stream_run()
        return web.json_response({
            "ok": True,
            "pinned": self._stream_pin_id,
            "active_run_id": active["run_id"] if active else None,
        })

    async def handle_stream_pin_status(self, request: web.Request) -> web.Response:
        """GET /api/stream/pin — return current pin and active run."""
        active = await self._active_stream_run()
        return web.json_response({
            "pinned": self._stream_pin_id,
            "active_run_id": active["run_id"] if active else None,
            "active_run_name": active.get("name") if active else None,
        })

    # ── Stream overlay pages (served at fixed manager port 8090) ───────────────

    async def handle_stream_index(self, request: web.Request) -> web.Response:
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
        active = await self._active_stream_run()
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
        # Preserve query string (?theme=…, ?layout=…, etc.) when proxying.
        qs = request.url.query_string
        target = (f"http://127.0.0.1:{active['http_port']}/stream/{name}{suffix}"
                  + (f"?{qs}" if qs else ""))
        try:
            async with request.app["proxy_session"].get(
                target, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                body = await resp.read()
                ct = resp.headers.get("Content-Type", "text/html")
                return web.Response(body=body, status=resp.status, content_type=ct.split(";")[0])
        except Exception as e:
            log.debug(f"Proxy /stream/{name}{suffix} → run {active['run_id']} failed: {e}")
            return web.Response(status=502, text=f"Upstream run {active['run_id']} unreachable")

    # ── API proxy endpoints (relay to active run) ──────────────────────────────

    async def handle_proxy_status(self, request: web.Request) -> web.Response:
        """GET /api/status — proxy to the active run or return empty status."""
        active = await self._active_stream_run()
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

    # ── R5b: paired checkpoint request / status / recover / save download ─────────────────────

    async def _run_json(self, request: web.Request, run: dict, method: str, path: str,
                        body: dict | None = None) -> web.Response:
        """One JSON round trip to a RUNNING run server, with the live proxy's status mapping."""
        url = f"http://127.0.0.1:{run['http_port']}{path}"
        timeout = aiohttp.ClientTimeout(total=5)
        try:
            if method == "GET":
                context = request.app["proxy_session"].get(url, timeout=timeout)
            else:
                context = request.app["proxy_session"].post(url, json=body or {}, timeout=timeout)
            async with context as resp:
                return web.json_response(await resp.json(content_type=None), status=resp.status)
        except TimeoutError:
            return web.json_response({"ok": False, "error": "timeout"}, status=504)
        except Exception as error:
            log.debug(f"Checkpoint proxy {method} {path} failed: {error}")
            return web.json_response({"ok": False, "error": "proxy_failed"}, status=502)

    def _running_run(self, run_id: str):
        """The registry entry and whether it can answer a run-server proxy right now."""
        run = _find_run(_load_registry(), run_id)
        if run is None:
            return None
        return run if run.get("status") == "running" and run.get("http_port") else None

    async def handle_run_checkpoint(self, request: web.Request) -> web.Response:
        """POST /api/runs/{run_id}/checkpoint — start one paired capture on the run server.

        The Manager mints the request id, because it is the side that can still read the reply
        after a restart: the run server's `/api/checkpoint/{request_id}` is the only status
        route it exposes.
        """
        run_id = request.match_info.get("run_id", "")
        run = self._running_run(run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "run not running"}, status=404)
        try:
            body = await request.json()
        except Exception:
            body = {}
        request_id = body.get("request_id") if isinstance(body, dict) else None
        if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
            request_id = secrets.token_hex(16)
        response = await self._run_json(request, run, "POST", "/api/checkpoint",
                                        {"request_id": request_id, "registry_run_id": run_id})
        if response.status in (200, 202):
            payload = json.loads(response.text)
            payload.setdefault("request_id", request_id)
            response = web.json_response(payload, status=response.status)
        return response

    async def handle_run_checkpoint_status(self, request: web.Request) -> web.Response:
        """GET /api/runs/{run_id}/checkpoint/{request_id} — the run server's own status."""
        run_id = request.match_info.get("run_id", "")
        request_id = request.match_info.get("request_id", "")
        run = self._running_run(run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "run not running"}, status=404)
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            return web.json_response({"ok": False, "error": "checkpoint request id required"}, status=400)
        return await self._run_json(request, run, "GET", f"/api/checkpoint/{request_id}")

    async def handle_run_checkpoints(self, request: web.Request) -> web.Response:
        """GET /api/runs/{run_id}/checkpoints — the recoverable checkpoint, or null.

        A running run reports the request the caller is polling; a stopped run reports ONLY the
        checkpoint its journal confirmed, re-validated against the store (a CURRENT pointer that
        no journal names is never offered for recovery).
        """
        run_id = request.match_info.get("run_id", "")
        run = _find_run(_load_registry(), run_id)
        if run is None:
            return web.json_response({"ok": False, "error": "Run not found"}, status=404)
        if run.get("status") == "running" and run.get("http_port"):
            request_id = request.query.get("request_id", "")
            if not re.fullmatch(r"[0-9a-f]{32}", request_id):
                return web.json_response({"ok": True, "current": None})
            status = await self._run_json(request, run, "GET", f"/api/checkpoint/{request_id}")
            if status.status != 200:
                return web.json_response({"ok": True, "current": None})
            payload = json.loads(status.text)
            return web.json_response({"ok": True, "current": {
                "checkpoint_id": (payload.get("confirmed") or {}).get("checkpoint_id"),
                "manifest_sha256": (payload.get("confirmed") or {}).get("manifest_sha256"),
                "status": payload.get("status")}})
        directory = _run_directory(run_id)
        if directory is None:
            return web.json_response({"ok": False, "error": "checkpoint unavailable"}, status=400)
        component, error = _confirmed_checkpoint_component(directory)
        if error:
            return web.json_response({"ok": False, "error": error}, status=503)
        entry = _confirmed_entry(component)
        if entry is None:
            return web.json_response({"ok": True, "current": None})
        from server.gen1_run_config import FILENAME as RUNTIME_FILENAME
        from server.paired_save_checkpoints import PairedCheckpointStore
        from server.protocol import decode_frame
        try:
            checkpoint = await asyncio.to_thread(PairedCheckpointStore(directory).load, entry["checkpoint_id"])
            run_spec = decode_frame((directory / RUNTIME_FILENAME).read_bytes())
        except Exception as problem:
            log.warning("confirmed checkpoint %s did not validate: %s", entry["checkpoint_id"], problem)
            return web.json_response({"ok": True, "current": None})
        # F2: a checkpoint reachable from the store's CURRENT pointer is not necessarily the one
        # THIS run's own journal confirmed, minted for THIS run, under source files that have not
        # drifted since — report it dropped rather than offering it for recovery.
        if _checkpoint_binding_error(checkpoint.manifest, entry, run_spec, run_id) is not None:
            return web.json_response({"ok": True, "current": None, "dropped": 1})
        return web.json_response({"ok": True, "current": {
            "checkpoint_id": checkpoint.manifest["checkpoint_id"],
            "manifest_sha256": entry["manifest_sha256"],
            "created_at": checkpoint.manifest["created_at"],
            "provenance": checkpoint.provenance()}})

    async def handle_recover(self, request: web.Request) -> web.Response:
        """POST /api/runs/{run_id}/recover — a NEW successor seeded from a confirmed checkpoint.

        The checkpoint's state is the authority here: `audit_predecessor` is deliberately NOT run
        (it audits the predecessor's LATER journal, which is exactly what recovery discards) — but
        F1/F8 still reads that same stopped journal read-only, for the two checks a rollback must
        never skip: no open trade, nothing left unacknowledged. A native predecessor's request
        body must carry fresh `rom_a`/`rom_b` local paths (F4): the Manager never persists the
        path it admitted a cartridge from, only its hashes.
        """
        run_id = request.match_info.get("run_id", "")
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        wanted = body.get("checkpoint_id")

        # F3: reserve the predecessor under the lock BEFORE any of the slow work below (checkpoint
        # load, cartridge staging, runtime creation) — a concurrent start/resume/second recovery
        # then sees `recovering` and refuses, exactly like handle_start's own reservation.
        token = secrets.token_hex(16)
        async with self._registry_lock:
            runs = _load_registry()
            run = _find_run(runs, run_id)
            if run is None:
                return web.json_response({"ok": False, "error": "Run not found"}, status=404)
            if run.get("status") in ("running", "starting") or _reservation_live(run):
                return web.json_response({"ok": False, "error": "stop the run before recovering it"}, status=409)
            if run.get("recovered_by"):
                return web.json_response({"ok": False, "error": "this run was already recovered"}, status=409)
            if run.get("resumed_by"):
                return web.json_response({"ok": False, "error": "this run was already resumed"}, status=409)
            if _recovering_live(run):
                return web.json_response({"ok": False, "error": "a recovery is already in progress for this run"}, status=409)
            run["recovering"] = {"token": token, "at": datetime.now(UTC).isoformat()}
            _save_registry(runs)

        async def _release():
            await self._update_run(run_id, lambda entry: _release_recovering(entry, token))

        directory = _run_directory(run_id)
        if directory is None:
            await _release()
            return web.json_response({"ok": False, "error": "checkpoint unavailable"}, status=400)
        component, error = _confirmed_checkpoint_component(directory)
        if error:
            await _release()
            return web.json_response({"ok": False, "error": error}, status=503)
        entry = _confirmed_entry(component)
        if entry is None:
            await _release()
            return web.json_response({"ok": False, "error": "no journal-confirmed checkpoint to recover"}, status=409)
        if wanted is not None and wanted != entry["checkpoint_id"]:
            await _release()
            return web.json_response({"ok": False, "error": "checkpoint is not the one this journal confirmed"}, status=409)
        checkpoint_id = entry["checkpoint_id"]
        from server.gen1_run_config import create_runtime
        from server.paired_save_checkpoints import CheckpointError, PairedCheckpointStore
        from server.protocol_journal import JournalError
        try:
            checkpoint = await asyncio.to_thread(PairedCheckpointStore(directory).load, checkpoint_id)
        except Exception as problem:
            await _release()
            return web.json_response({"ok": False, "error": f"checkpoint did not validate: {problem}"}, status=409)
        manifest = checkpoint.manifest

        successor_dir = None
        try:
            pretrade_error = _pretrade_checkpoint_error(manifest)  # F5
            if pretrade_error is not None:
                raise ValueError(pretrade_error)
            facts = await asyncio.to_thread(_stopped_journal_facts, directory)  # F1/F8: open trade / pending commands
            run_spec = facts["spec"]
            binding_error = _checkpoint_binding_error(manifest, entry, run_spec, run_id)  # F2
            if binding_error is not None:
                raise ValueError(binding_error)
            record = resume_record_from_checkpoint(run_id, manifest, checkpoint)
            contract = run_spec["contract"]
            native = bool(run_spec.get("native_trade")) and bool(run.get("native_trade"))
            successor_id = 'run_' + datetime.now(UTC).strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(3)
            successor_dir = Path(MANAGER_DIR) / successor_id
            tcp_port, http_port = _next_ports(runs)
            successor_dir.mkdir(parents=True, exist_ok=False)
            cartridges = None
            if native:
                # F4: the successor's OWN prepared pair, rebuilt from scratch — never copied from
                # the predecessor's directory.
                cartridges = await _stage_recovered_cartridges(successor_dir, directory, run, contract, body)
            rule_options = {key: bool(run.get(key, False)) for key in CHECKPOINT_RULE_KEYS}
            runtime = create_runtime(successor_dir, contract, rule_options=rule_options, free_service=True,
                prepared_cartridges=cartridges, native_trade=cartridges is not None, resume=record)
            try:
                rules = runtime.state().rules
                settings = {key: bool(getattr(rules, key)) for key in ('species_lock', 'gender_lock', 'type_lock',
                    'explode_mode', 'rival_team_swap', 'overworld_presence', 'native_messages', 'native_sounds',
                    'battle_calc', 'pc_trade_npc')}
            finally:
                runtime.close()
            shutil.copyfile(directory / "rom_contract.json", successor_dir / "rom_contract.json")
            successor = {'run_id': successor_id, 'name': f"{run.get('name', run_id)} (recovered)",
                'created_at': datetime.now(UTC).isoformat(), 'tcp_port': tcp_port, 'http_port': http_port,
                'status': 'stopped', 'pid': None, 'cartridges': contract["players"],
                'native_trade': cartridges is not None,
                'fastest_text': bool(run.get('fastest_text', False)), **settings}
            successor['resume'] = {'from_run': record['from_run'], 'contract_hash': record['contract_hash'],
                'required': record['required']}
            successor['recovered_from'] = {'run_id': run_id, 'checkpoint_id': checkpoint_id,
                'manifest_sha256': entry['manifest_sha256'],
                'discarded_after_revision': manifest['provenance'].get('journal_revision'),
                'discarded_through_revision': facts['final_revision']}
            _write_run_meta(successor)
            async with self._registry_lock:
                runs = _load_registry()
                predecessor = _find_run(runs, run_id)
                stale = (predecessor is None or predecessor.get('recovered_by') or predecessor.get('resumed_by')
                         or (predecessor.get('recovering') or {}).get('token') != token)
                if not stale:
                    predecessor.pop('recovering', None)
                    predecessor['recovered_by'] = successor_id
                    runs.append(successor)
                    _save_registry(runs)
            if stale:
                # F3: our reservation is already gone (someone else's transition took it), so
                # there is nothing of ours left to release — only the successor directory.
                shutil.rmtree(successor_dir, ignore_errors=True)
                return web.json_response({"ok": False, "error": "predecessor changed under the recovery"}, status=409)
        except (ValueError, TypeError, JournalError, CheckpointError) as error:
            # F1/F8: expected refusals (open trade/pending commands, a binding mismatch, a bad
            # cartridge pair, create_runtime's own contract checks) are 409s, never 500s.
            if successor_dir is not None:
                shutil.rmtree(successor_dir, ignore_errors=True)
            await _release()
            return web.json_response({"ok": False, "error": str(error)}, status=409)
        except Exception:
            if successor_dir is not None:
                shutil.rmtree(successor_dir, ignore_errors=True)
            await _release()
            raise
        return web.json_response({"ok": True, "run": successor, "checkpoint_id": checkpoint_id,
            "downloads": {"a": f"/api/runs/{successor_id}/recovery-save/a",
                          "b": f"/api/runs/{successor_id}/recovery-save/b"}})

    async def handle_recovery_save(self, request: web.Request) -> web.Response:
        """GET /api/runs/{run_id}/recovery-save/{player} — that player's archived SaveRAM bytes.

        Only a recovered run has them, only from the checkpoint its registry entry names, and the
        path never leaves the Manager: the bytes are the checkpoint's own, hash-labelled. F2: an
        unbound checkpoint (hash/provenance/source drift) is refused exactly like a missing one.
        """
        run_id = request.match_info.get("run_id", "")
        player = request.match_info.get("player", "")
        if player not in ("a", "b"):
            return web.json_response({"ok": False, "error": "unknown player"}, status=404)
        run = _find_run(_load_registry(), run_id)
        recovered = (run or {}).get("recovered_from") or {}
        if not recovered:
            return web.json_response({"ok": False, "error": "this run has no recovery save"}, status=404)
        source_dir = _run_directory(recovered["run_id"])
        if source_dir is None:
            return web.json_response({"ok": False, "error": "this run has no recovery save"}, status=404)
        from server.gen1_run_config import FILENAME as RUNTIME_FILENAME
        from server.paired_save_checkpoints import PairedCheckpointStore
        from server.protocol import decode_frame
        try:
            checkpoint = await asyncio.to_thread(PairedCheckpointStore(source_dir).load, recovered["checkpoint_id"])
            run_spec = decode_frame((source_dir / RUNTIME_FILENAME).read_bytes())
            binding_error = _checkpoint_binding_error(checkpoint.manifest, recovered, run_spec, recovered["run_id"])
            if binding_error is not None:
                raise ValueError(binding_error)
            data = checkpoint.save_bytes(player)
        except Exception as problem:
            log.warning("recovery save for %s did not validate: %s", run_id, problem)
            return web.json_response({"ok": False, "error": "recovery save unavailable"}, status=404)
        return web.Response(body=data, content_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{player}.SaveRAM"',
                     "X-SLink-Save-SHA256": hashlib.sha256(data).hexdigest()})

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
        active = await self._active_stream_run()
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

def _lan_addresses() -> list[str]:
    """Best-effort non-loopback IPv4 addresses of this host. Never raises: a machine with no
    usable interface still starts, it just cannot tell a partner where to connect."""
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address and address not in found and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    return found


def startup_banner(host: str, port: int) -> list[str]:
    """The lines a human reads at startup. On 0.0.0.0 the partner's URL matters as much as
    the local one: the second machine cannot reach 'localhost'."""
    display = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
    lines = [f"SLink Manager running at http://{display}:{port}/",
             f"Stream overlays at http://{display}:{port}/stream (fixed port — safe for OBS)"]
    if host == "0.0.0.0":
        for address in _lan_addresses():
            lines.append(f"Partner joins at: http://{address}:{port}/")
        lines.append(f"Allow inbound TCP {port} (Manager) plus each run's TCP/HTTP ports in the firewall")
    return lines


async def main(host: str, port: int):
    manager = RunManager(bind_host=host, manager_port=port)
    app = web.Application(middlewares=[csrf_protection, theme_cache, registry_errors])
    setup_templating(app)

    # Run-management routes
    app.router.add_get("/",                           manager.handle_index)
    app.router.add_get("/api/runs",                   manager.handle_list)
    app.router.add_get("/api/runs/{run_id}",          manager.handle_run)
    app.router.add_post("/api/runs/new",              manager.handle_new)
    app.router.add_post("/api/runs/{run_id}/start",   manager.handle_start)
    app.router.add_post("/api/runs/{run_id}/stop",    manager.handle_stop)
    app.router.add_post("/api/runs/{run_id}/archive", manager.handle_archive)
    app.router.add_post("/api/runs/{run_id}/delete",  manager.handle_delete)
    app.router.add_get("/api/runs/{run_id}/launcher/{player}", manager.handle_launcher)
    app.router.add_get("/api/runs/{run_id}/cartridge/{player}", manager.handle_run_cartridge)
    app.router.add_post("/api/runs/gen1", manager.handle_create_gen1)
    app.router.add_post("/api/runs/{run_id}/randomize", manager.handle_randomize)
    app.router.add_post("/api/runs/{run_id}/cartridges", manager.handle_cartridges)
    app.router.add_get("/api/runs/{run_id}/live",     manager.handle_run_live)
    app.router.add_post("/api/runs/{run_id}/checkpoint", manager.handle_run_checkpoint)
    app.router.add_get("/api/runs/{run_id}/checkpoint/{request_id}", manager.handle_run_checkpoint_status)
    app.router.add_get("/api/runs/{run_id}/checkpoints", manager.handle_run_checkpoints)
    app.router.add_post("/api/runs/{run_id}/recover", manager.handle_recover)
    app.router.add_get("/api/runs/{run_id}/recovery-save/{player}", manager.handle_recovery_save)

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
    app.router.add_get("/api/events",         manager.handle_proxy_events)
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
    for line in startup_banner(host, port):
        log.info(line)

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
