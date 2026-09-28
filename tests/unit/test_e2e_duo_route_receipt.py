"""The expansion duo route is admitted only by its configured row and exact server receipt."""

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import e2e_duo as duo  # noqa: E402


EXP = "emerald_expansion_28877d73"


def _run(tmp_path, flags=()):
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.scenario = "boxsync_gen3"
    run.cfg = dict(duo.SCENARIOS["boxsync_gen3"])
    run.game = "gen3_exp"
    run.gcfg = dict(duo.GAMES["gen3_exp"])
    run.tcp_port, run.http_port = 54321, 8080
    run.data_dir = str(tmp_path)
    run.args = argparse.Namespace(server_flags=list(flags), wire_log=False)
    run._server_run_id = "route-model"
    run._pydec_path = str(tmp_path / "pydec.txt")
    return run


@pytest.mark.parametrize("flags", [
    ["--test-only-route", EXP],
    [f"--test-only-route={EXP}"],
])
def test_user_server_flags_cannot_add_a_test_only_route(tmp_path, flags):
    with pytest.raises(ValueError, match="reserved for the configured game row"):
        _run(tmp_path, flags).server_cmd()


@pytest.mark.parametrize("route_line", [
    "TEST-ONLY route of crystal_ap -> gen3_exp enabled (production refuses it by name; production:false)",
    f"TEST-ONLY route of {EXP} -> gen3_exp enabled (production refuses it by name)",
    f"TEST-ONLY route of {EXP} -> gen3_frlge enabled (production refuses it by name; production:false)",
])
def test_wrong_route_or_missing_production_false_is_not_a_receipt(tmp_path, route_line):
    (tmp_path / "server.log").write_text("2026 [WARNING] " + route_line + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="logged no TEST-ONLY route"):
        _run(tmp_path)._require_test_only_route_receipt(timeout=0)


def test_exact_configured_route_with_production_false_is_receipted(tmp_path):
    line = (f"2026 [WARNING] TEST-ONLY route of {EXP} -> gen3_exp enabled "
            "(production refuses it by name; production:false)")
    (tmp_path / "server.log").write_text(line + "\n", encoding="utf-8")
    assert _run(tmp_path)._require_test_only_route_receipt(timeout=0) == [line]
    assert "production:false" in (tmp_path / "pydec.txt").read_text(encoding="utf-8")
