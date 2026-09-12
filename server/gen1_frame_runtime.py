"""RBY physical/source bindings for the shared bounded-frame ledger.

These pure transitions must be committed with their corresponding runtime
events. They do not clear a barrier or choose when gameplay is eligible. The
owner must settle a completed observation bundle before requesting another
range; pending_observation is an explicit hold for that work.
"""

import copy
import re

from server import frame_progress
from server.execution_window import VerifiedExecutionWindow
from server.gen1_bootstrap_receipt import validate as validate_bootstrap
from server.gen1_engine_signals import validate_batch
from server.gen1_initial_observation import validate as validate_inventory
from server.gen1_party_codec import PartyCodecError
from server.protocol import digest
from server.protocol_journal import JournalError

COMPONENT = "gen1-frame-progress"
BOOTSTRAP = "gen1-new-game-bootstrap"
BOUNDARY = "rby-frame-boundary-v1"


def validate_boundary(boundary, *, initial=None, frame=None):
    """Check a physical return marker; this does not qualify inventory or rules."""
    if (not isinstance(boundary, dict) or set(boundary) != {
            "schema", "context_generation", "final_sha1", "frame", "host"}
            or boundary["schema"] != BOUNDARY):
        raise JournalError("complete held frame boundary required")
    for name, size in (("context_generation", 32), ("final_sha1", 40)):
        if not isinstance(boundary[name], str) or not re.fullmatch(f"[0-9a-f]{{{size}}}", boundary[name]):
            raise JournalError("invalid frame boundary context or cartridge hash")
    if type(boundary["frame"]) is not int or not 0 <= boundary["frame"] <= 2**53 - 1:
        raise JournalError("invalid frame boundary frame")
    host = boundary["host"]
    if (not isinstance(host, dict) or set(host) != {"owner_id", "capability_id", "process_id", "held"}
            or not isinstance(host["owner_id"], str) or not re.fullmatch("[0-9a-f]{32}", host["owner_id"])
            or host["capability_id"] != "bizhawk-2.11.1-gambatte-exclusive-hold-v1"
            or type(host["process_id"]) is not int or host["process_id"] < 1 or host["held"] is not True):
        raise JournalError("owned held frame boundary required")
    if initial is not None and (boundary["context_generation"] != initial["binding"]["context_generation"]
            or boundary["final_sha1"] != initial["metadata"]["gen1_metadata"]["cartridge"]["final_rom_sha1"]
            or host != initial["observation"]["host"]):
        raise JournalError("frame boundary differs from immutable physical enrollment")
    if frame is not None and (type(frame) is not int or boundary["frame"] != frame):
        raise JournalError("frame boundary differs from its consumed return frame")
    return copy.deepcopy(boundary)


def boundary_from_inventory(inventory):
    """Derive only the held boundary fields; full inventory validation is separate."""
    if not isinstance(inventory, dict) or not {"context_generation", "final_sha1", "frame", "host"} <= set(inventory):
        raise JournalError("inventory lacks its held frame boundary")
    return validate_boundary({"schema": BOUNDARY, **{name: inventory[name] for name in (
        "context_generation", "final_sha1", "frame", "host")}})


def bundle_boundary(bundle):
    """Check either full legacy evidence or an explicit boundary with sparse evidence.

    This shape check does not bind enrollment or grant coverage. complete() owns
    those checks; inventory and engine evidence retain their separate validators.
    """
    if not isinstance(bundle, dict) or set(bundle) - {'acquisitions', 'native_checkpoint'} not in (
            {"inventory", "engine_signals"}, {"boundary", "inventory", "engine_signals"}):
        raise JournalError("complete held frame observation bundle required")
    acquisitions = bundle.get('acquisitions')
    from server.gen1_source_receipts import KINDS
    if acquisitions is not None and (not isinstance(acquisitions, list) or len(acquisitions) > 16
            or any(not isinstance(row, dict) or set(row) != {'kind', 'receipt'}
                   or row['kind'] not in KINDS for row in acquisitions)):
        raise JournalError('bounded typed frame acquisitions required')
    inventory = bundle["inventory"]
    if bundle.get('native_checkpoint') is not None and (inventory is None or not isinstance(bundle['native_checkpoint'], dict)):
        raise JournalError('native checkpoint requires its full frame inventory')
    if inventory is None and "boundary" not in bundle:
        raise JournalError("sparse frame observations require an explicit held boundary")
    if inventory is not None and not isinstance(inventory, dict):
        raise JournalError("typed frame inventory observation required")
    if "boundary" in bundle:
        boundary = validate_boundary(bundle["boundary"])
        if inventory is not None and boundary_from_inventory(inventory) != boundary:
            raise JournalError("frame inventory differs from its explicit held boundary")
        return boundary
    return boundary_from_inventory(inventory)


def anchor(document, player):
    if player not in ("a", "b"):
        raise JournalError("RBY frame player required")
    initial = document["components"].get("gen1-initial-observations", {}).get(player)
    bootstrap = document["components"].get(BOOTSTRAP, {}).get(player)
    if not isinstance(initial, dict) or not isinstance(bootstrap, dict):
        raise JournalError("normal new-game enrollment required before frame accounting")
    metadata = initial["metadata"]
    observation = initial["observation"]
    gen1 = metadata["gen1_metadata"]
    proof = validate_bootstrap(
        bootstrap["payload"],
        variant=gen1["cartridge"]["variant"],
        identity=metadata["save_identity"],
        context_generation=initial["binding"]["context_generation"],
        physical_instance=gen1["physical_instance"],
        final_sha1=gen1["cartridge"]["final_rom_sha1"],
        source=observation["source"],
        frame=observation["frame"],
    )
    if bootstrap["proof"] != proof:
        raise JournalError("frame bootstrap differs from its source receipt")
    return frame_progress.initial(
        context_generation=initial["binding"]["context_generation"],
        physical_digest=digest(
            {
                "metadata": {k: v for k, v in metadata.items() if k != "control_binding"},
                "host": observation["host"],
                "bootstrap": bootstrap["operation_id"],
            }
        ),
        frame=observation["frame"],
    )["anchor"]


def seed(document, player):
    expected = frame_progress.initial(**anchor(document, player))
    entries = document["components"].setdefault(COMPONENT, {})
    if player in entries:
        raise JournalError("frame accounting cannot replace an existing history")
    entries[player] = {"ledger": expected, "pending_observation": None}
    return entries[player]


def validate_state(document):
    entries = document["components"].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries) - {"a", "b"}:
        raise JournalError("invalid RBY frame ledger component")
    for player, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {"ledger", "pending_observation"}:
            raise JournalError("complete RBY frame ledger entry required")
        ledger = frame_progress.validate(entry["ledger"])
        if ledger["anchor"] != anchor(document, player):
            raise JournalError("frame progress physical enrollment changed")
        pending = entry["pending_observation"]
        if pending is not None:
            if not isinstance(pending, dict) or set(pending) != {"closed", "bundle_digest"}:
                raise JournalError("complete pending frame observation required")
            closed = frame_progress.verify_closed(pending["closed"], anchor=ledger["anchor"])
            if (
                ledger["pending"] is not None
                or digest(closed) != ledger["previous_digest"]
                or closed["receipt"]["after"] != ledger["frame"]
                or pending["bundle_digest"] != closed["receipt"]["observations_digest"]
            ):
                raise JournalError("unsettled observation differs from the consumed frame range")


def reserve(document, player, proof):
    validate_state(document)
    if not isinstance(proof, VerifiedExecutionWindow):
        raise JournalError("independently verified ordinary frame proof required")
    entry = document["components"].get(COMPONENT, {}).get(player)
    if entry is None:
        raise JournalError("frame progress must be seeded from verified bootstrap")
    if entry["pending_observation"] is not None:
        raise JournalError("previous frame observations must settle before further execution")
    if document["active_trade"] is not None:
        raise JournalError("native trade owns execution until its verified closure")
    admission = document["components"]["gen1-runtime"]["admissions"].get(player)
    if (
        admission is None
        or proof.scope["binding_digest"] != admission["binding"]["binding_digest"]
        or proof.scope["context_generation"] != admission["binding"]["context_generation"]
        or proof.scope["phase"] != "ordinary"
        or proof.state_digest != digest(document)
    ):
        raise JournalError("ordinary frame proof differs from the admitted journal state")
    result = frame_progress.reserve(entry["ledger"], proof)
    entry["ledger"] = result
    return copy.deepcopy(result["pending"])


def complete(document, player, receipt, bundle):
    """Close a consumed range without treating its observations as settled rules."""
    validate_state(document)
    if not isinstance(receipt, dict):
        raise JournalError("typed frame receipt required")
    entry = document["components"].get(COMPONENT, {}).get(player)
    if entry is None or entry["pending_observation"] is not None:
        raise JournalError("one outstanding frame range required")
    boundary = bundle_boundary(bundle)
    initial = document["components"]["gen1-initial-observations"][player]
    metadata, binding = initial["metadata"], initial["binding"]
    validate_boundary(boundary, initial=initial, frame=receipt.get("after"))
    inventory = bundle["inventory"]
    if inventory is not None:
        try:
            validate_inventory(inventory, metadata, binding)
        except PartyCodecError as error:
            raise JournalError(str(error)) from error
    signals = bundle["engine_signals"]
    if signals is not None:
        try:
            validate_batch(signals, metadata)
        except PartyCodecError as error:
            raise JournalError(str(error)) from error
    if receipt.get("observations_digest") != digest(bundle) or boundary["frame"] != receipt.get(
        "after"
    ):
        raise JournalError("frame receipt differs from the held observation bundle")
    next_ledger, closed = frame_progress.complete(entry["ledger"], receipt)
    if signals is not None:
        for signal in signals["signals"]:
            if not frame_progress.covers(closed, signal["frame"], anchor=next_ledger["anchor"]):
                raise JournalError("source signal occurred outside consumed authorized frames")
    entry["ledger"] = next_ledger
    entry["pending_observation"] = {"closed": closed, "bundle_digest": digest(bundle)}
    return copy.deepcopy(closed)


def verified_held_frame(document, player, frame, *, historical=False):
    """Only a settled, closed boundary can serve a later physical-write policy."""
    validate_state(document)
    entry = document["components"].get(COMPONENT, {}).get(player)
    if historical:
        if (entry is None or type(frame) is not int
                or not entry['ledger']['anchor']['frame'] <= frame <= entry['ledger']['frame']):
            raise JournalError('historical frame is outside accounted execution')
        return True
    if (
        entry is None
        or entry["ledger"]["pending"] is not None
        or entry["pending_observation"] is not None
    ):
        raise JournalError("held frame still has unclosed execution or observation obligations")
    if type(frame) is not int or frame != entry["ledger"]["frame"]:
        raise JournalError("held frame differs from the server-accounted step count")
    return True
