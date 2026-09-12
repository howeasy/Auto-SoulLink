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
    if not runtime.free_service or runtime.native_trade:
        raise JournalError("service continuity is limited to non-trade RBY free service")
    if not isinstance(evidence, dict) or set(evidence) != FIELDS or evidence.get("schema") != SCHEMA:
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

    point = evidence["inventory"]
    current = validate(point, metadata, initial["binding"])
    expected = validate(latest, initial["metadata"], initial["binding"])
    if _inventory_semantics(current) != _inventory_semantics(expected):
        raise JournalError("service continuity inventory differs from the last committed checkpoint")
    if (point["host"] != initial["observation"]["host"]
            or point["frame"] != idle["source_frame"]
            or point["frame"] < cursor["frame"]):
        raise JournalError("service continuity host or frame changed")
    return digest(copy.deepcopy(evidence))
