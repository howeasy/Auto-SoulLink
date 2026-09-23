"""The duo runner picks the right scenarios for `--game`.

`tools/e2e_duo.py` declared a per-scenario `games` key, documented it, and then read it
nowhere: `--scenario all` expanded to the whole table no matter which title was launched. So
`--game gen1 --scenario all` — a command the project's own docs give — booted two Game Boys
and fed them Radical Red scenarios, which died on a savestate no GB fixture has. The key was
load-bearing in exactly one place, `tests/e2e/test_duo.py`, which had hand-rolled its own copy
of the question with a *different* default and so answered it correctly by luck.

These are pure table lookups: no emulator, no server, no ROM. That is the point — the bug they
cover cost several minutes of two-emulator wall-clock per wrong scenario to discover.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import e2e_duo as duo_module  # noqa: E402
from e2e_duo import (  # noqa: E402
    GAMES,
    SCENARIOS,
    DuoRun,
    list_lines as duo_list_lines,
    scenario_applies,
    scenario_attempt_limit,
    scenarios_for,
)

GEN1_NEW_SCENARIOS = ("link_new", "deadzone_new", "linked_faint_bench_new",
                      "linked_faint_active_new", "trade_new", "reconnect_new", "ball_gate_new",
                      "admit_randomized_new", "soft_reset_new", "trade_decline_new",
                      "explode_new", "pc_ops_new", "changebox_new", "whiteout_new",
                      "type_clause_new", "species_clause_new", "poison_new", "rival_swap_new")


@pytest.mark.parametrize("game", sorted(GAMES))
def test_every_game_runs_something(game):
    """A title with an empty selection would report `all passed` having run nothing."""
    assert scenarios_for(game), f"no scenario applies to {game}"


# NOT asserted, and the reason is worth writing down: `faint` and `boxsync` declare
# `"savestate": "slink_overworld.State"` and still run on Gen 1 and Gen 2, which have no
# savestate at all. That is not a contradiction. The launch path branches on the GAME
# (`DuoRun.battery_boot`, from GAMES[game]["uses_savestate"]), so a scenario's savestate is
# Gen 3 data that battery-boot titles never read. The first version of this file asserted the
# tidy-looking invariant instead and failed on three games — the table was right and the test
# was wrong.


@pytest.mark.parametrize("game", sorted(GAMES))
def test_savestate_games_are_never_given_a_batteryless_scenario(game):
    """This direction IS load-bearing: tests/e2e/test_duo.py KeyErrors in `_states_for` on a
    scenario with no savestate, so selecting one for Gen 3 breaks collection of the whole
    module rather than failing a single test."""
    if not GAMES[game]["uses_savestate"]:
        pytest.skip(f"{game} boots from a battery save")
    offenders = [n for n in scenarios_for(game) if "savestate" not in SCENARIOS[n]]
    assert not offenders, (
        f"{game} loads savestates but would be given scenario(s) that declare none: "
        f"{offenders}")


def test_gen3_selection_is_exactly_the_radical_red_set():
    """Pinned rather than derived, so that widening a `games` tuple by accident has to be an
    explicit edit here too. tests/e2e/test_duo.py parametrizes straight off this selection."""
    assert sorted(scenarios_for("gen3_rr")) == sorted(
        ["faint", "boxsync", "trade", "ghost", "infopanel", "explode"])


def test_gen2_runs_the_three_scenarios_crystal_is_verified_on():
    assert sorted(scenarios_for("gen2")) == sorted(["faint", "boxsync", "memorialize"])


def test_the_old_gen1_titles_are_gone():
    """Deletion step 3: the `gen1`/`gen1_yellow` titles, their scenario drivers and the family
    rule that covered them are removed, so every `games` tuple is exact."""
    assert "gen1" not in GAMES and "gen1_yellow" not in GAMES
    for name in ("rivalswap", "explode_g1", "whiteout", "playthrough", "deadzone", "dupes"):
        assert name not in SCENARIOS, name
    assert not hasattr(duo_module, "FAMILIES") or not duo_module.FAMILIES


def test_selection_does_not_leak_across_generations():
    """Exact matching: nothing from another title's set may appear."""
    assert "memorialize" in scenarios_for("gen2") and "memorialize" not in scenarios_for("gen3_rr")
    assert not scenario_applies("trade", "gen2")
    assert not scenario_applies("link_new", "gen2")


def test_the_pytest_wrappers_agree_with_the_runner():
    """The per-generation wrapper hardcodes the scenarios it runs. If it names one the runner
    would refuse for that game, the two have drifted — which is the original bug, just pointing
    the other way."""
    for module, game in (("test_duo_gen2", "gen2"),):
        sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
        mod = __import__(module)
        for name in mod.SCENARIOS:
            assert scenario_applies(name, game), (
                f"{module}.py runs '{name}' on {game}, but the runner would refuse it")


def test_every_gen1_new_scenario_declares_an_oracle_that_exists():
    """A client RESULT is not a verdict: each Gen 1 scenario names the post-result method that
    reads the saved state, and the method has to exist on DuoRun."""
    for name in scenarios_for("gen1_new"):
        method = SCENARIOS[name].get("oracle")
        assert method, f"{name} declares no oracle"
        assert callable(getattr(DuoRun, method, None)), f"{name} names {method}, not a DuoRun method"
        assert isinstance(SCENARIOS[name].get("oracle_kwargs", {}), dict)


def test_other_generations_keep_the_legacy_verdict_path():
    """Gen 2/Gen 3 entries carry no oracle: for them a client RESULT is the whole verdict."""
    for game in ("gen2", "gen3_rr"):
        for name in scenarios_for(game):
            assert "oracle" not in SCENARIOS[name], f"{name} ({game}) declares an oracle"


def test_gen1_new_does_not_inherit_the_old_gen1_family():
    """The family rule exists for gen1_yellow. `gen1_new` is a different client whose driver
    refuses every old scenario name, so `--scenario all --game gen1_new` must select only its
    own eight rather than six scenarios it cannot run."""
    assert sorted(scenarios_for("gen1_new")) == sorted(GEN1_NEW_SCENARIOS)
    assert not scenario_applies("trade", "gen1_new")


def test_the_wrapper_lists_exactly_the_gen1_new_scenarios():
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen1_new")
    assert mod.GAME == "gen1_new"
    assert sorted(mod.SCENARIOS) == sorted(GEN1_NEW_SCENARIOS)


def test_whiteout_new_is_registered_for_gen1_new_and_nothing_else():
    """S-4/W-3's scenario opts in to `gen1_new` alone.

    Both directions matter: an entry that lost its `games` key would match every title the
    family rule does not exclude (the old default), and one written as `("gen1",)` would be
    handed to the gen1 driver, whose scenario table has no `whiteout_new`.
    """
    assert scenario_applies("whiteout_new", "gen1_new")
    assert "whiteout_new" in scenarios_for("gen1_new")
    assert not scenario_applies("whiteout_new", "gen1")
    assert not scenario_applies("whiteout_new", "gen1_yellow")
    assert not scenario_applies("whiteout_new", "gen3_rr")
    assert "whiteout_new" not in scenarios_for("gen2")


def test_the_clause_and_poison_scenarios_opt_in_to_gen1_new_alone():
    """A4's two clause scenarios and A7's poison run gen1_new's driver and nothing else: the
    gen1 family's own table has no such names, and neither does another generation's client."""
    for name in ("type_clause_new", "species_clause_new", "poison_new"):
        assert scenario_applies(name, "gen1_new")
        assert name in scenarios_for("gen1_new")
        assert not scenario_applies(name, "gen1")
        assert not scenario_applies(name, "gen1_yellow")
        assert not scenario_applies(name, "gen3_rr")
        assert name not in scenarios_for("gen2")


def test_the_clause_and_poison_entries_carry_their_flags_oracles_and_fixtures():
    """--type-clause / --species-clause are what make the server's clause machinery run at all
    (state.py:1750 gates the reroll on species_lock, :2629 on type_lock), and poison_new is the
    per-instance fixture case: A on the town fixture, B on the battle one."""
    assert SCENARIOS["type_clause_new"]["flags"] == ["--type-clause"]
    assert SCENARIOS["species_clause_new"]["flags"] == ["--species-clause"]
    assert SCENARIOS["poison_new"]["flags"] == []
    assert SCENARIOS["poison_new"]["target"] == {"a": "town", "b": "battle"}
    assert SCENARIOS["poison_new"]["timeout"] >= 2400
    assert SCENARIOS["poison_new"]["frames"] >= 300000
    for name, oracle in (("type_clause_new", "assert_type_clause_new_saved"),
                         ("species_clause_new", "assert_species_clause_new_saved"),
                         ("poison_new", "assert_poison_new_saved")):
        entry = SCENARIOS[name]
        assert entry["games"] == ("gen1_new",), name
        assert entry["no_setup"] is True and entry["target"], name
        assert entry["oracle"] == oracle
        assert callable(getattr(DuoRun, oracle, None)), name
    assert callable(getattr(DuoRun, "assert_species_clause_release", None))


def test_rival_swap_new_carries_its_flag_and_the_battle_fixture_on_both_halves():
    """The Route 22 rival events are only armed by the `lab,parcel,route1` chain
    (tools/gen1_fixtures.py:40), so A has to boot the battle fixture — and B too, for its party
    to carry a catch for the swap to mirror."""
    entry = SCENARIOS["rival_swap_new"]
    assert entry["flags"] == ["--rival-team-swap"]
    assert entry["target"] == {"a": "battle", "b": "battle"}
    assert entry["no_setup"] is True and entry["games"] == ("gen1_new",)
    assert entry["oracle"] == "assert_rival_swap_new_saved"
    assert callable(getattr(DuoRun, "assert_rival_swap_new_saved", None))
    assert scenario_applies("rival_swap_new", "gen1_new")
    assert not scenario_applies("rival_swap_new", "gen1")


def test_whiteout_new_carries_the_gen1_new_shape_and_both_of_its_gates():
    """The registry entry plus the two methods the orchestration calls: the pre-blackout
    BOTH_BOXED gate (orchestrate) and the post-result oracle (_run_oracle)."""
    entry = SCENARIOS["whiteout_new"]
    assert entry["games"] == ("gen1_new",)
    assert entry["no_setup"] is True and entry["flags"] == []
    assert entry["target"] == "battle" and entry["timeout"] == 1800
    assert entry["oracle"] == "assert_whiteout_new_saved"
    assert callable(getattr(DuoRun, "assert_whiteout_new_saved", None))
    assert callable(getattr(DuoRun, "assert_whiteout_both_boxed", None))


def test_the_wrapper_deadline_covers_every_attempt():
    """r2 finding 2: species_clause_new may run three whole attempts, so a deadline of one
    timeout would kill the third mid-run — the run would read as a crash, not a long scenario."""
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen1_new")
    for name in scenarios_for("gen1_new"):
        assert mod.deadline_for(name) == (SCENARIOS[name]["timeout"]
                                          * scenario_attempt_limit(name, "gen1_new")) + 300, name
    assert mod.deadline_for("species_clause_new") == (
        scenario_attempt_limit("species_clause_new", "gen1_new")
        * SCENARIOS["species_clause_new"]["timeout"] + 300)


def test_the_wrapper_resolves_fixtures_per_instance_not_as_a_cross_product():
    """r2 finding 3: poison_new boots Red/town and Blue/battle. Checking the cross product
    demanded red_battle and blue_town as well — fixtures the scenario never reads."""
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen1_new")
    assert mod.required_fixtures("poison_new") == [("red", "town"), ("blue", "battle")]
    assert mod.required_fixtures("link_new") == [("red", "battle"), ("blue", "battle")]

    present = {"red_town.SaveRAM", "blue_battle.SaveRAM"}
    exists = lambda path: os.path.basename(path) in present  # noqa: E731
    assert mod.missing_fixtures("poison_new", exists=exists) == []
    present.discard("red_town.SaveRAM")
    assert mod.missing_fixtures("poison_new", exists=exists) == [("red", "town")]
    present.discard("blue_battle.SaveRAM")
    assert len(mod.missing_fixtures("poison_new", exists=exists)) == 2


def test_list_lines_carry_the_attempt_limit_and_the_targets():
    """(r): lane cards quote these two numbers, so --list prints them from the same table the
    runner uses."""
    lines = {line.split()[0]: line for line in duo_list_lines("gen1_new")}
    assert lines["species_clause_new"] == "species_clause_new  attempts=8  targets=battle"
    assert lines["poison_new"] == "poison_new  attempts=4  targets=a:town, b:battle"
    assert lines["rival_swap_new"] == "rival_swap_new  attempts=3  targets=a:battle, b:battle"
    assert lines["ball_gate_new"] == "ball_gate_new  attempts=1  targets=town"
    for name in scenarios_for("gen1_new"):
        assert name in lines, name


# ── gen3_frlg: the new Gen 3 client on vanilla FRLG (card C4-6a) ────────────────────────────────
GEN3_FRLG_SCENARIOS = ("faint_cmd_gen3", "linked_faint_active_gen3", "boxsync_gen3",
                       "whiteout_gen3", "link_gen3", "deadzone_gen3", "reconnect_gen3")
# P5 (card C5-5): gen3_rr_new runs the same seven (their `games` tuples EXTENDED, never renamed)
# plus three RR-only scenarios (docs/gen3/PLAN.md §14 P5, minus ghost/trade/infopanel -- the old
# client's `gen3_rr` row keeps those -- and trade_abort, a later card).
GEN3_RR_ONLY_SCENARIOS = ("explode_gen3", "rival_swap_gen3", "native_absent_gen3")
GEN3_RR_NEW_SCENARIOS = GEN3_FRLG_SCENARIOS + GEN3_RR_ONLY_SCENARIOS


def test_gen3_frlg_selection_is_exactly_its_seven():
    """PLAN §5.5's FRLG matrix, pinned: `--scenario all --game gen3_frlg` runs these and only these."""
    assert sorted(scenarios_for("gen3_frlg")) == sorted(GEN3_FRLG_SCENARIOS)


def test_gen3_rr_new_selection_is_the_seven_shared_plus_its_own_three():
    """P5, card C5-5: `--scenario all --game gen3_rr_new` runs the seven gen3_frlg shares PLUS
    explode_gen3/rival_swap_gen3/native_absent_gen3 -- and nothing else (not the old client's
    trade/ghost/infopanel/explode on `gen3_rr`, not any gen1/gen2 name)."""
    assert sorted(scenarios_for("gen3_rr_new")) == sorted(GEN3_RR_NEW_SCENARIOS)
    assert "gen3_rr_new" in duo_module.OPT_IN_GAMES


def test_gen3_frlg_keys_do_not_leak_and_nothing_leaks_in():
    """Opt-in both ways: the `_gen3` keys name only gen3_frlg and gen3_rr_new (P5 adds gen3_rr_new
    by EXTENDING the shared seven's `games` tuple, never by renaming), and the savestate-less
    shared ones (faint/boxsync) and every other row's keys stay out of it."""
    assert "gen3_frlg" in duo_module.OPT_IN_GAMES
    for game in GAMES:
        if game not in ("gen3_frlg", "gen3_rr_new"):
            assert not set(scenarios_for(game)) & set(GEN3_RR_NEW_SCENARIOS), game
    for name in SCENARIOS:
        if name not in GEN3_FRLG_SCENARIOS:
            assert not scenario_applies(name, "gen3_frlg"), name
        if name not in GEN3_RR_NEW_SCENARIOS:
            assert not scenario_applies(name, "gen3_rr_new"), name
    for name in GEN3_FRLG_SCENARIOS:
        assert SCENARIOS[name]["games"] == ("gen3_frlg", "gen3_rr_new"), name
        assert scenario_attempt_limit(name, "gen3_frlg") == 1
        assert scenario_attempt_limit(name, "gen3_rr_new") == 1
    for name in GEN3_RR_ONLY_SCENARIOS:
        assert SCENARIOS[name]["games"] == ("gen3_rr_new",), name


def test_every_gen3_frlg_scenario_declares_an_oracle_that_exists():
    """The row requires an oracle (a missing one FAILS in _run_oracle), and its witness method
    exists beside them."""
    row = GAMES["gen3_frlg"]
    assert row["oracle_required"] is True
    assert callable(getattr(DuoRun, row["save_witness"], None))
    for name in scenarios_for("gen3_frlg"):
        method = SCENARIOS[name].get("oracle")
        assert method and callable(getattr(DuoRun, method, None)), name
        assert method == f"assert_{name}_saved", name


def test_every_gen3_rr_new_scenario_declares_an_oracle_that_exists():
    """P5 (card C5-5): gen3_rr_new's row (its own `save_witness`, `rr=True`) and all ten scenarios."""
    row = GAMES["gen3_rr_new"]
    assert row["oracle_required"] is True and row["rr"] is True
    assert callable(getattr(DuoRun, row["save_witness"], None))
    for name in scenarios_for("gen3_rr_new"):
        method = SCENARIOS[name].get("oracle")
        assert method and callable(getattr(DuoRun, method, None)), name
        assert method == f"assert_{name}_saved", name


def test_the_gen3_rr_new_wrapper_lists_the_shared_seven_plus_its_three():
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen3")
    assert mod.GAME_RR == "gen3_rr_new"
    assert sorted(mod.SCENARIOS_RR) == sorted(GEN3_RR_NEW_SCENARIOS)
    for name in mod.SCENARIOS_RR:
        assert scenario_applies(name, "gen3_rr_new")
        assert mod.deadline_for_rr(name) == SCENARIOS[name]["timeout"] + 300
    assert mod.required_fixtures_rr("boxsync_gen3") == ["rr_battle", "rr_town_b"]
    assert mod.required_fixtures_rr("faint_cmd_gen3") == ["rr_town", "rr_town_b"]


def test_the_gen3_wrapper_lists_exactly_the_gen3_frlg_scenarios():
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen3")
    assert mod.GAME == "gen3_frlg"
    assert sorted(mod.SCENARIOS) == sorted(GEN3_FRLG_SCENARIOS)
    for name in mod.SCENARIOS:
        assert scenario_applies(name, "gen3_frlg")
        assert mod.deadline_for(name) == SCENARIOS[name]["timeout"] + 300
    assert mod.required_fixtures("boxsync_gen3") == ["firered_party_battle", "leafgreen_party_town"]
