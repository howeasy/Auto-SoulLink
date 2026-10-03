"""MODEL: foreground polls are not trade pickups, on vanilla and pure overlays."""
from __future__ import annotations

import pytest

from tests.unit import test_gen1_client as vanilla
from tests.unit.gen1_trade_witness import consume_world, plant_restore
from tests.unit.test_gen1_purergb_overlay import OverlayWorld

TITLES = ("red", "blue", "purered", "pureblue", "puregreen")


def _synthetic_vanilla(title):
    rom = bytearray(0x100000)
    for site in vanilla.SITES[title]["sites"].values():
        raw = bytes.fromhex(site["expected_hex"])
        rom[site["rom_offset"]:site["rom_offset"] + len(raw)] = raw
    ws = vanilla.WS[title]["write_safe"]
    for key, value in ws.get("expected_hex", {}).items():
        raw = bytes.fromhex(value)
        rom[ws[key]:ws[key] + len(raw)] = raw
    rom[0x29C3:0x29C8] = bytes.fromhex("21004C063F")
    return plant_restore(rom, vanilla.PROFILE[title])


def _world(monkeypatch, title):
    if title in ("red", "blue"):
        monkeypatch.setattr(vanilla, "_rom", _synthetic_vanilla)
        world = vanilla.World(title)
    else:
        world = OverlayWorld(monkeypatch, title)
        trade = world.parts.profile.trade
        rom = bytearray(world.rom)
        dispatch = bytes.fromhex(trade.dispatch_hex)
        rom[trade.receptionist_hook:trade.receptionist_hook + len(dispatch)] = dispatch
        world.rom = bytes(rom)
        world.client.start(world.client)
    assert world.client.trade_enabled
    calls = []
    original = world.client.trade.picked_up

    def picked_up(trade, *evidence):
        calls.append(True)
        return original(trade, *evidence)

    world.client.trade.picked_up = picked_up
    return world, calls


def _fire(world):
    svc = world.client.trade.service_address()
    world.bus[world.ram["hLoadedROMBank"]] = svc.bank
    world.regs["PC"] = svc.addr
    world.frame += 1
    world.hooks["SLink-gen1-trade_service"][0]()


@pytest.mark.parametrize("title", TITLES)
def test_idle_trade_polls_cannot_fill_the_signal_queue_and_pickup_still_fires(monkeypatch, title):
    world, calls = _world(monkeypatch, title)
    base = world.ram["wSerialPartyMonsPatchList"]
    # The foreground lease byte aliases tiles; armed-looking +10 is not publication.
    world.bus[base + 10] = 1
    for _ in range(100):
        _fire(world)
    signals = world.client.signals
    assert signals.status(signals).failed is None
    assert len(signals.drain(signals)) == 0 and calls == []
    published = b"SLT1\x01" + bytes([5, 1, 0, 255, 0, 1, 0, 1, 2, 3, 4])
    world.bus[base:base + 16] = published
    world.client.trade.expected = world.lua.table(*published)
    world.client.trade.phase = "armed"
    _fire(world)
    queued = signals.drain(signals)
    assert len(queued) == 1 and queued[1].kind == "trade_service"
    assert calls == [True] and world.client.trade.phase == "armed"
    consume_world(world)
    assert calls == [True, True] and world.client.trade.phase == "picked_up"


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("offset", range(5))
def test_every_magic_and_version_byte_is_required(monkeypatch, title, offset):
    world, calls = _world(monkeypatch, title)
    base = world.ram["wSerialPartyMonsPatchList"]
    world.bus[base:base + 5] = b"SLT1\x01"
    world.bus[base + offset] ^= 1
    _fire(world)
    assert len(world.client.signals.drain(world.client.signals)) == 0
    assert calls == []


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("state", [0, 3, 5, 7])
def test_pickup_filter_adds_no_state_token_or_availability_restriction(monkeypatch, title, state):
    world, calls = _world(monkeypatch, title)
    base = world.ram["wSerialPartyMonsPatchList"]
    world.bus[base:base + 16] = b"SLT1\x01" + bytes([state]) + bytes(10)
    _fire(world)
    assert len(world.client.signals.drain(world.client.signals)) == 1
    assert calls == [True]
