"""
Every non-RR name the server can hand the damage calc must be a calc name for that
generation.

The calc (calc/calc/src/data/*.ts) matches species/ability/item/move names exactly per
generation -- Gen 1's RBY table, Gen 2's GSC extension, Gen 3's ADV extension -- and a game
ROM's own spelling ("BubbleBeam", "Faint Attack", "TwistedSpoon") silently computes the
wrong damage if it doesn't match. gen1_rby.py and gen3_frlge.py (vanilla path) map names
through data/games/gen1_rby/calc_names.json and data/games/gen3_frlge/calc_names_vanilla.json
(Gen1Adapter.calc_name / Gen3Adapter.calc_name); this suite pins that every name each
adapter can emit for a real in-game id resolves -- directly, or through the table -- or has
no normalised match in the calc at all (a non-battle item, a badge, an empty move slot: the
bridge leaves those blank). See tools/gen_rr_priority_trainers.calc_name_sets(gen) and
tests/unit/test_rr_calc_names.py, whose shape this mirrors for RR/Gen 9.
"""

import jsonimport reimport sysfrom pathlib import PathROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.adapters import gen1_codec  # noqa: E402from server.adapters.gen1_purergb import Gen1PureRGBAdapter  # noqa: E402from server.adapters.gen1_rby import Gen1Adapter  # noqa: E402from server.adapters.gen3_frlge import Gen3Adapter  # noqa: E402from server.data.items.gen3_vanilla import ITEM_NAMES as FRLG_ITEM_NAMES  # noqa: E402from server.data.moves.gen3_vanilla import MOVE_NAMES as GEN3_VANILLA_MOVE_NAMES  # noqa: E402from server.pokemon_data import NATIONAL_SPECIES_NAMES, species_name  # noqa: E402from server.server import _build_mon_entry  # noqa: E402from tools.gen_rr_priority_trainers import calc_name_sets  # noqa: E402CALC_GEN1 = calc_name_sets(1)
CALC_GEN3 = calc_name_sets(3)

GEN1_MOVES = {int(row["id"]): row["name"] for row in
              json.loads((ROOT / "data/games/gen1_rby/moves.json")
                        .read_text(encoding="utf-8"))["moves"]}
PURERGB_MOVES = {int(row["id"]): row["name"] for row in
                 json.loads((ROOT / "data/games/gen1_purergb/moves.json")
                           .read_text(encoding="utf-8"))["moves"]}

RBY = Gen1Adapter(rom_type="red")
PURERGB = Gen1PureRGBAdapter(rom_type="PureRed")
VANILLA = Gen3Adapter(is_rr=False)
RR = Gen3Adapter(is_rr=True)


def _norm(s: str) -> str:
    """normalise = lowercase, strip non-alphanumerics, ♀→f, ♂→m."""
    s = (s or "").lower().replace("♀", "f").replace("♂", "m")
    return re.sub(r"[^a-z0-9]", "", s)


def _assert_resolves(adapter, kind, calc_set, names, label):
    """Every name the adapter can emit for a real in-game id must either resolve exactly
    through calc_name, or have no normalised match in the calc at all (left unmapped:
    the bridge sends it blank)."""
    calc_norm = {_norm(n) for n in calc_set}
    bad = sorted(n for n in names
                 if adapter.calc_name(kind, n) not in calc_set and _norm(n) in calc_norm)
    assert not bad, (f"{label} {kind}: names the calc knows a close match for, but the "
                     f"table doesn't resolve: {bad}")


# ── Gen 1 (Red/Blue/Yellow) ───────────────────────────────────────────────────

def test_gen1_rby_species_resolve():
    names = {species_name(d, False) for d in range(1, 152)}  # real National Dex 1-151
    _assert_resolves(RBY, "species", CALC_GEN1["species"], names, "gen1_rby")


def test_gen1_rby_moves_resolve():
    _assert_resolves(RBY, "move", CALC_GEN1["move"], set(GEN1_MOVES.values()), "gen1_rby")


def test_gen1_rby_has_no_held_items_or_abilities_in_the_calc():
    """Gen 1 has no held-item mechanic and no abilities; the calc's own Gen 1 tables for
    both are empty, so every bag item name the adapter could emit is category (b): no
    normalised match at all, and the bridge leaves the field blank."""
    assert CALC_GEN1["item"] == set()
    assert CALC_GEN1["ability"] == set()
    assert not RBY.supports_abilities()


# ── pureRGB (Gen1PureRGBAdapter inherits gen1_rby's calc_names.json table) ────

def test_purergb_species_resolve():
    names = {PURERGB.species_name(sid) for sid in PURERGB._species}
    _assert_resolves(PURERGB, "species", CALC_GEN1["species"], names, "pureRGB")


def test_purergb_moves_resolve():
    _assert_resolves(PURERGB, "move", CALC_GEN1["move"], set(PURERGB_MOVES.values()), "pureRGB")


# ── Vanilla Gen 3 (FireRed/LeafGreen/Emerald) ─────────────────────────────────

def test_vanilla_gen3_species_resolve():
    names = {NATIONAL_SPECIES_NAMES[d] for d in range(1, 387) if d in NATIONAL_SPECIES_NAMES}
    _assert_resolves(VANILLA, "species", CALC_GEN3["species"], names, "vanilla gen3")


def test_vanilla_gen3_moves_resolve():
    _assert_resolves(VANILLA, "move", CALC_GEN3["move"],
                     set(GEN3_VANILLA_MOVE_NAMES.values()), "vanilla gen3")


def test_vanilla_gen3_items_resolve():
    _assert_resolves(VANILLA, "item", CALC_GEN3["item"],
                     set(FRLG_ITEM_NAMES.values()), "vanilla gen3")


def test_vanilla_gen3_leaves_rr_alone_and_vice_versa():
    assert RR.calc_name("species", "Silvally (Fight)") == "Silvally-Fighting"
    assert VANILLA.calc_name("species", "Silvally (Fight)") == "Silvally (Fight)"
    assert VANILLA.calc_name("move", "Vicegrip") == "Vise Grip"
    assert RR.calc_name("move", "Vicegrip") == "Vicegrip"  # not a table entry on the RR side


def test_table_targets_are_calc_names():
    for kind, table_path, calc in (("gen1_rby", ROOT / "data/games/gen1_rby/calc_names.json", CALC_GEN1),
                                    ("gen3_vanilla", ROOT / "data/games/gen3_frlge/calc_names_vanilla.json", CALC_GEN3)):
        table = json.loads(table_path.read_text(encoding="utf-8"))
        for k, mapping in table.items():
            if k == "_note":
                continue
            assert mapping, f"{kind}.{k} is empty"
            bad = {v for v in mapping.values() if v not in calc[k]}
            assert not bad, f"{kind}.{k}: table targets not calc names: {bad}"


# ── Nature / ability as adapter facts ─────────────────────────────────────────

def test_gen1_mon_entry_has_no_nature_or_ability():
    sid = gen1_codec.natdex_to_internal(1)  # Bulbasaur
    entry = _build_mon_entry("0000:0000:00",
                             {"species_id": sid, "level": 5, "hp": 10, "maxHP": 10}, RBY)
    assert entry["nature"] is None
    assert entry["ability_name"] == ""
    assert "Nature" not in entry["showdown_paste"]
    assert "Ability" not in entry["showdown_paste"]


def test_rr_mon_entry_keeps_nature_and_ability_unchanged():
    key = "00000005:00000000:00"
    detail = {"species_id": 1, "level": 50, "hp": 10, "maxHP": 10, "ability_name": "Overgrow"}
    entry = _build_mon_entry(key, detail, RR)
    assert entry["nature"] == RR.calc_nature(key)
    assert entry["nature"]
    assert entry["ability_name"] == "Overgrow"
    assert f"{entry['nature']} Nature" in entry["showdown_paste"]
    assert "Ability: Overgrow" in entry["showdown_paste"]


def test_gen3_enemy_without_personality_has_no_nature():
    """A foe-N enemy key carries no personality, so no made-up Hardy masks the set nature."""
    assert RR.calc_nature("foe-0") is None
