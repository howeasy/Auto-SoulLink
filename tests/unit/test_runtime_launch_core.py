"""Portable shared launcher and read-only journal checks, without Gen1 dependencies."""

import hashlib
import sqlite3

import pytest
from lupa import LuaRuntime

from server.journal_reader import read_journal
from server.protocol_journal import JournalError, ProtocolJournal
from server.runtime_launcher import file_bundle, render_launcher


def test_bundle_keeps_binary_bytes_exact_and_normalizes_only_text_line_endings(tmp_path):
    (tmp_path / "lua").mkdir()
    (tmp_path / "lua/slink.lua").write_bytes(b"return true\r\n")
    (tmp_path / "library.dll").write_bytes(b"\x00\xff\r\n")
    bundle = file_bundle(tmp_path, ["lua/slink.lua", "library.dll"])
    by_path = {item["path"]: item for item in bundle}
    assert by_path["library.dll"]["sha256"] == hashlib.sha256(b"\x00\xff\r\n").hexdigest()
    assert by_path["lua/slink.lua"]["sha256"] == hashlib.sha256(b"return true\n").hexdigest()
    configuration = {"run_id": "a" * 32, "player": "b", "files": bundle}
    source = render_launcher(
        configuration, host="::1", port=9000, name='@FILES@\n"end"', root_hint=str(tmp_path)
    )
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().source = source
    assert lua.eval("load(source)") is not None
    assert source.splitlines()[0].endswith('@FILES@ "end"')


@pytest.mark.parametrize(
    "path", ["../secret.lua", "C:/secret.lua", "/secret.lua", "folder\\file.lua", "a/../file.lua"]
)
def test_bundle_paths_cannot_escape_or_change_platform_meaning(tmp_path, path):
    with pytest.raises(ValueError):
        file_bundle(tmp_path, [path])


def test_renderer_cannot_skip_verifying_its_entrypoint():
    config = {
        "run_id": "a" * 32,
        "player": "a",
        "files": [{"path": "other.lua", "sha256": "b" * 64, "encoding": "raw"}],
    }
    with pytest.raises(ValueError, match="entrypoint"):
        render_launcher(config, host="localhost", port=9000)


def test_reader_observes_committed_wal_without_changing_the_writer(tmp_path):
    path = tmp_path / "journal.sqlite3"
    with_journal = ProtocolJournal(path, run_id="a" * 32, contract_hash="b" * 64)
    try:
        with_journal.bootstrap({"schema": "shared-test-v1", "value": 1})
        before = with_journal.snapshot()
        with_journal.commit(
            "a",
            "c" * 32,
            {"event": "change"},
            expected_revision=before.revision,
            state={"schema": "shared-test-v1", "value": 2},
            commands={"a": [], "b": []},
            result={"ack": "ACK"},
        )
        current = with_journal.snapshot()
        assert read_journal(path, run_id="a" * 32, contract_hash="b" * 64).snapshot == current
        assert with_journal.snapshot() == current
        with pytest.raises(JournalError):
            read_journal(path, run_id="f" * 32)
    finally:
        with_journal.close()
    before_bytes = path.read_bytes()
    assert read_journal(path).snapshot == current
    assert path.read_bytes() == before_bytes


@pytest.mark.parametrize(
    "damage",
    [
        "checksum",
        "negative_revision",
        "fractional_revision",
        "oversized_revision",
        "extra_metadata",
    ],
)
def test_reader_refuses_corrupt_snapshot_or_metadata_without_repair(tmp_path, damage):
    path = tmp_path / "journal.sqlite3"
    journal = ProtocolJournal(path, run_id="a" * 32, contract_hash="b" * 64)
    journal.bootstrap({"schema": "fixture-v1"})
    journal.close()
    db = sqlite3.connect(path)
    if damage == "checksum":
        db.execute("UPDATE snapshot SET digest=?", ("0" * 64,))
    elif damage == "extra_metadata":
        db.execute("INSERT INTO metadata VALUES ('unexpected','value')")
    else:
        value = {"negative_revision": -1, "fractional_revision": 1.5, "oversized_revision": 2**53}[
            damage
        ]
        db.execute("UPDATE snapshot SET revision=?", (value,))
    db.commit()
    db.close()
    before = path.read_bytes()
    with pytest.raises(JournalError):
        read_journal(path)
    assert path.read_bytes() == before
