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
    assert ':disabled="checkpointFor(current.run_id).busy"' in html, "the Checkpoint button has no busy gate"
    assert re.search(r'@click="recoverToCheckpoint\(\)"', html), "no Recover action"
    assert re.search(r':disabled="recovery\.busy \|\| !checkpoints\.current"', html), \
        "Recover must stay disabled until a confirmed checkpoint exists"


def test_the_poll_uses_the_captured_ids_and_stops_on_every_terminal_condition(html):
    match = re.search(r"async pollCheckpoint\(runId, requestId\)\s*\{([\s\S]*?)\n\s*\},", html)
    assert match, "no pollCheckpoint(runId, requestId) in the inline script"
    body = re.sub(r"//[^\n]*", "", match.group(1))
    assert "runId" in body and "requestId" in body, "the poll must use the ids captured at click time"
    assert "this.current.run_id" not in body, "the poll must not re-read the selected run"
    assert "this.current?.run_id !== runId" in body, "the poll must stop when the operator switches runs"
    assert "!res.ok || !j.ok" in body, "a failed fetch must stop the poll and show its error"
    assert "'confirmed'" in body and "'abandoned'" in body and "'refused'" in body, \
        "every terminal status must stop the poll"
    assert "setTimeout" in body and "2000" in body, "the poll must still wait 2 s between attempts"


def test_the_request_id_is_minted_once_per_click_and_reused(html):
    mint = re.search(r"newRequestId\(\)\s*\{([\s\S]*?)\n\s*\},", html)
    assert mint and "crypto.getRandomValues" in mint.group(1), "the request id must be minted client-side"
    body = re.sub(r"//[^\n]*", "", re.search(r"async requestCheckpoint\(\)\s*\{([\s\S]*?)\n\s*\},", html).group(1))
    assert "if (!state.request_id) state.request_id = this.newRequestId();" in body, \
        "a failed POST must reuse the id already minted for this run"
    assert "request_id: requestId" in body, "the POST body must carry the minted id"


def test_the_checkpoint_state_is_keyed_by_run_id(html):
    assert re.search(r"checkpointState: \{\}", html), "no per-run checkpoint state map"
    helper = re.search(r"checkpointFor\(runId\)\s*\{([\s\S]*?)\n\s*\},", html)
    assert helper and "this.checkpointState[runId]" in helper.group(1), "the state map is not keyed by run id"
    assert "checkpointFor(current.run_id)" in html, "the panel does not read this run's state"


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
    assert re.search(r"checkpoints: \{ current: null \}", html)
    assert re.search(r"recovery: \{ busy: false, error: '', result: null \}", html)
    assert "loadCheckpoints()" in html, "the confirmed checkpoint is never fetched"
