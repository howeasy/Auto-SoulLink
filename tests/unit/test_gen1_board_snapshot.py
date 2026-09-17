"""tools/gen1_board_snapshot.py offline paths: it must fail cleanly (a named
BOARD_ERROR / argparse error, exit 2) when there is no server and no saved
fixture, never a raw traceback -- and its --selftest replay must actually
produce the documented BOARD_ASSERT lines on a minimal known-good fixture
(a positive control: a script that always prints "everything false" without
crashing would pass a naive smoke test too).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "gen1_board_snapshot.py"


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or ROOT,
                           capture_output=True, text=True, check=False)


def test_no_args_fails_cleanly_with_a_named_reason():
    result = _run()
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "capture requires --http-port" in result.stderr


def test_http_port_with_no_server_listening_fails_cleanly(tmp_path):
    # Port 1 (TCP port assignment) is never a listening HTTP server in CI or dev --
    # no live-port guessing needed to prove the connection is refused.
    result = _run("--http-port", "1", "--out", str(tmp_path), "--label", "no-server")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "BOARD_ERROR" in result.stderr


def test_selftest_missing_files_fails_cleanly():
    result = _run("--selftest")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "--selftest requires --html FILE --status FILE" in result.stderr


def test_selftest_replay_on_minimal_fixture_produces_board_assert_lines(tmp_path):
    # Positive control (feedback_verify_the_probe_first.md): prove the replay path can
    # produce a true assertion at all, not just false-for-everything without crashing.
    html = tmp_path / "index.html"
    status = tmp_path / "status.json"
    html.write_text(
        '<div id="content" hx-get="/">'
        '<span class="phase-label">Waiting for Pokéballs</span></div>',
        encoding="utf-8",
    )
    status.write_text(json.dumps({"players": {"a": {}, "b": {}}}), encoding="utf-8")

    result = _run("--selftest", "--html", str(html), "--status", str(status))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert 'BOARD_ASSERT phase_label ok=true' in result.stdout
    # Everything else is legitimately absent from this minimal fixture.
    assert 'BOARD_ASSERT paired_sprites ok=false' in result.stdout
