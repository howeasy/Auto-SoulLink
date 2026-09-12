"""Durable Gen 1 HUD schema, projection, ordering and acknowledgement."""

from __future__ import annotations

import copy
import secrets

import pytest

from server.adapters import get_adapter
from server.gen1_acquisition_runtime import _decide_through_engine
from server.gen1_command_receipts import Gen1ReceiptPolicy
from server.gen1_engine_bridge import no_catch
from server.gen1_hud_feedback import (
    BODY_FIELDS,
    COMMAND_SCHEMA,
    RECEIPT_FIELDS,
    RECEIPT_SCHEMA,
    append_after_physical,
    build_notice,
    classify_captured,
    feedback_last,
    project,
    validate_body,
    verify_receipt,
)
from server.gen1_run_config import create_runtime
from server.gen1_staged_state import StagedGen1State
from server.protocol import digest
from server.protocol_journal import JournalError, ProtocolJournal
from server.state import AreaStatus, MonInfo, SoulLinkState
from tests.unit.test_gen1_sessions import contract


def notice(**changes):
    values = {
        "kind": "link_pending",
        "surface": "hud",
        "text": ">> Got Pikachu",
        "r": 100,
        "g": 180,
        "b": 255,
        "frames": 300,
        "now": lambda: 100,
    }
    values.update(changes)
    return build_notice(**values)


def journal_command(body=None):
    return {"command_id": "a" * 32, "command_sequence": 7, "body": body or notice()}


def hud_receipt(command=None, **changes):
    command = command or journal_command()
    values = {
        "schema": RECEIPT_SCHEMA,
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "body_digest": digest(command["body"]),
        "disposition": "drawn",
        "frame": 42,
    }
    values.update(changes)
    return values


def acknowledge_hud(runtime, *players):
    """Model the HUD executor's independent ACK lane, including behind physical FIFO entries."""
    for player in players or ("a", "b"):
        for command_id in runtime.journal.pending_ids(player):
            command = runtime.journal.command(player, command_id)
            if command["body"].get("cmd") != "hud_notice":
                continue
            receipt = hud_receipt(command)
            runtime.dispatcher.dispatch(
                player,
                secrets.token_hex(16),
                {
                    "event": "command_ack",
                    "command_id": command["command_id"],
                    "command_sequence": command["command_sequence"],
                    "outcome": "ACK",
                    "receipt": receipt,
                },
            )


def staged_rules(tmp_path):
    rules = SoulLinkState(
        data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type="red")
    )
    rules.rom_type = "red"
    rules.pokeballs_obtained = {"a": True, "b": True}
    return StagedGen1State.from_live(rules, {"retired_pairs": []})


def test_notice_builder_is_exact_bounded_and_uses_fixed_delivery_ttl():
    body = notice()
    assert set(body) == BODY_FIELDS
    assert body == {
        "cmd": "hud_notice",
        "schema": COMMAND_SCHEMA,
        "kind": "link_pending",
        "surface": "hud",
        "text": ">> Got Pikachu",
        "r": 100,
        "g": 180,
        "b": 255,
        "frames": 300,
        "issued_at": 100,
        "expires_at": 130,
    }
    assert validate_body(body) is body


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cmd", "hud_show"),
        ("schema", "slink-gen1-hud-notice-v2"),
        ("kind", "trade"),
        ("surface", "sound"),
        ("text", ""),
        ("text", "x" * 31),
        ("text", "Poke\nmon"),
        ("text", "Pokémon"),
        ("r", -1),
        ("g", 256),
        ("b", True),
        ("frames", 0),
        ("frames", 601),
        ("issued_at", -1),
        ("issued_at", 1.5),
        ("expires_at", 99),
        ("expires_at", 221),
    ],
)
def test_notice_schema_rejects_out_of_contract_fields_and_bounds(field, value):
    body = notice()
    body[field] = value
    with pytest.raises(JournalError):
        validate_body(body)


def test_projection_compacts_text_and_preserves_only_valid_legacy_style():
    body = project(
        {
            "cmd": "msgbox",
            "text": "Pokémon partners are linked across a very long route",
            "r": 7,
            "g": 8,
            "b": 9,
            "frames": 600,
        },
        kind="link_formed",
        surface="prompt",
        now=lambda: 500,
    )
    assert body["text"] == "Pokemon partners are linked..."
    assert len(body["text"]) == 30
    assert (body["r"], body["g"], body["b"], body["frames"]) == (7, 8, 9, 600)
    fallback = project(
        {"cmd": "hud_show", "text": "waiting", "r": True, "frames": 999},
        kind="link_pending",
        surface="hud",
        now=lambda: 500,
    )
    assert (fallback["r"], fallback["g"], fallback["b"], fallback["frames"]) == (
        100,
        180,
        255,
        300,
    )
    detailed = project(
        {"cmd": "gui_prompt", "text": "[x] Species clause: Pikachu in Viridian Forest"},
        kind="clause_retry",
        surface="prompt",
        now=lambda: 500,
    )
    assert detailed["text"] == "Pikachu in Viridian Forest"


def test_engine_projection_preserves_recipients_and_uses_explicit_purposes(tmp_path):
    rules = staged_rules(tmp_path)
    first = _decide_through_engine(
        rules,
        "a",
        "route_1",
        MonInfo(key="A:1", species=25, level=5, nickname="SPARK"),
        {"location": "box"},
        exempt=False,
        hud_now=lambda: 100,
    )
    assert first["linked"] is None and first["violation"] is None
    assert first["feedback"]["a"] == []
    assert [(body["kind"], body["surface"]) for body in first["feedback"]["b"]] == [
        ("link_pending", "hud")
    ]

    second = _decide_through_engine(
        rules,
        "b",
        "route_1",
        MonInfo(key="B:1", species=19, level=4, nickname="TAIL"),
        {"location": "box"},
        exempt=False,
        hud_now=lambda: 101,
    )
    assert second["linked"] is not None and second["violation"] is None
    for player in ("a", "b"):
        assert [(body["kind"], body["surface"]) for body in second["feedback"][player]] == [
            ("link_formed", "prompt")
        ]


def test_dead_zone_rejection_is_a_violation_not_a_species_clause(tmp_path):
    rules = staged_rules(tmp_path)
    rules.area_states["route_2"] = AreaStatus.DEAD_ZONE
    result = _decide_through_engine(
        rules,
        "a",
        "route_2",
        MonInfo(key="A:2", species=16, level=4, nickname="BIRD"),
        {"location": "party"},
        exempt=False,
        hud_now=lambda: 100,
    )
    assert result["violation"][0].startswith("Dead zone:")
    assert not result["violation"][0].startswith("Species clause:")
    assert [(body["kind"], body["surface"]) for body in result["feedback"]["a"]] == [
        ("violation", "prompt")
    ]
    assert "route_2" in result["feedback"]["a"][0]["text"]
    assert result["feedback"]["b"] == []


def test_no_catch_species_clause_gets_one_retry_notice_but_legacy_silent_cases_stay_silent(
    tmp_path,
):
    rules = staged_rules(tmp_path)
    result = no_catch(
        rules,
        "a",
        "viridian_forest",
        25,
        7,
        activated=True,
        proved_peers=None,
        decision=lambda *args, **kwargs: "species_clause",
        now=lambda: 100,
    )
    assert [(body["kind"], body["surface"]) for body in result["feedback"]["a"]] == [
        ("clause_retry", "prompt")
    ]
    assert "Pikachu" in result["feedback"]["a"][0]["text"]
    assert "Viridian Forest" in result["feedback"]["a"][0]["text"]
    for outcome in ("clause_retry", "dupe_already_notified"):
        rules.dupe_notified_areas["a"].add("viridian_forest")
        silent = no_catch(
            rules,
            "a",
            "viridian_forest",
            25,
            7,
            activated=True,
            proved_peers=None,
            decision=lambda *args, value=outcome, **kwargs: value,
            now=lambda: 100,
        )
        assert silent["feedback"] == {"a": [], "b": []}


def test_best_effort_projection_cannot_roll_back_rules_and_audits_clock_or_text_failure(
    tmp_path, caplog
):
    rules = staged_rules(tmp_path)

    def broken_clock():
        raise RuntimeError("clock unavailable")

    result = _decide_through_engine(
        rules,
        "a",
        "route_3",
        MonInfo(key="A:3", species=10, level=4, nickname="BUG"),
        {"location": "box"},
        exempt=False,
        hud_now=broken_clock,
    )
    assert result["feedback"] == {"a": [], "b": []}
    assert rules.pending_captures["route_3"]["a"].key == "A:3"
    assert "dropping Gen 1 HUD notice" in caplog.text

    caplog.clear()
    assert classify_captured(
        {"a": [{"cmd": "hud_show", "text": ""}], "b": []},
        linked=False,
        rejected=False,
        now=lambda: 100,
    ) == {"a": [], "b": []}
    assert "dropping Gen 1 HUD notice" in caplog.text


def test_link_formed_coalesces_pending_notice_for_same_recipient():
    feedback = classify_captured(
        {
            "a": [
                {"cmd": "hud_show", "text": ">> Got Pikachu"},
                {"cmd": "msgbox", "text": "Pikachu and Eevee linked!"},
            ],
            "b": [],
        },
        linked=True,
        rejected=False,
        now=lambda: 100,
    )
    assert [body["kind"] for body in feedback["a"]] == ["link_formed"]


def test_physical_commands_precede_hud_in_the_same_journal_commit(tmp_path):
    physical = {"cmd": "retirement_observe", "acquisition_id": "b" * 32, "key": "A:1"}
    hud = notice()
    commands = append_after_physical({"a": [physical], "b": []}, {"a": [hud], "b": []})
    assert [body["cmd"] for body in commands["a"]] == ["retirement_observe", "hud_notice"]
    reordered = feedback_last({"a": [hud, physical], "b": []})
    assert [body["cmd"] for body in reordered["a"]] == ["retirement_observe", "hud_notice"]

    journal = ProtocolJournal(tmp_path / "hud.sqlite3", run_id="c" * 32, contract_hash="d" * 64)
    try:
        journal.bootstrap({"state": "fixture"})
        snapshot = journal.snapshot()
        journal.commit(
            "a",
            "e" * 32,
            {"event": "fixture"},
            expected_revision=snapshot.revision,
            state=snapshot.state,
            commands=commands,
            result={"ack": "ACK"},
        )
        assert [body["cmd"] for body in journal.pending("a")] == [
            "retirement_observe",
            "hud_notice",
        ]
    finally:
        journal.close()


def test_receipt_is_exact_and_expiration_does_not_depend_on_server_wall_time():
    command = journal_command()
    drawn = hud_receipt(command)
    assert set(drawn) == RECEIPT_FIELDS
    assert verify_receipt(command, drawn) == {
        "disposition": "drawn",
        "frame": 42,
    }
    expired = hud_receipt(command, disposition="expired", frame=-1)
    assert verify_receipt(command, expired) == {
        "disposition": "expired",
        "frame": -1,
    }
    # The client owns the expiry decision. A clock-skewed server validates only the exact
    # command binding and the no-write disposition/frame shape.
    future = journal_command(notice(now=lambda: 2_000_000_000))
    assert verify_receipt(future, hud_receipt(future, disposition="expired", frame=-1)) == {
        "disposition": "expired",
        "frame": -1,
    }
    with pytest.raises(JournalError, match="frame -1"):
        verify_receipt(command, hud_receipt(command, disposition="expired", frame=0))

    mutations = [
        {"command_id": "b" * 32},
        {"command_sequence": 8},
        {"body_digest": "0" * 64},
        {"disposition": "ignored"},
        {"frame": True},
    ]
    for changes in mutations:
        receipt = copy.deepcopy(drawn)
        receipt.update(changes)
        with pytest.raises(JournalError):
            verify_receipt(command, receipt)


def test_receipt_policy_has_no_rule_followup_and_journal_ack_is_replay_idempotent(tmp_path):
    body = notice()
    journal = ProtocolJournal(tmp_path / "hud.sqlite3", run_id="c" * 32, contract_hash="d" * 64)
    try:
        journal.bootstrap({"state": "fixture"})
        snapshot = journal.snapshot()
        journal.commit(
            "a",
            "e" * 32,
            {"event": "fixture"},
            expected_revision=snapshot.revision,
            state=snapshot.state,
            commands={"a": [body], "b": []},
            result={"ack": "ACK"},
        )
        pending = journal.pending("a")[0]
        command = journal.command("a", pending["command_id"])
        receipt = hud_receipt(command)
        event = {
            "event": "command_ack",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "outcome": "ACK",
            "receipt": receipt,
        }
        policy = Gen1ReceiptPolicy({"a": "red", "b": "yellow"})
        assert policy("a", command, event, object()) == []
        assert journal.acknowledge("a", command["command_id"], "ACK", receipt) is True
        assert journal.acknowledge("a", command["command_id"], "ACK", receipt) is False
        assert journal.pending("a") == []
    finally:
        journal.close()


def test_durable_ack_replay_returns_the_original_commit_without_a_second_effect(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "yellow"))
    try:
        snapshot = runtime.journal.snapshot()
        runtime.journal.commit(
            "a",
            "e" * 32,
            {"event": "fixture"},
            expected_revision=snapshot.revision,
            state=snapshot.state,
            commands={"a": [notice()], "b": []},
            result={"ack": "ACK"},
        )
        pending = runtime.journal.pending("a")[0]
        command = runtime.journal.command("a", pending["command_id"])
        request = {
            "event": "command_ack",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "outcome": "ACK",
            "receipt": hud_receipt(command),
        }
        operation = "f" * 32
        first = runtime.dispatcher.dispatch("a", operation, request)
        committed = runtime.journal.snapshot()
        second = runtime.dispatcher.dispatch("a", operation, request)
        assert first.replayed is False and second.replayed is True
        assert second.revision == first.revision and second.result == first.result
        assert runtime.journal.snapshot() == committed
        assert runtime.journal.command("a", command["command_id"])["outcome"] == "ACK"
        assert runtime.journal.pending("a") == []
    finally:
        runtime.close()
