"""Source-qualified normal New Game enrollment evidence. This grants nothing.

Each player's proof binds one bootstrap receipt to that player's immutable initial
observation: the same admitted physical instance, context and cartridge, a normal
StartNewGame entry/return witnessed at or before the enrollment frame, and the same
still-empty save. Initial and recovery blockers stay in force, no frames are granted
and SaveRAM ownership is not asserted. A later frame-authority binding may require
this record; it must not be inferred from it.
"""

import copy

from server.admission_context import same_admitted_context
from server.gen1_bootstrap_receipt import validate
from server.gen1_initial_observation import COMPONENT as INITIAL
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier

COMPONENT = "gen1-new-game-bootstrap"
EVENT = "bootstrap_observation"
FIELDS = {"operation_id", "payload", "proof"}


def record_key(player):
    return digest({"component": COMPONENT, "player": player})[:32]


def message(entry):
    return {"event": EVENT, "payload": entry["payload"]}


def result(entry):
    return {
        "ack": "ACK",
        "bootstrap_proof_digest": digest(entry["proof"]),
        "ordinary_execution": False,
    }


def proof(payload, initial):
    """Tie a receipt to the player's immutable enrollment, never to live state."""
    metadata = initial["metadata"]
    cartridge = metadata["gen1_metadata"]["cartridge"]
    return validate(
        payload,
        variant=cartridge["variant"],
        identity=metadata["save_identity"],
        context_generation=initial["binding"]["context_generation"],
        physical_instance=metadata["gen1_metadata"]["physical_instance"],
        final_sha1=cartridge["final_rom_sha1"],
        source=initial["observation"]["source"],
        frame=initial["observation"]["frame"],
    )


def verify_entry(entry, initial):
    if not isinstance(entry, dict) or set(entry) != FIELDS:
        raise JournalError("complete new-game bootstrap record required")
    _identifier(entry["operation_id"])
    if entry["proof"] != proof(entry["payload"], initial):
        raise JournalError("bootstrap proof differs from its enrollment evidence")


def verify_state(stage):
    document = stage.document()
    entries = document["components"].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries) - {"a", "b"}:
        raise JournalError("invalid new-game bootstrap component")
    for player, entry in entries.items():
        initial = document["components"].get(INITIAL, {}).get(player)
        if initial is None:
            raise JournalError("bootstrap enrollment requires its initial observation")
        verify_entry(entry, initial)


def verify_journal(journal, stage):
    entries = stage.document()["components"].get(COMPONENT, {})
    for player in ("a", "b"):
        stored = journal.record(COMPONENT, record_key(player))
        entry = entries.get(player)
        if (stored is None) != (entry is None) or stored is not None and stored.value != entry:
            raise JournalError("bootstrap component differs from its atomic journal record")
        if entry is not None:
            receipt = journal.event(player, entry["operation_id"], message(entry))
            if (
                receipt is None
                or receipt.result != result(entry)
                or receipt.revision != stored.revision
            ):
                raise JournalError("bootstrap enrollment lacks its exact committed event")


def record(runtime, player, operation, request):
    previous = runtime.journal.event(player, operation, request)
    if previous is not None:
        return previous.result
    if set(request) != {"event", "payload"} or request["event"] != EVENT:
        raise JournalError("typed bootstrap observation required")
    stage = runtime.state()
    document = stage.document()
    initial = document["components"].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError("bootstrap enrollment requires its initial observation")
    if not same_admitted_context(initial["metadata"], runtime.gate.sessions[player].metadata):
        raise JournalError("bootstrap context changed; reconciliation required")
    entries = document["components"].setdefault(COMPONENT, {})
    if player in entries:
        raise JournalError("bootstrap enrollment is immutable; replacement requires reconciliation")
    entry = {
        "operation_id": operation,
        "payload": copy.deepcopy(request["payload"]),
        "proof": proof(request["payload"], initial),
    }
    verify_entry(entry, initial)
    entries[player] = entry
    from server.gen1_initial_save_runtime import schedule
    commands, save_records = schedule(document, player, operation)
    # Only the initial-save obligation is queued; all recovery holds remain.
    receipt = runtime.journal.commit(
        player,
        operation,
        request,
        expected_revision=stage.journal_revision,
        state=document,
        commands=commands,
        result=result(entry),
        records=[{"namespace": COMPONENT, "key": record_key(player), "value": entry}, *save_records],
    )
    return receipt.result
