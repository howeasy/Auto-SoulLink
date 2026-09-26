"""C-6 (docs/gen3_requirements.md:130): the deferred command queue is idempotent under the
shipped `SYNC_INFLIGHT_RECONCILES` re-issue window.

`SYNC_INFLIGHT_RECONCILES = 6` (server/state.py:73) is a *re-issue suppression window*, not an
ack deadline (docs/protocol.md:156, docs/gen3/PLAN.md §5.4). A client that holds a keyed sync
command past six reconciler passes gets the same command re-issued, and the reconciler may then
issue the OPPOSITE command for the same key. The oracle is lupa over the PRODUCTION graph
(`lua/gen3/entry.lua` build -> the real `lua/gen3/client.lua` + `lua/core/deferred.lua` + the
real `lua/gen3/boxes.lua`), driven by the fake GBA/server in tests/unit/gen3_world.py. None of
the client, the queue or the box mover is re-implemented here; the only things this file adds
are the ROM tables `boxes.lua` reads (seeded from the ACTIVE profile, no literal addresses) and
Python-side readers over the fake memory.

Each test names the guard that kills it:
  * `box_mon` for an already-boxed key    -> lua/gen3/boxes.lua:376-378 (deposit returns true)
  * `party_mon` for an already-in-party key -> lua/gen3/boxes.lua:414-417 (withdraw returns true)
  * duplicate `memorialize`, still queued -> lua/core/deferred.lua:83-86 (the push-time absorb)
  * `memorialize` re-issued after burial -> lua/gen3/boxes.lua:442-445 (already in the memorial)
  * the opposite command supersedes a held one -> lua/core/deferred.lua:80-82 (OPPOSITE cancel)
  * `stats_cache` carries the PRE-deposit snapshot -> lua/core/deferred.lua:161 (snapshot taken
    before `exec.deposit`) with :168 (sent only after the executor confirms)
  * reconnect inside the window -> lua/core/session.lua:363-366 (a disconnect clears
    `hello_sent`/`pre_hello` only; the deferred queue is untouched) + boxes.lua:376-378 for the
    post-reconnect re-issue's ack.
"""
from __future__ import annotations

import pytest

from server.adapters import gen3_codec as codec
from server.state import SYNC_INFLIGHT_RECONCILES
from tests.unit.gen3_world import World, key_of, mon_record

lupa = pytest.importorskip("lupa")

OT = 0x0000ABCD
A, B, C = 0x11111111, 0x22222222, 0x33333333
KA, KB, KC = key_of(A, OT), key_of(B, OT), key_of(C, OT)

ROM_BASE = 0x08000000
# A reconciler pass is one client tick: lua/core/session.lua:52 TICK_INTERVAL = 30 frames. The
# shipped window is SYNC_INFLIGHT_RECONCILES passes, so outlasting it is this many frames.
TICK = 30
WINDOW_FRAMES = SYNC_INFLIGHT_RECONCILES * TICK
HOLD_FRAMES = WINDOW_FRAMES + 2 * TICK               # two passes of slack past the window
assert HOLD_FRAMES > WINDOW_FRAMES, "the hold must outlast the shipped re-issue window"


# ── harness ───────────────────────────────────────────────────────────────────────────────

def poke_rom(w: World, address: int, data: bytes) -> None:
    """Seed the fake ROM at a ROM-absolute address (w.rom is keyed by rom_offset)."""
    for i, byte in enumerate(data):
        w.rom[address - ROM_BASE + i] = byte


def seed_vanilla_rom(w: World) -> None:
    """The ROM facts lua/gen3/boxes.lua reads: PP restore on deposit (restored_box) and the
    level/stat recompute on withdraw (party_from_box -> vanilla_tail).

    Same tables tests/unit/test_gen3_boxes.py::Cart.seed_vanilla_stats + seed_move_pp seed,
    taken from the ACTIVE profile: the header game code, one base-stats row per species in play
    (HP/Attack base must be non-zero, growth rate < 6), the growth-0 experience row, and the
    PP-Up mask (restored_box asserts each mask byte is non-zero).
    """
    rom, d = w.profile["rom"], w.profile["derived"]
    poke_rom(w, 0x080000AC, b"BPRE")                                # GBA header game code
    base_addr = d["BASESTATS_ADDR_BY_GAME_CODE"]["BPRE"]
    stride, growth_off = d["BASESTATS_ENTRY_SIZE"], d["BASESTATS_GROWTH_RATE_OFFSET"]
    for species in range(1, 12):
        row = bytearray(stride)
        row[:6] = bytes([45, 49, 49, 45, 65, 65])                 # Bulbasaur stat control
        row[growth_off] = 0                                        # medium fast
        poke_rom(w, base_addr + species * stride, bytes(row))
    count = d["EXPERIENCE_TABLE_ENTRY_COUNT"]
    for level in range(d["MAX_LEVEL"] + 1):
        # row 0 is growth 0 (growth_off above), so the row base is the table base
        poke_rom(w, rom["EXPERIENCE_TABLES_ADDR"] + (0 * count + level) * 4,
                 (max(level - 2, 0) * 40).to_bytes(4, "little"))
    poke_rom(w, rom["PP_UP_GET_MASK_ADDR"], b"\x03\x0c\x30\xc0")


def live(party_keys=(A, B, C), frames=60):
    """A connected, hello'd client on a clean overworld checkpoint, with the REAL box mover."""
    w = World("gen3_frlg", "firered")
    seed_vanilla_rom(w)
    w.set_party([mon_record(p, OT, species=4 + i) for i, p in enumerate(party_keys)])
    w.step_to(frames)
    assert w.client.writes_enabled is True
    assert len(w.events("hello")) == 1
    return w


def hold_past_the_window(w: World, cmd: dict) -> None:
    """Queue `cmd`, then keep the checkpoint closed for longer than the re-issue window."""
    w.break_checkpoint()
    w.command(**cmd)
    w.step(HOLD_FRAMES)
    assert w.client.deferred.size(w.client.deferred) == 1, \
        "the command must still be HELD after the whole window elapsed"


# ── Python-side readers over the fake memory (the independent side of every assertion) ─────

def party_mons(w: World) -> list[str]:
    """The live party keys, decoded by the independent Python codec off the fake memory."""
    count = w.bus.get(w.ram["PARTY_COUNT_ADDR"], 0)
    base = w.party_base()
    keys = []
    for slot in range(count):
        raw = bytes(w.bus.get(base + slot * codec.PARTY_MON_SIZE + i, 0)
                    for i in range(codec.PARTY_MON_SIZE))
        mon = codec.decode_party_mon(raw)
        keys.append(f"{mon['personality']:08X}:{mon['ot_id']:08X}")
    return keys


def box_slots_with_key(w: World, key: str, box: int | None = None) -> list[int]:
    """Every slot of one box (or of the whole store) that currently holds `key`."""
    d = w.profile["derived"]
    boxes = range(d["BOXES_PER_STORE"]) if box is None else [box]
    found = []
    for b in boxes:
        for slot in range(d["MONS_PER_BOX"]):
            raw = bytes(w.bus.get(w.box_addr(b, slot) + i, 0) for i in range(codec.BOX_MON_SIZE))
            mon = codec.decode_box_mon(raw)
            if not mon["species"]:
                continue
            if f"{mon['personality']:08X}:{mon['ot_id']:08X}" == key:
                found.append(slot)
    return found


def memorial_box(w: World) -> int:
    return w.profile["derived"]["BOXES_PER_STORE"] - 1


# ── box_mon for a key that is already boxed ───────────────────────────────────────────────

def test_a_box_mon_for_an_already_boxed_key_writes_nothing_and_never_fails():
    """Guard: lua/gen3/boxes.lua:376-378 -- deposit() returns `true` when the key is boxed and
    not in the party, so a re-issued deposit is an accept, not a second copy.

    Removing the guard makes deposit() fall to boxes.lua:378 `return nil, "key not party"`,
    which reaches the wire as `box_mon_failed` -- the failed-event assertion fails.
    """
    w = live(party_keys=(A,))                     # B lives in the box, not in the party
    w.set_box(0, 0, mon_record(B, OT, species=5))
    before = len(w.writes)
    w.command(cmd="box_mon", key=KB)
    w.step()
    assert w.client.deferred.size(w.client.deferred) == 0
    assert w.events("box_mon_failed") == [], "an already-boxed key is not a failed deposit"
    assert len(w.writes) == before, "the re-issued deposit wrote bytes"
    assert w.events("stats_cache") == [], "there is no party record to snapshot"
    assert box_slots_with_key(w, KB) == [0], "the key is still boxed exactly once"


def test_a_box_mon_re_issued_after_its_own_deposit_lands_moves_nothing_a_second_time():
    """Guard: lua/gen3/boxes.lua:376-378, over the shipped re-issue window: the held deposit
    lands once and the re-issue the six-pass window produces is absorbed by that same guard.

    Without the guard the re-issue is `box_mon_failed` and the write count grows.
    """
    w = live()
    hold_past_the_window(w, {"cmd": "box_mon", "key": KB})
    w.overworld_safe()
    w.step()                                       # the held deposit lands
    landed = len(w.writes)
    assert landed > 0 and len(w.events("stats_cache")) == 1
    assert box_slots_with_key(w, KB) == [0]
    w.command(cmd="box_mon", key=KB)              # the re-issue the window produced
    w.step()
    assert w.events("box_mon_failed") == []
    assert len(w.writes) == landed, "the re-issued deposit wrote a second copy"
    assert box_slots_with_key(w, KB) == [0], "the key is boxed exactly once"


# ── party_mon for a key that is already in the party ──────────────────────────────────────

def test_a_party_mon_for_an_already_in_party_key_acks_done_without_writing():
    """Guard: lua/gen3/boxes.lua:414-417 -- withdraw() returns `true` when the key is in the
    party and in no box, so the re-issue answers `sync_retrieve_done`.

    Without the guard it falls to boxes.lua:419 `return nil, "key not boxed"`, which reaches the
    wire as `sync_retrieve_failed` and the ack assertion fails.
    """
    w = live()                                    # B is in the party; the whole store is empty
    before = len(w.writes)
    w.command(cmd="party_mon", key=KB, nickname="MON1")
    w.step()
    assert w.client.deferred.size(w.client.deferred) == 0
    assert [e["key"] for e in w.events("sync_retrieve_done")] == [KB]
    assert w.events("sync_retrieve_failed") == []
    assert len(w.writes) == before, "an already-present key was written again"
    assert party_mons(w) == [KA, KB, KC]


# ── duplicate memorialize ─────────────────────────────────────────────────────────────────

def test_a_duplicate_memorialize_still_queued_is_absorbed_and_executed_once():
    """Guard: lua/core/deferred.lua:83-86 -- a second memorialize for a key that is already
    queued is dropped at push time, so a tail-retrying memorial is never multiplied.

    Without the guard the queue holds two entries; the second run would then be the
    boxes.lua:442-445 ack, so the queue-length assertion is what fails.
    """
    w = live()
    w.break_checkpoint()
    w.command(cmd="memorialize", key=KB)
    w.step(2)
    w.command(cmd="memorialize", key=KB)          # the re-issue while the first is still held
    w.step(2)
    assert w.client.deferred.size(w.client.deferred) == 1, \
        "the duplicate memorialize was queued, not absorbed"
    w.overworld_safe()
    w.step()
    assert w.client.deferred.size(w.client.deferred) == 0
    assert [e["key"] for e in w.events("memorialize_done")] == [KB]
    assert box_slots_with_key(w, KB, box=memorial_box(w)) == [0], "buried once"


def test_a_memorialize_re_issued_after_the_burial_acks_again_without_a_second_write():
    """Guard: lua/gen3/boxes.lua:442-445 -- a key already in the memorial box makes
    memorialize() return `true` instead of choosing a second free slot.

    Without the guard the second run picks the next free memorial slot and writes again; both
    the slot list and the write count break.
    """
    w = live()
    w.command(cmd="memorialize", key=KB)
    w.step()
    buried = len(w.writes)
    assert buried > 0
    (done,) = w.events("memorialize_done")
    assert done["key"] == KB and done["box"] == memorial_box(w)
    assert box_slots_with_key(w, KB, box=memorial_box(w)) == [0]
    w.command(cmd="memorialize", key=KB)          # the re-issue past the window
    w.step()
    assert [e["key"] for e in w.events("memorialize_done")] == [KB, KB]
    assert w.events("memorialize_failed") == []
    assert len(w.writes) == buried, "the re-issued memorial wrote again"
    assert box_slots_with_key(w, KB, box=memorial_box(w)) == [0], "buried once, not twice"


# ── the opposite command, both execution orders ───────────────────────────────────────────

def test_the_opposite_command_cancels_the_held_one_and_is_the_only_thing_that_runs():
    """Guard: lua/core/deferred.lua:80-82 (OPPOSITE at :53) -- pushing the opposite command for
    a key removes the held one, so a six-pass hold cannot deposit a mon the partner has since
    unboxed.

    Without the guard the deposit still runs when the checkpoint opens and the withdrawal then
    has a real move to make, so the zero-write assertion fails.
    """
    w = live()
    hold_past_the_window(w, {"cmd": "box_mon", "key": KB})
    w.command(cmd="party_mon", key=KB, nickname="MON1")   # the reconciler's opposite, FIRST
    w.step(2)
    assert w.client.deferred.size(w.client.deferred) == 1
    w.overworld_safe()
    w.step()
    assert w.client.deferred.size(w.client.deferred) == 0
    # B never left the party, so the withdrawal found it already there (boxes.lua:414-417)
    assert [e["key"] for e in w.events("sync_retrieve_done")] == [KB]
    assert w.events("sync_retrieve_failed") == []
    assert w.events("stats_cache") == [] and w.events("box_mon_failed") == []
    assert len(w.writes) == 0, "the cancelled deposit and the no-op withdrawal both wrote"
    assert box_slots_with_key(w, KB) == []
    assert sorted(party_mons(w)) == sorted([KA, KB, KC])   # a withdrawal appends, as the game does


def test_the_opposite_command_lands_after_the_held_one_executed_and_then_re_issues():
    """Guard: lua/gen3/boxes.lua:414-417 on the second order: the held deposit lands first, the
    reconciler's opposite withdrawal then converges the key to the newest intent, and ITS own
    re-issue is the idempotent ack. One move per delivered command, no record loss, no failure.

    Without the guard the second withdrawal answers `sync_retrieve_failed` ("key not boxed").
    """
    w = live()
    hold_past_the_window(w, {"cmd": "box_mon", "key": KB})
    w.overworld_safe()
    w.step()                                       # order 2: the held deposit lands
    deposited = len(w.writes)
    assert deposited > 0 and box_slots_with_key(w, KB) == [0]
    assert party_mons(w) == [KA, KC]
    w.command(cmd="party_mon", key=KB, nickname="MON1")   # the opposite, AFTER the execution
    w.step()
    withdrawn = len(w.writes)
    assert withdrawn > deposited, "the withdrawal converged the key back into the party"
    assert box_slots_with_key(w, KB) == []
    assert sorted(party_mons(w)) == sorted([KA, KB, KC])   # a withdrawal appends, as the game does
    assert [e["key"] for e in w.events("sync_retrieve_done")] == [KB]
    w.command(cmd="party_mon", key=KB, nickname="MON1")   # its own re-issue: idempotent ack
    w.step()
    assert w.events("sync_retrieve_failed") == []
    assert len(w.events("sync_retrieve_done")) == 2
    assert len(w.writes) == withdrawn, "the re-issued withdrawal wrote again"
    assert party_mons(w) == [KA, KC, KB]   # unchanged by the idempotent re-issue


# ── stats_cache carries the PRE-deposit snapshot ──────────────────────────────────────────

def test_stats_cache_carries_the_pre_deposit_snapshot_not_the_zeroed_party_record():
    """Guard: lua/core/deferred.lua:161 -- the stats are read off the party mon BEFORE
    `exec.deposit` runs (the move compacts the party and zeroes the vacated slot) and sent only
    after the executor confirms (deferred.lua:168).

    Without the guard (snapshot taken after the move) the payload is the vacated slot's zeros.
    """
    w = live()
    assert party_mons(w) == [KA, KB, KC]
    w.command(cmd="box_mon", key=KB)
    w.step()
    (cache,) = w.events("stats_cache")
    assert cache["key"] == KB
    # the party record for KB is gone: the payload can only be the pre-move snapshot
    assert party_mons(w) == [KA, KC]
    assert cache["stats"]["level"] == 5 and cache["stats"]["maxHP"] == 20
    assert cache["stats"]["attack"] == 11 and cache["stats"]["spAtk"] == 14
    assert cache["stats"]["spDef"] == 15
    assert cache["stats"]["pp1"] == 35 and cache["stats"]["pp2"] == 30


# ── reconnect inside the window ───────────────────────────────────────────────────────────

def test_a_reconnect_inside_the_window_keeps_the_held_command_and_its_reissue_is_idempotent():
    """Guards: lua/core/session.lua:363-366 (a disconnect clears `hello_sent`/`pre_hello` only;
    the deferred queue is untouched) and lua/gen3/boxes.lua:376-378 (the re-issue that arrives
    after the reconnect is the idempotent ack).

    Without the second guard the post-reconnect re-issue is `box_mon_failed`; without the first,
    the held command is gone and the "still queued" assertion fails.
    """
    w = live()
    w.break_checkpoint()
    w.command(cmd="box_mon", key=KB)
    w.step(HOLD_FRAMES // 2)
    w.connected = False
    w.step(2)                                      # the connection drops mid-hold
    assert w.client.deferred.size(w.client.deferred) == 1, "a disconnect dropped the held command"
    w.connected = True
    # the rest of the window, still held: the checkpoint is closed, so no hello can go out yet
    w.step(HOLD_FRAMES - HOLD_FRAMES // 2 - 2)
    assert len(w.events("hello")) == 1
    assert w.client.deferred.size(w.client.deferred) == 1, \
        "the command did not stay held for the whole re-issue window"
    w.overworld_safe()
    w.step()                                       # the reconnect hello goes out, then the deposit
    assert len(w.events("hello")) == 2
    landed = len(w.writes)
    assert landed > 0 and box_slots_with_key(w, KB) == [0]
    assert party_mons(w) == [KA, KC]
    w.command(cmd="box_mon", key=KB)               # the re-issue, now the whole window past
    w.step()
    assert w.events("box_mon_failed") == []
    assert len(w.writes) == landed, "the re-issued deposit wrote a second copy"
    assert box_slots_with_key(w, KB) == [0]
