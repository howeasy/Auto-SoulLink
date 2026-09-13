"""Native window progress for a command: live in-memory first, else the exact durable record.

`NativeExecutionPolicy.observed` is the progress of the windows a live process verified. After
a reopen it is empty, and the verification steps that need it (the verified-file check in
`NativeTradePolicy.verified`, the full-save receipt in `gen1_full_save.verify_receipt`) used to
refuse with "outside the owned native frame window" even though the same progress had been
journaled by gen1_native_windows in the grant's own commit. This reads that record back in
the exact shape the live cache has, for runtimes that selected free_service and native_trade,
and refuses anything that is not a complete, digest-bound window for that command. It grants
nothing and never fabricates progress: no live cache and no durable record means no window.
"""

from server.protocol_journal import JournalError

LIVE = frozenset({"process_id", "frame", "steps", "start", "intent_digest", "armed", "sequence_length"})


def enrolled_host(document, player):
    """The physical host the player enrolled with (gen1-initial-observations): its emulator process,
    physical instance and context generation; None before enrollment."""
    initial = document["components"].get("gen1-initial-observations", {}).get(player)
    if initial is None:
        return None
    return {"process_id": initial["observation"]["host"]["process_id"],
            "physical_instance": initial["metadata"]["gen1_metadata"]["physical_instance"],
            "context_generation": initial["binding"]["context_generation"]}


def durable_progress(runtime, player, command_id, binding):
    """The observed-shaped progress from the durable window record, or None.

    Frames are meaningful only inside the emulator process that ran the window, so the record
    is usable only while the player's enrolled host (the initial observation: process, physical
    instance, context generation, the same identity every held write is bound to) is the host
    the window was issued to AND the host of the player's CURRENT admission: `binding` must be
    the admitted control binding. The enrollment host and the window host are both historical
    values, so on their own they still agree after an emulator replacement; the current
    admission is what changes. A restarted emulator or client gets no window from here: its
    frame counter restarted too, and an old window must never bound a NEW flush. The receipt this authorizes is therefore
    only the one produced inside that window (verified() additionally requires it to equal the
    journaled applied receipt); a later flush falls outside the frame range and is refused.
    """
    if getattr(runtime, "free_service", False) is not True or getattr(runtime, "native_trade", False) is not True:
        return None
    from server.gen1_native_windows import ENTRY, windows_for

    document = runtime.state().document()
    entry = windows_for(document, player).get(command_id)
    if entry is None:
        return None
    if set(entry) != ENTRY or entry["scope"].get("operation_id") != command_id:
        raise JournalError("durable native window is incomplete for this command")
    if runtime.journal.command(player, command_id)["command_id"] != command_id:
        raise JournalError("durable native window names a command the journal never issued")
    admission = document["components"]["gen1-runtime"]["admissions"].get(player)
    if admission is None or admission["binding"] != {k: binding[k] for k in ("binding_digest", "context_generation")}:
        return None  # not the current admission: no window, fail closed
    enrolled = enrolled_host(document, player)
    if enrolled is None:
        return None  # never enrolled: nothing binds a process to this player
    # The current admission must still be the enrolled physical host: same context generation as
    # the enrollment AND as the window, same physical instance (the context generation is a
    # client-supplied nonce; a replaced emulator that replays it still presents a new instance).
    if (binding["context_generation"] != enrolled["context_generation"]
            or entry["scope"]["context_generation"] != enrolled["context_generation"]
            or admission["metadata"]["gen1_metadata"]["physical_instance"] != enrolled["physical_instance"]
            or entry["host"]["process_id"] != enrolled["process_id"]):
        return None  # another emulator, client or process: no window, fail closed
    return {"process_id": entry["host"]["process_id"], "frame": entry["host"]["frame"], "steps": entry["host"]["steps"],
            "start": entry["start"], "intent_digest": entry["intent_digest"], "armed": entry["armed"],
            "sequence_length": entry["sequence_length"], **entry["extra"], "durable": True}


def progress_for(policy, player, command_id, binding):
    """Live progress for (player, command, binding) when this process verified the window;
    else the durable record when the runtime retained one; else None."""
    live = policy.observed.get((player, command_id, binding["binding_digest"]))
    if live is not None:
        return live
    if policy.runtime is None:
        return None
    return durable_progress(policy.runtime, player, command_id, binding)
