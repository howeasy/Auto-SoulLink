"""Scripted grant receipts: registers at the call, fresh synthesis, prepend, payment.

Fixtures synthesize the delivered record the way AddPartyMon / SendNewMonToBox do
(exact experience, zero stat experience, max PP without PP Ups, fresh CalcStats, HP at
max, OT from wPlayerName, header catch rate with the title override, WriteMonMoves move
set); only the DVs and nickname are chosen freely, which is exactly what the decoder
cannot pin. Call points carry deliberately stale globals so every positive case proves
the registers decide. Sites, operands, prices, anchors and fresh content all come from
the generated data.
"""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from server.gen1_grant_receipt import (
    COST_TABLES,
    DATA,
    FRESH,
    SCHEMA,
    fresh_catch_rate,
    fresh_moves,
    fresh_stats,
    pairing_id,
    validate,
)
from server.gen1_party_codec import PartyCodec
from server.protocol_journal import JournalError
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_party_codec import make_blob

ROOT = Path(__file__).resolve().parents[2]
TRAINER = "92808C8450000000000000"  # SAME
SAVE = {"ot_id": "1234", "trainer_name": "SAME"}
CONTEXT = {"context_generation": "a" * 32, "physical_instance": "1" * 32}
STALE = {"cur_species": 255, "cur_level": 255, "mon_location": 1}  # wrapper has not run at the call
SITES = [(variant, source) for variant in DATA["titles"] for source in DATA["titles"][variant]["sites"]]
PRIZE_CASES = [
    (variant, source, slot)
    for variant, source in SITES
    for slot in (range(6) if "purchase" in DATA["titles"][variant]["sites"][source] else [None])
]


def content(variant):
    return FRESH["titles"][variant]


def fresh(codec, species, level, dv=0x5A5A, ot_id=0x1234):
    """A record exactly as AddPartyMon leaves it for these operands and DVs."""
    facts = codec.profile["species"][str(species)]
    table = content(codec.variant)
    stats = fresh_stats(codec, species, dv, level)
    moves = fresh_moves(table, species, level)
    raw = bytearray(66)
    raw[0] = species
    raw[1:3] = stats[0].to_bytes(2, "big")
    raw[5:7] = bytes(facts["types"])
    raw[7] = fresh_catch_rate(table, species)
    raw[8:12] = bytes(moves)
    raw[12:14] = ot_id.to_bytes(2, "big")
    raw[14:17] = codec.experience_for_level(facts["growth_rate"], level).to_bytes(3, "big")
    raw[27:29] = dv.to_bytes(2, "big")
    raw[29:33] = bytes(codec.max_pp(move, 0) if move else 0 for move in moves)
    raw[33] = level
    for index, value in enumerate(stats):
        raw[34 + 2 * index : 36 + 2 * index] = value.to_bytes(2, "big")
    raw[44:55] = bytes.fromhex(TRAINER)
    raw[55:66] = make_blob(codec)[55:66]
    return bytes(raw)


def boxed(blob, level):
    record = bytearray(blob[:33])
    record[3] = level
    return bytes(record), bytes.fromhex(TRAINER), blob[55:66]


def box_hex(records):
    blob = bytearray(1122)
    blob[0] = len(records)
    blob[1 : 1 + len(records)] = bytes(record[0][0] for record in records)
    blob[1 + len(records)] = 255
    for index, (record, ot, nick) in enumerate(records):
        blob[22 + 33 * index : 55 + 33 * index] = record
        blob[682 + 11 * index : 693 + 11 * index] = ot
        blob[902 + 11 * index : 913 + 11 * index] = nick
    return blob.hex().upper()


def point(variant, party, box, *, map_id, coins, added=0, globals_=None, which=0, window=0, prizes=b"\0\0\0", prices=b"\0" * 6, player_id="1234"):
    return {
        "party_hex": party_point(variant, party)["fields"]["party"],
        "box_hex": box_hex(box),
        "trainer_hex": TRAINER,
        "player_id_hex": player_id,
        "map_id": map_id,
        "battle_flag": 0,
        **(globals_ or STALE),
        "added_to_party": added,
        "current_box": 0,
        "coins_hex": f"{coins:04d}",
        "which_prize": which,
        "prize_window": window,
        "prizes_hex": prizes.hex().upper(),
        "prices_hex": prices.hex().upper(),
    }


def receipt(variant, source, *, delivery="party", slot=None, existing=2, boxed_before=3, species=None, level=None, allowed=None, ot_id="1234", dv=0x5A5A):
    """`species`/`level` override the delivered operands; `allowed` is the prize table a UPR
    static rewrite left (6 species, table order), defaulting to the clean one."""
    profile = DATA["titles"][variant]
    site = profile["sites"][source]
    codec = PartyCodec(variant)
    purchase = "purchase" in site
    index = slot or 0
    window, which = divmod(index, 3) if purchase else (0, 0)
    table = list(allowed) if allowed is not None else list(site["species"]["clean"])
    species = table[index] if species is None else species
    values = site["level"]["values"]
    level = (values[table.index(species)] if len(values) > 1 else values[0]) if level is None else level
    mon = fresh(codec, species, level, dv=dv, ot_id=int(ot_id, 16))
    party_before = [make_blob(codec, level=10, dv=0x1000 + i) for i in range(6 if delivery == "box" else existing)]
    box_before = [boxed(fresh(codec, 153, 7, dv=0x2000 + i), 7) for i in range(boxed_before)]
    if delivery == "party":
        party_after, box_after, added = party_before + [mon], box_before, 1
    else:
        party_after, box_after, added = party_before, [boxed(mon, level)] + box_before, 0  # prepend
    prizes = bytes(table[window * 3 : window * 3 + 3]) if purchase else b"\0\0\0"
    prices = bytes.fromhex(site["purchase"]["clean_costs_bcd"][COST_TABLES[window]]) if purchase else b"\0" * 6
    coins_before = 9999 if purchase else 0
    coins_after = coins_before - (int(prices[2 * which : 2 * which + 2].hex()) if purchase else 0)
    common = {"map_id": site["map_id"], "which": which, "window": window, "prizes": prizes, "prices": prices, "player_id": ot_id}
    written = {"cur_species": species, "cur_level": level, "mon_location": 0}
    value = {
        "schema": SCHEMA,
        "source_sha256": DATA["sha256"],
        "variant": variant,
        **CONTEXT,
        "final_sha1": profile["clean_sha1"],
        "source_id": source,
        "call": {"frame": 100, "pc": site["call"]["address"], "bank": site["call"]["bank"], "sp": 0xDFFE, "b": species, "c": level,
                 "point": point(variant, party_before, box_before, coins=coins_before, **common)},
        "return": {"frame": 140, "pc": site["return"]["address"], "bank": site["return"]["bank"], "sp": 0xDFFE, "flags": 0x10,
                   "point": point(variant, party_after, box_after, added=added, coins=coins_before, globals_=written, **common)},
    }
    if purchase:
        paid = site["purchase"]["paid"]
        value["paid"] = {"frame": 150, "pc": paid["address"], "bank": paid["bank"], "sp": 0xDFFE,
                         "point": point(variant, party_after, box_after, added=added, coins=coins_after, globals_=written, **common)}
    return value


def check(value, variant, **overrides):
    profile = DATA["titles"][variant]
    return validate(value, variant=variant, identity=SAVE, final_sha1=profile["clean_sha1"], **CONTEXT, **overrides)


def refuse(value, variant, match=None, **overrides):
    before = copy.deepcopy(value)
    with pytest.raises(JournalError, match=match):
        check(value, variant, **overrides)
    assert value == before


def party_bytes(value, witness="return"):
    return bytearray.fromhex(value[witness]["point"]["party_hex"])


def set_party(value, raw, witness="return"):
    value[witness]["point"]["party_hex"] = raw.hex().upper()


def box_bytes(value, witness="return"):
    return bytearray.fromhex(value[witness]["point"]["box_hex"])


def set_box(value, raw, witness="return"):
    value[witness]["point"]["box_hex"] = raw.hex().upper()


@pytest.mark.parametrize("delivery", ["party", "box"])
@pytest.mark.parametrize("variant,source,slot", PRIZE_CASES, ids=lambda v: str(v))
def test_every_pinned_grant_site_proves_delivery_and_payment(variant, source, slot, delivery):
    value = receipt(variant, source, delivery=delivery, slot=slot)
    before = copy.deepcopy(value)
    fact = check(value, variant)
    assert value == before
    site = DATA["titles"][variant]["sites"][source]
    assert fact["kind"] == "scripted_grant" and fact["source_id"] == source and fact["group"] == site["group"]
    assert fact["yellow_only"] is site["yellow_only"] and fact["frame"] == fact["return_frame"] == 140 and fact["call_frame"] == 100
    assert fact["species_index"] == value["call"]["b"] and fact["level"] == value["call"]["c"] and fact["map_id"] == site["map_id"]
    assert fact["delivery"] == delivery
    codec = PartyCodec(variant)
    if delivery == "party":
        assert fact["slot"] == 2 and fact["location"] == {"kind": "party", "slot": 2, "box": None}
        assert fact["key"] == codec.validate_blob(bytes.fromhex(fact["blob_hex"])).key
    else:
        assert fact["box_slot"] == 0 and fact["box_index"] == 0 and len(fact["blob_hex"]) == 110  # prepended
        assert fact["location"] == {"kind": "box", "slot": 0, "box": 0}
        raw = bytes.fromhex(fact["blob_hex"])
        assert fact["key"] == f"{raw[27:29].hex().upper()}:{raw[12:14].hex().upper()}:{raw[0]:02X}"
    if slot is None:
        assert fact["purchase"] is None
    else:
        window, which = divmod(slot, 3)
        prices = bytes.fromhex(site["purchase"]["clean_costs_bcd"][COST_TABLES[window]])
        price = int(prices[2 * which : 2 * which + 2].hex())
        assert fact["purchase"] == {"window": window, "which": which, "price": price, "coins_before": 9999, "coins_after": 9999 - price}
        assert fact["pairing_id"] == f"grant:game_corner_purchase:{window}:{which}"


def test_fresh_moves_follow_write_mon_moves_including_the_unsorted_yellow_learnset():
    yellow, red = content("yellow"), content("red")
    assert fresh_moves(red, 0x66, 25) == (33, 28, 0, 0)  # Eevee: first learnset level is 27
    assert fresh_moves(yellow, 0x66, 25) == (39, 28, 45, 98)  # fill, fill, then drop slot 0 for Bite
    assert fresh_moves(yellow, 0x66, 7) == (33, 39, 0, 0)
    quirk = yellow["species"]["117"]
    assert quirk["sorted"] is False and [46, 37] in quirk["learnset"] and [45, 103] in quirk["learnset"]
    assert 103 not in fresh_moves(yellow, 117, 45)  # engine stops at the out-of-order 46
    assert 103 in fresh_moves(yellow, 117, 46)
    assert all(row["sorted"] for row in red["species"].values())
    assert fresh_catch_rate(yellow, 0x26) == 0x60 and fresh_catch_rate(red, 0x26) == red["species"]["38"]["catch_rate"]


def test_pairing_ids_are_logical_events_not_titles_or_species():
    assert pairing_id("grant:dojo_choice:0", "dojo_choice") == pairing_id("grant:dojo_choice:1", "dojo_choice") == "grant:dojo_choice"
    assert pairing_id("grant:fossil_revival:0", "fossil_revival") == "grant:fossil_revival"
    assert pairing_id("grant:eevee:0", "eevee") == "grant:eevee:0"
    red = check(receipt("red", "grant:game_corner_purchase:0", slot=2), "red")
    blue = check(receipt("blue", "grant:game_corner_purchase:0", slot=2), "blue")
    assert red["species_index"] != blue["species_index"]  # Nidorina vs Nidorino
    assert red["pairing_id"] == blue["pairing_id"] == "grant:game_corner_purchase:0:2"
    yellow = {source for source, site in DATA["titles"]["yellow"]["sites"].items() if site["yellow_only"]}
    assert yellow == {"grant:yellow_bulbasaur:0", "grant:yellow_charmander:0", "grant:yellow_squirtle:0"}
    assert not (yellow & set(DATA["titles"]["red"]["sites"])) and not (yellow & set(DATA["titles"]["blue"]["sites"]))
    refuse(receipt("red", "grant:eevee:0") | {"source_id": "grant:yellow_bulbasaur:0"}, "red", "unknown grant source")


def test_call_registers_decide_the_operands_not_stale_globals():
    value = receipt("yellow", "grant:eevee:0")
    assert value["call"]["point"]["cur_species"] == 255 and value["call"]["point"]["mon_location"] == 1
    assert check(value, "yellow")["species_index"] == 0x66
    seeded = receipt("yellow", "grant:eevee:0")
    seeded["call"]["point"].update(cur_species=0x66, cur_level=25, mon_location=0)
    seeded["call"]["b"] = 4
    seeded["return"]["point"]["cur_species"] = 4
    refuse(seeded, "yellow", "not a pinned operand")
    inconsistent = receipt("yellow", "grant:eevee:0")
    inconsistent["call"]["b"] = 4
    refuse(inconsistent, "yellow", "globals at return differ")
    wrong_level = receipt("yellow", "grant:eevee:0")
    wrong_level["call"]["c"] += 1
    wrong_level["return"]["point"]["cur_level"] += 1
    refuse(wrong_level, "yellow", "level differs")
    drift = receipt("yellow", "grant:eevee:0")
    drift["return"]["point"]["cur_species"] = 4
    refuse(drift, "yellow", "globals at return differ")
    location = receipt("yellow", "grant:eevee:0")
    location["return"]["point"]["mon_location"] = 1
    refuse(location, "yellow", "globals at return differ")
    for field in ("b", "c"):
        missing = receipt("yellow", "grant:eevee:0")
        del missing["call"][field]
        refuse(missing, "yellow", "complete grant call witness")
    boolean = receipt("yellow", "grant:eevee:0")
    boolean["call"]["b"] = True
    refuse(boolean, "yellow", "invalid grant call b")


@pytest.mark.parametrize(
    "fault",
    [
        "schema", "source_pin", "variant", "context", "instance", "rom", "unknown_source", "starter", "extra_field",
        "call_pc", "call_bank", "return_pc", "stack", "frame_order", "no_carry", "identity", "map", "battle",
        "species", "level", "box_changed_on_party", "party_member_changed", "no_append", "added_flag_lies",
        "current_box_changed", "paid_on_gift", "bad_party_list", "boolean_frame", "foreign_codec", "bad_content",
    ],
)
def test_hostile_gift_receipts_are_refused_without_a_grant(fault):
    value = receipt("yellow", "grant:eevee:0")
    site = DATA["titles"]["yellow"]["sites"]["grant:eevee:0"]
    call, ret = value["call"], value["return"]
    overrides = {}
    if fault == "schema":
        value["schema"] = "rby-grant-receipt-v0"
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
        value["source_id"] = "grant:mew:0"
    elif fault == "starter":
        value["source_id"] = "grant:starter:0"
    elif fault == "extra_field":
        value["ordinal"] = 1
    elif fault == "call_pc":
        call["pc"] += 3
    elif fault == "call_bank":
        call["bank"] += 1
    elif fault == "return_pc":
        ret["pc"] = call["pc"]
    elif fault == "stack":
        ret["sp"] -= 2
    elif fault == "frame_order":
        ret["frame"] = call["frame"] - 1
    elif fault == "no_carry":
        ret["flags"] = 0x00
    elif fault == "identity":
        ret["point"]["player_id_hex"] = "5678"
    elif fault == "map":
        call["point"]["map_id"] = site["map_id"] + 1
    elif fault == "battle":
        ret["point"]["battle_flag"] = 1
    elif fault == "species":
        call["b"] = 4
        ret["point"]["cur_species"] = 4
    elif fault == "level":
        call["c"] = 26
        ret["point"]["cur_level"] = 26
    elif fault == "box_changed_on_party":
        ret["point"]["box_hex"] = box_hex([])
    elif fault == "party_member_changed":
        raw = party_bytes(value)
        raw[9] ^= 1
        set_party(value, raw)
    elif fault == "no_append":
        ret["point"]["party_hex"] = call["point"]["party_hex"]
    elif fault == "added_flag_lies":
        ret["point"]["added_to_party"] = 0
    elif fault == "current_box_changed":
        ret["point"]["current_box"] = 1
    elif fault == "paid_on_gift":
        value["paid"] = {k: v for k, v in ret.items() if k != "flags"}
    elif fault == "bad_party_list":
        raw = party_bytes(value)
        raw[1 + raw[0]] = 0
        set_party(value, raw)
    elif fault == "boolean_frame":
        call["frame"] = True
    elif fault == "foreign_codec":
        overrides = {"codec": PartyCodec("red")}
    elif fault == "bad_content":
        overrides = {"content": {"species": {}}}
    refuse(value, "yellow", **overrides)


@pytest.mark.parametrize(
    "field,offset,length,replacement",
    [
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
        ("ot_name", 44, 1, b"\x91"),
        ("catch_rate", 7, 1, None),
        ("moves", 8, 4, None),
        ("move_gap", 8, 4, b"\x01\x00\x02\x00"),
    ],
)
def test_party_delivery_must_be_a_fresh_add_party_mon(field, offset, length, replacement):
    value = receipt("red", "grant:lapras:0")
    codec = PartyCodec("red")
    raw = party_bytes(value)
    slot = raw[0] - 1
    base = 272 if field == "ot_name" else 8
    start = base + (11 if field == "ot_name" else 44) * slot + offset
    if replacement is None:
        current = raw[start : start + length]
        if field == "hp_below_max":
            replacement = (int.from_bytes(current, "big") - 1).to_bytes(2, "big")
        elif field == "experience":
            replacement = (int.from_bytes(current, "big") + 1).to_bytes(3, "big")
        elif field == "pp_ups":
            replacement = bytes([current[0] | 0x40])
        elif field == "catch_rate":
            replacement = bytes([current[0] ^ 1])
        elif field == "moves":
            moves = list(current)
            moves[0] = 57 if moves[0] != 57 else 58  # a legal move the level would not have taught
            replacement = bytes(moves)
            raw[start + 21 : start + 25] = bytes(codec.max_pp(m, 0) if m else 0 for m in moves)
        else:
            replacement = (int.from_bytes(current, "big") + 1).to_bytes(2, "big")
    raw[start : start + length] = replacement
    if field == "move_gap":
        raw[start + 21 : start + 25] = bytes((35, 0, 25, 0))
    set_party(value, raw)
    refuse(value, "red")


def test_yellow_kadabra_catch_override_applies_on_both_delivery_paths():
    codec = PartyCodec("yellow")
    site = DATA["titles"]["yellow"]["sites"]["grant:eevee:0"]
    offset = site["species"]["rom_offsets"][0]
    level = site["level"]["values"][0]
    for delivery in ("party", "box"):
        value = receipt("yellow", "grant:eevee:0", delivery=delivery, species=0x26, level=level)
        fact = check(value, "yellow", rom_bytes={offset: 0x26})
        assert fact["species_index"] == 0x26
        blob = bytes.fromhex(fact["blob_hex"])
        assert blob[7] == 0x60  # TWISTEDSPOON_GSC, not Kadabra's header catch rate
        header = codec.profile["species"]["38"]
        assert header and content("yellow")["species"]["38"]["catch_rate"] != 0x60
        if delivery == "party":
            raw = party_bytes(value)
            raw[8 + 44 * 2 + 7] = content("yellow")["species"]["38"]["catch_rate"]
            set_party(value, raw)
        else:
            raw = box_bytes(value)
            raw[22 + 7] = content("yellow")["species"]["38"]["catch_rate"]
            set_box(value, raw)
        refuse(value, "yellow", rom_bytes={offset: 0x26})
    red = receipt("red", "grant:eevee:0", species=0x26, level=level)
    fact = check(red, "red", rom_bytes={DATA["titles"]["red"]["sites"]["grant:eevee:0"]["species"]["rom_offsets"][0]: 0x26})
    assert bytes.fromhex(fact["blob_hex"])[7] == content("red")["species"]["38"]["catch_rate"]


def test_duplicate_randomized_prize_species_takes_the_first_dictionary_level_and_the_bought_slot_price():
    site = DATA["titles"]["red"]["sites"]["grant:game_corner_purchase:0"]
    clean = list(site["species"]["clean"])
    table = clean[:]
    table[1] = clean[0]  # a static rewrite made slots 0 and 1 the same species (Abra)
    offsets = site["species"]["rom_offsets"]
    value = receipt("red", "grant:game_corner_purchase:0", slot=1, allowed=table)
    assert value["call"]["c"] == site["level"]["values"][0]  # GetPrizeMonLevel: first match
    fact = check(value, "red", rom_bytes={offsets[1]: table[1]})
    prices = bytes.fromhex(site["purchase"]["clean_costs_bcd"]["PrizeMenuMon1Cost"])
    assert fact["purchase"]["which"] == 1 and fact["purchase"]["price"] == int(prices[2:4].hex())
    assert fact["pairing_id"] == "grant:game_corner_purchase:0:1" and fact["level"] == site["level"]["values"][0]
    # Without the checked ROM byte the RAM prize table itself is already foreign.
    refuse(value, "red", "prize table or slot differs|not a pinned operand")
    second_slot_level = receipt("red", "grant:game_corner_purchase:0", slot=1, allowed=table, level=site["level"]["values"][1])
    refuse(second_slot_level, "red", "level differs", rom_bytes={offsets[1]: table[1]})


def test_box_delivery_prepends_and_shifts_existing_records_intact():
    value = receipt("blue", "grant:eevee:0", delivery="box", boxed_before=4)
    fact = check(value, "blue")
    assert fact["box_slot"] == 0 and fact["delivery"] == "box"
    after = box_bytes(value)
    before = box_bytes(value, "call")
    assert after[0] == before[0] + 1 and after[1] == 0x66 and after[2:6] == before[1:5]
    assert after[55:88] == before[22:55]
    assert check(receipt("blue", "grant:eevee:0", delivery="box", boxed_before=0), "blue")["box_slot"] == 0
    assert check(receipt("blue", "grant:eevee:0", delivery="box", boxed_before=19), "blue")["box_slot"] == 0


@pytest.mark.parametrize(
    "fault",
    ["appended_instead", "shifted_record_altered", "shifted_ot_altered", "shifted_nick_altered", "species_list_not_shifted",
     "party_not_full", "no_box_append", "party_changed", "record_species", "record_box_level", "record_status", "record_hp",
     "record_experience", "record_stat_experience", "record_pp", "record_pp_ups", "record_types", "record_ot_id", "record_ot",
     "record_catch_rate", "record_moves"],
)
def test_hostile_box_deliveries_are_refused(fault):
    value = receipt("red", "grant:lapras:0", delivery="box")
    codec = PartyCodec("red")
    ret = value["return"]
    raw = box_bytes(value)
    if fault == "appended_instead":
        old = [boxed(fresh(codec, 153, 7, dv=0x2000 + i), 7) for i in range(3)]
        raw = bytearray.fromhex(box_hex(old + [boxed(fresh(codec, 0x13, 15), 15)]))
    elif fault == "shifted_record_altered":
        raw[22 + 33 * 1 + 5] ^= 1
    elif fault == "shifted_ot_altered":
        raw[682 + 11 * 2] = 0x91
    elif fault == "shifted_nick_altered":
        raw[902 + 11 * 3] ^= 1
    elif fault == "species_list_not_shifted":
        raw[1], raw[2] = raw[2], raw[1]
    elif fault == "party_not_full":
        value = receipt("red", "grant:lapras:0", delivery="box", existing=5)
        five = party_point("red", [make_blob(codec, level=10, dv=0x1000 + i) for i in range(5)])["fields"]["party"]
        value["call"]["point"]["party_hex"] = value["return"]["point"]["party_hex"] = five
    elif fault == "no_box_append":
        ret["point"]["box_hex"] = value["call"]["point"]["box_hex"]
    elif fault == "party_changed":
        party = party_bytes(value)
        party[9] ^= 1
        set_party(value, party)
    elif fault == "record_species":
        raw[22] = raw[1] = 4
    elif fault == "record_box_level":
        raw[22 + 3] += 1
    elif fault == "record_status":
        raw[22 + 4] = 8
    elif fault == "record_hp":
        raw[22 + 1 : 22 + 3] = b"\xff\xff"
    elif fault == "record_experience":
        raw[22 + 14 : 22 + 17] = b"\xff\xff\xff"
    elif fault == "record_stat_experience":
        raw[22 + 17 : 22 + 27] = b"\xff" * 10
    elif fault == "record_pp":
        raw[22 + 29 : 22 + 33] = b"\xff" * 4
    elif fault == "record_pp_ups":
        raw[22 + 29] |= 0x40
    elif fault == "record_types":
        raw[22 + 5 : 22 + 7] = b"\xff\xff"
    elif fault == "record_ot_id":
        raw[22 + 12 : 22 + 14] = b"\x56\x78"
    elif fault == "record_ot":
        raw[682] = 0x91
    elif fault == "record_catch_rate":
        raw[22 + 7] ^= 1
    elif fault == "record_moves":
        moves = list(raw[22 + 8 : 22 + 12])
        moves[0] = 57 if moves[0] != 57 else 58
        raw[22 + 8 : 22 + 12] = bytes(moves)
        raw[22 + 29 : 22 + 33] = bytes(codec.max_pp(m, 0) if m else 0 for m in moves)
    if fault not in ("party_not_full", "no_box_append", "party_changed"):
        set_box(value, raw)
    refuse(value, "red")


def test_cross_container_key_collisions_are_refused():
    codec = PartyCodec("yellow")
    value = receipt("yellow", "grant:eevee:0", boxed_before=0)
    delivered = fresh(codec, 0x66, 25)
    for witness in ("call", "return"):
        set_box(value, bytearray.fromhex(box_hex([boxed(delivered, 25)])), witness)
    refuse(value, "yellow", "one key in both party and current box|duplicates an existing")
    value = receipt("yellow", "grant:eevee:0", delivery="box", boxed_before=0)
    party = [make_blob(codec, level=10, dv=0x1000 + i) for i in range(5)] + [fresh(codec, 0x66, 25)]
    for witness in ("call", "return"):
        set_party(value, bytearray.fromhex(party_point("yellow", party)["fields"]["party"]), witness)
    refuse(value, "yellow", "one key in both party and current box|duplicates an existing")
    shared = receipt("yellow", "grant:lapras:0", boxed_before=0)
    twin = boxed(make_blob(codec, level=10, dv=0x1000), 10)
    for witness in ("call", "return"):
        set_box(shared, bytearray.fromhex(box_hex([twin])), witness)
    refuse(shared, "yellow", "one key in both party and current box")


@pytest.mark.parametrize(
    "fault",
    ["tm_window", "which_out_of_range", "slot_species_mismatch", "prize_table_mismatch", "price_table_not_clean",
     "missing_paid", "paid_pc", "paid_stack", "paid_frame", "not_enough_coins", "coins_unchanged", "overpaid",
     "coins_moved_before_payment", "storage_changed_after_delivery", "bad_bcd"],
)
def test_prize_purchases_require_pinned_prices_and_payment_after_delivery(fault):
    value = receipt("blue", "grant:game_corner_purchase:0", slot=4)
    site = DATA["titles"]["blue"]["sites"]["grant:game_corner_purchase:0"]
    call, ret, paid = value["call"], value["return"], value["paid"]
    if fault == "tm_window":
        for row in (call, ret, paid):
            row["point"]["prize_window"] = site["purchase"]["tm_window"]
    elif fault == "which_out_of_range":
        for row in (call, ret, paid):
            row["point"]["which_prize"] = 3
    elif fault == "slot_species_mismatch":
        for row in (call, ret, paid):
            row["point"]["which_prize"] = 0
    elif fault == "prize_table_mismatch":
        prizes = bytearray.fromhex(call["point"]["prizes_hex"])
        prizes[2] = 4
        call["point"]["prizes_hex"] = prizes.hex().upper()
    elif fault == "price_table_not_clean":
        prices = bytearray.fromhex(call["point"]["prices_hex"])
        prices[3] ^= 1
        call["point"]["prices_hex"] = prices.hex().upper()
        paid["point"]["coins_hex"] = f"{9999 - int(prices[2:4].hex()):04d}"
    elif fault == "missing_paid":
        del value["paid"]
    elif fault == "paid_pc":
        paid["pc"] = ret["pc"]
    elif fault == "paid_stack":
        paid["sp"] -= 2
    elif fault == "paid_frame":
        paid["frame"] = ret["frame"] - 1
    elif fault == "not_enough_coins":
        for row in (call, ret):
            row["point"]["coins_hex"] = "0001"
        paid["point"]["coins_hex"] = "0000"
    elif fault == "coins_unchanged":
        paid["point"]["coins_hex"] = call["point"]["coins_hex"]
    elif fault == "overpaid":
        paid["point"]["coins_hex"] = f"{int(paid['point']['coins_hex']) - 1:04d}"
    elif fault == "coins_moved_before_payment":
        ret["point"]["coins_hex"] = paid["point"]["coins_hex"]
    elif fault == "storage_changed_after_delivery":
        paid["point"]["box_hex"] = box_hex([])
    elif fault == "bad_bcd":
        call["point"]["coins_hex"] = "0A99"
    refuse(value, "blue")


def test_upr_rewritten_species_operand_needs_its_checked_rom_byte_and_never_moves_the_level():
    site = DATA["titles"]["yellow"]["sites"]["grant:eevee:0"]
    offset = site["species"]["rom_offsets"][0]
    level = site["level"]["values"][0]
    value = receipt("yellow", "grant:eevee:0", species=4, level=level)  # a fresh Clefairy
    refuse(value, "yellow", "not a pinned operand")
    fact = check(value, "yellow", rom_bytes={offset: 4})
    assert fact["species_index"] == 4 and fact["level"] == level
    assert bytes.fromhex(fact["blob_hex"])[8:12] == bytes(fresh_moves(content("yellow"), 4, level))
    refuse(value, "yellow", "does not read", rom_bytes={offset: 4, site["level"]["rom_offsets"][0]: 30})
    refuse(value, "yellow", "overrides must map", rom_bytes={str(offset): 4})
    moved = receipt("yellow", "grant:eevee:0", species=4, level=30)
    refuse(moved, "yellow", "level differs", rom_bytes={offset: 4})


def test_generated_data_is_reproducible_and_covers_every_source_call():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        from gen_gen1_acquisition_sources import TITLES
        from gen_gen1_grant_sites import FRESH_LUA, FRESH_OUTPUT, LUA, OUTPUT, lua
    finally:
        sys.path.pop(0)
    result = subprocess.run([sys.executable, str(ROOT / "tools/gen_gen1_grant_sites.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    header = "-- Generated by tools/gen_gen1_grant_sites.py from pinned source/ROMs.\nreturn "
    for path, lua_path, loaded in ((OUTPUT, LUA, DATA), (FRESH_OUTPUT, FRESH_LUA, FRESH)):
        stored = json.loads(path.read_text(encoding="utf-8"))
        body = {key: value for key, value in stored.items() if key != "sha256"}
        assert stored["sha256"] == loaded["sha256"] == hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert lua_path.read_text(encoding="utf-8") == header + lua(stored) + "\n"
    for variant, (source, _) in TITLES.items():
        repo = ROOT / ".cache/pret" / source
        calls = sum(path.read_text(encoding="utf-8").count("\tcall GivePokemon\n") for path in list(repo.glob("scripts/*.asm")) + [repo / "engine/events/prize_menu.asm"])
        profile = DATA["titles"][variant]
        assert calls == len(profile["sites"]), (variant, calls)
        assert set(profile["excluded"]) == {"grant:starter:0"}
        for site in profile["sites"].values():
            assert len(site["species"]["rom_offsets"]) == len(site["species"]["clean"])
            assert all(0 < level <= 100 for level in site["level"]["values"])
            assert site["return"]["address"] == site["call"]["address"] + 3
        assert profile["give_pokemon"]["party_call"]["add_party_mon_offset"] == (9 if variant == "yellow" else 3)
        prize = profile["sites"]["grant:game_corner_purchase:0"]["purchase"]
        assert prize["paid"]["expected_hex"].startswith("C3")
        table = content(variant)
        assert len(table["species"]) == 151 and table["clean_sha1"] == profile["clean_sha1"]
        assert all(row["base_moves"][0] and all(1 <= m <= 165 for _, m in row["learnset"]) for row in table["species"].values())
        assert table["catch_rate_overrides"] == profile["catch_rate_overrides"]
        assert all(str(species) in table["species"] for site in profile["sites"].values() for species in site["species"]["clean"])
