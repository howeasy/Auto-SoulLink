"""Artifact preflight is independently testable; these are not emulator results."""

import copy
import hashlib
import io
import json
import struct
import zipfile

import pytest

from tools.rr import controlled_load as subject


def busy_header():
    raw = bytearray(64)
    struct.pack_into("<I6H", raw, 0, 0x4B4E4C53, 2, 1, 2, 1, 1, 0)
    raw[40:48] = bytes(range(1, 9))
    return raw


def valid_state(*, core="Core.bin", **changes):
    members = {
        "BizVersion.txt": b"Version 2.11.1\r\n",
        core: bytes(range(256)) * 8,
        "SyncSettings.json": json.dumps(
            {
                "o": {
                    "$type": "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk+SyncSettings, BizHawk.Emulation.Cores",
                    "SkipBios": True,
                }
            }
        ).encode(),
        "UserData.txt": b'{"o":{}}',
    }
    members.update(changes)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return output.getvalue()


def producer_result(data):
    return {
        "complete": True,
        "release_ready": False,
        "identity": {
            "rom_sha1": subject.ROM_SHA1.upper(),
            "rom_sha256": subject.ROM_SHA256,
            "fixture_sha256": subject.BATTERY_SHA256,
        },
        "assertions": [
            {"id": name, "passed": True} for name in sorted(subject.PRODUCER_ASSERTIONS)
        ],
        "evidence": {
            "runtime": {
                "classification": "controlled_busy_ping_state_producer",
                "mode": "produce",
                "produced": {
                    "frame": 1660,
                    "mailbox_hex": busy_header().hex(),
                    "state_sha256": hashlib.sha256(data).hexdigest(),
                },
            }
        },
    }


@pytest.mark.parametrize("core", ["Core.bin", "Core.bin.zst"])
def test_valid_producer_freezes_only_userdata_difference(core):
    data = valid_state(core=core)
    metadata, fault = subject.experiment_metadata(producer_result(data), data)
    assert metadata["core_member"] == core and metadata["saved_frame"] == 1660
    assert metadata["release_ready"] is False and metadata["general_interlock_proved"] is False
    old, new = subject.state_members(data), subject.state_members(fault)
    assert old["UserData.txt"] != new["UserData.txt"]
    assert {k: v for k, v in old.items() if k != "UserData.txt"} == {
        k: v for k, v in new.items() if k != "UserData.txt"
    }


@pytest.mark.parametrize("offset,value", [(6, 23), (4, 1), (10, 2), (14, 1), (16, 1), (48, 1)])
def test_non_ping_or_acknowledged_mutating_marker_refused(offset, value):
    raw = busy_header()
    raw[offset] = value
    with pytest.raises(ValueError):
        subject.busy_ping_header(raw.hex())


@pytest.mark.parametrize(
    "field", ["rom", "complete", "mode", "assertion", "duplicate", "frame", "bytes", "marker"]
)
def test_producer_evidence_must_be_complete_and_exact(field):
    data = valid_state()
    result = producer_result(data)
    runtime = result["evidence"]["runtime"]
    if field == "rom":
        result["identity"]["rom_sha256"] = "f" * 64
    elif field == "complete":
        result["complete"] = False
    elif field == "mode":
        runtime["mode"] = "valid"
    elif field == "assertion":
        result["assertions"].pop()
    elif field == "duplicate":
        result["assertions"].append(copy.deepcopy(result["assertions"][0]))
    elif field == "frame":
        runtime["produced"]["frame"] = True
    elif field == "bytes":
        data += b"changed"
    else:
        runtime["produced"]["mailbox_hex"] = " " * 128
    with pytest.raises(ValueError):
        subject.experiment_metadata(result, data)


@pytest.mark.parametrize(
    "sync",
    [
        b'{"o":{"SkipBios":true}}',
        b'{"o":{"$type":"Other.MGBAHawk+SyncSettings","SkipBios":true}}',
        b"{}",
    ],
)
def test_untyped_or_other_sync_settings_are_refused(sync):
    with pytest.raises(ValueError):
        subject.state_members(valid_state(**{"SyncSettings.json": sync}))


def test_both_core_encodings_are_not_silently_chosen():
    with pytest.raises(ValueError, match="complete binary"):
        subject.state_members(valid_state(**{"Core.bin.zst": b"second"}))


def test_compressed_userdata_is_not_shadowed_with_a_plain_duplicate():
    data = valid_state(**{"UserData.txt.zst": b"unproved precedence"})
    with pytest.raises(ValueError, match="compressed UserData"):
        subject.experiment_metadata(producer_result(data), data)


@pytest.mark.parametrize("field", ["script", "path", "existing"])
def test_freezer_rejects_wrong_script_path_or_output_reuse(tmp_path, monkeypatch, field):
    root = tmp_path / "producer"
    (root / "results").mkdir(parents=True)
    data = valid_state()
    (root / "results/busy_ping.State").write_bytes(data)
    result = producer_result(data)
    result["evidence"]["runtime"]["produced"]["path"] = str(root / "results/busy_ping.State")
    result_path = root / "results/result.json"
    result_path.write_text(json.dumps(result))
    prepared = {
        "root": str(root),
        "result_path": str(result_path),
        "copies": {"source:" + subject.PROBE: {"copy": {"sha256": "a" * 64}}},
        "identity": {"script_sha256": "a" * 64, "binding_sha256": "b" * 64},
    }
    monkeypatch.setattr(subject.native_gate, "verify_preparation", lambda *_a, **_k: prepared)
    monkeypatch.setattr(subject.native_gate, "validate_result", lambda _p: result)
    if field == "script":
        prepared["identity"]["script_sha256"] = "c" * 64
    elif field == "path":
        result["evidence"]["runtime"]["produced"]["path"] = str(tmp_path / "not-private.State")
    else:
        (root / "results/controlled_load_artifacts").mkdir()
    with pytest.raises((ValueError, FileExistsError)):
        subject.freeze_experiment(root / "prepared.json", expected_probe_sha256="a" * 64)
