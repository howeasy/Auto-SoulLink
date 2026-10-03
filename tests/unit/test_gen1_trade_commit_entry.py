"""O-7 R3: distinguish a refused poll from committed native request entry."""
import pytest

from tests.unit.gen1_trade_witness import enter_world as enter
from tests.unit.test_gen1_trade_poll import _fire, _world
from tests.unit.test_gen1_trade_reliability import _applying_state, _armed


@pytest.mark.parametrize("title", ["red", "purered"])
def test_refused_polls_then_disturbance_restage_without_entry(monkeypatch, title):
    world, _ = _world(monkeypatch, title)
    _applying_state(world)
    base, _, _, _ = _armed(world)
    world.bus[world.ram["wWalkCounter"]] = 1
    for _ in range(3):
        _fire(world)
        world.client.signals.drain(world.client.signals)
    assert not world.client.trade.entry_observed
    world.bus[base] = 0
    staged = []
    world.parts.writes.write_enemy_party = lambda *_args: staged.append(True)
    world.client.trade_tick(world.client)
    assert staged == [True]
    assert world.client.trade.phase == "armed" and world.client.trade.pickup_error is None
    assert bytes(world.bus[base:base+4]) == b"SLT1"


@pytest.mark.parametrize("title", ["red", "purered"])
def test_only_committed_anchor_observes_entry(monkeypatch, title):
    world, _ = _world(monkeypatch, title)
    _armed(world)
    _fire(world)
    assert not world.client.trade.entry_observed
    enter(world)
    assert world.client.trade.entry_observed


@pytest.mark.parametrize("title", ["red", "purered"])
def test_real_entry_withdraw_is_ack_only_and_player_actionable(monkeypatch, title):
    world, _ = _world(monkeypatch, title)
    _applying_state(world)
    enter(world)
    before = bytes(world.bus)
    world.writes.clear()
    for _ in range(2):
        world.client.trade_withdraw(world.client, world.lua.table(token="late"))
    assert bytes(world.bus) == before and world.writes == []
    owed = list(world.client.trade_owed.values())
    assert len(owed) == 1 and owed[0].event == "trade_done" and owed[0].fields.uncertain is True
    assert len([h for h in world.hud if h[1] == "TRADE UNCERTAIN - CHECK PARTY"]) == 1


@pytest.mark.parametrize("title", ["red", "purered"])
def test_lost_consumption_hold_reports_once_after_bounded_frames_without_writes(monkeypatch, title):
    world, _ = _world(monkeypatch, title)
    _applying_state(world)
    base, _, _, preimage = _armed(world)
    enter(world)
    world.bus[base:base+16] = preimage
    reads = []
    original = world.parts.reads.read_party
    def party():
        reads.append(True)
        return original()
    world.parts.reads.read_party = party
    world.writes.clear()
    for frame in (1, 1800):
        world.client.frame = frame
        world.client.trade_tick(world.client)
    assert len(world.client.trade_owed) == 0
    for frame in (1801, 1802, 4000):
        world.client.frame = frame
        world.client.trade_tick(world.client)
    owed = list(world.client.trade_owed.values())
    assert len(owed) == 1 and owed[0].event == "trade_done" and owed[0].fields.uncertain is True
    assert reads == [True] and world.writes == []
    assert bytes(world.bus[base:base+16]) == preimage


def test_repeat_entry_observation_does_not_allocate_status_or_read_context(monkeypatch):
    world, _ = _world(monkeypatch, "red")
    _armed(world)
    statuses = []
    status = world.client.signals.status
    def counted(self):
        statuses.append(True)
        return status(self)
    world.client.signals.status = counted
    enter(world)
    reads = []
    register = world.io.register
    def counted_register(name):
        reads.append(name)
        return register(name)
    world.io.register = counted_register
    for _ in range(500):
        enter(world)
    assert len(statuses) <= 1 and reads == []
    assert len(world.client.signals.drain(world.client.signals)) == 0


@pytest.mark.parametrize("title", ["crystal", "gold", "silver"])
def test_real_gen2_binder_refusal_and_clobber_keep_pre_diff_result(title):
    from tests.unit.test_gen2_client import TradeCart, apply_cmd, nothing_changed, proposer_ready
    cart = TradeCart(title)
    proposer_ready(cart)
    cart.w.reply(apply_cmd())
    cart.w.frames(1)
    trade = cart.w.client.trade
    assert trade.phase == "armed"
    # Refusal before the native pickup label: no callback/ACK for these polls.
    cart.w.frames(3)
    assert trade.phase == "armed" and trade.poll_done(trade) is None
    frame = cart.frame()
    frame[0] = 0
    cart.poke(cart.lease, frame)
    assert trade.clobbered(trade) is True and trade.pickup_error is None
    cart.w.frames(1)
    assert nothing_changed(cart.w)
    assert cart.w.client.trade_state is None


@pytest.mark.parametrize("title", ["red", "purered"])
def test_locator_refuses_stack_save_without_generation_guard(monkeypatch, title):
    world, _ = _world(monkeypatch, title)
    site = world.client.trade.pickup_site(lambda addr: world.rom[int(addr)])
    image = bytearray(world.rom)
    image[site.rom_offset - 55 - 7] = 0  # ret z following cp b
    with pytest.raises(Exception, match="restore anchor missing"):
        world.client.trade.pickup_site(lambda addr: image[int(addr)])
