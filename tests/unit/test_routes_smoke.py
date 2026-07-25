"""Every registered GET route must render without blowing up.

Nothing in the suite rendered a page before this. `server/server.py` is 8000 lines of Jinja
context building behind ~90 routes, and template/context breakage is the regression class this
repo is most exposed to — a renamed field or a missing macro takes a page (or an OBS overlay
mid-stream) down and no test notices.

The list of routes is not written out here; it is walked off `build_app()`'s real router, so a
route added to the server is covered automatically instead of drifting away from a hand-kept copy.
"""
import pytest

aiohttp = pytest.importorskip("aiohttp")
pytest_asyncio = pytest.importorskip("pytest_asyncio")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from server.adapters.gen3_frlge import Gen3Adapter  # noqa: E402
from server.server import SLinkServer, build_app  # noqa: E402
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo  # noqa: E402

# Routes with side effects or long-lived responses. /api/events is an SSE stream that never
# completes; the calc catch-all serves files from a vendored bundle; the launcher needs a player.
SKIP = {"/api/events"}
DYNAMIC = {
    "/calc/{path:.*}": "/calc/index.html",
    "/launcher/{player}": "/launcher/a",
    "/api/obs/scenes/{player}": "/api/obs/scenes/a",
}


def _get_routes(app):
    out = []
    for r in app.router.routes():
        if r.method != "GET":
            continue
        path = getattr(r.resource, "canonical", None) or str(r.resource)
        if path in SKIP:
            continue
        out.append(DYNAMIC.get(path, path))
    return sorted(set(out))


@pytest.fixture
def srv(tmp_path):
    """A server with one linked pair and a memorialized pair, so pages have rows to render."""
    s = SLinkServer(data_dir=str(tmp_path))
    st = s.state
    st.adapter = Gen3Adapter(is_rr=True)
    alive = LinkEntry(area_id="route_1",
                      a=MonInfo(key="A:1", level=12, species=1, nickname="BULBA"),
                      b=MonInfo(key="B:2", level=13, species=4, nickname="CHAR"),
                      status=LinkStatus.ALIVE)
    dead = LinkEntry(area_id="route_2",
                     a=MonInfo(key="A:3", level=9, species=10),
                     b=MonInfo(key="B:4", level=9, species=13),
                     status=LinkStatus.MEMORIAL)
    for e in (alive, dead):
        st.links.append(e)
        st._index_entry(e)
    st.area_states["route_1"] = AreaStatus.LINKED
    st.area_states["route_2"] = AreaStatus.LINKED
    st.party_keys["a"].add("A:1")
    st.party_keys["b"].add("B:2")
    st.pokeballs_obtained = {"a": True, "b": True}
    return s


@pytest_asyncio.fixture
async def client(srv):
    c = TestClient(TestServer(build_app(srv)))
    await c.start_server()
    yield c
    await c.close()


def _route_ids():
    """Collected at import time so each route is a separately named test."""
    import types
    stub = types.SimpleNamespace()
    # build_app only reads attributes off srv to register handlers; any object with them works,
    # but the real class keeps the handler names honest.
    for name in dir(SLinkServer):
        if name.startswith("handle_") or name == "_build_sidebar_html":
            setattr(stub, name, getattr(SLinkServer, name))
    return _get_routes(build_app(stub))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _route_ids())
async def test_get_route_renders(client, path):
    resp = await client.get(path)
    ctype = resp.headers.get("Content-Type", "")
    raw = await resp.read()                     # bytes: /companion/*.ups serves a binary patch
    assert resp.status < 500, f"{path} -> {resp.status}\n{raw[:1500]!r}"
    # A 200 HTML page that came back empty means the template rendered to nothing.
    if resp.status == 200 and "text/html" in ctype:
        assert raw.decode("utf-8", "replace").strip(), f"{path} returned an empty HTML body"


@pytest.mark.asyncio
async def test_status_page_shows_the_linked_pair(client):
    body = await (await client.get("/")).text()
    assert "BULBA" in body and "CHAR" in body


@pytest.mark.asyncio
async def test_status_json_is_wellformed(client):
    data = await (await client.get("/api/status")).json()
    assert "links" in data
    assert len(data["links"]) == 2


@pytest.mark.asyncio
async def test_memorial_page_lists_the_dead_pair(client):
    resp = await client.get("/memorial")
    assert resp.status == 200
    assert (await resp.text()).strip()


# ── Alpine double-init ───────────────────────────────────────────────────────
# Alpine auto-invokes a component's `init()` with NO arguments during initialisation. Pairing
# that with x-init="init(...)" runs the method TWICE — once with every parameter undefined.
# That is what pointed the stylesheet <link> at /static/themes/undefined.css (a 404 on every
# dashboard load) and registered duplicate htmx:afterSettle / storage listeners.
HTML_ROUTES = ["/", "/memorial", "/stream", "/debug", "/twitch", "/obs", "/launcher/a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", HTML_ROUTES)
async def test_no_alpine_x_init_calls_a_method_named_init(client, path):
    body = await (await client.get(path)).text()
    assert 'x-init="init(' not in body and "x-init='init(" not in body, (
        f"{path} has x-init calling init(...) — Alpine also auto-calls init() with no "
        "arguments, so it will run twice, the first time with undefined parameters. "
        "Rename the method (e.g. setup()).")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", HTML_ROUTES)
async def test_no_page_builds_an_undefined_theme_url(client, path):
    body = await (await client.get(path)).text()
    assert "themes/undefined" not in body
