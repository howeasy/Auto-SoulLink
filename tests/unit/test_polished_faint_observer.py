"""Opt-in post-copy PRODUCER: real overlay, binder, FS authority and sent-tick consumer.

MODEL evidence only. The positive executes the native player copy routine on
its real SM83 bytes, then fires the actual registered 0f:44cd callback. It does
not inject a capture or allocate the FS clock from the test. Native FAINTED is
seeded evidence; animation, live callback timing and server PARTIAL recovery
remain OPEN. Mutants use the same behavioral assertions, not source pin tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.unit import test_polished_explode_path as br, test_polished_faint_client as fc
from tests.unit.polished_sm83 import SM83
from tests.unit.test_polished_write_path import SYM, overlay

ROOT = Path(__file__).resolve().parents[2]
SIGNALS = "lua/gen2/signals.lua"
CLIENT = "lua/gen2/client.lua"
ENTRY = "lua/gen2/entry.lua"
SOURCES = {p: (ROOT / p).read_text(encoding="utf-8") for p in (SIGNALS, CLIENT, ENTRY)}
SITE = "battle_faint_copyback_return"
HOOK = "SLink-gen2-polished:" + SITE
PC = SYM["ResolveFaints.no_fainted_mons"][1] + 6
PACK = json.loads((ROOT / "data/games/polished_crystal/engine_signals.json").read_text())
POINTS = ("wBattleMode", "wCurBattleMon", "wLinkMode", "wBattleMonHP", "wBattleMonStatus", "wPlayerSubStatus2")
DEFAULT_HOOKS = {"SLink-gen2-polished:capture_party": 0x652B, "SLink-gen2-polished:battle_faint": 0x44C8,
                 "SLink-gen2-checkpoint": 0x51BF, "SLink-gen2-battle-hold": 0x416A}


def mutation(path, old, new):
    source = SOURCES[path]
    assert source.count(old) == 1, old
    return {path: source.replace(old, new)}


def build(*, enabled=True, interface=True, overrides=None):
    harness = br.HARNESS_HOOKS
    if enabled:
        harness = harness.replace(fc.DEPS_OLD, fc.DEPS_OLD + " polished_faint_observer=true,")
    with patch.object(br, "HARNESS_HOOKS", harness):
        return fc.build(interface=interface, overrides=overrides)


def staged(overrides=None):
    rig, mons = build(overrides=overrides)
    br.order(rig, "force_faint", mons)
    br.at_hold(rig)
    assert fc.owner(rig).state == "awaiting" and len(rig.writes()) == 7
    rig.put("wPlayerSubStatus2", 4)
    return rig, mons


def fire(rig, *, name=HOOK, pc=PC, bank=15, bad_bytes=False):
    rig.put("hROMBank", bank)
    rig.io.register = rig.lua.eval(f"function(n) return n == 'PC' and {pc} or 0xC100 end")
    at = rig.log["hook_at"][name]
    assert at is not None, "post-copy observer hook is absent"
    offset = 15 * 0x4000 + at - 0x4000
    for i, byte in enumerate(overlay()[1][offset:offset + 3]):
        rig.mem[at + i] = byte
    if bad_bytes:
        rig.mem[at] = 0
    rig.log["hook_fn"][name]()


def batches(rig):
    return list(rig.client.signals.drain(rig.client.signals).values())


def consume(rig, batch):
    for event in batch.events.values():
        event.batch_generation = batch.generation
        rig.client.on_event(rig.client, event)


def native_copy(rig):
    """Execute UpdateBattleMonInParty itself, not a Python reimplementation."""
    cpu = SM83(overlay()[1], bank=15, hrombank=SYM["hROMBank"][1])
    for address, value in rig.mem.items():
        if address >= 0x8000:
            cpu.poke(address, value)
    result = cpu.call_routine(SYM["UpdateBattleMonInParty"][1])
    assert result.returned and result.sp_delta == 0
    for _, address, value in result.writes:
        if address >= 0x8000:
            rig.mem[address] = value


def positive(overrides=None):
    rig, _ = staged(overrides)
    ob, fs = fc.owner(rig), fc.FS(rig)
    attempt = ob.attempts[len(ob.attempts)]
    writes = len(rig.writes())
    native_copy(rig)
    fire(rig)
    assert fs.seq > attempt.seq, "producer did not allocate the shared clock at capture"
    captured_seq = fs.seq
    assert ob.obs_seq is None and ob.state == "awaiting" and fc.ko(rig) == []
    rig.frame(1)  # actual frame-end drain; no hand-built observation
    assert ob.obs_seq == captured_seq and fs.seq == captured_seq
    assert ob.state == "awaiting" and fc.ko(rig) == []
    fc.tick(rig)
    assert fs.seq > captured_seq and ob.state == "done" and len(fc.ko(rig)) == 1
    fire(rig)
    rig.frame(1)
    fc.tick(rig)
    assert len(fc.ko(rig)) == 1 and len(rig.writes()) == writes
    assert rig.sent("faint") == []


def test_real_producer_native_copy_drain_and_later_sent_tick_complete_once():
    positive()


def test_attempt_callback_drain_and_real_sent_tick_share_one_frame_clock():
    rig, mons = build()
    rig.io.frame += 1  # the next frame, before its end callback (not a savestate discontinuity)
    frame = rig.io.frame
    br.order(rig, "force_faint", mons)
    br.at_hold(rig)
    ob, fs = fc.owner(rig), fc.FS(rig)
    attempt_seq = ob.attempts[1].seq
    rig.put("wPlayerSubStatus2", 4)
    native_copy(rig)
    fire(rig)
    capture_seq = fs.seq
    rig.client.frame_end(rig.client)
    assert ob.obs_seq == capture_seq and ob.state == "awaiting"
    rig.client.send_tick(rig.client, "tick")
    assert rig.io.frame == frame and attempt_seq < capture_seq < fs.seq
    assert ob.state == "done" and len(fc.ko(rig)) == 1 and len(rig.writes()) == 7


@pytest.mark.parametrize("path,old,new", [
    (ENTRY, 'battle_sites=deps.polished_faint_observer == true and {"battle_faint", "battle_faint_copyback_return"} or {"battle_faint"},',
     'battle_sites={"battle_faint"},'),
    (SIGNALS, 'if prepared.id == "battle_faint_copyback_return" then return faint_copyback_return(prepared,context,held) end',
     'if prepared.id == "battle_faint_copyback_return" then return nil end'),
    (CLIENT, 'local seq = FS.next_seq()\n        if seq <= a.seq', 'local seq = a.seq\n        if seq <= a.seq'),
])
def test_red_controls_missing_hook_event_or_shared_clock_break_positive(path, old, new):
    with pytest.raises(AssertionError):
        positive(mutation(path, old, new))


@pytest.mark.parametrize("enabled,interface", [(False, True), (False, False), (True, True)])
def test_opt_in_hook_census_preserves_pinned_default(enabled, interface):
    rig, _ = build(enabled=enabled, interface=interface)
    expected = DEFAULT_HOOKS | ({HOOK: PC} if enabled else {})
    assert dict(rig.log["hook_at"].items()) == expected
    status = rig.client.signals.status(rig.client.signals)
    assert list(status.registered_sites.values()) == ["capture_party", "battle_faint"] + ([SITE] if enabled else [])


def test_observer_without_settlement_authority_degrades_inert_not_legacy_success():
    rig, _ = build(interface=False)
    assert dict(rig.log["hook_at"].items()) == {k: v for k, v in DEFAULT_HOOKS.items() if "polished:" not in k}
    assert any("client-owned faint capture authority required" in line for line in rig.lines())


def wrong_bank(overrides=None):
    rig, _ = staged(overrides)
    seq = fc.FS(rig).seq
    for _ in range(6500):
        fire(rig, bank=14)
    assert fc.FS(rig).seq == seq and batches(rig) == []
    status = rig.client.signals.status(rig.client.signals)
    assert dict(status.wrong_bank_hits.items()) == {SITE: 6500}
    assert status.pending == 0 and status.failed is None


def test_wrong_bank_hits_are_counted_without_rows_stamps_or_clock_advancement():
    wrong_bank()


def test_red_control_removed_bank_filter_is_caught():
    with pytest.raises(AssertionError):
        wrong_bank(mutation(SIGNALS, "if bank ~= prepared.anchor.bank then", "if false then"))


@pytest.mark.parametrize("bad", ["pc", "bytes"])
def test_callback_pc_and_executed_bytes_fail_closed(bad):
    rig, _ = staged()
    seq = fc.FS(rig).seq
    fire(rig, pc=PC + (bad == "pc"), bad_bytes=bad == "bytes")
    assert batches(rig) == [] and fc.FS(rig).seq == seq
    assert rig.client.signals.status(rig.client.signals).failed is not None
    fc.tick(rig)
    assert fc.owner(rig).state == "awaiting" and fc.ko(rig) == []


def stub_binder(rig, overrides=None, pack=None):
    """Real binder/registry with a permissive authority to expose each producer guard."""
    source = (overrides or {}).get(SIGNALS, SOURCES[SIGNALS])
    signals = rig.lua.execute(source)
    records = rig.lua.table()
    authority = rig.lua.eval("""function(records)
        return {capture=function() return {generation=1,operation='probe'} end,
                valid=function() return true end,
                capture_faint=function(b,held) records[#records+1]=b return {seq=1} end}
    end""")(records)
    options = rig.lua.table(title="polished", qualification="DEV_OVERLAY_SHA1", profile=rig.parts.profile,
                            pack=rig.lua.table_from(pack or PACK, recursive=True), io=rig.io,
                            reads=rig.parts.reads, key_fn=rig.lua.eval(f'dofile("{ROOT.as_posix()}/lua/gen2/polished.lua").mon_key'),
                            areas=rig.parts.data.area_map, authority=authority,
                            Registry=rig.lua.eval(f'dofile("{ROOT.as_posix()}/lua/hook_registry.lua")'),
                            GB=rig.lua.eval(f'dofile("{ROOT.as_posix()}/lua/gb_hook_binding.lua")'),
                            owner="Observer-test", max_pending=64, battle_sites=rig.lua.table_from([SITE]))
    result = signals.new_polished(options)
    if isinstance(result, tuple):
        binder, why, *_ = result
    else:
        binder, why = result, None
    return binder, why, records


READ_GUARDS = [
    ("mode", "wBattleMode", 0, "(b.mode ~= 1 and b.mode ~= 2)", "false"),
    ("slot", "wCurBattleMon", 6, "not integer(b.slot,0,5)", "false"),
    ("hp", "wBattleMonHP", 1, "or b.hp ~= 0 or b.status ~= 0", "or false or b.status ~= 0"),
    ("status", "wBattleMonStatus", 8, "or b.hp ~= 0 or b.status ~= 0", "or b.hp ~= 0 or false"),
    ("link", "wLinkMode", 1, "or b.link_mode ~= 0 or not b.fainted", "or false or not b.fainted"),
    ("fainted", "wPlayerSubStatus2", 2, "or b.link_mode ~= 0 or not b.fainted", "or b.link_mode ~= 0 or false"),
]


def producer_guard(label, value, overrides=None):
    rig, _ = staged()
    binder, why, records = stub_binder(rig, overrides)
    assert binder, why
    rig.put(label, value)
    fire(rig, name="Observer-test:" + SITE)
    assert len(records) == 0 and len(binder.drain(binder)) == 0, "inconsistent native evidence reached authority"


@pytest.mark.parametrize("name,label,value,old,new", READ_GUARDS, ids=[r[0] for r in READ_GUARDS])
def test_native_predicates_and_each_removed_guard_mutant(name, label, value, old, new):
    producer_guard(label, value)
    with pytest.raises(AssertionError):
        producer_guard(label, value, mutation(SIGNALS, old, new))


def test_hp_decodes_big_endian_with_asymmetric_nonzero_control():
    bypass = mutation(SIGNALS, "or b.hp ~= 0 or b.status ~= 0", "or false or b.status ~= 0")
    def check(source):
        rig, _ = staged()
        binder, why, records = stub_binder(rig, source)
        assert binder, why
        rig.put("wBattleMonHP", 1)
        rig.put("wBattleMonHP", 2, 1)
        fire(rig, name="Observer-test:" + SITE)
        assert records[1].hp == 258
        assert len(binder.drain(binder)) == 1
    check(bypass)
    little = {SIGNALS: bypass[SIGNALS].replace("first * 256 + second", "first + second * 256")}
    with pytest.raises(AssertionError):
        check(little)


@pytest.mark.parametrize("fault", ["before", "after", "unavailable"])
def test_point_bank_validity_and_byte_availability_are_checked(fault):
    rig, _ = staged()
    seq = fc.FS(rig).seq
    if fault == "unavailable":
        original = rig.io.read_u8
        rig.io.read_u8 = lambda a, d: None if a == SYM["wBattleMonHP"][1] else original(a, d)
    else:
        original = rig.io.bank_valid
        calls = 0

        def valid(bank, address, length):
            nonlocal calls
            if address == SYM["wBattleMode"][1]:
                calls += 1
                return calls != (1 if fault == "before" else 2)
            return original(bank, address, length)

        rig.io.bank_valid = valid
    fire(rig)
    assert batches(rig) == [] and fc.FS(rig).seq == seq
    assert rig.client.signals.status(rig.client.signals).failed is None


@pytest.mark.parametrize("when", ["before", "after"])
def test_red_controls_removing_each_point_mapping_check(when):
    old = ('need(io.bank_valid(p.bank,p.addr,n) == true,"OPEN: '
           + ("unmapped observer memory " if when == "before" else "observer bank changed ") + '"..name)')
    def check(overrides=None):
        rig, _ = staged()
        binder, why, records = stub_binder(rig, overrides)
        assert binder, why
        read_happened = False
        original = rig.io.read_u8
        def reading(address, domain):
            nonlocal read_happened
            if address == SYM["wBattleMode"][1]:
                read_happened = True
            return original(address, domain)
        def mapped(bank, address, length):
            if address == SYM["wBattleMode"][1]:
                return read_happened if when == "before" else not read_happened
            return True
        rig.io.read_u8, rig.io.bank_valid = reading, mapped
        fire(rig, name="Observer-test:" + SITE)
        assert len(records) == 0 and len(binder.drain(binder)) == 0
    check()
    with pytest.raises(AssertionError):
        check(mutation(SIGNALS, old, 'need(true,"mutant mapping")'))


def test_red_control_reading_wrong_fainted_bit_accepts_unrelated_native_flag():
    producer_guard("wPlayerSubStatus2", 2)
    with pytest.raises(AssertionError):
        producer_guard("wPlayerSubStatus2", 2,
                       mutation(SIGNALS, 'point("wPlayerSubStatus2")/4', 'point("wPlayerSubStatus2")/2'))


def test_substatus1_is_not_native_player_fainted():
    rig, _ = staged()
    rig.put("wPlayerSubStatus2", 0)
    rig.put("wPlayerSubStatus1", 4)
    seq = fc.FS(rig).seq
    fire(rig)
    assert batches(rig) == [] and fc.FS(rig).seq == seq


def test_pre_copy_only_never_completes_even_with_native_flag_and_zero_tick():
    rig, _ = staged()
    # Explicitly requesting the existing pre-copy site is a probe corroborator,
    # not an enabled-production requirement and never supplies a capture.
    rig.client.on_event(rig.client, fc.event(rig, kind="observation", site_id="battle_faint",
        phase="before_party_copyback", batch_generation=rig.client.epoch,
        battle={"slot": 0, "hp": 0, "status": 0, "link_mode": 0, "fainted": True}))
    fc.tick(rig)
    assert fc.owner(rig).state == "awaiting" and fc.owner(rig).obs_seq is None and fc.ko(rig) == []


def test_capture_snapshot_is_immutable_and_sequence_is_not_allocated_at_drain():
    rig, _ = staged()
    ob, fs = fc.owner(rig), fc.FS(rig)
    fire(rig)
    seq = fs.seq
    attempt = ob.attempts[len(ob.attempts)]
    identity, visit, key = ob.identity, attempt.visit, ob.phys
    ob.identity, attempt.visit, ob.phys = "changed", 9000, "replacement"
    rig.put("wCurBattleMon", 1)
    batch = batches(rig)[0]
    event = batch.events[1]
    assert batch.generation == event.capture.epoch == rig.client.epoch
    assert event.site_id == "battle_faint" and event.source_site_id == SITE
    assert event.capture.identity == identity and event.capture.visit == visit and event.capture.key == key
    assert event.battle.slot == 0 and event.capture.seq == seq and fs.seq == seq


@pytest.mark.parametrize("when", ["before-callback", "after-callback", "after-drain"])
def test_save_identity_change_cannot_rebind_or_complete_old_attempt(when):
    rig, _ = staged()
    ob, fs = fc.owner(rig), fc.FS(rig)
    seq = fs.seq
    old = None
    if when != "before-callback":
        fire(rig)
        if when == "after-drain":
            old = batches(rig)[0]
    rig.put("wPlayerID", (rig.get("wPlayerID") + 1) % 256)
    if when == "before-callback":
        fire(rig)
        assert batches(rig) == [] and fs.seq == seq and ob.state == "stale"
    else:
        fs.identity_changed()
        if old:
            consume(rig, old)
        assert batches(rig) == [] and ob.state == "stale"
    fc.tick(rig)
    assert fc.ko(rig) == [] and ob.obs_seq is None


def test_suspension_evidence_floor_rejects_an_old_queued_capture():
    rig, _ = staged()
    ob = fc.owner(rig)
    fire(rig)
    batch = batches(rig)[0]
    fs = fc.FS(rig)
    fs.suspend()
    fs.frame()
    assert not fs.suspended and fs.evidence_floor > batch.events[1].capture.seq
    consume(rig, batch)
    fc.tick(rig)
    assert ob.state == "awaiting" and ob.obs_seq is None and fc.ko(rig) == []


def capture_mutation(old, new):
    source = SOURCES[CLIENT]
    start = source.index("    function FS.capture_faint(")
    end = source.index("    -- Reserved consumer contract", start)
    method = source[start:end]
    assert old in method
    return {CLIENT: source[:start] + method.replace(old, new) + source[end:]}


CAPTURE_GUARDS = [
    ("suspended", "FS.suspended", "false"),
    ("held-epoch", "held.generation ~= self.epoch", "false"),
    ("native-mode", "(b.mode ~= 1 and b.mode ~= 2)", "false"),
    ("native-hp", "b.hp ~= 0", "false"),
    ("native-status", "b.status ~= 0", "false"),
    ("native-link", "b.link_mode ~= 0", "false"),
    ("native-fainted", "b.fainted ~= true", "false"),
    ("owner-generation", "ob.gen == FS.gen", "true"),
    ("owner-state", 'ob.state == "awaiting"', "true"),
    ("plain-only", 'a.kind == "plain"', "true"),
    ("attempt-epoch", "a.epoch == self.epoch", "true"),
    ("attempt-visit", "a.visit == FS.visit", "true"),
    ("attempt-slot", "a.slot == b.slot", "true"),
    ("unique-owner", "if candidate then return nil end", "if false then return nil end"),
    ("attempt-identity", "ob.identity ~= a.identity", "false"),
    ("physical-key", "mon_key(mon) ~= ob.phys", "false"),
    ("party-hp", "mon.hp ~= 0", "false"),
    ("party-status", "mon.status ~= 0", "false"),
]


def capture_guard(case, overrides=None):
    rig, _ = staged(overrides)
    fs, ob = fc.FS(rig), fc.owner(rig)
    a = ob.attempts[len(ob.attempts)]
    held = {"generation": rig.client.epoch}
    b = {"mode": 1, "slot": 0, "hp": 0, "status": 0, "link_mode": 0, "fainted": True}
    if case == "suspended":
        fs.suspended = True
    elif case == "held-epoch":
        held["generation"] -= 1
    elif case.startswith("native-"):
        field = {"native-mode": "mode", "native-hp": "hp", "native-status": "status",
                 "native-link": "link_mode", "native-fainted": "fainted"}[case]
        b[field] = False if field == "fainted" else (0 if field == "mode" else 1)
    elif case == "owner-generation":
        ob.gen += 1
    elif case == "owner-state":
        ob.state = "partial"
    elif case == "plain-only":
        a.kind = "explode"
    elif case == "attempt-epoch":
        a.epoch -= 1
    elif case == "attempt-visit":
        a.visit += 1
    elif case == "attempt-slot":
        b["slot"] = 1
    elif case == "unique-owner":
        fs.owed[2] = ob
    elif case == "attempt-identity":
        a.identity = "another save"
    elif case == "physical-key":
        ob.phys = "replaced"
    elif case == "party-hp":
        rig.mem[SYM["wPartyMon1HP"][1] + 1] = 1
    elif case == "party-status":
        rig.mem[SYM["wPartyMon1Status"][1]] = 8
    seq = fs.seq
    capture = fs.capture_faint(rig.lua.table_from(b), rig.lua.table_from(held))
    assert capture is None and fs.seq == seq, "invalid attempt/target binding allocated a witness"


@pytest.mark.parametrize("case,old,new", CAPTURE_GUARDS, ids=[r[0] for r in CAPTURE_GUARDS])
def test_private_client_capture_guards_and_removed_guard_mutants(case, old, new):
    capture_guard(case)
    # The second revalidation repeats epoch/visit/state checks. Remove the
    # same invariant at both checkpoints to test its effect, not redundancy.
    mutant = capture_mutation(old, new)
    if case in ("attempt-epoch", "attempt-visit", "owner-generation", "owner-state"):
        opposite = {"attempt-epoch": "a.epoch ~= self.epoch", "attempt-visit": "a.visit ~= FS.visit",
                    "owner-generation": "ob.gen ~= FS.gen", "owner-state": 'ob.state ~= "awaiting"'}[case]
        # Limit the negative-form replacement to the capture method as well.
        start = mutant[CLIENT].index("    function FS.capture_faint(")
        end = mutant[CLIENT].index("    -- Reserved consumer contract", start)
        mutant[CLIENT] = mutant[CLIENT][:start] + mutant[CLIENT][start:end].replace(opposite, "false") + mutant[CLIENT][end:]
    if case == "suspended":
        # check_identity independently enforces suspension; remove both guards
        # for this invariant mutant rather than call a redundant defense broken.
        old_identity = "return not FS.suspended and FS.last_identity == expected"
        assert mutant[CLIENT].count(old_identity) == 1
        mutant[CLIENT] = mutant[CLIENT].replace(old_identity, "return FS.last_identity == expected")
    with pytest.raises(AssertionError):
        capture_guard(case, mutant)


def test_identity_is_revalidated_after_fresh_target_reads_at_capture():
    rig, _ = staged()
    ob, fs = fc.owner(rig), fc.FS(rig)
    original = rig.parts.reads.read_party
    def changing_party():
        party = original()
        rig.put("wPlayerID", (rig.get("wPlayerID") + 1) % 256)
        return party
    rig.parts.reads.read_party = changing_party
    seq = fs.seq
    fire(rig)
    assert batches(rig) == [] and fs.seq == seq and ob.state == "stale"


@pytest.mark.parametrize("case", ["no-owner", "egg", "duplicate-party", "unavailable-party", "lost-owner"])
def test_ineligible_or_ambiguous_fresh_target_has_no_capture(case):
    rig, _ = staged()
    ob, fs = fc.owner(rig), fc.FS(rig)
    if case == "no-owner":
        fs.owed = rig.lua.table()
    elif case == "egg":
        at = SYM["wPartyMon1Form"][1]
        rig.mem[at] = (rig.mem[at] or 0) | 0x40
    elif case == "duplicate-party":
        at = SYM["wPartyMons"][1]
        for i in range(48):
            rig.mem[at + 48 + i] = rig.mem[at + i]
    elif case == "unavailable-party":
        rig.parts.reads.read_party = lambda: None
    else:
        ob.state = "lost"
    seq = fs.seq
    fire(rig)
    assert batches(rig) == [] and fs.seq == seq




@pytest.mark.parametrize("point", POINTS)
def test_missing_or_corrupt_required_point_refuses_registration(point):
    rig, _ = build(enabled=False)
    for missing in (True, False):
        pack = json.loads(json.dumps(PACK))
        points = pack["titles"]["polished_crystal"]["sites"][SITE]["point_symbols"]
        if missing:
            del points[point]
        else:
            points[point]["addr"] += 1
        binder, why, _ = stub_binder(rig, pack=pack)
        assert binder is None and ("point" in why or "SUBSTATUS2" in why)


def test_generated_site_census_adjacent_calls_proof_and_overlay_points():
    sys.path.insert(0, str(ROOT / "tools"))
    import gen_polished_engine_sites as gen

    row = PACK["titles"]["polished_crystal"]["sites"][SITE]
    assert (PACK["site_count"], PACK["resolved_count"], PACK["unresolved_count"]) == (54, 42, 12)
    assert (row["bank"], row["addr"], row["rom_offset"], row["symbol_offset"], row["hex_len"]) == (15, PC, 0x3C4CD, 6, 3)
    assert row["sym_anchor"] == row["symbol"] == "ResolveFaints.no_fainted_mons"
    assert row["phase"] == "after_party_copyback" and row["instructions"] == ["call UpdateEnemyMonInParty"]
    assert row["expected_hex"] == row["find_hex"] == "CDC334"
    clean = gen.read_sym(gen.SYMPATH)
    for name in POINTS:
        assert clean[name] == SYM[name] == (row["point_symbols"][name]["bank"], row["point_symbols"][name]["addr"])
    rom = overlay()[1]
    assert rom[row["rom_offset"] - 3:row["rom_offset"] + 3] == bytes.fromhex("CDB034CDC334")
    call = PACK["titles"]["polished_crystal"]["sites"]["battle_faint_copyback_call"]
    # 28 spans before the C5 commit helper; its bank-$7E body (7e:5300..573c) adds two; the title wordmark adds ten
    # (the _TitleScreen hook operand, the two TitleScreenEntrance immediates and seven runs of the 7e:5800 band).
    assert call["addr"] + 3 == row["addr"] and len(PACK["companion_overlay_spans"]) == 40


@pytest.mark.parametrize("change", ["intervening", "player-bank", "enemy-bank", "proof"])
def test_generator_rejects_broken_adjacency_or_call_proof(change):
    sys.path.insert(0, str(ROOT / "tools"))
    import gen_polished_engine_sites as gen

    row = next(s for s in gen.SITES if s["id"] == SITE)
    rom = bytearray((gen.DEFAULT_ROMS / "polishedcrystal-3.2.3.gbc").read_bytes())
    sym = gen.read_sym(gen.SYMPATH)
    if change == "intervening":
        rom[0x3C4CD:0x3C4D1] = bytes.fromhex("00CDC334")
    elif change.endswith("bank"):
        label = "UpdateBattleMonInParty" if change == "player-bank" else "UpdateEnemyMonInParty"
        sym[label] = (1, sym[label][1])
    else:
        sym["UpdateEnemyMonInParty"] = (0, sym["UpdateEnemyMonInParty"][1] + 1)
    with pytest.raises(SystemExit):
        gen.build_site(row, bytes(rom), sym, [])
