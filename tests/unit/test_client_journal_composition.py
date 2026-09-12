"""Atomic typed receipts and acknowledgement baselines; no cartridge execution."""

import json
from pathlib import Path

import pytest

from tests.unit.test_client_journal import accepted, command, start
from tests.unit.test_client_state_store import runtime  # noqa: F401


def configured(lua):
    start(lua)
    lua.execute("""
        map_calls=0;fail_map=false;fail_ack=false
        callbacks={completion_event=function(entry,outcome,proof)
            map_calls=map_calls+1
            assert(not fail_map,'injected mapper failure')
            return {event='native_decision',command_id=entry.command_id,
                command_sequence=entry.command_sequence,transaction_id=string.rep('a',32),receipt=proof}
        end,acknowledge_event=function(payload,id,baseline)
            assert(not fail_ack,'injected acknowledgement failure')
            baseline.last_ack={event=payload.event,operation_id=id}
            return baseline
        end}
        journal=assert(Journal.open(store,new_id,callbacks))
        function reopen_composed()
            store:close();store=assert(open_store());journal=assert(Journal.open(store,new_id,callbacks))
        end
    """)
    event = lua.globals().append('{"event":"sync"}')
    assert accepted(lua.globals().accept(event, json.dumps([command(1), command(2)])))


def test_typed_completion_confirmation_is_atomic_and_replays_without_mapper(runtime):  # noqa: F811
    lua = runtime
    configured(lua)
    assert accepted(
        lua.globals().complete(command(2)["command_id"], "ACK", '{"schema":"verified","yes":true}')
    )
    state = lua.globals().state()
    assert state.version == "slink-client-journal-v2"
    assert (
        state.inbox[2].completion_payload.event
        == state.outbox[1].payload.event
        == "native_decision"
    )
    ack = state.outbox[1].operation_id
    calls, writes = lua.globals().map_calls, lua.globals().writes
    lua.globals().fail_map = True
    lua.globals().reopen_composed()
    assert accepted(
        lua.globals().complete(command(2)["command_id"], "ACK", '{"schema":"verified","yes":true}')
    )
    assert (lua.globals().map_calls, lua.globals().writes) == (calls, writes)
    assert accepted(lua.globals().accept(ack, "[]"))
    state = lua.globals().state()
    assert state.command_floor == 0 and state.inbox[2].confirmed
    assert state.observation.last_ack.operation_id == ack
    lua.globals().fail_map = False
    assert accepted(
        lua.globals().complete(command(1)["command_id"], "ACK", '{"schema":"verified","yes":false}')
    )
    assert accepted(lua.globals().accept(lua.globals().state().outbox[1].operation_id, "[]"))
    assert lua.globals().state().command_floor == 2 and len(lua.globals().state().inbox) == 0


@pytest.mark.parametrize("mode,published", [("before", False), ("after", True)])
def test_uncertain_typed_receipt_write_preserves_outcome_and_event_together(
    runtime, mode, published  # noqa: F811
):  # noqa: F811
    lua = runtime
    configured(lua)
    lua.globals().mode = mode
    assert not accepted(
        lua.globals().complete(command(1)["command_id"], "ACK", '{"schema":"verified"}')
    )
    lua.globals().mode = "ok"
    lua.globals().reopen_composed()
    state = lua.globals().state()
    assert (state.inbox[1].outcome == "ACK") == published
    assert len(state.outbox) == int(published)
    if published:
        assert state.inbox[1].completion_payload.event == state.outbox[1].payload.event


@pytest.mark.parametrize(
    "mutation",
    [
        "payload.command_id=string.rep('f',32)",
        "payload.command_sequence=99",
        "payload.receipt={fake=true}",
        "payload.event='control'",
        "payload.seq=1",
    ],
)
def test_unbound_or_transient_typed_payload_refuses_before_publication(runtime, mutation):  # noqa: F811
    lua = runtime
    configured(lua)
    lua.execute(
        "local mapper=callbacks.completion_event;callbacks.completion_event=function(...) local payload=mapper(...);"
        + mutation
        + ";return payload end"
    )
    before = lua.globals().disk
    assert not accepted(
        lua.globals().complete(command(1)["command_id"], "ACK", '{"schema":"verified"}')
    )
    assert lua.globals().disk == before


def test_acknowledgement_callback_failure_keeps_event_and_inbox_unconfirmed(runtime):  # noqa: F811
    lua = runtime
    configured(lua)
    assert accepted(
        lua.globals().complete(command(1)["command_id"], "ACK", '{"schema":"verified"}')
    )
    before = lua.globals().disk
    ack = lua.globals().state().outbox[1].operation_id
    lua.globals().fail_ack = True
    assert not accepted(lua.globals().accept(ack, "[]"))
    assert lua.globals().disk == before
    lua.globals().fail_ack = False
    lua.globals().reopen_composed()
    assert accepted(lua.globals().accept(ack, "[]"))
    assert lua.globals().state().observation.last_ack.operation_id == ack


def test_intermediate_native_evidence_ack_does_not_confirm_terminal_receipt(runtime):  # noqa: F811
    lua = runtime
    configured(lua)
    intermediate = lua.globals().append(
        json.dumps(
            {
                "event": "native_applied",
                "command_id": command(1)["command_id"],
                "receipt": {"schema": "native-only"},
            }
        )
    )
    assert accepted(
        lua.globals().complete(command(1)["command_id"], "ACK", '{"schema":"file-verified"}')
    )
    assert accepted(lua.globals().accept(intermediate, "[]"))
    state = lua.globals().state()
    assert state.inbox[1].confirmed is None and state.command_floor == 0
    assert state.outbox[1].payload.event == "native_decision"
    assert accepted(lua.globals().accept(state.outbox[1].operation_id, "[]"))
    assert lua.globals().state().command_floor == 1


def test_previous_published_reader_refuses_composed_document_and_defaults_stay_v1(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    event = lua.globals().append('{"event":"sync"}')
    assert accepted(lua.globals().accept(event, json.dumps([command(1)])))
    assert accepted(
        lua.globals().complete(command(1)["command_id"], "ACK", '{"schema":"verified"}')
    )
    assert lua.globals().state().version == "slink-client-journal-v1"
    lua.execute("disk=nil")
    configured(lua)
    lua.globals().old_source = (
        Path(__file__).resolve().parents[1] / "fixtures/client_journal_v1.lua"
    ).read_text()
    assert lua.eval("select(1,assert(load(old_source))().open(store,new_id))==nil")

