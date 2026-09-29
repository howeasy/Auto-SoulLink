"""Replay the RR final-cut whiteout retirement through the real duo oracle."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import e2e_duo as duo  # noqa: E402


KA = "EBEF11DA:2BDDC8BF"
KB = "EBEF11DA:D4223740"
REFUSED = "[a] faint refused: party hidden; waiting for a trustworthy snapshot"
WHITEOUT = "[a] whiteout — force-fainting 1 partner mon(s)"
BATTLE = f"[a] faint → force_faint b:{KB}"


def _replay(tmp_path, monkeypatch, *, case="whiteout", cause="whiteout", status="dead",
            server_lines=(REFUSED, "[a] whiteout", WHITEOUT)):
    (tmp_path / "links.json").write_text(json.dumps({"links": [{
        "a": {"key": KA}, "b": {"key": KB}, "status": status, "cause": cause,
        "initiating_player": "a",
    }]}), encoding="utf-8")
    (tmp_path / "slink.log").write_text("\n".join(server_lines) + "\n", encoding="utf-8")
    run = duo.DuoRun.__new__(duo.DuoRun)
    run.data_dir = str(tmp_path)
    run.game = "gen3_rr"
    run.cfg = {"active_faint_case": case}
    run._link_keys = {"a": KA, "b": KB}
    run._gen3_memorial_box = lambda: 24
    run._gen3_saved = run._gen3_fixture_saved = lambda inst: ([], {})
    run._gen3_limits = lambda inst: {}
    run._pydec_note = lambda fact: None
    # Save and receipt validators have their own tests. Keep their calls observable here while
    # replaying the actual persisted-link and server-log checks in this oracle.
    calls = []
    monkeypatch.setattr(duo, "gen3_last_mon_problems", lambda *a, **kw: calls.append("last") or [])
    monkeypatch.setattr(duo, "gen3_memorial_problems", lambda *a, **kw: calls.append("memorial") or [])
    monkeypatch.setattr(duo, "gen3_receipt_problems", lambda *a, **kw: calls.append("receipt") or [])
    results = {"a": f"LAST_MON_KEPT {KA}\n", "b": f"LAST_MON_KEPT {KB}\n"}
    return run, results, calls


def test_rr_observed_whiteout_retires_link_and_runs_durable_checks(tmp_path, monkeypatch):
    run, results, calls = _replay(tmp_path, monkeypatch)
    receipt_checks = []
    def receipt_check(side, text, **checks):
        calls.append("receipt")
        receipt_checks.append((side, checks))
        return []
    monkeypatch.setattr(duo, "gen3_receipt_problems", receipt_check)
    run.assert_linked_faint_active_whiteout_gen3_saved(results)
    assert calls == ["last", "last", "receipt", "receipt"]
    a_checks = receipt_checks[0][1]
    assert receipt_checks[0][0] == "a"
    assert duo.gen3_tx("whiteout", "-") in a_checks["required"]
    assert (duo.gen3_tx("faint", KA), duo.gen3_tx("whiteout", "-")) in a_checks["ordered"]


@pytest.mark.parametrize("case,cause,status,server_lines", [
    ("wild", "whiteout", "dead", (REFUSED, "[a] whiteout", WHITEOUT)),
    ("whiteout", "whiteout", "alive", (REFUSED, "[a] whiteout", WHITEOUT)),
    ("whiteout", "whiteout", "dead", ("[a] whiteout", WHITEOUT)),
    ("whiteout", "whiteout", "dead", (REFUSED, "[a] whiteout")),
    ("whiteout", "whiteout", "dead", ("[a] whiteout", WHITEOUT, REFUSED)),
    ("whiteout", "whiteout", "dead", (REFUSED, "[a] whiteout", WHITEOUT, BATTLE)),
    ("wild", "battle", "dead", (REFUSED, "[a] whiteout", WHITEOUT)),
])
def test_whiteout_exception_does_not_weaken_other_cases(
        tmp_path, monkeypatch, case, cause, status, server_lines):
    run, results, _ = _replay(tmp_path, monkeypatch, case=case, cause=cause,
                              status=status, server_lines=server_lines)
    with pytest.raises(RuntimeError):
        run.assert_linked_faint_active_gen3_saved(results)


def test_battle_retirement_still_passes_with_battle_propagation(tmp_path, monkeypatch):
    run, results, calls = _replay(tmp_path, monkeypatch, case="wild", cause="battle",
                                  server_lines=(BATTLE,))
    run.assert_linked_faint_active_gen3_saved(results)
    assert calls == ["last", "last", "receipt", "receipt"]
