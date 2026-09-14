"""Server capture half of R5b-1: start -> save_upload x2 -> finalize_checkpoint, plus the
cross-store reconciliation on reopen. Real journal commits throughout, no emulator."""
import hashlib
import secrets
import time

import pytest

from server import gen1_checkpoint_runtime, paired_save_checkpoints
from server.gen1_checkpoint_runtime import COMPONENT, reconcile_on_open, record, start
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_run_resume import witness_ends_its_batch
from server.paired_save_checkpoints import CheckpointError, PairedCheckpointStore
from server.protocol_journal import JournalError
from tests.unit.test_client_state_store import runtime as lua_runtime  # noqa: F401
from tests.unit.test_gen1_checkpoint_client import boot as boot_lua_checkpoint_client
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


def _pin_witness_with_trailing_signal(runtime, player, owner, *, frame=200, sequence=1, cart_hex=CART_HEX):
    """The save_witness is NOT the last signal in its own committed batch (F1 red-test setup):
    a real gameplay signal lands in the SAME commit right after it. `payload(...)` (not a bare
    `signal(...)`) fixes up player_id_hex to match the admitted identity."""
    value = payload(runtime, player, ["battle_faint"], sequence)
    witness_sig = save_witness_signal(value["variant"], digest=_save_digest(cart_hex))
    witness_sig["frame"] = frame
    trailing = value["signals"][0]
    trailing["frame"] = frame + 1
    value["signals"] = [witness_sig, trailing]
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


def _envelope(runtime, player, owner, message, operation=None):
    session = runtime.gate.sessions[player]
    return runtime.process({**message, "protocol": runtime.protocol, "player": player,
        "session_id": session.session_id, "admission_epoch": runtime.gate.epoch, "seq": session.last_seq + 1,
        "operation_id": operation or secrets.token_hex(16)}, owner)


def _refuse(runtime, player, owner, request_id, witness, *, code="digest_mismatch", reason="test refusal", operation=None):
    command_id = runtime.journal.pending_ids(player)[0]
    command = runtime.journal.command(player, command_id)
    receipt = {"request_id": request_id, "witness": witness, "refused": {"code": code, "reason": reason}}
    message = {"event": "save_upload", "command_id": command_id, "command_sequence": command["command_sequence"],
        "receipt": receipt}
    return _envelope(runtime, player, owner, message, operation)


def _release(runtime, player, owner, request_id, outcome, *, operation=None):
    command_id = runtime.journal.pending_ids(player)[0]
    command = runtime.journal.command(player, command_id)
    receipt = {"request_id": request_id, "outcome": outcome}
    message = {"event": "checkpoint_release", "command_id": command_id, "command_sequence": command["command_sequence"],
        "receipt": receipt}
    return _envelope(runtime, player, owner, message, operation)


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

def test_capture_failure_during_publish_abandons_with_reason_and_releases_both(tmp_path, monkeypatch):
    # Round 2 (F2): the second upload's own ACK and the "preparing" intent are ONE atomic
    # commit, so a synchronous publish failure right after can never leave the request wedged
    # in "collecting" or "preparing" — it is abandoned (with a reason) in the same call, and
    # the uploading client's own response is unaffected (its upload really did succeed).
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    owners = _enroll_and_witness(runtime)
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])

    def failing_capture(self, *args, **kwargs):
        raise CheckpointError("simulated store failure")
    monkeypatch.setattr(paired_save_checkpoints.PairedCheckpointStore, "capture", failing_capture)
    second = _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    assert second["ack"] == "ACK"  # the upload itself succeeded
    monkeypatch.undo()

    component = _component(runtime)
    assert component["status"] == "abandoned"
    assert "simulated store failure" in component["abandoned_reason"]
    assert PairedCheckpointStore(runtime.data_dir).current() is None
    # Both players were released with the abandonment.
    assert [c["cmd"] for c in runtime.journal.pending("a")] == ["checkpoint_release"]
    assert [c["cmd"] for c in runtime.journal.pending("b")] == ["checkpoint_release"]
    _release(runtime, "a", owners["a"], "req-1", "abandoned")
    _release(runtime, "b", owners["b"], "req-1", "abandoned")
    assert _component(runtime)["releases"] == {"a": True, "b": True}

    # A brand new request is not blocked by the abandoned one, once released.
    third = start(runtime, "req-2", "registry-run-1")
    assert third["status"] == "collecting"
    runtime.close()


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


# -- round 2, F1: same-batch gameplay after the witness ------------------------

def test_witness_ends_its_batch_pure_unit():
    document = {"components": {"gen1-engine-signals": {"a": {"operation_id": "op1",
        "payload": {"signals": [{"frame": 1}, {"frame": 2}]}}}}}
    tail = {"witness_kind": "save_witness", "operation_id": "op1", "index": 1}
    not_tail = {**tail, "index": 0}
    other_batch = {**tail, "operation_id": "op2"}
    native = {"witness_kind": "native_pretrade"}
    assert witness_ends_its_batch(document, "a", tail) is True
    assert witness_ends_its_batch(document, "a", not_tail) is False
    assert witness_ends_its_batch(document, "a", other_batch) is True
    assert witness_ends_its_batch(document, "a", native) is True


def test_start_refuses_a_witness_not_at_the_tail_of_its_own_batch(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        owners = {}
        for player in ("a", "b"):
            owners[player] = admit(runtime, player)
            send(runtime, player, owners[player], observation(runtime, player))
        _pin_witness_with_trailing_signal(runtime, "a", owners["a"])
        _pin_witness(runtime, "b", owners["b"])
        with pytest.raises(JournalError, match="same batch"):
            start(runtime, "req-1", "registry-run-1")
    finally:
        runtime.close()


# -- round 2, F3: request_id reuse / reconciliation binds full identity -------

def _settle(runtime, owners, request_id):
    """Drive one checkpoint request all the way to confirmed + both releases delivered."""
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], request_id, component["witnesses"]["a"])
    _upload(runtime, "b", owners["b"], request_id, component["witnesses"]["b"])
    assert _component(runtime)["status"] == "confirmed"
    _release(runtime, "a", owners["a"], request_id, "confirmed")
    _release(runtime, "b", owners["b"], request_id, "confirmed")


def test_start_refuses_reusing_a_request_id_from_a_settled_request(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    _settle(runtime, owners, "req-1")
    start(runtime, "req-2", "registry-run-1")  # moves the tracked request on
    _settle(runtime, owners, "req-2")          # settle it too, so it's not itself "busy"
    with pytest.raises(JournalError, match="already been used"):
        start(runtime, "req-1", "registry-run-1")


def test_confirm_refuses_when_manifest_does_not_match_the_intent(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    manifest = PairedCheckpointStore(runtime.data_dir).current()
    intent = _component(runtime)["intent"]
    tampered = {**intent, "rules_sha256": "0" * 64}
    with pytest.raises(JournalError, match="does not match the prepared checkpoint intent"):
        gen1_checkpoint_runtime._confirm(runtime, "req-1", tampered, manifest)


def test_reconcile_on_open_abandons_when_archive_does_not_match_the_prepared_intent(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    owners = _enroll_and_witness(runtime)
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])

    def failing_confirm(*args, **kwargs):
        raise RuntimeError("simulated crash before confirm")
    monkeypatch.setattr(gen1_checkpoint_runtime, "_confirm", failing_confirm)
    with pytest.raises(Exception, match="simulated crash"):
        _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    monkeypatch.undo()

    # The archive really was published (round-1 behavior) -- but the journaled intent is now
    # corrupted/stale relative to it (standing in for "reused id, different content"): the
    # store's real manifest can no longer satisfy _intent_matches_manifest.
    stage = runtime.state()
    document = stage.document()
    corrupted = dict(document["components"][COMPONENT])
    corrupted["intent"] = {**corrupted["intent"], "rules_sha256": "0" * 64}
    document["components"][COMPONENT] = corrupted
    runtime.journal.commit("a", secrets.token_hex(16), {"event": "observation"},
        expected_revision=stage.journal_revision, state=document, commands={"a": [], "b": []}, result={"ack": "ACK"})
    runtime.close()

    reopened = open_runtime(tmp_path)
    try:
        component = _component(reopened)
        assert component["status"] == "abandoned"
        assert "no matching confirmed archive" in component["abandoned_reason"]
        # The confirmed pointer never moved off whatever it was before (None here).
        assert component["confirmed"] is None
    finally:
        reopened.close()


# -- round 2, F5: source pin drift refuses capture, never the runtime --------

def test_source_pin_drift_refuses_capture_not_the_runtime(tmp_path, monkeypatch):
    # F5 (round 3): drift is checked FRESH, not from a cached attribute -- and refuses at
    # start() itself (before humans upload for a doomed request), never the runtime's own
    # construction/reopen.
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    _enroll_and_witness(runtime)
    runtime.close()

    monkeypatch.setattr(gen1_checkpoint_runtime, "server_source_manifest",
        lambda runtime: {"client_files": [], "server_files": [{"path": "x", "sha256": "1" * 64, "encoding": "raw"}]})
    reopened = open_runtime(tmp_path)  # must NOT raise: the runtime itself opens fine
    try:
        with pytest.raises(JournalError, match="checkpoint capture refused"):
            start(reopened, "req-1", "registry-run-1")
        assert _component(reopened) is None  # refused before any component/command existed
    finally:
        reopened.close()


def test_source_pin_is_recorded_once_and_matches_on_a_clean_reopen(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        gen1_checkpoint_runtime._check_source_pin(reopened)  # must not raise
    finally:
        reopened.close()


def test_drift_discovered_during_collection_abandons_with_release(paired, monkeypatch):
    # F2/F5: the pin matched at start(), but the files changed WHILE collecting -- discovered
    # only when the second upload tries to build the intent. That is an EXPECTED failure: the
    # SAME commit as the (still-valid) second upload durably abandons and releases both.
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    monkeypatch.setattr(gen1_checkpoint_runtime, "server_source_manifest",
        lambda runtime: {"client_files": [], "server_files": [{"path": "x", "sha256": "1" * 64, "encoding": "raw"}]})
    second = _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    assert second["ack"] == "ACK"  # the upload itself still succeeded
    monkeypatch.undo()
    component = _component(runtime)
    assert component["status"] == "abandoned"
    assert "source files changed" in component["abandoned_reason"]
    assert "checkpoint_release" in [c["cmd"] for c in runtime.journal.pending("a")]
    assert "checkpoint_release" in [c["cmd"] for c in runtime.journal.pending("b")]


def test_raw_oserror_from_store_capture_leaves_preparing_recoverable_on_reopen(tmp_path, monkeypatch):
    # F2: an UNEXPECTED failure (a raw OSError, not a policy CheckpointError/JournalError) is
    # never guessed at in-process -- "preparing" stays durable, and reconcile_on_open resolves
    # it correctly (no matching archive exists) on the next open.
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    owners = _enroll_and_witness(runtime)
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])

    def raising_capture(self, *args, **kwargs):
        raise OSError("simulated disk failure")
    monkeypatch.setattr(paired_save_checkpoints.PairedCheckpointStore, "capture", raising_capture)
    with pytest.raises(OSError):
        _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    monkeypatch.undo()

    component = _component(runtime)
    assert component["status"] == "preparing"
    assert PairedCheckpointStore(runtime.data_dir).current() is None
    runtime.close()

    reopened = open_runtime(tmp_path)
    try:
        component = _component(reopened)
        assert component["status"] == "abandoned"
        assert "no matching confirmed archive" in component["abandoned_reason"]
    finally:
        reopened.close()


# -- round 3, A1: late completion after partner abandonment (joint doc §1) ----

def test_late_upload_after_partner_refusal_is_accepted_as_abandoned_and_releases_both(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _refuse(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    assert _component(runtime)["status"] == "abandoned"
    # B's checkpoint_upload is STILL outstanding -- the late upload must be accepted as
    # discarded evidence, never stored as a real upload, so B's queue can drain to its release.
    result = _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    assert result["ack"] == "ACK"
    component = _component(runtime)
    assert component["uploads"]["b"] is None
    assert component["refusals"]["b"] is None
    assert [c["cmd"] for c in runtime.journal.pending("a")] == ["checkpoint_release"]
    assert [c["cmd"] for c in runtime.journal.pending("b")] == ["checkpoint_release"]
    _release(runtime, "a", owners["a"], "req-1", "abandoned")
    _release(runtime, "b", owners["b"], "req-1", "abandoned")
    assert _component(runtime)["releases"] == {"a": True, "b": True}


def test_late_refusal_after_partner_refusal_is_also_accepted_as_abandoned(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _refuse(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    result = _refuse(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"],
        code="digest_mismatch", reason="bad")
    assert result["ack"] == "ACK"
    assert _component(runtime)["refusals"]["b"] is None  # discarded, not recorded


def test_late_completion_after_collect_timeout_drains_both_queues(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    runtime._checkpoint_collect_watch["deadline"] = 0
    gen1_checkpoint_runtime.check_collect_timeout(runtime)
    assert _component(runtime)["status"] == "abandoned"
    result_a = _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    result_b = _refuse(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    assert result_a["ack"] == "ACK" and result_b["ack"] == "ACK"
    _release(runtime, "a", owners["a"], "req-1", "abandoned")
    _release(runtime, "b", owners["b"], "req-1", "abandoned")
    assert _component(runtime)["releases"] == {"a": True, "b": True}


# -- round 3, F3: lifetime-unique ids, bounded budget -------------------------

def test_used_request_ids_budget_exhaustion_refuses_new_ids(paired, monkeypatch):
    runtime, owners = paired
    monkeypatch.setattr(gen1_checkpoint_runtime, "USED_ID_CAP", 1)
    start(runtime, "req-1", "registry-run-1")
    _settle(runtime, owners, "req-1")
    with pytest.raises(JournalError, match="budget exhausted"):
        start(runtime, "req-2", "registry-run-1")


# -- round 3, second request refused until terminal AND both released --------

def test_start_refuses_new_request_while_confirmed_but_not_yet_released(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    assert _component(runtime)["status"] == "confirmed"
    with pytest.raises(JournalError, match="already in progress"):
        start(runtime, "req-2", "registry-run-1")
    _release(runtime, "a", owners["a"], "req-1", "confirmed")
    with pytest.raises(JournalError, match="already in progress"):
        start(runtime, "req-2", "registry-run-1")  # one release still outstanding
    _release(runtime, "b", owners["b"], "req-1", "confirmed")
    result = start(runtime, "req-2", "registry-run-1")
    assert result["status"] == "collecting"


# -- round 3, F4: input validation precedes check_collect_timeout ------------

def test_start_validates_request_id_before_check_collect_timeout(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    runtime._checkpoint_collect_watch["deadline"] = 0  # would abandon req-1 if evaluated
    with pytest.raises(JournalError, match=r"1-64 characters"):
        start(runtime, "bad id with spaces!", "registry-run-1")
    assert _component(runtime)["status"] == "collecting"
    assert runtime._checkpoint_collect_watch is not None


# -- round 3, F5: the selected client closure ---------------------------------

def test_client_source_files_matches_the_runtime_selected_closure():
    from server.gen1_launcher import FILES, FREE_FILES, NATIVE_FILES, OBSERVATION_FILES

    class _Fake:
        native_trade = False
        free_service = False
    assert gen1_checkpoint_runtime._client_source_files(_Fake()) == FILES + OBSERVATION_FILES
    _Fake.free_service = True
    assert gen1_checkpoint_runtime._client_source_files(_Fake()) == FILES + OBSERVATION_FILES + FREE_FILES
    _Fake.free_service = False
    _Fake.native_trade = True
    assert gen1_checkpoint_runtime._client_source_files(_Fake()) == FILES + OBSERVATION_FILES + NATIVE_FILES


# -- round 3, F6: pins captured at start(), not the live session -------------

def test_upload_binding_compared_against_the_pin_not_the_live_session(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    # Mutate the LIVE session metadata after start() pinned it -- the upload must still be
    # checked against the ORIGINAL pin.
    runtime.gate.sessions["a"].metadata["gen1_metadata"]["physical_instance"] = "9" * 32
    result = _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    assert result["ack"] == "ACK"


def test_collect_timeout_triggers_via_the_control_heartbeat_path(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    runtime._checkpoint_collect_watch["deadline"] = 0
    session = runtime.gate.sessions["a"]
    challenge = secrets.token_hex(16)
    binding = session.metadata["control_binding"]
    runtime.process({"protocol": runtime.protocol, "player": "a", "session_id": session.session_id,
        "admission_epoch": runtime.gate.epoch, "seq": session.last_seq + 1, "event": "control",
        "operation_id": challenge, "control": {**binding, "challenge": challenge}}, owners["a"])
    assert _component(runtime)["status"] == "abandoned"


# -- round 2, F6/addendum: refusal, release, timeout --------------------------

def test_refusal_receipt_abandons_and_releases_both(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _refuse(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"],
        code="unsafe_timeout", reason="hold expired")
    component = _component(runtime)
    assert component["status"] == "abandoned"
    assert component["refusals"]["a"] == {"code": "unsafe_timeout", "reason": "hold expired"}
    assert "unsafe_timeout" in component["abandoned_reason"]
    # 'a' refused (its own checkpoint_upload is consumed by that same commit); 'b' never
    # uploaded at all, so its original checkpoint_upload is still sitting there too -- the
    # durable outbox has no "retract", it is simply followed by the release.
    assert [c["cmd"] for c in runtime.journal.pending("a")] == ["checkpoint_release"]
    assert "checkpoint_release" in [c["cmd"] for c in runtime.journal.pending("b")]


def test_refusal_receipt_is_never_treated_as_an_upload(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _refuse(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    component = _component(runtime)
    assert component["uploads"]["a"] is None
    assert PairedCheckpointStore(runtime.data_dir).current() is None


def test_release_completion_acks_and_marks_delivered(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _refuse(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    result = _release(runtime, "a", owners["a"], "req-1", "abandoned")
    assert result["ack"] == "ACK"
    assert _component(runtime)["releases"] == {"a": True, "b": False}


def test_release_refuses_a_mismatched_outcome(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    _refuse(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    with pytest.raises(JournalError, match="differs from the request's resolution"):
        _release(runtime, "a", owners["a"], "req-1", "confirmed")


def test_player_upload_status_transitions(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    component = _component(runtime)
    assert gen1_checkpoint_runtime.player_upload_status(component, "a") == "waiting"
    _upload(runtime, "a", owners["a"], "req-1", component["witnesses"]["a"])
    component = _component(runtime)
    assert gen1_checkpoint_runtime.player_upload_status(component, "a") == "uploaded"
    assert gen1_checkpoint_runtime.player_upload_status(component, "b") == "waiting"
    _upload(runtime, "b", owners["b"], "req-1", component["witnesses"]["b"])
    component = _component(runtime)
    assert component["status"] == "confirmed"
    assert gen1_checkpoint_runtime.player_upload_status(component, "b") == "uploaded"
    _release(runtime, "a", owners["a"], "req-1", "confirmed")
    component = _component(runtime)
    assert gen1_checkpoint_runtime.player_upload_status(component, "a") == "released"


def test_collect_timeout_abandons_and_releases(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    runtime._checkpoint_collect_watch["deadline"] = 0
    gen1_checkpoint_runtime.check_collect_timeout(runtime)
    component = _component(runtime)
    assert component["status"] == "abandoned"
    assert component["abandoned_reason"] == "collect_timeout"
    # Neither player uploaded, so both still carry their original checkpoint_upload too.
    assert "checkpoint_release" in [c["cmd"] for c in runtime.journal.pending("a")]
    assert "checkpoint_release" in [c["cmd"] for c in runtime.journal.pending("b")]


def test_collect_timeout_triggers_via_a_real_dispatched_sync_event(paired):
    runtime, owners = paired
    start(runtime, "req-1", "registry-run-1")
    runtime._checkpoint_collect_watch["deadline"] = 0
    session = runtime.gate.sessions["a"]
    runtime.process({"protocol": runtime.protocol, "player": "a", "session_id": session.session_id,
        "admission_epoch": runtime.gate.epoch, "seq": session.last_seq + 1, "event": "sync",
        "operation_id": secrets.token_hex(16)}, owners["a"])
    assert _component(runtime)["status"] == "abandoned"


def test_collect_timeout_is_caught_by_reconcile_on_open(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    _enroll_and_witness(runtime)
    start(runtime, "req-1", "registry-run-1")
    stage = runtime.state()
    document = stage.document()
    component = {**document["components"][COMPONENT], "started_at": time.time() - 10_000}
    document["components"][COMPONENT] = component
    runtime.journal.commit("a", secrets.token_hex(16), {"event": "observation"},
        expected_revision=stage.journal_revision, state=document, commands={"a": [], "b": []}, result={"ack": "ACK"})
    runtime.close()

    reopened = open_runtime(tmp_path)
    try:
        component = _component(reopened)
        assert component["status"] == "abandoned"
        assert component["abandoned_reason"] == "collect_timeout"
    finally:
        reopened.close()


# -- round 3, A2/joint doc: the REAL Lua client validator on release/upload commands --

def test_upload_and_release_commands_pass_the_real_lua_client_validator(lua_runtime):  # noqa: F811
    """A2: server-emitted checkpoint_upload/checkpoint_release command bodies must satisfy
    lua/gen1_checkpoint_client.lua's own M.validate -- release reason is NEVER null and is
    always a printable-ASCII string of at most 256 characters."""
    import json as _json
    lua = lua_runtime
    boot_lua_checkpoint_client(lua)

    upload_body = {"cmd": "checkpoint_upload", "request_id": "req-1",
        "witness": {"frame": 1, "digest": "a" * 64, "projection": "cartram-0498-8000-v1",
                    "index": 0, "operation_id": "b" * 32}}
    confirmed_release = gen1_checkpoint_runtime._release_commands("req-1", "confirmed", None)["a"][0]
    abandoned_release = gen1_checkpoint_runtime._release_commands(
        "req-1", "abandoned", "player a refused (digest_mismatch): bad witness")["b"][0]
    assert confirmed_release["reason"] == ""  # A2: never null, "" on success
    assert isinstance(abandoned_release["reason"], str) and len(abandoned_release["reason"]) <= 256

    for body in (upload_body, confirmed_release, abandoned_release):
        lua.globals().body_json = _json.dumps(body)
        lua.execute("Checkpoint.validate(JSON.decode(body_json))")  # must not raise


def test_release_reason_from_a_long_abandon_reason_still_passes_the_client_validator(lua_runtime):  # noqa: F811
    """A truncated/sanitized-but-still-long internal reason must still satisfy the client's
    own <=256 bound after _release_reason's normalization."""
    import json as _json
    lua = lua_runtime
    boot_lua_checkpoint_client(lua)
    long_reason = "x" * 1000
    release = gen1_checkpoint_runtime._release_commands("req-1", "abandoned", long_reason)["a"][0]
    assert len(release["reason"]) <= 256
    lua.globals().body_json = _json.dumps(release)
    lua.execute("Checkpoint.validate(JSON.decode(body_json))")
