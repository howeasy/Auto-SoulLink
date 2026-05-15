"""server/obs_controller.py — OBS WebSocket integration for SLink.

Controls OBS Studio scene switching based on Soul Link game events.
Uses obs-websocket v5 (built into OBS 28+) via the simpleobsws library.

Two players each have their own OBS instance (separate machines or localhost).
Trigger rules map game events to scene changes with per-player filtering.

Config stored at: data/obs_config.json  (global — not per-run)

Usage (inside SLinkServer):
    self.obs = OBSController(config_path)
    self.obs.start_workers()           # call after asyncio loop starts
    ...
    self.obs.submit_trigger("battle_start", "a")   # non-blocking, from _dispatch
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Optional

log = logging.getLogger(__name__)

try:
    import simpleobsws
    _OBS_AVAILABLE = True
except ImportError:
    _OBS_AVAILABLE = False
    log.warning("simpleobsws not installed — OBS integration disabled. Run: pip install simpleobsws")


# ── default config ─────────────────────────────────────────────────────────────

_DEFAULT_CONFIG: dict = {
    "enabled": False,
    "connections": {
        "a": {"host": "", "port": 4455, "password": ""},
        "b": {"host": "", "port": 4455, "password": ""},
    },
    "triggers": [],
}

# All recognized trigger names (for UI dropdowns and validation)
ALL_TRIGGER_EVENTS = [
    "battle_start",
    "wild_battle_start",
    "trainer_battle_start",
    "battle_end",
    "faint",
    "link_death",
    "whiteout",
    "capture",
    "shiny",
    "linked",
    "dead_zone",
    "area_enter",
    "area_enter_new",
    "battle_start_new",
    "party_to_box",
    "box_to_party",
    "run_over",
    "memorialize_done",
]


class OBSController:
    """Manages OBS WebSocket connections and game-event-driven scene switching.

    Thread/coroutine model:
    - submit_trigger() is SYNCHRONOUS — safe to call from _dispatch() without await.
    - One asyncio worker task per player serialises all OBS I/O.
    - Workers include a reconnect loop; OBS failures never propagate to the caller.
    - Coalescing queues (maxsize=1): only the latest pending scene matters.
    """

    def __init__(self, config_path: str):
        self._config_path = config_path
        self._config: dict = {}
        self._clients: dict[str, Optional["simpleobsws.WebSocketClient"]] = {"a": None, "b": None}
        self._queues: dict[str, asyncio.Queue] = {
            "a": asyncio.Queue(maxsize=1),
            "b": asyncio.Queue(maxsize=1),
        }
        self._workers: dict[str, Optional[asyncio.Task]] = {"a": None, "b": None}
        self._reconnect_tasks: dict[str, Optional[asyncio.Task]] = {"a": None, "b": None}
        self._status: dict[str, str] = {"a": "disconnected", "b": "disconnected"}
        self.load_config()

    # ── config ──────────────────────────────────────────────────────────────────

    def load_config(self):
        if not os.path.exists(self._config_path):
            self._config = dict(_DEFAULT_CONFIG)
            self._config["connections"] = {
                "a": dict(_DEFAULT_CONFIG["connections"]["a"]),
                "b": dict(_DEFAULT_CONFIG["connections"]["b"]),
            }
            self._config["triggers"] = []
            return
        try:
            with open(self._config_path) as f:
                data = json.load(f)
            cfg = dict(_DEFAULT_CONFIG)
            cfg["enabled"] = data.get("enabled", False)
            cfg["connections"] = {
                "a": {**_DEFAULT_CONFIG["connections"]["a"], **data.get("connections", {}).get("a", {})},
                "b": {**_DEFAULT_CONFIG["connections"]["b"], **data.get("connections", {}).get("b", {})},
            }
            cfg["triggers"] = data.get("triggers", [])
            self._config = cfg
        except Exception as e:
            log.warning(f"[OBS] Failed to load config: {e}")
            self._config = dict(_DEFAULT_CONFIG)

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "w") as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            log.warning(f"[OBS] Failed to save config: {e}")

    def get_config_safe(self) -> dict:
        """Return config with passwords redacted (for API responses)."""
        cfg = dict(self._config)
        conns = {}
        for pid, conn in cfg.get("connections", {}).items():
            c = dict(conn)
            c["password"] = ""  # never expose passwords
            conns[pid] = c
        cfg["connections"] = conns
        return cfg

    # ── worker lifecycle ─────────────────────────────────────────────────────────

    def start_workers(self):
        """Start per-player worker tasks. Call once after the asyncio loop is running."""
        for pid in ("a", "b"):
            self._start_worker(pid)

    def _start_worker(self, player_id: str):
        t = self._workers.get(player_id)
        if t and not t.done():
            return
        self._workers[player_id] = asyncio.ensure_future(self._worker(player_id))

    def stop_workers(self):
        """Cancel all worker tasks and disconnect cleanly."""
        for pid in ("a", "b"):
            t = self._workers.get(pid)
            if t and not t.done():
                t.cancel()
            rt = self._reconnect_tasks.get(pid)
            if rt and not rt.done():
                rt.cancel()

    async def apply_new_config(self, new_config: dict):
        """Hot-reload: stop workers, swap config, restart workers."""
        self.stop_workers()
        # Disconnect existing clients cleanly
        for pid in ("a", "b"):
            c = self._clients.get(pid)
            if c:
                try:
                    await c.disconnect()
                except Exception:
                    pass
                self._clients[pid] = None
                self._status[pid] = "disconnected"
        self._config = new_config
        self.save_config()
        # Re-initialise queues so no stale scenes carry over
        self._queues = {
            "a": asyncio.Queue(maxsize=1),
            "b": asyncio.Queue(maxsize=1),
        }
        self.start_workers()

    # ── trigger submission (synchronous, from _dispatch) ────────────────────────

    def _push_scene(self, player_id: str, scene: str):
        """Internal: push a resolved scene onto the coalescing queue for one player."""
        q = self._queues[player_id]
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            q.put_nowait(scene)
        except asyncio.QueueFull:
            pass

    def submit_fired(self, fired_list: list):
        """Priority-resolve multiple simultaneous triggers; submit at most one scene per target.

        fired_list: [(trigger_name, src_player_id, metadata_dict), ...]

        Rules are evaluated in list order (index 0 = highest priority).
        For each target player, the FIRST matching rule across all fired events wins —
        lower-indexed rules can never be overwritten by higher-indexed ones.

        Called synchronously from SLinkServer._emit_obs_triggers().
        """
        if not _OBS_AVAILABLE:
            return
        if not self._config.get("enabled"):
            return
        if not fired_list:
            return

        # winners[target_player] = scene_name (set once; first rule match wins)
        winners: dict[str, str] = {}

        for rule in self._config.get("triggers", []):
            if len(winners) == 2:
                break  # both players already resolved
            scene = rule.get("scene", "")
            if not scene:
                continue
            rule_event = rule.get("event")
            pf = rule.get("player_filter", "any")
            target = rule.get("target", "own")
            area_filter = rule.get("area_id_filter", "")

            for (ev, src_player, meta) in fired_list:
                if ev != rule_event:
                    continue
                if pf not in ("any", src_player):
                    continue
                if area_filter and meta.get("area_id") != area_filter:
                    continue

                # This rule matches — resolve target players
                if target == "own":
                    tgts = [src_player]
                elif target == "both":
                    tgts = ["a", "b"]
                elif target in ("a", "b"):
                    tgts = [target]
                else:
                    tgts = [src_player]

                for tgt in tgts:
                    if tgt not in winners:
                        winners[tgt] = scene

                break  # rule matched; move on to next rule

        for tgt, scene in winners.items():
            self._push_scene(tgt, scene)

    def submit_trigger(self, trigger_name: str, player_id: str, metadata: dict = None):
        """Convenience wrapper: submit a single fired event for priority resolution."""
        self.submit_fired([(trigger_name, player_id, metadata or {})])

    # ── worker ──────────────────────────────────────────────────────────────────

    async def _worker(self, player_id: str):
        """Per-player scene-change worker. Serialises all OBS I/O for one player."""
        log.debug(f"[OBS] Worker started for player {player_id}")
        # Start background reconnect task
        self._reconnect_tasks[player_id] = asyncio.ensure_future(
            self._reconnect_loop(player_id))
        try:
            while True:
                scene = await self._queues[player_id].get()
                await self._send_scene(player_id, scene)
        except asyncio.CancelledError:
            pass
        finally:
            rt = self._reconnect_tasks.get(player_id)
            if rt and not rt.done():
                rt.cancel()
            log.debug(f"[OBS] Worker stopped for player {player_id}")

    async def _send_scene(self, player_id: str, scene: str):
        """Send SetCurrentProgramScene to player's OBS. Silently drops on failure."""
        if not _OBS_AVAILABLE:
            return
        client = self._clients.get(player_id)
        if not client:
            log.debug(f"[OBS] [{player_id}] No client configured, dropping scene '{scene}'")
            return
        if not client.is_identified():
            log.debug(f"[OBS] [{player_id}] Not connected, dropping scene '{scene}'")
            return
        try:
            req = simpleobsws.Request("SetCurrentProgramScene", {"sceneName": scene})
            resp = await client.call(req)
            if resp.ok():
                log.info(f"[OBS] [{player_id}] Scene → '{scene}'")
            else:
                log.warning(
                    f"[OBS] [{player_id}] SetCurrentProgramScene failed: "
                    f"code={resp.requestStatus.code} "
                    f"comment={getattr(resp.requestStatus, 'comment', '')}"
                )
        except Exception as e:
            log.debug(f"[OBS] [{player_id}] Scene change error: {e}")

    async def _reconnect_loop(self, player_id: str):
        """Maintain a persistent connection to the player's OBS instance."""
        backoff = 5
        while True:
            try:
                conn = self._config.get("connections", {}).get(player_id, {})
                host = conn.get("host", "127.0.0.1")
                port = conn.get("port", 4455)
                password = conn.get("password", "")

                if not host:
                    await asyncio.sleep(10)
                    continue

                url = f"ws://{host}:{port}"
                log.info(f"[OBS] [{player_id}] Connecting to {url}")
                self._status[player_id] = "connecting"

                client = simpleobsws.WebSocketClient(url=url, password=password)
                self._clients[player_id] = client

                await client.connect()
                identified = await asyncio.wait_for(
                    client.wait_until_identified(), timeout=10.0)
                if not identified:
                    self._status[player_id] = "auth_failed"
                    log.warning(f"[OBS] [{player_id}] Identification failed (wrong password?)")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue

                self._status[player_id] = "connected"
                backoff = 5
                log.info(f"[OBS] [{player_id}] Connected and identified")

                # Wait until the connection drops
                while client.is_identified():
                    await asyncio.sleep(1)

                self._status[player_id] = "disconnected"
                log.info(f"[OBS] [{player_id}] Connection lost, reconnecting in {backoff}s")

            except asyncio.CancelledError:
                self._status[player_id] = "disconnected"
                break
            except Exception as e:
                self._status[player_id] = "disconnected"
                log.debug(f"[OBS] [{player_id}] Connection error: {e}")

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    # ── utility ─────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return connection status for each player (safe for API responses)."""
        conns = self._config.get("connections", {})
        conn_a = conns.get("a", {})
        conn_b = conns.get("b", {})
        return {
            "available": _OBS_AVAILABLE,
            "enabled": self._config.get("enabled", False),
            "connections": {
                "a": {
                    "host":   conn_a.get("host", ""),
                    "port":   conn_a.get("port", 4455),
                    "status": self._status.get("a", "disconnected"),
                },
                "b": {
                    "host":   conn_b.get("host", ""),
                    "port":   conn_b.get("port", 4455),
                    "status": self._status.get("b", "disconnected"),
                },
            },
            "trigger_count": len(self._config.get("triggers", [])),
        }

    async def list_scenes(self, player_id: str) -> list[str]:
        """Fetch available scene names from a player's OBS. Returns [] on failure."""
        if not _OBS_AVAILABLE:
            return []
        client = self._clients.get(player_id)
        if not client or not client.is_identified():
            return []
        try:
            req = simpleobsws.Request("GetSceneList")
            resp = await client.call(req)
            if not resp.ok():
                return []
            scenes = resp.responseData.get("scenes", [])
            return [s.get("sceneName", "") for s in scenes if s.get("sceneName")]
        except Exception as e:
            log.debug(f"[OBS] [{player_id}] GetSceneList error: {e}")
            return []

    async def connect_player(self, player_id: str):
        """Force (re)connect a player's OBS. Cancels existing reconnect loop and restarts."""
        rt = self._reconnect_tasks.get(player_id)
        if rt and not rt.done():
            rt.cancel()
        # Reset backoff by restarting the reconnect task
        self._reconnect_tasks[player_id] = asyncio.ensure_future(
            self._reconnect_loop(player_id))

    async def disconnect_player(self, player_id: str):
        """Disconnect a player's OBS and cancel reconnect loop."""
        rt = self._reconnect_tasks.get(player_id)
        if rt and not rt.done():
            rt.cancel()
        c = self._clients.get(player_id)
        if c:
            try:
                await c.disconnect()
            except Exception:
                pass
            self._clients[player_id] = None
        self._status[player_id] = "disconnected"

    async def test_scene(self, player_id: str, scene: str) -> dict:
        """Fire a test SetCurrentProgramScene immediately (bypasses queue)."""
        if not _OBS_AVAILABLE:
            return {"ok": False, "error": "simpleobsws not installed"}
        client = self._clients.get(player_id)
        if not client or not client.is_identified():
            return {"ok": False, "error": f"Player {player_id} OBS not connected"}
        try:
            req = simpleobsws.Request("SetCurrentProgramScene", {"sceneName": scene})
            resp = await client.call(req)
            if resp.ok():
                return {"ok": True}
            return {
                "ok": False,
                "error": f"OBS error {resp.requestStatus.code}: "
                         f"{getattr(resp.requestStatus, 'comment', '')}",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


def obs_config_path(data_dir: str = None) -> str:
    """Return the path to obs_config.json (always at global DATA_DIR, not per-run)."""
    from server.state import DATA_DIR as _DATA_DIR
    base = data_dir or _DATA_DIR
    # Walk up to find the root data dir when in manager mode (data/runs/<id>/ → data/)
    # OBS config is global — shared across all runs.
    # Heuristic: if data_dir ends with /runs/<something>, go up two levels.
    if base and os.path.basename(os.path.dirname(base)) == "runs":
        base = os.path.dirname(os.path.dirname(base))
    elif base and os.path.basename(base) != "data":
        # If it's a custom path that isn't obviously a run dir, use it as-is
        pass
    return os.path.join(base, "obs_config.json")
