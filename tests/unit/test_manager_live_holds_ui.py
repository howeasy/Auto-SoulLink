"""Structural checks; runtime dispatch is covered by the handler and runtime tests.

The Manager's live panel polls `/api/runs/{id}/live` -> the run's `/api/status`, whose `holds`
list the Gen 1 runtime owns (server/gen1_runtime.py `holds()`, published by
server/runtime_boundary.read_runtime_holds). Alpine runs client-side, so all this file can pin
without a browser is the markup that renders those holds:

  * a global banner in the run-over slot, naming the first hold's instruction
  * a per-player "waiting on" row inside the player card, with the raw reasons in its tooltip
  * the filter helper, so an unattributed hold shows on both cards

The payload side is covered by tests/unit/test_gen1_sessions.py (runtime) and
tests/unit/test_manager_http_hardening.py (shape parity with empty_status_payload).
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


def test_the_run_held_banner_names_the_first_hold(html):
    match = re.search(r'<template x-if="liveStatus\.holds && liveStatus\.holds\.length">([\s\S]{0,200}?)</template>', html)
    assert match, "no global hold banner gated on liveStatus.holds"
    block = match.group(1)
    assert 'class="mgr-live-gameover"' in block, "the banner does not reuse the run-over banner class"
    assert "liveStatus.holds[0].text" in block, "the banner does not name a hold instruction"


def test_each_player_card_has_a_waiting_on_row(html):
    match = re.search(r'<div class="mgr-live-row mgr-live-hold"[^>]*>([\s\S]*?)</div>\s*<div class="mgr-live-party"', html)
    assert match, "no per-player hold row before the party block"
    row = match.group(0)
    assert 'x-show="liveHoldsFor(pid).length"' in row, "the row is not gated on this player's holds"
    assert 'x-text="liveHoldsFor(pid).map(h => h.text).join(' in row, "the row does not show the instructions"
    assert "h.reason" in row, "the raw reason must stay available (tooltip)"
    assert "waiting on" in row.lower(), "the row has no label a human reads"


def test_the_filter_helper_keeps_unattributed_holds_on_both_cards(html):
    match = re.search(r"liveHoldsFor\(pid\)\s*\{([\s\S]*?)\n\s*\},", html)
    assert match, "no liveHoldsFor(pid) helper in the inline script"
    body = re.sub(r"//[^\n]*", "", match.group(1))
    assert "liveStatus?.holds" in body or "liveStatus.holds" in body, "the helper does not read the polled payload"
    assert re.search(r"!h\.player\s*\|\|\s*h\.player\s*===\s*pid", body), \
        "an unattributed hold must show on both cards"
