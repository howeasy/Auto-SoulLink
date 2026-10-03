"""CR-R2 wiring uses one cartridge reader and never exports content on non-randomized ROMs.

Companion artifacts only: a randomized FR/LG is admitted as rand_companion (the wire still says
"rand"); the clean cartridge is not a production artifact."""

import pytest

from tests.unit.gen3_world import REPO, World
from tests.unit.test_gen3_client import A, B, party


def make_world(kind, mode, monkeypatch):
    monkeypatch.setenv("SLINK_GEN3_BATTLE_NONCE", "0000BEEF")
    world = World()
    world.client.stop(world.client)
    runtime = world.lua
    calls = {"new": 0, "payload": 0}
    payload = runtime.table(tables=runtime.table(runtime.table(addr=0x0823EAC8, hex="abcd")), fingerprint="ab" * 20)

    def factory(tables, io):
        calls["new"] += 1
        assert tables.gTrainers.address == 0x0823EAC8
        assert tables.gTrainers.count == 743
        assert tables.gWildMonHeaders.count == 133
        address = 0x08000000 + world.sites["frame_control"]["rom_offset"]
        assert io.read_u8(address) == world._byte(address)

        def read(*_):
            calls["payload"] += 1
            if mode == "nil":
                return None, "injected reader failure"
            if mode == "throw":
                raise RuntimeError("injected reader failure")
            return payload

        return runtime.table(payload=read)

    net = runtime.table(connected=lambda: world.connected, pump=lambda: None,
                        send=world._send, receive=lambda: world.replies.pop(0) if world.replies else None)
    hud = runtime.table(show=lambda *_: None, prompt=lambda *_: None, set_game_over=lambda *_: None,
                        set_rebuilding=lambda *_: None, clear_rebuilding=lambda *_: None, nuzlocke_start=lambda *_: None)
    world.client, world.parts = world.Entry.build(runtime.table(
        root=REPO.as_posix(), mode="production", io=world.io, ev=world.ev, net=net, hud=hud,
        pack="gen3_frlg", title="firered", kind=kind, player="a", rom_sha1="01" * 20,
        rom_content_new=factory, log=lambda line: world.logs.append(str(line))))
    world.set_party(party(A, B))
    world.client.start(world.client)
    world.step_to(60)
    return world, calls


def test_rand_hello_has_cached_rom_content_and_rand_kind(monkeypatch):
    world, calls = make_world("rand_companion", "ok", monkeypatch)
    hello = world.events("hello")[-1]
    assert hello["artifact_kind"] == "rand"
    assert hello["rom_content"] == {"tables": [{"addr": 0x0823EAC8, "hex": "abcd"}], "fingerprint": "ab" * 20}
    world.connected = False
    world.step()
    world.connected = True
    world.step()
    assert world.events("hello")[-1]["rom_content"] == hello["rom_content"]
    assert calls == {"new": 1, "payload": 1}


@pytest.mark.parametrize("mode", ["nil", "throw"])
def test_reader_failure_is_logged_once_and_hello_continues(mode, monkeypatch):
    world, calls = make_world("rand_companion", mode, monkeypatch)
    assert "rom_content" not in world.events("hello")[-1]
    world.connected = False
    world.step()
    world.connected = True
    world.step()
    assert "rom_content" not in world.events("hello")[-1]
    assert sum("injected reader failure" in line for line in world.logs) == 1
    assert calls == {"new": 1, "payload": 1}


def test_companion_hello_never_constructs_or_calls_the_reader(monkeypatch):
    world, calls = make_world("companion", "throw", monkeypatch)
    assert "rom_content" not in world.events("hello")[-1]
    assert calls == {"new": 0, "payload": 0}
