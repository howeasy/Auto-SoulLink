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

from e2e_duo import GAMES, SCENARIOS, DuoRun, scenario_applies, scenarios_for  # noqa: E402

GEN1_NEW_SCENARIOS = ("link_new", "deadzone_new", "linked_faint_bench_new",
                      "linked_faint_active_new", "trade_new", "reconnect_new", "ball_gate_new",
                      "admit_randomized_new", "soft_reset_new", "trade_decline_new",
                      "explode_new")


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


def test_a_games_entry_matches_the_whole_family():
    """`("gen1",)` has to cover gen1_yellow.

    The Yellow/Red pairing exists so a byte-shift bug shows up as an asymmetry between the two
    halves instead of cancelling out, and tests/e2e/test_duo_gen1.py runs the full scenario
    list against it. Exact-id matching would have silently reduced that pairing to the
    scenarios carrying no `games` key at all — coverage vanishing with nothing going red.
    """
    assert scenarios_for("gen1_yellow") == scenarios_for("gen1")
    assert scenario_applies("rivalswap", "gen1_yellow")


def test_family_matching_does_not_leak_across_generations():
    """Prefix matching must not make "gen1" swallow "gen1x", nor gen2 inherit Gen 1's set."""
    assert not scenario_applies("rivalswap", "gen2")
    assert not scenario_applies("whiteout", "gen3_rr")
    assert not scenario_applies("trade", "gen1")


def test_the_pytest_wrappers_agree_with_the_runner():
    """Each per-generation wrapper hardcodes the scenarios it runs. If one names a scenario the
    runner would refuse for that game, the two have drifted — which is the original bug, just
    pointing the other way."""
    for module, game in (("test_duo_gen1", "gen1"), ("test_duo_gen2", "gen2")):
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
    assert not scenario_applies("playthrough", "gen1_new")
    assert scenarios_for("gen1_yellow") == scenarios_for("gen1")


def test_the_wrapper_lists_exactly_the_gen1_new_scenarios():
    sys.path.insert(0, os.path.join(REPO, "tests", "e2e"))
    mod = __import__("test_duo_gen1_new")
    assert mod.GAME == "gen1_new"
    assert sorted(mod.SCENARIOS) == sorted(GEN1_NEW_SCENARIOS)
