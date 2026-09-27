"""Vanilla FireRed/LeafGreen trainer names, Upcoming Key Trainers and calc labels (owner ruling 28).

data/games/gen3_frlge/frlg_trainers.json is generated from pinned pret pokefirered by
tools/gen_gen3_trainers.py. Tests that read the pret clone skip by name when it is absent and fail
when it is at another commit (tests/unit/gen3_pret.py); the rest read committed files only.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen3_pret  # noqa: E402

from server.adapters.gen3_frlge import Gen3Adapter  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_gen3_trainers as gen  # noqa: E402

DATA = json.loads((ROOT / "data/games/gen3_frlge/frlg_trainers.json").read_text(encoding="utf-8"))
TRAINERS = DATA["trainers"]


def _pret():
    return gen3_pret.require(gen3_pret.find())


def _party(tid):
    return [(m["species"], m["level"], m["moves"]) for m in TRAINERS[str(tid)]["party"]]


# ── generator ─────────────────────────────────────────────────────────────────────────────────

def test_generator_check_matches_committed_json():
    root = _pret()
    fresh = gen.dump(gen.build(root))
    assert fresh == (ROOT / "data/games/gen3_frlge/frlg_trainers.json").read_text(encoding="utf-8"), (
        "frlg_trainers.json is stale: run python tools/gen_gen3_trainers.py")
    assert DATA["source"]["commit"] == gen3_pret.PIN


def test_default_moves_mirror_give_box_mon_initial_moveset():
    ls = [(1, "A"), (1, "B"), (4, "A"), (5, "C"), (6, "D"), (7, "E"), (9, "F")]
    assert gen.default_moves(ls, 1) == ["A", "B"]
    assert gen.default_moves(ls, 5) == ["A", "B", "C"]              # a known move is skipped
    assert gen.default_moves(ls, 7) == ["B", "C", "D", "E"]         # full: the first is pushed out
    assert gen.default_moves(ls, 100) == ["C", "D", "E", "F"]


# ── the wire id is the gTrainers index ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("sym", ["pokefirered.sym", "pokeleafgreen.sym"])
def test_table_covers_gtrainers_in_both_titles(sym):
    # gTrainers is 40-byte struct Trainer entries (include/battle.h); the .sym size / 40 is the count
    line = next(ln for ln in (ROOT / "data/gen3/pret" / sym).read_text().splitlines()
                if ln.endswith(" gTrainers"))
    assert int(line.split()[2], 16) // 40 == len(TRAINERS) == 743
    assert sorted(int(k) for k in TRAINERS) == list(range(743))


def test_json_keys_are_pret_trainer_constants():
    root = _pret()
    opp = gen.defines((root / "include/constants/opponents.h").read_text(encoding="utf-8"), "TRAINER_")
    order = re.findall(r"^    \[(TRAINER_\w+)\] = \{", (root / "src/data/trainers.h").read_text(encoding="utf-8"), re.M)
    # designated initializers in index order: gTrainers[TRAINER_X] -- the value the client reads
    # from gTrainerBattleOpponent_A and CreateNPCTrainerParty indexes gTrainers with
    assert [opp[c] for c in order] == list(range(len(order)))
    assert {int(k): v["const"] for k, v in TRAINERS.items()} == {opp[c]: c for c in order}
    assert opp["TRAINER_BUG_CATCHER_RICK"] == 102 and opp["TRAINER_LEADER_BROCK"] == 414


# ── pret-grounded spot checks ─────────────────────────────────────────────────────────────────

def test_brock():
    # pret trainers.h [TRAINER_LEADER_BROCK]; trainer_parties.h sParty_LeaderBrock (explicit moves)
    t = TRAINERS["414"]
    assert (t["name"], t["class"], t["area"], t["key"], t["level_cap"]) == (
        "Brock", "Leader", "pewter_city", True, 14)
    assert _party(414) == [("Geodude", 12, ["Tackle", "Defense Curl"]),
                           ("Onix", 14, ["Tackle", "Bind", "Rock Tomb"])]
    assert t["calc_label"] == "Leader Brock"


def test_viridian_forest_bug_catchers():
    # data/maps/ViridianForest/scripts.inc runs these five trainerbattles; default moves from the
    # learnsets (Kakuna/Metapod learn Harden at 1 and 7: one Harden)
    forest = {k: v for k, v in TRAINERS.items() if v.get("area") == "viridian_forest"}
    assert {(v["class"], v["name"]) for v in forest.values()} == {
        ("Bug Catcher", n) for n in ("Rick", "Doug", "Sammy", "Anthony", "Charlie")}
    assert _party(102) == [("Weedle", 6, ["Poison Sting", "String Shot"]),
                           ("Caterpie", 6, ["Tackle", "String Shot"])]
    assert _party(103)[1] == ("Kakuna", 7, ["Harden"])
    assert not any(v.get("key") for v in forest.values())


def test_rival_starter_variants():
    # TRAINER_RIVAL_OAKS_LAB_{SQUIRTLE,BULBASAUR,CHARMANDER} = 326..328; the in-game name is the
    # player's choice for RIVAL_EARLY/RIVAL_LATE/CHAMPION (src/battle_message.c), so name ""
    lab = {k: TRAINERS[str(k)] for k in (326, 327, 328)}
    assert [t["party"][0]["species"] for t in lab.values()] == ["Squirtle", "Bulbasaur", "Charmander"]
    assert all(t["rival"] and t["name"] == "" and t["class"] == "Rival" and t["area"] == "oaks_lab"
               for t in lab.values())
    assert [t["fight_label"] for t in lab.values()] == [
        "Rival has Squirtle", "Rival has Bulbasaur", "Rival has Charmander"]
    champ = TRAINERS["438"]
    assert (champ["class"], champ["name"], champ["area"]) == ("Champion", "", "indigo_plateau")
    assert champ["party"][-1] == {"species": "Blastoise", "level": 63, "item": "Sitrus Berry",
                                  "moves": ["Hydro Pump", "Rain Dance", "Skull Bash", "Bite"]}


def test_key_trainers():
    key = {v["const"] for v in TRAINERS.values() if v.get("key")}
    assert len(key) == 47
    for c in ("TRAINER_LEADER_GIOVANNI", "TRAINER_BOSS_GIOVANNI", "TRAINER_ELITE_FOUR_LANCE_2",
              "TRAINER_TEAM_ROCKET_ADMIN", "TRAINER_CHAMPION_REMATCH_CHARMANDER"):
        assert c in key
    assert all(v.get("area") for v in TRAINERS.values() if v.get("key"))
    by_area = {tid for ids in DATA["trainers_by_area"].values() for tid in ids}
    assert by_area == {int(k) for k, v in TRAINERS.items() if v.get("key")}


# ── calc Prep tab join ────────────────────────────────────────────────────────────────────────

def test_calc_labels_are_frlg_setdex_keys():
    setdex = gen.load_setdex(gen.SETDEX)
    keys = {full.split(" | ")[0].strip() for sets in setdex.values() for full in sets}
    labels = {v["calc_label"] for v in TRAINERS.values() if "calc_label" in v}
    assert labels <= keys
    # every setdex trainer is joined to a pret trainer, except "Biker Goon 2": OMP review
    # cx-6b3b8309 finding 5 (calc_label's by_key fallback let a single-mon party take a label from
    # a DIFFERENT fight whose species+level didn't match its own -- FRLG.js's "Biker Goon 2" is one
    # setdex entry covering a combined Koffing+Grimer fight, but TRAINER_BIKER_GOON_2 (Koffing 38)
    # and TRAINER_BIKER_GOON_3 (Grimer 38) are two separate single-mon trainers, neither an exact
    # species+level match). A single-mon party now only takes an exact match, so it's unjoined.
    assert len(keys) - len(labels) == 1 and "Biker Goon 2" in keys - labels
    key_trainers = [v for v in TRAINERS.values() if v.get("key")]
    # the two Sevii Rocket admins are not in FRLG.js: they fall back to species/level matching
    assert [v["const"] for v in key_trainers if "calc_label" not in v] == [
        "TRAINER_TEAM_ROCKET_ADMIN", "TRAINER_TEAM_ROCKET_ADMIN_2"]


def test_party_species_are_calc_names():
    calc_species = set(gen.load_setdex(gen.SETDEX))
    used = {m["species"] for v in TRAINERS.values() if v.get("calc_label") for m in v["party"]}
    assert used <= calc_species | {"Ekans"}, used - calc_species


# ── adapter ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", ["firered", "leafgreen"])
def test_adapter_vanilla_titles(title):
    a = Gen3Adapter(is_rr=False, rom_type=title)
    assert a.trainer_info(102) == ("Rick", "Bug Catcher")
    assert a.trainer_info(414) == ("Brock", "Leader")
    assert a.trainer_info(326) == ("", "Rival")
    assert a.trainer_info(0) == ("", "") and a.trainer_info(9999) == ("", "")
    assert a.trainers_for_area("pewter_city") == [414]
    assert a.trainers_for_area("viridian_forest") == [] and a.trainers_for_area("") == []
    assert [m["species"] for m in a.trainer_party(414)] == ["Geodude", "Onix"]
    b = a.trainer_brief(326)
    assert (b["name"], b["class"], b["area"], b["calc_label"], b["level_cap"]) == (
        "Rival", "Rival", "oaks_lab", "Rival 1", 5)
    assert a.trainer_brief(102)["calc_label"] == "Bug Catcher Rick"
    assert a.trainer_brief(0) is None                     # TRAINER_NONE: no party
    a.trainer_brief(414)["party"][0]["species"] = "X"     # callers get copies
    assert a.trainer_party(414)[0]["species"] == "Geodude"


@pytest.mark.parametrize("rom_type", ["", "emerald", "firered_ap", "leafgreen_ap"])
def test_adapter_other_titles_have_no_frlg_table(rom_type):
    a = Gen3Adapter(is_rr=False, rom_type=rom_type)
    assert a.trainer_info(102) == ("", "")
    assert a.trainers_for_area("pewter_city") == []
    assert a.trainer_party(414) == [] and a.trainer_brief(414) is None


def test_rr_unchanged():
    rr = Gen3Adapter(is_rr=True, rom_type="firered_rr")
    assert rr._frlg_trainer_table() is None
    assert rr.trainer_info(327) == ("", "Rival")          # rr_trainers.json key 326 = gTrainers[327]
    assert 414 in rr.trainers_for_area("pewter_city") or 56 in rr.trainers_for_area("pewter_city")


# ── the board panel ───────────────────────────────────────────────────────────────────────────

def _server(adapter):
    from server.server import SLinkServer
    srv = SLinkServer.__new__(SLinkServer)
    srv.adapter = adapter
    srv._player_adapters = {"a": adapter}
    return srv


def test_board_panel_renders_fr_key_trainers():
    srv = _server(Gen3Adapter(is_rr=False, rom_type="firered"))
    html = srv._trainer_panel_html("oaks_lab", "a")
    assert "Upcoming Key Trainers" in html
    # the three starter variants group into one row (distinct fight_labels, one name)
    assert html.count('class="trainer-row') == 1 and html.count('class="tr-variant"') == 3
    assert 'data-calc-label="Rival 1"' in html and "Rival has Squirtle" in html
    brock = srv._trainer_panel_html("pewter_city", "a")
    assert "Brock" in brock and "Onix" in brock and 'data-calc-label="Leader Brock"' in brock
    assert srv._trainer_panel_html("viridian_forest", "a") == ""


# ── PHYSICAL: the trainer the FR/LG trainer-battle duo receipts fought ─────────────────────────

@pytest.mark.parametrize("title,tag", [("firered", "fr"), ("leafgreen", "lg")])
def test_duo_receipt_trainer_is_named(title, tag):
    probes = ROOT / "docs/gen3/probes"
    receipt = (probes / f"fc_linked_faint_active_trainer_gen3_{tag}_as_a_a2985d5a.txt").read_text(encoding="utf-8")
    assert "linked_faint_active_trainer_gen3: PASS" in receipt and "case=trainer" in receipt
    # the scenario enters its trainer battle only when gTrainerBattleOpponent_A == this id
    # (lua/tests/gen3_routes.lua enter_trainer asserts s.trainer_id == expected)
    scen = (ROOT / "lua/tests/duo/scenario_gen3_linked_faint_active.lua").read_text(encoding="utf-8")
    (tid,) = {int(x) for x in re.findall(r'enter_trainer\("linked_faint_active trainer", (\d+)', scen)}
    # the trainer-bench receipt prints the id the live client read
    bench = (probes / f"trainer_bench_{tag}_as_a_2bee46f2_2026-09-23.txt").read_text(encoding="utf-8")
    assert set(re.findall(r"trainer_id=(\d+)", bench)) == {str(tid)}
    assert Gen3Adapter(is_rr=False, rom_type=title).trainer_info(tid) == ("Rick", "Bug Catcher")
