"""Independent RBY native UI readback validation beneath an owned runtime policy.

These functions validate bound evidence, not client admission or frame authority.
The caller owns the expected artifact, physical context and current party evidence.
"""

from __future__ import annotations

import re

from server.gen1_command_receipts import validate_party_snapshot
from server.gen1_native_trade_receipts import _bytes, validate_party_storage
from server.protocol_journal import JournalError, _encode


def verify_receptionist_offer(payload, *, manifest, context, snapshot):
    fields = {
        "schema",
        "final_sha1",
        "context_generation",
        "query_generation",
        "offer_generation",
        "token_hex",
        "slot",
        "key",
        "snapshot",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != fields
        or payload["schema"] != "rby-receptionist-offer-v1"
        or payload["final_sha1"] != manifest["final_sha1"]
        or payload["context_generation"] != context.context_generation
    ):
        raise JournalError("native receptionist offer binding differs")
    if any(
        type(payload[name]) is not int or not 0 <= payload[name] <= 255
        for name in ("query_generation", "offer_generation")
    ):
        raise JournalError("native receptionist lease generation differs")
    if _bytes(payload["token_hex"], 4) == bytes(4):
        raise JournalError("native receptionist lease token is missing")
    party = validate_party_snapshot(payload["snapshot"], variant=manifest["variant"])
    if (
        payload["snapshot"] != snapshot
        or snapshot["battle_flag"] != 0
        or snapshot["save_id"] != context.save_identity.ot_id
        or snapshot["save_name"] != context.save_identity.trainer_name
    ):
        raise JournalError("native receptionist party/save differs from current owned observation")
    slot = payload["slot"]
    if (
        type(slot) is not int
        or not 0 <= slot < len(party)
        or party[slot].key != payload["key"]
        or party[slot].hp == 0
    ):
        raise JournalError("native receptionist selection is not the current live member")
    return payload["key"]


def verify_partner_prompt(command, receipt, *, manifest):
    fields = {
        "schema",
        "command_id",
        "command_sequence",
        "transaction_id",
        "proposal_digest",
        "context_generation",
        "final_sha1",
        "result",
        "token_hex",
        "generation",
        "before",
        "after",
        "sequence",
        "counts",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != fields
        or receipt["schema"] != "rby-native-prompt-v1"
    ):
        raise JournalError("native partner receipt schema differs")
    body = command["body"]
    if body["cmd"] != "native_trade_prompt" or body["payload"]["schema"] != "rby-native-prompt-v1":
        raise JournalError("native partner prompt command required")
    proposal = body["payload"]["proposal"]
    if _encode(proposal)[1] != body["proposal_digest"]:
        raise JournalError("native prompt proposal digest differs")
    own = proposal["participants"][body["player"]]
    for field in ("command_id", "command_sequence"):
        if type(receipt[field]) is not type(command[field]) or receipt[field] != command[field]:
            raise JournalError("native prompt command identity differs")
    if (
        any(receipt[field] != body[field] for field in ("transaction_id", "proposal_digest"))
        or receipt["context_generation"] != own["context"]["context_generation"]
        or receipt["final_sha1"] != manifest["final_sha1"]
    ):
        raise JournalError("native prompt transaction/context/artifact differs")
    if type(receipt["result"]) is not int or receipt["result"] not in (0, 1, 3):
        raise JournalError("native partner result is uncertain")
    expected = ["service", "prompt"] + ([] if receipt["result"] == 3 else ["choice"])
    if (
        receipt["sequence"] != expected
        or receipt["counts"] != dict.fromkeys(expected, 1)
        or any(type(value) is not int for value in receipt["counts"].values())
    ):
        raise JournalError("native partner prompt/choice path was not observed exactly once")
    if (
        type(receipt["generation"]) is not int
        or not 1 <= receipt["generation"] <= 255
        or _bytes(receipt["token_hex"], 4) == bytes(4)
    ):
        raise JournalError("native prompt lease differs")
    before = receipt["before"]
    if (
        not isinstance(before, dict)
        or set(before)
        != {"party", "map", "fields", "party_storage_hex", "tiles_hex", "cart_digest"}
        or _encode(before)[1] != _encode(receipt["after"])[1]
    ):
        raise JournalError("native prompt changed party/save/map/controls")
    validate_prompt_view(before, manifest=manifest, participant=own)
    return receipt["result"] == 0


def validate_prompt_view(before, *, manifest, participant):
    """Validate read-only UI state; this function proves no native execution."""
    if not isinstance(before, dict) or set(before) != {"party", "map", "fields", "party_storage_hex", "tiles_hex", "cart_digest"}:
        raise JournalError("complete native prompt view is required")
    party = validate_party_snapshot(before["party"], variant=manifest["variant"])
    validate_party_storage(before["party_storage_hex"], party)
    _bytes(before["tiles_hex"], 360)
    if (
        type(before["map"]) is not int
        or not 0 <= before["map"] <= 255
        or not isinstance(before["cart_digest"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", before["cart_digest"])
        or not isinstance(before["fields"], dict)
        or set(before["fields"]) != set(manifest["receptionist"]["partner_prompt"]["saved_fields"])
        or any(
            type(value) is not int or not 0 <= value <= 255 for value in before["fields"].values()
        )
    ):
        raise JournalError("complete native prompt view is required")
    save = participant["context"]["save_identity"]
    if (
        before["party"]["battle_flag"] != 0
        or before["party"]["party"] != participant["snapshot"]["party"]
        or before["party"]["save_id"] != save["ot_id"]
        or before["party"]["save_name"] != save["trainer_name"]
    ):
        raise JournalError("native prompt prestate differs from its prepared participant")
    return party
