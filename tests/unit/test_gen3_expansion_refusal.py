"""Expansion production routing; obsolete test overrides cannot qualify these positives."""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from server import adapters
from server.server import SLinkServer
from tests.unit.companion_evidence import companion

REPO = Path(__file__).resolve().parents[2]
EXP = "emerald_expansion_28877d73"


def hello(player="a", rom=EXP, ot="12345678"):
    return {
        "event": "hello",
        "player": player,
        "rom_type": rom,
        "artifact_kind": "clean",
        "trainer_name": player.upper(),
        "ot_id": ot,
        "party": [],
        "has_pokeballs": True,
    }


def test_fresh_process_routes_known_build_without_an_override():
    code = (
        "from server.adapters import game_id_for_rom_type,foundation_for_rom_type;import json;print(json.dumps([game_id_for_rom_type('"
        + EXP
        + "'),foundation_for_rom_type('"
        + EXP
        + "')]))"
    )
    got = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert json.loads(got.stdout) == ["gen3_exp", "gen3_exp"]


def test_known_build_is_routed_and_unknown_build_and_ap_stay_refused():
    assert adapters.game_id_for_rom_type(EXP) == "gen3_exp"
    assert adapters.foundation_for_rom_type(EXP) == "gen3_exp"
    assert adapters.adapter_class_for_rom_type(EXP).__name__ == "Gen3ExpansionAdapter"
    assert adapters.game_id_for_rom_type("emerald_expansion_unknown") is None
    assert adapters.game_id_for_rom_type("crystal_ap") is None
    assert "this Crystal build is not supported" in adapters.unrouted_rom_type_reason("Crystal (AP)")


def test_production_hello_and_persisted_reload_need_no_seam(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    for player, ot in (("a", "12345678"), ("b", "87654321")):
        srv._dispatch(player, hello(player, ot=ot))
        assert not srv.state.identity_error.get(player)
        assert srv.is_admitted(player)
    assert srv.adapter.game_id == "gen3_exp"
    assert srv.state.rom_type == EXP
    loaded = SLinkServer(data_dir=str(tmp_path))
    assert loaded.adapter.game_id == "gen3_exp" and loaded.state.rom_type == EXP
    code = "from server.server import SLinkServer;import sys,json;s=SLinkServer(data_dir=sys.argv[1]);print(json.dumps([s.adapter.game_id,s.state.rom_type]))"
    got = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(got.stdout) == ["gen3_exp", EXP]


@pytest.mark.asyncio
async def test_accepted_hello_logs_actual_production_route_after_identity_acceptance(
    tmp_path, caplog
):
    caplog.set_level(logging.INFO)
    srv = SLinkServer(data_dir=str(tmp_path))
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    connections = {}

    async def send(player, msg):
        reader, writer = connections[player]
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()
        return json.loads(await asyncio.wait_for(reader.readline(), 5))

    try:
        for player, ot in (("a", "12345678"), ("b", "87654321")):
            connections[player] = await asyncio.open_connection(
                "127.0.0.1", tcp.sockets[0].getsockname()[1]
            )
            await send(player, hello(player, ot=ot))
            assert srv.is_admitted(player)
        lines = [r.getMessage() for r in caplog.records if " (production)" in r.getMessage()]
        assert lines == [
            f"[a] route {EXP} -> gen3_exp (production)",
            f"[b] route {EXP} -> gen3_exp (production)",
        ]
        caplog.clear()
        reply = await send("a", hello(ot="FFFFFFFF"))
        assert any("WRONG SAVE" in c.get("text", "") for c in reply["commands"])
        assert not [r for r in caplog.records if " (production)" in r.getMessage()]
        assert srv.state.player_identity["a"]["ot_id"] == "12345678"
    finally:
        for _reader, writer in connections.values():
            writer.close()
            await writer.wait_closed()
        tcp.close()
        await tcp.wait_closed()


@pytest.mark.asyncio
async def test_unknown_hello_has_no_production_route_log(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    srv = SLinkServer(data_dir=str(tmp_path))
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    reader, writer = await asyncio.open_connection("127.0.0.1", tcp.sockets[0].getsockname()[1])
    try:
        writer.write((json.dumps(hello(rom="emerald_expansion_unknown")) + "\n").encode())
        await writer.drain()
        reply = json.loads(await asyncio.wait_for(reader.readline(), 5))
        assert any("UNKNOWN ROM" in c.get("text", "") for c in reply["commands"])
    finally:
        writer.close()
        await writer.wait_closed()
        tcp.close()
        await tcp.wait_closed()
    assert srv.state.identity_error.get("a")
    assert srv.state.rom_type == ""
    assert not [r for r in caplog.records if " (production)" in r.getMessage()]


def test_obsolete_test_route_api_and_cli_are_removed():
    assert not hasattr(adapters, "set_test_only_routes")
    assert not hasattr(adapters, "test_only_routes")
    got = subprocess.run(
        [sys.executable, "-m", "server.server", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "--test-only-route" not in got.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize("rom,game_id", [(EXP, "gen3_exp"), ("firered", "gen3_frlge")])
async def test_uncontracted_server_trusts_reported_sha_and_does_not_prove_rom(
    tmp_path, rom, game_id
):
    """Exact-ROM admission is client-side; this preserves the shared server trust model."""
    srv = SLinkServer(data_dir=str(tmp_path))
    tcp = await asyncio.start_server(srv.handle_client, "127.0.0.1", 0)
    reader, writer = await asyncio.open_connection("127.0.0.1", tcp.sockets[0].getsockname()[1])
    try:
        msg = hello(rom=rom)
        msg.update(companion(rom))   # a vanilla title connects PATCHED (companion required); the expansion is exempt
        msg["rom_sha1"] = "0" * 40
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()
        reply = json.loads(await asyncio.wait_for(reader.readline(), 5))
        assert srv.is_admitted("a") and not srv.state.identity_error.get("a")
        assert srv.adapter.game_id == game_id and srv.state.rom_type == rom
        assert not any(c.get("refused") for c in reply["commands"])
    finally:
        writer.close()
        await writer.wait_closed()
        tcp.close()
        await tcp.wait_closed()
