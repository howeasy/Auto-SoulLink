"""Preflight/freeze private controlled-load experiments; never launches an emulator."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import struct
import zipfile
from pathlib import Path

from tools.emulator_sandbox import json_bytes
from tools.rr import native_gate
from tools.rr.reset_probe_fixture import failed_after_restore_copy

ROM_SHA1 = "65c6b2739bab54f8ffda590d79ba551a0b7baec8"
ROM_SHA256 = "3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301"
BATTERY_SHA256 = "c8eb84b434b80dc5c7cac7b84a9a8106d78088078d277a860fb6e4b067b43d13"
PROBE = "lua/tests/rr/controlled_load_probe.lua"
SCHEMA = "slink-rr-controlled-load-experiment-v1"
COMMON_ASSERTIONS = {
    "controlled_mode",
    "controlled_purpose",
    "controlled_frozen03",
    "controlled_fixture_battery",
    "controlled_host",
    "controlled_initial_unpaused_unheld",
    "controlled_frame_budget",
    "controlled_native_entry_anchor",
    "descriptor_matches_bound_rom",
    "controlled_positive_ping_receipt",
    "controlled_positive_native_dispatch",
    "controlled_trace_complete",
    "controlled_callbacks_removed",
    "controlled_exit_held",
    "controlled_no_failures",
}
PRODUCER_ASSERTIONS = COMMON_ASSERTIONS | {
    "controlled_pre_save_hold",
    "controlled_saved_busy_ping",
    "controlled_saved_state_exists",
    "controlled_saved_state_held",
    "controlled_zero_save_dispatch",
}
CONSUMER_ASSERTIONS = COMMON_ASSERTIONS | {
    "controlled_state_hash",
    "controlled_pre_load_hold",
    "controlled_old_owner_invalidated",
    "controlled_load_return",
    "controlled_success_notifications",
    "controlled_restored_frame",
    "controlled_restored_busy",
    "controlled_zero_restored_dispatch",
    "controlled_retained_busy",
}


def busy_ping_header(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{128}", value):
        raise ValueError("complete64-byte BUSY PING header required")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("invalid BUSY header hex") from exc
    sig, abi, opcode, seq, status, ack, reason = struct.unpack_from("<I6H", raw)
    if (sig, abi, opcode, status, reason) != (0x4B4E4C53, 2, 1, 1, 0) or seq == ack:
        raise ValueError("only an unacknowledged ABI2 BUSY OP_PING is permitted")
    if raw[16:40] != bytes(24) or raw[40:48] == bytes(8) or raw[48:] != bytes(16):
        raise ValueError("PING arguments/reservation/result differ from the safe marker")
    return raw


def state_members(data: bytes) -> dict[str, bytes]:
    if not isinstance(data, bytes) or not 0 < len(data) <= 16 * 1024 * 1024:
        raise ValueError("bounded state bytes required")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if (
            len(names) != len(set(names))
            or sum(item.file_size for item in infos) > 16 * 1024 * 1024
        ):
            raise ValueError("duplicate or oversized state members")
        result = {item.filename: archive.read(item) for item in infos}
    cores = set(result) & {"Core.bin", "Core.bin.zst"}
    if len(cores) != 1 or not set(result) >= {"BizVersion.txt", "SyncSettings.json"}:
        raise ValueError("complete binary BizHawk state required")
    if result["BizVersion.txt"].decode("utf-8-sig").strip() != "Version 2.11.1":
        raise ValueError("state host version differs")
    sync = json.loads(result["SyncSettings.json"].decode("utf-8-sig"))
    if not isinstance(sync, dict) or not isinstance(sync.get("o"), dict):
        raise ValueError("typed mGBA sync settings required")
    expected_type = (
        "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk+SyncSettings, BizHawk.Emulation.Cores"
    )
    if sync["o"].get("$type") != expected_type or sync["o"].get("SkipBios") is not True:
        raise ValueError("state must use the frozen mGBA/SkipBios configuration")
    return result


def experiment_metadata(result: dict, valid_state: bytes) -> tuple[dict, bytes]:
    """Pure checks after the outer caller has validated the bound producer result."""
    identity = result.get("identity", {})
    runtime = result.get("evidence", {}).get("runtime", {})
    produced = runtime.get("produced", {})
    if result.get("complete") is not True or result.get("release_ready") is not False:
        raise ValueError("completed private producer evidence required")
    if (
        identity.get("rom_sha1", "").lower() != ROM_SHA1
        or identity.get("rom_sha256") != ROM_SHA256
        or identity.get("fixture_sha256") != BATTERY_SHA256
    ):
        raise ValueError("producer is not the frozen03 ROM/battery")
    assertions = result.get("assertions", [])
    ids = [row.get("id") for row in assertions]
    if (
        len(ids) != len(set(ids))
        or not set(ids) >= PRODUCER_ASSERTIONS
        or any(row.get("passed") is not True for row in assertions)
    ):
        raise ValueError("producer structural assertions are incomplete")
    if (
        runtime.get("classification") != "controlled_busy_ping_state_producer"
        or runtime.get("mode") != "produce"
    ):
        raise ValueError("wrong producer probe mode")
    if hashlib.sha256(valid_state).hexdigest() != produced.get("state_sha256"):
        raise ValueError("producer state bytes changed")
    frame = produced.get("frame")
    if type(frame) is not int or not 0 <= frame < 2**31:
        raise ValueError("producer frame must be an observed integer")
    busy_ping_header(produced.get("mailbox_hex"))
    original = state_members(valid_state)
    fault, fault_manifest = failed_after_restore_copy(valid_state)
    modified = state_members(fault)
    for name, content in original.items():
        if name != "UserData.txt" and modified[name] != content:
            raise ValueError("fault variant changed native state contents")
    core = next(name for name in original if name in {"Core.bin", "Core.bin.zst"})
    metadata = {
        "schema": SCHEMA,
        "rom_sha1": ROM_SHA1,
        "rom_sha256": ROM_SHA256,
        "battery_sha256": BATTERY_SHA256,
        "saved_frame": frame,
        "mailbox_hex": produced["mailbox_hex"].lower(),
        "core_member": core,
        "core_member_sha256": hashlib.sha256(original[core]).hexdigest(),
        "sync_settings_sha256": hashlib.sha256(original["SyncSettings.json"]).hexdigest(),
        "valid": {
            "file_name": "busy_ping.State",
            "sha256": hashlib.sha256(valid_state).hexdigest(),
        },
        "late_failure": {
            "file_name": "busy_late_failure.State",
            "sha256": hashlib.sha256(fault).hexdigest(),
        },
        "fault_manifest": fault_manifest,
        "general_interlock_proved": False,
        "release_ready": False,
    }
    return metadata, fault


def freeze_experiment(prepared_path: Path, *, expected_probe_sha256: str) -> Path:
    """Write only beneath the validated producer's private results directory."""
    prepared = native_gate.verify_preparation(prepared_path, after_execution=True)
    result = native_gate.validate_result(prepared)
    script = prepared["copies"].get("source:" + PROBE)
    if (
        not script
        or script["copy"]["sha256"] != expected_probe_sha256
        or prepared["identity"]["script_sha256"] != expected_probe_sha256
    ):
        raise ValueError("producer script differs from the explicitly reviewed probe")
    root = Path(prepared["root"]).resolve()
    source = root / "results/busy_ping.State"
    if Path(result["evidence"]["runtime"]["produced"]["path"]).resolve() != source:
        raise ValueError("producer state path is not its private fixed output")
    state = source.read_bytes()
    metadata, fault = experiment_metadata(result, state)
    metadata["producer_result_sha256"] = hashlib.sha256(
        Path(prepared["result_path"]).read_bytes()
    ).hexdigest()
    metadata["producer_binding_sha256"] = prepared["identity"]["binding_sha256"]
    destination = root / "results/controlled_load_artifacts"
    destination.mkdir(exist_ok=False)
    (destination / "busy_ping.State").write_bytes(state)
    (destination / "busy_late_failure.State").write_bytes(fault)
    (destination / "experiment.json").write_bytes(json_bytes(metadata))
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument(
        "--probe-sha256", required=True, help="Explicitly reviewed producer probe hash"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.probe_sha256):
        parser.error("--probe-sha256 must be a lowercase SHA-256")
    print(freeze_experiment(args.prepared, expected_probe_sha256=args.probe_sha256))


if __name__ == "__main__":
    main()
