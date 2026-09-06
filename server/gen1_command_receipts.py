"""RBY physical command receipts, independently checked before durable ACK.

These are readback predicates, not an assertion that client-provided bytes are
cryptographically authenticated. Admission and the executor bind them to a save.
"""
from __future__ import annotations

import re

from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.protocol_journal import JournalError

SCHEMA = "gen1-party-readback-v1"
RECEIPT_SCHEMA = "gen1-force-faint-receipt-v1"
FIELDS = {"schema", "variant", "save_id", "save_name", "party_count", "party",
          "species_list", "battle_flag", "active_slot", "battle_hp"}


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise JournalError("invalid " + label)
    return value


def validate_party_snapshot(snapshot, *, variant):
    if (variant not in ("red", "blue", "yellow") or not isinstance(snapshot, dict)
            or set(snapshot) != FIELDS or snapshot.get("schema") != SCHEMA or snapshot.get("variant") != variant):
        raise JournalError("readback schema/variant mismatch")
    identity = snapshot.get("save_id")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9A-F]{4}", identity):
        raise JournalError("readback needs the save player ID")
    if (not isinstance(snapshot.get("save_name"), str) or not 1 <= len(snapshot["save_name"].encode("utf-8")) <= 40
            or any(ord(char) < 32 for char in snapshot["save_name"])):
        raise JournalError("readback needs the save name")
    count = _integer(snapshot.get("party_count"), 1, 6, "readback party count")
    encoded = snapshot.get("party")
    if not isinstance(encoded, list) or len(encoded) != count:
        raise JournalError("readback party count differs from its blobs")
    blobs = []
    for blob in encoded:
        if not isinstance(blob, str) or not re.fullmatch(r"[0-9A-F]{132}", blob):
            raise JournalError("readback needs canonical full party hex")
        blobs.append(bytes.fromhex(blob))
    try:
        party = PartyCodec(variant).validate_party(blobs, species_list=snapshot.get("species_list"))
    except PartyCodecError as exc:
        raise JournalError(str(exc)) from exc
    if not isinstance(snapshot.get("species_list"), list) or len(snapshot["species_list"]) != count + 1:
        raise JournalError("readback needs the exact count/species/$FF list")
    battle = _integer(snapshot.get("battle_flag"), 0, 2, "battle flag")
    if battle:
        _integer(snapshot.get("active_slot"), 0, count - 1, "active party slot")
        _integer(snapshot.get("battle_hp"), 0, 999, "battle HP")
    elif snapshot.get("active_slot") is not None or snapshot.get("battle_hp") is not None:
        raise JournalError("overworld readback must not assert an active battler")
    return party


def verify_force_faint(command, before, after, *, variant, identity):
    if not isinstance(command, dict) or command.get("cmd") != "force_faint":
        raise JournalError("force-faint receipt has the wrong command")
    pre = validate_party_snapshot(before, variant=variant)
    post = validate_party_snapshot(after, variant=variant)
    if not isinstance(identity, dict):
        raise JournalError("admitted save identity required")
    for snapshot in (before, after):
        if snapshot["save_id"] != identity.get("ot_id") or snapshot["save_name"] != identity.get("trainer_name"):
            raise JournalError("readback belongs to a different save")
    slots = [index for index, mon in enumerate(pre) if mon.key == command.get("key")]
    if len(slots) != 1 or len(pre) != len(post):
        raise JournalError("force-faint target is missing or party count changed")
    target = slots[0]
    if before["species_list"] != after["species_list"]:
        raise JournalError("force-faint changed party identities/order")
    for index, (old, new) in enumerate(zip(pre, post, strict=True)):
        expected = bytearray(old.raw)
        if index == target:
            expected[1:3] = b"\x00\x00"
        if new.raw != expected:
            raise JournalError("force-faint changed unrelated party data or did not clear HP")
    if before["battle_flag"] != after["battle_flag"] or before.get("active_slot") != after.get("active_slot"):
        raise JournalError("battle context changed across the write")
    expected_hp = before.get("battle_hp")
    if before["battle_flag"] and before["active_slot"] == target:
        expected_hp = 0
    if after.get("battle_hp") != expected_hp:
        raise JournalError("active battle HP mirror does not match force-faint")
    return {"key": command["key"], "slot": target}


def verify_force_faint_receipt(command, receipt, *, variant, identity):
    if (not isinstance(receipt, dict) or set(receipt) != {"schema", "before", "after"}
            or receipt.get("schema") != RECEIPT_SCHEMA):
        raise JournalError("versioned force-faint receipt required")
    return verify_force_faint(command, receipt["before"], receipt["after"], variant=variant, identity=identity)


class Gen1ReceiptPolicy:
    """Receiver-specific physical proof callback for the staged dispatcher.

    Only force_faint ACK has a complete policy here. Other commands and terminal
    NACKs require their own proved no-effect/compensation rules before activation.
    The authoritative command comes from the journal, not from the ACK payload.
    """

    def __init__(self, variants):
        if (not isinstance(variants, dict) or set(variants) != {"a", "b"}
                or any(value not in ("red", "blue", "yellow") for value in variants.values())):
            raise JournalError("both admitted player variants are required")
        self._variants = dict(variants)

    def __call__(self, player, command, event, state):
        if (player not in self._variants or not isinstance(event, dict)
                or event.get("event") != "command_ack" or event.get("outcome") != "ACK"):
            raise JournalError("receipt policy requires an explicit physical ACK")
        if not isinstance(command, dict) or not isinstance(command.get("body"), dict):
            raise JournalError("authoritative journal command required")
        body = command["body"]
        if body.get("cmd") != "force_faint":
            raise JournalError("command has no verified RBY receipt policy")
        verify_force_faint_receipt(body, event.get("receipt"), variant=self._variants[player],
                                   identity=state.player_identity.get(player))
        # The original faint transition already marked the linked pair dead.
        # Confirming its physical effect must not manufacture a second faint.
        return []
