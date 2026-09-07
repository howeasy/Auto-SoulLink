from dataclasses import replace
from itertools import count

import pytest

from server.identity_registry import (
    IdentityContext,
    IdentityRegistry,
    IdentityWitness,
    MigrationWitness,
)
from server.protocol import digest
from server.protocol_journal import JournalError, ProtocolJournal
from server.save_identity import SaveIdentity

RUN = "9" * 32


def token(value):
    return f"{value:032x}"


@pytest.fixture
def registry():
    sequence = count(100)
    registry = IdentityRegistry(RUN, new_id=lambda: token(next(sequence)))
    a = IdentityContext("a", "gen3_frlge", SaveIdentity("AAAA", "ALICE"), "a" * 64, "a" * 32, "1" * 32)
    b = IdentityContext("b", "gen3_frlge", SaveIdentity("BBBB", "BOB"), "b" * 64, "b" * 32, "2" * 32)
    registry.bind_context(a)
    registry.bind_context(b)
    return registry, a, b


def observed(context, key, evidence="d"):
    return IdentityWitness(context, key, evidence * 64, 1)


def acquire(registry, context, key, number=1):
    return registry.acquire(token(number), token(number + 1000), observed(context, key))["member_id"]


def migration(member_id, source, key, target, new_key):
    return MigrationWitness(member_id, source, key, "e" * 64, observed(target, new_key, "f"))


def test_raw_keys_are_scoped_to_player_and_save_not_global_logical_ids(registry):
    state, a, b = registry
    first = acquire(state, a, "SAME:RAW:KEY")
    second = acquire(state, b, "SAME:RAW:KEY")
    assert first != second
    assert state.resolve(a, "SAME:RAW:KEY") == first
    assert state.resolve(b, "SAME:RAW:KEY") == second


@pytest.mark.parametrize("key", ["12345678:12345678", "1234:4321:99", "future binding opaque key"])
def test_registry_does_not_assume_a_cartridge_key_layout(registry, key):
    state, a, _ = registry
    member = acquire(state, a, key)
    assert state.member(member)["current"]["key"] == key


def test_exact_retry_and_duplicate_detection_never_create_another_member(registry):
    state, a, _ = registry
    first = state.acquire(token(1), token(1001), observed(a, "before"))
    before = state.document()
    repeated = state.acquire(token(1), token(1001), observed(a, "before"))
    assert first["created"] and not first["replayed"]
    assert repeated["member_id"] == first["member_id"]
    assert repeated["replayed"] and not repeated["created"]
    assert state.document() == before
    other_detector = state.acquire(token(2), token(1001), observed(a, "before", "c"))
    assert not other_detector["created"] and other_detector["member_id"] == first["member_id"]
    with pytest.raises(JournalError, match="already bound"):
        state.acquire(token(3), token(1003), observed(a, "before"))
    confirmed = state.acquire(token(3), token(1003), observed(a, "before"), existing_member_id=first["member_id"])
    assert not confirmed["created"] and len(state.document()["members"]) == 1


def test_conflicting_event_or_acquisition_identity_does_not_publish(registry):
    state, a, _ = registry
    acquire(state, a, "before")
    before = state.document()
    with pytest.raises(JournalError, match="reused"):
        state.acquire(token(1), token(1001), observed(a, "different"))
    with pytest.raises(JournalError, match="conflicting physical"):
        state.acquire(token(2), token(1001), observed(a, "different"))
    assert state.document() == before


def test_confirmed_nature_or_npc_key_migration_keeps_member_acquisition_and_link_identity(registry):
    state, a, b = registry
    member = acquire(state, a, "old-key")
    peer = acquire(state, b, "peer-key")
    link = state.create_link("a", token(2), [member, peer])["link_id"]
    before_acquisitions = state.document()["acquisitions"]
    witness = migration(member, a, "old-key", a, "new-key")
    state.migrate_many("a", token(3), [witness])
    assert state.resolve(a, "old-key") is None
    assert state.resolve(a, "new-key") == member
    assert state.historical_members("a", "old-key") == [member]
    assert state.document()["acquisitions"] == before_acquisitions
    assert state.document()["links"][link]["members"] == [member, peer]
    assert state.migrate_many("a", token(3), [witness])["replayed"]
    assert len(state.member(member)["history"]) == 2


def test_native_trade_transfers_existing_members_and_preserves_ids(registry):
    state, a, b = registry
    first, second = acquire(state, a, "A"), acquire(state, b, "B")
    link = state.create_link("a", token(2), [first, second])["link_id"]
    source = state.document()["acquisitions"]
    witnesses = [migration(first, a, "A", b, "A"), migration(second, b, "B", a, "B")]
    result = state.migrate_many("b", token(2), witnesses)
    assert result["created_members"] == 0
    assert state.resolve(a, "B") == second and state.resolve(b, "A") == first
    assert state.resolve(a, "A") is None and state.resolve(b, "B") is None
    assert state.document()["acquisitions"] == source
    assert state.document()["links"][link]["members"] == [first, second]


def test_batch_can_swap_scoped_keys_without_an_intermediate_duplicate_or_partial_result(registry):
    state, a, _ = registry
    first = acquire(state, a, "A")
    second = acquire(state, a, "B", 2)
    state.migrate_many("a", token(3), [migration(first, a, "A", a, "B"), migration(second, a, "B", a, "A")])
    assert state.resolve(a, "A") == second and state.resolve(a, "B") == first


@pytest.mark.parametrize("failure", ["collision", "wrong_member", "wrong_before", "duplicate", "stale_context"])
def test_invalid_migration_batch_publishes_none_of_its_members(registry, failure):
    state, a, b = registry
    first, second = acquire(state, a, "A"), acquire(state, b, "B")
    witnesses = [migration(first, a, "A", a, "new-A"), migration(second, b, "B", b, "new-B")]
    if failure == "collision":
        witnesses[1] = migration(second, b, "B", a, "new-A")
    elif failure == "wrong_member":
        witnesses[1] = replace(witnesses[1], member_id=token(999))
    elif failure == "wrong_before":
        witnesses[1] = replace(witnesses[1], before_key="not-B")
    elif failure == "duplicate":
        witnesses[1] = witnesses[0]
    else:
        witnesses[1] = replace(witnesses[1], source_context=replace(b, context_generation="f" * 32))
    before = state.document()
    with pytest.raises(JournalError):
        state.migrate_many("a", token(9), witnesses)
    assert state.document() == before


def test_historical_key_reuse_is_new_identity_and_never_retargets_old_obligations(registry):
    state, a, _ = registry
    member = acquire(state, a, "old")
    state.migrate_many("a", token(2), [migration(member, a, "old", a, "new")])
    replacement = acquire(state, a, "old", 3)
    assert member != replacement
    assert state.resolve(a, "old") == replacement
    assert state.member(member)["current"]["key"] == "new"
    assert state.historical_members("a", "old") == sorted([member, replacement])


def test_new_context_requires_fresh_witness_but_prior_exact_action_replay_is_read_only(registry):
    state, a, _ = registry
    member = acquire(state, a, "A")
    new = replace(a, context_generation="f" * 32)
    state.bind_context(new)
    before = state.document()
    assert state.acquire(token(1), token(1001), observed(a, "A"))["replayed"]
    with pytest.raises(JournalError, match="stale"):
        state.acquire(token(2), token(1002), observed(a, "B"))
    with pytest.raises(JournalError, match="stale"):
        state.resolve(a, "A")
    assert state.document() == before and state.resolve(new, "A") == member


def test_save_replacement_and_duplicate_physical_instance_are_refused(registry):
    state, a, b = registry
    before = state.document()
    with pytest.raises(JournalError, match="another save"):
        state.bind_context(replace(a, save_identity=SaveIdentity("DIFFERENT")))
    with pytest.raises(JournalError, match="independent"):
        state.bind_context(replace(b, physical_instance=a.physical_instance))
    assert state.document() == before


def test_link_reassignment_preserves_logical_links_and_history_atomically(registry):
    state, a, b = registry
    ids = [acquire(state, a, "A", 1), acquire(state, b, "B", 1),
           acquire(state, a, "C", 2), acquire(state, b, "D", 2)]
    l1 = state.create_link("a", token(3), ids[:2])["link_id"]
    l2 = state.create_link("b", token(3), ids[2:])["link_id"]
    before = state.document()
    with pytest.raises(JournalError, match="duplicate link membership"):
        state.replace_link_members("a", token(4), {l1: [ids[0], ids[3]]})
    assert state.document() == before
    state.replace_link_members("a", token(4), {l1: [ids[0], ids[3]], l2: [ids[2], ids[1]]})
    assert state.document()["links"][l1]["history"][0]["members"] == ids[:2]
    assert state.document()["links"][l2]["history"][0]["members"] == ids[2:]


@pytest.mark.parametrize("damage", ["unknown", "history", "origin", "wrong_save", "duplicate_key", "wrong_event", "partial_context"])
def test_strict_restore_refuses_partial_or_inconsistent_identity_documents(registry, damage):
    state, a, _ = registry
    first = acquire(state, a, "A")
    second = acquire(state, a, "B", 2)
    document = state.document()
    if damage == "unknown":
        document["members"][first]["silent_extra"] = True
    elif damage == "history":
        document["members"][first]["history"] = []
    elif damage == "origin":
        document["members"][first]["origin_acquisition"] = "a:" + token(999)
    elif damage == "wrong_save":
        document["members"][first]["current"]["save_ref"] = "0" * 64
    elif damage == "duplicate_key":
        document["members"][second]["current"]["key"] = "A"
        document["members"][second]["history"][-1]["location"]["key"] = "A"
    elif damage == "wrong_event":
        document["events"]["a:" + token(1)]["result"]["member_id"] = token(999)
    else:
        del document["contexts"]["a"]["physical_instance"]
    with pytest.raises(JournalError):
        IdentityRegistry.restore(document, run_id=RUN)


def test_unknown_legacy_object_graph_and_wrong_run_cannot_be_coerced_into_registry(registry):
    state, _, _ = registry
    with pytest.raises(JournalError):
        IdentityRegistry.restore({"links": [{"a": {"key": "unwitnessed"}}]}, run_id=RUN)
    with pytest.raises(JournalError, match="another run"):
        IdentityRegistry.restore(state.document(), run_id="0" * 32)


@pytest.mark.parametrize("count", [0, 2, True, 1.0])
def test_ambiguous_count_and_unvalidated_json_are_not_identity_witnesses(registry, count):
    state, a, _ = registry
    with pytest.raises(JournalError):
        IdentityWitness(a, "A", "d" * 64, count)
    with pytest.raises(JournalError, match="typed"):
        state.acquire(token(1), token(1001), {"key": "A", "observed_count": 1})


def test_identity_migration_and_pending_death_reference_commit_and_reload_together(tmp_path, registry):
    state, a, _ = registry
    member = acquire(state, a, "old")
    obligation = {"id": token(500), "member_id": member, "state": "pending"}
    journal = ProtocolJournal(tmp_path / "identities.db", run_id=RUN, contract_hash="a" * 64)
    try:
        journal.bootstrap({"identities": state.document(), "death_obligations": [obligation]})
        state.migrate_many("a", token(2), [migration(member, a, "old", a, "new")])
        journal.commit("a", token(2), {"event": "verified_identity_migration"}, expected_revision=0,
                       state={"identities": state.document(), "death_obligations": [obligation]},
                       commands={"a": [], "b": []}, result={"ack": "ACK"})
        journal.close()
        journal = ProtocolJournal(tmp_path / "identities.db", run_id=RUN, contract_hash="a" * 64)
        saved = journal.snapshot().state
        restored = IdentityRegistry.restore(saved["identities"], run_id=journal.run_id)
        assert saved["death_obligations"] == [obligation]
        assert restored.member(obligation["member_id"])["current"]["key"] == "new"
        assert restored.document() == state.document()
    finally:
        journal.close()


@pytest.mark.parametrize("damage", ["migration_result", "link_result", "history_creator", "alias_origin",
                                    "current_key", "event_kind_list", "acquisition_member_list", "link_creator",
                                    "ordinal", "request", "missing_migration_history"])
def test_restored_results_and_histories_cannot_be_retargeted_to_other_known_identities(registry, damage):
    state, a, b = registry
    first, peer = acquire(state, a, "A"), acquire(state, b, "B")
    other = acquire(state, a, "C", 2)
    link = state.create_link("a", token(3), [first, peer])["link_id"]
    other_link = state.create_link("b", token(3), [other])["link_id"]
    state.acquire(token(4), token(1004), observed(a, "A"), existing_member_id=first)
    state.migrate_many("a", token(5), [migration(first, a, "A", a, "new-A")])
    document = state.document()
    if damage == "migration_result":
        document["events"]["a:" + token(5)]["result"]["member_ids"] = [other]
    elif damage == "link_result":
        document["events"]["a:" + token(3)]["result"]["link_id"] = other_link
    elif damage == "history_creator":
        document["members"][first]["history"][0]["event"] = "b:" + token(1)
    elif damage == "alias_origin":
        document["members"][first]["origin_acquisition"] = "a:" + token(1004)
    elif damage == "current_key":
        document["members"][first]["current"]["key"] = "unwitnessed"
        assert document["members"][first]["history"][-1]["location"]["key"] == "new-A"
        assert document["acquisitions"]["a:" + token(1001)]["origin"]["key"] == "A"
    elif damage == "event_kind_list":
        document["events"]["a:" + token(5)]["kind"] = []
    elif damage == "acquisition_member_list":
        document["acquisitions"]["a:" + token(1009)] = {"member_id": [], "origin": state.member(first)["current"]}
    elif damage == "link_creator":
        document["links"][link]["created_by"] = "b:" + token(3)
    elif damage == "ordinal":
        document["events"]["a:" + token(5)]["ordinal"] = 1
    elif damage == "request":
        document["events"]["a:" + token(5)]["request"]["witnesses"][0]["after"]["key"] = "changed"
    else:
        document["members"][first]["history"].pop()
        document["members"][first]["current"] = dict(document["members"][first]["history"][0]["location"])
    with pytest.raises(JournalError):
        IdentityRegistry.restore(document, run_id=RUN)


def test_exported_acquisition_locations_are_independent_copies(registry):
    state, a, _ = registry
    member = acquire(state, a, "A")
    document = state.document()
    current = document["members"][member]["current"]
    history = document["members"][member]["history"][0]["location"]
    origin = document["acquisitions"]["a:" + token(1001)]["origin"]
    assert current is not history and current is not origin and history is not origin
    current["key"] = "changed"
    assert history["key"] == origin["key"] == state.member(member)["current"]["key"] == "A"
    with pytest.raises(JournalError):
        IdentityRegistry.restore(document, run_id=RUN)


def test_retired_context_cannot_be_reactivated_or_imported_as_latest(registry):
    state, a, _ = registry
    new = replace(a, context_generation="f" * 32)
    state.bind_context(new)
    before = state.document()
    with pytest.raises(JournalError, match="retired"):
        state.bind_context(a)
    assert state.document() == before
    document = state.document()
    document["context_history"]["a"].append(document["context_history"]["a"][0])
    document["contexts"]["a"] = document["context_history"]["a"][0]["context"]
    with pytest.raises(JournalError, match="retired"):
        IdentityRegistry.restore(document, run_id=RUN)


def resign(event):
    event["digest"] = digest({"kind": event["kind"], "request": event["request"]})


def test_global_replay_rejects_temporarily_duplicate_physical_identity(registry):
    state, a, _ = registry
    first = acquire(state, a, "A", 1)
    second = acquire(state, a, "B", 2)
    state.migrate_many("a", token(3), [migration(first, a, "A", a, "C")])
    state.migrate_many("a", token(4), [migration(second, a, "B", a, "A")])
    document = state.document()
    e1, e2 = document["events"]["a:" + token(3)], document["events"]["a:" + token(4)]
    e1["ordinal"], e2["ordinal"] = e2["ordinal"], e1["ordinal"]
    with pytest.raises(JournalError, match="duplicate current"):
        IdentityRegistry.restore(document, run_id=RUN)


def test_global_replay_rejects_link_creation_before_its_members(registry):
    state, a, b = registry
    first, second = acquire(state, a, "A"), acquire(state, b, "B")
    state.create_link("a", token(2), [first, second])
    document = state.document()
    e1, e2 = document["events"]["a:" + token(1)], document["events"]["a:" + token(2)]
    e1["ordinal"], e2["ordinal"] = e2["ordinal"], e1["ordinal"]
    with pytest.raises(JournalError, match="unknown member"):
        IdentityRegistry.restore(document, run_id=RUN)


def test_global_replay_rejects_temporarily_duplicate_link_membership(registry):
    state, a, b = registry
    first, second = acquire(state, a, "A"), acquire(state, b, "B")
    l1 = state.create_link("a", token(2), [first])["link_id"]
    l2 = state.create_link("b", token(2), [second])["link_id"]
    state.replace_link_members("a", token(3), {l1: []})
    state.replace_link_members("a", token(4), {l2: [second, first]})
    document = state.document()
    e1, e2 = document["events"]["a:" + token(3)], document["events"]["a:" + token(4)]
    e1["ordinal"], e2["ordinal"] = e2["ordinal"], e1["ordinal"]
    with pytest.raises(JournalError, match="duplicate link membership"):
        IdentityRegistry.restore(document, run_id=RUN)


def test_restored_new_acquisition_alias_requires_its_explicit_confirmation(registry):
    state, a, _ = registry
    first = acquire(state, a, "A")
    state.acquire(token(2), token(1002), observed(a, "A"), existing_member_id=first)
    document = state.document()
    event = document["events"]["a:" + token(2)]
    event["request"]["existing_member_id"] = None
    resign(event)
    with pytest.raises(JournalError, match="confirm duplicate"):
        IdentityRegistry.restore(document, run_id=RUN)


def test_restored_noop_migration_is_refused_even_with_consistent_final_locations(registry):
    state, a, _ = registry
    first = acquire(state, a, "A")
    state.migrate_many("a", token(2), [migration(first, a, "A", a, "B")])
    document = state.document()
    event = document["events"]["a:" + token(2)]
    event["request"]["witnesses"][0]["after"]["key"] = "A"
    resign(event)
    document["members"][first]["current"]["key"] = "A"
    document["members"][first]["history"][-1]["location"]["key"] = "A"
    with pytest.raises(JournalError, match="must witness"):
        IdentityRegistry.restore(document, run_id=RUN)


@pytest.mark.parametrize("kind", ["acquisition", "migration"])
def test_restore_replays_binding_activation_and_refuses_retired_context_actions(registry, kind):
    state, a, _ = registry
    first = acquire(state, a, "A")
    new = replace(a, context_generation="f" * 32)
    state.bind_context(new)
    if kind == "acquisition":
        acquire(state, new, "B", 2)
    else:
        state.migrate_many("a", token(2), [migration(first, new, "A", new, "B")])
    document = state.document()
    event = document["events"]["a:" + token(2)]
    old = document["context_history"]["a"][0]["context"]
    if kind == "acquisition":
        event["request"]["witness"]["context"] = old
    else:
        event["request"]["witnesses"][0]["source_context"] = old
    resign(event)
    with pytest.raises(JournalError, match="stale"):
        IdentityRegistry.restore(document, run_id=RUN)


def test_restore_rejects_huge_ordinal_without_allocating_its_claimed_range(registry):
    state, _, _ = registry
    document = state.document()
    document["ordinal"] = 2**53 - 1
    with pytest.raises(JournalError, match="ordinal"):
        IdentityRegistry.restore(document, run_id=RUN)
