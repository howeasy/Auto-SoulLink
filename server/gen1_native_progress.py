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


def enrolled_process(document, player):
    """The emulator process the player enrolled with (gen1-initial-observations host), or None."""
    initial = document["components"].get("gen1-initial-observations", {}).get(player)
    if initial is None:
        return None
    return initial["observation"]["host"]["process_id"]


def durable_progress(runtime, player, command_id):
    """The observed-shaped progress from the durable window record, or None.

    Frames are meaningful only inside the emulator process that ran the window, so the record
    is usable only while the player's enrolled process (the initial observation host, the same
    identity every held write is bound to) is the process the window was issued to. A restarted
    emulator gets no window from here: its frame counter restarted too, and an old window must
    never bound a NEW flush. The receipt this authorizes is therefore only the one produced
    inside that window (verified() additionally requires it to equal the journaled applied
    receipt); a later flush falls outside the frame range and is refused.
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
    process = enrolled_process(document, player)
    if process is None or process != entry["host"]["process_id"]:
        return None  # a different (or unknown) emulator process: no window, fail closed
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
    return durable_progress(policy.runtime, player, command_id)
