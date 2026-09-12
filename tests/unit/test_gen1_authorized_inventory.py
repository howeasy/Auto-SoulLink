"""Actual ACK/observation handlers distinguish authorized writes from raw drift."""

import copy
import secrets

import pytest

from server.gen1_authorized_inventory import build, delta, replay
from server.gen1_initial_observation import inventory
from server.gen1_initial_save_runtime import prepared
from server.gen1_inventory_observation import COMPONENT, record_key, result
from server.gen1_inventory_transition import transition
from server.gen1_memorial_runtime import expand_entry
from server.gen1_run_config import create_runtime, open_runtime
from server.protocol import canonical_json, digest
from server.protocol_journal import JournalError
from server.gen1_observation_runtime import record as record_batch
from tests.unit.observation_fixture import observe, setup, starters
from tests.unit.test_gen1_faint_runtime import ack, signal_batch
from tests.unit.test_gen1_held_faint import checkpoint
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_inventory_observation import deliver
from tests.unit.test_gen1_memorial import fixture
from tests.unit.test_gen1_memorial_runtime import completion
from tests.unit.test_gen1_sessions import contract


def first_observation(runtime, player="a", *, change_tile=False):
    document = runtime.state().document()
    initial = document["components"]["gen1-initial-observations"][player]
    after = copy.deepcopy(initial["observation"])
    after["source"] = prepared(document, player)["after"]
    after["frame"] += 1
    if change_tile:
        after["source"]["fields"]["tiles"] = "01"
    request = {
        "sequence": 1,
        "previous_operation_id": initial["operation_id"],
        "observation": after,
    }
    return request


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_first_baseline_uses_verified_save_but_preserves_raw_enrollment_and_later_drift(
    tmp_path, variant
):
    runtime = create_runtime(tmp_path, contract(variant, variant))
    try:
        setup(runtime)
        before = runtime.state().document()["components"]["gen1-initial-observations"]["a"][
            "observation"
        ]
        request = first_observation(runtime, change_tile=True)
        operation = secrets.token_hex(16)
        owner = runtime.gate.sessions["a"].owner
        deliver(runtime, "a", owner, request, operation)
        saved = runtime.journal.snapshot()
        deliver(runtime, "a", owner, request, operation)
        assert runtime.journal.snapshot() == saved
        entry = runtime.state().document()["components"][COMPONENT]["a"]
        assert entry["before"] == before and entry["before"]["source"]["save_status"] == 0
        steps, baseline = replay(before["source"], entry["write_attribution"])
        assert len(steps) == 1 and steps[0][3]["kind"] == "initial_save"
        assert baseline == prepared(runtime.state().document(), "a")["after"]
        assert baseline["fields"]["tiles"] == "00"
        assert entry["observation"]["source"]["fields"]["tiles"] == "01"
        assert (
            entry["transition"]["unattributed_segments"][-1]["before_digest"]
            != entry["transition"]["unattributed_segments"][-1]["after_digest"]
        )
        assert len(canonical_json(entry["write_attribution"])) < 20000
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert runtime.state().document()["components"][COMPONENT]["a"] == entry
    finally:
        runtime.close()


def receiver_memorial(runtime):
    """A source faint at122; B's two-member roster stays held at120 for its writes."""
    starters(runtime)
    document = runtime.state().document()
    b = copy.deepcopy(document["components"][COMPONENT]["b"]["observation"])
    variant = b["source"]["variant"]
    party = bytearray.fromhex(b["source"]["fields"]["party"])
    spare, _, _ = fixture(variant, count=2, slot=0)
    second = bytes.fromhex(spare["fields"]["party"])
    party[0] = 2
    party[2:4] = bytes((second[2], 255))
    party[52:96] = second[52:96]
    party[283:294] = second[283:294]
    party[349:360] = second[349:360]
    b["source"]["fields"]["party"] = party.hex().upper()
    # Preserve the already proved physical initial save rather than reverting
    # to the older synthetic starter helper's pre-save CartRAM/status.
    saved = prepared(document, "b")["after"]
    b["source"]["cart_hex"], b["source"]["save_status"] = saved["cart_hex"], 2
    b["frame"] = 120
    observe(runtime, "b", inventory=b)
    signal = signal_batch(runtime, "a")
    # A keeps a second member too, so its own memorial can complete later: a lone dead member
    # would need terminal retention, which this run never reaches.
    party = bytearray.fromhex(signal["signals"][-1]["point"]["party_hex"])
    party[0] = 2
    party[2:4] = bytes((second[2], 255))
    party[52:96] = second[52:96]
    party[283:294] = second[283:294]
    party[349:360] = second[349:360]
    signal["signals"][-1]["point"]["party_hex"] = party.hex().upper()
    a = copy.deepcopy(runtime.state().document()["components"][COMPONENT]["a"]["observation"])
    a["frame"] = 122
    a["source"]["fields"]["party"] = party.hex().upper()
    a["source"]["cart_hex"], a["source"]["save_status"] = prepared(document, "a")["after"]["cart_hex"], 2
    observe(runtime, "a", inventory=a, signals=signal)
    owner = runtime.gate.sessions["b"].owner
    command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
    members = inventory(b["source"], {"ot_id": "0000", "trainer_name": "SAME"})["members"]
    pre = {
        "schema": "gen1-party-readback-v1",
        "variant": variant,
        "save_id": "0000",
        "save_name": "SAME",
        "party_count": 2,
        "party": [row["blob_hex"] for row in members],
        "species_list": [bytes.fromhex(row["blob_hex"])[0] for row in members] + [255],
        "battle_flag": 0,
        "active_slot": None,
        "battle_hp": None,
    }
    post = copy.deepcopy(pre)
    post["party"][0] = post["party"][0][:2] + "0000" + post["party"][0][6:]
    ack(
        runtime,
        "b",
        owner,
        {
            "event": "command_ack",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "outcome": "ACK",
            "receipt": {"schema": "gen1-force-faint-receipt-v1", "before": pre, "after": post},
        },
    )
    command = runtime.journal.command("b", runtime.journal.pending_ids("b")[0])
    physical = copy.deepcopy(b["source"])
    raw = bytearray.fromhex(physical["fields"]["party"])
    raw[9:11] = b"\0\0"
    physical["fields"]["party"] = raw.hex().upper()
    initial = runtime.state().document()["components"]["gen1-initial-observations"]["b"]
    ack(
        runtime,
        "b",
        owner,
        {
            "event": "command_ack",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "outcome": "ACK",
            "receipt": {
                "schema": "rby-memorial-observation-v1",
                "command_id": command["command_id"],
                "command_sequence": command["command_sequence"],
                "context_generation": initial["binding"]["context_generation"],
                "final_sha1": initial["observation"]["final_sha1"],
                "host": {**b["host"], "frame": 120},
                "checkpoint": checkpoint(variant),
                "point": physical,
            },
        },
    )
    _, message = completion(runtime, "b")
    ack(runtime, "b", owner, message)
    archived = runtime.state().document()["components"]["gen1-memorial-settlement"]["entries"]["b"][
        -1
    ]
    after = copy.deepcopy(b)
    after["source"] = expand_entry(runtime.journal, archived)["payload"]["after"]
    after["frame"] = 121
    return b, after, a


def complete_memorial(runtime, player, point, frame):
    """Acknowledge the memorial observe and memorialize commands for ``player`` at its held frame."""
    owner = runtime.gate.sessions[player].owner
    initial = runtime.state().document()["components"]["gen1-initial-observations"][player]
    command = runtime.journal.command(player, runtime.journal.pending_ids(player)[0])
    ack(
        runtime,
        player,
        owner,
        {
            "event": "command_ack",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "outcome": "ACK",
            "receipt": {
                "schema": "rby-memorial-observation-v1",
                "command_id": command["command_id"],
                "command_sequence": command["command_sequence"],
                "context_generation": initial["binding"]["context_generation"],
                "final_sha1": initial["observation"]["final_sha1"],
                "host": {**point["host"], "frame": frame},
                "checkpoint": checkpoint(point["source"]["variant"]),
                "point": copy.deepcopy(point["source"]),
            },
        },
    )
    _, message = completion(runtime, player)
    ack(runtime, player, owner, message)


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_forced_faint_and_memorial_same_frame_have_ordered_attribution_not_gameplay_deposits(
    tmp_path, variant
):
    runtime = create_runtime(tmp_path, contract(variant, variant))
    try:
        before, after, source_point = receiver_memorial(runtime)
        # An unrelated byte change remains visible after the authorized image.
        after["source"]["cart_hex"] = "01" + after["source"]["cart_hex"][2:]
        # B's own obligations are clear, but A's memorial is open: the heartbeat waits (P10).
        assert runtime.journal.pending_ids("a") and not runtime.journal.pending_ids("b")
        _, _, deferred = observe(runtime, "b", inventory=after, allow_deferred=True)
        assert deferred["inventory_deferred"] is True
        complete_memorial(runtime, "a", source_point, 122)
        assert not runtime.journal.pending_ids("a")
        after["frame"] = 122
        operation, request, result = observe(runtime, "b", inventory=after)
        saved = runtime.journal.snapshot()
        assert record_batch(runtime, "b", operation, request) == result
        assert runtime.journal.snapshot() == saved
        entry = runtime.state().document()["components"][COMPONENT]["b"]
        writes = entry["transition"]["authorized_writes"]
        assert [row["kind"] for row in writes] == ["force_faint", "memorialize"]
        assert writes[0]["revision"] < writes[1]["revision"]
        assert not entry["transition"]["movements"] and not entry["transition"]["party_hp_zero"]
        assert transition(
            before["source"], after["source"], {"ot_id": "0000", "trainer_name": "SAME"}
        )["movements"]
        _, baseline = replay(before["source"], entry["write_attribution"])
        assert delta(baseline, after["source"])["cart"]["runs"][0]["offset"] == 0
    finally:
        runtime.close()
    runtime = open_runtime(tmp_path)
    try:
        assert runtime.state().document()["components"][COMPONENT]["b"] == entry
    finally:
        runtime.close()


def test_other_players_pending_command_does_not_authorize_or_block_this_inventory(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        owner = admit(runtime, "a")
        initial = observation(runtime, "a", occupied=True)
        operation = secrets.token_hex(16)
        send(runtime, "a", owner, initial, operation)
        before = runtime.journal.snapshot()
        runtime.journal.commit(
            "a",
            secrets.token_hex(16),
            {"event": "foreign-player-command-fixture"},
            expected_revision=before.revision,
            state=before.state,
            commands={"a": [], "b": [{"cmd": "force_faint", "key": "1234:9999:99"}]},
            result={"ack": "ACK"},
        )
        after = copy.deepcopy(initial)
        after["frame"] += 1
        deliver(
            runtime,
            "a",
            owner,
            {"sequence": 1, "previous_operation_id": operation, "observation": after},
        )
        assert not runtime.state().document()["components"][COMPONENT]["a"]["write_attribution"][
            "writes"
        ]
    finally:
        runtime.close()


def test_unapplied_command_arriving_mid_batch_defers_only_the_heartbeat_checkpoint(tmp_path):
    from server.gen1_held_faint import verify
    from tests.unit.test_gen1_held_faint import evidence

    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(runtime)
        signal = signal_batch(runtime, "a")
        a = copy.deepcopy(runtime.state().document()["components"][COMPONENT]["a"]["observation"])
        a["frame"] = 122
        a["source"]["fields"]["party"] = signal["signals"][-1]["point"]["party_hex"]
        observe(runtime, "a", inventory=a, signals=signal)
        pending = runtime.journal.pending_ids("b")
        assert len(pending) == 1
        b = copy.deepcopy(runtime.state().document()["components"][COMPONENT]["b"]["observation"])
        b["frame"] = 115
        _, _, result = observe(runtime, "b", inventory=b, allow_deferred=True)
        assert result["inventory_deferred"] is True and runtime.journal.pending_ids("b") == pending
        assert runtime.state().document()["components"][COMPONENT]["b"]["observation"]["frame"] == 110
        binding = runtime.gate.sessions["b"].metadata["control_binding"]
        command = runtime.journal.command("b", pending[0])
        value = evidence(runtime, command)
        value["host"]["frame"] = 115  # the momentary hold follows the batch the server settled
        assert verify("b", command, value, runtime.state().document(), binding)
        value["host"]["frame"] = 114
        with pytest.raises(JournalError, match="precedes the observation checkpoint"):
            verify("b", command, value, runtime.state().document(), binding)
    finally:
        runtime.close()


@pytest.mark.parametrize("fault", ["actor", "revision", "missing_ack", "omitted"])
def test_checked_replay_metadata_cannot_replace_command_provenance(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        deliver(runtime, "a", runtime.gate.sessions["a"].owner, first_observation(runtime))
        snap = runtime.journal.snapshot()
        document = snap.state
        entry = document["components"][COMPONENT]["a"]
        ref = entry["write_attribution"]["writes"][0]["reference"]
        if fault == "missing_ack":
            runtime.journal._db.execute(
                "DELETE FROM events WHERE player=? AND operation_id=?", ("a", ref["operation_id"])
            )
        else:
            if fault == "actor":
                ref["player"] = "b"
                entry["transition"]["authorized_writes"][0]["player"] = "b"
            elif fault == "revision":
                entry["write_attribution"]["through_revision"] -= 1
            else:
                del entry["write_attribution"]
                entry["transition"] = transition(
                    entry["before"]["source"],
                    entry["observation"]["source"],
                    {"ot_id": "0000", "trainer_name": "SAME"},
                )
            runtime.journal._db.execute(
                "UPDATE snapshot SET body=?,digest=? WHERE singleton=1",
                (canonical_json(document), digest(document)),
            )
            runtime.journal._db.execute(
                "UPDATE records SET body=?,digest=? WHERE namespace=? AND record_key=?",
                (canonical_json(entry), digest(entry), COMPONENT, record_key("a")),
            )
            runtime.journal._db.execute(
                "UPDATE events SET result=?,result_digest=? WHERE player=? AND operation_id=?",
                (canonical_json(result(entry)), digest(result(entry)), "a", entry["operation_id"]),
            )
        with pytest.raises(JournalError):
            runtime.state()
    finally:
        runtime.close()


def test_client_cannot_supply_an_authorized_baseline_or_cross_physical_context(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        request = first_observation(runtime)
        request["baseline"] = request["observation"]
        with pytest.raises(JournalError):
            deliver(runtime, "a", runtime.gate.sessions["a"].owner, request)
        document = runtime.state().document()
        before = document["components"]["gen1-initial-observations"]["a"]["observation"]
        after = first_observation(runtime)["observation"]
        after["host"]["owner_id"] = "f" * 32
        with pytest.raises(JournalError):
            build(
                runtime.journal,
                document,
                "a",
                before,
                after,
                after_revision=1,
                through_revision=runtime.journal.snapshot().revision,
            )
    finally:
        runtime.close()


def test_native_trade_refuses_new_inventory_but_does_not_invalidate_earlier_attribution(tmp_path):
    runtime = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        setup(runtime)
        document = runtime.state().document()
        initial = document["components"]["gen1-initial-observations"]["a"]
        before, after = initial["observation"], first_observation(runtime)["observation"]
        low = runtime.journal.event_snapshot("a", initial["operation_id"]).revision
        high = runtime.journal.snapshot().revision
        expected = build(
            runtime.journal, document, "a", before, after, after_revision=low, through_revision=high
        )
        document["active_trade"] = "later-native-trade-fixture"
        with pytest.raises(JournalError, match="non-trade"):
            build(
                runtime.journal,
                document,
                "a",
                before,
                after,
                after_revision=low,
                through_revision=high,
            )
        assert (
            build(
                runtime.journal,
                document,
                "a",
                before,
                after,
                after_revision=low,
                through_revision=high,
                historical=True,
            )
            == expected
        )
    finally:
        runtime.close()
