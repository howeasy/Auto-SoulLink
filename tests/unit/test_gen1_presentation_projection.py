"""Displaying committed rules must not replay physical proofs or grant authority."""

import pytest

from server.gen1_run_config import create_runtime
from server.protocol_journal import JournalError
from tests.unit.observation_fixture import setup
from tests.unit.test_gen1_sessions import contract


def test_presentation_is_detached_and_does_not_replace_authority_audit(tmp_path, monkeypatch):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        from server import gen1_initial_save_runtime as saves

        original = saves.verify_journal
        checks = []

        def counted(*args):
            checks.append(True)
            return original(*args)

        monkeypatch.setattr(saves, "verify_journal", counted)
        view = runtime._presentation_state()
        assert not view.rules.pokeballs_obtained["a"]
        view.rules.pokeballs_obtained["a"] = True
        view.barrier.set_blockers({**view.barrier.document()["blockers"], "f" * 32: "fixture"})
        published = []
        runtime._publish(lambda rules, status: published.append((rules, status)))
        assert len(published) == 1 and not published[0][0].pokeballs_obtained["a"]
        assert "f" * 32 not in runtime._presentation_state().barrier.document()["blockers"]
        assert checks == []
        runtime.journal._db.execute(
            "UPDATE records SET digest=? WHERE namespace=?", ("0" * 64, saves.COMPONENT)
        )
        with pytest.raises(JournalError):
            runtime.state()
        assert checks
    finally:
        runtime.close()


def test_presentation_still_rejects_corrupt_snapshot(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        runtime.journal._db.execute("UPDATE snapshot SET digest=?", ("0" * 64,))
        with pytest.raises(JournalError):
            runtime._presentation_state()
    finally:
        runtime.close()
