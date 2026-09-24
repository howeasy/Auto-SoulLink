"""Card U1G: the multi-run engine-site receipt (gen2-engine-site-receipt-v2) and its O-33 synthetic runs.

The proven set is the union of the runs' proven sets. Each run is validated like a v1 receipt, and a site's
requires_prior must be proven in the SAME run: a union never supplies a causal prerequisite. A synthetic fixture is
accepted only inside a v2 run. Such a run carries its disclosure, and every party/box-mutating site it proves (from
the pack: an acquisition/identity signal past its "before" phase) carries a live RAM-effect record:
  - the effect bytes are wPartyCount, wPartySpecies[slot] or sBoxCount at the pack's own address;
  - before_hex equals the probe's arming-time read of those bytes (arming_frame at or after the run's arrival);
  - after_hex is read inside the aligned callback, differs from before, and never equals the setup's bytes there.
The capture RAM-effect frame alignment must come from at least one non-synthetic run. A synthetic run binds to the
committed disclosure of its fixture (reports[<fixture>]) and through it to its base fixture's passed report."""
from __future__ import annotations

import copy
import json

import pytest

from tests.unit.test_gen2_signals import FIXTURE_SHA256, QUALIFICATION, U1_EXPECT, World, production, receipt

V2 = "gen2-engine-site-receipt-v2"
TITLES = ["crystal", "gold", "silver"]


def addr(world, symbol):
    for site in world.sites.values():
        if symbol in site["point_symbols"]:
            return site["point_symbols"][symbol]["addr"]
    raise KeyError(symbol)


def effect(world, site, symbol, before, after, *, offset=0):
    return {"site": site, "symbol": symbol, "wram": addr(world, symbol) + offset, "size": len(before) // 2,
            "arming_frame": 55, "arming_hex": before, "before_hex": before, "hit_frame": 102, "callback": 102,
            "after_hex": after}


def disclosure(world, fixture):
    return {"schema": "gen2-synth-disclosure-v1", "builder": "tools/gen2_synth_fixtures.py", "title": world.title,
            "base_fixture": f"{world.title}_battle", "base_sha256": "cd" * 32, "sha256": "ab" * 32,
            "fields": [{"symbol": "wPartyCount", "offset": 0, "wram": addr(world, "wPartyCount"), "size": 1,
                        "old_hex": "01", "new_hex": "05"}],
            "source_facts": ["macros/ram.asm party_struct"], "edits": {}}


def synth_run(world, proven=("capture_box", "capture_box_finalized"), effects=None, kind="grass"):
    run = receipt(world, proven)
    run["fixture"] = f"{world.title}_synth_{kind}"
    run["fixture_sha256"] = "ab" * 32
    run["arrival_frame"] = 50
    run["frame_alignment"] = {"passed": True, "aligned_hits": 3, "misaligned_hits": 0}
    run["synth"] = disclosure(world, run["fixture"])
    run["effects"] = effects if effects is not None else [
        effect(world, "capture_box", "sBoxCount", "00", "01"), effect(world, "capture_box_finalized", "sBoxCount", "00", "01")]
    return run


def v2(world, *runs):
    return {"schema": V2, "title": world.title, "runs": list(runs)}


def registered(world, qualification):
    binder, why = production(world, qualification)
    if binder is None:
        return None, why
    return sorted(binder.status(binder).registered_sites.values()), None


@pytest.mark.parametrize("title", TITLES)
def test_a_v2_receipt_registers_the_union_of_its_runs(title):
    world = World(title)
    sites, why = registered(world, v2(world, receipt(world), synth_run(world)))
    assert sites == sorted(set(U1_EXPECT) | {"capture_box", "capture_box_finalized"}), why


def test_a_v1_receipt_still_registers_unchanged():
    world = World()
    assert registered(world, receipt(world))[0] == sorted(U1_EXPECT)


@pytest.mark.parametrize("title", TITLES)
def test_a_final_whose_prior_is_only_in_another_run_is_rejected(title):
    world = World(title)
    first = receipt(world, (*U1_EXPECT, "capture_box"))
    second = synth_run(world, ("capture_box_finalized",),
                       effects=[effect(world, "capture_box_finalized", "sBoxCount", "00", "01")])
    sites, why = registered(world, v2(world, first, second))
    assert sites is None and "prior" in why and world.callbacks == {}


@pytest.mark.parametrize("title", TITLES)
def test_a_synthetic_fixture_is_refused_outside_a_v2_run(title):
    world = World(title)
    alone = synth_run(world, U1_EXPECT, effects=[])
    alone["frame_alignment"] = copy.deepcopy(receipt(world)["frame_alignment"])
    sites, why = registered(world, alone)
    assert sites is None and "synthetic" in why and world.callbacks == {}


FAULTS = ["no_disclosure", "disclosure_schema", "disclosure_builder", "disclosure_no_fields", "disclosure_no_facts",
          "disclosure_other_bytes", "no_effect", "effect_unchanged", "effect_is_the_setup_value",
          "effect_before_not_the_arming_read", "effect_arming_before_arrival", "effect_arming_after_the_hit",
          "effect_misaligned", "effect_wram_null_equal_to_setup", "effect_wram_elsewhere", "effect_unrelated_site",
          "contest_insert_without_effect", "no_live_capture_alignment", "other_rom", "empty_runs"]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("fault", FAULTS)
def test_a_faulty_v2_receipt_registers_nothing(title, fault):
    world = World(title)
    first, second = receipt(world), synth_run(world)
    e = second["effects"][0]
    d = second["synth"]
    if fault == "no_disclosure":
        del second["synth"]
    elif fault == "disclosure_schema":
        d["schema"] = "made-up"
    elif fault == "disclosure_builder":
        d["builder"] = "tools/hand_edit.py"
    elif fault == "disclosure_no_fields":
        d["fields"] = []
    elif fault == "disclosure_no_facts":
        d["source_facts"] = []
    elif fault == "disclosure_other_bytes":
        d["sha256"] = "ef" * 32
    elif fault == "no_effect":
        second["effects"] = []
    elif fault == "effect_unchanged":
        e["after_hex"] = e["before_hex"]
    elif fault == "effect_is_the_setup_value":
        second["effects"] = [effect(world, "capture_box", "wPartyCount", "04", "05"), second["effects"][1]]
    elif fault == "effect_before_not_the_arming_read":
        e["before_hex"] = "07"
    elif fault == "effect_arming_before_arrival":
        e["arming_frame"] = 40
    elif fault == "effect_arming_after_the_hit":
        e["arming_frame"] = 102
    elif fault == "effect_misaligned":
        e["callback"] = 103
    elif fault == "effect_wram_null_equal_to_setup":
        e.update(symbol="wPartyCount", wram=None, before_hex="04", after_hex="05")
    elif fault == "effect_wram_elsewhere":
        e["wram"] += 1
    elif fault == "effect_unrelated_site":
        e["site"] = "hatch_species"
    elif fault == "contest_insert_without_effect":
        second = synth_run(world, ("contest_box_inserted",), effects=[])
    elif fault == "no_live_capture_alignment":
        first = synth_run(world, U1_EXPECT, effects=[effect(world, "capture_party", "wPartyCount", "05", "06"),
                                                     effect(world, "capture_party_finalized", "wPartyCount", "05", "06")])
        first["frame_alignment"] = copy.deepcopy(receipt(world)["frame_alignment"])
    elif fault == "other_rom":
        second["rom_sha1"] = "0" * 40
    sites, why = registered(world, v2(world) if fault == "empty_runs" else v2(world, first, second))
    assert sites is None and why and world.callbacks == {}, fault


@pytest.mark.parametrize("title", TITLES)
def test_a_synthetic_setup_value_is_a_legal_baseline_for_a_live_transition(title):
    """O-33 + coordinator ruling: the disclosed party count 5 may be the BEFORE (the arming read) of a live 5 -> 6;
    only an AFTER equal to the disclosed bytes is refused."""
    world = World(title)
    second = synth_run(world, ("capture_party", "capture_party_finalized"),
                       effects=[effect(world, "capture_party", "wPartyCount", "05", "06"),
                                effect(world, "capture_party_finalized", "wPartyCount", "05", "06")])
    assert registered(world, v2(world, receipt(world), second))[0] == sorted(U1_EXPECT)


def test_the_synthetic_fixtures_are_allow_listed_and_marked_synthetic():
    module = World().module
    for title in TITLES:
        listed = set(module.U1_FIXTURES[title].values())
        synth = {name for name in module.SYNTH_FIXTURES.values() if name.startswith(title + "_")}
        assert synth == {f"{title}_synth_{kind}" for kind in ("grass", "kyle", "bill")} and synth <= listed


def test_v2_binding_ties_a_synthetic_run_to_its_committed_disclosure_and_qualified_base():
    """A synthetic run binds to reports[<its fixture>], the committed disclosure (same bytes, same base, same
    fields), and through it to the base fixture's passed report."""
    world = World()
    committed = disclosure(world, "crystal_synth_grass")
    committed["base_sha256"] = FIXTURE_SHA256
    reports = {"crystal_battle": json.loads(QUALIFICATION.read_text()), "crystal_synth_grass": committed}

    def bind(qualification, reports=reports):
        result = world.module.bind_fixture_qualification(world.lua.table_from(qualification, recursive=True),
                                                         world.lua.table_from(reports, recursive=True))
        return result if isinstance(result, tuple) else (result, None)

    good = synth_run(world)
    good["synth"] = copy.deepcopy(committed)
    assert bind(v2(world, receipt(world), good)) == (True, None)
    for fault in ("fake_sha", "run_disclosure_differs", "no_committed_disclosure", "base_sha", "base_name",
                  "attempt", "first_run"):
        second, first, table = copy.deepcopy(good), receipt(world), copy.deepcopy(reports)
        if fault == "fake_sha":
            second["fixture_sha256"] = second["synth"]["sha256"] = "ef" * 32
        elif fault == "run_disclosure_differs":
            second["synth"]["fields"][0]["new_hex"] = "04"
        elif fault == "no_committed_disclosure":
            del table["crystal_synth_grass"]
        elif fault == "base_sha":
            table["crystal_synth_grass"]["base_sha256"] = second["synth"]["base_sha256"] = "0" * 64
        elif fault == "base_name":
            table["crystal_synth_grass"]["base_fixture"] = second["synth"]["base_fixture"] = "crystal_town"
        elif fault == "attempt":
            second["qualification_attempt_id"] = "other"
        else:
            first["fixture_sha256"] = "0" * 64
        ok, why = bind(v2(world, first, second), table)
        assert ok is None and why, fault


# --- card U1G: the direct gift (givepoke) is published once its caller is qualified by the generated gifts pack ---

BILL = {"group": 11, "number": 6, "bank": 21, "addr": 19461, "species": 133}   # crystal gifts.json BillScript row


def gift_world(*, gifts=True):
    world = World()
    options = world.options()
    if gifts:
        options.gifts = world.lua.table_from(world.read_pack("gifts"), recursive=True)
    result = world.module.new_model(options)
    binder = result[0] if isinstance(result, tuple) else result
    assert binder is not None, result
    world.field("wMapGroup", BILL["group"])
    world.field("wMapNumber", BILL["number"])
    world.field("wScriptBank", BILL["bank"])
    world.field("wScriptPos", BILL["addr"] + 40, 2)
    world.field("wCurPartySpecies", BILL["species"])
    return world, binder


def give(world, binder, species=BILL["species"]):
    world.fire("gift_begin")
    world.party([world.mon(), world.mon(species=species, dvs=0x1357)])
    world.field("wCurPartyMon", 1)
    world.set_guards("gift_party_finalized")
    world.fire("gift_party_finalized")
    return world.events(binder)


def test_a_qualified_givepoke_publishes_one_gift_capture_with_the_pack_area():
    world, binder = gift_world()
    [event] = give(world, binder)
    assert (event.kind, event.acquisition, event.area_id, event.destination, event.slot) == (
        "capture", "gift", "goldenrod_city", "party", 1)
    assert event.gift_id == "BillsFamilysHouse:BillScript:27" and event.mon.species_id == 133
    assert event.mon.key == "1357:1234:85"


@pytest.mark.parametrize("fault", ["other_map", "script_before_the_label", "other_bank", "other_species",
                                   "no_insert"])
def test_an_unqualified_gift_caller_or_result_publishes_nothing(fault):
    world, binder = gift_world()
    if fault == "other_map":
        world.field("wMapNumber", BILL["number"] + 1)
    elif fault == "script_before_the_label":
        world.field("wScriptPos", BILL["addr"] - 1, 2)
    elif fault == "other_bank":
        world.field("wScriptBank", BILL["bank"] + 1)
    if fault == "no_insert":
        world.fire("gift_begin")
        world.set_guards("gift_party_finalized")
        world.fire("gift_party_finalized")
        events = world.events(binder)
    else:
        events = give(world, binder, species=25 if fault == "other_species" else BILL["species"])
    assert events == [] and binder.status(binder).refusals, fault


def test_without_the_gifts_pack_the_gift_stays_open():
    world, binder = gift_world(gifts=False)
    assert give(world, binder) == []
    assert "OPEN" in binder.status(binder).refusals.gift_begin
