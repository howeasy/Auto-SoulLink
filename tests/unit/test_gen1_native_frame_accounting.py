"""Real journal/ordinary ledgers; native eligibility and terminal ACK are fixtures.

Existing native policy/engine suites own cartridge behavior. These tests prove
that even an eligible native command cannot spend unrecorded frame capacity.
"""

import copy
import secrets

import pytest

from server.execution_window import SCHEMA, command_scope, issue
from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_held_faint import verify as held_verify
from server.gen1_initial_observation import inventory
from server.gen1_native_execution import NativeExecutionPolicy
from server.gen1_native_frame_accounting import (
    COMPONENT,
    HISTORY,
    _return_transition,
    borrowed,
    handoff,
    handoff_status,
    key,
    persist_grant,
    returned,
)
from server.gen1_native_observation import checkpoint_from
from server.gen1_run_config import create_runtime
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.observation_fixture import ledger, observe, starters
from tests.unit.test_gen1_held_faint import checkpoint
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_trade_result import rules


def compose(value, tmp_path):
    """Install the native execution policy and receptionist the composed runtime would."""
    models = {p: rules("yellow") for p in ("a", "b")}
    manifests = {p: copy.deepcopy(companion_profiles()["yellow"]["manifest"]) for p in models}
    for p in models:
        models[p].rom_sha1 = value.contract["players"][p]["final_rom_sha1"]
        manifests[p]["final_sha1"] = models[p].rom_sha1
    policy = NativeExecutionPolicy(rules=models, manifests=manifests, fallback=held_verify)
    policy.bind(value)
    value.verify_operation_execution = policy
    value._native_acceptance = {}
    from types import SimpleNamespace

    from server.gen1_receptionist_runtime import ReceptionistRuntime
    from server.gen1_trade_rules import Gen1TradeRules

    ui_policy = SimpleNamespace(
        runtime=value,
        execution=policy,
        rules=models,
        manifests=manifests,
        binding=Gen1TradeRules(models, data_dir=tmp_path),
        candidate_checkpoints=lambda _player: {
            p: checkpoint_from(
                party_snapshot(value, p),
                value.state().document()["components"]["gen1-inventory-observations"][p][
                    "observation"
                ],
            )
            for p in ("a", "b")
        },
    )
    value.receptionist = ReceptionistRuntime(ui_policy)


@pytest.fixture
def runtime(tmp_path):
    value = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(value)
        ledger(value)  # the settled ordinary baseline a native loan borrows against
        compose(value, tmp_path)
        yield value
    finally:
        value.close()


def party_snapshot(runtime, player):
    point = runtime.state().document()["components"]["gen1-inventory-observations"][player][
        "observation"
    ]
    mons = inventory(point["source"], {"ot_id": "0000", "trainer_name": "SAME"})["members"]
    return {
        "schema": "gen1-party-readback-v1",
        "variant": "yellow",
        "save_id": "0000",
        "save_name": "SAME",
        "party_count": len(mons),
        "party": [row["blob_hex"] for row in mons],
        "species_list": [bytes.fromhex(row["blob_hex"])[0] for row in mons] + [255],
        "battle_flag": 0,
        "active_slot": None,
        "battle_hp": None,
    }


def queue(runtime, player="a"):
    manifest = runtime.verify_operation_execution.manifests[player]
    point = runtime.receptionist.policy.candidate_checkpoints(player)[player]
    query = {
        "schema": "rby-receptionist-query-v1",
        "pc": 0x40,
        "bank": manifest["receptionist"]["entry"]["bank"],
        "caller": manifest["receptionist"]["query_return"],
        "overlay_hex": "534C543101010100" + "00" * 8,
    }
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    runtime.receptionist.start(
        player,
        secrets.token_hex(16),
        {
            "event": "receptionist_entered",
            "payload": {
                "schema": "rby-receptionist-entry-v1",
                "context_generation": binding["context_generation"],
                "final_sha1": manifest["final_sha1"],
                "query": query,
                "checkpoint": point,
            },
        },
    )
    return runtime.journal.command(player, runtime.journal.pending_ids(player)[0])


def host(runtime, player, frame_number):
    initial = runtime.state().document()["components"]["gen1-initial-observations"][player]
    return {
        **initial["observation"]["host"],
        "frame": frame_number,
        "steps": frame_number - initial["observation"]["frame"],
        "bounded": True,
        "failed": False,
    }


def grant(runtime, command, frame_number, player="a", *, acceptance_frame=None):
    document = runtime.state().document()
    binding = runtime.gate.sessions[player].metadata["control_binding"]
    evidence = {
        "schema": "rby-native-window-evidence-v1",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "context_generation": binding["context_generation"],
        "final_sha1": runtime.contract["players"][player]["final_rom_sha1"],
        "host": host(runtime, player, frame_number),
        "native": {"phase": "before", "schema": "explicit-native-eligibility-fixture"},
        "accounting": runtime._native_acceptance.get(player)
        if borrowed(document, player)
        else None,
    }
    scope = command_scope(command, binding, phase=command["body"]["cmd"])
    # Typed policy publication is deliberate: no fabricated proof of ROM execution.
    proof = runtime.verify_operation_execution.publish(
        player,
        command,
        evidence,
        document,
        binding,
        scope,
        "f" * 64,
        False,
        {"token_hex": "12ABCDEF"},
    )
    request = {"schema": SCHEMA, "challenge": secrets.token_hex(16), "scope": scope}
    response = issue(request, proof)
    persist_grant(runtime, player, request, response, evidence)
    runtime._native_acceptance[player] = {
        "schema": "rby-native-grant-acceptance-v1",
        "challenge": request["challenge"],
        "host": host(
            runtime, player, frame_number if acceptance_frame is None else acceptance_frame
        ),
    }
    return request, response, evidence


def terminal(runtime, command, frame_number, player="a"):
    document = runtime.state().document()
    observed = copy.deepcopy(
        document["components"]["gen1-inventory-observations"][player]["observation"]
    )
    observed["frame"] = frame_number
    mons = inventory(observed["source"], {"ot_id": "0000", "trainer_name": "SAME"})["members"]
    party = {
        "schema": "gen1-party-readback-v1",
        "variant": "yellow",
        "save_id": "0000",
        "save_name": "SAME",
        "party_count": len(mons),
        "party": [row["blob_hex"] for row in mons],
        "species_list": [bytes.fromhex(row["blob_hex"])[0] for row in mons] + [255],
        "battle_flag": 0,
        "active_slot": None,
        "battle_hp": None,
    }
    native = checkpoint_from(party, observed)
    receipt = {
        "schema": "rby-receptionist-return-v1",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "checkpoint": native,
        "context_generation": runtime.gate.sessions[player].metadata["control_binding"][
            "context_generation"
        ],
        "final_sha1": runtime.contract["players"][player]["final_rom_sha1"],
        "sequence": ["after_query", "menus_restored"],
        "offer_operation_id": None,
        "frame": frame_number,
        "token_hex": "12ABCDEF",
    }
    operation = secrets.token_hex(16)
    message = {
        "event": "command_ack",
        "command_id": command["command_id"],
        "command_sequence": command["command_sequence"],
        "outcome": "ACK",
        "receipt": receipt,
    }
    runtime.receptionist.acknowledge(player, operation, message)
    entry = runtime.state().document()["components"][COMPONENT][player]
    return {
        "event": "native_frame_return",
        "payload": {
            "schema": "rby-native-frame-return-v1",
            "command_id": command["command_id"],
            "command_sequence": command["command_sequence"],
            "receipt_operation_id": operation,
            "receipt_digest": digest(receipt),
            "grant_challenge": entry["challenge"],
            "ledger_sequence": entry["progress"]["sequence"] + (entry["offered"] is not None),
            "accounting": copy.deepcopy(runtime._native_acceptance[player]),
            "host": host(runtime, player, frame_number),
            "inventory": observed,
            "checkpoint": checkpoint("yellow"),
            "native_checkpoint": native,
        },
    }


def test_native_renewal_retires_unused_capacity_and_keeps_ordinary_frozen(runtime):
    command = queue(runtime)
    baseline = runtime.state().document()["components"]["gen1-frame-progress"]["a"]
    first = grant(runtime, command, 110)
    saved = runtime.journal.snapshot()
    persist_grant(runtime, "a", *first)
    assert runtime.journal.snapshot() == saved
    grant(runtime, command, 115)
    entry = runtime.state().document()["components"][COMPONENT]["a"]
    assert entry["closed"] is None
    assert entry["progress"]["pending"]["before"] == 110
    assert entry["offered"]["host"]["frame"] == 115
    assert runtime.state().document()["components"]["gen1-frame-progress"]["a"] == baseline
    assert borrowed(runtime.state().document(), "a")
    message = terminal(runtime, command, 120)
    returned(runtime, "a", secrets.token_hex(16), message)
    assert runtime.state().document()["components"][COMPONENT]["a"]["progress"]["frame"] == 120


def test_old_credits_spent_during_renewal_rpc_are_not_charged_to_the_new_grant(runtime):
    command = queue(runtime)
    grant(runtime, command, 110)
    # Request at140, spend all30 remaining OLD credits before the response at170,
    # then spend all60 NEW credits. Request-time anchoring would reject230>200.
    grant(runtime, command, 140, acceptance_frame=170)
    message = terminal(runtime, command, 230)
    returned(runtime, "a", secrets.token_hex(16), message)
    entry = runtime.state().document()["components"][COMPONENT]["a"]
    assert entry["closed"]["receipt"]["before"] == 170
    assert entry["closed"]["receipt"]["after"] == 230
    assert entry["closed"]["receipt"]["steps"] == 60
    assert entry["progress"]["steps"] - entry["baseline"]["ledger"]["steps"] == 120


def test_acceptance_boundary_cannot_spend_beyond_the_old_grant(runtime):
    command = queue(runtime)
    grant(runtime, command, 110)
    grant(runtime, command, 140, acceptance_frame=171)
    message = terminal(runtime, command, 180)
    before = runtime.journal.snapshot()
    with pytest.raises(JournalError, match="granted range"):
        returned(runtime, "a", secrets.token_hex(16), message)
    assert runtime.journal.snapshot() == before


@pytest.mark.parametrize(
    "fault", ["extra_frames", "wrong_count", "owner", "challenge", "sequence", "receipt"]
)
def test_native_return_cannot_adopt_ungranted_or_foreign_progress(runtime, fault):
    command = queue(runtime)
    grant(runtime, command, 110)
    message = terminal(runtime, command, 120)
    payload = message["payload"]
    if fault == "extra_frames":
        payload["host"].update(frame=171, steps=71)
        payload["inventory"]["frame"] = 171
    elif fault == "wrong_count":
        payload["host"]["steps"] += 1
    elif fault == "owner":
        payload["host"]["owner_id"] = "f" * 32
    elif fault == "challenge":
        payload["grant_challenge"] = "f" * 32
    elif fault == "sequence":
        payload["ledger_sequence"] += 1
    else:
        payload["receipt_digest"] = "f" * 64
    before = runtime.journal.snapshot()
    with pytest.raises(JournalError):
        returned(runtime, "a", secrets.token_hex(16), message)
    assert runtime.journal.snapshot() == before


def test_next_native_command_waits_for_exact_prior_return_ack(runtime):
    first = queue(runtime)
    grant(runtime, first, 110)
    terminal(runtime, first, 120)
    second = queue(runtime)
    before = runtime.journal.snapshot()
    with pytest.raises(JournalError, match="previous frame-return"):
        grant(runtime, second, 120)
    assert runtime.journal.snapshot() == before


def test_removed_grant_history_refuses_even_after_a_later_return(runtime):
    command = queue(runtime)
    first, _, _ = grant(runtime, command, 110)
    grant(runtime, command, 115)
    returned(runtime, "a", secrets.token_hex(16), terminal(runtime, command, 120))
    runtime.journal._db.execute(
        "DELETE FROM records WHERE namespace=? AND record_key=?",
        (HISTORY, key("a", first["challenge"])),
    )
    with pytest.raises(JournalError):
        runtime.state()


def test_two_sided_returns_then_delayed_handoff_and_later_native_cycle(runtime):
    messages = {}
    for player in ("a", "b"):
        command = queue(runtime, player)
        grant(runtime, command, 110, player)
        messages[player] = terminal(runtime, command, 120, player)
        returned(runtime, player, secrets.token_hex(16), messages[player])
    # Readiness cannot force an active coordinator to close; the prior return
    # stays reusable after peer closure, without any additional frame adoption.
    document = runtime.state().document()
    blocked = copy.deepcopy(document)
    blocked["active_trade"] = "e" * 32
    request = {"event": "native_frame_handoff", "payload": messages["a"]["payload"]}
    with pytest.raises(JournalError, match="transaction"):
        _return_transition(
            runtime.journal,
            blocked,
            "a",
            request,
            operation=secrets.token_hex(16),
            revision=runtime.journal.snapshot().revision + 1,
            handoff=True,
        )
    for player in ("b", "a"):
        message = {"event": "native_frame_handoff", "payload": messages[player]["payload"]}
        operation = secrets.token_hex(16)
        handoff(runtime, player, operation, message)
        saved = runtime.journal.snapshot()
        handoff(runtime, player, operation, message)
        assert runtime.journal.snapshot() == saved
        current = runtime.state().document()["components"]["gen1-frame-progress"][player]
        assert current["ledger"]["frame"] == 120 and current["pending_observation"] is None
    from server.gen1_native_observation import candidate_checkpoints, checkpoints

    assert set(checkpoints(runtime)) == {"a", "b"} and set(candidate_checkpoints(runtime, "b")) == {"a", "b"}
    # A later loan borrows the handed-back ledger exactly where the handoff left it.
    next_command = queue(runtime)
    grant(runtime, next_command, 120)
    returned(runtime, "a", secrets.token_hex(16), terminal(runtime, next_command, 130))
    assert runtime.state().document()["components"][COMPONENT]["a"]["progress"]["frame"] == 130


def test_handoff_query_is_read_only_and_binds_return_reference(runtime):
    command = queue(runtime)
    grant(runtime, command, 110)
    message = terminal(runtime, command, 120)
    operation = secrets.token_hex(16)
    returned(runtime, "a", operation, message)
    challenge = secrets.token_hex(16)
    request = {
        "window": {"schema": "rby-native-handoff-query-v1", "challenge": challenge},
        "evidence": {
            "schema": "rby-native-handoff-query-v1",
            "challenge": challenge,
            "return_operation_id": operation,
            "context_generation": "a" * 32,
        },
    }
    before = runtime.journal.snapshot()
    assert handoff_status(runtime, "a", request)["ready"] is True
    assert runtime.journal.snapshot() == before


def test_composed_native_verifier_preserves_the_existing_held_faint_policy(tmp_path):
    from server.held_write_permit import VerifiedHeldWrite
    from tests.unit.test_gen1_faint_runtime import signal_batch
    from tests.unit.test_gen1_held_faint import evidence

    value = create_runtime(tmp_path, contract("yellow", "yellow"))
    try:
        starters(value)
        signal = signal_batch(value, "a")
        observed = copy.deepcopy(
            value.state().document()["components"]["gen1-inventory-observations"]["a"]["observation"]
        )
        observed["frame"] = 122
        observed["source"]["fields"]["party"] = signal["signals"][-1]["point"]["party_hex"]
        observe(value, "a", inventory=observed, signals=signal)
        compose(value, tmp_path)
        command = value.journal.command("b", value.journal.pending_ids("b")[0])
        point = evidence(value, command)
        point["host"]["frame"] = 110
        proof = value.verify_operation_execution(
            "b",
            command,
            point,
            value.state().document(),
            value.gate.sessions["b"].metadata["control_binding"],
        )
        assert isinstance(proof, VerifiedHeldWrite) and not hasattr(proof, "frames")
    finally:
        value.close()


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_native_commit_attribution_only_replaces_verified_footprint_and_keeps_other_drift(variant):
    from server.gen1_authorized_inventory import _native_points
    from server.gen1_full_save import SYMBOLS, image
    from server.gen1_party_codec import PartyCodec
    from tests.unit.test_gen1_memorial import fixture as saved_fixture
    from tests.unit.test_gen1_party_codec import make_blob

    before, _, identity = saved_fixture(variant, count=2, initialized=False)
    before["save_status"] = 2
    after = copy.deepcopy(before)
    incoming = make_blob(PartyCodec(variant), species=84, dv=0x6789, otid=0xBEEF)
    raw = bytearray.fromhex(after["fields"]["party"])
    raw[1], raw[8:52], raw[272:283], raw[338:349] = incoming[0], incoming[:44], incoming[44:55], incoming[55:]
    after["fields"]["party"] = raw.hex().upper()
    after["cart_hex"] = image(after).hex().upper()
    symbols = SYMBOLS["pokeyellow" if variant == "yellow" else "pokered"]

    def snapshot(point):
        main = bytes.fromhex(point["fields"]["main"])
        offset = symbols["wPokedexOwned"]-symbols["wMainDataStart"]
        return {"party_storage_hex": point["fields"]["party"], "save_name_hex": point["fields"]["name"],
                "map": main[symbols["wCurMap"]-symbols["wMainDataStart"]], "dex_hex": main[offset:offset+38].hex().upper()}

    mons = inventory(before, identity)["members"]
    party = {"schema": "gen1-party-readback-v1", "variant": variant, "save_id": identity["ot_id"], "save_name": identity["trainer_name"],
             "party_count": 2, "party": [mon["blob_hex"] for mon in mons],
             "species_list": [bytes.fromhex(mon["blob_hex"])[0] for mon in mons]+[255],
             "battle_flag": 0, "active_slot": None, "battle_hp": None}
    checkpoint = checkpoint_from(party, {"source": before, "final_sha1": "f"*40})
    observed = copy.deepcopy(after)
    observed["fields"]["tiles"] = "7F"  # Unrelated, unattributed source evidence.
    pre, post = _native_points(None, "a", before, {"body": {"cmd": "native_trade_commit"}},
        {"native": {"before": snapshot(before), "after": snapshot(after)}, "save_image_hex": after["cart_hex"]},
        {"native_initial": {"phase": "before", "checkpoint": checkpoint}, "native_return": {"inventory": {"source": observed}}})
    assert pre == before and post == after
    assert post["fields"]["tiles"] != observed["fields"]["tiles"]
