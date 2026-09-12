"""Durable initial-save obligation after normal new-game bootstrap.

This lifecycle preserves all initial/recovery holds. Its only write authority is
an exact fixed-frame, command-scoped image/repair/flush permit.
"""

import copy

from server.admission_context import same_admitted_context
from server.gen1_initial_save import prepare, verify_receipt, wire_payload
from server.gen1_save_delta import recover_point
from server.held_write_permit import VerifiedHeldWrite
from server.operation_scope import command_scope
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier

COMPONENT = "gen1-initial-save"
BOOTSTRAP = "gen1-new-game-bootstrap"
INITIAL = "gen1-initial-observations"
EVIDENCE = "rby-held-initial-save-evidence-v1"
FIELDS = {"bootstrap_operation", "origin", "payload", "receipt_operation", "receipt_digest"}


def record_key(player):
    return digest({"component": COMPONENT, "player": player})[:32]


def arguments(document, player):
    initial = document["components"].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError("initial save requires immutable enrollment")
    return {
        "identity": initial["metadata"]["save_identity"],
        "context_generation": initial["binding"]["context_generation"],
        "final_sha1": initial["metadata"]["gen1_metadata"]["cartridge"]["final_rom_sha1"],
        "frame": initial["observation"]["frame"],
    }


def prepared(document, player):
    return prepare(
        document["components"][INITIAL][player]["observation"]["source"],
        **arguments(document, player),
    )


def body(entry):
    return {"cmd": "initial_save", "payload": entry["payload"]}


def schedule(document, origin_player, operation):
    """Schedule only after both immutable initial observations are established."""
    commands, records = {"a": [], "b": []}, []
    if set(document["components"].get(INITIAL, {})) != {"a", "b"}:
        return commands, records
    bootstraps = document["components"].get(BOOTSTRAP, {})
    if not bootstraps:
        return commands, records
    entries = document["components"].setdefault(COMPONENT, {})
    for player, bootstrap in bootstraps.items():
        if player in entries:
            continue
        entry = {
            "bootstrap_operation": bootstrap["operation_id"],
            "origin": {"player": origin_player, "operation_id": operation},
            "payload": wire_payload(prepared(document, player)),
            "receipt_operation": None,
            "receipt_digest": None,
        }
        entries[player] = entry
        commands[player].append(body(entry))
        records.append(
            {"namespace": COMPONENT, "key": record_key(player), "value": copy.deepcopy(entry)}
        )
    return commands, records


def verify_state(stage):
    document = stage.document()
    entries = document["components"].get(COMPONENT, {})
    bootstraps = document["components"].get(BOOTSTRAP, {})
    required = (
        set(bootstraps) if set(document["components"].get(INITIAL, {})) == {"a", "b"} else set()
    )
    if not isinstance(entries, dict) or set(entries) != required:
        raise JournalError("bootstrap and initial-save obligations differ")
    for player, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != FIELDS:
            raise JournalError("complete initial-save obligation required")
        origin = entry["origin"]
        if (
            not isinstance(origin, dict)
            or set(origin) != {"player", "operation_id"}
            or origin["player"] not in ("a", "b")
        ):
            raise JournalError("initial-save scheduling origin required")
        _identifier(origin["operation_id"])
        origins = [
            document["components"].get(component, {}).get(origin["player"], {}).get("operation_id")
            for component in (INITIAL, BOOTSTRAP)
        ]
        if origin["operation_id"] not in origins:
            raise JournalError("initial-save origin is not its enrollment or bootstrap event")
        if entry["bootstrap_operation"] != bootstraps[player]["operation_id"]:
            raise JournalError("initial-save bootstrap origin differs")
        if entry["payload"] != wire_payload(prepared(document, player)):
            raise JournalError("initial save differs from immutable enrollment image")
        if entry["receipt_operation"] is None:
            if entry["receipt_digest"] is not None:
                raise JournalError("initial-save receipt digest has no committed event")
        else:
            _identifier(entry["receipt_operation"])
            if not isinstance(entry["receipt_digest"], str) or len(entry["receipt_digest"]) != 64:
                raise JournalError("initial-save receipt digest required")


def original_command(journal, player, entry):
    origin = journal.event_snapshot(entry["origin"]["player"], entry["origin"]["operation_id"])
    if origin is None or len(origin.command_ids) != 1:
        raise JournalError("initial save lacks its unique bootstrap command")
    command = journal.command(player, origin.command_ids[0])
    if command["body"] != body(entry):
        raise JournalError("initial-save command differs from its original preparation")
    return command


def verify_journal(journal, stage):
    document = stage.document()
    entries = document["components"].get(COMPONENT, {})
    for player in ("a", "b"):
        stored = journal.record(COMPONENT, record_key(player))
        entry = entries.get(player)
        if (stored is None) != (entry is None) or stored is not None and stored.value != entry:
            raise JournalError("initial-save component differs from its atomic record")
        if entry is None:
            continue
        command = original_command(journal, player, entry)
        if entry["receipt_operation"] is None:
            origin = journal.event_snapshot(
                entry["origin"]["player"], entry["origin"]["operation_id"]
            )
            if command["outcome"] is not None or stored.revision != origin.revision:
                raise JournalError("pending initial save differs from its bootstrap commit")
            continue
        event = journal.event_snapshot(player, entry["receipt_operation"])
        if (
            event is None
            or event.revision != stored.revision
            or event.result != {"ack": "ACK"}
            or event.command_ids
        ):
            raise JournalError("initial-save completion lacks its exact committed event")
        expected_message = {
            "event": "command_ack",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "outcome": "ACK",
            "receipt": command["receipt"],
        }
        if (
            command["outcome"] != "ACK"
            or event.request != expected_message
            or digest(command["receipt"]) != entry["receipt_digest"]
        ):
            raise JournalError("initial-save receipt differs from its command acknowledgement")
        verify_receipt(
            command,
            command["receipt"],
            prepared(document, player)["before"],
            **arguments(document, player),
        )


def acknowledge(runtime, player, operation, message):
    old = runtime.journal.event(player, operation, message)
    if old is not None:
        return old.result
    if (
        set(message) != {"event", "command_id", "command_sequence", "outcome", "receipt"}
        or message["event"] != "command_ack"
        or message["outcome"] != "ACK"
    ):
        raise JournalError("typed initial-save acknowledgement required")
    stage = runtime.state()
    document = stage.document()
    entry = document["components"].get(COMPONENT, {}).get(player)
    if entry is None or entry["receipt_operation"] is not None:
        raise JournalError("one pending initial-save obligation required")
    command = original_command(runtime.journal, player, entry)
    pending = runtime.journal.pending_ids(player)
    if (
        not pending
        or pending[0] != command["command_id"]
        or message["command_id"] != command["command_id"]
        or type(message["command_sequence"]) is not int
        or message["command_sequence"] != command["command_sequence"]
    ):
        raise JournalError("initial-save acknowledgement must own the oldest exact command")
    initial = document["components"][INITIAL][player]
    if not same_admitted_context(initial["metadata"], runtime.gate.sessions[player].metadata):
        raise JournalError("initial-save physical context changed; reconciliation required")
    verify_receipt(
        command, message["receipt"], initial["observation"]["source"], **arguments(document, player)
    )
    entry["receipt_operation"] = operation
    entry["receipt_digest"] = digest(message["receipt"])
    return runtime.journal.commit(
        player,
        operation,
        message,
        expected_revision=stage.journal_revision,
        state=document,
        commands={"a": [], "b": []},
        result={"ack": "ACK"},
        records=[{"namespace": COMPONENT, "key": record_key(player), "value": entry}],
        acknowledgements=[
            {
                "player": player,
                "command_id": command["command_id"],
                "outcome": "ACK",
                "receipt": message["receipt"],
            }
        ],
    ).result


def verify_operation(player, command, evidence, document, binding):
    from server.gen1_held_faint import verify_owned_checkpoint

    if (
        not isinstance(evidence, dict)
        or set(evidence)
        != {
            "schema",
            "command_id",
            "command_sequence",
            "context_generation",
            "final_sha1",
            "host",
            "checkpoint",
            "intent",
            "current",
            "phase",
        }
        or evidence["schema"] != EVIDENCE
    ):
        raise JournalError("complete held initial-save evidence required")
    verify_owned_checkpoint(player, command, evidence, document, binding)
    entry = document["components"].get(COMPONENT, {}).get(player)
    if (
        entry is None
        or entry["receipt_operation"] is not None
        or command["body"] != body(entry)
        or evidence["host"]["frame"] != arguments(document, player)["frame"]
        or evidence["intent"]
        != {"schema": "rby-initial-save-intent-v1", "body_digest": digest(command["body"])}
    ):
        raise JournalError("initial-save evidence differs from its owned preparation")
    payload = prepared(document, player)
    phase, current = evidence["phase"], evidence["current"]
    if phase == "initial_save_repair":
        recover_point(current, entry["payload"])
    elif phase in ("initial_save", "initial_save_flush"):
        if current != payload["before" if phase == "initial_save" else "after"]:
            raise JournalError("initial-save phase differs from physical image")
    else:
        raise JournalError("unknown initial-save permission phase")
    return VerifiedHeldWrite(
        command_scope(command, binding, phase=phase), digest(evidence), 1000, digest(document)
    )
