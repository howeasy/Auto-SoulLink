from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from server.adapters.gen3_frlge import Gen3Adapter
from server.durable_dispatch import DurableDispatcher
from server.protocol_journal import JournalError, ProtocolJournal
from server.save_identity import SaveIdentity
from server.staged_state import StagedSoulLinkState
from server.state import SoulLinkState


def state(tmp_path):
    result = SoulLinkState(data_dir=str(tmp_path), is_rr=True, adapter=Gen3Adapter(is_rr=True))
    result.player_identity["a"] = {"ot_id": "00000001", "trainer_name": "ASH"}
    return result


def hello(ot_id="00000002"):
    return {"event": "hello", "trainer_name": "untrusted display", "ot_id": ot_id,
            "has_pokeballs": False,
            "party": [{"key": "12345678:00000002", "hp": 20, "maxHP": 20,
                       "level": 5, "blob_hex": "aa" * 100}]}


def test_admitted_save_identity_accepts_traded_lead_without_changing_pokemon_key(tmp_path):
    s = state(tmp_path)
    event = hello()
    s.handle_event("a", event, save_identity=SaveIdentity("00000001", "ASH"))
    assert not event.get("_rejected")
    assert s.player_identity["a"] == {"ot_id": "00000001", "trainer_name": "ASH"}
    assert s.party_keys["a"] == {"12345678:00000002"}
    assert s.partner_blobs["a"][0]["key"] == "12345678:00000002"


@pytest.mark.parametrize("trusted", [False, True])
def test_rejected_hello_preserves_commands_party_identity_and_trade_watchdog(tmp_path, monkeypatch, trusted):
    s = state(tmp_path)
    s.party_keys["a"] = {"old-key"}
    s.party_size["a"] = 2
    s.partner_blobs["a"] = [{"key": "old-key", "blob": b"old"}]
    s.queued_commands["a"] = [{"cmd": "force_faint", "key": "old-key"}]
    s.pending_trade = {"phase": "confirming", "token": "t1", "age": s.TRADE_WATCHDOG_EVENTS + 1}
    fields = ("player_identity", "party_keys", "party_size", "partner_blobs", "queued_commands", "pending_trade")
    before = {name: deepcopy(getattr(s, name)) for name in fields}
    monkeypatch.setattr(s, "_save", lambda: pytest.fail("rejected identity attempted persistence"))
    event = hello("00000001" if trusted else "00000002")
    identity = SaveIdentity("00000002", "OTHER") if trusted else None
    commands = s.handle_event("a", event, save_identity=identity)
    assert event["_rejected"] and "a" in s.identity_error
    assert [entry["cmd"] for entry in commands] == ["hud_show"]
    assert {name: getattr(s, name) for name in fields} == before


def test_json_lookalike_does_not_grant_trusted_identity_and_legacy_ot_still_works(tmp_path):
    s = state(tmp_path)
    event = hello()
    event["save_identity"] = {"ot_id": "00000001", "trainer_name": "ASH"}
    s.handle_event("a", event)
    assert event["_rejected"]
    event["ot_id"] = "00000001"
    s.handle_event("a", event)
    assert not event.get("_rejected") and "a" not in s.identity_error


@pytest.mark.parametrize("ot,name", [("", "ASH"), (" id ", "ASH"), ("id\n", "ASH"),
                                    (True, "ASH"), ("id", None), ("id", "A\x00B")])
def test_trusted_value_has_bounded_normalized_shape(ot, name):
    with pytest.raises(ValueError):
        SaveIdentity(ot, name)


def test_trusted_value_is_immutable_and_keyword_rejects_json_objects(tmp_path):
    identity = SaveIdentity("00000001", "ASH")
    with pytest.raises(FrozenInstanceError):
        identity.ot_id = "00000002"
    s = state(tmp_path)
    with pytest.raises(TypeError):
        s.handle_event("a", hello(), save_identity={"ot_id": "00000001"})
    with pytest.raises(ValueError):
        s.handle_event("a", {"event": "tick"}, save_identity=identity)


def test_staged_dispatch_persists_admitted_identity_and_keeps_legacy_document_shape(tmp_path):
    s = state(tmp_path)
    journal = ProtocolJournal(tmp_path / "journal.sqlite3", contract_hash="a" * 64)
    try:
        journal.bootstrap(StagedSoulLinkState.from_live(s, {"retired_pairs": []}).document())
        dispatcher = DurableDispatcher(journal, data_dir=tmp_path, validate_event=lambda *_: None,
                                       validate_receipt=lambda *_: [])
        event = hello()
        result = dispatcher.dispatch("a", "1" * 32, event, save_identity=SaveIdentity("00000001", "ASH"))
        assert result.revision == 1
        restored = dispatcher.state()
        assert restored.player_identity["a"] == {"ot_id": "00000001", "trainer_name": "ASH"}
        assert restored.party_keys["a"] == {"12345678:00000002"}
        assert not (tmp_path / "links.json").exists()
    finally:
        journal.close()


def test_durable_identity_rejection_cannot_commit_or_publish_old_queued_work(tmp_path):
    s = state(tmp_path)
    s.queued_commands["a"] = [{"cmd": "force_faint", "key": "old-key"}]
    journal = ProtocolJournal(tmp_path / "journal.sqlite3", contract_hash="a" * 64)
    try:
        journal.bootstrap(StagedSoulLinkState.from_live(s, {"retired_pairs": []}).document())
        before = journal.snapshot()
        dispatcher = DurableDispatcher(journal, data_dir=tmp_path, validate_event=lambda *_: None,
                                       validate_receipt=lambda *_: [])
        with pytest.raises(JournalError, match="identity was rejected"):
            dispatcher.dispatch("a", "1" * 32, hello("00000001"),
                                save_identity=SaveIdentity("00000002", "OTHER"))
        assert journal.snapshot() == before
        assert not journal.pending("a") and not journal.pending("b")
        assert dispatcher.state().queued_commands["a"] == s.queued_commands["a"]
    finally:
        journal.close()
