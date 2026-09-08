"""Exercise the shared manager board using real detached run projections."""

import asyncio
import copy
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server import manager
from server.manager_board import stopped_context
from server.server import build_app
from tests.dashboard_scenarios import dashboard_scenario
from tests.html_contract import Document


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    directory = tmp_path / "runs"
    directory.mkdir()
    monkeypatch.setattr(manager, "MANAGER_DIR", str(directory))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(directory / "registry.json"))
    monkeypatch.setattr(manager, "_is_alive", lambda pid: bool(pid))
    return directory


@pytest.mark.parametrize("game", ["gen3", "gen1"])
@pytest.mark.asyncio
async def test_live_board_uses_registered_run_and_stopped_board_contains_only_saved_facts(isolated, game):
    run_id = "run_" + game
    server = dashboard_scenario(game, isolated / run_id)
    server._run_id, server._run_name, server._manager_port = run_id, 'Run <script> & "name"', 8090
    document = server.state.to_document()
    (isolated / run_id / "links.json").write_text(json.dumps(document), encoding="utf-8")
    async with TestServer(build_app(server)) as remote:
        run = {"run_id": run_id, "name": server._run_name, "status": "running", "pid": 123,
               "tcp_port": 54321, "http_port": remote.port, "game_family": server.adapter.game_id}
        manager._save_registry([run])
        service = manager.RunManager("127.0.0.1")
        async with TestClient(TestServer(manager.build_app(service))) as client:
            base = "/runs/" + run_id
            response = await client.get(base + "/?theme=light")
            assert response.status == 200
            page = await response.text()
            assert 'class="theme-light' in page
            assert '<script> & "name"' not in page and "Run &lt;script&gt; &amp;" in page
            dom = Document(page)
            assert not list(dom.root.descendants("iframe"))
            assert len([node for node in dom.root.descendants() if node.attrs.get("hx-trigger") == "every 2s"]) == 1
            assert sum(node.attrs.get("data-now-player") is not None for node in dom.root.descendants()) == 2
            content = next(node for node in dom.root.descendants() if node.attrs.get("id") == "content")
            assert content.attrs["hx-get"] == base + "/?theme=light"
            assert content.attrs["hx-select-oob"] == "#run-list:morph"
            assert f'href="{base}/launcher/a"' in page and f'href="{base}/calc/normal.html"' in page
            assert 'data-mon-key=' in page and '&lt;img ' not in page
            stream = await client.get(base + "/api/events")
            assert await asyncio.wait_for(stream.content.readuntil(b"\n\n"), 2) == b"retry: 3000\n\n"
            assert await asyncio.wait_for(stream.content.readuntil(b"\n\n"), 2) == b"event: ping\ndata: \n\n"
            assert len(server._sse_clients) == 1
            pages = await asyncio.gather(*(client.get(base + path) for path in
                ("/", "/stream/party-a/fragment?theme=light", "/stream/linked-party/fragment?theme=transparent", "/api/calc/mons")))
            assert all(response.status == 200 for response in pages)
            for response in pages:
                await response.read()
            stream.close()
            before = copy.deepcopy(server.state.to_document())
            await service._mutate_registry(lambda runs: runs[0].update(status="stopped", pid=None))
            page = await (await client.get(base + "/")).text()
            dom = Document(page)
            assert not [node for node in dom.root.descendants() if "data-now-player" in node.attrs]
            assert 'data-zone="linked"' in page
            assert 'data-run-available="false"' in page
            assert 'data-calc-link' in page
            assert all(not node.has_class("board-hp") for node in dom.root.descendants())
            assert server.state.to_document() == before
            assert (await client.get(base + "/launcher/a")).status == 200
            assert (await client.get(base + "/api/status")).status == 503

            # A newly created or other active run must not substitute for this one.
            await service._mutate_registry(lambda runs: runs.append({**run, "run_id": "run_other"}))
            assert (await client.get(base + "/api/status")).status == 503


@pytest.mark.asyncio
async def test_wrong_target_identity_is_rejected_before_a_run_mutation(isolated):
    server = dashboard_scenario("gen3", isolated / "run_one")
    server._run_id, server._manager_port = "run_one", 8090
    before = copy.deepcopy(server.state.to_document())
    async with TestClient(TestServer(build_app(server))) as client:
        response = await client.post("/api/reset", headers={"X-SLink-Target-Run": "run_other"})
        assert response.status == 409
    assert server.state.to_document() == before


@pytest.mark.asyncio
async def test_wrong_live_context_identity_cannot_show_another_runs_observations(isolated):
    server = dashboard_scenario("gen3", isolated / "run_actual")
    server._run_id, server._manager_port = "run_actual", 8090
    async with TestServer(build_app(server)) as remote:
        manager._save_registry([{"run_id": "run_requested", "name": "Requested", "status": "running", "pid": 123,
                                 "tcp_port": 54321, "http_port": remote.port}])
        async with TestClient(TestServer(manager.build_app(manager.RunManager("127.0.0.1")))) as client:
            response = await client.get("/runs/run_requested/")
            page = await response.text()
            assert response.status == 200 and "This run is unavailable." in page
            assert 'data-now-player=' not in page and 'data-mon-key=' not in page


@pytest.mark.asyncio
async def test_corrupt_saved_document_is_preserved_and_never_presented_as_live(isolated):
    directory = isolated / "run_bad"
    directory.mkdir()
    path = directory / "links.json"
    path.write_bytes(b'{"broken')
    manager._save_registry([{"run_id": "run_bad", "name": "Broken", "status": "stopped", "pid": None,
                             "tcp_port": 54321, "http_port": 8081}])
    async with TestClient(TestServer(manager.build_app(manager.RunManager("127.0.0.1")))) as client:
        page = await (await client.get("/runs/run_bad/")).text()
        assert "Saved progress cannot be read" in page and 'data-now-player=' not in page
    assert path.read_bytes() == b'{"broken'


def test_stopped_projection_does_not_infer_cartridges_or_runtime_from_saved_caches(isolated):
    server = dashboard_scenario("gen3", isolated / "fixture")
    document = server.state.to_document()
    context = stopped_context({"run_id": "run_saved", "name": "Saved", "status": "stopped"}, {"available": True, "document": document})
    for player in context["players"].values():
        assert player["cartridge"] == "Cartridge not recorded"
        assert not player["observed"] and not player["battle"]
        assert player["age"] is None and player["admission"] is None
    assert context["status"] is None
    assert all(not mon["show_hp"] and mon["where"] is None for row in context["rows"] for mon in (row["a"], row["b"]) if mon)


@pytest.mark.asyncio
async def test_new_run_form_and_names_are_rendered_as_text_with_no_embedded_registry_script(isolated):
    attack = '</script><img data-ui-probe="unsafe">'
    manager._save_registry([{"run_id": "run_safe", "name": attack, "status": "stopped", "pid": None,
                             "tcp_port": 54321, "http_port": 8081}])
    async with TestClient(TestServer(manager.build_app(manager.RunManager("127.0.0.1")))) as client:
        page = await (await client.get("/")).text()
    assert attack not in page and '&lt;/script&gt;&lt;img data-ui-probe=' in page
    dom = Document(page)
    assert not list(dom.root.descendants("iframe"))
    assert any(node.attrs.get("id") == "new-run" for node in dom.root.descendants("form"))
    assert any(node.attrs.get("name") == "game_family" for node in dom.root.descendants("select"))
    assert 'name="auto_start" checked' in page
    rail = dom.by_id("run-list")
    assert rail.attrs["hx-trigger"] == "every 2s"
    assert rail.attrs["hx-request"] == '{"timeout":10000}'
