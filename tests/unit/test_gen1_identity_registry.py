"""RBY models compose verified blob identities with the shared domain registry.

These synthetic witnesses exercise the domain contract for all ordered titles;
physical validation/admission and native transaction execution remain separate.
"""
from __future__ import annotations

import copy
from itertools import product

import pytest

from server.gen1_admission import clean_profiles
from server.gen1_party_codec import PartyCodec
from server.identity_registry import (
    IdentityContext,
    IdentityRegistry,
    IdentityWitness,
    MigrationWitness,
)
from server.protocol import digest
from server.protocol_journal import JournalError, ProtocolJournal
from server.save_identity import SaveIdentity
from tests.unit.test_gen1_party_codec import make_blob

RUN = "9" * 32
TITLES = ("red", "blue", "yellow")


def context(player, variant):
    # Identical save IDs/names and even identical cartridge hashes must remain
    # separate participants. Physical-instance validation belongs to admission.
    return IdentityContext(player, "gen1_rby", SaveIdentity("0000", "SAME"),
                           digest(clean_profiles()[variant]), player * 32,
                           ("1" if player == "a" else "2") * 32)


def mon(variant, dex, *, otid=0xBEEF, dv=0x7654):
    codec = PartyCodec(variant)
    species = next(int(index) for index, facts in codec.profile["species"].items() if facts["dex"] == dex)
    return codec.validate_blob(make_blob(codec, species=species, otid=otid, dv=dv))


def observed(binding, blob):
    return IdentityWitness(binding, blob.key, blob.sha256, 1)


def registry(first, second):
    state = IdentityRegistry(RUN)
    a, b = context("a", first), context("b", second)
    state.bind_context(a)
    state.bind_context(b)
    return state, a, b


@pytest.mark.parametrize("titles", list(product(TITLES, repeat=2)))
def test_all_ordered_titles_preserve_logical_members_through_trade_evolution_and_journal_reload(tmp_path, titles):
    first, second = titles
    state, a, b = registry(first, second)
    outgoing_a, outgoing_b = mon(first, 93), mon(second, 64, otid=0x1234)
    member_a = state.acquire("1" * 32, "3" * 32, observed(a, outgoing_a))["member_id"]
    member_b = state.acquire("2" * 32, "4" * 32, observed(b, outgoing_b))["member_id"]
    link_id = state.create_link("a", "5" * 32, [member_a, member_b])["link_id"]
    acquisitions = copy.deepcopy(state.document()["acquisitions"])
    obligation = {"member_id": member_a, "state": "pending", "id": "6" * 32}
    before = state.document()
    # The recipient cartridge supplies the resulting species/key. Raw OT is
    # independent of the save's wPlayerID and never replaces that save binding.
    received_b = mon(second, 94)
    received_a = mon(first, 65, otid=0x1234)
    changes = [MigrationWitness(member_a, a, outgoing_a.key, outgoing_a.sha256, observed(b, received_b)),
               MigrationWitness(member_b, b, outgoing_b.key, outgoing_b.sha256, observed(a, received_a))]
    staged = IdentityRegistry.restore(before, run_id=RUN)
    staged.migrate_many("a", "7" * 32, changes)
    assert state.document() == before
    assert staged.resolve(a, received_a.key) == member_b
    assert staged.resolve(b, received_b.key) == member_a
    assert staged.resolve(a, outgoing_a.key) is None and staged.resolve(b, outgoing_b.key) is None
    assert staged.document()["acquisitions"] == acquisitions
    assert staged.document()["links"][link_id]["members"] == [member_a, member_b]
    assert staged.document()["contexts"]["a"]["save_identity"] == {"ot_id": "0000", "trainer_name": "SAME"}
    journal_path = tmp_path / "run.sqlite3"
    journal = ProtocolJournal(journal_path, run_id=RUN, contract_hash="a" * 64)
    try:
        journal.bootstrap({"identities": before, "pending_deaths": [obligation]})
        journal.commit("a", "8" * 32, {"event": "verified_trade_model"}, expected_revision=0,
                       state={"identities": staged.document(), "pending_deaths": [obligation]},
                       commands={"a": [], "b": []}, result={"ack": "ACK"})
    finally:
        journal.close()
    journal = ProtocolJournal(journal_path, run_id=RUN, contract_hash="a" * 64)
    try:
        saved = journal.snapshot().state
        restored = IdentityRegistry.restore(saved["identities"], run_id=RUN)
        assert restored.document() == staged.document()
        assert saved["pending_deaths"] == [obligation]
        replay_before = restored.document()
        assert restored.migrate_many("a", "7" * 32, changes)["replayed"]
        assert restored.document() == replay_before
    finally:
        journal.close()


def test_yellow_yellow_identical_raw_keys_remain_distinct_members_after_ownership_swap():
    state, a, b = registry("yellow", "yellow")
    same = mon("yellow", 25)
    left = state.acquire("1" * 32, "3" * 32, observed(a, same))["member_id"]
    right = state.acquire("1" * 32, "3" * 32, observed(b, same))["member_id"]
    assert left != right and a.binding_digest == b.binding_digest
    assert a.save_identity == b.save_identity and a.physical_instance != b.physical_instance
    link = state.create_link("a", "5" * 32, [left, right])["link_id"]
    codec = PartyCodec("yellow")
    for receiver in (a, b):
        prepared, predicted = codec.prepare_exchange([same.raw], 0, same.raw, expected_key=same.key,
            incoming_key=same.key, evolved_species=same.species_index, boxed_keys=())
        assert prepared == (same.raw,) and predicted == same.key
        assert state.resolve(receiver, same.key) in (left, right)
    state.migrate_many("a", "2" * 32, [
        MigrationWitness(left, a, same.key, same.sha256, observed(b, same)),
        MigrationWitness(right, b, same.key, same.sha256, observed(a, same)),
    ])
    assert state.resolve(a, same.key) == right and state.resolve(b, same.key) == left
    assert state.document()["links"][link]["members"] == [left, right]
    assert IdentityRegistry.restore(state.document(), run_id=RUN).document() == state.document()


@pytest.mark.parametrize("recipient", TITLES)
def test_post_evolution_key_collision_publishes_neither_trade_half(recipient):
    state, a, b = registry("yellow", recipient)
    haunter, kadabra, occupied = mon("yellow", 93), mon(recipient, 64, otid=0x1234), mon(recipient, 94)
    left = state.acquire("1" * 32, "4" * 32, observed(a, haunter))["member_id"]
    right = state.acquire("2" * 32, "5" * 32, observed(b, kadabra))["member_id"]
    state.acquire("3" * 32, "6" * 32, observed(b, occupied))
    before = state.document()
    with pytest.raises(JournalError, match="duplicate current physical"):
        state.migrate_many("a", "7" * 32, [
            MigrationWitness(right, b, kadabra.key, kadabra.sha256, observed(a, mon("yellow", 65, otid=0x1234))),
            MigrationWitness(left, a, haunter.key, haunter.sha256, observed(b, occupied)),
        ])
    assert state.document() == before
