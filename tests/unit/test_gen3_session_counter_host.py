"""Installed NLua cold-start proof for the Gen 3 per-install session counter."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "tools/gen3_session_counter_host_probe.ps1"


def _host():
    shell = shutil.which("pwsh")
    runtime = Path(os.environ.get("SLINK_BIZHAWK", "E:/Howard/Bizhawk"))
    if os.name != "nt" or not shell or not (runtime / "dll/NLua.dll").is_file():
        pytest.skip("installed Windows NLua/BizHawk runtime absent")
    return shell, runtime


def _start(shell, runtime, root, side, *, held=None, release=None):
    cmd = [shell, "-NoProfile", "-File", str(PROBE), "-Root", str(root), "-Side", side,
           "-Trace", str(root / f"{side}.trace"), "-SourceRoot", str(ROOT),
           "-BizHawk", str(runtime)]
    if held is not None:
        cmd += ["-HoldAfterClaim", "-Held", str(held), "-Release", str(release)]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)


def _finish(process):
    out, err = process.communicate(timeout=35)
    assert process.returncode == 0, out + err
    match = re.search(r"\bVALUE=(\d+)\b.*\bGUARD_BUSY=(\d+)\b", out)
    assert match, out
    return int(match[1]), int(match[2])


def _files(root):
    assert (root / "slink_gen3_session.born").is_file()
    assert (root / "slink_gen3_session.lock").is_file()
    assert (root / "slink_gen3_session.baton").read_text() == "2"
    assert sorted(p.name for p in root.glob("slink_gen3_session.*")) == [
        "slink_gen3_session.baton", "slink_gen3_session.born", "slink_gen3_session.lock"]


def test_simultaneous_installed_nlua_cold_starts_allocate_distinct_monotonic_values(tmp_path):
    shell, runtime = _host()
    for trial in range(6):
        root = tmp_path / f"cold-{trial}"
        root.mkdir()
        a, b = _start(shell, runtime, root, "a"), _start(shell, runtime, root, "b")
        try:
            values = [_finish(a)[0], _finish(b)[0]]
            assert sorted(values) == [1, 2], (trial, values)
            _files(root)
        finally:
            for process in (a, b):
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)


def test_installed_nlua_guard_yields_while_peer_holds_claim_before_read(tmp_path):
    shell, runtime = _host()
    root = tmp_path / "held-claim"
    root.mkdir()
    held, release = root / "held.marker", root / "release.marker"
    a = _start(shell, runtime, root, "a", held=held, release=release)
    b = None
    try:
        deadline = time.monotonic() + 12
        while not held.exists() and a.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert held.exists(), a.communicate(timeout=2)
        b = _start(shell, runtime, root, "b")
        deadline = time.monotonic() + 12
        trace = root / "b.trace"
        while (not trace.exists() or "reason=busy" not in trace.read_text()) \
                and b.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert trace.exists() and "reason=busy" in trace.read_text(), b.communicate(timeout=2)
        release.write_text("release\n")
        av, _ = _finish(a)
        bv, busy = _finish(b)
        assert (av, bv) == (1, 2) and busy >= 1
        _files(root)
    finally:
        release.write_text("release\n")
        for process in (a, b):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
