"""The art behind a player card (server/area_art.py): which picture an area gets, and the
route serving it from the cache without touching the network."""
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from server import area_art


def test_an_area_gets_its_own_picture_a_part_gets_the_wholes_a_route_its_kinds():
    assert area_art.source("Viridian Forest") == area_art.ART["Viridian Forest"]
    assert area_art.source("Pokemon Tower 3F") == area_art.ART["Pokémon Tower"], "floors and spelling"
    assert area_art.source("Diglett's Cave Route 2") == area_art.ART["Diglett's Cave"]
    assert area_art.source("Safari Zone East Rest House") == area_art.ART["Safari Zone"]
    assert area_art.source("Route 1") == area_art.GENERIC["route"]
    assert area_art.source("Route 20") == area_art.GENERIC["sea"]
    assert area_art.source("Mt. Moon B2F") == area_art.GENERIC["cave"]
    assert area_art.source("Pewter Museum") == area_art.ART["Pewter City"], "an interior is in its town"
    assert area_art.source("Route 12") == area_art.ART["Route 12"], "its own before its kind"
    assert area_art.source("Bill's House") is None
    assert area_art.source("Map 999") is None


def test_every_curated_source_is_a_title_or_a_url_with_a_stable_slug():
    seen = {}
    for name, src in {**area_art.ART, **area_art.GENERIC}.items():
        assert src.startswith(("File:", "https://")), (name, src)
        seen.setdefault(area_art.slug(src), src)
        assert seen[area_art.slug(src)] == src, f"two sources share a cache file: {src}"


@pytest.mark.asyncio
async def test_the_route_serves_the_cache_and_404s_what_nothing_depicts(tmp_path, monkeypatch):
    monkeypatch.setattr(area_art, "ART_DIR", tmp_path)
    (tmp_path / (area_art.slug(area_art.ART["Pallet Town"]) + ".png")).write_bytes(b"\x89PNG art")
    asked = []

    async def no_network(src):
        asked.append(src)
        raise OSError("offline")
    monkeypatch.setattr(area_art, "fetch", no_network)
    app = web.Application()
    area_art.setup_area_art_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        r = await client.get("/area-art/Pallet%20Town")
        assert r.status == 200 and await r.read() == b"\x89PNG art" and asked == []
        assert (await client.get("/area-art/Bill's%20House")).status == 404 and asked == []
        assert (await client.get("/area-art/Route%201")).status == 404, "offline: nothing yet"
        assert asked == [area_art.GENERIC["route"]]
    finally:
        await client.close()
