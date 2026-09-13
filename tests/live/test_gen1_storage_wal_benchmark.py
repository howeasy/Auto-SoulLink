"""TEMPORARY one-host storage microbench; not a production WAL or speed gate."""

import base64
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
import zlib
from pathlib import Path

import pytest

from server.protocol import canonical_json
from tools.run_gb_gate import BIZHAWK_CONFIG, run_gate
from tools.verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[2]
GATE = "lua/tests/test_gen1_storage_wal_benchmark_gate.lua"
REFERENCE = ROOT / ".cache/free-service-yy-pem7le27/runtime.sqlite3"
SAMPLES = 200


def representative_document():
    assert REFERENCE.is_file() and REFERENCE.resolve().is_relative_to((ROOT / ".cache").resolve())
    database = sqlite3.connect(f"file:{REFERENCE.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = database.execute(
            "SELECT request,request_digest FROM events WHERE player='a' "
            "AND json_extract(request,'$.event')='observation' ORDER BY revision LIMIT 1"
        ).fetchone()
    finally:
        database.close()
    assert row is not None
    text, expected = row
    assert 70_000 < len(text) < 80_000
    assert canonical_json(json.loads(text)) == text
    assert hashlib.sha256(text.encode("ascii")).hexdigest() == expected
    compressed = zlib.compress(text.encode("ascii"), 1)
    assert 1_500 <= len(compressed) <= 2_200
    return text, expected, compressed


def distribution(values):
    assert len(values) == SAMPLES and all(type(value) in (int, float) and 0 < value < 1_000 for value in values)
    ordered = sorted(values)
    return {"n": len(values), "p50_ms": ordered[math.ceil(0.50 * len(values)) - 1],
            "p90_ms": ordered[math.ceil(0.90 * len(values)) - 1],
            "p99_ms": ordered[math.ceil(0.99 * len(values)) - 1],
            "first_ms": values[0], "min_ms": ordered[0], "max_ms": ordered[-1],
            "top_five_ms": ordered[-5:]}


@pytest.mark.live
@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("SLINK_LIVE") != "1", reason="exclusive BizHawk lane required")
def test_pinned_yellow_local_storage_replace_vs_persistent_append():
    assert not verify()["failures"]
    text, expected_digest, compressed = representative_document()
    client_base = Path(os.environ["LOCALAPPDATA"]) / "SLink" / "clients"
    client_base.mkdir(parents=True, exist_ok=True)
    assert (not client_base.is_symlink() and not client_base.is_junction()
            and client_base.resolve().is_relative_to(Path(os.environ["LOCALAPPDATA"]).resolve()))
    bench_dir = Path(tempfile.mkdtemp(prefix=".slink-storage-bench-", dir=client_base))
    token = bench_dir.name.removeprefix(".slink-storage-bench-")
    marker = bench_dir / ".slink-storage-bench-owner"
    marker.write_text(token)
    try:
        evidence = Path(tempfile.mkdtemp(prefix="gen1-storage-wal-bench-", dir=ROOT / ".cache"))
        config = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
        assert config["PreferredCores"]["GB"] == "Gambatte"
        config["Rewind"]["Enabled"] = False
        config["FrameSkip"] = 0
        config["AutoMinimizeSkipping"] = False
        config_path = evidence / "base-config.ini"
        config_path.write_text(json.dumps(config))
        output = evidence / "raw-receipt.json"
        spec = evidence / "input.json"
        spec.write_text(json.dumps({
            "schema": "rby-bizhawk-local-storage-benchmark-input-v1", "samples": SAMPLES,
            "directory": bench_dir.as_posix(), "atomic_path": (bench_dir / "atomic-current.bin").as_posix(),
            "small_path": (bench_dir / "wal-small.bin").as_posix(),
            "large_path": (bench_dir / "wal-large.bin").as_posix(),
            "output": output.as_posix(), "preferred_core": "Gambatte",
            "canonical_document": text, "source_bytes": len(text), "source_sha256": expected_digest,
            "compressed_base64": base64.b64encode(compressed).decode("ascii"),
        }))
        passed, verdict_path, log = run_gate(
            GATE, rom_key="yellow", target="town", timeout=180, quiet=True,
            config_base=str(config_path), extra_env={"SLINK_STORAGE_BENCH_INPUT": str(spec)},
        )
        assert passed, f"{verdict_path}\n{log[-4000:]}"
        receipt = json.loads(output.read_text())
        assert receipt["schema"] == "rby-bizhawk-local-storage-benchmark-v1"
        assert receipt["variant"] == "yellow" and receipt["preferred_core"] == "Gambatte"
        assert receipt["directory"] == bench_dir.as_posix()
        assert receipt["source_bytes"] == len(text) and receipt["compressed_bytes"] == len(compressed)
        assert receipt["source_sha256"] == expected_digest
        assert set(receipt["samples"]) == {"atomic", "wal_small", "wal_large"}
        summary = {"schema": "rby-bizhawk-local-storage-benchmark-summary-v1",
                   "evidence": evidence.as_posix(), "directory": bench_dir.as_posix(),
                   "limitations": ["atomic replacement writes identical canonical bytes 200 times; "
                                   "AV/content caching may make this comparator optimistic",
                                   "storage calls only; no client journal serialization or gameplay FPS"],
                   "host": {"variant": "yellow", "preferred_core": "Gambatte",
                            "rom_sha1": receipt["rom_sha1"]},
                   "source_bytes": len(text), "compressed_bytes": len(compressed),
                   "samples": {name: distribution(values) for name, values in receipt["samples"].items()}}
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2))
    finally:
        resolved = bench_dir.resolve(strict=True)
        assert (not bench_dir.is_symlink() and not bench_dir.is_junction()
                and resolved.parent == client_base.resolve()
                and bench_dir.name.startswith(".slink-storage-bench-")
                and marker.read_text() == token), "storage benchmark cleanup ownership changed"
        allowed = {".slink-storage-bench-owner", "atomic-current.bin", "atomic-current.bin.lock",
                   "wal-small.bin", "wal-large.bin"}
        for item in bench_dir.iterdir():
            assert (item.is_file() and not item.is_symlink() and item.resolve().parent == resolved
                    and (item.name in allowed or item.name.startswith("atomic-current.bin.tmp-"))), (
                        "unexpected file in storage benchmark directory", item)
        assert not (bench_dir / "journal.json").exists()
        shutil.rmtree(resolved)
        assert not resolved.exists()
