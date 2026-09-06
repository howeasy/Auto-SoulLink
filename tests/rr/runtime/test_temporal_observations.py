import pytest

from tests.rr.runtime.rr_harness import RRHarness


def keys(h):
    return [event["key"] for event in h.events("faint")]


@pytest.mark.parametrize("order", ["ring_first", "counter_first", "together"])
def test_late_duplicate_counter_and_ring_evidence_cannot_kill_next_mon(rr_repo, order):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battler(0, 111, 0)
    h.step(3)
    assert keys(h) == []  # No authoritative evidence has arrived yet.
    h.set_mon(0, 111, 0)
    h.set_battler(1, 333, 50)
    if order in ("ring_first", "together"):
        h.native_event(h.MB.EV_PLAYER_FAINT, 1)
        h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    if order in ("counter_first", "together"):
        h.set_faint_counter(1)
    h.step()
    if order == "ring_first":
        h.set_faint_counter(1)
    if order == "counter_first":
        h.native_event(h.MB.EV_PLAYER_FAINT, 1)
        h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.set_battler(1, 333, 0)
    h.step()
    h.set_battler(1, 333, 1)
    h.step()
    assert keys(h) == [h.key(111)]
    assert not h.events("whiteout")
    # Fresh counter/ring ordinal2 still confirms B immediately; dedupe must not
    # consume future evidence or disable legitimate subsequent death detection.
    h.set_faint_counter(2)
    h.native_event(h.MB.EV_PLAYER_FAINT, 2)
    h.set_battler(1, 333, 0)
    h.step()
    assert keys(h) == [h.key(111), h.key(333)]
    assert len(h.events("whiteout")) == 1


def test_prior_battle_native_entries_do_not_credit_a_new_battle(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battler(0, 111, 0)
    h.set_faint_counter(1)
    h.step()
    h.set_mon(0, 111, 0)
    h.set_battle(False, outcome=1)
    h.step()
    h.set_faint_counter(0)
    h.set_battler(1, 333, 50)
    h.set_battle(True)
    h.step()
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.native_event(h.MB.EV_OUTCOME, 2)
    h.set_battler(1, 333, 0)
    h.step()
    h.set_battler(1, 333, 1)
    h.step()
    assert keys(h) == [h.key(111)]
    assert not h.events("whiteout")
    h.set_faint_counter(1)
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.set_battler(1, 333, 0)
    h.step()
    assert keys(h) == [h.key(111), h.key(333)]
    assert len(h.events("whiteout")) == 1


@pytest.mark.parametrize("end_on_damage_frame", [False, True])
def test_doubles_final_ko_survives_end_cleanup_and_duplicate_loss(rr_repo, end_on_damage_frame):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.set_battler(0, 111, battler=0)
    h.set_battler(1, 333, battler=2)
    h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4)
    h.set_battle(True, flags=1)
    h.step()
    h.set_battler(0, 111, 0, battler=0)
    h.set_battler(1, 333, 0, battler=2)
    h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4)
    h.set_faint_counter(2)
    if end_on_damage_frame:
        h.set_battle(False, outcome=2, flags=1)
        h.seed_u32(0x030030F4, 0x08000001)  # Engine still owns a battle callback.
        h.native_event(h.MB.EV_OUTCOME, 2)
    else:
        h.native_event(h.MB.EV_PLAYER_FAINT, 1)
        h.native_event(h.MB.EV_PLAYER_FAINT, 2)
        h.native_event(h.MB.EV_PLAYER_FAINT, 2)
    h.step()
    assert keys(h) == [h.key(111), h.key(333)]
    assert len(h.events("whiteout")) == 1
    h.set_mon(0, 111, 0)
    h.set_mon(1, 333, 0)
    h.set_battle(False, outcome=2, flags=1)
    h.seed_u32(0x030030F4, 0x080565B5)
    h.native_event(h.MB.EV_OUTCOME, 2)
    h.native_event(h.MB.EV_OUTCOME, 2)
    h.step(6)
    assert keys(h) == [h.key(111), h.key(333)]
    assert len(h.events("whiteout")) == 1


def test_borrowed_counter_and_outcome_do_not_leak_after_restore(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    real = h.bytes(int(h.M.PARTY_BASE), 600)
    h.seed(int(h.M.REAL_PARTY_BACKUP_ADDR), real)
    h.seed_u8(0x0203F840, 1)
    h.seed_u8(0x0203F841, 1)
    h.seed_u32(0x0203F844, 111)
    h.set_mon(0, 999)
    h.set_mon(1, 1000)
    h.set_battler(0, 999)
    h.set_battle(True, flags=12)
    h.step()
    h.set_battler(0, 999, 0)
    h.set_faint_counter(1)
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.step(4)
    h.set_battle(False, outcome=2)
    h.native_event(h.MB.EV_OUTCOME, 2)
    h.step()
    h.seed(int(h.M.PARTY_BASE), real)
    h.seed_u8(0x0203F840, 0)
    h.set_battler(0, 111)
    h.step(18)
    h.set_faint_counter(0)
    h.set_battle(True)
    h.step()
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.native_event(h.MB.EV_OUTCOME, 2)
    h.set_battler(0, 111, 0)
    h.step()
    h.set_battler(0, 111, 1)
    h.step()
    assert not h.events("faint") and not h.events("whiteout") and not h.events("capture")
    h.set_faint_counter(1)
    h.set_battler(0, 111, 0)
    h.step()
    assert keys(h) == [h.key(111)]


def test_chained_results_keep_origin_species_and_precede_later_same_area_capture(rr_repo):
    h = RRHarness(rr_repo)
    h.step()
    h.set_battle(True)
    h.step()
    foe = int(h.M.BATTLE_MONS_ADDR + h.M.BATTLE_MON_SIZE)
    h.seed_u16(foe, 16)
    h.seed_u8(foe + 0x2A, 5)
    h.set_battle(False, outcome=4)
    h.step()
    h.seed_u16(foe, 19)
    h.set_battle(True)
    h.step()
    h.set_mon(1, 333)
    h.seed_u8(h.M.PARTY_COUNT_ADDR, 2)
    h.step()
    events = [e for e in h.events() if e["event"] in ("no_catch", "capture")]
    assert [(e["event"], e["area_id"]) for e in events] == [
        ("no_catch", "route_1"),
        ("capture", "route_1"),
    ]
    assert events[0]["species_id"] == 16 and events[0]["level"] == 5
    h.set_battle(False, outcome=7)
    h.step(95)
    assert len(h.events("no_catch")) == 1


def test_caught_result_retains_immutable_origin_until_capture_is_observed(rr_repo):
    h = RRHarness(rr_repo)
    module = h.lua.eval('require("rr.observations")')
    if isinstance(module, tuple):
        module = module[0]
    observer = module.new(h.lua.table_from({"result_grace": 3}))
    origin = h.lua.table_from({"area_id": "route_1", "wild": True})
    observer.begin_battle(origin, h.lua.table(), 0, 0, False)
    occupied = h.lua.table_from({0: True, 1: False})
    observer.set_box_origin(0, occupied)
    observer.end_battle(7, h.lua.table_from({"species_id": 16, "level": 5}), 1)
    origin.area_id = "route_2"
    occupied[0] = False
    observer.begin_battle(
        h.lua.table_from({"area_id": "route_2", "wild": True}), h.lua.table(), 0, 2, False
    )
    assert len(observer.drain_results(100)) == 0
    pending = observer.pending_results()
    assert len(pending) == 1 and pending[1].origin.area_id == "route_1"
    assert pending[1].origin.box_occupied[1] is True
    pending[1].origin.area_id = "caller_mutated_copy"
    assert observer.pending_results()[1].origin.area_id == "route_1"
    observer.capture("route_1", "captured-key")
    assert len(observer.drain_results(101)) == 0
    assert len(observer.pending_results()) == 0


def test_overworld_poison_zero_is_immediate_and_egg_does_not_hide_whiteout(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.seed_u8(int(h.M.PARTY_BASE) + 100 + h.M.OFF_FLAGS, 6)
    h.step()
    h.set_mon(0, 111, 0)
    h.step()
    assert keys(h) == [h.key(111)]
    assert len(h.events("whiteout")) == 1


def test_prolonged_zero_without_authoritative_evidence_can_recover(rr_repo):
    h = RRHarness(rr_repo)
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battler(0, 111, 0)
    h.step(60)
    assert not h.events("faint") and not h.events("whiteout")
    h.set_battler(0, 111, 1)
    h.step(4)
    assert not h.events("faint") and not h.events("whiteout")


def test_external_bench_zero_without_native_increment_does_not_steal_next_ordinal(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333, 555))
    h.step()
    h.set_battler(1, 333)
    h.set_battle(True)
    h.step()
    h.command("force_faint", key=h.key(111))
    h.step()
    assert h.u16(int(h.M.PARTY_BASE) + h.M.OFF_HP) == 0
    assert not keys(h)
    h.set_faint_counter(1)
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.set_battler(1, 333, 0)
    h.step()
    assert keys(h) == [h.key(333)]
    assert not h.events("whiteout")  # Third living mon excludes a LOSS shortcut.


def test_engine_explosion_zero_consumes_native_ordinal_without_echo(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333, 555))
    h.step()
    h.set_battle(True)
    h.step()
    h.command("force_explode", key=h.key(111))
    h.step()
    h.set_battler(0, 111, 0)
    h.set_faint_counter(1)
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.step()
    assert not keys(h)
    h.set_battler(1, 333, 50)
    h.step()
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.set_battler(1, 333, 0)
    h.step(4)
    h.set_battler(1, 333, 1)
    h.step()
    assert not keys(h)
    h.set_faint_counter(2)
    h.set_battler(1, 333, 0)
    h.step()
    assert keys(h) == [h.key(333)]


def test_pending_death_survives_short_ended_battle_and_next_begin(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battler(0, 111, 0)
    h.step()
    h.set_mon(0, 111, 0)
    h.set_battle(False, outcome=1)
    h.seed_u32(0x030030F4, 0x08000001)
    h.step()  # Not yet a settled field snapshot.
    assert not keys(h)
    h.set_area(20)
    h.set_battler(1, 333)
    h.set_battle(True)
    h.step(4)
    assert not keys(h)  # New-battle counters cannot certify the old candidate.
    h.set_battle(False, outcome=1)
    h.seed_u32(0x030030F4, 0x080565B5)
    h.step()
    assert keys(h) == [h.key(111)]
    assert h.events("faint")[0]["area_id"] == "route_1"


def test_doubles_partial_counter_waits_for_protection_to_resolve(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.set_battler(0, 111, battler=0)
    h.set_battler(1, 333, battler=2)
    h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4)
    h.set_battle(True, flags=1)
    h.step()
    h.set_battler(0, 111, 0, battler=0)
    h.set_battler(1, 333, 0, battler=2)
    h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4)
    h.set_faint_counter(1)
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.step(6)
    assert not keys(h) and not h.events("whiteout")
    h.set_battler(1, 333, 1, battler=2)
    h.seed_u8(h.M.BATTLERS_COUNT_ADDR, 4)
    h.step()
    assert keys(h) == [h.key(111)]
    assert not h.events("whiteout")


def test_checkpoint_roundtrip_retains_claims_and_rejects_bad_policy(rr_repo):
    h = RRHarness(rr_repo)
    module = h.lua.eval('require("rr.observations")')
    codec = h.lua.eval('require("json_codec")')
    if isinstance(module, tuple):
        module = module[0]
    if isinstance(codec, tuple):
        codec = codec[0]
    observer = module.new()
    previous = h.lua.table_from(
        {"a": h.lua.table_from({"hp": 50}), "b": h.lua.table_from({"hp": 50})}
    )
    current = h.lua.table_from(
        {"a": h.lua.table_from({"hp": 0}), "b": h.lua.table_from({"hp": 50})}
    )
    observer.begin_battle(
        h.lua.table_from({"area_id": "route_1", "wild": True}), previous, 0, 0, False
    )
    sample = h.lua.table_from(
        {
            "observable": True,
            "in_battle": True,
            "party": current,
            "counter": 1,
            "area_id": "route_1",
        }
    )
    assert len(observer.observe(sample)) == 1
    encoded = codec.encode(observer.checkpoint())
    restored = module.new()
    assert restored.restore(codec.decode(encoded)) is True
    current["b"]["hp"] = 0
    sample.native_events = h.lua.table_from([h.lua.table_from({"type": 1, "a": 1})] * 2)
    assert len(restored.observe(sample)) == 0
    current["b"]["hp"] = 1
    assert len(restored.observe(sample)) == 0
    before = codec.encode(restored.checkpoint())
    broken = codec.decode(before)
    broken.policy.death_evidence = "timer-only"
    assert restored.restore(broken)[0] is False
    assert codec.encode(restored.checkpoint()) == before
    current["b"]["hp"] = 0
    sample.counter = 2
    events = restored.observe(sample)
    assert [event.event for event in events.values()] == ["faint", "whiteout"]
    assert events[1].key == "b"


def test_same_area_capture_requires_unambiguous_battle_identity(rr_repo):
    h = RRHarness(rr_repo)
    module = h.lua.eval('require("rr.observations")')
    if isinstance(module, tuple):
        module = module[0]
    observer = module.new()
    origin = h.lua.table_from({"area_id": "route_1", "wild": True})
    observer.begin_battle(origin, h.lua.table(), 0, 0, False)
    first = observer.current_battle_id()
    observer.end_battle(7, h.lua.table(), 1)
    observer.begin_battle(origin, h.lua.table(), 0, 2, False)
    second = observer.current_battle_id()
    assert first != second
    assert observer.capture("route_1", "key-without-origin")[0] is False
    assert observer.capture("route_1", "second-key", second) is True
    observer.end_battle(7, h.lua.table(), 3)
    observer.drain_results(100)
    pending = observer.pending_results()
    assert len(pending) == 1 and pending[1].id == first


def test_checkpoint_refuses_nonboolean_death_policy_without_changing_state(rr_repo):
    h = RRHarness(rr_repo)
    module = h.lua.eval('require("rr.observations")')
    codec = h.lua.eval('require("json_codec")')
    if isinstance(module, tuple):
        module = module[0]
    if isinstance(codec, tuple):
        codec = codec[0]
    observer = module.new()
    previous = h.lua.table_from({"a": h.lua.table_from({"hp": 50})})
    current = h.lua.table_from({"a": h.lua.table_from({"hp": 0})})
    observer.begin_battle(
        h.lua.table_from({"area_id": "route_1", "wild": True}), previous, 0, 0, False
    )
    observer.observe(
        h.lua.table_from(
            {
                "observable": True,
                "in_battle": True,
                "party": current,
                "counter": 0,
                "area_id": "route_1",
            }
        )
    )
    before = codec.encode(observer.checkpoint())
    bad = codec.decode(before)
    bad.death.pending["a"].outside = "true"
    assert observer.restore(bad)[0] is False
    assert codec.encode(observer.checkpoint()) == before


def test_outgoing_faint_is_not_lost_when_battler_index_advances_first(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333, 555))
    h.step()
    h.set_battle(True)
    h.step()
    h.set_battler(0, 111, 0)
    h.seed_u16(h.M.BATTLER_PARTY_INDEXES_ADDR, 1)  # Index says B; struct still names A.
    h.set_faint_counter(1)
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.step()
    h.set_mon(0, 111, 0)
    h.set_battler(1, 333, 50)
    h.step()
    h.set_battler(1, 333, 0)
    h.step(5)
    h.set_battler(1, 333, 1)
    h.step()
    assert keys(h) == [h.key(111)]
    assert not h.events("whiteout")


@pytest.mark.parametrize("recovers", [False, True])
def test_field_script_zero_waits_for_owned_party_readback(rr_repo, recovers):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.seed_u8(0x03000F9C, 1)
    h.set_mon(0, 111, 0)
    h.step(5)
    assert not keys(h)
    if recovers:
        h.set_mon(0, 111, 50)
    h.seed_u8(0x03000F9C, 0)
    h.step()
    assert keys(h) == ([] if recovers else [h.key(111)])


@pytest.mark.parametrize("index", [0, 5])
def test_duplicate_raw_identity_is_unattributed_even_with_plausible_index(rr_repo, index):
    h = RRHarness(rr_repo, party=(111, 111), load=False)
    h.set_battler(0, 111, 0)
    h.seed_u16(h.M.BATTLER_PARTY_INDEXES_ADDR, index)
    h.set_battle(True)
    h.set_faint_counter(1)
    reader = h.lua.eval('require("rr.battle_snapshot")')
    if isinstance(reader, tuple):
        reader = reader[0]
    assert reader.read(h.M, h.lua.globals().memory, 0) == (None, "unattributed zero")
    h.load_client()
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.step(35)
    assert not h.events("hello") and not h.events("faint") and not h.events("whiteout")


def test_duplicate_identity_introduced_at_final_ko_cannot_bypass_context(rr_repo):
    h = RRHarness(rr_repo, party=(111, 333))
    h.step()
    h.set_battle(True)
    h.step()
    h.set_mon(1, 111, 0)
    h.set_mon(0, 111, 0)
    h.set_battler(0, 111, 0)
    h.set_faint_counter(2)
    h.set_battle(False, outcome=2)
    h.native_event(h.MB.EV_OUTCOME, 2)
    h.step(35)
    assert not keys(h) and not h.events("whiteout")
    assert all("party" not in event for event in h.events("tick"))


@pytest.mark.parametrize("field_callback", [False, True])
def test_counted_vacancy_at_final_ko_cannot_supply_death_proof(rr_repo, field_callback):
    h = RRHarness(rr_repo, party=(111, 333, 555))
    h.step()
    h.set_battle(True)
    h.step()
    h.seed(int(h.M.PARTY_BASE) + 100, bytes(100))
    h.set_mon(0, 111, 0)
    h.set_battler(0, 111, 0)
    h.set_faint_counter(1)
    h.set_battle(False, outcome=2)
    if not field_callback:
        h.seed_u32(0x030030F4, 0x080567DD)
    h.native_event(h.MB.EV_PLAYER_FAINT, 1)
    h.native_event(h.MB.EV_OUTCOME, 2)
    h.step(35)
    assert not keys(h) and not h.events("whiteout")
    assert not h.events("party_to_box")
    assert all("party" not in event for event in h.events("tick"))
