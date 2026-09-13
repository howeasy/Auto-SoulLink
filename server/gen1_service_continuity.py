"""Narrow same-process idle continuity proof for the RBY free service.

This admits no recovery frames and repairs no state.  It only proves that an
already-held client still owns the exact enrolled BizHawk process, cartridge,
save and last acknowledged observation, with no outstanding transport,
physical or battle work.
"""

import copy
import re

from server.gen1_initial_observation import COMPONENT as INITIAL, validate
from server.gen1_inventory_observation import COMPONENT as INVENTORY
from server.gen1_observation_runtime import COMPONENT as PROGRESS
from server.gen1_trade_recovery import transactions
from server.protocol import canonical_json, digest
from server.protocol_journal import JournalError

SCHEMA = "rby-free-service-continuity-v1"
FIELDS = {
    "schema",
    "service_epoch",
    "binding_digest",
    "initial_operation_id",
    "cursor",
    "inventory",
    "idle",
}
OPTIONAL = {"pending_inventory_retry", "native"}
NATIVE = {"lease_phase", "host_armed", "host_failure"}
CURSOR = {"sequence", "operation_id", "frame"}
IDLE = {
    "pending_events",
    "pending_commands",
    "acquisition_open",
    "acquisition_pending",
    "engine_pending",
    "instruction_open",
    "instruction_armed",
    "battle",
    "source_frame",
}
RETRY = {"operation_id", "sequence", "frame"}
MAX_INT = 2**53 - 1


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise JournalError(f"invalid service continuity {label}")
    return value


def _latest_inventory(document, player):
    initial = document["components"].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError("service continuity requires immutable initial identity")
    latest = document["components"].get(INVENTORY, {}).get(player)
    point = latest["observation"] if latest is not None else initial["observation"]
    return initial, point


def _inventory_semantics(value):
    return {name: copy.deepcopy(value[name]) for name in (
        "party_count", "current_box", "boxes_initialized", "members", "boxes"
    )}


def verify(runtime, player, evidence, stage, binding):
    if not runtime.free_service:
        raise JournalError("service continuity is limited to RBY free service")
    if not isinstance(evidence, dict) or set(evidence) - OPTIONAL != FIELDS or evidence.get("schema") != SCHEMA:
        raise JournalError("typed RBY free-service continuity proof required")
    if evidence["service_epoch"] != runtime._service_epoch:
        raise JournalError("service continuity proof refers to a stale service epoch")
    if evidence["binding_digest"] != binding["binding_digest"]:
        raise JournalError("service continuity proof differs from the current admission")
    if set(runtime.gate.sessions) != {"a", "b"}:
        raise JournalError("paired admission is required for service continuity")

    document = stage.document()
    initial, latest = _latest_inventory(document, player)
    if evidence["initial_operation_id"] != initial["operation_id"]:
        raise JournalError("service continuity proof replaced the initial identity")
    metadata = runtime.gate.sessions[player].metadata
    admitted = {key: value for key, value in metadata.items() if key != "control_binding"}
    original = {key: value for key, value in initial["metadata"].items() if key != "control_binding"}
    if (canonical_json(admitted) != canonical_json(original)
            or binding["context_generation"] != initial["binding"]["context_generation"]):
        raise JournalError("service continuity admission differs from the initial physical identity")

    cursor = evidence["cursor"]
    progress = document["components"].get(PROGRESS, {}).get(player)
    expected_cursor = progress or {
        "sequence": 0,
        "operation_id": initial["operation_id"],
        "frame": initial["observation"]["frame"],
    }
    if (not isinstance(cursor, dict) or set(cursor) != CURSOR
            or canonical_json(cursor) != canonical_json(expected_cursor)):
        raise JournalError("service continuity cursor differs from the last committed observation")
    if (type(cursor["sequence"]) is not int or not 0 <= cursor["sequence"] <= MAX_INT
            or type(cursor["frame"]) is not int or not 0 <= cursor["frame"] <= MAX_INT):
        raise JournalError("invalid service continuity observation cursor")
    _identifier(cursor["operation_id"], "observation operation")

    idle = evidence["idle"]
    if not isinstance(idle, dict) or set(idle) != IDLE:
        raise JournalError("complete service continuity idle state required")
    zeros = ("pending_events", "pending_commands", "acquisition_pending", "engine_pending", "battle")
    if (any(type(idle[name]) is not int or idle[name] != 0 for name in zeros)
            or idle["acquisition_open"] is not False
            or idle["instruction_open"] is not False
            or idle["instruction_armed"] is not False
            or type(idle["source_frame"]) is not int
            or not 0 <= idle["source_frame"] <= MAX_INT):
        raise JournalError("service continuity requires an idle held client")
    if any(runtime.journal.pending_ids(participant) for participant in ("a", "b")):
        raise JournalError("durable commands prohibit service continuity")
    if document.get("active_trade") or any(
        entry.get("phase") not in {"cancelled", "completed"}
        for entry in transactions(document).values()
    ):
        raise JournalError("native trade state prohibits service continuity")
    if runtime.native_trade:
        # Terminal-only native continuity: the player's held start-of-script read must have been
        # accepted and released by the server (nothing published/armed/done, lease idle or released,
        # no pending native command, no open trade at that read); a missing or held read refuses.
        from server.gen1_native_reattach_runtime import COMPONENT as REATTACH
        entry = document["components"].get(REATTACH, {}).get(player)
        if entry is None:
            raise JournalError("native service continuity requires the accepted held reattach read")
        # The read must be THIS admission's held read: the control binding digest rotates on every
        # HELLO (the client's context generation does not, durable_runtime re-HELLOs the same entry), so
        # a released entry from an earlier session is not evidence about the current process until the
        # client republishes its read under the new binding.
        if (entry["binding_digest"] != binding["binding_digest"]
                or entry["context_generation"] != binding["context_generation"]):
            raise JournalError("native service continuity requires the current admission's held reattach read")
        if entry["verdict"] != "released" or entry["lease_phase"] not in {"idle", "released"} or entry["physical"] != "clean":
            raise JournalError("native service continuity requires a released idle reattach read")
        # And the client's own held statement of its native state now, not only the recorded read.
        native = evidence.get("native")
        if (not isinstance(native, dict) or set(native) != NATIVE
                or native["lease_phase"] not in {"idle", "released"} or native["host_armed"] is not False
                or native["host_failure"] is not None):
            raise JournalError("native service continuity requires an idle native lease and an unarmed, unfailed native host")
    elif "native" in evidence:
        raise JournalError("native continuity fields belong to the native-selected service")

    point = evidence["inventory"]
    current = validate(point, metadata, initial["binding"])
    expected = validate(latest, initial["metadata"], initial["binding"])
    retry = evidence.get("pending_inventory_retry")
    if retry is not None:
        if (not isinstance(retry, dict) or set(retry) != RETRY
                or type(retry["sequence"]) is not int or type(retry["frame"]) is not int
                or not 1 <= retry["sequence"] <= cursor["sequence"]
                or not 0 <= retry["frame"] <= cursor["frame"]):
            raise JournalError("invalid deferred inventory retry cursor")
        operation = _identifier(retry["operation_id"], "deferred inventory operation")
        receipt = runtime.journal.event_snapshot(player, operation)
        request = receipt.request if receipt is not None else None
        if (not isinstance(request, dict) or request.get("event") != "observation"
                or request.get("sequence") != retry["sequence"] or request.get("frame") != retry["frame"]
                or request.get("inventory") is None or receipt.result.get("inventory_deferred") is not True
                or request.get("context") != {
                    "context_generation": initial["binding"]["context_generation"],
                    "physical_instance": initial["metadata"]["gen1_metadata"]["physical_instance"],
                    "save_identity": initial["metadata"]["save_identity"],
                }):
            raise JournalError("service continuity retry lacks its exact deferred observation")
        recorded = document["components"].get(INVENTORY, {}).get(player)
        if recorded is not None:
            latest_receipt = runtime.journal.event_snapshot(player, recorded["operation_id"])
            if latest_receipt is None or latest_receipt.revision >= receipt.revision:
                raise JournalError("deferred retry predates the latest committed inventory")
        deferred = validate(request["inventory"], metadata, initial["binding"])
        if _inventory_semantics(current) != _inventory_semantics(deferred):
            raise JournalError("held inventory differs from its deferred physical witness")
    elif _inventory_semantics(current) != _inventory_semantics(expected):
        raise JournalError("service continuity inventory differs from the last committed checkpoint")
    if (point["host"] != initial["observation"]["host"]
            or point["frame"] != idle["source_frame"]
            or point["frame"] < cursor["frame"]):
        raise JournalError("service continuity host or frame changed")
    return digest(copy.deepcopy(evidence))
