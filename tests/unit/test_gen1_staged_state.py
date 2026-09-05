"""Stage actual rule transitions without writes; restore every persisted/runtime field."""
import builtins
import copy
import json

import pytest

from server.adapters import get_adapter
from server.gen1_staged_state import StagedGen1State
from server.protocol_journal import JournalError, ProtocolJournal
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo, SoulLinkState

A, B = "1234:1234:99", "5678:5678:B0"


def populated(tmp_path):
    state = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby", rom_type="Yellow"),
                          species_lock=True, rival_team_swap=True)
    state.rom_type = "Yellow"
    pair = LinkEntry("route_1", MonInfo(A, 5, 1, "A"), MonInfo(B, 5, 4, "B"), LinkStatus.ALIVE)
    state.links.append(pair)
    state._index_entry(pair)
    state.area_states["route_1"] = AreaStatus.LINKED
    state.party_keys = {"a": {A}, "b": {B}}
    state.party_size = {"a": 2, "b": 2}
    state.pokeballs_obtained = {"a": True, "b": True}
    state._has_helld = {"a", "b"}
    state.mon_stats[A] = {"level": 5, "maxHP": 20}
    state._ingest_party_blobs("a", [{"slot": 0, "key": A, "species_id": 1, "level": 5, "blob_hex": "AA" * 66}])
    return state


def no_file_access(*args, **kwargs):
    pytest.fail("staged rule transition touched the filesystem")


def test_export_is_detached_and_strict_restore_never_reads_a_file(tmp_path, monkeypatch):
    original = populated(tmp_path)
    monkeypatch.setattr(builtins, "open", no_file_access)
    document = original.to_document()
    restored = SoulLinkState.from_document(document, data_dir=str(tmp_path))
    assert restored.to_document() == document
    document["mon_stats"][A]["level"] = 99
    assert original.mon_stats[A]["level"] == restored.mon_stats[A]["level"] == 5
    assert restored._key_index[A] is restored.links[0]


@pytest.mark.parametrize("change", [lambda doc: doc["links"].append({"status": "alive"}),
                                  lambda doc: doc["links"][0].update(status="unknown"),
                                  lambda doc: doc.update(game_id="unsupported")])
def test_strict_restore_raises_instead_of_returning_a_partially_loaded_run(tmp_path, change):
    document = populated(tmp_path).to_document()
    change(document)
    with pytest.raises((ValueError, TypeError, KeyError)):
        SoulLinkState.from_document(document, data_dir=str(tmp_path))


def test_actual_faint_transition_changes_only_the_stage_and_drains_both_outboxes(tmp_path, monkeypatch):
    original = populated(tmp_path)
    before = original.to_document()
    staged = StagedGen1State.from_live(original, {"retired_pairs": []})
    monkeypatch.setattr(builtins, "open", no_file_access)
    monkeypatch.setattr("server.state.os.makedirs", no_file_access)
    immediate = staged.handle_event("a", {"event": "faint", "key": A, "area_id": "route_1"})
    commands = staged.take_commands("a", immediate)
    assert original.to_document() == before and original._key_index[A].status == LinkStatus.ALIVE
    assert staged._key_index[A].status == LinkStatus.DEAD
    assert any(c.get("cmd") == "force_faint" and c.get("key") == B for c in commands["b"])
    assert staged.queued_commands == {"a": [], "b": []}
    assert original.queued_commands == {"a": [], "b": []}
    assert staged._key_index[A] is staged.links[0] and staged.links[0] is not original.links[0]


def test_multiple_memorial_appends_in_one_transition_are_retained_without_file_reads(tmp_path, monkeypatch):
    original = populated(tmp_path)
    staged = StagedGen1State.from_live(original, {"retired_pairs": [{"existing": True}]})
    monkeypatch.setattr(builtins, "open", no_file_access)
    staged._write_memorial(staged.links[0])
    staged._write_memorial(LinkEntry("route_2", MonInfo("9999:1234:99"), None, LinkStatus.DEAD))
    rows = staged.document()["memorial"]["retired_pairs"]
    assert rows[0] == {"existing": True}
    assert [row["area_id"] for row in rows[1:]] == ["route_1", "route_2"]


def test_document_roundtrip_preserves_runtime_queues_sets_blobs_and_rule_decisions(tmp_path):
    original = populated(tmp_path)
    original.dupe_notified_areas = {"a": {"route_2", "route_1"}, "b": {"route_3"}}
    original.queued_commands["a"] = [{"cmd": "hud_show", "text": "waiting"}]
    first = StagedGen1State.from_live(original, {"retired_pairs": []})
    document = first.document()
    second = StagedGen1State.restore(document, data_dir=str(tmp_path))
    assert second.document() == document
    assert second.partner_blobs == first.partner_blobs
    assert second.party_keys == first.party_keys and second._has_helld == {"a", "b"}
    event = {"event": "faint", "key": A}
    first_out = first.handle_event("a", copy.deepcopy(event))
    second_out = second.handle_event("a", copy.deepcopy(event))
    assert first.take_commands("a", first_out) == second.take_commands("a", second_out)
    # Death timestamps are observed by each independent transition; everything
    # else, including link identity and both outboxes, must agree.
    for state in (first, second):
        state.links[0].killed_at = "same-time"
    assert first.document() == second.document()


def test_unknown_runtime_fields_cannot_be_silently_lost(tmp_path):
    original = populated(tmp_path)
    original.new_semantic_field = {"pending": True}
    with pytest.raises(JournalError, match="unclassified"):
        StagedGen1State.from_live(original, {"retired_pairs": []})


@pytest.mark.parametrize("change", [lambda doc: doc["runtime"].pop("party_keys"),
                                  lambda doc: doc["runtime"].update(extra="unknown"),
                                  lambda doc: doc["runtime"]["party_keys"]["a"].append(A),
                                  lambda doc: doc["core"].update(unknown="must not disappear"),
                                  lambda doc: doc["core"]["rules"].update(species_lock="false")])
def test_incomplete_ambiguous_or_coerced_documents_are_refused(tmp_path, change):
    document = StagedGen1State.from_live(populated(tmp_path), {"retired_pairs": []}).document()
    change(document)
    with pytest.raises(JournalError):
        StagedGen1State.restore(document, data_dir=str(tmp_path))


@pytest.mark.parametrize("variant", ["red_ap", "blue_ap", "FireRed"])
def test_other_modes_cannot_use_the_new_staged_store(tmp_path, variant):
    original = SoulLinkState(data_dir=str(tmp_path), adapter=get_adapter("gen1_rby" if variant.endswith("_ap") else "gen3_frlge"))
    original.rom_type = variant
    with pytest.raises(JournalError, match="vanilla RBY"):
        StagedGen1State.from_live(original, {"retired_pairs": []})


def test_legacy_trade_record_requires_recovery_instead_of_being_discarded(tmp_path):
    original = populated(tmp_path)
    original.pending_trade = {"phase": "applying", "done": {"a": True, "b": False}}
    with pytest.raises(JournalError, match="legacy trade"):
        StagedGen1State.from_live(original, {"retired_pairs": []})
    assert original.pending_trade["done"] == {"a": True, "b": False}


def test_real_rule_transition_and_memorial_can_be_restored_from_one_atomic_journal_commit(tmp_path):
    original = populated(tmp_path)
    staged = StagedGen1State.from_live(original, {"retired_pairs": []})
    path = tmp_path / "journal.sqlite3"
    journal = ProtocolJournal(path, run_id="1" * 32, contract_hash="2" * 64)
    journal.bootstrap(staged.document())
    request = {"event": "faint", "key": A}
    immediate = staged.handle_event("a", request)
    staged._write_memorial(staged.links[0])
    commands = staged.take_commands("a", immediate)
    journal.commit("a", "3" * 32, request, expected_revision=0, state=staged.document(),
                   commands=commands, result={"ack": "ACK"})
    journal.close()
    reopened = ProtocolJournal(path, run_id="1" * 32, contract_hash="2" * 64)
    try:
        recovered = StagedGen1State.restore(reopened.snapshot().state, data_dir=str(tmp_path))
        assert recovered.links[0].status == LinkStatus.DEAD
        assert recovered.document()["memorial"]["retired_pairs"][0]["a"]["key"] == A
        assert any(c["cmd"] == "force_faint" for c in reopened.pending("b"))
        assert original.links[0].status == LinkStatus.ALIVE
        assert not (tmp_path / "links.json").exists() and not (tmp_path / "memorial.json").exists()
        assert json.dumps(recovered.document(), sort_keys=True) == json.dumps(staged.document(), sort_keys=True)
    finally:
        reopened.close()
