"""P5 whiteout: the faint engine signal decides it, the shared engine settles it, the runtime records it once."""
import copy
import secrets

import pytest

from server import gen1_whiteout as wo
from server.gen1_engine_signals import DATA
from server.gen1_faint_runtime import COMPONENT as FAINT
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.protocol_journal import JournalError
from server.state import LinkStatus
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
        assert [c["cmd"] for c in runtime.journal.pending("b")] == ["force_faint"]
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
        assert [c["cmd"] for c in runtime.journal.pending("b")] == ["force_faint"]
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
