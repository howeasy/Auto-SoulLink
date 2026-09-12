"""Source-shaped encounter boundaries, without timer or rule authority."""

import json
from pathlib import Path

from server.gen1_bag import decode_bag
from server.gen1_engine_signals import integer, raw
from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.protocol import digest
from server.protocol_journal import JournalError

DATA = json.loads(
    (
        Path(__file__).resolve().parents[1] / "data/games/gen1_rby/wild_encounter_sites.json"
    ).read_text()
)
SCHEMA = "rby-wild-encounter-receipt-v1"
POINT = {
    "map_id",
    "cur_opponent",
    "species_index",
    "level",
    "battle_flag",
    "battle_type",
    "battle_result",
    "link_state",
    "bag_hex",
    "trainer_hex",
    "player_id_hex",
}
HEADER = {
    "schema",
    "source_sha256",
    "variant",
    "context_generation",
    "physical_instance",
    "final_sha1",
    "kind",
    "witness",
}


def validate(receipt, *, variant, identity, context_generation, physical_instance, final_sha1):
    if not isinstance(variant, str) or variant not in DATA["titles"]:
        raise JournalError("RBY wild encounter variant required")
    if (
        not isinstance(receipt, dict)
        or set(receipt) != HEADER
        or receipt["kind"] not in ("begin", "end")
    ):
        raise JournalError("complete wild encounter boundary required")
    if (
        receipt["schema"] != SCHEMA
        or receipt["source_sha256"] != DATA["sha256"]
        or receipt["variant"] != variant
        or receipt["context_generation"] != context_generation
        or receipt["physical_instance"] != physical_instance
        or receipt["final_sha1"] != final_sha1
    ):
        raise JournalError("wild encounter source/admission differs")
    profile = DATA["titles"][variant]
    site = profile["sites"][receipt["kind"]]
    w = receipt["witness"]
    if not isinstance(w, dict) or set(w) != {"frame", "pc", "bank", "sp", "point"}:
        raise JournalError("complete wild encounter witness required")
    if (
        type(w["pc"]) is not int
        or w["pc"] != site["address"]
        or type(w["bank"]) is not int
        or w["bank"] != site["bank"]
    ):
        raise JournalError("wild encounter instruction site differs")
    integer(w["frame"], 0, 2**53 - 1, "encounter frame")
    integer(w["sp"], 0xC000, 0xDFFF, "encounter stack")
    p = w["point"]
    if not isinstance(p, dict) or set(p) != POINT:
        raise JournalError("complete wild encounter point required")
    for key in POINT - {"bag_hex", "trainer_hex", "player_id_hex"}:
        integer(p[key], 0, 255, key)
    codec = PartyCodec(variant)
    try:
        name = raw(p["trainer_hex"], 11)
        codec._name(name, "wild encounter save")
    except PartyCodecError as error:
        raise JournalError(str(error)) from error
    raw(p["player_id_hex"], 2)
    if identity != {"ot_id": p["player_id_hex"], "trainer_name": display_name(name)}:
        raise JournalError("wild encounter belongs to another save")
    bag = decode_bag(p["bag_hex"])
    if p["battle_flag"] != 1:
        raise JournalError("wild boundary is not in a wild battle")
    excluded = None
    if p["link_state"] != 0:
        excluded = "link_battle"
    elif p["battle_type"] not in (
        profile["battle_types"]["BATTLE_TYPE_NORMAL"],
        profile["battle_types"]["BATTLE_TYPE_SAFARI"],
    ):
        excluded = "tutorial_or_scripted_battle_type"
    elif p["map_id"] in profile["tower_maps"] and not any(
        row["item"] == profile["silph_scope"] for row in bag
    ):
        excluded = "unidentified_ghost"
    elif p["map_id"] == profile["ghost_script_map"] and p["cur_opponent"] != 0:
        # UPR may rewrite Ghost Marowak's species. Its scripted map remains the
        # engine's uncatchable encounter; species 0x91 is not an authority anchor.
        excluded = "ghost_marowak"
    species = codec.profile["species"].get(str(p["species_index"]))
    if excluded is None and (species is None or not 1 <= p["level"] <= 100):
        raise JournalError("wild encounter species/level are unavailable")
    if receipt["kind"] == "end" and p["battle_result"] not in (0, 1, 2):
        raise JournalError("unknown wild battle result")
    return {
        "kind": "wild_" + receipt["kind"],
        "frame": w["frame"],
        "map_id": p["map_id"],
        "species_index": p["species_index"],
        "species_id": species["dex"] if species else 0,
        "level": p["level"],
        "battle_type": p["battle_type"],
        "cur_opponent": p["cur_opponent"],
        "battle_result": p["battle_result"] if receipt["kind"] == "end" else None,
        "exclusion": excluded,
        "receipt_digest": digest(receipt),
    }
