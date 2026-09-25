"""The debug panel's memorial log reads /api/debug/raw_state -> _memorial.memorial_log as a list."""
from __future__ import annotations

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from server.server import SLinkServer, build_app


@pytest.mark.asyncio
async def test_memorial_log_is_the_retired_pairs_list(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    pairs = [{"area_id": "route_1", "a": None, "b": None, "cause": "battle"}]
    with open(srv.state._memorial_path, "w") as f:
        json.dump({"retired_pairs": pairs}, f)
    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    try:
        body = await (await client.get("/api/debug/raw_state")).json()
    finally:
        await client.close()
    assert body["_memorial"]["memorial_log"] == pairs
