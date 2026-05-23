"""
server/state.py — SoulLinkState: Soul Link Nuzlocke finite state machine.

Processes events from both BizHawk instances, updates shared Soul Link state,
and emits commands back to each game.

Commands for the requesting player are returned immediately.
Commands for the partner are queued and delivered on the partner's next event.

Persistence:
    data/links.json   — link table + area states (written on every state change)
    data/memorial.json — Phase 4 (retired pair log)

When `data_dir` is passed to SoulLinkState() / SoulLinkState.load(), those files
are written inside `data_dir` instead of the global DATA_DIR.  The manager uses
this to give each run its own isolated data directory.
"""

import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from server.adapters.base import GameRulesAdapter
from server.pokemon_data import _parse_pid_otid_key, pid_otid_shiny

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LINKS_PATH    = os.path.join(DATA_DIR, "links.json")
MEMORIAL_PATH = os.path.join(DATA_DIR, "memorial.json")

class AreaStatus(str, Enum):
    UNSEEN      = "unseen"
    PENDING_A   = "pending_a"    # A captured/entered; B not yet resolved
    PENDING_B   = "pending_b"    # B captured/entered; A not yet resolved
    PENDING_BOTH = "pending_both"  # both entered, neither resolved yet
    LINKED      = "linked"
    DEAD_ZONE   = "dead_zone"


class LinkStatus(str, Enum):
    ALIVE    = "alive"
    DEAD     = "dead"
    MEMORIAL = "memorial"  # Phase 4: moved to Box 13


@dataclass
class MonInfo:
    key: str
    level: int = 0
    species: int = 0
    nickname: str = ""
    is_shiny: bool = False


@dataclass
class LinkEntry:
    area_id: str
    a: Optional[MonInfo]  # Player A's mon; None if A didn't capture
    b: Optional[MonInfo]  # Player B's mon; None if B didn't capture
    status: LinkStatus
    encounter_a: Optional[MonInfo] = None  # A's wild encounter even if not caught (display only)
    encounter_b: Optional[MonInfo] = None  # B's wild encounter even if not caught (display only)
    # Killfeed fields — set at death time, None/empty until the pair dies
    killed_at: Optional[str] = None          # ISO 8601 UTC timestamp
    cause: str = ""                          # "battle", "dead_zone", or "whiteout"
    killer: Optional[dict] = None            # {species, level, is_trainer, trainer_name} (battle only)
    initiating_player: str = ""              # "a" or "b" — whose action triggered the pair death


def _partner(player_id: str) -> str:
    return "b" if player_id == "a" else "a"


def is_shiny(key: str) -> bool:
    """Determine if a mon is shiny from its personality:otId key (Gen III formula).

    NOTE: This is a standalone utility kept for backward compatibility with tests.
    The state machine uses self.adapter.is_shiny() at runtime for game-appropriate logic.
    """
    parsed = _parse_pid_otid_key(key)
    if parsed is None:
        return False
    return pid_otid_shiny(*parsed)


class SoulLinkState:
    def __init__(self, data_dir: str = None, species_lock: bool = False, gender_lock: bool = False, type_lock: bool = False, is_rr: bool = False, adapter: GameRulesAdapter = None):
        # When data_dir is provided (manager mode) use it; otherwise fall back to the
        # module-level globals so monkeypatch works in tests and the standalone server
        # keeps working unchanged.
        self._data_dir      = data_dir if data_dir else DATA_DIR
        self._links_path    = os.path.join(self._data_dir, "links.json") if data_dir else LINKS_PATH
        self._memorial_path = os.path.join(self._data_dir, "memorial.json") if data_dir else MEMORIAL_PATH
        # Whether the connected clients are Radical Red / CFRU (True) or vanilla/AP (False).
        # Controls species ID interpretation — CFRU IDs vs National Dex.
        self.is_rr: bool = is_rr
        # Game adapter — provides game-specific rule logic.
        # Default to Gen3Adapter for backward compatibility.
        if adapter is not None:
            self.adapter = adapter
        else:
            from server.adapters.gen3_frlge import Gen3Adapter
            self.adapter = Gen3Adapter(is_rr=is_rr)
        self.links: list[LinkEntry] = []
        self.area_states: dict[str, AreaStatus] = {}
        # area_id → {player_id → MonInfo} for captures not yet linked
        self.pending_captures: dict[str, dict[str, MonInfo]] = {}
        # monKey → LinkEntry for O(1) faint lookup
        self._key_index: dict[str, LinkEntry] = {}
        # commands queued for delivery to each player on their next request
        self.queued_commands: dict[str, list[dict]] = {"a": [], "b": []}
        # set of monKeys known to be in each player's party right now
        self.party_keys: dict[str, set[str]] = {"a": set(), "b": set()}
        # cached party stats per monKey (populated by party_to_box events, echoed in party_mon)
        self.mon_stats: dict[str, dict] = {}
        # True once the player has entered a non-gift encounter area (Pokéballs guaranteed).
        # no_catch and area state transitions are suppressed until this activates.
        self.pokeballs_obtained: dict[str, bool] = {"a": False, "b": False}
        # Committed ROM type — set once on first hello, persisted across restarts.
        self.rom_type: str = ""
        # Committed trainer names — set once per player on first hello, static for run.
        self.trainer_names: dict[str, str] = {"a": "", "b": ""}
        # monKeys awaiting memorialize_done confirmation from each player
        self.pending_memorials: dict[str, set[str]] = {"a": set(), "b": set()}
        # tracks which players have sent at least one hello this session
        self._has_helld: set[str] = set()
        # Last-known party size for each player (from hello/tick party snapshots).
        # Used to check room for paired retrieval after link formation.
        self.party_size: dict[str, int] = {"a": 0, "b": 0}
        # Lock rules (opt-in, default off)
        self.species_lock: bool = species_lock
        self.gender_lock: bool = gender_lock
        self.type_lock: bool = type_lock
        # Shiny Clause: always on.  Shiny captures are bonus mons outside the link system.
        # Tracked for dedup (prevent duplicate HUD/sound on replayed events).
        self.bonus_keys: dict[str, set[str]] = {"a": set(), "b": set()}
        # Pending bonus encounters: when a player catches a shiny, the partner gets
        # a slot in this FIFO queue.  Their next non-shiny capture becomes the bonus pair partner.
        self.pending_bonus: dict[str, deque[str]] = {"a": deque(), "b": deque()}
        # True once the run is definitively over (no alive links, no pending captures).
        self.run_over: bool = False
        # Manual attempts counter (set by the user via the stream index page).
        self.attempts_count: int = 0
        # Player identity lock: {player_id: {"ot_id": str, "trainer_name": str}}
        # Set on first hello with a non-empty party; verified on subsequent hellos.
        self.player_identity: dict[str, dict] = {}
        # Rejection message for display on status page (cleared on successful hello).
        self.identity_error: dict[str, str] = {}
        # Areas where a species/lock clause rejected a capture — suppress no_catch
        # until the player successfully captures a valid mon on this area.
        self.retry_areas: dict[str, set[str]] = {"a": set(), "b": set()}
        # Areas where dupes clause was already notified at wild battle start.
        # Suppresses the duplicate gui_prompt on the subsequent no_catch event.
        # In-memory only — not persisted (tied to the current session).
        self.dupe_notified_areas: dict[str, set[str]] = {"a": set(), "b": set()}
        # Per-player auto-rebuild context, set when a whiteout fires and the
        # player still has alive linked pairs boxed; cleared once every queued
        # party_mon has been confirmed via sync_retrieve_done or dropped via
        # sync_retrieve_failed. Persisted so a mid-rebuild restart can re-arm.
        self.rebuild_pending: dict[str, Optional[dict]] = {"a": None, "b": None}

    # ── public API ───────────────────────────────────────────────────────────

    def handle_event(self, player_id: str, msg: dict) -> list[dict]:
        """
        Process one event from player_id.
        Returns commands to send back to player_id (including any queued cross-player commands).
        Cross-player commands are queued and delivered on the partner's next call.
        """
        event = msg.get("event", "unknown")

        if event == "hello":
            self._handle_hello(player_id, msg)
        elif event == "area_enter":
            self._handle_area_enter(player_id, msg)
        elif event == "capture":
            self._handle_capture(player_id, msg)
        elif event == "faint":
            self._handle_faint(player_id, msg)
        elif event == "no_catch":
            self._handle_no_catch(player_id, msg)
        elif event == "whiteout":
            self._handle_whiteout(player_id, msg)
        elif event == "party_to_box":
            self._handle_party_to_box(player_id, msg)
        elif event == "box_to_party":
            self._handle_box_to_party(player_id, msg)
        elif event == "key_change":
            self._handle_key_change(player_id, msg)
        elif event == "stats_cache":
            # Stats-only update from exec_box_mon: cache without triggering sync commands.
            # Also mark key as no longer in party so subsequent party_to_box decisions are accurate.
            # Decrement party_size immediately so box_to_party full-party checks use the current
            # count; otherwise party_size stays stale until the next tick (up to 0.5 s), which
            # can cause a false "partner's party full" block if the partner tries to withdraw
            # their linked mon during that window.
            key = msg.get("key", "")
            stats = msg.get("stats")
            if key and stats:
                self.mon_stats[key] = stats
                if key in self.party_keys[player_id]:
                    self.party_size[player_id] = max(0, self.party_size.get(player_id, 0) - 1)
                self.party_keys[player_id].discard(key)
        elif event == "sync_retrieve_done":
            # Sent by exec_party_mon after successfully retrieving a mon from the box.
            key = msg.get("key", "")
            if key:
                self.party_keys[player_id].add(key)
                rb = self.rebuild_pending.get(player_id)
                if rb and key in rb.get("queued_keys", []):
                    rb["restored_keys"].add(key)
                    self._maybe_finish_rebuild(player_id)
        elif event == "sync_retrieve_failed":
            # Retrieval failed (party full, no stats, etc.) — don't add to party_keys.
            # Since both linked mons must stay in sync, re-box the partner's mon too.
            key = msg.get("key", "")
            if key:
                self.party_keys[player_id].discard(key)
                log.info(f"[{player_id}] sync_retrieve_failed for {key[:8]}")
                rb = self.rebuild_pending.get(player_id)
                if rb and key in rb.get("queued_keys", []):
                    # Drop the key from the rebuild plan; corresponding partner
                    # half stays where it is (sync handler below will reconcile
                    # if needed) and the banner clears once everything resolves.
                    rb["queued_keys"] = [k for k in rb["queued_keys"] if k != key]
                    self._maybe_finish_rebuild(player_id)
                # Find the linked partner and re-box them to maintain sync
                entry = self._key_index.get(key)
                if entry and entry.status == LinkStatus.ALIVE:
                    partner = _partner(player_id)
                    partner_mon = entry.a if player_id == "b" else entry.b
                    if partner_mon and partner_mon.key in self.party_keys[partner]:
                        self.queued_commands[partner].append({"cmd": "box_mon", "key": partner_mon.key})
                        self.party_keys[partner].discard(partner_mon.key)
                        self.queued_commands[partner].append({
                            "cmd": "hud_show",
                            "text": "! Partner can't fit -- " + (partner_mon.nickname or self.adapter.species_name(partner_mon.species) or partner_mon.key[:8]) + " re-deposited",
                            "r": 255, "g": 200, "b": 60
                        })
                        log.info(f"[{partner}] re-boxing {partner_mon.key[:8]} — partner's retrieve failed")
        elif event == "memorialize_done":
            self._handle_memorialize_done(player_id, msg)
        elif event == "memorialize_failed":
            self._handle_memorialize_failed(player_id, msg)
        elif event in ("safe", "tick"):
            # Accept pokéballs activation update from tick events so the server learns
            # the nuzlocke became active mid-session (between hello events).
            if msg.get("has_pokeballs") is True:
                self.pokeballs_obtained[player_id] = True
            # Update party size from tick/safe snapshots for paired retrieval checks.
            party = msg.get("party")
            if party is not None:
                old_size = self.party_size.get(player_id, 0)
                self.party_size[player_id] = len(party)
                if old_size != len(party):
                    log.debug(f"[PARTY] player={player_id}  party_size {old_size} → {len(party)}  (tick/safe)")

        cmds = self.queued_commands[player_id][:]
        self.queued_commands[player_id].clear()
        if cmds:
            _summary = ", ".join(
                c.get("cmd", "?") + (":" + c["key"][:8] if "key" in c else "")
                for c in cmds
            )
            log.debug(f"[CMD QUEUE→{player_id}] flushing {len(cmds)} cmd(s): {_summary}")
        return cmds if cmds else [{"cmd": "noop"}]

    @classmethod
    def load(cls, data_dir: str = None, species_lock: bool = False, gender_lock: bool = False, type_lock: bool = False, is_rr: bool = False, adapter: GameRulesAdapter = None) -> "SoulLinkState":
        """Load persisted state from data/links.json, or return a fresh instance."""
        state = cls(data_dir=data_dir, species_lock=species_lock, gender_lock=gender_lock, type_lock=type_lock, is_rr=is_rr, adapter=adapter)
        if not os.path.exists(state._links_path):
            return state
        try:
            with open(state._links_path) as f:
                data = json.load(f)
            for ed in data.get("links", []):
                a = MonInfo(**ed["a"]) if ed.get("a") else None
                b = MonInfo(**ed["b"]) if ed.get("b") else None
                enc_a = MonInfo(**ed["encounter_a"]) if ed.get("encounter_a") else None
                enc_b = MonInfo(**ed["encounter_b"]) if ed.get("encounter_b") else None
                entry = LinkEntry(
                    area_id=ed["area_id"],
                    a=a, b=b,
                    status=LinkStatus(ed["status"]),
                    encounter_a=enc_a,
                    encounter_b=enc_b,
                    killed_at=ed.get("killed_at"),
                    cause=ed.get("cause", ""),
                    killer=ed.get("killer"),
                    initiating_player=ed.get("initiating_player", ""),
                )
                state.links.append(entry)
                state._index_entry(entry)
            for area_id, status_str in data.get("area_states", {}).items():
                state.area_states[area_id] = AreaStatus(status_str)
            for area_id, players in data.get("pending_captures", {}).items():
                state.pending_captures[area_id] = {
                    pid: MonInfo(**mon_data)
                    for pid, mon_data in players.items()
                }
            state.mon_stats = data.get("mon_stats", {})
            # Restore Pokéball gate; default True for both if any links exist
            # (backwards-compat: old saves without this field).
            saved_pb = data.get("pokeballs_obtained", {})
            if saved_pb:
                state.pokeballs_obtained["a"] = bool(saved_pb.get("a", False))
                state.pokeballs_obtained["b"] = bool(saved_pb.get("b", False))
            elif state.links or state.pending_captures:
                # Old save without field but has game state → infer both had Pokéballs.
                state.pokeballs_obtained = {"a": True, "b": True}
            # Restore pending memorials (will be re-queued on next hello from each player).
            saved_pm = data.get("pending_memorials", {})
            state.pending_memorials["a"] = set(saved_pm.get("a", []))
            state.pending_memorials["b"] = set(saved_pm.get("b", []))
            # Restore lock rules from persisted state (CLI flags are initial defaults;
            # saved values take precedence so mid-run restarts honor the original config).
            saved_rules = data.get("rules", {})
            if saved_rules:
                state.species_lock = bool(saved_rules.get("species_lock", species_lock))
                state.gender_lock = bool(saved_rules.get("gender_lock", gender_lock))
                state.type_lock = bool(saved_rules.get("type_lock", type_lock))
            state.run_over = bool(data.get("run_over", False))
            state.attempts_count = int(data.get("attempts_count", 0))
            state.rom_type = data.get("rom_type", "")
            # Infer is_rr from persisted rom_type (belt-and-suspenders with CLI flag)
            if state.rom_type.endswith("_rr"):
                state.is_rr = True
            # Restore game_id — validate adapter matches if one was provided.
            saved_game_id = data.get("game_id", "")
            effective_rr = state.is_rr
            if saved_game_id and state.adapter.game_id != saved_game_id:
                log.warning(f"Saved game_id={saved_game_id!r} differs from adapter "
                            f"game_id={state.adapter.game_id!r}; using saved game_id")
                # Re-resolve adapter from registry if available
                try:
                    from server.adapters import get_adapter
                    state.adapter = get_adapter(saved_game_id, is_rr=effective_rr)
                except (KeyError, ImportError):
                    log.warning(f"No adapter for saved game_id={saved_game_id!r}; keeping current adapter")
            elif effective_rr != getattr(state.adapter, '_is_rr', False):
                # Adapter game_id matches but is_rr flag differs — recreate
                try:
                    from server.adapters import get_adapter
                    state.adapter = get_adapter(state.adapter.game_id, is_rr=effective_rr)
                except (KeyError, ImportError):
                    pass
            saved_names = data.get("trainer_names", {})
            if saved_names:
                state.trainer_names["a"] = saved_names.get("a", "")
                state.trainer_names["b"] = saved_names.get("b", "")
            # Restore player identity lock
            state.player_identity = data.get("player_identity", {})
            # Restore lock-clause retry areas
            saved_retry = data.get("retry_areas", {})
            state.retry_areas["a"] = set(saved_retry.get("a", []))
            state.retry_areas["b"] = set(saved_retry.get("b", []))
            # Restore shiny clause bonus keys
            saved_bonus = data.get("bonus_keys", {})
            state.bonus_keys["a"] = set(saved_bonus.get("a", []))
            state.bonus_keys["b"] = set(saved_bonus.get("b", []))
            # Restore pending bonus encounters (FIFO queue per player)
            saved_pending = data.get("pending_bonus", {})
            state.pending_bonus["a"] = deque(saved_pending.get("a", []))
            state.pending_bonus["b"] = deque(saved_pending.get("b", []))
            # Restore in-flight auto-rebuild context.
            saved_rebuild = data.get("rebuild_pending", {})
            for pid in ("a", "b"):
                rb = saved_rebuild.get(pid)
                if rb:
                    state.rebuild_pending[pid] = {
                        "started_at":         rb.get("started_at", ""),
                        "queued_keys":        list(rb.get("queued_keys", [])),
                        "queued_partner_keys": list(rb.get("queued_partner_keys", [])),
                        "restored_keys":      set(rb.get("restored_keys", [])),
                    }
            log.info(f"Loaded {len(state.links)} links from {state._links_path}")
        except Exception as e:
            log.error(f"Failed to load {state._links_path}: {e}")
        return state

    # ── event handlers ───────────────────────────────────────────────────────

    def _set_area_state(self, area_id: str, new_status: AreaStatus, *,
                        player: str = "", reason: str = "") -> None:
        """Set area_states[area_id] and emit a DEBUG log when the value changes."""
        old = self.area_states.get(area_id, AreaStatus.UNSEEN)
        self.area_states[area_id] = new_status
        if old != new_status:
            ctx_parts = []
            if player:
                ctx_parts.append(f"player={player}")
            if reason:
                ctx_parts.append(f"reason={reason}")
            ctx = "  " + "  ".join(ctx_parts) if ctx_parts else ""
            log.debug(f"[AREA] {area_id}: {old.value} → {new_status.value}{ctx}")

    def _handle_hello(self, player_id: str, msg: dict):
        """
        Reconcile on reconnect.
        Only flags mons that are still IN the party with hp == 0 as newly fainted —
        missing-from-party mons may simply be boxed (do not treat as dead).
        """
        party = msg.get("party", [])
        old_size = self.party_size.get(player_id, 0)
        self.party_size[player_id] = len(party)
        log.debug(f"[PARTY] player={player_id}  party_size {old_size} → {len(party)}  (hello)")

        # ── Identity lock ──
        # Extract OT ID from first party mon's key via the adapter.
        incoming_ot = None
        if party:
            first_key = party[0].get("key", "")
            incoming_ot = self.adapter.parse_ot_id(first_key)
        incoming_name = msg.get("trainer_name", "")

        if incoming_ot:
            existing = self.player_identity.get(player_id)
            if existing:
                if existing["ot_id"] != incoming_ot:
                    partner = _partner(player_id)
                    err = (f"Identity mismatch for slot {player_id.upper()}: "
                           f"expected {existing['trainer_name']} "
                           f"(OT {existing['ot_id'][:8]}), "
                           f"got {incoming_name or '?'} "
                           f"(OT {incoming_ot[:8]})")
                    log.warning(f"[{player_id}] REJECTED: {err}")
                    self.identity_error[player_id] = err
                    # Queue rejection commands — disconnect HUD + refuse processing
                    self.queued_commands[player_id].append({
                        "cmd": "hud_show",
                        "text": f"WRONG SAVE! Slot {player_id.upper()} is locked to {existing['trainer_name']}",
                        "color": [255, 0, 0],
                        "duration": 600,
                    })
                    # Signal the hello was rejected — caller checks this flag
                    msg["_rejected"] = True
                    return
                else:
                    # Identity matches — clear any previous error
                    self.identity_error.pop(player_id, None)
                    log.debug(f"[IDENTITY] player={player_id}  stored_ot={existing['ot_id'][:8]}  "
                              f"incoming_ot={incoming_ot[:8]}  result=ok")
                    # Update trainer name if it changed (e.g. first connect had no name)
                    if incoming_name:
                        self.player_identity[player_id]["trainer_name"] = incoming_name
                        self._save()
            else:
                # First hello with a party — lock identity
                self.player_identity[player_id] = {
                    "ot_id": incoming_ot,
                    "trainer_name": incoming_name or player_id.upper(),
                }
                self.identity_error.pop(player_id, None)
                log.info(f"[{player_id}] Identity locked: {incoming_name or player_id.upper()} (OT {incoming_ot[:8]})")
                self._save()

        # Accept pokéballs status from Lua (M.hasPokeballs() reads actual bag).
        # If the field is absent (old client), fall back to non-empty party heuristic.
        has_pokeballs = msg.get("has_pokeballs")
        if has_pokeballs is True:
            self.pokeballs_obtained[player_id] = True
        elif has_pokeballs is None and party:
            self.pokeballs_obtained[player_id] = True

        # Rebuild party_keys from the snapshot
        self._has_helld.add(player_id)
        # A new hello from player_id means a fresh session start for that player.
        # Discard the partner from _has_helld so any events arriving before the partner's
        # hello use the optimistic path (exec_box_mon is idempotent if key not in party).
        # This prevents stale party_keys from the previous session blocking sync commands.
        self._has_helld.discard(_partner(player_id))
        self.party_keys[player_id] = {
            m["key"] for m in party if m.get("maxHP", 0) > 0
        }
        # Strip dead/memorial mons that may have been re-added (e.g. hp=0 mon still in party
        # slot when a reconnect happens before the Lua sends the faint event back).
        for _k in list(self.party_keys[player_id]):
            _e = self._key_index.get(_k)
            if _e and _e.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL):
                self.party_keys[player_id].discard(_k)

        # Re-quarantine: if any pending (unlinked) captures are in the party,
        # remove from party_keys and re-queue box_mon so they go back to the box.
        # Safety: never quarantine if it would leave the player with no alive mons.
        alive_keys = {m["key"] for m in party if m.get("hp", 0) > 0}
        quarantined = set()
        for area_id, players in self.pending_captures.items():
            cap = players.get(player_id)
            if cap and cap.key in self.party_keys[player_id]:
                remaining_alive = alive_keys - quarantined - {cap.key}
                if not remaining_alive:
                    log.info(f"[{player_id}] skip re-quarantine: {cap.key[:8]} (no alive mons would remain)")
                    continue
                quarantined.add(cap.key)
                self.party_keys[player_id].discard(cap.key)
                self.queued_commands[player_id].append({"cmd": "box_mon", "key": cap.key})
                log.info(f"[{player_id}] re-quarantine on hello: {cap.key[:8]} (pending in {area_id})")

        for m in party:
            key = m.get("key", "")
            hp  = m.get("hp", 1)
            if not key:
                continue
            if hp > 0:
                # Mon is alive — log confirmation if it's a known linked mon.
                entry = self._key_index.get(key)
                if entry and entry.status == LinkStatus.ALIVE:
                    log.debug(f"[RECONCILE] player={player_id}  key={key[:8]}  decision=alive_confirmed")
                continue
            # Mon is in party but hp == 0 → it fainted while we were disconnected.
            # Only treat as a Soul Link death if the nuzlocke run was already active.
            if not self.pokeballs_obtained[player_id]:
                log.debug(f"[RECONCILE] player={player_id}  key={key[:8]}  decision=ignored  reason=pre_nuzlocke")
                continue
            entry = self._key_index.get(key)
            if entry and entry.status == LinkStatus.ALIVE:
                log.info(f"[RECONCILE] player={player_id}  key={key[:8]}  decision=faint_detected  reason=hp=0_in_party")
                self._propagate_faint(player_id, entry, level=m.get("level", 0))
            else:
                reason = "not_linked" if not entry else f"status={entry.status.value}"
                log.debug(f"[RECONCILE] player={player_id}  key={key[:8]}  decision=ignored  reason={reason}")

        # Re-queue any memorials that were not yet confirmed before disconnecting
        for key in list(self.pending_memorials[player_id]):
            if not any(c.get("cmd") == "memorialize" and c.get("key") == key
                       for c in self.queued_commands[player_id]):
                self.queued_commands[player_id].append({"cmd": "memorialize", "key": key})
                log.info(f"[{player_id}] reconnect: re-queued memorialize for {key[:8]}")

        # Dead/memorial mons in party → re-memorialize (handles script reload case
        # where Lua's memorialized_keys is lost and player retrieved a dead mon).
        for m in party:
            key = m.get("key", "")
            if not key:
                continue
            entry = self._key_index.get(key)
            if entry and entry.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL):
                if not any(c.get("cmd") == "memorialize" and c.get("key") == key
                           for c in self.queued_commands[player_id]):
                    self.queued_commands[player_id].append({"cmd": "memorialize", "key": key})
                    self.queued_commands[player_id].append({
                        "cmd": "hud_show",
                        "text": "X Dead mon in party -- returning to memorial",
                        "r": 255, "g": 80, "b": 80
                    })
                    log.warning(f"[{player_id}] hello: {key[:8]} is dead/memorial but in party — re-memorializing")

        # Back-fill display data (nickname/species) for any linked mons whose MonInfo
        # was loaded from links.json without this data (e.g., captured in a prior session).
        display_updated = False
        for m in party:
            key  = m.get("key", "")
            nick = m.get("nickname", "")
            sid  = m.get("species_id", 0)
            if not key or (not nick and not sid):
                continue
            entry = self._key_index.get(key)
            if not entry:
                continue
            mon = entry.a if player_id == "a" else entry.b
            if mon:
                if nick and not mon.nickname:
                    mon.nickname = nick
                    display_updated = True
                if sid and mon.species != sid:
                    mon.species = sid
                    display_updated = True
        if display_updated:
            self._save()

        # Send resolved areas to the client so the encounter HUD doesn't re-fire
        # after a script reload or reconnect.
        resolved = set()
        for area_id, status in self.area_states.items():
            if status in (AreaStatus.LINKED, AreaStatus.DEAD_ZONE):
                resolved.add(area_id)
        # Areas where THIS player already has a pending capture are also resolved.
        for area_id, players in self.pending_captures.items():
            if player_id in players:
                resolved.add(area_id)
        if resolved:
            self.queued_commands[player_id].append({
                "cmd": "resolved_areas", "areas": sorted(resolved)
            })
        else:
            # Always send (even if empty) so client knows seeding is complete
            self.queued_commands[player_id].append({
                "cmd": "resolved_areas", "areas": []
            })

        # Re-arm an in-flight rebuild: reconcile restored_keys from the fresh
        # party snapshot (some party_mons may have executed before disconnect),
        # then re-queue party_mon + rebuild_start for any still-outstanding
        # keys so the auto-rebuild resumes seamlessly.
        rb = self.rebuild_pending.get(player_id)
        if rb:
            queued_keys = list(rb.get("queued_keys", []))
            restored = set(rb.get("restored_keys", set()))
            party_now = self.party_keys[player_id]
            for k in queued_keys:
                if k in party_now:
                    restored.add(k)
            rb["restored_keys"] = restored
            outstanding_picks: list[MonInfo] = []
            for k in queued_keys:
                if k in restored:
                    continue
                entry = self._key_index.get(k)
                if not entry:
                    continue
                mon = entry.a if player_id == "a" else entry.b
                if mon:
                    outstanding_picks.append(mon)
            if outstanding_picks:
                self._queue_rebuild_commands(player_id, outstanding_picks, [])
                log.info(f"[{player_id}] reconnect: re-armed rebuild — "
                         f"{len(outstanding_picks)} outstanding")
            self._maybe_finish_rebuild(player_id)

        # Re-send game_over if the run was already over before this reconnect
        if self.run_over:
            self.queued_commands[player_id].append({"cmd": "game_over"})

    def _handle_area_enter(self, player_id: str, msg: dict):
        area_id = msg.get("area_id", "")
        if not area_id:
            return
        # Gift areas (oaks_lab, intro, etc.) are not encounter areas — their captures
        # are handled directly via _handle_capture.  Don't create pending area state.
        if self.adapter.is_gift_area(area_id):
            return
        # Always track area state — Lua only sends area_enter events once it has confirmed
        # Pokéballs are available (M.hasPokeballs() gate on the client side).
        status = self.area_states.get(area_id, AreaStatus.UNSEEN)
        if status == AreaStatus.UNSEEN:
            # PENDING_X means "waiting for X to act" — the other player already entered.
            self._set_area_state(area_id,
                AreaStatus.PENDING_B if player_id == "a" else AreaStatus.PENDING_A,
                player=player_id)
        elif status == AreaStatus.PENDING_B and player_id == "b":
            self._set_area_state(area_id, AreaStatus.PENDING_BOTH, player=player_id)
        elif status == AreaStatus.PENDING_A and player_id == "a":
            self._set_area_state(area_id, AreaStatus.PENDING_BOTH, player=player_id)
        self._save()

    def _is_gift_capture(self, area_id: str, is_egg: bool) -> bool:
        """Effective gift status for a capture event.

        True if the area is a known gift area OR the capture is a definitive egg
        from outside the daycare (NPC egg-givers in encounter areas).
        """
        if self.adapter.is_gift_area(area_id):
            return True
        if is_egg and not self.adapter.is_daycare_area(area_id):
            return True
        return False

    def _handle_capture(self, player_id: str, msg: dict):
        area_id = msg.get("area_id", "")
        key     = msg.get("key", "")
        if not area_id or not key:
            return
        is_egg  = bool(msg.get("is_egg", False))

        # A catch in any non-gift area confirms Pokéballs are available.
        if not self._is_gift_capture(area_id, is_egg):
            self.pokeballs_obtained[player_id] = True

        # ── Shiny Clause (always on) ──────────────────────────────────────────
        # Shiny captures are bonus mons kept outside the link system.
        # They bypass all area state checks, species/gender/type clauses, and quarantine.
        if self.adapter.is_shiny(key):
            if key in self.bonus_keys[player_id]:
                log.debug(f"[SHINY] player={player_id}  key={key[:8]}  action=duplicate_skip")
                return  # duplicate event, already handled
            self.bonus_keys[player_id].add(key)
            self.party_keys[player_id].add(key)
            partner = _partner(player_id)
            species = msg.get("species_id", 0)
            sname = self.adapter.species_name(species) if species else "Pokémon"
            log.info(f"[{player_id}] ★ SHINY CLAUSE: {sname} ({key[:8]}) in {area_id} — kept as bonus")
            log.debug(f"[SHINY] player={player_id}  key={key[:8]}  action=detected  species={sname}  area={area_id}")
            # Capturing player: shiny sound + prominent GUI prompt
            self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 95})  # SE_SHINY
            self.queued_commands[player_id].append({
                "cmd": "gui_prompt",
                "text": f"* Shiny {sname}! Shiny Clause -- bonus mon!",
                "r": 255, "g": 215, "b": 0,
                "frames": 600,
            })
            # Partner: shiny sound + GUI prompt notification
            self.queued_commands[partner].append({"cmd": "play_sound", "sound": 95})  # SE_SHINY
            self.queued_commands[partner].append({
                "cmd": "gui_prompt",
                "text": f"★ Partner caught a shiny {sname}! Catch anything as your bonus pair!",
                "r": 255, "g": 215, "b": 0,
                "frames": 480,
            })
            # Undo Lua's resolved_areas mark so the normal encounter for this area
            # is not consumed.  Skip if the area is already legitimately resolved
            # or if this player already has a pending capture here.
            status = self.area_states.get(area_id, AreaStatus.UNSEEN)
            already_resolved = status in (AreaStatus.LINKED, AreaStatus.DEAD_ZONE)
            has_pending = bool(self.pending_captures.get(area_id, {}).get(player_id))
            if not already_resolved and not has_pending:
                self.queued_commands[player_id].append({
                    "cmd": "unresolve_area",
                    "area_id": area_id,
                })
            # Queue a pending bonus slot for the partner
            self.pending_bonus[partner].append(key)
            log.debug(f"[SHINY] player={player_id}  key={key[:8]}  action=queued  pending_for={partner}  queue_depth={len(self.pending_bonus[partner])}")
            # Cache stats (including species_id) so bonus pair formation can check lock clauses
            stats = msg.get("stats")
            if not stats:
                lv = msg.get("level", 0)
                mhp = msg.get("maxHP", 0)
                if lv and mhp:
                    stats = {"level": lv, "maxHP": mhp}
            if stats is None:
                stats = {}
            stats["species_id"] = species  # always store, even if 0
            self.mon_stats[key] = stats
            self._save()
            return

        # ── Pending bonus encounter ─────────────────────────────────────────────────
        # If this player has a pending bonus (the partner caught a shiny earlier),
        # intercept this capture to form the bonus pair BEFORE normal area processing.
        if self.pending_bonus[player_id]:
            shiny_key = self.pending_bonus[player_id][0]  # peek; pop only on success
            partner = _partner(player_id)

            # Reconstruct MonInfo for the shiny side using cached stats
            shiny_stats = self.mon_stats.get(shiny_key, {})
            shiny_species = shiny_stats.get("species_id", 0)
            shiny_mon_info = MonInfo(key=shiny_key, species=shiny_species,
                                     level=shiny_stats.get("level", 0),
                                     is_shiny=True)

            cap_species_local = msg.get("species_id", 0)
            this_mon = MonInfo(key=key, level=msg.get("level", 0),
                               nickname=msg.get("nickname", ""),
                               species=cap_species_local)

            # Build a_mon/b_mon for _check_link_violation
            # pending_bonus[player_id] was populated when the PARTNER caught a shiny.
            # So partner's side = shiny, player's side = this new catch.
            if player_id == "a":
                a_mon_for_check = this_mon      # A is catching; A is "a" side
                b_mon_for_check = shiny_mon_info  # partner (B) caught the shiny; B is "b" side
            else:
                a_mon_for_check = shiny_mon_info  # partner (A) caught the shiny; A is "a" side
                b_mon_for_check = this_mon        # B is catching; B is "b" side

            # Check lock clauses
            result = self._check_link_violation(a_mon_for_check, b_mon_for_check)
            if result:
                violation, _violator = result
                log.debug(f"[SHINY] player={player_id}  key={key[:8]}  action=violated  reason={violation!r}  shiny_key={shiny_key[:8]}")
                nickname = msg.get("nickname", "")
                self.party_keys[player_id].discard(key)
                self.queued_commands[player_id].append({"cmd": "force_faint", "key": key, "nickname": nickname})
                self._queue_memorialize(player_id, key)
                self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 26})   # SE_FAILURE
                self.queued_commands[player_id].append({
                    "cmd": "gui_prompt",
                    "text": f"{violation} -- bonus pair rejected, catch again!",
                    "r": 255, "g": 200, "b": 60,
                    "frames": 360,
                })
                # Unresolve area so the player can try their bonus encounter again
                cur_status = self.area_states.get(area_id, AreaStatus.UNSEEN)
                if cur_status not in (AreaStatus.LINKED, AreaStatus.DEAD_ZONE):
                    has_pending = bool(self.pending_captures.get(area_id, {}).get(player_id))
                    if not has_pending:
                        self.queued_commands[player_id].append({
                            "cmd": "unresolve_area",
                            "area_id": area_id,
                        })
                self._save()
                return

            # No violation — form the bonus pair
            self.pending_bonus[player_id].popleft()
            self.bonus_keys[partner].discard(shiny_key)

            bonus_area_id = f"_bonus_{shiny_key[:8]}"
            entry = LinkEntry(area_id=bonus_area_id,
                              a=a_mon_for_check, b=b_mon_for_check,
                              status=LinkStatus.ALIVE)
            self.links.append(entry)
            self._index_entry(entry)

            # Track party presence
            self.party_keys[player_id].add(key)
            # Cache stats for this new catch
            stats_local = msg.get("stats")
            if not stats_local:
                lv = msg.get("level", 0)
                mhp = msg.get("maxHP", 0)
                if lv and mhp:
                    stats_local = {"level": lv, "maxHP": mhp}
            if stats_local:
                stats_local["species_id"] = cap_species_local
                self.mon_stats[key] = stats_local

            # Party sync at formation: both mons should be in the same location.
            bonus_in_box = msg.get("in_box", False)
            shiny_in_party = shiny_key in self.party_keys[partner]
            if bonus_in_box and shiny_in_party:
                # Bonus catch went to box (party full) — sync shiny to box too
                self.queued_commands[partner].append({"cmd": "box_mon", "key": shiny_key})
                self.party_keys[partner].discard(shiny_key)
                log.info(f"[{player_id}] bonus pair formed — shiny {shiny_key[:8]} boxed to sync (bonus in box)")
            elif not bonus_in_box and not shiny_in_party:
                # Shiny is in box — sync bonus catch to box too
                self.queued_commands[player_id].append({"cmd": "box_mon", "key": key})
                self.party_keys[player_id].discard(key)
                log.info(f"[{player_id}] bonus pair formed — {key[:8]} boxed to sync (shiny in box)")

            # Unresolve area so the player's normal area encounter is still available
            cur_status = self.area_states.get(area_id, AreaStatus.UNSEEN)
            if cur_status not in (AreaStatus.LINKED, AreaStatus.DEAD_ZONE):
                has_pending = bool(self.pending_captures.get(area_id, {}).get(player_id))
                if not has_pending:
                    self.queued_commands[player_id].append({
                        "cmd": "unresolve_area",
                        "area_id": area_id,
                    })

            # Notify both players
            cap_sname = self.adapter.species_name(cap_species_local) if cap_species_local else "Pokémon"
            shiny_sname = self.adapter.species_name(shiny_species) if shiny_species else "Pokémon"
            link_text = f"★ Bonus Pair: {shiny_sname} <> {cap_sname}!"
            log.info(f"[{player_id}] ★ BONUS PAIR: {shiny_key[:8]} ↔ {key[:8]} in {bonus_area_id}")
            log.debug(f"[SHINY] player={player_id}  key={key[:8]}  action=formed  shiny_key={shiny_key[:8]}  area={bonus_area_id}  shiny_species={shiny_sname}  cap_species={cap_sname}")
            self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 25})   # SE_SUCCESS
            self.queued_commands[partner].append({"cmd": "play_sound", "sound": 25})
            self.queued_commands[player_id].append({
                "cmd": "hud_show", "text": link_text,
                "r": 255, "g": 215, "b": 0, "frames": 480,
            })
            self.queued_commands[partner].append({
                "cmd": "hud_show", "text": link_text,
                "r": 255, "g": 215, "b": 0, "frames": 480,
            })
            self._save()
            return

        status = self.area_states.get(area_id, AreaStatus.UNSEEN)

        if status == AreaStatus.DEAD_ZONE:
            # Area is dead — retire this mon immediately without altering the display entry,
            # so the original "no catch" record is preserved in the Linked Pairs table.
            log.warning(
                f"[{player_id}] capture in dead-zone area={area_id} key={key} — retiring immediately"
            )
            nickname = msg.get("nickname", "")
            label = self._label_from_msg(msg, key)
            self.party_keys[player_id].discard(key)
            self.queued_commands[player_id].append({"cmd": "force_faint", "key": key, "nickname": nickname})
            self._queue_memorialize(player_id, key)
            self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 26})  # SE_FAILURE
            self.queued_commands[player_id].append({
                "cmd": "hud_show",
                "text": f"Dead zone \u2014 {label} retired!",
                "r": 255, "g": 80, "b": 80, "frames": 360,
            })
            self._save()
            return

        if status == AreaStatus.LINKED:
            # Extra capture in an already-linked area — illegal, retire immediately.
            log.warning(
                f"[{player_id}] extra capture in already-linked area={area_id} key={key} — retiring immediately"
            )
            nickname = msg.get("nickname", "")
            label = self._label_from_msg(msg, key)
            self.party_keys[player_id].discard(key)
            self.queued_commands[player_id].append({"cmd": "force_faint", "key": key, "nickname": nickname})
            self._queue_memorialize(player_id, key)
            self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 26})  # SE_FAILURE
            self.queued_commands[player_id].append({
                "cmd": "hud_show",
                "text": f"Already linked here \u2014 {label} retired!",
                "r": 255, "g": 80, "b": 80, "frames": 360,
            })
            self._save()
            return

        # Guard: don't overwrite an existing pending capture for this player.
        # A second capture in the same area is illegal — retire it immediately.
        existing = self.pending_captures.get(area_id, {}).get(player_id)
        if existing:
            if existing.key == key:
                return  # duplicate event for the same mon, ignore
            log.warning(
                f"[{player_id}] second capture in area={area_id} "
                f"(already have {existing.key}), retiring {key}"
            )
            nickname = msg.get("nickname", "")
            label = self._label_from_msg(msg, key)
            existing_label = existing.nickname or (self.adapter.species_name(existing.species) if existing.species else None) or existing.key[:8]
            self.party_keys[player_id].discard(key)
            self.queued_commands[player_id].append({"cmd": "force_faint", "key": key, "nickname": nickname})
            self._queue_memorialize(player_id, key)
            self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 26})  # SE_FAILURE
            self.queued_commands[player_id].append({
                "cmd": "hud_show",
                "text": f"2nd catch! {label} retired (already have {existing_label})",
                "r": 255, "g": 80, "b": 80, "frames": 360,
            })
            self._save()
            return

        # Species clause: reject capture immediately if the player already has this
        # species family in an alive link OR a pending capture in another area.
        # Don't wait for the partner to catch — reject now, unresolve the area,
        # and let the player try again.
        cap_species = msg.get("species_id", 0)
        if self.species_lock and cap_species and not self.adapter.is_fixed_species_gift(area_id):
            cap_base = self.adapter.evo_family(cap_species)
            dup_name: Optional[str] = None

            # Check alive links
            for entry in self.links:
                if entry.status != LinkStatus.ALIVE:
                    continue
                player_mon = entry.a if player_id == "a" else entry.b
                if player_mon and player_mon.species and self.adapter.evo_family(player_mon.species) == cap_base:
                    dup_name = self.adapter.species_name(player_mon.species)
                    break
                partner_mon = entry.b if player_id == "a" else entry.a
                if partner_mon and partner_mon.species and self.adapter.evo_family(partner_mon.species) == cap_base:
                    dup_name = self.adapter.species_name(partner_mon.species)
                    break

            # Check pending captures in OTHER areas
            if not dup_name:
                for pend_area, pend_map in self.pending_captures.items():
                    if pend_area == area_id:
                        continue
                    pend_mon = pend_map.get(player_id)
                    if pend_mon and pend_mon.species and self.adapter.evo_family(pend_mon.species) == cap_base:
                        dup_name = self.adapter.species_name(pend_mon.species)
                        break
                    pend_mon = pend_map.get(_partner(player_id))
                    if pend_mon and pend_mon.species and self.adapter.evo_family(pend_mon.species) == cap_base:
                        dup_name = self.adapter.species_name(pend_mon.species)
                        break

            if dup_name:
                cap_name = self.adapter.species_name(cap_species)
                log.info(
                    f"[{player_id}] species clause: captured {cap_name} "
                    f"same family as existing {dup_name} — rejecting in {area_id}"
                )
                nickname = msg.get("nickname", "")
                self.queued_commands[player_id].append({"cmd": "force_faint", "key": key, "nickname": nickname})
                self._queue_memorialize(player_id, key)
                self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 26})   # SE_FAILURE
                self.queued_commands[player_id].append({
                    "cmd": "gui_prompt",
                    "text": f"Species clause: already have {dup_name} -- catch again!",
                    "r": 255, "g": 200, "b": 60,
                    "frames": 360,
                })
                self.queued_commands[player_id].append({
                    "cmd": "unresolve_area",
                    "area_id": area_id,
                })
                self.retry_areas[player_id].add(area_id)
                self._save()
                return

        if area_id not in self.pending_captures:
            self.pending_captures[area_id] = {}

        mon = MonInfo(key=key, level=msg.get("level", 0),
                      nickname=msg.get("nickname", ""),
                      species=msg.get("species_id", 0))
        self.pending_captures[area_id][player_id] = mon
        log.debug(f"[PENDING] {area_id}  player={player_id}  action=add  key={key[:8]}"
                  f"  species={mon.species}  lv={mon.level}")
        self.retry_areas[player_id].discard(area_id)  # valid capture clears retry
        in_box = msg.get("in_box", False)
        # Quarantine: unlinked mons must go to the box until linked.
        # Exception: never quarantine if it would empty the party (e.g. starter).
        # party_size reflects count BEFORE this capture; if >= 1, the player has
        # at least one other mon and it's safe to deposit.  Default to 0 (safe)
        # when party_size hasn't been reported yet — prevents quarantining the
        # starter before the first hello sets the actual count.
        party_count = self.party_size.get(player_id, 0)
        if not in_box and party_count >= 1 and not self._is_gift_capture(area_id, is_egg):
            self.queued_commands[player_id].append({"cmd": "box_mon", "key": key})
            log.info(f"[{player_id}] quarantine: {key[:8]} → box (pending link)")
        elif not in_box and self._is_gift_capture(area_id, is_egg):
            log.info(f"[{player_id}] skip quarantine: {key[:8]} (gift area {area_id}{', egg' if is_egg else ''})")
        elif not in_box:
            log.info(f"[{player_id}] skip quarantine: {key[:8]} (only mon in party)")
        # Cache stats from capture event so party_mon can restore them later.
        stats = msg.get("stats")
        if not stats:
            # Capture events send hp/maxHP/level as top-level fields, not nested.
            lv = msg.get("level", 0)
            mhp = msg.get("maxHP", 0)
            if lv and mhp:
                stats = {"level": lv, "maxHP": mhp}
        if stats:
            self.mon_stats[key] = stats

        partner     = _partner(player_id)
        partner_cap = self.pending_captures[area_id].get(partner)

        if partner_cap:
            # Both players captured in this area — check lock rules before linking.
            # Gift areas always produce the same species, so clauses don't apply.
            a_mon = self.pending_captures[area_id].get("a")
            b_mon = self.pending_captures[area_id].get("b")

            # Fixed-species gift areas bypass clause checks — both players always receive
            # the same predetermined species with no meaningful choice difference.
            # Player-choice gifts (starters at oaks_lab, fossils at cinnabar_lab) still enforce.
            is_gift = self.adapter.is_fixed_species_gift(area_id)
            result = None if is_gift else self._check_link_violation(a_mon, b_mon)
            if result:
                violation, violator = result
                # If violator is "" (cross-player), reject the player who just captured.
                # If violator is a specific player, reject that player's capture.
                reject_pid = violator if violator else player_id
                reject_key = (a_mon.key if reject_pid == "a" else b_mon.key)
                reject_nick = (a_mon.nickname if reject_pid == "a" else b_mon.nickname) or ""
                log.warning(f"[{reject_pid}] {violation} in area={area_id} — rejecting capture")
                self.party_keys[reject_pid].discard(reject_key)
                self.queued_commands[reject_pid].append({"cmd": "force_faint", "key": reject_key, "nickname": reject_nick})
                self._queue_memorialize(reject_pid, reject_key)
                self.queued_commands[reject_pid].append({"cmd": "play_sound", "sound": 26})   # SE_FAILURE
                self.queued_commands[_partner(reject_pid)].append({"cmd": "play_sound", "sound": 22})  # SE_BOO
                del self.pending_captures[area_id][reject_pid]
                log.debug(f"[PENDING] {area_id}  player={reject_pid}  action=reject  key={reject_key[:8]}  reason={violation!r}")
                # Area stays pending — waiting for the violating player to retry
                self._set_area_state(area_id,
                    AreaStatus.PENDING_A if reject_pid == "a" else AreaStatus.PENDING_B,
                    player=reject_pid, reason="clause_violation_retry")
                self.queued_commands[reject_pid].append({
                    "cmd": "gui_prompt",
                    "text": violation + " -- catch again!",
                    "r": 255, "g": 200, "b": 60,
                    "frames": 360,
                })
                # Tell Lua to un-resolve this area so the rejected player can retry
                # and no_catch won't fire when they leave.
                self.queued_commands[reject_pid].append({
                    "cmd": "unresolve_area",
                    "area_id": area_id,
                })
                self.retry_areas[reject_pid].add(area_id)
                self._save()
                return

            entry = LinkEntry(area_id=area_id, a=a_mon, b=b_mon, status=LinkStatus.ALIVE)
            self.links.append(entry)
            self._index_entry(entry)
            self._set_area_state(area_id, AreaStatus.LINKED, player=player_id, reason="both_captured")
            del self.pending_captures[area_id]
            log.debug(f"[PENDING] {area_id}  removed  (link formed)")
            log.info(f"Linked {a_mon.key} ↔ {b_mon.key} in {area_id}")
            # Notify both players with success sound + link info HUD
            a_label = a_mon.nickname or self.adapter.species_name(a_mon.species) or a_mon.key[:8]
            b_label = b_mon.nickname or self.adapter.species_name(b_mon.species) or b_mon.key[:8]
            link_text = f"Linked: {a_label} <> {b_label}"
            self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 25})   # SE_SUCCESS
            self.queued_commands[partner].append({"cmd": "play_sound", "sound": 25})
            self.queued_commands[player_id].append({
                "cmd": "hud_show", "text": link_text,
                "r": 100, "g": 255, "b": 160, "frames": 300,
            })
            self.queued_commands[partner].append({
                "cmd": "hud_show", "text": link_text,
                "r": 100, "g": 255, "b": 160, "frames": 300,
            })
            # Un-quarantine: both mons were boxed while pending — retrieve to party
            # ONLY if both players have room. Both must stay in sync.
            a_has_room = self.party_size.get("a", 6) < 6
            b_has_room = self.party_size.get("b", 6) < 6
            if a_has_room and b_has_room:
                for pid, mon_obj in [("a", a_mon), ("b", b_mon)]:
                    cmd: dict = {"cmd": "party_mon", "key": mon_obj.key}
                    if mon_obj.nickname:
                        cmd["nickname"] = mon_obj.nickname
                    cached = self.mon_stats.get(mon_obj.key)
                    if cached:
                        cmd["stats"] = cached
                    # Cancel any pending box_mon for this key (quarantine command may still be queued)
                    self.queued_commands[pid] = [
                        c for c in self.queued_commands[pid]
                        if not (c.get("key") == mon_obj.key and c.get("cmd") == "box_mon")
                    ]
                    self.queued_commands[pid].append(cmd)
                    log.info(f"Post-link: {pid}:{mon_obj.key[:8]} → party_mon (un-quarantine)")
            else:
                # At least one party is full — keep both in box, cancel stale quarantine commands.
                for pid in ("a", "b"):
                    mon_obj = a_mon if pid == "a" else b_mon
                    self.queued_commands[pid] = [
                        c for c in self.queued_commands[pid]
                        if not (c.get("key") == mon_obj.key and c.get("cmd") == "box_mon")
                    ]
                full_pid = "a" if not a_has_room else "b"
                log.info(f"Post-link: both stay in box — {full_pid} party full ({self.party_size.get(full_pid, 0)}/6)")
        else:
            # PENDING_X = "waiting for X to act"
            self._set_area_state(area_id,
                AreaStatus.PENDING_B if player_id == "a" else AreaStatus.PENDING_A,
                player=player_id, reason="first_capture")
            # Notify partner that a new link opportunity is available.
            disp = area_id.replace("_", " ").title()
            nick = mon.nickname or self.adapter.species_name(mon.species)
            label = nick or disp
            self.queued_commands[partner].append({
                "cmd": "hud_show",
                "text": f">> Partner caught {label} at {disp}",
                "r": 100, "g": 180, "b": 255,
                "frames": 300,
            })

        self._save()

    def _handle_faint(self, player_id: str, msg: dict):
        key = msg.get("key", "")
        if not key:
            return
        was_in_party = key in self.party_keys[player_id]
        self.party_keys[player_id].discard(key)
        if was_in_party:
            log.debug(f"[PARTY] player={player_id}  party_keys remove {key[:8]}  (faint)")
        # Soul Link deaths only count once the nuzlocke run is active (pokéballs obtained).
        # Faints before that point (e.g. starter knocked out before first Pokéball) are ignored.
        if not self.pokeballs_obtained[player_id]:
            log.debug(f"[FAINT GATE] player={player_id}  key={key[:8]}  suppressed=True  reason=nuzlocke_not_active")
            return
        entry = self._key_index.get(key)
        if not entry or entry.status != LinkStatus.ALIVE:
            log.debug(f"[{player_id}] faint {key[:8]}: no alive linked entry — ignored "
                      f"(status={entry.status.value if entry else 'not_found'})")
            return
        # Build killer info from server-enriched fields (injected by server.py before routing here).
        killer_species = msg.get("_killer_species", 0)
        killer: Optional[dict] = None
        if killer_species:
            killer = {
                "species":      killer_species,
                "level":        msg.get("_killer_level", 0),
                "is_trainer":   bool(msg.get("_is_trainer", False)),
                "trainer_name": msg.get("_trainer_name", ""),
                "trainer_class": msg.get("_trainer_class", ""),
            }
        self._propagate_faint(player_id, entry, killer=killer,
                              level=msg.get("_level", 0))

    def _dupes_reroll(self, player_id: str, area_id: str, text: str):
        """Send GUI prompt + unresolve_area so the player gets another encounter."""
        self.queued_commands[player_id].append({
            "cmd": "gui_prompt",
            "text": text,
            "r": 100, "g": 200, "b": 255,
            "frames": 300,
        })
        self.queued_commands[player_id].append({
            "cmd": "unresolve_area",
            "area_id": area_id,
        })

    def check_dupe_on_encounter(self, player_id: str, area_id: str, enc_species: int,
                                partner_battle_species: int = 0) -> bool:
        """Check for a dupes-clause reroll at wild battle start and notify the player immediately.

        Called as soon as the enemy species is known (first tick with in_battle=True) so the
        player sees the gui_prompt during the battle rather than after fleeing.

        Returns True if a dupe was detected and the gui_prompt was queued.
        """
        if not self.species_lock or not enc_species or not area_id:
            return False
        if not self.pokeballs_obtained.get(player_id):
            return False
        current = self.area_states.get(area_id, AreaStatus.UNSEEN)
        if current in (AreaStatus.LINKED, AreaStatus.DEAD_ZONE):
            return False
        # Skip if player already has a capture pending for this area (they caught already).
        if self.pending_captures.get(area_id, {}).get(player_id):
            return False

        partner = _partner(player_id)
        enc_base = self.adapter.evo_family(enc_species)
        enc_name = self.adapter.species_name(enc_species)

        # Check 1: same family as something this player already has in an alive link.
        for entry in self.links:
            if entry.status != LinkStatus.ALIVE:
                continue
            player_mon = entry.a if player_id == "a" else entry.b
            if player_mon and player_mon.species and self.adapter.evo_family(player_mon.species) == enc_base:
                existing_name = self.adapter.species_name(player_mon.species)
                log.info(
                    f"[{player_id}] dupes clause (battle start): {enc_name} "
                    f"same family as existing {existing_name} in {entry.area_id}"
                )
                self.dupe_notified_areas[player_id].add(area_id)
                self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                return True
            partner_mon = entry.b if player_id == "a" else entry.a
            if partner_mon and partner_mon.species and self.adapter.evo_family(partner_mon.species) == enc_base:
                existing_name = self.adapter.species_name(partner_mon.species)
                log.info(
                    f"[{player_id}] dupes clause (battle start): {enc_name} "
                    f"same family as partner's {existing_name} in {entry.area_id}"
                )
                self.dupe_notified_areas[player_id].add(area_id)
                self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                return True

        # Check 2: partner already captured on this area with same evo family.
        partner_cap = self.pending_captures.get(area_id, {}).get(partner)
        if partner_cap and partner_cap.species:
            partner_base = self.adapter.evo_family(partner_cap.species)
            if enc_base == partner_base:
                partner_name = self.adapter.species_name(partner_cap.species)
                log.info(
                    f"[{player_id}] dupes clause (battle start): {enc_name} "
                    f"same family as partner's {partner_name} on {area_id}"
                )
                self.dupe_notified_areas[player_id].add(area_id)
                self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                return True
        for pend_area, pend_map in self.pending_captures.items():
            if pend_area == area_id:
                continue
            pend_mon = pend_map.get(partner)
            if pend_mon and pend_mon.species and self.adapter.evo_family(pend_mon.species) == enc_base:
                partner_name = self.adapter.species_name(pend_mon.species)
                log.info(
                    f"[{player_id}] dupes clause (battle start): {enc_name} "
                    f"same family as partner's pending {partner_name} on {pend_area}"
                )
                self.dupe_notified_areas[player_id].add(area_id)
                self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                return True

        # Check 3: partner is currently in a wild battle on the same area with the same evo family.
        # Covers the concurrent-battle case where neither player has captured yet.
        if partner_battle_species:
            partner_base = self.adapter.evo_family(partner_battle_species)
            if enc_base == partner_base:
                partner_name = self.adapter.species_name(partner_battle_species)
                log.info(
                    f"[{player_id}] dupes clause (battle start): {enc_name} "
                    f"same family as partner's concurrent battle {partner_name} on {area_id}"
                )
                self.dupe_notified_areas[player_id].add(area_id)
                self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                return True

        return False

    def _handle_no_catch(self, player_id: str, msg: dict):
        area_id = msg.get("area_id", "")
        if not area_id:
            return

        # Gift areas can never become dead zones — wild encounters there are coincidental.
        if self.adapter.is_gift_area(area_id):
            log.debug(f"[{player_id}] no_catch ignored — {area_id} is a gift area")
            return

        current = self.area_states.get(area_id, AreaStatus.UNSEEN)
        if current in (AreaStatus.LINKED, AreaStatus.DEAD_ZONE):
            return  # Already resolved

        # If this player already captured here, the no_catch is a stale/spurious event.
        if self.pending_captures.get(area_id, {}).get(player_id):
            log.debug(f"[{player_id}] no_catch ignored — player already captured in {area_id}")
            return

        # Clause retry: a previous capture was rejected (species/gender/type clause).
        # Suppress ALL no_catch until the player successfully captures a valid mon.
        # Also suppress if the PARTNER has a retry pending — their rejected capture
        # means the area is still open; B dead-zoning it would destroy A's chance.
        partner = _partner(player_id)
        if area_id in self.retry_areas[player_id] or area_id in self.retry_areas[partner]:
            log.info(f"[{player_id}] no_catch suppressed — retry pending for {area_id}")
            self.queued_commands[player_id].append({
                "cmd": "unresolve_area",
                "area_id": area_id,
            })
            return

        # Species clause reroll: if species lock is active and the encountered
        # species belongs to a family the player already has in an alive link,
        # the encounter doesn't count — area stays open for a different catch.
        enc_species = msg.get("species_id", 0)
        enc_level   = msg.get("level", 0)

        # Dupes already notified at battle start — keep area open without repeating the prompt.
        if area_id in self.dupe_notified_areas[player_id]:
            self.dupe_notified_areas[player_id].discard(area_id)
            self.queued_commands[player_id].append({"cmd": "unresolve_area", "area_id": area_id})
            log.info(f"[{player_id}] no_catch — dupes reroll for {area_id} (already notified at battle start)")
            return

        if self.species_lock and enc_species:
            enc_base = self.adapter.evo_family(enc_species)
            enc_name = self.adapter.species_name(enc_species)

            # Check 1: same family as something this player already has alive
            for entry in self.links:
                if entry.status != LinkStatus.ALIVE:
                    continue
                player_mon = entry.a if player_id == "a" else entry.b
                if player_mon and player_mon.species and self.adapter.evo_family(player_mon.species) == enc_base:
                    existing_name = self.adapter.species_name(player_mon.species)
                    log.info(
                        f"[{player_id}] species clause reroll: {enc_name} "
                        f"same family as existing {existing_name} in {entry.area_id} — no_catch suppressed"
                    )
                    self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                    return
                partner_mon = entry.b if player_id == "a" else entry.a
                if partner_mon and partner_mon.species and self.adapter.evo_family(partner_mon.species) == enc_base:
                    existing_name = self.adapter.species_name(partner_mon.species)
                    log.info(
                        f"[{player_id}] species clause reroll: {enc_name} "
                        f"same family as partner's {existing_name} in {entry.area_id} — no_catch suppressed"
                    )
                    self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                    return

            # Check 2: partner already captured on this area and species would
            # violate species lock (same family) — catching it would be rejected
            # anyway, so give the player a free reroll.
            partner_cap = self.pending_captures.get(area_id, {}).get(partner)
            if partner_cap and partner_cap.species:
                partner_base = self.adapter.evo_family(partner_cap.species)
                if enc_base == partner_base:
                    partner_name = self.adapter.species_name(partner_cap.species)
                    log.info(
                        f"[{player_id}] dupes clause reroll: {enc_name} "
                        f"same family as partner's {partner_name} on {area_id} — no_catch suppressed"
                    )
                    self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                    return
            for pend_area, pend_map in self.pending_captures.items():
                if pend_area == area_id:
                    continue
                pend_mon = pend_map.get(partner)
                if pend_mon and pend_mon.species and self.adapter.evo_family(pend_mon.species) == enc_base:
                    partner_name = self.adapter.species_name(pend_mon.species)
                    log.info(
                        f"[{player_id}] dupes clause reroll: {enc_name} "
                        f"same family as partner's pending {partner_name} on {pend_area} — no_catch suppressed"
                    )
                    self._dupes_reroll(player_id, area_id, f"Dupes clause: {enc_name} -- reroll!")
                    return

        self._set_area_state(area_id, AreaStatus.DEAD_ZONE,
                            player=player_id, reason="no_catch")
        partner_cap = self.pending_captures.get(area_id, {}).get(partner)
        log.info(f"[DEAD ZONE] {area_id}  reason=no_catch  triggered_by={player_id}  partner_had_capture={partner_cap is not None}")
        # Notify both players with a failure sound + HUD banner naming the dead area.
        area_disp = self.adapter.area_display_name(area_id) or area_id
        dz_text = f"!! Dead zone -- {area_disp}!"
        self.queued_commands[player_id].append({"cmd": "play_sound", "sound": 26})   # SE_FAILURE
        self.queued_commands[player_id].append({
            "cmd": "hud_show", "text": dz_text,
            "r": 255, "g": 80, "b": 80, "frames": 480,
        })
        partner     = _partner(player_id)
        self.queued_commands[partner].append({"cmd": "play_sound", "sound": 26})
        self.queued_commands[partner].append({
            "cmd": "hud_show", "text": dz_text,
            "r": 255, "g": 80, "b": 80, "frames": 480,
        })
        partner_cap = self.pending_captures.get(area_id, {}).get(partner)

        # Always create a LinkEntry so the dead zone and both sides' encounters are logged.
        # Current player had no catch (None); partner may or may not have caught something.
        # Build a sentinel MonInfo (key="") for the no-catch side if encounter data was sent.
        enc_level   = msg.get("level", 0)
        no_catch_mon = MonInfo(key="", species=enc_species, level=enc_level) if enc_species else None
        a_mon = (None if player_id == "a" else partner_cap)
        b_mon = (None if player_id == "b" else partner_cap)
        a_enc = (no_catch_mon if player_id == "a" else None)
        b_enc = (no_catch_mon if player_id == "b" else None)
        entry = LinkEntry(area_id=area_id, a=a_mon, b=b_mon, status=LinkStatus.DEAD,
                          encounter_a=a_enc, encounter_b=b_enc,
                          killed_at=datetime.now(timezone.utc).isoformat(),
                          cause="dead_zone",
                          initiating_player=player_id)
        self.links.append(entry)
        self._index_entry(entry)

        if partner_cap:
            self.queued_commands[partner].append({"cmd": "force_faint", "key": partner_cap.key, "nickname": partner_cap.nickname or ""})
            self.party_keys[partner].discard(partner_cap.key)
            self._queue_memorialize(partner, partner_cap.key)
            log.info(f"[{partner}] dead-zone retire: {partner_cap.key} in {area_id}")
        else:
            log.info(f"dead zone {area_id}: {player_id} no catch, partner had no pending capture")

        if area_id in self.pending_captures:
            del self.pending_captures[area_id]
            log.debug(f"[PENDING] {area_id}  removed  (dead zone)")

        self._check_game_over()
        self._save()

    def _handle_whiteout(self, player_id: str, msg: dict):
        """
        Force-faint all living linked partners of the whited-out player.
        Only processes mons known to be in the whited-out player's party
        (tracked via party_keys) to avoid killing boxed mons' partners.

        Then either: (a) queue an auto-rebuild from alive boxed linked pairs,
        or (b) fire game_over if no alive linked pairs remain anywhere. The
        rebuild's party_mon commands are queued BEFORE the force-faint loop's
        memorialize commands so the Lua deferred queue drains in the right
        order — party_mon lands first (q_count goes 1→2), then memorialize
        for the dying mons can proceed (PMC-heal-softlock guard releases as
        soon as a second slot is occupied).
        """
        partner = _partner(player_id)
        now = datetime.now(timezone.utc).isoformat()

        # Plan rebuild against the pre-whiteout state. Dying-pair halves are
        # still in party_keys at this point, so the co-location check inside
        # _alive_pc_mons filters them out — only fully-boxed alive pairs
        # survive into the picks.
        player_picks, partner_picks = self._plan_rebuild(player_id)
        if player_picks:
            self.rebuild_pending[player_id] = {
                "started_at":         now,
                "queued_keys":        [m.key for m in player_picks],
                "queued_partner_keys": [m.key for m in partner_picks],
                "restored_keys":      set(),
            }
            self._queue_rebuild_commands(player_id, player_picks, partner_picks)
            log.info(f"[{player_id}] whiteout rebuild armed — "
                     f"restoring {len(player_picks)} mon(s); partner mirrors "
                     f"{len(partner_picks)}")

        retired = []
        for entry in self.links:
            if entry.status != LinkStatus.ALIVE:
                continue
            player_mon  = entry.a if player_id == "a" else entry.b
            partner_mon = entry.b if player_id == "a" else entry.a
            if not player_mon or not partner_mon:
                continue
            # Only act on mons we believe are in the whited-out player's party
            if player_mon.key not in self.party_keys[player_id]:
                continue
            self.queued_commands[partner].append({"cmd": "force_faint", "key": partner_mon.key, "nickname": partner_mon.nickname or ""})
            self.party_keys[partner].discard(partner_mon.key)
            entry.status = LinkStatus.DEAD
            entry.killed_at = now
            entry.cause = "whiteout"
            entry.initiating_player = player_id
            self._queue_memorialize(player_id, player_mon.key)
            self._queue_memorialize(partner, partner_mon.key)
            retired.append(partner_mon.key)

        self.party_keys[player_id].clear()

        if retired:
            log.info(f"[{player_id}] whiteout — force-fainting {len(retired)} partner mon(s)")

        # No alive boxed pairs left after a real whiteout → run is over. With
        # no party and no rebuild candidates, the whited-out player cannot
        # battle or progress. Firing game_over now also drops the blocked
        # last-party-mon memorialize cleanly in the Lua client (it checks
        # game_over_flag and removes the command instead of waiting).
        if retired and not player_picks:
            self.queued_commands[player_id].append({
                "cmd":  "hud_show",
                "text": "X No alive mons left in PC",
                "r": 255, "g": 80, "b": 80, "frames": 360,
            })
            if not self.run_over:
                self.run_over = True
                log.info(f"[{player_id}] whiteout — no rebuild possible, run over")
                for pid in ("a", "b"):
                    self.queued_commands[pid].append({"cmd": "game_over"})

        if retired or player_picks:
            # Belt-and-suspenders: also run the standard check (covers the
            # no-whiteout-events but already-dead-pairs case, and is a no-op
            # if run_over was just set above).
            self._check_game_over()
            self._save()

    def _handle_party_to_box(self, player_id: str, msg: dict):
        """
        Player deposited a linked mon at the PC.
        Cache its stats and send box_mon to partner so their linked mon is auto-deposited.
        """
        key = msg.get("key", "")
        if not key:
            return
        # Cache stats so we can echo them back in the partner's party_mon command later.
        stats = msg.get("stats")
        if stats:
            self.mon_stats[key] = stats
        # Decrement party_size immediately (same reason as stats_cache handler): avoids a
        # false "partner's party full" block if the partner tries to withdraw their linked mon
        # before the next tick arrives and corrects the count.
        if key in self.party_keys[player_id]:
            old_size = self.party_size.get(player_id, 0)
            self.party_size[player_id] = max(0, old_size - 1)
            log.debug(f"[PARTY] player={player_id}  party_size {old_size} → {self.party_size[player_id]}  (party_to_box)")
        self.party_keys[player_id].discard(key)
        log.debug(f"[PARTY] player={player_id}  party_keys remove {key[:8]}  (party_to_box)")
        entry = self._key_index.get(key)
        if not entry or entry.status != LinkStatus.ALIVE:
            return
        partner     = _partner(player_id)
        partner_mon = entry.b if player_id == "a" else entry.a

        # Queue box_mon when: (a) partner's mon is known to be in their party, OR
        # (b) partner hasn't sent hello yet this session — we can't tell, so queue
        # optimistically. exec_box_mon is idempotent: it no-ops if key not found.
        partner_in_party = (
            partner not in self._has_helld
            or partner_mon.key in self.party_keys[partner]
        )
        if partner_mon and partner_in_party:
            # Cancel any pending party_mon for the same key before queuing box_mon.
            self.queued_commands[partner] = [
                c for c in self.queued_commands[partner]
                if not (c.get("key") == partner_mon.key and c.get("cmd") == "party_mon")
            ]
            self.queued_commands[partner].append({"cmd": "box_mon", "key": partner_mon.key})
            self.party_keys[partner].discard(partner_mon.key)
            log.debug(f"[PARTY] player={partner}  party_keys remove {partner_mon.key[:8]}  (partner party_to_box sync)")
            log.info(f"[{player_id}] party_to_box {key[:8]} → box_mon {partner}:{partner_mon.key[:8]}")
        else:
            log.info(f"[{player_id}] party_to_box {key[:8]} → no box_mon queued (no linked partner or partner already boxed)")
        self._save()

    def _handle_box_to_party(self, player_id: str, msg: dict):
        """
        Player retrieved a linked mon from the PC.
        Both linked mons must always be in the same place. If the partner can't
        fit their mon (party full), block the withdrawal and re-box this player's mon.
        """
        key = msg.get("key", "")
        if not key:
            return

        # During an active auto-rebuild, server-driven party_mon writes confirm
        # via sync_retrieve_done — they don't normally produce a box_to_party
        # event. If we see one whose key the rebuild is restoring (race / Lua
        # detecting the write as a withdrawal), treat it as the rebuild path
        # confirming: add to party_keys and let _maybe_finish_rebuild close
        # things out. Suppresses the noisy reactive HUDs during rebuild.
        rb = self.rebuild_pending.get(player_id)
        if rb and key in rb.get("queued_keys", []):
            self.party_keys[player_id].add(key)
            rb["restored_keys"].add(key)
            self._maybe_finish_rebuild(player_id)
            return

        # Quarantine enforcement: if this mon is a pending (unlinked) capture,
        # re-queue box_mon to send it back to the box. Don't add to party_keys.
        for area_id, players in self.pending_captures.items():
            cap = players.get(player_id)
            if cap and cap.key == key:
                self.queued_commands[player_id].append({"cmd": "box_mon", "key": key})
                log.warning(f"[{player_id}] box_to_party blocked: {key[:8]} is quarantined (pending in {area_id})")
                self.queued_commands[player_id].append({
                    "cmd": "hud_show",
                    "text": "! " + (cap.nickname or self.adapter.species_name(cap.species) or key[:8]) + " is unlinked -- must stay in box",
                    "r": 255, "g": 200, "b": 60
                })
                return

        entry = self._key_index.get(key)
        if not entry:
            self.party_keys[player_id].add(key)
            return

        # Dead/memorial mons must stay in the memorial box — re-box immediately.
        if entry.status in (LinkStatus.DEAD, LinkStatus.MEMORIAL):
            my_mon = entry.a if entry.a.key == key else entry.b
            nick = my_mon.nickname or self.adapter.species_name(my_mon.species) or msg.get("nickname") or key[:8]
            self.queued_commands[player_id].append({"cmd": "memorialize", "key": key})
            self.queued_commands[player_id].append({
                "cmd": "hud_show",
                "text": "X " + nick + " is dead -- back to memorial box",
                "r": 255, "g": 80, "b": 80
            })
            log.warning(f"[{player_id}] box_to_party blocked: {key[:8]} is dead/memorial — re-memorializing")
            return

        if entry.status != LinkStatus.ALIVE:
            self.party_keys[player_id].add(key)
            return
        partner     = _partner(player_id)
        partner_mon = entry.b if player_id == "a" else entry.a

        # Check if partner's party has room using the server's logical view.
        # party_keys is already updated for queued box_mon commands (keys are discarded
        # in _handle_party_to_box before the command is sent), but party_size lags
        # behind until partner's Lua ACKs the command.  Subtract pending box_mon
        # commands from party_size so we don't get false "party full" blocks when a
        # swap is in-flight.
        if partner_mon and partner_mon.key not in self.party_keys[partner]:
            pending_box_mons = sum(
                1 for c in self.queued_commands[partner] if c.get("cmd") == "box_mon"
            )
            adjusted_party_size = max(0, self.party_size.get(partner, 0) - pending_box_mons)
            logical_size = max(self._linked_party_size(partner), adjusted_party_size)
            log.debug(f"[PARTY] box_to_party full-check: partner={partner}  "
                      f"party_size={self.party_size.get(partner,0)}  "
                      f"pending_box_mons={pending_box_mons}  logical={logical_size}")
            if logical_size >= 6:
                self.queued_commands[player_id].append({"cmd": "box_mon", "key": key})
                my_mon = entry.a if entry.a.key == key else entry.b
                nick = my_mon.nickname or self.adapter.species_name(my_mon.species) or msg.get("nickname") or key[:8]
                self.queued_commands[player_id].append({
                    "cmd": "hud_show",
                    "text": "! Partner's party full -- " + nick + " re-deposited",
                    "r": 255, "g": 200, "b": 60
                })
                log.info(f"[{player_id}] box_to_party blocked: {key[:8]} — partner {partner} party logically full ({logical_size}/6)")
                return

        self.party_keys[player_id].add(key)
        log.debug(f"[PARTY] player={player_id}  party_keys add {key[:8]}  (box_to_party)")
        if partner_mon and partner_mon.key not in self.party_keys[partner]:
            cmd: dict = {"cmd": "party_mon", "key": partner_mon.key}
            if partner_mon.nickname:
                cmd["nickname"] = partner_mon.nickname
            cached = self.mon_stats.get(partner_mon.key)
            if cached:
                cmd["stats"] = cached
            # Cancel any pending box_mon for the same key before queuing party_mon.
            self.queued_commands[partner] = [
                c for c in self.queued_commands[partner]
                if not (c.get("key") == partner_mon.key and c.get("cmd") == "box_mon")
            ]
            self.queued_commands[partner].append(cmd)
            # Don't add to party_keys yet — wait for sync_retrieve_done confirmation.
            log.info(f"[{player_id}] box_to_party {key[:8]} → party_mon {partner}:{partner_mon.key[:8]}"
                     + (" (stats cached)" if cached else " (no cached stats)"))
        self._save()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _linked_party_size(self, player_id: str) -> int:
        """Count party keys excluding bonus (shiny clause) mons."""
        bonus = self.bonus_keys.get(player_id, set())
        return sum(1 for k in self.party_keys[player_id] if k not in bonus)

    # ── auto-rebuild helpers (after whiteout) ────────────────────────────────

    def _alive_pc_mons(self, player_id: str) -> list[tuple[str, str]]:
        """Enumerate alive linked-pair halves boxed in this player's PC after a
        whiteout, paired with their partner's boxed half. Walks self.links in
        chronological capture order (oldest first). Bonus (shiny-clause) pairs
        are eligible too — they are linked pairs and follow the same
        co-location rule. Pending unlinked captures are NOT included; they
        remain quarantined per Soul Link rules.

        Returns a list of (player_key, partner_key) tuples.
        """
        out: list[tuple[str, str]] = []
        partner = _partner(player_id)
        my_party = self.party_keys.get(player_id, set())
        partner_party = self.party_keys.get(partner, set())
        for entry in self.links:
            if entry.status != LinkStatus.ALIVE:
                continue
            my_mon = entry.a if player_id == "a" else entry.b
            partner_mon = entry.b if player_id == "a" else entry.a
            if not my_mon or not partner_mon:
                continue
            if not my_mon.key or not partner_mon.key:
                continue
            # Both halves must be currently boxed (Soul Link co-location).
            if my_mon.key in my_party or partner_mon.key in partner_party:
                continue
            out.append((my_mon.key, partner_mon.key))
        return out

    def _plan_rebuild(self, player_id: str) -> tuple[list[MonInfo], list[MonInfo]]:
        """Greedy pick of alive boxed pairs for auto-rebuild after a whiteout.
        Returns (player_picks, partner_picks). A pair is included only if the
        partner has room (logical party + already-picked partner halves < 6);
        otherwise the pair is skipped entirely — both halves must be
        co-located. Stops at 6 player picks or when candidates are exhausted.
        """
        partner = _partner(player_id)
        partner_size_start = self._linked_party_size(partner)
        player_picks: list[MonInfo] = []
        partner_picks: list[MonInfo] = []
        for my_key, _partner_key in self._alive_pc_mons(player_id):
            if len(player_picks) >= 6:
                break
            if partner_size_start + len(partner_picks) >= 6:
                # Partner has no more room. Per Soul Link co-location, both
                # halves must move together — skip this and any further pairs.
                break
            entry = self._key_index.get(my_key)
            if not entry:
                continue
            my_mon = entry.a if player_id == "a" else entry.b
            partner_mon = entry.b if player_id == "a" else entry.a
            if not my_mon or not partner_mon:
                continue
            player_picks.append(my_mon)
            partner_picks.append(partner_mon)
        return player_picks, partner_picks

    def _queue_rebuild_commands(self, player_id: str,
                                 player_picks: list[MonInfo],
                                 partner_picks: list[MonInfo]) -> None:
        """Queue party_mon commands for both player and partner halves of the
        rebuild, plus a persistent REBUILDING banner for the player and a
        soft informational HUD for the partner.
        """
        partner = _partner(player_id)

        def _enqueue(pid: str, mon: MonInfo) -> None:
            # Cancel any stale box_mon for this key (same idempotent pattern
            # used in the post-link path at _handle_capture).
            self.queued_commands[pid] = [
                c for c in self.queued_commands[pid]
                if not (c.get("key") == mon.key and c.get("cmd") == "box_mon")
            ]
            cmd: dict = {"cmd": "party_mon", "key": mon.key}
            if mon.nickname:
                cmd["nickname"] = mon.nickname
            cached = self.mon_stats.get(mon.key)
            if cached:
                cmd["stats"] = cached
            self.queued_commands[pid].append(cmd)

        for mon in player_picks:
            _enqueue(player_id, mon)
        for mon in partner_picks:
            _enqueue(partner, mon)

        def _label(mon: MonInfo) -> str:
            if mon.nickname:
                return mon.nickname
            if mon.species:
                name = self.adapter.species_name(mon.species)
                if name:
                    return name
            return mon.key[:6]

        labels = [_label(m) for m in player_picks[:3]]
        suffix = "" if len(player_picks) <= 3 else f" +{len(player_picks) - 3}"
        banner_text = "REBUILDING: " + ", ".join(labels) + suffix
        self.queued_commands[player_id].append({
            "cmd":  "rebuild_start",
            "text": banner_text,
            "keys": [m.key for m in player_picks],
        })
        if partner_picks:
            self.queued_commands[partner].append({
                "cmd":    "hud_show",
                "text":   f">> Partner rebuilding -- {len(player_picks)} mon(s) restored",
                "r": 100, "g": 180, "b": 255,
                "frames": 360,
            })

    def _maybe_finish_rebuild(self, player_id: str) -> None:
        """Clear rebuild state and tell the client to dismiss the banner once
        every queued rebuild key has either been confirmed
        (sync_retrieve_done) or dropped (sync_retrieve_failed)."""
        rb = self.rebuild_pending.get(player_id)
        if not rb:
            return
        queued = set(rb.get("queued_keys", []))
        restored = rb.get("restored_keys", set())
        if queued - restored:
            return  # still waiting on some sync events
        self.queued_commands[player_id].append({"cmd": "rebuild_done"})
        log.info(f"[{player_id}] rebuild complete — {len(restored)} restored, "
                 f"{len(queued) - len(restored)} dropped")
        self.rebuild_pending[player_id] = None
        self._save()

    def _handle_key_change(self, player_id: str, msg: dict):
        """Handle a key change (nature change, NPC trade, or evolution).

        The Lua client detected that a mon's key changed.  For Gen 3 (RR Nature
        Changer), personality changes but otId/species/nickname stay the same.
        For NPC in-game trades, the outgoing mon's key is replaced by the
        received mon's key and the Soul Link pair is preserved.
        For Gen 1, evolution changes the internal species index in the key, and
        may also update species/nickname.

        Migrate the old key → new key in all server-side tracking structures.
        Optional fields ``new_species`` and ``new_nickname`` update the linked
        MonInfo when present (used by Gen 1 evolution key migration).
        """
        old_key = msg.get("old_key", "")
        new_key = msg.get("new_key", "")
        if not old_key or not new_key or old_key == new_key:
            return

        reason = msg.get("reason", "nature_change")
        log.info(f"[{player_id}] key_change ({reason}): {old_key[:8]} → {new_key[:8]}")

        _migrated = False

        # 1. Links + key index
        mon = None
        entry = self._key_index.pop(old_key, None)
        if entry:
            _migrated = True
            side = "a" if player_id == "a" else "b"
            mon = getattr(entry, side)
            if mon and mon.key == old_key:
                mon.key = new_key
                # Update species/nickname if provided (Gen 1 evolution changes species)
                new_species = msg.get("new_species")
                new_nickname = msg.get("new_nickname")
                if new_species is not None:
                    mon.species = new_species
                if new_nickname is not None:
                    mon.nickname = new_nickname
            self._key_index[new_key] = entry

        # 2. Pending captures
        for area_id, players in self.pending_captures.items():
            cap = players.get(player_id)
            if cap and cap.key == old_key:
                cap.key = new_key
                _migrated = True

        # 3. Party keys
        if old_key in self.party_keys[player_id]:
            self.party_keys[player_id].discard(old_key)
            self.party_keys[player_id].add(new_key)
            _migrated = True

        # 4. Mon stats cache
        if old_key in self.mon_stats:
            self.mon_stats[new_key] = self.mon_stats.pop(old_key)
            _migrated = True

        # 5. Bonus keys (shiny clause)
        if old_key in self.bonus_keys[player_id]:
            self.bonus_keys[player_id].discard(old_key)
            self.bonus_keys[player_id].add(new_key)
            _migrated = True

        # 6. Pending memorials
        if old_key in self.pending_memorials[player_id]:
            self.pending_memorials[player_id].discard(old_key)
            self.pending_memorials[player_id].add(new_key)
            _migrated = True

        # 7. Queued commands referencing the old key
        for cmd in self.queued_commands[player_id]:
            if cmd.get("key") == old_key:
                cmd["key"] = new_key

        # 8. Pending bonus queue (shiny keys in partner's pending_bonus)
        for pid in ("a", "b"):
            self.pending_bonus[pid] = deque(
                new_key if k == old_key else k for k in self.pending_bonus[pid]
            )

        if not _migrated:
            log.warning(
                f"[{player_id}] key_change: old_key {old_key[:8]} not found in any"
                " tracking structure — possible spurious event"
            )

        self._save()

    def _check_link_violation(self, a_mon: MonInfo, b_mon: MonInfo) -> Optional[tuple[str, str]]:
        """Return (violation_message, violating_player_id) or None if the link is valid."""
        if self.species_lock and a_mon.species and b_mon.species:
            # Cross-player check: A and B can't be the same species/family
            a_base = self.adapter.evo_family(a_mon.species)
            b_base = self.adapter.evo_family(b_mon.species)
            if a_base == b_base:
                a_name = self.adapter.species_name(a_mon.species)
                b_name = self.adapter.species_name(b_mon.species)
                if a_mon.species == b_mon.species:
                    # Both sides are bad — blame the later capturer (caller decides)
                    return (f"Species clause: both are {a_name}", "")
                else:
                    return (f"Species clause: {a_name} & {b_name} same family", "")

            # Same-save duplicate check: neither player can have a species/family
            # that already exists in one of their other alive links.
            for entry in self.links:
                if entry.status != LinkStatus.ALIVE:
                    continue
                if entry.a and entry.a.species and self.adapter.evo_family(entry.a.species) == a_base:
                    existing_name = self.adapter.species_name(entry.a.species)
                    a_name = self.adapter.species_name(a_mon.species)
                    return (f"Species clause: {a_name} — A already has {existing_name}", "a")
                if entry.b and entry.b.species and self.adapter.evo_family(entry.b.species) == b_base:
                    existing_name = self.adapter.species_name(entry.b.species)
                    b_name = self.adapter.species_name(b_mon.species)
                    return (f"Species clause: {b_name} — B already has {existing_name}", "b")
                if entry.a and entry.a.species and self.adapter.evo_family(entry.a.species) == b_base:
                    existing_name = self.adapter.species_name(entry.a.species)
                    b_name = self.adapter.species_name(b_mon.species)
                    return (f"Species clause: {b_name} — already have {existing_name}", "b")
                if entry.b and entry.b.species and self.adapter.evo_family(entry.b.species) == a_base:
                    existing_name = self.adapter.species_name(entry.b.species)
                    a_name = self.adapter.species_name(a_mon.species)
                    return (f"Species clause: {a_name} — already have {existing_name}", "a")

        if self.gender_lock and a_mon.key and b_mon.key and a_mon.species and b_mon.species:
            a_gender = self.adapter.gender_from_key(a_mon.key, a_mon.species)
            b_gender = self.adapter.gender_from_key(b_mon.key, b_mon.species)
            if a_gender in ("male", "female") and b_gender in ("male", "female"):
                if a_gender == b_gender:
                    symbol = "♂" if a_gender == "male" else "♀"
                    return (f"Gender clause: both are {symbol}", "")

        if self.type_lock and a_mon.species and b_mon.species:
            a_types = self.adapter.species_types(a_mon.species)
            b_types = self.adapter.species_types(b_mon.species)
            if a_types and b_types:
                # Collect unique types for each mon (monotypes have t1==t2)
                a_set = {a_types[0], a_types[1]} if a_types[0] != a_types[1] else {a_types[0]}
                b_set = {b_types[0], b_types[1]} if b_types[0] != b_types[1] else {b_types[0]}
                shared = a_set & b_set
                if shared:
                    shared_names = ", ".join(sorted(self.adapter.type_name(t) for t in shared))
                    return (f"Type clause: shared {shared_names}", "")

        # All clause checks passed — log the evaluation summary at DEBUG.
        a_name = self.adapter.species_name(a_mon.species) if a_mon.species else a_mon.key[:8]
        b_name = self.adapter.species_name(b_mon.species) if b_mon.species else b_mon.key[:8]
        checks = []
        if self.species_lock:
            checks.append("species=OK")
        if self.gender_lock:
            checks.append("gender=OK")
        if self.type_lock:
            checks.append("type=OK")
        if checks:
            log.debug(f"[CLAUSE] {a_name} ↔ {b_name}  " + "  ".join(checks))
        return None

    def _propagate_faint(self, player_id: str, entry: LinkEntry, killer: Optional[dict] = None,
                         level: int = 0):
        """Mark entry dead, queue force_faint for partner, queue memorialize for both."""
        partner     = _partner(player_id)
        player_mon  = entry.a if player_id == "a" else entry.b
        partner_mon = entry.b if player_id == "a" else entry.a
        if partner_mon:
            self.queued_commands[partner].append({"cmd": "force_faint", "key": partner_mon.key, "nickname": partner_mon.nickname or ""})
            self.party_keys[partner].discard(partner_mon.key)
            log.debug(f"[PARTY] player={partner}  party_keys remove {partner_mon.key[:8]}  (force_faint from {player_id})")
            log.info(f"[{player_id}] faint → force_faint {partner}:{partner_mon.key}")
        entry.status = LinkStatus.DEAD
        entry.killed_at = datetime.now(timezone.utc).isoformat()
        entry.cause = "battle"
        entry.killer = killer
        entry.initiating_player = player_id
        # Update MonInfo levels to death-time values so memorial shows current level.
        if player_mon:
            lv = level or self.mon_stats.get(player_mon.key, {}).get("level", 0)
            if lv:
                player_mon.level = lv
        if partner_mon:
            lv = self.mon_stats.get(partner_mon.key, {}).get("level", 0)
            if lv:
                partner_mon.level = lv
        if player_mon:
            self._queue_memorialize(player_id, player_mon.key)
        if partner_mon:
            self._queue_memorialize(partner, partner_mon.key)
        self._check_game_over()
        self._save()

    def _index_entry(self, entry: LinkEntry):
        if entry.a:
            self._key_index[entry.a.key] = entry
        if entry.b:
            self._key_index[entry.b.key] = entry

    def _queue_memorialize(self, player_id: str, key: str):
        """
        Queue a memorialize command for player_id's key.
        Cancels any stale box_mon/party_mon for the same key (they're now dead).
        """
        self.queued_commands[player_id] = [
            c for c in self.queued_commands[player_id]
            if not (c.get("cmd") in ("box_mon", "party_mon") and c.get("key") == key)
        ]
        self.queued_commands[player_id].append({"cmd": "memorialize", "key": key})
        self.pending_memorials[player_id].add(key)
        log.info(f"[{player_id}] memorialize queued for {key[:8]}")

    def _label_from_msg(self, msg: dict, key: str) -> str:
        """Return the best available display label for a mon from a capture event dict."""
        nick = msg.get("nickname", "")
        species = msg.get("species_id", 0)
        return nick or (self.adapter.species_name(species) if species else None) or key[:8]

    def _handle_memorialize_done(self, player_id: str, msg: dict):
        """
        Lua client confirmed it moved the mon to a memorial box.
        When both sides of a pair are confirmed, mark entry MEMORIAL and write memorial.json.
        """
        key = msg.get("key", "")
        if not key:
            return
        self.pending_memorials[player_id].discard(key)
        self.party_keys[player_id].discard(key)
        log.info(f"[{player_id}] memorialize_done key={key[:8]}")
        entry = self._key_index.get(key)
        if not entry or entry.status != LinkStatus.DEAD:
            self._save()
            return
        a_key = entry.a.key if entry.a else None
        b_key = entry.b.key if entry.b else None
        a_done = (a_key is None) or (a_key not in self.pending_memorials["a"])
        b_done = (b_key is None) or (b_key not in self.pending_memorials["b"])
        if a_done and b_done:
            entry.status = LinkStatus.MEMORIAL
            log.info(f"pair in {entry.area_id} fully memorialized")
            self._write_memorial(entry)
        self._save()

    def _handle_memorialize_failed(self, player_id: str, msg: dict):
        """
        Lua couldn't move the mon to a memorial box (all boxes full or key not found).
        Treat as done — remove from pending so the pair can reach MEMORIAL status.
        The mon stays wherever it was; this is a best-effort operation.
        """
        key = msg.get("key", "")
        reason = msg.get("reason", "unknown")
        if not key:
            return
        self.pending_memorials[player_id].discard(key)
        log.warning(f"[{player_id}] memorialize_failed key={key[:8]} reason={reason}")
        # Check if the pair can now be finalized despite the failure
        entry = self._key_index.get(key)
        if not entry or entry.status != LinkStatus.DEAD:
            self._save()
            return
        a_key = entry.a.key if entry.a else None
        b_key = entry.b.key if entry.b else None
        a_done = (a_key is None) or (a_key not in self.pending_memorials["a"])
        b_done = (b_key is None) or (b_key not in self.pending_memorials["b"])
        if a_done and b_done:
            entry.status = LinkStatus.MEMORIAL
            log.info(f"pair in {entry.area_id} marked memorial (with failed memorialization)")
            self._write_memorial(entry)
        self._save()

    def _write_memorial(self, entry: LinkEntry):
        """Append the retired pair to memorial.json via atomic rewrite."""
        os.makedirs(self._data_dir, exist_ok=True)
        try:
            with open(self._memorial_path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"retired_pairs": []}
        data["retired_pairs"].append({
            "area_id": entry.area_id,
            "a": asdict(entry.a) if entry.a else None,
            "b": asdict(entry.b) if entry.b else None,
            "killed_at": entry.killed_at,
            "cause": entry.cause,
            "killer": entry.killer,
            "initiating_player": entry.initiating_player,
        })
        try:
            self._atomic_write_json(self._memorial_path, data)
        except OSError as e:
            log.warning(f"[SAVE] memorial.json write failed (non-fatal): {e}")

    def _check_game_over(self):
        """
        Check if the Soul Link run is over.
        Conditions (all must be true):
        1. Both players have obtained Pokéballs (nuzlocke started)
        2. At least one real linked pair has ever existed (both a and b present)
        3. Zero alive links remain
        4. Zero pending captures that could still form new links
        5. Not already flagged
        When triggered, queues game_over command to both players.
        """
        if self.run_over:
            return
        # Gate: nuzlocke must be active for both players
        if not (self.pokeballs_obtained.get("a") and self.pokeballs_obtained.get("b")):
            return
        # Gate: run must have actually started — at least one real pair ever formed
        has_real_pair = any(
            e.a is not None and e.a.key and e.b is not None and e.b.key
            for e in self.links
        )
        if not has_real_pair:
            return
        # Any alive links?
        if any(e.status == LinkStatus.ALIVE for e in self.links):
            return
        # Any pending captures waiting to form links?
        if self.pending_captures:
            return
        # Game over
        self.run_over = True
        log.info("GAME OVER — no alive links and no pending captures remain")
        for pid in ("a", "b"):
            self.queued_commands[pid].append({"cmd": "game_over"})

    def _atomic_write_json(self, path: str, payload):
        """Write JSON atomically: write to .tmp, fsync, rename over target.

        On crash mid-write, the original file at `path` is untouched.
        `os.replace` is atomic on both Windows and POSIX.

        On Windows, file sync software (e.g. Google Drive) can briefly hold
        a lock on the target file, making `os.replace` raise PermissionError.
        We retry up to 5 times with a short sleep before giving up.
        """
        import time
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def _save(self):
        os.makedirs(self._data_dir, exist_ok=True)
        payload = {
            "game_id": self.adapter.game_id,
            "rules": {
                "species_lock": self.species_lock,
                "gender_lock": self.gender_lock,
                "type_lock": self.type_lock,
            },
            "links": [
                {
                    "area_id": e.area_id,
                    "a":          asdict(e.a) if e.a else None,
                    "b":          asdict(e.b) if e.b else None,
                    "status":     e.status.value,
                    "encounter_a": asdict(e.encounter_a) if e.encounter_a else None,
                    "encounter_b": asdict(e.encounter_b) if e.encounter_b else None,
                    "killed_at":   e.killed_at,
                    "cause":       e.cause,
                    "killer":      e.killer,
                    "initiating_player": e.initiating_player,
                }
                for e in self.links
            ],
            "area_states": {k: v.value for k, v in self.area_states.items()},
            # Persist pending captures so the same-player no_catch guard survives restarts.
            "pending_captures": {
                area_id: {
                    player_id: asdict(mon)
                    for player_id, mon in players.items()
                }
                for area_id, players in self.pending_captures.items()
            },
            # Cached party stats per monKey (echoed in party_mon commands after box_to_party).
            "mon_stats": self.mon_stats,
            # Pokéball gate: whether each player has confirmed they can catch Pokémon.
            "pokeballs_obtained": self.pokeballs_obtained,
            # Committed ROM type (set once on first hello, static for run lifetime).
            "rom_type": self.rom_type,
            "trainer_names": self.trainer_names,
            # Player identity lock: OT ID + trainer name per slot.
            "player_identity": self.player_identity,
            # Memorials awaiting Lua confirmation (re-queued on reconnect).
            "pending_memorials": {
                pid: list(keys) for pid, keys in self.pending_memorials.items()
            },
            "retry_areas": {
                pid: list(areas) for pid, areas in self.retry_areas.items()
            },
            "bonus_keys": {
                pid: list(keys) for pid, keys in self.bonus_keys.items()
            },
            "pending_bonus": {
                pid: list(q) for pid, q in self.pending_bonus.items()
            },
            "run_over": self.run_over,
            "attempts_count": self.attempts_count,
            "rebuild_pending": {
                pid: (
                    {
                        "started_at":         rb.get("started_at", ""),
                        "queued_keys":        list(rb.get("queued_keys", [])),
                        "queued_partner_keys": list(rb.get("queued_partner_keys", [])),
                        "restored_keys":      list(rb.get("restored_keys", set())),
                    }
                    if rb else None
                )
                for pid, rb in self.rebuild_pending.items()
            },
        }
        try:
            self._atomic_write_json(self._links_path, payload)
        except OSError as e:
            log.warning(f"[SAVE] links.json write failed (non-fatal): {e}")
