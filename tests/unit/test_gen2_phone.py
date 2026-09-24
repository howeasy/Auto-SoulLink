"""P4.5c: lua/gen2/phone.lua, the Soul Link phone-call binder (O-29), under lupa.

Spec: docs/gen2/reviews/P4_5_PHONE_CALLS_PLAN_2026-09-23.md §2-§3. The host writes +32
PHONE_REQUEST (1..3) only on a fresh SLink cartridge that advertises SLINK_CAP_PHONE, only while
+32 and +33 both read 0, one call in flight, a MIN_GAP of emulator frames between deliveries,
priority fallen > dead_zone > first_link, first_link once per session, nothing retried across a
freshness loss. The ROM half (P4.5b) is modelled here from §2.2; nothing is live yet.
"""
from __future__ import annotations

import pathlib

import pytest

from tests.unit.test_gb_panel import _abi
from tests.unit.test_gen2_panel import CAP_PANEL, PERMIT, Cart

REPO = pathlib.Path(__file__).resolve().parents[2]
PHONE = (REPO / "lua" / "gen2" / "phone.lua").as_posix()
CAP_PHONE = 0x08            # plan §6: SLINK_CAP_PHONE = 1 << 3
REQ, ARMED = 32, 33         # plan §2.1
FALLEN, DEAD_ZONE, FIRST_LINK = 1, 2, 3


class PhoneCart(Cart):
    """Cart + the P4.5b service's phone tail (§2.2, mailbox half only) + the binder."""

    def __init__(self, title="crystal", caps=CAP_PANEL | CAP_PHONE, **kw):
        super().__init__(title, caps=caps, **kw)
        self.logs: list[str] = []
        io = self.lua.table(read_u8=lambda a, d=None: self.mem[int(a)], framecount=lambda: self.frame,
                            write_u8=self._write_u8)
        self.pw = self.P.writes(io, self.lua.eval(f'dofile("{PERMIT}")'))
        self.phone = self.lua.eval(f'dofile("{PHONE}")').new(self.panel, io, self.pw,
                                                             lambda s: self.logs.append(str(s)))
        self.min_gap = int(self.lua.eval(f'dofile("{PHONE}")').MIN_GAP)

    def service_rom(self):
        super().service_rom()
        mb = self.mb
        if self.mem[mb + ARMED] == 0 and self.mem[mb + REQ] != 0:
            req, self.mem[mb + REQ] = self.mem[mb + REQ], 0   # ack, also for an invalid id
            if req <= 3:
                self.mem[mb + ARMED] = req

    def step(self, n=1):
        for _ in range(n):
            super().step()
            self.phone.service(self.phone)

    def request(self, name):
        return self.phone.request(self.phone, name)

    def posts(self):
        return [b for a, bs in self.writes if a == self.mb + REQ for b in bs]

    def deliver(self):
        """The call script ran: `loadmem ARMED, 0`."""
        self.mem[self.mb + ARMED] = 0
        self.step()


def live(**kw):
    c = PhoneCart(**kw)
    c.step(3)
    assert c.panel.fresh(c.panel)
    c.writes.clear()
    return c


# -- the capability gate: no bit, no write ---------------------------------------------------

@pytest.mark.parametrize("caps", [CAP_PANEL, 0x00, 0xFF])
def test_a_cartridge_without_the_phone_bit_gets_zero_writes(caps):
    c = live(caps=caps)
    for name in ("fallen", "dead_zone", "first_link"):
        c.request(name)
    c.step(20)
    assert c.posts() == [] and list(c.pw.log.values()) == []


def test_a_clean_cartridge_gets_zero_writes():
    c = PhoneCart(patched=False)
    c.step(3)
    c.request("fallen")
    c.step(20)
    assert c.writes == [] and list(c.pw.log.values()) == []


def test_a_stale_mailbox_gets_zero_writes():
    """A beacon with the bit but a stalled counter is last session's mailbox (panel freshness)."""
    c = live()
    c.running = False
    c.step(70)
    c.request("fallen")
    c.step(20)
    assert c.posts() == []


def test_an_unknown_tag_is_ignored():
    c = live()
    assert not c.request("birthday") and not c.request(3)
    c.step(5)
    assert c.posts() == []


# -- one call: post, ack, deliver --------------------------------------------------------------

def test_a_tagged_request_posts_once_and_is_receipted():
    c = live()
    assert c.request("fallen")
    c.step(3)
    assert c.posts() == [FALLEN]
    assert c.mem[c.mb + REQ] == 0 and c.mem[c.mb + ARMED] == FALLEN
    [receipt] = list(c.pw.log.values())
    assert receipt["why"] == "phone" and receipt["addr"] == c.mb + REQ and receipt["n"] == 1


def test_a_posting_with_armed_set_is_refused():
    c = live()
    c.mem[c.mb + ARMED] = DEAD_ZONE          # a call the ROM still holds
    c.request("fallen")
    c.step(30)
    assert c.posts() == []
    c.deliver()
    c.step()
    assert c.posts() == [FALLEN]


def test_a_second_call_waits_the_gap_in_emulator_frames():
    c = live()
    c.request("fallen")
    c.step(2)
    c.deliver()
    c.request("dead_zone")
    c.step(c.min_gap - 5)
    assert c.posts() == [FALLEN]
    c.step(10)
    assert c.posts() == [FALLEN, DEAD_ZONE]


def test_the_gap_counts_emulator_frames_not_the_mailbox_counter():
    """OMP F3: the sampled counter stalls in serial modes and jumps after Card Flip."""
    c = live()
    c.request("fallen")
    c.step(2)
    c.deliver()
    c.request("dead_zone")
    c.mem[c.mb + 5], c.mem[c.mb + 6] = 0xF0, 0xFF   # the counter leaps
    c.step(5)
    assert c.posts() == [FALLEN]


# -- priority ---------------------------------------------------------------------------------

@pytest.mark.parametrize("order", [("first_link", "dead_zone", "fallen"), ("fallen", "first_link", "dead_zone")])
def test_one_queued_call_and_the_higher_priority_wins(order):
    c = live()
    c.mem[c.mb + ARMED] = 9                   # hold the queue
    for name in order:
        c.request(name)
    c.mem[c.mb + ARMED] = 0
    c.step(5)
    assert c.posts() == [FALLEN]
    c.deliver()
    c.step(c.min_gap + 5)
    assert c.posts() == [FALLEN], "the replaced lower calls are gone, not queued behind"


# -- first_link once per session, freshness loss forgets ---------------------------------------

def test_first_link_rings_at_most_once_per_session():
    c = live()
    c.request("first_link")
    c.step(2)
    c.deliver()
    c.step(c.min_gap + 5)
    c.request("first_link")
    c.step(5)
    assert c.posts() == [FIRST_LINK]


def test_a_freshness_loss_forgets_the_call_and_starts_no_gap():
    c = live()
    c.request("fallen")
    c.step(2)
    assert c.posts() == [FALLEN]
    c.running = False                         # Reset: the service stops, the mailbox goes stale
    c.step(70)
    c.mem[c.mb:c.mb + 40] = bytes(40)         # Init clears WRAM
    c.running = True
    c.step(3)
    assert c.mem[c.mb + ARMED] == 0, "the ROM never re-arms a lost call"
    c.request("dead_zone")
    c.step(3)
    assert c.posts() == [FALLEN, DEAD_ZONE], "no retry of FALLEN, no gap from an undelivered call"


def test_constants_equal_patch_gb_slink_abi_inc():
    P = PhoneCart().lua.eval(f'dofile("{PHONE}")')
    abi = _abi()
    assert (P.OFF_REQUEST, P.OFF_ARMED, P.CAP) == (REQ, ARMED, CAP_PHONE) == (
        abi["SLINK_OFS_PHONE_REQUEST"], abi["SLINK_OFS_PHONE_ARMED"], abi["SLINK_CAP_PHONE"])


# -- the production client: the tag on a real command reaches the binder -------------------------

def _production(caps):
    from tests.unit.test_gen2_client import World
    world = World("crystal", production=True)
    mb = world.profile["overlay"]["ram"]["wSlinkMailbox"]
    world.hello()
    if caps is not None:          # a live SLink service: header, caps, cookie, a moving counter
        tick = world.lua.eval("function(emu, mb, caps) return function(n) "
                              "emu.poke('System Bus', mb, {0x53,0x4C,0x4E,0x4B,3,n%256,0,0,caps}) "
                              "emu.poke('System Bus', mb+31, {0xA5}) end end")(world.emu, mb, caps)
        frames = world.frames

        def run(n=1):
            for _ in range(n):
                tick(world.emu.frame)
                frames(1)
        world.frames = run
    world.frames(3)
    return world, mb


@pytest.mark.parametrize("caps, posted", [(CAP_PANEL | CAP_PHONE, [(FALLEN, "System Bus")]),
                                          (CAP_PANEL, []), (None, [])])
def test_the_client_forwards_a_tagged_command_only_to_a_phone_build(caps, posted):
    world, mb = _production(caps)
    world.reply({"cmd": "msgbox", "text": "A and B linked!", "phone": "fallen"})
    world.frames(5)
    assert [(v, d) for a, v, d in world.written() if a == mb + REQ] == posted
