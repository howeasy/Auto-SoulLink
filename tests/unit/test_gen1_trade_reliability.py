"""O-7 MODEL replays: drain holds, uncertain-result polling and proven pickup."""
from __future__ import annotations

import pytest

from tests.unit.test_gen1_trade_poll import TITLES, _fire, _world


def _armed(world):
    base = world.ram["wSerialPartyMonsPatchList"]
    backup = world.ram["wEnemyMons"] + world.d["battle_struct_size"]
    preimage = bytes(range(16))
    published = b"SLT1\x01" + bytes([5, 17, 16, 255, 0, 1, 0, 1, 2, 3, 4])
    world.bus[base:base + 16] = published
    world.bus[backup:backup + 16] = preimage
    world.client.trade.expected = world.lua.table(*published)
    world.client.trade.phase = "armed"
    return base, backup, published, preimage


@pytest.mark.parametrize("title", ["red", "purered"])
@pytest.mark.parametrize("step", ["panel", "pump", "hello", "validate", "owed"])
def test_raising_preframe_step_cannot_starve_signals_for_200_frames(monkeypatch, title, step):
    world, _ = _world(monkeypatch, title)
    base = world.ram["wSerialPartyMonsPatchList"]
    world.bus[base:base + 5] = b"SLT1\x01"
    target, key = {"panel": (world.client.panel, "service"), "pump": (world.net, "pump"),
                   "hello": (world.client.hello_session, "step"), "validate": (world.client, "validate"),
                   "owed": (world.client.owed, "step")}[step]
    original = target[key]
    seen = []
    world.client.on_signal = lambda _self, signal: seen.append(signal.kind)

    def broken(*_args):
        raise RuntimeError(f"{step} blocked at frame {world.frame}")

    target[key] = broken
    run = world.lua.eval("function(c) return pcall(function() c:frame_end() end) end")
    for tick in range(200):
        _fire(world)
        world.frame = (tick + 1) * 60
        run(world.client)
    status = world.client.signals.status(world.client.signals)
    assert status.pending == 0 and status.failed is None
    assert len(seen) == 200
    logs = [s for s in world.logs if "frame hold:" in s]
    assert len(logs) == 1 and "blocked" in logs[0]
    assert world.hud == []
    target[key] = original
    run(world.client)
    target[key] = broken
    run(world.client)
    assert len([s for s in world.logs if "frame hold:" in s]) == 2


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("phase", ["picked_up", "done"])
def test_uncertain_hold_never_queues_500_inert_trade_tokens(monkeypatch, title, phase):
    world, calls = _world(monkeypatch, title)
    base, _backup, published, _preimage = _armed(world)
    done = bytearray(published)
    done[5], done[7], done[8] = 7, done[6], 2
    world.bus[base:base + 16] = done
    if phase == "done":
        assert world.client.trade.poll_done(world.client.trade).result == 2
    else:
        world.client.trade.phase = phase
    for _ in range(500):
        _fire(world)
    signals = world.client.signals
    assert signals.status(signals).failed is None
    assert len(signals.drain(signals)) == 0 and calls == []


@pytest.mark.parametrize("title", TITLES)
def test_refused_foreground_poll_keeps_an_armed_request_withdrawable(monkeypatch, title):
    world, _ = _world(monkeypatch, title)
    base, _backup, _published, preimage = _armed(world)
    world.bus[world.ram["wWalkCounter"]] = 1
    _fire(world)
    assert world.client.trade.phase == "armed"
    world.parts.writes.arm(world.parts.writes, "overworld")
    assert world.client.trade.withdraw(world.client.trade) is True
    assert bytes(world.bus[base:base + 16]) == preimage


@pytest.mark.parametrize("title", TITLES)
def test_verified_post_restore_pickup_precedes_any_frame_callback(monkeypatch, title):
    world, _ = _world(monkeypatch, title)
    base, _backup, published, preimage = _armed(world)
    site = world.client.trade.pickup_site(lambda addr: world.rom[int(addr)])
    sp = 0xDE80
    world.bus[base:base + 16] = preimage
    world.bus[sp:sp + 16] = published[::-1]
    world.bus[world.ram["hLoadedROMBank"]] = site.bank
    world.regs["PC"], world.regs["SP"] = site.address, sp
    world.hooks["SLink-gen1-trade_consumed"][0]()
    assert world.client.trade.phase == "picked_up"
    assert world.client.trade.withdraw(world.client.trade) is False


@pytest.mark.parametrize("fault", ["stack", "restore", "sp"])
def test_unverified_native_consumption_holds_instead_of_restaging_or_cancelling(monkeypatch, fault):
    world, _ = _world(monkeypatch, "red")
    base, _backup, published, preimage = _armed(world)
    site = world.client.trade.pickup_site(lambda addr: world.rom[int(addr)])
    sp = 0xDE80
    world.bus[base:base + 16] = preimage
    world.bus[sp:sp + 16] = published[::-1]
    if fault == "stack":
        world.bus[sp] ^= 1
    elif fault == "restore":
        world.bus[base] ^= 1
    else:
        sp = 0xFFF0
    world.bus[world.ram["hLoadedROMBank"]] = site.bank
    world.regs["PC"], world.regs["SP"] = site.address, sp
    world.hooks["SLink-gen1-trade_consumed"][0]()
    assert world.client.trade.phase == "picked_up" and world.client.trade.pickup_error
    assert world.client.trade.withdraw(world.client.trade) is False
    assert world.client.trade.clobbered(world.client.trade) is False
    assert sum("consumption unverified; holding" in line for line in world.logs) == 1


def test_missing_lease_address_is_refused_at_registration_not_inside_a_hook(monkeypatch):
    world, _ = _world(monkeypatch, "red")
    world.client.signals.close(world.client.signals)
    site = world.client.trade.service_address()
    flat = site.bank * 0x4000 + site.addr - 0x4000
    descriptor = world.lua.table(bank=site.bank, address=site.addr, rom_offset=flat,
                                 expected_hex=world.rom[flat:flat + 6].hex())
    calls = []
    world.io.on_bus_exec = lambda *_args: calls.append(True) or 1
    with pytest.raises(Exception, match="lease_address"):
        world.parts.signals.new(world.parts.profile, world.lua.table(trade_service=descriptor), world.io)
    assert calls == []


@pytest.mark.parametrize("fault", ["missing", "ambiguous"])
def test_native_restore_anchor_is_required_and_unique(monkeypatch, fault):
    world, _ = _world(monkeypatch, "red")
    image = bytearray(world.rom)
    site = world.client.trade.service_address()
    first = site.bank * 0x4000 + site.addr - 0x4000
    if fault == "missing":
        image[first:first + 0x200] = bytes(0x200)
    else:
        # The fixture's exact native block appears again within the bounded service.
        image[first + 0x100:first + 0x100 + 61] = image[first + 0x28:first + 0x28 + 61]
    with pytest.raises(Exception, match="restore anchor"):
        world.client.trade.pickup_site(lambda addr: image[int(addr)])
