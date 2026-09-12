"""Refresh display/planning data from a generation-validated physical party.

This cache cannot acquire a member, form a link, activate rules, or make an
unqualified key usable. The caller owns decoding and observation provenance.
"""

import copy

from server.protocol_journal import JournalError


def refresh(rules, player, rows, *, limit=6):
    if (
        type(limit) is not int
        or not 1 <= limit <= 64
        or player not in ("a", "b")
        or not isinstance(rows, list)
        or len(rows) > limit
    ):
        raise JournalError("bounded observed party required")
    fields = {"slot", "key", "species_id", "level", "blob", "stats"}
    if any(
        not isinstance(row, dict)
        or set(row) != fields
        or type(row["slot"]) is not int
        or row["slot"] != index
        or not isinstance(row["key"], str)
        or not row["key"]
        or type(row["blob"]) is not bytes
        or not row["blob"]
        or not isinstance(row["stats"], dict)
        for index, row in enumerate(rows)
    ):
        raise JournalError("complete decoded party rows required")
    keys = {row["key"] for row in rows}
    if len(keys) != len(rows):
        raise JournalError("observed party has ambiguous physical keys")
    rules.party_size[player] = len(rows)
    rules.partner_blobs[player] = [
        copy.deepcopy({k: v for k, v in row.items() if k != "stats"}) for row in rows
    ]
    # Usability belongs to source-qualified acquisition/storage/migration policy.
    # Removing a disappearing key here would erase the outgoing member's status
    # before a same-frame NPC exchange can transfer it to the incoming member.
    for row in rows:
        if row['key'] in rules.party_keys[player]:
            rules.cache_stats(player, row["key"], copy.deepcopy(row["stats"]))
