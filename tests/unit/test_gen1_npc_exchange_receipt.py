"""NPC exchange receipts: selector register, RemovePokemon compaction, engine-built incoming mon.

Every fixture here is synthetic: the incoming record is synthesized the way the engine
builds it (AddPartyMon at the outgoing level with chosen DVs, then the table nickname, the
`<TRAINER>` OT string and the rolled OT id copied over it; Yellow's RICKY row evolved to
Machamp with Machoke's catch-rate byte, experience and moves). Only the DVs and the OT id
are free, which is exactly what the decoder cannot pin. Sites, engine PCs, table rows and
the trainer string all come from the generated data, which the census test cross-checks.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from server.gen1_grant_receipt import FRESH, fresh_catch_rate, fresh_moves, fresh_stats
from server.gen1_initial_observation import display_name
from server.gen1_npc_exchange_receipt import DATA, SCHEMA, validate
from server.gen1_party_codec import PartyCodec
from server.protocol_journal import JournalError
from tests.unit.test_gen1_grant_receipt import CONTEXT, SAVE, TRAINER, box_hex, boxed, fresh
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_party_codec import make_blob

ROOT = Path(__file__).resolve().parents[2]
SITES = [(variant, source) for variant in DATA["titles"] for source in DATA["titles"][variant]["sites"]]
STALE = {"which_trade": 255, "which_pokemon": 255, "cur_species": 255, "cur_level": 255, "mon_location": 1, "remove_from_box": 1,
         "give_species": 0, "receive_species": 0, "traded_ot_id_hex": "0000", "trade_nick_hex": "00" * 11}


def profile(variant):
    return DATA["titles"][variant]


def trainer_string(variant):
    return bytes.fromhex(profile(variant)["engine"]["trainer_string"]["expected_hex"])


def received(codec, site, level, dv=0x5A5A, ot_id=0xBEEF):
    """The record InGameTrade_DoTrade leaves at the last slot for this row, level, DVs and rolled OT id."""
    table = FRESH["titles"][codec.variant]
    receive, delivered = site["receive_species"], site["delivered_species"]
    stats = fresh_stats(codec, delivered, dv, level)
    moves = fresh_moves(table, receive, level)
    raw = bytearray(66)
    raw[0] = delivered
    raw[1:3] = stats[0].to_bytes(2, "big")
    raw[5:7] = bytes(codec.profile["species"][str(delivered)]["types"])
    raw[7] = fresh_catch_rate(table, receive)  # evolution never rewrites this byte
    raw[8:12] = bytes(moves)
    raw[12:14] = ot_id.to_bytes(2, "big")
    raw[14:17] = codec.experience_for_level(codec.profile["species"][str(receive)]["growth_rate"], level).to_bytes(3, "big")
    raw[27:29] = dv.to_bytes(2, "big")
    raw[29:33] = bytes(codec.max_pp(move, 0) if move else 0 for move in moves)
    raw[33] = level
    for index, value in enumerate(stats):
        raw[34 + 2 * index : 36 + 2 * index] = value.to_bytes(2, "big")
    raw[44:55] = trainer_string(codec.variant)
    raw[55:66] = bytes.fromhex(site["nickname_hex"])
    return bytes(raw)


def point(variant, party, box, *, map_id, globals_=None, player_id="1234"):
    return {
        "party_hex": party_point(variant, party)["fields"]["party"],
        "box_hex": box_hex(box),
        "trainer_hex": TRAINER,
        "player_id_hex": player_id,
        "map_id": map_id,
        "battle_flag": 0,
        "current_box": 0,
        **(globals_ or STALE),
    }


def receipt(variant, source, *, slot=1, existing=3, boxed_before=2, level=20, dv=0x5A5A, ot_id=0xBEEF, party_before=None, box=None):
    site = profile(variant)["sites"][source]
    engine = profile(variant)["engine"]
    codec = PartyCodec(variant)
    if party_before is None:
        party_before = [make_blob(codec, level=10, dv=0x1000 + index) for index in range(existing)]
        party_before[slot] = make_blob(codec, species=site["give_species"], level=level, dv=0x1111)
    incoming = received(codec, site, level, dv=dv, ot_id=ot_id)
    party_after = party_before[:slot] + party_before[slot + 1 :] + [incoming]
    box = [boxed(fresh(codec, 153, 7, dv=0x2000 + index), 7) for index in range(boxed_before)] if box is None else box
    written = {"which_trade": site["trade_index"], "which_pokemon": slot, "cur_species": site["receive_species"], "cur_level": level,
               "mon_location": 0, "remove_from_box": 0, "give_species": site["give_species"], "receive_species": site["receive_species"],
               "traded_ot_id_hex": f"{ot_id:04X}", "trade_nick_hex": site["nickname_hex"]}
    return {
        "schema": SCHEMA,
        "source_sha256": DATA["sha256"],
        "variant": variant,
        **CONTEXT,
        "final_sha1": profile(variant)["clean_sha1"],
        "source_id": source,
        "call": {"frame": 100, "pc": site["call"]["address"], "bank": site["call"]["bank"], "sp": 0xDFF0, "a": site["trade_index"],
                 "point": point(variant, party_before, box, map_id=site["map_id"])},
        "remove": {"frame": 130, "pc": engine["remove"]["address"], "bank": engine["remove"]["bank"], "sp": 0xDFE8,
                   "point": point(variant, party_before, box, map_id=site["map_id"], globals_=written)},
        "return": {"frame": 140, "pc": engine["return"]["address"], "bank": engine["return"]["bank"], "sp": 0xDFE8,
                   "point": point(variant, party_after, box, map_id=site["map_id"], globals_=written)},
    }


def check(value, variant, **overrides):
    return validate(value, variant=variant, identity=SAVE, final_sha1=profile(variant)["clean_sha1"], **CONTEXT, **overrides)


def refuse(value, variant, match=None, **overrides):
    before = copy.deepcopy(value)
    with pytest.raises(JournalError, match=match):
        check(value, variant, **overrides)
    assert value == before


def party_bytes(value, witness="return"):
    return bytearray.fromhex(value[witness]["point"]["party_hex"])


def set_party(value, raw, witness="return"):
    value[witness]["point"]["party_hex"] = raw.hex().upper()


@pytest.mark.parametrize("slot,existing", [(0, 1), (0, 3), (2, 3), (5, 6)])
@pytest.mark.parametrize("variant,source", SITES, ids=lambda v: str(v))
def test_every_pinned_exchange_proves_removal_compaction_and_delivery(variant, source, slot, existing):
    value = receipt(variant, source, slot=slot, existing=existing)
    before = copy.deepcopy(value)
    fact = check(value, variant)
    assert value == before
    site = profile(variant)["sites"][source]
    codec = PartyCodec(variant)
    outgoing_blob = bytes.fromhex(value["call"]["point"]["party_hex"])
    outgoing = outgoing_blob[8 + 44 * slot : 52 + 44 * slot] + outgoing_blob[272 + 11 * slot : 283 + 11 * slot] + outgoing_blob[338 + 11 * slot : 349 + 11 * slot]
    assert fact["kind"] == "npc_exchange" and fact["source_id"] == source and fact["exchange_id"] == site["exchange_id"]
    assert fact["trade_index"] == site["trade_index"] and fact["map_id"] == site["map_id"]
    assert fact["give_species"] == site["give_species"] and fact["receive_species"] == site["receive_species"]
    assert fact["delivered_species"] == site["delivered_species"]
    assert fact["outgoing"] == {"key": codec.validate_blob(outgoing).key, "species_index": site["give_species"], "level": 20,
                                "slot": slot, "blob_hex": outgoing.hex().upper()}
    incoming = fact["incoming"]
    assert incoming["slot"] == existing - 1 and incoming["species_index"] == site["delivered_species"] and incoming["level"] == 20
    assert incoming["ot_id"] == 0xBEEF and incoming["key"] == f"5A5A:BEEF:{site['delivered_species']:02X}"
    assert incoming["nickname"] == display_name(bytes.fromhex(site["nickname_hex"]))
    assert bytes.fromhex(incoming["blob_hex"])[44:55] == trainer_string(variant)
    assert (fact["call_frame"], fact["remove_frame"], fact["return_frame"], fact["frame"]) == (100, 130, 140, 140)
    assert len(fact["receipt_digest"]) == 64


def test_exchange_ids_are_title_neutral_and_yellow_shares_the_same_npcs():
    ids = {variant: {site["exchange_id"] for site in profile(variant)["sites"].values()} for variant in DATA["titles"]}
    assert ids["red"] == ids["blue"] and ids["yellow"] < ids["red"]
    assert all(site["exchange_id"] == "exchange:" + source.removeprefix("npc:") for variant, source in SITES for site in [profile(variant)["sites"][source]])
    red = check(receipt("red", "npc:route_2_trade_house:1"), "red")
    yellow = check(receipt("yellow", "npc:route_2_trade_house:1"), "yellow")
    assert red["exchange_id"] == yellow["exchange_id"] == "exchange:route_2_trade_house:1"
    assert red["give_species"] != yellow["give_species"]  # Abra vs Clefairy, both for Mr. Mime
    refuse(receipt("yellow", "npc:route_2_trade_house:1") | {"source_id": "npc:cerulean_trade_house:6"}, "yellow", "unknown exchange source")


def test_yellow_ricky_is_delivered_as_a_forced_machamp_keeping_machoke_bytes():
    site = profile("yellow")["sites"]["npc:underground_path_route_5:9"]
    assert (site["receive_species"], site["delivered_species"]) == (41, 126) and site["trade_evolution"]["forced"] is True
    assert all("trade_evolution" not in row for variant in ("red", "blue") for row in profile(variant)["sites"].values())
    fact = check(receipt("yellow", "npc:underground_path_route_5:9", level=30), "yellow")
    blob = bytes.fromhex(fact["incoming"]["blob_hex"])
    codec = PartyCodec("yellow")
    content = FRESH["titles"]["yellow"]
    assert fact["incoming"]["species_index"] == 126 and blob[7] == fresh_catch_rate(content, 41) == 90 != fresh_catch_rate(content, 126)
    assert tuple(blob[8:12]) == fresh_moves(content, 41, 30) and tuple(int.from_bytes(blob[i:i + 2], "big") for i in range(34, 44, 2)) == fresh_stats(codec, 126, 0x5A5A, 30)
    unevolved = receipt("yellow", "npc:underground_path_route_5:9", level=30)
    raw = party_bytes(unevolved)
    slot = raw[0] - 1
    raw[8 + 44 * slot] = 41  # Machoke left in place: the forced evolution cannot be cancelled
    raw[1 + slot] = 41
    set_party(unevolved, raw)
    refuse(unevolved, "yellow", "not the engine's construction")
    catch = receipt("yellow", "npc:underground_path_route_5:9", level=30)
    raw = party_bytes(catch)
    raw[8 + 44 * slot + 7] = fresh_catch_rate(content, 126)  # Machamp's header value would mean a rewritten byte
    set_party(catch, raw)
    refuse(catch, "yellow", "not the engine's construction")


def test_previously_traded_mons_in_party_and_box_decode_through_the_codec_ot_rule():
    variant, source = "red", "npc:cerulean_trade_house:6"
    codec = PartyCodec(variant)
    earlier = received(codec, profile(variant)["sites"]["npc:route_2_trade_house:1"], 12, dv=0x0F0F, ot_id=0x0BAD)
    give = make_blob(codec, species=110, level=20, dv=0x1111)
    stored = bytearray(received(codec, profile(variant)["sites"]["npc:vermilion_trade_house:4"], 9, dv=0x0A0A, ot_id=0x0BAD))
    box = [(bytes(stored[:33]), bytes(stored[44:55]), bytes(stored[55:66]))]
    value = receipt(variant, source, slot=1, party_before=[earlier, give], box=box)
    fact = check(value, variant)
    assert fact["outgoing"]["slot"] == 1 and fact["incoming"]["slot"] == 1
    assert bytes.fromhex(value["return"]["point"]["party_hex"])[272:283] == trainer_string(variant)  # the earlier mon stays first, OT intact
    assert codec.validate_blob(earlier).ot_name == trainer_string(variant)  # no stand-in: the codec's OT rule


@pytest.mark.parametrize(
    "fault",
    [
        "schema", "source_pin", "variant", "context", "instance", "rom", "unknown_source", "extra_field", "missing_remove",
        "call_pc", "call_bank", "remove_pc", "return_pc", "engine_stack_differs", "script_stack_not_above", "remove_before_call",
        "return_before_remove", "register_a", "identity", "map_call", "map_return", "battle", "which_trade", "give_global",
        "receive_global", "cur_species", "mon_location", "remove_from_box", "nick_buffer", "traded_id_changed", "party_moved_before_removal",
        "box_changed", "slot_outside_party", "wrong_give_species", "cur_level", "party_grew", "party_shrank", "remaining_mon_changed",
        "compaction_order", "key_collision_box", "key_collision_party", "current_box_changed", "rom_override", "foreign_codec",
        "boolean_frame", "bad_party_list", "bad_trainer",
    ],
)
def test_hostile_exchange_receipts_are_refused(fault):
    variant, source = "yellow", "npc:route_2_trade_house:1"
    value = receipt(variant, source)
    site = profile(variant)["sites"][source]
    call, remove, ret = value["call"], value["remove"], value["return"]
    overrides = {}
    if fault == "schema":
        value["schema"] = "rby-npc-exchange-receipt-v0"
    elif fault == "source_pin":
        value["source_sha256"] = "f" * 64
    elif fault == "variant":
        value["variant"] = "red"
    elif fault == "context":
        value["context_generation"] = "b" * 32
    elif fault == "instance":
        value["physical_instance"] = "2" * 32
    elif fault == "rom":
        value["final_sha1"] = "f" * 40
    elif fault == "unknown_source":
        value["source_id"] = "npc:route_2_trade_house:2"
    elif fault == "extra_field":
        value["ordinal"] = 1
    elif fault == "missing_remove":
        del value["remove"]
    elif fault == "call_pc":
        call["pc"] = site["dispatch"]["address"]
    elif fault == "call_bank":
        call["bank"] += 1
    elif fault == "remove_pc":
        remove["pc"] = ret["pc"]
    elif fault == "return_pc":
        ret["pc"] = remove["pc"]
    elif fault == "engine_stack_differs":
        ret["sp"] -= 2
    elif fault == "script_stack_not_above":
        call["sp"] = remove["sp"]
    elif fault == "remove_before_call":
        remove["frame"] = call["frame"] - 1
    elif fault == "return_before_remove":
        ret["frame"] = remove["frame"] - 1
    elif fault == "register_a":
        call["a"] = site["trade_index"] + 1
    elif fault == "identity":
        ret["point"]["player_id_hex"] = "5678"
    elif fault == "map_call":
        call["point"]["map_id"] += 1
    elif fault == "map_return":
        ret["point"]["map_id"] += 1
    elif fault == "battle":
        remove["point"]["battle_flag"] = 1
    elif fault == "which_trade":
        remove["point"]["which_trade"] = site["trade_index"] + 1
    elif fault == "give_global":
        ret["point"]["give_species"] += 1
    elif fault == "receive_global":
        remove["point"]["receive_species"] += 1
    elif fault == "cur_species":
        remove["point"]["cur_species"] = site["give_species"]
    elif fault == "mon_location":
        remove["point"]["mon_location"] = 0x80
    elif fault == "remove_from_box":
        remove["point"]["remove_from_box"] = 1
    elif fault == "nick_buffer":
        remove["point"]["trade_nick_hex"] = profile(variant)["sites"]["npc:route_11_gate_2f:0"]["nickname_hex"]
    elif fault == "traded_id_changed":
        ret["point"]["traded_ot_id_hex"] = "BEEE"
    elif fault == "party_moved_before_removal":
        raw = party_bytes(value, "remove")
        raw[8:52], raw[52:96] = raw[52:96], raw[8:52]
        raw[1], raw[2] = raw[2], raw[1]
        set_party(value, raw, "remove")
        remove["point"]["which_pokemon"] = 0
    elif fault == "box_changed":
        ret["point"]["box_hex"] = box_hex([])
    elif fault == "slot_outside_party":
        remove["point"]["which_pokemon"] = 3
    elif fault == "wrong_give_species":
        remove["point"]["which_pokemon"] = 0  # a legal party member, but not the species this NPC takes
    elif fault == "cur_level":
        remove["point"]["cur_level"] += 1
    elif fault == "party_grew":
        ret["point"]["party_hex"] = receipt(variant, source, existing=4, slot=1)["return"]["point"]["party_hex"]
    elif fault == "party_shrank":
        ret["point"]["party_hex"] = receipt(variant, source, existing=2, slot=1)["return"]["point"]["party_hex"]
    elif fault == "remaining_mon_changed":
        raw = party_bytes(value)
        raw[8 + 13] ^= 1  # slot 0 OT id: codec-legal, so only the compaction predicate can notice
        set_party(value, raw)
    elif fault == "compaction_order":
        raw = party_bytes(value)
        raw[8:52], raw[52:96] = raw[52:96], raw[8:52]
        raw[1], raw[2] = raw[2], raw[1]
        set_party(value, raw)
    elif fault == "key_collision_box":
        codec = PartyCodec(variant)
        twin = boxed(fresh(codec, site["delivered_species"], 7, dv=0x5A5A, ot_id=0xBEEF), 7)
        for witness in (call, remove, ret):
            witness["point"]["box_hex"] = box_hex([twin])
    elif fault == "key_collision_party":
        codec = PartyCodec(variant)
        twin = make_blob(codec, species=site["delivered_species"], level=10, dv=0x5A5A, otid=0xBEEF)
        value = receipt(variant, source, slot=1, party_before=[twin, make_blob(codec, species=site["give_species"], level=20, dv=0x1111)])
    elif fault == "current_box_changed":
        ret["point"]["current_box"] = 1
    elif fault == "rom_override":
        overrides = {"rom_bytes": {site["record_rom_offset"]: 1}}
    elif fault == "foreign_codec":
        overrides = {"codec": PartyCodec("red")}
    elif fault == "boolean_frame":
        call["frame"] = True
    elif fault == "bad_party_list":
        raw = party_bytes(value)
        raw[1 + raw[0]] = 0
        set_party(value, raw)
    elif fault == "bad_trainer":
        call["point"]["trainer_hex"] = "5D" + "50" * 10
    refuse(value, variant, **overrides)


@pytest.mark.parametrize(
    "field,offset,length,replacement",
    [
        ("species", 0, 1, None),
        ("status", 4, 1, b"\x08"),
        ("hp", 1, 2, b"\xff\xff"),
        ("hp_below_max", 1, 2, None),
        ("experience", 14, 3, None),
        ("stat_experience", 17, 10, b"\xff" * 10),
        ("pp_zero", 29, 4, b"\0\0\0\0"),
        ("pp_ups", 29, 1, None),
        ("stats", 36, 2, None),
        ("box_level", 3, 1, b"\x05"),
        ("types", 5, 2, b"\x00\x00"),
        ("ot_id", 12, 2, b"\x56\x78"),
        ("ot_name", 44, 11, None),
        ("nickname", 55, 1, b"\x80"),
        ("catch_rate", 7, 1, None),
        ("moves", 8, 4, None),
        ("move_gap", 8, 4, b"\x01\x00\x02\x00"),
        ("level", 33, 1, None),
    ],
)
def test_incoming_mon_must_be_the_engine_construction(field, offset, length, replacement):
    variant = "red"
    value = receipt(variant, "npc:cerulean_trade_house:6")
    codec = PartyCodec(variant)
    raw = party_bytes(value)
    slot = raw[0] - 1
    base = {"ot_name": 272, "nickname": 338}.get(field, 8)
    stride = 44 if base == 8 else 11
    start = base + stride * slot + (offset - 44 if field == "ot_name" else offset - 55 if field == "nickname" else offset)
    if replacement is None:
        current = raw[start : start + length]
        if field == "species":
            replacement = bytes([0x48 ^ 1])  # not Jynx
            raw[1 + slot] = replacement[0]
        elif field == "hp_below_max":
            replacement = (int.from_bytes(current, "big") - 1).to_bytes(2, "big")
        elif field == "experience":
            replacement = (int.from_bytes(current, "big") + 1).to_bytes(3, "big")
        elif field == "pp_ups":
            replacement = bytes([current[0] | 0x40])
        elif field == "catch_rate":
            replacement = bytes([current[0] ^ 1])
        elif field == "moves":
            moves = list(current)
            moves[0] = 57 if moves[0] != 57 else 58
            replacement = bytes(moves)
            raw[start + 21 : start + 25] = bytes(codec.max_pp(m, 0) if m else 0 for m in moves)
        elif field == "ot_name":
            replacement = bytes.fromhex(TRAINER)  # the player's own name: AddPartyMon's OT left uncopied
        elif field == "level":
            replacement = bytes([current[0] + 1])
        else:
            replacement = (int.from_bytes(current, "big") + 1).to_bytes(2, "big")
    raw[start : start + length] = replacement
    if field == "move_gap":
        raw[start + 21 : start + 25] = bytes((35, 0, 25, 0))
    set_party(value, raw)
    refuse(value, variant)


def test_generated_data_is_current_and_matches_the_acquisition_census():
    result = subprocess.run([sys.executable, str(ROOT / "tools/gen_gen1_npc_exchange_sites.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    census = json.loads((ROOT / "data/games/gen1_rby/acquisition_sources.json").read_text(encoding="utf-8"))
    for variant, title in DATA["titles"].items():
        rows = {row["source_id"]: row for row in census["titles"][variant]["sources"] if row["kind"] == "npc_exchange"}
        assert set(rows) == set(title["sites"])
        for source, site in title["sites"].items():
            row = rows[source]
            assert (site["map_id"], site["trade_index"], site["give_species"], site["receive_species"], site["record_rom_offset"]) == (
                row["map_id"], row["trade_index"], row["wanted_species_index"], row["received_species_index"], row["record_rom_offset"])
            record = bytes.fromhex(site["record_hex"])
            assert record[0] == site["give_species"] and record[1] == site["receive_species"] and record[3:].hex().upper() == site["nickname_hex"]
            assert site["call"]["expected_hex"].startswith("EA") and site["dispatch"]["expected_hex"] == f"3E{title['predef_id']:02X}CD" + site["dispatch"]["expected_hex"][6:]
        assert title["unused"] == census["titles"][variant]["unused_trade_rows"]
        assert title["engine"]["trainer_string"]["expected_hex"] == "5D" + "50" * 10
        assert title["table"]["policy"].startswith("pinned: gen1_upr_scan claims no in-game-trade domain")
    lua = (ROOT / "data/games/gen1_rby/gen1_npc_exchange_sites.lua").read_text(encoding="utf-8")
    assert lua.startswith("-- Generated by tools/gen_gen1_npc_exchange_sites.py") and DATA["sha256"] in lua
