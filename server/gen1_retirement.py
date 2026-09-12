"""Exact non-linked retirement images: faint the member and preserve it in storage.

The runtime proves the cause-specific acquisition policy and owns the source
preimage/reservation. No link, death record, execution or file ownership is
created by this pure transform.
"""

import copy
import hashlib

from server.gen1_full_save import image
from server.gen1_grave_storage import append, validate_saved
from server.gen1_initial_observation import inventory
from server.gen1_memorial import expected as memorial
from server.gen1_memorial_policy import (
    BOX_SIZE,
    MemorialRecoveryRequired,
    entirely_empty,
    storage_policy,
)
from server.gen1_native_trade_receipts import _bytes
from server.gen1_save_delta import wire_payload as delta
from server.protocol import digest
from server.protocol_journal import JournalError
from server.save_file_receipt import verify_file_image

SCHEMA = "rby-retirement-receipt-v1"
DELTA = "rby-retirement-delta-v1"


def remove_box(raw, slot):
    """The pinned _RemovePokemon box path, including its unused-tail behavior."""
    data = bytearray(_bytes(raw, BOX_SIZE) if isinstance(raw, str) else raw)
    if (
        len(data) != BOX_SIZE
        or type(slot) is not int
        or not 0 <= slot < data[0] <= 20
        or data[data[0] + 1] != 255
    ):
        raise JournalError("valid current-box removal slot required")
    old_count = data[0]
    data[0] -= 1
    data[1 + slot : 1 + old_count] = data[2 + slot : 2 + old_count]
    if slot == 19:
        data[682 + 11 * slot] = 255
        return bytes(data)
    # CopyDataUntil shifts through the entire capacity, not just used entries.
    for base, stride in ((682, 11), (22, 33), (902, 11)):
        data[base + slot * stride : base + 19 * stride] = data[
            base + (slot + 1) * stride : base + 20 * stride
        ]
    return bytes(data)


def prepend_box(before, boxed):
    """Source SendNewMonToBox shifts only the occupied entries."""
    data = bytearray(_bytes(before, BOX_SIZE) if isinstance(before, str) else before)
    if (
        len(data) != BOX_SIZE
        or len(boxed) != 55
        or not 0 <= data[0] < 20
        or data[data[0] + 1] != 255
    ):
        raise JournalError("valid boxed delivery preimage required")
    count = data[0]
    for base, stride, value in (
        (22, 33, boxed[:33]),
        (682, 11, boxed[33:44]),
        (902, 11, boxed[44:]),
    ):
        data[base + stride : base + (count + 1) * stride] = data[base : base + count * stride]
        data[base : base + stride] = value
    data[2 : count + 3] = data[1 : count + 2]
    data[0] = count + 1
    data[1] = boxed[0]
    return bytes(data)


def expected(point, key, *, identity, reserved_digest=None, birth_box=None):
    roster = inventory(point, identity)
    validate_saved(point)
    targets = [row for row in roster["members"] if row["key"] == key]
    if len(targets) != 1 or roster["party_count"] < 1:
        raise JournalError("retirement requires one exact target and a nonempty party")
    target = targets[0]
    if target["location"] == "party":
        if roster["party_count"] <= 1:
            raise MemorialRecoveryRequired("last-party", "last party member cannot be retired")
        dead = copy.deepcopy(point)
        party = bytearray.fromhex(dead["fields"]["party"])
        offset = 8 + 44 * target["slot"]
        party[offset + 1 : offset + 3] = b"\0\0"
        dead["fields"]["party"] = party.hex().upper()
        policy = storage_policy(dead, reserved_digest=reserved_digest)
        after = memorial(
            dead, key, identity=identity, reserved_digest=reserved_digest, storage_policy=policy
        )
    else:
        if target["box"] != roster["current_box"]:
            raise MemorialRecoveryRequired(
                "inactive-target", "retirement target must remain in its observed current box"
            )
        live = _bytes(target["box_blob_hex"], 55)
        boxed = bytearray(live)
        boxed[1:3] = b"\0\0"
        boxed = bytes(boxed)
        after = copy.deepcopy(point)
        if target["box"] == 11:
            if (
                not isinstance(birth_box, dict)
                or set(birth_box) != {"before", "after"}
                or target["slot"] != 0
            ):
                raise JournalError("gift in active grave requires its exact delivery lineage")
            before = _bytes(birth_box["before"], BOX_SIZE)
            delivered = prepend_box(before, live)
            if delivered != _bytes(birth_box["after"], BOX_SIZE) or delivered != _bytes(
                point["fields"]["box"], BOX_SIZE
            ):
                raise JournalError("active-grave gift differs from its exact boxed birth")
            if reserved_digest is None:
                if not entirely_empty(before):
                    raise JournalError("active grave had unowned data before the gift")
            elif hashlib.sha256(before).hexdigest() != reserved_digest:
                raise JournalError("active-grave birth replaced its owned reservation")
            for slot in range(20):
                index = 22 + 33 * slot
                if before[index] not in (0, 255) and before[index + 1 : index + 3] != b"\0\0":
                    raise JournalError("active grave contains another live member")
            raw = bytearray(delivered)
            raw[23:25] = b"\0\0"
            after["fields"]["box"] = raw.hex().upper()
        else:
            raw = bytearray.fromhex(point["fields"]["box"])
            index = 22 + 33 * target["slot"]
            raw[index + 1 : index + 3] = b"\0\0"
            after["fields"]["box"] = remove_box(bytes(raw), target["slot"]).hex().upper()
            policy = storage_policy(after, reserved_digest=reserved_digest)
            fields = {name: bytearray.fromhex(value) for name, value in after["fields"].items()}
            cart = bytearray.fromhex(after["cart_hex"])
            append(after, fields, cart, boxed, reserved_digest=reserved_digest, policy=policy)
            after["fields"] = {name: value.hex().upper() for name, value in fields.items()}
            after["cart_hex"] = cart.hex().upper()
        after["cart_hex"] = image(after).hex().upper()
        after["save_status"] = 2
    final = inventory(after, identity)
    target_after = [row for row in final["members"] if row["key"] == key]
    if (
        len(target_after) != 1
        or target_after[0]["location"] != "box"
        or target_after[0]["box"] != 11
        or bytes.fromhex(target_after[0]["box_blob_hex"])[1:3] != b"\0\0"
        or {row["key"] for row in roster["members"]} != {row["key"] for row in final["members"]}
    ):
        raise JournalError("retirement did not preserve exact fainted archive identity")
    return after


def prepare(
    point,
    key,
    *,
    identity,
    context_generation,
    final_sha1,
    frame,
    reserved_digest=None,
    birth_box=None,
):
    after = expected(
        point, key, identity=identity, reserved_digest=reserved_digest, birth_box=birth_box
    )
    return {
        "before": copy.deepcopy(point),
        "after": after,
        "key": key,
        "context_generation": context_generation,
        "final_sha1": final_sha1,
        "frame": frame,
        "reserved_digest": reserved_digest,
        "birth_box": copy.deepcopy(birth_box),
    }


def wire_payload(payload):
    return delta(payload, schema=DELTA)


def verify_receipt(command, receipt, payload, *, identity):
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {
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
        or receipt["schema"] != SCHEMA
    ):
        raise JournalError("complete retirement file receipt required")
    if (
        command["body"].get("cmd") != "acquisition_retire"
        or command["body"].get("key") != payload["key"]
        or command["body"].get("payload") != wire_payload(payload)
    ):
        raise JournalError("retirement command differs from its owned preparation")
    wanted = {
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "body_digest": digest(command["body"]),
        "context_generation": payload["context_generation"],
        "final_sha1": payload["final_sha1"],
        "before_digest": digest(payload["before"]),
    }
    if any(type(receipt[k]) is not type(v) or receipt[k] != v for k, v in wanted.items()):
        raise JournalError("retirement receipt changed command, source or context")
    after = expected(
        payload["before"],
        payload["key"],
        identity=identity,
        reserved_digest=payload["reserved_digest"],
        birth_box=payload["birth_box"],
    )
    if payload["after"] != after or receipt["after"] != after:
        raise JournalError("retirement differs from the exact preserved archive image")
    verify_file_image(
        receipt["file"],
        bytes.fromhex(after["cart_hex"]),
        host_profile="bizhawk-2.11.1-gambatte-exclusive-hold-v1",
        frame_from=payload["frame"],
        frame_to=payload["frame"],
    )
    return {"key": payload["key"], "after_digest": digest(after)}
