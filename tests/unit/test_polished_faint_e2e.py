"""Composed F1 -> native ResolveFaints -> OBS -> FS settlement, MODEL only.

The real overlay executes the HP predicate, FAINTED SET, faint ordering and
player copyback. Audio/animation/text callees are trapped; no native witness,
capture binding or FS clock is invented by the positive test. Registered Lua
callbacks run at the CPU's actual pre/post-copy PCs over the CPU's RAM image.
Both opt-ins are supplied to ONE entry.build client. Commanded deaths emit
ordinary HP-zero ticks and one local KO, never a natural-faint wire echo.

The positive's seeded link is in the real Polished SoulLinkState: its partner
faint produces the delivered command, and the client's HP0 ticks return to State.
No emulator, interrupt/banking/timing, animation, save durability, socket server
or production enablement is proved. Source mutants live in memory only.
"""
from __future__ import annotations

import pytest

from server.state import LinkStatus
from tests.unit import (
    test_polished_explode_path as br,
    test_polished_faint_client as fc,
    test_polished_faint_observer as obs,
    test_polished_plain_faint as pf,
)
from tests.unit.polished_sm83 import SM83
from tests.unit.polished_state_rig import new_state, seed_pair
from tests.unit.test_polished_write_path import SYM, key_of, overlay

POST_PC = 0x44CD
PRE_PC = 0x44C8
MEDIA_TRAPS = (
    "BreakAttractionAndResetMirrorHerb", "SetVariableBattleMusicCondition",
    "WaitSFX", "PlaySlowCryBC", "PlaySFX", "PlayerMonFaintedAnimation",
    "PlayerMonFaintHappinessMod", "ClearPlayerHUD", "LoadTileMapToTempTileMap",
    "StdBattleTextbox",
)


def staged(overrides=None, command_factory=None):
    rig, mons = obs.build(overrides=overrides)
    assert rig.client.faint_settle is not None
    assert rig.log["hook_at"][obs.HOOK] == POST_PC
    key = key_of(mons[0])
    if command_factory is None:
        br.order(rig, "force_faint", mons)
    else:
        command = command_factory(rig, mons)
        assert command["cmd"] == "force_faint" and command["key"] == key
        rig.client.handle_command(rig.client, rig.lua.table_from(command))
    ob = fc.owner(rig)
    assert ob.state == "pending" and rig.writes() == []
    br.at_hold(rig)
    assert ob.state == "awaiting" and ob.kind == "plain"
    assert [w["addr"] for w in rig.writes()] == pf.addresses()
    assert rig.hp(0) == 0 and rig.status(0) == 0
    assert rig.get("wPlayerSubStatus2") & 4 == 0, "F1 must not forge native FAINTED"
    assert rig.get("wWhichMonFaintedFirst") == 1
    assert not rig.client.dead_keys[key] and fc.ko(rig) == []
    return rig, mons, ob


def native_resolve(rig, *, post=True):
    """Run real ResolveFaints and fire any registered observer at instruction entry.

    Traps suppress only unrelated presentation/happiness/cleanup boundaries.
    HasUserFainted/GetBattleVarAddr, FAINTED SET, SwitchTurn, both copyback
    routines and CheckPlayerPartyForFitPkmn execute their overlay ROM bytes.
    """
    # Seed the SAME setup bytes in the client bus and CPU (poke is unlogged).
    rig.put("wBattleMode", 2)  # trainer battle: no victory music branch
    rig.put("wEnemyMonHP", 0)
    rig.put("wEnemyMonHP", 9, 1)
    rig.put("hBattleTurn", 1)
    cpu = SM83(overlay()[1], bank=15, hrombank=SYM["hROMBank"][1])
    for address, value in rig.mem.items():
        if address >= 0x8000:
            cpu.poke(address, value)
    trapped = []
    for name in MEDIA_TRAPS:
        bank, address = SYM[name]
        cpu.trap(address, lambda _cpu, n=name: trapped.append(n), bank=bank or None)
    visits = []
    step = cpu.step

    def sync():
        for _, address, _ in cpu.writes:
            rig.mem[address] = cpu.peek(address)[0]
        rig.put("hROMBank", cpu.bank)

    def with_callbacks():
        if cpu.bank == 15 and cpu.pc in (PRE_PC, POST_PC):
            sync()
            for label in obs.POINTS:
                span = 2 if label == "wBattleMonHP" else 1
                address = SYM[label][1]
                assert bytes(rig.mem[address + i] or 0 for i in range(span)) == cpu.peek(address, span)
            visits.append(cpu.pc)
            name = "SLink-gen2-polished:" + ("battle_faint" if cpu.pc == PRE_PC else obs.SITE)
            if rig.log["hook_at"][name] is not None and (cpu.pc != POST_PC or post):
                obs.fire(rig, name=name, pc=cpu.pc, bank=cpu.bank)
        step()

    cpu.step = with_callbacks
    result = cpu.call_routine(SYM["ResolveFaints"][1], sp=0xC100)
    assert result.returned and result.sp_delta == 0
    sync()
    assert visits == [PRE_PC, POST_PC]
    assert "PlayerMonFaintedAnimation" in trapped
    assert rig.get("wPlayerSubStatus2") & 4
    assert rig.get("wWhichMonFaintedFirst") == 0
    assert any(address == SYM["wPlayerSubStatus2"][1] and value & 4
               for _, address, value in result.writes), "native SET was never executed"
    return result


def assert_awaiting(rig, ob, *, natural_key=None):
    assert ob.state == "awaiting" and ob.obs_seq is None, "settled without bound native evidence"
    assert fc.ko(rig) == [] and not rig.client.dead_keys[ob.key]
    if natural_key is None:
        assert rig.sent("faint") == []
    else:
        assert natural_key != ob.key
        assert [event["key"] for event in rig.sent("faint")] == [natural_key]


def settled_once(overrides=None, command_factory=None):
    rig, mons, ob = staged(overrides, command_factory)
    writes = rig.writes()
    attempt = ob.attempts[1]
    fc.tick(rig)  # own zero bytes are insufficient
    assert_awaiting(rig, ob)
    native_resolve(rig)
    assert fc.FS(rig).seq > attempt.seq
    captured = fc.FS(rig).seq
    assert_awaiting(rig, ob)  # callback enqueues; it cannot complete
    rig.frame(1)  # production frame_end drains the frozen capture
    assert ob.obs_seq == captured and ob.state == "awaiting"
    fc.tick(rig)
    assert ob.state == "done" and len(fc.ko(rig)) == 1
    assert rig.client.dead_keys[key_of(mons[0])]
    assert rig.sent("tick")[-1]["party"][0]["hp"] == 0
    assert rig.sent("faint") == []
    obs.fire(rig)  # same attempt's duplicate callback has no eligible owner
    rig.frame(1)
    fc.tick(rig)
    br.order(rig, "force_faint", mons)  # server redelivery cannot repeat this KO
    br.at_hold(rig)
    fc.tick(rig)
    assert len(fc.ko(rig)) == 1, "same attempt settled twice"
    assert rig.writes() == writes, "duplicate settlement repeated a writer operation"
    assert rig.sent("faint") == []
    return rig


def test_plain_faint_settles_once_through_native_copyback_and_registered_producer(tmp_path):
    state = new_state(tmp_path)
    tick_start = None

    def server_command(rig, mons):
        nonlocal tick_start
        key, partner = key_of(mons[0]), key_of(mons[1])
        entry = seed_pair(state, key, partner, a_party=True, b_party=True)
        # A surviving link keeps this a continuing run: State stops repair after game_over.
        seed_pair(state, key_of(mons[2]), key_of(br.party(4)[3]), area="route_30",
                  a_party=True, b_party=True)
        state.party_keys["a"] = {key_of(mon) for mon in mons}
        state.party_size["a"], state.party_size["b"] = len(mons), 2
        state.handle_event("b", {"event": "faint", "key": partner})
        assert entry.status == LinkStatus.DEAD and not state.run_over
        commands = state.handle_event("a", {"event": "tick", "in_battle": True})
        command, = [cmd for cmd in commands if cmd["cmd"] == "force_faint"]
        tick_start = len(rig.sent("tick"))  # exclude startup overworld telemetry
        return command  # actual death command, unchanged; memorialization is a separate obligation

    rig = settled_once(command_factory=server_command)
    key = state.links[0].a.key
    # HP-zero telemetry clears a prior repair incident without a new faint echo.
    state.faint_repairs["a"][key] = 1
    state.faint_repair_stalled["a"][key] = 1
    assert tick_start is not None
    ticks = rig.sent("tick")[tick_start:]
    assert ticks and all(tick["in_battle"] is True and tick["party"][0]["hp"] == 0 for tick in ticks)
    assert state.faint_repairs["a"][key] == state.faint_repair_stalled["a"][key] == 1
    for tick in ticks:
        state.handle_event("a", tick)
    assert state.links[0].status == LinkStatus.DEAD
    assert key not in state.faint_repairs["a"] and key not in state.faint_repair_stalled["a"]
    assert state.party_size["a"] == rig.count()


@pytest.mark.parametrize("case", ["wrong-slot", "stale-generation", "before-write"],
                         ids=["wrong-slot", "stale-generation", "before-write"])
def test_other_slot_stale_capture_and_prior_native_faint_cannot_settle(case):
    natural_key = None
    if case == "before-write":
        rig, mons = obs.build()
        br.order(rig, "force_faint", mons)
        ob = fc.owner(rig)
        assert ob.state == "pending" and len(ob.attempts) == 0
        # A native faint BEFORE this command's writer attempt cannot bind to it.
        rig.put("wBattleMonHP", 0)
        rig.put("wBattleMonHP", 0, 1)
        rig.put("wBattleMonStatus", 0)
        rig.put("wWhichMonFaintedFirst", 1)
        seq = fc.FS(rig).seq
        native_resolve(rig)
        assert fc.FS(rig).seq == seq and rig.client.signals.status(rig.client.signals).pending == 1
        assert rig.writes() == []
        rig.io.register = rig.lua.eval("function(n) return n == 'PC' and 0x416A or 0 end")
        br.at_hold(rig)  # F1's already-native-fainted, zero-write outcome still awaits a NEW capture
        assert ob.state == "awaiting" and len(ob.attempts) == 1 and rig.writes() == []
    else:
        rig, mons, ob = staged()
        seq = fc.FS(rig).seq
        if case == "wrong-slot":
            rig.put("wCurBattleMon", 1)
            native_resolve(rig)
            assert rig.hp(1) == 0  # real copyback was for another occupied slot
            natural_key = key_of(mons[1])
            assert fc.FS(rig).seq == seq and rig.client.signals.status(rig.client.signals).pending == 1
        else:
            native_resolve(rig)
            before_copy, batch = obs.batches(rig)
            observation, faint = list(before_copy.events.values())
            assert observation.phase == "before_party_copyback" and observation.capture is None
            assert faint.kind == "faint" and faint.mon.key == ob.key
            obs.consume(rig, before_copy)  # deliver natural events; only the post-copy envelope is made stale
            assert batch.events[1].capture.attempt_seq == ob.attempts[1].seq
            batch.generation -= 1  # genuinely captured payload delivered under a stale epoch envelope
            obs.consume(rig, batch)
            assert fc.FS(rig).seq == batch.events[1].capture.seq
    rig.frame(1)
    fc.tick(rig)
    assert_awaiting(rig, ob, natural_key=natural_key)


def legacy_queued(overrides=None):
    rig, mons = obs.build(enabled=False, interface=False, overrides=overrides)
    assert rig.client.faint_settle is None and rig.log["hook_at"][obs.HOOK] is None
    sent = len(rig.sent())
    br.order(rig, "force_faint", mons)
    br.at_hold(rig)
    assert rig.hp(0) == 300 and rig.writes() == [] and len(rig.client.pending_battle_writes) == 1
    assert any("not composed on Polished" in line for line in rig.lines())
    rig.put("wBattleMode", 0)
    rig.put("hROMBank", 0x25)
    rig.frame(3)
    assert len(rig.client.pending_battle_writes) == 0
    assert rig.hp(0) == 0 and rig.status(0) == 0 and rig.hp(1) == 300
    fc.tick(rig)
    assert rig.sent("faint") == []
    return rig.sent()[sent:], rig.writes()


def test_flags_off_sent_events_equal_existing_queued_overworld_path():
    expected_rig, mons = br.ready()  # existing rig with neither flag supplied
    sent = len(expected_rig.sent())
    br.order(expected_rig, "force_faint", mons)
    br.at_hold(expected_rig)
    assert expected_rig.hp(0) == 300 and expected_rig.writes() == []
    expected_rig.put("wBattleMode", 0)
    expected_rig.put("hROMBank", 0x25)
    expected_rig.frame(3)
    fc.tick(expected_rig)
    expected = expected_rig.sent()[sent:], expected_rig.writes()
    assert expected[0] and any(m["event"] == "tick" and m["party"][0]["hp"] == 0 for m in expected[0])
    assert legacy_queued() == expected  # complete wire fields/seq/order and write sequence, not event names alone


def mutated_method(path, start, end, pairs):
    """Exact, bounded source-copy mutation; never write a runtime file."""
    source = obs.SOURCES[path]
    lo, hi = source.index(start), source.index(end, source.index(start))
    body = source[lo:hi]
    for old, new in pairs:
        assert body.count(old) == 1, f"mutant anchor drifted: {old!r}"
        body = body.replace(old, new)
    return source[:lo] + body + source[hi:]


def no_native_flag(overrides=None):
    rig, _, ob = staged(overrides)
    assert rig.get("wPlayerSubStatus2") & 4 == 0
    obs.fire(rig)  # HP mirrors are F1's own zero bytes; native flag is absent
    rig.frame(1)
    fc.tick(rig)
    assert_awaiting(rig, ob)


def test_red_control_capture_without_native_fainted_cannot_complete():
    no_native_flag()
    signals = obs.SOURCES[obs.SIGNALS]
    old = "or b.link_mode ~= 0 or not b.fainted"
    assert signals.count(old) == 1
    signals = signals.replace(old, "or b.link_mode ~= 0")
    client = obs.SOURCES[obs.CLIENT]
    for old, new in (
        ("or b.fainted ~= true then return nil end", "then return nil end"),
        ("and b.fainted == true then", "then"),
        ("native and native.fainted == true and native.hp == 0", "native and native.hp == 0"),
    ):
        assert client.count(old) == 1
        client = client.replace(old, new)
    with pytest.raises(AssertionError, match="settled without bound native evidence"):
        no_native_flag({obs.SIGNALS: signals, obs.CLIENT: client})


PRE_SITES = ('battle_sites=deps.polished_faint_observer == true '
             'and {"battle_faint", "whiteout_before_heal", "battle_faint_copyback_return"} or {"battle_faint", "whiteout_before_heal"},')


def pre_copy_only(overrides=None):
    entry = obs.SOURCES[obs.ENTRY]
    assert entry.count(PRE_SITES) == 1
    overrides = dict(overrides or {})
    overrides[obs.ENTRY] = entry  # pre-copy registration is now production-default, not a test-only addition
    rig, _, ob = staged(overrides)
    native_resolve(rig, post=False)  # registered 44c8 callback only; no post-copy evidence
    rig.frame(1)
    fc.tick(rig)
    assert_awaiting(rig, ob)


def test_red_control_pre_copy_observation_cannot_complete():
    pre_copy_only()
    # Deliberately bind at the OLD physical callback and weaken the consumer's phase guard.
    # The real authority still allocates capture.seq synchronously; the test never mints it.
    source = mutated_method(obs.SIGNALS, "        local function faint_boundary(",
                            "        -- This instruction is after", [
        ('return batch(events,context,held)',
         'local b={slot=slot,hp=wram("wBattleMonHP",2),status=0,mode=mode,link_mode=wram("wLinkMode"),fainted=true}\n'
         '            local captured=authority.capture_faint(b,held)\n'
         '            events[1]=observation(prepared.id,battle_sites[prepared.id],{battle=b,capture=captured})\n'
         '            return batch(events,context,held)'),
    ])
    client = obs.SOURCES[obs.CLIENT]
    old = 'and ev.phase == "after_party_copyback"'
    assert client.count(old) == 1
    with pytest.raises(AssertionError, match="settled without bound native evidence"):
        pre_copy_only({obs.SIGNALS: source, obs.CLIENT: client.replace(old, "and true")})


def test_red_control_same_attempt_cannot_settle_twice():
    # Keep a done owner and incorrectly let later ticks complete it again.
    client = mutated_method(obs.CLIENT, "    function FS.complete(",
                            "    -- an attempt of partial", [("        FS.remove(ob)", "        -- mutant retains owner")])
    lo = client.index("    function FS.after_tick(")
    hi = client.index("    -- The post-copy producer", lo)
    body = client[lo:hi]
    old = 'ob.state == "awaiting"'
    assert body.count(old) == 1
    body = body.replace(old, '(ob.state == "awaiting" or ob.state == "done")')
    with pytest.raises(AssertionError, match="same attempt settled twice"):
        settled_once({obs.CLIENT: client[:lo] + body + client[hi:]})
