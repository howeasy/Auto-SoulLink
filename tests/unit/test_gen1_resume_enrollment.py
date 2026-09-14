"""Resumed enrollment: each player of a run resumed from a closed predecessor must present the
witnessed save and a witnessed CONTINUE before the inherited rules history is allowed to stand."""
import copy
import hashlib
import json
import secrets
from pathlib import Path

import pytest

from server.gen1_faint_runtime import COMPONENT as FAINTS, verify_state as verify_faints
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_run_resume import COMPONENT, audit_predecessor
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_wild_encounter_runtime import _activation
from server.protocol_journal import JournalError
from server.state import LinkStatus
from tests.unit.test_gen1_engine_signal_runtime import deliver
from tests.unit.test_gen1_faint_runtime import signal_batch
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_party_codec import make_blob
from tests.unit.test_gen1_run_resume import entry, predecessor
from tests.unit.test_gen1_sessions import contract

CONTINUE = json.loads((Path(__file__).resolve().parents[2] / "data/games/gen1_rby/continue_sites.json").read_text())


def continue_witness(runtime, player, *, frame=90):
    variant = runtime.contract["players"][player]["variant"]
    sites = CONTINUE["titles"][variant]["sites"]
    stages = {}
    for offset, kind in enumerate(("load", "loaded", "chose", "pressed", "enter")):
        stages[kind] = {"frame": frame - 10 + 2 * offset, "pc": sites[kind]["address"], "bank": sites[kind]["bank"], "sp": 0xDFF0}
    stages["loaded"]["status"] = 2
    return {"schema": "rby-continue-receipt-v1", "source_sha256": CONTINUE["sha256"], "variant": variant,
            "context_generation": player * 32, "physical_instance": ("1" if player == "a" else "2") * 32,
            "final_sha1": runtime.contract["players"][player]["final_rom_sha1"], **stages}


def party_field(blobs):
    """A wPartyDataStart image holding the given 66-byte codec blobs (44 data + 11 OT + 11 nick)."""
    party = bytearray(404)
    party[0] = len(blobs)
    party[1:1 + len(blobs)] = bytes(blob[0] for blob in blobs)
    party[1 + len(blobs)] = 255
    for slot, blob in enumerate(blobs):
        party[8 + 44 * slot:52 + 44 * slot] = blob[:44]
        party[272 + 11 * slot:283 + 11 * slot] = blob[44:55]
        party[338 + 11 * slot:349 + 11 * slot] = blob[55:66]
    return party.hex().upper()


def resumed_payload(runtime, player, *, cart_hex=None, party=None):
    """The inherited living members (the predecessor's cached party blobs) are presented by default."""
    payload = observation(runtime, player)
    if cart_hex is not None:
        payload["source"]["cart_hex"] = cart_hex
    if party is None:
        party = [row["blob"] for row in runtime.state().rules.partner_blobs[player]]
    payload["source"]["fields"]["party"] = party_field(party)
    payload["continue_witness"] = continue_witness(runtime, player)
    return payload


def digest_of(cart_hex):
    return hashlib.sha256(cart_hex[0x498 * 2:].encode("ascii")).hexdigest()


def build_successor(tmp_path, **options):
    """A predecessor whose witnessed saves are exactly the fixture observation's CartRAM image."""
    cart_hex = "FF" * 0x8000  # tests.unit.test_gen1_initial_observation.source()
    pred = tmp_path / "pred"
    predecessor(pred, digests={"a": digest_of(cart_hex), "b": digest_of(cart_hex)})
    audit = audit_predecessor(pred, registry_entry=entry())
    assert audit.ok, audit.reasons
    return create_runtime(tmp_path / "next", contract("red", "blue"), resume=audit.resume_record(), **options)


@pytest.fixture
def successor(tmp_path):
    runtime = build_successor(tmp_path)
    try:
        yield runtime
    finally:
        runtime.close()


def test_creation_seeds_rules_resume_contract_and_inherited_activation(successor):
    document = successor.state().document()
    assert document["rules"]["core"]["links"][0]["area_id"] == "oaks_lab"
    assert document["rules"]["core"]["pokeballs_obtained"] == {"a": True, "b": True}
    resume = document["components"][COMPONENT]
    assert resume["from_run"] == "run_20260913_000000_abcdef" and resume["pending"] == {"a": True, "b": True}
    assert set(resume["required"]) == {"a", "b"} and set(resume) >= {"from_run", "required", "pending", "imported_at"}
    for player in ("a", "b"):
        activation = document["components"][FAINTS]["activations"][player]
        assert activation["index"] is None and activation["engine_record"] is None
        assert activation["inherited"]["from_run"] == "run_20260913_000000_abcdef"
        assert activation["inherited"]["digest"] == resume["required"][player]["digest"]
        assert _activation(document, player, 10 ** 6) is False  # no enrollment yet: not effective
    assert not successor.journal.pending_ids("a") and not successor.journal.pending_ids("b")
    spec = json.loads((Path(successor.data_dir) / "gen1_runtime.json").read_text())
    assert spec["initial_observations"] is True


def test_missing_continue_witness_is_refused(successor):
    owner = admit(successor, "a")
    before = successor.journal.snapshot()
    with pytest.raises(JournalError, match="witnessed CONTINUE"):
        send(successor, "a", owner, observation(successor, "a"))
    assert successor.journal.snapshot() == before


@pytest.mark.parametrize("fault", ["schema", "status", "order", "site", "context", "late"])
def test_malformed_or_new_game_witness_is_refused(successor, fault):
    owner = admit(successor, "a")
    payload = resumed_payload(successor, "a")
    witness = payload["continue_witness"]
    if fault == "schema":
        witness["schema"] = "rby-bootstrap-receipt-v1"
    elif fault == "status":
        witness["loaded"]["status"] = 1
    elif fault == "order":
        witness["enter"]["frame"] = witness["load"]["frame"] - 1
    elif fault == "site":
        witness["chose"]["pc"] += 1
    elif fault == "context":
        witness["context_generation"] = "f" * 32
    else:
        witness["enter"]["frame"] = payload["frame"] + 1
    before = successor.journal.snapshot()
    with pytest.raises(JournalError, match="witnessed CONTINUE"):
        send(successor, "a", owner, payload)
    assert successor.journal.snapshot() == before


def test_digest_mismatch_is_refused(successor):
    owner = admit(successor, "a")
    before = successor.journal.snapshot()
    with pytest.raises(JournalError, match="save projection differs"):
        send(successor, "a", owner, resumed_payload(successor, "a", cart_hex="FE" * 0x8000))
    assert successor.journal.snapshot() == before


def test_matching_save_and_continue_enroll_and_journal_the_resume(successor):
    owner = admit(successor, "a")
    operation = secrets.token_hex(16)
    result = send(successor, "a", owner, resumed_payload(successor, "a"), operation)
    assert result["ack"] == "ACK"
    document = successor.state().document()
    resume = document["components"][COMPONENT]
    assert resume["pending"] == {"a": False, "b": True}
    record = resume["enrolled"]["a"]
    assert record["from_run"] == "run_20260913_000000_abcdef" and record["digest"] == resume["required"]["a"]["digest"]
    assert record["witness_index"] == resume["required"]["a"]["witness_index"]
    assert record["binding"] == document["components"]["gen1-initial-observations"]["a"]["binding"]
    assert record["continue_witness"]["loaded"]["status"] == 2
    assert successor.journal.record(COMPONENT, record["record_key"]).value == record
    # The inherited history stands: links and ball activation survive the enrollment.
    assert document["rules"]["core"]["links"][0]["status"] == "alive"
    assert document["rules"]["core"]["pokeballs_obtained"]["a"] is True
    assert _activation(document, "a", 100) is True and _activation(document, "a", 99) is False
    assert _activation(document, "b", 100) is False
    # Replay is idempotent; a second attempt is immutable like any enrollment.
    before = successor.journal.snapshot()
    send(successor, "a", owner, resumed_payload(successor, "a"), operation)
    assert successor.journal.snapshot() == before
    with pytest.raises(JournalError, match="immutable"):
        send(successor, "a", owner, resumed_payload(successor, "a"))
    # The committed state restores through every verifier, including the faint activation shape.
    restored = Gen1RuntimeState.restore(document, data_dir=successor.data_dir)
    verify_faints(restored)
    for damage in ("activation", "witness", "save"):
        damaged = copy.deepcopy(document)
        if damage == "activation":
            damaged["components"][FAINTS]["activations"]["a"]["inherited"]["digest"] = "0" * 64
        elif damage == "witness":
            damaged["components"][COMPONENT]["enrolled"]["a"]["continue_witness"]["loaded"]["status"] = 1
        else:
            damaged["components"][COMPONENT]["required"]["a"]["digest"] = "0" * 64
            damaged["components"][COMPONENT]["enrolled"]["a"]["digest"] = "0" * 64
            damaged["components"][FAINTS]["activations"]["a"]["inherited"]["digest"] = "0" * 64
        with pytest.raises(JournalError):
            Gen1RuntimeState.restore(damaged, data_dir=successor.data_dir)


def test_both_players_resume_and_the_run_reopens(tmp_path):
    successor = build_successor(tmp_path)
    try:
        for player in ("a", "b"):
            owner = admit(successor, player)
            send(successor, player, owner, resumed_payload(successor, player))
        document = successor.state().document()
        assert document["components"][COMPONENT]["pending"] == {"a": False, "b": False}
        assert set(document["components"]["gen1-initial-observations"]) == {"a", "b"}
        directory = successor.data_dir
    finally:
        successor.close()
    reopened = open_runtime(directory)
    try:
        assert reopened.state().document()["components"][COMPONENT] == document["components"][COMPONENT]
    finally:
        reopened.close()


def test_fresh_run_refuses_a_continue_witness_and_keeps_its_guards(tmp_path):
    runtime = create_runtime(tmp_path, contract("red", "blue"))
    try:
        owner = admit(runtime, "a")
        payload = resumed_payload(runtime, "a")
        with pytest.raises(JournalError, match="continue witness"):
            send(runtime, "a", owner, payload)
        assert COMPONENT not in runtime.state().document()["components"]
    finally:
        runtime.close()


def test_creation_imports_no_identity_contexts_or_events(tmp_path):
    successor = build_successor(tmp_path)
    try:
        document = successor.state().document()
        identities = document["identities"]
        assert identities["contexts"] == {"a": None, "b": None} and identities["context_history"] == {"a": [], "b": []}
        assert identities["members"] == {} and identities["links"] == {} and identities["events"] == {}
        assert identities["acquisitions"] == {} and identities["ordinal"] == 0
        resume = document["components"][COMPONENT]
        assert set(resume["identities"]) == {"a", "b"}
        for player in ("a", "b"):
            assert set(resume["identities"][player]) == {"known_keys"}
            assert "1234:0000:99" in resume["identities"][player]["known_keys"]
    finally:
        successor.close()


def test_enrollment_refuses_when_an_inherited_living_member_is_absent(successor):
    owner = admit(successor, "a")
    before = successor.journal.snapshot()
    with pytest.raises(JournalError, match="absent from the presented"):
        send(successor, "a", owner, resumed_payload(successor, "a", party=[]))
    assert successor.journal.snapshot() == before


def test_enrollment_refuses_a_living_key_the_predecessor_never_knew(successor):
    owner = admit(successor, "a")
    stranger = make_blob(PartyCodec("red"), dv=0x4321, otid=0x0000)
    party = [row["blob"] for row in successor.state().rules.partner_blobs["a"]] + [stranger]
    before = successor.journal.snapshot()
    with pytest.raises(JournalError, match="predecessor never"):
        send(successor, "a", owner, resumed_payload(successor, "a", party=party))
    assert successor.journal.snapshot() == before


def test_enrollment_binds_inherited_members_and_links_to_the_new_contexts(tmp_path):
    successor = build_successor(tmp_path)
    try:
        owner_a = admit(successor, "a")
        send(successor, "a", owner_a, resumed_payload(successor, "a"))
        identities = successor.state().identities.document()
        assert len(identities["members"]) == 1 and identities["links"] == {}
        member = next(iter(identities["members"].values()))
        assert member["current"] == {"player": "a", "save_ref": member["current"]["save_ref"], "key": "1234:0000:99"}
        owner_b = admit(successor, "b")
        send(successor, "b", owner_b, resumed_payload(successor, "b"))
        stage = successor.state()
        identities = stage.identities.document()
        assert len(identities["members"]) == 2 and len(identities["links"]) == 1
        link = next(iter(identities["links"].values()))
        assert set(link["members"]) == set(identities["members"])
        assert all(identities["contexts"][p] is not None for p in ("a", "b"))
        # A linked death on the INHERITED pair settles in the resumed run and reaches the partner.
        value = signal_batch(successor, "a", sequence=1, activate=False)
        assert deliver(successor, "a", owner_a, value)["ack"] == "ACK"
        stage = successor.state()
        assert stage.rules.links[0].status == LinkStatus.DEAD
        assert [c["cmd"] for c in successor.journal.pending("b")][0] == "force_faint"
        document = stage.document()
        Gen1RuntimeState.restore(document, data_dir=successor.data_dir)
    finally:
        successor.close()


def test_inherited_faint_before_the_partner_enrolls_is_refused(tmp_path):
    successor = build_successor(tmp_path)
    try:
        owner_a = admit(successor, "a")
        send(successor, "a", owner_a, resumed_payload(successor, "a"))
        before = successor.journal.snapshot()
        with pytest.raises(JournalError, match="paired enrollment required before linked faint settlement"):
            deliver(successor, "a", owner_a, signal_batch(successor, "a", sequence=1, activate=False))
        assert successor.journal.snapshot() == before
    finally:
        successor.close()
