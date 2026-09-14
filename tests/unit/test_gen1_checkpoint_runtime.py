"""Server capture half of R5b-1: start -> save_upload x2 -> finalize_checkpoint, plus the
cross-store reconciliation on reopen. Real journal commits throughout, no emulator."""
import hashlib
import secrets

import pytest

from server import gen1_checkpoint_runtime, paired_save_checkpoints
from server.gen1_checkpoint_runtime import COMPONENT, reconcile_on_open, record, start
from server.gen1_run_config import create_runtime, open_runtime
from server.paired_save_checkpoints import CheckpointError, PairedCheckpointStore
from server.protocol_journal import JournalError
from tests.unit.test_gen1_engine_signal_runtime import deliver, payload
from tests.unit.test_gen1_engine_signals import witness as save_witness_signal
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_sessions import contract

CART_HEX = "FF" * 0x8000


def _save_digest(cart_hex):
    return hashlib.sha256(cart_hex[0x498 * 2:].encode("ascii")).hexdigest()


def _pin_witness(runtime, player, owner, *, frame=200, sequence=1, cart_hex=CART_HEX):
    value = payload(runtime, player, [], sequence)
    value["signals"] = [save_witness_signal(value["variant"], digest=_save_digest(cart_hex))]
    value["signals"][0]["frame"] = frame
    return deliver(runtime, player, owner, value)


def _enroll_and_witness(runtime):
    owners = {}
    for player in ("a", "b"):
        owners[player] = admit(runtime, player)
        send(runtime, player, owners[player], observation(runtime, player))
        _pin_witness(runtime, player, owners[player])
    return owners


def _receipt(runtime, player, request_id, witness, *, cart_hex=CART_HEX, frame=200, **overrides):
    receipt = {"request_id": request_id, "witness": witness, "frame": frame,
        "context_generation": player * 32, "physical_instance": ("1" if player == "a" else "2") * 32,
        "final_sha1": runtime.contract["players"][player]["final_rom_sha1"], "cart_hex": cart_hex}
    receipt.update(overrides)
    return receipt


def _upload(runtime, player, owner, request_id, witness, *, operation=None, command_id=None, **receipt_overrides):
    # A retry/duplicate-attempt test passes the ORIGINAL command_id explicitly: once a player's
    # checkpoint_upload is ACKed it leaves pending_ids(), so a second lookup would find nothing.
    if command_id is None:
        command_id = runtime.journal.pending_ids(player)[0]
    command = runtime.journal.command(player, command_id)
    receipt = _receipt(runtime, player, request_id, witness, **receipt_overrides)
    message = {"event": "save_upload", "command_id": command_id, "command_sequence": command["command_sequence"],
        "receipt": receipt}
    session = runtime.gate.sessions[player]
    return runtime.process({**message, "protocol": runtime.protocol, "player": player,
        "session_id": session.session_id, "admission_epoch": runtime.gate.epoch, "seq": session.last_seq + 1,
        "operation_id": operation or secrets.token_hex(16)}, owner)


def _component(runtime):
    return runtime.state().document()["components"].get(COMPONENT)


@pytest.fixture
def paired(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        owners = _enroll_and_witness(runtime)
        yield runtime, owners
    finally:
        runtime.close()


# -- start refusals -----------------------------------------------------------

def test_start_refuses_when_a_witness_is_missing(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        admit(runtime, "a")
        with pytest.raises(JournalError, match="no acknowledged save witness"):
            start(runtime, "req-1", "registry-run-1")
    finally:
        runtime.close()


def test_start_refuses_a_wrong_projection_witness_directly():
    document = {"components": {"gen1-save-witness": {
        "a": {"frame": 1, "digest": "d" * 64, "projection": "whole-file", "index": 0, "operation_id": "o" * 32},
        "b": {"frame": 1, "digest": "d" * 64, "projection": "cartram-0498-8000-v1", "index": 0, "operation_id": "o" * 32}}}}
    with pytest.raises(JournalError, match="persistent CartRAM projection"):
        gen1_checkpoint_runtime._pinned_witnesses(document)


def test_start_refuses_pending_commands(paired):
    runtime, owners = paired
    stage = runtime.state()
    document = stage.document()
    runtime.journal.commit("a", secrets.token_hex(16), {"event": "observation"},
        expected_revision=stage.journal_revision, state=document,
        commands={"a": [{"cmd": "debug_hold"}], "b": []}, result={"ack": "ACK"})
    with pytest.raises(JournalError, match="commands pending"):
        start(runtime, "req-1", "registry-run-1")


def test_start_refuses_a_second_request_while_one_is_collecting(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    with pytest.raises(JournalError, match="already in progress"):
        start(runtime, "req-2", "registry-run-1")


def test_start_is_idempotent_on_the_same_request_id(paired):
    runtime, owners = paired
    first = start(runtime, "req-1", "registry-run-1")
    second = start(runtime, "req-1", "registry-run-1")
    assert first == second == {"ack": "ACK", "request_id": "req-1", "status": "collecting"}
    # No duplicate commands were issued.
    assert len(runtime.journal.pending_ids("a")) == 1 and len(runtime.journal.pending_ids("b")) == 1


# -- upload refusals ------------------------------------------------------------

def test_upload_refuses_wrong_command_id(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    message = {"event": "save_upload", "command_id": "0" * 32, "command_sequence": 1,
        "receipt": _receipt(runtime, "a", "req-1", witness)}
    session = runtime.gate.sessions["a"]
    with pytest.raises(JournalError):
        runtime.process({**message, "protocol": runtime.protocol, "player": "a", "session_id": session.session_id,
            "admission_epoch": runtime.gate.epoch, "seq": session.last_seq + 1,
            "operation_id": secrets.token_hex(16)}, owners["a"])


def test_upload_refuses_from_the_wrong_player(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    # Player 'a' tries to ACK player 'b's command id.
    command_id_b = runtime.journal.pending_ids("b")[0]
    with pytest.raises(JournalError):
        runtime.journal.command("a", command_id_b)


def test_upload_refuses_binding_mismatch_final_sha1(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    with pytest.raises(JournalError, match="physical session"):
        _upload(runtime, "a", owners["a"], "req-1", witness, final_sha1="f" * 40)


def test_upload_refuses_wrong_size_cart_hex(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    with pytest.raises(JournalError, match="65536 uppercase hex"):
        _upload(runtime, "a", owners["a"], "req-1", witness, cart_hex="FF" * 100)


def test_upload_refuses_non_hex_cart_hex(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    bad = ("gg" + "FF" * (0x8000 - 1))
    with pytest.raises(JournalError, match="65536 uppercase hex"):
        _upload(runtime, "a", owners["a"], "req-1", witness, cart_hex=bad)


def test_upload_refuses_wrong_digest(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    other_hex = "AA" * 0x8000
    with pytest.raises(JournalError, match="pinned witness"):
        _upload(runtime, "a", owners["a"], "req-1", witness, cart_hex=other_hex)


def test_upload_refuses_a_different_witness_than_pinned(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = dict(_component(runtime)["witnesses"]["a"])
    witness["frame"] = witness["frame"] + 1  # looks legitimate, but isn't the pinned one
    with pytest.raises(JournalError, match="differs from the pinned witness"):
        _upload(runtime, "a", owners["a"], "req-1", witness)


def test_upload_refuses_gameplay_committed_since_the_witness(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    # A real gameplay event lands for 'a' after its witness (a frame safely past the witness's).
    extra = payload(runtime, "a", ["battle_faint"], 2)
    extra["signals"][0]["frame"] = witness["frame"] + 100
    deliver(runtime, "a", owners["a"], extra)
    with pytest.raises(JournalError, match="gameplay committed"):
        _upload(runtime, "a", owners["a"], "req-1", witness)


def test_duplicate_upload_under_the_same_operation_is_idempotent(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    op = secrets.token_hex(16)
    command_id = runtime.journal.pending_ids("a")[0]
    first = _upload(runtime, "a", owners["a"], "req-1", witness, operation=op, command_id=command_id)
    before = runtime.journal.snapshot()
    second = _upload(runtime, "a", owners["a"], "req-1", witness, operation=op, command_id=command_id)
    # "seq" is the transport envelope's own echo (each call bumps the session's last_seq) and
    # legitimately differs; the committed result content is what must be replay-identical.
    assert {k: v for k, v in second.items() if k != "seq"} == {k: v for k, v in first.items() if k != "seq"}
    assert runtime.journal.snapshot() == before


def test_second_upload_attempt_for_an_already_uploaded_player_refuses(paired):
    # Once ACKed, the command leaves pending_ids() — a fresh attempt (new operation_id) for the
    # same player refuses at the FIFO/pending check; component["uploads"][player] being already
    # set is the same "first upload holds" invariant, checked defensively in code even though
    # this exact path can no longer reach it (the command is never pending again to retry).
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    command_id = runtime.journal.pending_ids("a")[0]
    _upload(runtime, "a", owners["a"], "req-1", witness, command_id=command_id)
    with pytest.raises(JournalError, match="oldest pending command"):
        _upload(runtime, "a", owners["a"], "req-1", witness, command_id=command_id)


def test_one_upload_never_publishes(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    _upload(runtime, "a", owners["a"], "req-1", witness)
    component = _component(runtime)
    assert component["status"] == "collecting"
    assert component["uploads"]["b"] is None
    store = PairedCheckpointStore(runtime.data_dir)
    assert store.current() is None


# -- both valid: publish + journal confirmation --------------------------------

def test_both_valid_uploads_publish_matching_files_rules_identity_provenance(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    witness_a, witness_b = component["witnesses"]["a"], component["witnesses"]["b"]
    _upload(runtime, "a", owners["a"], "req-1", witness_a)
    _upload(runtime, "b", owners["b"], "req-1", witness_b)

    component = _component(runtime)
    assert component["status"] == "confirmed"
    assert component["confirmed"]["request_id"] == "req-1"

    store = PairedCheckpointStore(runtime.data_dir)
    current = store.current()
    assert current["checkpoint_id"] == component["confirmed"]["checkpoint_id"]
    assert current["players"]["a"]["witness"] == witness_a
    assert current["players"]["b"]["witness"] == witness_b
    assert current["provenance"]["request_id"] == "req-1"
    assert current["provenance"]["registry_run_id"] == "registry-run-1"
    assert current["provenance"]["run_id"] == runtime.journal.run_id

    checkpoint = store.load(current["checkpoint_id"])
    assert checkpoint.save_bytes("a") == bytes.fromhex(CART_HEX)
    assert checkpoint.save_bytes("b") == bytes.fromhex(CART_HEX)
    import json as _json
    assert _json.loads(checkpoint.rules_bytes()) == runtime.state().rules.document()
    from server.gen1_run_resume import known_keys
    document = runtime.state().document()
    assert _json.loads(checkpoint.identity_bytes()) == known_keys(document, runtime.state().rules.document())


def test_reopened_run_still_shows_the_confirmed_checkpoint(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    owners = _enroll_and_witness(runtime)
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    checkpoint_id = _component(runtime)["confirmed"]["checkpoint_id"]
    runtime.close()

    reopened = open_runtime(tmp_path)
    try:
        component = _component(reopened)
        assert component["status"] == "confirmed"
        assert component["confirmed"]["checkpoint_id"] == checkpoint_id
    finally:
        reopened.close()

    # And a fully STOPPED run (no live Gen1Runtime at all) is still readable for R5b-3 recover.
    stopped = gen1_checkpoint_runtime.confirmed_checkpoints(tmp_path)
    assert stopped["status"] == "confirmed"
    assert stopped["confirmed"]["checkpoint_id"] == checkpoint_id


def test_confirmed_checkpoints_is_none_for_a_directory_with_no_run(tmp_path):
    assert gen1_checkpoint_runtime.confirmed_checkpoints(tmp_path) is None


# -- cross-store failure windows / reconciliation ------------------------------

def test_intent_before_capture_failure_is_abandoned_on_reopen_previous_confirmed_stands(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    owners = _enroll_and_witness(runtime)
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])

    real_capture = PairedCheckpointStore.capture

    def failing_capture(self, *args, **kwargs):
        raise CheckpointError("simulated store failure")
    monkeypatch.setattr(paired_save_checkpoints.PairedCheckpointStore, "capture", failing_capture)
    with pytest.raises(JournalError, match="paired checkpoint capture failed"):
        _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    monkeypatch.setattr(paired_save_checkpoints.PairedCheckpointStore, "capture", real_capture)

    component = _component(runtime)
    assert component["status"] == "preparing"
    assert PairedCheckpointStore(runtime.data_dir).current() is None
    runtime.close()

    reopened = open_runtime(tmp_path)
    try:
        component = _component(reopened)
        assert component["status"] == "abandoned"
        assert component["confirmed"] is None
        assert PairedCheckpointStore(reopened.data_dir).current() is None
        # A NEW checkpoint request is not blocked by the abandoned one (admissions and save
        # witnesses are committed document state, not live-session state, so this needs no
        # re-admission on the reopened, held-service runtime).
        second = start(reopened, "req-2", "registry-run-1")
        assert second["status"] == "collecting"
    finally:
        reopened.close()


def test_archive_published_but_confirm_crashed_is_confirmed_on_reopen(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    owners = _enroll_and_witness(runtime)
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])

    def failing_confirm(*args, **kwargs):
        raise RuntimeError("simulated crash between archive publish and confirm commit")
    monkeypatch.setattr(gen1_checkpoint_runtime, "_confirm", failing_confirm)
    with pytest.raises(Exception, match="simulated crash"):
        _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    monkeypatch.undo()

    component = _component(runtime)
    assert component["status"] == "preparing"
    store = PairedCheckpointStore(runtime.data_dir)
    orphaned = store.current()
    assert orphaned is not None and orphaned["provenance"]["request_id"] == "req-1"
    runtime.close()

    reopened = open_runtime(tmp_path)
    try:
        component = _component(reopened)
        assert component["status"] == "confirmed"
        assert component["confirmed"]["checkpoint_id"] == orphaned["checkpoint_id"]
        assert PairedCheckpointStore(reopened.data_dir).current()["checkpoint_id"] == orphaned["checkpoint_id"]
    finally:
        reopened.close()


def test_reconcile_on_open_is_a_no_op_without_a_checkpoint_component(paired):
    runtime, owners = paired
    reconcile_on_open(runtime)  # must not raise or mutate anything absent a component
    assert _component(runtime) is None


def test_record_replays_a_committed_operation_without_redispatch(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    witness = _component(runtime)["witnesses"]["a"]
    op = secrets.token_hex(16)
    command_id = runtime.journal.pending_ids("a")[0]
    command = runtime.journal.command("a", command_id)
    receipt = _receipt(runtime, "a", "req-1", witness)
    request = {"event": "save_upload", "command_id": command_id, "command_sequence": command["command_sequence"],
               "receipt": receipt}
    first = record(runtime, "a", op, request)
    second = record(runtime, "a", op, request)
    assert first == second
