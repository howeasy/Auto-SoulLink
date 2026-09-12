import copy
import secrets
import sqlite3
from itertools import product

import pytest

from server.gen1_bootstrap_receipt import DATA, SCHEMA, projection
from server.gen1_bootstrap_runtime import COMPONENT, record_key
from server.gen1_initial_observation import COMPONENT as INITIAL, blocker
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.protocol import ProtocolError, digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_sessions import contract

# Initial snapshots come from the shared synthetic empty-save fixture in
# test_gen1_initial_observation; the receipt below is derived from that fixture,
# never from independent constants.


def receipt(runtime, player, initial):
    variant = runtime.contract["players"][player]["variant"]
    profile = DATA["titles"][variant]
    value = {
        "schema": SCHEMA,
        "source_sha256": DATA["sha256"],
        "variant": variant,
        "context_generation": initial["context_generation"],
        "physical_instance": initial["host"]["owner_id"],
        "final_sha1": initial["final_sha1"],
    }
    for kind, frame in (("begin", initial["frame"] - 60), ("end", initial["frame"] - 10)):
        site = profile["sites"][kind]
        value[kind] = {"frame": frame, "pc": site["address"], "bank": site["bank"], "sp": 0xDFFE}
    value["end"]["point"] = projection(initial["source"])
    return value


def deliver(runtime, player, owner, payload, operation=None):
    session = runtime.gate.sessions[player]
    return runtime.process(
        {
            "protocol": runtime.protocol,
            "player": player,
            "session_id": session.session_id,
            "admission_epoch": runtime.gate.epoch,
            "seq": session.last_seq + 1,
            "event": "bootstrap_observation",
            "operation_id": operation or secrets.token_hex(16),
            "payload": payload,
        },
        owner,
    )


def enroll(runtime, player):
    owner = admit(runtime, player)
    initial = observation(runtime, player)
    send(runtime, player, owner, initial, secrets.token_hex(16))
    return owner, initial


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)))
def test_new_game_proof_is_atomic_replayable_and_grants_nothing(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        for player in ("a", "b"):
            owner, initial = enroll(runtime, player)
            payload = receipt(runtime, player, initial)
            operation = secrets.token_hex(16)
            first = deliver(runtime, player, owner, payload, operation)
            snapshot = runtime.journal.snapshot()
            replay = deliver(runtime, player, owner, payload, operation)
            # Replay returns the committed result; only the transport seq advances.
            assert {k: v for k, v in replay.items() if k not in ("seq", "commands")} == {
                k: v for k, v in first.items() if k not in ("seq", "commands")
            }
            assert [(c["command_id"], c["body"]) for c in replay["commands"]] == [(c["command_id"], c["body"]) for c in first["commands"]]
            assert runtime.journal.snapshot() == snapshot
            entry = runtime.state().document()["components"][COMPONENT][player]
            assert entry["operation_id"] == operation and entry["payload"] == payload
            assert entry["proof"]["entry_frame"] < entry["proof"]["return_frame"] <= initial["frame"]
            assert entry["proof"]["frame"] == initial["frame"]
            assert runtime.journal.record(COMPONENT, record_key(player)).value == entry
            committed = runtime.journal.event(
                player, operation, {"event": "bootstrap_observation", "payload": payload}
            ).result
            assert committed == {
                "ack": "ACK",
                "bootstrap_proof_digest": digest(entry["proof"]),
                "ordinary_execution": False,
            }
        state = runtime.state()
        document = state.document()
        # Initial-save obligations are queued; holds and gameplay remain untouched.
        for player in ("a", "b"):
            assert blocker(runtime.journal.run_id, player) in state.barrier.document()["blockers"]
        assert state.barrier.ticket() is None
        assert not document["identities"]["members"] and not document["rules"]["core"]["links"]
        assert not any(document["rules"]["runtime"]["party_keys"].values())
        for player in ("a", "b"):
            pending = runtime.journal.pending_ids(player)
            assert len(pending) == 1
            assert runtime.journal.command(player, pending[0])["body"]["cmd"] == "initial_save"
        saved = document["components"][COMPONENT]
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        assert reopened.state().document()["components"][COMPONENT] == saved
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "fault",
    [
        "context",
        "owner",
        "rom",
        "source_pin",
        "future_frame",
        "debug_entry",
        "later_history",
        "identity",
        "extra_field",
        "missing_entry",
        "no_initial",
        "unselected",
    ],
)
def test_hostile_binding_replay_or_history_commits_nothing(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        if fault == "no_initial":
            owner = admit(runtime, "a")
            initial = observation(runtime, "a")
        else:
            owner, initial = enroll(runtime, "a")
        payload = receipt(runtime, "a", initial)
        if fault == "context":
            payload["context_generation"] = "f" * 32
        elif fault == "owner":
            payload["physical_instance"] = "f" * 32
        elif fault == "rom":
            payload["final_sha1"] = "f" * 40
        elif fault == "source_pin":
            payload["source_sha256"] = "f" * 64
        elif fault == "future_frame":
            payload["end"]["frame"] = initial["frame"] + 1
        elif fault == "debug_entry":
            payload["begin"]["pc"] += 5
        elif fault == "later_history":
            payload["end"]["point"]["party"] = "01" + payload["end"]["point"]["party"][2:]
        elif fault == "identity":
            payload["end"]["point"]["player_id"] = "FFFF"
        elif fault == "extra_field":
            payload["grant"] = "ordinary"
        elif fault == "missing_entry":
            del payload["begin"]
        elif fault == "unselected":
            runtime.initial_observations = False
        before = runtime.journal.snapshot()
        with pytest.raises((JournalError, ProtocolError)):
            deliver(runtime, "a", owner, payload)
        assert runtime.journal.snapshot() == before
        assert runtime.journal.record(COMPONENT, record_key("a")) is None
        assert COMPONENT not in runtime.journal.snapshot().state["components"]
    finally:
        runtime.close()


def test_second_proof_cannot_replace_the_first(tmp_path):
    runtime = create_runtime(tmp_path, contract("blue", "yellow"))
    try:
        owner, initial = enroll(runtime, "a")
        payload = receipt(runtime, "a", initial)
        deliver(runtime, "a", owner, payload)
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError, match="immutable"):
            deliver(runtime, "a", owner, payload)  # Same evidence, new operation.
        later = copy.deepcopy(payload)
        later["begin"]["frame"] += 1
        later["end"]["frame"] += 1
        with pytest.raises(JournalError, match="immutable"):
            deliver(runtime, "a", owner, later)  # Different valid evidence.
        assert runtime.journal.snapshot() == before
        assert len(runtime.journal.record_history(COMPONENT, record_key("a"))) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["proof", "payload", "operation", "fields", "orphan", "player"])
def test_stopped_state_restore_revalidates_the_proof(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("red", "red"))
    try:
        owner, initial = enroll(runtime, "a")
        deliver(runtime, "a", owner, receipt(runtime, "a", initial))
        state = runtime.state().document()
        entry = state["components"][COMPONENT]["a"]
        if fault == "proof":
            entry["proof"]["return_frame"] -= 1
        elif fault == "payload":
            entry["payload"]["end"]["sp"] -= 2
        elif fault == "operation":
            entry["operation_id"] = "not-hex"
        elif fault == "fields":
            entry["granted_frames"] = 1
        elif fault == "orphan":
            del state["components"][INITIAL]
        else:
            state["components"][COMPONENT]["c"] = entry
        with pytest.raises(JournalError):
            Gen1RuntimeState.restore(state, data_dir=tmp_path)
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["removed", "replaced"])
def test_missing_or_foreign_atomic_record_refuses_continuation(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owner, initial = enroll(runtime, "a")
        deliver(runtime, "a", owner, receipt(runtime, "a", initial))
        if fault == "removed":
            runtime.journal._db.execute("DELETE FROM records WHERE namespace=?", (COMPONENT,))
        else:
            runtime.journal._db.execute(
                "UPDATE records SET record_key=? WHERE namespace=?", (record_key("b"), COMPONENT)
            )
        with pytest.raises(JournalError):
            runtime.state()
    finally:
        runtime.close()


def test_sql_failure_rolls_back_and_reopen_restores_the_enrollment_exactly(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = {}
        initials = {}
        for player in ("a", "b"):
            owners[player], initials[player] = enroll(runtime, player)
        payload = receipt(runtime, "a", initials["a"])
        operation = secrets.token_hex(16)
        before = runtime.journal.snapshot()
        runtime.journal._db.execute(
            "CREATE TRIGGER fail_bootstrap BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT, 'fixture'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            deliver(runtime, "a", owners["a"], payload, operation)
        assert runtime.journal.snapshot() == before
        assert runtime.journal.record(COMPONENT, record_key("a")) is None
        assert COMPONENT not in before.state["components"]
        runtime.journal._db.execute("DROP TRIGGER fail_bootstrap")
        assert runtime._failed and not runtime.gate.sessions
        runtime.close()
        runtime = open_runtime(tmp_path)
        state = runtime.state()
        document = state.document()
        # Nothing of the failed commit survives the restart; enrollment does.
        assert COMPONENT not in document["components"]
        assert set(document["components"][INITIAL]) == {"a", "b"}
        for player in ("a", "b"):
            assert blocker(runtime.journal.run_id, player) in state.barrier.document()["blockers"]
        # A new transport binding can deliver immutable historical evidence when
        # the same physical/context/cartridge/save identity is re-admitted.
        owner = admit(runtime, "a")
        deliver(runtime, "a", owner, payload, operation)
        assert runtime.journal.record(COMPONENT, record_key("a")) is not None
        assert runtime.state().barrier.ticket() is None
    finally:
        runtime.close()


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_same_core_transport_reconnect_can_deliver_original_bootstrap(tmp_path, variant):
    runtime = create_runtime(tmp_path, contract(variant, variant))
    try:
        owner, initial = enroll(runtime, 'a')
        payload = receipt(runtime, 'a', initial)
        old = copy.deepcopy(runtime.gate.sessions['a'].metadata)
        runtime.disconnect('a', owner)
        owner = admit(runtime, 'a')
        assert runtime.gate.sessions['a'].metadata['control_binding'] != old['control_binding']
        deliver(runtime, 'a', owner, payload)
        assert runtime.state().document()['components'][COMPONENT]['a']['payload'] == payload
        assert runtime.state().barrier.ticket() is None
    finally:
        runtime.close()
