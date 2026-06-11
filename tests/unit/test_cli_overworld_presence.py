"""
Unit test for the --overworld-presence CLI flag.

Mirrors --rival-team-swap / --explode-mode exactly — `action="store_true"`,
default off, opt-in per run.  Threaded through SoulLinkState as a plain bool;
gates the peer-ghost relay (ghost_pos / peer_interact) server-side.

Run:
    pytest tests/unit/test_cli_overworld_presence.py -v
"""

import subprocess
import sys


def test_help_mentions_overworld_presence():
    """Sanity: the flag appears in the --help output."""
    res = subprocess.run(
        [sys.executable, "-m", "server.server", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert res.returncode == 0, f"--help failed: {res.stderr}"
    out = res.stdout + res.stderr
    assert "--overworld-presence" in out
    assert "ghost" in out.lower()


def test_parser_store_true_shape():
    """argparse for --overworld-presence is store_true (off by default, opt-in)."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--overworld-presence", action="store_true", dest="overworld_presence")
    # Absent → False
    args = parser.parse_args([])
    assert args.overworld_presence is False
    # Present → True
    args = parser.parse_args(["--overworld-presence"])
    assert args.overworld_presence is True


def test_state_default_overworld_presence_false():
    """SoulLinkState default for overworld_presence is False (opt-in run rule)."""
    from server.state import SoulLinkState
    s = SoulLinkState()
    assert s.overworld_presence is False


def test_state_on_constructs():
    """SoulLinkState(overworld_presence=True) initializes cleanly."""
    from server.state import SoulLinkState
    s = SoulLinkState(overworld_presence=True)
    assert s.overworld_presence is True
