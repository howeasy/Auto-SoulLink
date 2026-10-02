"""Production routing requires both actual client identities and accepted server HELLOs."""

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
    with pytest.raises(ValueError, match="test-only route flags are not supported"):
        _run(tmp_path, flags).server_cmd()


def test_production_server_argv_contains_no_expansion_override(tmp_path):
    assert "--test-only-route" not in _run(tmp_path).server_cmd()


def test_production_receipt_requires_both_real_client_admissions(tmp_path, monkeypatch):
    run = _run(tmp_path)
    monkeypatch.setattr(run, "_result_path", lambda side: str(tmp_path / f"{side}.txt"))
    server = "\n".join(f"2026-10-02 12:00:00,000 [INFO] [{side}] route {EXP} -> gen3_exp (production)" for side in "ab")
    (tmp_path / "server.log").write_text(server + "\n")
    for side in "ab":
        (tmp_path / f"{side}.txt").write_text(f"[client] [SLink-gen3] gen3_exp/{EXP} (clean by hash) player {side} -> 127.0.0.1:1234 (rom 28877d73)\n")
    proof = run._require_production_route_receipt(timeout=0)
    assert len(proof) == 2
    (tmp_path / "b.txt").write_text("TCP connected\n")
    with pytest.raises(RuntimeError, match="production route"):
        run._require_production_route_receipt(timeout=0)


@pytest.mark.parametrize("change", [
    lambda text: text.replace("[b] route", "[a] route"),
    lambda text: text.replace("player b ->", "player a ->"),
    lambda text: text.replace("28877d73)", "00000000)"),
    lambda text: text.replace("clean by hash", "clean by anchors"),
    lambda text: text.replace("-> gen3_exp (production)", "-> gen3_emerald (production)"),
    lambda text: text + "\nTEST-ONLY admission of gen3_exp/emerald_expansion_28877d73\n",
])
def test_production_route_rejects_each_identity_or_route_mutation(change):
    text = "\n".join(
        line for side in "ab" for line in (
            f"2026 [INFO] [{side}] route {EXP} -> gen3_exp (production)",
            f"[client] [SLink-gen3] gen3_exp/{EXP} (clean by hash) player {side} -> 127.0.0.1:1234 (rom 28877d73)"))
    def accepted(body):
        return all(duo.gen3_production_route_lines(body, body, side, "gen3_exp", EXP, "28877d73") for side in "ab")
    assert accepted(text)
    assert not accepted(change(text))
