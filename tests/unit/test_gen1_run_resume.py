"""Clean same-run resume audit (owner policy P2a): a closed predecessor is readable only when both
players saved before either exited, nothing is owed, and the exported rules round-trip typed."""
import hashlib
import json
import secrets

import pytest

from server import gen1_run_resume
from server.gen1_engine_signals import SAVE_PROJECTION
from server.gen1_run_config import FILENAME, create_runtime
from server.gen1_run_resume import audit_predecessor
from server.gen1_staged_state import StagedGen1State
from server.protocol import digest
from tests.unit.test_gen1_engine_signal_runtime import deliver, payload
from tests.unit.test_gen1_engine_signals import witness
from tests.unit.test_gen1_faint_runtime import bag, paired, signal_batch
from tests.unit.test_gen1_sessions import contract

DIGEST = {"a": "1" * 64, "b": "2" * 64}


def entry(run_id="run_20260913_000000_abcdef", status="stopped", **more):
    return {"run_id": run_id, "name": "Predecessor", "status": status, "tcp_port": 54321, "http_port": 8081,
            "pid": None, "cartridges": contract("red", "blue")["players"], "native_trade": False, **more}


def predecessor(directory, *, witnesses=("a", "b"), faint=False, after=False, trailing=False, digests=DIGEST):
    """A paired starter link, both balls obtained, then each player's START-menu save witness."""
    runtime = create_runtime(directory, contract("red", "blue"))
    try:
        owners = paired(runtime)
        sequence = {"a": 2, "b": 2}

        def send(player, signals):
            value = payload(runtime, player, [], sequence[player])
            sequence[player] += 1
            value["signals"] = signals
            deliver(runtime, player, owners[player], value)
        if faint:  # A's linked death leaves B's force_faint unacknowledged
            deliver(runtime, "a", owners["a"], signal_batch(runtime, "a", sequence=2))
            sequence["a"] = 3
        for player in ("a", "b"):
            variant = runtime.contract["players"][player]["variant"]
            signals = [] if faint and player == "a" else [bag(variant)]
            if player in witnesses:
                signals.append({**witness(variant, digest=digests[player]), "frame": 130})
                if trailing and player == "a":
                    signals.append({**bag(variant), "frame": 131})
            send(player, signals)
            if after and player == "a":
                send("a", [{**bag(variant), "frame": 140}])
        return runtime.state().document(), runtime.journal.run_id
    finally:
        runtime.close()


def test_clean_predecessor_exports_typed_rules_and_both_witnesses(tmp_path):
    document, journal_run_id = predecessor(tmp_path)
    audit = audit_predecessor(tmp_path, registry_entry=entry())
    assert audit.ok and audit.reasons == ()
    assert audit.from_run == "run_20260913_000000_abcdef" and audit.journal_run_id == journal_run_id
    spec = json.loads((tmp_path / FILENAME).read_text())
    assert audit.contract_hash == digest(spec["contract"]) and audit.cartridges == spec["contract"]["players"]
    for player in ("a", "b"):
        seen = document["components"]["gen1-save-witness"][player]
        assert audit.required[player] == {"digest": DIGEST[player], "projection": SAVE_PROJECTION,
                                          "witness_index": seen["index"], "operation_id": seen["operation_id"]}
    # Typed round-trip: what is exported is exactly what StagedGen1State would restore.
    assert audit.rules == StagedGen1State.restore(document["rules"], data_dir=str(tmp_path)).document()
    assert audit.rules["core"]["links"][0]["area_id"] == "oaks_lab"
    assert audit.rules["core"]["pokeballs_obtained"] == {"a": True, "b": True}
    assert audit.rules["runtime"]["queued_commands"] == {"a": [], "b": []}
    resume = audit.resume_record()
    assert set(resume) == {"from_run", "required", "rules", "contract_hash"} and resume["rules"] == audit.rules


def test_missing_witness_for_either_player_refuses(tmp_path):
    predecessor(tmp_path, witnesses=("a",))
    audit = audit_predecessor(tmp_path, registry_entry=entry())
    assert not audit.ok and any("b" in reason and "witness" in reason for reason in audit.reasons)
    assert audit.rules is None and audit.required is None


def test_projection_mismatch_refuses(tmp_path, monkeypatch):
    predecessor(tmp_path)
    monkeypatch.setattr(gen1_run_resume, "PROJECTION", "wram-projection-v9")
    audit = audit_predecessor(tmp_path, registry_entry=entry())
    assert not audit.ok and any("projection" in reason for reason in audit.reasons)


def test_pending_commands_refuse(tmp_path):
    predecessor(tmp_path, faint=True)
    audit = audit_predecessor(tmp_path, registry_entry=entry())
    assert not audit.ok and any("pending" in reason and "b" in reason for reason in audit.reasons)


def test_active_trade_refuses(tmp_path, monkeypatch):
    predecessor(tmp_path)
    real = gen1_run_resume.read_journal

    def traded(path, **kwargs):
        stored = real(path, **kwargs)
        stored.snapshot.state["active_trade"] = {"phase": "offered"}
        return stored
    monkeypatch.setattr(gen1_run_resume, "read_journal", traded)
    audit = audit_predecessor(tmp_path, registry_entry=entry())
    assert not audit.ok and any("trade" in reason for reason in audit.reasons)


@pytest.mark.parametrize("shape", ["after", "trailing"])
def test_saved_but_unwitnessed_newer_play_holds(tmp_path, shape):
    predecessor(tmp_path, **{shape: True})
    audit = audit_predecessor(tmp_path, registry_entry=entry())
    assert not audit.ok and any("a" in reason and "after" in reason for reason in audit.reasons)


def test_running_predecessor_refuses(tmp_path):
    predecessor(tmp_path)
    audit = audit_predecessor(tmp_path, registry_entry=entry(status="running", pid=4242))
    assert not audit.ok and any("running" in reason for reason in audit.reasons)


def test_absent_or_foreign_run_directory_refuses(tmp_path):
    audit = audit_predecessor(tmp_path / "nowhere", registry_entry=entry())
    assert not audit.ok and audit.reasons
    # A registry that names different cartridges than the journal's contract is not the same run.
    predecessor(tmp_path)
    audit = audit_predecessor(tmp_path, registry_entry=entry(cartridges=contract("yellow", "yellow")["players"]))
    assert not audit.ok and any("cartridge" in reason for reason in audit.reasons)


def test_audit_is_read_only(tmp_path):
    predecessor(tmp_path)
    def files():  # sqlite's -wal/-shm side files appear for any reader; they carry no committed content
        return {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file() and not p.name.endswith(("-wal", "-shm"))}
    before = files()
    assert audit_predecessor(tmp_path, registry_entry=entry()).ok
    assert files() == before


def test_client_style_digest_matches_server_projection():
    cart_hex = secrets.token_bytes(0x8000).hex().upper()
    client = hashlib.sha256(cart_hex[0x498 * 2:].encode("ascii")).hexdigest()  # lua: sha256(cart_hex:sub(0x498*2+1))
    assert gen1_run_resume.save_digest(cart_hex) == client
    assert gen1_run_resume.save_digest(cart_hex) != hashlib.sha256(bytes.fromhex(cart_hex)[0x498:]).hexdigest()
