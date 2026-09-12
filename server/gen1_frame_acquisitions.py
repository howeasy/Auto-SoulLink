"""Source receipts inside a consumed RBY frame, staged once after inventory.

No caller-supplied decoded fact is accepted here. Prior callback frames must be
covered by the retained return/grant chain; final delivery/payment belongs to
the range being closed. This module grants no ordinary or recovery execution.

One raw wire list, `bundle['acquisitions']`, carries every source kind in observer order;
`gen1_source_receipts.decode` types it once and every fact keeps its raw index. Inside one frame
the order is fixed: static origins/ends (and the captures they may claim) first, so an
attributed capture pairs under its static rather than its map; then acquisition settlement;
then NPC exchanges and ordinary evolutions, which migrate existing members. Everything lands in the ONE
record list root commits atomically, and `result` carries one digest per component.

Wild-encounter rows (`wild_begin`/`wild_end`, `ENCOUNTER_KINDS`) are transport only here: they
are decoded and frame-verified with the rest of the list, then returned untouched as
`encounters` (typed `{kind, fact, source_ref}` rows, raw indices kept) for root's frame journal
to hand to the wild-encounter lifecycle. This module stages nothing for them.
"""

from server import event_reference, frame_progress
from server.gen1_acquisition_runtime import (
    COMPONENT,
    source_rom,
    stage_acquisitions,
)
from server.gen1_frame_journal import retained_return as retained_return
from server.gen1_npc_exchange_runtime import COMPONENT as EXCHANGES, stage_exchanges
from server.gen1_source_receipts import (
    ACQUISITION_KINDS,
    ENCOUNTER_KINDS,
    EVOLUTION_KINDS,
    EXCHANGE_KINDS,
    LIFECYCLE_KINDS,
    decode,
    witness_frames,
)
from server.gen1_static_lifecycle import stage as stage_statics
from server.protocol import digest
from server.protocol_journal import JournalError

MAX_SOURCE_WINDOWS = 4096


def verify_frames(journal, player, anchor, closed, rows, facts):
    """Verify every witness frame, not just a monotonic receipt timestamp.

    Every row's final witness belongs to the range being closed; earlier witnesses may sit in
    retained prior windows. Deliveries (captures, grants) must be listed in successful
    delivery order since ordinals follow it; static and exchange rows keep the observer's
    order (a battle end may precede the capture it follows in frame terms).
    """
    frame_progress.verify_closed(closed, anchor=anchor)
    frames = []
    final_frame = None
    for raw, decoded in zip(rows, facts, strict=True):
        values, first = witness_frames(raw, decoded["fact"])
        if not frame_progress.covers(closed, values[-1], anchor=anchor):
            raise JournalError(
                "final acquisition delivery/payment is outside the current consumed range"
            )
        if raw["kind"] in ACQUISITION_KINDS:
            if final_frame is not None and values[-1] < final_frame:
                raise JournalError("acquisition receipts are not in successful delivery order")
            final_frame = values[-1]
        if first != values[0]:
            raise JournalError("acquisition call differs from source witness")
        frames.extend(values)
    pending = {frame for frame in frames if not frame_progress.covers(closed, frame, anchor=anchor)}
    history = closed
    seen = set()
    while pending:
        fingerprint = history["grant"]["previous_digest"]
        if (
            history["grant"]["sequence"] <= 1
            or fingerprint in seen
            or len(seen) >= MAX_SOURCE_WINDOWS
            or min(pending) <= anchor["frame"]
        ):
            raise JournalError("acquisition call lacks accounted frame history")
        seen.add(fingerprint)
        prior = retained_return(journal, player, fingerprint, anchor)
        if (
            prior["receipt"]["after"] != history["receipt"]["before"]
            or prior["grant"]["sequence"] + 1 != history["grant"]["sequence"]
        ):
            raise JournalError("acquisition source frame history is not contiguous")
        pending = {
            frame for frame in pending if not frame_progress.covers(prior, frame, anchor=anchor)
        }
        history = prior


def stage(runtime, state, document, player, operation, message, closed):
    """Stage every source receipt of a consumed bundle; None when nothing can move.

    Returns `{entry, result, commands, records, encounters}` for root's one atomic commit: `entry`
    is the acquisition entry, `records` the static-origin, acquisition and exchange records,
    `result` carries `acquisition_digest`, `static_digest`, `exchange_digest` and, when present,
    `evolution_digest`, and
    `encounters` the decoded wild-encounter rows this module only transports.
    """
    rows = message["bundle"].get("acquisitions") or []
    components = document["components"]
    pending = any(components.get(name, {}).get(player, {}).get("pending") for name in (COMPONENT, EXCHANGES))
    if not rows and not (pending and message["bundle"]["inventory"] is not None):
        return None
    initial = components["gen1-initial-observations"][player]
    provider = getattr(runtime, "prepared_cartridges", None)
    rom = source_rom(initial["metadata"], player, provider.rom if provider is not None else None)
    reference = event_reference.make(player, operation, message)
    facts = decode(rows, initial["metadata"], initial["binding"], reference=reference, rom=rom)
    anchor = components["gen1-frame-progress"][player]["ledger"]["anchor"]
    verify_frames(runtime.journal, player, anchor, closed, rows, facts)
    # 1. Statics first, in list order, so origins and ends are known before any capture pairs.
    statics = stage_statics(document, player, [fact for fact in facts if fact["kind"] in LIFECYCLE_KINDS], reference)
    held = set(statics["held"])
    from server.gen1_static_lifecycle import held_blockers
    state.barrier.set_blockers({**state.barrier.document()['blockers'], **held_blockers(document)})
    document['components']['gen1-runtime']['recovery'] = state.barrier.document()
    # 2. Acquisitions: a static's own capture pairs under the static id; ambiguous captures stay held.
    acquisition = stage_acquisitions(
        runtime,
        state,
        document,
        player,
        operation,
        [fact for fact in facts if fact["kind"] in ACQUISITION_KINDS and fact["fact"]["key"] not in held],
        frame_origin=reference,
        frame_request=message,
        rom=rom,
        attributions=statics["attributions"],
    )
    # 3. Exchanges migrate identities and rule halves that acquisitions settled; no ordinal, no acquisition.
    exchange = stage_exchanges(
        runtime,
        state,
        document,
        player,
        operation,
        [fact for fact in facts if fact["kind"] in EXCHANGE_KINDS],
        frame_origin=reference,
        frame_request=message,
    )
    evolution = None
    evolutions = [fact for fact in facts if fact['kind'] in EVOLUTION_KINDS]
    if evolutions:
        from server.gen1_evolution_runtime import stage_evolutions
        evolution = stage_evolutions(runtime, state, document, player, operation, evolutions,
            frame_origin=reference, frame_request=message, rom=rom)
    result = {
        "ack": "ACK",
        "acquisition_digest": acquisition["result"]["acquisition_digest"],
        "static_digest": digest(statics["records"][0]["value"]),
        "exchange_digest": exchange["result"]["exchange_digest"],
        "ordinary_execution": False,
    }
    if evolution is not None:
        result['evolution_digest'] = evolution['result']['evolution_digest']
    commands = {recipient: acquisition["commands"][recipient] + exchange["commands"][recipient]
                + (evolution['commands'][recipient] if evolution is not None else []) for recipient in ("a", "b")}
    return {
        "entry": acquisition["entry"],
        "result": result,
        "commands": commands,
        "records": statics["records"] + acquisition["records"] + exchange["records"]
                   + (evolution['records'] if evolution is not None else []),
        "encounters": [fact for fact in facts if fact["kind"] in ENCOUNTER_KINDS],
    }
