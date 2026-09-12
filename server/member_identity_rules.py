"""Rekey a proved existing rule member without changing its area or pairing.

The generation caller owns identity/physical proof and usability. Every MonInfo
field comes from that caller's replacement, including a changed shiny status.
"""

import copy
from dataclasses import fields

from server.protocol_journal import JournalError
from server.state import MonInfo


def rekey(rules, player, outgoing, mon):
    if (
        player not in ("a", "b")
        or not isinstance(outgoing, str)
        or not outgoing
        or not isinstance(mon, MonInfo)
        or not mon.key
    ):
        raise JournalError("owned rule-member replacement required")
    matches = []
    for link in rules.links:
        half = getattr(link, player)
        if half is not None and half.key == outgoing:
            matches.append(("link", link.area_id, half, link))
        elif half is not None and half.key == mon.key:
            raise JournalError("rule-member replacement collides with another link")
    for area, rows in rules.pending_captures.items():
        half = rows.get(player)
        if half is not None and half.key == outgoing:
            matches.append(("pending_capture", area, half, None))
        elif half is not None and half.key == mon.key:
            raise JournalError("rule-member replacement collides with another pending capture")
    if len(matches) > 1:
        raise JournalError("outgoing rule member is ambiguous")
    if not matches:
        return "identity_only", None
    kind, area, half, link = matches[0]
    for field in fields(MonInfo):
        setattr(half, field.name, copy.deepcopy(getattr(mon, field.name)))
    if link is not None:
        rules._refresh_key_projection(outgoing)
        rules._index_entry(link)
    return kind, area
