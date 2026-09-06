"""Pure private-test fixture builder; never loads a state or controls an emulator.

Pinned BizHawk2.11.1 loads Core.bin before parsing UserData.txt. This creates an
intentional late-metadata failure while preserving every other decompressed ZIP
member. The caller must independently bind the source and use a harmless BUSY
PING, pre-established hold, and disposable private process for execution.
"""

from __future__ import annotations

import hashlib
import io
import zipfile

MALFORMED_USERDATA = b"{this-is-an-intentional-private-interlock-probe\n"
REQUIRED = {"BizVersion.txt", "SyncSettings.json"}
CORE_NAMES = {"Core.bin", "Core.bin.zst"}
MAX_BYTES = 16 * 1024 * 1024


def failed_after_restore_copy(source: bytes) -> tuple[bytes, dict]:
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_BYTES:
        raise ValueError("bounded source state bytes required")
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if "UserData.txt.zst" in names:
            raise ValueError("compressed UserData has not been established for this fault lane")
        if (
            len(names) != len(set(names))
            or not set(names) >= REQUIRED
            or len(set(names) & CORE_NAMES) != 1
        ):
            raise ValueError("state has duplicate or missing required members")
        if sum(item.file_size for item in infos) > MAX_BYTES:
            raise ValueError("expanded state exceeds byte bound")
        members = {item.filename: archive.read(item) for item in infos}
    version = members["BizVersion.txt"].decode("utf-8-sig").strip()
    if version != "Version 2.11.1":
        raise ValueError("private probe requires a BizHawk2.11.1 state")
    core = next(name for name in members if name in CORE_NAMES)
    if not members[core] or not members["SyncSettings.json"]:
        raise ValueError("empty core or sync-settings member")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for item in infos:
            content = (
                MALFORMED_USERDATA if item.filename == "UserData.txt" else members[item.filename]
            )
            archive.writestr(item, content)
        if "UserData.txt" not in members:
            item = zipfile.ZipInfo("UserData.txt", date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, MALFORMED_USERDATA)
    result = output.getvalue()
    if len(result) > MAX_BYTES:
        raise ValueError("fault state exceeds byte bound")
    unchanged = {
        name: hashlib.sha256(value).hexdigest()
        for name, value in members.items()
        if name != "UserData.txt"
    }
    return result, {
        "schema": "slink-rr-late-load-failure-fixture-v1",
        "classification": "intentionally_invalid_metadata_private_probe_only",
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "output_sha256": hashlib.sha256(result).hexdigest(),
        "unchanged_member_sha256": unchanged,
        "changed_member": "UserData.txt",
        "core_payload_modified": False,
        "rom_or_busy_marker_verified": False,
        "emulator_executed": False,
        "interlock_proved": False,
        "release_ready": False,
    }
