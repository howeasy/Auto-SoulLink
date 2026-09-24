"""Card U1G: the multi-run engine-site receipt (gen2-engine-site-receipt-v2) and its O-33 synthetic runs.

The proven set is the union of the runs' proven sets. Each run is validated like a v1 receipt, and a site's
requires_prior must be proven in the SAME run: a union never supplies a causal prerequisite. A run on a synthetic
fixture carries its disclosure, and every acquisition/identity site it proves carries a live RAM-effect record: an
effect sampled after the run's arrival, changing before the callback, and never equal to the bytes the setup wrote.
The capture RAM-effect frame alignment must come from at least one non-synthetic run."""
from __future__ import annotations

import copy

import pytest

from tests.unit.test_gen2_signals import U1_EXPECT, World, production, receipt

V2 = "gen2-engine-site-receipt-v2"
SYNTH = "crystal_synth_grass"
PARTY_COUNT = 0xDCD7


def synth_run(world, proven=("capture_box", "capture_box_finalized"), effects=None):
    run = receipt(world, proven)
    run["fixture"] = SYNTH
    run["fixture_sha256"] = "ab" * 32
    run["arrival_frame"] = 50
    run["frame_alignment"] = {"passed": True, "aligned_hits": 3, "misaligned_hits": 0}
    run["synth"] = {"schema": "gen2-synth-disclosure-v1", "builder": "tools/gen2_synth_fixtures.py",
                    "base_fixture": "crystal_battle", "base_sha256": "cd" * 32, "sha256": "ab" * 32,
                    "fields": [{"symbol": "wPartyCount", "offset": 0, "wram": PARTY_COUNT, "size": 1,
                                "old_hex": "01", "new_hex": "06"}],
                    "source_facts": ["macros/ram.asm party_struct"]}
    run["effects"] = effects if effects is not None else [
        {"site": "capture_box", "symbol": "sBoxCount", "wram": None, "size": 1, "before_frame": 60,
         "before_hex": "00", "armed": 102, "callback": 102, "after_hex": "01"}]
    return run


def v2(*runs):
    return {"schema": V2, "title": "crystal", "runs": list(runs)}


def registered(world, qualification):
    binder, why = production(world, qualification)
    if binder is None:
        return None, why
    return sorted(binder.status(binder).registered_sites.values()), None


def test_a_v2_receipt_registers_the_union_of_its_runs():
    world = World()
    sites, why = registered(world, v2(receipt(world), synth_run(world)))
    assert sites == sorted(set(U1_EXPECT) | {"capture_box", "capture_box_finalized"}), why


def test_a_v1_receipt_still_registers_unchanged():
    world = World()
    assert registered(world, receipt(world))[0] == sorted(U1_EXPECT)


def test_a_final_whose_prior_is_only_in_another_run_is_rejected():
    world = World()
    first = receipt(world, (*U1_EXPECT, "capture_box"))
    second = synth_run(world, ("capture_box_finalized",), effects=[])
    sites, why = registered(world, v2(first, second))
    assert sites is None and "prior" in why and world.callbacks == {}


@pytest.mark.parametrize("fault", ["no_disclosure", "disclosure_schema", "disclosure_other_bytes", "no_effect",
                                   "effect_unchanged", "effect_is_the_setup_value", "effect_before_arrival",
                                   "effect_after_callback", "effect_misaligned", "no_live_capture_alignment",
                                   "other_rom", "empty_runs"])
def test_a_faulty_v2_receipt_registers_nothing(fault):
    world = World()
    first, second = receipt(world), synth_run(world)
    effect = second["effects"][0]
    if fault == "no_disclosure":
        del second["synth"]
    elif fault == "disclosure_schema":
        second["synth"]["schema"] = "made-up"
    elif fault == "disclosure_other_bytes":
        second["synth"]["sha256"] = "ef" * 32
    elif fault == "no_effect":
        second["effects"] = []
    elif fault == "effect_unchanged":
        effect["after_hex"] = effect["before_hex"]
    elif fault == "effect_is_the_setup_value":
        effect.update(symbol="wPartyCount", wram=PARTY_COUNT, before_hex="05", after_hex="06")
    elif fault == "effect_before_arrival":
        effect["before_frame"] = 40
    elif fault == "effect_after_callback":
        effect["before_frame"] = 102
    elif fault == "effect_misaligned":
        effect["callback"] = 103
    elif fault == "no_live_capture_alignment":
        first = synth_run(world, U1_EXPECT, effects=[
            {"site": "capture_party", "symbol": "wPartyCount", "wram": PARTY_COUNT, "size": 1, "before_frame": 60,
             "before_hex": "06", "armed": 102, "callback": 102, "after_hex": "07"}])
        first["frame_alignment"] = copy.deepcopy(receipt(world)["frame_alignment"])
    elif fault == "other_rom":
        second["rom_sha1"] = "0" * 40
    sites, why = registered(world, v2() if fault == "empty_runs" else v2(first, second))
    assert sites is None and why and world.callbacks == {}, fault


def test_a_synthetic_setup_value_is_a_legal_baseline_for_a_live_transition():
    """O-33 + coordinator ruling: the disclosed party count 6 may be the BEFORE of a live 6 -> 7 style change;
    only an AFTER equal to the disclosed bytes is refused."""
    world = World()
    second = synth_run(world, ("capture_party", "capture_party_finalized"), effects=[
        {"site": "capture_party", "symbol": "wPartyCount", "wram": PARTY_COUNT, "size": 1, "before_frame": 60,
         "before_hex": "06", "armed": 102, "callback": 102, "after_hex": "07"}])
    assert registered(world, v2(receipt(world), second))[0] == sorted(U1_EXPECT)


def test_the_synthetic_fixtures_are_allow_listed_and_marked_synthetic():
    module = World().module
    for title in ("crystal", "gold", "silver"):
        listed = set(module.U1_FIXTURES[title].values())
        synth = {name for name in module.SYNTH_FIXTURES.values() if name.startswith(title + "_")}
        assert synth == {f"{title}_synth_{kind}" for kind in ("grass", "kyle", "bill")} and synth <= listed


def test_v2_binding_ties_each_run_to_its_qualified_bytes_and_a_synthetic_run_to_its_qualified_base():
    """A synthetic run is bound through its disclosure: the base fixture's passed report names the base bytes the
    builder started from (the synthetic bytes themselves are the disclosure's sha256 = the run's fixture_sha256)."""
    import json

    from tests.unit.test_gen2_signals import FIXTURE_SHA256, QUALIFICATION
    world = World()
    reports = {"crystal_battle": json.loads(QUALIFICATION.read_text())}

    def bind(qualification, reports=reports):
        result = world.module.bind_fixture_qualification(world.lua.table_from(qualification, recursive=True),
                                                         world.lua.table_from(reports, recursive=True))
        return result if isinstance(result, tuple) else (result, None)

    good = synth_run(world)
    good["synth"]["base_sha256"] = FIXTURE_SHA256
    assert bind(v2(receipt(world), good)) == (True, None)
    for fault in ("base_sha", "base_name", "attempt", "first_run"):
        second, first = copy.deepcopy(good), receipt(world)
        if fault == "base_sha":
            second["synth"]["base_sha256"] = "0" * 64
        elif fault == "base_name":
            second["synth"]["base_fixture"] = "crystal_town"
        elif fault == "attempt":
            second["qualification_attempt_id"] = "other"
        else:
            first["fixture_sha256"] = "0" * 64
        ok, why = bind(v2(first, second))
        assert ok is None and why, fault
