import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server import manager
from server.server import build_app
from tests.dashboard_scenarios import dashboard_scenario
from tests.html_contract import Document


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["gen3", "gen1"])
async def test_shared_destinations_render_with_current_navigation_and_scoped_polling(tmp_path, game):
    server = dashboard_scenario(game, tmp_path / game)
    async with TestClient(TestServer(build_app(server))) as client:
        for path in ("/broadcast?tab=overlays", "/broadcast?tab=obs", "/broadcast?tab=twitch", "/tools"):
            response = await client.get(path)
            page = await response.text()
            assert response.status == 200, page[:200]
            dom = Document(page)
            assert not [node for node in dom.root.descendants() if node.attrs.get("hx-trigger") == "every 2s"]
            scripts = [node.attrs.get("src") for node in dom.root.descendants("script")]
            assert scripts.count("/static/poll.js") == 1
            assert "/static/run-http.js" in scripts and "/static/board.js" in scripts
            rail = next(node for node in dom.root.descendants() if node.has_class("board-rail"))
            current = [node for node in rail.descendants("a") if node.attrs.get("aria-current") == "page"]
            assert len(current) == 1
            assert current[0].attrs["href"] == path.split("?")[0]
            assert sum(node.attrs.get("id") == "debug-dialog" for node in dom.root.descendants("dialog")) == 1


@pytest.mark.asyncio
async def test_manager_destinations_keep_run_selection_explicit_and_never_enable_old_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "MANAGER_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "REGISTRY_PATH", str(tmp_path / "registry.json"))
    manager._save_registry([{"run_id": "run_one", "name": 'One <script> & "two"', "status": "stopped", "pid": None,
                             "tcp_port": 54321, "http_port": 8081, "game_family": "gen1_rby"}])
    async with TestClient(TestServer(manager.build_app(manager.RunManager("127.0.0.1")))) as client:
        for path in ("/broadcast?tab=obs", "/broadcast?tab=twitch", "/tools", "/runs/run_one/broadcast?tab=obs", "/runs/run_one/tools"):
            response = await client.get(path)
            page = await response.text()
            assert response.status == 200, page[:200]
            assert 'One <script>' not in page
            dom = Document(page)
            assert not [node for node in dom.root.descendants() if node.attrs.get("hx-trigger") == "every 2s"]
            state = next(node for node in dom.root.descendants("script") if node.attrs.get("id") == "application-state")
            data = json.loads("".join(state.content))
            assert data["run_id"] == ("run_one" if path.startswith("/runs/") else None)
            if "tab=obs" in path:
                assert 'id="obs-rules"' in page and "unassigned and disabled" in page


@pytest.mark.asyncio
async def test_retired_pages_redirect_with_queries_and_debug_fragment_intact(tmp_path):
    server = dashboard_scenario("gen3", tmp_path / "gen3")
    async with TestClient(TestServer(build_app(server))) as client:
        for old, expected in (("/obs", "/broadcast?tab=obs&theme=light"), ("/twitch", "/broadcast?tab=twitch&theme=light"),
                              ("/debug", "/?debug=1&theme=light"), ("/stream", "/broadcast?tab=overlays&theme=light"),
                              ("/patcher", "/tools?theme=light"), ("/memorial", "/?theme=light#zone-fallen")):
            response = await client.get(old + "?theme=light", allow_redirects=False)
            assert response.status == 302 and response.headers["Location"] == expected
