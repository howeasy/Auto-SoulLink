import hashlib
import json
import os
import threading
import time

import pytest

from server import paired_save_checkpoints
from server.paired_save_checkpoints import CheckpointError, PairedCheckpointStore

SAVE_SIZE = 0x8000


def _save(tag):
    body = f"save-{tag}".encode()
    return body + b"\x00" * (SAVE_SIZE - len(body))


def _witness(player, seq, *, operation_id=None, index=0):
    return {"frame": seq, "digest": f"digest-{player}-{seq}", "projection": "cartram-hex-sha256",
            "index": index, "operation_id": operation_id or f"op-{player}-{seq}"}


def _players(seq):
    return {"a": {"save": _save(f"a{seq}"), "witness": _witness("a", seq)},
            "b": {"save": _save(f"b{seq}"), "witness": _witness("b", seq)}}


def _capture(store, seq, **kwargs):
    return store.capture(_players(seq), f"rules-{seq}".encode(), f"identity-{seq}".encode(),
                          "contract-x", f"source-{seq}", **kwargs)


def _rewrite_manifest(path, mutator):
    document = json.loads(path.read_text())
    mutator(document)
    encoded = json.dumps(document, sort_keys=True, indent=2).encode("utf-8")
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _write_current(checkpoints_dir, checkpoint_id, manifest_sha256):
    (checkpoints_dir / "CURRENT").write_text(json.dumps({"checkpoint_id": checkpoint_id, "manifest_sha256": manifest_sha256}))


# -- happy path / basic chain -------------------------------------------------

def test_happy_capture_current_load(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    manifest = _capture(store, 1)

    assert manifest["schema"] == "slink-paired-checkpoint-v1"
    assert manifest["predecessor"] is None
    assert store.current() == manifest

    checkpoint = store.load(manifest["checkpoint_id"])
    assert checkpoint.save_bytes("a") == _save("a1")
    assert checkpoint.save_bytes("b") == _save("b1")
    assert checkpoint.rules_bytes() == b"rules-1"
    assert checkpoint.identity_bytes() == b"identity-1"


def test_second_capture_supersedes_and_records_predecessor(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)
    second = _capture(store, 2)

    assert second["predecessor"] == {"checkpoint_id": first["checkpoint_id"], "manifest_sha256": _manifest_hash(tmp_path, first)}
    assert store.current() == second


def _manifest_hash(tmp_path, manifest):
    path = tmp_path / "checkpoints" / manifest["checkpoint_id"] / "manifest.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_history_order_and_broken_pointer(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)
    second = _capture(store, 2)
    third = _capture(store, 3)

    order = store.history()
    assert [m["checkpoint_id"] for m in order] == [third["checkpoint_id"], second["checkpoint_id"], first["checkpoint_id"]]

    import shutil
    shutil.rmtree(tmp_path / "checkpoints" / first["checkpoint_id"])

    walked = store.history()
    assert [m["checkpoint_id"] for m in walked[:2]] == [third["checkpoint_id"], second["checkpoint_id"]]
    assert walked[2]["checkpoint_id"] == first["checkpoint_id"]
    assert "error" in walked[2]


def test_history_empty_when_no_checkpoints(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    assert store.history() == []
    assert store.current() is None


def test_manifest_serialization_round_trips_through_json(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    manifest = _capture(store, 1)
    manifest_path = tmp_path / "checkpoints" / manifest["checkpoint_id"] / "manifest.json"
    assert json.loads(manifest_path.read_text()) == manifest


# -- finding 1: concurrent captures must not corrupt CURRENT / the chain -----

def test_concurrent_captures_never_leave_current_dangling(tmp_path, monkeypatch):
    store = PairedCheckpointStore(tmp_path)
    real_replace = os.replace

    def slow_replace(src, dst):
        time.sleep(0.02)
        return real_replace(src, dst)
    monkeypatch.setattr(paired_save_checkpoints.os, "replace", slow_replace)

    errors = []

    def worker(seq):
        try:
            _capture(store, seq)
        except Exception as exc:  # noqa: BLE001 - surfaced via errors, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(seq,)) for seq in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    history = store.history()
    assert len(history) == 2
    assert all("error" not in entry for entry in history)
    newer, older = history
    assert newer["predecessor"]["checkpoint_id"] == older["checkpoint_id"]
    dir_names = {p.name for p in (tmp_path / "checkpoints").iterdir() if p.is_dir()}
    assert dir_names == {newer["checkpoint_id"], older["checkpoint_id"]}


def test_capture_times_out_when_lock_is_held(tmp_path, monkeypatch):
    store = PairedCheckpointStore(tmp_path)
    (tmp_path / "checkpoints").mkdir(parents=True)
    lock_path = tmp_path / "checkpoints" / paired_save_checkpoints.LOCK_NAME
    os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    monkeypatch.setattr(paired_save_checkpoints, "LOCK_TIMEOUT", 0.05)
    monkeypatch.setattr(paired_save_checkpoints, "LOCK_POLL", 0.01)

    with pytest.raises(CheckpointError, match="lock"):
        _capture(store, 1)


# -- finding 2: historical manifests are hash-anchored to their successor ----

def test_tampered_older_manifest_makes_load_raise_naming_manifest(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)
    _capture(store, 2)

    first_path = tmp_path / "checkpoints" / first["checkpoint_id"] / "manifest.json"
    _rewrite_manifest(first_path, lambda doc: doc.__setitem__("source_fingerprint", "tampered"))

    with pytest.raises(CheckpointError, match="manifest.json"):
        store.load(first["checkpoint_id"])


def test_load_of_current_checkpoint_detects_tamper_too(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    manifest = _capture(store, 1)
    path = tmp_path / "checkpoints" / manifest["checkpoint_id"] / "manifest.json"
    _rewrite_manifest(path, lambda doc: doc.__setitem__("source_fingerprint", "tampered"))

    with pytest.raises(CheckpointError, match="manifest.json"):
        store.load(manifest["checkpoint_id"])


def test_history_detects_predecessor_cycle(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)
    second = _capture(store, 2)
    checkpoints_dir = tmp_path / "checkpoints"
    first_path = checkpoints_dir / first["checkpoint_id"] / "manifest.json"
    second_path = checkpoints_dir / second["checkpoint_id"] / "manifest.json"

    first_hash = _rewrite_manifest(first_path, lambda doc: doc.__setitem__(
        "predecessor", {"checkpoint_id": second["checkpoint_id"], "manifest_sha256": "0" * 64}))
    second_hash = _rewrite_manifest(second_path, lambda doc: doc["predecessor"].__setitem__("manifest_sha256", first_hash))
    _write_current(checkpoints_dir, second["checkpoint_id"], second_hash)

    history = store.history()
    assert history[0]["checkpoint_id"] == second["checkpoint_id"]
    assert history[1]["checkpoint_id"] == first["checkpoint_id"]
    assert history[2]["checkpoint_id"] == second["checkpoint_id"]
    assert "cycle" in history[2]["error"]


# -- finding 3: load()/capture() fail open on shape --------------------------

def test_load_rejects_archived_file_shorter_than_declared_size_even_with_matching_hash(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    manifest = _capture(store, 1)
    checkpoint_dir = tmp_path / "checkpoints" / manifest["checkpoint_id"]
    one_byte = b"\x7f"
    (checkpoint_dir / "a.sav").write_bytes(one_byte)
    _rewrite_manifest(checkpoint_dir / "manifest.json", lambda doc: doc["players"]["a"].__setitem__(
        "save_sha256", hashlib.sha256(one_byte).hexdigest()))
    # The successor-recorded hash anchor is gone (there is no successor); re-point CURRENT
    # at the edited manifest's new hash so the edit under test is what load() actually checks.
    new_hash = hashlib.sha256((checkpoint_dir / "manifest.json").read_bytes()).hexdigest()
    _write_current(tmp_path / "checkpoints", manifest["checkpoint_id"], new_hash)

    with pytest.raises(CheckpointError, match="a.sav"):
        store.load(manifest["checkpoint_id"])


def test_capture_refuses_none_contract_fingerprint(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    with pytest.raises(CheckpointError, match="contract_fingerprint"):
        store.capture(_players(1), b"rules", b"identity", None, "source")


def test_load_refuses_path_traversal_checkpoint_id(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    _capture(store, 1)
    with pytest.raises(CheckpointError, match="invalid checkpoint id"):
        store.load("../x")


@pytest.mark.parametrize("mutate,message", [
    (lambda p: p.pop("b"), "both players are required"),
    (lambda p: p["a"].pop("witness"), "missing save or witness"),
    (lambda p: p["a"].__setitem__("save", b""), "exactly"),
    (lambda p: p["a"].__setitem__("save", b"x" * (SAVE_SIZE - 1)), "exactly"),
    (lambda p: p["a"]["witness"].pop("digest"), "witness is missing required keys"),
    (lambda p: p["a"]["witness"].__setitem__("frame", -1), "nonnegative int"),
    (lambda p: p["a"]["witness"].__setitem__("digest", ""), "non-empty string"),
])
def test_capture_refuses_malformed_players(tmp_path, mutate, message):
    store = PairedCheckpointStore(tmp_path)
    players = _players(1)
    mutate(players)
    with pytest.raises(CheckpointError, match=message):
        store.capture(players, b"rules", b"identity", "contract", "source")


def test_capture_refuses_empty_rules(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    with pytest.raises(CheckpointError, match="rules"):
        store.capture(_players(1), b"", b"identity", "contract", "source")


def test_capture_refuses_empty_identity(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    with pytest.raises(CheckpointError, match="identity"):
        store.capture(_players(1), b"rules", b"", "contract", "source")


def test_capture_refuses_same_batch_witness_by_default(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    players = {"a": {"save": _save("a1"), "witness": _witness("a", 1, operation_id="shared-op", index=3)},
               "b": {"save": _save("b1"), "witness": _witness("b", 1, operation_id="shared-op", index=3)}}
    with pytest.raises(CheckpointError, match="same batch"):
        store.capture(players, b"rules", b"identity", "contract", "source")

    manifest = store.capture(players, b"rules", b"identity", "contract", "source", allow_same_batch=True)
    assert manifest["checkpoint_id"]


# -- finding 4: error contract ------------------------------------------------

def test_malformed_current_pointer_raises_checkpoint_error(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    _capture(store, 1)
    (tmp_path / "checkpoints" / "CURRENT").write_bytes(b"{")

    with pytest.raises(CheckpointError):
        store.current()


def test_history_reports_truncated_manifest_as_broken_entry_not_raise(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)
    second = _capture(store, 2)
    (tmp_path / "checkpoints" / first["checkpoint_id"] / "manifest.json").write_bytes(b"{")

    history = store.history()
    assert history[0]["checkpoint_id"] == second["checkpoint_id"]
    assert history[1]["checkpoint_id"] == first["checkpoint_id"]
    assert "error" in history[1]


# -- finding 5: failure windows during capture --------------------------------

def test_capture_failure_after_b_sav_before_manifest_leaves_no_partial_dir(tmp_path, monkeypatch):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)

    real_write_verified = PairedCheckpointStore._write_verified

    def flaky(self, path, data):
        if path.name == "rules.json":
            raise OSError("simulated failure writing rules.json")
        return real_write_verified(self, path, data)
    monkeypatch.setattr(PairedCheckpointStore, "_write_verified", flaky)

    with pytest.raises(OSError):
        _capture(store, 2)

    assert store.current() == first
    dirs = [p.name for p in (tmp_path / "checkpoints").iterdir() if p.is_dir()]
    assert dirs == [first["checkpoint_id"]]


def test_capture_failure_promoting_directory_leaves_current_and_dirs_clean(tmp_path, monkeypatch):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)

    def fail_replace(src, dst):
        raise OSError("simulated directory promotion failure")
    monkeypatch.setattr(paired_save_checkpoints.os, "replace", fail_replace)

    with pytest.raises(OSError):
        _capture(store, 2)
    monkeypatch.undo()

    assert store.current() == first
    dirs = [p.name for p in (tmp_path / "checkpoints").iterdir() if p.is_dir()]
    assert dirs == [first["checkpoint_id"]]


def test_capture_failure_publishing_current_removes_promoted_directory(tmp_path, monkeypatch):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)
    real_replace = os.replace
    calls = {"n": 0}

    def fail_second_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_replace(src, dst)  # directory promotion succeeds
        raise OSError("simulated CURRENT publish failure")
    monkeypatch.setattr(paired_save_checkpoints.os, "replace", fail_second_replace)

    with pytest.raises(OSError):
        _capture(store, 2)
    monkeypatch.undo()

    assert store.current() == first
    dirs = [p.name for p in (tmp_path / "checkpoints").iterdir() if p.is_dir()]
    assert dirs == [first["checkpoint_id"]]  # the promoted-but-unpublished dir was removed


# -- round 3, finding 1: top-level schema completeness -----------------------

def test_history_reports_missing_predecessor_field_as_broken_entry_not_keyerror(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)
    second = _capture(store, 2)
    checkpoints_dir = tmp_path / "checkpoints"
    first_path = checkpoints_dir / first["checkpoint_id"] / "manifest.json"
    second_path = checkpoints_dir / second["checkpoint_id"] / "manifest.json"

    document = json.loads(first_path.read_text())
    del document["predecessor"]  # entirely absent, not null
    encoded = json.dumps(document, sort_keys=True, indent=2).encode("utf-8")
    first_path.write_bytes(encoded)
    new_hash = hashlib.sha256(encoded).hexdigest()
    second_hash = _rewrite_manifest(second_path, lambda doc: doc["predecessor"].__setitem__("manifest_sha256", new_hash))
    _write_current(checkpoints_dir, second["checkpoint_id"], second_hash)

    history = store.history()  # must not raise KeyError
    assert history[0]["checkpoint_id"] == second["checkpoint_id"]
    assert history[1]["checkpoint_id"] == first["checkpoint_id"]
    assert "error" in history[1]
    assert "top-level" in history[1]["error"]


# -- round 3, finding 2: current() validates archived file bytes -------------

def test_current_validates_archived_save_bytes(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    manifest = _capture(store, 1)
    save_path = tmp_path / "checkpoints" / manifest["checkpoint_id"] / "a.sav"
    save_path.write_bytes(b"\xff" * SAVE_SIZE)

    with pytest.raises(CheckpointError, match="a.sav"):
        store.current()


def test_history_does_not_validate_archived_bytes(tmp_path):
    # history() is metadata-only (see its docstring): a corrupt a.sav does not break it.
    store = PairedCheckpointStore(tmp_path)
    manifest = _capture(store, 1)
    (tmp_path / "checkpoints" / manifest["checkpoint_id"] / "a.sav").write_bytes(b"\xff" * SAVE_SIZE)

    history = store.history()
    assert history == [manifest]


# -- round 3, finding 3: _write_current cleans up its own temp file ----------

def test_write_current_failure_leaves_no_orphan_temp_file(tmp_path, monkeypatch):
    store = PairedCheckpointStore(tmp_path)
    _capture(store, 1)
    real_replace = os.replace
    calls = {"n": 0}

    def fail_second_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_replace(src, dst)  # directory promotion succeeds
        raise OSError("simulated CURRENT publish failure")
    monkeypatch.setattr(paired_save_checkpoints.os, "replace", fail_second_replace)

    with pytest.raises(OSError):
        _capture(store, 2)
    monkeypatch.undo()

    checkpoints_dir = tmp_path / "checkpoints"
    leftover_temps = [p.name for p in checkpoints_dir.iterdir() if p.is_file() and p.name.startswith(".CURRENT.tmp-")]
    assert leftover_temps == []


# -- round 3, finding 4: provenance ------------------------------------------

def test_capture_with_provenance_round_trips_through_load(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    provenance = {"journal_revision": 42, "predecessor_run_id": "run-a", "note": None}
    manifest = store.capture(_players(1), b"rules", b"identity", "contract", "source", provenance=provenance)

    assert manifest["provenance"] == provenance
    checkpoint = store.load(manifest["checkpoint_id"])
    assert checkpoint.provenance() == provenance


def test_capture_defaults_provenance_to_empty_object(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    manifest = _capture(store, 1)
    assert manifest["provenance"] == {}


def test_tampering_provenance_makes_load_raise(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    manifest = store.capture(_players(1), b"rules", b"identity", "contract", "source",
                              provenance={"journal_revision": 1})
    path = tmp_path / "checkpoints" / manifest["checkpoint_id"] / "manifest.json"
    _rewrite_manifest(path, lambda doc: doc["provenance"].__setitem__("journal_revision", 999))

    with pytest.raises(CheckpointError, match="manifest.json"):
        store.load(manifest["checkpoint_id"])


@pytest.mark.parametrize("provenance,message", [
    ({str(i): "x" for i in range(33)}, "at most 32 keys"),
    ({"": "x"}, "non-empty string"),
    ({"k": True}, "must be str, int, or null"),
    ({"k": ["nested"]}, "must be str, int, or null"),
    ({"k": "x" * 513}, "exceeds 512 characters"),
])
def test_capture_refuses_malformed_provenance(tmp_path, provenance, message):
    store = PairedCheckpointStore(tmp_path)
    with pytest.raises(CheckpointError, match=message):
        store.capture(_players(1), b"rules", b"identity", "contract", "source", provenance=provenance)
