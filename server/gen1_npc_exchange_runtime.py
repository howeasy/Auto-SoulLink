"""Durable NPC exchange settlement: a validated exchange fact -> one identity migration.

An in-game trade (`gen1_npc_exchange_receipt.validate`) hands the outgoing mon's logical
identity to the incoming mon. The fact stays PENDING until the player's latest stable
inventory checkpoint at or after `return_frame` shows the incoming key in the party with
the receipt's species, level and OT id and no longer shows the outgoing key; a checkpoint
after `return_frame` that contradicts either refuses. On settlement the outgoing member is
migrated (`identity_registry.migrate_many`, never `acquire`), and whichever rule half held
the outgoing key (a LinkEntry half or a pending capture) is rewritten in place to the
incoming MonInfo under its ORIGINAL area. An exchange never creates an acquisition, never
consumes an ordinal (`gen1-acquisition-ordinals` is untouched) and never pairs anything.
An outgoing key with no logical identity is refused: the registry cannot mint one here.

Phase / staging. The compound settlement calls `stage_exchanges` once per consumed
bundle, AFTER inventory settlement and AFTER `stage_acquisitions`, in the same detached
stage/document, folding `records` into the one atomic commit and `result['exchange_digest']`
into the frame result. The raw rows are the `npc_exchange` entries of the ONE wire list
`bundle['acquisitions']` (see `receipts_of`; `source_ref.index` is the raw position there);
`record` is the standalone handler for runs without frame accounting and a test driver only.
`verify_state` belongs beside the acquisition check in `Gen1RuntimeState.__init__`,
`verify_journal` beside it in `Gen1Runtime.state`.
"""
import copy
import hashlib

from server import event_reference
from server.admission_context import same_admitted_context
from server.gen1_initial_observation import (
    COMPONENT as INITIAL,
    display_name,
    inventory,
    validate as validate_observation,
)
from server.gen1_party_codec import PartyCodec
from server.gen1_starter_settlement import context as identity_context
from server.identity_registry import IdentityWitness, MigrationWitness
from server.gen1_engine_bridge import rekey as _rekey
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier
from server.state import MonInfo

COMPONENT = 'gen1-npc-exchanges'
ORDINALS = 'gen1-acquisition-ordinals'
ACQUISITIONS = 'gen1-acquisition-settlement'
EVENT = 'npc_exchange_observation'
SCHEMA = 'rby-npc-exchange-observation-v1'
INVENTORY = 'gen1-inventory-observations'
MAX_RECEIPTS = 16
ENTRY_FIELDS = {'sequence', 'operation_id', 'previous_operation_id', 'pending', 'settled'}
SETTLED_FIELDS = {'kind', 'source_ref', 'fact', 'exchange_event', 'member_id', 'inventory_operation', 'rule', 'area',
                  'before_evidence_digest', 'evidence_digest'}
RULES = ('link', 'pending_capture', 'identity_only')


def record_key(player):
    return digest({'component': COMPONENT, 'player': player})[:32]


def result_for(entry):
    return {'ack': 'ACK', 'exchange_digest': digest(entry), 'ordinary_execution': False}


def _typed(request):
    if set(request) != {'event', 'payload'} or request['event'] != EVENT or not isinstance(request['payload'], dict):
        raise JournalError('typed exchange observation required')
    payload = request['payload']
    if set(payload) != {'schema', 'variant', 'context_generation', 'final_sha1', 'sequence', 'receipts'} or payload['schema'] != SCHEMA:
        raise JournalError('complete exchange observation required')
    if not isinstance(payload['receipts'], list) or len(payload['receipts']) > MAX_RECEIPTS:
        raise JournalError('bounded exchange receipt list required')
    return payload


def decode_receipts(receipts, metadata, binding, *, reference):
    """Decode raw exchange receipts with the admitted context; each fact keeps its source reference.

    A thin caller of `gen1_source_receipts.decode`: indices are positions in `receipts` as given.
    """
    from server.gen1_source_receipts import EXCHANGE_KINDS, decode

    return decode(receipts, metadata, binding, reference=reference, kinds=EXCHANGE_KINDS)


def receipts_of(request):
    """Raw receipt list inside a standalone event or a compound frame bundle."""
    if request.get('event') == EVENT:
        return _typed(request)['receipts']
    if request.get('event') == 'frame_complete':
        rows = request.get('bundle', {}).get('acquisitions')  # one wire list; exchange rows keep their raw index
        return rows or []
    raise JournalError('exchange source event is neither standalone nor a compound frame')


def _stable(document, player, fact, initial):
    """The incoming mon as the latest stable checkpoint shows it, or None if not yet stable."""
    checkpoint = document['components'].get(INVENTORY, {}).get(player)
    if checkpoint is None or checkpoint['observation']['frame'] < fact['return_frame']:
        return None
    if checkpoint['observation']['host'] != initial['observation']['host']:
        raise JournalError('exchange checkpoint changed host; reconciliation required')
    roster = inventory(checkpoint['observation']['source'], initial['metadata']['save_identity'])
    rows = {row['key']: row for row in roster['members']}
    if fact['outgoing']['key'] in rows:
        raise JournalError('stable inventory after the exchange still holds the outgoing key; reconciliation required')
    row = rows.get(fact['incoming']['key'])
    if row is None or row['location'] != 'party':
        raise JournalError('stable inventory after the exchange lacks the incoming party member; reconciliation required')
    incoming = fact['incoming']
    blob = bytes.fromhex(row['blob_hex'])
    # The key already fixes species, DVs and OT id; level is the receipt's own claim.
    if blob[0] != incoming['species_index'] or blob[33] != incoming['level'] or int.from_bytes(blob[12:14], 'big') != incoming['ot_id']:
        raise JournalError('stable inventory shows a different mon under the incoming key')
    return {'operation_id': checkpoint['operation_id'], 'blob': blob, 'slot': row['slot']}


def stage_exchanges(runtime, stage, document, player, operation, facts, frame_origin=None, *, frame_request=None):
    """Stage new facts as pending, then settle every pending fact a stable checkpoint proves.

    Returns entry/result/commands/records for the caller's atomic commit. Only the
    detached stage/document change; `commands` is always empty. `facts` come from
    decode_receipts.
    """
    if not isinstance(facts, list) or len(facts) > MAX_RECEIPTS:
        raise JournalError('bounded decoded exchange facts required')
    initial = document['components'].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError('exchange settlement requires initial enrollment')
    session = runtime.gate.sessions.get(player)
    if session is None or not same_admitted_context(session.metadata, initial['metadata']):
        raise JournalError('exchange settlement needs its current admitted owner')
    if document['active_trade']:
        raise JournalError('native trade owns exchange settlement until verified closure')
    if frame_origin is not None:
        # ponytail: gen1_observation_provenance._contained knows no exchange kind yet; root adds
        # the elif there and swaps this for stage_origin(...) when it wires the frame bundle.
        origin = event_reference.validate(frame_origin)
        if (frame_request is None or frame_request.get('event') != 'frame_complete'
                or origin != event_reference.make(player, operation, frame_request)):
            raise JournalError('exchange frame origin differs from the staged operation')
    elif player in document['components'].get('gen1-frame-progress', {}):
        raise JournalError('frame-accounted exchanges require a compound frame origin')
    entries = document['components'].setdefault(COMPONENT, {})
    old = entries.get(player)
    entry = {'sequence': (old['sequence'] + 1) if old else 1, 'operation_id': operation,
             'previous_operation_id': old['operation_id'] if old else initial['operation_id'],
             'pending': copy.deepcopy(old['pending']) if old else [], 'settled': copy.deepcopy(old['settled']) if old else []}
    if frame_origin is not None:
        entry['frame_origin'] = copy.deepcopy(frame_origin)
    known = {row['fact']['receipt_digest'] for row in entry['pending'] + entry['settled']}
    known |= {row['fact']['incoming']['key'] for row in entry['pending'] + entry['settled']}
    for row in facts:
        if (not isinstance(row, dict) or set(row) != {'kind', 'fact', 'source_ref'} or not isinstance(row['fact'], dict)
                or not isinstance(row['fact'].get('incoming'), dict)
                or row['fact'].get('receipt_digest') in known or row['fact']['incoming'].get('key') in known):
            raise JournalError('exchange fact is malformed or repeats a delivered exchange')
        reference = row['source_ref']
        if not isinstance(reference, dict) or set(reference) != {'event', 'index'} or type(reference['index']) is not int or reference['index'] < 0:
            raise JournalError('exchange fact lacks its exact source row')
        current_ref = event_reference.make(player, operation, frame_request) if frame_request is not None else None
        source_request = frame_request if reference['event'] == current_ref else event_reference.resolve(runtime.journal, reference['event']).request
        raw = receipts_of(source_request)
        if reference['index'] >= len(raw):
            raise JournalError('exchange source index leaves its receipt list')
        checked = decode_receipts([raw[reference['index']]], initial['metadata'], initial['binding'], reference=reference['event'])[0]
        if checked['kind'] != row['kind'] or checked['fact'] != row['fact']:
            raise JournalError('exchange staging refuses caller-forged decoded facts')
        known |= {row['fact']['receipt_digest'], row['fact']['incoming']['key']}
        entry['pending'].append(copy.deepcopy(row))
    codec = PartyCodec(initial['metadata']['gen1_metadata']['cartridge']['variant'])
    own_context = identity_context(initial, player)
    still_pending = []
    for row in entry['pending']:
        fact = row['fact']
        stable = _stable(document, player, fact, initial)
        if stable is None:
            still_pending.append(row)
            continue
        outgoing = fact['outgoing']['key']
        member_id = stage.identities.resolve(own_context, outgoing)
        if member_id is None:
            raise JournalError('outgoing exchange mon has no logical identity; reconciliation required')
        mon = codec.validate_blob(stable['blob'])
        before_digest = hashlib.sha256(bytes.fromhex(fact['outgoing']['blob_hex'])).hexdigest()
        event_id = digest({'run_id': runtime.journal.run_id, 'player': player, 'exchange': row['source_ref']})[:32]
        witness = MigrationWitness(member_id, own_context, outgoing, before_digest, IdentityWitness(own_context, mon.key, mon.sha256, 1))
        stage.identities.migrate_many(player, event_id, [witness])
        info = MonInfo(key=mon.key, level=mon.level, species=mon.species_id, nickname=display_name(mon.nickname))
        rule, area = _rekey(stage.rules, player, outgoing, info, reason="npc_trade")
        if outgoing in stage.rules.party_keys[player]:
            stage.rules.party_keys[player].discard(outgoing)
            stage.rules.party_keys[player].add(mon.key)
        entry['settled'].append({'kind': row['kind'], 'source_ref': row['source_ref'], 'fact': fact, 'exchange_event': event_id,
            'member_id': member_id, 'inventory_operation': stable['operation_id'], 'rule': rule, 'area': area,
            'before_evidence_digest': before_digest, 'evidence_digest': mon.sha256})
    entry['pending'] = still_pending
    entries[player] = entry
    document['rules'] = stage.rules.document()
    document['identities'] = stage.identities.document()
    from server.gen1_runtime_state import recovery_history
    stage.barrier.set_history(recovery_history(document['rules'], document['identities'], document['active_trade'],
        document['components'].get('gen1-trade')))
    document['components']['gen1-runtime']['recovery'] = stage.barrier.document()
    return {'entry': entry, 'result': result_for(entry), 'commands': {'a': [], 'b': []},
            'records': [{'namespace': COMPONENT, 'key': record_key(player), 'value': entry}]}


def record(runtime, player, operation, request):
    """Standalone handler for runs without frame accounting; frame runs go through stage_exchanges."""
    previous = runtime.journal.event(player, operation, request)
    if previous is not None:
        return previous.result
    payload = _typed(request)
    stage = runtime.state()
    document = stage.document()
    initial = document['components'].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError('exchange settlement requires initial enrollment')
    metadata = runtime.gate.sessions[player].metadata
    old = document['components'].get(COMPONENT, {}).get(player)
    if payload['sequence'] != ((old['sequence'] + 1) if old else 1):
        raise JournalError('exchange observation sequence skipped or repeated')
    cartridge = metadata['gen1_metadata']['cartridge']
    if (payload['variant'] != cartridge['variant'] or payload['final_sha1'] != cartridge['final_rom_sha1']
            or payload['context_generation'] != initial['binding']['context_generation']):
        raise JournalError('exchange observation differs from admitted cartridge/context')
    reference = event_reference.make(player, operation, request)
    facts = decode_receipts(payload['receipts'], initial['metadata'], initial['binding'], reference=reference)
    staged = stage_exchanges(runtime, stage, document, player, operation, facts, frame_request=request)
    return runtime.journal.commit(player, operation, request, expected_revision=stage.journal_revision, state=document,
        commands=staged['commands'], result=staged['result'], records=staged['records']).result


def _source_ref(row):
    event_reference.validate(row['source_ref']['event'])
    if type(row['source_ref']['index']) is not int or not 0 <= row['source_ref']['index'] < MAX_RECEIPTS:
        raise JournalError('invalid exchange source index')


def verify_state(stage):
    document = stage.document()
    entries = document['components'].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries) - {'a', 'b'}:
        raise JournalError('invalid exchange component')
    members = document['identities']['members']
    events = document['identities']['events']
    acquired = {row['fact']['key'] for entry in document['components'].get(ACQUISITIONS, {}).values()
                for row in entry['pending'] + entry['settled']}
    granted = {row['fact']['key']: row for entry in document['components'].get(ACQUISITIONS, {}).values() for row in entry['settled']}
    for player, entry in entries.items():
        initial = document['components'].get(INITIAL, {}).get(player)
        if initial is None or not isinstance(entry, dict) or not set(entry) >= ENTRY_FIELDS or set(entry) - ENTRY_FIELDS - {'frame_origin'}:
            raise JournalError('incomplete exchange entry')
        _identifier(entry['operation_id'])
        _identifier(entry['previous_operation_id'])
        if type(entry['sequence']) is not int or entry['sequence'] < 1:
            raise JournalError('invalid exchange sequence')
        if 'frame_origin' in entry:
            origin = event_reference.validate(entry['frame_origin'])
            if origin['player'] != player or origin['operation_id'] != entry['operation_id']:
                raise JournalError('exchange frame origin differs from its current owner')
        if not isinstance(entry['pending'], list) or not isinstance(entry['settled'], list):
            raise JournalError('ordered pending and settled exchanges required')
        seen = set()
        for row in entry['pending']:
            if set(row) != {'kind', 'fact', 'source_ref'} or row['kind'] != 'npc_exchange' or row['fact']['receipt_digest'] in seen:
                raise JournalError('invalid pending exchange')
            _source_ref(row)
            seen.add(row['fact']['receipt_digest'])
        halves = [getattr(link, player) for link in stage.rules.links if getattr(link, player) is not None]
        halves += [rows[player] for rows in stage.rules.pending_captures.values() if player in rows]
        for row in entry['settled']:
            if set(row) != SETTLED_FIELDS or row['kind'] != 'npc_exchange' or row['fact']['receipt_digest'] in seen or row['rule'] not in RULES:
                raise JournalError('invalid settled exchange')
            seen.add(row['fact']['receipt_digest'])
            _source_ref(row)
            for field in ('exchange_event', 'member_id', 'inventory_operation'):
                _identifier(row[field])
            incoming, outgoing = row['fact']['incoming']['key'], row['fact']['outgoing']['key']
            member = members.get(row['member_id'])
            event = events.get(player + ':' + row['exchange_event'])
            lineage = [step for step in (member or {}).get('history', []) if step['event'] == player + ':' + row['exchange_event']]
            if (member is None or event is None or event['kind'] != 'identity_migration' or len(lineage) != 1
                    or lineage[0]['location']['key'] != incoming or lineage[0]['evidence_digest'] != row['evidence_digest']
                    or lineage[0].get('before_evidence_digest') != row['before_evidence_digest']
                    or [w['before_key'] for w in event['request']['witnesses']] != [outgoing]):
                raise JournalError('settled exchange lost its identity migration lineage')
            if incoming in acquired or player + ':' + row['exchange_event'] in document['identities']['acquisitions']:
                raise JournalError('exchange incoming mon was counted as an acquisition')
            if any(half.key == outgoing for half in halves):
                raise JournalError('settled exchange left its outgoing key in the rules')
            grant = granted.get(outgoing)
            if grant is not None and row['rule'] != 'identity_only' and grant['area'] != row['area']:
                raise JournalError('exchange moved a granted mon off its pairing area')
            # ponytail: the rewritten half itself is not re-checked here; a later native trade, death or
            # memorial legitimately moves it, and the migration lineage above is the durable proof.


def verify_journal(journal, stage):
    document = stage.document()
    entries = document['components'].get(COMPONENT, {})
    for player in ('a', 'b'):
        stored = journal.record(COMPONENT, record_key(player))
        entry = entries.get(player)
        if (stored is None) != (entry is None) or stored is not None and stored.value != entry:
            raise JournalError('exchange component differs from its atomic journal record')
        if entry is None:
            continue
        initial = document['components'][INITIAL][player]
        current = journal.event_snapshot(player, entry['operation_id'])
        if current is None or current.revision != stored.revision:
            raise JournalError('exchange current entry lost its exact committed event/revision')
        if entry.get('frame_origin') is not None:
            if event_reference.resolve(journal, entry['frame_origin']) != current or current.request.get('event') != 'frame_complete':
                raise JournalError('exchange current frame origin differs')
            if current.result.get('exchange_digest') != digest(entry) or current.result.get('observations_settled') is not True:
                raise JournalError('exchange current frame result differs from its entry')
        elif current.request.get('event') != EVENT or current.result != result_for(entry):
            raise JournalError('exchange current standalone result differs')
        else:
            payload = _typed(current.request)
            cartridge = initial['metadata']['gen1_metadata']['cartridge']
            if (payload['sequence'] != entry['sequence'] or payload['variant'] != cartridge['variant']
                    or payload['final_sha1'] != cartridge['final_rom_sha1']
                    or payload['context_generation'] != initial['binding']['context_generation']):
                raise JournalError('current exchange event differs from its admitted sequence/context')
        for row in entry['pending'] + entry['settled']:
            reference = row['source_ref']
            snapshot = event_reference.resolve(journal, reference['event'])
            receipts = receipts_of(snapshot.request)
            if (reference['event']['player'] != player or type(reference['index']) is not int
                    or not 0 <= reference['index'] < len(receipts) or snapshot.revision > stored.revision):
                raise JournalError('exchange source reference leaves its receipt list')
            # Re-decode the authoritative raw receipt; the stored fact is never trusted on its own.
            decoded = decode_receipts([receipts[reference['index']]], initial['metadata'], initial['binding'], reference=reference['event'])[0]
            if decoded['kind'] != row['kind'] or decoded['fact'] != row['fact']:
                raise JournalError('exchange fact differs from its authoritative receipt')
            if row not in entry['settled']:
                continue
            stable_event = journal.event_snapshot(player, row['inventory_operation'])
            if stable_event is None or not snapshot.revision <= stable_event.revision <= stored.revision:
                raise JournalError('settled exchange lost its stable inventory event')
            if stable_event.request.get('event') == 'frame_complete':
                observed = stable_event.request.get('bundle', {}).get('inventory')
            elif stable_event.request.get('event') == 'inventory_observation':
                observed = stable_event.request.get('payload', {}).get('observation')
            else:
                observed = None
            validate_observation(observed, initial['metadata'], initial['binding'])
            view = {'components': {INVENTORY: {player: {'operation_id': row['inventory_operation'], 'observation': observed}}}}
            stable = _stable(view, player, row['fact'], initial)
            if stable is None:
                raise JournalError('settled exchange inventory predates its return frame')
            witnesses = document['identities']['events'].get(player + ':' + row['exchange_event'], {}).get('request', {}).get('witnesses', [])
            if (len(witnesses) != 1 or witnesses[0]['after']['evidence_digest'] != hashlib.sha256(stable['blob']).hexdigest()
                    or witnesses[0]['before_evidence_digest'] != hashlib.sha256(bytes.fromhex(row['fact']['outgoing']['blob_hex'])).hexdigest()
                    or witnesses[0]['before_key'] != row['fact']['outgoing']['key'] or witnesses[0]['after']['key'] != row['fact']['incoming']['key']):
                raise JournalError('exchange identity migration differs from its physical witnesses')
