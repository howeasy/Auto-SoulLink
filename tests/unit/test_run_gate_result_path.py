"""run_gate finds a gate's result file: literal patch/build path, or the shared G.open helper."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import run_gate  # noqa: E402


def test_gopen_only_gate_resolves_to_its_result_file():
    # probe_gen3_checkpoint.lua names its file only through G.open (no literal path in source)
    path = run_gate._result_path_for("lua/tests/probe_gen3_checkpoint.lua")
    assert path and os.path.basename(path) == "probe_gen3_checkpoint_result.txt"


def test_literal_path_still_wins():
    path = run_gate._result_path_for("lua/tests/probe_gen3_battle_census.lua")
    assert os.path.basename(path) == "gen3_battle_census_result.txt"
