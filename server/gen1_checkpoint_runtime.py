"""Paired save checkpoint capture: the server-side half of R5b-1 (round 3).

Authoritative contract: docs/gen1_reference/reviews/R5b-joint-protocol.md. Both players' latest
START-menu save witnesses, physical bindings and a rules/identity digest are pinned at `start`;
each player uploads its exact 32 KiB CartRAM image against that pin (`record`, dispatched for
the typed `save_upload` completion of the durable `checkpoint_upload` command), and once both
uploads land the archive is captured through `server/paired_save_checkpoints.py`. A client may
instead complete `checkpoint_upload` with a REFUSAL receipt (`{request_id, witness, refused:
{code, reason}}`, no `cart_hex`) — that abandons the request and releases both players; it is
never treated as an upload.

Ordering invariant (joint doc §1): for each player, its upload/refusal completion (U) always
precedes its release completion (R). The server accepts the EXACT outstanding U completion
while the request is `collecting` OR already `abandoned` (as discarded evidence — never
capture) — so a still-outstanding checkpoint_upload can never block the release behind it once
the OTHER player has already ended the request. R is only ever ACKable after U retired.

Two-phase cross-store commit: the SECOND upload's own commit and the prepared intent are one
atomic transaction (or, if intent-building itself fails, that same commit becomes the
abandonment) — there is no durable state where both uploads are recorded but the request's
fate is not. `finalize_checkpoint` (the direct, upload-free entry point R5b/N3 calls with its
own already-retained images) runs the same intent-then-capture-then-confirm sequence. Every
EXPECTED refusal (a policy check failing) durably abandons and releases both players; an
UNEXPECTED one (a raw OSError from the store) is deliberately left as a recoverable `preparing`
for `reconcile_on_open` to resolve on the next open — it is never guessed at in-process.

Every intent binds the FULL archive identity (both witnesses, both saves' sha256, rules/identity
sha256, contract/source fingerprints, provenance); `_confirm`/`reconcile_on_open` validate every
field against the store's own manifest before ever confirming, and a request_id is refused a
second use for the lifetime of the run once it has been used.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import time
from pathlib import Path

from server.gen1_run_resume import (
    checkpoint_anchor_operation,
    known_keys,
    no_gameplay_since,
    save_digest,
    witness_ends_its_batch,
)
from server.paired_save_checkpoints import CheckpointError, PairedCheckpointStore
from server.protocol import digest
from server.protocol_journal import JournalError, _encode
from server.trade_coordinator import TERMINAL

COMPONENT = "gen1-checkpoint"
SCHEMA = "slink-gen1-checkpoint-v1"
KEY = digest({"component": COMPONENT})[:32]
SOURCE_PIN_COMPONENT = "gen1-checkpoint-source-pin"
SOURCE_PIN_SCHEMA = "slink-gen1-checkpoint-source-pin-v1"
SOURCE_PIN_KEY = digest({"component": SOURCE_PIN_COMPONENT})[:32]
SAVE_WITNESS = "gen1-save-witness"
PROJECTION = "cartram-0498-8000-v1"
STATUSES = ("collecting", "preparing", "confirmed", "abandoned")
BUSY_STATUSES = ("collecting", "preparing")
TERMINAL_STATUSES = ("confirmed", "abandoned")
UPLOAD_RECEIPT_FIELDS = frozenset({"request_id", "witness", "frame", "context_generation",
    "physical_instance", "final_sha1", "cart_hex"})
REFUSAL_RECEIPT_FIELDS = frozenset({"request_id", "witness", "refused"})
REFUSAL_CODES = frozenset({"digest_mismatch", "unsafe_timeout", "identity_changed"})
RELEASE_RECEIPT_FIELDS = frozenset({"request_id", "outcome"})
CHECKPOINT_COLLECT_SECONDS = 120
USED_ID_CAP = 256
# This module's own bookkeeping events are not gameplay: fed to no_gameplay_since as extra_events
# so a checkpoint round trip never itself blocks a later checkpoint's "no gameplay since" check.
CHECKPOINT_EVENTS = frozenset({"checkpoint_start", "save_upload", "checkpoint_prepare",
    "checkpoint_confirm", "checkpoint_reconcile", "checkpoint_abandon", "checkpoint_release"})

# Wire bounds (docs/gen1_reference/reviews/R5b-joint-protocol.md §2 — shared with the client's
# own lua/gen1_checkpoint_client.lua validator; joint tests check both sides agree).
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
HEX32 = re.compile(r"[0-9a-f]{32}")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX_UPPER_65536 = re.compile(r"[0-9A-F]{65536}")
PRINTABLE_ASCII = re.compile(r"[\x20-\x7e]*")
COMMAND_SEQUENCE_MAX = 2**53 - 1
FRAME_MAX = 2**53 - 1
RELEASE_REASON_MAX = 256
REFUSAL_REASON_MAX = 256

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_request_id(value):
    return isinstance(value, str) and bool(REQUEST_ID_RE.fullmatch(value))


def _valid_registry_run_id(value):
    return value is None or (isinstance(value, str) and 1 <= len(value) <= 64)


def _valid_hex(value, pattern):
    return isinstance(value, str) and bool(pattern.fullmatch(value))


def _valid_command_sequence(value):
    return type(value) is int and 1 <= value <= COMMAND_SEQUENCE_MAX


def _valid_frame(value):
    return type(value) is int and 0 <= value <= FRAME_MAX


def _valid_release_reason(value):
    return isinstance(value, str) and len(value) <= RELEASE_REASON_MAX and bool(PRINTABLE_ASCII.fullmatch(value))


def _valid_refusal_reason(value):
    return isinstance(value, str) and 1 <= len(value) <= REFUSAL_REASON_MAX and bool(PRINTABLE_ASCII.fullmatch(value))


def _server_source_files(repo_root):
    """server_files half of the source pin: state.py/protocol_journal.py/paired_save_checkpoints.py
    plus identity_registry/durable_runtime/trade_coordinator/staged_state (F5: named explicitly
    rather than left to the gen1_*.py glob, since none of those four match that pattern) plus
    every gen1_*.py module, by glob so a new Gen 1 module is pinned automatically."""
    server_dir = Path(repo_root) / "server"
    paths = {"server/state.py", "server/protocol_journal.py", "server/paired_save_checkpoints.py",
        "server/identity_registry.py", "server/durable_runtime.py", "server/trade_coordinator.py",
        "server/staged_state.py"}
    paths.update("server/" + path.name for path in server_dir.glob("gen1_*.py"))
    return tuple(sorted(paths))


def _client_source_files(runtime):
    """F5: the SELECTED client closure this run's own launcher actually ships (mirrors
    gen1_launcher.build_configuration's own file_bundle selection), not a fixed subset."""
    from server.gen1_launcher import FILES, FREE_FILES, NATIVE_FILES, OBSERVATION_FILES
    selected = FILES + OBSERVATION_FILES
    if getattr(runtime, "native_trade", False):
        selected += NATIVE_FILES
    if getattr(runtime, "free_service", False):
        selected += FREE_FILES
    return selected


def server_source_manifest(runtime):
    """{client_files, server_files}, recomputed fresh on every call — never cached on the
    runtime — so `_check_source_pin` always compares "right now" against what was persisted
    at this run's first open."""
    from server.runtime_launcher import file_bundle
    client_files = file_bundle(str(_REPO_ROOT), _client_source_files(runtime))
    server_files = file_bundle(str(_REPO_ROOT), _server_source_files(_REPO_ROOT))
    return {"client_files": client_files, "server_files": server_files}


def ensure_source_pin(runtime):
    """Persist the source-identity digest ONCE, at this run's first-ever open (a system commit,
    only if the component is absent). Drift is never checked from a cached value — every
    capture-adjacent call (`start`, `_build_intent`) recomputes fresh via `_check_source_pin`."""
    stage = runtime.state()
    document = stage.document()
    if document["components"].get(SOURCE_PIN_COMPONENT) is not None:
        return
    pin = {"schema": SOURCE_PIN_SCHEMA, "digest": digest(server_source_manifest(runtime))}
    document["components"][SOURCE_PIN_COMPONENT] = pin
    op = secrets.token_hex(16)
    runtime.journal.commit("a", op, {"event": "checkpoint_source_pin"},
        expected_revision=stage.journal_revision, state=document, commands={"a": [], "b": []},
        result={"ack": "ACK"}, records=[{"namespace": SOURCE_PIN_COMPONENT, "key": SOURCE_PIN_KEY, "value": pin}])


def _check_source_pin(runtime):
    """F5: fresh comparison against the persisted pin, every time — a drifted pin refuses
    ONLY the checkpoint request/capture in progress, never the runtime itself."""
    pin = runtime.state().document()["components"].get(SOURCE_PIN_COMPONENT)
    if pin is None:
        raise JournalError("no startup source pin recorded for this run; checkpoint capture refused")
    manifest = server_source_manifest(runtime)
    if digest(manifest) != pin["digest"]:
        raise JournalError("server/client source files changed since this run was created; checkpoint capture refused")
    return manifest


def _player_binding(runtime, player):
    metadata = runtime.gate.sessions[player].metadata
    return {"context_generation": metadata["control_binding"]["context_generation"],
        "physical_instance": metadata["gen1_metadata"]["physical_instance"],
        "final_sha1": metadata["gen1_metadata"]["cartridge"]["final_rom_sha1"]}


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


def _request_settled(component):
    """Joint doc trigger table: a second request is refused until the previous one is
    terminal AND both releases have retired — a bare "confirmed"/"abandoned" status is not
    enough, since the client is still holding until its own release completion lands."""
    return component["status"] in TERMINAL_STATUSES and component["releases"]["a"] and component["releases"]["b"]


def _with_used_id(used_ids, request_id):
    """F3: lifetime uniqueness, never truncated — a bounded budget refused explicitly once
    exhausted, rather than silently dropping an old id and losing its reuse protection."""
    if len(used_ids) >= USED_ID_CAP:
        raise JournalError(f"checkpoint request_id budget exhausted ({USED_ID_CAP} used on this run)")
    return [*used_ids, request_id]


def player_upload_status(component, player):
    """"waiting"|"uploaded"|"refused"|"released" — the F6/status-endpoint view of one player."""
    if component["releases"].get(player):
        return "released"
    if component["refusals"].get(player) is not None:
        return "refused"
    if component["uploads"].get(player) is not None:
        return "uploaded"
    return "waiting"


def _release_reason(reason):
    """A2/joint doc §2: NEVER null, printable ASCII, at most 256 characters — "" on success."""
    if reason is None:
        return ""
    text = "".join(ch if 0x20 <= ord(ch) <= 0x7E else "?" for ch in str(reason))
    return text[:RELEASE_REASON_MAX]


def _release_commands(request_id, outcome, reason):
    body = {"cmd": "checkpoint_release", "request_id": request_id, "outcome": outcome,
        "reason": _release_reason(reason)}
    return {"a": [dict(body)], "b": [dict(body)]}


def _set_collect_watch(runtime, request_id, started_at):
    runtime._checkpoint_collect_watch = {"request_id": request_id, "deadline": started_at + CHECKPOINT_COLLECT_SECONDS}


def _clear_collect_watch(runtime, request_id):
    watch = getattr(runtime, "_checkpoint_collect_watch", None)
    if watch is not None and watch["request_id"] == request_id:
        runtime._checkpoint_collect_watch = None


def check_collect_timeout(runtime):
    """Cheap (an attribute check, no journal read) unless a request is actually collecting and
    overdue. Hooked wherever the joint doc requires "even without semantic traffic" to still
    expire it: `Gen1Runtime._dispatch_semantic`'s first line, `Gen1Runtime._control`'s first
    line (the heartbeat/challenge path), and the `GET /api/checkpoint/{id}` status handler —
    no background thread anywhere."""
    watch = getattr(runtime, "_checkpoint_collect_watch", None)
    if watch is None or time.time() < watch["deadline"]:
        return
    runtime._checkpoint_collect_watch = None
    _abandon(runtime, watch["request_id"], "collect_timeout")


def start(runtime, request_id, registry_run_id):
    """Admit a new paired-checkpoint request: pin both players' latest save witnesses,
    physical bindings and the current rules/identity digest, then issue one durable
    `checkpoint_upload` command per player. Idempotent on an exact repeat of the same
    request_id; refuses while a different request is not yet terminal-and-released (F3's
    lifetime-unique ids), and refuses outright on a stale source pin (F5) rather than let
    humans upload for a doomed request."""
    if not _valid_request_id(request_id):
        raise JournalError("checkpoint request_id must be 1-64 characters of [A-Za-z0-9_.-]")
    if not _valid_registry_run_id(registry_run_id):
        raise JournalError("registry_run_id must be a non-empty string of at most 64 characters, or None")
    check_collect_timeout(runtime)
    stage = runtime.state()
    document = stage.document()
    existing = document["components"].get(COMPONENT)
    if existing is not None and existing["request_id"] == request_id:
        return {"ack": "ACK", "request_id": request_id, "status": existing["status"]}
    if existing is not None and not _request_settled(existing):
        raise JournalError("another checkpoint request is already in progress")
    used = existing["used_request_ids"] if existing else []
    if request_id in used:
        raise JournalError("checkpoint request_id has already been used on this run")
    _check_source_pin(runtime)
    witnesses = _pinned_witnesses(document)
    _refuse_unless_idle(runtime, stage, document)
    for player in ("a", "b"):
        if not witness_ends_its_batch(document, player, witnesses[player]):
            raise JournalError(f"gameplay committed in the same batch as player {player}'s checkpoint witness")
        anchor = checkpoint_anchor_operation(witnesses[player])
        if not no_gameplay_since(runtime.journal, player, anchor, extra_events=CHECKPOINT_EVENTS):
            raise JournalError(f"gameplay committed for player {player} since its checkpoint witness")
    bindings = {p: _player_binding(runtime, p) for p in ("a", "b")}
    rules_bytes = _encode(stage.rules.document())[0].encode("ascii")
    identity_bytes = _encode(known_keys(document, stage.rules.document()))[0].encode("ascii")
    pin = {"rules_sha256": hashlib.sha256(rules_bytes).hexdigest(),
        "identity_sha256": hashlib.sha256(identity_bytes).hexdigest()}
    started_at = time.time()
    component = {"schema": SCHEMA, "request_id": request_id, "registry_run_id": registry_run_id,
        "status": "collecting", "started_at": started_at, "witnesses": witnesses, "bindings": bindings,
        "pin": pin, "uploads": {"a": None, "b": None}, "refusals": {"a": None, "b": None},
        "releases": {"a": False, "b": False},
        "confirmed": existing["confirmed"] if existing else None, "intent": None,
        "abandoned_reason": None, "used_request_ids": _with_used_id(used, request_id)}
    document["components"][COMPONENT] = component
    commands = {p: [{"cmd": "checkpoint_upload", "request_id": request_id, "witness": witnesses[p]}] for p in ("a", "b")}
    op = secrets.token_hex(16)
    result = runtime.journal.commit("a", op, {"event": "checkpoint_start", "request_id": request_id},
        expected_revision=stage.journal_revision, state=document, commands=commands,
        result={"ack": "ACK", "request_id": request_id, "status": "collecting"},
        records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])
    _set_collect_watch(runtime, request_id, started_at)
    return result.result


def _validate_completion_envelope(request):
    if set(request) != {"event", "command_id", "command_sequence", "receipt"}:
        raise JournalError("typed checkpoint completion required")
    if not isinstance(request["command_id"], str) or not request["command_id"]:
        raise JournalError("command_id must be a non-empty string")
    if not _valid_command_sequence(request["command_sequence"]):
        raise JournalError("command_sequence must be a plain integer in 1..2**53-1")


def _validate_issued_command(runtime, player, request, component, *, cmd):
    pending = runtime.journal.pending_ids(player)
    if not pending or pending[0] != request["command_id"]:
        raise JournalError("checkpoint completion must ACK the oldest pending command")
    command = runtime.journal.command(player, request["command_id"])
    if (command["command_sequence"] != request["command_sequence"] or command["outcome"] is not None
            or command["body"].get("cmd") != cmd or command["body"].get("request_id") != component["request_id"]):
        raise JournalError("checkpoint completion differs from its issued command")
    return command


def _validate_receipt_shape(receipt):
    """F4: pure bounds/shape checks — everything checkable without touching the journal or a
    component — done BEFORE `check_collect_timeout` so a malformed wire input never even
    provokes a side-effecting timeout evaluation. Returns "upload" or "refusal"."""
    if not isinstance(receipt, dict) or not _valid_request_id(receipt.get("request_id")):
        raise JournalError("checkpoint upload receipt is incomplete")
    if set(receipt) == REFUSAL_RECEIPT_FIELDS:
        if not isinstance(receipt.get("witness"), dict):
            raise JournalError("checkpoint upload receipt is incomplete")
        refused = receipt.get("refused")
        if (not isinstance(refused, dict) or set(refused) != {"code", "reason"}
                or refused["code"] not in REFUSAL_CODES or not _valid_refusal_reason(refused["reason"])):
            raise JournalError("invalid checkpoint upload refusal")
        return "refusal"
    if set(receipt) == UPLOAD_RECEIPT_FIELDS:
        return "upload"
    raise JournalError("checkpoint upload receipt is incomplete")


def record(runtime, player, operation_id, request):
    """Typed completion of a `checkpoint_upload` command: either an upload receipt or a
    REFUSAL receipt. No separate command_ack; the command is ACKed through the ordinary
    acknowledgements channel of the same commit that records the outcome. Accepts the exact
    outstanding completion while the request is `collecting` (normal) OR already `abandoned`
    (A1/joint doc §1 — discarded evidence, never fabricated capture) so the OTHER player's
    queue can never be blocked behind a request that already ended without them."""
    previous = runtime.journal.event(player, operation_id, request)
    if previous is not None:
        return previous.result
    _validate_completion_envelope(request)
    receipt = request["receipt"]
    kind = _validate_receipt_shape(receipt)
    check_collect_timeout(runtime)
    stage = runtime.state()
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None or receipt["request_id"] != component["request_id"]:
        raise JournalError("no matching checkpoint request is collecting uploads")
    if component["status"] == "abandoned":
        if component["uploads"].get(player) is not None or component["refusals"].get(player) is not None:
            raise JournalError("no matching checkpoint request is collecting uploads")
        return _record_late_completion(runtime, stage, document, player, operation_id, request, component)
    if component["status"] != "collecting":
        raise JournalError("no matching checkpoint request is collecting uploads")
    if kind == "refusal":
        return _record_refusal(runtime, stage, document, player, operation_id, request, receipt, component)
    return _record_upload(runtime, stage, document, player, operation_id, request, receipt, component)


def _record_late_completion(runtime, stage, document, player, operation_id, request, component):
    """A1/joint doc §1: the exact outstanding U completion, accepted while ABANDONED, as
    discarded evidence — never an upload, never a fabricated receipt. ACKs plainly so this
    player's queue drains and the release behind it becomes deliverable."""
    _validate_issued_command(runtime, player, request, component, cmd="checkpoint_upload")
    result = runtime.journal.commit(player, operation_id, request, expected_revision=stage.journal_revision,
        state=document, commands={"a": [], "b": []},
        result={"ack": "ACK", "checkpoint": "abandoned", "request_id": component["request_id"]}, records=[],
        acknowledgements=[{"player": player, "command_id": request["command_id"], "outcome": "ACK",
            "receipt": request["receipt"]}])
    return result.result


def _record_upload(runtime, stage, document, player, operation_id, request, receipt, component):
    _validate_issued_command(runtime, player, request, component, cmd="checkpoint_upload")
    if component["uploads"][player] is not None:
        raise JournalError(f"player {player} already uploaded for this checkpoint request")
    witness = component["witnesses"][player]
    if receipt["witness"] != witness:
        raise JournalError("checkpoint upload witness differs from the pinned witness")
    binding = component["bindings"][player]
    if not (_valid_hex(receipt.get("context_generation"), HEX32) and _valid_hex(receipt.get("physical_instance"), HEX32)
            and _valid_hex(receipt.get("final_sha1"), HEX40)):
        raise JournalError("checkpoint upload binding fields are malformed")
    # F6: compared against the binding PINNED at start(), never the "current" live session --
    # a reconnection under a different physical identity must be caught even if the live
    # session metadata itself already moved on without anyone noticing.
    if (receipt["context_generation"] != binding["context_generation"]
            or receipt["physical_instance"] != binding["physical_instance"]
            or receipt["final_sha1"] != binding["final_sha1"]):
        raise JournalError("checkpoint upload binding differs from the pinned physical session")
    if not _valid_frame(receipt.get("frame")) or receipt["frame"] < witness["frame"]:
        raise JournalError("checkpoint upload frame precedes its pinned witness")
    cart_hex = receipt["cart_hex"]
    if not isinstance(cart_hex, str) or not HEX_UPPER_65536.fullmatch(cart_hex):
        raise JournalError("checkpoint upload must carry exactly 65536 uppercase hex characters")
    if save_digest(cart_hex) != witness["digest"]:
        raise JournalError("checkpoint upload projection differs from its pinned witness")
    if not witness_ends_its_batch(document, player, witness):
        raise JournalError("gameplay committed in the same batch as the pinned checkpoint witness")
    anchor = checkpoint_anchor_operation(witness)
    if not no_gameplay_since(runtime.journal, player, anchor, extra_events=CHECKPOINT_EVENTS):
        raise JournalError("gameplay committed since the pinned checkpoint witness")
    raw = bytes.fromhex(cart_hex)
    component["uploads"][player] = {"command_id": request["command_id"], "frame": receipt["frame"],
        "cart_hex": cart_hex, "full_sha256": hashlib.sha256(raw).hexdigest()}
    other = "b" if player == "a" else "a"
    commands = {"a": [], "b": []}
    result = {"ack": "ACK", "checkpoint": "upload_recorded", "request_id": component["request_id"]}
    should_publish = False
    intent = rules_bytes = identity_bytes = None
    if component["uploads"][other] is not None:
        # F2/A1: fold the prepared intent into this SAME atomic commit as the completing
        # upload's own ACK — the durable "preparing" marker and the ACK land together, or
        # neither does. An EXPECTED refusal discovered only now (drift/gameplay during
        # collection) becomes the abandonment, in this SAME commit, instead of a later one.
        save_sha256 = {p: component["uploads"][p]["full_sha256"] for p in ("a", "b")}
        provenance = {"run_id": runtime.journal.run_id, "registry_run_id": component["registry_run_id"],
            "journal_revision": stage.journal_revision + 1, "request_id": component["request_id"],
            "witness_a_op": component["witnesses"]["a"].get("operation_id"),
            "witness_a_index": component["witnesses"]["a"].get("index"),
            "witness_b_op": component["witnesses"]["b"].get("operation_id"),
            "witness_b_index": component["witnesses"]["b"].get("index")}
        try:
            intent, rules_bytes, identity_bytes = _build_intent(runtime, stage, document,
                witnesses=component["witnesses"], provenance=provenance, save_sha256=save_sha256)
        except JournalError as error:
            reason = str(error)
            component = {**component, "status": "abandoned", "abandoned_reason": reason[:500]}
            commands = _release_commands(component["request_id"], "abandoned", reason)
            result = {"ack": "ACK", "checkpoint": "abandoned", "request_id": component["request_id"]}
        else:
            component = {**component, "status": "preparing", "intent": intent}
            result = {"ack": "ACK", "checkpoint": "preparing", "request_id": component["request_id"]}
            should_publish = True
    document["components"][COMPONENT] = component
    receipt_result = runtime.journal.commit(player, operation_id, request, expected_revision=stage.journal_revision,
        state=document, commands=commands, result=result,
        records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}],
        acknowledgements=[{"player": player, "command_id": request["command_id"], "outcome": "ACK", "receipt": receipt}])
    if component["status"] != "collecting":
        _clear_collect_watch(runtime, component["request_id"])
    if should_publish:
        images = {p: bytes.fromhex(component["uploads"][p]["cart_hex"]) for p in ("a", "b")}
        _publish_and_confirm_or_abandon(runtime, component["request_id"], images, intent, rules_bytes, identity_bytes)
    return receipt_result.result


def _record_refusal(runtime, stage, document, player, operation_id, request, receipt, component):
    """A player's client refused to complete the upload (digest mismatch, an unsafe-hold
    timeout, or its own identity changing underneath it). Never an upload: abandons the whole
    request and releases both players in the SAME commit as this refusal's own ACK."""
    _validate_issued_command(runtime, player, request, component, cmd="checkpoint_upload")
    witness = component["witnesses"][player]
    if receipt["witness"] != witness:
        raise JournalError("checkpoint upload witness differs from the pinned witness")
    refused = receipt["refused"]
    reason = f"player {player} refused ({refused['code']}): {refused['reason']}"
    component = {**component, "status": "abandoned", "abandoned_reason": reason[:500],
        "refusals": {**component["refusals"], player: {"code": refused["code"], "reason": refused["reason"]}}}
    document["components"][COMPONENT] = component
    result = runtime.journal.commit(player, operation_id, request, expected_revision=stage.journal_revision,
        state=document, commands=_release_commands(component["request_id"], "abandoned", reason),
        result={"ack": "ACK", "checkpoint": "abandoned", "request_id": component["request_id"]},
        records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}],
        acknowledgements=[{"player": player, "command_id": request["command_id"], "outcome": "ACK", "receipt": receipt}])
    _clear_collect_watch(runtime, component["request_id"])
    return result.result


def record_release(runtime, player, operation_id, request):
    """Typed completion of the read-only `checkpoint_release` command: `{request_id, outcome}`.
    Marks that player's release delivered; no other state changes (the request already settled
    by the time a release is ever issued). Stale/wrong-request releases refuse without any
    mutation, never clearing the current hold."""
    previous = runtime.journal.event(player, operation_id, request)
    if previous is not None:
        return previous.result
    _validate_completion_envelope(request)
    receipt = request["receipt"]
    if not isinstance(receipt, dict) or set(receipt) != RELEASE_RECEIPT_FIELDS or not _valid_request_id(receipt.get("request_id")):
        raise JournalError("checkpoint release receipt is incomplete")
    check_collect_timeout(runtime)
    stage = runtime.state()
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None or receipt["request_id"] != component["request_id"]:
        raise JournalError("no matching checkpoint request for this release")
    _validate_issued_command(runtime, player, request, component, cmd="checkpoint_release")
    if component["status"] not in TERMINAL_STATUSES or receipt["outcome"] != component["status"]:
        raise JournalError("checkpoint release outcome differs from the request's resolution")
    component = {**component, "releases": {**component["releases"], player: True}}
    document["components"][COMPONENT] = component
    result = runtime.journal.commit(player, operation_id, request, expected_revision=stage.journal_revision,
        state=document, commands={"a": [], "b": []}, result={"ack": "ACK"},
        records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}],
        acknowledgements=[{"player": player, "command_id": request["command_id"], "outcome": "ACK", "receipt": receipt}])
    return result.result


def _build_intent(runtime, stage, document, *, witnesses, provenance, save_sha256):
    """Re-validated fresh right before preparing (F1/F5/F6, never inferred from a successful
    first upload): the startup source pin, both witnesses' batch-tail and no-gameplay-since,
    and — if this request pinned one at start() — that current rules/identity still match it
    (defense in depth beyond no_gameplay_since's per-player event scan). Returns (intent,
    rules_bytes, identity_bytes) — intent binds the FULL archive identity (F3): both
    witnesses, both saves' sha256, rules/identity sha256, contract/source fingerprints,
    provenance — everything `_confirm`/`reconcile_on_open` must match exactly against the
    store's own manifest before ever confirming."""
    manifest = _check_source_pin(runtime)
    for player in ("a", "b"):
        witness = witnesses[player]
        if not witness_ends_its_batch(document, player, witness):
            raise JournalError(f"gameplay committed in the same batch as player {player}'s checkpoint witness")
        anchor = checkpoint_anchor_operation(witness)
        if not no_gameplay_since(runtime.journal, player, anchor, extra_events=CHECKPOINT_EVENTS):
            raise JournalError(f"gameplay committed for player {player} since its checkpoint witness")
    rules_bytes = _encode(stage.rules.document())[0].encode("ascii")
    identity_bytes = _encode(known_keys(document, stage.rules.document()))[0].encode("ascii")
    rules_sha256 = hashlib.sha256(rules_bytes).hexdigest()
    identity_sha256 = hashlib.sha256(identity_bytes).hexdigest()
    pin = document["components"].get(COMPONENT, {}).get("pin")
    if pin is not None and (pin["rules_sha256"] != rules_sha256 or pin["identity_sha256"] != identity_sha256):
        raise JournalError("rules/identity state changed since this checkpoint request started")
    intent = {"contract_fingerprint": digest(runtime.contract), "source_fingerprint": digest(manifest),
        "rules_sha256": rules_sha256, "identity_sha256": identity_sha256,
        "save_sha256": dict(save_sha256), "witnesses": copy.deepcopy(witnesses), "provenance": copy.deepcopy(provenance)}
    return intent, rules_bytes, identity_bytes


def _publish_and_confirm_or_abandon(runtime, request_id, images, intent, rules_bytes, identity_bytes):
    """The publish half of the already-durable "preparing" state: capture, then confirm. An
    EXPECTED failure (CheckpointError from the store's own validation, or a JournalError from
    an intent/manifest mismatch) abandons durably with a reason. An UNEXPECTED failure (a raw
    OSError, or anything else) is deliberately left as "preparing" — `reconcile_on_open`
    resolves it on the next open rather than guessing here. Either way, this failure is never
    raised back into the completing upload's own response — that upload already succeeded."""
    try:
        manifest = PairedCheckpointStore(runtime.data_dir).capture(
            players={p: {"save": images[p], "witness": intent["witnesses"][p]} for p in ("a", "b")},
            rules=rules_bytes, identity=identity_bytes, contract_fingerprint=intent["contract_fingerprint"],
            source_fingerprint=intent["source_fingerprint"], provenance=intent["provenance"], allow_same_batch=True)
        _confirm(runtime, request_id, intent, manifest)
    except (CheckpointError, JournalError) as error:
        _abandon(runtime, request_id, str(error))


def finalize_checkpoint(runtime, *, images, witnesses, provenance, request_id):
    """Journal a prepared intent, publish the archive, then journal the confirmed checkpoint —
    callable directly (bypassing `start`/`record`) by a caller (R5b/N3) that already has its
    own two full-save images and per-kind witnesses. This IS "start" for that direct caller:
    the source pin and request_id-reuse checks run up front exactly as `start()` runs them.
    Every expected failure (source drift, no-gameplay-since, an intent/manifest mismatch, or a
    CheckpointError from the store) both raises (to this synchronous caller) AND abandons
    durably; an unexpected one (a raw OSError) is left as a recoverable "preparing"."""
    if set(images) != {"a", "b"} or set(witnesses) != {"a", "b"}:
        raise JournalError("finalize_checkpoint requires both players' images and witnesses")
    if not _valid_request_id(request_id):
        raise JournalError("checkpoint request_id must be 1-64 characters of [A-Za-z0-9_.-]")
    stage = runtime.state()
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is not None and component["request_id"] != request_id and not _request_settled(component):
        raise JournalError("another checkpoint request is already in progress")
    if component is not None and component["status"] == "confirmed" and (component["confirmed"] or {}).get("request_id") == request_id:
        return component["confirmed"]
    used = component["used_request_ids"] if component else []
    if component is None or component["request_id"] != request_id:
        if request_id in used:
            raise JournalError("checkpoint request_id has already been used on this run")
        _check_source_pin(runtime)
        component = {"schema": SCHEMA, "request_id": request_id,
            "registry_run_id": component["registry_run_id"] if component else None,
            "status": "collecting", "started_at": time.time(), "witnesses": copy.deepcopy(witnesses),
            "bindings": {"a": None, "b": None}, "pin": None,
            "uploads": dict.fromkeys(("a", "b")), "refusals": dict.fromkeys(("a", "b")),
            "releases": {"a": False, "b": False},
            "confirmed": component["confirmed"] if component else None, "intent": None,
            "abandoned_reason": None, "used_request_ids": _with_used_id(used, request_id)}
        document["components"][COMPONENT] = component
        op = secrets.token_hex(16)
        runtime.journal.commit("a", op, {"event": "checkpoint_start", "request_id": request_id},
            expected_revision=stage.journal_revision, state=document, commands={"a": [], "b": []},
            result={"ack": "ACK"}, records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])
        stage = runtime.state()
        document = stage.document()
    try:
        save_sha256 = {p: hashlib.sha256(images[p]).hexdigest() for p in ("a", "b")}
        intent, rules_bytes, identity_bytes = _build_intent(runtime, stage, document,
            witnesses=witnesses, provenance=provenance, save_sha256=save_sha256)
    except JournalError as error:
        _abandon(runtime, request_id, str(error))
        raise JournalError(f"paired checkpoint finalize failed: {error}") from error
    component = {**document["components"][COMPONENT], "status": "preparing", "intent": intent}
    document["components"][COMPONENT] = component
    op = secrets.token_hex(16)
    runtime.journal.commit("a", op, {"event": "checkpoint_prepare", "request_id": request_id},
        expected_revision=stage.journal_revision, state=document, commands={"a": [], "b": []},
        result={"ack": "ACK"}, records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])
    try:
        manifest = PairedCheckpointStore(runtime.data_dir).capture(
            players={p: {"save": images[p], "witness": witnesses[p]} for p in ("a", "b")},
            rules=rules_bytes, identity=identity_bytes, contract_fingerprint=intent["contract_fingerprint"],
            source_fingerprint=intent["source_fingerprint"], provenance=provenance, allow_same_batch=True)
    except CheckpointError as error:
        _abandon(runtime, request_id, str(error))
        raise JournalError(f"paired checkpoint capture failed: {error}") from error
    return _confirm(runtime, request_id, intent, manifest)


def _manifest_sha256(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")).hexdigest()


def _intent_matches_manifest(intent, manifest):
    """F3: the archive `_confirm` is about to bless must be EXACTLY the one `intent` describes —
    not merely "some archive naming the same request_id"."""
    return (manifest["contract_fingerprint"] == intent["contract_fingerprint"]
        and manifest["source_fingerprint"] == intent["source_fingerprint"]
        and manifest["rules_sha256"] == intent["rules_sha256"]
        and manifest["identity_sha256"] == intent["identity_sha256"]
        and manifest["players"]["a"]["save_sha256"] == intent["save_sha256"]["a"]
        and manifest["players"]["b"]["save_sha256"] == intent["save_sha256"]["b"]
        and manifest["players"]["a"]["witness"] == intent["witnesses"]["a"]
        and manifest["players"]["b"]["witness"] == intent["witnesses"]["b"]
        and manifest["provenance"] == intent["provenance"])


def _confirm(runtime, request_id, intent, manifest):
    if not _intent_matches_manifest(intent, manifest):
        raise JournalError("store archive does not match the prepared checkpoint intent")
    stage = runtime.state()
    document = stage.document()
    component = document["components"][COMPONENT]
    confirmed = {"checkpoint_id": manifest["checkpoint_id"], "manifest_sha256": _manifest_sha256(manifest),
        "request_id": request_id}
    component = {**component, "status": "confirmed", "confirmed": confirmed, "abandoned_reason": None,
        "releases": {"a": False, "b": False}}
    document["components"][COMPONENT] = component
    op = secrets.token_hex(16)
    runtime.journal.commit("a", op, {"event": "checkpoint_confirm", "request_id": request_id,
        "checkpoint_id": manifest["checkpoint_id"]},
        expected_revision=stage.journal_revision, state=document,
        commands=_release_commands(request_id, "confirmed", None),
        result={"ack": "ACK", "checkpoint_id": manifest["checkpoint_id"]},
        records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])
    _clear_collect_watch(runtime, request_id)
    return confirmed


def _abandon(runtime, request_id, reason):
    """No-op if REQUEST_ID is no longer the tracked (or is already terminal) request — every
    caller (a failed publish, a collection timeout, reconciliation on reopen) may race a
    concurrent resolution, and only the first to land should mutate anything."""
    stage = runtime.state()
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None or component["request_id"] != request_id or component["status"] not in BUSY_STATUSES:
        return
    reason = str(reason)[:500]
    component = {**component, "status": "abandoned", "abandoned_reason": reason, "releases": {"a": False, "b": False}}
    document["components"][COMPONENT] = component
    op = secrets.token_hex(16)
    runtime.journal.commit("a", op, {"event": "checkpoint_abandon", "request_id": request_id, "reason": reason},
        expected_revision=stage.journal_revision, state=document,
        commands=_release_commands(request_id, "abandoned", reason),
        result={"ack": "ACK"}, records=[{"namespace": COMPONENT, "key": KEY, "value": copy.deepcopy(component)}])
    _clear_collect_watch(runtime, request_id)


def reconcile_on_open(runtime):
    """Cross-store reconciliation at every reopen (R5b spec (2)): a "preparing" intent with no
    matching journal confirmation is resolved against the store's own CURRENT — confirmed now
    ONLY if `current()` exists and matches the intent EXACTLY (F3, via `_confirm`'s own check),
    abandoned otherwise. A "collecting" request resumes its original deadline, or is abandoned
    immediately if it already expired. Either way the previously confirmed checkpoint (if any)
    is untouched."""
    stage = runtime.state()
    document = stage.document()
    component = document["components"].get(COMPONENT)
    if component is None:
        return
    if component["status"] == "collecting":
        deadline = component["started_at"] + CHECKPOINT_COLLECT_SECONDS
        if time.time() >= deadline:
            _abandon(runtime, component["request_id"], "collect_timeout")
        else:
            _set_collect_watch(runtime, component["request_id"], component["started_at"])
        return
    if component["status"] != "preparing" or component.get("intent") is None:
        return
    intent = component["intent"]
    try:
        current = PairedCheckpointStore(runtime.data_dir).current()
    except CheckpointError:
        current = None
    if current is not None and current["provenance"].get("request_id") == component["request_id"]:
        try:
            _confirm(runtime, component["request_id"], intent, current)
            return
        except JournalError:
            pass  # exists, but doesn't match the intent (F3) -- fall through to abandon
    _abandon(runtime, component["request_id"], "no matching confirmed archive found on reopen")


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
            or set(component) != {"schema", "request_id", "registry_run_id", "status", "started_at",
                                   "witnesses", "bindings", "pin", "uploads", "refusals", "releases",
                                   "confirmed", "intent", "abandoned_reason", "used_request_ids"}
            or component["schema"] != SCHEMA or not isinstance(component["request_id"], str) or not component["request_id"]
            or component["status"] not in STATUSES or set(component["witnesses"]) != {"a", "b"}
            or set(component["bindings"]) != {"a", "b"} or set(component["uploads"]) != {"a", "b"}
            or set(component["refusals"]) != {"a", "b"} or set(component["releases"]) != {"a", "b"}
            or not isinstance(component["used_request_ids"], list) or component["request_id"] not in component["used_request_ids"]):
        raise JournalError("invalid checkpoint component")
    for player in ("a", "b"):
        binding = component["bindings"][player]
        if binding is not None and (not isinstance(binding, dict)
                or set(binding) != {"context_generation", "physical_instance", "final_sha1"}):
            raise JournalError("invalid checkpoint binding record")
        upload = component["uploads"][player]
        if upload is not None and (not isinstance(upload, dict)
                or set(upload) != {"command_id", "frame", "cart_hex", "full_sha256"}):
            raise JournalError("invalid checkpoint upload record")
        refusal = component["refusals"][player]
        if refusal is not None and (not isinstance(refusal, dict) or set(refusal) != {"code", "reason"}):
            raise JournalError("invalid checkpoint refusal record")
    if component["pin"] is not None and (not isinstance(component["pin"], dict)
            or set(component["pin"]) != {"rules_sha256", "identity_sha256"}):
        raise JournalError("invalid checkpoint pin record")
    if component["confirmed"] is not None and (
            not isinstance(component["confirmed"], dict)
            or set(component["confirmed"]) != {"checkpoint_id", "manifest_sha256", "request_id"}):
        raise JournalError("invalid checkpoint confirmation record")
    if component["intent"] is not None and (
            not isinstance(component["intent"], dict)
            or set(component["intent"]) != {"contract_fingerprint", "source_fingerprint", "rules_sha256",
                                              "identity_sha256", "save_sha256", "witnesses", "provenance"}):
        raise JournalError("invalid checkpoint intent record")
