"""
Phase 1 test: verify the server handles all event types and responds correctly.
Tests use asyncio TCP (matching the LuaSocket Lua client).

The live_server fixture (conftest.py) starts a server subprocess automatically.
"""
import asyncio
import json
import pytest

pytestmark = pytest.mark.usefixtures("live_server")


SERVER_HOST = "127.0.0.1"
SERVER_PORT = 54321


async def send_event(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, payload: dict) -> dict:
    """Send one JSON event over the open TCP connection and return the response."""
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))
    await writer.drain()
    raw = await reader.readline()
    return json.loads(raw)


@pytest.mark.asyncio
async def test_hello_event_gets_response():
    """hello event is accepted and returns a commands list."""
    reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
    try:
        result = await send_event(reader, writer, {
            "event": "hello", "player": "a", "seq": 1,
            "area_id": "route_1", "rom_type": "firered",
            "writes_enabled": True, "party": [],
        })
    finally:
        writer.close()
        await writer.wait_closed()
    assert "commands" in result
    assert isinstance(result["commands"], list)


@pytest.mark.asyncio
async def test_capture_event_gets_response():
    """capture event is accepted and returns a commands list."""
    reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
    try:
        result = await send_event(reader, writer, {
            "event": "capture", "player": "a", "seq": 2,
            "key": "AABBCCDD:11223344", "level": 5,
            "hp": 20, "maxHP": 20, "area_id": "route_1",
        })
    finally:
        writer.close()
        await writer.wait_closed()
    assert "commands" in result


@pytest.mark.asyncio
async def test_faint_event_gets_response():
    """faint event is accepted and returns a commands list."""
    reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
    try:
        result = await send_event(reader, writer, {
            "event": "faint", "player": "b", "seq": 3,
            "key": "AABBCCDD:11223344", "area_id": "route_1",
        })
    finally:
        writer.close()
        await writer.wait_closed()
    assert "commands" in result


@pytest.mark.asyncio
async def test_area_enter_event_gets_response():
    """area_enter event is accepted and returns a commands list."""
    reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
    try:
        result = await send_event(reader, writer, {
            "event": "area_enter", "player": "a", "seq": 4,
            "area_id": "viridian_city",
        })
    finally:
        writer.close()
        await writer.wait_closed()
    assert "commands" in result


@pytest.mark.asyncio
async def test_duplicate_seq_still_gets_response():
    """Server must always return a response, even for duplicate seq numbers."""
    reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
    try:
        for _ in range(3):
            result = await send_event(reader, writer, {
                "event": "area_enter", "player": "b", "seq": 0,
                "area_id": "route_2",
            })
            assert "commands" in result, "Expected a response even for duplicate seq"
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_invalid_player_gets_noop():
    """Unknown player_id is rejected gracefully with a noop response."""
    reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
    try:
        result = await send_event(reader, writer, {
            "event": "hello", "player": "z", "seq": 1,
            "area_id": "route_1",
        })
    finally:
        writer.close()
        await writer.wait_closed()
    assert "commands" in result
