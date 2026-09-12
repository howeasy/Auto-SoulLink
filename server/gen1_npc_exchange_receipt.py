"""Source-qualified NPC in-game exchange facts. This module settles no rules.

An exchange receipt is three read-only witnesses: the map script's `ld [wWhichTrade], a`
(register A = trade index; the store's PC names the source), the engine's `call
RemovePokemon` (party still intact, wWhichPokemon = the outgoing slot, wCurEnemyLevel = its
level, wTradedEnemyMonOTID already rolled) and the `call ClearScreen` reached only after
AddPartyMon, InGameTrade_CopyDataToReceivedMon and the trade-evolution hook returned. The
incoming record is re-synthesized the way the engine builds it: AddPartyMon at the outgoing
level with random DVs, then the table nickname, the `<TRAINER>` OT string and the random OT
id copied over it; for Yellow's forced Machoke evolution the species, stats, HP and types
follow Machamp while the catch-rate byte, experience and moves stay Machoke's. The result is
a fact for the coordinator's identity migration, never a migration itself.
"""

import json
from pathlib import Path

from server.gen1_grant_receipt import (
    FRESH,
    box,
    fresh_catch_rate,
    fresh_moves,
    fresh_pp,
    fresh_stats,
    party,
)
from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.protocol import digest
from server.protocol_journal import JournalError

_DATA_DIR = Path(__file__).resolve().parents[1] / "data/games/gen1_rby"
DATA = json.loads((_DATA_DIR / "npc_exchange_sites.json").read_text())
SCHEMA = "rby-npc-exchange-receipt-v1"
WITNESS = {"frame", "pc", "bank", "sp", "point"}
POINT = {
    "party_hex",
    "box_hex",
    "trainer_hex",
    "player_id_hex",
    "map_id",
    "battle_flag",
    "which_trade",
    "which_pokemon",
    "cur_species",
    "cur_level",
    "mon_location",
    "remove_from_box",
    "give_species",
    "receive_species",
    "traded_ot_id_hex",
    "trade_nick_hex",
    "current_box",
}
BYTES = {"which_trade", "which_pokemon", "cur_species", "cur_level", "mon_location", "remove_from_box", "give_species",
         "receive_species", "map_id", "battle_flag", "current_box"}
PARTY_OT, NAME = 272, 11


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise JournalError("invalid exchange " + label)
    return value


def _raw(value, length, label):
    if not isinstance(value, str) or len(value) != length * 2:
        raise JournalError("canonical exchange " + label + " bytes required")
    try:
        return bytes.fromhex(value)
    except ValueError as error:
        raise JournalError("canonical exchange " + label + " bytes required") from error


def _witness(value, site, label, *, extra=frozenset()):
    if not isinstance(value, dict) or set(value) != WITNESS | set(extra):
        raise JournalError("complete exchange " + label + " witness required")
    _integer(value["frame"], 0, 2**53 - 1, label + " frame")
    _integer(value["sp"], 0xC000, 0xDFFF, label + " stack")
    if (
        type(value["pc"]) is not int
        or value["pc"] != site["address"]
        or type(value["bank"]) is not int
        or value["bank"] != site["bank"]
    ):
        raise JournalError("exchange " + label + " site differs")
    for field in extra:
        _integer(value[field], 0, 255, label + " " + field)
    return value


def records(blob):
    """Raw 66-byte party records (struct + OT + nickname) in slot order, unmasked."""
    return [
        blob[8 + 44 * slot : 52 + 44 * slot] + blob[PARTY_OT + NAME * slot : PARTY_OT + NAME * (slot + 1)]
        + blob[338 + NAME * slot : 349 + NAME * slot]
        for slot in range(blob[0])
    ]


def _point(value, codec, identity, profile, label):
    if not isinstance(value, dict) or set(value) != POINT:
        raise JournalError("complete exchange " + label + " observation required")
    for field in BYTES:
        _integer(value[field], 0, 255, label + " " + field)
    name = _raw(value["trainer_hex"], NAME, label + " trainer")
    try:
        codec._name(name, "exchange save name")
    except PartyCodecError as error:
        raise JournalError(str(error)) from error
    _raw(value["player_id_hex"], 2, label + " player id")
    if identity != {"ot_id": value["player_id_hex"], "trainer_name": display_name(name)}:
        raise JournalError("exchange " + label + " belongs to another save")
    if value["battle_flag"] != profile["out_of_battle_flag"]:
        raise JournalError("exchange " + label + " is not an out-of-battle delivery")
    party_raw = _raw(value["party_hex"], 404, label + " party")
    box_raw = _raw(value["box_hex"], 1122, label + " box")
    if party_raw[0] > 6 or box_raw[0] > 20:
        raise JournalError("invalid exchange " + label + " storage count")
    try:
        decoded_party = party(codec, party_raw)
        decoded_box = box(codec, box_raw)
    except JournalError as error:
        raise JournalError("exchange " + label + " storage: " + str(error)) from error
    if {mon.key for mon in decoded_party} & {row["key"] for row in decoded_box}:
        raise JournalError("exchange " + label + " has one key in both party and current box")
    return {
        "party": decoded_party,
        "records": records(party_raw),
        "party_raw": party_raw,
        "box_raw": box_raw,
        "box_keys": {row["key"] for row in decoded_box},
        "traded_ot_id": _raw(value["traded_ot_id_hex"], 2, label + " traded OT id"),
        "trade_nick": _raw(value["trade_nick_hex"], NAME, label + " trade nickname"),
        "name": name,
    }


def _received(codec, content, profile, site, mon, record, level, ot_id):
    """AddPartyMon at the outgoing level, then InGameTrade_CopyDataToReceivedMon, then the trade evolution."""
    receive, delivered = site["receive_species"], site["delivered_species"]
    facts = codec.profile["species"][str(delivered)]
    stats = fresh_stats(codec, delivered, mon.dv_word, level)
    if (
        mon.species_index != delivered
        or mon.level != level
        or mon.box_level != 0
        or mon.status != 0
        or mon.ot_id != ot_id
        or record[44:55] != bytes.fromhex(profile["engine"]["trainer_string"]["expected_hex"])
        or record[55:66] != bytes.fromhex(site["nickname_hex"])
        or mon.types != tuple(facts["types"])
        # Evolution never rewrites the catch-rate byte: it stays the received species' header value.
        or mon.catch_rate != fresh_catch_rate(content, receive)
        or mon.moves != fresh_moves(content, receive, level)
        or mon.experience != codec.experience_for_level(codec.profile["species"][str(receive)]["growth_rate"], level)
        or any(mon.stat_experience)
        or mon.computed_stats != stats
        or mon.hp != stats[0]
        or any(mon.pp_ups)
        or not fresh_pp(codec, mon.moves, mon.pp)
    ):
        raise JournalError("incoming mon is not the engine's construction for this exchange")


def validate(receipt, *, variant, identity, context_generation, physical_instance, final_sha1, rom_bytes=None, codec=None):
    """Return the completed exchange as a source-qualified fact, or refuse.

    `rom_bytes` is accepted for signature parity with the grant decoder but must be empty:
    the trade table is never a UPR claim, so no operand of an exchange is mutable under
    admission. `codec` may supply admitted species content for the receipt's title.
    """
    if not isinstance(variant, str) or variant not in DATA["titles"]:
        raise JournalError("RBY exchange variant required")
    if rom_bytes:
        raise JournalError("exchange operands are never mutable: no ROM override is accepted")
    profile = DATA["titles"][variant]
    content = FRESH["titles"][variant]
    required = {"schema", "source_sha256", "variant", "context_generation", "physical_instance", "final_sha1", "source_id", "call", "remove", "return"}
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise JournalError("complete exchange receipt required")
    if (
        receipt["schema"] != SCHEMA
        or receipt["source_sha256"] != DATA["sha256"]
        or receipt["variant"] != variant
        or receipt["context_generation"] != context_generation
        or receipt["physical_instance"] != physical_instance
        or receipt["final_sha1"] != final_sha1
    ):
        raise JournalError("exchange source or physical context differs")
    source_id = receipt["source_id"]
    if not isinstance(source_id, str) or source_id not in profile["sites"]:
        raise JournalError("unknown exchange source")
    site = profile["sites"][source_id]
    call = _witness(receipt["call"], site["call"], "call", extra={"a"})
    remove = _witness(receipt["remove"], profile["engine"]["remove"], "remove")
    ret = _witness(receipt["return"], profile["engine"]["return"], "return")
    if not call["frame"] <= remove["frame"] <= ret["frame"]:
        raise JournalError("exchange witnesses are out of frame order")
    # Both engine calls sit in InGameTrade_DoTrade's own frame, eight bytes below the script's.
    if remove["sp"] != ret["sp"] or not remove["sp"] < call["sp"]:
        raise JournalError("exchange call/remove/return stack differs")
    if call["a"] != site["trade_index"]:
        raise JournalError("selector register differs from the pinned trade index")
    codec = codec or PartyCodec(variant)
    if not isinstance(codec, PartyCodec) or codec.variant != variant:
        raise JournalError("exchange codec must describe the receipt's title")
    before = _point(call["point"], codec, identity, profile, "call")
    removal = _point(remove["point"], codec, identity, profile, "remove")
    after = _point(ret["point"], codec, identity, profile, "return")
    for label, point in (("call", call["point"]), ("remove", remove["point"]), ("return", ret["point"])):
        if point["map_id"] != site["map_id"]:
            raise JournalError("exchange " + label + " map differs from its call site")
        if point["current_box"] != call["point"]["current_box"]:
            raise JournalError("current box changed during the exchange")
    for label, point in (("remove", remove["point"]), ("return", ret["point"])):
        if (
            point["which_trade"] != site["trade_index"]
            or point["give_species"] != site["give_species"]
            or point["receive_species"] != site["receive_species"]
            or point["cur_species"] != site["receive_species"]
        ):
            raise JournalError("exchange " + label + " trade globals differ from the pinned table row")
    if remove["point"]["mon_location"] != 0 or remove["point"]["remove_from_box"] != 0:
        raise JournalError("RemovePokemon was not addressed at the player's party")
    if removal["trade_nick"] != bytes.fromhex(site["nickname_hex"]) or after["trade_nick"] != removal["trade_nick"]:
        raise JournalError("trade nickname buffer differs from the pinned table row")
    if after["traded_ot_id"] != removal["traded_ot_id"]:
        raise JournalError("traded OT id changed between removal and delivery")
    if removal["party_raw"] != before["party_raw"]:
        raise JournalError("party changed between the dialogue and the removal")
    if not removal["box_raw"] == before["box_raw"] == after["box_raw"]:
        raise JournalError("current box changed during the exchange")
    slot = remove["point"]["which_pokemon"]
    if slot >= len(before["party"]):
        raise JournalError("outgoing slot is not in the party")
    outgoing = before["party"][slot]
    if outgoing.species_index != site["give_species"]:
        raise JournalError("outgoing mon is not the species this exchange takes")
    if remove["point"]["cur_level"] != outgoing.level or ret["point"]["cur_level"] != outgoing.level:
        raise JournalError("wCurEnemyLevel differs from the outgoing mon's level")
    # RemovePokemon compacts the slot away; AddPartyMon appends at the new count.
    if len(after["party"]) != len(before["party"]):
        raise JournalError("exchange must replace exactly one party mon")
    kept = before["records"][:slot] + before["records"][slot + 1 :]
    if after["records"][:-1] != kept:
        raise JournalError("party compaction differs from RemovePokemon")
    incoming, record = after["party"][-1], after["records"][-1]
    _received(codec, content, profile, site, incoming, record, outgoing.level, int.from_bytes(removal["traded_ot_id"], "big"))
    known = {mon.key for mon in before["party"]} | before["box_keys"]
    if incoming.key in known:
        raise JournalError("incoming mon duplicates an existing party or boxed key")
    return {
        "kind": "npc_exchange",
        "source_id": source_id,
        "exchange_id": site["exchange_id"],
        "trade_index": site["trade_index"],
        "map_id": site["map_id"],
        "give_species": site["give_species"],
        "receive_species": site["receive_species"],
        "delivered_species": site["delivered_species"],
        "outgoing": {
            "key": outgoing.key,
            "species_index": outgoing.species_index,
            "level": outgoing.level,
            "slot": slot,
            "blob_hex": before["records"][slot].hex().upper(),
        },
        "incoming": {
            "key": incoming.key,
            "species_index": incoming.species_index,
            "level": incoming.level,
            "slot": len(after["party"]) - 1,
            "blob_hex": record.hex().upper(),
            "ot_id": incoming.ot_id,
            "nickname": display_name(record[55:66]),
        },
        "call_frame": call["frame"],
        "remove_frame": remove["frame"],
        "return_frame": ret["frame"],
        "frame": ret["frame"],
        "receipt_digest": digest(receipt),
    }
