import json

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


def _players(seq, **overrides):
    players = {"a": {"save": _save(f"a{seq}"), "witness": _witness("a", seq)},
               "b": {"save": _save(f"b{seq}"), "witness": _witness("b", seq)}}
    for player, patch in overrides.items():
        players[player] = {**players[player], **patch}
    return players


def _capture(store, seq, **kwargs):
    return store.capture(_players(seq), f"rules-{seq}".encode(), f"identity-{seq}".encode(),
                          "contract-x", f"source-{seq}", **kwargs)


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

    assert second["predecessor"] == first["checkpoint_id"]
    assert store.current() == second


def test_tampered_save_file_makes_load_raise_naming_it(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    manifest = _capture(store, 1)
    save_path = tmp_path / "checkpoints" / manifest["checkpoint_id"] / "a.sav"
    save_path.write_bytes(b"\xff" * SAVE_SIZE)

    with pytest.raises(CheckpointError, match="a.sav"):
        store.load(manifest["checkpoint_id"])


def test_failure_before_current_update_leaves_current_untouched(tmp_path, monkeypatch):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)

    real_replace = paired_save_checkpoints.os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated failure renaming into place")
        return real_replace(src, dst)

    monkeypatch.setattr(paired_save_checkpoints.os, "replace", flaky_replace)

    with pytest.raises(OSError):
        _capture(store, 2)

    assert store.current() == first
    checkpoints_dir = tmp_path / "checkpoints"
    dirs = [p for p in checkpoints_dir.iterdir() if p.is_dir()]
    assert len(dirs) == 1
    assert dirs[0].name == first["checkpoint_id"]


@pytest.mark.parametrize("mutate,message", [
    (lambda p: p.pop("b"), "both players are required"),
    (lambda p: p["a"].pop("witness"), "missing save or witness"),
    (lambda p: p["a"].__setitem__("save", b""), "exactly"),
    (lambda p: p["a"].__setitem__("save", b"x" * (SAVE_SIZE - 1)), "exactly"),
    (lambda p: p["a"]["witness"].pop("digest"), "witness is missing required keys"),
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


def test_history_order_and_broken_pointer(tmp_path):
    store = PairedCheckpointStore(tmp_path)
    first = _capture(store, 1)
    second = _capture(store, 2)
    third = _capture(store, 3)

    order = store.history()
    assert [m["checkpoint_id"] for m in order] == [third["checkpoint_id"], second["checkpoint_id"], first["checkpoint_id"]]

    # Break the chain: delete the oldest checkpoint's directory.
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
