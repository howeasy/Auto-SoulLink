"""Pre-starter SaveGameData transform and command/file receipt verification.

The caller must independently establish bootstrap provenance, an owned held
checkpoint, durable preparation and fresh write/save permission. This kernel
neither supplies those proofs nor clears any runtime blocker.
"""

import copy

from server.frame_progress import identifier, integer
from server.gen1_bootstrap_receipt import projection, validation_dependencies
from server.gen1_full_save import image, layout
from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.gen1_save_delta import wire_payload as save_delta
from server.protocol import digest
from server.protocol_journal import JournalError
from server.save_file_receipt import verify_file_image
from server.verified_content_cache import verified_content_cache

COMMAND = "initial_save"
PREPARED = "rby-initial-save-prepared-v1"
DELTA = "rby-initial-save-delta-v1"
RECEIPT = "rby-initial-save-receipt-v1"


@verified_content_cache(dependencies=validation_dependencies)
def expected(before, *, identity):
    """Copy the held pre-starter WRAM to SRAM, preserving every outside byte."""
    actual = projection(before)
    if any(not actual[name].startswith("00FF") for name in ("party", "box")) or (
        actual["owned"] != "00" * 19 or actual["seen"] != "00" * 19 or actual["current_box"] != "00"
    ):
        raise JournalError("initial save requires an empty pre-starter point")
    name = bytes.fromhex(actual["trainer"])
    try:
        PartyCodec(before["variant"])._name(name, "initial save trainer")
    except PartyCodecError as error:
        raise JournalError(str(error)) from error
    if identity != {"ot_id": actual["player_id"], "trainer_name": display_name(name)}:
        raise JournalError("initial save identity differs from enrollment")
    after = copy.deepcopy(before)
    after.update(cart_hex=image(before).hex().upper(), save_status=2)
    return after


def prepare(before, *, identity, context_generation, final_sha1, frame):
    return {
        "schema": PREPARED,
        "before": copy.deepcopy(before),
        "after": expected(before, identity=identity),
        "context_generation": identifier(context_generation),
        "final_sha1": identifier(final_sha1, 40),
        "frame": integer(frame),
    }


@verified_content_cache(dependencies=lambda: {variant: layout(variant) for variant in ('red', 'blue', 'yellow')})
def wire_payload(payload):
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "schema",
            "before",
            "after",
            "context_generation",
            "final_sha1",
            "frame",
        }
        or payload["schema"] != PREPARED
    ):
        raise JournalError("prepared initial save required")
    identifier(payload["context_generation"])
    identifier(payload["final_sha1"], 40)
    integer(payload["frame"])
    before = payload["before"]
    saved = image(before).hex().upper()
    if payload["after"] != {**before, "cart_hex": saved, "save_status": 2}:
        raise JournalError("initial save delta differs from source-defined copies")
    return save_delta(payload, schema=DELTA)


def verify_receipt(command, receipt, before, *, identity, context_generation, final_sha1, frame):
    payload = prepare(
        before,
        identity=identity,
        context_generation=context_generation,
        final_sha1=final_sha1,
        frame=frame,
    )
    if not isinstance(command, dict) or not isinstance(command.get("body"), dict):
        raise JournalError("owned initial save command required")
    body = command["body"]
    if digest(body) != digest({"cmd": COMMAND, "payload": wire_payload(payload)}):
        raise JournalError("initial save command differs from its prepared image")
    fields = {
        "schema",
        "command_id",
        "command_sequence",
        "body_digest",
        "context_generation",
        "final_sha1",
        "before_digest",
        "after",
        "file",
    }
    if not isinstance(receipt, dict) or set(receipt) != fields or receipt["schema"] != RECEIPT:
        raise JournalError("complete initial save receipt required")
    wanted = {
        "command_id": identifier(command.get("command_id")),
        "command_sequence": integer(command.get("command_sequence"), 1),
        "body_digest": digest(body),
        "context_generation": context_generation,
        "final_sha1": final_sha1,
        "before_digest": digest(before),
    }
    if any(type(receipt[k]) is not type(v) or receipt[k] != v for k, v in wanted.items()):
        raise JournalError("initial save receipt command/context/preimage differs")
    if receipt["after"] != payload["after"]:
        raise JournalError("initial save differs from its exact prepared poststate")
    verify_file_image(
        receipt["file"],
        bytes.fromhex(payload["after"]["cart_hex"]),
        host_profile="bizhawk-2.11.1-gambatte-exclusive-hold-v1",
        frame_from=frame,
        frame_to=frame,
    )
    return {"before_digest": digest(before), "after_digest": digest(payload["after"])}
