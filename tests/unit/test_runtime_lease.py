"""Actual OS writer exclusion and independent WAL readers; no emulator launches."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from server.journal_reader import read_journal
from server.protocol_journal import ProtocolJournal
from server.runtime_lease import RuntimeLease

ROOT = Path(__file__).resolve().parents[2]
CHILD = """
import json, os, sys
from server.runtime_lease import RuntimeLease
from server.journal_reader import read_journal
if sys.argv[1] == 'acquire':
    try:
        with RuntimeLease(sys.argv[2]):
            result = {'acquired': True}
    except RuntimeError as error:
        result = {'acquired': False, 'reason': str(error)}
else:
    read = read_journal(sys.argv[2])
    result = {'run_id': read.run_id, 'revision': read.snapshot.revision, 'state': read.snapshot.state}
print(json.dumps(dict(result, pid=os.getpid())))
"""


def child(action, path):
    # run() bounds and waits for this exact child; its timeout only stops that
    # Popen. No discovery, name-based cleanup or persistent background process.
    completed = subprocess.run([sys.executable, "-c", CHILD, action, str(path)],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["pid"] != os.getpid()
    return result


def test_actual_two_handle_exclusion_and_failed_contender_close_preserve_first_owner(tmp_path):
    path = tmp_path / "writer.lock"
    with RuntimeLease(path):
        contender = RuntimeLease(path)
        with pytest.raises(RuntimeError, match="another server owns this runtime"):
            contender.__enter__()
        contender.__exit__(None, None, None)
        # Closing the failed acquisition must not unlock the first handle.
        with pytest.raises(RuntimeError, match="another server owns this runtime"), RuntimeLease(path):
            pytest.fail("failed contender released the owner")
    assert path.is_file()  # A remaining lock file alone does not establish ownership.
    with RuntimeLease(path):
        pass


def test_actual_child_process_is_excluded_then_can_acquire_after_parent_close(tmp_path):
    path = tmp_path / "writer.lock"
    with RuntimeLease(path):
        denied = child("acquire", path)
        assert denied["acquired"] is False and "another server owns this runtime" in denied["reason"]
        with pytest.raises(RuntimeError), RuntimeLease(path):
            pytest.fail("child's failed attempt released the parent")
    assert child("acquire", path)["acquired"] is True
    # The completed child's exact handle no longer excludes a new owner.
    with RuntimeLease(path):
        pass


@pytest.mark.parametrize("exception", [False, True])
def test_normal_and_exceptional_context_exit_permit_reacquisition(tmp_path, exception):
    class BodyFailure(Exception):
        pass

    path = tmp_path / "writer.lock"
    lease = RuntimeLease(path)
    if exception:
        with pytest.raises(BodyFailure, match="body failed"), lease:
            raise BodyFailure("body failed")
    else:
        with lease:
            pass
    with RuntimeLease(path), pytest.raises(RuntimeError), lease:
        pytest.fail("closed original bypassed a new owner")
    with lease:
        pass


def test_actual_wal_journal_readers_remain_available_while_writer_lease_is_held(tmp_path):
    path = tmp_path / "journal.sqlite3"
    with RuntimeLease(tmp_path / "writer.lock"):
        journal = ProtocolJournal(path, run_id="a" * 32, contract_hash="b" * 64)
        try:
            assert journal._db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            journal._db.execute("PRAGMA wal_autocheckpoint=0")
            journal.bootstrap({"schema": "lease-reader-fixture-v1", "value": 0})
            journal.commit("a", "c" * 32, {"event": "first"}, expected_revision=0,
                state={"schema": "lease-reader-fixture-v1", "value": 1},
                commands={"a": [], "b": []}, result={"ack": "ACK"})
            wal = Path(str(path) + "-wal")
            assert wal.is_file() and wal.stat().st_size > 0
            expected = journal.snapshot()
            assert read_journal(path, run_id="a" * 32, contract_hash="b" * 64).snapshot == expected
            read = child("read", path)
            assert read["run_id"] == "a" * 32 and read["revision"] == expected.revision
            assert read["state"] == expected.state
            assert journal.snapshot() == expected
            journal.commit("a", "d" * 32, {"event": "second"}, expected_revision=expected.revision,
                state={"schema": "lease-reader-fixture-v1", "value": 2},
                commands={"a": [], "b": []}, result={"ack": "ACK"})
            assert read_journal(path).snapshot == journal.snapshot()
            assert journal.snapshot().state["value"] == 2
        finally:
            journal.close()
