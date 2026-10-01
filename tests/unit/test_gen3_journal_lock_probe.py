"""The physical probe's helper owns an OS handle without touching journal bytes."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "tools/gen3_journal_lock_holder.ps1"


def test_guard_helper_marks_acquire_release_without_mutating_journal(tmp_path):
    shell = shutil.which("pwsh")
    if os.name != "nt" or not shell:
        pytest.skip("Windows PowerShell host unavailable")
    guard, log = tmp_path / "slink_gen3_trade.guard", tmp_path / "slink_gen3_trade.log"
    guard.write_bytes(b"SLINK-TRADE-JOURNAL-1\nmodel-seal\n")
    log.write_bytes(b"SLINK-TRADE-JOURNAL-1\nmodel-log\n")
    before = guard.read_bytes(), log.read_bytes()
    held, release = tmp_path / "held.marker", tmp_path / "release.marker"
    process = subprocess.Popen(
        [shell, "-NoProfile", "-File", str(HELPER), "-Root", str(tmp_path),
         "-HeldMarker", str(held), "-ReleaseMarker", str(release), "-MaxSeconds", "10"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = time.monotonic() + 8
        while not held.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert held.exists(), process.communicate(timeout=2)
        marker = held.read_text(encoding="utf-8")
        assert "LOCK_HELD pid=" in marker and str(guard) in marker
        with pytest.raises(PermissionError):
            guard.read_bytes()  # Share.None is a real exclusive OS hold, not a marker-only claim
        assert log.read_bytes() == before[1]
        release.write_text("release\n", encoding="utf-8")
        out, err = process.communicate(timeout=8)
        assert process.returncode == 0, out + err
        assert "LOCK_RELEASED pid=" in out and str(guard) in out
        assert (guard.read_bytes(), log.read_bytes()) == before
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=3)
