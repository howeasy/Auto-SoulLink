"""
Unit tests for Rival Team Swap Phase 2:
- _handle_trainer_battle_start (currently log-only, no command queued)
- queue_rival_team_swap helper (used by manual inject + Phase 3 auto-trigger)

Run:
    pytest tests/unit/test_state_rival_battle_start.py -v
"""

from server.adapters.gen3_frlge import Gen3Adapter
from server.state import SoulLinkState


def _state_with_rr_adapter() -> SoulLinkState:
    """Fresh state with the Gen3 RR adapter and the rival-team-swap rule ON.

    Default state has rival_team_swap=False (opt-in per run, mirrors
    --explode-mode); tests asserting the feature's behaviour need it ON.
    Tests that exercise the disabled path flip it off explicitly.
    """
    adapter = Gen3Adapter(is_rr=True)
    return SoulLinkState(adapter=adapter, is_rr=True, rival_team_swap=True)


def _declare_battle_identity(state: SoulLinkState, player_id: str) -> None:
    """The real path for the capability (card C5-10b): a hello that declares it. A client that
    never declares it keeps the pre-card manual-inject behaviour."""
    state.handle_event(player_id, {"event": "hello", "party": [], "battle_identity": True})


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
    # card C5-10: the manual path inherits the client's latest announced identity, so a manual
    # inject needs one to have been announced first (see test_c510_* for the refusal without).
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 437,
                             "session": "ABCD1234", "battle_id": 1})
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
    assert (cmd["session"], cmd["battle_id"]) == ("ABCD1234", 1)


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


# ── card C5-10: the battle request identity (session nonce + battle counter) ─────────────────

SESSION_A = "ABCD1234"
SESSION_B = "9999BEEF"


def test_c510_the_identity_is_stored_per_player_and_echoed_on_the_command():
    """The auto path stores what the client announced and echoes BOTH halves on the command for
    that battle; the other player is untouched."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=2)
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                                    "session": SESSION_A, "battle_id": 1})
    (cmd,) = _replace_cmds(cmds)
    assert (cmd["session"], cmd["battle_id"]) == (SESSION_A, 1)
    assert state.latest_battle_requests["a"] == (SESSION_A, 1, 325)
    assert "b" not in state.latest_battle_requests


def test_c510_the_counter_advances_and_the_session_survives_a_re_battle():
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                             "session": SESSION_A, "battle_id": 1})
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                                    "session": SESSION_A, "battle_id": 2})
    (cmd,) = _replace_cmds(cmds)
    assert (cmd["session"], cmd["battle_id"]) == (SESSION_A, 2)


def test_c510_an_old_client_gets_no_identity_fields_at_all():
    """Gen 1, Gen 2 and old Gen 3 clients never send one: the command must stay byte-identical to
    what it was before this card (no session, no battle_id keys), and nothing is stored."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=2)
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325})
    (cmd,) = _replace_cmds(cmds)
    assert "session" not in cmd and "battle_id" not in cmd
    assert state.latest_battle_requests == {}


def test_c510_a_malformed_identity_is_not_stored_and_not_echoed():
    """Never coerced: a boolean counter, a fractional counter, an out-of-range counter and a
    non-hex nonce each leave the server with no identity to echo."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    for bad in ({"session": SESSION_A, "battle_id": True},
                {"session": SESSION_A, "battle_id": 1.5},
                {"session": SESSION_A, "battle_id": 0},
                {"session": SESSION_A, "battle_id": 2 ** 32},
                {"session": "not-hex", "battle_id": 1},
                {"session": "", "battle_id": 1},
                {"session": "A" * 17, "battle_id": 1},
                {"session": SESSION_A}):
        state.latest_battle_requests.clear()
        cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325, **bad})
        (cmd,) = _replace_cmds(cmds)
        assert "session" not in cmd and "battle_id" not in cmd, bad
        assert state.latest_battle_requests == {}, bad


def test_c510_the_manual_path_inherits_the_latest_identity():
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                             "session": SESSION_A, "battle_id": 4})
    ok, reason = state.queue_rival_team_swap("a", trainer_id=325, source="manual")
    assert ok, reason
    cmd = state.queued_commands["a"][-1]
    assert (cmd["session"], cmd["battle_id"]) == (SESSION_A, 4)


def test_c510_a_manual_inject_without_stored_identity_is_refused():
    """Codex REV-5: after a server restart (or before any announcement) there is no identity to
    send, and sending one that the client cannot match is a guaranteed refusal a round trip
    later. The manual inject refuses here instead."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    _declare_battle_identity(state, "a")
    ok, reason = state.queue_rival_team_swap("a", trainer_id=325, source="manual")
    assert not ok and "battle request identity" in reason
    assert state.queued_commands["a"] == []


def test_c510b_an_old_client_still_gets_a_manual_inject_with_no_identity_fields():
    """The regression the card refused: the OLD RR client never announces an identity, so the
    manual inject must behave exactly as it did before card C5-10 — queued, no session, no
    battle_id."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=2)
    assert state.battle_identity_clients == {}
    ok, reason = state.queue_rival_team_swap("a", trainer_id=437, source="manual")
    assert ok and reason == "queued", reason
    cmd = state.queued_commands["a"][-1]
    assert cmd["cmd"] == "replace_rival_team"
    assert "session" not in cmd and "battle_id" not in cmd


def test_c510b_a_declared_client_is_refused_without_a_stored_identity():
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    _declare_battle_identity(state, "a")
    assert state.battle_identity_clients["a"] is True
    ok, reason = state.queue_rival_team_swap("a", trainer_id=437, source="manual")
    assert not ok and "battle request identity" in reason
    assert state.queued_commands["a"] == []


def test_c510b_a_declared_client_queues_the_identity_after_an_announcement():
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    _declare_battle_identity(state, "a")
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 437,
                             "session": SESSION_A, "battle_id": 2})
    ok, reason = state.queue_rival_team_swap("a", trainer_id=437, source="manual")
    assert ok and reason == "queued", reason
    cmd = state.queued_commands["a"][-1]
    assert (cmd["session"], cmd["battle_id"]) == (SESSION_A, 2)


def test_c510b_a_hello_without_the_declaration_leaves_the_capability_off():
    state = _state_with_rr_adapter()
    state.handle_event("a", {"event": "hello", "party": []})
    assert state.battle_identity_clients["a"] is False
    state.handle_event("a", {"event": "hello", "party": [], "battle_identity": False})
    assert state.battle_identity_clients["a"] is False


def test_c510_a_manual_inject_after_a_session_change_is_refused_by_the_client_guard():
    """The stale-metadata case: the stored identity belongs to a session the client has left.
    The server still echoes what it has (it cannot know), and the CLIENT's guard is what refuses
    it — so this test pins the server side of that contract: the echoed id is the OLD session's,
    never a freshly invented one."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    first = _replace_cmds(state.handle_event("a", {"event": "trainer_battle_start",
                                                  "trainer_id": 325,
                                                  "session": SESSION_A, "battle_id": 7}))
    # a restarted client announces a NEW session; the old command keeps its own identity
    second = _replace_cmds(state.handle_event("a", {"event": "trainer_battle_start",
                                                   "trainer_id": 325,
                                                   "session": SESSION_B, "battle_id": 1}))
    queued = first + second
    assert (queued[0]["session"], queued[0]["battle_id"]) == (SESSION_A, 7)
    assert (queued[1]["session"], queued[1]["battle_id"]) == (SESSION_B, 1)
    assert state.latest_battle_requests["a"] == (SESSION_B, 1, 325)


def test_c510_an_already_queued_command_is_never_retagged():
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                             "session": SESSION_A, "battle_id": 3})
    before = _replace_cmds(state.handle_event("a", {"event": "trainer_battle_start",
                                                   "trainer_id": 325,
                                                   "session": SESSION_A, "battle_id": 3}))
    after = _replace_cmds(state.handle_event("a", {"event": "trainer_battle_start",
                                                  "trainer_id": 325,
                                                  "session": SESSION_B, "battle_id": 9}))
    assert len(before) == len(after) == 1
    assert before[0] != after[0]
    assert (before[0]["session"], before[0]["battle_id"]) == (SESSION_A, 3)


def test_c510b_auto_never_inherits_a_stored_identity():
    """MAJOR 2 (Codex): an AUTO command echoes ONLY the identity of the announcement that
    triggered it; and a legacy announcement (no identity at all) CLEARS the stored one."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                             "session": SESSION_A, "battle_id": 4})
    cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325})
    (cmd,) = _replace_cmds(cmds)
    assert "session" not in cmd and "battle_id" not in cmd
    assert "a" not in state.latest_battle_requests, "a legacy announcement clears"


def test_c510b_a_malformed_announcement_is_rejected_and_never_treated_as_legacy():
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                             "session": SESSION_A, "battle_id": 4})
    for bad in ({"session": "zz", "battle_id": 4}, {"session": SESSION_A, "battle_id": True},
                {"session": SESSION_A, "battle_id": 0}, {"session": "A" * 17, "battle_id": 4}):
        cmds = state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325, **bad})
        (cmd,) = _replace_cmds(cmds)
        assert "session" not in cmd and "battle_id" not in cmd, bad
        assert state.latest_battle_requests["a"] == (SESSION_A, 4, 325), bad


def _lock_slot(state: SoulLinkState, player: str, ot: str) -> None:
    state.handle_event(player, {"event": "hello", "party": [{"key": f"AAAA0000:{ot}"}],
                                "ot_id": ot})


def test_c510b_a_rejected_hello_cannot_grant_the_capability():
    """MAJOR 3: the capability is adopted only after the identity lock accepts the hello, so a
    wrong-save hello cannot flip the manual-inject gate."""
    state = _state_with_rr_adapter()
    _lock_slot(state, "a", "11111111")
    state.handle_event("a", {"event": "hello", "party": [{"key": "BBBB0000:22222222"}],
                             "ot_id": "22222222", "battle_identity": True})
    assert state.battle_identity_clients.get("a") is not True, "a rejected hello grants nothing"


def test_c510b_a_rejected_hello_cannot_revoke_the_capability():
    state = _state_with_rr_adapter()
    _lock_slot(state, "a", "11111111")
    _declare_battle_identity(state, "a")
    assert state.battle_identity_clients["a"] is True
    state.handle_event("a", {"event": "hello", "party": [{"key": "BBBB0000:22222222"}],
                             "ot_id": "22222222"})
    assert state.battle_identity_clients["a"] is True, "a rejected hello revokes nothing"


def test_c510b_an_accepted_hello_adopts_the_declaration():
    state = _state_with_rr_adapter()
    _lock_slot(state, "a", "11111111")
    state.handle_event("a", {"event": "hello", "party": [{"key": "AAAA0000:11111111"}],
                             "ot_id": "11111111", "battle_identity": True})
    assert state.battle_identity_clients["a"] is True


def test_c511c_an_accepted_legacy_hello_clears_the_stored_identity():
    """MAJOR 7: a client that stops speaking the protocol must not leave a stale pair behind."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                             "session": SESSION_A, "battle_id": 7})
    assert state.latest_battle_requests["a"] == (SESSION_A, 7, 325)
    state.handle_event("a", {"event": "hello", "party": []})          # accepted, legacy
    assert "a" not in state.latest_battle_requests
    ok, reason = state.queue_rival_team_swap("a", trainer_id=325, source="manual")
    assert ok and reason == "queued"
    cmd = state.queued_commands["a"][-1]
    assert "session" not in cmd and "battle_id" not in cmd


def test_c511c_an_explicitly_invalid_pair_is_rejected_not_inherited():
    """Minor: only a FULLY OMITTED pair may inherit the stored identity; an explicitly supplied
    invalid one is refused outright."""
    state = _state_with_rr_adapter()
    _cache_partner_blob(state, "b", count=1)
    state.handle_event("a", {"event": "trainer_battle_start", "trainer_id": 325,
                             "session": SESSION_A, "battle_id": 7})
    for bad in ({"session": "zz", "battle_id": 7}, {"session": SESSION_A, "battle_id": True},
                {"session": SESSION_A, "battle_id": 0}, {"session": SESSION_A, "battle_id": 2 ** 32}):
        ok, reason = state.queue_rival_team_swap("a", trainer_id=325, source="manual", **bad)
        assert not ok and "invalid battle identity" in reason, bad
    assert state.queued_commands["a"] == []
    # both fields omitted (None is the parameter default) is the INHERIT case, not an invalid one
    ok, reason = state.queue_rival_team_swap("a", trainer_id=325, source="manual",
                                             session=None, battle_id=None)
    assert ok, reason
    cmd = state.queued_commands["a"][-1]
    assert (cmd["session"], cmd["battle_id"]) == (SESSION_A, 7)
