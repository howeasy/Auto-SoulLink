"""Generation-owned grave image mechanics shared by memorial and retirement.

Mutates only caller-detached bytearrays. It grants no write or reservation
authority; callers bind the original point, target removal and saved receipt.
"""

from server.gen1_full_save import SYMBOLS, layout
from server.gen1_memorial_policy import (
    BOX_SIZE,
    box_offset,
    entirely_empty,
    grave_digest,
    storage_policy,
)
from server.protocol_journal import JournalError


def validate_saved(point):
    info = layout(point["variant"])
    symbols = SYMBOLS["pokeyellow" if point["variant"] == "yellow" else "pokered"]
    main = bytes.fromhex(point["fields"]["main"])
    cart = bytes.fromhex(point["cart_hex"])
    identity = symbols["wPlayerID"] - symbols["wMainDataStart"]
    flag = symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]
    saved = info["regions"]["main"]["target"]
    if (
        sum(cart[info["start"] : info["checksum"] + 1]) % 256 != 255
        or cart[info["start"] : info["start"] + 11] != bytes.fromhex(point["fields"]["name"])
        or cart[saved + identity : saved + identity + 2] != main[identity : identity + 2]
        or cart[saved + flag] != main[flag]
    ):
        raise JournalError("memorial requires the same valid saved trainer and current box")


def checksum_banks(cart, banks):
    for bank in sorted(banks):
        sums = [
            sum(cart[bank * 0x2000 + i * BOX_SIZE : bank * 0x2000 + (i + 1) * BOX_SIZE])
            for i in range(6)
        ]
        offset = bank * 0x2000 + 0x1A4C
        cart[offset : offset + 7] = bytes(
            [(255 - sum(sums)) & 255, *((255 - value) & 255 for value in sums)]
        )


def append(point, fields, cart, boxed, *, reserved_digest=None, policy=None):
    """Append a fainted 33+11+11 record, preserving owned full archives."""
    if not isinstance(boxed, bytes) or len(boxed) != 55 or boxed[1:3] != b"\0\0":
        raise JournalError("fainted complete box record required for archival")
    validate_saved(point)
    symbols = SYMBOLS["pokeyellow" if point["variant"] == "yellow" else "pokered"]
    flag_offset = symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]
    flag = bytes.fromhex(point["fields"]["main"])[flag_offset]
    active = flag & 127 == 11
    initializing = not flag & 128
    if active and initializing:
        raise JournalError("active memorial box cannot precede box initialization")
    if active and policy is None:
        raise JournalError("active memorial box requires reconciliation")
    if reserved_digest is not None and reserved_digest != grave_digest(point):
        raise JournalError("memorial reservation changed")
    offset = box_offset(11)
    grave = fields["box"] if active else bytearray(cart[offset : offset + BOX_SIZE])
    if initializing and not active and not entirely_empty(bytes(grave), before_init=True):
        raise JournalError("unowned memorial box is not empty before initialization")
    count = 0 if initializing and not active else grave[0]
    if count and reserved_digest is None:
        raise JournalError("nonempty memorial requires an owned reservation")
    if not initializing and count == 0 and reserved_digest is None and not entirely_empty(bytes(grave)):
        raise JournalError("empty grave contains unowned bytes; reconciliation required")
    if count >= 20 and policy is None:
        raise JournalError("memorial box full")
    if not initializing or active:
        for slot in range(20):
            index = 22 + 33 * slot
            # Canonical RemovePokemon can leave the vacated slot19 bytes.
            # Only an exact prior owned reservation may overwrite unused
            # tails; occupied live members and every unowned tail still refuse.
            if (
                grave[index] not in (0, 255)
                and grave[index + 1 : index + 3] != b"\0\0"
                and (slot < count or reserved_digest is None)
            ):
                raise JournalError("memorial contains live or hidden live storage")
    changed = set()
    if policy is not None:
        if policy != storage_policy(point, reserved_digest=reserved_digest):
            raise JournalError("memorial storage policy differs from its exact owned preimage")
        rotation = policy["rotation"]
        if rotation is not None:
            destination = box_offset(rotation["box"])
            cart[destination : destination + BOX_SIZE] = grave
            changed.add(2 + rotation["box"] // 6)
            grave = bytearray(BOX_SIZE)
            grave[1] = 255
            count = 0
    if initializing:
        for bank in (2, 3):
            for slot in range(6):
                start = bank * 0x2000 + slot * BOX_SIZE
                cart[start : start + 2] = b"\0\xff"
        fields["main"][flag_offset] |= 128
        changed.update((2, 3))
    for index, value in (
        (22 + 33 * count, boxed[:33]),
        (682 + 11 * count, boxed[33:44]),
        (902 + 11 * count, boxed[44:]),
    ):
        grave[index : index + len(value)] = value
    grave[count + 1 : count + 3] = bytes((boxed[0], 255))
    grave[0] = count + 1
    if active:
        fields["box"] = grave
    else:
        cart[offset : offset + BOX_SIZE] = grave
        changed.add(3)
    checksum_banks(cart, changed)
    return {"box": 11, "slot": count, "rotation": policy["rotation"] if policy else None}
