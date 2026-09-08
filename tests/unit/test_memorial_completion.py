import pytest

from server.linked_death_rules import record_linked_death, record_memorial_completion
from server.party_grant_rules import record_exempt_party_grant
from server.protocol_journal import JournalError
from server.state import LinkStatus, MonInfo
from tests.unit.test_party_grant_rules import staged


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_paired_completion_archives_once_in_the_detached_document(tmp_path, order):
    state = staged(tmp_path)
    mon = MonInfo(key="same", species=25, level=5)
    record_exempt_party_grant(state, "a", "gift", mon)
    record_exempt_party_grant(state, "b", "gift", mon, peer=mon)
    state.pokeballs_obtained["a"] = True
    record_linked_death(
        state,
        "a",
        "same",
        cause="battle",
        level=5,
        at="2026-09-08T00:00:00+00:00",
        partner_command="force_faint",
    )
    assert record_memorial_completion(state, order[0], "same") is False
    assert (
        state.links[0].status == LinkStatus.DEAD
        and not state.document()["memorial"]["retired_pairs"]
    )
    assert record_memorial_completion(state, order[1], "same") is True
    assert state.links[0].status == LinkStatus.MEMORIAL
    assert len(state.document()["memorial"]["retired_pairs"]) == 1 and not any(
        state.queued_commands.values()
    )
    before = state.document()
    with pytest.raises(JournalError):
        record_memorial_completion(state, order[1], "same")
    assert state.document() == before


@pytest.mark.parametrize("fault", ["unknown", "alive", "missing_half", "ambiguous"])
def test_invalid_completion_cannot_remove_pending_or_archive(tmp_path, fault):
    from server.state import LinkEntry

    state = staged(tmp_path)
    link = LinkEntry(
        "area",
        a=MonInfo(key="a", species=25, level=5),
        b=None if fault == "missing_half" else MonInfo(key="b", species=25, level=5),
        status=LinkStatus.ALIVE if fault == "alive" else LinkStatus.DEAD,
    )
    state.links.append(link)
    state.pending_memorials = {"a": {"a"}, "b": {"b"}}
    if fault == "ambiguous":
        state.links.append(LinkEntry("other", a=link.a, b=link.b, status=LinkStatus.DEAD))
    before = state.document()
    with pytest.raises(JournalError):
        record_memorial_completion(state, "a", "unknown" if fault == "unknown" else "a")
    assert state.document() == before
