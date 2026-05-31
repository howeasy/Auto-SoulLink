"""
Unit tests for the peer-ghost overworld pipeline (server side).

The server is intentionally game-agnostic: it caches the latest position from
each player's `ghost_pos` event and pushes back a `ghost_pos` (or `ghost_clear`)
command to the partner via the existing `queued_commands` round-trip.

Run:
    pytest tests/unit/test_peer_ghost.py -v
"""

import pytest

from server import state as state_mod
from server.state import SoulLinkState


# ── helpers ───────────────────────────────────────────────────────────────────

def _gp(player: str, mg: int, mn: int, x: int, y: int, f: int = 1, mv: int = 0,
        imgs: int = 0, anim: int = 0, pal: int = 0) -> dict:
    return {
        "event": "ghost_pos",
        "player": player,
        "mg": mg, "mn": mn,
        "x": x, "y": y,
        "f": f, "mv": mv,
        "imgs": imgs, "anim": anim, "pal": pal,
    }


def _cmds_of(cmds: list, name: str) -> list[dict]:
    return [c for c in cmds if c.get("cmd") == name]


# ── basic caching ─────────────────────────────────────────────────────────────

def test_ghost_pos_stores_position():
    """Sender's PeerPos is cached verbatim under self.peer_pos[player_id]."""
    state = SoulLinkState()
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9, f=2, mv=1))

    p = state.peer_pos["a"]
    assert p is not None
    assert (p.mg, p.mn, p.x, p.y, p.f, p.mv) == (3, 5, 14, 9, 2, 1)
    assert p.ts > 0
    # Partner unaffected.
    assert state.peer_pos["b"] is None


def test_ghost_pos_malformed_payload_is_ignored():
    """Missing fields or bad types drop the event silently — no crash, no cache."""
    state = SoulLinkState()
    state.handle_event("a", {"event": "ghost_pos"})  # no coords
    state.handle_event("a", {"event": "ghost_pos", "mg": "three", "mn": 5, "x": 1, "y": 1})
    assert state.peer_pos["a"] is None


# ── same-map gating ───────────────────────────────────────────────────────────

def test_queues_partner_command_when_same_map():
    """Both players on same (mg, mn) → B's next round-trip carries A's ghost_pos."""
    state = SoulLinkState()
    state.trainer_names["a"] = "ALICE"
    # B reports their own position first so the same-map test has both sides.
    state.handle_event("b", _gp("b", mg=3, mn=5, x=20, y=20))
    # A reports — this should push a ghost_pos into B's queue (and won't flush
    # because B isn't the recipient of this handle_event).
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9, f=2, mv=1))

    cmds_b = state.handle_event("b", {"event": "tick"})
    ghosts = _cmds_of(cmds_b, "ghost_pos")
    assert len(ghosts) == 1
    g = ghosts[0]
    assert (g["mg"], g["mn"], g["x"], g["y"], g["f"], g["mv"]) == (3, 5, 14, 9, 2, 1)
    assert g["name"] == "ALICE"


def test_chosen_trainer_graphics_relay_to_partner():
    """The partner's chosen-trainer pointers (images/anims/palette) relay verbatim so
    the ghost can render their actual trainer, not a clone of the viewer."""
    state = SoulLinkState()
    state.handle_event("b", _gp("b", mg=3, mn=5, x=20, y=20))
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9,
                                imgs=0x0915B6F0, anim=0x0915B0F4, pal=0x092FB8CC))
    g = _cmds_of(state.handle_event("b", {"event": "tick"}), "ghost_pos")[0]
    assert g["imgs"] == 0x0915B6F0
    assert g["anim"] == 0x0915B0F4
    assert g["pal"] == 0x092FB8CC


def test_no_ghost_until_recipient_reports_own_position():
    """Same-map gate can't be evaluated until B has sent its own ghost_pos."""
    state = SoulLinkState()
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9))
    cmds_b = state.handle_event("b", {"event": "tick"})
    assert _cmds_of(cmds_b, "ghost_pos") == []
    assert _cmds_of(cmds_b, "ghost_clear") == []


def test_different_map_no_ghost_emitted():
    """A on map (3,5), B on map (3,6) → B gets no ghost_pos."""
    state = SoulLinkState()
    state.handle_event("b", _gp("b", mg=3, mn=6, x=1, y=1))
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9))

    cmds_b = state.handle_event("b", {"event": "tick"})
    assert _cmds_of(cmds_b, "ghost_pos") == []


# ── ghost_clear on map change ─────────────────────────────────────────────────

def test_emits_clear_when_partner_changes_map():
    """A leaves the shared map → B gets a single ghost_clear, never repeated."""
    state = SoulLinkState()
    state.handle_event("b", _gp("b", mg=3, mn=5, x=20, y=20))
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9))
    cmds_b1 = state.handle_event("b", {"event": "tick"})
    assert _cmds_of(cmds_b1, "ghost_pos"), "B should see A while same-map"

    # A walks through a door into map (3, 6).
    state.handle_event("a", _gp("a", mg=3, mn=6, x=0, y=0))
    cmds_b2 = state.handle_event("b", {"event": "tick"})
    assert len(_cmds_of(cmds_b2, "ghost_clear")) == 1
    assert _cmds_of(cmds_b2, "ghost_pos") == []

    # Subsequent ticks while still different-map: nothing more (no spam).
    cmds_b3 = state.handle_event("b", {"event": "tick"})
    assert _cmds_of(cmds_b3, "ghost_clear") == []
    assert _cmds_of(cmds_b3, "ghost_pos") == []


# ── coalescing ────────────────────────────────────────────────────────────────

def test_coalesces_rapid_sends_in_queue():
    """5 ghost_pos in a row from A → exactly 1 in B's queue, with latest values."""
    state = SoulLinkState()
    state.handle_event("b", _gp("b", mg=3, mn=5, x=20, y=20))
    for i in range(5):
        state.handle_event("a", _gp("a", mg=3, mn=5, x=10 + i, y=9))
    # Inspect B's queue directly without flushing.
    ghosts = _cmds_of(state.queued_commands["b"], "ghost_pos")
    assert len(ghosts) == 1
    assert ghosts[0]["x"] == 14  # last value wins


def test_coalesce_replaces_clear_with_pos():
    """If a ghost_clear is already queued and A returns, only the latest survives."""
    state = SoulLinkState()
    state.handle_event("b", _gp("b", mg=3, mn=5, x=20, y=20))
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9))
    state.handle_event("b", {"event": "tick"})  # flush — clears _ghost_visible_to bookkeeping reset path

    # A leaves → queue a clear.
    state.handle_event("a", _gp("a", mg=3, mn=6, x=0, y=0))
    assert len(_cmds_of(state.queued_commands["b"], "ghost_clear")) == 1

    # A returns to the shared map BEFORE B flushed — replace clear with fresh pos.
    state.handle_event("a", _gp("a", mg=3, mn=5, x=15, y=9))
    q = state.queued_commands["b"]
    assert _cmds_of(q, "ghost_clear") == []
    assert len(_cmds_of(q, "ghost_pos")) == 1


# ── staleness ─────────────────────────────────────────────────────────────────

def test_staleness_drops_position_and_emits_one_clear(monkeypatch):
    """Partner's PeerPos older than GHOST_STALENESS_SECONDS → one ghost_clear,
    then no further ghost_pos / ghost_clear on subsequent ticks."""
    fake_now = [1_000_000.0]
    monkeypatch.setattr(state_mod.time, "time", lambda: fake_now[0])

    state = SoulLinkState()
    state.handle_event("b", _gp("b", mg=3, mn=5, x=20, y=20))
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9))

    cmds_b1 = state.handle_event("b", {"event": "tick"})
    assert _cmds_of(cmds_b1, "ghost_pos"), "B should see A initially"

    # Jump past the staleness window.
    fake_now[0] += state_mod.GHOST_STALENESS_SECONDS + 0.5
    cmds_b2 = state.handle_event("b", {"event": "tick"})
    assert len(_cmds_of(cmds_b2, "ghost_clear")) == 1
    assert _cmds_of(cmds_b2, "ghost_pos") == []

    # No spam on subsequent stale ticks.
    fake_now[0] += 5.0
    cmds_b3 = state.handle_event("b", {"event": "tick"})
    assert _cmds_of(cmds_b3, "ghost_clear") == []
    assert _cmds_of(cmds_b3, "ghost_pos") == []


# ── persistence ───────────────────────────────────────────────────────────────

def test_peer_pos_not_persisted(tmp_path, monkeypatch):
    """save/load round-trip must leave peer_pos at {a: None, b: None}.

    Positions are stale on restart; replaying them would render ghosts at
    long-gone tiles.  Confirms PeerPos was deliberately omitted from _save().
    """
    monkeypatch.setattr("server.state.LINKS_PATH", str(tmp_path / "links.json"))
    state = SoulLinkState(data_dir=str(tmp_path))
    state.handle_event("a", _gp("a", mg=3, mn=5, x=14, y=9))
    state.handle_event("b", _gp("b", mg=3, mn=5, x=20, y=20))
    state._save()
    assert state.peer_pos["a"] is not None  # cached in memory pre-reload

    reloaded = SoulLinkState.load(data_dir=str(tmp_path))
    assert reloaded.peer_pos == {"a": None, "b": None}
    assert reloaded._ghost_visible_to == {"a": False, "b": False}
