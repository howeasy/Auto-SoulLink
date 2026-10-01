"""Gen 4 (HGSS) data tools -- CARD gen4-G2-data-tools.

tools/gen_gen4_{area_map,encounters,trainers,acquisition}.py generate data/games/gen4_hgss/
{area_map,locations,encounters,trainers,acquisition}.json from the pinned pret/pokeheartgold clone.

Tests that need the clone skip BY NAME when it is absent and FAIL when it is at another commit or
dirty (absent skips, wrong fails). The rest read only the committed JSON. Every control below was
revert-tested once: the mutation that must turn it red is named in the test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen4_pins  # noqa: E402
import gen_gen4_acquisition as acq  # noqa: E402
import gen_gen4_area_map as base  # noqa: E402
import gen_gen4_encounters as enc  # noqa: E402
import gen_gen4_trainers as trn  # noqa: E402

DATA = ROOT / "data" / "games" / "gen4_hgss"
TOOLS = {
    "area_map": (base, ["area_map.json", "locations.json"]),
    "encounters": (enc, ["encounters.json"]),
    "trainers": (trn, ["trainers.json"]),
    "acquisition": (acq, ["acquisition.json"]),
}
ALL_FILES = [f for _m, fs in TOOLS.values() for f in fs]
PIN = gen4_pins.SOURCE_COMMITS["pokeheartgold_citation"]


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# ── the pinned clone: absent -> skip by name, wrong commit -> FAIL ───────────────────────────────


@pytest.fixture(scope="module")
def clone() -> Path:
    try:
        path = base.locate_clone()
    except base.PretAbsent as exc:
        pytest.skip(f"pret/pokeheartgold @ {PIN[:8]} not available: {exc}")
    try:
        base.verify_clone(path)
    except base.PretMismatch as exc:
        pytest.fail(str(exc))
    return path


def run_tool(mod, argv: list[str], monkeypatch, capsys) -> tuple[int, str]:
    monkeypatch.setattr(sys, "argv", [mod.__name__, *argv])
    rc = mod.main()
    return rc, capsys.readouterr().err


# ── --check mode: regenerate in memory, diff vs committed ────────────────────────────────────────


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_check_mode_matches_committed(tool, clone, monkeypatch, capsys):
    mod, files = TOOLS[tool]
    rc, err = run_tool(mod, ["--check", "--pret", str(clone)], monkeypatch, capsys)
    assert rc == 0, f"{tool} drifted from the committed JSON: {err}"


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_check_mode_detects_drift(tool, clone, monkeypatch, capsys, tmp_path):
    """Control: a one-byte edit to a committed file must turn --check red (revert-tested by
    making finish() always return True)."""
    mod, files = TOOLS[tool]
    for name in files:
        (tmp_path / name).write_text((DATA / name).read_text(encoding="utf-8"), encoding="utf-8")
    victim = tmp_path / files[0]
    text = victim.read_text(encoding="utf-8")
    victim.write_text(text.replace('"commit": "' + PIN, '"commit": "' + "0" * 40, 1), encoding="utf-8")
    rc, err = run_tool(mod, ["--check", "--pret", str(clone), "--out-dir", str(tmp_path)], monkeypatch, capsys)
    assert rc == 1 and "DRIFT" in err and files[0] in err


def test_check_mode_flags_a_missing_committed_file(clone, monkeypatch, capsys, tmp_path):
    rc, err = run_tool(trn, ["--check", "--pret", str(clone), "--out-dir", str(tmp_path)], monkeypatch, capsys)
    assert rc == 1 and "DRIFT" in err


# ── pret availability controls (no clone needed) ─────────────────────────────────────────────────


def test_absent_clone_is_open_and_names_the_path(monkeypatch, capsys, tmp_path):
    missing = tmp_path / "no-pokeheartgold"
    for mod, _f in TOOLS.values():
        rc, err = run_tool(mod, ["--check", "--pret", str(missing)], monkeypatch, capsys)
        assert rc == 2 and str(missing) in err and "OPEN" in err
    with pytest.raises(base.PretAbsent, match="no-pokeheartgold"):
        base.locate_clone(str(missing))


def _fake_clone(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "fake-pret"
    (repo / "include" / "constants").mkdir(parents=True)
    (repo / "include" / "constants" / "maps.h").write_text("// stub\n")
    env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), *env, "commit", "-q", "-m", "x"], check=True)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return repo, head


def test_wrong_pret_head_fails_not_skips(monkeypatch, capsys, tmp_path):
    repo, head = _fake_clone(tmp_path)
    assert head != PIN
    with pytest.raises(base.PretMismatch, match="pinned"):
        base.verify_clone(repo)
    for mod, _f in TOOLS.values():
        rc, err = run_tool(mod, ["--check", "--pret", str(repo)], monkeypatch, capsys)
        assert rc == 1 and "FAIL" in err and head in err


def test_dirty_pret_clone_fails(monkeypatch, tmp_path):
    repo, head = _fake_clone(tmp_path)
    monkeypatch.setattr(base, "PIN", head)
    base.verify_clone(repo)  # clean at the (patched) pin: accepted
    (repo / "include" / "constants" / "maps.h").write_text("// edited\n")
    with pytest.raises(base.PretMismatch, match="tracked modifications"):
        base.verify_clone(repo)


# ── committed data: provenance, counts, retirement precondition ─────────────────────────────────


def test_every_file_records_the_pinned_commit_and_inputs():
    lock = json.loads((ROOT / "data" / "gen4_sources.lock.json").read_text(encoding="utf-8"))
    assert lock["sources"]["pokeheartgold_citation"]["commit"] == PIN
    for name in ALL_FILES:
        src = load(name)["source"]
        assert src["repo"] == "pret/pokeheartgold" and src["commit"] == PIN, name
        assert src["inputs"] and all(len(h) == 64 for h in src["inputs"].values()), name


def test_successors_exist_before_gen4_hgsspt_can_be_deleted():
    """PLAN 4.6: data/games/gen4_hgsspt/** may go only after its successors exist in gen4_hgss/."""
    for name in ALL_FILES:
        assert (DATA / name).stat().st_size > 1000, f"{name} is missing or a stub"


def test_area_map_and_locations_counts():
    area, loc = load("area_map.json"), load("locations.json")
    assert len(area["maps"]) == 540 and len(loc["locations"]) == 540
    assert set(area["maps"]) == set(loc["locations"])
    assert {m for m in area["maps"] if area["maps"][m] is None} == set(area["unmapped_maps"])
    for mid, aid in area["maps"].items():
        assert aid is None or mid_in(area, aid, int(mid)), (mid, aid)
        assert loc["locations"][mid]["area"] == aid


def mid_in(area: dict, aid: str, mid: int) -> bool:
    return mid in area["areas"][aid]["maps"]


def test_special_zones_bug_contest_and_safari_are_their_own_areas():
    area = load("area_map.json")
    assert area["areas"]["bug_catching_contest"]["maps"] == [487]
    assert area["areas"]["bug_catching_contest"]["special"] == "bug_contest"
    assert area["areas"]["national_park"]["maps"] == [96, 488], "the contest map must not stay in National Park"
    sub = {a: v for a, v in area["areas"].items() if v["parent"] == "safari_zone"}
    assert len(sub) == 12 and all(v["maps"] == [] and v["special"] == "safari" for v in sub.values())
    assert len(area["areas"]["safari_zone"]["maps"]) == 15
    modes = load("acquisition.json")["special_modes"]
    assert modes["bug_contest"]["area"] == "bug_catching_contest" and set(modes["safari"]["areas"]) == set(sub)
    assert {r["species"]["name"] for r in modes["roamers"].values()} == {"Raikou", "Entei", "Latias", "Latios"}


def split_banks(doc: dict) -> set[str]:
    hg, ss = doc["versions"]["heartgold"]["banks"], doc["versions"]["soulsilver"]["banks"]
    return {k for k in hg if hg[k] != ss[k]}


def test_encounter_counts_and_hg_ss_split_preserved():
    doc = load("encounters.json")
    assert doc["bank_count"] == 142 and doc["split_bank_count"] == 53
    for title in ("heartgold", "soulsilver"):
        assert len(doc["versions"][title]["banks"]) == 142
        assert len(doc["versions"][title]["headbutt"]) == 60
    differing = split_banks(doc)
    assert len(differing) == 53
    assert differing == {k for k, b in doc["banks"].items() if b["version_split"]}
    assert len(doc["banks_without_map"]) == 7 and len(doc["safari"]["areas"]) == 12


def test_a_merged_hg_eq_ss_bank_is_detected():
    """Control: collapsing SS into HG for a bank that pret splits (R30) must change the detector's
    answer (revert-tested by swapping split() for a HEARTGOLD-only collapse in the generator)."""
    doc = load("encounters.json")
    assert "R30" in split_banks(doc)
    doc["versions"]["soulsilver"]["banks"]["R30"] = doc["versions"]["heartgold"]["banks"]["R30"]
    assert "R30" not in split_banks(doc) and len(split_banks(doc)) == 52


def test_split_banks_match_pret_independently(clone):
    """Oracle: the banks that differ per version are exactly the gs_enc_data.json entries that contain
    a {"HEARTGOLD","SOULSILVER"} node (computed here, not by the generator)."""
    raw = json.loads(base.read(clone, "files/fielddata/encountdata/gs_enc_data.json"))["encounters"]

    def has_pair(o) -> bool:
        if isinstance(o, dict):
            return set(o) == {"HEARTGOLD", "SOULSILVER"} or any(has_pair(v) for v in o.values())
        return isinstance(o, list) and any(has_pair(v) for v in o)

    expected = {e["map"] for e in raw if has_pair(e)}
    assert len(expected) == 53
    doc = load("encounters.json")
    assert {doc["banks"][k]["json_map"] for k in split_banks(doc)} == expected
    # spot check a land-level split and a swarm split against the raw source
    r30 = next(e for e in raw if e["map"] == "R30")
    hg_lv = r30["land"]["mons"][0]["level"]
    assert doc["versions"]["heartgold"]["banks"]["R30"]["land"]["day"][0]["min_level"] == (hg_lv["HEARTGOLD"] if isinstance(hg_lv, dict) else hg_lv)
    assert doc["versions"]["soulsilver"]["banks"]["R30"]["swarm"]["land"]["name"] == "Ledyba"
    assert doc["versions"]["heartgold"]["banks"]["R30"]["swarm"]["land"]["name"] == "Pidgey"


def test_trainers_counts_and_roles():
    doc = load("trainers.json")
    assert doc["trainer_count"] == len(doc["trainers"]) == 738 and doc["version_split"] is False
    names = {(t["name"], t["role"]) for t in doc["trainers"].values() if t["role"]}
    assert ("Falkner", "leader") in names and ("Lance", "champion") in names and ("Silver", "rival") in names
    assert all(t["const"].startswith("TRAINER_") for t in doc["trainers"].values())


# ── acquisition: 61 script sites, C producers, 13 NPC records (10/2/1) ───────────────────────────


def test_acquisition_inventory_counts_are_pinned():
    doc = load("acquisition.json")
    inv = doc["inventory"]
    assert inv["script_site_count"] == len(doc["script_sites"]) == 61
    assert inv["script_command_counts"] == {"GiveMon": 13, "GiveEgg": 3, "GiveTogepiEgg": 1, "GiveSpikyEarPichu": 1, "GiveLoanMon": 2, "CreateRoamer": 8, "WildBattle": 21, "LoadNPCTrade": 11, "ChooseStarter": 1}
    assert inv["npc_record_count"] == len(doc["npc_trade_records"]) == 13
    assert inv["npc_classification"] == {"authored_exchange": 10, "authored_loan_grant": 2, "dormant_narc_record_in_pinned_authored_scan": 1}
    assert inv["npc_load_site_count"] == 11 and inv["npc_distinct_exchange_ids"] == [0, 1, 2, 3, 5, 8, 9, 10, 11, 12]
    assert inv["commands_without_a_c_producer"] == []
    assert inv["c_call_site_count"] == 29


def test_npc_records_classification_and_loans_are_not_exchanges():
    recs = {r["index"]: r for r in load("acquisition.json")["npc_trade_records"]}
    assert [i for i, r in recs.items() if r["source_class"] == "authored_loan_grant"] == [6, 7]
    assert [i for i, r in recs.items() if r["source_class"].startswith("dormant")] == [4]
    assert recs[5]["same_species"] and recs[10]["same_species"] and recs[5]["source_class"] == recs[10]["source_class"] == "authored_exchange"
    assert recs[8]["load_sites"] == ["scr_seq_0195_R10R0201:64", "scr_seq_0196_R10R0202:207"], "ID 8 has two load sites"
    for i in (6, 7):
        assert "never key_change" in recs[i]["identity_rule"] and recs[i]["load_sites"] == []


def test_loan_species_come_from_the_npc_record_not_the_map_argument():
    """Contradicts docs/gen4/research/data/acquisition_manifest.json, which parsed GiveLoanMon's third
    argument (a map number: 75 / 101) as a species. The macro is GiveLoanMon tradeno, level, mapno."""
    sites = {s["id"]: s for s in load("acquisition.json")["script_sites"] if s["command"] == "GiveLoanMon"}
    assert {s["species"]["value"]["name"] for s in sites.values()} == {"Shuckle", "Spearow"}
    assert {s["loan_map_arg"] for s in sites.values()} == {75, 101}


def test_nothing_unresolved_vanishes():
    doc = load("acquisition.json")
    listed = {u["id"] for u in doc["unresolved"]}
    for s in doc["script_sites"]:
        assert s["status"] in {"resolved", "version_branch", "candidates", "unresolved"}
        if s["status"] in {"candidates", "unresolved"}:
            assert s["id"] in listed, f"{s['id']} is {s['status']} but not in `unresolved`"
    assert {"hg_engine", "mystery_gift", "link_trade_gts_pal_park"} <= listed
    assert any(u["status"] == "open_policy" for u in doc["unresolved"]), "daycare withdrawal open question"
    # the runtime HG/SS branches that decide a site are carried, with the version each side takes
    by_id = {s["id"]: s for s in doc["script_sites"]}
    assert by_id["scr_seq_0021_D17R0110:73"]["level"]["by_version"] == {"heartgold": 45, "soulsilver": 70}  # Ho-Oh
    assert by_id["scr_seq_0104_D40R0107:85"]["level"]["by_version"] == {"heartgold": 70, "soulsilver": 45}  # Lugia
    latios = by_id["scr_seq_0750_T03:396"]["species"]["by_version"]
    assert (latios["heartgold"]["name"], latios["soulsilver"]["name"]) == ("Latios", "Latias")
    assert {c["name"] for c in by_id["scr_seq_0755_T03R0101:359"]["species"]["candidates"]} >= {"Omanyte", "Cranidos"}


def test_site_areas_exist_and_zones_follow_d10():
    doc, area = load("acquisition.json"), load("area_map.json")
    for s in doc["script_sites"]:
        assert s["area"] in area["areas"], s["id"]
        assert s["zone"] == acq.ZONE_POLICY[s["kind"]]["zone"]
    zones = {s["kind"]: s["zone"] for s in doc["script_sites"]}
    assert zones["roamer"] == "roamer" and zones["static"] == "gift" and zones["npc_exchange"] == "exchange"
    for bank in load("encounters.json")["banks"].values():
        assert all(a in area["areas"] for a in bank["areas"])


def test_sites_match_the_independent_research_inventory():
    """The generator re-derives the 61 hits; docs/gen4/research/data was produced separately."""
    ours = {(s["file"], s["line"], s["command"], s["map_id"]) for s in load("acquisition.json")["script_sites"]}
    research = json.loads((ROOT / "docs/gen4/research/data/acquisition_manifest.json").read_text(encoding="utf-8"))
    assert ours == {(h["file"], h["line"], h["command"], h["map_num"]) for h in research["hits"]}
    raw = json.loads((ROOT / "docs/gen4/research/data/npc_trades.json").read_text(encoding="utf-8"))
    recs = load("acquisition.json")["npc_trade_records"]
    for r, old in zip(recs, raw, strict=True):
        assert r["record"] == {k: v for k, v in old["hg"].items() if not k.endswith("_name")} and old["hg"] == old["ss"]
        assert r["source_class"] == old["source_class"]


# ── C producers: a new, unclassified call site must fail generation ─────────────────────────────


def test_unclassified_c_producer_fails_generation(clone, tmp_path, monkeypatch):
    """Control (revert-tested by deleting the `problems` check in scan_c): a classified producer that
    disappears from the table, or a changed call count, is reported."""
    producers, problems = acq.scan_c(clone)
    assert problems == [] and len(producers) == 25
    victim = ("src/trainer_data.c", "CreateNPCTrainerParty", "Party_AddMon")
    monkeypatch.setitem(acq.C_PRODUCERS, victim, {**acq.C_PRODUCERS[victim], "n": 3})
    _p, problems = acq.scan_c(clone)
    assert any("4 call sites" in p for p in problems)
    monkeypatch.delitem(acq.C_PRODUCERS, victim)
    _p, problems = acq.scan_c(clone)
    assert any("unclassified C producer" in p and "trainer_data.c" in p for p in problems)


def test_npc_narc_parse_matches_record_count(clone):
    recs = acq.parse_npc_narc((clone / "files/a/1/1/2").read_bytes())
    assert len(recs) == 13 and recs[0]["give_species"] == 95 and recs[4]["give_species"] == 78
