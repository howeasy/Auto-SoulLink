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
    self.obs.submit_fired([("battle_start", "a", {})])   # non-blocking, from _dispatch
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os

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

# ── area groups ─────────────────────────────────────────────────────────────
#
# Areas are classified into groups by suffix/prefix heuristics so the OBS UI
# can offer "All Routes" / "All Caves" filters that match every area in the
# group. The area_id_filter on a trigger rule may be:
#   ""              → no filter (match any area)
#   "route_1"       → exact area_id match
#   "group:route"   → matches any area whose classify_area() == "route"

AREA_GROUPS: list[dict] = [
    {"id": "route",    "label": "Routes"},
    {"id": "city",     "label": "Cities & Towns"},
    {"id": "cave",     "label": "Caves & Mountains"},
    {"id": "forest",   "label": "Forests"},
    {"id": "tower",    "label": "Towers"},
    {"id": "building", "label": "Buildings & Indoor"},
    {"id": "water",    "label": "Water & Bridges"},
    {"id": "gift",     "label": "Gift / Event"},
    {"id": "other",    "label": "Other"},
]

_CAVE_SPECIALS = frozenset({
    "victory_road", "ice_path", "whirl_islands", "seafoam_islands",
    "dark_cave", "tohjo_falls", "dragons_den",
})

_BUILDING_SPECIALS = frozenset({
    "silph_co", "silph_co_7f",
    "pokemon_league", "team_rocket_hq", "battle_frontier",
    "indigo_plateau", "dreamyard",
})


def classify_area(area_id: str) -> str:
    """Return the AREA_GROUPS id that an area_id belongs to."""
    if not area_id:
        return "other"
    a = area_id.lower()
    if a.startswith("gift_") or a.startswith("egg_") or a == "gift":
        return "gift"
    # Specials checked before pattern rules — e.g. "victory_road" ends in
    # "_road" but is a cave dungeon, not a route.
    if a in _CAVE_SPECIALS:
        return "cave"
    if a in _BUILDING_SPECIALS:
        return "building"
    if a.startswith("route_") or a.endswith("_road"):
        return "route"
    if (a.endswith("_cave") or a.startswith("mt_")
            or a.endswith("_tunnel") or a.endswith("_mountain")
            or a.endswith("_well") or a.endswith("_chasm")
            or a.endswith("_path")):
        return "cave"
    if a.endswith("_forest") or a.endswith("_woods"):
        return "forest"
    if a.endswith("_tower"):
        return "tower"
    if (a.endswith("_bridge") or a.endswith("_bay")
            or a.endswith("_lake") or a.endswith("_falls")
            or a.startswith("lake_")):
        return "water"
    if (a.endswith("_city") or a.endswith("_town")
            or a.endswith("_island") or a.endswith("_isle")):
        return "city"
    if (a.endswith("_mansion") or a.endswith("_lab") or a.endswith("_dojo")
            or a.endswith("_lighthouse") or a.endswith("_castle")
            or a.endswith("_hideout") or a.endswith("_warehouse")
            or a.endswith("_condominiums") or a.endswith("_chamber")
            or a.endswith("_hq") or a.endswith("_pokecenter")
            or a.endswith("_shrine") or a.endswith("_ruins")
            or a.endswith("_yard") or a.endswith("_resort")
            or a.endswith("_storage") or a.endswith("_plant")
            or a.endswith("_park")
            or a.startswith("safari_zone") or a.startswith("ruins_")):
        return "building"
    return "other"


class OBSController:
    """Manages OBS WebSocket connections and game-event-driven scene switching.

    Thread/coroutine model:
    - submit_fired() is SYNCHRONOUS — safe to call from _dispatch() without await.
    - One asyncio worker task per player serialises all OBS I/O.
    - Workers include a reconnect loop; OBS failures never propagate to the caller.
    - Coalescing queues (maxsize=1): only the latest pending scene matters.
    """

    def __init__(self, config_path: str):
        self._config_path = config_path
        self._config: dict = {}
        self._clients: dict[str, simpleobsws.WebSocketClient | None] = {"a": None, "b": None}
        self._queues: dict[str, asyncio.Queue] = {
            "a": asyncio.Queue(maxsize=1),
            "b": asyncio.Queue(maxsize=1),
        }
        self._workers: dict[str, asyncio.Task | None] = {"a": None, "b": None}
        self._reconnect_tasks: dict[str, asyncio.Task | None] = {"a": None, "b": None}
        self._status: dict[str, str] = {"a": "disconnected", "b": "disconnected"}
        self._lifecycle_lock = asyncio.Lock()
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

    async def stop_workers(self):
        """Wait for all workers and connection cleanup to finish."""
        async with self._lifecycle_lock:
            await self._stop_workers()

    async def _stop_workers(self):
        """Stop under the lifecycle lock, detaching workers before cancelling them."""
        workers = [t for t in self._workers.values() if t is not None]
        # Detached workers must not disconnect a replacement in their finally block.
        self._workers = {"a": None, "b": None}
        for task in workers:
            if not task.done():
                task.cancel()
        for pid in ("a", "b"):
            await self._disconnect_player(pid)
        await asyncio.gather(*workers, return_exceptions=True)

    async def apply_new_config(self, new_config: dict):
        """Hot-reload: stop workers, swap config, restart workers."""
        async with self._lifecycle_lock:
            await self._stop_workers()
            self._config = new_config
            self.save_config()
            # Re-initialise queues so no stale scenes carry over.
            self._queues = {
                "a": asyncio.Queue(maxsize=1),
                "b": asyncio.Queue(maxsize=1),
            }
            self.start_workers()

    # ── trigger submission (synchronous, from _dispatch) ────────────────────────

    def _push_scene(self, player_id: str, scene: str):
        """Internal: push a resolved scene onto the coalescing queue for one player."""
        q = self._queues[player_id]
        with contextlib.suppress(asyncio.QueueEmpty):
            q.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(scene)

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
                if area_filter:
                    target_area = meta.get("area_id", "")
                    if area_filter.startswith("group:"):
                        if classify_area(target_area) != area_filter[6:]:
                            continue
                    elif target_area != area_filter:
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

    # ── worker ──────────────────────────────────────────────────────────────────

    async def _worker(self, player_id: str):
        """Per-player scene-change worker. Serialises all OBS I/O for one player."""
        log.debug(f"[OBS] Worker started for player {player_id}")
        try:
            await self.connect_player(player_id)
            while True:
                scene = await self._queues[player_id].get()
                await self._send_scene(player_id, scene)
        except asyncio.CancelledError:
            pass
        finally:
            if self._workers.get(player_id) is asyncio.current_task():
                await self.disconnect_player(player_id)
                self._workers[player_id] = None
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
        if not _OBS_AVAILABLE:
            return
        backoff = 5
        try:
            while True:
                client = None
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
                    else:
                        self._status[player_id] = "connected"
                        backoff = 5
                        log.info(f"[OBS] [{player_id}] Connected and identified")

                        # Wait until the connection drops.
                        while client.is_identified():
                            await asyncio.sleep(1)

                        self._status[player_id] = "disconnected"
                        log.info(f"[OBS] [{player_id}] Connection lost, reconnecting in {backoff}s")
                except Exception as e:
                    self._status[player_id] = "disconnected"
                    log.debug(f"[OBS] [{player_id}] Connection error: {e}")
                finally:
                    if client is not None:
                        await self._disconnect_client(player_id, client)

                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
        finally:
            if (self._reconnect_tasks.get(player_id) is asyncio.current_task()
                    and self._clients.get(player_id) is None):
                self._status[player_id] = "disconnected"

    async def _disconnect_client(self, player_id: str, client):
        """Finish closing an attempt even when cancellation arrives during cleanup."""
        cleanup = asyncio.ensure_future(client.disconnect())
        cancelled = False
        try:
            while True:
                try:
                    await asyncio.shield(cleanup)
                    break
                except asyncio.CancelledError:
                    if cleanup.cancelled():
                        raise
                    cancelled = True
                except Exception as e:
                    log.debug(f"[OBS] [{player_id}] Disconnect error: {e}")
                    break
        finally:
            if self._clients.get(player_id) is client:
                self._clients[player_id] = None
        if cancelled:
            raise asyncio.CancelledError

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
        async with self._lifecycle_lock:
            await self._disconnect_player(player_id)
            # Reset backoff only after the old loop has released its client.
            self._reconnect_tasks[player_id] = asyncio.ensure_future(
                self._reconnect_loop(player_id))

    async def disconnect_player(self, player_id: str):
        """Disconnect a player's OBS and cancel reconnect loop."""
        async with self._lifecycle_lock:
            await self._disconnect_player(player_id)

    async def _disconnect_player(self, player_id: str):
        """Disconnect under the lifecycle lock."""
        rt = self._reconnect_tasks.get(player_id)
        if rt is not None:
            if not rt.done():
                rt.cancel()
            # An expected cancellation of rt is a result; cancellation of this
            # caller must still propagate instead of starting a new connection.
            await asyncio.gather(rt, return_exceptions=True)
            if self._reconnect_tasks.get(player_id) is rt:
                self._reconnect_tasks[player_id] = None
        c = self._clients.get(player_id)
        if c is not None:
            await self._disconnect_client(player_id, c)
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
    return os.path.join(base, "obs_config.json")
