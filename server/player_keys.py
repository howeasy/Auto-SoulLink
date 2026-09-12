"""Player-scoped compatibility keys; independent of cartridge and logical IDs.

Raw keys are observations, not globally unique identities. Linear resolution is
intentional for the RC: use the authoritative link halves and refuse ambiguity.
The logical identity registry still owns acquisitions/migrations/replay.
"""
from __future__ import annotations


class AmbiguousPhysicalKey(ValueError):
    """Physical ownership cannot be resolved without reconciliation."""


def reference(player, key):
    if player not in ("a", "b") or not isinstance(key, str) or not key:
        raise ValueError("player and physical key required")
    return f"{player}|{key}"


def find_link(links, player, key):
    reference(player, key)
    found = None
    for entry in links:
        half = getattr(entry, player)
        if half is not None and half.key == key:
            if found is not None and found is not entry:
                raise AmbiguousPhysicalKey(f"ambiguous physical key in player {player}'s save")
            found = entry
    return found


def unique_link(links, key):
    """Read-only legacy projection; a cross-player ambiguity has no answer."""
    found = None
    for entry in links:
        if any(half is not None and half.key == key for half in (entry.a, entry.b)):
            if found is not None and found is not entry:
                return None
            found = entry
    return found
