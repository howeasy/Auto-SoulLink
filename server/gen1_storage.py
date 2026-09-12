"""RBY PC container transforms from pinned MoveMon, RemovePokemon and CalcStats.

No execution authority lives here. The caller supplies a complete owned point;
the result preserves HP/status, all unrelated boxes and save regions. Admitted
UPR options cannot alter base stats, types or growth curves used by PartyCodec.
"""

import copy
import math

from server.gen1_full_save import SYMBOLS, image
from server.gen1_grave_storage import checksum_banks
from server.gen1_initial_observation import inventory
from server.gen1_memorial_policy import box_offset
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.gen1_retirement import remove_box
from server.gen1_save_delta import wire_payload as delta
from server.protocol import digest
from server.protocol_journal import JournalError
from server.save_file_receipt import verify_file_image

SCHEMA = "rby-storage-receipt-v1"
DELTA = "rby-storage-delta-v1"


class StorageRefusal(JournalError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def withdraw_blob(boxed, variant):
    """CalcLevelFromExperience + CalcStats; never trust cached party tails."""
    if not isinstance(boxed, bytes) or len(boxed) != 55:
        raise StorageRefusal("complete-box-record-required")
    codec = PartyCodec(variant)
    facts = codec.profile["species"].get(str(boxed[0]))
    if facts is None:
        raise StorageRefusal("unknown-species")
    level = codec.level_from_experience(facts["growth_rate"], int.from_bytes(boxed[14:17], "big"))
    a, b = boxed[27:29]
    dvs = [
        (a >> 4 & 1) * 8 + (a & 1) * 4 + (b >> 4 & 1) * 2 + (b & 1),
        a >> 4,
        a & 15,
        b >> 4,
        b & 15,
    ]
    stats = []
    for i, base in enumerate(facts["base_stats"]):
        exp = int.from_bytes(boxed[17 + 2 * i : 19 + 2 * i], "big")
        root = math.isqrt(exp)
        # Pinned CalcStat stops at255, before squaring that candidate.
        bonus = min(255, root + (root * root < exp)) // 4
        stats.append(
            min(999, ((base + dvs[i]) * 2 + bonus) * level // 100 + (level + 10 if i == 0 else 5))
        )
    raw = boxed[:33] + bytes([level]) + b"".join(s.to_bytes(2, "big") for s in stats) + boxed[33:]
    codec.validate_blob(raw)
    return raw


def remove_party(raw, slot):
    """Whole-capacity cartridge shifts, including the final-OT-byte quirk."""
    out = bytearray(raw)
    count = out[0]
    if (
        len(out) != 404
        or type(slot) is not int
        or not 0 <= slot < count <= 6
        or out[count + 1] != 255
    ):
        raise StorageRefusal("invalid-party-removal")
    out[0] -= 1
    out[slot + 1 : count + 1] = out[slot + 2 : count + 2]
    if slot == 5:
        out[272 + 11 * slot] = 255
    else:
        for base, stride in ((272, 11), (8, 44), (338, 11)):
            out[base + slot * stride : base + 5 * stride] = out[
                base + (slot + 1) * stride : base + 6 * stride
            ]
    return out


def deposit_effect(point, raw):
    main = bytearray.fromhex(point["fields"]["main"])
    if point["variant"] != "yellow":
        return main
    symbols = SYMBOLS["pokeyellow"]

    def offset(name):
        return symbols[name] - symbols["wMainDataStart"]

    if (
        raw[0] == 0x54
        and raw[12:14] == main[offset("wPlayerID") : offset("wPlayerID") + 2]
        and raw[44:49] == bytes.fromhex(point["fields"]["name"])[:5]
    ):
        if main[offset("wPikachuOverworldStateFlags")] & 2:
            raise StorageRefusal("yellow-starter-following-disabled")
        happiness, mood = offset("wPikachuHappiness"), offset("wPikachuMood")
        main[happiness] = max(0, main[happiness] - (5 if main[happiness] >= 200 else 3))
        main[mood] = min(main[mood], 98)
    return main


def initialize_inactive(point, cart):
    """Canonical headers/flag, only after all uninitialized bytes prove empty."""
    for index in range(12):
        start = box_offset(index)
        if any(value not in (0, 255) for value in cart[start : start + 1122]):
            raise StorageRefusal("unowned-uninitialized-storage")
    for index in range(12):
        start = box_offset(index)
        cart[start : start + 2] = b"\0\xff"
    symbols = SYMBOLS["pokeyellow" if point["variant"] == "yellow" else "pokered"]
    main = bytearray.fromhex(point["fields"]["main"])
    main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]] |= 128
    point["fields"]["main"] = main.hex().upper()
    checksum_banks(cart, {2, 3})


def append_box(raw, boxed):
    raw = bytearray(raw)
    slot = raw[0]
    if slot >= 20:
        raise StorageRefusal("current-box-full")
    for start, stride, data in (
        (22, 33, boxed[:33]),
        (682, 11, boxed[33:44]),
        (902, 11, boxed[44:55]),
    ):
        raw[start + slot * stride : start + (slot + 1) * stride] = data
    raw[slot + 1 : slot + 3] = bytes([boxed[0], 255])
    raw[0] += 1
    return raw


def relocate(point, key, destination, *, identity, reserved_boxes):
    roster = inventory(point, identity)
    target = next(
        (m for m in roster["members"] if m["key"] == key and m["location"] == "box"), None
    )
    if target is None:
        raise StorageRefusal("boxed-relocation-target-required")
    box_offset(destination)
    if destination in reserved_boxes or destination == target["box"]:
        raise StorageRefusal("illegal-boxed-relocation-destination")
    out = copy.deepcopy(point)
    cart = bytearray.fromhex(point["cart_hex"])
    active = roster["current_box"]
    if destination != active and not roster["boxes_initialized"]:
        initialize_inactive(out, cart)

    def stored(index):
        return (
            bytes.fromhex(out["fields"]["box"])
            if index == active
            else bytes(cart[box_offset(index) : box_offset(index) + 1122])
        )

    rebuilt = withdraw_blob(bytes.fromhex(target["box_blob_hex"]), point["variant"])
    boxed = bytearray(rebuilt[:33])
    boxed[3] = rebuilt[33]
    updated = {
        target["box"]: remove_box(stored(target["box"]), target["slot"]),
        destination: append_box(stored(destination), bytes(boxed) + rebuilt[44:]),
    }
    banks = set()
    for index, raw in updated.items():
        if index == active:
            out["fields"]["box"] = bytes(raw).hex().upper()
        else:
            offset = box_offset(index)
            cart[offset : offset + 1122] = raw
            banks.add(2 + index // 6)
    checksum_banks(cart, banks)
    out["cart_hex"] = cart.hex().upper()
    out["cart_hex"] = image(out).hex().upper()
    out["save_status"] = 2
    if {m["key"] for m in inventory(out, identity)["members"]} != {
        m["key"] for m in roster["members"]
    }:
        raise StorageRefusal("boxed-relocation-identity-set-changed")
    return out


def expected(point, key, direction, *, identity, reserved_boxes=(11,), destination_box=None):
    """Deposit to the current box, or retrieve an exact key from any known box."""
    try:
        if direction == "relocate":
            return relocate(
                point, key, destination_box, identity=identity, reserved_boxes=reserved_boxes
            )
        roster = inventory(point, identity)
        if direction not in ("deposit", "withdraw", "confirm"):
            raise StorageRefusal("unknown-storage-direction")
        rows = [m for m in roster["members"] if m["key"] == key]
        if len(rows) != 1:
            raise StorageRefusal("unique-storage-target-required")
        target = rows[0]
        if direction == "confirm":
            out = copy.deepcopy(point)
            out["cart_hex"] = image(out).hex().upper()
            out["save_status"] = 2
            return out
        if target["location"] != ("party" if direction == "deposit" else "box"):
            raise StorageRefusal("storage-target-moved")
        box = (
            (roster["current_box"] if destination_box is None else destination_box)
            if direction == "deposit"
            else target["box"]
        )
        if box in reserved_boxes:
            raise StorageRefusal("reserved-archive-box")
        out = copy.deepcopy(point)
        party = bytearray.fromhex(point["fields"]["party"])
        cart = bytearray.fromhex(point["cart_hex"])
        active = box == roster["current_box"]
        if not active and not roster["boxes_initialized"]:
            initialize_inactive(out, cart)
        off = box_offset(box)
        stored = bytearray.fromhex(point["fields"]["box"]) if active else cart[off : off + 1122]
        if direction == "deposit":
            if party[0] <= 1:
                raise StorageRefusal("last-party-member")
            if stored[0] >= 20:
                raise StorageRefusal("current-box-full")
            raw = bytes.fromhex(target["blob_hex"])
            out["fields"]["main"] = (
                deposit_effect({**point, "fields": out["fields"]}, raw).hex().upper()
            )
            boxed = bytearray(raw[:33])
            boxed[3] = raw[33]
            stored = append_box(stored, bytes(boxed) + raw[44:])
            party = remove_party(party, target["slot"])
        else:
            if party[0] >= 6:
                raise StorageRefusal("party-full")
            raw = withdraw_blob(bytes.fromhex(target["box_blob_hex"]), point["variant"])
            slot = party[0]
            for base, stride, data in (
                (8, 44, raw[:44]),
                (272, 11, raw[44:55]),
                (338, 11, raw[55:66]),
            ):
                party[base + slot * stride : base + (slot + 1) * stride] = data
            party[slot + 1 : slot + 3] = bytes([raw[0], 255])
            party[0] += 1
            stored = remove_box(stored, target["slot"])
        out["fields"]["party"] = bytes(party).hex().upper()
        if active:
            out["fields"]["box"] = bytes(stored).hex().upper()
        else:
            cart[off : off + 1122] = stored
            checksum_banks(cart, {2 + box // 6})
            out["cart_hex"] = bytes(cart).hex().upper()
        out["cart_hex"] = image(out).hex().upper()
        out["save_status"] = 2
        final = inventory(out, identity)
        if {r["key"] for r in final["members"]} != {r["key"] for r in roster["members"]}:
            raise StorageRefusal("storage-identity-set-changed")
        return out
    except PartyCodecError as exc:
        raise StorageRefusal(str(exc)) from exc


def prepare(
    point,
    key,
    direction,
    *,
    identity,
    context_generation,
    final_sha1,
    frame,
    reserved_boxes=(11,),
    destination_box=None,
):
    return {
        "before": copy.deepcopy(point),
        "after": expected(
            point,
            key,
            direction,
            identity=identity,
            reserved_boxes=reserved_boxes,
            destination_box=destination_box,
        ),
        "key": key,
        "direction": direction,
        "context_generation": context_generation,
        "final_sha1": final_sha1,
        "frame": frame,
        "reserved_boxes": list(reserved_boxes),
        "destination_box": destination_box,
    }


def wire_payload(payload):
    return {**delta(payload), "schema": DELTA}


def verify_receipt(command, receipt, payload, *, identity):
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
    if not isinstance(receipt, dict) or set(receipt) != fields or receipt["schema"] != SCHEMA:
        raise JournalError("complete storage image and file receipt required")
    for key, wanted in {
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "body_digest": digest(command["body"]),
        "context_generation": payload["context_generation"],
        "final_sha1": payload["final_sha1"],
        "before_digest": digest(payload["before"]),
        "after": payload["after"],
    }.items():
        if receipt[key] != wanted:
            raise JournalError("storage receipt differs from owned prepared image")
    if command["body"].get("cmd") != "storage_apply" or command["body"].get(
        "payload"
    ) != wire_payload(payload):
        raise JournalError("storage receipt command differs from prepared instruction")
    if (
        expected(
            payload["before"],
            payload["key"],
            payload["direction"],
            identity=identity,
            reserved_boxes=payload["reserved_boxes"],
            destination_box=payload.get("destination_box"),
        )
        != payload["after"]
    ):
        raise JournalError("storage transform differs from prepared image")
    verify_file_image(
        receipt["file"],
        bytes.fromhex(payload["after"]["cart_hex"]),
        host_profile="bizhawk-2.11.1-gambatte-exclusive-hold-v1",
        frame_from=payload["frame"],
        frame_to=payload["frame"],
    )
