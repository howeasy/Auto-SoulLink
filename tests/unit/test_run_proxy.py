"""Real loopback HTTP routing with isolated storage and no game processes."""

import asyncio
import json

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from multidict import CIMultiDict

from server import manager
from server.http_safety import csrf_protection, theme_cache
from server.run_proxy import allowed, prefix_html


@pytest_asyncio.fixture
async def proxy(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(tmp_path / "registry.json"))
    monkeypatch.setattr(manager, "_is_alive", lambda pid: bool(pid))
    calls, release, finished = [], asyncio.Event(), asyncio.Event()

    async def endpoint(request):
        calls.append({"method": request.method, "path": request.path, "raw": request.raw_path,
                      "headers": dict(request.headers), "body": await request.read()})
        if request.path == "/api/events":
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            try:
                await response.write(b'event: state\ndata: {"run":"one"}\n\n')
                await release.wait()
                await response.write(b'event: state\ndata: {"run":"two"}\n\n')
            finally:
                finished.set()
            return response
        if request.path.startswith("/calc/"):
            headers = {"Content-Type": "application/octet-stream", "ETag": '"artifact"',
                       "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT", "Content-Disposition": 'attachment; filename="pair.gb"'}
            if request.headers.get("If-None-Match") == '"artifact"':
                return web.Response(status=304, headers=headers)
            if request.headers.get("Range") == "bytes=1-2":
                return web.Response(body=b"\x01\x02", status=206, headers={**headers, "Content-Range": "bytes 1-2/4"})
            return web.Response(body=b"\x00\x01\x02\xff", headers=headers)
        if request.path == "/memorial":
            return web.Response(text='<div hx-get="/memorial?filter=a&amp;b=2"><a href="/debug">Debug</a></div>',
                content_type="text/html", headers=CIMultiDict([("ETag", '"page"'), ("Vary", "Accept-Language"), ("Set-Cookie", "a=1; Path=/"), ("Set-Cookie", "b=2; Path=/")]))
        if request.path == "/calc":
            raise web.HTTPFound("/calc/normal.html?mode=a%2Bb")
        return web.json_response({"ok": True, "raw": request.raw_path})

    upstream = web.Application(middlewares=[csrf_protection, theme_cache], handler_args={"handler_cancellation": True})
    async def identify(request, response):
        response.headers["X-SLink-Run-Id"] = "run_other" if request.headers.get("X-Test-Other-Run") else "run_one"
    upstream.on_response_prepare.append(identify)
    upstream.router.add_route("*", "/{path:.*}", endpoint)
    async with TestServer(upstream) as remote:
        run = {"run_id": "run_one", "name": "One", "status": "running", "pid": 123,
               "tcp_port": 54321, "http_port": remote.port}
        manager._save_registry([run])
        service = manager.RunManager("127.0.0.1")
        async with TestClient(TestServer(manager.build_app(service))) as client:
            yield client, service, calls, release, finished


@pytest.mark.asyncio
async def test_proxy_preserves_exact_query_cookies_origin_and_request_body(proxy):
    client, _, calls, _, _ = proxy
    origin = str(client.make_url("/")).rstrip("/")
    response = await client.post("/runs/run_one/api/attempts?q=a%2Bb&q=c+d&empty=", data=b'{"value":3}',
                                 headers={"Origin": origin, "Cookie": "slink-theme=light", "Content-Type": "application/json"})
    assert response.status == 200
    assert calls[-1]["raw"] == "/api/attempts?q=a%2Bb&q=c+d&empty="
    assert calls[-1]["headers"]["Cookie"] == "slink-theme=light"
    assert calls[-1]["headers"]["Origin"] == origin
    assert calls[-1]["headers"]["Host"] == client.make_url("/").authority
    assert calls[-1]["body"] == b'{"value":3}'
    assert response.headers["X-SLink-Run-Id"] == "run_one"


@pytest.mark.asyncio
async def test_cross_origin_mutation_stops_before_upstream(proxy):
    client, _, calls, _, _ = proxy
    for origin in ("null", "http://elsewhere.invalid", "http://localhost:1234"):
        assert (await client.post("/runs/run_one/api/reset", headers={"Origin": origin})).status == 403
    assert not calls


@pytest.mark.parametrize("path", ["/_ui/board-context", "/api/obs/execute", "/api/runs/new", "/api/randomizer/inspect", "/api/unknown", "/stream/all", "/stream/ticker/private"])
@pytest.mark.asyncio
async def test_unlisted_routes_never_reach_upstream(proxy, path):
    client, _, calls, _, _ = proxy
    assert (await client.get("/runs/run_one" + path)).status == 404
    assert (await client.post("/runs/run_one" + path)).status == 404
    assert not calls


@pytest.mark.asyncio
async def test_downloads_ranges_conditional_headers_and_head_survive(proxy):
    client, _, _, _, _ = proxy
    path = "/runs/run_one/calc/artifact.gb"
    response = await client.get(path)
    assert await response.read() == b"\x00\x01\x02\xff"
    assert response.headers["Content-Disposition"] == 'attachment; filename="pair.gb"'
    assert response.headers["ETag"] == '"artifact"'
    assert "Last-Modified" in response.headers
    response = await client.get(path, headers={"If-None-Match": '"artifact"'})
    assert response.status == 304 and await response.read() == b""
    response = await client.get(path, headers={"Range": "bytes=1-2"})
    assert response.status == 206 and await response.read() == b"\x01\x02"
    assert response.headers["Content-Range"] == "bytes 1-2/4"
    response = await client.head(path)
    assert response.status == 200 and await response.read() == b""
    assert response.headers["Content-Length"] == "4"


@pytest.mark.asyncio
async def test_html_fragment_urls_theme_cache_cookies_and_redirects(proxy):
    client, _, _, _, _ = proxy
    response = await client.get("/runs/run_one/memorial?theme=light")
    page = await response.text()
    assert 'hx-get="/runs/run_one/memorial?filter=a&amp;b=2"' in page
    assert 'href="/runs/run_one/debug"' in page
    assert {x.strip() for x in response.headers["Vary"].split(",")} == {"Cookie", "Accept-Language"}
    assert len(response.headers.getall("Set-Cookie")) == 2
    assert response.headers["ETag"] == '"page"'
    response = await client.get("/runs/run_one/calc", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"] == "/runs/run_one/calc/normal.html?mode=a%2Bb"


@pytest.mark.asyncio
async def test_real_event_bytes_are_streamed_without_manager_dummy_events(proxy):
    client, _, _, release, finished = proxy
    response = await client.get("/runs/run_one/api/events")
    first = await asyncio.wait_for(response.content.readuntil(b"\n\n"), 2)
    assert first == b'event: state\ndata: {"run":"one"}\n\n'
    # Other page polling can proceed while this connection stays open.
    assert (await client.get("/runs/run_one/api/status")).status == 200
    assert (await client.get("/api/events")).status == 404
    release.set()
    assert await asyncio.wait_for(response.content.readuntil(b"\n\n"), 2) == b'event: state\ndata: {"run":"two"}\n\n'
    await asyncio.wait_for(finished.wait(), 2)
    response.close()


@pytest.mark.asyncio
async def test_stopped_deleted_unknown_runs_do_not_resolve_to_another_run(proxy):
    client, service, calls, _, _ = proxy
    original = service._get()[0]
    await service._mutate_registry(lambda runs: runs.extend([{**original, "run_id": "run_other"}]))
    await service._mutate_registry(lambda runs: runs[0].update(status="stopped", pid=None))
    assert (await client.get("/runs/run_one/api/status")).status == 503
    assert (await client.get("/runs/missing/api/status")).status == 404
    await service._mutate_registry(lambda runs: runs.pop(0))
    assert (await client.get("/runs/run_one/api/status")).status == 404
    assert not calls
    assert (await client.get("/runs/run_other/api/status", headers={"X-Test-Other-Run": "1"})).status == 200


@pytest.mark.asyncio
async def test_wrong_process_at_a_registered_port_cannot_return_live_status(proxy):
    client, _, calls, _, _ = proxy
    response = await client.get("/runs/run_one/api/status", headers={"X-Test-Other-Run": "1"})
    assert response.status == 502 and len(calls) == 1
    assert '"ok": true' not in await response.text()


@pytest.mark.asyncio
async def test_closing_calc_sse_cancels_and_closes_its_upstream_connection(proxy):
    client, _, _, _, finished = proxy
    response = await client.get("/runs/run_one/api/events")
    assert await response.content.readuntil(b"\n\n")
    response.close()
    await asyncio.wait_for(finished.wait(), 2)


def test_attribute_rewriter_preserves_safe_text_json_and_external_urls():
    page = '<!doctype html><!-- keep --><script>{"url":"/api/reset","text":"<x>"}</script><p>/api/status &amp; &#9;</p><a href="//other.test/x">X</a><a href="/static/a.js">S</a><form action="/api/reset"></form>'
    rewritten = prefix_html(page, "/runs/run_one")
    assert rewritten == page.replace('action="/api/reset"', 'action="/runs/run_one/api/reset"')
    assert not allowed("GET", "/calc/../private")
    assert not allowed("POST", "/calc/a")
