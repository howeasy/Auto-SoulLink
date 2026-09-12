"""RBY memorial storage choices, never execution or ownership authority.

The cartridge keeps its active box in WRAM (ChangeBox copies the entire box
and empties the source header). A full box has twenty slots; BillsPCDeposit
refuses to remove the last party member. This policy preserves those limits.
"""

import hashlib

from server.gen1_full_save import SYMBOLS, image
from server.gen1_initial_observation import inventory
from server.gen1_native_trade_receipts import _bytes
from server.gen1_party_codec import PartyCodecError
from server.protocol import digest
from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import LinkStatus

BOX_SIZE = 1122
GRAVE_BOX = 11
CAPACITY = 20


class MemorialRecoveryRequired(JournalError):
    """A known capacity condition, not permission to delete or adopt storage."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def box_offset(index):
    if type(index) is not int or not 0 <= index < 12:
        raise JournalError("memorial box must be within the twelve cartridge boxes")
    return (2 + index // 6) * 0x2000 + (index % 6) * BOX_SIZE


def current_box(point):
    image(point)
    symbols = SYMBOLS["pokeyellow" if point["variant"] == "yellow" else "pokered"]
    main = bytes.fromhex(point["fields"]["main"])
    flag = main[symbols["wCurrentBoxNum"] - symbols["wMainDataStart"]]
    if flag & 127 >= 12:
        raise JournalError("invalid current memorial box")
    return flag & 127, bool(flag & 128)


def box_image(point, index):
    """Read the authoritative storage, excluding stale active-slot SRAM tails."""
    active, initialized = current_box(point)
    offset = box_offset(index)
    if index == active:
        return _bytes(point["fields"]["box"], BOX_SIZE)
    if not initialized:
        raise JournalError("inactive box has not been initialized by the cartridge")
    return _bytes(point["cart_hex"], 0x8000)[offset : offset + BOX_SIZE]


def grave_digest(point):
    active, initialized = current_box(point)
    if active != GRAVE_BOX and not initialized:
        start = box_offset(GRAVE_BOX)
        raw = _bytes(point["cart_hex"], 0x8000)[start : start + BOX_SIZE]
    else:
        raw = box_image(point, GRAVE_BOX)
    return hashlib.sha256(raw).hexdigest()


def entirely_empty(raw, *, before_init=False):
    """A zero count alone cannot reserve stale or hidden monster/name bytes."""
    if before_init:
        return (
            isinstance(raw, bytes)
            and len(raw) == BOX_SIZE
            and (
                raw == b"\xff" * BOX_SIZE
                or (raw[:2] in (b"\0\0", b"\0\xff") and raw[2:] == bytes(BOX_SIZE - 2))
            )
        )
    return (
        isinstance(raw, bytes)
        and len(raw) == BOX_SIZE
        and raw[:2] == b"\0\xff"
        and all(value in (0, 255) for value in raw[2:])
    )


def empty_archive_candidates(point):
    """List inactive boxes whose entire image proves there is nothing to replace.

    This is a proposal, not authorization to take a normal box for memorials.
    The caller must durably reserve the selected destination and retain its
    preimage in the same prepared transaction that would move the archive.
    """
    active, initialized = current_box(point)
    if not initialized:
        return []
    return [
        index
        for index in range(12)
        if index not in (active, GRAVE_BOX) and entirely_empty(box_image(point, index))
    ]


def storage_policy(point, *, reserved_digest=None):
    """Choose a non-destructive image operation, bound to its entire preimage.

    Only a previously reserved grave may rotate. The destination must be
    inactive and completely empty, so normal live/unowned contents never move.
    The prepared payload and exact file receipt durably retain all archive bytes.
    """
    active, initialized = current_box(point)
    if reserved_digest is not None and reserved_digest != grave_digest(point):
        raise JournalError("memorial reservation changed")
    raw = box_image(point, GRAVE_BOX) if initialized or active == GRAVE_BOX else None
    if not initialized and not active:
        start = box_offset(GRAVE_BOX)
        unowned = _bytes(point["cart_hex"], 0x8000)[start : start + BOX_SIZE]
        if not entirely_empty(unowned, before_init=True):
            raise JournalError("empty grave contains unowned bytes; reconciliation required")
    count = raw[0] if raw is not None else 0
    if count > CAPACITY:
        raise JournalError("invalid memorial box capacity")
    if count and reserved_digest is None:
        raise JournalError("nonempty memorial requires an owned reservation")
    if raw is not None and count == 0 and reserved_digest is None and not entirely_empty(raw):
        raise JournalError("empty grave contains unowned bytes; reconciliation required")
    rotation = None
    if count == CAPACITY:
        candidates = empty_archive_candidates(point)
        if not candidates:
            raise MemorialRecoveryRequired(
                "no-empty-archive-box",
                "memorial box full; no proved-empty inactive archive box is available",
            )
        destination = candidates[0]
        rotation = {
            "box": destination,
            "empty_digest": hashlib.sha256(box_image(point, destination)).hexdigest(),
            "archive_digest": hashlib.sha256(raw).hexdigest(),
        }
    return {
        "schema": "rby-memorial-storage-policy-v1",
        "before_digest": digest(point),
        "grave_box": GRAVE_BOX,
        "active_grave": active == GRAVE_BOX,
        "rotation": rotation,
    }


def terminal_retention(stage, player, death_id, point):
    """Attest a last dead party member without pretending it was deposited.

    The caller must bind this point to an owned read command and persist the
    attestation. This function neither completes memorial rules nor clears
    blockers; terminal execution and all outstanding physical obligations stay
    blocked. It makes no SaveRAM/file-persistence claim.
    """
    if player not in ("a", "b") or not isinstance(stage.rules, StagedSoulLinkState):
        raise JournalError("detached terminal rule state required")
    rules = stage.rules
    if rules.run_over is not True or any(link.status == LinkStatus.ALIVE for link in rules.links):
        raise JournalError("terminal retention requires a run with no live linked pair")
    document = stage.document()
    # The component name is owned by the faint runtime, whose current constant
    # is imported lazily to avoid policy/runtime construction cycles.
    from server.gen1_faint_runtime import COMPONENT as FAINT

    death = document["components"].get(FAINT, {}).get("deaths", {}).get(death_id)
    if not isinstance(death, dict) or death.get("phase") != "pending_memorial":
        raise JournalError("terminal retention requires completed peer faint evidence")
    key = death["key"] if death["player"] == player else death["peer_key"]
    link = rules.find_link(player, key)
    if (
        link is None
        or link.status != LinkStatus.DEAD
        or key not in rules.pending_memorials[player]
        or key in rules.party_keys[player]
        or death_id not in stage.barrier.document()["blockers"]
        or rules.document()["memorial"]["retired_pairs"].count(rules._memorial_record(link))
    ):
        raise JournalError("terminal retention must preserve the exact blocked death obligation")
    try:
        roster = inventory(point, rules.player_identity[player])
    except PartyCodecError as error:
        raise JournalError(str(error)) from error
    party = [mon for mon in roster["members"] if mon["location"] == "party"]
    if len(party) != 1 or party[0]["key"] != key:
        raise JournalError("terminal retention must identify the exact last party member")
    if bytes.fromhex(party[0]["blob_hex"])[1:3] != b"\0\0":
        raise JournalError("terminal retained party member is not physically fainted")
    return {
        "schema": "rby-terminal-memorial-retention-v1",
        "player": player,
        "death_id": death_id,
        "key": key,
        "disposition": "retained-dead-party",
        "point_digest": digest(point),
        "blob_digest": party[0]["evidence_digest"],
        "party_slot": party[0]["slot"],
        "saved": False,
        "memorial_complete": False,
        "ordinary_execution": False,
    }
