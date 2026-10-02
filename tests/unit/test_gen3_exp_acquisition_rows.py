"""SEED-PENDING setup: native boot/save only; interaction/R4 hatch are not proved here."""
import json
from pathlib import Path

import pytest

from tools import gen3_gift_egg_rows as rows

ROOT = Path(__file__).resolve().parents[2]
TITLE = "emerald_expansion_28877d73"


@pytest.mark.parametrize("case", ["gift", "hatch", "egg_receive", "choice_gift", "gift_box"])
def test_expansion_setup_has_own_rom_facts_and_qualifies_without_acquisition(case):
    rom = (ROOT / ".cache/expansion-output/reference/pokeemerald.gba").read_bytes()
    facts = rows.expansion_facts(rom, case)
    raw, manifest = rows.build_exp_seed((ROOT / "tests/fixtures/gen3/exp_pc.sav").read_bytes(), case, rom)
    assert facts["title"] == TITLE
    assert facts["hatch_level"] == 1 and facts["egg_cycle_steps"] == 128
    assert manifest and all(m.startswith("SYNTH ") for m in manifest)
    assert not rows.exp_seed_problems(raw, facts)
    if case == "gift":
        assert facts["group"] == 14 and facts["num"] == 7
        assert facts["area"] == "mossdeep_city_stevens_house"


@pytest.mark.parametrize("fault", ["rom", "received", "where", "egg"])
def test_acquisition_seed_refuses_one_fact_drift(fault):
    from tools import gen3_fixtures as f
    c = f.codec
    rom = (ROOT / ".cache/expansion-output/reference/pokeemerald.gba").read_bytes()
    if fault == "rom":
        changed = bytearray(rom)
        changed[100] ^= 1
        with pytest.raises(ValueError, match="identity"):
            rows.expansion_facts(bytes(changed))
        return
    case = "hatch" if fault == "egg" else "gift"
    facts = rows.expansion_facts(rom, case)
    raw, _ = rows.build_exp_seed((ROOT / "tests/fixtures/gen3/exp_pc.sav").read_bytes(), case, rom)
    p = c.parse_flash(raw, title=c.TITLE_EXPANSION)
    sb1 = bytearray(p["sb1"])
    if fault == "received":
        sb1[facts["flags_off"] + facts["flag"] // 8] |= 1 << (facts["flag"] % 8)
    elif fault == "where":
        sb1[0] ^= 1
    else:
        sb1[c._TITLE_PARTY_OFFSETS[c.TITLE_EXPANSION][0]] = 1
    body = f.exp_write_slot({"sb1": bytes(sb1), "sb2": p["sb2"], "storage": p["storage"]}, counter=p["counter"])
    assert rows.exp_seed_problems(body, facts)


def test_choice_side_changes_native_fossil_selector_only():
    rom = (ROOT / ".cache/expansion-output/reference/pokeemerald.gba").read_bytes()
    a = rows.expansion_facts(rom, "choice_gift", "a")
    b = rows.expansion_facts(rom, "choice_gift", "b")
    assert a["species"] != b["species"] and a["area"] == b["area"]


def test_source_hatch_configuration_is_bound_to_the_recipe():
    config = json.loads((ROOT / "data/games/gen3_exp/28877d73/config.json").read_text())
    assert config["macros"]["P_EGG_HATCH_LEVEL"]["value"] >= 4
    assert config["macros"]["P_EGG_CYCLE_LENGTH"]["value"] >= 8


def test_native_qualified_fixtures_are_hash_bound_and_still_pending():
    import hashlib

    from tools import gen3_fixtures as f
    manifest = json.loads((ROOT / "tests/fixtures/gen3/exp_acquisition_synth_manifest.json").read_text())
    rom = (ROOT / ".cache/expansion-output/reference/pokeemerald.gba").read_bytes()
    assert manifest["rom_sha1"] == hashlib.sha1(rom).hexdigest()
    assert {(r["case"], r["side"]) for r in manifest["fixtures"]} == {
        (case, side) for case in rows.EXP_CASES for side in ("a", "b")}
    for entry in manifest["fixtures"]:
        base = (ROOT / entry["seed"]).read_bytes()
        raw, edits = rows.build_exp_seed(base, entry["case"], rom, entry["side"])
        saved = (ROOT / entry["file"]).read_bytes()
        assert hashlib.sha256(base).hexdigest() == entry["seed_sha256"]
        assert hashlib.sha256(raw).hexdigest() == entry["synth_seed_sha256"]
        assert hashlib.sha256(saved).hexdigest() == entry["sha256"]
        assert edits == entry["edits"]
        before = f.qualify_one(raw, rr=False, title=f.codec.TITLE_EXPANSION)
        after = f.qualify_one(saved, rr=False, title=f.codec.TITLE_EXPANSION)
        assert f.boot_check_verdict(before, after) == (True, [])
        assert not rows.exp_seed_problems(saved, rows.expansion_facts(rom, entry["case"], entry["side"]))
        assert "SYNTH_QUALIFY PASS" in (ROOT / entry["qualification"]).read_text()
        receipt = (ROOT / entry["qualification"]).read_text()
        assert "seed_sha256=" + entry["synth_seed_sha256"] in receipt
        import re
        match = re.search(r"SYNTH_QUALIFY PASS .*file=(\S+) sha256=([0-9a-f]{64})", receipt)
        assert match and match[1].replace("\\", "/") == entry["file"] and match[2] == entry["sha256"]


def test_all_exp_acquisition_cases_are_registered_with_real_carriers():
    from tools import e2e_duo as d
    for name in ("gift_gen3", "egg_hatch_gen3", "egg_receive_gen3", "choice_gift_gen3", "gift_box_gen3"):
        assert d.scenario_applies(name, "gen3_exp")
        assert d.SCENARIOS[name]["scenario_module"] == "gift_egg"
        assert d.SCENARIOS[name]["oracle"] == "assert_gift_egg_gen3_saved"


def test_exp_trace_controls_the_actual_wire_contract():
    pack = json.loads((ROOT / "data/games/gen3_exp/28877d73/engine_signals.json").read_text())
    site = pack["titles"][TITLE]["artifacts"]["clean"]["sites"]["hatch"]
    cap = {"key":"12345678:12345678", "area_id":"gift_daycare", "is_egg":False,"gift":True}
    def mark(tag,doc):
        return tag + " " + json.dumps(doc) + "\n"
    text = (mark("ACQUISITION_BEFORE",{"captures":0,"balls":3})
            + mark("ACQUISITION_SIGNAL",{"kind":"hatch","address":site["address"] + site["capture_offset"]})
            + "TX capture " + cap["key"] + " " + json.dumps(cap) + "\n"
            + mark("ACQUISITION_AFTER",{"balls":3,"egg":0})
            + mark("ACQUISITION_READY",cap))
    assert rows.exp_trace_problems(text, "hatch") == []
    for changed in (text.replace(str(site["address"] + site["capture_offset"]),"123"),
                    text.replace('"captures": 0','"captures": 1'),
                    text.replace('"balls": 3','"balls": 2',1),
                    text.replace("TX capture ","TX no_catch ",1),
                    text + "TX capture " + cap["key"] + " " + json.dumps(cap) + "\n",
                    text + "TX capture broken {malformed\n"):
        assert rows.exp_trace_problems(changed, "hatch")


def test_saved_location_projection_uses_the_real_decoder_box_dictionary():
    from tools import e2e_duo as h
    party, boxes = h.gen3_decode((ROOT / "tests/fixtures/gen3/exp_pc.sav").read_bytes(), title=TITLE)
    assert isinstance(boxes, dict) and boxes
    combined = rows.saved_records(party, boxes)
    assert len(combined) == len(party) + len(boxes)
    assert combined[len(party)] is next(iter(boxes.values()))


def test_near_hatch_experience_uses_native_level_one_not_vanilla_zero():
    from tools import gen3_fixtures as f, gen_gen3_profile as profile

    context = profile.expansion_inputs()
    raw, _ = rows.build_exp_seed((ROOT / "tests/fixtures/gen3/exp_pc.sav").read_bytes(), "hatch", context["rom"])
    party = f.codec.party_from_save(raw, title=TITLE, layout=f._record_layout(TITLE))
    species = json.loads((ROOT / "data/games/gen3_exp/28877d73/data.json").read_text())["species"][party[1]["species"]]
    import struct
    symbol = profile.expansion_symbol(context, "gExperienceTables")
    expected = struct.unpack_from("<I",context["rom"],symbol["address"]-0x08000000+4*(species["growthRate"]*101+1))[0]
    assert expected == 1  # pinned Medium Slow level1; EXP0 is level0 in this fork
    assert party[1]["experience"] == expected


def test_extra_diagnostic_hooks_are_opt_in_and_include_mirror_aliases(monkeypatch):
    rom = (ROOT / ".cache/expansion-output/reference/pokeemerald.gba").read_bytes()
    monkeypatch.delenv("SLINK_EXP_ACQ_PROBES", raising=False)
    assert rows.expansion_facts(rom)["probes"] == []
    monkeypatch.setenv("SLINK_EXP_ACQ_PROBES", "1")
    probes = rows.expansion_facts(rom)["probes"]
    assert len(probes) == 6
    assert all(p["address"] >= 0x0A000000 for p in probes if p["name"].endswith("_mirror"))
