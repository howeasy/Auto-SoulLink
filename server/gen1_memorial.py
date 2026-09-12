"""Independent prepared memorial/save transform. This module grants no writes.

Generation-owned storage geometry and Yellow effects stay here; complete save
copying and file receipt checks reuse the existing save modules. The caller must
bind the preimage and reservation to its owned command before applying anything.
"""

import copy

from server.gen1_full_save import SYMBOLS, image
from server.gen1_initial_observation import inventory
from server.gen1_memorial_policy import grave_digest
from server.gen1_party_codec import PartyCodecError
from server.protocol import digest
from server.protocol_journal import JournalError
from server.save_file_receipt import verify_file_image

SCHEMA = "rby-memorial-receipt-v1"
GRAVE = 0x75EA
BOX_SIZE = 1122


def _inventory(point, identity):
    try:
        return inventory(point, identity)
    except PartyCodecError as exc:
        raise JournalError(str(exc)) from exc


def reservation(point):
    """Fingerprint the authoritative grave, including tails; not ownership proof."""
    return grave_digest(point)


def expected(point, key, *, identity, reserved_digest=None, storage_policy=None):
    """Exact deposit plus full SaveGameData image, with unrelated bytes retained.

    A nonempty grave requires the caller's previously committed reservation.
    Active box12 and full-grave rotation require the caller's exact recorded
    storage policy. The final party member can never be removed by this kernel.
    """
    roster = _inventory(point, identity)
    variant = point["variant"]
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]
    fields = {name: bytearray.fromhex(raw) for name, raw in point["fields"].items()}
    main, party = fields["main"], fields["party"]
    cart = bytearray.fromhex(point["cart_hex"])

    def offset(name):
        return symbols[name] - symbols["wMainDataStart"]

    flag_offset = offset("wCurrentBoxNum")
    flag = main[flag_offset]
    active_grave = flag & 127 == 11
    if active_grave and storage_policy is None:
        raise JournalError("active memorial box requires reconciliation")
    if party[0] <= 1:
        raise JournalError("last party member cannot be memorialized")
    slots = [
        member
        for member in roster["members"]
        if member["key"] == key and member["location"] == "party"
    ]
    if len(slots) != 1:
        raise JournalError("exact memorial party target required")
    selected = slots[0]
    raw = bytes.fromhex(selected["blob_hex"])
    if raw[1:3] != b"\0\0":
        raise JournalError("memorial target must already be physically fainted")
    if (
        variant == "yellow"
        and raw[0] == 0x54
        and raw[12:14] == main[offset("wPlayerID") : offset("wPlayerID") + 2]
        and raw[44:49] == fields["name"][:5]
    ):
        if main[offset("wPikachuOverworldStateFlags")] & 2:
            raise JournalError("sleeping starter Pikachu cannot be deposited")
        happiness = offset("wPikachuHappiness")
        main[happiness] = max(0, main[happiness] - (5 if main[happiness] >= 200 else 3))
        mood = offset("wPikachuMood")
        main[mood] = min(main[mood], 98)
    boxed = bytearray(raw[:33])
    boxed[3] = raw[33]
    from server.gen1_grave_storage import append

    append(point, fields, cart, bytes(boxed) + raw[44:66],
           reserved_digest=reserved_digest, policy=storage_policy)
    slot, remaining = selected["slot"], party[0] - 1
    for base, stride in ((8, 44), (272, 11), (338, 11)):
        party[base + slot * stride : base + remaining * stride] = party[
            base + (slot + 1) * stride : base + (remaining + 1) * stride
        ]
        party[base + remaining * stride : base + (remaining + 1) * stride] = bytes(stride)
    party[0] = remaining
    party[1 : remaining + 2] = bytes([party[8 + 44 * i] for i in range(remaining)] + [255])
    after = copy.deepcopy(point)
    after["fields"] = {name: bytes(value).hex().upper() for name, value in fields.items()}
    after["cart_hex"] = bytes(cart).hex().upper()
    after["cart_hex"] = image(after).hex().upper()
    after["save_status"] = 2
    _inventory(after, identity)
    return after


def verify_receipt(
    command,
    receipt,
    *,
    before,
    identity,
    context_generation,
    final_sha1,
    frame,
    reserved_digest=None,
    storage_policy=None,
):
    """Check against a caller-owned preimage, never a receipt-chosen preimage."""
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
        raise JournalError("complete memorial save receipt required")
    body = command["body"]
    if body.get("cmd") != "memorialize" or not body.get("death_id"):
        raise JournalError("owned death memorial command required")
    wanted = {
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "body_digest": digest(body),
        "context_generation": context_generation,
        "final_sha1": final_sha1,
        "before_digest": digest(before),
    }
    if any(type(receipt[k]) is not type(v) or receipt[k] != v for k, v in wanted.items()):
        raise JournalError("memorial receipt command/context/preimage differs")
    after = expected(
        before, body.get("key"), identity=identity, reserved_digest=reserved_digest,
        storage_policy=storage_policy,
    )
    if receipt["after"] != after:
        raise JournalError("memorial storage/save differs from its exact prepared poststate")
    verify_file_image(
        receipt["file"],
        bytes.fromhex(after["cart_hex"]),
        host_profile="bizhawk-2.11.1-gambatte-exclusive-hold-v1",
        frame_from=frame,
        frame_to=frame,
    )
    return {
        "key": body["key"],
        "reservation_digest": reservation(after),
        "after_digest": digest(after),
    }
