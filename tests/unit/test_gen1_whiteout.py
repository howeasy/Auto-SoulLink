"""P5 whiteout: the faint engine signal decides it, the shared engine settles it, the runtime records it once."""
import copy
import secrets

import pytest

from server import gen1_semantic_events as ev, gen1_whiteout as wo
from server.gen1_engine_signals import DATA
from server.gen1_faint_runtime import COMPONENT as FAINT, record_death_obligation
from server.gen1_hud_feedback import classify_death
from server.gen1_initial_observation import COMPONENT as INITIAL
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_staged_state import StagedGen1State
from server.protocol_journal import JournalError
from server.state import LinkEntry, LinkStatus, MonInfo
from tests.unit.test_gen1_engine_signal_runtime import deliver
from tests.unit.test_gen1_engine_signals import signal
from tests.unit.test_gen1_faint_runtime import paired, signal_batch
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_semantic_events import KEY_A, KEY_B, cmds, find, linked_state
from tests.unit.test_gen1_sessions import contract


def faint(variant, hps, *, kind="battle_faint", fainted=0, stale=None):
    """A faint signal over a party whose slot HPs are hps. The fainting slot may still show stale
    HP in party_hex: the battle site fires before the copy-down, and battle_hp is the truth."""
    codec = PartyCodec(variant)
    blobs = []
    for slot, hp in enumerate(hps):
        raw = bytearray(make_blob(codec, dv=0x1000 + slot))
        raw[1:3] = (stale if slot == fainted and stale is not None else hp).to_bytes(2, "big")
        if kind == "poison_faint" and slot == fainted:
            raw[4] = 8
        blobs.append(bytes(raw))
    value = signal(variant, kind)
    value["point"]["party_hex"] = party_point(variant, blobs)["fields"]["party"]
    value["point"]["active_slot" if kind == "battle_faint" else "which"] = fainted
    return value


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_second_faint_of_a_party_of_two_is_a_whiteout(variant):
    value = faint(variant, [0, 0], fainted=1, stale=17)
    assert wo.whiteout_from_faint(None, None, value, area_id="route_1") == {"event": "whiteout", "area_id": "route_1"}


def test_one_living_member_is_not_a_whiteout():
    assert wo.whiteout_from_faint(None, None, faint("red", [0, 9], fainted=0), area_id="x") is None
    assert wo.whiteout_from_faint(None, None, faint("red", [3, 0], fainted=1, stale=0), area_id="x") is None


def test_poison_faint_uses_which_and_an_empty_party_never_whites_out():
    assert wo.whiteout_from_faint(None, None, faint("yellow", [0, 0], kind="poison_faint", fainted=1), area_id="x")
    value = faint("red", [0])
    value["point"]["party_hex"] = "00FF" + "00" * 402
    assert wo.whiteout_from_faint(None, None, value, area_id="x") is None


def test_area_comes_from_the_adapter_map():
    assert wo.area_for_map(DATA["titles"]["red"]["starter_map"]) == "oaks_lab" and wo.area_for_map(255) is None


def test_engine_outcome_matches_the_shared_whiteout_standard(tmp_path):
    state = linked_state(tmp_path)
    event = wo.whiteout_from_faint(None, None, faint("red", [0, 0], fainted=1), area_id="route_1")
    own = state.handle_event("a", event)
    assert state.find_link("a", KEY_A).status == LinkStatus.DEAD
    assert find(state, "b", "force_faint", KEY_B), cmds(state, "b")
    assert state.run_over is True and any(c.get("cmd") == "game_over" for c in own), own


def test_multi_link_whiteout_reports_rebuild_held_without_claiming_party_restoration(tmp_path):
    state = linked_state(tmp_path)
    first = state.links[0]
    first.status = LinkStatus.DEAD  # the source faint settles before whiteout
    state.party_keys = {"a": set(), "b": set()}
    for index in (1, 2):
        entry = LinkEntry(area_id=f"route_{index + 1}",
                          a=MonInfo(key=f"A:BOX:{index}", species=0x4C, nickname=f"A{index}"),
                          b=MonInfo(key=f"B:BOX:{index}", species=0x07, nickname=f"B{index}"),
                          status=LinkStatus.ALIVE)
        state.links.append(entry)
        state._index_entry(entry)
    staged = StagedGen1State.from_live(state, {"retired_pairs": []})
    immediate = staged.handle_event("a", {"event": "whiteout", "area_id": "route_1"})
    captured = staged.take_commands("a", immediate)
    assert staged.run_over is False
    assert [c["cmd"] for c in captured["a"] if c["cmd"] in ("party_mon", "rebuild_start")] == [
        "party_mon", "party_mon", "rebuild_start"]
    assert sum(c["cmd"] == "party_mon" for c in captured["b"]) == 2
    feedback = classify_death(captured, member_labels={"a": "WHITEOUT", "b": "WHITEOUT"},
                              whiteout=True, now=lambda: 100)
    assert [c["text"] for c in feedback["a"]] == ["!! WHITEOUT!", "REBUILD PENDING - PC available"]
    assert [c["text"] for c in feedback["b"]] == ["!! WHITEOUT!", "REBUILD PENDING"]
    assert not any(c["cmd"] == "hud_state" for commands in feedback.values() for c in commands)
    assert not any(c["cmd"] == "party_mon" for commands in feedback.values() for c in commands)


def two_mon_batch(runtime, player, second_hp):
    """The paired starter faints in slot 0 while a second, unlinked member sits in slot 1."""
    value = signal_batch(runtime, player)
    point = value["signals"][1]["point"]
    raw = bytearray.fromhex(point["party_hex"])
    variant = runtime.contract["players"][player]["variant"]
    extra = bytearray(make_blob(PartyCodec(variant), otid=0x4242, dv=0x2222))
    extra[1:3] = second_hp.to_bytes(2, "big")
    raw[0] = 2
    raw[2] = extra[0]
    raw[3] = 255
    raw[52:96] = extra[:44]
    raw[283:294] = extra[44:55]
    raw[349:360] = extra[55:]
    point["party_hex"] = raw.hex().upper()
    return value


@pytest.mark.parametrize("variants", [("red", "blue"), ("yellow", "yellow")])
def test_whiteout_settles_once_behind_its_faint_and_survives_restore(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        owners = paired(runtime)
        value = signal_batch(runtime, "a")  # the only party member faints: AnyPartyAlive is false
        op = secrets.token_hex(16)
        deliver(runtime, "a", owners["a"], value, op)
        before = runtime.journal.snapshot()
        deliver(runtime, "a", owners["a"], value, op)
        assert runtime.journal.snapshot() == before
        document = runtime.state().document()
        deaths = document["components"][FAINT]["deaths"]
        whiteouts = document["components"][wo.COMPONENT]
        assert set(whiteouts) == set(deaths) and len(deaths) == 1
        record = next(iter(whiteouts.values()))
        assert record["player"] == "a" and record["area_id"] == "oaks_lab" and record["index"] == 1
        assert [c["cmd"] for c in runtime.journal.pending("b")] == ["force_faint", "hud_notice", "hud_notice"]
        assert [c["text"] for c in runtime.journal.pending("a") if c["cmd"] == "hud_notice"][-1] == "!! WHITEOUT!"
        assert runtime.state().rules.party_keys["a"] == set() and runtime.state().rules.links[0].status == LinkStatus.DEAD
        wo.verify_state(runtime.state())
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        assert reopened.state().document()["components"][wo.COMPONENT] == whiteouts
        wo.verify_state(reopened.state())
    finally:
        reopened.close()


@pytest.mark.parametrize("second_hp", [9, 0])
def test_a_second_member_decides_between_a_plain_faint_and_a_whiteout(tmp_path, second_hp):
    runtime = create_runtime(tmp_path, contract("red", "red"))
    try:
        owners = paired(runtime)
        deliver(runtime, "a", owners["a"], two_mon_batch(runtime, "a", second_hp))
        document = runtime.state().document()
        assert len(document["components"][FAINT]["deaths"]) == 1
        assert (wo.COMPONENT in document["components"]) == (second_hp == 0)
        assert [c["cmd"] for c in runtime.journal.pending("b")] == (
            ["force_faint", "hud_notice", "hud_notice"] if second_hp == 0 else ["force_faint", "hud_notice"])
    finally:
        runtime.close()


def test_faint_before_ball_activation_records_no_whiteout(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owners = paired(runtime)
        value = signal_batch(runtime, "a")
        value["signals"].reverse()
        for row in value["signals"]:
            row["frame"] = 120
        deliver(runtime, "a", owners["a"], value)
        assert wo.COMPONENT not in runtime.state().document()["components"]
        assert runtime.state().rules.links[0].status == LinkStatus.ALIVE
    finally:
        runtime.close()


@pytest.mark.parametrize("fault,message", [("area", "whiteout record differs"), ("death", "whiteout|recovery holds"),
                                           ("keys", "incomplete whiteout record")])
def test_tampered_whiteout_records_are_refused_by_the_state_aggregate(tmp_path, fault, message):
    """Gen1RuntimeState runs gen1_whiteout.verify_state next to the faint verifier, so a tampered record
    never restores (the area and shape faults are caught by nothing else)."""
    runtime = create_runtime(tmp_path, contract("blue", "blue"))
    try:
        owners = paired(runtime)
        deliver(runtime, "a", owners["a"], signal_batch(runtime, "a"))
        document = copy.deepcopy(runtime.state().document())
        Gen1RuntimeState.restore(document, data_dir=tmp_path)
        whiteout_id, record = next(iter(document["components"][wo.COMPONENT].items()))
        if fault == "area":
            record["area_id"] = "route_1"
        elif fault == "death":
            document["components"][FAINT]["deaths"].pop(whiteout_id)
        else:
            record["extra"] = True
        with pytest.raises(JournalError, match=message):
            Gen1RuntimeState.restore(document, data_dir=tmp_path)
    finally:
        runtime.close()


class _FakeBlockers:
    """Stand-in for stage.barrier: the recovery-hold document settle_whiteout reads and writes."""

    def __init__(self):
        self._blockers = {}

    def document(self):
        return {"blockers": dict(self._blockers)}

    def set_blockers(self, blockers):
        self._blockers = dict(blockers)


class _FakeIdentities:
    """Stand-in for stage.identities: resolve() is identity (member id == physical key), so
    _link_identity's cross-player match only needs document()["links"] to carry the pairing.
    The real IdentityRegistry is exercised elsewhere (gen1_run_resume, starter settlement);
    this double isolates settle_whiteout/record_death_obligation from that machinery.
    """

    def __init__(self, links):
        self._links = links  # {link_id: {"members": [key_a, key_b]}}

    def resolve(self, context, key):
        return key

    def document(self):
        return {"links": self._links}


def _real_initials(runtime):
    """A real, fully-enrolled initials component (from a paired runtime) -- context() needs its
    exact shape (save_identity, gen1_metadata, binding), which no small hand-built dict reproduces
    faithfully; reuse it rather than fake it.
    """
    return runtime.state().document()["components"][INITIAL]


def _collateral_fixture(tmp_path):
    """L1 (real starter identity) faints in a real, decodable 2-slot battle_faint batch; L2 is a
    second ALIVE linked pair (hand-built LinkEntry + a minimal identities double -- _link_identity
    only needs resolve()/document()["links"], and the real IdentityRegistry's own correctness is
    exercised elsewhere, e.g. gen1_starter_settlement/gen1_acquisition_runtime) that reads 0 HP in
    the SAME party capture without ever firing its own battle_faint/poison_faint signal (a missed
    or debounced faint, or simply never sampled mid-battle -- see docs/gen1_reference/reviews/
    C1-reachability-successor.md for a source-grounded natural route to this exact shape).

    Returns (fake_stage, document, component, entry, index, signal, trigger_key, key_a2, key_b2).
    entry/index/signal are REAL: two_mon_batch's own battle_faint signal, decodable by
    validate_batch/verified_source -- so verify_state (not just the happy-path settle_whiteout
    call) is a real check here, not bypassed.
    """
    runtime = create_runtime(tmp_path, contract("red", "red"))
    paired(runtime)  # L1: real identity + real initials, enrolled by the runtime itself
    stage = runtime.state()
    initials = _real_initials(runtime)
    rules = stage.rules
    link1 = rules.links[0]
    trigger_key = link1.a.key

    key_a2, key_b2 = "AAAA:0001:07", "BBBB:0002:6A"
    l2 = LinkEntry(area_id="route_2", a=MonInfo(key=key_a2, level=5, species=0x07),
                    b=MonInfo(key=key_b2, level=7, species=0x6A), status=LinkStatus.ALIVE)
    rules.links.append(l2)
    rules._index_entry(l2)
    rules.party_keys["a"].add(key_a2)
    rules.party_keys["b"].add(key_b2)
    rules.pokeballs_obtained["a"] = rules.pokeballs_obtained["b"] = True  # nuzlocke gate active

    batch = two_mon_batch(runtime, "a", second_hp=0)  # signals[0]=bag (activation), [1]=battle_faint
    entry = {"operation_id": secrets.token_hex(16), "payload": batch}
    index = 1
    signal = batch["signals"][index]

    # L1's own faint settles first, exactly like gen1_faint_runtime.settle()'s per-signal loop
    # (handle_event, then take_commands to drain the peer force_faint it queued).
    immediate = rules.handle_event("a", ev.faint_event(key=trigger_key, level=link1.a.level))
    assert link1.status == LinkStatus.DEAD
    assert l2.status == LinkStatus.ALIVE  # still alive and still in a's party: the collateral case
    drained = rules.take_commands("a", immediate)
    trigger_command = next(c for c in drained["b"] if c.get("cmd") == "force_faint")

    identities = _FakeIdentities({
        "1" * 32: {"members": [link1.a.key, link1.b.key]},
        "2" * 32: {"members": [key_a2, key_b2]},
    })
    document = {"components": {
        INITIAL: initials,
        FAINT: {"activations": {"a": {"engine_record": entry, "index": 0}}, "deaths": {}},
    }}
    component = document["components"][FAINT]

    class _Stage:
        def document(self):
            return document

    fake = _Stage()
    fake.rules = rules
    fake.identities = identities
    fake.barrier = _FakeBlockers()

    trigger_death_id = record_death_obligation(
        fake, document, component, {"a": [], "b": []}, player="a", partner="b", entry=entry,
        index=index, key=trigger_key, link=link1, command=trigger_command, at=link1.killed_at,
    )
    return runtime, fake, document, component, entry, index, signal, trigger_key, trigger_death_id, key_a2, key_b2


def test_two_alive_links_whiteout_produces_collateral_force_faint(tmp_path):
    """CLAUDE.md 'Whiteout': every partner of a remaining linked party mon gets force-fainted --
    even for a second linked pair that reads 0 HP in the SAME party capture without ever firing
    its own battle_faint/poison_faint signal. Falsifies C1-CLAIM: settle_whiteout must no longer
    discard this as an error -- and, per the round-2 review, verify_state must actually accept the
    resulting record on restore, not just the happy-path settle_whiteout return value.
    """
    from server.gen1_faint_runtime import REASON, verify_state as faint_verify_state

    runtime, fake, document, component, entry, index, signal, trigger_key, trigger_death_id, key_a2, key_b2 = (
        _collateral_fixture(tmp_path)
    )
    try:
        rules = fake.rules
        l2 = next(link for link in rules.links if link.a.key == key_a2)
        assert len(component["deaths"]) == 1

        feedback = wo.settle_whiteout(fake, document, "a", entry, index, signal,
                                      trigger_death_id=trigger_death_id, trigger_key=trigger_key)

        assert l2.status == LinkStatus.DEAD  # the shared engine's own collateral force-faint still ran
        assert len(component["deaths"]) == 2  # trigger + collateral, distinct death_ids
        collateral_id = next(d for d in component["deaths"] if d != trigger_death_id)
        collateral = component["deaths"][collateral_id]
        assert collateral["collateral_of"] == trigger_death_id
        assert collateral["key"] == key_a2 and collateral["peer_key"] == key_b2 and collateral["peer"] == "b"
        assert collateral["command"] == "force_faint"
        # B actually receives the collateral force_faint command, with its own death_id.
        b_force_faints = [c for c in feedback["b"] if c.get("cmd") == "force_faint"]
        assert len(b_force_faints) == 1
        assert b_force_faints[0]["key"] == key_b2 and b_force_faints[0]["death_id"] == collateral_id
        blockers = fake.barrier.document()["blockers"]
        assert blockers.get(trigger_death_id) == REASON
        assert blockers.get(collateral_id) == REASON

        # The round-2 finding: verify_state must accept this on restore, not just settle_whiteout's
        # happy-path return. Both battle_faint and poison_faint decode to kind=="faint" (see
        # gen1_engine_signals.py) -- the old collateral branch demanded the raw kind names from the
        # DECODED row and could never pass; this must actually succeed now.
        faint_verify_state(fake)
        wo.verify_state(fake)
    finally:
        runtime.close()


def test_whiteout_still_refuses_a_genuine_duplicate_of_the_triggering_mon(tmp_path):
    """If _handle_whiteout ever re-found the SAME mon its own faint should already have killed
    (a call-ordering regression), settle_whiteout must still refuse -- collateral handling must
    never paper over a genuine duplicate death for the trigger's own link."""
    state = linked_state(tmp_path)
    staged = StagedGen1State.from_live(state, {"retired_pairs": []})

    class _Stage:
        pass

    fake = _Stage()
    fake.rules = staged
    fake.identities = _FakeIdentities({})  # never reached: the duplicate check raises first
    fake.barrier = _FakeBlockers()
    document = {"components": {FAINT: {"activations": {}, "deaths": {}}}}

    # link never settled its own faint -- still ALIVE when the whiteout signal arrives.
    value = faint("red", [0, 0], fainted=1, stale=17)
    with pytest.raises(JournalError, match="its faint settlement left alive"):
        wo.settle_whiteout(fake, document, "a", {"operation_id": "op-dup"}, 0, value,
                            trigger_death_id="dummy-trigger", trigger_key=KEY_A)


@pytest.mark.parametrize("fault,message", [
    ("non_whiteout_trigger", "not anchored to its triggering whiteout"),
    ("unrelated_pair", "differs from committed rules"),
    ("wrong_peer_key", "does not bind to its own actual link"),
    ("reused_trigger_key", "not anchored to its triggering whiteout"),
    ("swapped_identity", "differs from its resolved logical identity"),
])
def test_collateral_death_binding_is_refused_when_tampered(tmp_path, fault, message):
    """Round-2 finding #3: a collateral death record must genuinely bind to its own actual link
    and to a real triggering whiteout -- not just carry plausible-looking fields. Each corruption
    below is refused by verify_state."""
    from server.gen1_faint_runtime import verify_state as faint_verify_state

    runtime, fake, document, component, entry, index, signal, trigger_key, trigger_death_id, key_a2, key_b2 = (
        _collateral_fixture(tmp_path)
    )
    try:
        rules = fake.rules
        wo.settle_whiteout(fake, document, "a", entry, index, signal,
                          trigger_death_id=trigger_death_id, trigger_key=trigger_key)
        collateral_id = next(d for d in component["deaths"] if d != trigger_death_id)
        collateral = component["deaths"][collateral_id]

        if fault == "non_whiteout_trigger":
            document["components"][wo.COMPONENT].pop(trigger_death_id)
        elif fault == "unrelated_pair":
            # A third, untouched ALIVE pair the whiteout never retired (still boxed/unaffected):
            # a self-consistent record (identifier included) claiming IT is the collateral death.
            from server.gen1_faint_runtime import identifier as death_identifier

            key_a3, key_b3 = "CCCC:0003:01", "DDDD:0004:02"
            l3 = LinkEntry(area_id="route_3", a=MonInfo(key=key_a3, level=5, species=0x01),
                            b=MonInfo(key=key_b3, level=7, species=0x02), status=LinkStatus.ALIVE)
            rules.links.append(l3)
            rules._index_entry(l3)
            fake.identities._links["3" * 32] = {"members": [key_a3, key_b3]}
            collateral["key"], collateral["peer_key"] = key_a3, key_b3
            collateral["link_id"], collateral["members"] = "3" * 32, [key_a3, key_b3]
            new_id = death_identifier(collateral["player"], collateral["engine_record"]["operation_id"],
                                       collateral["index"], discriminant=key_a3)
            component["deaths"][new_id] = component["deaths"].pop(collateral_id)
            collateral_id = new_id
        elif fault == "wrong_peer_key":
            collateral["peer_key"] = rules.find_link("a", trigger_key).b.key  # the trigger's own peer
        elif fault == "reused_trigger_key":
            collateral["key"] = trigger_key
        elif fault == "swapped_identity":
            collateral["link_id"], collateral["members"] = "1" * 32, [trigger_key, rules.find_link("a", trigger_key).b.key]

        with pytest.raises(JournalError, match=message):
            faint_verify_state(fake)
    finally:
        runtime.close()


def test_collateral_death_defers_behind_a_busy_storage_job(tmp_path):
    """Round-2 finding #5: exactly like the primary path (gen1_faint_runtime.record_death_obligation
    checks _storage_jobs before appending the physical command), a collateral death whose peer pair
    has an unfinished storage job takes the pending_issue path instead of issuing immediately."""
    from server.gen1_faint_runtime import verify_state as faint_verify_state
    from server.gen1_storage_runtime import COMPONENT as STORAGE

    runtime, fake, document, component, entry, index, signal, trigger_key, trigger_death_id, key_a2, key_b2 = (
        _collateral_fixture(tmp_path)
    )
    try:
        document["components"][STORAGE] = {
            "jobs": {"a" * 32: {"complete": False, "keys": {"a": key_a2, "b": key_b2}}}
        }
        feedback = wo.settle_whiteout(fake, document, "a", entry, index, signal,
                                      trigger_death_id=trigger_death_id, trigger_key=trigger_key)

        collateral_id = next(d for d in component["deaths"] if d != trigger_death_id)
        collateral = component["deaths"][collateral_id]
        assert collateral["phase"] == "pending_issue"
        assert collateral["deferred"]["origin"] is None
        assert collateral["deferred"]["jobs"] == ["a" * 32]
        assert collateral["deferred"]["command"]["key"] == key_b2
        # Not issued yet: no force_faint for b in the returned feedback.
        assert not any(c.get("cmd") == "force_faint" for c in feedback["b"])

        faint_verify_state(fake)
    finally:
        runtime.close()
