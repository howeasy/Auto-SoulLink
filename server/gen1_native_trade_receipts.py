"""Validate the durable RBY client's native execution and canonical SRAM receipt.

Admission and current physical ownership remain the runtime's responsibility.
This proves neither SaveRAM file flush nor paired recovery/permission to resume.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from server.gen1_command_receipts import validate_party_snapshot
from server.gen1_trade_result import TradeResultRules
from server.protocol_journal import JournalError, _encode

SEQUENCE = ["service", "InternalClockTradeAnim", "TryEvolvingMon", "SavePartyAndDexData"]
FIELDS = {"schema", "command_id", "command_sequence", "transaction_id", "proposal_digest",
          "prepared_digest", "context_generation", "final_sha1", "before", "after", "counts",
          "sequence", "token_hex", "generation", "save_file_verified"}


def _bytes(value, length=None):
    if (not isinstance(value, str) or len(value)%2 or not re.fullmatch(r"[0-9A-F]+", value)
            or length is not None and len(value) != length*2):
        raise JournalError("canonical native receipt bytes required")
    return bytes.fromhex(value)


def validate_party_storage(storage_hex, party):
    """Shared RBY UI/native readback check for the complete 404-byte party block."""
    storage = _bytes(storage_hex, 404)
    if storage[:len(party)+2] != bytes([len(party), *(mon.species_index for mon in party), 255]):
        raise JournalError("native party storage/list differs")
    for slot, mon in enumerate(party):
        raw = storage[8+44*slot:8+44*(slot+1)] + storage[272+11*slot:272+11*(slot+1)] + storage[338+11*slot:338+11*(slot+1)]
        if raw != mon.raw:
            raise JournalError("native party storage/blob differs")
    return storage


@dataclass(frozen=True)
class NativeTradeReadback:
    command_id: str
    received_key: str
    received_digest: str
    save_region_digest: str
    # An immutable result value cannot promote an SRAM read into a disk flush.
    save_file_verified: bool = False


def verify_native_release(command, receipt, *, trade):
    """Close only the finalized trade's exact command and persisted native result."""
    body = command["body"]
    fields = {"schema", "command_id", "command_sequence", "transaction_id", "proposal_digest",
              "native_command_id", "context_generation", "final_sha1", "after"}
    if (trade["phase"] != "link_committed" or body["cmd"] != "native_trade_release"
            or body["payload"]["schema"] != "paired-trade-release-v1"
            or not isinstance(receipt, dict) or set(receipt) != fields
            or receipt["schema"] != "rby-native-release-receipt-v1"):
        raise JournalError("finalized native trade closure required")
    native = trade["applied"][body["player"]]
    for key in ("command_id", "command_sequence"):
        if type(receipt[key]) is not type(command[key]) or receipt[key] != command[key]:
            raise JournalError("native release command identity differs")
    if (any(receipt[key] != body[key] or receipt[key] != native[key]
            for key in ("transaction_id", "proposal_digest"))
            or receipt["transaction_id"] != trade["id"] or receipt["proposal_digest"] != trade["proposal_digest"]
            or receipt["native_command_id"] != native["command_id"]
            or receipt["context_generation"] != native["context_generation"]
            or receipt["final_sha1"] != native["final_sha1"]
            or _encode(receipt["after"])[1] != _encode(native["after"])[1]):
        raise JournalError("native closure differs from the verified transaction/party/save")
    return receipt


def verify_native_trade_receipt(command, receipt, *, rules: TradeResultRules, boxed_keys):
    """Called only under the admitted connection/physical-context owner."""
    if not isinstance(rules, TradeResultRules):
        raise JournalError("admitted cartridge trade rules required")
    if (not isinstance(receipt, dict) or set(receipt) != FIELDS
            or receipt["schema"] != "rby-native-execution-v1"
            or receipt["save_file_verified"] is not False):
        raise JournalError("native SRAM receipt schema differs")
    if (not isinstance(command, dict) or not re.fullmatch(r"[0-9a-f]{32}", command.get("command_id", ""))
            or type(command.get("command_sequence")) is not int or command["command_sequence"] < 1):
        raise JournalError("stored native command identity required")
    body = command["body"]
    if body.get("cmd") != "native_trade_commit" or body.get("player") not in ("a", "b"):
        raise JournalError("paired native COMMIT required")
    payload = body["payload"]
    if (payload.get("schema") != "paired-native-commit-v1"
            or _encode(payload["proposal"])[1] != body["proposal_digest"]
            or _encode(payload["prepared"])[1] != payload["prepared_digest"]):
        raise JournalError("native prepared proposal differs")
    for field in ("command_id", "command_sequence"):
        if type(receipt[field]) is not type(command[field]) or receipt[field] != command[field]:
            raise JournalError("native receipt command differs")
    for field in ("transaction_id", "proposal_digest"):
        if receipt[field] != body[field]:
            raise JournalError("native receipt transaction differs")
    if receipt["prepared_digest"] != payload["prepared_digest"] or receipt["final_sha1"] != rules.rom_sha1:
        raise JournalError("native receipt cartridge/preparation differs")
    if (receipt["sequence"] != SEQUENCE or receipt["counts"] != dict.fromkeys(SEQUENCE, 1)
            or any(type(value) is not int for value in receipt["counts"].values())):
        raise JournalError("complete original native animation/evolution/save sequence required")
    if type(receipt["generation"]) is not int or not 1 <= receipt["generation"] <= 255:
        raise JournalError("native lease generation differs")
    if _bytes(receipt["token_hex"], 4) == bytes(4):
        raise JournalError("native lease token absent")
    player = body["player"]
    selected = payload["proposal"]["participants"][player]
    peer = payload["proposal"]["participants"]["b" if player == "a" else "a"]
    prepared = payload["prepared"]
    if (receipt["context_generation"] != selected["context"]["context_generation"]
            or prepared["context_generation"] != receipt["context_generation"]
            or prepared["proposal_digest"] != receipt["proposal_digest"]
            or prepared["evidence_digest"] != selected["evidence_digest"]):
        raise JournalError("native physical context differs")
    before, after = receipt["before"], receipt["after"]
    expected_fields = {"party", "party_storage_hex", "save_region_hex", "dex_hex", "save_name_hex", "map"}
    if rules.variant == "yellow":
        expected_fields.add("pikachu_hex")
    if any(not isinstance(value, dict) or set(value) != expected_fields for value in (before, after)):
        raise JournalError("complete native before/after snapshot required")
    parties = []
    for observed in (before, after):
        party = validate_party_snapshot(observed["party"], variant=rules.variant)
        if observed["party"]["battle_flag"] != 0:
            raise JournalError("native trade receipt is not an overworld result")
        save = selected["context"]["save_identity"]
        if observed["party"]["save_id"] != save["ot_id"] or observed["party"]["save_name"] != save["trainer_name"]:
            raise JournalError("native save identity differs")
        validate_party_storage(observed["party_storage_hex"], party)
        if type(observed["map"]) is not int or not 0 <= observed["map"] <= 255:
            raise JournalError("native source map required")
        parties.append(party)
    if before["party"]["party"] != selected["snapshot"]["party"]:
        raise JournalError("native prestate differs from the prepared party")
    if before["map"] != after["map"] or before["save_name_hex"] != after["save_name_hex"]:
        raise JournalError("native map/save name changed")
    incoming = _bytes(peer["snapshot"]["party"][peer["slot"]], 66)
    pre, post = parties
    outcome = rules.verify_party([mon.raw for mon in pre], selected["slot"], incoming,
        [mon.raw for mon in post], expected_key=selected["key"], incoming_key=peer["key"], boxed_keys=boxed_keys)
    digest = rules.verify_save_region(_bytes(after["save_region_hex"]), _bytes(after["party_storage_hex"], 404),
        [mon.raw for mon in post], before_region=_bytes(before["save_region_hex"]), before_dex=_bytes(before["dex_hex"], 38),
        incoming=incoming, outgoing=pre[selected["slot"]].raw, outcome=outcome,
        save_id=before["party"]["save_id"], save_name=_bytes(before["save_name_hex"], 11),
        before_pikachu=_bytes(before["pikachu_hex"], 2) if rules.variant == "yellow" else None)
    expected_dex = bytearray(_bytes(before["dex_hex"], 38))
    for species in (rules.codec.validate_blob(incoming).species_index, *outcome.evolution_path):
        dex = rules.codec.profile["species"][str(species)]["dex"]-1
        for base in (0, 19):
            expected_dex[base+dex//8] |= 1 << (dex % 8)
    if _bytes(after["dex_hex"], 38) != expected_dex:
        raise JournalError("native live Pokédex differs from the verified save")
    if rules.variant == "yellow":
        expected = _bytes(before["pikachu_hex"], 2)
        outgoing = pre[selected["slot"]]
        if (outgoing.species_index == 84 and outgoing.ot_id == int(before["party"]["save_id"], 16)
                and outgoing.ot_name[:5] == _bytes(before["save_name_hex"], 11)[:5]):
            expected = bytes((max(0, expected[0]-(20 if expected[0] >= 200 else 10)), 0))
        if _bytes(after["pikachu_hex"], 2) != expected:
            raise JournalError("native live Pikachu state differs from the verified save")
    return NativeTradeReadback(command["command_id"], post[-1].key, post[-1].sha256, digest)
