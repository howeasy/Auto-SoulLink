"""Request policy tests exercise the middleware before a mutating handler."""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server.http_safety import csrf_protection, theme_cache


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Site": "none"},
    {"Sec-Fetch-Site": "unknown"},
    {"Sec-Fetch-Mode": "no-cors"},
    {"Origin": "null"},
    {"Origin": "https://attacker.example"},
    {"Referer": "https://attacker.example/form"},
    {"Origin": "http://slink.local:8091"},
    {"Origin": "http://slink.local.attacker.example:8090"},
    {"Origin": "http://slink.local:8090@attacker.example"},
    {"Origin": "http://slink.local:8090/path"},
    {"Origin": "http://slink.local:8090#fragment"},
    {"Origin": "http://slink.local:99999"},
    {"Origin": "null", "Referer": "http://slink.local:8090/"},
    {"Origin": "http://slink.local:8090", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://attacker.example", "Sec-Fetch-Site": "same-origin"},
])
async def test_browser_mutation_is_rejected_before_handler(method, headers):
    effects = []

    async def mutate(request):
        effects.append(request.method)
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[csrf_protection])
    app.router.add_route("*", "/mutation", mutate)
    async with TestClient(TestServer(app)) as client:
        response = await client.request(method, "/mutation", headers={"Host": "slink.local:8090", **headers})
        assert response.status == 403
        assert (await response.json())["ok"] is False
        assert response.headers["Cache-Control"] == "no-store"
        assert effects == []


@pytest.mark.asyncio
@pytest.mark.parametrize("host,headers", [
    ("slink.local:8090", {}),
    ("slink.local:8090", {"Sec-Fetch-Site": "same-origin"}),
    ("slink.local:8090", {"Origin": "http://slink.local:8090"}),
    ("slink.local:8090", {"Referer": "http://slink.local:8090/runs?selected=one"}),
    ("192.168.1.20:8090", {"Origin": "http://192.168.1.20:8090"}),
    ("slink.local:8090", {"Origin": "http://SLINK.LOCAL:8090", "Sec-Fetch-Site": "same-site"}),
    ("slink.local:8090", {"Origin": "http://slink.local:8090", "Sec-Fetch-Site": "none"}),
    ("slink.local", {"Origin": "http://slink.local:80"}),
    ("[::1]:8090", {"Origin": "http://[::1]:8090"}),
])
async def test_same_origin_and_native_mutations_work(host, headers):
    effects = []

    async def mutate(request):
        effects.append(await request.text())
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[csrf_protection])
    app.router.add_post("/mutation", mutate)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/mutation", headers={"Host": host, **headers}, data="test")
        assert response.status == 200
        assert effects == ["test"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_read_only_requests_remain_compatible(method):
    async def read(request):
        return web.Response(text="read-only")

    app = web.Application(middlewares=[csrf_protection])
    app.router.add_route("*", "/read", read)
    async with TestClient(TestServer(app)) as client:
        response = await client.request(method, "/read", headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("existing,expected", [
    ({}, {"Cache-Control": "no-cache", "Vary": "Cookie"}),
    ({"Vary": "Accept-Encoding"}, {"Cache-Control": "no-cache", "Vary": "Accept-Encoding, Cookie"}),
    ({"Vary": "cookie, Accept-Encoding", "Cache-Control": "private, no-cache"},
     {"Vary": "cookie, Accept-Encoding", "Cache-Control": "private, no-cache"}),
    ({"Vary": "*", "Cache-Control": "no-store"}, {"Vary": "*", "Cache-Control": "no-store, no-cache"}),
])
async def test_html_revalidates_without_losing_existing_cache_headers(existing, expected):
    async def page(request):
        return web.Response(text=request.cookies.get("slink-theme", "default"),
                            content_type="text/html", headers=existing)

    app = web.Application(middlewares=[theme_cache])
    app.router.add_get("/page", page)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/page", headers={"Cookie": "slink-theme=light"})
        assert await response.text() == "light"
        for name, value in expected.items():
            assert response.headers[name] == value


@pytest.mark.asyncio
async def test_non_html_cache_policy_is_unchanged():
    async def data(request):
        return web.json_response({"ok": True}, headers={"Cache-Control": "no-store", "Vary": "Accept"})

    app = web.Application(middlewares=[theme_cache])
    app.router.add_get("/data", data)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/data")
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Vary"] == "Accept"


@pytest.mark.asyncio
async def test_repeated_header_fields_are_preserved():
    async def page(request):
        response = web.Response(text="themed", content_type="text/html")
        response.headers.add("Vary", "Accept-Encoding")
        response.headers.add("Vary", "Accept-Language")
        response.headers.add("Cache-Control", "private")
        response.headers.add("Cache-Control", "no-store")
        return response

    app = web.Application(middlewares=[theme_cache])
    app.router.add_get("/page", page)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/page")
        assert response.headers["Vary"] == "Accept-Encoding, Accept-Language, Cookie"
        assert response.headers["Cache-Control"] == "private, no-store, no-cache"
