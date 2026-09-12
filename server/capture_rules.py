"""Staged rule bookkeeping for a proved acquisition that is subject to clauses.

The generation binding proves source, physical presence and identity first. This
operation stages the shared pending-capture / area-link rules exactly as the live
coordinator does for an ordinary catch or a player-choice gift, without queueing
any command: no quarantine, retrieval, sound or dialogue. A clause violation is
returned, not enforced; the rule coordinator owns the consequence.
"""
import copy

from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo


def record_clause_checked_acquisition(state, player, area, mon, *, gift, activate_from_capture=True):
    """Return {"linked": LinkEntry|None, "violation": (message, player)|None}."""
    if not isinstance(state, StagedSoulLinkState) or player not in ('a', 'b'):
        raise JournalError('detached paired rule state required')
    if not isinstance(area, str) or not 1 <= len(area) <= 128 or not area.isprintable():
        raise JournalError('explicit acquisition area required')
    if (not isinstance(mon, MonInfo) or not isinstance(mon.key, str) or not mon.key
            or type(mon.species) is not int or mon.species < 1 or type(mon.level) is not int or not 1 <= mon.level <= 100):
        raise JournalError('validated acquisition member required')
    if state.run_over or any(state.queued_commands.values()):
        raise JournalError('acquisition cannot replace ended rules or unpublished commands')
    if any(getattr(link, player) is not None and getattr(link, player).key == mon.key for link in state.links):
        raise JournalError('acquisition key is already linked')
    if any(player in rows and rows[player].key == mon.key for rows in state.pending_captures.values()):
        raise JournalError('acquisition key already has a pending acquisition')
    if mon.key in state.bonus_keys[player] or mon.key in state.pending_memorials[player]:
        raise JournalError('acquisition key has prior bonus or memorial obligations')
    status = state.area_states.get(area, AreaStatus.UNSEEN)
    if status in (AreaStatus.LINKED, AreaStatus.DEAD_ZONE):
        raise JournalError('acquisition area is already resolved')
    partner = 'b' if player == 'a' else 'a'
    pending = state.pending_captures.get(area, {})
    if player in pending:
        raise JournalError('player already holds a pending acquisition in this area')
    own = copy.deepcopy(mon)
    if type(activate_from_capture) is not bool:
        raise JournalError('explicit capture activation policy required')
    if not gift and activate_from_capture:
        # A catch in any non-gift area confirms Pokeballs are available (live rule).
        state.pokeballs_obtained[player] = True
    state.party_keys[player].add(mon.key)
    peer = pending.get(partner)
    if peer is None:
        state.pending_captures[area] = {player: own}
        state._set_area_state(area, AreaStatus.PENDING_B if player == 'a' else AreaStatus.PENDING_A,
                              player=player, reason='verified_acquisition')
        return {'linked': None, 'violation': None}
    halves = {player: own, partner: copy.deepcopy(peer)}
    violation = None if state.adapter.is_fixed_species_gift(area) else state._check_link_violation(halves['a'], halves['b'])
    if violation is not None:
        # Both halves stay pending; the coordinator decides the consequence.
        state.pending_captures[area][player] = own
        return {'linked': None, 'violation': list(violation)}
    link = LinkEntry(area_id=area, a=halves['a'], b=halves['b'], status=LinkStatus.ALIVE)
    state.links.append(link)
    state._index_entry(link)
    del state.pending_captures[area]
    state._set_area_state(area, AreaStatus.LINKED, player=player, reason='verified_acquisitions')
    return {'linked': link, 'violation': None}
