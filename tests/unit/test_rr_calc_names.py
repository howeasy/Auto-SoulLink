"""
Every Radical Red name the server can hand the damage calc must be a calc name.

The calc (calc/calc/src/data/*.ts) matches species/ability/item/move names
exactly, so an RR ROM spelling ("Silvally (Fight)", "WeaknessPol.", "Cotton
Cloud", "Crafty Guard") silently computes the wrong damage. The server maps
names through data/games/gen3_frlge/calc_names.json (Gen3Adapter.calc_name);
this suite pins that every name it can emit resolves — directly, through the
table, or via UNRESOLVABLE below with a reason — so a new RR name fails here.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server import pokemon_data as pd  # noqa: E402
from server.adapters.gen3_frlge import _RR_ITEMS, Gen3Adapter  # noqa: E402
from server.data.moves.gen3_rr import MOVE_NAMES  # noqa: E402
from server.server import _build_mon_entry, _calc_trainer_label  # noqa: E402
from tools.gen_rr_priority_trainers import calc_name_sets, canonicalise_parties  # noqa: E402

_DATA = ROOT / "data" / "games" / "gen3_frlge"
CALC = calc_name_sets()
RR = Gen3Adapter(is_rr=True)

_NO_BATTLE_EFFECT = ("no in-battle damage effect (key item, medicine, mail, vitamin, valuable, "
                     "evolution/form item); the calc has no entry and needs none")
# kind -> {name: reason}. Every entry must be emitted by the server AND still unresolvable.
UNRESOLVABLE: dict[str, dict[str, str]] = {
    "species": {
        "Palkia (Primal)": "RR-custom form; the calc has no Palkia-Primal",
    },
    "ability": {
        "As One": "two RR ability ids share this name; the calc splits it by rider "
                  "(As One (Glastrier)/(Spectrier)), which the name alone can't pick "
                  "(the roster tool resolves it per species)",
    },
    "move": {
        "-": "empty move slot",
        "Placeholder": "unused ROM move slot",
        "Leech Fang": "RR-custom move the calc doesn't implement",
        "Metal Bash": "RR-custom move the calc doesn't implement",
        **{f"Z-Move {i}": "generic ROM label for a Z-Move slot; never in a moveset"
           for i in range(1, 54)},
    },
    "item": {
        "????????": "empty ROM item slot",
        "Free Space22": "unused ROM item slot",
        "Applite": "one RR stone for Appletun-Mega and Flapple-Mega; the calc splits it "
                   "(Appletunite/Flapplite), which the name alone can't pick "
                   "(the roster tool resolves it per species)",
        "Grimmsnite": "RR-custom Mega Stone; the calc has no Grimmsnarl-Mega",
        "Eter.Max Orb": "RR-custom form item the calc doesn't model",
        **{f"TM{i:02d}": _NO_BATTLE_EFFECT for i in range(1, 121)},
        **{f"HM{i:02d}": _NO_BATTLE_EFFECT for i in range(1, 9)},
        **dict.fromkeys((
            "Ability Pill", "Acro Bike", "Amulet Coin", "Antidote", "Aurora Ticket",
            "Awakening", "BalmMushroom", "Basement Key", "Bead Mail", "Berry Pouch",
            "Bicycle", "Big Malasada", "Big Mushroom", "Big Pearl", "Bike Voucher",
            "Bird Fossil", "Black Flute", "Blue Flute", "Blue Scarf", "Blue Shard",
            "Burn Heal", "Calcium", "Carbos", "Card Key", "Casteliacone", "Cleanse Tag",
            "Clever Wing", "Coin Case", "Comet Shard", "Contest Pass", "DNA Splicers",
            "Dark Stone", "Devon Goods", "Devon Scope", "Dino Fossil", "Dire Hit",
            "Drake Fossil", "Dream Mail", "Dream Patch", "Dynamax Band", "Elixir",
            "Energy Root", "EnergyPowder", "Eon Ticket", "Escape Rope", "Ether",
            "Everstone", "Exp. Share", "Fab Mail", "Fish Fossil", "Fluffy Tail",
            "Fresh Water", "Full Heal", "Full Restore", "G.Bottle Cap", "Galar Crown",
            "Genius Wing", "Glitter Mail", "Go-Goggles", "Gold Teeth", "Good Rod",
            "Gracidea", "Green Scarf", "Green Shard", "Guard Spec.", "HP Up",
            "Harbor Mail", "Heal Powder", "Health Wing", "Heart Scale", "Honey",
            "Hyper Potion", "Ice Heal", "Iron", "Itemfinder", "Lava Cookie", "Lemonade",
            "Letter", "Lift Key", "Light Stone", "Link Cable", "Locater", "Luck Incense",
            "Lucky Egg", "Mach Bike", "Magma Stone", "Max Elixir", "Max Ether",
            "Max Potion", "Max Repel", "Max Revive", "Mech Mail", "Medicine", "Mega Ring",
            "Meteorite", "Moomoo Milk", "Moon Flute", "Muscle Wing", "Mystic Ticket",
            "N-Solarizer", "Necrozmizer", "Nugget", "Oak’s Parcel", "Odd Keystone",
            "Old Gateau", "Old Rod", "Orange Mail", "Oval Charm", "PP Max", "PP Up",
            "Paralyz Heal", "Pearl", "Pearl String", "Pink Nectar", "Pink Scarf",
            "Poké Ball", "Poké Doll", "Poké Flute", "Poké Rider",
            "Potion", "Pretty Wing", "PrisonBottle", "Protein", "Pure Incense",
            "PurpleNectar", "RM. 1 Key", "RM. 2 Key", "RM. 4 Key", "RM. 6 Key",
            "RageCandyBar", "Rainbow Pass", "Rainbow Wing", "Rare Candy", "Red Flute",
            "Red Nectar", "Red Scarf", "Red Shard", "Relic Crown", "Repel", "Resist Wing",
            "Retro Mail", "Reveal Glass", "Revival Herb", "Revive", "Ruby", "S.S. Ticket",
            "Sacred Ash", "Sapphire", "Scanner", "Secret Key", "Shadow Mail",
            "ShalourSable", "Shiny Charm", "Shoal Salt", "Shoal Shell", "Silph Scope",
            "Silver Wing", "Smoke Ball", "Soda Pop", "Soot Sack", "Soothe Bell",
            "Star Piece", "Stardust", "Stat Scanner", "Storage Key", "Sun Flute",
            "Super Potion", "Super Repel", "Super Rod", "Swift Wing", "TM Case", "Tea",
            "Teachy TV", "Teal Mask", "TinyMushroom", "Town Map", "Tri-Pass",
            "Tropic Mail", "Wailmer Pail", "Wave Mail", "White Flute", "Wish Piece",
            "Wood Mail", "X Accuracy", "X Attack", "X Defend", "X Sp. Atk", "X Speed",
            "Yellow Flute", "Yellow Scarf", "Yellow Shard", "YellowNectar",
            "Z-Power Ring", "Zinc"), _NO_BATTLE_EFFECT),
    },
}


def _emitted() -> dict[str, set[str]]:
    """Every name the RR server can put in the calc DTO, per kind."""
    species = json.loads((_DATA / "rr_species.json").read_text(encoding="utf-8"))
    return {
        "species": {RR.species_name(int(k)) for k in species if k.isdigit()} | set(species.values()),
        "ability": set(pd.RR_ABILITY_NAMES.values()) | set(pd.CFRU_ABILITY_NAME_OVERRIDES.values()),
        "item": set(_RR_ITEMS.values()),
        "move": set(MOVE_NAMES.values()),
    }


EMITTED = _emitted()
KINDS = ("species", "ability", "item", "move")


def test_calc_parse_sees_known_names():
    """Known-positive control: the .ts parse finds names of every shape."""
    for kind, name in (("species", "Silvally-Fighting"), ("species", "Farfetch’d"),
                       ("species", "Flabébé"), ("item", "Utility Umbrella"),
                       ("item", "Burnt Seed"), ("item", "Charizardite X"),
                       ("ability", "Cotton Down"), ("move", "Crafty Shield"),
                       ("move", "King's Shield")):
        assert name in CALC[kind], (kind, name)


@pytest.mark.parametrize("kind", KINDS)
def test_every_emitted_rr_name_resolves(kind):
    bad = sorted(n for n in EMITTED[kind]
                 if RR.calc_name(kind, n) not in CALC[kind] and n not in UNRESOLVABLE[kind])
    assert not bad, (f"RR {kind} names the calc doesn't know — map them in "
                     f"data/games/gen3_frlge/calc_names.json or allowlist with a reason: {bad}")


@pytest.mark.parametrize("kind", KINDS)
def test_allowlist_is_live(kind):
    """Allowlisted names must still be emitted and still unresolvable."""
    stale = sorted(n for n in UNRESOLVABLE[kind]
                   if n not in EMITTED[kind] or RR.calc_name(kind, n) in CALC[kind])
    assert not stale, stale


@pytest.mark.parametrize("kind", KINDS)
def test_table_targets_are_calc_names(kind):
    table = json.loads((_DATA / "calc_names.json").read_text(encoding="utf-8"))[kind]
    assert table
    assert not {k: v for k, v in table.items() if v not in CALC[kind]}


def test_adapter_maps_rr_and_leaves_vanilla_alone():
    assert RR.calc_name("species", "Silvally (Fight)") == "Silvally-Fighting"
    assert RR.calc_name("species", "Tauros P (Water)") == "Tauros-Paldea-Aqua"
    assert RR.calc_name("species", "Brutebonnet") == "Brute Bonnet"
    assert RR.calc_name("ability", "Cotton Cloud") == "Cotton Down"
    assert RR.calc_name("item", "WeaknessPol.") == "Weakness Policy"
    assert RR.calc_name("move", "Crafty Guard") == "Crafty Shield"
    assert RR.calc_name("move", "Tackle") == "Tackle"
    assert Gen3Adapter(is_rr=False).calc_name("species", "Silvally (Fight)") == "Silvally (Fight)"


def test_calc_dto_carries_calc_names():
    ids = {v: k for k, v in pd.SPECIES_NAMES.items()}
    item = {v: k for k, v in _RR_ITEMS.items()}["WeaknessPol."]
    move = {v: k for k, v in MOVE_NAMES.items()}["Crafty Guard"]
    e = _build_mon_entry("0:0", {"species_id": ids["Silvally (Fight)"], "held_item_id": item,
                                 "ability_name": "Cotton Cloud", "moves": [move, "Drain Kiss"],
                                 "level": 50, "hp": 1, "maxHP": 1}, RR)
    assert (e["species_name"], e["item_name"], e["ability_name"], e["moves"]) == (
        "Silvally-Fighting", "Weakness Policy", "Cotton Down", ["Crafty Shield", "Draining Kiss"])
    assert e["showdown_paste"].startswith("Silvally-Fighting @ Weakness Policy\nAbility: Cotton Down")


def test_rival_trainer_id_resolves_to_calc_set_key():
    """RR's roster maps runtime trainer ids to the calc's setdex keys; the key reaches the
    bridge only when the roster party matches the live enemy."""
    brief = RR.trainer_brief(426)
    assert brief["calc_label"] == "Rival Blue Set 1"
    enemy = [{"species_name": m["species"]} for m in brief["party"]]
    assert _calc_trainer_label(brief, enemy) == "Rival Blue"
    assert _calc_trainer_label(RR.trainer_brief(739), [{"species_name": "Staraptor"}]) == "Rival Blue"
    assert _calc_trainer_label(brief, [{"species_name": "Pikachu"}]) == ""   # swapped team
    assert _calc_trainer_label(None, enemy) == ""


def test_roster_and_setdex_supplement_are_canonical():
    """The generated roster + calc supplement only hold calc names."""
    roster = json.loads((_DATA / "rr_priority_trainers.json").read_text(encoding="utf-8"))
    js = (ROOT / "calc/src/js/data/sets/slink_priority.js").read_text(encoding="utf-8")
    supp = json.loads(re.search(r"var ADD = (.*?);\s*\n\s*if \(typeof window", js, re.S).group(1))
    bad = []
    for sets in [[m for p in roster["parties"].values() for m in p["party"]],
                 [dict(s, species=sp) for sp, by in supp.items() for s in by.values()]]:
        for m in sets:
            for kind, vals in (("species", [m["species"]]), ("ability", [m.get("ability")]),
                               ("item", [m.get("item")]), ("move", m.get("moves") or [])):
                bad += [(kind, v) for v in vals if v and v not in CALC[kind]]
    assert not bad, sorted(set(bad))


def test_roster_tool_rejects_unknown_names():
    parties = {"1": {"name": "X", "party": [
        {"species": "Charizard-MegaY", "ability": "Blaze\nDrought", "item": "Weakness Pol.",
         "moves": ["Cease. Edge", "-"]},
        {"species": "Notamon", "ability": "", "item": "", "moves": ["Notamove"]}]}}
    errors = canonicalise_parties(parties)
    assert parties["1"]["party"][0] == {"species": "Charizard-Mega-Y", "ability": "Drought",
                                        "item": "Weakness Policy", "moves": ["Ceaseless Edge"]}
    assert errors == ["trainer 1 (X): species 'Notamon'", "trainer 1 (X): move 'Notamove'"]
