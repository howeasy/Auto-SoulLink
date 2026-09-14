"""The player-facing dashboard's holds: a run-wide banner and a per-card 'waiting on' line.

Rendered through the real `_build_status_html()` (the same way
tests/unit/test_http_server_security.py:170 does) with a stub runtime that publishes holds, so
this pins what a human sees on the second monitor, not just the payload. ids are stable
(id="hold-banner", id="hold-a"/"hold-b") because idiomorph swaps the body every 2 s.
"""
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.server import SLinkServer, build_app


def _server(tmp_path, holds):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.gen1_runtime = SimpleNamespace(holds=lambda: holds)
    return srv


def test_a_hold_renders_the_banner_and_only_the_named_players_card(tmp_path):
    holds = [{"player": "a", "kind": "blocker", "reason": "raw reason", "text": "A must act", "since": None}]
    body = _server(tmp_path, holds)._build_status_html()
    assert 'id="hold-a"' in body and "waiting on: A must act" in body
    assert 'id="hold-b"' not in body
    assert 'title="raw reason"' in body


def test_a_global_hold_lands_on_both_cards_and_none_render_without_holds(tmp_path):
    holds = [{"player": None, "kind": "service", "reason": "r", "text": "both", "since": None}]
    body = _server(tmp_path, holds)._build_status_html()
    assert 'id="hold-a"' in body and 'id="hold-b"' in body
    clean = _server(tmp_path, [])._build_status_html()
    assert 'id="hold-a"' not in clean and 'id="hold-b"' not in clean


@pytest.mark.asyncio
async def test_the_dashboard_route_injects_the_banner_and_escapes_it(tmp_path):
    holds = [{"player": "a", "kind": "blocker", "reason": "r", "text": "<script>bad</script>", "since": None}]
    srv = _server(tmp_path, holds)
    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    try:
        body = await (await client.get("/")).text()
        assert 'id="hold-banner"' in body and "Run held" in body
        assert "&lt;script&gt;bad&lt;/script&gt;" in body and "<script>bad</script>" not in body
    finally:
        await client.close()
