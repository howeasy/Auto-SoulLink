"""Stream active-run pins and capability-gated controls, through the real HTTP surfaces.

The manager serves every stream overlay at a stable URL (`/stream/{name}` on port 8090) and
proxies it to ONE run: the run pinned through `POST /api/stream/pin`, else the newest running
one. OBS browser sources point at the manager, so which run answers is the whole feature.
Nothing exercised `/api/stream/pin` or `RunManager._active_stream_run` before this file.

The second half pins the controls the page renders only when the cartridge can honour them:
the party table's Ability column follows `adapter.supports_abilities()` (Gen 1 predates
abilities) and the patcher's START-panel feature follows the target's `capabilities.panel`
(Yellow has no panel).
"""

import json
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import server.manager as manager
from server.adapters.gen1_rby import Gen1Adapter
from server.adapters.gen3_frlge import Gen3Adapter
from server.server import SLinkServer, build_app
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo
from server.status_payload import empty_status_payload


@pytest.fixture(autouse=True)
def manager_dir(tmp_path, monkeypatch):
    directory = tmp_path / "runs"
    directory.mkdir()
    monkeypatch.setattr(manager, "MANAGER_DIR", str(directory))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(directory / "registry.json"))
    return directory


@pytest.fixture
def alive(monkeypatch):
    """The set of pids the manager believes are running; the test decides who dies."""
    pids: set[int] = set()
    monkeypatch.setattr(manager, "_is_alive", lambda pid: pid in pids)
    return pids


@pytest_asyncio.fixture
async def manager_client(monkeypatch):
    """The app `manager.main` builds, served by an isolated test client."""
    captured = {}

    class AppCaptured(Exception):
        pass

    class Runner:
        def __init__(self, app):
            captured["app"] = app

        async def setup(self):
            pass

    class Site:
        def __init__(self, runner, host, port):
            pass

        async def start(self):
            raise AppCaptured

    with monkeypatch.context() as lifecycle:
        lifecycle.setattr(manager.web, "AppRunner", Runner)
        lifecycle.setattr(manager.web, "TCPSite", Site)
        with pytest.raises(AppCaptured):
            await manager.main("127.0.0.1", 0)

    async with TestClient(TestServer(captured["app"])) as client:
        yield client


async def _overlay_stub(label: str) -> TestClient:
    """A stand-in for one run's HTTP server: every /stream path answers with its label."""
    hits: list[str] = []

    async def overlay(request):
        hits.append(request.path_qs)
        return web.Response(text=f"overlay:{label}:{request.path_qs}", content_type="text/html")

    app = web.Application()
    app["hits"] = hits
    app.router.add_get("/stream/{name}", overlay)
    app.router.add_get("/stream/{name}/fragment", overlay)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def _run(run_id: str, pid: int, port: int, created_at: str, status: str = "running") -> dict:
    return {"run_id": run_id, "name": f"run {run_id}", "status": status, "pid": pid,
            "created_at": created_at, "http_port": port, "tcp_port": port + 1000}


@pytest_asyncio.fixture
async def two_runs(alive):
    """An older and a newer running run, each backed by a live overlay stub, plus a stopped one."""
    old = await _overlay_stub("old")
    new = await _overlay_stub("new")
    alive.update({101, 102})
    manager._save_registry([
        _run("old", 101, old.server.port, "2026-09-12T10:00:00"),
        _run("new", 102, new.server.port, "2026-09-12T11:00:00"),
        _run("gone", 103, 1, "2026-09-12T12:00:00", status="stopped"),
    ])
    try:
        yield {"old": old, "new": new}
    finally:
        await old.close()
        await new.close()


@pytest.mark.asyncio
async def test_without_a_pin_the_newest_running_run_is_the_stream_target(manager_client, two_runs):
    status = await (await manager_client.get("/api/stream/pin")).json()
    assert status == {"pinned": None, "active_run_id": "new", "active_run_name": "run new"}

    page = await manager_client.get("/stream/links")
    assert page.status == 200
    assert await page.text() == "overlay:new:/stream/links"
    assert two_runs["old"].server.app["hits"] == []


@pytest.mark.asyncio
async def test_pinning_an_older_run_redirects_every_overlay_to_it(manager_client, two_runs):
    pinned = await manager_client.post("/api/stream/pin", json={"run_id": "old"})
    assert pinned.status == 200
    assert await pinned.json() == {"ok": True, "pinned": "old", "active_run_id": "old"}

    status = await (await manager_client.get("/api/stream/pin")).json()
    assert status == {"pinned": "old", "active_run_id": "old", "active_run_name": "run old"}

    # The page, its HTMX fragment poll and the query string all follow the pin.
    for path in ("/stream/links", "/stream/links/fragment", "/stream/party-a?theme=dark"):
        page = await manager_client.get(path)
        assert page.status == 200, path
        assert await page.text() == f"overlay:old:{path}"
    assert two_runs["new"].server.app["hits"] == []


@pytest.mark.asyncio
async def test_an_unknown_run_id_is_refused_and_the_pin_is_kept(manager_client, two_runs):
    await manager_client.post("/api/stream/pin", json={"run_id": "old"})
    refused = await manager_client.post("/api/stream/pin", json={"run_id": "nope"})
    assert refused.status == 404
    assert (await refused.json())["ok"] is False
    status = await (await manager_client.get("/api/stream/pin")).json()
    assert status["pinned"] == "old" and status["active_run_id"] == "old"

    bad = await manager_client.post("/api/stream/pin", data=b"{not json")
    assert bad.status == 400
    assert (await bad.json())["ok"] is False


@pytest.mark.asyncio
async def test_a_stopped_or_dead_run_cannot_be_pinned_and_the_pin_is_kept(manager_client, two_runs, alive):
    """The registry knows "gone" (stopped) and, once 102 dies, "new" (running but dead).

    Accepting either used to answer 200 with pinned=<that id> while _active_stream_run had
    already dropped the pin, so the next GET contradicted the POST. Both are refused now and
    the previous pin survives.
    """
    await manager_client.post("/api/stream/pin", json={"run_id": "old"})
    refused = await manager_client.post("/api/stream/pin", json={"run_id": "gone"})
    assert refused.status == 409
    assert (await refused.json()) == {"ok": False, "error": "Run is not running"}
    alive.discard(102)
    dead = await manager_client.post("/api/stream/pin", json={"run_id": "new"})
    assert dead.status == 409
    status = await (await manager_client.get("/api/stream/pin")).json()
    assert status == {"pinned": "old", "active_run_id": "old", "active_run_name": "run old"}
    # The response of an accepted pin reports the stored pin, never the request echo.
    accepted = await (await manager_client.post("/api/stream/pin", json={"run_id": "old"})).json()
    assert accepted["pinned"] == status["pinned"] == "old"


@pytest.mark.asyncio
async def test_unpinning_restores_newest_running_selection(manager_client, two_runs):
    await manager_client.post("/api/stream/pin", json={"run_id": "old"})
    cleared = await (await manager_client.post("/api/stream/pin", json={"run_id": None})).json()
    assert cleared == {"ok": True, "pinned": None, "active_run_id": "new"}
    assert await (await manager_client.get("/stream/links")).text() == "overlay:new:/stream/links"


@pytest.mark.asyncio
async def test_a_pinned_run_that_dies_falls_back_and_is_recorded_as_stopped(manager_client, two_runs, alive):
    await manager_client.post("/api/stream/pin", json={"run_id": "old"})
    alive.discard(101)

    status = await (await manager_client.get("/api/stream/pin")).json()
    assert status == {"pinned": None, "active_run_id": "new", "active_run_name": "run new"}
    assert await (await manager_client.get("/stream/links")).text() == "overlay:new:/stream/links"
    registry = json.loads(open(manager.REGISTRY_PATH, encoding="utf-8").read())
    by_id = {r["run_id"]: r for r in registry["runs"]}
    assert by_id["old"]["status"] == "stopped" and by_id["old"]["pid"] is None


@pytest.mark.asyncio
async def test_with_no_running_run_the_overlay_explains_and_status_is_empty(manager_client, two_runs, alive):
    alive.clear()
    page = await manager_client.get("/stream/links")
    assert page.status == 404
    assert "No active run" in await page.text()
    assert await (await manager_client.get("/api/stream/pin")).json() == {
        "pinned": None, "active_run_id": None, "active_run_name": None}
    assert await (await manager_client.get("/api/status")).json() == empty_status_payload()


# ── capability-gated controls ────────────────────────────────────────────────────────────

def _linked_server(tmp_path, adapter, key_a: str, key_b: str) -> SLinkServer:
    s = SLinkServer(data_dir=str(tmp_path))
    st = s.state
    st.adapter = s.adapter = adapter
    entry = LinkEntry(area_id="route_1",
                      a=MonInfo(key=key_a, level=12, species=1, nickname="BULBA"),
                      b=MonInfo(key=key_b, level=13, species=4, nickname="CHAR"),
                      status=LinkStatus.ALIVE)
    st.links.append(entry)
    st._index_entry(entry)
    st.area_states["route_1"] = AreaStatus.LINKED
    st.party_keys["a"].add(key_a)
    st.party_keys["b"].add(key_b)
    st.pokeballs_obtained = {"a": True, "b": True}
    # The party table renders from party_details (slot order), not from party_keys alone.
    for owner, key, species in (("a", key_a, 1), ("b", key_b, 4)):
        s.party_details[owner][key] = {"slot": 0, "level": 12, "species_id": species,
                                       "nickname": "BULBA" if owner == "a" else "CHAR",
                                       "hp": 30, "max_hp": 30, "ability_id": 0, "ability_name": ""}
    return s


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter,keys,has_abilities", [
    (lambda: Gen1Adapter(variant="red"), ("AABB:30B8:99", "CCDD:7B0B:B1"), False),
    (lambda: Gen3Adapter(is_rr=True), ("A:1", "B:2"), True),
], ids=["gen1_rby", "gen3_rr"])
async def test_the_ability_column_follows_the_adapter_capability(tmp_path, adapter, keys, has_abilities):
    """Gen 1 predates abilities: the column must not render, and it must for a game that has them."""
    srv = _linked_server(tmp_path, adapter(), *keys)
    assert srv.adapter.supports_abilities() is has_abilities
    async with TestClient(TestServer(build_app(srv))) as client:
        html = await (await client.get("/")).text()
    assert 'class="party-table"' in html, "no party table rendered; the column check would be vacuous"
    assert ('<th class="col-abl">Ability</th>' in html) is has_abilities


@pytest.mark.asyncio
@pytest.mark.parametrize("slug,has_panel", [("rb-red", True), ("rb-blue", True), ("yellow", False)])
async def test_the_patcher_offers_the_start_panel_only_where_the_target_has_one(manager_client, slug, has_panel):
    from server.patcher import TARGETS
    assert TARGETS[slug]["capabilities"]["panel"] is has_panel
    html = await (await manager_client.get(f"/patcher?game={slug}")).text()
    # The feature list is the gated control; the shared note above it names the panel for
    # every Gen 1 target, so match the list item rather than the phrase.
    assert ("<li><strong>START panel</strong>" in html) is has_panel
    assert "<li><strong>Pokémon Center trade</strong>" in html
