"""Clause/link bookkeeping separated from physical party usability.

Legacy rule primitives assume party membership while pairing. This adapter runs
them on detached state and restores that mask before returning; the caller must
prove both source members and assign usability through its disposition policy.
"""

import copy

from server.capture_rules import record_clause_checked_acquisition
from server.party_grant_rules import record_exempt_party_grant


def record(state, player, area, mon, *, exempt):
    masks = copy.deepcopy(state.party_keys)
    try:
        partner = "b" if player == "a" else "a"
        peer = state.pending_captures.get(area, {}).get(partner)
        if exempt:
            if peer is not None:
                state.party_keys[partner].add(peer.key)
            return {
                "linked": record_exempt_party_grant(state, player, area, mon, peer=peer),
                "violation": None,
            }
        return record_clause_checked_acquisition(
            state, player, area, mon, gift=False, activate_from_capture=False
        )
    finally:
        state.party_keys = masks
