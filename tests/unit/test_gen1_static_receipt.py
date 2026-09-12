"""Static origin receipts: arm names the static, began proves the battle, attribute joins.

Every fixture is synthetic: witness points are built from the generated site data (clean
species/level operands, map ids, sprite indices) and shaped as the engine leaves RAM at the
two pinned PCs. No live engine evidence is claimed here; the regeneration test re-checks
the generator's ROM-byte anchors against the clean cartridges.
"""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from server.gen1_capture_receipt import decode_capture
from server.gen1_static_receipt import DATA, SCHEMA, attribute, validate, validate_end
from server.protocol_journal import JournalError
from tests.unit.test_gen1_capture_receipt import receipt as capture_receipt

ROOT = Path(__file__).resolve().parents[2]
TRAINER = "92808C8450000000000000"  # SAME
SAVE = {"ot_id": "1234", "trainer_name": "SAME"}
CONTEXT = {"context_generation": "a" * 32, "physical_instance": "1" * 32}
SITES = [(variant, source) for variant in DATA["titles"] for source in DATA["titles"][variant]["sites"]]
EXCLUDED = [(variant, source) for variant in DATA["titles"] for source in DATA["titles"][variant]["excluded"]]
STALE = 0xEE  # a value the decoder must never read at the witness in question


def point(map_id, species, level, *, battle_flag, battle_type=0, enemy_species2, sprite_index, engaged_class, engaged_set, player_id="1234",
          battle_result=0):
    return {
        "map_id": map_id,
        "cur_opponent": species,
        "cur_level": level,
        "enemy_species2": enemy_species2,
        "battle_flag": battle_flag,
        "battle_type": battle_type,
        "sprite_index": sprite_index,
        "engaged_class": engaged_class,
        "engaged_set": engaged_set,
        "battle_result": battle_result,
        "trainer_hex": TRAINER,
        "player_id_hex": player_id,
    }


def receipt(variant, source, *, species=None, level=None, arm_frame=100, began_frame=101):
    """`species`/`level` override the written operands (clean by default)."""
    profile = DATA["titles"][variant]
    site = profile["sites"][source]
    species = site["species"]["clean"][0] if species is None else species
    level = site["level"]["values"][0] if level is None else level
    obj = site["kind"] == "object"
    engaged = {"sprite_index": site["object_index"] if obj else 7, "engaged_class": species if obj else STALE, "engaged_set": level if obj else STALE}
    return {
        "schema": SCHEMA,
        "source_sha256": DATA["sha256"],
        "variant": variant,
        **CONTEXT,
        "final_sha1": profile["clean_sha1"],
        "source_id": source,
        "arm": {"frame": arm_frame, "pc": site["arm"]["address"], "bank": site["arm"]["bank"], "sp": 0xDFFE,
                "point": point(site["map_id"], species, level, battle_flag=0, enemy_species2=STALE, **engaged)},
        "began": {"frame": began_frame, "pc": profile["began"]["address"], "bank": profile["began"]["bank"], "sp": 0xDFF0,
                  "point": point(site["map_id"], species, level, battle_flag=1, enemy_species2=species, **engaged)},
    }


def check(value, variant, **overrides):
    return validate(value, variant=variant, identity=SAVE, final_sha1=DATA["titles"][variant]["clean_sha1"], **CONTEXT, **overrides)


def end_receipt(variant, source="static:route12_snorlax", *, frame=300, battle_result=0, battle_flag=1, species=None, level=None):
    """EndOfBattle's entry as the engine leaves RAM there: operands intact, wBattleResult final."""
    profile = DATA["titles"][variant]
    site = profile["sites"][source]
    species = site["species"]["clean"][0] if species is None else species
    level = site["level"]["values"][0] if level is None else level
    return {
        "schema": SCHEMA,
        "source_sha256": DATA["sha256"],
        "variant": variant,
        **CONTEXT,
        "final_sha1": profile["clean_sha1"],
        "end": {"frame": frame, "pc": profile["battle_end"]["address"], "bank": profile["battle_end"]["bank"], "sp": 0xDFF4,
                "point": point(site["map_id"], species, level, battle_flag=battle_flag, enemy_species2=species, sprite_index=7,
                               engaged_class=STALE, engaged_set=STALE, battle_result=battle_result)},
    }


def check_end(value, variant):
    return validate_end(value, variant=variant, identity=SAVE, final_sha1=DATA["titles"][variant]["clean_sha1"], **CONTEXT)


def refuse(value, variant, match=None, **overrides):
    before = copy.deepcopy(value)
    with pytest.raises(JournalError, match=match):
        check(value, variant, **overrides)
    assert value == before


def capture_fact(variant, source, **over):
    """A real decode_capture fact for the static's clean operands on its map."""
    site = DATA["titles"][variant]["sites"][source]
    fields = {"species": site["species"]["clean"][0], "level": site["level"]["values"][0], "map_id": site["map_id"]}
    fields.update(over)
    return decode_capture(capture_receipt(variant, **fields), variant, SAVE)


@pytest.mark.parametrize("variant,source", SITES, ids=lambda v: str(v))
def test_every_catchable_static_yields_its_title_neutral_id(variant, source):
    value = receipt(variant, source)
    before = copy.deepcopy(value)
    fact = check(value, variant)
    assert value == before
    site = DATA["titles"][variant]["sites"][source]
    assert fact["kind"] == "static_origin" and fact["static_id"] == fact["source_id"] == source
    assert fact["static_kind"] == site["kind"] and fact["object_index"] == site.get("object_index")
    assert fact["species_index"] == site["species"]["clean"][0] and fact["level"] == site["level"]["values"][0]
    assert fact["map_id"] == site["map_id"] and fact["battle_type"] == 0
    assert fact["arm_frame"] == 100 and fact["frame"] == fact["began_frame"] == 101
    assert len(fact["receipt_digest"]) == 64
    if site["kind"] == "script":
        assert value["arm"]["point"]["engaged_class"] == STALE  # object fields are read, not proved, for script statics
    else:
        assert value["arm"]["bank"] == 0  # the shared home routine names the object through wSpriteIndex


def test_static_ids_and_operands_are_identical_across_titles():
    red, blue, yellow = (DATA["titles"][variant]["sites"] for variant in ("red", "blue", "yellow"))
    assert set(red) == set(blue) == set(yellow) and len(red) == 14
    for source in red:
        assert red[source]["species"]["clean"] == blue[source]["species"]["clean"] == yellow[source]["species"]["clean"]
        assert red[source]["level"]["values"] == blue[source]["level"]["values"] == yellow[source]["level"]["values"]
        assert red[source]["map_id"] == blue[source]["map_id"] == yellow[source]["map_id"]
        facts = [check(receipt(variant, source), variant) for variant in ("red", "blue", "yellow")]
        assert len({fact["static_id"] for fact in facts}) == 1
    assert DATA["titles"]["red"]["began"]["bank"] == 15 and DATA["titles"]["yellow"]["began"]["bank"] == 61  # Yellow moved InitBattle


@pytest.mark.parametrize(
    "fault",
    ["schema", "source_pin", "variant", "context", "instance", "rom", "unknown_source", "missing_field", "extra_field",
     "arm_pc", "arm_bank", "began_pc", "began_bank", "frame_order", "boolean_frame", "stack", "identity_arm", "identity_began",
     "bad_name", "arm_map", "began_map", "arm_in_battle", "began_not_wild", "began_old_man", "began_safari",
     "opponent_changed", "enemy_species2", "level_changed", "species_drift", "level_drift", "trainer_class",
     "zero_species", "point_field_missing", "point_extra"],
)
def test_hostile_origin_receipts_are_refused(fault):
    value = receipt("yellow", "static:route12_snorlax")
    arm, began = value["arm"], value["began"]
    match = None
    if fault == "schema":
        value["schema"] = "rby-static-origin-receipt-v0"
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
        value["source_id"], match = "static:mew", "unknown static source"
    elif fault == "missing_field":
        del value["began"]
    elif fault == "extra_field":
        value["ordinal"] = 1
    elif fault == "arm_pc":
        arm["pc"] -= 5
    elif fault == "arm_bank":
        arm["bank"] += 1
    elif fault == "began_pc":
        began["pc"] -= 5  # the `ld [wIsInBattle], a` itself, before the flag is written
    elif fault == "began_bank":
        began["bank"] = 15  # Red's bank on a Yellow cartridge
    elif fault == "frame_order":
        began["frame"], match = arm["frame"] - 1, "began before its operands"
    elif fault == "boolean_frame":
        arm["frame"] = True
    elif fault == "stack":
        began["sp"] = 0xBFFF
    elif fault == "identity_arm":
        arm["point"]["player_id_hex"] = "5678"
    elif fault == "identity_began":
        began["point"]["trainer_hex"] = "91808C8450000000000000"
    elif fault == "bad_name":
        arm["point"]["trainer_hex"] = "00" * 11
    elif fault == "arm_map":
        arm["point"]["map_id"], match = 27, "map differs"  # Route 16's Snorlax script, wrong for the Route 12 site
    elif fault == "began_map":
        began["point"]["map_id"], match = 27, "map differs"
    elif fault == "arm_in_battle":
        arm["point"]["battle_flag"], match = 1, "not written from the overworld"
    elif fault == "began_not_wild":
        began["point"]["battle_flag"], match = 2, "not a normal wild battle"
    elif fault == "began_old_man":
        began["point"]["battle_type"], match = 1, "not a normal wild battle"
    elif fault == "began_safari":
        began["point"]["battle_type"], match = 2, "not a normal wild battle"
    elif fault == "opponent_changed":
        began["point"]["cur_opponent"] = began["point"]["enemy_species2"] = 0x85
        match = "operands differ"
    elif fault == "enemy_species2":
        began["point"]["enemy_species2"], match = 0x85, "operands differ"
    elif fault == "level_changed":
        began["point"]["cur_level"], match = 31, "operands differ"
    elif fault == "species_drift":
        for row in (arm, began):
            row["point"]["cur_opponent"] = row["point"]["enemy_species2"] = 0x85
        match = "not a pinned operand"
    elif fault == "level_drift":
        for row in (arm, began):
            row["point"]["cur_level"] = 31
        match = "level differs"
    elif fault == "trainer_class":
        for row in (arm, began):
            row["point"]["cur_opponent"] = row["point"]["enemy_species2"] = 201  # OPP_ID_OFFSET + 1
        match = "not a pinned operand"
    elif fault == "zero_species":
        for row in (arm, began):
            row["point"]["cur_opponent"] = row["point"]["enemy_species2"] = 0
    elif fault == "point_field_missing":
        del began["point"]["battle_type"]
    elif fault == "point_extra":
        arm["point"]["silph_scope"] = 1
    refuse(value, "yellow", match)


@pytest.mark.parametrize("variant,source", EXCLUDED, ids=lambda v: str(v))
def test_uncatchable_scripted_battles_are_refused_by_id_with_their_reason(variant, source):
    profile = DATA["titles"][variant]
    value = receipt(variant, "static:route12_snorlax") | {"source_id": source}
    refuse(value, variant, "uncatchable scripted battle is excluded")
    assert profile["excluded"][source]["reason"]
    if source == "script-battle:ghost-marowak":
        assert profile["excluded"][source]["map_id"] in profile["tower_map_ids"] and profile["excluded"][source]["species_index"] == 0x91
    elif source == "script-battle:unidentified-tower-ghost":
        assert profile["excluded"][source]["map_ids"] == profile["tower_map_ids"] == list(range(142, 149))
    else:
        assert "BATTLE_TYPE" in profile["excluded"][source]["reason"]
    assert "script-battle:oak-pikachu" in profile["excluded"] if variant == "yellow" else "script-battle:oak-pikachu" not in profile["excluded"]


@pytest.mark.parametrize("map_id", range(142, 149))
def test_pokemon_tower_battles_never_yield_a_static_id(map_id):
    # A Marowak-shaped battle (species 0x91, level 30) on a tower map, claimed under a Snorlax site.
    value = receipt("red", "static:route12_snorlax", species=0x91)
    value["began"]["point"]["map_id"] = map_id
    refuse(value, "red", "Pokemon Tower battle")
    value["arm"]["point"]["map_id"] = map_id
    refuse(value, "red", "Pokemon Tower battle")
    # A randomized Zapdos slot that became Marowak is still a Power Plant static: only the Tower is refused.
    offset = DATA["titles"]["red"]["sites"]["static:powerplant_zapdos"]["species"]["rom_offsets"][0]
    marowak = receipt("red", "static:powerplant_zapdos", species=0x91)
    assert check(marowak, "red", rom_bytes={offset: 0x91})["species_index"] == 0x91


def test_object_static_is_named_by_map_and_sprite_index():
    one, two = "static:powerplant_voltorb1", "static:powerplant_voltorb2"
    value = receipt("blue", one)
    assert check(value, "blue")["object_index"] == 1
    swapped = receipt("blue", one)
    for row in (swapped["arm"], swapped["began"]):
        row["point"]["sprite_index"] = DATA["titles"]["blue"]["sites"][two]["object_index"]
    refuse(swapped, "blue", "not this static's object")
    stale = receipt("blue", one)
    stale["arm"]["point"]["engaged_class"] = 0x85
    refuse(stale, "blue", "engaged object record differs")
    stale = receipt("blue", one)
    stale["arm"]["point"]["engaged_set"] = 41
    refuse(stale, "blue", "engaged object record differs")
    # The Snorlax scripts never read the object fields: stale values there are irrelevant.
    snorlax = receipt("blue", "static:route16_snorlax")
    snorlax["arm"]["point"].update(sprite_index=1, engaged_class=6, engaged_set=40)
    assert check(snorlax, "blue")["static_id"] == "static:route16_snorlax"


def test_upr_rewritten_species_needs_its_checked_rom_byte_and_never_moves_the_level():
    site = DATA["titles"]["yellow"]["sites"]["static:seafoamislandsb4f_articuno"]
    offset, level_offset = site["species"]["rom_offsets"][0], site["level"]["rom_offsets"][0]
    value = receipt("yellow", "static:seafoamislandsb4f_articuno", species=4)  # a randomized Clefairy
    refuse(value, "yellow", "not a pinned operand")
    fact = check(value, "yellow", rom_bytes={offset: 4})
    assert fact["species_index"] == 4 and fact["level"] == 50 and fact["static_id"] == "static:seafoamislandsb4f_articuno"
    refuse(value, "yellow", "does not read", rom_bytes={offset: 4, level_offset: 50})
    refuse(value, "yellow", "overrides must map", rom_bytes={str(offset): 4})
    refuse(value, "yellow", "overrides must map", rom_bytes={offset: 256})
    refuse(value, "yellow", "not a pinned operand", rom_bytes={offset: 5})
    moved = receipt("yellow", "static:seafoamislandsb4f_articuno", species=4, level=51)
    refuse(moved, "yellow", "level differs", rom_bytes={offset: 4})
    assert level_offset not in site["species"]["rom_offsets"]


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
@pytest.mark.parametrize("battle_result,battle_flag", [(0, 1), (1, 1), (2, 1), (0, 2)], ids=["win", "lose", "draw", "trainer"])
def test_every_title_yields_a_battle_end_fact_without_a_static_id(variant, battle_result, battle_flag):
    value = end_receipt(variant, "static:powerplant_zapdos", battle_result=battle_result, battle_flag=battle_flag)
    before = copy.deepcopy(value)
    fact = check_end(value, variant)
    assert value == before
    assert fact == {"kind": "static_battle_end", "static_id": None, "map_id": 83, "battle_flag": battle_flag, "battle_type": 0,
                    "species_index": 0x4B, "level": 50, "battle_result": battle_result, "frame": 300, "receipt_digest": fact["receipt_digest"]}
    assert len(fact["receipt_digest"]) == 64
    assert DATA["titles"][variant]["battle_end"]["bank"] == 4 and DATA["titles"][variant]["battle_end"]["expected_hex"].endswith("FE04")


@pytest.mark.parametrize(
    "fault",
    ["pc", "bank", "result_range", "result_type", "out_of_battle", "blackout_marker", "missing_end", "origin_shape", "extra_field",
     "identity", "schema", "source_pin", "variant", "stack", "point_missing", "point_extra"],
)
def test_hostile_battle_end_receipts_are_refused(fault):
    value = end_receipt("yellow")
    end = value["end"]
    match = None
    if fault == "pc":
        end["pc"] += 5  # `.notLinkBattle`-ward: not the entry
        match = "site differs"
    elif fault == "bank":
        end["bank"], match = 15, "site differs"
    elif fault == "result_range":
        end["point"]["battle_result"], match = 3, "result byte out of range"
    elif fault == "result_type":
        end["point"]["battle_result"] = True
    elif fault == "out_of_battle":
        end["point"]["battle_flag"], match = 0, "outside a battle"
    elif fault == "blackout_marker":
        end["point"]["battle_flag"], match = 0xFF, "outside a battle"  # the overworld's $ff is written after EndOfBattle
    elif fault == "missing_end":
        del value["end"]
        match = "complete static battle end receipt"
    elif fault == "origin_shape":
        value.update(receipt("yellow", "static:route12_snorlax"))
        match = "complete static battle end receipt"
    elif fault == "extra_field":
        value["static_id"], match = "static:route12_snorlax", "complete static battle end receipt"
    elif fault == "identity":
        end["point"]["player_id_hex"], match = "5678", "another save"
    elif fault == "schema":
        value["schema"] = "rby-static-origin-receipt-v0"
    elif fault == "source_pin":
        value["source_sha256"] = "f" * 64
    elif fault == "variant":
        value["variant"] = "red"
    elif fault == "stack":
        end["sp"] = 0xE000
    elif fault == "point_missing":
        del end["point"]["battle_result"]
    else:
        end["point"]["link_state"] = 0
    before = copy.deepcopy(value)
    with pytest.raises(JournalError, match=match):
        check_end(value, "yellow")
    assert value == before
    # An origin receipt never passes as a battle end and vice versa.
    with pytest.raises(JournalError, match="complete static origin receipt"):
        check(end_receipt("yellow"), "yellow")


EARLIER = {"arm_frame": 10, "began_frame": 20}  # the capture fixture delivers at frame 100


def test_attribute_joins_a_real_capture_fact_to_its_origin():
    origin = check(receipt("red", "static:route12_snorlax", **EARLIER), "red")
    caught = capture_fact("red", "static:route12_snorlax")
    assert caught["kind"] == "capture" and caught["species_index"] == 0x84 and caught["level"] == 30 and caught["map_id"] == 23
    assert caught["call_frame"] == 100 and origin["frame"] == 20
    assert attribute(caught, origin, variant="red") == "static:route12_snorlax"
    boxed = capture_fact("yellow", "static:ceruleancaveb1f_mewtwo", destination="box")
    mewtwo = check(receipt("yellow", "static:ceruleancaveb1f_mewtwo", **EARLIER), "yellow")
    assert attribute(boxed, mewtwo, variant="yellow") == "static:ceruleancaveb1f_mewtwo"
    same_frame = check(receipt("red", "static:route12_snorlax", arm_frame=99, began_frame=caught["call_frame"]), "red")
    assert attribute(caught, same_frame, variant="red") == "static:route12_snorlax"
    # The default fixture (began at 101) is exactly one frame too late: order is enforced, not assumed.
    with pytest.raises(JournalError, match="before the static battle began"):
        attribute(caught, check(receipt("red", "static:route12_snorlax"), "red"), variant="red")


@pytest.mark.parametrize(
    "fault",
    ["map", "old_man_type", "safari_type", "species", "level", "frame_before", "capture_kind", "capture_shape", "capture_type",
     "origin_kind", "origin_unknown", "origin_excluded", "origin_variant", "variant"],
)
def test_attribute_refuses_captures_that_are_not_the_static_battle(fault):
    origin = check(receipt("red", "static:powerplant_zapdos", **EARLIER), "red")
    caught = capture_fact("red", "static:powerplant_zapdos")
    variant, match = "red", None
    if fault == "map":
        caught, match = capture_fact("red", "static:powerplant_zapdos", map_id=84), "another map"
    elif fault == "old_man_type":
        caught["battle_type"], match = 1, "battle type differs"
    elif fault == "safari_type":
        caught["battle_type"], match = 2, "battle type differs"  # delivering, but not the static's normal battle
    elif fault == "species":
        caught, match = capture_fact("red", "static:powerplant_zapdos", species=0x54), "species/level differ"
    elif fault == "level":
        caught, match = capture_fact("red", "static:powerplant_zapdos", level=49), "species/level differ"
    elif fault == "frame_before":
        late = receipt("red", "static:powerplant_zapdos", arm_frame=caught["call_frame"], began_frame=caught["call_frame"] + 1)
        origin, match = check(late, "red"), "before the static battle began"
    elif fault == "capture_kind":
        caught["kind"], match = "scripted_grant", "capture fact required"
    elif fault == "capture_shape":
        del caught["call_frame"]
        match = "capture fact required"
    elif fault == "capture_type":
        caught, match = ["capture"], "capture fact required"
    elif fault == "origin_kind":
        origin["kind"], match = "capture", "origin fact required"
    elif fault == "origin_unknown":
        origin["static_id"], match = "static:mew", "not a catchable static"
    elif fault == "origin_excluded":
        origin["static_id"], match = "script-battle:ghost-marowak", "not a catchable static"
    elif fault == "origin_variant":
        variant, match = "yellow", None  # Zapdos is the same static in Yellow; the fact itself is title-neutral
        assert attribute(caught, origin, variant=variant) == "static:powerplant_zapdos"
        return
    elif fault == "variant":
        variant, match = "gold", "variant required"
    with pytest.raises(JournalError, match=match):
        attribute(caught, origin, variant=variant)


def test_generated_data_is_reproducible_and_covers_the_census():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        from gen_gen1_acquisition_sources import TITLES
        from gen_gen1_grant_sites import lua
        from gen_gen1_static_sites import LUA, OUTPUT
    finally:
        sys.path.pop(0)
    result = subprocess.run([sys.executable, str(ROOT / "tools/gen_gen1_static_sites.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    stored = json.loads(OUTPUT.read_text(encoding="utf-8"))
    body = {key: value for key, value in stored.items() if key != "sha256"}
    assert stored["sha256"] == DATA["sha256"] == hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert LUA.read_text(encoding="utf-8") == "-- Generated by tools/gen_gen1_static_sites.py from pinned source/ROMs.\nreturn " + lua(stored) + "\n"
    census = json.loads((ROOT / "data/games/gen1_rby/acquisition_sources.json").read_text(encoding="utf-8"))
    layout = json.loads((ROOT / "data/games/gen1_rby/upr_layout.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
    for variant, (_, target) in TITLES.items():
        profile = DATA["titles"][variant]
        rom = (ROOT / lock["clean_roms"][target]["filename"]).read_bytes()
        rows = census["titles"][variant]["sources"]
        statics = [row for row in rows if row["kind"] == "catchable_static"]
        uncatchable = [row for row in rows if row["kind"] == "uncatchable_script_battle"]
        assert {row["source_id"] for row in statics} == set(profile["sites"]) and len(statics) == 14
        assert {row["source_id"] for row in uncatchable} == set(profile["excluded"])
        for row in uncatchable:
            assert isinstance(profile["excluded"][row["source_id"]]["reason"], str)
        for row in statics:
            site = profile["sites"][row["source_id"]]
            assert site["map_id"] == row["map_id"] and site["species"]["clean"] == [row["species_index"]]
            assert site["level"]["values"] == [row.get("level", 30)] and 1 <= site["level"]["values"][0] <= 100
            assert site["kind"] == ("script" if "entry" in row else "object")
            if site["kind"] == "object":
                assert site["object_index"] == row["object_index"] and site["arm"] == profile["object_arm"]
                assert site["species"]["rom_offsets"] == [row["species_rom_offset"]] and site["level"]["rom_offsets"] == [row["level_rom_offset"]]
            else:
                assert site["arm"]["address"] == row["entry"]["address"] + 10 and site["species"]["rom_offsets"] == [row["opponent_species_rom_offset"]]
            # ROM-byte-verified: every anchor still reads the pinned clean bytes.
            for anchor in (site["arm"], site["writes"], profile["began"], profile["began"]["prelude"], profile["object_arm"]["routine"],
                           profile["battle_end"], profile["battle_end"]["reset"], profile["battle_end"]["call"]):
                assert rom[anchor["rom_offset"] : anchor["rom_offset"] + len(anchor["expected_hex"]) // 2].hex().upper() == anchor["expected_hex"]
            # UPR: the species byte belongs to exactly one non-ghost static record whose level byte is this site's; levels are never species.
            offsets = site["species"]["rom_offsets"]
            hits = [rec for rec in layout["profiles"][variant]["statics"] if set(offsets) & set(rec["Species"])]
            assert len(hits) == 1 and not hits[0]["ghost"] and hits[0]["Level"] == site["level"]["rom_offsets"]
            assert not any(set(site["level"]["rom_offsets"]) & set(rec["Species"]) for rec in layout["profiles"][variant]["statics"])
        ghost = [rec for rec in layout["profiles"][variant]["statics"] if rec["ghost"]]
        assert len(ghost) == 1 and profile["excluded"]["script-battle:ghost-marowak"]["opponent_species_rom_offset"] in ghost[0]["Species"]
        assert profile["began"]["prelude"]["expected_hex"].startswith("3E01EA") and profile["object_arm"]["expected_hex"] == "C9"
        assert profile["origin_battle_type"] == 0 and profile["battle_types"]["BATTLE_TYPE_NORMAL"] == 0
        # battle_end: EndOfBattle's entry `ld a, [wLinkState] ; cp LINK_STATE_BATTLING`; its `.resetVariables` clears wIsInBattle
        # (`xor a` then six `ld [..], a`); the ROM's only `callfar EndOfBattle` directly follows `call(far) StartBattle`.
        end = profile["battle_end"]
        link = profile["addresses"]["wLinkState"].to_bytes(2, "little").hex().upper()
        assert end["symbol"] == "EndOfBattle" and end["expected_hex"] == "FA" + link + "FE04"
        reset = end["reset"]["expected_hex"]
        assert reset.startswith("AFEA") and len(reset) == 38 and reset.count("EA") >= 6
        assert reset[14:16] == "EA" and reset[16:20] == profile["addresses"]["wIsInBattle"].to_bytes(2, "little").hex().upper()
        entry = end["address"].to_bytes(2, "little").hex().upper()
        callfar = "21" + entry + "0604CD" + ("843E" if variant == "yellow" else "D635")  # ld hl, EndOfBattle ; ld b, 4 ; call Bankswitch
        assert end["call"]["expected_hex"].endswith(callfar) and rom.count(bytes.fromhex(callfar)) == 1  # the ROM's only call
        assert end["call"]["expected_hex"].startswith("CD" if variant != "yellow" else "21")  # call StartBattle / callfar StartBattle
        assert profile["battle_results"] == {"win": 0, "lose": 1, "draw": 2} and profile["trainer_battle_flag"] == 2
