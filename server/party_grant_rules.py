"""Shared staged rule bookkeeping for a proved, exempt grant already in a party.

The generation binding proves source, exemption, unique physical presence and
the peer's provenance. This operation grants no execution and queues no writes.
"""
import copy

from server.protocol_journal import JournalError
from server.staged_state import StagedSoulLinkState
from server.state import AreaStatus, LinkEntry, LinkStatus, MonInfo


def record_exempt_party_grant(state, player, area, mon, *, peer=None):
    if not isinstance(state, StagedSoulLinkState) or player not in ('a', 'b'):
        raise JournalError('detached paired rule state required')
    if not isinstance(area, str) or not 1 <= len(area) <= 128 or not area.isprintable():
        raise JournalError('explicit grant pairing area required')
    for value in (mon, peer):
        if value is not None and (not isinstance(value, MonInfo) or not isinstance(value.key, str)
                or not value.key or type(value.species) is not int or value.species < 1
                or type(value.level) is not int or not 1 <= value.level <= 100):
            raise JournalError('validated grant member required')
    if mon is None or state.run_over or any(state.queued_commands.values()):
        raise JournalError('grant cannot replace ended rules or unpublished commands')
    partner = 'b' if player == 'a' else 'a'
    pending = state.pending_captures.get(area, {})
    expected = {} if peer is None else {partner: peer}
    if pending != expected:
        raise JournalError('grant pairing does not match its verified peer')
    if peer is not None and (peer.key not in state.party_keys[partner] or any(
            getattr(link, partner) is not None and getattr(link, partner).key == peer.key for link in state.links)):
        raise JournalError('grant peer is not an unlinked party member')
    if any(link.area_id == area or getattr(link, player) is not None and getattr(link, player).key == mon.key
           for link in state.links):
        raise JournalError('grant key or pairing area is already linked')
    if any(player in rows and rows[player].key == mon.key for rows in state.pending_captures.values()):
        raise JournalError('grant key already has a pending acquisition')
    if state.area_states.get(area, AreaStatus.UNSEEN) not in (
            AreaStatus.UNSEEN, AreaStatus.PENDING_A, AreaStatus.PENDING_B):
        raise JournalError('grant area has incompatible rule history')
    if mon.key in state.bonus_keys[player] or mon.key in state.pending_memorials[player]:
        raise JournalError('grant key has prior bonus or memorial obligations')
    own = copy.deepcopy(mon)
    state.party_keys[player].add(mon.key)
    if peer is None:
        state.pending_captures[area] = {player: own}
        state._set_area_state(area, AreaStatus.PENDING_B if player == 'a' else AreaStatus.PENDING_A,
                              player=player, reason='verified_scripted_grant')
        return None
    halves = {player: own, partner: copy.deepcopy(peer)}
    link = LinkEntry(area_id=area, a=halves['a'], b=halves['b'], status=LinkStatus.ALIVE)
    state.links.append(link)
    state._index_entry(link)
    del state.pending_captures[area]
    state._set_area_state(area, AreaStatus.LINKED, player=player, reason='verified_scripted_grants')
    return link
