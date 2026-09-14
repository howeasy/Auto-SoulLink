"""Paired save checkpoint capture: the server-side half of R5b-1.

Both players' latest START-menu save witnesses are pinned (`start`), each player uploads its
exact 32 KiB CartRAM image against that pin (`record`, dispatched for the typed `save_upload`
completion of the durable `checkpoint_upload` command), and once both uploads land the archive
is captured through `server/paired_save_checkpoints.py` (`finalize_checkpoint`) — a SEPARATE
callable, so R5b/N3's native-trade path can call it directly with its own two pretrade images
and native-pretrade witnesses instead of running the upload path at all.

Two-phase cross-store commit: a "preparing" intent is journaled BEFORE `store.capture()`, and
the confirmed checkpoint_id/manifest digest is journaled only AFTER it returns. `CURRENT` in
the store is never trusted alone — `reconcile_on_open` runs at every reopen and either confirms
an orphaned-but-exact archive (crash after capture, before confirm) or abandons a stale intent
(crash before capture, or a mismatched archive), leaving the previously confirmed checkpoint
(if any) untouched either way.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
from pathlib import Path

from server.gen1_run_resume import (
    checkpoint_anchor_operation,
    known_keys,
    no_gameplay_since,
    save_digest,
)
from server.paired_save_checkpoints import CheckpointError, PairedCheckpointStore
from server.protocol import digest
from server.protocol_journal import JournalError, _encode
from server.trade_coordinator import TERMINAL

COMPONENT = "gen1-checkpoint"
SCHEMA = "slink-gen1-checkpoint-v1"
KEY = digest({"component": COMPONENT})[:32]
SAVE_WITNESS = "gen1-save-witness"
PROJECTION = "cartram-0498-8000-v1"
STATUSES = ("collecting", "preparing", "confirmed", "abandoned")
BUSY_STATUSES = ("collecting", "preparing")
UPLOAD_RECEIPT_FIELDS = frozenset({"request_id", "witness", "frame", "context_generation",
    "physical_instance", "final_sha1", "cart_hex"})
# This module's own bookkeeping events are not gameplay: fed to no_gameplay_since as extra_events
# so a checkpoint round trip never itself blocks a later checkpoint's "no gameplay since" check.
CHECKPOINT_EVENTS = frozenset({"checkpoint_start", "save_upload", "checkpoint_prepare",
    "checkpoint_confirm", "checkpoint_reconcile", "checkpoint_abandon"})
HEX_UPPER_65536 = re.compile(r"[0-9A-F]{65536}")

# server_files half of the startup source-identity pin (see server_source_manifest). client_files
# stays an explicit empty list until R5b-2 wires the launcher's pinned runtime_launcher.file_bundle
# through a real launch configuration — a documented gap, not a silent one: the manifest is still
# RECORDED (so "absent" never fires) and a later client_files population still fails closed the
# instant it drifts from what was pinned at runtime start.
_REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_SOURCE_FILES = ("server/paired_save_checkpoints.py", "server/gen1_checkpoint_runtime.py",
    "server/gen1_run_resume.py", "server/gen1_runtime.py")


def server_source_manifest():
    """digest({client_files, server_files}) inputs, recomputed fresh each call so a caller can
    compare "at runtime start" against "right now" and refuse on drift within one process."""
    from server.runtime_launcher import file_bundle
    return {"client_files": [], "server_files": file_bundle(str(_REPO_ROOT), SERVER_SOURCE_FILES)}


def _pinned_witnesses(document):
    witnesses = document["components"].get(SAVE_WITNESS, {})
    result = {}
    for player in ("a", "b"):
        witness = witnesses.get(player)
        if witness is None:
            raise JournalError(f"player {player} has no acknowledged save witness")
        if witness["projection"] != PROJECTION:
            raise JournalError(f"player {player} save witness projection is not the persistent CartRAM projection")
        result[player] = copy.deepcopy(witness)
    return result


def _refuse_unless_idle(runtime, stage, document):
    """The `start` honesty predicates (R5b spec (2)): both admitted, no active trade, no
    pending captures/memorial/rebuild/storage/native/death work, empty ordinary outbox."""
    if stage.component["admissions"]["a"] is None or stage.component["admissions"]["b"] is None:
        raise JournalError("checkpoint capture requires both players admitted")
    if document.get("active_trade") is not None:
        raise JournalError("checkpoint capture requires no active trade")
    if stage.rules.pending_captures:
        raise JournalError("checkpoint capture requires no pending captures")
    if any(stage.rules.pending_memorials.values()):
        raise JournalError("checkpoint capture requires no pending memorials")
    if any(stage.rules.rebuild_pending.values()):
        raise JournalError("checkpoint capture requires no pending rebuild")
    if any(not job["complete"] for job in document["components"].get("gen1-storage-settlement", {}).get("jobs", {}).values()):
        raise JournalError("checkpoint capture requires no pending storage settlement")
    from server.gen1_trade_recovery import transactions
    if any(entry["phase"] not in TERMINAL for entry in transactions(document).values()):
        raise JournalError("checkpoint capture requires no pending native trade work")
    deaths = document["components"].get("gen1-faint-settlement", {}).get("deaths", {})
    if any(death["phase"] in ("pending_issue", "pending_faint") for death in deaths.values()):
        raise JournalError("checkpoint capture requires no pending death work")
    for player in ("a", "b"):
        if runtime.journal.pending_ids(player):
            raise JournalError(f"player {player} has commands pending; checkpoint capture requires an empty outbox")


def start(runtime, request_id, registry_run_id):
    """Admit a new paired-checkpoint request: pin both players' latest save witnesses and
    issue one durable `checkpoint_upload` command per player. Idempotent on an exact repeat of
    the same request_id; refuses while a different request is collecting/preparing."""
    if not isinstance(request_id, str) or not request_id:
        raise JournalError("checkpoint request_id must be a non-empty string")
    stage = runtime.state()
    document = stage.document()
    existing = document["components"].get(COMPONENT)
    if existing is not None and existing["request_id"] == request_id:
        return {"ack": "ACK", "request_id": request_id, "status": existing["status"]}
    if existing is not None and existing["status"] in BUSY_STATUSES:
        raise JournalError("another checkpoint request is already in progress")
    witnesses = _pinned_witnesses(document)
    _refuse_unless_idle(runtime, stage, document)
    component = {"schema": SCHEMA, "request_id": request_id, "registry_run_id": registry_run_id,
        "status": "collecting", "witnesses": witnesses, "uploads": {"a": None, "b": None},
        "confirmed": existing["confirmed"] if existing else None, "intent": None}
    document["components"][COMPONENT] = component
    commands = {p: [{"cmd": "checkpoint_upload", "request_id": request_id, "witness": witnesses[p]}] for p in ("a", "b")}
    op = secrets.token_hex(16)
    result = runtime.journal.commit("a", op, {"event": "checkpoint_start", "request_id": request_id},
        expected_revision=stage.journal_revision, state=document, commands=commands,
        result={"ack": "ACK", "request_id": request_id, "status": "collecting"},
        records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])
    return result.result


def record(runtime, player, operation_id, request):
    """Typed `save_upload` completion of a `checkpoint_upload` command (protocol: the client's
    typed-completion envelope is `{event, command_id, command_sequence, receipt: {...}}` — no
    separate command_ack; the command is ACKed through the ordinary acknowledgements channel)."""
    previous = runtime.journal.event(player, operation_id, request)
    if previous is not None:
        return previous.result
    if set(request) != {"event", "command_id", "command_sequence", "receipt"}:
        raise JournalError("typed checkpoint upload completion required")
    receipt = request["receipt"]
    if not isinstance(receipt, dict) or set(receipt) != UPLOAD_RECEIPT_FIELDS:
        raise JournalError("checkpoint upload receipt is incomplete")
    stage = runtime.state()
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None or component["status"] != "collecting" or receipt["request_id"] != component["request_id"]:
        raise JournalError("no matching checkpoint request is collecting uploads")
    pending = runtime.journal.pending_ids(player)
    if not pending or pending[0] != request["command_id"]:
        raise JournalError("checkpoint upload must ACK the oldest pending command")
    command = runtime.journal.command(player, request["command_id"])
    if (command["command_sequence"] != request["command_sequence"] or command["outcome"] is not None
            or command["body"].get("cmd") != "checkpoint_upload" or command["body"].get("request_id") != component["request_id"]):
        raise JournalError("checkpoint upload differs from its issued command")
    if component["uploads"][player] is not None:
        raise JournalError(f"player {player} already uploaded for this checkpoint request")
    witness = component["witnesses"][player]
    if receipt["witness"] != witness:
        raise JournalError("checkpoint upload witness differs from the pinned witness")
    metadata = runtime.gate.sessions[player].metadata
    if (receipt["context_generation"] != metadata["control_binding"]["context_generation"]
            or receipt["physical_instance"] != metadata["gen1_metadata"]["physical_instance"]
            or receipt["final_sha1"] != metadata["gen1_metadata"]["cartridge"]["final_rom_sha1"]):
        raise JournalError("checkpoint upload binding differs from the current physical session")
    if type(receipt["frame"]) is not int or receipt["frame"] < witness["frame"]:
        raise JournalError("checkpoint upload frame precedes its pinned witness")
    cart_hex = receipt["cart_hex"]
    if not isinstance(cart_hex, str) or not HEX_UPPER_65536.fullmatch(cart_hex):
        raise JournalError("checkpoint upload must carry exactly 65536 uppercase hex characters")
    if save_digest(cart_hex) != witness["digest"]:
        raise JournalError("checkpoint upload projection differs from its pinned witness")
    anchor = checkpoint_anchor_operation(witness)
    if not no_gameplay_since(runtime.journal, player, anchor, extra_events=CHECKPOINT_EVENTS):
        raise JournalError("gameplay committed since the pinned checkpoint witness")
    raw = bytes.fromhex(cart_hex)
    component["uploads"][player] = {"command_id": request["command_id"], "frame": receipt["frame"],
        "cart_hex": cart_hex, "full_sha256": hashlib.sha256(raw).hexdigest()}
    receipt_result = runtime.journal.commit(player, operation_id, request, expected_revision=stage.journal_revision,
        state=document, commands={"a": [], "b": []},
        result={"ack": "ACK", "checkpoint": "upload_recorded", "request_id": component["request_id"]},
        records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}],
        acknowledgements=[{"player": player, "command_id": request["command_id"], "outcome": "ACK", "receipt": receipt}])
    if all(component["uploads"][p] is not None for p in ("a", "b")):
        images = {p: bytes.fromhex(component["uploads"][p]["cart_hex"]) for p in ("a", "b")}
        witnesses = {p: component["witnesses"][p] for p in ("a", "b")}
        provenance = {"run_id": runtime.journal.run_id, "registry_run_id": component["registry_run_id"],
            "journal_revision": receipt_result.revision, "request_id": component["request_id"],
            "witness_a_op": witnesses["a"].get("operation_id"), "witness_a_index": witnesses["a"].get("index"),
            "witness_b_op": witnesses["b"].get("operation_id"), "witness_b_index": witnesses["b"].get("index")}
        finalize_checkpoint(runtime, images=images, witnesses=witnesses, provenance=provenance,
            request_id=component["request_id"])
    return receipt_result.result


def finalize_checkpoint(runtime, *, images, witnesses, provenance, request_id):
    """Journal a prepared intent, publish the archive, then journal the confirmed checkpoint —
    callable directly (bypassing `start`/`record`) by a caller (R5b/N3) that already has its
    own two full-save images and per-kind witnesses, e.g. a native-pretrade transaction's
    already-retained pretrade images. Refuses if a DIFFERENT request is mid-flight."""
    if set(images) != {"a", "b"} or set(witnesses) != {"a", "b"}:
        raise JournalError("finalize_checkpoint requires both players' images and witnesses")
    manifest_source = getattr(runtime, "_source_manifest", None)
    if not manifest_source or not manifest_source.get("server_files"):
        raise JournalError("no startup server-source manifest recorded; checkpoint capture refused")
    if server_source_manifest() != manifest_source:
        raise JournalError("server source files drifted since runtime start; checkpoint capture refused")
    for player, witness in witnesses.items():
        anchor = checkpoint_anchor_operation(witness)
        if not no_gameplay_since(runtime.journal, player, anchor, extra_events=CHECKPOINT_EVENTS):
            raise JournalError(f"gameplay committed for player {player} since its checkpoint witness; refusing finalize")
    stage = runtime.state()
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is not None and component["request_id"] != request_id and component["status"] in BUSY_STATUSES:
        raise JournalError("another checkpoint request is already in progress")
    if component is None or component["request_id"] != request_id:
        component = {"schema": SCHEMA, "request_id": request_id,
            "registry_run_id": component["registry_run_id"] if component else None,
            "status": "collecting", "witnesses": copy.deepcopy(witnesses),
            "uploads": dict.fromkeys(("a", "b")),
            "confirmed": component["confirmed"] if component else None, "intent": None}
    if component["status"] == "confirmed" and (component["confirmed"] or {}).get("request_id") == request_id:
        return component["confirmed"]
    rules_bytes = _encode(stage.rules.document())[0].encode("ascii")
    identity_bytes = _encode(known_keys(document, stage.rules.document()))[0].encode("ascii")
    contract_fingerprint = digest(runtime.contract)
    source_fingerprint = digest(manifest_source)
    component = {**component, "status": "preparing", "intent": {"contract_fingerprint": contract_fingerprint,
        "source_fingerprint": source_fingerprint, "provenance": copy.deepcopy(provenance)}}
    document["components"][COMPONENT] = component
    op = secrets.token_hex(16)
    runtime.journal.commit("a", op, {"event": "checkpoint_prepare", "request_id": request_id},
        expected_revision=stage.journal_revision, state=document, commands={"a": [], "b": []},
        result={"ack": "ACK"}, records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])
    try:
        manifest = PairedCheckpointStore(runtime.data_dir).capture(
            players={p: {"save": images[p], "witness": witnesses[p]} for p in ("a", "b")},
            rules=rules_bytes, identity=identity_bytes, contract_fingerprint=contract_fingerprint,
            source_fingerprint=source_fingerprint, provenance=provenance, allow_same_batch=True)
    except CheckpointError as error:
        raise JournalError(f"paired checkpoint capture failed: {error}") from error
    return _confirm(runtime, request_id, manifest)


def _manifest_sha256(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")).hexdigest()


def _confirm(runtime, request_id, manifest):
    stage = runtime.state()
    document = stage.document()
    component = document["components"][COMPONENT]
    confirmed = {"checkpoint_id": manifest["checkpoint_id"], "manifest_sha256": _manifest_sha256(manifest),
        "request_id": request_id}
    component = {**component, "status": "confirmed", "confirmed": confirmed}
    document["components"][COMPONENT] = component
    op = secrets.token_hex(16)
    runtime.journal.commit("a", op, {"event": "checkpoint_confirm", "request_id": request_id,
        "checkpoint_id": manifest["checkpoint_id"]},
        expected_revision=stage.journal_revision, state=document, commands={"a": [], "b": []},
        result={"ack": "ACK", "checkpoint_id": manifest["checkpoint_id"]},
        records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])
    return confirmed


def reconcile_on_open(runtime):
    """Cross-store reconciliation at every reopen (R5b spec (2)): a "preparing" intent with no
    matching journal confirmation is resolved against the store's own CURRENT — confirmed now
    if it is EXACTLY this intent's archive (by request_id), abandoned otherwise. Either way the
    previously confirmed checkpoint (if any) is untouched; CURRENT alone is never trusted."""
    stage = runtime.state()
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None or component["status"] != "preparing" or component.get("intent") is None:
        return
    try:
        current = PairedCheckpointStore(runtime.data_dir).current()
    except CheckpointError:
        current = None
    if current is not None and current["provenance"].get("request_id") == component["request_id"]:
        _confirm(runtime, component["request_id"], current)
        return
    component = {**component, "status": "abandoned"}
    document["components"][COMPONENT] = component
    op = secrets.token_hex(16)
    runtime.journal.commit("a", op, {"event": "checkpoint_abandon", "request_id": component["request_id"]},
        expected_revision=stage.journal_revision, state=document, commands={"a": [], "b": []},
        result={"ack": "ACK"}, records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])


def confirmed_checkpoints(run_directory):
    """Read-only: this component's status straight from a STOPPED run's journal file, no live
    Gen1Runtime needed — for R5b-3 (Manager recover), which only ever sees a run after it has
    stopped. Mirrors gen1_run_resume.audit_predecessor's own read-only open of a closed run's
    prepared journal. Returns None if the directory never ran a Gen1 durable session, or the
    run never issued a checkpoint request."""
    from server.gen1_run_config import FILENAME, SCHEMA as RUN_SCHEMA
    from server.journal_reader import read_journal
    from server.protocol import decode_frame

    directory = Path(run_directory).resolve()
    path = directory / FILENAME
    if not path.is_file() or not (directory / "runtime.sqlite3").is_file():
        return None
    spec = decode_frame(path.read_bytes())
    if spec.get("schema") != RUN_SCHEMA:
        return None
    stored = read_journal(directory / spec["journal"], run_id=spec["run_id"], contract_hash=digest(spec["contract"]))
    return stored.snapshot.state["components"].get(COMPONENT)


def verify_state(stage):
    """Component validation (structural only — the cross-store archive itself is R5a's job)."""
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    if (not isinstance(component, dict)
            or set(component) != {"schema", "request_id", "registry_run_id", "status", "witnesses",
                                   "uploads", "confirmed", "intent"}
            or component["schema"] != SCHEMA or not isinstance(component["request_id"], str) or not component["request_id"]
            or component["status"] not in STATUSES or set(component["witnesses"]) != {"a", "b"}
            or set(component["uploads"]) != {"a", "b"}):
        raise JournalError("invalid checkpoint component")
    if component["confirmed"] is not None and (
            not isinstance(component["confirmed"], dict)
            or set(component["confirmed"]) != {"checkpoint_id", "manifest_sha256", "request_id"}):
        raise JournalError("invalid checkpoint confirmation record")
    if component["intent"] is not None and (
            not isinstance(component["intent"], dict)
            or set(component["intent"]) != {"contract_fingerprint", "source_fingerprint", "provenance"}):
        raise JournalError("invalid checkpoint intent record")
    for player in ("a", "b"):
        upload = component["uploads"][player]
        if upload is not None and (not isinstance(upload, dict)
                or set(upload) != {"command_id", "frame", "cart_hex", "full_sha256"}):
            raise JournalError("invalid checkpoint upload record")
