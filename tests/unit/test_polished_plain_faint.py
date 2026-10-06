"""F1 bounded plain faint: real composed facade/permit, fake synchronous CPU hold.

No client settlement, native action cancellation or physical qualification claim.
Mutants run the same observed-state assertions as the real writer. F0 separately
tests native consumption; these tests do not pretend that memory writes animate.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.unit import test_polished_explode_path as battle_rig
from tests.unit.test_polished_explode_path import SYM, lcall, ready, snapshot
from tests.unit.test_polished_plain_faint_engine import resolve_visits
from tests.unit.test_polished_write_path import key_of, overlay

ROOT = Path(__file__).resolve().parents[2]
WRITER = "lua/gen2/polished_writes.lua"
FACADE = "lua/gen2/polished_explode.lua"
SOURCE = {p: (ROOT / p).read_text() for p in (WRITER, FACADE)}


def setup(*, order=0, overrides=None, faults=False):
    harness = battle_rig.HARNESS_HOOKS
    if faults:
        harness = harness.replace("function io.read_u8(a, d)", """function io.read_u8(a, d)
            if io.f1_touched and a == io.f1_at and io.f1_fault == 'unreadable' then return nil end""")
        harness = harness.replace("function io.write_u8(a, v, d)", """function io.write_u8(a, v, d)
            if a == io.f1_at then
                io.f1_touched = true
                if io.f1_fault == 'swallow' then return end
                if io.f1_fault == 'throw-before' then error('injected before-write',0) end
            end""")
        harness = harness.replace('else mem[a] = v end', """else mem[a] = v end
            if a == io.f1_at and io.f1_fault == 'throw-after' then error('injected after-write',0) end""")
    with patch.object(battle_rig, "HARNESS_HOOKS", harness):
        rig, mons = ready(overrides=overrides)
    rig.io.register = rig.lua.eval("function(name) return name == 'PC' and 0x416A or nil end")
    rig.put("wBattleMonHP", 1)
    rig.put("wBattleMonHP", 44, 1)
    rig.put("wBattleMonStatus", 8)
    rig.put("wPlayerSubStatus2", 0)
    rig.put("wPlayerSwitchTarget", 0)
    rig.put("wDeferredSwitch", 0)
    rig.put("wWhichMonFaintedFirst", order)
    return rig, mons


def addresses(slot=0):
    base = SYM["wPartyMons"][1] + 48 * slot
    return [SYM["wBattleMonStatus"][1], base + 32, base + 34, base + 35,
            SYM["wBattleMonHP"][1], SYM["wBattleMonHP"][1] + 1, SYM["wWhichMonFaintedFirst"][1]]


def call(rig, mons, *, hooked=True, after_arm=None, allow=None, **fields):
    writer, entry = rig.parts.battle.writes, rig.parts.battle.entry
    if hooked:
        entry.enter("explode")
    ok, why = lcall(rig, writer.arm, writer, "battle_hold", allow)
    if ok:
        if after_arm:
            after_arm()
        ok, why = lcall(rig, writer.faint_active_battler, writer, 0,
                        snapshot(rig, key=key_of(mons[0]), **fields))
    writer.disarm(writer)
    entry.leave()
    return ok, str(why)


def assert_landed(rig, before, order):
    expected = addresses()[:6] + ([] if order else addresses()[6:])
    assert [w["addr"] for w in rig.writes()] == expected, "exact faint write order"
    for a in addresses()[:6]:
        assert rig.mem[a] == 0, "HP/status zero"
    assert rig.get("wWhichMonFaintedFirst") == (order or 1), "native order preserved"
    after = dict(rig.mem.items())
    for a in set(before) | set(after):
        if a not in expected:
            assert before.get(a, 0) == after.get(a, 0), f"unexpected write {a:04x}"


@pytest.mark.parametrize("order", [0, 1, 2], ids=["notify-player", "keep-player", "keep-enemy"])
def test_exact_bytes_order_and_no_other_state_changed(order):
    rig, mons = setup(order=order)
    before = dict(rig.mem.items())
    ok, why = call(rig, mons)
    assert ok, why
    assert_landed(rig, before, order)


CASES = [
    ("switch", "wPlayerSwitchTarget", 1, "pending player switch"),
    ("deferred", "wDeferredSwitch", 1, "deferred switch"),
    ("transform", "wPlayerSubStatus2", 0x10, "Transform refused"),
    ("fainted-live", "wPlayerSubStatus2", 4, "FAINTED flag with live HP"),
    ("order", "wWhichMonFaintedFirst", 3, "invalid faint order"),
    ("item", "wBattlePlayerAction", 1, "needs USEMOVE"),
    ("link", "wLinkMode", 1, "link"),
    ("bank", "hROMBank", 0x25, "hold"),
    ("mode", "wBattleMode", 0, "battle"),
    ("active", "wCurBattleMon", 1, "target changed"),
]


@pytest.mark.parametrize("_case,label,value,reason", CASES, ids=[c[0] for c in CASES])
def test_refusal_has_named_reason_and_zero_writes(_case, label, value, reason):
    rig, mons = setup()
    rig.put(label, value)
    ok, why = call(rig, mons)
    assert not ok and reason.lower() in why.lower(), why
    assert rig.writes() == []


@pytest.mark.parametrize("case", ["pc", "hook", "key", "species", "preimage", "mapping", "late-span"],
                         ids=["wrong-pc", "no-token", "changed-key", "species-mismatch", "changed-record",
                              "unmapped", "late-span-preflight"])
def test_additional_identity_and_permit_refusals(case):
    rig, mons = setup()
    fields, hook, after, allow = {}, True, None, None
    expected = ""
    if case == "pc":
        rig.io.register = rig.lua.eval("function() return 0x416B end")
        expected = "PC/bank"
    elif case == "hook":
        hook, expected = False, "inside the explode"
    elif case == "key":
        rig.put("wPartyMon1DVs", (rig.get("wPartyMon1DVs") + 1) % 256)
        expected = "key changed"
    elif case == "species":
        rig.put("wBattleMonSpecies", 1)
        expected = "species mismatch"
    elif case == "preimage":
        # After the facade's fresh keyed read but before low-level revalidation.
        facade = SOURCE[FACADE].replace("return writer:faint_active_battler(slot, snap)",
            "snap.party_record[2] = (snap.party_record[2] + 1) % 256\n"
            "        return writer:faint_active_battler(slot, snap)")
        rig, mons = setup(overrides={FACADE: facade})
        expected = "preimage changed"
    elif case == "mapping":
        # Reject the LAST span: Permit must preflight it before any earlier byte.
        bad = addresses()[6]
        rig.io.bank_valid = rig.lua.eval(f"function(bank, a, n) return not (a <= {bad} and a+n > {bad}) end")
        expected = "read"
    else:
        allow = rig.lua.eval(f"function(d,a,n) return a ~= {addresses()[6]} end")
        expected = "outside the battle_hold window"
    ok, why = call(rig, mons, hooked=hook, after_arm=after, allow=allow, **fields)
    assert not ok, why
    assert expected.lower() in why.lower(), why
    assert rig.writes() == []


def test_faint_coordinates_are_pinned_symbols():
    rig, _ = setup()
    mod = rig.lua.eval(f'dofile("{ROOT.as_posix()}/lua/gen2/polished_explode.lua")')
    for name, row in mod.FAINT_COORDS.items():
        assert tuple(row.values()) == SYM[name]


@pytest.mark.parametrize("order,fainted", [(1, False), (2, False), (0, True)],
                         ids=["player-pending", "enemy-pending", "native-already-fainted"])
def test_already_zero_is_idempotent_without_order_retrigger(order, fainted):
    rig, mons = setup(order=order)
    for a in addresses()[:6]:
        rig.mem[a] = 0
    rig.put("wPlayerSubStatus2", 4 if fainted else 0)
    ok, why = call(rig, mons)
    assert ok, why
    assert rig.writes() == [] and rig.get("wWhichMonFaintedFirst") == order


def assert_player_notification(rig, start):
    assert [w["addr"] for w in rig.writes()[start:]] == [addresses()[6]], "repair writes only notification"
    assert all(rig.mem[a] == 0 for a in addresses()[:6])
    assert rig.get("wWhichMonFaintedFirst") == 1, "player notification present"
    # F0 executes the built ResolveFaints selector; its FaintUserPokemon trap
    # observes dispatch/order only, not native animation or complete whiteout.
    assert resolve_visits((overlay()[1], SYM), rig.get("wWhichMonFaintedFirst")) == [0, 1]


def test_zero_hp_without_pending_or_processed_faint_repairs_notification():
    rig, mons = setup()
    for a in addresses()[:6]:
        rig.mem[a] = 0
    ok, why = call(rig, mons)
    assert ok, why
    assert_player_notification(rig, 0)


@pytest.mark.parametrize("fault", ["swallow", "throw-before", "throw-after"],
                         ids=["lost-order-byte", "order-write-throws", "order-landed-then-throws"])
def test_final_notification_fault_then_fresh_retry_dispatches_player_faint(fault):
    rig, mons = setup(faults=True)
    rig.io.f1_at, rig.io.f1_fault = addresses()[6], fault
    ok, why = call(rig, mons)
    assert not ok and "PARTIAL ACTIVE FAINT" in why, why
    assert all(rig.mem[a] == 0 for a in addresses()[:6])
    assert rig.get("wWhichMonFaintedFirst") == (1 if fault == "throw-after" else 0)
    rig.io.f1_fault = None
    start = len(rig.writes())
    # call() takes the unchanged key, but the facade rereads the now-zero record.
    ok, why = call(rig, mons)
    assert ok, why
    if fault == "throw-after":
        assert len(rig.writes()) == start, "already pending notification must not retrigger"
        assert resolve_visits((overlay()[1], SYM), rig.get("wWhichMonFaintedFirst")) == [0, 1]
    else:
        assert_player_notification(rig, start)


def test_control_returning_success_without_notification_fails_repair_oracle():
    old = 'if order ~= 0 or (sub & 0x04) ~= 0 then'
    assert SOURCE[WRITER].count(old) == 1
    rig, mons = setup(overrides={WRITER: SOURCE[WRITER].replace(old, 'if true then')})
    for a in addresses()[:6]:
        rig.mem[a] = 0
    ok, why = call(rig, mons)
    assert ok, why
    assert resolve_visits((overlay()[1], SYM), rig.get("wWhichMonFaintedFirst")) == []
    with pytest.raises(AssertionError, match="repair writes only notification"):
        assert_player_notification(rig, 0)


@pytest.mark.parametrize("fault", ["swallow", "throw-before"], ids=["repair-drop", "repair-throws"])
def test_notification_only_repair_failure_is_still_partial(fault):
    rig, mons = setup(faults=True)
    for a in addresses()[:6]:
        rig.mem[a] = 0
    rig.io.f1_at, rig.io.f1_fault = addresses()[6], fault
    ok, why = call(rig, mons)
    assert not ok and "PARTIAL ACTIVE FAINT" in why, why
    assert f'{addresses()[6]:04X}=00' in why.split("observed=", 1)[1]
    assert all(rig.mem[a] == 0 for a in addresses()[:6])
    assert all(w["addr"] == addresses()[6] for w in rig.writes())
    assert rig.parts.battle.writes.armed is None


@pytest.mark.parametrize("mutant", [False, True], ids=["unsettled-mirror", "ignore-mirror-control"])
def test_zero_battle_hp_does_not_hide_an_unsettled_party_mirror(mutant):
    source = SOURCE[WRITER]
    if mutant:
        source = source.replace('before[1] == 0 and before[2] == 0 and before[3] == 0 and before[4] == 0', 'true')
    # Keep a notification pending: isolate the mirror guard from repair readback.
    rig, mons = setup(order=1, overrides={WRITER: source})
    rig.put("wBattleMonHP", 0)
    rig.put("wBattleMonHP", 0, 1)
    ok, why = call(rig, mons)
    assert rig.writes() == []
    if mutant:
        with pytest.raises(AssertionError, match="unsettled cannot complete"):
            assert not ok, "unsettled cannot complete"
    else:
        assert not ok and "unsettled mirror/status" in why


@pytest.mark.parametrize("case", ["swallow", "throw-after", "unreadable"],
                         ids=["silent-hp-drop", "write-then-throw", "readback-unreadable"])
def test_partial_failure_reports_actual_observed_bytes(case):
    rig, mons = setup(faults=True)
    at = SYM["wBattleMonHP"][1]
    rig.io.f1_at, rig.io.f1_fault = at, case
    ok, why = call(rig, mons)
    assert not ok and "PARTIAL ACTIVE FAINT" in why and "before=" in why and "observed=" in why, why
    observed = why.split("observed=", 1)[1]
    for a in addresses():
        want = "UNREADABLE" if case == "unreadable" and a == at else f"{int(rig.mem[a] or 0):02X}"
        assert f"{a:04X}={want}" in observed
    assert rig.writes() and rig.parts.battle.writes.armed is None


MUTANTS = [
    ("switch", 'read("wPlayerSwitchTarget") == 0', 'true', "wPlayerSwitchTarget", 1),
    ("deferred", 'read("wDeferredSwitch") == 0', 'true', "wDeferredSwitch", 1),
    ("transform", '(sub & 0x10) == 0', 'true', "wPlayerSubStatus2", 0x10),
    ("fainted-live", '(sub & 0x04) == 0 or zero', 'true', "wPlayerSubStatus2", 4),
    ("order", 'integer(order, 0, 2)', 'true', "wWhichMonFaintedFirst", 3),
    ("item", 'snapshot.player_action == 0 and read("wBattlePlayerAction") == 0', 'true', "wBattlePlayerAction", 1),
]


@pytest.mark.parametrize("_name,old,new,label,value", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_removed_guard_defeats_the_same_zero_write_oracle(_name, old, new, label, value):
    assert SOURCE[WRITER].count(old) == 1
    rig, mons = setup(overrides={WRITER: SOURCE[WRITER].replace(old, new)})
    rig.put(label, value)
    call(rig, mons)
    with pytest.raises(AssertionError, match="zero-write refusal"):
        assert rig.writes() == [], "zero-write refusal"


@pytest.mark.parametrize("case", ["pc", "key", "species", "hook", "active", "bank", "link", "mode", "record"],
                         ids=["pc-gate", "key-binding", "species-binding", "entry-token", "active-slot",
                              "bank-gates", "link-gates", "mode-gates", "record-binding"])
def test_identity_and_context_mutants_defeat_zero_write_oracle(case):
    writer, facade = SOURCE[WRITER], SOURCE[FACADE]
    if case == "pc":
        writer = writer.replace('io.register("PC") == hold.execution_before.pc', 'true')
    elif case == "key":
        facade = facade.replace('if mon.key == snap.key then', 'if mon.slot == slot then')
    elif case == "species":
        facade = facade.replace('assert(species_matches(target),', 'assert(true,')
    elif case == "hook":
        facade = facade.replace('assert(entered == site,', 'assert(true,')
    elif case == "active":
        writer = writer.replace('snapshot.active_slot == slot and read("wCurBattleMon") == slot', 'true')
    elif case == "record":
        facade = facade.replace('return writer:faint_active_battler(slot, snap)',
            'snap.party_record[2] = (snap.party_record[2] + 1) % 256\n'
            '        return writer:faint_active_battler(slot, snap)')
        writer = writer.replace('read("wPartyMons", base + i - 1) == snapshot.party_record[i]', 'true')
    else:
        # These have TWO independent defences: writer state + ownership recheck.
        # Arm with valid state, then invalidate it before the guarded call.
        facade = facade.replace('return kind ~= nil and battle:check(kind) == true', 'return kind ~= nil')
        old = {'bank': 'read("hROMBank") == hold.execution_before.bank',
               'link': 'read("wLinkMode") == 0',
               'mode': '(mode == 1 or mode == c.TRAINER_BATTLE) and snapshot.mode == mode'}[case]
        writer = writer.replace(old, 'true')
    rig, mons = setup(overrides={WRITER: writer, FACADE: facade})
    after = None
    if case == "pc":
        rig.io.register = rig.lua.eval('function() return 0x416B end')
    elif case == "key":
        rig.put("wPartyMon1DVs", (rig.get("wPartyMon1DVs") + 1) % 256)
    elif case == "species":
        rig.put("wBattleMonSpecies", 1)
    elif case == "active":
        rig.put("wCurBattleMon", 1)
    elif case in ("bank", "link", "mode"):
        label, value = {'bank': ('hROMBank', 0x25), 'link': ('wLinkMode', 1), 'mode': ('wBattleMode', 0)}[case]
        def after():
            rig.put(label, value)
    call(rig, mons, hooked=case != "hook", after_arm=after)
    with pytest.raises(AssertionError, match="zero-write refusal"):
        assert rig.writes() == [], "zero-write refusal"


@pytest.mark.parametrize("case", ["order-first", "reset-order", "idempotence", "readback"],
                         ids=["notification-first", "reset-native-order", "repeat-zero-write", "skip-readback"])
def test_semantic_mutants_break_the_real_oracles(case):
    source = SOURCE[WRITER]
    if case == "order-first":
        source = source.replace("gate:write_batch(spans) --", "local last = table.remove(spans); table.insert(spans, 1, last)\n                gate:write_batch(spans) --")
    elif case == "reset-order":
        source = source.replace("if order == 0 then", "if true then")
    elif case == "idempotence":
        source = source.replace("if zero then", "if false then").replace("if not zero then", "if true then")
    else:
        source = source.replace('assert(after[i] == 0, "active faint HP/status read-back mismatch")', '')
        # Deliberately corrupt the requested battle HP byte; only readback can reject it.
        source = source.replace('addr=at.wBattleMonHP, bytes={0, 0}', 'addr=at.wBattleMonHP, bytes={1, 0}')
    assert source != SOURCE[WRITER]
    order = 2 if case == "reset-order" else 0
    rig, mons = setup(order=order, overrides={WRITER: source})
    if case == "idempotence":
        for a in addresses()[:6]:
            rig.mem[a] = 0
        rig.put("wPlayerSubStatus2", 4)  # native already processed, not missing notification
    before = dict(rig.mem.items())
    ok, _ = call(rig, mons)
    if case == "idempotence":
        with pytest.raises(AssertionError, match="idempotent"):
            assert rig.writes() == [], "idempotent"
    elif case == "readback":
        with pytest.raises(AssertionError, match="bad readback"):
            assert not ok, "bad readback"
    else:
        with pytest.raises(AssertionError):
            assert_landed(rig, before, order)


@pytest.mark.parametrize("widen", [False, True], ids=["narrow-window", "widened-control"])
def test_extra_move_span_is_preflighted_before_any_faint_byte(widen):
    source = SOURCE[WRITER].replace("gate:write_batch(spans) --", """
                spans[#spans + 1] = {domain='System Bus', addr=at.wBattleMonMoves, bytes={99}}
                gate:write_batch(spans) --""")
    if widen:
        source = source.replace("and in_faint_window(addr, n)", "and true")
    rig, mons = setup(overrides={WRITER: source})
    ok, why = call(rig, mons)
    if not widen:
        assert not ok and "interval outside domain bounds" in why, why
        assert "PARTIAL" not in why and rig.writes() == []
    else:
        assert ok, why
        with pytest.raises(AssertionError, match="zero-write refusal"):
            assert rig.writes() == [], "zero-write refusal"
