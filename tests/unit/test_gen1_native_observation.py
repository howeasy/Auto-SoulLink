"""Actual journal checkpoint provenance; modeled cartridge observations.

The native checkpoint reaches the server inside a native frame handoff (the one compound event
left). The loan itself is driven with the native accounting helpers.
"""

import copy
import secrets

import pytest

from server.gen1_initial_observation import inventory
from server.gen1_native_observation import (
    COMPONENT,
    candidate_checkpoints,
    checkpoints,
    key,
    stage,
    verify_journal,
)
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol_journal import JournalError
from tests.unit.observation_fixture import ledger, starters
from tests.unit.test_gen1_native_frame_accounting import (
    compose,
    grant,
    handoff,
    queue,
    returned,
    terminal,
)
from tests.unit.test_gen1_sessions import contract


def handoff_message(value, player):
    """A native handoff carrying the latest checkpoint one frame on, as the native client returns it."""
    state = value.state().document()
    initial = state["components"]["gen1-initial-observations"][player]
    observation = copy.deepcopy(state["components"]["gen1-inventory-observations"][player]["observation"])
    observation["frame"] += 1
    source = observation["source"]
    raw = bytes.fromhex(source["fields"]["party"])
    members = inventory(source, initial["metadata"]["save_identity"])["members"]
    party = [member["blob_hex"] for member in members if member["location"] == "party"]
    save = initial["metadata"]["save_identity"]
    readback = {
        "schema": "gen1-party-readback-v1",
        "variant": source["variant"],
        "save_id": save["ot_id"],
        "save_name": save["trainer_name"],
        "party_count": len(party),
        "party": party,
        "species_list": list(raw[1 : 2 + len(party)]),
        "battle_flag": 0,
        "active_slot": None,
        "battle_hp": None,
    }
    return {"event": "native_frame_handoff", "payload": {
        "schema": "rby-native-frame-return-v1", "inventory": observation,
        "host": {**observation["host"], "frame": observation["frame"]},
        "native_checkpoint": {"party": readback}}}


@pytest.mark.parametrize("mutation", [None, "identity", "owner", "battle", "party", "missing_inventory"])
def test_handoff_checkpoint_stages_detached_and_refuses_bad_evidence(tmp_path, mutation):
    value = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(value)
        message = handoff_message(value, "a")
        party = message["payload"]["native_checkpoint"]["party"]
        if mutation == "identity":
            party["save_id"] = "FFFF"
        elif mutation == "owner":
            message["payload"]["inventory"]["host"]["process_id"] += 1
        elif mutation == "battle":
            party.update(battle_flag=1, active_slot=0, battle_hp=10)
        elif mutation == "party":
            party["party"][0] = "00" * 66
        elif mutation == "missing_inventory":
            message["payload"]["inventory"] = None
        document = value.state().document()
        before = value.journal.snapshot()
        if mutation is None:
            staged = stage(document, "a", secrets.token_hex(16), message)
            assert staged["entry"]["frame"] == message["payload"]["inventory"]["frame"]
            assert staged["entry"]["party"] == party and staged["record"]["key"] == key("a")
            assert document["components"][COMPONENT]["a"] == staged["entry"]
        else:
            with pytest.raises(JournalError):
                stage(document, "a", secrets.token_hex(16), message)
            assert COMPONENT not in document["components"]
        assert value.journal.snapshot() == before and value.journal.record(COMPONENT, key("a")) is None
    finally:
        value.close()


def test_paired_checkpoints_follow_both_handed_back_loans_and_reopen(tmp_path):
    value = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(value)
        ledger(value)
        compose(value, tmp_path)
        with pytest.raises(JournalError, match="both native"):
            checkpoints(value)
        for player in ("a", "b"):
            command = queue(value, player)
            grant(value, command, 110, player)
            message = terminal(value, command, 120, player)
            returned(value, player, secrets.token_hex(16), message)
            with pytest.raises(JournalError, match="both native"):
                checkpoints(value)
            handoff(value, player, secrets.token_hex(16), {"event": "native_frame_handoff", "payload": message["payload"]})
            entry = value.state().document()["components"][COMPONENT][player]
            assert entry["frame"] == 120 and value.journal.record(COMPONENT, key(player)).value == entry
        checked = checkpoints(value)
        checked["a"]["map"] ^= 1
        assert checkpoints(value)["a"]["map"] != checked["a"]["map"]  # detached copies
        assert set(candidate_checkpoints(value, "b")) == {"a", "b"}
        verify_journal(value.journal, value.state())
        saved = value.state().document()["components"][COMPONENT]
    finally:
        value.close()
    reopened = open_runtime(tmp_path)
    try:
        assert reopened.state().document()["components"][COMPONENT] == saved
        assert set(checkpoints(reopened)) == {"a", "b"}
    finally:
        reopened.close()


# ── the free-run bridge: the checkpoint rides the heartbeat inventory, no ledger ─────────

def free_readback(runtime, player, point):
    """The party readback a native client reads in the same held frame as its heartbeat inventory."""
    state = runtime.state().document()
    initial = state["components"]["gen1-initial-observations"][player]
    source = point["source"]
    raw = bytes.fromhex(source["fields"]["party"])
    members = inventory(source, initial["metadata"]["save_identity"])["members"]
    party = [member["blob_hex"] for member in members if member["location"] == "party"]
    save = initial["metadata"]["save_identity"]
    return {"schema": "rby-native-observation-v1", "party": {
        "schema": "gen1-party-readback-v1", "variant": source["variant"], "save_id": save["ot_id"],
        "save_name": save["trainer_name"], "party_count": len(party), "party": party,
        "species_list": list(raw[1 : 2 + len(party)]), "battle_flag": 0, "active_slot": None, "battle_hp": None}}


def test_free_batches_anchor_the_checkpoint_to_their_heartbeat_inventory_and_reopen(tmp_path):
    from server.gen1_observation_runtime import verify_journal as verify_batches
    from tests.unit.test_gen1_observation_runtime import (
        batch,
        checkpoint,
        deliver,
        enrolled,
        publish,
    )

    value = create_runtime(tmp_path, contract("yellow", "red"), free_service=True)
    try:
        owners, points = {}, {}
        for player in ("a", "b"):
            owner, initial, _first = enrolled(value, player, occupied=True)
            owners[player], points[player] = owner, checkpoint(initial, 130)
        with pytest.raises(JournalError, match="both native"):
            checkpoints(value)
        for player in ("a", "b"):
            point = points[player]
            request = {**batch(value, player, 1, frame=130, inventory=point), "native_checkpoint": free_readback(value, player, point)}
            _operation, result = publish(value, player, owners[player], request)
            entry = value.state().document()["components"][COMPONENT][player]
            assert entry["frame"] == 130 and entry["anchor"] == {"inventory_sequence": 1}
            assert result["native_checkpoint_digest"] == digest_of(entry)
            assert value.journal.record(COMPONENT, key(player)).value == entry
        checked = checkpoints(value)
        assert set(checked) == {"a", "b"} and checked["a"]["party"] == free_readback(value, "a", points["a"])["party"]
        assert set(candidate_checkpoints(value, "b")) == {"a", "b"}
        state = value.state()
        verify_journal(value.journal, state)
        verify_batches(value.journal, state)
        # A later heartbeat without a checkpoint supersedes the old one: stale, refused.
        deliver(value, "a", owners["a"], batch(value, "a", 2, frame=160, inventory=checkpoint(points["a"], 160)))
        with pytest.raises(JournalError, match="stale"):
            checkpoints(value)
        with pytest.raises(JournalError, match="stale"):
            candidate_checkpoints(value, "a")
        assert set(candidate_checkpoints(value, "b")) == {"a", "b"}  # the peer's is still current
        # The next heartbeat that carries the checkpoint makes it current again.
        point = checkpoint(points["a"], 190)
        publish(value, "a", owners["a"], {**batch(value, "a", 3, frame=190, inventory=point), "native_checkpoint": free_readback(value, "a", point)})
        assert value.state().document()["components"][COMPONENT]["a"]["anchor"] == {"inventory_sequence": 3}
        assert set(checkpoints(value)) == {"a", "b"}
        verify_journal(value.journal, value.state())
        saved = value.state().document()["components"][COMPONENT]
    finally:
        value.close()
    reopened = open_runtime(tmp_path)
    try:
        assert reopened.state().document()["components"][COMPONENT] == saved
        assert set(checkpoints(reopened)) == {"a", "b"}
        verify_journal(reopened.journal, reopened.state())
    finally:
        reopened.close()


@pytest.mark.parametrize("fault", ["no_inventory", "bad_schema", "identity", "battle"])
def test_free_checkpoint_faults_commit_nothing(tmp_path, fault):
    from tests.unit.test_gen1_observation_runtime import batch, checkpoint, deliver, enrolled

    value = create_runtime(tmp_path, contract("blue", "blue"), free_service=True)
    try:
        owner, initial, _first = enrolled(value, "a", occupied=True)
        point = checkpoint(initial, 130)
        native = free_readback(value, "a", point)
        request = {**batch(value, "a", 1, frame=130, inventory=point), "native_checkpoint": native}
        if fault == "no_inventory":
            request["inventory"] = None
        elif fault == "bad_schema":
            native["schema"] = "rby-native-observation-v0"
        elif fault == "identity":
            native["party"]["save_id"] = "FFFF"
        elif fault == "battle":
            native["party"].update(battle_flag=1, active_slot=0, battle_hp=10)
        before = value.journal.snapshot()
        with pytest.raises(JournalError):
            deliver(value, "a", owner, request)
        assert value.journal.snapshot() == before
        assert COMPONENT not in value.state().document()["components"]
    finally:
        value.close()


def test_free_checkpoint_is_deferred_with_its_heartbeat_behind_an_open_obligation(tmp_path):
    from tests.unit.test_gen1_engine_signal_runtime import deliver as deliver_signals
    from tests.unit.test_gen1_faint_runtime import enroll, signal_batch, source_and_checkpoint
    from tests.unit.test_gen1_inventory_observation import deliver as deliver_inventory
    from tests.unit.test_gen1_observation_runtime import batch, checkpoint, deliver, publish

    value = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        instant = value.clock()
        value.clock = lambda: instant
        owners, initials, operations = enroll(value)
        points = {}
        for player in ("a", "b"):
            source, stable = source_and_checkpoint(value, player, initials[player], operations[player])
            deliver_signals(value, player, owners[player], source)
            deliver_inventory(value, player, owners[player], stable)
            points[player] = stable["observation"]
        deliver(value, "a", owners["a"], batch(value, "a", 1, frame=121, signals=signal_batch(value, "a")))
        assert value.journal.pending_ids("b")  # the partner owes a physical faint
        point = checkpoint(points["a"], 160)
        _operation, result = publish(value, "a", owners["a"], {**batch(value, "a", 2, frame=160, inventory=point),
                                                              "native_checkpoint": free_readback(value, "a", point)})
        assert result["inventory_deferred"] is True and result["native_checkpoint_deferred"] is True
        assert COMPONENT not in value.state().document()["components"]
    finally:
        value.close()


def digest_of(entry):
    from server.protocol import digest

    return digest(entry)
