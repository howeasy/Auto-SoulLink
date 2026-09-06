import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.server import SLinkServer, build_app


@pytest.mark.asyncio
@pytest.mark.parametrize("hp,maximum,expected", [(501, 1000, "hp-h"), (50, 100, "hp-m"), (201, 1000, "hp-m"), (20, 100, "hp-l"), (None, 100, "hp-unknown")])
async def test_actual_party_overlay_uses_shared_raw_hp_policy(tmp_path, hp, maximum, expected):
    server = SLinkServer(data_dir=str(tmp_path))
    server.state.party_keys["a"] = {"key"}
    server.party_details["a"] = {"key": {"species_id": 25, "nickname": "Example", "hp": hp, "maxHP": maximum}}
    async with TestClient(TestServer(build_app(server))) as client:
        response = await client.get("/stream/party-a/fragment")
        assert response.status == 200
        text = await response.text()
    assert expected in text
    if hp is None:
        assert "HP unknown" in text and "FNT</span>" not in text and "width:None%" not in text
