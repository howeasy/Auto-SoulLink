"""Offline rejudgment must preserve the original failed evidence and fail closed."""
from types import SimpleNamespace

import pytest

from tools import rejudge_gen1_synth as replay


@pytest.mark.parametrize("fault", [None, "oracle", "mutation"])
def test_rejudge_preserves_original_and_labels_new_verdict(tmp_path, monkeypatch, fault):
    original = tmp_path / "original_pydec.txt"
    original.write_text("PYDEC: FAIL original timeout\n")
    run = SimpleNamespace()
    def oracle(results):
        assert results == {"a": "unmodified receipt"}
        if fault == "oracle":
            raise RuntimeError("saved bag mismatch")
        if fault == "mutation":
            original.write_text("changed concurrently")
    def note(fact):
        with open(run._pydec_path, "a", encoding="utf-8") as handle:
            handle.write(fact + "\n")
    run.attempt = 1
    run._run_oracle, run._pydec_note = oracle, note
    monkeypatch.setattr(replay, "revision", lambda _root: "a" * 40)
    monkeypatch.setattr(replay.subprocess, "check_output", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(replay, "prepare", lambda *_args: (run, {"a": "unmodified receipt"}, [], [original]))
    if fault:
        with pytest.raises(RuntimeError, match="saved bag mismatch|input changed"):
            replay.rejudge(tmp_path, tmp_path, "gen1_new", "explode_new", "lane")
    else:
        replay.rejudge(tmp_path, tmp_path, "gen1_new", "explode_new", "lane")
    verdict = (tmp_path / "rejudged_aaaaaaaa_pydec_result.txt").read_text()
    assert "TARGETED OFFLINE REJUDGMENT rejudged with " + "a" * 40 in verdict
    assert "INPUT_SHA256 " in verdict
    assert ("PYDEC: FAIL" if fault else "PYDEC: PASS") in verdict
    if fault != "mutation":
        assert original.read_text() == "PYDEC: FAIL original timeout\n"
    with pytest.raises(FileExistsError):
        replay.rejudge(tmp_path, tmp_path, "gen1_new", "explode_new", "lane")


def test_rejudge_refuses_dirty_oracle_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "revision", lambda _root: "a" * 40)
    monkeypatch.setattr(replay.subprocess, "check_output", lambda *_args, **_kwargs: " M tools/e2e_duo.py")
    with pytest.raises(RuntimeError, match="commit oracle changes"):
        replay.rejudge(tmp_path, tmp_path, "gen1_new", "explode_new", "lane")
