"""Same-BizHawk-process idle recovery for the Gen 1 free service."""

import copy
import secrets

import pytest

from server.gen1_initial_observation import COMPONENT as INITIAL
from server.gen1_inventory_observation import COMPONENT as INVENTORY
from server.gen1_observation_runtime import COMPONENT as PROGRESS
from server.gen1_run_config import create_runtime, open_runtime
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_observation_runtime import batch, checkpoint, deliver
from tests.unit.test_gen1_sessions import contract


def enroll_progress(runtime):
    owners = {}
    for player in ("a", "b"):
        owners[player] = admit(runtime, player)
        initial = observation(runtime, player)
        send(runtime, player, owners[player], initial)
        deliver(
            runtime,
            player,
            owners[player],
            batch(runtime, player, 1, frame=130, inventory=checkpoint(initial, 130)),
        )
    assert not any(runtime.journal.pending_ids(player) for player in ("a", "b"))
    runtime._service_release_ready = lambda stage: True
    return owners


def control(runtime, owners, player, continuity=None):
    session = runtime.gate.sessions[player]
    binding = session.metadata["control_binding"]
    challenge = secrets.token_hex(16)
    message = {
        "protocol": runtime.protocol,
        "player": player,
        "event": "control",
        "session_id": session.session_id,
        "admission_epoch": runtime.gate.epoch,
        "seq": session.last_seq + 1,
        "operation_id": challenge,
        "control": {**binding, "challenge": challenge},
    }
    if continuity is not None:
        message["service_continuity"] = continuity
    return runtime.process(message, owners[player])


def proof(runtime, player):
    document = runtime.state().document()
    initial = document["components"][INITIAL][player]
    progress = document["components"].get(PROGRESS, {}).get(player)
    latest_entry = document["components"].get(INVENTORY, {}).get(player)
    latest = latest_entry["observation"] if latest_entry else initial["observation"]
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    return {
        "schema": "rby-free-service-continuity-v1",
        "service_epoch": runtime.status()["service"]["epoch"],
        "binding_digest": binding["binding_digest"],
        "initial_operation_id": initial["operation_id"],
        "cursor": copy.deepcopy(progress or {
            "sequence": 0,
            "operation_id": initial["operation_id"],
            "frame": initial["observation"]["frame"],
        }),
        "inventory": copy.deepcopy(latest),
        "idle": {
            "pending_events": 0,
            "pending_commands": 0,
            "acquisition_open": False,
            "acquisition_pending": 0,
            "engine_pending": 0,
            "instruction_open": False,
            "instruction_armed": False,
            "battle": 0,
            "source_frame": latest["frame"],
        },
    }


def reconnect(runtime):
    owners = {player: admit(runtime, player) for player in ("a", "b")}
    runtime._service_release_ready = lambda stage: True
    return owners


def test_clean_connector_reconnect_requires_both_current_proofs_and_duplicates_nothing(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "yellow"), free_service=True)
    try:
        owners = enroll_progress(runtime)
        control(runtime, owners, "a")
        granted = control(runtime, owners, "b")["control"]
        assert granted["authority"] == "service"
        before = runtime.journal.snapshot()

        assert runtime.disconnect("a", owners["a"])
        owners = reconnect(runtime)
        after_reconnect = runtime.journal.snapshot()
        first = control(runtime, owners, "a", proof(runtime, "a"))
        assert first["control"]["authority"] == "hold"
        assert first["service_recovery"]["proofs"] == {"a": True, "b": False}
        second = control(runtime, owners, "b", proof(runtime, "b"))
        assert second["control"]["authority"] == "service"
        assert second["service_recovery"] == {
            "schema": "slink-service-recovery-v1",
            "required": False,
            "service_epoch": second["control"]["service_epoch"],
            "paired_admission": True,
            "proofs": {"a": True, "b": True},
            "refusals": {"a": None, "b": None},
        }
        assert control(runtime, owners, "a")["control"]["authority"] == "service"
        assert runtime.journal.snapshot() == after_reconnect
        assert runtime.journal.snapshot().state["components"][PROGRESS] == before.state["components"][PROGRESS]
        assert not any(runtime.journal.pending_ids(player) for player in ("a", "b"))
    finally:
        runtime.close()


def test_actual_server_object_reopen_accepts_only_fresh_paired_continuity(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "blue"), free_service=True)
    owners = enroll_progress(runtime)
    control(runtime, owners, "a")
    control(runtime, owners, "b")
    old_epoch = runtime.status()["service"]["epoch"]
    runtime.close()

    reopened = open_runtime(tmp_path)
    try:
        assert reopened.status()["service"]["epoch"] != old_epoch
        owners = reconnect(reopened)
        before = reopened.journal.snapshot()
        assert control(reopened, owners, "a", proof(reopened, "a"))["control"]["authority"] == "hold"
        assert control(reopened, owners, "b", proof(reopened, "b"))["control"]["authority"] == "service"
        assert reopened.journal.snapshot() == before
    finally:
        reopened.close()


def test_later_frame_volatile_main_bytes_do_not_replace_inventory_semantics(tmp_path):
    from server.gen1_full_save import SYMBOLS

    runtime = create_runtime(tmp_path, contract("yellow", "red"), free_service=True)
    try:
        owners = enroll_progress(runtime)
        runtime.disconnect("a", owners["a"])
        owners = reconnect(runtime)
        value = proof(runtime, "a")
        value["inventory"]["frame"] = 145
        value["idle"]["source_frame"] = 145
        value["inventory"]["source"]["save_status"] = 1  # Deliberately transient, not inventory identity.
        main = bytearray.fromhex(value["inventory"]["source"]["fields"]["main"])
        symbols = SYMBOLS["pokeyellow"]
        playtime = symbols["wPlayTimeFrames"] - symbols["wMainDataStart"]
        main[playtime] = (main[playtime] + 1) % 60
        value["inventory"]["source"]["fields"]["main"] = main.hex().upper()
        first = control(runtime, owners, "a", value)
        assert first["control"]["authority"] == "hold"
        assert first["service_recovery"]["proofs"] == {"a": True, "b": False}
        assert first["service_recovery"]["refusals"]["a"] is None
        assert control(runtime, owners, "b", proof(runtime, "b"))["control"]["authority"] == "service"
    finally:
        runtime.close()


def test_idle_reconnect_can_use_exact_deferred_inventory_then_retry_after_release(tmp_path):
    from server.gen1_full_save import SYMBOLS

    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owners = enroll_progress(runtime)
        recorded = proof(runtime, "a")["inventory"]
        deferred = checkpoint(recorded, 160)
        main = bytearray.fromhex(deferred["source"]["fields"]["main"])
        symbols = SYMBOLS["pokeyellow"]
        selector = symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]
        main[selector] = 1 if main[selector] != 1 else 2
        deferred["source"]["fields"]["main"] = main.hex().upper()
        stage = runtime.state()
        [obligation] = runtime.journal.commit("a", secrets.token_hex(16), {"event": "fixture_obligation"},
            expected_revision=stage.journal_revision, state=stage.document(),
            commands={"a": [], "b": [{"cmd": "fixture_pending"}]}, result={"ack": "ACK"}).command_ids
        response = deliver(runtime, "a", owners["a"], batch(runtime, "a", 2, frame=160, inventory=deferred))
        assert response["observation_result"]["inventory_status"] == "deferred"
        assert runtime.state().document()["components"][INVENTORY]["a"]["observation"] == recorded
        stage = runtime.state()
        runtime.journal.commit("b", secrets.token_hex(16), {"event": "fixture_obligation_settled"},
            expected_revision=stage.journal_revision, state=stage.document(),
            commands={"a": [], "b": []}, result={"ack": "ACK"},
            acknowledgements=[{"player": "b", "command_id": obligation,
                "outcome": "ACK", "receipt": {"schema": "fixture-receipt-v1"}}])
        operation = response["operation_id"]
        runtime.disconnect("a", owners["a"])
        owners = reconnect(runtime)
        value = proof(runtime, "a")
        value["inventory"] = deferred
        value["idle"]["source_frame"] = 160
        value["pending_inventory_retry"] = {"operation_id": operation, "sequence": 2, "frame": 160}
        first = control(runtime, owners, "a", value)
        assert first["service_recovery"]["proofs"] == {"a": True, "b": False}
        assert control(runtime, owners, "b", proof(runtime, "b"))["control"]["authority"] == "service"
        # The deferred point was not adopted as inventory by continuity. Only
        # a fresh post-release observation may do that.
        assert runtime.state().document()["components"][INVENTORY]["a"]["observation"] == recorded
        accepted = deliver(runtime, "a", owners["a"], batch(runtime, "a", 3, frame=190,
                           inventory=checkpoint(deferred, 190)))
        assert accepted["observation_result"]["inventory_status"] == "recorded"
        assert runtime.state().document()["components"][INVENTORY]["a"]["observation"]["frame"] == 190
    finally:
        runtime.close()


def test_disconnect_after_saves_before_first_observation_uses_initial_cursor(tmp_path):
    from tests.unit.test_gen1_initial_save_runtime import complete_initial_save, setup

    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    try:
        owners = setup(runtime)
        for player in ("a", "b"):
            complete_initial_save(runtime, player, owners[player])
        assert PROGRESS not in runtime.state().document()["components"]
        control(runtime, owners, "a")
        assert control(runtime, owners, "b")["control"]["authority"] == "service"
        runtime.disconnect("a", owners["a"])
        owners = reconnect(runtime)
        for player in ("a", "b"):
            value = proof(runtime, player)
            initial = runtime.state().document()["components"][INITIAL][player]
            assert value["cursor"] == {
                "sequence": 0,
                "operation_id": initial["operation_id"],
                "frame": initial["observation"]["frame"],
            }
            response = control(runtime, owners, player, value)
        assert response["control"]["authority"] == "service"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("epoch", "stale service epoch"),
        ("binding", "current admission"),
        ("cursor", "last committed observation"),
        ("initial", "initial identity"),
        ("member", "last committed checkpoint"),
        ("box", "last committed checkpoint"),
        ("process", "host or frame changed"),
        ("backwards", "host or frame changed"),
        ("open", "idle held client"),
    ],
)
def test_stale_changed_or_nonidle_proof_remains_held(tmp_path, fault, message):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"), free_service=True)
    try:
        owners = enroll_progress(runtime)
        runtime.disconnect("a", owners["a"])
        owners = reconnect(runtime)
        value = proof(runtime, "a")
        peer_notices = []

        class PeerWriter:
            def write(self, payload):
                peer_notices.append(payload)

        runtime._writers["b"] = (owners["b"], PeerWriter())
        if fault == "epoch":
            value["service_epoch"] = "f" * 32
        elif fault == "binding":
            value["binding_digest"] = "f" * 64
        elif fault == "cursor":
            value["cursor"]["sequence"] += 1
        elif fault == "initial":
            value["initial_operation_id"] = "f" * 32
        elif fault == "member":
            from tests.unit.test_gen1_initial_observation import source

            value["inventory"]["source"] = source("yellow", occupied=True)
        elif fault == "box":
            from server.gen1_full_save import SYMBOLS

            main = bytearray.fromhex(value["inventory"]["source"]["fields"]["main"])
            offset = SYMBOLS["pokeyellow"]["wCurrentBoxNum"] - SYMBOLS["pokeyellow"]["wMainDataStart"]
            main[offset] = 1
            value["inventory"]["source"]["fields"]["main"] = main.hex().upper()
        elif fault == "process":
            value["inventory"]["host"]["process_id"] += 1
        elif fault == "backwards":
            value["inventory"]["frame"] = 129
            value["idle"]["source_frame"] = 129
        else:
            value["idle"]["engine_pending"] = 1
        epoch = runtime.status()["service"]["epoch"]
        response = control(runtime, owners, "a", value)
        assert response["control"]["authority"] == "hold"
        assert message in response["control"]["reason"]
        status = runtime.status()["service"]
        assert status["epoch"] == epoch
        assert status["recovery_required"] is True and status["current"] is False
        assert status["continuity"] == {"a": False, "b": False}
        assert message in status["continuity_refusals"]["a"]
        assert set(runtime.gate.sessions) == {"a", "b"}
        assert peer_notices == []
        again = control(runtime, owners, "a")
        assert again["control"]["authority"] == "hold"
        assert again["service_recovery"]["refusals"]["a"] == status["continuity_refusals"]["a"]
        assert runtime.status()["service"]["epoch"] == epoch and peer_notices == []
    finally:
        runtime._writers.clear()
        runtime.close()


def test_one_sided_and_pre_restart_proofs_never_cross_service_epochs(tmp_path):
    runtime = create_runtime(tmp_path, contract("blue", "red"), free_service=True)
    owners = enroll_progress(runtime)
    runtime.disconnect("a", owners["a"])
    owners = reconnect(runtime)
    stale_peer = proof(runtime, "b")
    assert control(runtime, owners, "a", proof(runtime, "a"))["control"]["authority"] == "hold"
    runtime.close()

    reopened = open_runtime(tmp_path)
    try:
        owners = reconnect(reopened)
        epoch = reopened.status()["service"]["epoch"]
        response = control(reopened, owners, "b", stale_peer)
        assert response["control"]["authority"] == "hold"
        assert "stale service epoch" in response["control"]["reason"]
        assert reopened.status()["service"]["epoch"] == epoch
        assert reopened.status()["service"]["continuity"] == {"a": False, "b": False}
        assert reopened.status()["service"]["recovery_required"] is True
    finally:
        reopened.close()


def test_missing_peer_or_server_command_obligation_remains_held(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"), free_service=True)
    try:
        owners = enroll_progress(runtime)
        runtime.disconnect("a", owners["a"])
        owner_a = admit(runtime, "a")
        owners = {"a": owner_a}
        waiting = control(runtime, owners, "a")
        assert waiting["control"]["authority"] == "hold"
        assert waiting["service_recovery"]["paired_admission"] is False
        response = control(runtime, owners, "a", proof(runtime, "a"))
        assert response["control"]["authority"] == "hold"
        assert "paired admission" in response["control"]["reason"]
        assert runtime.status()["service"]["recovery_required"] is True

        owner_b = admit(runtime, "b")
        owners["b"] = owner_b
        snapshot = runtime.journal.snapshot()
        runtime.journal.commit(
            "a",
            secrets.token_hex(16),
            {"event": "continuity-obligation-fixture"},
            expected_revision=snapshot.revision,
            state=snapshot.state,
            commands={"a": [], "b": [{"cmd": "fixture_pending"}]},
            result={"ack": "ACK"},
        )
        response = control(runtime, owners, "a", proof(runtime, "a"))
        assert response["control"]["authority"] == "hold"
        assert "durable commands" in response["control"]["reason"]
        assert runtime.status()["service"]["recovery_required"] is True
    finally:
        runtime.close()


def test_held_no_write_command_can_settle_then_same_epoch_proofs_restore_service(tmp_path):
    runtime = create_runtime(tmp_path, contract("blue", "yellow"), free_service=True)
    try:
        owners = enroll_progress(runtime)
        runtime.disconnect("a", owners["a"])
        owners = reconnect(runtime)
        original_owners = dict(owners)
        snapshot = runtime.journal.snapshot()
        runtime.journal.commit(
            "a",
            secrets.token_hex(16),
            {"event": "held-no-write-fixture"},
            expected_revision=snapshot.revision,
            state=snapshot.state,
            commands={"a": [], "b": [{"cmd": "fixture_no_write"}]},
            result={"ack": "ACK"},
        )
        command = runtime.journal.pending("b")[0]
        epoch = runtime.status()["service"]["epoch"]
        refused = control(runtime, owners, "a", proof(runtime, "a"))
        assert refused["control"]["authority"] == "hold"
        assert "durable commands" in refused["service_recovery"]["refusals"]["a"]
        assert set(runtime.gate.sessions) == {"a", "b"}

        assert runtime.journal.acknowledge(
            "b", command["command_id"], "ACK", {"schema": "fixture-no-write-receipt-v1"}
        )
        assert not any(runtime.journal.pending_ids(player) for player in ("a", "b"))
        first = control(runtime, owners, "a", proof(runtime, "a"))
        assert first["control"]["authority"] == "hold"
        assert first["service_recovery"]["refusals"]["a"] is None
        final = control(runtime, owners, "b", proof(runtime, "b"))
        assert final["control"]["authority"] == "service"
        assert final["control"]["service_epoch"] == epoch
        assert runtime.status()["service"]["recovery_required"] is False
        assert all(runtime.gate.owns(player, original_owners[player]) for player in ("a", "b"))
    finally:
        runtime.close()
