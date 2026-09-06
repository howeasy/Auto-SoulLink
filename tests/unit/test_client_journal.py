import json

import pytest

from tests.unit.test_client_state_store import runtime  # noqa: F401


def start(lua):
    lua.execute("""
        Journal=require('client_journal');initial=Journal.initial();next_id=0
        function new_id() next_id=next_id+1;return string.format('%032x',next_id) end
        store=assert(open_store());journal=assert(Journal.open(store,new_id))
        function append(text) return journal:append(assert(JSON.decode(text))) end
        function accept(id,text) return journal:accept_response(id,assert(JSON.decode(text))) end
        function complete(id,outcome,text) return journal:complete_command(id,outcome,assert(JSON.decode(text))) end
        function prepare(id,text) return journal:prepare_command(id,assert(JSON.decode(text))) end
        function reopen() store:close();store=assert(open_store());journal=assert(Journal.open(store,new_id)) end
        function state() return (assert(store:read())) end
    """)


def command(number, **body):
    return {"command_id": f"{number + 1000:032x}", "command_sequence": number,
            "body": {"cmd": "box_mon", "key": "1234:5678:99", **body}}


def accepted(result):
    return result[0] if isinstance(result, tuple) else result


def test_observation_ids_and_payloads_survive_reopen_until_exact_fifo_ack(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    first = lua.globals().append('{"event":"capture","key":"1234:5678:99"}')
    second = lua.globals().append('{"event":"faint","key":"1234:5678:99"}')
    assert len(first) == 32 and first != second
    lua.globals().reopen()
    pending = lua.globals().journal.pending_events(lua.globals().journal)
    assert [p.operation_id for p in pending.values()] == [first, second]
    assert accepted(lua.globals().accept(second, "[]")) is False
    assert len(lua.globals().state().outbox) == 2
    assert accepted(lua.globals().accept(first, "[]")) is True
    lua.globals().reopen()
    assert lua.globals().state().outbox[1].operation_id == second


def test_response_persists_command_inbox_before_removing_the_outbox_event(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    event = lua.globals().append('{"event":"tick"}')
    lua.globals().mode = "before"
    assert accepted(lua.globals().accept(event, json.dumps([command(1)]))) is False
    lua.globals().mode = "ok"
    lua.globals().reopen()
    state = lua.globals().state()
    assert len(state.outbox) == 1 and len(state.inbox) == 0
    assert accepted(lua.globals().accept(event, json.dumps([command(1)]))) is True
    lua.globals().reopen()
    state = lua.globals().state()
    assert len(state.outbox) == 0 and state.inbox[1].command_id == command(1)["command_id"]
    assert state.inbox[1].outcome is None


def test_physical_receipt_and_ack_event_commit_together_and_advance_only_contiguous_floor(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    event = lua.globals().append('{"event":"tick"}')
    assert accepted(lua.globals().accept(event, json.dumps([command(1), command(2)])))
    # Immediate command2 may finish while deferred command1 is still waiting.
    proof = '{"validated_by":"test coordinator"}'
    assert accepted(lua.globals().complete(command(2)["command_id"], "ACK", proof))
    state = lua.globals().state()
    ack2 = state.outbox[1].operation_id
    assert state.outbox[1].payload.event == "command_ack" and state.inbox[2].outcome == "ACK"
    assert accepted(lua.globals().accept(ack2, "[]"))
    assert lua.globals().state().command_floor == 0 and len(lua.globals().state().inbox) == 2
    assert accepted(lua.globals().complete(command(1)["command_id"], "NACK", '{"reason":"party full"}'))
    ack1 = lua.globals().state().outbox[1].operation_id
    assert accepted(lua.globals().accept(ack1, "[]"))
    lua.globals().reopen()
    assert lua.globals().state().command_floor == 2 and len(lua.globals().state().inbox) == 0


def test_duplicate_commands_and_receipts_do_not_execute_or_enqueue_twice(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    first = lua.globals().append('{"event":"tick"}')
    assert accepted(lua.globals().accept(first, json.dumps([command(1)])))
    second = lua.globals().append('{"event":"tick"}')
    assert accepted(lua.globals().accept(second, json.dumps([command(1)])))
    assert len(lua.globals().state().inbox) == 1
    assert accepted(lua.globals().complete(command(1)["command_id"], "ACK", '{"proof":"same"}'))
    count = lua.globals().writes
    assert accepted(lua.globals().complete(command(1)["command_id"], "ACK", '{"proof":"same"}'))
    assert lua.globals().writes == count and len(lua.globals().state().outbox) == 1
    assert accepted(lua.globals().complete(command(1)["command_id"], "ACK", '{"proof":"different"}')) is False
    assert len(lua.globals().state().outbox) == 1


@pytest.mark.parametrize("payload", [{"event": "hello"}, {"event": "tick", "seq": 1},
                                    {"event": "tick", "session_id": "old"}, {"event": "tick", "operation_id": "old"}])
def test_delivery_attempt_identity_never_enters_durable_semantic_payload(runtime, payload):  # noqa: F811
    lua = runtime
    start(lua)
    before = lua.globals().disk
    assert lua.globals().append(json.dumps(payload))[0] is None
    assert lua.globals().disk == before


def test_conflicting_stale_and_malformed_command_batches_leave_event_pending(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    first = lua.globals().append('{"event":"tick"}')
    assert accepted(lua.globals().accept(first, json.dumps([command(2)])))
    second = lua.globals().append('{"event":"tick"}')
    before = lua.globals().disk
    for commands in ([command(2, key="changed")], [command(1)], {"hidden": command(3)}):
        assert accepted(lua.globals().accept(second, json.dumps(commands))) is False
        assert lua.globals().disk == before


def test_outbox_bound_is_explicit_and_preserves_every_accepted_operation(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.execute("Journal.MAX_EVENTS=3")
    ids = [lua.globals().append('{"event":"tick"}') for _ in range(3)]
    assert lua.globals().append('{"event":"tick"}')[0] is None
    lua.globals().reopen()
    assert [entry.operation_id for entry in lua.globals().state().outbox.values()] == ids


def test_prepared_intent_is_immutable_and_survives_reopen_and_command_replay(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    event = lua.globals().append('{"event":"tick"}')
    entry = command(1)
    assert accepted(lua.globals().accept(event, json.dumps([entry])))
    intent = '{"schema":"test-intent-v1","before":{"hp":20},"after":{"hp":0}}'
    assert accepted(lua.globals().prepare(entry["command_id"], intent))
    writes = lua.globals().writes
    assert accepted(lua.globals().prepare(entry["command_id"], intent))
    assert lua.globals().writes == writes
    assert not accepted(lua.globals().prepare(entry["command_id"], intent.replace('20', '19')))
    lua.globals().reopen()
    event = lua.globals().append('{"event":"tick"}')
    assert accepted(lua.globals().accept(event, json.dumps([entry])))
    prepared = lua.globals().journal.get_command(lua.globals().journal, entry["command_id"])
    assert prepared.intent.before.hp == 20 and prepared.intent.after.hp == 0
    prepared.intent.before.hp = 100
    assert lua.globals().state().inbox[1].intent.before.hp == 20


@pytest.mark.parametrize("intent", [{}, [], {"schema": ""}, {"schema": 1}, {"before": 20}])
def test_preparation_requires_versioned_policy_document(runtime, intent):  # noqa: F811
    lua = runtime
    start(lua)
    event = lua.globals().append('{"event":"tick"}')
    assert accepted(lua.globals().accept(event, json.dumps([command(1)])))
    before = lua.globals().disk
    assert not accepted(lua.globals().prepare(command(1)["command_id"], json.dumps(intent)))
    assert lua.globals().disk == before


def batch(lua, payloads, observation=None):
    values = lua.globals().JSON.decode(json.dumps(payloads))
    baseline = lua.globals().JSON.decode(json.dumps(observation)) if observation is not None else None
    return lua.globals().journal.append_many(lua.globals().journal, values, baseline)


def test_frame_observations_and_baseline_publish_once_and_survive_reopen(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    before = lua.globals().writes
    ids = batch(lua, [{"event": "capture", "key": "one"}, {"event": "faint", "key": "two"}],
                {"frame": 10, "party": ["one", "two"]})
    assert lua.globals().writes == before + 1
    assert len(set(ids.values())) == 2
    lua.globals().reopen()
    state = lua.globals().state()
    assert [entry.operation_id for entry in state.outbox.values()] == list(ids.values())
    assert [entry.payload.event for entry in state.outbox.values()] == ["capture", "faint"]
    assert state.observation.frame == 10
    assert list(state.observation.party.values()) == ["one", "two"]


@pytest.mark.parametrize("mode,published", [("before", False), ("after", True)])
def test_batch_publication_failure_never_leaves_a_partial_frame(runtime, mode, published):  # noqa: F811
    lua = runtime
    start(lua)
    assert batch(lua, [], {"frame": 1}) is not None
    lua.globals().mode = mode
    result = batch(lua, [{"event": "capture"}, {"event": "faint"}], {"frame": 2})
    assert accepted(result) is None
    writes = lua.globals().writes
    assert accepted(batch(lua, [{"event": "tick"}], {"frame": 3})) is None
    assert lua.globals().writes == writes, "uncertain store stays latched until reopen"
    lua.globals().mode = "ok"
    lua.globals().reopen()
    state = lua.globals().state()
    assert state.observation.frame == (2 if published else 1)
    assert len(state.outbox) == (2 if published else 0)
    if published:
        assert [entry.operation_id for entry in state.outbox.values()] == [f"{i:032x}" for i in (1, 2)]


def test_batch_exceeding_remaining_capacity_keeps_prior_outbox_and_baseline(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    lua.globals().Journal.MAX_EVENTS = 3
    assert accepted(batch(lua, [{"event": "capture"}, {"event": "faint"}], {"frame": 1})) is not None
    before, writes = lua.globals().disk, lua.globals().writes
    assert accepted(batch(lua, [{"event": "capture"}, {"event": "faint"}], {"frame": 2})) is None
    assert (lua.globals().disk, lua.globals().writes) == (before, writes)
    lua.globals().reopen()
    assert len(lua.globals().state().outbox) == 2
    assert lua.globals().state().observation.frame == 1


@pytest.mark.parametrize("generator", [
    "function() return string.rep('a',32) end",
    "function() next_id=next_id+1;if next_id==2 then return nil,'failed ID' end;return string.format('%032x',next_id) end",
    "function() next_id=next_id+1;if next_id==2 then error('ID source failed') end;return string.format('%032x',next_id) end",
])
def test_batch_identifier_failure_is_atomic(runtime, generator):  # noqa: F811
    lua = runtime
    start(lua)
    lua.globals().journal.new_id = lua.eval(generator)
    before, writes = lua.globals().disk, lua.globals().writes
    assert accepted(batch(lua, [{"event": "capture"}, {"event": "faint"}], {"frame": 9})) is None
    assert (lua.globals().disk, lua.globals().writes) == (before, writes)


@pytest.mark.parametrize("payloads,observation", [
    ({}, {"frame": 1}), ([], None), ([{"event": "capture"}, {"event": "hello"}], {"frame": 1}),
    ([{"event": "capture"}, {"event": "faint", "seq": 2}], {"frame": 1}),
    ([{"event": "capture"}, None], {"frame": 1}), ([{"event": "capture"}], []),
    ([{"event": "capture"}], False),
])
def test_invalid_frame_shapes_do_not_publish(runtime, payloads, observation):  # noqa: F811
    lua = runtime
    start(lua)
    before, writes = lua.globals().disk, lua.globals().writes
    assert accepted(batch(lua, payloads, observation)) is None
    assert (lua.globals().disk, lua.globals().writes) == (before, writes)


def test_deliberate_empty_batch_updates_only_the_baseline(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    first = lua.globals().append('{"event":"capture"}')
    ids = batch(lua, [], {"frame": 42})
    assert len(ids) == 0
    lua.globals().reopen()
    assert lua.globals().state().outbox[1].operation_id == first
    assert lua.globals().state().observation.frame == 42
    assert accepted(lua.globals().journal.append(lua.globals().journal, None, lua.eval("{}"))) is None


def test_batch_collision_with_existing_operation_preserves_the_entire_frame(runtime):  # noqa: F811
    lua = runtime
    start(lua)
    first = lua.globals().append('{"event":"capture"}')
    lua.globals().journal.new_id = lua.eval("function() return string.format('%032x',1) end")
    before, writes = lua.globals().disk, lua.globals().writes
    assert accepted(batch(lua, [{"event": "faint"}], {"frame": 2})) is None
    assert (lua.globals().disk, lua.globals().writes) == (before, writes)
    lua.globals().reopen()
    assert lua.globals().state().outbox[1].operation_id == first


@pytest.mark.parametrize("event", ["", "x" * 65])
def test_batch_rejects_event_names_the_shared_wire_would_refuse(runtime, event):  # noqa: F811
    lua = runtime
    start(lua)
    before, writes = lua.globals().disk, lua.globals().writes
    assert accepted(batch(lua, [{"event": "capture"}, {"event": event}], {"frame": 2})) is None
    assert (lua.globals().disk, lua.globals().writes) == (before, writes)
