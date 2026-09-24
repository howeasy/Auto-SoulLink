"""UI-TRADE-BANNER: the pair board's rendering of `status.trade_problem` / `trade_last`.

`server.state.trade_problem()` and `.trade_last` are server-owned and already reach the
status payload (server.py ~2567); this only proves `_board.html` actually shows them, and
does it safely — `tp.problem` and the free-text verdict strings come from in-game party
readback (arbitrary attacker-controlled bytes on an untrusted link), so they must go through
Jinja's autoescape, never `|safe`.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

pytest_plugins = ["tests.unit.populated_server"]


@pytest_asyncio.fixture
async def board(populated):
    srv, client = populated
    return srv, client


async def _html(client) -> str:
    resp = await client.get("/")
    assert resp.status == 200
    return await resp.text()


@pytest.mark.asyncio
async def test_no_banner_when_nothing_is_wrong(board):
    """Control: the mock cast has no pending trade, so the banner must not appear."""
    srv, client = board
    html = await _html(client)
    assert "trade-problem" not in html
    assert "trade-last-note" not in html


@pytest.mark.asyncio
async def test_uncertain_trade_renders_the_amber_banner(board):
    srv, client = board
    a_key = next(iter(srv.party_details["a"]))
    b_key = next(iter(srv.party_details["b"]))
    srv.state.trade_problem = lambda: {
        "phase": "uncertain", "token": "tok1", "a_key": a_key, "b_key": b_key,
        "verdict": {"a": "traded", "b": "await"}, "problem": "",
    }
    html = await _html(client)
    assert "trade-problem-uncertain" in html
    assert "Trade uncertain" in html
    assert "trade-problem-conflict" not in html


@pytest.mark.asyncio
async def test_conflict_trade_escapes_the_problem_text(board):
    """The `problem` string is built from party readback, not typed by an admin — a
    template that forgot autoescape (or reached for `|safe`) would let it inject markup."""
    srv, client = board
    a_key = next(iter(srv.party_details["a"]))
    b_key = next(iter(srv.party_details["b"]))
    srv.state.trade_problem = lambda: {
        "phase": "conflict", "token": "tok2", "a_key": a_key, "b_key": b_key,
        "verdict": {"a": "traded", "b": "a: holds BOTH <b>x</b> and y (duplicated)"},
        "problem": "<script>alert(1)</script>",
    }
    html = await _html(client)
    assert "trade-problem-conflict" in html
    assert "Trade conflict" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>x</b>" not in html


@pytest.mark.asyncio
async def test_last_trade_note_shows_only_when_nothing_is_currently_wrong(board):
    srv, client = board
    srv.state.trade_last = {
        "token": "tok3", "outcome": "committed", "at": 0,
        "a_key": "aaaaaaaaaaaaaaaa", "b_key": "bbbbbbbbbbbbbbbb",
        "a_new": None, "b_new": None,
        "verdict": {"a": "traded", "b": "traded"}, "problem": "",
    }
    html = await _html(client)
    assert "trade-last-note" in html
    assert "committed" in html

    # An active problem takes priority over the quiet historical note.
    srv.state.trade_problem = lambda: {
        "phase": "uncertain", "token": "tok4",
        "a_key": "aaaaaaaaaaaaaaaa", "b_key": "bbbbbbbbbbbbbbbb",
        "verdict": {"a": "await", "b": "await"}, "problem": "",
    }
    html = await _html(client)
    assert "trade-problem-uncertain" in html
    assert "trade-last-note" not in html


@pytest.mark.asyncio
async def test_held_events_are_listed_on_the_banner(board):
    """Invariant review MAJOR-3: what waits on the trade is visible next to the resolve hint."""
    srv, client = board
    srv.state.trade_problem = lambda: {
        "phase": "conflict", "token": "tok5", "a_key": "A:1", "b_key": "B:2",
        "verdict": {"a": "traded", "b": "none"}, "problem": "",
    }
    srv.state.trade_held = lambda: [{"player": "b", "event": "faint", "key": "B:2"}]
    html = await _html(client)
    assert "trade-problem-held" in html and "B faint B:2" in html
    assert '"adopt"' in html
