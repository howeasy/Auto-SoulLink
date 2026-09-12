"""Source-qualified static-battle origin facts. This module settles no rules.

An origin receipt is two read-only witnesses: `arm`, the PC right after the static's
opponent species and level were written (a Snorlax map script's own write block, or the
shared `InitBattleEnemyParameters.noTrainer` ret for object statics, where wSpriteIndex
names the object), and `began`, InitWildBattle just after wIsInBattle := 1, where the
engine has copied wCurOpponent into wEnemyMonSpecies2. The arm site (plus map and, for
objects, sprite index) names the static; `began` proves a normal wild battle started with
exactly those operands. `attribute` then joins a decoded ItemUseBall capture fact to the
origin by map, delivering battle type, species, level and frame order. Ghost Marowak and
the unidentified GHOST never yield a static id: every Pokemon Tower map is refused.

A third witness, `end`, is EndOfBattle's entry: the one routine every battle leaves through
(win, loss, RUN, capture, wild flight), where wBattleResult is final and the operands are
still intact. `validate_end` turns it into a `static_battle_end` fact without naming a
static; `gen1_static_lifecycle` joins it to the live origin by order. A ball that breaks free
never reaches EndOfBattle, so it is not a battle end.
"""

import json
from pathlib import Path

from server.gen1_capture_receipt import DATA as CAPTURE
from server.gen1_engine_signals import integer, raw
from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.protocol import digest
from server.protocol_journal import JournalError

DATA = json.loads((Path(__file__).resolve().parents[1] / "data/games/gen1_rby/static_sites.json").read_text())
SCHEMA = "rby-static-origin-receipt-v1"
WITNESS = {"frame", "pc", "bank", "sp", "point"}
POINT = {
    "map_id",
    "cur_opponent",
    "cur_level",
    "enemy_species2",
    "battle_flag",
    "battle_type",
    "sprite_index",
    "engaged_class",
    "engaged_set",
    "battle_result",
    "trainer_hex",
    "player_id_hex",
}
HEADER = {"schema", "source_sha256", "variant", "context_generation", "physical_instance", "final_sha1"}
REQUIRED = HEADER | {"source_id", "arm", "began"}
END_REQUIRED = HEADER | {"end"}
CAPTURE_FACT = {"kind", "map_id", "battle_type", "species_index", "level", "call_frame"}


def _witness(value, site, label):
    if not isinstance(value, dict) or set(value) != WITNESS:
        raise JournalError("complete static " + label + " witness required")
    integer(value["frame"], 0, 2**53 - 1, label + " frame")
    integer(value["sp"], 0xC000, 0xDFFF, label + " stack")
    if (
        type(value["pc"]) is not int
        or value["pc"] != site["address"]
        or type(value["bank"]) is not int
        or value["bank"] != site["bank"]
    ):
        raise JournalError("static " + label + " site differs")
    return value


def _point(value, codec, identity, label):
    if not isinstance(value, dict) or set(value) != POINT:
        raise JournalError("complete static " + label + " observation required")
    for field in POINT - {"trainer_hex", "player_id_hex"}:
        integer(value[field], 0, 255, label + " " + field)
    name = raw(value["trainer_hex"], 11)
    try:
        codec._name(name, "static save name")
    except PartyCodecError as error:
        raise JournalError(str(error)) from error
    raw(value["player_id_hex"], 2)
    if identity != {"ot_id": value["player_id_hex"], "trainer_name": display_name(name)}:
        raise JournalError("static " + label + " belongs to another save")
    return value


def _header(receipt, required, label, variant, context_generation, physical_instance, final_sha1):
    if not isinstance(variant, str) or variant not in DATA["titles"]:
        raise JournalError("RBY static variant required")
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise JournalError("complete static " + label + " receipt required")
    if (
        receipt["schema"] != SCHEMA
        or receipt["source_sha256"] != DATA["sha256"]
        or receipt["variant"] != variant
        or receipt["context_generation"] != context_generation
        or receipt["physical_instance"] != physical_instance
        or receipt["final_sha1"] != final_sha1
    ):
        raise JournalError("static source or physical context differs")
    return DATA["titles"][variant]


def validate_end(receipt, *, variant, identity, context_generation, physical_instance, final_sha1):
    """Return the end of a battle as a fact, or refuse. Names no static: order does that.

    EndOfBattle's entry is reached exactly once per battle, whatever ended it; wBattleResult
    ($00 win, $01 lose, $02 draw: caught or ran) and the opponent operands are still intact.
    """
    profile = _header(receipt, END_REQUIRED, "battle end", variant, context_generation, physical_instance, final_sha1)
    end = _witness(receipt["end"], profile["battle_end"], "battle end")
    point = _point(end["point"], PartyCodec(variant), identity, "battle end")
    if point["battle_flag"] not in (profile["wild_battle_flag"], profile["trainer_battle_flag"]):
        raise JournalError("static battle end witnessed outside a battle")
    if point["battle_result"] not in profile["battle_results"].values():
        raise JournalError("battle result byte out of range")
    return {
        "kind": "static_battle_end",
        "static_id": None,
        "map_id": point["map_id"],
        "battle_flag": point["battle_flag"],
        "battle_type": point["battle_type"],
        "species_index": point["cur_opponent"],
        "level": point["cur_level"],
        "battle_result": point["battle_result"],
        "frame": end["frame"],
        "receipt_digest": digest(receipt),
    }


def validate(receipt, *, variant, identity, context_generation, physical_instance, final_sha1, rom_bytes=None):
    """Return the static battle origin as a source-qualified fact, or refuse.

    `rom_bytes` maps pinned mutable ROM offsets to the admitted cartridge's bytes when an
    approved UPR static rewrite changed the species operand; without it only the clean
    operand is accepted. Level operands are never mutable.
    """
    profile = _header(receipt, REQUIRED, "origin", variant, context_generation, physical_instance, final_sha1)
    source_id = receipt["source_id"]
    if isinstance(source_id, str) and source_id in profile["excluded"]:
        raise JournalError("uncatchable scripted battle is excluded: " + profile["excluded"][source_id]["reason"])
    if not isinstance(source_id, str) or source_id not in profile["sites"]:
        raise JournalError("unknown static source")
    site = profile["sites"][source_id]
    arm = _witness(receipt["arm"], site["arm"], "arm")
    began = _witness(receipt["began"], profile["began"], "began")
    if began["frame"] < arm["frame"]:
        raise JournalError("static battle began before its operands were written")
    codec = PartyCodec(variant)
    before, after = _point(arm["point"], codec, identity, "arm"), _point(began["point"], codec, identity, "began")
    if after["map_id"] in profile["tower_map_ids"]:
        raise JournalError("Pokemon Tower battle: Ghost Marowak or unidentified GHOST, never a catchable static")
    if before["map_id"] != site["map_id"] or after["map_id"] != site["map_id"]:
        raise JournalError("static map differs from its source")
    if before["battle_flag"] != profile["out_of_battle_flag"]:
        raise JournalError("static operands were not written from the overworld")
    if after["battle_flag"] != profile["wild_battle_flag"] or after["battle_type"] != profile["origin_battle_type"]:
        raise JournalError("static battle is not a normal wild battle")
    species, level = before["cur_opponent"], before["cur_level"]
    if after["cur_opponent"] != species or after["enemy_species2"] != species or after["cur_level"] != level:
        raise JournalError("battle operands differ from the static's written operands")
    if site["kind"] == "object":
        if before["sprite_index"] != site["object_index"]:
            raise JournalError("engaged sprite is not this static's object")
        if before["engaged_class"] != species or before["engaged_set"] != level:
            raise JournalError("engaged object record differs from the written operands")
    overrides = rom_bytes or {}
    if not isinstance(overrides, dict) or any(
        type(k) is not int or type(v) is not int or not 0 <= v <= 255 for k, v in overrides.items()
    ):
        raise JournalError("ROM operand overrides must map pinned offsets to bytes")
    if set(overrides) - set(site["species"]["rom_offsets"]):
        raise JournalError("ROM override names a byte this static does not read")
    allowed = [
        overrides.get(offset, clean)
        for offset, clean in zip(site["species"]["rom_offsets"], site["species"]["clean"], strict=True)
    ]
    if species not in allowed or not 1 <= species < profile["constants"]["opp_id_offset"]:
        raise JournalError("static species is not a pinned operand of this source")
    if level != site["level"]["values"][0]:
        raise JournalError("static level differs from its pinned operand")
    return {
        "kind": "static_origin",
        "static_id": source_id,  # the census id is already title-neutral (asserted by the generator)
        "source_id": source_id,
        "static_kind": site["kind"],
        "object_index": site.get("object_index"),
        "species_index": species,
        "level": level,
        "map_id": site["map_id"],
        "battle_type": after["battle_type"],
        "arm_frame": arm["frame"],
        "began_frame": began["frame"],
        "frame": began["frame"],
        "receipt_digest": digest(receipt),
    }


def attribute(capture_fact, origin_fact, *, variant):
    """Name the static a decoded capture fact came from, or refuse.

    The capture must be a delivering wild battle on the origin's map with the origin's
    species and level, delivered at or after the battle began. Same-battle continuity is
    not proved here: the caller consumes each origin once, with the first such capture.
    """
    if not isinstance(variant, str) or variant not in DATA["titles"]:
        raise JournalError("RBY static variant required")
    profile = DATA["titles"][variant]
    if not isinstance(origin_fact, dict) or origin_fact.get("kind") != "static_origin":
        raise JournalError("static origin fact required")
    static_id = origin_fact.get("static_id")
    if static_id not in profile["sites"]:
        raise JournalError("static origin is not a catchable static of this title")
    if not isinstance(capture_fact, dict) or CAPTURE_FACT - set(capture_fact) or capture_fact["kind"] != "capture":
        raise JournalError("decoded capture fact required")
    for field in ("map_id", "battle_type", "species_index", "level"):
        integer(capture_fact[field], 0, 255, "capture " + field)
    integer(capture_fact["call_frame"], 0, 2**53 - 1, "capture call_frame")
    if capture_fact["map_id"] != origin_fact["map_id"]:
        raise JournalError("capture happened on another map than the static battle")
    if (
        capture_fact["battle_type"] not in CAPTURE["titles"][variant]["delivering_battle_types"].values()
        or capture_fact["battle_type"] != origin_fact["battle_type"]
    ):
        raise JournalError("capture battle type differs from the static battle")
    if capture_fact["species_index"] != origin_fact["species_index"] or capture_fact["level"] != origin_fact["level"]:
        raise JournalError("captured species/level differ from the static's operands")
    if capture_fact["call_frame"] < origin_fact["frame"]:
        raise JournalError("capture was delivered before the static battle began")
    return static_id
