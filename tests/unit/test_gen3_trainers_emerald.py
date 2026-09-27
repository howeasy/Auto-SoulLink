"""Vanilla Emerald trainer names, Upcoming Key Trainers and calc labels (owner ruling 28, card TG-1).

data/games/gen3_emerald/emerald_trainers.json is generated from pinned pret pokeemerald by
tools/gen_gen3_trainers.py --game emerald, the FR/LG code path. Tests that read the pret clone skip
by name when it is absent and fail when it is at another commit (tests/unit/gen3_pret.py
find_emerald/require_emerald); the rest read committed files only. Spot values below are copied
from pokeemerald src/data/trainers.h + trainer_parties.h at the pin.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen3_pret  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_gen3_trainers as gen  # noqa: E402

GAME = gen.GAMES["emerald"]
DATA = json.loads(GAME["out"].read_text(encoding="utf-8"))
TRAINERS = DATA["trainers"]


def _pret():
    return gen3_pret.require_emerald(gen3_pret.find_emerald())


def _party(tid):
    return [(m["species"], m["level"], m.get("item"), m["moves"]) for m in TRAINERS[str(tid)]["party"]]


# ── generator ─────────────────────────────────────────────────────────────────────────────────

def test_generator_check_matches_committed_json():
    fresh = gen.dump(gen.build(_pret(), game="emerald"))
    assert fresh == GAME["out"].read_text(encoding="utf-8"), (
        "emerald_trainers.json is stale: run python tools/gen_gen3_trainers.py --game emerald")
    assert DATA["source"] == {"repo": "pret/pokeemerald", "commit": gen3_pret.EMERALD_PIN}
    assert DATA["titles"] == ["emerald"] and "learnsets_by_title" not in DATA


def test_table_covers_gtrainers():
    # gTrainers is 40-byte struct Trainer entries; the .sym size / 40 is the count. The generator
    # drops the 4 link-battle save-slot placeholders (TRAINER_RED/LEAF/BRENDAN_PLACEHOLDER/
    # MAY_PLACEHOLDER, ids 851-854, the table's last 4): no trainerbattle or other reference in
    # data/maps or data/scripts ever fights them, so they'd otherwise dangle as an unfightable
    # "Groudon Lv5"/"Kyogre Lv5" a trainer_brief lookup could still surface (GAMES["emerald"]
    # ["unused"] in tools/gen_gen3_trainers.py).
    line = next(ln for ln in (ROOT / "data/gen3/pret/pokeemerald.sym").read_text().splitlines()
                if ln.endswith(" gTrainers"))
    assert int(line.split()[2], 16) // 40 == 855
    assert len(TRAINERS) == 851
    assert sorted(int(k) for k in TRAINERS) == list(range(851))


def test_json_keys_are_pret_trainer_constants():
    root = _pret()
    opp = gen.defines((root / "include/constants/opponents.h").read_text(encoding="utf-8"), "TRAINER_")
    order = re.findall(r"^    \[(TRAINER_\w+)\] =", (root / "src/data/trainers.h").read_text(encoding="utf-8"), re.M)
    assert [opp[c] for c in order] == list(range(len(order)))
    order = [c for c in order if c not in gen.GAMES["emerald"]["unused"]]
    assert {int(k): v["const"] for k, v in TRAINERS.items()} == {opp[c]: c for c in order}


# ── pret-grounded spot checks ─────────────────────────────────────────────────────────────────

def test_roxanne():
    # [TRAINER_ROXANNE_1] = 265, sParty_Roxanne1 (ITEM_CUSTOM_MOVES); Rustboro Gym warps to the
    # unmapped Rustboro City, whose nearest mapped neighbour (by id) is route_104
    t = TRAINERS["265"]
    assert (t["const"], t["name"], t["class"], t["area"], t["key"], t["level_cap"], t["calc_label"]) == (
        "TRAINER_ROXANNE_1", "Roxanne", "Leader", "route_104", True, 15, "Leader Roxanne")
    rock = ["Tackle", "Defense Curl", "Rock Throw", "Rock Tomb"]
    assert _party(265) == [("Geodude", 12, None, rock), ("Geodude", 12, None, rock),
                           ("Nosepass", 15, "Oran Berry", ["Block", "Harden", "Tackle", "Rock Tomb"])]
    assert "fight_label" not in t
    # gRematchTable REMATCH_ROXANNE: tiers 2..5 fight where tier 1 does
    assert [(TRAINERS[str(i)]["fight_label"], TRAINERS[str(i)]["area"]) for i in range(770, 774)] == [
        (f"Rematch {n}", "route_104") for n in range(1, 5)]


def test_wattson_is_filed_under_mauville_city_not_route_110():
    # [TRAINER_WATTSON] = 267 (+ 4 rematch tiers 778-781). Owner ruling 28 RC defect: Mauville City
    # has no wild encounters of its own (unlike e.g. Petalburg/Lilycove), so it was missing from
    # area_map.json entirely and Wattson's gym warped straight past it to the nearest wild-linked
    # neighbour, Route 110 -- same "nearest-area rule" mechanism test_roxanne documents for
    # Rustboro, but Mauville has NO trainers of its own outside the gym, so misfiling them under
    # Route 110 hides them from that route's real trainers. Scoped to Mauville only (the flagged
    # city); Rustboro/Fortree/Littleroot/Oldale/Fallarbor/Verdanturf have the identical area_map
    # gap and are a separate owner call.
    for tid in (267, 778, 779, 780, 781):
        t = TRAINERS[str(tid)]
        assert t["name"] == "Wattson"
        assert t["area"] == "mauville_city", (tid, t["area"])
    area_map = json.loads(GAME["area_map"].read_text(encoding="utf-8"))
    assert "mauville_city" in area_map.values()


def test_wallace_is_the_champion_and_steven_is_not():
    # Emerald's Champion is Wallace (TRAINER_CLASS_CHAMPION, 335); Steven (804) is a RIVAL-class
    # {PKMN} TRAINER fought postgame in Meteor Falls
    champs = [v["const"] for v in TRAINERS.values() if v["class"] == "Champion"]
    assert champs == ["TRAINER_WALLACE"]
    w = TRAINERS["335"]
    assert (w["name"], w["area"], w["level_cap"], w["calc_label"]) == ("Wallace", "ever_grande_city", 58, "Champion Wallace")
    assert w["party"][-1] == {"species": "Milotic", "level": 58, "item": "Sitrus Berry",
                              "moves": ["Recover", "Surf", "Ice Beam", "Toxic"]}
    s = TRAINERS["804"]
    assert (s["name"], s["class"], s["area"], s["key"], s["level_cap"]) == (
        "Steven", "Pokémon Trainer", "meteor_falls", True, 78)
    assert s["party"][-1]["species"] == "Metagross"


def test_may_and_brendan_route_103():
    # TRAINER_{BRENDAN,MAY}_ROUTE_103_{MUDKIP,TREECKO,TORCHIC}: the suffix is the PLAYER's starter,
    # the party the rival's (sParty_MayRoute103Mudkip = Treecko Lv5). Names are fixed in Emerald.
    want = {"MUDKIP": "Treecko", "TREECKO": "Torchic", "TORCHIC": "Mudkip"}
    for rival, ids in (("Brendan", (520, 523, 526)), ("May", (529, 532, 535))):
        for tid, (player, theirs) in zip(ids, want.items(), strict=True):
            t = TRAINERS[str(tid)]
            assert t["const"] == f"TRAINER_{rival.upper()}_ROUTE_103_{player}"
            assert (t["name"], t["class"], t["area"], t["key"], "rival" in t) == (
                rival, "Pokémon Trainer", "route_103", True, False)
            assert [(m["species"], m["level"]) for m in t["party"]] == [(theirs, 5)]
            assert t["fight_label"] == f"Rival has {theirs}"
    # default moves: Treecko Lv5 knows Pound, Leer (pret sTreeckoLevelUpLearnset)
    assert TRAINERS["529"]["party"][0]["moves"] == ["Pound", "Leer"]
    # Emerald.js keys May's fights "<town> May" and Brendan's "<town> Rival"
    assert TRAINERS["529"]["calc_label"].endswith("May") and TRAINERS["520"]["calc_label"].endswith("Rival")


def test_default_moves_follow_the_emerald_learnset():
    # [TRAINER_SAWYER_1]: sParty_Sawyer1 = Geodude Lv21, NO_ITEM_DEFAULT_MOVES. Geodude learns
    # Tackle, Defense Curl 1, Mud Sport 6, Rock Throw 11, Magnitude 16, Self-Destruct 21.
    assert _party(1) == [("Geodude", 21, None, ["Mud Sport", "Rock Throw", "Magnitude", "Self-Destruct"])]


def test_key_trainers():
    """KEY RULE (tool docstring): key class, a party, and an area from some map script."""
    key = {v["const"] for v in TRAINERS.values() if v.get("key")}
    assert len(key) == 92
    for c in ("TRAINER_ROXANNE_1", "TRAINER_JUAN_5", "TRAINER_SIDNEY", "TRAINER_WALLACE",
              "TRAINER_STEVEN", "TRAINER_WALLY_MAUVILLE", "TRAINER_WALLY_VR_1", "TRAINER_ARCHIE",
              "TRAINER_MAXIE_MOSSDEEP", "TRAINER_MATT", "TRAINER_TABITHA_MT_CHIMNEY",
              "TRAINER_MAY_LILYCOVE_TORCHIC", "TRAINER_BRENDAN_RUSTBORO_MUDKIP"):
        assert c in key, c
    # link-battle save-slot placeholders no script ever fights: dropped from TRAINERS entirely
    # (test_table_covers_gtrainers), so they can't be key either
    assert not key & {"TRAINER_RED", "TRAINER_LEAF", "TRAINER_BRENDAN_PLACEHOLDER", "TRAINER_MAY_PLACEHOLDER"}
    assert not {"TRAINER_RED", "TRAINER_LEAF", "TRAINER_BRENDAN_PLACEHOLDER", "TRAINER_MAY_PLACEHOLDER"} & \
        {v["const"] for v in TRAINERS.values()}
    assert {v["class"] for v in TRAINERS.values() if v.get("key")} == {
        "Leader", "Elite Four", "Champion", "Pokémon Trainer", "Magma Leader", "Aqua Leader",
        "Magma Admin", "Aqua Admin"}
    by_area = {tid for ids in DATA["trainers_by_area"].values() for tid in ids}
    assert by_area == {int(k) for k, v in TRAINERS.items() if v.get("key")}
    assert set(DATA["trainers_by_area"]) <= set(json.loads(GAME["area_map"].read_text(encoding="utf-8")).values())


# ── calc Prep tab join ────────────────────────────────────────────────────────────────────────

def test_calc_labels_are_emerald_setdex_keys():
    setdex = gen.load_setdex(GAME["setdex"])
    keys = {full.split(" | ")[0].strip() for sets in setdex.values() for full in sets}
    labels = {v["calc_label"] for v in TRAINERS.values() if "calc_label" in v}
    assert labels <= keys
    # 475 of Emerald.js's 499 trainer keys join; the rest are ambiguous grunts ("Magma Grunt 5"
    # spans two places) or setdex parties that differ from pret (Fortree May | Mudkip has a
    # Pelipper where sParty_MayRoute119Mudkip has Lombre).
    # OMP review cx-6b3b8309 finding 5: calc_label's fuzzy fallback used to let a single-mon party
    # take a label from a DIFFERENT fight whose species+level didn't match its own (Mt Chimney's
    # combined Numel+Zubat "Magma Grunt" fight labelled a lone Numel AND a lone Zubat; an unrelated
    # "Magma Grunt 5" fight labelled a lone Mightyena at the same level). A single-mon party now
    # only takes a label whose setdex fight has its exact species+level, dropping 3 labels (146,
    # 579, 589) and the now-unused "Magma Grunt" text from `labels` (476 -> 475, 506 -> 503).
    assert (len(labels), len(keys)) == (475, 499)
    assert sum("calc_label" in v for v in TRAINERS.values()) == 503
    # every first-fight key trainer is joined; rematch tiers are not in the setdex
    unjoined = [v["const"] for v in TRAINERS.values() if v.get("key") and "calc_label" not in v]
    assert all(re.search(r"_[2-5]$", c) for c in unjoined if c != "TRAINER_MAY_ROUTE_119_MUDKIP"), unjoined


def test_party_species_are_calc_names():
    calc_species = set(gen.load_setdex(GAME["setdex"]))
    used = {m["species"] for v in TRAINERS.values() if v.get("calc_label") for m in v["party"]}
    assert used <= calc_species, used - calc_species
