"""
SLink TCP server — Soul Link Nuzlocke coordinator.

Each BizHawk instance connects via LuaSocket and sends newline-delimited JSON
events (area_enter, capture, faint, etc.).  The server responds with a
newline-delimited JSON object: {"commands": [...]}.

A separate HTTP status page is served on --http-port (default 8080) for
live monitoring in a browser.

Transport: asyncio.start_server for the game protocol (no aiohttp on that path).
Status UI:  aiohttp on a separate port — browser-only, never touched by Lua.

Run:
    python -m server.server [--host 0.0.0.0] [--port 54321] [--http-port 8080]
"""

import argparse
import asyncio
import contextlib
import copy
import html
import json
import logging
import logging.handlers
import mimetypes
import ntpath
import os
import re
import shutil
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from server import gen1_admission
from server import runtime_boundary
from server.ui_projection import move_details, player_capabilities
from server.save_identity import SaveIdentity
from server.http_safety import csrf_protection, theme_cache
from server.lua_literals import lua_comment, lua_string
from server.overlay_catalog import build_index_context as _build_stream_index_context

try:
    from aiohttp import web as aiohttp_web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    from .state import DATA_DIR, LINKS_PATH, SoulLinkState
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from server.state import DATA_DIR, LINKS_PATH, SoulLinkState

try:
    from .obs_controller import (
        AREA_GROUPS,
        OBSController,
        classify_area,
        obs_config_path,
    )
except ImportError:
    from server.obs_controller import (
        AREA_GROUPS,
        OBSController,
        classify_area,
        obs_config_path,
    )

try:
    from .templating import resolve_layout, resolve_theme, setup_templating
except ImportError:
    from server.templating import resolve_layout, resolve_theme, setup_templating

import aiohttp_jinja2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

VALID_PLAYERS = {"a", "b"}
_EVENTS_MAX = 200  # max entries kept in memory and written to events.json


def _configure_logging(data_dir: str | None, verbose: bool) -> None:
    """Add a RotatingFileHandler next to links.json.

    Without ``--verbose``: both file and console stay at INFO.
    With    ``--verbose``: file and console are both lowered to DEBUG so every
    state-machine decision is captured for post-mortem analysis.
    """
    log_dir = data_dir if data_dir else DATA_DIR
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "slink.log")

    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root = logging.getLogger()
    root.addHandler(fh)

    if verbose:
        root.setLevel(logging.DEBUG)
        # Also lower the existing console StreamHandler so DEBUG appears on screen.
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler):
                h.setLevel(logging.DEBUG)
        log.info(f"[--verbose] DEBUG logging enabled → {log_path}")
    else:
        log.info(f"Logging to {log_path}")




# ── Damage Calculator integration ────────────────────────────────────────────

_CALC_DIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "calc", "dist")
# Dev-loop convenience: edits under calc/src/ go live on the next page reload
# without running the `npm run build` step. `handle_calc_files` prefers
# src/ when a path exists there and falls through to dist/ otherwise. The
# HTML entry points (`/calc/normal.html`, `/calc/hardcore.html`) only exist
# in dist/ (the src files are `*.template.html` with build placeholders), so
# the fallback resolves them from dist automatically.
_CALC_SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "calc", "src")

_NATURE_NAMES = (
    "Hardy","Lonely","Brave","Adamant","Naughty",
    "Bold","Docile","Relaxed","Impish","Lax",
    "Timid","Hasty","Serious","Jolly","Naive",
    "Modest","Mild","Quiet","Bashful","Rash",
    "Calm","Gentle","Sassy","Careful","Quirky",
)

def _nature_from_key(key: str) -> str:
    """Derive nature name from a monKey ('PERS_HEX:OTID_HEX...')."""
    try:
        return _NATURE_NAMES[int(key.split(":")[0], 16) % 25]
    except Exception:
        return "Hardy"


def _format_killed_at(raw: str | None) -> str:
    """Render an ISO-8601 killed_at timestamp via the browser-locale format
    (matches ``new Date(raw).toLocaleString()``). Falls back to the raw
    value on parse errors so a malformed string is still visible to
    operators.
    """
    if not raw:
        return ""
    try:
        # Preserve tz-aware parsing for the trailing "+00:00" form the state
        # machine emits at server/state.py:_set_killfeed_metadata.
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        return raw
    try:
        return dt.strftime("%-m/%-d/%Y, %-I:%M:%S %p")
    except ValueError:
        # Windows libc has no %- modifier; use %# instead for unpadded fields.
        return dt.strftime("%#m/%#d/%Y, %#I:%M:%S %p")




def _build_mon_entry(key, detail, adapter):
    """Build a JSON-serialisable dict for one mon, suitable for /api/calc/mons."""
    sid = detail.get("species_id", 0)
    if not sid:
        return None
    species = adapter.species_name(sid)
    nature   = _nature_from_key(key)
    abl_name = detail.get("ability_name", "") or adapter.ability_name(detail.get("ability_id", 0), sid)
    item_id  = detail.get("held_item_id", 0)
    item     = adapter.item_name(item_id) if item_id else ""
    raw_moves = [m for m in (detail.get("moves") or []) if m][:4]
    moves = []
    for m in raw_moves:
        if isinstance(m, int):
            name = adapter.move_name(m)
            if name:
                moves.append(name)
        elif isinstance(m, str) and m:
            moves.append(m)
    level    = detail.get("level", 0)
    nick     = detail.get("nickname", "")
    hp       = detail.get("hp", 0)
    maxhp    = max(detail.get("maxHP", 1), 1)
    hp_pct   = max(0, min(100, int(hp / maxhp * 100)))
    disp     = f"{species} ({nick})" if nick and nick != species else species
    lines    = [disp + (f" @ {item}" if item else "")]
    lines   += [f"Ability: {abl_name}" if abl_name else "Ability: None"]
    lines   += [f"Level: {level}", f"{nature} Nature"]
    for m in moves:
        lines.append(f"- {m}")
    return {
        "key":           key,
        "nickname":      nick,
        "species_name":  species,
        "level":         level,
        "nature":        nature,
        "ability_name":  abl_name,
        "item_name":     item,
        "moves":         moves,
        "hp_pct":        hp_pct,
        "hp":            hp,
        "maxHP":         maxhp,
        "status_cond":   detail.get("status_cond", 0),
        "stat_stages":   detail.get("stat_stages"),
        "slot":          detail.get("slot", 999),
        "active":        detail.get("active", False),
        "showdown_paste": "\n".join(lines),
    }


# ── Inline damage-preview widget (lazy-loaded on the status page) ───────────
# Uses the calc engine served at /calc/ — silent no-op if not built.
# Raw string so no {{ }} escaping needed.





# ── Debug page ─────────────────────────────────────────────────────────────────



def _bot_load_config(data_dir: str | None) -> dict:
    """Load bot config from data/twitch_bot.json. Returns defaults if absent."""
    bot_dir = data_dir or DATA_DIR
    path = os.path.join(bot_dir, "twitch_bot.json")
    defaults = {"channel": "", "nick": "", "prefix": "!", "command_cooldown_sec": 5, "enabled": True}
    if not os.path.exists(path):
        return dict(defaults)
    try:
        with open(path) as f:
            cfg = json.load(f)
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(defaults)



def _bot_save_config(data_dir: str | None, cfg: dict):
    """Save bot config to data/twitch_bot.json. Tokens are never stored here — use env vars."""
    bot_dir = data_dir or DATA_DIR
    path = os.path.join(bot_dir, "twitch_bot.json")
    safe = dict(cfg)
    os.makedirs(bot_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump(safe, f, indent=2)


# ── per-connection handler ─────────────────────────────────────────────────────

# A client is considered stale once it has said nothing for this long. The Gen 3 client ticks
# about twice a second and the dashboard polls every 2s, so 10s is far outside normal jitter.
STALE_AFTER_SECS = 10


def _age_secs(ts):
    """Whole seconds since `ts` (an epoch float), or None if there is no timestamp."""
    if not ts:
        return None
    return max(0, int(time.time() - ts))


def _age_label(age):
    """Human 'how long ago' for the players panel. None -> em dash."""
    if age is None:
        return "—"
    if age < 60:
        return f"{age}s ago"
    if age < 3600:
        return f"{age // 60}m ago"
    return f"{age // 3600}h ago"


def _area_tag(name: str) -> str:
    """Abbreviate an area name for the info panel's 4-character label column.

    "Route 3" -> "RT03" reads better than a blind truncation to "Rout", which is why this is not
    just a slice. Purely string handling — no game data — so it is not adapter territory; the name
    itself comes from the adapter.
    """
    m = re.match(r"\s*route\s*(\d+)", name or "", re.I)
    if m:
        return f"RT{int(m.group(1)):02d}"
    return re.sub(r"[^0-9A-Za-z]", "", name or "").upper()[:4]


class SLinkServer:
    def __init__(self, data_dir: str = None, run_id: str = None,
                 run_name: str = "", tcp_port: int = 0,
                 manager_port: int = 0,
                 species_lock: bool = False, gender_lock: bool = False,
                 type_lock: bool = False, explode_mode: bool = False,
                 rival_team_swap: bool = False, overworld_presence: bool = False,
                 native_messages: bool = False, native_sounds: bool = False,
                 battle_calc: bool = True, pc_trade_npc: bool = True):
        self._data_dir = data_dir  # None → use global DATA_DIR (backward compat)
        self._run_id   = run_id
        self._run_name = run_name
        self._tcp_port = tcp_port
        self._manager_port = manager_port
        self._last_seq: dict[str, int] = {}
        self._connection_owners: dict[str, object] = {}
        self._gen1_sessions = gen1_admission.SessionGate()
        self.state = SoulLinkState.load(data_dir=data_dir,
                                        species_lock=species_lock,
                                        gender_lock=gender_lock,
                                        type_lock=type_lock,
                                        explode_mode=explode_mode,
                                        rival_team_swap=rival_team_swap,
                                        overworld_presence=overworld_presence,
                                        native_messages=native_messages,
                                        native_sounds=native_sounds,
                                        battle_calc=battle_calc,
                                        pc_trade_npc=pc_trade_npc)
        # Game adapter — shared with state machine for consistent behavior.
        # Provides both rules and presentation methods.
        self.adapter = self.state.adapter
        # A run may be played on ROMs randomized per player -- same settings, different
        # seeds -- so "what does this route hold" has a different answer for each of them.
        # get_adapter() is not a singleton, so one adapter per player is cheap; absent an
        # entry here a player simply uses the run-global adapter and the shipped tables.
        self._player_adapters: dict[str, object] = {}

        # ── Admission ─────────────────────────────────────────────────────────
        # A run built from randomized ROMs records, per player, the fingerprint of the
        # cartridge the Manager made for them. Until a client proves it is running that
        # cartridge it is ADMITTED to connect and to say hello, and to nothing else --
        # because every other event mutates rule state, and rule state built on the wrong
        # ROM is worse than no run at all.
        #
        # A run with no contract has nothing to check and admits everyone, which is every
        # vanilla run and the entire existing test suite.
        self._rom_contract_mtime: float | None = None
        self._rom_contract = self._load_rom_contract()
        self.admission: dict[str, dict] = {}
        # Track live connections: player_id → {rom_type, last_event, connected}
        self.connected_players: dict[str, dict] = {}
        # Per-player display data (updated from events, used only for status page)
        self.player_area: dict[str, str] = {"a": "", "b": ""}
        self.player_area_id: dict[str, str] = {"a": "", "b": ""}  # raw area_id for state lookups
        self.player_ball_count: dict[str, int] = {"a": 0, "b": 0}
        self.player_badges: dict[str, int] = {"a": 0, "b": 0}
        self.player_kanto_badges: dict[str, int] = {"a": 0, "b": 0}
        self.trainer_name: dict[str, str] = {
            "a": self.state.trainer_names.get("a", ""),
            "b": self.state.trainer_names.get("b", ""),
        }
        self.pc_boxes: dict[str, list] = {"a": [], "b": []}
        # key → {level, hp, maxHP, nickname, species_id, gender} — best-effort party snapshot
        self.party_details: dict[str, dict[str, dict]] = {"a": {}, "b": {}}
        # Persistent per-monKey cache of display info (species_id, nickname, level, gender).
        # Survives party↔box transitions so sprites don't go blank between ticks.
        self._mon_cache: dict[str, dict] = {}
        # Orphan keys already warned about — suppress repeat warnings on every tick.
        self._warned_orphan_keys: set[str] = set()
        self._warned_memorial_keys: set[tuple[str, str]] = set()
        # Last `link_panel` payload sent to each player, so it is re-sent only on change.
        self._last_panel_sig: dict[str, str] = {"a": None, "b": None}
        # Battle state: in_battle flag + enemy team snapshot
        self.battle_state: dict[str, dict] = {
            "a": {"in_battle": False, "is_trainer_battle": False, "enemy_party": [],
                  "trainer_id": 0, "opponent_name": "", "opponent_class": "",
                  "is_doubles": False},
            "b": {"in_battle": False, "is_trainer_battle": False, "enemy_party": [],
                  "trainer_id": 0, "opponent_name": "", "opponent_class": "",
                  "is_doubles": False},
        }
        # Ring buffer of recent events for the stream overlay event feed.
        self._recent_events: deque[dict] = deque(maxlen=_EVENTS_MAX)
        self._events_path = (
            os.path.join(data_dir, "events.json") if data_dir
            else os.path.join(DATA_DIR, "events.json")
        )
        self._load_events()
        # SSE: set of asyncio.Queue (one per connected browser).
        # Each queue holds at most 1 item (coalescing — latest snapshot wins).
        self._sse_clients: set[asyncio.Queue] = set()
        # Rolling backup: copy links.json every 5 min when both players connected.
        self._backup_task: asyncio.Task | None = None
        self._backup_interval = 300  # seconds
        self._backup_max = 6
        self._bot_activity = []   # ring buffer, max 50 entries [{ts, text}]
        self._bot_last_error: str = ""
        self._bot_task = None
        self._bot_instance = None
        # OBS WebSocket integration
        _obs_cfg = obs_config_path(data_dir)
        self.obs = OBSController(_obs_cfg)

    def _get_sprite_html(self, species_id: int, form: int = 0) -> str:
        """Get sprite HTML by delegating to the game adapter.

        Optional `form` byte (default 0) is the alt-form discriminator from Block B
        (Gen 4+). Adapters that ignore it still produce correct base-form sprites.
        """
        return self.adapter.sprite_html(species_id, form)

    _METHOD_ICON: dict[str, str] = {
        "Day":        "☀",
        "Night":      "🌙",
        "Surfing":    "🌊",
        "Rock Smash": "🪨",
        "Old Rod":    "🎣 Old",
        "Good Rod":   "🎣 Good",
        "Super Rod":  "🎣 Super",
    }

    def _ingest_rom_content(self, player_id: str, payload: dict) -> None:
        """Adopt a player's own cartridge tables, or leave them without any.

        Failure is NOT silent and NOT a fallback: a player whose payload we cannot read
        keeps no ROM tables and the UI says the data is unavailable for them. Falling back
        to the shipped tables would print retail species beside a randomized cartridge,
        which is the exact misinformation this exists to remove.
        """
        from server.adapters import game_id_for_rom_type, get_adapter
        failed = False
        try:
            tables = self.adapter.ingest_rom_content(payload)
        except Exception as exc:                      # noqa: BLE001 - report, never adopt
            log.warning("[%s] rom_content rejected — encounter data will be shown as "
                        "unavailable for this player: %s", player_id, exc)
            tables, failed = {}, True
        if tables is None:
            return                                    # this generation cannot read its ROM

        rom_type = self.connected_players.get(player_id, {}).get("rom_type", "")
        game_id = game_id_for_rom_type(rom_type) or self.adapter.game_id
        adapter = get_adapter(game_id, is_rr=self.state.is_rr, rom_type=rom_type)
        adopt = getattr(adapter, "use_rom_encounters", None)
        if adopt is None:
            return
        # THREE STATES, and the middle one is the reason this is not a plain boolean:
        #   no entry here  -> nobody reported a ROM; the shipped tables are all we have
        #   {}             -> a client TRIED and we could not read it; show nothing
        #   populated      -> this cartridge's own tables
        # An unreadable payload must NOT fall back to the shipped tables: the client only
        # sends this when it can see its ROM, so a failure is evidence something is unusual
        # about that ROM, and retail species printed beside a randomized cartridge is the
        # exact misinformation this whole path exists to remove.
        adopt(tables)
        self._player_adapters[player_id] = adapter
        if failed:
            log.info("[%s] encounter data marked unavailable", player_id)
        else:
            log.info("[%s] using this cartridge's own encounter tables (%d areas)",
                     player_id, len(tables))

    def _load_rom_contract(self) -> dict | None:
        """The randomized-ROM contract for this run, if the Manager wrote one.

        Re-read rather than cached for the run's lifetime. The Manager writes this file from
        `handle_randomize` while the server is already up, so a snapshot taken in __init__
        made the gate depend on the ORDER the two were started in: a run whose server came
        up first kept `_rom_contract = None` and admitted everyone, forever, with no way to
        notice. The mtime check keeps it to one stat() per hello.
        """
        base = self._data_dir or DATA_DIR
        path = os.path.join(base, "rom_contract.json")
        if not os.path.exists(path):
            self._rom_contract_mtime = None
            return None
        try:
            with open(path, "rb") as f:
                raw = f.read(131073)
            if len(raw) > 131072:
                raise ValueError("cartridge contract exceeds 128 KiB")
            contract = gen1_admission.decode_frame(raw)
        except (OSError, ValueError) as exc:
            # Fail CLOSED and say so. A contract we cannot read is not the same as no
            # contract: the run was built from randomized ROMs and we have lost the only
            # record of which ones, so admitting anyone would defeat the check entirely.
            log.error("rom_contract.json is unreadable (%s) — every player will be "
                      "rejected until it is fixed or removed", exc)
            return {"unreadable": True, "players": {}}
        log.debug("loaded cartridge contract (UPR %s, categories %s)",
                 contract.get("upr_version", "?"), contract.get("categories", []))
        return contract

    def _refresh_rom_contract(self, *, force=False) -> None:
        """Pick up a contract the Manager wrote after this server started."""
        base = self._data_dir or DATA_DIR
        path = os.path.join(base, "rom_contract.json")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if force or mtime != getattr(self, "_rom_contract_mtime", "unset"):
            self._rom_contract = self._load_rom_contract()
            self._rom_contract_mtime = mtime

    def _decide_admission(self, player_id: str, msg: dict) -> dict:
        """Re-run on EVERY hello, so a reconnect or a swapped ROM is re-checked.

        Returns the admission record; never raises. A player who cannot be admitted is not
        an error condition, it is a run that has not started for them yet.
        """
        if not self._rom_contract:
            return {"state": "admitted", "reason": "no randomized-ROM contract for this run"}
        if self._rom_contract.get("unreadable"):
            return {"state": "rejected", "reason": "this run's rom_contract.json could not be read"}

        expected = (self._rom_contract.get("players") or {}).get(player_id) or {}
        want = expected.get("fingerprint")
        if not want:
            return {"state": "rejected",
                    "reason": f"the contract names no cartridge for player {player_id}"}

        payload = msg.get("rom_content")
        if not payload:
            return {"state": "rejected",
                    "reason": "this run is bound to randomized ROMs, but the client did not "
                              "report its cartridge — an older client, or a BizHawk build "
                              "with no flat ROM domain"}
        try:
            got = self.adapter.rom_content_fingerprint(payload)
        except Exception as exc:                      # noqa: BLE001
            # Distinct from a mismatch on purpose: "unreadable report" and "wrong ROM" send
            # whoever is debugging to different places.
            return {"state": "rejected",
                    "reason": f"the client's cartridge report could not be read: {exc}"}
        if got is None:
            return {"state": "admitted",
                    "reason": "this generation cannot fingerprint its ROM; nothing to check"}
        if got != want:
            return {"state": "rejected",
                    "reason": (f"this is not the cartridge built for player {player_id} "
                               f"(reported {got[:12]}, expected {want[:12]})")}
        return {"state": "admitted", "reason": "cartridge matches the contract"}

    def is_admitted(self, player_id: str) -> bool:
        """A player with no verdict yet is `contract_pending`, not admitted.

        The default used to be "admitted" so that an uncontracted run behaved exactly as it
        always had -- correct for that case, and wrong for the contracted one. Nothing
        requires a hello before `_dispatch`: `handle_client` takes the player id from the
        message itself, so a client whose first line is a `capture` (a reconnect after a
        crash that lost the hello, or any client that reorders) found no record, took the
        default, and mutated rule state on a cartridge nobody had checked.

        The distinction is only meaningful when there IS something to check, so an
        uncontracted run keeps the old behaviour exactly.
        """
        state = (getattr(self, "admission", {}).get(player_id) or {}).get("state")
        if state is None:
            # getattr for the same reason adapter_for uses it: some tests build an
            # SLinkServer without running __init__.
            return not getattr(self, "_rom_contract", None)
        return state == "admitted"

    def _player_has_panel(self, player_id: str) -> bool:
        """Does THIS player's cartridge have the native panel?

        Per player, not per adapter. On Gen 1 the panel comes from the companion ROM patch,
        so a patched and an unpatched cartridge can sit in the same run and the generation
        alone cannot answer. A client that can render it says so at hello; one that says
        nothing gets no panel payloads rather than a stream of unknown-command warnings.

        The adapter still has a veto: a generation with no panel at all never sends one,
        whatever a client claims.
        """
        adapter = self.adapter_for(player_id)
        if not adapter.supports_info_panel():
            return False
        reported = (self.connected_players.get(player_id) or {}).get("panel")
        if reported is None:
            # Generations whose clients predate the capability report keep working: they
            # were already receiving the panel on the adapter's say-so.
            return adapter.info_panel_width() == 0
        return bool(reported)

    def adapter_for(self, player_id: str):
        """The adapter that describes THIS player's cartridge.

        Only content differs per player, never rules: the supported randomizer settings
        deliberately exclude types, evolutions, movesets and base stats, so the species and
        type clauses stay seed-independent and keep using the run-global adapter.
        """
        # getattr, not a plain attribute read: some tests build an SLinkServer without
        # running __init__, and a lookup helper should answer for those rather than raise.
        # A class-level dict would be shared across instances, which is worse.
        return (getattr(self, "_player_adapters", None) or {}).get(player_id) or self.adapter

    def _encounter_html(self, area_id: str, player_id: str = "",
                        key_prefix: str = "") -> str:
        """Return collapsible encounter widget HTML for an area, or '' if none.

        Only populated for RR runs (adapter.encounter_table returns non-None).
        ``player_id`` namespaces the DOM id + localStorage key so two cards in
        the same area don't share one collapsed/expanded state.
        ``key_prefix`` lets callers further namespace the keys when the same
        widget is rendered in multiple views simultaneously (e.g. combined
        view passes "lp:" so its IDs don't collide with the split view's).

        ``player_id`` also selects WHOSE tables these are. It used to namespace the DOM id
        and nothing else, so both cards rendered one run-global table -- fine until two
        players hold ROMs randomized with different seeds, when it means one of them is
        shown the other's route.
        """
        enc = self.adapter_for(player_id).encounter_table(area_id)
        if not enc:
            return ""

        methods_html = ""
        for method, entries in enc.items():
            if not entries:
                continue
            # A multi-floor dungeon labels its methods "Grass B1F" / "Water B4F", so the
            # icon is looked up on the BASE method. Without this a floor loses its icon
            # and reads as a different kind of encounter from the one above it.
            icon = self._METHOD_ICON.get(method.split(" ")[0], "")
            label = f"{icon} {method}" if icon else method
            rows = ""
            for e in entries:
                sid = e.get("species_id", 0)
                name = e.get("name", "?")
                rate = e.get("rate", 0)
                min_lv = e.get("min_level", 0)
                max_lv = e.get("max_level", 0)
                # Rate colour: hsl(rate*2, 85%, 45%) — green=high, red=low
                # Hue carries the meaning (red = rare, green = common) so it stays; only the
                # LIGHTNESS is theme-controlled. Fixed at 48% this was 1.06:1 on the light theme —
                # a yellow "20%" on near-white. --enc-rate-l lets each theme pick a readable one
                # without flattening the gradient into a single colour.
                rate_color = f"hsl({min(rate * 2, 120)}, 85%, var(--enc-rate-l, 48%))"
                if sid:
                    sprite_tag = self.adapter.sprite_html(sid)
                    # Replace mon-sprite class with enc-sprite for smaller 20px icon
                    sprite_tag = sprite_tag.replace('class="mon-sprite"', 'class="enc-sprite"')
                else:
                    sprite_tag = '<span class="enc-sprite"></span>'
                lv_text = f"lv{min_lv}" if min_lv == max_lv else f"lv{min_lv}–{max_lv}"
                rows += (
                    f'<div class="enc-entry">'
                    f'{sprite_tag}'
                    f'<span class="enc-name">{name}</span>'
                    f'<span class="enc-rate" style="color:{rate_color}">{rate}%</span>'
                    f'<span class="enc-lv">({lv_text})</span>'
                    f'</div>'
                )
            methods_html += (
                f'<div class="enc-method">'
                f'<span class="enc-method-label">{label}</span>'
                f'<div class="enc-list">{rows}</div>'
                f'</div>'
            )

        if not methods_html:
            return ""
        # data-details-key + matching id give idiomorph a stable persistent
        # element to preserve across each 2 s polling morph. With both:
        #   * idiomorph keeps the same DOM node (matched by id) instead of
        #     re-creating it — so the attribute-update phase is the only
        #     path that touches `open`, and our beforeAttributeUpdated hook
        #     in dashboard.js vetoes that removal.
        #   * data-details-key drives the localStorage cross-session save
        #     so a hard refresh still lands the widget in the right state.
        pid_seg = f"{player_id}:" if player_id else ""
        key = f"{key_prefix}enc:{pid_seg}{html.escape(area_id, quote=True)}"
        return (
            f'<details class="enc-widget" id="d-{key}" data-details-key="{key}">'
            f'<summary><svg class="inline-ico" aria-hidden="true"><use href="#i-target"/></svg> Encounters</summary>'
            f'<div class="enc-methods">{methods_html}</div>'
            f'</details>'
        )

    def _trainer_panel_html(self, area_id: str, player_id: str = "",
                            key_prefix: str = "",
                            highest_party_level: int = 0) -> str:
        """Return collapsible Upcoming Trainers widget HTML for an area, or ''.

        Each area row expands to show the trainer's full curated party
        (species, level, ability, item, moves).

        ``key_prefix`` is prepended to the data-details-key/id so the same
        widget can be rendered in both the split AND combined views without
        DOM-id collisions (both views live in the DOM simultaneously and are
        toggled via body.lp-view). Pass "lp:" from combined-view callers.

        ``highest_party_level`` is the level of the player's strongest
        owned mon at the moment of rendering. The spreadsheet expresses
        many trainer mon levels as "Max Level - N" / "Highest Lv -N",
        which the game resolves at fight time as
        ``max(1, highest_party_level + level_offset)`` (offset <= 0). Pass
        0 to fall back to the static `level` value baked into the JSON.

        Mirrors `_encounter_html`'s structure exactly so idiomorph morph
        behaviour, `data-details-key` localStorage persistence, and the
        existing CSS variable palette all work without new infrastructure.
        """
        if not area_id:
            return ""
        # THIS PLAYER'S adapter, not the run-global one. Trainer parties and levels are an
        # ALLOWED randomization category, so on a randomized pair the two cartridges can
        # disagree about what a trainer fields -- and a widget built from whichever adapter
        # the first hello happened to install would show one player the other's game.
        # (Today only Gen 3 populates these, and Gen 1 returns [] so the widget renders
        # nothing at all. The global lookup was still the wrong source to read from.)
        adapter = self.adapter_for(player_id) if player_id else self.adapter
        try:
            trainer_ids = adapter.trainers_for_area(area_id)
        except Exception:
            trainer_ids = []
        if not trainer_ids:
            return ""

        # Resolve briefs.
        briefs: list[tuple[int, dict]] = []
        for rt_id in trainer_ids:
            brief = adapter.trainer_brief(rt_id)
            if brief:
                briefs.append((rt_id, brief))

        # Bucket by (name, cap_bucket) — candidates for grouping. Then
        # decide row-vs-variant based on whether fight_labels are DISTINCT.
        # Distinct labels = true starter-variants ("If Rival Has X/Y/Z"
        # for one rival encounter) → render as ONE row with sub-blocks.
        # Identical or missing labels = separate encounters (Left/Right
        # Rocket Guards both labeled "Rocket Hide.") → render as
        # individual rows. Sequential same-name fights at different caps
        # land in different cap buckets and get progress-filtered.
        _CAP_BUCKET = 10
        groups: list[list[tuple[int, dict]]] = []
        candidates: dict[tuple[str, int], list[tuple[int, dict]]] = {}
        order: list[tuple[str, int]] = []
        for rt_id, brief in briefs:
            nm_key = brief.get("name", "").title() or f"#{rt_id}"
            cap = None
            fl = brief.get("fight_label") or ""
            if hasattr(self.adapter, "milestone_cap_for_fight_label"):
                cap = self.adapter.milestone_cap_for_fight_label(fl)
            if cap is None:
                cap = brief.get("level_cap") or 0
            cap_bucket = (cap or 0) // _CAP_BUCKET
            key = (nm_key, cap_bucket)
            if key not in candidates:
                candidates[key] = []
                order.append(key)
            candidates[key].append((rt_id, brief))
        # Promote each candidate bucket into one or more groups: a single
        # group when fight_labels are all distinct (true variants), one
        # group per entry otherwise.
        for key in order:
            bucket = candidates[key]
            labels = [b.get("fight_label") or "" for _, b in bucket]
            distinct_nonempty = (
                len(bucket) > 1
                and all(labels)
                and len(set(labels)) == len(labels)
            )
            if distinct_nonempty:
                groups.append(bucket)
            else:
                for entry in bucket:
                    groups.append([entry])

        # Sequential-fight filter: when the SAME trainer name has multiple
        # cap buckets at the same area (i.e. they're different fights at
        # different points in the story), hide groups not currently relevant
        # to the player's progress. For each name with >1 bucket:
        #   • Skip "past" buckets (cap + window < highest)
        #   • Keep the FIRST upcoming bucket only (lowest cap above highest)
        #   • If the player is past all buckets, keep the latest bucket only.
        def _bucket_cap(group_list: list[tuple[int, dict]]) -> int:
            # All entries in a bucket share approximately the same cap.
            _, b = group_list[0]
            fl = b.get("fight_label") or ""
            c = None
            if hasattr(self.adapter, "milestone_cap_for_fight_label"):
                c = self.adapter.milestone_cap_for_fight_label(fl)
            return c if c is not None else (b.get("level_cap") or 0)

        if highest_party_level > 0:
            # Re-bucket groups by trainer name so we can pick the most
            # progress-relevant fight per trainer. `groups` was flattened
            # above; we need name-level visibility for the filter.
            by_name: dict[str, list[list[tuple[int, dict]]]] = {}
            for g in groups:
                if not g:
                    continue
                nm = (g[0][1].get("name") or "").title() or "?"
                by_name.setdefault(nm, []).append(g)
            for _nm, buckets in by_name.items():
                if len(buckets) < 2:
                    continue
                ordered = sorted(buckets, key=_bucket_cap)
                # Sequential filtering only applies when the buckets cover
                # genuinely different progress milestones (e.g. Pre-Surge vs
                # Post-Surge Bugsy). When all buckets share roughly the
                # same cap (Left Guard + Right Guard at the same hideout),
                # they're simultaneous encounters in the same playthrough
                # and ALL should remain visible.
                caps = [_bucket_cap(g) for g in ordered]
                if (max(caps) - min(caps)) < _CAP_BUCKET:
                    continue
                keep = None
                for g in ordered:
                    if _bucket_cap(g) >= highest_party_level - _CAP_BUCKET:
                        keep = g
                        break
                if keep is None:
                    keep = ordered[-1]
                for g in ordered:
                    if g is not keep:
                        for entry in g:
                            entry[1]["_filtered_out"] = True

        # Helper: classify a fight against the player's current progress.
        # Returns ("past" | "current" | "future" | "unknown", css_class).
        # "Pre X" milestone cap → fight happens BEFORE that cap; "Post X" →
        # fight happens AFTER. A fight with cap=C against highest_party_level
        # h is:
        #   • past    when h is well past C (we've moved on to later content)
        #   • future  when h is far below C (we haven't earned the right to be
        #             there yet — adjacent fights show up in the panel anyway,
        #             but visually de-emphasised so the *current* one pops)
        #   • current otherwise (within +/-CURRENT_WINDOW of C)
        _CURRENT_WINDOW = 10
        def _classify_fight(fight_brief: dict) -> tuple[str, int | None]:
            fl = fight_brief.get("fight_label") or ""
            cap = self.adapter.milestone_cap_for_fight_label(fl) \
                  if hasattr(self.adapter, "milestone_cap_for_fight_label") else None
            if cap is None or highest_party_level <= 0:
                return ("unknown", cap)
            if highest_party_level >= cap + _CURRENT_WINDOW:
                return ("past", cap)
            if highest_party_level <= cap - _CURRENT_WINDOW:
                return ("future", cap)
            return ("current", cap)

        rows_html = ""
        for group in groups:
            variants = group  # list[(rt_id, brief)]
            # Skip groups the sequential-fight filter marked as not relevant
            # to the player's current progress (handled above).
            if any(b.get("_filtered_out") for _, b in variants):
                continue
            primary_id, primary_brief = variants[0]
            # The first variant's brief drives the summary; remaining variants
            # are surfaced as selectable tabs inside the expanded body.
            rt_id = primary_id
            brief = primary_brief
            cls_raw  = brief.get("class", "") or ""
            name_raw = brief.get("name", "") or f"Trainer #{rt_id}"
            # Collapse "Team Rocket Grunt" + name "Grunt" → just the class;
            # avoids "TEAM ROCKET GRUNT Grunt" duplication.
            if name_raw.strip().lower() in cls_raw.strip().lower().split():
                name_raw = ""
            cls   = html.escape(cls_raw)
            name  = html.escape(name_raw)
            party = brief.get("party") or []
            party_count = len(party)
            n_variants = len(variants)
            state, _ms_cap = _classify_fight(brief)
            def _render_party(mons: list[dict]) -> str:
                """Render a single variant's party as a stack of mon rows.

                Levels are resolved at render time: when a mon has a
                level_offset (relative "Max Level - N" entry from the
                spreadsheet) AND the caller passed a non-zero
                highest_party_level, we recompute the level dynamically.
                Otherwise the static fallback baked into the JSON is used.
                A small "rel" hint appears next to dynamically-computed
                levels so the user knows the number reflects their team.
                """
                out = ""
                for mon in mons:
                    species = html.escape(str(mon.get("species") or "?"))
                    level    = mon.get("level") or 0
                    offset   = mon.get("level_offset")
                    dynamic  = False
                    if (isinstance(offset, int) and highest_party_level > 0):
                        level = max(1, highest_party_level + offset)
                        dynamic = True
                    ability = html.escape(str(mon.get("ability") or ""))
                    item    = html.escape(str(mon.get("item") or ""))
                    nature  = html.escape(str(mon.get("nature") or ""))
                    moves   = mon.get("moves") or []
                    moves_html = ""
                    if moves:
                        move_chips = "".join(
                            f'<span class="tr-move">{html.escape(str(m))}</span>'
                            for m in moves if m and m != "-"
                        )
                        moves_html = f'<div class="tr-moves">{move_chips}</div>'
                    if isinstance(level, int) and level > 0:
                        lv_text = f"Lv{level}"
                        if dynamic:
                            # Show the rule that produced this number so the
                            # player understands why it scales with their team.
                            if offset == 0:
                                lv_text += ' <span class="tr-lv-rule">(Max Lv)</span>'
                            else:
                                lv_text += (f' <span class="tr-lv-rule">'
                                            f'(Max Lv {offset:+d})</span>')
                    else:
                        lv_text = "Lv?"
                    meta_bits = []
                    # Column-aligned table of optional meta chips — kept on one line each.
                    if ability: meta_bits.append(f'<span class="tr-ability">{ability}</span>')   # noqa: E701
                    if item:    meta_bits.append(f'<span class="tr-item">@ {item}</span>')       # noqa: E701
                    if nature:  meta_bits.append(f'<span class="tr-nature dim">{nature}</span>') # noqa: E701
                    meta_html = (' · '.join(meta_bits)) if meta_bits else ''
                    # Built outside the f-string: a backslash inside an f-string expression
                    # is Python 3.12+ syntax and would not parse on 3.11.
                    meta_row = f'<div class="tr-mon-meta">{meta_html}</div>' if meta_html else ''
                    out += (
                        f'<div class="tr-party-row">'
                        f'<div class="tr-mon-hdr">'
                        f'<span class="tr-species">{species}</span>'
                        f'<span class="tr-lv">{lv_text}</span>'
                        f'</div>'
                        f'{meta_row}'
                        f'{moves_html}'
                        f'</div>'
                    )
                return out

            if n_variants == 1:
                mons_html = _render_party(party)
            else:
                # Render each variant in a sub-block. Header text comes from
                # the variant's own fight_label ("If Rival Has Squirtle",
                # "Pre Lt. Surge", "Team Two", …) when present — this is the
                # spreadsheet author's stated trigger condition. Falls back
                # to "Variant N" when no label is available. Each variant
                # also gets its own Calc button so the user can load the
                # specific matchup into the Prep tab.
                blocks = []
                for vi, (v_rt_id, v_brief) in enumerate(variants, start=1):
                    v_party = v_brief.get("party") or []
                    lead_species = v_party[0].get("species", "?") if v_party else "?"
                    v_label = v_brief.get("fight_label") or f"Variant {vi}"
                    v_calc_label = v_brief.get("calc_label", "") or ""
                    blocks.append(
                        f'<div class="tr-variant">'
                        f'<div class="tr-variant-hdr">'
                        f'<span class="tr-variant-label">{html.escape(v_label)}</span>'
                        f'<span class="tr-variant-lead dim">lead: '
                        f'{html.escape(str(lead_species))}</span>'
                        f'<button type="button" class="tr-calc-btn tr-variant-calc" '
                        f'data-pid="{html.escape(player_id, quote=True)}" '
                        f'data-tid="{v_rt_id}" '
                        f'data-calc-label="{html.escape(v_calc_label, quote=True)}" '
                        f'title="Open this variant in RR Calc Prep tab">'
                        f'&#9876;</button>'
                        f'</div>'
                        f'{_render_party(v_party)}'
                        f'</div>'
                    )
                mons_html = '<div class="tr-variants">' + ''.join(blocks) + '</div>'
            pid_seg = f"{player_id}:" if player_id else ""
            row_key = f"{key_prefix}tr:{pid_seg}{html.escape(area_id, quote=True)}:{rt_id}"
            # Summary metadata: party size + level cap + fight condition +
            # variant count. The fight_label is the "WHEN you fight him"
            # condition pulled from the xlsx ("If Lv ≥ 27", "If Lv ≥ 44", …).
            meta_chunks = [f'<span class="tr-size dim">· {party_count} mons</span>']
            lc = brief.get("level_cap")
            if isinstance(lc, int) and lc > 0:
                meta_chunks.append(
                    f'<span class="tr-cap dim">· Lv≤{lc}</span>')
            fight_label = brief.get("fight_label") or ""
            if fight_label:
                meta_chunks.append(
                    f'<span class="tr-fight-label">· '
                    f'{html.escape(fight_label)}</span>')
            if n_variants > 1:
                meta_chunks.append(
                    f'<span class="tr-variant-count">{n_variants} variants</span>')
            meta_html = "".join(meta_chunks)
            sprite_url = brief.get("sprite_url") or ""
            sprite_html = ""
            if sprite_url:
                sprite_html = (
                    f'<img class="tr-sprite" loading="lazy" '
                    f'src="{html.escape(sprite_url, quote=True)}" '
                    f'alt="" referrerpolicy="no-referrer" '
                    f'onerror="this.style.display=\'none\'">'
                )
            # The widget header already declares these are "Upcoming
            # Trainers"; a per-row "upcoming"/"current"/"past" chip would be
            # redundant noise. The progress state class still drives subtle
            # styling (faded past fights, accented border for current) and
            # the sequential-fight filter above hides genuinely-past variants
            # so only the relevant ones reach this loop.
            rows_html += (
                f'<details class="trainer-row tr-state-{state}" id="d-{row_key}" '
                f'data-details-key="{row_key}">'
                f'<summary>'
                f'{sprite_html}'
                f'<span class="tr-class">{cls}</span> '
                f'<span class="tr-name">{name}</span>'
                f'{meta_html}'
                f'<button type="button" class="tr-calc-btn" '
                f'data-pid="{html.escape(player_id, quote=True)}" '
                f'data-tid="{rt_id}" '
                f'data-calc-label="{html.escape(brief.get("calc_label", "") or "", quote=True)}" '
                f'title="Open in RR Calc Prep tab (reuses calc tab if open)">&#9876;</button>'
                f'</summary>'
                f'<div class="tr-party">{mons_html}</div>'
                f'</details>'
            )
        if not rows_html:
            return ""
        pid_seg = f"{player_id}:" if player_id else ""
        key = f"{key_prefix}tr:{pid_seg}{html.escape(area_id, quote=True)}"
        return (
            f'<details class="trainer-widget" id="d-{key}" data-details-key="{key}">'
            f'<summary><svg class="inline-ico" aria-hidden="true">'
            f'<use href="#i-swords"/></svg> Upcoming Key Trainers</summary>'
            f'<div class="trainer-list">{rows_html}</div>'
            f'</details>'
        )

    def _enc_table_for_status(self, area_id: str, player_id: str = "") -> dict | None:
        """Return encounter table dict with sprite_src added to each entry.

        sprite_src is just the image URL — much smaller than sprite_html
        (~115 chars vs ~400 chars per entry). The overlay JS builds the
        <img> tag. CFRU→NatDex conversion is handled by the adapter.

        Returns None when no encounter data exists (non-RR or unmapped area).

        ``player_id`` selects whose cartridge to describe; without it the run-global
        adapter answers, which is right only while both players hold the same content.
        """
        adapter = self.adapter_for(player_id)
        enc = adapter.encounter_table(area_id)
        if not enc:
            return None
        return {
            method: [
                {**e, "sprite_src": adapter.sprite_src(e.get("species_id", 0))}
                for e in entries
            ]
            for method, entries in enc.items()
        }

    # rom_type → game_id and rom_type → variant-label maps live in
    # server.adapters (single source of truth alongside the registry).
    # Access via game_id_for_rom_type() and variant_label() helpers.

    def _page_title(self) -> str:
        """Build dynamic page title: Pokémon Soul Link Tracker — <variant> — <run name>.

        Game variant is committed once on first hello and persisted in links.json,
        so it survives server restarts and client disconnects.
        """
        parts = ["Pokémon Soul Link Tracker"]
        if self.state.rom_type:
            from server.adapters import variant_label
            parts.append(variant_label(self.state.rom_type))
        if self._run_name:
            parts.append(html.escape(self._run_name))
        return " — ".join(parts)

    def _build_sidebar_html(self, active: str) -> str:
        """Build the dashboard sidebar HTML. Delegates to server.chrome so
        the sidebar can also be rendered by Jinja-templated pages (memorial,
        stream gallery, calc) and the manager. The per-run server enriches
        the call with its TCP port + manager port."""
        from server.chrome import build_sidebar_html
        return build_sidebar_html(
            active,
            tcp_port=self._tcp_port,
            manager_port=self._manager_port,
        )

    def _notify_sse(self):
        """Push an update notification to all connected SSE clients.

        Uses coalescing: each queue holds at most 1 item.  If the queue is
        full (client hasn't consumed the previous update yet), the old item
        is replaced with a fresh sentinel so the client always gets the
        latest state when it reads.
        """
        if not self._sse_clients:
            return
        for q in self._sse_clients:
            # Drain any unconsumed item, then put the new sentinel.
            with contextlib.suppress(asyncio.QueueEmpty):
                q.get_nowait()
            # QueueFull should not happen after the drain, but be safe.
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(True)


    # ── Rolling backups ───────────────────────────────────────────────────────

    def _both_connected(self) -> bool:
        return (self.connected_players.get("a", {}).get("connected", False)
                and self.connected_players.get("b", {}).get("connected", False))

    def start_backup_task(self):
        """Spawn the rolling-backup task. Idempotent if already running."""
        if self._backup_task is None or self._backup_task.done():
            from server.backup import backup_loop
            self._backup_task = asyncio.ensure_future(backup_loop(
                links_path=self.state._links_path,
                events_path=self._events_path,
                max_slots=self._backup_max,
                interval_s=self._backup_interval,
                is_active=self._both_connected,
            ))

    async def handle_sse(self, request):
        """GET /api/events — Server-Sent Events stream.

        Emits two named event types:
          - ``event: status``  — full JSON status dict (for stream overlays)
          - ``event: ping``    — empty data (triggers fetch+morph on main page)

        Clients that only need the ping can ignore ``status`` events and
        vice-versa, keeping the architecture flexible with a single endpoint.
        """
        resp = aiohttp_web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"  # disable nginx buffering
        resp.force_close()  # disable HTTP keep-alive; SSE connections must not be reused
        await resp.prepare(request)

        async def _write(data: bytes) -> bool:
            """Write with a 10-second timeout. Returns False on failure/timeout."""
            try:
                await asyncio.wait_for(resp.write(data), timeout=10.0)
                return True
            except (TimeoutError, ConnectionResetError, ConnectionAbortedError, asyncio.CancelledError):
                return False
            except Exception as e:
                log.debug(f"SSE write error: {e}")
                return False

        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._sse_clients.add(q)
        try:
            # Send retry hint and an immediate ping so clients fetch the initial state
            if not await _write(b"retry: 3000\n\n"):
                return resp
            if not await _write(b"event: ping\ndata: \n\n"):
                return resp

            while True:
                # Short heartbeat interval (3s instead of the previous 15s) so
                # dead client connections are detected and cleaned up quickly.
                # The earlier 15s window caused F5-spam to stack up to 6
                # zombie SSE connections inside Chrome's per-origin pool,
                # which then blocked any new fetches on the dashboard until
                # the heartbeats finally noticed the disconnects.
                try:
                    await asyncio.wait_for(q.get(), timeout=3.0)
                except TimeoutError:
                    # Proactive disconnect detection: if the transport has
                    # already closed, exit immediately without attempting a
                    # write. Saves up to one heartbeat cycle of latency.
                    if request.transport is None or request.transport.is_closing():
                        break
                    if not await _write(b": heartbeat\n\n"):
                        break
                    continue
                except asyncio.CancelledError:
                    break

                # Real update — send a tiny ping; clients fetch /api/status themselves
                if not await _write(b"event: ping\ndata: \n\n"):
                    break
        except Exception as e:
            log.debug(f"SSE handler exited: {e}")
        finally:
            self._sse_clients.discard(q)
        return resp

    def _gen1_wire_response(self, player_id, msg, owner):
        """The RBY TCP boundary. No caller-supplied flag can bypass admission."""
        self._refresh_rom_contract(force=True)
        gate = self._gen1_sessions
        if gate.refresh(self._rom_contract):
            for player in ("a", "b"):
                self.admission[player] = {"state": "contract_pending", "reason": "cartridge contract changed"}
                self.state._has_helld.discard(player)
                if player in self.connected_players:
                    self.connected_players[player]["connected"] = False
        hello = msg.get("event") == "hello"
        try:
            if hello:
                session = gate.admit(self._rom_contract, player_id, msg, owner,
                                     self.state.player_identity.get(player_id))
                # Facts become visible only after ALL cartridge/identity checks pass.
                from server.adapters import get_adapter
                variant = session.metadata["variant"]
                adapter = get_adapter("gen1_rby", rom_type=variant)
                if self.state.adapter.game_id != "gen1_rby":
                    if self.state.rom_type:
                        gate.close(player_id, owner)
                        raise gen1_admission.AdmissionError("run already belongs to a different game generation")
                    self.state.adapter = self.adapter = adapter
                    self.state.is_rr = False
                self._player_adapters[player_id] = adapter
                self._connection_owners[player_id] = owner
                self.admission[player_id] = {"state": "admitted", "reason": "verified complete cartridge contract",
                                             "admission_epoch": gate.epoch, "session_id": session.session_id}
                self.connected_players[player_id] = {
                    "rom_type": variant, "panel": session.metadata["capabilities"]["panel"],
                    "panel_abi": session.metadata["patch_version"], **session.metadata}
            else:
                retry = gate.accept(player_id, msg, owner)
                if retry is not None:
                    return retry
                session = gate.sessions[player_id]
            info = self.connected_players[player_id]
            info.update(connected=True, last_event=msg.get("event", "?"),
                        last_seen=datetime.now().strftime("%H:%M:%S"), last_seen_ts=time.time())
            commands = self._dispatch(player_id, msg, _gen1_session=session)
            return gate.response(player_id, msg, commands, hello=hello)
        except gen1_admission.AdmissionError as exc:
            # A rejected second socket must not revoke the verified socket's ownership.
            owned = gate.close(player_id, owner)
            if owned or player_id not in gate.sessions:
                self.admission[player_id] = {"state": "contract_pending" if not self._rom_contract else "rejected",
                                             "reason": str(exc)}
                self.state._has_helld.discard(player_id)
                if player_id in self.connected_players:
                    self.connected_players[player_id]["connected"] = False
            return gen1_admission.nack(msg, str(exc), pending=not self._rom_contract)
        except Exception:
            # A partial handler failure is ambiguous. Never replay it as a new event.
            log.exception("[%s] RBY dispatcher failed; session revoked", player_id)
            gate.close(player_id, owner)
            self.admission[player_id] = {"state": "rejected", "reason": "dispatcher failure requires recovery"}
            self.state._has_helld.discard(player_id)
            if player_id in self.connected_players:
                self.connected_players[player_id]["connected"] = False
            return gen1_admission.nack(msg, "dispatcher failure requires recovery")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        log.info(f"Client connected: {peer}")
        player_id_for_conn: str | None = None
        owner = object()
        gen1_connection = False
        legacy_hello_accepted = False
        dropping_line = False
        try:
            while True:
                try:
                    raw = await reader.readuntil(b"\n")
                except asyncio.IncompleteReadError:
                    break  # peer closed cleanly
                except asyncio.LimitOverrunError as e:
                    # A single line exceeded the configured 4 MiB limit. Drain
                    # the overrun bytes so the next readuntil starts at a fresh
                    # line, log a warning, and keep the connection alive instead
                    # of letting asyncio tear it down.
                    log.warning(f"Oversized line from {peer} ({e.consumed} bytes consumed before limit) — dropping")
                    try:
                        # Consume only the reported prefix. readuntil preserves any
                        # following frame in its buffer, including a coalesced HELLO.
                        await reader.readexactly(e.consumed)
                        dropping_line = True
                    except asyncio.IncompleteReadError:
                        break
                    continue
                if dropping_line:
                    dropping_line = False
                    await self._respond_packet(writer, gen1_admission.nack({}, "oversized protocol frame"))
                    continue
                if not raw.strip():
                    continue
                try:
                    msg = gen1_admission.decode_frame(raw)
                except gen1_admission.AdmissionError as e:
                    log.warning(f"Bad JSON from {peer}: {e}")
                    await self._respond_packet(writer, gen1_admission.nack({}, "invalid JSON frame"))
                    continue

                player_id = msg.get("player", "")
                if player_id not in VALID_PLAYERS:
                    log.warning(f"Rejected unknown player_id: {repr(player_id)} from {peer}")
                    await self._respond(writer, [{"cmd": "noop"}])
                    continue

                # Track which player owns this connection.
                if player_id_for_conn is None:
                    if msg.get("event") != "hello":
                        await self._respond_packet(writer, gen1_admission.nack(msg, "HELLO is required before events", pending=True))
                        continue
                    player_id_for_conn = player_id
                elif player_id != player_id_for_conn:
                    await self._respond_packet(writer, gen1_admission.nack(msg, "a connection cannot change player slots"))
                    continue

                self._refresh_rom_contract()
                rom_type = str(msg.get("rom_type", "")).lower()
                gen1_connection = (gen1_connection or msg.get("protocol") == gen1_admission.PROTOCOL
                    or rom_type in gen1_admission.VARIANTS | {"gen1_rby"}
                    or self.state.rom_type.lower() in gen1_admission.VARIANTS | {"gen1_rby"}
                    or (self._rom_contract or {}).get("schema") == gen1_admission.CONTRACT_SCHEMA)
                if gen1_connection:
                    packet = self._gen1_wire_response(player_id, msg, owner)
                    await self._respond_packet(writer, packet)
                    self._notify_sse()
                    continue
                # A legacy peer may not claim a slot currently owned by an admitted
                # RBY socket, even by announcing a different game in its HELLO.
                if player_id in self._gen1_sessions.sessions:
                    await self._respond_packet(writer, gen1_admission.nack(msg, "slot belongs to an admitted RBY session"))
                    continue
                if msg.get("event") == "hello":
                    # Recognize the cartridge before this socket can replace an
                    # owner, adopt an adapter, publish facts or advance sequence.
                    from server.adapters import game_id_for_rom_type
                    legacy_hello_accepted = False
                    declared_rom = msg.get("rom_type")
                    if not isinstance(declared_rom, str) or game_id_for_rom_type(declared_rom) is None:
                        reason = "Unrecognized cartridge identity; load a supported game and send HELLO again."
                        log.warning("[%s] rejected HELLO from %s: unrecognized cartridge rom_type=%s",
                                    player_id, peer, repr(declared_rom)[:160])
                        # A rejected second socket has no authority to revoke
                        # the correctly connected player's admission or facts.
                        if self._connection_owners.get(player_id) in (None, owner):
                            self.admission[player_id] = {
                                "state": "rejected", "reason_code": "unrecognized_cartridge", "reason": reason}
                        await self._respond_packet(writer, {
                            "ack": "NACK", "reason_code": "unrecognized_cartridge", "reason": reason,
                            "commands": [{"cmd": "noop"}]})
                        self._notify_sse()
                        continue
                    legacy_hello_accepted = True
                elif not legacy_hello_accepted or self._connection_owners.get(player_id) is not owner:
                    await self._respond_packet(writer, {
                        "ack": "NACK", "reason_code": "legacy_connection_not_admitted",
                        "reason": "A valid HELLO on the current connection is required before events.",
                        "commands": [{"cmd": "noop"}]})
                    continue
                self._connection_owners[player_id] = owner

                # Update connection info
                prev_conn = self.connected_players.get(player_id, {})
                self.connected_players[player_id] = {
                    "connected":  True,
                    "last_event": msg.get("event", "?"),
                    "last_seen":  datetime.now().strftime("%H:%M:%S"),
                    # `connected` only clears in the reader's finally block, so a crashed emulator
                    # or a slept laptop leaves the badge green forever. An age does not lie.
                    "last_seen_ts": time.time(),
                    "rom_type":   prev_conn.get("rom_type", "?"),
                }
                # CARRY THE CARTRIDGE FACTS FORWARD. This dict is rebuilt from scratch on
                # EVERY inbound message, but `panel`/`panel_abi` are written only on hello
                # -- so the first tick after connecting erased them, `_player_has_panel`
                # fell back to the adapter default, and Gen 1 (width 20, not 0) answered
                # False. The panel payload therefore went out exactly once, at hello, and
                # the cartridge showed the run frozen at connect time for the rest of the
                # session. Gen 3 never noticed: it leaves info_panel_width at 0, so its
                # fallback answered True.
                for carried in ("panel", "panel_abi"):
                    if carried in prev_conn:
                        self.connected_players[player_id][carried] = prev_conn[carried]
                if msg.get("event") == "hello":
                    self.connected_players[player_id]["rom_type"] = msg.get("rom_type", "?")
                    # Panel capability is per CARTRIDGE: on Gen 1 it comes from the
                    # companion ROM patch, so a patched and an unpatched cartridge can
                    # sit in one run and the generation alone cannot answer.
                    if "panel" in msg:
                        self.connected_players[player_id]["panel"] = bool(msg.get("panel"))
                        self.connected_players[player_id]["panel_abi"] = msg.get("panel_abi", 0)
                    # Resolve correct adapter from rom_type.
                    # Once rom_type is committed (set-once), the adapter is locked — ignore
                    # any later hello that carries a different rom_type (e.g. early-boot
                    # detect_variant returning 'vanilla' before IWRAM is initialised).
                    rom_type = msg.get("rom_type", "")
                    if not self.state.rom_type:
                        from server.adapters import game_id_for_rom_type, get_adapter
                        new_game_id = game_id_for_rom_type(rom_type)
                        new_is_rr = rom_type.endswith("_rr")
                        if new_game_id and new_game_id != self.state.adapter.game_id:
                            self.state.adapter = get_adapter(new_game_id, is_rr=new_is_rr, rom_type=rom_type)
                            self.state.is_rr = new_is_rr
                            self.adapter = self.state.adapter
                            log.info(f"Adapter switched to {new_game_id} (rom_type={rom_type})")
                            log.debug(f"[ADAPTER] player={player_id}  game_id={new_game_id}  is_rr={new_is_rr}  rom_type={rom_type!r}  reason=game_id_changed")
                        elif new_is_rr != self.state.is_rr:
                            self.state.is_rr = new_is_rr
                            from server.adapters import get_adapter
                            self.state.adapter = get_adapter(
                                self.state.adapter.game_id, is_rr=new_is_rr, rom_type=rom_type)
                            self.adapter = self.state.adapter
                            log.info(f"Adapter updated: is_rr={new_is_rr}")
                            log.debug(f"[ADAPTER] player={player_id}  game_id={self.state.adapter.game_id}  is_rr={new_is_rr}  rom_type={rom_type!r}  reason=is_rr_changed")
                    elif rom_type and rom_type != self.state.rom_type:
                        log.warning(f"[{player_id}] hello rom_type={rom_type!r} ignored — "
                                    f"run already locked to {self.state.rom_type!r}")
                # Duplicate-event guard.  Detect client restarts by seq resetting to 0/1.
                seq = msg.get("seq", -1)
                if seq != -1:
                    last = self._last_seq.get(player_id, -1)
                    if seq <= last:
                        if seq <= 1 and last > 10:
                            log.info(f"[{player_id}] client restart (seq {last}→{seq}), resetting")
                            self._last_seq[player_id] = -1
                        else:
                            log.debug(f"[{player_id}] duplicate seq {seq}, skipping")
                            await self._respond(writer, [{"cmd": "noop"}])
                            continue
                    self._last_seq[player_id] = seq
                    log.debug(f"[TCP] player={player_id}  seq={seq}  last={last}  outcome=accepted  event={msg.get('event','?')}")

                commands = self._dispatch(player_id, msg)
                await self._respond(writer, commands)
                # Log non-trivial responses at DEBUG for post-mortem tracing.
                _real_cmds = [c for c in commands if c.get("cmd") not in ("noop", "resolved_areas")]
                if _real_cmds:
                    _summary = ", ".join(
                        c["cmd"] + (":" + c["key"][:8] if "key" in c else "")
                        for c in _real_cmds
                    )
                    log.debug(f"[CMD FLUSH] player={player_id}  {len(_real_cmds)} cmd(s): {_summary}")
                # Notify SSE clients after TCP response (no game-client latency impact)
                self._notify_sse()

        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            log.info(f"Client disconnected: {peer}")
            if player_id_for_conn and self._connection_owners.get(player_id_for_conn) is owner:
                info = self.connected_players.get(player_id_for_conn, {})
                info["connected"] = False
                self.connected_players[player_id_for_conn] = info
                self._connection_owners.pop(player_id_for_conn, None)
                if self._gen1_sessions.close(player_id_for_conn, owner):
                    self.admission[player_id_for_conn] = {"state": "contract_pending", "reason": "client disconnected"}
                    self.state._has_helld.discard(player_id_for_conn)
                self._notify_sse()  # Push disconnect status to browsers
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _respond_packet(writer: asyncio.StreamWriter, packet: dict):
        writer.write((json.dumps(packet, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8"))
        await writer.drain()

    @staticmethod
    async def _respond(writer: asyncio.StreamWriter, commands: list):
        data = json.dumps({"commands": commands}) + "\n"
        writer.write(data.encode("utf-8"))
        await writer.drain()

    # Mirrors BAR_W in patch/src/handlers.c: the info panel's HP bar is 38 px of track. The scaling
    # is done here because the ROM blob has no libgcc and therefore cannot divide at runtime.
    INFO_BAR_W = 38

    def _build_link_panel(self, player_id: str) -> dict:
        """Rows for the native in-game SOULLINK panel, for ONE player.

        Built per recipient because the panel is framed as "yours" and "your partner's" — the same
        run reads differently from each side, and telling the halves of a pair apart is the entire
        point of the screen.

        Rows are emitted PRE-FORMATTED and flat, `field|field|...`, because the Lua client has no
        JSON decoder — `parse_command_list` is a pattern scraper, so a nested payload simply never
        reaches it. Flat strings of a shape it can scrape keep the formatting here, in Python, where
        it is unit-testable.

        Field order matches MB.info_mon: label|name|level|hp|barpx|state. A row with an EMPTY label
        continues the pair above it (that is what draws the tie bracket). Two fields = label/value,
        one = full-width text. Pairs occupy 2 rows each and the client pages 6 rows at a time, so a
        pair can never straddle a page boundary.
        """
        from server.state import AreaStatus, LinkStatus
        partner = "b" if player_id == "a" else "a"
        s = self.state

        def half(mon, owner, label):
            det = self.party_details.get(owner, {}).get(mon.key) or {}
            cached = self._mon_cache.get(mon.key, {})
            species = det.get("species_id") or cached.get("species_id") or mon.species
            name = (det.get("nickname") or cached.get("nickname")
                    or (self.adapter.species_name(species) if species else "")
                    or mon.nickname or "?")
            level = int(det.get("level") or cached.get("level") or mon.level or 0)
            if not det:
                # Boxed: alive but out of the party, so there is no live HP. It gets its own state
                # rather than an empty bar, which the panel would colour like a dead mon.
                return f"{label}|{name[:10]}|{level}|BOX|0|B|"
            hp, mx = int(det.get("hp", 0) or 0), int(det.get("maxHP", 0) or 0)
            if hp <= 0:
                return f"{label}|{name[:10]}|{level}|FNT|0||"
            px = max(1, min(self.INFO_BAR_W, round(hp * self.INFO_BAR_W / mx))) if mx > 0 else 0
            # 7th field: status. A poisoned or paralysed linked mon is exactly the kind of thing a
            # player opens this screen to find out, and it is invisible from the HP bar alone.
            tok = self.adapter.status_token(int(det.get("status_cond", 0) or 0))
            return f"{label}|{name[:10]}|{level}|{hp}/{mx}|{px}||{tok}"

        rows = []
        npairs = 0
        for e in s.links:
            if not (e.a and e.a.key and e.b and e.b.key):
                continue                      # half-formed: one side hasn't caught yet
            mine_mon   = e.a if player_id == "a" else e.b
            theirs_mon = e.b if player_id == "a" else e.a
            rows.append(half(mine_mon, player_id, _area_tag(self.adapter.area_display_name(e.area_id))))
            rows.append(half(theirs_mon, partner, ""))   # empty label = continues the pair above
            npairs += 1

        if not rows:
            rows.append("No linked pairs yet")
        dead_zones = sorted(a for a, st in s.area_states.items() if st == AreaStatus.DEAD_ZONE)
        alive = sum(1 for e in s.links if e.status == LinkStatus.ALIVE)
        rows.append(f"Pairs alive|{alive}/{npairs}")
        rows.append(f"Dead zones|{len(dead_zones)}")
        # NOTE for the Gen 1 native panel (Phase 5): this reads SoulLinkState.player_badges,
        # which is a COUNT set only by the `status` event -- a different attribute from
        # SLinkServer.player_badges, which holds the BITMASK from hello/tick. Gen 1 never
        # sends `status`, so this row would read 0/8 there. Correct for Gen 3 as written;
        # switch it to popcount(self.player_badges[...]) when Gen 1 gets the panel.
        rows.append(f"Badges|{s.player_badges.get(player_id, 0)}/8")
        # NAME the dead zones. A count tells a player a number; the names tell them where they can
        # no longer catch, which is the part they can act on. Pagination carries the overflow.
        for area_id in dead_zones:
            rows.append("- " + self.adapter.area_display_name(area_id)[:28])

        # A NARROW SCREEN GETS ITS OWN ROWS, not these truncated.
        # The rows above are `label|field|field|...` for a client that lays them out in
        # columns on a 30-wide screen. A Game Boy has 20, which is not enough for that
        # layout at all, so chopping them would produce something that fits and says
        # nothing. Compact rows are plain single-line text the client prints as-is.
        width = self.adapter.info_panel_width()
        if width and width <= 20:
            npairs_alive = f"{alive}/{npairs}"
            # popcount the BITMASK here. The row above uses SoulLinkState.player_badges,
            # which is a count set only by the `status` event -- and Gen 1 never sends one,
            # so it would always read 0/8. SLinkServer.player_badges holds the bitmask that
            # hello and tick actually deliver.
            mask = 0
            try:
                mask = int(self.player_badges.get(player_id, 0) or 0)
            except (TypeError, ValueError):
                mask = 0
            badges = bin(mask).count("1")
            compact = [
                "SOUL LINK",
                "",
                f"PAIRS {npairs_alive}",
                f"BADGES {badges}/8",
                f"DEAD ZONES {len(dead_zones)}",
            ]
            # THE PAIRS THEMSELVES, which is what the screen is for. A count tells the
            # player a number; the names and levels tell them which of their mons is tied
            # to which of their partner's, and whether it is still alive -- the thing they
            # opened the menu to find out.
            live = [e for e in s.links if e.a and e.a.key and e.b and e.b.key]
            if live:
                compact.append("")
                for e in live:
                    mine = e.a if player_id == "a" else e.b
                    theirs = e.b if player_id == "a" else e.a
                    tag = "X" if e.status != LinkStatus.ALIVE else " "
                    compact.append(f"{tag}{self._panel_name(mine)}-{self._panel_name(theirs)}"[:width])
            # NAME the dead zones, all of them. They used to be capped at eight because a
            # single screen holds eighteen rows and there was nowhere to put the rest; the
            # panel pages now, so the cap only hid information the player can act on.
            if dead_zones:
                compact.append("")
                for area_id in dead_zones:
                    compact.append(("-" + self.adapter.area_display_name(area_id))[:width])
            return {"cmd": "link_panel", "rows": [r[:width] for r in compact]}

        return {"cmd": "link_panel", "rows": rows}

    def _panel_name(self, mon) -> str:
        """A mon's short name for the 20-column native panel.

        Nickname when there is one, species otherwise, and never more than eight
        characters: two of these plus a separator has to fit in twenty columns.
        """
        if mon is None:
            return "?"
        name = (mon.nickname or "").strip() or self.adapter.species_name(mon.species) or "?"
        return name[:8]

    def _cache_mon_info(self, key: str, detail: dict):
        """Update the persistent per-monKey display cache from a detail dict.

        Also backfills level=0 and stale nicknames in any LinkEntry MonInfo
        for this key, so data gets corrected once the mon connects with
        live party data.
        """
        entry = self._mon_cache.get(key, {})
        for field in ("species_id", "nickname", "level", "gender", "held_item_id"):
            val = detail.get(field)
            if val:  # only overwrite with non-empty / non-zero
                entry[field] = val
        self._mon_cache[key] = entry
        # Backfill mon_stats for PC box level display (covers shiny/bonus mons)
        lv = detail.get("level", 0)
        maxhp = detail.get("maxHP", 0)
        if lv and key not in self.state.mon_stats:
            self.state.mon_stats[key] = {"level": lv}
            if maxhp:
                self.state.mon_stats[key]["maxHP"] = maxhp
        elif lv and not self.state.mon_stats.get(key, {}).get("level"):
            self.state.mon_stats[key]["level"] = lv
        # Backfill level and nickname into link entries
        nick = detail.get("nickname", "")
        species_id = detail.get("species_id", 0)
        if (lv or nick or species_id) and self.state._key_index.get(key):
            link_entry = self.state._key_index[key]
            dirty = False
            for mi in (link_entry.a, link_entry.b):
                if mi and mi.key == key:
                    if lv and not mi.level:
                        mi.level = lv
                        dirty = True
                    if nick and nick != mi.nickname:
                        mi.nickname = nick
                        dirty = True
                    if species_id and species_id != mi.species:
                        mi.species = species_id
                        dirty = True
            if dirty:
                self.state._save()

    def _mon_display_name(self, player_id: str, key: str) -> str:
        if not key:
            return "?"
        detail = self.party_details.get(player_id, {}).get(key, {})
        if detail.get("nickname"):
            return detail["nickname"]
        cached = self._mon_cache.get(key, {})
        if cached.get("nickname"):
            return cached["nickname"]
        species_id = detail.get("species_id", 0) or cached.get("species_id", 0)
        if species_id:
            return self.adapter.species_name(species_id)
        link_entry = self.state._key_index.get(key)
        if link_entry:
            for mon in (link_entry.a, link_entry.b):
                if mon and mon.key == key:
                    return mon.nickname or self.adapter.species_name(mon.species) or key[:8]
        return key[:8]

    def _load_events(self):
        """Load persisted recent events from events.json on startup."""
        try:
            with open(self._events_path, encoding="utf-8") as f:
                events = json.load(f)
            self._recent_events = deque(events[:_EVENTS_MAX], maxlen=_EVENTS_MAX)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_events(self):
        """Persist the recent events ring buffer to events.json."""
        try:
            os.makedirs(os.path.dirname(self._events_path), exist_ok=True)
            with open(self._events_path, "w", encoding="utf-8") as f:
                # Belt-and-suspenders: never write more than _EVENTS_MAX entries.
                json.dump(list(self._recent_events)[:_EVENTS_MAX], f)
        except Exception as e:
            log.warning(f"Failed to save events.json: {e}")

    def _log_event(self, player_id: str, event_type: str, text: str,
                   area_id: str = "", key: str = ""):
        """Append a timestamped entry to the recent events ring buffer."""
        self._recent_events.appendleft({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "player": player_id,
            "type": event_type,
            "text": text,
            "area_id": area_id,
            "key": key,
        })
        self._save_events()

    def _party_snapshot(self, player_id: str, party: list) -> dict:
        """Legacy display fields shared by admitted HELLO and tick observations.

        Cartridge/rule validation and cache publication remain at their existing
        dispatch boundaries. This helper only constructs the display snapshot.
        """
        adapter = self.adapter_for(player_id)
        return {
            mon["key"]: {
                "level": mon.get("level", 0),
                "hp": mon.get("hp", 1),
                "maxHP": mon.get("maxHP", 1),
                "nickname": mon.get("nickname", ""),
                "species_id": mon.get("species_id", 0),
                "held_item_id": mon.get("held_item_id", mon.get("held_item", 0)),
                "ability_id": mon.get("ability_id", mon.get("ability", 0)),
                "gender": adapter.gender_from_key(mon["key"], mon.get("species_id", 0)),
                "moves": mon.get("moves", []),
                "pp": mon.get("pp", []),
                "slot": mon.get("slot", index),
                "active": mon.get("active", False),
                "status_cond": mon.get("status_cond", 0),
                "stat_stages": mon.get("stat_stages"),
            }
            for index, mon in enumerate(party) if mon.get("key")
        }

    def _dispatch(self, player_id: str, msg: dict, *, _gen1_session=None) -> list:
        # The Python session object is never deserialized from a client frame.
        if (msg.get("protocol") == gen1_admission.PROTOCOL and
                (_gen1_session is None or self._gen1_sessions.sessions.get(player_id) is not _gen1_session)):
            return [{"cmd": "noop"}]
        event = msg.get("event", "unknown")
        # Snapshot area state before the event so we can detect outcome transitions.
        _pre_area_state = self.state.area_states.get(msg.get("area_id", ""))
        _pre_battle = self.battle_state[player_id]["in_battle"]
        _pre_memorial_status = None
        if event == "memorialize_done":
            _pre_memorial_link = self.state._key_index.get(msg.get("key", ""))
            if _pre_memorial_link:
                _pre_memorial_status = getattr(_pre_memorial_link.status, "value", _pre_memorial_link.status)

        # Block all events from a player whose identity was rejected.
        # Only a hello with correct identity can clear the error.
        if event != "hello" and self.state.identity_error.get(player_id):
            return [{"cmd": "noop"}]

        # Block everything but hello until the player's cartridge is admitted. Same shape as
        # the identity gate above and for the same reason: only a hello can change the
        # verdict, so letting anything else through would mutate rule state on evidence we
        # have already decided not to trust. `tick` is NOT exempt -- it carries the party
        # snapshot that diff_party turns into captures, which is exactly a semantic event.
        if event != "hello" and not self.is_admitted(player_id):
            return [{"cmd": "noop"}]

        if event == "hello":
            # Pick up a contract written after this server started, before deciding.
            self._refresh_rom_contract()
            verdict = (self.admission[player_id] if _gen1_session is not None
                       else self._decide_admission(player_id, msg))
            if self.admission.get(player_id, {}).get("state") != verdict["state"]:
                (log.info if verdict["state"] == "admitted" else log.warning)(
                    "[%s] admission: %s — %s", player_id, verdict["state"], verdict["reason"])
            self.admission[player_id] = verdict
            if verdict["state"] != "admitted":
                # STOP HERE. Recording the verdict was not enough: control used to fall
                # straight into state.handle_event, which permanently locks
                # player_identity, saves it, rebuilds party_keys from the rejected
                # cartridge and QUEUES box_mon write commands back to the very client we
                # just refused -- and then _ingest_rom_content adopted its encounter
                # tables. Booting the wrong ROM once therefore did not merely fail to
                # connect, it corrupted the run and wrote into the wrong save file.
                self._log_event(player_id, "hello",
                                f"REJECTED — {verdict['reason']}",
                                msg.get("loc_name", "") or msg.get("area_id", ""))
                return [{"cmd": "noop"}]

            area    = msg.get("area_id", "")
            loc     = msg.get("loc_name", "")
            party_n = len(msg.get("party", []))
            rom     = msg.get("rom_type", "unknown")
            log.info(f"[{player_id}] hello rom={rom} area='{area or loc}' party={party_n}")

            # Run state machine first (handles identity lock check).
            identity_options = {}
            if _gen1_session is not None:
                # The RBY gate verified these save fields before this dispatch.
                # Trading a foreign-OT mon into the lead slot cannot redefine them.
                identity_options["save_identity"] = SaveIdentity(msg["ot_id"], msg["trainer_name"])
            cmds = self.state.handle_event(player_id, msg, preserve_peer_session=_gen1_session is not None,
                                           **identity_options)

            if msg.get("_rejected"):
                # Identity mismatch — log it, surface error, but don't update display data.
                self._log_event(player_id, "hello",
                                "REJECTED — wrong save/slot", area or loc)
                return cmds

            self._log_event(player_id, "hello",
                            f"Connected ({rom}, {party_n} mons)", loc or area)
            self.player_area[player_id] = loc or area
            self.player_area_id[player_id] = area
            # Commit ROM type once — static for the run's lifetime.
            _dirty = False
            if rom and rom != "unknown" and not self.state.rom_type:
                self.state.rom_type = rom
                _dirty = True
                log.info(f"Committed ROM type '{rom}' for this run")
            if "ball_count" in msg:
                self.player_ball_count[player_id] = msg["ball_count"]
            if "badges" in msg:
                self.player_badges[player_id] = msg["badges"]
            if "kanto_badges" in msg:
                self.player_kanto_badges[player_id] = msg["kanto_badges"]
            if "trainer_name" in msg:
                tname = msg["trainer_name"]
                self.trainer_name[player_id] = tname
                # Commit trainer name once per player — static for the run.
                if tname and not self.state.trainer_names.get(player_id):
                    self.state.trainer_names[player_id] = tname
                    _dirty = True
                    log.info(f"Committed trainer name '{tname}' for player {player_id}")
            if _dirty:
                self.state._save()
            # Clean admission already proves every ROM domain canonical. Never
            # replace that profile with a partial client-reported encounter table.
            if msg.get("rom_content") and _gen1_session is None:
                self._ingest_rom_content(player_id, msg["rom_content"])
            if "pc_boxes" in msg:
                self.pc_boxes[player_id] = msg["pc_boxes"]
                for bentry in msg["pc_boxes"]:
                    bk = bentry.get("key", "")
                    if bk:
                        self._cache_mon_info(bk, bentry)
                self._check_memorial_box_contamination(player_id, msg["pc_boxes"])
            # Seed party_details from snapshot
            self.party_details[player_id] = self._party_snapshot(player_id, msg.get("party", []))
            for k, det in self.party_details[player_id].items():
                self._cache_mon_info(k, det)
            # Seed battle state from hello (so page reflects battle immediately)
            if "in_battle" in msg:
                self.battle_state[player_id]["in_battle"] = bool(msg["in_battle"])
            if "is_trainer_battle" in msg:
                self.battle_state[player_id]["is_trainer_battle"] = bool(msg["is_trainer_battle"])
            if "enemy_party" in msg:
                self.battle_state[player_id]["enemy_party"] = msg["enemy_party"]
            return cmds
        elif event == "area_enter":
            area = msg.get("area_id", "")
            loc  = msg.get("loc_name", "")
            disp = loc or area  # prefer specific location name for display
            log.info(f"[{player_id}] area_enter → '{disp}'")
            if disp:
                self.player_area[player_id] = disp
                # Use area_id for display name resolution (has underscores for proper formatting)
                disp_name = self.adapter.area_display_name(area or disp)
                self._log_event(player_id, "area_enter",
                                f"Entered {disp_name}", disp)
            if area:
                self.player_area_id[player_id] = area
        elif event == "capture":
            key = msg.get("key", "")
            log.info(f"[{player_id}] capture key={key} lv={msg.get('level','?')} area='{msg.get('area_id','')}'")
            if key:
                sid = msg.get("species_id", 0)
                sp_name = self.adapter.species_name(sid) if sid else "?"
                self._log_event(player_id, "capture",
                                f"Caught {sp_name} Lv{msg.get('level','?')}",
                                msg.get("area_id", ""), key)
                detail = {
                    "level":        msg.get("level", 0),
                    "hp":           msg.get("hp", 1),
                    "maxHP":        msg.get("maxHP", 1),
                    "nickname":     msg.get("nickname", ""),
                    "species_id":   sid,
                    "held_item_id": msg.get("held_item_id", msg.get("held_item", 0)),
                    "ability_id":   msg.get("ability_id", msg.get("ability", 0)),
                    "gender":       self.adapter.gender_from_key(key, sid),
                }
                self.party_details[player_id][key] = detail
                self._cache_mon_info(key, detail)
        elif event == "faint":
            key = msg.get("key", "")
            log.info(f"[{player_id}] faint key={key} area='{msg.get('area_id','')}'")
            if key and key in self.party_details[player_id]:
                self.party_details[player_id][key]["hp"] = 0
                nick = self.party_details[player_id][key].get("nickname", "")
                self._log_event(player_id, "faint",
                                f"{nick or key[:8]} fainted!",
                                msg.get("area_id", ""), key)
            # Enrich msg with cached battle-state killer info for state machine killfeed tracking.
            bs = self.battle_state.get(player_id, {})
            enemy = bs.get("enemy_party") or []
            active_foe = next((e for e in enemy if e.get("hp", 1) > 0), enemy[0] if enemy else None)
            if active_foe:
                msg["_killer_species"] = active_foe.get("species_id", 0)
                msg["_killer_level"]   = active_foe.get("level", 0)
            msg["_is_trainer"] = bool(bs.get("is_trainer_battle", False))
            if msg["_is_trainer"]:
                msg["_trainer_name"] = bs.get("opponent_name", "")
                msg["_trainer_class"] = bs.get("opponent_class", "")
            # Inject current level from party_details so memorial shows death-time level.
            pd = self.party_details[player_id].get(key, {})
            if pd.get("level"):
                msg["_level"] = pd["level"]
        elif event == "no_catch":
            log.info(f"[{player_id}] no_catch area='{msg.get('area_id','')}'")
            self._log_event(player_id, "no_catch",
                            f"Missed catch at {self.adapter.area_display_name(msg.get('area_id',''))}",
                            msg.get("area_id", ""))
        elif event == "whiteout":
            log.info(f"[{player_id}] whiteout")
            for key in self.party_details[player_id]:
                self.party_details[player_id][key]["hp"] = 0
            self._log_event(player_id, "whiteout", "WHITED OUT! All party mons fainted")
        elif event == "party_to_box":
            key = msg.get("key", "")
            log.info(f"[{player_id}] party_to_box key={key}")
            self.party_details[player_id].pop(key, None)
        elif event == "stats_cache":
            key = msg.get("key", "")
            log.debug(f"[{player_id}] stats_cache key={key}")
            self.party_details[player_id].pop(key, None)
        elif event == "box_to_party":
            key = msg.get("key", "")
            log.info(f"[{player_id}] box_to_party key={key}")
            if key and key not in self.party_details[player_id]:
                # Populate from persistent cache so sprites don't go blank until next tick.
                cached = self._mon_cache.get(key, {})
                self.party_details[player_id][key] = {
                    "level":        cached.get("level", 0),
                    "hp":           1,
                    "maxHP":        1,
                    "nickname":     cached.get("nickname", ""),
                    "species_id":   cached.get("species_id", 0),
                    "held_item_id": cached.get("held_item_id", 0),
                    "gender":       cached.get("gender", ""),
                }
        elif event == "memorialize_done":
            key = msg.get("key", "")
            log.info(f"[{player_id}] memorialize_done key={key}")
            self.party_details[player_id].pop(key, None)
        elif event == "key_change":
            old_key = msg.get("old_key", "")
            new_key = msg.get("new_key", "")
            log.info(f"[{player_id}] key_change {old_key[:8]} → {new_key[:8]}")
            # Migrate party_details: move old entry to new key
            old_detail = self.party_details[player_id].pop(old_key, None)
            if old_detail:
                self.party_details[player_id][new_key] = old_detail
            # Migrate _mon_cache
            old_mon = self._mon_cache.pop(old_key, None)
            if old_mon:
                self._mon_cache[new_key] = old_mon
        elif event == "safe":
            log.debug(f"[{player_id}] safe state")
        elif event == "tick":
            if "ball_count" in msg:
                self.player_ball_count[player_id] = msg["ball_count"]
            if "badges" in msg:
                self.player_badges[player_id] = msg["badges"]
            if "kanto_badges" in msg:
                self.player_kanto_badges[player_id] = msg["kanto_badges"]
            if "trainer_name" in msg:
                self.trainer_name[player_id] = msg["trainer_name"]
            if "pc_boxes" in msg:
                self.pc_boxes[player_id] = msg["pc_boxes"]
                for bentry in msg["pc_boxes"]:
                    bk = bentry.get("key", "")
                    if bk:
                        self._cache_mon_info(bk, bentry)
                self._check_memorial_box_contamination(player_id, msg["pc_boxes"])
            if "in_battle" in msg:
                was_in_battle = self.battle_state[player_id]["in_battle"]
                now_in_battle = bool(msg["in_battle"])
                self.battle_state[player_id]["in_battle"] = now_in_battle
                if was_in_battle and not now_in_battle:
                    self.battle_state[player_id]["trainer_id"] = 0
                    self.battle_state[player_id]["opponent_name"] = ""
                    self.battle_state[player_id]["opponent_class"] = ""
                    self.battle_state[player_id]["is_trainer_battle"] = False
                    self.battle_state[player_id]["enemy_party"] = []
                    self.battle_state[player_id]["is_doubles"] = False
            if "is_trainer_battle" in msg:
                self.battle_state[player_id]["is_trainer_battle"] = bool(msg["is_trainer_battle"])
            if "trainer_id" in msg:
                tid = msg["trainer_id"]
                self.battle_state[player_id]["trainer_id"] = tid
                # Resolve trainer name/class via adapter
                tr_name, tr_class = self.adapter.trainer_info(tid)
                if tr_class:
                    self.battle_state[player_id]["opponent_name"] = tr_name
                    self.battle_state[player_id]["opponent_class"] = tr_class
                elif "opponent_name" in msg or "opponent_class" in msg:
                    # Non-RR (e.g. Gen 1/2 client emits class+name directly because
                    # trainer_id alone is ambiguous without class context). Accept
                    # whatever the client provided.
                    if msg.get("opponent_name"):
                        self.battle_state[player_id]["opponent_name"] = msg["opponent_name"]
                    if msg.get("opponent_class"):
                        self.battle_state[player_id]["opponent_class"] = msg["opponent_class"]
            if "enemy_party" in msg:
                self.battle_state[player_id]["enemy_party"] = msg["enemy_party"]
            if "is_doubles" in msg:
                self.battle_state[player_id]["is_doubles"] = bool(msg["is_doubles"])
            elif "enemy_party" in msg:
                # Passive inference: >1 active enemy implies doubles (benefits Gen 4/5 automatically).
                active_count = sum(1 for e in msg["enemy_party"] if e.get("active"))
                if active_count > 1:
                    self.battle_state[player_id]["is_doubles"] = True
            # Dupes clause: notify at wild battle start (before handle_event flushes the queue).
            if "in_battle" in msg and not was_in_battle and now_in_battle \
                    and not self.battle_state[player_id].get("is_trainer_battle"):
                _battle_area_id = msg.get("area_id", "")
                _ep = self.battle_state[player_id].get("enemy_party", [])
                _enc_species = _ep[0].get("species_id", 0) if _ep else 0
                if _battle_area_id and _enc_species:
                    # Check if partner is also in a concurrent wild battle on the same area.
                    _partner_id = "b" if player_id == "a" else "a"
                    _partner_bs = self.battle_state[_partner_id]
                    _partner_battle_species = 0
                    if (_partner_bs.get("in_battle") and not _partner_bs.get("is_trainer_battle")
                            and self.player_area_id.get(_partner_id) == _battle_area_id):
                        _partner_ep = _partner_bs.get("enemy_party", [])
                        _partner_battle_species = _partner_ep[0].get("species_id", 0) if _partner_ep else 0
                    if self.state.check_dupe_on_encounter(player_id, _battle_area_id, _enc_species,
                                                          partner_battle_species=_partner_battle_species):
                        _sp_name = self.adapter.species_name(_enc_species)
                        self._log_event(player_id, "reroll",
                                        f"🔁 Dupes clause: {_sp_name} -- reroll!", _battle_area_id)
            # Update location from tick in case area_enter was missed (e.g. on reconnect).
            tick_area = msg.get("loc_name", "") or msg.get("area_id", "")
            if tick_area:
                self.player_area[player_id] = tick_area
            tick_area_id = msg.get("area_id", "")
            if tick_area_id:
                self.player_area_id[player_id] = tick_area_id
            log.debug(f"[{player_id}] tick")
        elif event == "ghost_pos":
            # High-frequency (~20Hz) overworld peer-position relay; handled in
            # state.handle_event (_handle_ghost_pos). No server-side enrichment or
            # per-frame logging (would flood at this rate).
            pass
        elif event == "peer_interact":
            # Talk-to-ghost: handled in state.handle_event (_handle_peer_interact),
            # which notifies the partner. Low-frequency; no enrichment needed here.
            pass
        elif event == "command_nack":
            # Diagnostic refusal only. In particular, do not tick the old trade
            # watchdog or infer any physical poststate from an unrecognized ACK.
            command = msg.get("command")
            reason = msg.get("reason")
            command = command[:64] if isinstance(command, str) else "invalid"
            reason = reason[:256] if isinstance(reason, str) else "command refused"
            self._log_event(player_id, "command_nack", f"Command refused ({command}): {reason}")
            return [{"cmd": "noop"}]
        elif event in ("trade_request", "mon_chosen", "menu_result", "trade_done", "status"):
            # Talk-to-partner trade flow (request → pick → confirm → trade scene → done) + periodic
            # badge status: handled in state.handle_event. User-paced (or ~0.2 Hz for status); no
            # server-side enrichment or per-event logging needed.
            pass
        else:
            log.debug(f"[{player_id}] unknown event '{event}' seq={msg.get('seq','?')}")

        # On tick, replace party_details entirely from the authoritative party snapshot.
        # This prevents captures that went straight to the PC box (full-party captures)
        # from appearing as phantom party mons between ticks.
        if "party" in msg and event == "tick":
            self.party_details[player_id] = self._party_snapshot(player_id, msg["party"])
            for k, det in self.party_details[player_id].items():
                self._cache_mon_info(k, det)

        cmds = self.state.handle_event(player_id, msg)

        # Refresh the native in-game panel, but only when its content actually changed — this runs
        # on every tick, and the panel is a few hundred bytes. The client keeps the last one staged
        # in EWRAM so opening the menu needs no round-trip at all.
        if self._player_has_panel(player_id):
            _panel = self._build_link_panel(player_id)
            _sig = json.dumps(_panel, sort_keys=True)
            if _sig != self._last_panel_sig.get(player_id):
                self._last_panel_sig[player_id] = _sig
                cmds = list(cmds) + [_panel]

        # Post-dispatch: log outcome events that require state-machine results.
        _partner = "b" if player_id == "a" else "a"
        _area_id = msg.get("area_id", "")
        if event in ("capture", "no_catch") and _area_id:
            _new_state = self.state.area_states.get(_area_id)
            if _new_state is not None and _new_state != _pre_area_state:
                _area_disp = self.adapter.area_display_name(_area_id)
                _sv = _new_state.value if hasattr(_new_state, "value") else str(_new_state)
                if _sv == "linked":
                    _cap_key = msg.get("key", "")
                    _link = self.state._key_index.get(_cap_key) if _cap_key else None
                    if _link:
                        _ma = _link.a if player_id == "a" else _link.b
                        _mb = _link.b if player_id == "a" else _link.a
                        _ma_nick = (_ma.nickname or self.adapter.species_name(_ma.species)) if _ma else "?"
                        _mb_nick = (_mb.nickname or self.adapter.species_name(_mb.species)) if _mb else "?"
                        self._log_event(player_id, "linked",
                                        f"✓ Linked {_ma_nick} × {_mb_nick} on {_area_disp}", _area_id)
                        self._log_event(_partner, "linked",
                                        f"✓ Linked {_mb_nick} × {_ma_nick} on {_area_disp}", _area_id)
                elif _sv == "dead_zone":
                    self._log_event(player_id, "dead_zone",
                                    f"☠ Dead zone: {_area_disp}", _area_id)
                    self._log_event(_partner, "dead_zone",
                                    f"☠ Dead zone: {_area_disp}", _area_id)

        if event == "faint" and msg.get("key"):
            _faint_key = msg["key"]
            _link = self.state._key_index.get(_faint_key)
            if _link:
                _p_mon = _link.b if player_id == "a" else _link.a
                _death = (self.state.queued_death_cmd(_partner, _p_mon.key)
                          if _p_mon else None)
                if _death:
                    _cached = self._mon_cache.get(_p_mon.key, {})
                    _p_nick = (
                        _cached.get("nickname") or
                        self.adapter.species_name(_cached.get("species_id", 0)) or
                        _p_mon.key[:8]
                    )
                    _verb = "exploded" if _death == "force_explode" else "force fainted"
                    self._log_event(_partner, _death,
                                    f"⚡ {_p_nick} {_verb}!",
                                    _area_id, _p_mon.key)

        if event == "capture":
            _cap_key = msg.get("key", "")
            if _cap_key and _cap_key in self.state.bonus_keys.get(player_id, set()):
                _nick = self._mon_display_name(player_id, _cap_key)
                self._log_event(player_id, "shiny",
                                f"✨ Shiny {_nick}!", _area_id, _cap_key)

        if event == "party_to_box":
            _box_key = msg.get("key", "")
            if _box_key:
                _nick = self._mon_display_name(player_id, _box_key)
                self._log_event(player_id, "party_to_box",
                                f"📦 {_nick} deposited", "", _box_key)

        if event == "box_to_party":
            _box_key = msg.get("key", "")
            if _box_key:
                _nick = self._mon_display_name(player_id, _box_key)
                self._log_event(player_id, "box_to_party",
                                f"↑ {_nick} retrieved", "", _box_key)

        if event == "memorialize_done":
            _mem_key = msg.get("key", "")
            _link = self.state._key_index.get(_mem_key) if _mem_key else None
            _post_status = getattr(getattr(_link, "status", None), "value", getattr(_link, "status", None))
            if _link and _post_status == "memorial" and _pre_memorial_status != "memorial":
                _a_name = (_link.a.nickname or self.adapter.species_name(_link.a.species)) if _link.a else "?"
                _b_name = (_link.b.nickname or self.adapter.species_name(_link.b.species)) if _link.b else "?"
                self._log_event(player_id, "memorialize",
                                f"⚰ {_a_name} × {_b_name} laid to rest", _link.area_id, _mem_key)

        if event == "key_change":
            _new_key = msg.get("new_key", "")
            _migrated = self.party_details[player_id].get(_new_key, {})
            _nick = _migrated.get("nickname", "") or msg.get("old_key", "")[:8]
            _reason = msg.get("reason", "")
            if msg.get("new_species") is not None:
                _what = "evolved"
            elif _reason == "trade_undo":
                _what = "trade reverted"
            else:
                _what = "nature/ability changed"
            self._log_event(player_id, "key_change",
                            f"🔄 {_nick or _new_key[:8]} {_what}", "", _new_key)

        # Log clause violations (capture rejected) and dupes rerolls (no_catch suppressed).
        # gui_prompt commands are only queued for these scenarios, so they're a reliable signal.
        if event in ("capture", "no_catch"):
            for c in cmds:
                if c.get("cmd") == "gui_prompt":
                    _prompt_text = c.get("text", "")
                    if "catch again" in _prompt_text.lower():
                        self._log_event(player_id, "violation",
                                        f"⚠ {_prompt_text}", _area_id)
                    elif "reroll" in _prompt_text.lower():
                        self._log_event(player_id, "reroll",
                                        f"🔁 {_prompt_text}", _area_id)

        self._emit_obs_triggers(player_id, msg, cmds, _pre_area_state, _pre_battle)
        return cmds


    def _emit_obs_triggers(self, player_id: str, msg: dict, cmds: list,
                           pre_area_state, pre_battle: bool):
        """Collect all game events that fired this dispatch cycle and submit them
        to OBSController.submit_fired() for priority-ordered scene resolution.

        Rules are evaluated in list order — the first matching rule per target player
        wins regardless of how many events fire simultaneously.
        """
        event = msg.get("event", "")
        _area_id = msg.get("area_id", "")
        _partner = "b" if player_id == "a" else "a"

        # fired: list of (trigger_name, src_player, metadata)
        fired = []

        # battle_start / battle_end — in_battle transition from tick
        if event == "tick" and "in_battle" in msg:
            now_battle = self.battle_state[player_id]["in_battle"]
            if not pre_battle and now_battle:
                fired.append(("battle_start", player_id, {}))
                if self.battle_state[player_id].get("is_trainer_battle"):
                    fired.append(("trainer_battle_start", player_id, {}))
                else:
                    fired.append(("wild_battle_start", player_id, {}))
                _cur_area = self.player_area_id.get(player_id, "")
                if self._area_has_open_encounter(_cur_area):
                    fired.append(("battle_start_new", player_id, {}))
            elif pre_battle and not now_battle:
                fired.append(("battle_end", player_id, {}))

        if event == "faint":
            fired.append(("faint", player_id, {}))
            # link_death — partner receives a death command (force_faint or force_explode)
            _faint_key = msg.get("key", "")
            if _faint_key:
                _link = self.state._key_index.get(_faint_key)
                if _link:
                    _p_mon = _link.b if player_id == "a" else _link.a
                    if _p_mon and self.state.queued_death_cmd(_partner, _p_mon.key):
                        fired.append(("link_death", _partner, {}))

        if event == "whiteout":
            fired.append(("whiteout", player_id, {}))

        if event == "capture":
            fired.append(("capture", player_id, {}))
            _cap_key = msg.get("key", "")
            if _cap_key and _cap_key in self.state.bonus_keys.get(player_id, set()):
                fired.append(("shiny", player_id, {}))

        if event == "area_enter":
            fired.append(("area_enter", player_id, {"area_id": _area_id}))
            if self._area_has_open_encounter(_area_id):
                fired.append(("area_enter_new", player_id, {"area_id": _area_id}))

        if event == "party_to_box":
            fired.append(("party_to_box", player_id, {}))

        if event == "box_to_party":
            fired.append(("box_to_party", player_id, {}))

        if event == "memorialize_done":
            fired.append(("memorialize_done", player_id, {}))

        # linked / dead_zone — area state transition post-dispatch
        if event in ("capture", "no_catch") and _area_id:
            _new_state = self.state.area_states.get(_area_id)
            if _new_state is not None and _new_state != pre_area_state:
                _sv = _new_state.value if hasattr(_new_state, "value") else str(_new_state)
                if _sv == "linked":
                    fired.append(("linked", player_id, {}))
                    fired.append(("linked", _partner, {}))
                elif _sv == "dead_zone":
                    fired.append(("dead_zone", player_id, {}))
                    fired.append(("dead_zone", _partner, {}))

        if self.state.run_over:
            fired.append(("run_over", player_id, {}))

        if fired:
            self.obs.submit_fired(fired)

    def _area_display(self, area_id: str) -> str:
        """Return a human-readable display name for area_id, handling bonus pair synthetic IDs."""
        if area_id.startswith("_bonus_"):
            return "✦ Bonus Pair"
        return self.adapter.area_display_name(area_id)

    def _area_has_open_encounter(self, area_id: str) -> bool:
        """True if area_id is an active nuzlocke area that hasn't been fully resolved.

        Returns False if: area not tracked, already linked, or dead zone.
        """
        if not area_id:
            return False
        state = self.state.area_states.get(area_id)
        if state is None:
            return False
        sv = state.value if hasattr(state, "value") else str(state)
        return sv not in ("linked", "dead_zone")

    def read_rule_state(self) -> dict:
        return runtime_boundary.read_rule_state(self)

    def read_runtime_facts(self, *, now=None) -> dict:
        return runtime_boundary.read_runtime_facts(self, now=now)

    def _restricted_operation_response(self, operation):
        decision = runtime_boundary.operation_decision(self, operation)
        if not decision["available"]:
            return aiohttp_web.json_response({"ok": False, "error": decision["reason"],
                "reason_code": decision["reason_code"], "operation": operation, "available": False}, status=409)
        return None

    def _build_status_dict(self) -> dict:
        """Serialize current server state to a JSON-safe dict."""
        s = self.state
        runtime = self.read_runtime_facts()

        def _enrich_killer(killer, player_id):
            """Add species_name to a killer dict for the memorial/killfeed."""
            if not killer:
                return killer
            k = dict(killer)
            sp = k.get("species", 0)
            if sp:
                k["species_name"] = self.adapter_for(player_id).species_name(sp)
            return k

        def _enrich_party(pid):
            adapter = self.adapter_for(pid)
            enriched = {}
            for key, detail in self.party_details.get(pid, {}).items():
                mon = dict(detail)
                species = mon.get("species_id", 0)
                mon["key"] = key
                mon["species_name"] = adapter.species_name(species) if species else ""
                mon["sprite_html"] = adapter.sprite_html(species, mon.get("form", 0)) if species else ""
                ability = mon.get("ability_id", 0)
                mon["ability_name"] = adapter.ability_name(ability, species) if ability else ""
                item = mon.get("held_item_id", 0)
                mon["held_item_name"] = adapter.item_name(item) if item else ""
                mon["move_details"] = move_details(adapter, mon)
                enriched[key] = mon
            return enriched

        def _enrich_box(pid):
            adapter = self.adapter_for(pid)
            enriched = []
            for entry in self.pc_boxes.get(pid, []):
                mon = dict(entry)
                species = mon.get("species_id", 0)
                mon["species_name"] = adapter.species_name(species) if species else ""
                mon["sprite_html"] = adapter.sprite_html(species, mon.get("form", 0)) if species else ""
                item = mon.get("held_item_id", 0)
                mon["held_item_name"] = adapter.item_name(item) if item else ""
                mon["move_details"] = move_details(adapter, mon, boxed=True)
                enriched.append(mon)
            return enriched

        def _enrich_battle_state(pid):
            adapter = self.adapter_for(pid)
            battle = dict(self.battle_state.get(pid, {"in_battle": False, "enemy_party": []}))
            enriched = []
            for entry in battle.get("enemy_party", []):
                mon = dict(entry)
                species = mon.get("species_id", 0)
                if species and not mon.get("sprite_html"):
                    mon["sprite_html"] = adapter.sprite_html(species, mon.get("form", 0))
                if species and not mon.get("species_name"):
                    mon["species_name"] = adapter.species_name(species)
                item = mon.get("held_item_id", 0)
                mon["held_item_name"] = adapter.item_name(item) if item else ""
                mon["move_details"] = move_details(adapter, mon)
                enriched.append(mon)
            battle["enemy_party"] = enriched
            return battle

        # Nested move/stage/event containers belong to the renderer after this
        # boundary; sharing them would let a display edit mutate live caches.
        return copy.deepcopy({
            # "" when the last save succeeded; the error text when it did not.
            "save_failed": s.save_failed,
            "players": {
                pid: {
                    "connected":      self.connected_players.get(pid, {}).get("connected", False),
                    "rom_type":       self.connected_players.get(pid, {}).get("rom_type", "?"),
                    "last_event":     self.connected_players.get(pid, {}).get("last_event", "—"),
                    "last_seen":      self.connected_players.get(pid, {}).get("last_seen", "—"),
                    # Seconds since this player last said anything, or None if never seen.
                    "last_seen_age":  _age_secs(self.connected_players.get(pid, {}).get("last_seen_ts")),
                    "nuzlocke_active": s.pokeballs_obtained.get(pid, False),
                    "current_area":   self.player_area.get(pid, ""),
                    "current_area_id": self.player_area_id.get(pid, ""),
                    "current_area_display": self.adapter_for(pid).area_display_name(
                        self.player_area_id.get(pid, "") or self.player_area.get(pid, "")
                    ),
                    "ball_count":     self.player_ball_count.get(pid, 0),
                    "badges":         self.player_badges.get(pid, 0),
                    "kanto_badges":   self.player_kanto_badges.get(pid, 0),
                    "trainer_name":   self.trainer_name.get(pid, ""),
                    "pc_boxes":       _enrich_box(pid),
                    "party_keys":     self._get_party_ordered(pid),
                    "party_details":  _enrich_party(pid),
                    "queued":         len(s.queued_commands.get(pid, [])),
                    "battle_state":   _enrich_battle_state(pid),
                    "identity_error": s.identity_error.get(pid, ""),
                    # Surfaced rather than only logged: a player whose events are being
                    # dropped needs to be told which cartridge the run expects, otherwise
                    # the game simply appears not to be recording anything.
                    "admission": getattr(self, "admission", {}).get(pid, {}).get(
                        "state", "contract_pending"),
                    "admission_reason": getattr(self, "admission", {}).get(pid, {}).get(
                        "reason", ""),
                    "capabilities": player_capabilities(runtime["players"][pid], runtime["requested_rules"]),
                    "encounter_table": self._enc_table_for_status(
                        self.player_area_id.get(pid, "") or self.player_area.get(pid, ""),
                        pid,
                    ),
                }
                for pid in ["a", "b"]
            },
            "links": [
                {
                    "area_id":    e.area_id,
                    "area_display": self._area_display(e.area_id),
                    "a_key":      e.a.key if e.a else None,
                    "a_nickname": e.a.nickname if e.a else "",
                    "a_species":  e.a.species if e.a else 0,
                    "a_species_name": self.adapter_for("a").species_name(e.a.species) if e.a and e.a.species else "",
                    "a_sprite_html": self.adapter_for("a").sprite_html(e.a.species) if e.a and e.a.species else "",
                    "a_level":    self._resolve_level("a", e.a),
                    "a_shiny":    e.a.is_shiny if e.a else False,
                    "b_key":      e.b.key if e.b else None,
                    "b_nickname": e.b.nickname if e.b else "",
                    "b_species":  e.b.species if e.b else 0,
                    "b_species_name": self.adapter_for("b").species_name(e.b.species) if e.b and e.b.species else "",
                    "b_sprite_html": self.adapter_for("b").sprite_html(e.b.species) if e.b and e.b.species else "",
                    "b_level":    self._resolve_level("b", e.b),
                    "b_shiny":    e.b.is_shiny if e.b else False,
                    "a_enc_species": e.encounter_a.species if e.encounter_a else 0,
                    "a_enc_level":   e.encounter_a.level   if e.encounter_a else 0,
                    "b_enc_species": e.encounter_b.species if e.encounter_b else 0,
                    "b_enc_level":   e.encounter_b.level   if e.encounter_b else 0,
                    "status":     e.status.value,
                }
                for e in s.links
            ],
            "area_states": {k: v.value for k, v in s.area_states.items()},
            "pending_captures": {
                area: {
                    pid: {
                        "key": mon.key, "nickname": mon.nickname,
                        "species": mon.species, "level": mon.level,
                        "species_name": self.adapter_for(pid).species_name(mon.species) if mon.species else "",
                        "sprite_html": self.adapter_for(pid).sprite_html(mon.species) if mon.species else "",
                    }
                    for pid, mon in players.items()
                }
                for area, players in s.pending_captures.items()
            },
            "rules": {
                "species_lock": s.species_lock,
                "gender_lock": s.gender_lock,
                "type_lock": s.type_lock,
                "explode_mode": s.explode_mode,
                "rival_team_swap": s.rival_team_swap,
                "overworld_presence": s.overworld_presence,
                "native_messages": s.native_messages,
                "native_sounds": s.native_sounds,
                "battle_calc": s.battle_calc,
                "pc_trade_npc": s.pc_trade_npc,
            },
            "recent_events": list(self._recent_events),
            "killfeed": sorted(
                [
                    {
                        "killed_at":        e.killed_at,
                        "area_id":          e.area_id,
                        "area_display":     self._area_display(e.area_id),
                        "cause":            e.cause,
                        "killer":           _enrich_killer(e.killer, e.initiating_player),
                        "initiating_player": e.initiating_player,
                        "a_key":      e.a.key      if e.a else None,
                        "a_nickname": e.a.nickname if e.a else "",
                        "a_species":  e.a.species  if e.a else 0,
                        "a_species_name": self.adapter_for("a").species_name(e.a.species) if e.a and e.a.species else "",
                        "a_sprite_html": self.adapter_for("a").sprite_html(e.a.species) if e.a and e.a.species else "",
                        "a_level":    self._resolve_level("a", e.a),
                        "b_key":      e.b.key      if e.b else None,
                        "b_nickname": e.b.nickname if e.b else "",
                        "b_species":  e.b.species  if e.b else 0,
                        "b_species_name": self.adapter_for("b").species_name(e.b.species) if e.b and e.b.species else "",
                        "b_sprite_html": self.adapter_for("b").sprite_html(e.b.species) if e.b and e.b.species else "",
                        "b_level":    self._resolve_level("b", e.b),
                        "status":     e.status.value,
                    }
                    for e in s.links if e.killed_at
                ],
                key=lambda x: x["killed_at"],
                reverse=True,
            ),
            "run_over": s.run_over,
            "attempts_count": s.attempts_count,
            "bonus_keys": {
                pid: sorted(s.bonus_keys.get(pid, set()))
                for pid in ["a", "b"]
            },
            "pending_bonus": {
                pid: list(s.pending_bonus.get(pid, []))
                for pid in ["a", "b"]
            },
            "badge_slugs": self.adapter.gym_badge_slugs(s.rom_type or ""),
        })

    def _build_dashboard_context(self) -> dict:
        from server.dashboard import build_dashboard_context
        return build_dashboard_context(self)

    def _build_status_html(self) -> str:
        from server.dashboard import render_dashboard
        return render_dashboard(self._build_dashboard_context())

    async def handle_status_html(self, request):
        return await self._handle_dashboard_template(request)

    async def _handle_dashboard_template(self, request):
        context = self._build_dashboard_context()
        context["theme"] = resolve_theme(request)
        return aiohttp_jinja2.render_template("dashboard.html", request, context)

    async def handle_status_json(self, request):
        return aiohttp_web.json_response(self._build_status_dict())

    # ── RR Damage Calculator handlers ───────────────────────────────────────

    async def handle_calc_redirect(self, request):
        raise aiohttp_web.HTTPFound('/calc/normal.html')

    async def handle_calc_files(self, request):
        """Serve calc assets — `calc/src/` wins over `calc/dist/` when both have the path.

        HTML entry points (`normal.html`, `hardcore.html`) are wrapped in the
        Jinja `calc.html` template so they pick up the same theme / font /
        sidebar chrome as the rest of the SLink UI. Everything else (CSS, JS,
        fonts, sprites, data files) is served verbatim from disk.

        Resolution: prefer `calc/src/` when the path exists there, fall back
        to `calc/dist/` otherwise. Lets calc/src/ edits go live without
        running the build script. The HTML entry points only exist in dist/
        (src has `*.template.html` with build placeholders), so they resolve
        from dist automatically.
        """
        path = request.match_info.get('path', '')
        # URL paths must stay relative on Windows as well as POSIX. Normalizing
        # first can hide traversal, and a drive-qualified join discards its base.
        if (ntpath.splitdrive(path)[0] or path.startswith('/') or '\\' in path
                or '\x00' in path or '..' in path.split('/')):
            raise aiohttp_web.HTTPForbidden()
        abs_path = None
        for directory in (_CALC_SRC_DIR, _CALC_DIST_DIR):
            try:
                root = Path(directory).resolve()
                candidate = (root / path).resolve()
                # resolve() follows symlinks and Windows junctions before the
                # containment check; a textual prefix check is insufficient.
                if not candidate.is_relative_to(root):
                    raise aiohttp_web.HTTPForbidden()
                if candidate.is_file():
                    abs_path = candidate
                    break
            except (OSError, RuntimeError, ValueError):
                raise aiohttp_web.HTTPForbidden() from None
        if abs_path is None:
            raise aiohttp_web.HTTPNotFound()
        if path.endswith('.html'):
            with open(abs_path, encoding='utf-8') as fh:
                full = fh.read()
            # Slice the calc body inner. Regex-matched rather than
            # `text.find('<body')` so HEAD comments that mention `<body>`
            # textually don't trip the parser (the dist HTML's HEAD comment
            # block currently does this). Same end-of-body match for symmetry.
            # If markers can't be found, falls back to serving the full text
            # so a malformed dist file degrades gracefully rather than 500ing.
            body_open_match  = re.search(r'<body\b[^>]*>', full)
            body_close_match = list(re.finditer(r'</body\s*>', full))
            if body_open_match and body_close_match:
                calc_body = full[body_open_match.end():body_close_match[-1].start()]
            else:
                calc_body = full
            is_hardcore = 'hardcore' in path.lower()
            ctx = {
                "page_title":      "Pokémon Radical Red Damage Calculator",
                "theme":           resolve_theme(request),
                "body_class":      "dark-theme",
                "sidebar_html":    self._build_sidebar_html("calc"),
                "sidebar_css":     "sidebar",
                "calc_body_html":  calc_body,
                "calc_mode_label": "Hardcore Mode" if is_hardcore else "Normal Mode",
                "is_stream":       False,
                "hide_chrome":     False,
            }
            resp = aiohttp_jinja2.render_template("calc.html", request, ctx)
            # The rendered theme depends on the `slink-theme` cookie. Without
            # this header the browser may serve a stale heuristic-cached copy
            # after the user changes themes on another page; revalidating
            # forces a fresh render. Same pattern as the static middleware in
            # templating.py for `/static/*`.
            resp.headers["Cache-Control"] = "no-cache"
            return resp
        mime, _ = mimetypes.guess_type(abs_path)
        ct = mime or 'application/octet-stream'
        return aiohttp_web.FileResponse(abs_path, headers={"Content-Type": ct})

    async def handle_calc_mons(self, request):
        """Return live party + linked mons for both players as Showdown pastes."""
        d = self._build_status_dict()
        s = self.state
        result = {}
        for pid in ("a", "b"):
            p = d["players"][pid]
            party, linked = [], []
            # Party mons
            for key in p.get("party_keys", []):
                detail = p["party_details"].get(key, {})
                entry = _build_mon_entry(key, detail, self.adapter)
                if entry:
                    entry["loc"] = "party"
                    entry["hp_pct"] = (
                        max(0, min(100, int(detail.get("hp", 0)
                                           / max(detail.get("maxHP", 1), 1) * 100))))
                    party.append(entry)
            # Linked alive mons not already in party
            party_key_set = set(p.get("party_keys", []))
            for lnk in s.links:
                if lnk.status.value != "alive":
                    continue
                mi = lnk.a if pid == "a" else lnk.b
                if not mi or not mi.key or mi.key in party_key_set:
                    continue
                stats = s.mon_stats.get(mi.key, {})
                detail = {
                    "species_id":   mi.species,
                    "level":        mi.level or stats.get("level", 0),
                    "nickname":     mi.nickname or "",
                    "hp":           0,
                    "maxHP":        0,
                    "held_item_id": 0,
                    "ability_id":   0,
                    "ability_name": "",
                    "moves":        stats.get("moves", []),
                }
                entry = _build_mon_entry(mi.key, detail, self.adapter)
                if entry:
                    entry["loc"] = "box"
                    linked.append(entry)
            bs = p.get("battle_state", {})
            enemy = []
            if bs.get("in_battle"):
                is_trainer = bs.get("is_trainer_battle", False)
                opp_name  = bs.get("opponent_name", "")
                opp_class = bs.get("opponent_class", "")
                trainer_label = " ".join(filter(None, [opp_class, opp_name])) if is_trainer else "Wild"
                for ei, em in enumerate(bs.get("enemy_party", [])):
                    esid  = em.get("species_id", 0)
                    if not esid:
                        continue
                    detail = {
                        "species_id":   esid,
                        "level":        em.get("level", 0),
                        "nickname":     "",
                        "hp":           em.get("hp", 0),
                        "maxHP":        em.get("maxHP", 1),
                        "held_item_id": em.get("held_item_id", 0),
                        "ability_id":   em.get("ability_id", 0),
                        "ability_name": "",
                        "moves":        em.get("moves", []),
                        "status_cond":  em.get("status_cond", 0),
                        "stat_stages":  em.get("stat_stages"),
                    }
                    entry = _build_mon_entry(f"foe-{ei}", detail, self.adapter)
                    if entry:
                        entry["loc"]    = "enemy"
                        entry["active"] = em.get("active", False)
                        entry["hp_pct"] = max(0, min(100, int(
                            em.get("hp", 0) / max(em.get("maxHP", 1), 1) * 100)))
                        entry["trainer_label"] = trainer_label
                        enemy.append(entry)
            result[pid] = {
                "trainer_name": p.get("trainer_name", pid.upper()),
                "party":  party,
                "linked": linked,
                "enemy":  enemy,
            }
        return aiohttp_web.json_response(result)

    async def handle_memorial_html(self, request):
        return await self._handle_memorial_template(request)

    async def _handle_memorial_template(self, request):
        """Jinja-rendered memorial wall."""
        # Smoke-test path: render every macro against mock data so a designer
        # can visually verify a macro in isolation without needing a live run.
        if request.query.get("_smoke") == "1":
            return aiohttp_jinja2.render_template(
                "_smoke.html", request,
                {
                    "page_title": self._page_title(),
                    "theme": resolve_theme(request),
                },
            )

        # Build the killfeed slice of the status dict and reverse it so the
        # memorial wall renders oldest-first (chronological order).
        d = self._build_status_dict()
        killfeed = list(reversed(d.get("killfeed", [])))
        for entry in killfeed:
            entry["killed_at_display"] = _format_killed_at(entry.get("killed_at"))

        return aiohttp_jinja2.render_template(
            "memorial.html", request,
            {
                "page_title": self._page_title(),
                "theme": resolve_theme(request),
                "killfeed": killfeed,
                "sidebar_html": self._build_sidebar_html("memorial"),
            },
        )

    # ── Stream overlay handlers ──────────────────────────────────────────────

    async def handle_stream_index(self, request):
        ctx = _build_stream_index_context(request)
        ctx["sidebar_html"] = self._build_sidebar_html("stream")
        return aiohttp_jinja2.render_template("stream_index.html", request, ctx)

    async def handle_stream_party_a(self, request):
        return await self._handle_stream_party_template(request, "a")

    async def handle_stream_party_b(self, request):
        return await self._handle_stream_party_template(request, "b")

    # ── Templated party overlay ────────────────────────────────

    def _build_party_overlay_context(self, player_id: str) -> dict:
        """Slice and reshape `_build_status_dict()` into the template context
        the party overlay expects. One full status-dict build per HTMX poll
        (every 2 s) — acceptable at SLink's localhost-only scale.
        """
        d = self._build_status_dict()
        p = d["players"].get(player_id, {})
        keys = p.get("party_keys", [])
        details = p.get("party_details", {})

        mons = []
        for key in keys:
            det = details.get(key) or {}
            hp = det.get("hp", 0) or 0
            max_hp = det.get("maxHP", 0) or 0
            fainted = (hp == 0)
            if fainted or max_hp <= 0:
                tone = "fnt" if fainted else "bl"
            else:
                pct = (hp / max_hp) * 100
                if pct > 50:
                    tone = "bh"
                elif pct > 20:
                    tone = "bm"
                else:
                    tone = "bl"
            mons.append({
                "key":          key,
                "species_id":   det.get("species_id", 0),
                "species_name": det.get("species_name", ""),
                "nickname":     det.get("nickname", "") or det.get("species_name", "") or key[:8],
                "level":        det.get("level", 0),
                "hp":           hp,
                "maxHP":        max_hp,
                "sprite_html":  det.get("sprite_html", ""),
                "status_tone":  tone,
                "fainted":      fainted,
                "status_cond":  det.get("status_cond", 0),
                "stat_stages":  det.get("stat_stages", []) if det.get("active") else None,
                "active":       det.get("active", False),
            })

        return {
            "player_id":    player_id,
            "trainer_name": p.get("trainer_name", ""),
            "mons":         mons,
        }

    async def _handle_stream_party_template(self, request, player_id: str):
        """Render the templated party overlay. Two call sites:
            * /stream/party-{a,b}         — full page (initial paint)
            * /stream/party-{a,b}/fragment — #root only (HTMX poll target)
        Both pull from `_build_party_overlay_context(player_id)`. The
        fragment endpoint is wired in the router below.
        """
        is_fragment = request.match_info.get("fragment") == "fragment" \
                      or request.path.endswith("/fragment")
        ctx = self._build_party_overlay_context(player_id)
        ctx["theme"]         = resolve_theme(request)
        ctx["layout_class"]  = resolve_layout(request)
        ctx["overlay_title"] = f"Party {player_id.upper()}"
        # Fragment endpoint URL the body's hx-get points at — must preserve
        # ?theme= / ?layout= so themed polls keep returning themed bodies.
        query = request.url.query_string
        ctx["fragment_url"]  = f"/stream/party-{player_id}/fragment" + (f"?{query}" if query else "")

        template = "stream/_party_root.html" if is_fragment else "stream/party.html"
        return aiohttp_jinja2.render_template(template, request, ctx)

    async def handle_stream_party_a_fragment(self, request):
        return await self._handle_stream_party_template(request, "a")

    async def handle_stream_party_b_fragment(self, request):
        return await self._handle_stream_party_template(request, "b")

    async def handle_stream_enemy_focus_a(self, request):
        return await self._battle_overlay(request, "enemy-focus-a", "enemy_focus", "a")

    async def handle_stream_enemy_focus_b(self, request):
        return await self._battle_overlay(request, "enemy-focus-b", "enemy_focus", "b")

    async def handle_stream_enemy_focus_a_fragment(self, request):
        return await self._battle_fragment(request, "enemy-focus-a", "enemy_focus", "a")

    async def handle_stream_enemy_focus_b_fragment(self, request):
        return await self._battle_fragment(request, "enemy-focus-b", "enemy_focus", "b")

    async def handle_stream_enemy_trainer_a(self, request):
        return await self._battle_overlay(request, "enemy-trainer-a", "enemy_trainer", "a")

    async def handle_stream_enemy_trainer_b(self, request):
        return await self._battle_overlay(request, "enemy-trainer-b", "enemy_trainer", "b")

    async def handle_stream_enemy_trainer_a_fragment(self, request):
        return await self._battle_fragment(request, "enemy-trainer-a", "enemy_trainer", "a")

    async def handle_stream_enemy_trainer_b_fragment(self, request):
        return await self._battle_fragment(request, "enemy-trainer-b", "enemy_trainer", "b")

    # ── Battle overlay dispatch ──────────────────────────

    async def _battle_overlay(self, request, slug: str, template_base: str,
                              player_id: str):
        ctx = self._build_battle_overlay_context(player_id, template_base)
        self._apply_battle_body_class(ctx, template_base, request)
        return await self._render_stream_overlay(
            request, slug, ctx, template_base=template_base)

    async def _battle_fragment(self, request, slug: str, template_base: str, player_id: str):
        ctx = self._build_battle_overlay_context(player_id, template_base)
        self._apply_battle_body_class(ctx, template_base, request)
        return await self._render_stream_overlay(
            request, slug, ctx, template_base=template_base, fragment=True)

    @staticmethod
    def _apply_battle_body_class(ctx: dict, template_base: str, request) -> None:
        """Focus + enemy-focus need `body.ov-focus` for their shell scaling
        rules to apply. The CSS extras are stitched onto `layout_class` so
        the existing _render_stream_overlay plumbing stays untouched."""
        if template_base not in ("focus", "enemy_focus"):
            return
        existing = resolve_layout(request)
        ctx["layout_class"] = (existing + " ov-focus").strip()

    def _build_battle_overlay_context(self, player_id: str, template_base: str) -> dict:
        """Unified context builder for enemy_focus / enemy_trainer / focus.
        Dispatches on template_base to assemble the right slice."""
        d = self._build_status_dict()
        p  = d.get("players", {}).get(player_id, {}) or {}
        bs = p.get("battle_state", {}) or {}
        ctx = {"player_id": player_id, "in_battle": bool(bs.get("in_battle"))}

        if template_base == "enemy_focus":
            return {**ctx, **self._enemy_focus_ctx(bs)}
        if template_base == "enemy_trainer":
            return {**ctx, **self._enemy_trainer_ctx(bs)}
        if template_base == "focus":
            return {**ctx, **self._focus_ctx(p, bs)}
        return ctx

    def _enemy_focus_ctx(self, bs: dict) -> dict:
        if not bs.get("in_battle"):
            return {"active_mons": [], "is_doubles": False, "is_trainer": False, "title": ""}
        enemy_party = bs.get("enemy_party", []) or []
        active = [m for m in enemy_party if m.get("active")]
        if not active and enemy_party:
            active = [enemy_party[0]]
        is_doubles = bool(bs.get("is_doubles")) or len(active) > 1
        is_trainer = bool(bs.get("is_trainer_battle"))
        if is_trainer:
            title = (bs.get("opponent_class") or "TRAINER")
            if bs.get("opponent_name"):
                title += " " + bs["opponent_name"]
        else:
            title = "WILD ENCOUNTER"
        return {
            "active_mons": [self._battle_slot(m) for m in active],
            "is_doubles": is_doubles,
            "is_trainer": is_trainer,
            "title": title,
        }

    def _enemy_trainer_ctx(self, bs: dict) -> dict:
        if not bs.get("in_battle") or not bs.get("is_trainer_battle"):
            return {"mons": [], "trainer_label": ""}
        team = bs.get("enemy_party", []) or []
        label = (bs.get("opponent_class") or "Trainer")
        if bs.get("opponent_name"):
            label += " " + bs["opponent_name"]
        return {
            "mons": [self._battle_mon_card(m) for m in team],
            "trainer_label": label,
        }

    def _focus_ctx(self, p: dict, bs: dict) -> dict:
        keys = p.get("party_keys", []) or []
        details = p.get("party_details", {}) or {}
        active_slots = []
        for k in keys:
            det = details.get(k) or {}
            if not det.get("active"):
                continue
            active_slots.append(self._battle_slot(det))
        is_doubles = bool(bs.get("is_doubles")) or len(active_slots) > 1
        return {
            "active_mons": active_slots,
            "is_doubles":  is_doubles,
        }

    def _battle_slot(self, det: dict) -> dict:
        """Compose a {mon, moves} dict the focus/enemy-focus templates expect."""
        return {
            "mon":   self._battle_mon_card(det),
            "moves": [self._battle_move(md) for md in det.get("move_details", []) or []],
        }

    def _battle_mon_card(self, det: dict) -> dict:
        """Project a party_details / enemy_party entry into the shape mon_card expects."""
        hp     = det.get("hp", 0) or 0
        max_hp = det.get("maxHP", 0) or 0
        fnt    = hp == 0
        pct    = self._hp_pct(hp, max_hp)
        if fnt:
            tone = "fnt"
        elif pct > 50:
            tone = "bh"
        elif pct > 20:
            tone = "bm"
        else:
            tone = "bl"
        return {
            "species_id":   det.get("species_id", 0),
            "species_name": det.get("species_name", ""),
            "nickname":     det.get("nickname") or det.get("species_name") or "???",
            "level":        det.get("level", 0),
            "hp":           hp,
            "maxHP":        max_hp,
            "sprite_html":  det.get("sprite_html", ""),
            "status_tone":  tone,
            "fainted":      fnt,
            "status_cond":  det.get("status_cond", 0),
            "stat_stages":  det.get("stat_stages", []) if det.get("active") else None,
            "active":       bool(det.get("active")),
        }

    def _battle_move(self, md: dict) -> dict:
        """Project a move detail entry into the shape the moves-grid expects."""
        max_pp = md.get("pp", 0) or 0
        cur_pp = md.get("current_pp", 0) or 0
        pct    = max(0, min(100, round(cur_pp / max_pp * 100))) if max_pp else 0
        if pct > 50:
            cls = "pp-h"
        elif pct > 25:
            cls = "pp-m"
        else:
            cls = "pp-l"
        return {
            "name":       md.get("name") or "?",
            "type_name":  md.get("type_name") or "",
            "current_pp": cur_pp,
            "pp_max":     max_pp,
            "pp_cls":     cls,
        }

    async def handle_stream_links(self, request):
        return await self._render_stream_overlay(
            request, "links", self._build_links_overlay_context())

    async def handle_stream_links_fragment(self, request):
        return await self._render_stream_overlay(
            request, "links", self._build_links_overlay_context(), fragment=True)

    async def handle_stream_linked_party(self, request):
        return await self._render_stream_overlay(
            request, "linked-party", self._build_linked_party_overlay_context())

    async def handle_stream_linked_party_fragment(self, request):
        return await self._render_stream_overlay(
            request, "linked-party", self._build_linked_party_overlay_context(), fragment=True)

    async def handle_stream_boxed_links(self, request):
        return await self._render_stream_overlay(
            request, "boxed-links", self._build_boxed_links_overlay_context())

    async def handle_stream_boxed_links_fragment(self, request):
        return await self._render_stream_overlay(
            request, "boxed-links", self._build_boxed_links_overlay_context(), fragment=True)

    # ── Links overlay context builders ───────────────────

    @staticmethod
    def _hp_class(pct: int) -> str:
        return "hp-h" if pct > 50 else ("hp-m" if pct > 20 else "hp-l")

    @staticmethod
    def _hp_pct(hp: int, max_hp: int) -> int:
        if max_hp <= 0 or hp <= 0:
            return 0
        return max(0, min(100, round(hp / max_hp * 100)))

    def _build_links_overlay_context(self) -> dict:
        """Alive + dead link cards for /stream/links."""
        d = self._build_status_dict()
        alive, dead = [], []
        for lnk in d.get("links", []):
            item = {
                "area_display": lnk.get("area_display") or "",
                "a": {
                    "nickname":     lnk.get("a_nickname") or "",
                    "species_name": lnk.get("a_species_name") or "",
                    "sprite_html":  lnk.get("a_sprite_html") or "",
                },
                "b": {
                    "nickname":     lnk.get("b_nickname") or "",
                    "species_name": lnk.get("b_species_name") or "",
                    "sprite_html":  lnk.get("b_sprite_html") or "",
                },
            }
            (alive if lnk.get("status") == "alive" else dead).append(item)
        return {"alive": alive, "dead": dead}

    def _build_linked_party_overlay_context(self) -> dict:
        """Linked pairs where BOTH mons are currently in party — full
        sprite + HP card layout for /stream/linked-party."""
        d = self._build_status_dict()
        pa = d.get("players", {}).get("a", {}) or {}
        pb = d.get("players", {}).get("b", {}) or {}
        a_keys = set(pa.get("party_keys", []))
        b_keys = set(pb.get("party_keys", []))
        a_det  = pa.get("party_details", {}) or {}
        b_det  = pb.get("party_details", {}) or {}

        pairs = []
        for lnk in d.get("links", []):
            if lnk.get("status") != "alive":
                continue
            a_key = lnk.get("a_key")
            b_key = lnk.get("b_key")
            if a_key not in a_keys or b_key not in b_keys:
                continue
            ad = a_det.get(a_key) or {}
            bd = b_det.get(b_key) or {}
            a_hp, a_mx = ad.get("hp", 0) or 0, ad.get("maxHP", 0) or 0
            b_hp, b_mx = bd.get("hp", 0) or 0, bd.get("maxHP", 0) or 0
            a_pct = self._hp_pct(a_hp, a_mx)
            b_pct = self._hp_pct(b_hp, b_mx)
            a_fnt = a_hp == 0
            b_fnt = b_hp == 0
            pairs.append({
                "area_display": lnk.get("area_display") or "",
                "both_fainted": a_fnt and b_fnt,
                "a": {
                    "nickname":     ad.get("nickname") or lnk.get("a_nickname") or "",
                    "species_name": lnk.get("a_species_name") or "",
                    "sprite_html":  ad.get("sprite_html") or lnk.get("a_sprite_html") or "",
                    "level":        ad.get("level") or lnk.get("a_level") or 0,
                    "hp": a_hp, "max_hp": a_mx, "pct": a_pct,
                    "hp_cls": self._hp_class(a_pct), "fainted": a_fnt,
                },
                "b": {
                    "nickname":     bd.get("nickname") or lnk.get("b_nickname") or "",
                    "species_name": lnk.get("b_species_name") or "",
                    "sprite_html":  bd.get("sprite_html") or lnk.get("b_sprite_html") or "",
                    "level":        bd.get("level") or lnk.get("b_level") or 0,
                    "hp": b_hp, "max_hp": b_mx, "pct": b_pct,
                    "hp_cls": self._hp_class(b_pct), "fainted": b_fnt,
                },
            })
        return {"pairs": pairs}

    def _build_boxed_links_overlay_context(self) -> dict:
        """Alive pairs where at least one mon is in the box (not party)."""
        d = self._build_status_dict()
        pa = d.get("players", {}).get("a", {}) or {}
        pb = d.get("players", {}).get("b", {}) or {}
        a_keys = set(pa.get("party_keys", []))
        b_keys = set(pb.get("party_keys", []))

        pairs = []
        for lnk in d.get("links", []):
            if lnk.get("status") != "alive":
                continue
            a_in = lnk.get("a_key") in a_keys
            b_in = lnk.get("b_key") in b_keys
            if a_in and b_in:
                continue  # both in party → belongs to linked-party overlay
            pairs.append({
                "area_display": lnk.get("area_display") or "",
                "a": {
                    "nickname":     lnk.get("a_nickname") or "",
                    "species_name": lnk.get("a_species_name") or "",
                    "sprite_html":  lnk.get("a_sprite_html") or "",
                    "level":        lnk.get("a_level") or 0,
                    "in_party":     a_in,
                },
                "b": {
                    "nickname":     lnk.get("b_nickname") or "",
                    "species_name": lnk.get("b_species_name") or "",
                    "sprite_html":  lnk.get("b_sprite_html") or "",
                    "level":        lnk.get("b_level") or 0,
                    "in_party":     b_in,
                },
            })
        return {"pairs": pairs}

    async def handle_stream_deaths(self, request):
        return await self._render_stream_overlay(
            request, "deaths", self._build_deaths_overlay_context())

    async def handle_stream_deaths_fragment(self, request):
        return await self._render_stream_overlay(
            request, "deaths", self._build_deaths_overlay_context(), fragment=True)

    async def handle_stream_attempts(self, request):
        return await self._render_stream_overlay(
            request, "attempts", self._build_attempts_overlay_context())

    async def handle_stream_attempts_fragment(self, request):
        return await self._render_stream_overlay(
            request, "attempts", self._build_attempts_overlay_context(), fragment=True)

    # ── Shared template plumbing for stream overlays ─────────────

    async def _render_stream_overlay(self, request, slug: str, ctx: dict, *,
                                     fragment: bool = False, template_base: str | None = None):
        """Render `stream/{base}.html` (or `stream/_{base}_root.html` for the
        HTMX fragment endpoint). Shared by every stream overlay so the
        theme + layout + fragment-url plumbing lives in exactly one place.

        ``template_base`` lets two-player overlays (e.g. /stream/focus-a +
        /stream/focus-b) share one template — pass ``template_base='focus'``
        for both and the per-side context tells the template which player.
        """
        ctx = dict(ctx)
        ctx.setdefault("overlay_title", slug.replace("-", " ").title())
        ctx["theme"]        = resolve_theme(request)
        # `setdefault` (not `=`) so handlers that already stitched extras onto
        # layout_class — e.g. `_apply_battle_body_class` adding `ov-focus` to
        # focus / enemy-focus — survive this plumbing. Otherwise body.ov-focus
        # is silently dropped and the doubles flex-row split layout never
        # activates, leaving both columns stacked vertically.
        ctx.setdefault("layout_class", resolve_layout(request))
        query = request.url.query_string
        ctx["fragment_url"] = f"/stream/{slug}/fragment" + (f"?{query}" if query else "")
        base = (template_base or slug).replace("-", "_")
        template = f"stream/_{base}_root.html" if fragment else f"stream/{base}.html"
        return aiohttp_jinja2.render_template(template, request, ctx)

    def _build_deaths_overlay_context(self) -> dict:
        """Alive vs dead link counts for the SOUL LINK overlay."""
        alive = dead = 0
        for lnk in self.state.links:
            status = lnk.status.value if hasattr(lnk.status, "value") else lnk.status
            if status == "alive":
                alive += 1
            elif status in ("dead", "memorial"):
                dead += 1
        return {"alive_count": alive, "dead_count": dead}

    def _build_attempts_overlay_context(self) -> dict:
        return {"attempts_count": self.state.attempts_count}

    async def handle_stream_areas(self, request):
        return await self._render_stream_overlay(
            request, "areas", self._build_areas_overlay_context())

    async def handle_stream_areas_fragment(self, request):
        return await self._render_stream_overlay(
            request, "areas", self._build_areas_overlay_context(), fragment=True)

    async def handle_api_attempts(self, request):
        """POST /api/attempts — set the manual attempts counter."""
        restriction = self._restricted_operation_response("attempts_edit")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        count = body.get("count")
        if count is None or not isinstance(count, int) or count < 0:
            return aiohttp_web.json_response(
                {"ok": False, "error": "count must be a non-negative integer"}, status=400)
        self.state.attempts_count = count
        self.state._save()
        self._notify_sse()
        return aiohttp_web.json_response({"ok": True, "attempts_count": count})

    async def handle_stream_events(self, request):
        return await self._render_stream_overlay(
            request, "events", self._build_events_overlay_context(request))

    async def handle_stream_events_fragment(self, request):
        return await self._render_stream_overlay(
            request, "events", self._build_events_overlay_context(request), fragment=True)

    async def handle_stream_badges_a(self, request):
        return await self._badges_overlay(request, "a")

    async def handle_stream_badges_b(self, request):
        return await self._badges_overlay(request, "b")

    async def handle_stream_badges_a_fragment(self, request):
        return await self._badges_fragment(request, "a")

    async def handle_stream_badges_b_fragment(self, request):
        return await self._badges_fragment(request, "b")

    async def _badges_overlay(self, request, player_id: str):
        return await self._render_stream_overlay(
            request, f"badges-{player_id}",
            self._build_badges_overlay_context(player_id),
            template_base="badges")

    async def _badges_fragment(self, request, player_id: str):
        return await self._render_stream_overlay(
            request, f"badges-{player_id}",
            self._build_badges_overlay_context(player_id),
            template_base="badges", fragment=True)

    async def handle_stream_encounters(self, request):
        return await self._render_stream_overlay(
            request, "encounters", self._build_encounters_overlay_context())

    async def handle_stream_encounters_fragment(self, request):
        return await self._render_stream_overlay(
            request, "encounters", self._build_encounters_overlay_context(), fragment=True)

    async def handle_stream_stream_memorial(self, request):
        return await self._render_stream_overlay(
            request, "stream-memorial", self._build_memorial_scroll_context(),
            template_base="stream_memorial")

    async def handle_stream_stream_memorial_fragment(self, request):
        return await self._render_stream_overlay(
            request, "stream-memorial", self._build_memorial_scroll_context(),
            template_base="stream_memorial", fragment=True)

    async def handle_stream_ticker(self, request):
        return await self._render_stream_overlay(
            request, "ticker", self._build_ticker_overlay_context(request))

    async def handle_stream_ticker_fragment(self, request):
        return await self._render_stream_overlay(
            request, "ticker", self._build_ticker_overlay_context(request), fragment=True)

    async def handle_stream_focus_a(self, request):
        return await self._battle_overlay(request, "focus-a", "focus", "a")

    async def handle_stream_focus_b(self, request):
        return await self._battle_overlay(request, "focus-b", "focus", "b")

    async def handle_stream_focus_a_fragment(self, request):
        return await self._battle_fragment(request, "focus-a", "focus", "a")

    async def handle_stream_focus_b_fragment(self, request):
        return await self._battle_fragment(request, "focus-b", "focus", "b")

    async def handle_stream_area_encounter(self, request):
        return await self._render_stream_overlay(
            request, "area-encounter", self._build_area_encounter_overlay_context())

    async def handle_stream_area_encounter_fragment(self, request):
        return await self._render_stream_overlay(
            request, "area-encounter", self._build_area_encounter_overlay_context(), fragment=True)

    async def handle_stream_enc_table_a(self, request):
        return await self._enc_table_overlay(request, "a")

    async def handle_stream_enc_table_b(self, request):
        return await self._enc_table_overlay(request, "b")

    async def handle_stream_enc_table_a_fragment(self, request):
        return await self._enc_table_fragment(request, "a")

    async def handle_stream_enc_table_b_fragment(self, request):
        return await self._enc_table_fragment(request, "b")

    async def _enc_table_overlay(self, request, player_id: str):
        return await self._render_stream_overlay(
            request, f"enc-table-{player_id}",
            self._build_enc_table_overlay_context(player_id),
            template_base="enc_table")

    async def _enc_table_fragment(self, request, player_id: str):
        return await self._render_stream_overlay(
            request, f"enc-table-{player_id}",
            self._build_enc_table_overlay_context(player_id),
            template_base="enc_table", fragment=True)

    # ── Context builders for the remaining overlays ──

    def _build_areas_overlay_context(self) -> dict:
        linked = dead = pending = 0
        for st in self.state.area_states.values():
            sv = st.value if hasattr(st, "value") else str(st)
            if sv == "linked":
                linked += 1
            elif sv == "dead_zone":
                dead += 1
            elif sv.startswith("pending"):
                pending += 1
        return {"linked": linked, "dead": dead, "pending": pending}

    def _build_badges_overlay_context(self, player_id: str) -> dict:
        d = self._build_status_dict()
        p = d.get("players", {}).get(player_id, {}) or {}
        slugs = d.get("badge_slugs", []) or []
        primary = p.get("badges", 0) or 0
        kanto = p.get("kanto_badges", 0) or 0
        trainer_name = p.get("trainer_name") or f"Player {player_id.upper()}"
        badges = []
        for i, pair in enumerate(slugs):
            earned = bool((primary >> i) & 1) if i < 8 else bool((kanto >> (i - 8)) & 1)
            badges.append({
                "slug": pair[0] if isinstance(pair, (list, tuple)) else str(pair),
                "name": pair[1] if isinstance(pair, (list, tuple)) and len(pair) > 1 else "",
                "earned": earned,
            })
        return {
            "player_id":    player_id,
            "trainer_name": trainer_name,
            "badges":       badges,
        }

    def _build_encounters_overlay_context(self) -> dict:
        d = self._build_status_dict()
        links = d.get("links", []) or []
        linked = sum(1 for lk in links if lk.get("status") == "alive")
        dead   = sum(1 for lk in links if lk.get("status") != "alive")
        shinies = sum(1 for lk in links if lk.get("a_shiny") or lk.get("b_shiny"))
        bonus = d.get("bonus_keys", {}) or {}
        shinies += len(bonus.get("a", []) or []) + len(bonus.get("b", []) or [])
        last = links[-1] if links else None
        last_ctx = None
        if last:
            last_ctx = {
                "area_display": last.get("area_display") or "",
                "a": {
                    "nickname":     last.get("a_nickname") or "",
                    "species_name": last.get("a_species_name") or "",
                    "level":        last.get("a_level") or 0,
                    "sprite_html":  last.get("a_sprite_html") or "",
                    "shiny":        bool(last.get("a_shiny")),
                },
                "b": {
                    "nickname":     last.get("b_nickname") or "",
                    "species_name": last.get("b_species_name") or "",
                    "level":        last.get("b_level") or 0,
                    "sprite_html":  last.get("b_sprite_html") or "",
                    "shiny":        bool(last.get("b_shiny")),
                },
            }
        return {
            "linked":  linked + dead,
            "dead":    dead,
            "shinies": shinies,
            "last":    last_ctx,
        }

    def _build_memorial_scroll_context(self) -> dict:
        """Killfeed for the streaming memorial scroll, oldest first."""
        d = self._build_status_dict()
        kf = sorted(d.get("killfeed", []) or [], key=lambda x: x.get("killed_at") or "")
        entries = [{
            "area_display": k.get("area_display") or "",
            "a": {
                "nickname":     k.get("a_nickname") or "",
                "species_name": k.get("a_species_name") or "",
                "sprite_html":  k.get("a_sprite_html") or "",
            },
            "b": {
                "nickname":     k.get("b_nickname") or "",
                "species_name": k.get("b_species_name") or "",
                "sprite_html":  k.get("b_sprite_html") or "",
            },
        } for k in kf]
        return {"entries": entries}

    _EVENT_TYPE_CLASSES = {
        "capture":      "ec", "faint":        "ef", "whiteout":   "ew",
        "no_catch":     "en", "area_enter":   "ea", "linked":     "el",
        "dead_zone":    "ed", "violation":    "ev", "key_change": "ek",
        "force_faint":  "ef", "hello":        "eh", "shiny":      "es",
        "force_explode": "ef",
        "memorialize":  "em", "party_to_box": "ep", "box_to_party": "ep",
        "reroll":       "er",
    }

    @staticmethod
    def _format_event_ts(raw) -> str:
        if not raw:
            return ""
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone()
        except (ValueError, TypeError):
            s = str(raw)
            return s[11:16] if len(s) >= 16 else s
        h12 = dt.hour % 12 or 12
        return f"{h12}:{dt.minute:02d}{'p' if dt.hour >= 12 else 'a'}"

    def _build_events_overlay_context(self, request) -> dict:
        return self._build_event_feed_context(request, top_n=16, list_mode="events")

    def _build_ticker_overlay_context(self, request) -> dict:
        return self._build_event_feed_context(request, top_n=16, list_mode="ticker")

    def _build_event_feed_context(self, request, top_n: int, list_mode: str) -> dict:
        d = self._build_status_dict()
        events = (d.get("recent_events", []) or [])[:top_n]
        # Filter by ?filter=type1,type2 if provided
        flt = request.query.get("filter", "").strip()
        if flt:
            allow = {t for t in flt.split(",") if t}
            events = [e for e in events if e.get("type") in allow]
        pa = d.get("players", {}).get("a", {}) or {}
        pb = d.get("players", {}).get("b", {}) or {}
        name_a = pa.get("trainer_name") or "A"
        name_b = pb.get("trainer_name") or "B"
        rows = []
        for ev in events:
            rows.append({
                "ts":   self._format_event_ts(ev.get("ts")),
                "who":  name_a if ev.get("player") == "a" else name_b,
                "type": ev.get("type") or "",
                "text": ev.get("text") or ev.get("type") or "",
                "cls":  self._EVENT_TYPE_CLASSES.get(ev.get("type"), ""),
            })
        key = "pills" if list_mode == "ticker" else "events"
        return {key: rows}

    def _build_area_encounter_overlay_context(self) -> dict:
        """Current most-active area: linked / dead-zone / pending."""
        d = self._build_status_dict()
        # Pick the area both players are in, or the first pending area.
        area_a = self.player_area_id.get("a") or self.player_area.get("a") or ""
        area_b = self.player_area_id.get("b") or self.player_area.get("b") or ""
        focus  = area_a if area_a == area_b else (area_a or area_b)
        if not focus:
            return {
                "area_display": "", "status_tone": "dim", "status_label": "",
                "side_a": {"sprite_html": "", "name": "", "level": 0, "tag": "", "tag_cls": ""},
                "side_b": {"sprite_html": "", "name": "", "level": 0, "tag": "", "tag_cls": ""},
            }
        state = d.get("area_states", {}).get(focus, "unseen")
        # Find a link for this area
        linked_entry = None
        for lk in d.get("links", []) or []:
            if lk.get("area_id") == focus:
                linked_entry = lk
                break
        pending = d.get("pending_captures", {}).get(focus, {}) or {}

        def side(slot_id):
            if linked_entry:
                tag_cls = ("ae-tag-dead" if linked_entry.get("status") in ("dead", "memorial")
                           else "ae-tag-caught")
                tag = "DEAD" if linked_entry.get("status") in ("dead", "memorial") else "CAUGHT"
                return {
                    "sprite_html": linked_entry.get(f"{slot_id}_sprite_html") or "",
                    "name":        linked_entry.get(f"{slot_id}_nickname")
                                   or linked_entry.get(f"{slot_id}_species_name") or "",
                    "level":       linked_entry.get(f"{slot_id}_level") or 0,
                    "tag":         tag,
                    "tag_cls":     tag_cls,
                }
            p = pending.get(slot_id) or {}
            return {
                "sprite_html": "",
                "name":        p.get("nickname") or p.get("species_name") or "",
                "level":       p.get("level") or 0,
                "tag":         "WAITING" if p else "",
                "tag_cls":     "ae-tag-waiting",
            }

        if state == "linked":
            tone, label = "alive", "LINKED"
        elif state == "dead_zone":
            tone, label = "dead", "DEAD ZONE"
        elif state.startswith("pending"):
            tone, label = "pend", "PENDING"
        else:
            tone, label = "dim", "OPEN"
        return {
            "area_display": self._area_display(focus),
            "status_tone":  tone,
            "status_label": label,
            "side_a":       side("a"),
            "side_b":       side("b"),
        }

    def _build_enc_table_overlay_context(self, player_id: str) -> dict:
        """Wild encounter rates for the player's current area, sourced
        via _enc_table_for_status.

        Source shape from `_enc_table_for_status` is `{method: [entry, ...]}`
        directly (no `"methods"` wrapper); each entry carries `name`,
        `species_id`, `rate`, `min_level`, `max_level`. The `level_range`
        display string is derived here ("lvX" when min == max, else "lvX–Y")
        to match the pre-HTMX renderer's output. """
        area_id = self.player_area_id.get(player_id) or self.player_area.get(player_id) or ""
        raw = self._enc_table_for_status(area_id, player_id) or {}
        methods = []
        for method_name, entries in raw.items():
            mlist = []
            for e in entries:
                sid = e.get("species_id", 0)
                lo, hi = e.get("min_level", 0), e.get("max_level", 0)
                lv_range = f"lv{lo}" if lo == hi else f"lv{lo}–{hi}"
                mlist.append({
                    "species_id":   sid,
                    "species_name": e.get("name") or e.get("species_name") or "?",
                    "rate":         e.get("rate", 0),
                    "level_range":  lv_range if lo or hi else "",
                    "sprite_html":  self._get_sprite_html(sid) if sid else "",
                })
            if mlist:
                methods.append({"name": method_name, "entries": mlist})
        return {
            "player_id":    player_id,
            "area_display": self._area_display(area_id) if area_id else "",
            "methods":      methods,
        }

    # ── Launcher script download ─────────────────────────────────────────────

    _LAUNCHER_TEMPLATE = (
        '-- Auto-generated by SLink - {run_name}\n'
        '-- Player {player_upper}: load this script in BizHawk Lua Console\n'
        '-- This file can be loaded from any location (Desktop, Downloads, etc.)\n'
        '--\n'
        '-- Override: set SLINK_ROOT to skip auto-detection entirely:\n'
        'local SLINK_ROOT = nil  -- e.g. "C:/SLink/"\n'
        '\n'
        'SLINK_HOST   = {host}\n'
        'SLINK_PORT   = {tcp_port}\n'
        'SLINK_PLAYER = {player}\n'
        '\n'
        '-- Config file lives next to this launcher and caches the project root path.\n'
        'local _launcher_dir = ((debug.getinfo(1, "S") or {{}}).source or ""):match("@(.+[\\\\/])") or ""\n'
        'local _cfg_path = _launcher_dir .. "slink_path.cfg"\n'
        '\n'
        'local function _valid_root(path)\n'
        '    if not path or path == "" or path == "nil" then return false end\n'
        '    local f = io.open(path .. "lua/slink.lua", "r")\n'
        '    if f then f:close(); return true end\n'
        '    return false\n'
        'end\n'
        '\n'
        '-- 1. Load cached path from config file\n'
        'if not SLINK_ROOT then\n'
        '    local f = io.open(_cfg_path, "r")\n'
        '    if f then\n'
        '        local cached = f:read("*l"); f:close()\n'
        '        if _valid_root(cached) then SLINK_ROOT = cached end\n'
        '    end\n'
        'end\n'
        '\n'
        '-- 2. Auto-detect: search from this script\'s directory upward for lua/slink.lua\n'
        'if not SLINK_ROOT then\n'
        '    local dir = _launcher_dir\n'
        '    for _, rel in ipairs({{"", "../", "../../", "../../../"}}) do\n'
        '        if _valid_root(dir .. rel) then SLINK_ROOT = dir .. rel; break end\n'
        '    end\n'
        'end\n'
        '\n'
        '-- 3. Fallback: show folder picker\n'
        'if not SLINK_ROOT then\n'
        '    luanet.load_assembly("System.Windows.Forms")\n'
        '    local FBD = luanet.import_type("System.Windows.Forms.FolderBrowserDialog")\n'
        '    local DR = luanet.import_type("System.Windows.Forms.DialogResult")\n'
        '    local dlg = FBD()\n'
        '    dlg.Description = "Select the SLink project folder (the folder that contains lua/ and server/)"\n'
        '    dlg.ShowNewFolderButton = false\n'
        '    local result = dlg:ShowDialog()\n'
        '    if result == DR.OK then\n'
        '        local path = tostring(dlg.SelectedPath)\n'
        '        if path and path ~= "" then\n'
        '            SLINK_ROOT = path:gsub("\\\\", "/") .. "/"\n'
        '        end\n'
        '    end\n'
        'end\n'
        '\n'
        'if not SLINK_ROOT then\n'
        '    error("[SLink] No project folder selected — cannot start.", 2)\n'
        'end\n'
        '\n'
        '-- Save path for next run\n'
        'local f = io.open(_cfg_path, "w")\n'
        'if f then f:write(SLINK_ROOT); f:close() end\n'
        '\n'
        'dofile(SLINK_ROOT .. "lua/slink.lua")\n'
    )

    async def handle_launcher(self, request):
        """GET /launcher/{player} — serve a per-player launcher .lua file."""
        player = request.match_info["player"]
        if player not in ("a", "b"):
            return aiohttp_web.Response(text="player must be 'a' or 'b'", status=400)
        host_header = request.host or "127.0.0.1"
        connect_host = host_header.split(":")[0] or "127.0.0.1"
        run_name = self._run_name or self._run_id or "SLink"
        content = self._LAUNCHER_TEMPLATE.format(
            run_name=lua_comment(run_name),
            player_upper=player.upper(),
            host=lua_string(connect_host),
            tcp_port=self._tcp_port,
            player=lua_string(player),
        )
        safe_name = re.sub(r'[^\w-]', '_', run_name).strip('_') or "SLink"
        filename = f"slink_{safe_name}_{player}.lua"
        return aiohttp_web.Response(
            text=content,
            content_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Twitch bot management page ───────────────────────────────────────────


    async def handle_twitch_page(self, request):
        from markupsafe import Markup

        context = {"sidebar_html": Markup(self._build_sidebar_html("twitch")),
                   "page_title": self._page_title()}
        return aiohttp_jinja2.render_template("twitch.html", request, context)

    # ── OBS integration page & API ────────────────────────────────────────────


    async def handle_obs_page(self, request):
        from markupsafe import Markup

        context = {"sidebar_html": Markup(self._build_sidebar_html("obs")),
                   "page_title": self._page_title()}
        return aiohttp_jinja2.render_template("obs.html", request, context)

    async def handle_obs_status(self, request):
        """GET /api/obs/status — connection status + config (passwords omitted)."""
        status = self.obs.get_status()
        # Include triggers (no passwords in triggers)
        status["triggers"] = self.obs._config.get("triggers", [])
        return aiohttp_web.json_response(status)

    async def handle_obs_config(self, request):
        """POST /api/obs/config — save config and hot-reload connections."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        new_cfg = {
            "enabled": bool(body.get("enabled", False)),
            "connections": {},
            "triggers": body.get("triggers", []),
        }
        for pid in ("a", "b"):
            conn_in = body.get("connections", {}).get(pid, {})
            existing_pw = self.obs._config.get("connections", {}).get(pid, {}).get("password", "")
            new_cfg["connections"][pid] = {
                "host": str(conn_in.get("host", "")),
                "port": int(conn_in.get("port", 4455)),
                # Empty password = keep existing; non-empty = update
                "password": conn_in.get("password") or existing_pw,
            }
        # Ensure each trigger has an id
        import uuid as _uuid
        for t in new_cfg["triggers"]:
            if not t.get("id"):
                t["id"] = _uuid.uuid4().hex[:8]
        await self.obs.apply_new_config(new_cfg)
        return aiohttp_web.json_response({"ok": True})

    async def handle_obs_triggers(self, request):
        """POST /api/obs/triggers — save only the triggers list (auto-save, no creds)."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        import uuid as _uuid
        triggers = body.get("triggers", [])
        for t in triggers:
            if not t.get("id"):
                t["id"] = _uuid.uuid4().hex[:8]
        # Update triggers in-place — don't restart OBS connections (would briefly disconnect both players)
        self.obs._config["triggers"] = triggers
        self.obs.save_config()
        return aiohttp_web.json_response({"ok": True})

    async def handle_obs_scenes(self, request):
        """GET /api/obs/scenes/{player} — list available scene names from OBS."""
        player = request.match_info.get("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "scenes": []}, status=400)
        scenes = await self.obs.list_scenes(player)
        return aiohttp_web.json_response({"ok": True, "scenes": scenes})

    async def handle_obs_test(self, request):
        """POST /api/obs/test — fire a test scene change immediately."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        player = body.get("player", "a")
        scene  = body.get("scene", "")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "Invalid player"}, status=400)
        if not scene:
            return aiohttp_web.json_response({"ok": False, "error": "scene required"}, status=400)
        result = await self.obs.test_scene(player, scene)
        return aiohttp_web.json_response(result)

    async def handle_obs_connect(self, request):
        """POST /api/obs/connect — save connection settings for this player and (re)connect."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        player = body.get("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "Invalid player"}, status=400)
        # Persist any connection settings provided — preserves the other player's settings
        host = str(body.get("host", "")).strip()
        port_raw = body.get("port")
        port = int(port_raw) if port_raw else None
        password = body.get("password")  # None = not provided; "" = explicitly cleared
        if host or port is not None or password:
            conns = {k: dict(v) for k, v in self.obs._config.get("connections", {}).items()}
            conn = dict(conns.get(player, {}))
            if host:
                conn["host"] = host
            if port is not None:
                conn["port"] = port
            if password:  # only update if non-empty; blank = keep existing
                conn["password"] = password
            conns[player] = conn
            self.obs._config = {**self.obs._config, "connections": conns}
            self.obs.save_config()
        await self.obs.connect_player(player)
        return aiohttp_web.json_response({"ok": True})

    async def handle_obs_disconnect(self, request):
        """POST /api/obs/disconnect — disconnect a player's OBS."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        player = body.get("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "Invalid player"}, status=400)
        await self.obs.disconnect_player(player)
        return aiohttp_web.json_response({"ok": True})

    def _load_known_area_ids(self) -> list[str]:
        """Return every area_id known to the active game's area maps, sorted.

        Reads all area_map*.json files in data/games/<game_id>/, handling the
        four formats currently in use (gen1/2 object-of-objects, gen3 flat
        bank:map → slug, gen4 slug → {display,maps}, gen5 list of zone records).
        Falls back to gen3_frlge if the adapter's game dir doesn't exist.
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        game_id = self.adapter.game_id if self.adapter else "gen3_frlge"
        game_dir = os.path.join(base_dir, "data", "games", game_id)
        if not os.path.isdir(game_dir):
            game_dir = os.path.join(base_dir, "data", "games", "gen3_frlge")
        area_ids: set[str] = set()
        try:
            entries = os.listdir(game_dir)
        except OSError:
            return []
        for fname in entries:
            if not (fname.startswith("area_map") and fname.endswith(".json")):
                continue
            try:
                with open(os.path.join(game_dir, fname)) as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                for k, v in data.items():
                    if k.startswith("_"):  # _comment etc
                        continue
                    if isinstance(v, dict) and "area_id" in v:
                        # gen1/gen2: {id_str: {area_id, name}}
                        if v["area_id"]:
                            area_ids.add(v["area_id"])
                    elif isinstance(v, str) and v:
                        # gen3: {bank:map: area_slug}
                        area_ids.add(v)
                    elif isinstance(v, dict) and "display" in v:
                        # gen4: {area_slug: {display, maps}}
                        area_ids.add(k)
            elif isinstance(data, list):
                # gen5: [{zone_id, area_id, name}, ...]
                for entry in data:
                    if isinstance(entry, dict) and entry.get("area_id"):
                        area_ids.add(entry["area_id"])
        return sorted(area_ids)

    async def handle_obs_areas(self, request):
        """GET /api/obs/areas — grouped area list for the active game.

        Response shape:
            {
              "game_id": "gen3_frlge",
              "groups":  [{"id": "route", "label": "Routes", "count": 25}, ...],
              "areas":   [{"id": "route_1", "name": "Route 1", "group": "route"}, ...],
            }
        """
        area_ids = self._load_known_area_ids()
        # Bucket by group, preserving the AREA_GROUPS display order
        grouped: dict[str, list[dict]] = {g["id"]: [] for g in AREA_GROUPS}
        for aid in area_ids:
            gid = classify_area(aid)
            if gid not in grouped:
                gid = "other"
            name = self.adapter.area_display_name(aid) if self.adapter else aid
            grouped[gid].append({"id": aid, "name": name, "group": gid})
        groups_out: list[dict] = []
        areas_out: list[dict] = []
        for g in AREA_GROUPS:
            items = grouped.get(g["id"], [])
            if not items:
                continue
            items.sort(key=lambda a: a["name"].lower())
            groups_out.append({"id": g["id"], "label": g["label"], "count": len(items)})
            areas_out.extend(items)
        return aiohttp_web.json_response({
            "game_id": self.adapter.game_id if self.adapter else "",
            "groups":  groups_out,
            "areas":   areas_out,
        })

    async def handle_bot_status(self, request):
        """GET /api/bot/status — returns current bot status + config + recent activity."""
        cfg = _bot_load_config(self._data_dir)
        access_token = os.environ.get("TWITCH_ACCESS_TOKEN", "")
        connected = (self._bot_instance is not None
                     and self._bot_task is not None
                     and not self._bot_task.done()
                     and bool(access_token))
        status = "disabled" if not cfg.get("enabled", True) else ("connected" if connected else "disconnected")
        return aiohttp_web.json_response({
            "ok": True,
            "status": status,
            "access_token_set": bool(access_token),
            "client_id_set": bool(cfg.get("client_id", "")),
            "last_error": self._bot_last_error,
            "channel": cfg.get("channel", ""),
            "config": {k: v for k, v in cfg.items() if k != "token"},
            "activity": list(self._bot_activity[-50:]),
        })

    async def handle_bot_config(self, request):
        """POST /api/bot/config — save non-sensitive config to data/twitch_bot.json."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        cfg = _bot_load_config(self._data_dir)
        allowed = {"channel", "nick", "prefix", "command_cooldown_sec", "enabled", "client_id"}
        for k in allowed:
            if k in body:
                cfg[k] = body[k]
        _bot_save_config(self._data_dir, cfg)
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_reload(self, request):
        """POST /api/bot/reload — cancel + restart the bot task."""
        await self._restart_bot()
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_enable(self, request):
        """POST /api/bot/enable — mark enabled in config and restart."""
        cfg = _bot_load_config(self._data_dir)
        cfg["enabled"] = True
        _bot_save_config(self._data_dir, cfg)
        await self._restart_bot()
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_disable(self, request):
        """POST /api/bot/disable — mark disabled and cancel task."""
        cfg = _bot_load_config(self._data_dir)
        cfg["enabled"] = False
        _bot_save_config(self._data_dir, cfg)
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._bot_task = None
        self._bot_instance = None
        return aiohttp_web.json_response({"ok": True})

    async def handle_bot_preview(self, request):
        """POST /api/bot/preview — return what a command would reply without sending."""
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        cmd = (body.get("command") or "").lower().strip()
        arg = (body.get("arg") or "").strip()
        if self._bot_instance:
            reply = await self._bot_instance.build_reply(cmd, arg)
        else:
            try:
                from server.twitch_bot import build_reply_standalone
                reply = await build_reply_standalone(cmd, arg, self, self._data_dir or DATA_DIR)
            except Exception as e:
                reply = f"(Bot not running — {e})"
        return aiohttp_web.json_response({"ok": True, "reply": reply})

    async def _restart_bot(self):
        """Cancel the existing bot task (if any) and start a fresh one."""
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._bot_task = None
        self._bot_instance = None
        cfg = _bot_load_config(self._data_dir)
        if not cfg.get("enabled", True):
            return
        access_token = os.environ.get("TWITCH_ACCESS_TOKEN", "")
        if not access_token:
            self._bot_last_error = (
                "TWITCH_ACCESS_TOKEN environment variable is not set. "
                "Set it before starting the server (see /twitch for instructions)."
            )
            log.warning("Twitch bot: TWITCH_ACCESS_TOKEN not set — bot disabled")
            return
        refresh_token = os.environ.get("TWITCH_REFRESH_TOKEN", "")
        client_secret = os.environ.get("TWITCH_CLIENT_SECRET", "")
        if not client_secret:
            self._bot_last_error = (
                "TWITCH_CLIENT_SECRET environment variable is not set. "
                "Generate a Client Secret at dev.twitch.tv/console → your app → New Secret."
            )
            log.warning("Twitch bot: TWITCH_CLIENT_SECRET not set — bot disabled")
            return
        client_id = cfg.get("client_id", "")
        if not client_id:
            self._bot_last_error = (
                "Client ID is not configured. Register an app at dev.twitch.tv/console, "
                "copy the Client ID, and save it in the config form."
            )
            log.warning("Twitch bot: client_id not set — bot disabled")
            return
        if not cfg.get("channel"):
            self._bot_last_error = "Channel is not configured. Enter a channel name and save."
            log.warning("Twitch bot: channel not set — bot disabled")
            return
        self._bot_last_error = ""
        try:
            from server.twitch_bot import SLinkChatBot
            bot = SLinkChatBot(
                self, self._data_dir or DATA_DIR, cfg,
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
            )
            self._bot_instance = bot
            self._bot_task = asyncio.create_task(bot.start())
            self._bot_task.add_done_callback(self._on_bot_done)
            log.info(f"Twitch bot started for channel #{cfg.get('channel','?')}")
        except Exception as e:
            self._bot_last_error = f"Startup failed: {e}"
            log.error(f"Twitch bot startup failed: {e}")

    def _on_bot_done(self, task):
        if task.cancelled():
            pass
        elif task.exception():
            err = str(task.exception())
            self._bot_last_error = f"Connection failed: {err}"
            log.error(f"Twitch bot task failed: {err}")
            entry = {"ts": datetime.utcnow().isoformat(), "text": f"⚠ Error: {err}"}
            self._bot_activity.append(entry)
            if len(self._bot_activity) > 50:
                self._bot_activity = self._bot_activity[-50:]
        self._bot_task = None
        self._bot_instance = None

    # ── Debug page & API ─────────────────────────────────────────────────────

    async def handle_debug_html(self, request):
        from markupsafe import Markup

        context = {"sidebar_html": Markup(self._build_sidebar_html("debug")),
                   "page_title": self._page_title()}
        return aiohttp_jinja2.render_template("debug.html", request, context)

    async def handle_debug_manual_link_data(self, request):
        """GET /api/debug/manual_link_data — return mon options + area data for manual linking."""
        s = self.state
        # Build reverse map: monKey → pending area
        pending_key_to_area: dict[tuple, str] = {}
        for pc_area, players in s.pending_captures.items():
            for pid_pc, mon_pc in players.items():
                pending_key_to_area[(pid_pc, mon_pc.key)] = pc_area

        result: dict = {}
        for pid in ["a", "b"]:
            opts = []
            seen_keys = set()
            # Party mons
            for key in self._get_party_ordered(pid):
                det = self.party_details[pid][key]
                nick = det.get("nickname", "")
                sid = det.get("species_id", 0)
                sp_name = self.adapter.species_name(sid) if sid else "?"
                lv = det.get("level", 0)
                linked = key in s._key_index
                label = f"{nick or sp_name} Lv{lv} [{key[:8]}]"
                pend = pending_key_to_area.get((pid, key), "")
                opts.append({"key": key, "label": label, "linked": linked,
                             "pending_area": pend, "loc": "party"})
                seen_keys.add(key)
            # Box mons
            for bentry in self.pc_boxes.get(pid, []):
                key = bentry.get("key", "")
                if not key:
                    continue
                nick = bentry.get("nickname", "")
                sid = bentry.get("species_id", 0)
                sp_name = self.adapter.species_name(sid) if sid else "?"
                box_num = bentry.get("box", 0) + 1
                linked = key in s._key_index
                label = f"{nick or sp_name} [Box{box_num}] [{key[:8]}]"
                pend = pending_key_to_area.get((pid, key), "")
                opts.append({"key": key, "label": label, "linked": linked,
                             "pending_area": pend, "loc": "box"})
                seen_keys.add(key)
            # Linked/dead/memorial mons from link entries (not already shown)
            for entry in s.links:
                mon = entry.a if pid == "a" else entry.b
                if not mon or mon.key in seen_keys:
                    continue
                nick = mon.nickname or ""
                sp_name = self.adapter.species_name(mon.species) if mon.species else "?"
                status_tag = entry.status.value.upper()
                label = f"{nick or sp_name} Lv{mon.level} [{mon.key[:8]}] ({status_tag})"
                opts.append({"key": mon.key, "label": label, "linked": True,
                             "pending_area": "", "loc": status_tag.lower()})
                seen_keys.add(mon.key)
            # Pending captures not yet in party/box display (e.g. quarantined)
            for pc_area, players in s.pending_captures.items():
                cap = players.get(pid)
                if cap and cap.key not in seen_keys:
                    sp_name = self.adapter.species_name(cap.species) if cap.species else "?"
                    label = f"{cap.nickname or sp_name} Lv{cap.level} [{cap.key[:8]}] (PENDING)"
                    opts.append({"key": cap.key, "label": label, "linked": False,
                                 "pending_area": pc_area, "loc": "pending"})
                    seen_keys.add(cap.key)
            result[f"{pid}_options"] = opts

        # Build area list
        try:
            _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # Try adapter-specific area map first, fall back to gen3_frlge
            _game_id = self.adapter.game_id if self.adapter else "gen3_frlge"
            _map_path = os.path.join(_base_dir, "data", "games", _game_id, "area_map.json")
            if not os.path.exists(_map_path):
                _map_path = os.path.join(_base_dir, "data", "games", "gen3_frlge", "area_map.json")
            with open(_map_path) as _mf:
                _all_area_ids = sorted({v for v in json.load(_mf).values() if v})
        except Exception:
            _all_area_ids = []
        all_area_set = set(_all_area_ids)
        for extra_src in [s.area_states.keys(), s.pending_captures.keys()]:
            for extra in extra_src:
                if extra and extra not in all_area_set:
                    _all_area_ids.append(extra)
                    all_area_set.add(extra)
        if "gift" not in all_area_set:
            _all_area_ids.append("gift")
        _all_area_ids.sort()

        area_data: dict[str, dict] = {}
        for aid in _all_area_ids:
            disp = self.adapter.area_display_name(aid)
            st = s.area_states.get(aid)
            st_str = st.value if st else "unseen"
            pend_who = ""
            if aid in s.pending_captures:
                pend_who = ",".join(sorted(s.pending_captures[aid].keys()))
            area_data[aid] = {"d": disp, "s": st_str, "p": pend_who}

        result["areas"] = area_data
        result["area_ids"] = _all_area_ids
        result["name_a"] = self.trainer_name.get("a") or "Player A"
        result["name_b"] = self.trainer_name.get("b") or "Player B"
        return aiohttp_web.json_response(result)

    async def handle_debug_raw_state(self, request):
        """GET /api/debug/raw_state — return raw links.json content + live state."""
        s = self.state
        raw = {}
        if os.path.exists(s._links_path):
            with open(s._links_path) as f:
                raw = json.load(f)
        raw["_live"] = {
            "queued_commands": {p: list(cmds) for p, cmds in s.queued_commands.items()},
            "connected_players": {p: dict(d) for p, d in self.connected_players.items()},
            "player_area": dict(self.player_area),
            "player_ball_count": dict(self.player_ball_count),
            "party_keys": {p: sorted(keys) for p, keys in s.party_keys.items()},
            "bonus_keys": {p: sorted(keys) for p, keys in s.bonus_keys.items()},
            "pending_bonus": {p: list(q) for p, q in s.pending_bonus.items()},
            "party_size": dict(s.party_size),
            "identity_errors": dict(s.identity_error),
            "battle_state": {p: {"in_battle": bs["in_battle"],
                                  "is_trainer": bs["is_trainer_battle"]}
                             for p, bs in self.battle_state.items()},
            "recent_events": list(self._recent_events),
        }
        # Memorial data for debug panel
        mem_box_idx = self.adapter.memorial_box_index if self.adapter else -1
        memorial_log = []
        mem_path = s._memorial_path
        if os.path.exists(mem_path):
            try:
                with open(mem_path) as mf:
                    memorial_log = json.load(mf)
            except Exception:
                pass
        # Build memorial box contents from pc_boxes (mons in the memorial box)
        memorial_box_contents: dict[str, list] = {}
        if mem_box_idx >= 0:
            # Collect all dead/memorial keys from link entries for cross-referencing
            dead_keys: set[str] = set()
            pending_mem_keys: set[str] = set()
            pending_cap_keys: set[str] = set()
            for entry in s.links:
                if entry.status.value in ("dead", "memorial"):
                    if entry.a:
                        dead_keys.add(entry.a.key)
                    if entry.b:
                        dead_keys.add(entry.b.key)
            for pid in ("a", "b"):
                pending_mem_keys.update(s.pending_memorials.get(pid, set()))
                for _area, players in s.pending_captures.items():
                    cap = players.get(pid)
                    if cap:
                        pending_cap_keys.add(cap.key)
            for pid in ("a", "b"):
                entries = []
                for bentry in self.pc_boxes.get(pid, []):
                    if bentry.get("box") == mem_box_idx:
                        key = bentry.get("key", "")
                        status = "dead" if key in dead_keys else "unknown"
                        if key in pending_mem_keys and status == "unknown":
                            status = "pending_memorial"
                        if key in pending_cap_keys:
                            status = "quarantined"  # should NOT be here
                        entries.append({
                            "slot": bentry.get("slot", 0),
                            "key": key,
                            "species_id": bentry.get("species_id", 0),
                            "nickname": bentry.get("nickname", ""),
                            "species_name": self.adapter.species_name(bentry.get("species_id", 0)) if self.adapter else "",
                            "status": status,
                        })
                entries.sort(key=lambda e: e["slot"])
                memorial_box_contents[pid] = entries
        raw["_memorial"] = {
            "memorial_box_index": mem_box_idx,
            "memorial_log": memorial_log,
            "memorial_box_contents": memorial_box_contents,
            "pending_memorials": {
                pid: [
                    {
                        "key": k,
                        "species_name": self._memorial_key_species(k),
                    }
                    for k in keys
                ]
                for pid, keys in s.pending_memorials.items()
            },
        }
        return aiohttp_web.json_response(raw)

    async def handle_debug_inject_event(self, request):
        """POST /api/debug/inject_event — send a synthetic event through the state machine."""
        restriction = self._restricted_operation_response("debug_mutation")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        player = body.pop("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "player must be 'a' or 'b'"}, status=400)
        if "event" not in body:
            return aiohttp_web.json_response({"ok": False, "error": "event field required"}, status=400)
        try:
            cmds = self.state.handle_event(player, body)
            self._notify_sse()
            return aiohttp_web.json_response({
                "ok": True,
                "player": player,
                "event": body.get("event"),
                "commands_returned": cmds,
            })
        except Exception as e:
            log.exception(f"Debug inject_event error: {e}")
            return aiohttp_web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_debug_queue_command(self, request):
        """POST /api/debug/queue_command — manually queue a command for a player."""
        restriction = self._restricted_operation_response("debug_mutation")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        player = body.pop("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "player must be 'a' or 'b'"}, status=400)
        cmd_type = body.get("cmd", "noop")
        cmd = {"cmd": cmd_type}
        for k, v in body.items():
            if k not in ("player",):
                cmd[k] = v
        self.state.queued_commands.setdefault(player, []).append(cmd)
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "player": player,
            "command": cmd,
            "queue_length": len(self.state.queued_commands[player]),
        })

    async def handle_debug_set_pokeballs(self, request):
        """POST /api/debug/set_pokeballs — toggle pokeballs_obtained."""
        restriction = self._restricted_operation_response("debug_mutation")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        player = body.get("player", "a")
        if player not in ("a", "b"):
            return aiohttp_web.json_response({"ok": False, "error": "player must be 'a' or 'b'"}, status=400)
        value = bool(body.get("value", True))
        self.state.pokeballs_obtained[player] = value
        self.state._save()
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True, "player": player,
            "pokeballs_obtained": value,
        })

    async def handle_debug_set_area_state(self, request):
        """POST /api/debug/set_area_state — manually set an area's state."""
        restriction = self._restricted_operation_response("debug_mutation")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        area_id = body.get("area_id", "").strip()
        new_state = body.get("state", "").strip()
        if not area_id:
            return aiohttp_web.json_response({"ok": False, "error": "area_id required"}, status=400)
        from server.state import AreaStatus
        valid = {s.value: s for s in AreaStatus}
        if new_state not in valid:
            return aiohttp_web.json_response({"ok": False, "error": f"Invalid state. Valid: {list(valid.keys())}"}, status=400)
        if new_state == "unseen":
            self.state.area_states.pop(area_id, None)
        else:
            self.state.area_states[area_id] = valid[new_state]
        self.state._save()
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True, "area_id": area_id, "state": new_state,
        })

    async def handle_debug_clear_pending(self, request):
        """POST /api/debug/clear_pending — clear pending captures (all or by area)."""
        restriction = self._restricted_operation_response("debug_mutation")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            body = {}
        area_id = body.get("area_id", "").strip()
        if area_id:
            removed = area_id in self.state.pending_captures
            self.state.pending_captures.pop(area_id, None)
            msg = f"Cleared pending for {area_id}" if removed else f"No pending for {area_id}"
        else:
            count = len(self.state.pending_captures)
            self.state.pending_captures.clear()
            msg = f"Cleared all pending captures ({count} areas)"
        self.state._save()
        self._notify_sse()
        return aiohttp_web.json_response({"ok": True, "message": msg})

    async def handle_debug_unlink(self, request):
        """POST /api/debug/unlink — remove a link entry.

        Body: {"area_id": "route_1", "index": 0}
        Uses index as tiebreaker if multiple links share an area (shouldn't happen
        but be safe). Removes the link entry, cleans up _key_index and area_states.
        """
        restriction = self._restricted_operation_response("debug_mutation")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        area_id = body.get("area_id", "").strip()
        idx = body.get("index", -1)
        if not area_id:
            return aiohttp_web.json_response({"ok": False, "error": "area_id required"}, status=400)

        from server.state import AreaStatus

        s = self.state
        # Find the entry — match by area_id and list index for safety
        entry = None
        if isinstance(idx, int) and 0 <= idx < len(s.links):
            candidate = s.links[idx]
            if candidate.area_id == area_id:
                entry = candidate
        # Fallback: search by area_id
        if entry is None:
            for e in s.links:
                if e.area_id == area_id:
                    entry = e
                    break
        if entry is None:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"No link found for area {area_id}"}, status=404)

        # Remove from _key_index
        if entry.a and entry.a.key in s._key_index:
            del s._key_index[entry.a.key]
        if entry.b and entry.b.key in s._key_index:
            del s._key_index[entry.b.key]

        # Remove from links list
        s.links.remove(entry)

        # Reset area state to unseen (unless there are pending captures)
        if area_id in s.pending_captures:
            remaining = s.pending_captures[area_id]
            if "a" in remaining and "b" not in remaining:
                s.area_states[area_id] = AreaStatus.PENDING_B
            elif "b" in remaining and "a" not in remaining:
                s.area_states[area_id] = AreaStatus.PENDING_A
            elif "a" in remaining and "b" in remaining:
                s.area_states[area_id] = AreaStatus.PENDING_BOTH
        else:
            s.area_states[area_id] = AreaStatus.UNSEEN

        a_name = entry.a.nickname if entry.a else "?"
        b_name = entry.b.nickname if entry.b else "?"

        s._save()
        log.info(f"[unlink] Removed link: {a_name} <-> {b_name} on {area_id}")
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "message": f"Unlinked {a_name} <-> {b_name} on {self.adapter.area_display_name(area_id)}. Area reset.",
        })

    async def handle_debug_revive(self, request):
        """POST /api/debug/revive — revive a dead/memorial link back to alive.

        Body: {"area_id": "route_22", "index": 0}
        Sets status back to alive, clears death metadata, removes from pending_memorials,
        and re-adds keys to party_keys. User must manually restore mons in-game.
        """
        restriction = self._restricted_operation_response("debug_mutation")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        area_id = body.get("area_id", "").strip()
        idx = body.get("index", -1)
        if not area_id:
            return aiohttp_web.json_response({"ok": False, "error": "area_id required"}, status=400)

        from server.state import LinkStatus

        s = self.state
        # Find the entry
        entry = None
        if isinstance(idx, int) and 0 <= idx < len(s.links):
            candidate = s.links[idx]
            if candidate.area_id == area_id:
                entry = candidate
        if entry is None:
            for e in s.links:
                if e.area_id == area_id and e.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL):
                    entry = e
                    break
        if entry is None:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"No dead/memorial link found for area {area_id}"}, status=404)
        if entry.status == LinkStatus.ALIVE:
            return aiohttp_web.json_response(
                {"ok": False, "error": "Link is already alive"}, status=400)

        # Revive: set status to alive, clear death metadata
        entry.status = LinkStatus.ALIVE
        entry.killed_at = None
        entry.cause = None
        entry.killer = None
        entry.initiating_player = None

        # Remove from pending_memorials and re-add to party_keys
        if entry.a:
            s.pending_memorials["a"].discard(entry.a.key)
            s.party_keys["a"].add(entry.a.key)
        if entry.b:
            s.pending_memorials["b"].discard(entry.b.key)
            s.party_keys["b"].add(entry.b.key)

        a_name = entry.a.nickname if entry.a else "?"
        b_name = entry.b.nickname if entry.b else "?"

        s._save()
        log.info(f"[revive] Revived link: {a_name} <-> {b_name} on {area_id}")
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "message": f"Revived {a_name} <-> {b_name} on {self.adapter.area_display_name(area_id)}. Restore mons from memorial box manually.",
        })

    async def handle_debug_list_backups(self, request):
        """GET /api/debug/backups — list available rolling backups with summary."""
        backup_dir = os.path.join(os.path.dirname(self.state._links_path), "backups")
        backups = []
        if os.path.isdir(backup_dir):
            for i in range(1, self._backup_max + 1):
                fp = os.path.join(backup_dir, f"links.backup.{i}.json")
                if os.path.exists(fp):
                    stat = os.stat(fp)
                    entry: dict = {
                        "slot": i,
                        "file": f"links.backup.{i}.json",
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    # Read backup JSON for summary stats
                    try:
                        with open(fp) as fh:
                            data = json.loads(fh.read())
                        links = data.get("links", [])
                        alive = sum(1 for lnk in links if lnk.get("status") == "alive")
                        dead = sum(1 for lnk in links if lnk.get("status") in ("dead", "memorial"))
                        areas = data.get("area_states", {})
                        pending = sum(1 for v in areas.values() if v.startswith("pending"))
                        dead_zones = sum(1 for v in areas.values() if v == "dead_zone")
                        entry["summary"] = {
                            "links_alive": alive,
                            "links_dead": dead,
                            "areas_pending": pending,
                            "areas_dead_zone": dead_zones,
                        }
                    except Exception:
                        entry["summary"] = None
                    backups.append(entry)
        return aiohttp_web.json_response({"ok": True, "backups": backups})

    async def handle_debug_rollback(self, request):
        """POST /api/debug/rollback — restore links.json (and events.json) from a backup slot."""
        restriction = self._restricted_operation_response("restore")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        slot = body.get("slot")
        if not isinstance(slot, int) or slot < 1 or slot > self._backup_max:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"Invalid slot (1-{self._backup_max})"}, status=400)
        backup_dir = os.path.join(os.path.dirname(self.state._links_path), "backups")
        backup_links  = os.path.join(backup_dir, f"links.backup.{slot}.json")
        backup_events = os.path.join(backup_dir, f"events.backup.{slot}.json")
        if not os.path.exists(backup_links):
            return aiohttp_web.json_response(
                {"ok": False, "error": f"Backup slot {slot} not found"}, status=404)
        os.makedirs(backup_dir, exist_ok=True)
        # Save current state as pre-rollback snapshots
        if os.path.exists(self.state._links_path):
            shutil.copy2(self.state._links_path,
                         os.path.join(backup_dir, "links.pre_rollback.json"))
        if os.path.exists(self._events_path):
            shutil.copy2(self._events_path,
                         os.path.join(backup_dir, "events.pre_rollback.json"))
        # Restore links.json and reload state
        shutil.copy2(backup_links, self.state._links_path)
        self.state = SoulLinkState.load(
            data_dir=self._data_dir,
            species_lock=self.state.species_lock,
            gender_lock=self.state.gender_lock,
            type_lock=self.state.type_lock,
            explode_mode=self.state.explode_mode,
            rival_team_swap=self.state.rival_team_swap,
            overworld_presence=self.state.overworld_presence,
            native_messages=self.state.native_messages,
            native_sounds=self.state.native_sounds,
            battle_calc=self.state.battle_calc,
            pc_trade_npc=self.state.pc_trade_npc)
        self.adapter = self.state.adapter
        # Restore events.json and reload ring buffer
        if os.path.exists(backup_events):
            shutil.copy2(backup_events, self._events_path)
        else:
            # No events backup for this slot — clear the ring buffer so it stays in sync.
            with open(self._events_path, "w") as _ef:
                _ef.write("[]")
        self._load_events()
        log.warning(f"⚠  Rolled back to backup slot {slot}")
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "message": f"Rolled back to backup slot {slot}. Pre-rollback state saved."
        })

    async def handle_reset_api(self, request):
        """POST /api/reset — wipe all Soul Link state and start a fresh run."""
        restriction = self._restricted_operation_response("reset")
        if restriction is not None:
            return restriction
        links_path = self.state._links_path
        if os.path.exists(links_path):
            os.remove(links_path)
        self.state = SoulLinkState(data_dir=self._data_dir,
                                   species_lock=self.state.species_lock,
                                   gender_lock=self.state.gender_lock,
                                   type_lock=self.state.type_lock,
                                   explode_mode=self.state.explode_mode,
                                   rival_team_swap=self.state.rival_team_swap,
                                   overworld_presence=self.state.overworld_presence,
                                   native_messages=self.state.native_messages,
                                   native_sounds=self.state.native_sounds,
                                   battle_calc=self.state.battle_calc,
                                   pc_trade_npc=self.state.pc_trade_npc)
        self.adapter = self.state.adapter
        self._last_seq.clear()
        self._gen1_sessions = gen1_admission.SessionGate()
        self._connection_owners.clear()
        self.admission.clear()
        self.connected_players.clear()
        # Clear derived display caches so SSE doesn't broadcast stale data.
        self.player_area = {"a": "", "b": ""}
        self.player_area_id = {"a": "", "b": ""}
        self.player_ball_count = {"a": 0, "b": 0}
        self.player_badges = {"a": 0, "b": 0}
        self.player_kanto_badges = {"a": 0, "b": 0}
        self.trainer_name = {"a": "", "b": ""}
        self.pc_boxes = {"a": [], "b": []}
        self.party_details = {"a": {}, "b": {}}
        self._mon_cache.clear()
        self.battle_state = {
            p: {"in_battle": False, "is_trainer_battle": False, "enemy_party": [],
                "trainer_id": 0, "opponent_name": "", "opponent_class": "",
                "is_doubles": False}
            for p in ("a", "b")
        }
        self._recent_events.clear()
        self._save_events()
        log.warning("⚠  State reset via API — all links, area states, and captures cleared.")
        self._notify_sse()
        return aiohttp_web.json_response({"ok": True, "message": "State reset. Starting fresh run."})

    def _memorial_key_species(self, key: str) -> str:
        """Look up a species name for a pending memorial key."""
        s = self.state
        entry = s._key_index.get(key)
        if entry:
            mon = entry.a if (entry.a and entry.a.key == key) else entry.b
            if mon:
                name = mon.nickname or (self.adapter.species_name(mon.species) if mon.species else "")
                if name:
                    return name
        return key[:8] if key else "?"

    def _memorial_box_indices(self) -> set[int]:
        """Return set of box indices used for memorial storage (primary + overflow).

        The primary memorial box is always excluded. Overflow is calculated from
        the number of dead/memorial links — each dead link contributes one mon per
        player to the memorial boxes. Boxes fill at 30 mons each.
        """
        from server.state import LinkStatus
        mem_idx = self.adapter.memorial_box_index if self.adapter else -1
        if mem_idx < 0:
            return set()
        indices = {mem_idx}
        mons_per_box = self.adapter.mons_per_box if self.adapter else 30
        # Count dead/memorial mons: each such link has one mon per player in memorial
        dead_count = sum(1 for e in self.state.links
                         if e.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL))
        # Add pending memorials (not yet moved but will be)
        for pid in ("a", "b"):
            dead_count += len(self.state.pending_memorials[pid])
        # How many overflow boxes beyond the primary?
        overflow_boxes = max(0, (dead_count - mons_per_box) // mons_per_box)
        for i in range(1, overflow_boxes + 1):
            if mem_idx - i >= 0:
                indices.add(mem_idx - i)
        return indices

    def _check_memorial_box_contamination(self, player_id: str, pc_boxes: list):
        """Scan pc_boxes for memorial box integrity violations and take corrective action.

        Three checks (all require a dedicated memorial box, i.e. mem_idx >= 0):

        1. Non-dead mon in memorial box — quarantine relocation (existing behaviour).
           A pending-capture that somehow ended up in the memorial box is pulled out
           and re-deposited to a normal box via party_mon + box_mon.

        2. Dead/memorial mon found in a regular (non-memorial) box — re-memorialize.
           Handles the case where a player manually retrieves a dead mon from the
           memorial box via the PC menu, or a write glitch placed it in the wrong box.

        3. Orphan in memorial box — log-only warning.
           A mon in the memorial box whose key is not tracked as dead/memorial and is
           not in pending_memorials.  We don't auto-fix this because it may be a mon
           the player placed there manually; it is surfaced as "unknown" in the debug
           panel so a human can investigate.
        """
        mem_idx = self.adapter.memorial_box_index if self.adapter else -1
        if mem_idx < 0:
            return
        s = self.state

        # Collect keys that belong in the memorial box (dead/memorial link entries).
        all_dead_keys: set[str] = set()
        for entry in s.links:
            if entry.status.value in ("dead", "memorial"):
                if entry.a:
                    all_dead_keys.add(entry.a.key)
                if entry.b:
                    all_dead_keys.add(entry.b.key)

        # Also treat pending_memorials for *this* player as "expected in memorial box"
        # so they are not flagged as orphans while still in transit.
        pending_for_player: set[str] = set(s.pending_memorials.get(player_id, set()))
        expected_in_memorial = all_dead_keys | pending_for_player

        for bentry in pc_boxes:
            box = bentry.get("box")
            key = bentry.get("key", "")
            if not key:
                continue
            nick = bentry.get("nickname", "") or (
                self.adapter.species_name(bentry.get("species_id", 0)) if self.adapter else key[:8]
            )

            if box == mem_idx:
                # ── Check 1: non-dead mon in memorial box ──────────────────────
                if key not in expected_in_memorial:
                    # Once per key, like Check 3 twenty lines below. Unguarded, this
                    # re-logged on every event carrying pc_boxes -- roughly twice a
                    # second, forever -- and the trigger is ordinary: the Gen 1
                    # memorial box IS Box 12 (SRAM 0x75EA = sBox12), so anything the
                    # player ever stored there, or any mon revived from the dashboard,
                    # is permanently "unexpected".
                    if (player_id, key) not in self._warned_memorial_keys:
                        self._warned_memorial_keys.add((player_id, key))
                        log.warning(
                            f"[{player_id}] ⚠ NON-DEAD mon in memorial box: {nick} "
                            f"[{key[:8]}] (box {mem_idx} slot {bentry.get('slot', '?')})"
                        )
                    # Relocate if it is a quarantined pending capture.
                    for _area, players in s.pending_captures.items():
                        cap = players.get(player_id)
                        if cap and cap.key == key:
                            log.warning(
                                f"[{player_id}] Quarantined mon {key[:8]} found in memorial box! "
                                f"Queueing party_mon + box_mon to relocate."
                            )
                            stats = s.mon_stats.get(key, {})
                            s.queued_commands[player_id].append({"cmd": "party_mon", "key": key, "stats": stats})
                            s.queued_commands[player_id].append({"cmd": "box_mon", "key": key})
                            break

                    # ── Check 3: orphan in memorial box (log-only, once per key) ────
                    # Only log if not a quarantine case (already logged above).
                    else:
                        if key not in self._warned_orphan_keys:
                            self._warned_orphan_keys.add(key)
                            log.warning(
                                f"[{player_id}] ⚠ Orphan mon in memorial box: {nick} [{key[:8]}] "
                                f"(box {mem_idx} slot {bentry.get('slot', '?')}) — "
                                f"not tracked as dead/memorial; investigate manually"
                            )

            elif key in all_dead_keys:
                # ── Check 2: dead/memorial mon found in a regular box ───────────
                # This happens if the player moved a dead mon out of the memorial box
                # via the PC, or if a previous memorialize write went to the wrong box.
                already_queued = any(
                    c.get("cmd") == "memorialize" and c.get("key") == key
                    for c in s.queued_commands.get(player_id, [])
                )
                if not already_queued:
                    log.warning(
                        f"[{player_id}] ⚠ DEAD mon in regular box {box}: {nick} [{key[:8]}] "
                        f"(slot {bentry.get('slot', '?')}) — re-queuing memorialize"
                    )
                    s._queue_memorialize(player_id, key)

    def _get_party_ordered(self, pid: str) -> list:
        """Return monKeys for player `pid` sorted by party slot order.

        Uses the ``slot`` field stored in party_details (populated from the Lua
        snapshot's ``slot=i`` field).  Falls back to 999 for old clients that
        don't send slot info, which puts them at the end in original order.
        """
        pd = self.party_details.get(pid, {})
        return sorted(pd.keys(), key=lambda k: pd[k].get("slot", 999))

    def _resolve_level(self, player_id: str, mi) -> int:
        """Return the best available level for a MonInfo.

        Falls back through mon_stats cache and party_details when the stored
        level is 0 (e.g. manual links that didn't capture level at creation).
        """
        if not mi:
            return 0
        if mi.level:
            return mi.level
        # Try mon_stats cache (set when mon was deposited to box)
        cached = self.state.mon_stats.get(mi.key)
        if cached and cached.get("level"):
            return cached["level"]
        # Try live party_details from either player
        for pid in ("a", "b"):
            det = self.party_details.get(pid, {}).get(mi.key)
            if det and det.get("level"):
                return det["level"]
        return 0

    def _lookup_mon_detail(self, player_id: str, key: str) -> dict:
        """Look up mon details from party_details first, then pc_boxes.

        Enriches with level from mon_stats cache or the link entry when the
        primary source (e.g. pc_boxes) doesn't carry it.
        """
        det = self.party_details.get(player_id, {}).get(key)
        if det:
            return det
        result: dict = {}
        for bentry in self.pc_boxes.get(player_id, []):
            if bentry.get("key") == key:
                result = dict(bentry)
                break
        if not result:
            # Check pending_captures as last resort
            for _area, players in self.state.pending_captures.items():
                mon = players.get(player_id)
                if mon and mon.key == key:
                    return {"nickname": mon.nickname, "species_id": mon.species, "level": mon.level}
        # Enrich with level from mon_stats cache or existing link entry
        if result and not result.get("level"):
            cached = self.state.mon_stats.get(key)
            if cached and cached.get("level"):
                result["level"] = cached["level"]
            else:
                link_entry = self.state._key_index.get(key)
                if link_entry:
                    mi = link_entry.a if link_entry.a and link_entry.a.key == key else link_entry.b
                    if mi and mi.level:
                        result["level"] = mi.level
        # Also check the OTHER player's party_details (for solo-testing with same OT)
        if result and not result.get("level"):
            other = "b" if player_id == "a" else "a"
            other_det = self.party_details.get(other, {}).get(key)
            if other_det and other_det.get("level"):
                result["level"] = other_det["level"]
        return result

    def _find_pending_area_for_key(self, player_id: str, key: str) -> str | None:
        """Return the area_id where this key has a pending capture, or None."""
        for area, players in self.state.pending_captures.items():
            mon = players.get(player_id)
            if mon and mon.key == key:
                return area
        return None

    async def handle_inject_link_api(self, request):
        """POST /api/inject_link — manually create a linked pair.

        Body (JSON): {"a_key": "...", "b_key": "...", "area_id": "route_1",
                      "force": false}

        Looks up mon info from party, box, AND pending_captures.
        If either mon has a pending capture on a different area than specified
        and force is not set, returns a warning with requires_force=true.
        On success, cleans up pending_captures and updates area_states.
        """
        restriction = self._restricted_operation_response("manual_link")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        a_key  = body.get("a_key", "").strip()
        b_key  = body.get("b_key", "").strip()
        area   = body.get("area_id", "manual").strip()
        force  = body.get("force", False)
        override = body.get("override", False)
        if not a_key or not b_key:
            return aiohttp_web.json_response(
                {"ok": False, "error": "a_key and b_key are required"}, status=400)

        from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo

        s = self.state

        # If override requested, unlink existing entries for these keys
        if override:
            for key_to_free in [a_key, b_key]:
                old_entry = s._key_index.get(key_to_free)
                if old_entry:
                    if old_entry.a and old_entry.a.key in s._key_index:
                        del s._key_index[old_entry.a.key]
                    if old_entry.b and old_entry.b.key in s._key_index:
                        del s._key_index[old_entry.b.key]
                    if old_entry in s.links:
                        s.links.remove(old_entry)
                    old_area = old_entry.area_id
                    if old_area and old_area != area and old_area not in s.pending_captures:
                        s.area_states[old_area] = AreaStatus.UNSEEN
                    log.info(f"[inject_link] override: removed old link on {old_area}")

        # Reject already-linked keys (unless override already cleared them)
        if a_key in s._key_index:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"Player A mon {a_key[:8]} is already linked."}, status=400)
        if b_key in s._key_index:
            return aiohttp_web.json_response(
                {"ok": False, "error": f"Player B mon {b_key[:8]} is already linked."}, status=400)

        # Detect pending-area conflicts
        a_pend_area = self._find_pending_area_for_key("a", a_key)
        b_pend_area = self._find_pending_area_for_key("b", b_key)
        conflicts = []
        if a_pend_area and a_pend_area != area:
            a_det = self._lookup_mon_detail("a", a_key)
            a_name = a_det.get("nickname") or f"#{a_det.get('species_id', '?')}"
            conflicts.append(f"Player A's {a_name} is pending on {self.adapter.area_display_name(a_pend_area)}")
        if b_pend_area and b_pend_area != area:
            b_det = self._lookup_mon_detail("b", b_key)
            b_name = b_det.get("nickname") or f"#{b_det.get('species_id', '?')}"
            conflicts.append(f"Player B's {b_name} is pending on {self.adapter.area_display_name(b_pend_area)}")
        if conflicts and not force:
            return aiohttp_web.json_response({
                "ok": False, "requires_force": True,
                "conflicts": conflicts,
                "error": " | ".join(conflicts) + " — use Link anyway to override.",
            })

        # Pull mon info from party, box, or pending_captures
        a_det = self._lookup_mon_detail("a", a_key)
        b_det = self._lookup_mon_detail("b", b_key)
        entry = LinkEntry(
            area_id=area,
            a=MonInfo(key=a_key,
                      nickname=a_det.get("nickname", ""),
                      species=a_det.get("species_id", 0),
                      level=a_det.get("level", 0)),
            b=MonInfo(key=b_key,
                      nickname=b_det.get("nickname", ""),
                      species=b_det.get("species_id", 0),
                      level=b_det.get("level", 0)),
            status=LinkStatus.ALIVE,
        )
        s.links.append(entry)
        s._index_entry(entry)
        s.area_states[area] = AreaStatus.LINKED

        # Clean up pending_captures for both mons
        for pid, _key, pend_area in [("a", a_key, a_pend_area), ("b", b_key, b_pend_area)]:
            if pend_area and pend_area in s.pending_captures:
                s.pending_captures[pend_area].pop(pid, None)
                if not s.pending_captures[pend_area]:
                    del s.pending_captures[pend_area]
                # Recompute area_state for the old pending area (if different from link area)
                if pend_area != area:
                    remaining = s.pending_captures.get(pend_area, {})
                    if not remaining:
                        # No one pending here anymore — revert to unseen
                        s.area_states[pend_area] = AreaStatus.UNSEEN
                    elif "a" in remaining and "b" not in remaining:
                        s.area_states[pend_area] = AreaStatus.PENDING_B
                    elif "b" in remaining and "a" not in remaining:
                        s.area_states[pend_area] = AreaStatus.PENDING_A
            # Also clean pending on the link area itself
            if area in s.pending_captures:
                s.pending_captures[area].pop(pid, None)
                if not s.pending_captures[area]:
                    del s.pending_captures[area]

        # Only add to party_keys if the mon is actually in the party
        if a_key in self.party_details.get("a", {}):
            s.party_keys["a"].add(a_key)
        if b_key in self.party_details.get("b", {}):
            s.party_keys["b"].add(b_key)

        s._save()
        a_name = a_det.get("nickname") or a_key[:8]
        b_name = b_det.get("nickname") or b_key[:8]
        log.info(f"[inject_link] A:{a_name}({a_key[:8]}) <-> B:{b_name}({b_key[:8]}) area={area}")
        self._notify_sse()
        return aiohttp_web.json_response({
            "ok": True,
            "a_key": a_key, "b_key": b_key, "area_id": area,
            "message": f"Linked {a_name} <-> {b_name} on {self.adapter.area_display_name(area)}.",
        })

    async def handle_inject_link_by_slot_api(self, request):
        """POST /api/inject_link_by_slot — link party slots without knowing the keys.

        Body (JSON): {"a_slot": 0, "b_slot": 0, "area_id": "test"}
        Resolves slot indices to keys, then delegates to handle_inject_link_api.
        """
        restriction = self._restricted_operation_response("manual_link")
        if restriction is not None:
            return restriction
        try:
            body = await request.json()
        except Exception:
            return aiohttp_web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

        a_slot = int(body.get("a_slot", 0))
        b_slot = int(body.get("b_slot", 0))

        s = self.state
        a_keys = sorted(s.party_keys.get("a", set()))
        b_keys = sorted(s.party_keys.get("b", set()))

        if not a_keys:
            return aiohttp_web.json_response(
                {"ok": False, "error": "No party keys known for player A."}, status=400)
        if not b_keys:
            return aiohttp_web.json_response(
                {"ok": False, "error": "No party keys known for player B."}, status=400)
        if a_slot >= len(a_keys):
            return aiohttp_web.json_response(
                {"ok": False, "error": f"a_slot {a_slot} out of range (A has {len(a_keys)} party mons)"}, status=400)
        if b_slot >= len(b_keys):
            return aiohttp_web.json_response(
                {"ok": False, "error": f"b_slot {b_slot} out of range (B has {len(b_keys)} party mons)"}, status=400)

        # Build a fake request that delegates to inject_link
        resolved = {
            "a_key": a_keys[a_slot], "b_key": b_keys[b_slot],
            "area_id": body.get("area_id", "manual"),
            "force": body.get("force", False),
        }
        class _Req:
            async def json(self_): return resolved
        return await self.handle_inject_link_api(_Req())


# ── entrypoint ─────────────────────────────────────────────────────────────────


def build_app(srv):
    """Build the aiohttp app with every route registered.

    Extracted from main() so tests can construct the SAME app and walk the SAME route
    table — a test that re-declared the routes would drift the moment one was added here.
    """
    app = aiohttp_web.Application(middlewares=[csrf_protection, theme_cache])
    setup_templating(app)
    app.router.add_get("/",            srv.handle_status_html)
    app.router.add_get("/memorial",    srv.handle_memorial_html)
    app.router.add_get("/api/status",  srv.handle_status_json)
    app.router.add_get("/api/events",  srv.handle_sse)
    app.router.add_post("/api/reset",              srv.handle_reset_api)
    app.router.add_post("/api/inject_link",        srv.handle_inject_link_api)
    app.router.add_post("/api/inject_link_by_slot", srv.handle_inject_link_by_slot_api)
    # Stream overlay routes
    app.router.add_get("/stream",          srv.handle_stream_index)
    app.router.add_get("/stream/",         srv.handle_stream_index)
    app.router.add_get("/stream/party-a",          srv.handle_stream_party_a)
    app.router.add_get("/stream/party-b",          srv.handle_stream_party_b)
    # HTMX poll targets for the templated party overlay — return only the
    # #root subtree so idiomorph swaps in place without re-rendering the
    # vendored script tags.
    app.router.add_get("/stream/party-a/fragment", srv.handle_stream_party_a_fragment)
    app.router.add_get("/stream/party-b/fragment", srv.handle_stream_party_b_fragment)
    app.router.add_get("/stream/enemy-focus-a/fragment",    srv.handle_stream_enemy_focus_a_fragment)
    app.router.add_get("/stream/enemy-focus-b/fragment",    srv.handle_stream_enemy_focus_b_fragment)
    app.router.add_get("/stream/enemy-trainer-a/fragment",  srv.handle_stream_enemy_trainer_a_fragment)
    app.router.add_get("/stream/enemy-trainer-b/fragment",  srv.handle_stream_enemy_trainer_b_fragment)
    app.router.add_get("/stream/focus-a/fragment",          srv.handle_stream_focus_a_fragment)
    app.router.add_get("/stream/focus-b/fragment",          srv.handle_stream_focus_b_fragment)
    app.router.add_get("/stream/enemy-focus-a",   srv.handle_stream_enemy_focus_a)
    app.router.add_get("/stream/enemy-focus-b",   srv.handle_stream_enemy_focus_b)
    app.router.add_get("/stream/enemy-trainer-a", srv.handle_stream_enemy_trainer_a)
    app.router.add_get("/stream/enemy-trainer-b", srv.handle_stream_enemy_trainer_b)
    app.router.add_get("/stream/links",                  srv.handle_stream_links)
    app.router.add_get("/stream/links/fragment",         srv.handle_stream_links_fragment)
    app.router.add_get("/stream/linked-party",           srv.handle_stream_linked_party)
    app.router.add_get("/stream/linked-party/fragment",  srv.handle_stream_linked_party_fragment)
    app.router.add_get("/stream/boxed-links",            srv.handle_stream_boxed_links)
    app.router.add_get("/stream/boxed-links/fragment",   srv.handle_stream_boxed_links_fragment)
    app.router.add_get("/stream/deaths",            srv.handle_stream_deaths)
    app.router.add_get("/stream/deaths/fragment",   srv.handle_stream_deaths_fragment)
    app.router.add_get("/stream/attempts",          srv.handle_stream_attempts)
    app.router.add_get("/stream/attempts/fragment", srv.handle_stream_attempts_fragment)
    app.router.add_post("/api/attempts",   srv.handle_api_attempts)
    app.router.add_get("/stream/areas",             srv.handle_stream_areas)
    app.router.add_get("/stream/areas/fragment",    srv.handle_stream_areas_fragment)
    app.router.add_get("/stream/events",            srv.handle_stream_events)
    app.router.add_get("/stream/events/fragment",   srv.handle_stream_events_fragment)
    app.router.add_get("/stream/badges-a",          srv.handle_stream_badges_a)
    app.router.add_get("/stream/badges-a/fragment", srv.handle_stream_badges_a_fragment)
    app.router.add_get("/stream/badges-b",          srv.handle_stream_badges_b)
    app.router.add_get("/stream/badges-b/fragment", srv.handle_stream_badges_b_fragment)
    app.router.add_get("/stream/encounters",            srv.handle_stream_encounters)
    app.router.add_get("/stream/encounters/fragment",   srv.handle_stream_encounters_fragment)
    app.router.add_get("/stream/stream-memorial",           srv.handle_stream_stream_memorial)
    app.router.add_get("/stream/stream-memorial/fragment",  srv.handle_stream_stream_memorial_fragment)
    app.router.add_get("/stream/ticker",            srv.handle_stream_ticker)
    app.router.add_get("/stream/ticker/fragment",   srv.handle_stream_ticker_fragment)
    app.router.add_get("/stream/focus-a",         srv.handle_stream_focus_a)
    app.router.add_get("/stream/focus-b",         srv.handle_stream_focus_b)
    app.router.add_get("/stream/area-encounter",            srv.handle_stream_area_encounter)
    app.router.add_get("/stream/area-encounter/fragment",   srv.handle_stream_area_encounter_fragment)
    app.router.add_get("/stream/enc-table-a",               srv.handle_stream_enc_table_a)
    app.router.add_get("/stream/enc-table-a/fragment",      srv.handle_stream_enc_table_a_fragment)
    app.router.add_get("/stream/enc-table-b",               srv.handle_stream_enc_table_b)
    app.router.add_get("/stream/enc-table-b/fragment",      srv.handle_stream_enc_table_b_fragment)
    app.router.add_get("/launcher/{player}", srv.handle_launcher)
    # Twitch bot routes
    app.router.add_get("/twitch",               srv.handle_twitch_page)
    app.router.add_get("/api/bot/status",       srv.handle_bot_status)
    app.router.add_post("/api/bot/config",      srv.handle_bot_config)
    app.router.add_post("/api/bot/reload",      srv.handle_bot_reload)
    app.router.add_post("/api/bot/enable",      srv.handle_bot_enable)
    app.router.add_post("/api/bot/disable",     srv.handle_bot_disable)
    app.router.add_post("/api/bot/preview",     srv.handle_bot_preview)
    # OBS scene trigger routes
    app.router.add_get("/obs",                  srv.handle_obs_page)
    app.router.add_get("/api/obs/status",       srv.handle_obs_status)
    app.router.add_post("/api/obs/config",      srv.handle_obs_config)
    app.router.add_post("/api/obs/triggers",    srv.handle_obs_triggers)
    app.router.add_get("/api/obs/scenes/{player}", srv.handle_obs_scenes)
    app.router.add_get("/api/obs/areas",        srv.handle_obs_areas)
    app.router.add_post("/api/obs/test",        srv.handle_obs_test)
    app.router.add_post("/api/obs/connect",     srv.handle_obs_connect)
    app.router.add_post("/api/obs/disconnect",  srv.handle_obs_disconnect)
    # Debug routes
    app.router.add_get("/debug",                       srv.handle_debug_html)
    app.router.add_get("/api/debug/raw_state",         srv.handle_debug_raw_state)
    app.router.add_get("/api/debug/manual_link_data",  srv.handle_debug_manual_link_data)
    app.router.add_post("/api/debug/inject_event",     srv.handle_debug_inject_event)
    app.router.add_post("/api/debug/queue_command",    srv.handle_debug_queue_command)
    app.router.add_post("/api/debug/set_pokeballs",    srv.handle_debug_set_pokeballs)
    app.router.add_post("/api/debug/set_area_state",   srv.handle_debug_set_area_state)
    app.router.add_post("/api/debug/clear_pending",    srv.handle_debug_clear_pending)
    app.router.add_post("/api/debug/unlink",            srv.handle_debug_unlink)
    app.router.add_post("/api/debug/revive",            srv.handle_debug_revive)
    app.router.add_get("/api/debug/backups",            srv.handle_debug_list_backups)
    app.router.add_post("/api/debug/rollback",          srv.handle_debug_rollback)
    # RR Damage Calculator routes
    app.router.add_get("/calc",           srv.handle_calc_redirect)
    app.router.add_get("/calc/",          srv.handle_calc_redirect)
    app.router.add_get("/calc/{path:.*}", srv.handle_calc_files)
    app.router.add_get("/api/calc/mons",  srv.handle_calc_mons)

    from server.patcher import setup_patcher_routes
    setup_patcher_routes(app, srv._build_sidebar_html)
    return app


async def main(host: str, port: int, http_port: int, reset: bool = False,
               data_dir: str = None, run_id: str = None, run_name: str = "",
               species_lock: bool = False, gender_lock: bool = False,
               type_lock: bool = False, explode_mode: bool = False,
               rival_team_swap: bool = False, overworld_presence: bool = False,
               native_messages: bool = False, native_sounds: bool = False,
               battle_calc: bool = True, pc_trade_npc: bool = True,
               manager_port: int = 0, verbose: bool = False):
    _configure_logging(data_dir, verbose)
    if reset:
        links_path = os.path.join(data_dir, "links.json") if data_dir else LINKS_PATH
        if os.path.exists(links_path):
            os.remove(links_path)
            log.warning("⚠  --reset: links.json deleted. Starting a fresh run.")
        else:
            log.info("--reset: no existing state found, starting fresh.")
    srv = SLinkServer(data_dir=data_dir, run_id=run_id, run_name=run_name,
                      tcp_port=port, manager_port=manager_port,
                      species_lock=species_lock, gender_lock=gender_lock,
                      type_lock=type_lock, explode_mode=explode_mode,
                      rival_team_swap=rival_team_swap,
                      overworld_presence=overworld_presence,
                      native_messages=native_messages,
                      native_sounds=native_sounds,
                      battle_calc=battle_calc,
                      pc_trade_npc=pc_trade_npc)

    # TCP game server.
    # limit=4 MiB lifts asyncio's default 64 KiB readline buffer so Gen 5's
    # full party+box hello payload (24 boxes × 30 slots × ~150 bytes JSON ≈ 110 KiB)
    # doesn't trip LimitOverrunError and force the connection closed each tick.
    # Gen 4 (18 boxes) and Gen 1-3 (smaller PCs) fit under the old limit but get
    # the bigger headroom for free.
    try:
        tcp_server = await asyncio.start_server(srv.handle_client, host, port,
                                                limit=4 * 1024 * 1024)
    except OSError as e:
        # A bare traceback here reads as "SLink is broken" when it almost always means the port
        # is taken — usually a server the user forgot they left running.
        raise SystemExit(
            f"\nCannot listen on TCP {host}:{port} — {e}\n"
            "  Another SLink server is probably already running.\n"
            f"  Use a different port:  python -m server.server --port {port + 10}\n"
        ) from None
    addrs = ", ".join(str(s.getsockname()) for s in tcp_server.sockets)
    run_label = f" [{run_id}]" if run_id else ""
    log.info(f"SLink{run_label} TCP server listening on {addrs}")

    # Start rolling backup task
    srv.start_backup_task()
    # Start OBS worker tasks
    srv.obs.start_workers()

    # HTTP status page
    if AIOHTTP_AVAILABLE:
        app = build_app(srv)
        runner = aiohttp_web.AppRunner(app)
        await runner.setup()
        http_site = aiohttp_web.TCPSite(runner, host, http_port)
        try:
            await http_site.start()
        except OSError as e:
            await runner.cleanup()
            tcp_server.close()
            raise SystemExit(
                f"\nCannot listen on HTTP {host}:{http_port} — {e}\n"
                "  The dashboard port is in use (the Run Manager uses 8090, and the runs\n"
                "  it spawns start at 8081).\n"
                f"  Use a different port:  python -m server.server --http-port {http_port + 10}\n"
            ) from None
        # Start Twitch bot if configured
        await srv._restart_bot()
        log.info(f"SLink{run_label} status page at http://{host if host != '0.0.0.0' else 'localhost'}:{http_port}/")
    else:
        log.warning("aiohttp not installed — HTTP status page disabled. Run: pip install aiohttp")
        runner = None

    async with tcp_server:
        await tcp_server.serve_forever()

    if runner:
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SLink Soul Link server")
    parser.add_argument("--host",      default="0.0.0.0",  help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port",      type=int, default=54321, help="TCP port (default: 54321)")
    parser.add_argument("--http-port", type=int, default=8080,  help="HTTP status port (default: 8080)")
    parser.add_argument("--reset",     action="store_true",     help="Clear all saved state and start a fresh run")
    parser.add_argument("--data-dir",  default=None,            help="Data directory for links/memorial JSON (default: data/)")
    parser.add_argument("--run-id",    default=None,            help="Optional run label (used in log output)")
    parser.add_argument("--run-name",  default="",              help="Human-readable run name (shown in page title)")
    parser.add_argument("--species-clause", action="store_true", dest="species_lock", help="Reject links where both mons share the same evolution family")
    parser.add_argument("--gender-clause",  action="store_true", dest="gender_lock",  help="Reject links where both mons share the same gender")
    parser.add_argument("--type-clause",    action="store_true", dest="type_lock",    help="Reject links where both mons share any type")
    parser.add_argument("--explode-mode",   action="store_true", dest="explode_mode", help="On partner death, force the linked mon to auto-Explode (RR only; menu-skip via Variant-3 memory writes)")
    parser.add_argument("--rival-team-swap", action="store_true", dest="rival_team_swap",
        help="On rival battles, replace the rival's team with the partner's current party (RR only; mirrors --explode-mode as an opt-in per-run rule)")
    parser.add_argument("--overworld-presence", action="store_true", dest="overworld_presence",
        help="Peer ghost: render your partner walking your overworld as a live NPC (RR + companion patch required; opt-in per-run rule)")
    parser.add_argument("--native-messages", action="store_true", dest="native_messages",
        help="Show SLink notifications via the companion patch's native message box / in-battle text instead of the Lua HUD overlay (RR + patch; default off)")
    parser.add_argument("--native-sounds", action="store_true", dest="native_sounds",
        help="Play SLink notification sounds via the companion patch's native PlaySE (RR + patch; default off)")
    parser.add_argument("--no-battle-calc", action="store_false", dest="battle_calc",
        help="Hide the bundled Battle Calc damage display (RR + patch; shown by default)")
    parser.add_argument("--no-pc-trade-npc", action="store_false", dest="pc_trade_npc",
        help="Disable the Pokémon-Center trade NPC (RR + patch; on by default, only active while overworld presence is off)")
    parser.add_argument("--manager-port", type=int, default=0,   help="Manager HTTP port (enables 'Run Manager' link on status page)")
    parser.add_argument("--verbose",      action="store_true",   help="Enable DEBUG-level logging to file and console (default: INFO only)")
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port, args.http_port, args.reset, args.data_dir, args.run_id,
                     run_name=args.run_name,
                     species_lock=args.species_lock, gender_lock=args.gender_lock,
                     type_lock=args.type_lock,
                     explode_mode=args.explode_mode,
                     rival_team_swap=args.rival_team_swap,
                     overworld_presence=args.overworld_presence,
                     native_messages=args.native_messages,
                     native_sounds=args.native_sounds,
                     battle_calc=args.battle_calc,
                     pc_trade_npc=args.pc_trade_npc,
                     manager_port=args.manager_port,
                     verbose=args.verbose))
