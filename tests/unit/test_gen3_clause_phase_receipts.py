"""C3: phase-1 PASS cannot stand in for a still-catching phase-2 partner."""
from pathlib import Path
from types import SimpleNamespace

from lupa import LuaRuntime

from tests.unit.test_e2e_duo_lane_isolation import _args
from tools import e2e_duo as h

ROOT = Path(__file__).resolve().parents[2]


def run_for(monkeypatch, tmp_path, attempt=1):
    monkeypatch.setattr(h, "BUILD", str(tmp_path))
    return h.DuoRun("ball_gate_gen3", _args(game="gen3_emerald", scenario="ball_gate_gen3", lane="phase-model"), attempt=attempt)


def test_generated_phase_two_stub_waits_for_its_current_partner(monkeypatch, tmp_path):
    import gen3_fixtures
    run = run_for(monkeypatch, tmp_path)
    monkeypatch.setattr(h, "REPO", str(tmp_path))
    monkeypatch.setattr(gen3_fixtures, "write_gba_run_config", lambda *_: None)
    monkeypatch.setattr(h.subprocess, "Popen", lambda *a, **k: SimpleNamespace())
    run._rom_for = lambda _: "fixture.gba"
    run._phase = {"a": "post_flip", "b": "post_flip"}
    Path(run._result_path("b")).write_text("RESULT: PASS (native first ball saved)\n")
    current = Path(run._phase_result_path("b", "post_flip"))
    current.write_text("BALL_STOCK_READY {}\nTHREW 1\nTHREW 2\n")
    run.launch_instance("a", phase="post_flip", seed=False)
    lua = LuaRuntime()
    lua.execute("dofile=function() end")
    lua.execute(Path(run.stub_path("a")).read_text())
    source = (ROOT / "lua/tests/duo/duo_gen3_main.lua").read_text()
    start, end = source.index("function ctx.partner_result()"), source.index("function ctx.party()")
    lua.execute("ctx={};D=SLINK_DUO\n" + source[start:end])
    assert lua.globals().ctx.partner_done() is False
    current.write_text("CAUGHT B\nRESULT: PASS (caught B)\n")
    assert lua.globals().ctx.partner_done() is True


def test_python_catch_and_key_pollers_read_the_current_phase(monkeypatch, tmp_path):
    run = run_for(monkeypatch, tmp_path)
    run._phase = {"a": "post_flip", "b": "post_flip"}
    for side in ("a", "b"):
        Path(run._result_path(side)).write_text(f"MYKEY 0 OLD_{side}\nCAUGHT OLD_{side}\nRESULT: PASS\n")
        Path(run._phase_result_path(side, "post_flip")).write_text(f"MYKEY 0 NEW_{side}\nCAUGHT NEW_{side}\n")
    run.wait_for = lambda _, predicate, timeout: predicate()
    assert run.wait_keys() == ({0: "NEW_a"}, {0: "NEW_b"})
    assert run._caught("a") == "NEW_a" and run._caught("b") == "NEW_b"


def test_final_result_wait_passes_current_phase_receipts_to_the_oracle(monkeypatch, tmp_path):
    run = run_for(monkeypatch, tmp_path)
    run._phase = {"a": "post_flip", "b": "post_flip"}
    run.wait_for = lambda _, predicate, timeout: predicate()
    for side in ("a", "b"):
        Path(run._result_path(side)).write_text('BALL_FLIP {"balls":1}\nRESULT: PASS\n')
        Path(run._phase_result_path(side, "post_flip")).write_text('BALL_STOCK_READY {"balls":20}\n')
    assert run.wait_results() is None  # old PASS cannot finish a still-running new phase
    for side in ("a", "b"):
        with Path(run._phase_result_path(side, "post_flip")).open("a") as receipt:
            receipt.write(f"CAUGHT NEW_{side}\nRESULT: PASS\n")
    results = run.wait_results()
    assert all("BALL_STOCK_READY" in text and "BALL_FLIP" not in text for text in results)


def test_gen3_retry_preserves_prior_numbered_receipts_but_a_new_run_clears_them(monkeypatch, tmp_path):
    run = run_for(monkeypatch, tmp_path, attempt=2)
    old = tmp_path / "e2e_ball_gate_gen3_a_attempt1_result.txt"
    old.write_text('FAMILY_ENCOUNTER {"species":951}\nRESULT: PASS\n')
    live = Path(run._result_path("a"))
    live.write_text("stale live receipt\n")
    run._clear_attempt_artifacts()
    assert old.is_file() and not live.exists()
    run.attempt = 1
    run._clear_attempt_artifacts()
    assert not old.exists()


def test_rr_family_has_sixteen_opportunities_without_changing_other_titles():
    assert h.scenario_attempt_limit("species_family_gen3", "gen3_rr") == 16
    assert h.scenario_attempt_limit("species_family_gen3", "gen3_frlg") == 8
