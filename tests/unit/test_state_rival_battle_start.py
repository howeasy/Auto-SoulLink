"""
Unit tests for Rival Team Swap Phase 2:
- _handle_trainer_battle_start (currently log-only, no command queued)
- queue_rival_team_swap helper (used by manual inject + Phase 3 auto-trigger)

Run:
    pytest tests/unit/test_state_rival_battle_start.py -v
"""

from server.state import SoulLinkState
from server.adapters.gen3_frlge import Gen3Adapter


def _state_with_rr_adapter() -> SoulLinkState:
    """Fresh state with the Gen3 RR adapter and the rival-team-swap rule ON.

    Default state has rival_team_swap=False (opt-in per run, mirrors
    --explode-mode); tests asserting the feature's behaviour need it ON.
    Tests that exercise the disabled path flip it off explicitly.
    """
    adapter = Gen3Adapter(is_rr=True)
    return SoulLinkState(adapter=adapter, is_rr=True, rival_team_swap=True)


def _cache_partner_blob(state: SoulLinkState, player_id: str, count: int = 1):
    """Cheap fixture: shove `count` 100-byte blobs into the partner's cache."""
    state.partner_blobs[player_id] = [
        {"slot": i, "species_id": 25 + i, "level": 30 + i,
         "key": f"K{i}", "blob": bytes([0xA0 + i] * 100)}
        for i in range(count)
    ]


# ── _handle_trainer_battle_start (Phase 3: auto-trigger when enabled) ────────

def _replace_cmds(cmds):
    """Filter the returned cmds list to just our replace_rival_team entries."""
    return [c for c in cmds if c.get("cmd") == "replace_rival_team"]


def test_trainer_battle_start_auto_fires_when_rival_and_enabled():
    """Default state has rival_team_swap=True → rival fight auto-injects."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=3)
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325})
    rt = _replace_cmds(cmds)
    assert len(rt) == 1
    cmd = rt[0]
    assert cmd["trainer_id"] == 325
    assert cmd["source"] == "auto"
    assert cmd["n"] == 3


def test_trainer_battle_start_no_op_for_non_rival_id():
    """ID outside the adapter's rival set → no command."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=3)
    # Trainer ID 2 ("Red", class 13) is in rr_trainers.json but not a Terry rival.
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 2})
    assert _replace_cmds(cmds) == []


def test_trainer_battle_start_respects_global_disable():
    state = _state_with_rr_adapter()
    state.rival_team_swap = False
    _cache_partner_blob(state, "b", count=3)
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325})
    assert _replace_cmds(cmds) == []


def test_trainer_battle_start_skips_when_partner_offline():
    """Rival ID + toggle on, but partner has no blobs → no command."""
    state = _state_with_rr_adapter()
    # Note: no _cache_partner_blob call — partner cache stays empty.
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325})
    assert _replace_cmds(cmds) == []


def test_trainer_battle_start_vanilla_adapter_no_op():
    """Vanilla Gen3 returns empty rival set → never fires even with toggle on."""
    from server.adapters.gen3_frlge import Gen3Adapter
    vanilla = Gen3Adapter(is_rr=False)
    state = SoulLinkState(adapter=vanilla, is_rr=False)
    _cache_partner_blob(state, "b", count=3)
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325})
    assert _replace_cmds(cmds) == []


def test_trainer_battle_start_ignores_zero_id():
    state = _state_with_rr_adapter()
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 0})
    assert _replace_cmds(cmds) == []


def test_trainer_battle_start_ignores_missing_id():
    state = _state_with_rr_adapter()
    cmds = state.handle_event("a", {"event": "trainer_battle_start"})
    assert _replace_cmds(cmds) == []


def test_trainer_battle_start_ignores_non_int_id():
    state = _state_with_rr_adapter()
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": "325"})
    assert _replace_cmds(cmds) == []


# ── queue_rival_team_swap helper ─────────────────────────────────────────────

def test_queue_helper_succeeds_when_partner_has_blobs():
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=6)
    ok, reason = state.queue_rival_team_swap("a", trainer_id=437, source="manual")
    assert ok is True
    assert reason == "queued"
    cmds = state.queued_commands["a"]
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd["cmd"] == "replace_rival_team"
    assert cmd["trainer_id"] == 437
    assert cmd["n"] == 6
    assert len(cmd["blobs_hex"]) == 6
    assert all(len(h) == 200 for h in cmd["blobs_hex"])
    assert cmd["source"] == "manual"


def test_queue_helper_fails_when_partner_blobs_empty():
    state = _state_with_rr_adapter()
    ok, reason = state.queue_rival_team_swap("a", trainer_id=325, source="manual")
    assert ok is False
    assert "no cached party blobs" in reason
    assert state.queued_commands["a"] == []


def test_queue_helper_uses_correct_partner():
    """target=a should use b's blobs, target=b should use a's blobs."""
    state = _state_with_rr_adapter()
    state.partner_blobs["a"] = [{
        "slot": 0, "species_id": 1, "level": 5, "key": "Ka",
        "blob": bytes([0xAA] * 100),
    }]
    state.partner_blobs["b"] = [{
        "slot": 0, "species_id": 4, "level": 5, "key": "Kb",
        "blob": bytes([0xBB] * 100),
    }]
    # Player a's rival fight → uses b's blobs.
    ok_a, _ = state.queue_rival_team_swap("a", trainer_id=325)
    assert ok_a is True
    assert state.queued_commands["a"][0]["blobs_hex"][0] == "bb" * 100
    # Player b's rival fight → uses a's blobs.
    ok_b, _ = state.queue_rival_team_swap("b", trainer_id=325)
    assert ok_b is True
    assert state.queued_commands["b"][0]["blobs_hex"][0] == "aa" * 100


def test_queue_helper_default_source_is_auto():
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    state.queue_rival_team_swap("a", trainer_id=325)
    assert state.queued_commands["a"][0]["source"] == "auto"


def test_queue_helper_blob_hex_round_trip():
    """Bytes-to-hex round-trip preserves original blob exactly."""
    state = _state_with_rr_adapter()
    payload = bytes(range(100))  # 0x00..0x63
    state.partner_blobs["b"] = [{
        "slot": 0, "species_id": 25, "level": 30, "key": "K0",
        "blob": payload,
    }]
    state.queue_rival_team_swap("a", trainer_id=325)
    hex_str = state.queued_commands["a"][0]["blobs_hex"][0]
    assert bytes.fromhex(hex_str) == payload


# ── rival_team_replaced ack ──────────────────────────────────────────────────

def test_rival_team_replaced_ack_accepts_valid_payload():
    state = _state_with_rr_adapter()
    state.handle_event("a", {
        "event": "rival_team_replaced",
        "trainer_id": 325,
        "species_ids": [25, 6, 9],
    })
    # No state mutation expected — handler is pure logging for Phase 2.
    assert state.queued_commands["a"] == []
    assert state.queued_commands["b"] == []


def test_rival_team_replaced_ack_tolerates_bad_payload():
    state = _state_with_rr_adapter()
    state.handle_event("a", {
        "event": "rival_team_replaced",
        "trainer_id": 325,
        "species_ids": "not a list",
    })
    assert state.queued_commands["a"] == []
