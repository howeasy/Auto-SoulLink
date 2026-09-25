#!/usr/bin/env python3
"""
gen_gen3_emerald_statics.py -- build data/games/gen3_emerald/statics.json.

Gift / fixed-gift / choice-gift / daycare / static-encounter facts for vanilla
Emerald, hand-curated from pret/pokeemerald source (scripts + flags) -- see
the "source" field on every entry for the exact file:line. Unlike area_map
(struct/table data best read programmatically), these are narrative-script
facts: each one is a `givemon`/`giveegg`/`setwildbattle`/`seteventmon` call
gated by a specific FLAG_*, so a hand-curated table with citations is the
fact, not a shortcut around one (PLAN.md TEMPLATES.md T1/T4 citation style).

Fields per entry:
  species          canonical SPECIES_* name(s); a list for choice gifts
  map              "mapGroup:mapNum" of the map.json actually containing the
                    givemon/setwildbattle/seteventmon call (from map_groups.json,
                    same derivation as gen_area_map.py generate_emerald())
  flag             the FLAG_* that gates re-triggering / marks it done
  kind             gift | fixed_gift | choice_gift | static | daycare
  bypass_clauses   PLAN.md section 0 default: fixed single-species gifts
                    (Beldum, Wynaut egg, Castform, Mew, Deoxys) bypass Soul
                    Link clauses; choice gifts (starter, fossil, Eon) do not;
                    static legendary encounters do not either (not in the
                    named bypass list)
  level            level given/encountered at, where fixed
  source           pret/pokeemerald file:line (commit c65e93f2)

Run: cd SLink && python tools/gen_gen3_emerald_statics.py
"""

import json
import os

from gen_area_map import _find_pret_checkout

PRET_COMMIT = "c65e93f20a5275ab03b07d6f6411096a82a60ffd"


def _map_key_index():
    """folder name -> "mapGroup:mapNum", same order pret's mapjson.cpp assigns MAP_xxx ids."""
    pret = _find_pret_checkout("pokeemerald")
    with open(os.path.join(pret, "data", "maps", "map_groups.json"), encoding="utf-8") as f:
        groups_data = json.load(f)
    key_of_folder = {}
    for group_idx, group_name in enumerate(groups_data["group_order"]):
        for map_idx, folder in enumerate(groups_data[group_name]):
            key_of_folder[folder] = f"{group_idx}:{map_idx}"
    return key_of_folder


def generate_statics():
    key_of = _map_key_index()

    def m(folder):
        return key_of[folder]

    entries = [
        # -- Choice gifts (do not bypass clauses) -----------------------------
        {
            "id": "starter",
            "species": ["SPECIES_TREECKO", "SPECIES_TORCHIC", "SPECIES_MUDKIP"],
            "map": m("Route101"),
            "flag": "FLAG_SYS_POKEMON_GET",
            "kind": "choice_gift",
            "bypass_clauses": False,
            "level": 5,
            "source": "data/maps/Route101/scripts.inc:218-241 (Route101_EventScript_BirchsBag, "
                      "`special ChooseStarter`); species list src/starter_choose.c:113-119",
        },
        {
            "id": "fossil",
            "species": ["SPECIES_LILEEP", "SPECIES_ANORITH"],
            "map": m("RustboroCity_DevonCorp_2F"),
            "flag": "FLAG_RECEIVED_REVIVED_FOSSIL_MON",
            "kind": "choice_gift",
            "bypass_clauses": False,
            "level": 20,
            "source": "data/maps/RustboroCity_DevonCorp_2F/scripts.inc:145-146,185,190-191,230 "
                      "(givemon SPECIES_LILEEP/SPECIES_ANORITH, 20); which fossil item is available "
                      "to revive is chosen earlier at data/maps/MirageTower_4F/scripts.inc:9,29 "
                      "(giveitem ITEM_ROOT_FOSSIL / ITEM_CLAW_FOSSIL, FLAG_CHOSE_ROOT_FOSSIL / "
                      "FLAG_CHOSE_CLAW_FOSSIL)",
        },
        # Eon ticket / Latios-vs-Latias roamer choice: the roamer species is picked
        # by player gender at game start, not a menu choice in the field -- see the
        # "roaming" note below. No separate Eon-ticket static in vanilla Emerald
        # (Southern Island is expansion/event-only); recorded as a limit, not a card.

        # -- Fixed single-species gifts (bypass clauses per PLAN.md section 0) --
        {
            "id": "beldum",
            "species": "SPECIES_BELDUM",
            "map": m("MossdeepCity_StevensHouse"),
            "flag": "FLAG_RECEIVED_BELDUM",
            "kind": "fixed_gift",
            "bypass_clauses": True,
            "level": 5,
            "source": "data/maps/MossdeepCity_StevensHouse/scripts.inc:85-86,126 "
                      "(givemon SPECIES_BELDUM, 5; FLAG_RECEIVED_BELDUM)",
        },
        {
            "id": "wynaut_egg",
            "species": "SPECIES_WYNAUT",
            "map": m("LavaridgeTown"),
            "flag": "FLAG_RECEIVED_LAVARIDGE_EGG",
            "kind": "fixed_gift",
            "bypass_clauses": True,
            "level": "egg",
            "source": "data/maps/LavaridgeTown/scripts.inc:232-245 "
                      "(giveegg SPECIES_WYNAUT; FLAG_RECEIVED_LAVARIDGE_EGG)",
        },
        {
            "id": "castform",
            "species": "SPECIES_CASTFORM",
            "map": m("Route119_WeatherInstitute_2F"),
            "flag": "FLAG_RECEIVED_CASTFORM",
            "kind": "fixed_gift",
            "bypass_clauses": True,
            "level": 25,
            "source": "data/maps/Route119_WeatherInstitute_2F/scripts.inc:84-85,123 "
                      "(givemon SPECIES_CASTFORM, 25, ITEM_MYSTIC_WATER; FLAG_RECEIVED_CASTFORM); "
                      "form (Sunny/Rainy/Snowy/Normal) is weather-derived at runtime, not fixed at gift time",
        },
        {
            "id": "mew",
            "species": "SPECIES_MEW",
            "map": m("FarawayIsland_Interior"),
            "flag": "FLAG_CAUGHT_MEW",
            "kind": "static",
            "bypass_clauses": True,
            "level": 30,
            "source": "data/maps/FarawayIsland_Interior/scripts.inc:38-43,122,130,139 "
                      "(seteventmon SPECIES_MEW, 30; FLAG_CAUGHT_MEW / FLAG_DEFEATED_MEW); "
                      "event-only map (Faraway Island), not reachable without an external distribution",
        },
        {
            "id": "deoxys",
            "species": "SPECIES_DEOXYS",
            "map": m("BirthIsland_Exterior"),
            "flag": "FLAG_DEFEATED_DEOXYS",
            "kind": "static",
            "bypass_clauses": True,
            "level": 30,
            "source": "data/maps/BirthIsland_Exterior/scripts.inc:16-26,79,83 "
                      "(seteventmon SPECIES_DEOXYS, 30; FLAG_BATTLED_DEOXYS / FLAG_DEFEATED_DEOXYS); "
                      "event-only map (Birth Island), not reachable without an external distribution",
        },

        # -- Daycare (not a fixed species -- does not bypass clauses) -----------
        {
            "id": "route_117_daycare_egg",
            "species": None,
            "map": m("Route117_PokemonDayCare"),
            "flag": "FLAG_PENDING_DAYCARE_EGG",
            "kind": "daycare",
            "bypass_clauses": False,
            "level": "egg",
            "source": "data/scripts/day_care.inc:1-36 (Route117_EventScript_DaycareReceiveEgg, "
                      "`special GiveEggFromDaycare`); species depends on the two parents left at "
                      "the Route 117 Day Care, not fixed",
        },

        # -- Static legendary / rare encounters (not in the bypass list) --------
        {
            "id": "kyogre",
            "species": "SPECIES_KYOGRE",
            "map": m("MarineCave_End"),
            "flag": "FLAG_DEFEATED_KYOGRE",
            "kind": "static",
            "bypass_clauses": False,
            "level": 70,
            "source": "data/maps/MarineCave_End/scripts.inc:17-57 (setwildbattle SPECIES_KYOGRE, 70; "
                      "FLAG_DEFEATED_KYOGRE); post-story Marine Cave, not the Sootopolis story cutscene",
        },
        {
            "id": "groudon",
            "species": "SPECIES_GROUDON",
            "map": m("TerraCave_End"),
            "flag": "FLAG_DEFEATED_GROUDON",
            "kind": "static",
            "bypass_clauses": False,
            "level": 70,
            "source": "data/maps/TerraCave_End/scripts.inc:17-57 (setwildbattle SPECIES_GROUDON, 70; "
                      "FLAG_DEFEATED_GROUDON); post-story Terra Cave, not the Sootopolis story cutscene",
        },
        {
            "id": "rayquaza",
            "species": "SPECIES_RAYQUAZA",
            "map": m("SkyPillar_Top"),
            "flag": "FLAG_DEFEATED_RAYQUAZA",
            "kind": "static",
            "bypass_clauses": False,
            "level": 70,
            "source": "data/maps/SkyPillar_Top/scripts.inc:28-67 (setwildbattle SPECIES_RAYQUAZA, 70; "
                      "FLAG_DEFEATED_RAYQUAZA)",
        },
        {
            "id": "regirock",
            "species": "SPECIES_REGIROCK",
            "map": m("DesertRuins"),
            "flag": "FLAG_DEFEATED_REGIROCK",
            "kind": "static",
            "bypass_clauses": False,
            "level": 40,
            "source": "data/maps/DesertRuins/scripts.inc:18-64 (setwildbattle SPECIES_REGIROCK, 40; "
                      "FLAG_DEFEATED_REGIROCK; puzzle gate FLAG_SYS_REGIROCK_PUZZLE_COMPLETED)",
        },
        {
            "id": "regice",
            "species": "SPECIES_REGICE",
            "map": m("IslandCave"),
            "flag": "FLAG_DEFEATED_REGICE",
            "kind": "static",
            "bypass_clauses": False,
            "level": 40,
            "source": "data/maps/IslandCave/scripts.inc:18-97 (setwildbattle SPECIES_REGICE, 40; "
                      "FLAG_DEFEATED_REGICE; puzzle gate FLAG_SYS_BRAILLE_REGICE_COMPLETED)",
        },
        {
            "id": "registeel",
            "species": "SPECIES_REGISTEEL",
            "map": m("AncientTomb"),
            "flag": "FLAG_DEFEATED_REGISTEEL",
            "kind": "static",
            "bypass_clauses": False,
            "level": 40,
            "source": "data/maps/AncientTomb/scripts.inc:19-64 (setwildbattle SPECIES_REGISTEEL, 40; "
                      "FLAG_DEFEATED_REGISTEEL; puzzle gate FLAG_SYS_REGISTEEL_PUZZLE_COMPLETED)",
        },
        {
            "id": "lugia",
            "species": "SPECIES_LUGIA",
            "map": m("NavelRock_Bottom"),
            "flag": "FLAG_DEFEATED_LUGIA",
            "kind": "static",
            "bypass_clauses": False,
            "level": 70,
            "source": "data/maps/NavelRock_Bottom/scripts.inc:7-54 (seteventmon SPECIES_LUGIA, 70; "
                      "FLAG_CAUGHT_LUGIA / FLAG_DEFEATED_LUGIA); event-only map (Navel Rock)",
        },
        {
            "id": "ho_oh",
            "species": "SPECIES_HO_OH",
            "map": m("NavelRock_Top"),
            "flag": "FLAG_DEFEATED_HO_OH",
            "kind": "static",
            "bypass_clauses": False,
            "level": 70,
            "source": "data/maps/NavelRock_Top/scripts.inc:7-58 (seteventmon SPECIES_HO_OH, 70; "
                      "FLAG_CAUGHT_HO_OH / FLAG_DEFEATED_HO_OH); event-only map (Navel Rock)",
        },
        {
            "id": "voltorb_electrode_new_mauville",
            "species": "SPECIES_VOLTORB",
            "map": m("NewMauville_Inside"),
            "flag": None,
            "kind": "static",
            "bypass_clauses": False,
            "level": 25,
            "source": "data/maps/NewMauville_Inside/scripts.inc:179,203,227 "
                      "(setwildbattle SPECIES_VOLTORB, 25 x3; New Mauville also has ordinary "
                      "Voltorb/Electrode wild encounters via wild_encounters.json land_mons, "
                      "not part of this static set); no per-encounter FLAG_*, these are repeat "
                      "scripted encounters on the generator floor, not one-time gifts",
        },
        {
            "id": "kecleon_route_120",
            "species": "SPECIES_KECLEON",
            "map": m("Route120"),
            "flag": "FLAG_HIDE_ROUTE_120_KECLEON_BRIDGE",
            "kind": "static",
            "bypass_clauses": False,
            "level": 30,
            "source": "data/maps/Route120/scripts.inc:175-197 (setwildbattle SPECIES_KECLEON, 30); "
                      "object event flag data/maps/Route120/map.json object_events "
                      "LOCALID_BRIDGE_KECLEON = FLAG_HIDE_ROUTE_120_KECLEON_BRIDGE",
        },
        {
            "id": "kecleon_fortree_city",
            "species": "SPECIES_KECLEON",
            "map": m("FortreeCity"),
            "flag": "FLAG_HIDE_FORTREE_CITY_KECLEON",
            "kind": "static",
            "bypass_clauses": False,
            "level": "†UNVERIFIED",
            "source": "data/maps/FortreeCity/scripts.inc:76 (SPECIES_KECLEON cry); object event flag "
                      "data/maps/FortreeCity/map.json FLAG_HIDE_FORTREE_CITY_KECLEON; level not traced "
                      "in this pass (no local setwildbattle call found -- shared/common script)",
        },
        {
            "id": "kecleon_lilycove_house1",
            "species": "SPECIES_KECLEON",
            "map": m("LilycoveCity_House1"),
            "flag": None,
            "kind": "static",
            "bypass_clauses": False,
            "level": "†UNVERIFIED",
            "source": "data/maps/LilycoveCity_House1/scripts.inc:12 (SPECIES_KECLEON cry); object "
                      "event flag not traced in this pass (no local setwildbattle call found)",
        },
        {
            "id": "kecleon_sootopolis_house1",
            "species": "SPECIES_KECLEON",
            "map": m("SootopolisCity_House1"),
            "flag": None,
            "kind": "static",
            "bypass_clauses": False,
            "level": "†UNVERIFIED",
            "source": "data/maps/SootopolisCity_House1/scripts.inc:25 (SPECIES_KECLEON cry); object "
                      "event flag not traced in this pass (no local setwildbattle call found)",
        },

        # -- Roaming (no fixed map -- recorded as a limit, not a normal static) --
        {
            "id": "latias_latios_roamer",
            "species": ["SPECIES_LATIAS", "SPECIES_LATIOS"],
            "map": None,
            "flag": None,
            "kind": "static",
            "bypass_clauses": False,
            "level": 40,
            "source": "src/roamer.c:39-58 (sRoamerLocations, roams Route 104-134 and connecting "
                      "towns), :64-97 (CreateInitialRoamerMon: Latias if player is male, Latios if "
                      "female -- src/roamer.c:84-92 with gSpecialVar_0x8004 from the player-gender "
                      "check at data/scripts/players_house.inc:472 `special InitRoamer`); tracked in "
                      "the ROAMER save-block struct, not a FLAG_*; RECORDED LIMIT: no single "
                      "mapGroup:mapNum -- a roaming encounter cannot be expressed as one static row",
        },
    ]

    # RECORDED LIMITS (verified absent / out of scope for this card; not written as rows):
    #   - Unown: no SPECIES_UNOWN reference anywhere in src/data/wild_encounters.json or any
    #     data/maps/*/scripts.inc at pret/pokeemerald c65e93f2 -- not obtainable in vanilla Emerald.
    #   - Sudowoodo: only data/maps/BattleFrontier_OutsideEast/scripts.inc -- Battle Frontier is
    #     out of scope for the Emerald RC (PLAN.md section 0 "Scope (Emerald RC)").
    #   - Eon Ticket / Southern Island (Latias-or-Latios *choice* gift, as opposed to the roamer
    #     above): event-distribution only in vanilla Emerald, no in-game trigger; not a card here.

    out = {
        "_source": f"pret/pokeemerald @ {PRET_COMMIT}",
        "_schema": "gen3-emerald-statics-v1",
        "entries": entries,
    }

    os.makedirs(os.path.join("data", "games", "gen3_emerald"), exist_ok=True)
    with open(os.path.join("data", "games", "gen3_emerald", "statics.json"), "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    print(f"Generated {len(entries)} static/gift entries")
    print("  -> data/games/gen3_emerald/statics.json")
    kinds = {}
    for e in entries:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    for k, c in sorted(kinds.items()):
        print(f"  {k}: {c}")


if __name__ == "__main__":
    generate_statics()
