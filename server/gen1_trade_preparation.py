"""Independent RBY preparation checks. Admission, liveness and holds are external.

Physical box bytes are retained so omitted/colliding keys cannot be accepted as
an empty inventory. This is read-only evidence, not a save-file flush or grant.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from server.gen1_command_receipts import validate_party_snapshot
from server.gen1_native_trade_receipts import _bytes, validate_party_storage
from server.gen1_trade_result import TradeResultRules
from server.protocol import digest
from server.protocol_journal import JournalError
from server.trade_coordinator import PreparedTrade

SCHEMA = "rby-trade-checkpoint-v1"
FIELDS = {"schema", "final_sha1", "party", "party_storage_hex", "name_hex", "map",
          "current_box", "active_box_hex", "cart_hex"}
SYMBOLS = json.loads((Path(__file__).resolve().parents[1]/"data/pret_syms.json").read_text())


def boxed_keys(checkpoint, codec):
    """Current WRAM box plus initialized inactive SRAM slots, including box12.

    Matches the cartridge's active-box authority and first-ChangeBox boundary.
    Unused records and the active box's stale SRAM copy are not live inventory.
    This validates identity/list structure; it is not full boxed-stat validation.
    """
    flag = checkpoint["current_box"]
    if type(flag) is not int or not 0 <= flag <= 255 or flag & 127 >= 12:
        raise JournalError("invalid current RBY box")
    active = _bytes(checkpoint["active_box_hex"], 1122)
    cart = _bytes(checkpoint["cart_hex"], 0x8000)
    keys = set()
    for index in range(12):
        if index == flag & 127:
            raw = active
        elif flag & 128:
            offset = (2+index//6)*0x2000+(index % 6)*1122
            raw = cart[offset:offset+1122]
        else:
            continue
        count = raw[0]
        if count > 20 or raw[count+1] != 255:
            raise JournalError("invalid stored RBY count/species terminator")
        for slot in range(count):
            mon = raw[22+33*slot:22+33*(slot+1)]
            if str(mon[0]) not in codec.profile["species"] or raw[slot+1] != mon[0]:
                raise JournalError("invalid stored RBY species list")
            key = f"{mon[27:29].hex().upper()}:{mon[12:14].hex().upper()}:{mon[0]:02X}"
            if key in keys:
                raise JournalError("duplicate stored RBY key")
            keys.add(key)
    return frozenset(keys)


def validate_checkpoint(checkpoint, *, rules, participant):
    if (not isinstance(rules, TradeResultRules) or not isinstance(checkpoint, dict)
            or set(checkpoint) != FIELDS or checkpoint["schema"] != SCHEMA
            or checkpoint["final_sha1"] != rules.rom_sha1):
        raise JournalError("complete admitted RBY trade checkpoint required")
    observed = checkpoint["party"]
    party = validate_party_snapshot(observed, variant=rules.variant)
    save = participant["context"]["save_identity"]
    if (observed["battle_flag"] != 0 or observed["party"] != participant["snapshot"]["party"]
            or observed["save_id"] != save["ot_id"] or observed["save_name"] != save["trainer_name"]):
        raise JournalError("preparation party/save differs from proposed participant")
    slot = participant["slot"]
    if (type(slot) is not int or not 0 <= slot < len(party) or not party[slot].hp
            or party[slot].key != participant["key"] or party[slot].sha256 != participant["evidence_digest"]):
        raise JournalError("preparation selected member differs")
    validate_party_storage(checkpoint["party_storage_hex"], party)
    if type(checkpoint["map"]) is not int or not 0 <= checkpoint["map"] <= 255:
        raise JournalError("preparation map required")
    name = _bytes(checkpoint["name_hex"], 11)
    rules.codec._name(name, "save trainer name")
    cart = _bytes(checkpoint["cart_hex"], 0x8000)
    symbols = SYMBOLS["pokeyellow" if rules.variant == "yellow" else "pokered"]
    # These main-save symbols are all in SRAM bank1; CartRAM is a flat domain.
    start, end = symbols["sGameData"]-0x8000, symbols["sMainDataCheckSum"]-0x8000+1
    player = symbols["sMainData"]-0x8000+symbols["wPlayerID"]-symbols["wMainDataStart"]
    if (sum(cart[start:end]) % 256 != 255 or cart[start:start+11] != name
            or cart[player:player+2].hex().upper() != save["ot_id"]):
        raise JournalError("preparation requires a valid canonical save with the same trainer")
    keys = boxed_keys(checkpoint, rules.codec)
    rules.codec.validate_party([mon.raw for mon in party], boxed_keys=keys)
    return keys


def preparation_payload(trade, player, *, rules, checkpoints):
    """Use current owned observations of both participants; no native execution."""
    proposal = trade["proposal"]
    if digest(proposal) != trade["proposal_digest"] or set(rules) != {"a", "b"}:
        raise JournalError("paired preparation proposal/rules required")
    inventories = {p: validate_checkpoint(checkpoints[p], rules=rules[p],
        participant=proposal["participants"][p]) for p in ("a", "b")}
    own, peer = proposal["participants"][player], proposal["participants"]["b" if player == "a" else "a"]
    incoming = _bytes(peer["snapshot"]["party"][peer["slot"]], 66)
    species = {outcome.blob[0] for outcome in rules[player].outcomes(incoming)}
    if len(species) != 1:
        raise JournalError("native preparation has ambiguous evolution species")
    evolved = species.pop()
    rules[player].codec.prepare_exchange([_bytes(raw, 66) for raw in own["snapshot"]["party"]],
        own["slot"], incoming, expected_key=own["key"], incoming_key=peer["key"],
        evolved_species=evolved, boxed_keys=inventories[player])
    return {"schema": "rby-native-prepare-v1", "proposal": copy.deepcopy(proposal),
        "evolved_species": evolved, "own_name_hex": checkpoints[player]["name_hex"],
        "peer_name_hex": checkpoints["b" if player == "a" else "a"]["name_hex"]}


def verify_preparation(command, receipt, *, rules):
    body = command["body"]
    payload = body["payload"]
    fields = {"schema", "command_id", "command_sequence", "transaction_id", "proposal_digest",
              "context_generation", "checkpoint"}
    if (body["cmd"] != "native_trade_prepare" or payload["schema"] != "rby-native-prepare-v1"
            or digest(payload["proposal"]) != body["proposal_digest"]
            or not isinstance(receipt, dict) or set(receipt) != fields or receipt["schema"] != "rby-native-ready-v1"):
        raise JournalError("bound native preparation receipt required")
    for key in ("command_id", "command_sequence"):
        if type(receipt[key]) is not type(command[key]) or receipt[key] != command[key]:
            raise JournalError("preparation command identity differs")
    for key in ("transaction_id", "proposal_digest"):
        if receipt[key] != body[key]:
            raise JournalError("preparation transaction differs")
    own = payload["proposal"]["participants"][body["player"]]
    peer = payload["proposal"]["participants"]["b" if body["player"] == "a" else "a"]
    if receipt["context_generation"] != own["context"]["context_generation"]:
        raise JournalError("preparation physical context differs")
    checkpoint = receipt["checkpoint"]
    keys = validate_checkpoint(checkpoint, rules=rules, participant=own)
    incoming = _bytes(peer["snapshot"]["party"][peer["slot"]], 66)
    if {outcome.blob[0] for outcome in rules.outcomes(incoming)} != {payload["evolved_species"]}:
        raise JournalError("prepared evolution differs from the recipient cartridge")
    rules.codec.prepare_exchange([_bytes(raw, 66) for raw in own["snapshot"]["party"]], own["slot"], incoming,
        expected_key=own["key"], incoming_key=peer["key"], evolved_species=payload["evolved_species"], boxed_keys=keys)
    rules.codec._name(_bytes(payload["peer_name_hex"], 11), "partner trainer name")
    if checkpoint["name_hex"] != payload["own_name_hex"]:
        raise JournalError("prepared trainer name changed")
    return PreparedTrade(body["proposal_digest"], receipt["context_generation"], own["evidence_digest"],
        {"schema": "rby-native-prepared-v1", "evolved_species": payload["evolved_species"],
         "peer_name_hex": payload["peer_name_hex"], "checkpoint_digest": digest(checkpoint),
         "boxed_keys": sorted(keys)})
