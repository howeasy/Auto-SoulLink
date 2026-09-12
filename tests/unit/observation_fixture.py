"""Observation-path (P10) drivers shared by the Gen 1 runtime tests.

The frame-credit loop and its compound-frame fixtures (frame_enrollment, frame_grant,
frame_complete) are retired. These publish the same evidence as ``observation`` batches through
``gen1_observation_runtime.record`` and keep the old helper names, so the callers read the same.
"""

import copy
import secrets

from server import frame_progress
from server.execution_window import VerifiedExecutionWindow
from server.gen1_inventory_observation import COMPONENT as INVENTORY
from server.gen1_native_frame_accounting import seed_ledger
from server.gen1_observation_runtime import COMPONENT as PROGRESS, EVENT, SCHEMA, record
from server.protocol import digest
from tests.unit.test_gen1_acquisition_runtime import grant as grant_receipt
from tests.unit.test_gen1_bootstrap_receipt import fixture
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_starter_settlement import source_and_checkpoint

INITIAL = "gen1-initial-observations"


def setup(runtime):
    """Admit both players, enroll them, witness New Game and complete the initial save."""
    instant = runtime.clock()
    runtime.clock = lambda: instant
    owners = {player: admit(runtime, player) for player in ("a", "b")}
    for player in ("a", "b"):
        initial = observation(runtime, player)
        send(runtime, player, owners[player], initial)
        receipt, _ = fixture(runtime.contract["players"][player]["variant"])
        receipt["begin"]["frame"] = 10
        receipt["end"]["frame"] = 90
        receipt.update(
            context_generation=player * 32,
            physical_instance=initial["host"]["owner_id"],
            final_sha1=initial["final_sha1"],
        )
        session = runtime.gate.sessions[player]
        runtime.process(
            {
                "protocol": runtime.protocol,
                "player": player,
                "session_id": session.session_id,
                "admission_epoch": runtime.gate.epoch,
                "seq": session.last_seq + 1,
                "operation_id": secrets.token_hex(16),
                "event": "bootstrap_observation",
                "payload": receipt,
            },
            owners[player],
        )
    from tests.unit.test_gen1_initial_save_runtime import complete_initial_save

    for player in ("a", "b"):
        complete_initial_save(runtime, player, owners[player])


start = setup


def batch(runtime, player, *, frame, signals=None, acquisitions=(), inventory=None):
    """One observation request in the shape lua/gen1_observation_loop.lua publishes."""
    document = runtime.state().document()
    initial = document["components"][INITIAL][player]
    metadata = runtime.gate.sessions[player].metadata
    progress = document["components"].get(PROGRESS, {}).get(player)
    return {
        "schema": SCHEMA,
        "event": EVENT,
        "frame": frame,
        "sequence": progress["sequence"] + 1 if progress else 1,
        "context": {
            "context_generation": initial["binding"]["context_generation"],
            "physical_instance": metadata["gen1_metadata"]["physical_instance"],
            "save_identity": metadata["save_identity"],
        },
        "rom": metadata["gen1_metadata"]["cartridge"]["final_rom_sha1"],
        "signals": signals,
        "acquisitions": list(acquisitions),
        "inventory": inventory,
    }


def observe(runtime, player, *, inventory=None, signals=None, acquisitions=(), frame=None,
            operation=None, allow_deferred=False):
    """Publish one batch; returns (operation, request, result).

    A heartbeat checkpoint is deferred while ANY physical obligation is open (P10 section 2);
    that is loud here unless the caller expects it.
    """
    if frame is None:
        if inventory is not None:
            frame = inventory["frame"]
        else:
            document = runtime.state().document()
            progress = document["components"].get(PROGRESS, {}).get(player)
            frame = progress["frame"] + 1 if progress else document["components"][INITIAL][player]["observation"]["frame"]
    request = batch(runtime, player, frame=frame, signals=signals, acquisitions=acquisitions, inventory=inventory)
    operation = operation or secrets.token_hex(16)
    result = record(runtime, player, operation, request)
    if inventory is not None and not allow_deferred and result.get("inventory_deferred"):
        raise AssertionError("heartbeat checkpoint was deferred behind an open physical obligation")
    return operation, request, result


def current_frame(runtime, player):
    """The frame a momentary hold reports: never behind the latest observation batch."""
    components = runtime.state().document()["components"]
    progress = components.get(PROGRESS, {}).get(player)
    latest = components.get(INVENTORY, {}).get(player)
    point = latest["observation"] if latest else components[INITIAL][player]["observation"]
    return max(point["frame"], progress["frame"] if progress else 0)


def starters(runtime):
    """Enroll both players and settle their starters through observation batches."""
    setup(runtime)
    for player in ("a", "b"):
        initial = runtime.state().document()["components"][INITIAL][player]
        source, stable = source_and_checkpoint(runtime, player, initial["observation"], initial["operation_id"])
        # P10 stages the checkpoint before the source is remembered, so the pair settles across two batches.
        observe(runtime, player, signals=source, frame=105)
        observe(runtime, player, inventory=stable["observation"])


# The witness whose point shows what a delivering row left behind; static and wild rows deliver nothing.
DELIVERED = {"grant": lambda r: r["return"]["point"], "capture": lambda r: r["receipt"]["end"]["point"],
             "npc_exchange": lambda r: r["return"]["point"], "evolution": lambda r: r["after"]["point"]}


def party_after(rows):
    """The party the last delivering row leaves behind, or None when none delivers."""
    for row in reversed(rows):
        if row["kind"] in DELIVERED:
            return DELIVERED[row["kind"]](row["receipt"])["party_hex"]
    return None


def checkpoint(runtime, player, rows, after, *, party=None):
    """The latest checkpoint moved to ``after``, showing the last delivering row's returned party/box."""
    document = runtime.state().document()
    old = document["components"].get(INVENTORY, {}).get(player)
    result = copy.deepcopy(old["observation"] if old else document["components"][INITIAL][player]["observation"])
    result["frame"] = after
    for row in reversed(rows):
        if row["kind"] in DELIVERED:
            point = DELIVERED[row["kind"]](row["receipt"])
            result["source"]["fields"]["party"] = point["party_hex"]
            result["source"]["fields"]["box"] = point["box_hex"]
            break
    if party is not None:
        result["source"]["fields"]["party"] = party
    return result


def source(runtime, player, name="grant:eevee:0", *, call=110, finish=130, **options):
    row = grant_receipt(runtime, player, name, boxed_before=0, **options)
    receipt = row["receipt"]
    receipt["call"]["frame"] = call
    receipt["return"]["frame"] = finish
    if "paid" in receipt:
        receipt["paid"]["frame"] = finish + 1
    return row


def party_blobs(raw):
    data = bytes.fromhex(raw)
    return [
        data[8 + 44 * i : 52 + 44 * i]
        + data[272 + 11 * i : 283 + 11 * i]
        + data[338 + 11 * i : 349 + 11 * i]
        for i in range(data[0])
    ]


def message(runtime, player, rows, *, after=140, sparse=False, point=None):
    """The batch ``commit`` publishes: ``rows`` plus, unless sparse, the checkpoint at ``after``."""
    point = point or checkpoint(runtime, player, rows, after)
    return batch(runtime, player, frame=point["frame"], acquisitions=rows, inventory=None if sparse else point)


def commit(runtime, player, rows, *, after=140, sparse=False, point=None, allow_deferred=False):
    """Publish one receipt batch; returns (operation, request, result)."""
    operation = secrets.token_hex(16)
    request = message(runtime, player, rows, after=after, sparse=sparse, point=point)
    result = record(runtime, player, operation, request)
    if not sparse and not allow_deferred and result.get("inventory_deferred"):
        raise AssertionError("heartbeat checkpoint was deferred behind an open physical obligation")
    return operation, request, result


def ledger(runtime, frame=110):
    """Seed the ordinary baseline ledger a native loan borrows against, advanced to ``frame``.

    The frame-credit loop used to seed (frame_enrollment) and advance (frame_complete) it;
    gen1_native_frame_accounting still borrows against exactly this shape, so the native tests
    seed it directly. A ledgered player publishes no further observation batches.
    """
    for player in ("a", "b"):
        stage = runtime.state()
        document = stage.document()
        entry = seed_ledger(document, player)
        progress = entry["ledger"]
        if frame > progress["frame"]:
            binding = runtime.gate.sessions[player].metadata["control_binding"]
            scope = {
                "operation_id": secrets.token_hex(16),
                "operation_digest": "d" * 64,
                "context_generation": binding["context_generation"],
                "binding_digest": binding["binding_digest"],
                "phase": "ordinary",
            }
            proof = VerifiedExecutionWindow(scope, "e" * 64, frame - progress["frame"], 1000)
            reserved = frame_progress.reserve(progress, proof)
            receipt = {
                "schema": frame_progress.RECEIPT,
                "sequence": reserved["pending"]["sequence"],
                "scope": scope,
                "before": progress["frame"],
                "after": frame,
                "steps": frame - progress["frame"],
                "observations_digest": "f" * 64,
            }
            progress, _ = frame_progress.complete(reserved, receipt)
            entry["ledger"] = progress
        runtime.journal.commit(
            player,
            secrets.token_hex(16),
            {"event": "frame_ledger_fixture"},
            expected_revision=stage.journal_revision,
            state=document,
            commands={"a": [], "b": []},
            result={"ack": "ACK", "frame_anchor_digest": digest(progress["anchor"]), "ordinary_execution": False},
        )
