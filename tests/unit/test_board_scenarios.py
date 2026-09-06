import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.server import build_app
from tests.dashboard_scenarios import SCENARIOS, dashboard_scenario
from tests.html_contract import Document


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_hydrated_board_scenarios_keep_required_states_visible(tmp_path, scenario):
    server = dashboard_scenario(scenario, tmp_path / scenario)
    async with TestClient(TestServer(build_app(server))) as client:
        response = await client.get("/")
        assert response.status == 200
        text = await response.text()
    dom = Document(text)
    zones = {node.attrs["data-zone"] for node in dom.root.descendants() if "data-zone" in node.attrs}
    if scenario == "empty":
        assert not zones and "No links yet" in text and "Waiting for game" in text
    elif scenario in ("gen3", "gen1"):
        assert {"party", "pending", "boxed", "unlinked", "fallen"} <= zones
    elif scenario == "warnings":
        assert "save-warn" in text and "This run is over" in text and "save identity warning" in text
    elif scenario == "split":
        assert "split" in zones and "Solo" in text
    elif scenario == "doubles":
        assert "Doubles · opposing side" in text
        assert {node.attrs["data-foe-owner"] for node in dom.root.descendants() if "data-foe-owner" in node.attrs} == {"a", "b"}
    elif scenario == "hp_boundaries":
        bars = [node for node in dom.root.descendants() if node.attrs.get("role") == "progressbar"]
        assert any(node.attrs.get("aria-valuenow") == "0" for node in bars)
        assert "at risk" in text
    elif scenario == "stopped":
        assert "linked" in zones and "This run is stopped" in text
        assert not [node for node in dom.root.descendants() if "data-now-player" in node.attrs or node.attrs.get("role") == "progressbar"]
    elif scenario == "disconnected":
        assert "Disconnected · last observation" in text and "Last observation" in text
    elif scenario == "stale":
        assert "stale-warn" in text and "Last observation is stale" in text
    elif scenario == "rejected":
        assert "connection rejected" in text and "assigned cartridge &lt;A&gt;" in text
    elif scenario == "unknown_hp":
        assert "HP unknown" in text and "HP not fully observed" in text
    elif scenario == "persisted":
        assert "linked" in zones and "party" not in zones and "Waiting for game" in text
