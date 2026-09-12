"""Cross-generation rule member replacement copies complete verified MonInfo."""

import copy

import pytest

from server.member_identity_rules import rekey
from server.protocol_journal import JournalError
from server.state import LinkEntry, LinkStatus, MonInfo
from tests.unit.test_gen1_wild_encounter import runtime  # noqa: F401


@pytest.mark.parametrize("kind", ["link", "pending_capture"])
def test_all_member_fields_and_original_area_survive_rekey(runtime, kind):  # noqa: F811
    rules = runtime.state().rules
    old = MonInfo("old", 5, 1, "OLD", False)
    peer = MonInfo("old", 6, 2, "PEER", False)
    if kind == "link":
        rules.links.append(LinkEntry("original", old, peer, LinkStatus.ALIVE))
        rules._index_entry(rules.links[0])
    else:
        rules.pending_captures["original"] = {"a": old, "b": peer}
    new = MonInfo("new", 17, 3, "NEW", True)
    assert rekey(rules, "a", "old", new) == (kind, "original")
    assert old == new and old is not new and peer == MonInfo("old", 6, 2, "PEER", False)
    assert not rules.party_keys["a"]  # Caller owns usability; this helper grants none.


def test_collision_is_refused_before_replacing_any_rule_field(runtime):  # noqa: F811
    rules = runtime.state().rules
    rules.pending_captures = {
        "one": {"a": MonInfo("old", 5, 1)},
        "two": {"a": MonInfo("new", 5, 2)},
    }
    before = copy.deepcopy(rules.pending_captures)
    with pytest.raises(JournalError, match="collides"):
        rekey(rules, "a", "old", MonInfo("new", 7, 3))
    assert rules.pending_captures == before
