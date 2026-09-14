"""Structural checks for the Manager's checkpoint controls; the routes are covered by
tests/unit/test_manager_checkpoint_recovery.py.

Recovery is the one button in this dashboard that discards progress, so what is pinned here is
its wording and its wiring: the poll every 2 s, the two confirm() texts (a plain checkpoint vs a
pre-trade rollback), the busy gates, and the per-player download links with the instruction that
sends each player to their OWN machine. Alpine runs client-side, so this is a text check.
"""
from __future__ import annotations

import os
import re

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


@pytest.fixture(scope="module")
def html():
    with open(os.path.join(_REPO, "server", "templates", "manager.html"), encoding="utf-8") as f:
        return f.read()


def test_the_checkpoint_button_posts_and_the_recover_button_is_gated_on_a_confirmed_checkpoint(html):
    assert re.search(r'@click="requestCheckpoint\(\)"', html), "no Checkpoint action"
    assert re.search(r':disabled="checkpoint\.busy"', html), "the Checkpoint button has no busy gate"
    assert re.search(r'@click="recoverToCheckpoint\(\)"', html), "no Recover action"
    assert re.search(r':disabled="recovery\.busy \|\| !checkpoints\.current"', html), \
        "Recover must stay disabled until a confirmed checkpoint exists"


def test_the_poll_waits_for_the_request_and_stops_when_it_settles(html):
    match = re.search(r"async pollCheckpoint\(\)\s*\{([\s\S]*?)\n\s*\},", html)
    assert match, "no pollCheckpoint() in the inline script"
    body = re.sub(r"//[^\n]*", "", match.group(1))
    assert "setTimeout" in body and "2000" in body, "the poll must re-arm every 2 s"
    assert "'confirmed'" in body and "'abandoned'" in body, "the poll must stop on both terminal statuses"
    assert "waiting for A/B" in body, "the waiting wording is the run's own collecting state"


def test_both_confirm_texts_name_the_cost(html):
    match = re.search(r"async recoverToCheckpoint\(\)\s*\{([\s\S]*?)\n\s*\},", html)
    assert match, "no recoverToCheckpoint() in the inline script"
    body = re.sub(r"//[^\n]*", "", match.group(1))
    assert "Recover both players to the last checkpoint." in body
    assert "All progress after " in body
    assert "native_pretrade" in body, "a pre-trade rollback needs its own wording"
    assert "This trade and all progress after the checkpoint will be discarded." in body
    assert "confirm(text)" in body, "recovery must be an explicit confirmation"


def test_the_recovery_result_shows_downloads_and_the_resume_instruction(html):
    assert "recovery.result.downloads.a" in html and "recovery.result.downloads.b" in html
    assert re.search(r"download YOUR save on YOUR machine", html), "the download instruction is missing"
    assert re.search(r"--resume-save &lt;file&gt;", html), "the launcher flag is not named"
    assert not re.search(r"[A-Za-z]:\\\\", html), "no server-local path may be shown to a remote player"


def test_the_state_blocks_match_the_script(html):
    assert re.search(r"checkpoint: \{ busy: false, status: '', error: '', request_id: '' \}", html)
    assert re.search(r"checkpoints: \{ current: null \}", html)
    assert re.search(r"recovery: \{ busy: false, error: '', result: null \}", html)
    assert "loadCheckpoints()" in html, "the confirmed checkpoint is never fetched"
