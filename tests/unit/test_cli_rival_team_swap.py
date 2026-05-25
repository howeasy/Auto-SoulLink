"""
Unit test for the --rival-team-swap CLI flag.

Phase 4 cleanup: flag now mirrors --explode-mode exactly — `action="store_true"`,
default off, opt-in per run.  Threaded through SoulLinkState as a plain bool.

Run:
    pytest tests/unit/test_cli_rival_team_swap.py -v
"""

import subprocess
import sys


def test_help_mentions_rival_team_swap():
    """Sanity: the flag appears in the --help output."""
    res = subprocess.run(
        [sys.executable, "-m", "server.server", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert res.returncode == 0, f"--help failed: {res.stderr}"
    out = res.stdout + res.stderr
    assert "--rival-team-swap" in out
    assert "rival" in out.lower()


def test_parser_store_true_shape():
    """argparse for --rival-team-swap is store_true (off by default, opt-in)."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rival-team-swap", action="store_true", dest="rival_team_swap")
    # Absent → False
    args = parser.parse_args([])
    assert args.rival_team_swap is False
    # Present → True
    args = parser.parse_args(["--rival-team-swap"])
    assert args.rival_team_swap is True


def test_state_default_rival_team_swap_false():
    """SoulLinkState default for rival_team_swap is False (opt-in run rule)."""
    from server.state import SoulLinkState
    s = SoulLinkState()
    assert s.rival_team_swap is False


def test_state_on_constructs():
    """SoulLinkState(rival_team_swap=True) initializes cleanly."""
    from server.state import SoulLinkState
    s = SoulLinkState(rival_team_swap=True)
    assert s.rival_team_swap is True
