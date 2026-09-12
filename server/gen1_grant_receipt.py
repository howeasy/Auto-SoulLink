"""Source-qualified scripted Pokemon grant facts. This module settles no rules.

A grant receipt is three read-only witnesses around one pinned `call GivePokemon`:
the call (the inputs are still in registers B=species, C=level; the wrapper writes
wCurPartySpecies/wCurEnemyLevel/wMonDataLocation only after this PC), the return
(carry = delivered, wAddedToParty = party vs. current box) and, for a Game Corner
prize, the `jp PrintPrizePrice` reached only after the coins were subtracted. The
call site names the source; the map only corroborates it. The delivered record is
re-synthesized from species, level and its own DVs the way AddPartyMon /
LoadEnemyMonData + SendNewMonToBox build it, including the header catch rate and
the WriteMonMoves move set from the generated fresh-content table; only the random
DVs and the player's nickname are taken from the record. The result is a fact for
the shared party-grant rules and frame batching, never an area or ordinal.
"""

import json
from pathlib import Path

from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.protocol import digest
from server.protocol_journal import JournalError

_DATA_DIR = Path(__file__).resolve().parents[1] / "data/games/gen1_rby"
DATA = json.loads((_DATA_DIR / "grant_sites.json").read_text())
FRESH = json.loads((_DATA_DIR / "grant_fresh_content.json").read_text())
SCHEMA = "rby-grant-receipt-v1"
WITNESS = {"frame", "pc", "bank", "sp", "point"}
POINT = {
    "party_hex",
    "box_hex",
    "trainer_hex",
    "player_id_hex",
    "map_id",
    "battle_flag",
    "cur_species",
    "cur_level",
    "mon_location",
    "added_to_party",
    "current_box",
    "coins_hex",
    "which_prize",
    "prize_window",
    "prizes_hex",
    "prices_hex",
}
CARRY = 0x10
PARTY_LENGTH, MONS_PER_BOX = 6, 20
BOX_RECORD, BOX_MONS, BOX_OT, BOX_NICK = 33, 22, 682, 902
COST_TABLES = ("PrizeMenuMon1Cost", "PrizeMenuMon2Cost")


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise JournalError("invalid grant " + label)
    return value


def raw(value, length, label):
    if not isinstance(value, str) or len(value) != length * 2:
        raise JournalError("canonical grant " + label + " bytes required")
    try:
        return bytes.fromhex(value)
    except ValueError as error:
        raise JournalError("canonical grant " + label + " bytes required") from error


def bcd(value):
    digits = value.hex()
    if any(ch > "9" for ch in digits):
        raise JournalError("invalid BCD coin value")
    return int(digits)


def fresh_stats(codec, species, dv_word, level):
    """CalcStats with zero stat experience, as pinned in home/move_mon.asm."""
    base = codec.profile["species"][str(species)]["base_stats"]  # hp, atk, def, spd, spc
    atk, dfn, spd, spc = (dv_word >> 12) & 15, (dv_word >> 8) & 15, (dv_word >> 4) & 15, dv_word & 15
    ivs = (((atk & 1) << 3) | ((dfn & 1) << 2) | ((spd & 1) << 1) | (spc & 1), atk, dfn, spd, spc)
    return tuple(
        (b + iv) * 2 * level // 100 + (level + 10 if index == 0 else 5)
        for index, (b, iv) in enumerate(zip(base, ivs, strict=True))
    )


def fresh_moves(content, species, level):
    """Header level-1 moves, then WriteMonMoves (engine/pokemon/evos_moves.asm).

    For each learnset (level, move) in ascending order until level exceeds the mon's:
    skip a move already known, fill the first empty slot, else drop slot 0 and append.
    """
    row = content["species"][str(species)]
    moves = list(row["base_moves"])
    for learned_level, move in row["learnset"]:
        if learned_level > level:
            break
        if move in moves:
            continue
        if 0 in moves:
            moves[moves.index(0)] = move
        else:
            moves = moves[1:] + [move]
    return tuple(moves)


def fresh_catch_rate(content, species):
    """Header catch rate, or the title's script override (Yellow Kadabra: TWISTEDSPOON_GSC)."""
    return content["catch_rate_overrides"].get(str(species), content["species"][str(species)]["catch_rate"])


def fresh_pp(codec, moves, packed):
    """AddPartyMon_WriteMovePP / LoadMovePPs: max PP per move, none for empty, no PP Ups."""
    for move, value in zip(moves, packed, strict=True):
        if value != (codec.max_pp(move, 0) if move else 0):
            return False
    return True


def party(codec, blob):
    """Decode an authoritative 404-byte party the same way engine signals do."""
    count = blob[0]
    if count > PARTY_LENGTH or blob[count + 1] != 255:
        raise JournalError("invalid grant party list")
    mons = []
    for slot in range(count):
        record = blob[8 + 44 * slot : 52 + 44 * slot] + blob[272 + 11 * slot : 283 + 11 * slot]
        record += blob[338 + 11 * slot : 349 + 11 * slot]
        try:
            mon = codec.validate_blob(record)
        except PartyCodecError as error:
            raise JournalError(str(error)) from error
        if mon.species_index != blob[slot + 1] or any(row.key == mon.key for row in mons):
            raise JournalError("grant party species/key collision")
        mons.append(mon)
    return mons


def box(codec, blob):
    """Decode the current box as exact records; boxes carry no stats to recompute."""
    count = blob[0]
    if count > MONS_PER_BOX or blob[count + 1] != 255:
        raise JournalError("invalid grant box list")
    records = []
    for slot in range(count):
        mon = blob[BOX_MONS + BOX_RECORD * slot : BOX_MONS + BOX_RECORD * (slot + 1)]
        if mon[0] != blob[slot + 1] or str(mon[0]) not in codec.profile["species"]:
            raise JournalError("invalid grant boxed species")
        ot = blob[BOX_OT + 11 * slot : BOX_OT + 11 * (slot + 1)]
        nick = blob[BOX_NICK + 11 * slot : BOX_NICK + 11 * (slot + 1)]
        try:
            codec._ot_name(ot, "boxed OT")
            codec._name(nick, "boxed nickname")
        except PartyCodecError as error:
            raise JournalError(str(error)) from error
        key = f"{mon[27:29].hex().upper()}:{mon[12:14].hex().upper()}:{mon[0]:02X}"
        if any(row["key"] == key for row in records):
            raise JournalError("grant box key collision")
        records.append({"key": key, "record": mon, "ot": ot, "nick": nick})
    return records


def pairing_id(source_id, group, window=None, which=None):
    """Title-neutral logical event: choices pair by event, prizes by slot, gifts by site."""
    if group in ("dojo_choice", "fossil_revival"):
        return "grant:" + group
    if group == "game_corner_purchase":
        return f"grant:{group}:{window}:{which}"
    return source_id


def _witness(value, site, label, *, extra=frozenset()):
    if not isinstance(value, dict) or set(value) != WITNESS | set(extra):
        raise JournalError("complete grant " + label + " witness required")
    integer(value["frame"], 0, 2**53 - 1, label + " frame")
    integer(value["sp"], 0xC000, 0xDFFF, label + " stack")
    if (
        type(value["pc"]) is not int
        or value["pc"] != site["address"]
        or type(value["bank"]) is not int
        or value["bank"] != site["bank"]
    ):
        raise JournalError("grant " + label + " site differs")
    for field in extra:
        integer(value[field], 0, 255, label + " " + field)
    return value


def _point(value, codec, identity, profile, label):
    if not isinstance(value, dict) or set(value) != POINT:
        raise JournalError("complete grant " + label + " observation required")
    for field in ("map_id", "battle_flag", "cur_species", "cur_level", "mon_location", "current_box"):
        integer(value[field], 0, 255, label + " " + field)
    integer(value["added_to_party"], 0, 1, label + " added_to_party")
    integer(value["which_prize"], 0, 255, label + " which_prize")
    integer(value["prize_window"], 0, 255, label + " prize_window")
    name = raw(value["trainer_hex"], 11, label + " trainer")
    try:
        codec._name(name, "grant save name")
    except PartyCodecError as error:
        raise JournalError(str(error)) from error
    raw(value["player_id_hex"], 2, label + " player id")
    if identity != {"ot_id": value["player_id_hex"], "trainer_name": display_name(name)}:
        raise JournalError("grant " + label + " belongs to another save")
    if value["battle_flag"] != profile["out_of_battle_flag"]:
        raise JournalError("grant " + label + " is not an out-of-battle delivery")
    decoded_party = party(codec, raw(value["party_hex"], 404, label + " party"))
    decoded_box = box(codec, raw(value["box_hex"], 1122, label + " box"))
    if {mon.key for mon in decoded_party} & {row["key"] for row in decoded_box}:
        raise JournalError("grant " + label + " has one key in both party and current box")
    return {
        "party": decoded_party,
        "party_raw": bytes.fromhex(value["party_hex"]),
        "box": decoded_box,
        "box_raw": bytes.fromhex(value["box_hex"]),
        "coins": bcd(raw(value["coins_hex"], 2, label + " coins")),
        "prizes": raw(value["prizes_hex"], 3, label + " prizes"),
        "prices": raw(value["prices_hex"], 6, label + " prices"),
        "name": name,
    }


def _fresh_party_mon(codec, content, mon, species, level, ot_id, name):
    """AddPartyMon, not wild: everything but the random DVs and the nickname is determined."""
    facts = codec.profile["species"][str(species)]
    stats = fresh_stats(codec, species, mon.dv_word, level)
    if (
        mon.species_index != species
        or mon.level != level
        or mon.box_level != 0
        or mon.status != 0
        or mon.ot_id != ot_id
        or mon.ot_name != name
        or mon.types != tuple(facts["types"])
        or mon.catch_rate != fresh_catch_rate(content, species)
        or mon.moves != fresh_moves(content, species, level)
        or mon.experience != codec.experience_for_level(facts["growth_rate"], level)
        or any(mon.stat_experience)
        or mon.computed_stats != stats
        or mon.hp != stats[0]
        or any(mon.pp_ups)
        or not fresh_pp(codec, mon.moves, mon.pp)
    ):
        raise JournalError("delivered party mon is not a fresh AddPartyMon result for the pinned operands")


def _fresh_box_record(codec, content, record, ot, species, level, ot_id, name):
    """LoadEnemyMonData + SendNewMonToBox: HP is the fresh HP stat, exp exact, EVs zero."""
    facts = codec.profile["species"][str(species)]
    dv_word = int.from_bytes(record[27:29], "big")
    moves, packed = tuple(record[8:12]), tuple(record[29:33])
    if (
        record[0] != species
        or record[3] != level
        or record[4] != 0
        or tuple(record[5:7]) != tuple(facts["types"])
        or record[7] != fresh_catch_rate(content, species)
        or moves != fresh_moves(content, species, level)
        or int.from_bytes(record[1:3], "big") != fresh_stats(codec, species, dv_word, level)[0]
        or int.from_bytes(record[12:14], "big") != ot_id
        or int.from_bytes(record[14:17], "big") != codec.experience_for_level(facts["growth_rate"], level)
        or any(record[17:27])
        or any(value >> 6 for value in packed)
        or not fresh_pp(codec, moves, packed)
        or ot != name
    ):
        raise JournalError("delivered boxed mon is not a fresh SendNewMonToBox record for the pinned operands")


def validate(
    receipt,
    *,
    variant,
    identity,
    context_generation,
    physical_instance,
    final_sha1,
    rom_bytes=None,
    codec=None,
    content=None,
):
    """Return the delivered grant as a source-qualified fact, or refuse.

    `rom_bytes` maps pinned mutable ROM offsets to the admitted cartridge's bytes when
    an approved UPR static rewrite changed a species operand; without it the clean
    operands are the only ones accepted. Level operands and prize prices are never
    mutable. `codec`/`content` let a caller supply admitted species content for a
    cartridge whose approved changes altered it; under current approval policy the
    audit refuses such changes, so the clean tables are the admitted content.
    """
    if not isinstance(variant, str) or variant not in DATA["titles"]:
        raise JournalError("RBY grant variant required")
    profile = DATA["titles"][variant]
    content = content or FRESH["titles"][variant]
    required = {
        "schema",
        "source_sha256",
        "variant",
        "context_generation",
        "physical_instance",
        "final_sha1",
        "source_id",
        "call",
        "return",
    }
    if not isinstance(receipt, dict) or not required <= set(receipt) or set(receipt) - required - {"paid"}:
        raise JournalError("complete grant receipt required")
    if (
        receipt["schema"] != SCHEMA
        or receipt["source_sha256"] != DATA["sha256"]
        or receipt["variant"] != variant
        or receipt["context_generation"] != context_generation
        or receipt["physical_instance"] != physical_instance
        or receipt["final_sha1"] != final_sha1
    ):
        raise JournalError("grant source or physical context differs")
    source_id = receipt["source_id"]
    if source_id in profile["excluded"]:
        raise JournalError("starter grant is settled by the engine-signal starter pair")
    if not isinstance(source_id, str) or source_id not in profile["sites"]:
        raise JournalError("unknown grant source")
    site = profile["sites"][source_id]
    # The wrapper has not run at the call PC: the operands are the incoming registers.
    call = _witness(receipt["call"], site["call"], "call", extra={"b", "c"})
    ret = _witness(receipt["return"], site["return"], "return", extra={"flags"})
    if ret["sp"] != call["sp"] or ret["frame"] < call["frame"]:
        raise JournalError("grant call/return stack or frame differs")
    if not ret["flags"] & CARRY:
        raise JournalError("grant was not delivered: party and box were full")
    codec = codec or PartyCodec(variant)
    if not isinstance(codec, PartyCodec) or codec.variant != variant:
        raise JournalError("grant codec must describe the receipt's title")
    if not isinstance(content, dict) or not {"species", "catch_rate_overrides"} <= set(content):
        raise JournalError("grant fresh-content table must carry species and overrides")
    before = _point(call["point"], codec, identity, profile, "call")
    after = _point(ret["point"], codec, identity, profile, "return")
    for point in (call["point"], ret["point"]):
        if point["map_id"] != site["map_id"]:
            raise JournalError("grant map differs from its call site")
    species, level = call["b"], call["c"]
    if (
        ret["point"]["cur_species"] != species
        or ret["point"]["cur_level"] != level
        or ret["point"]["mon_location"] != 0
    ):
        raise JournalError("GivePokemon globals at return differ from the call registers")
    overrides = rom_bytes or {}
    if not isinstance(overrides, dict) or any(
        type(k) is not int or type(v) is not int or not 0 <= v <= 255 for k, v in overrides.items()
    ):
        raise JournalError("ROM operand overrides must map pinned offsets to bytes")
    if set(overrides) - set(site["species"]["rom_offsets"]):
        raise JournalError("ROM override names a byte this grant does not read")
    allowed = [
        overrides.get(offset, clean)
        for offset, clean in zip(site["species"]["rom_offsets"], site["species"]["clean"], strict=True)
    ]
    if species not in allowed or str(species) not in codec.profile["species"] or str(species) not in content["species"]:
        raise JournalError("grant species is not a pinned operand of this source")
    # GetPrizeMonLevel takes the FIRST dictionary key equal to the species; a duplicated
    # randomized prize species therefore gets the first slot's level whichever slot was bought.
    values = site["level"]["values"]
    if level != (values[allowed.index(species)] if len(values) > 1 else values[0]):
        raise JournalError("grant level differs from its pinned operand")
    purchase = None
    if "purchase" in site:
        window, which = call["point"]["prize_window"], call["point"]["which_prize"]
        if window not in site["purchase"]["mon_windows"] or not 0 <= which <= 2:
            raise JournalError("prize purchase is not a Pokemon prize slot")
        if allowed[window * 3 + which] != species or before["prizes"] != bytes(allowed[window * 3 : window * 3 + 3]):
            raise JournalError("prize table or slot differs from the delivered species")
        # Prices are never rewritten by approved presets; the RAM table must be the pinned one.
        if before["prices"] != bytes.fromhex(site["purchase"]["clean_costs_bcd"][COST_TABLES[window]]):
            raise JournalError("prize price table differs from the pinned clean costs")
        if "paid" not in receipt:
            raise JournalError("delivered prize lacks its payment witness")
        paid = _witness(receipt["paid"], site["purchase"]["paid"], "paid")
        if paid["sp"] != call["sp"] or paid["frame"] < ret["frame"]:
            raise JournalError("prize payment stack or frame differs")
        settled = _point(paid["point"], codec, identity, profile, "paid")
        if settled["party_raw"] != after["party_raw"] or settled["box_raw"] != after["box_raw"]:
            raise JournalError("storage changed between delivery and payment")
        price = bcd(before["prices"][2 * which : 2 * which + 2])
        if before["coins"] < price:
            raise JournalError("prize was delivered without enough coins")
        if after["coins"] != before["coins"] or settled["coins"] != before["coins"] - price:
            raise JournalError("prize payment differs from its price")
        purchase = {
            "window": window,
            "which": which,
            "price": price,
            "coins_before": before["coins"],
            "coins_after": settled["coins"],
        }
    elif "paid" in receipt:
        raise JournalError("only a prize purchase carries a payment witness")
    if call["point"]["current_box"] != ret["point"]["current_box"]:
        raise JournalError("current box changed during delivery")
    ot_id = int(call["point"]["player_id_hex"], 16)
    known = {mon.key for mon in before["party"]} | {row["key"] for row in before["box"]}
    fact = {
        "kind": "scripted_grant",
        "source_id": source_id,
        "group": site["group"],
        "yellow_only": site["yellow_only"],
        "pairing_id": pairing_id(source_id, site["group"], purchase and purchase["window"], purchase and purchase["which"]),
        "species_index": species,
        "level": level,
        "map_id": site["map_id"],
        "call_frame": call["frame"],
        "return_frame": ret["frame"],
        "frame": ret["frame"],
        "purchase": purchase,
        "receipt_digest": digest(receipt),
    }
    if ret["point"]["added_to_party"] == 1:
        if len(after["party"]) != len(before["party"]) + 1 or after["box_raw"] != before["box_raw"]:
            raise JournalError("party delivery must append exactly one mon and leave the box")
        if [mon.raw for mon in after["party"][:-1]] != [mon.raw for mon in before["party"]]:
            raise JournalError("party delivery changed an existing party member")
        mon = after["party"][-1]
        _fresh_party_mon(codec, content, mon, species, level, ot_id, before["name"])
        if mon.key in known:
            raise JournalError("delivered mon duplicates an existing party or boxed key")
        fact.update(delivery="party", slot=len(before["party"]), key=mon.key, blob_hex=mon.raw.hex().upper(),
                    location={"kind": "party", "slot": len(before["party"]), "box": None})
        return fact
    if len(before["party"]) != PARTY_LENGTH or after["party_raw"] != before["party_raw"]:
        raise JournalError("box delivery requires a full, unchanged party")
    if len(after["box"]) != len(before["box"]) + 1:
        raise JournalError("box delivery must add exactly one record")
    # SendNewMonToBox inserts at slot 0 and shifts every existing record, OT and nickname down.
    for old, new in zip(before["box"], after["box"][1:], strict=True):
        if (old["record"], old["ot"], old["nick"]) != (new["record"], new["ot"], new["nick"]):
            raise JournalError("box delivery did not shift the existing records intact")
    record = after["box"][0]
    _fresh_box_record(codec, content, record["record"], record["ot"], species, level, ot_id, before["name"])
    if record["key"] in known:
        raise JournalError("delivered mon duplicates an existing party or boxed key")
    fact.update(
        delivery="box",
        box_index=ret["point"]["current_box"] & 127,
        box_slot=0,
        key=record["key"],
        blob_hex=(record["record"] + record["ot"] + record["nick"]).hex().upper(),
        location={"kind": "box", "slot": 0, "box": ret["point"]["current_box"] & 127},
    )
    return fact
