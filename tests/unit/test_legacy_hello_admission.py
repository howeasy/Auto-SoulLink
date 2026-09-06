"""Real TCP unknown-cartridge refusals must precede legacy owner/state adoption."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from unittest.mock import Mock

import pytest
import pytest_asyncio

from server.adapters import game_id_for_rom_type
from server.server import SLinkServer

UNKNOWN = ["unknown", "vanilla", "unrecognized_rr", "", None, 7, True, [], {}, "missing-field"]


def hello(rom_type="firered", **updates):
    message = {"event": "hello", "player": "a", "rom_type": rom_type, "seq": 12,
               "trainer_name": "ALICE", "ot_id": "1234", "party": [], "area_id": "route_1"}
    message.update(updates)
    if rom_type == "missing-field":
        del message["rom_type"]
    return message


async def send(peer, message):
    reader, writer = peer
    writer.write(json.dumps(message).encode() + b"\n")
    await writer.drain()
    return json.loads(await asyncio.wait_for(reader.readline(), timeout=3))


@pytest_asyncio.fixture
async def tcp(tmp_path):
    server = SLinkServer(data_dir=str(tmp_path / "run"))
    peers, tasks = [], set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            await server.handle_client(reader, writer)
        finally:
            tasks.discard(task)

    listener = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]

    async def connect():
        peer = await asyncio.open_connection("127.0.0.1", port)
        peers.append(peer)
        return peer

    try:
        yield server, connect
    finally:
        for _, writer in peers:
            writer.close()
        for _, writer in peers:
            await writer.wait_closed()
        listener.close()
        await listener.wait_closed()
        if tasks:
            await asyncio.wait_for(asyncio.gather(*list(tasks)), timeout=3)


def snapshot(server):
    return copy.deepcopy({
        "state": server.state.to_document(), "connected": server.connected_players,
        "area": server.player_area, "area_id": server.player_area_id, "party": server.party_details,
        "boxes": server.pc_boxes, "battle": server.battle_state, "cache": server._mon_cache,
        "seq": server._last_seq, "queues": server.state.queued_commands,
    })


@pytest.mark.parametrize("rom_type", UNKNOWN)
@pytest.mark.asyncio
async def test_unknown_first_hello_never_adopts_adapter_identity_snapshot_or_sequence(tcp, monkeypatch, caplog, rom_type):
    server, connect = tcp
    server.state.queued_commands["a"] = [{"cmd": "force_faint", "key": "KEEP"}]
    before, adapter = snapshot(server), server.adapter
    dispatch = Mock(wraps=server._dispatch)
    monkeypatch.setattr(server, "_dispatch", dispatch)
    peer = await connect()
    with caplog.at_level(logging.WARNING):
        response = await send(peer, hello(rom_type, seq=999, trainer_name="WRONG", ot_id="DEAD",
                                          party=[{"key": "MALFORMED"}], rom_content={"untrusted": True}))
    assert response["ack"] == "NACK" and response["reason_code"] == "unrecognized_cartridge"
    assert response["commands"] == [{"cmd": "noop"}]
    assert snapshot(server) == before
    assert server.adapter is adapter and server.state.adapter is adapter
    assert server._player_adapters == {} and server._connection_owners == {}
    assert server.read_runtime_facts()["players"]["a"]["admission"]["reason_code"] == "unrecognized_cartridge"
    assert not server.is_admitted("a")
    assert any(record.levelno == logging.WARNING and "unrecognized cartridge" in record.message for record in caplog.records)
    assert (await send(peer, {"event": "tick", "player": "a", "seq": 1000, "rom_type": "firered"}))["ack"] == "NACK"
    assert snapshot(server) == before
    dispatch.assert_not_called()


@pytest.mark.parametrize("rom_type", UNKNOWN)
@pytest.mark.asyncio
async def test_unknown_hello_on_existing_socket_revokes_admission_without_adopting_new_state(tcp, rom_type):
    server, connect = tcp
    peer = await connect()
    await send(peer, hello())
    before, adapter, owner = snapshot(server), server.adapter, server._connection_owners["a"]
    response = await send(peer, hello(rom_type, seq=13, ot_id="BAD", trainer_name="WRONG"))
    assert response["reason_code"] == "unrecognized_cartridge"
    assert not server.is_admitted("a") and snapshot(server) == before
    assert server.adapter is adapter and server._connection_owners["a"] is owner
    assert (await send(peer, {"event": "capture", "player": "a", "seq": 14, "key": "UNTRUSTED"}))["ack"] == "NACK"
    assert snapshot(server) == before
    # The refusal did not consume seq13. A recognized HELLO on this same socket
    # can recover admission even when the run's cartridge was already locked.
    response = await send(peer, hello(seq=13))
    assert response.get("ack") != "NACK" and server.is_admitted("a")
    assert server.state.rom_type == "firered" and server.state.player_identity["a"]["ot_id"] == "1234"


@pytest.mark.parametrize("rom_type", ["firered", "leafgreen", "emerald", "firered_rr",
                                      "firered_ap", "leafgreen_ap", "red_ap", "blue_ap",
                                      "Crystal (AP)", "crystal_ap"])
@pytest.mark.asyncio
async def test_recognized_gen3_and_ap_startup_keeps_existing_adapter_and_command_behavior(tcp, rom_type):
    server, connect = tcp
    peer = await connect()
    response = await send(peer, hello(rom_type))
    assert response.get("ack") != "NACK"
    assert any(command["cmd"] == "config" for command in response["commands"])
    assert server.state.rom_type == rom_type
    assert server.adapter.game_id == game_id_for_rom_type(rom_type)
    assert server.state.is_rr == rom_type.endswith("_rr")
    assert server.is_admitted("a") and server.connected_players["a"]["connected"]
    assert server.connected_players["a"]["rom_type"] == rom_type
    assert (await send(peer, {"event": "tick", "player": "a", "seq": 13})).get("ack") != "NACK"


@pytest.mark.asyncio
async def test_rejected_second_socket_cannot_revoke_steal_or_disconnect_the_valid_owner(tcp):
    server, connect = tcp
    valid, rejected = await connect(), await connect()
    await send(valid, hello())
    before, owner, admission = snapshot(server), server._connection_owners["a"], copy.deepcopy(server.admission)
    assert (await send(rejected, hello("not-supported", seq=999)))["ack"] == "NACK"
    assert snapshot(server) == before and server.admission == admission
    assert (await send(rejected, {"event": "tick", "player": "a", "seq": 1000}))["ack"] == "NACK"
    assert snapshot(server) == before and server._connection_owners["a"] is owner
    rejected[1].close()
    await rejected[1].wait_closed()
    assert (await send(valid, {"event": "tick", "player": "a", "seq": 13})).get("ack") != "NACK"
    assert server._connection_owners["a"] is owner and server.connected_players["a"]["connected"]


@pytest.mark.asyncio
async def test_recognized_retry_after_unknown_first_hello_adopts_only_the_valid_cartridge(tcp):
    server, connect = tcp
    peer = await connect()
    assert (await send(peer, hello("unrecognized_rr", seq=999)))["ack"] == "NACK"
    assert not server.state.is_rr and not server._connection_owners
    response = await send(peer, hello("red_ap", seq=1))
    assert response.get("ack") != "NACK" and any(c["cmd"] == "config" for c in response["commands"])
    assert server.is_admitted("a") and "reason_code" not in server.admission["a"]
    assert server.state.rom_type == "red_ap" and server.adapter.game_id == "gen1_rby"
    assert server._last_seq["a"] == 1 and server.connected_players["a"]["rom_type"] == "red_ap"


@pytest.mark.asyncio
async def test_replaced_legacy_socket_cannot_reclaim_ownership_with_a_later_event_or_close(tcp):
    server, connect = tcp
    old, current = await connect(), await connect()
    await send(old, hello())
    previous = server._connection_owners["a"]
    await send(current, hello(seq=1))
    owner = server._connection_owners["a"]
    assert owner is not previous
    before = snapshot(server)
    assert (await send(old, {"event": "tick", "player": "a", "seq": 999}))["ack"] == "NACK"
    assert snapshot(server) == before and server._connection_owners["a"] is owner
    old[1].close()
    await old[1].wait_closed()
    assert (await send(current, {"event": "tick", "player": "a", "seq": 2})).get("ack") != "NACK"
    assert server._connection_owners["a"] is owner and server.connected_players["a"]["connected"]
