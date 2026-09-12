"""Free-running Gen 1 observation batches: one client event, one atomic settlement.

Proposal P10 (docs/gen1_reference/proposals/P10-free-run-server.md), the server half of
handoff item 3. lua/gen1_observation_loop.lua (P4) publishes ONE ``observation`` event
whenever an engine signal, a source receipt or the heartbeat exists::

    {"schema": "rby-observation-v1", "event": "observation", "frame": 4821, "sequence": 17,
     "context": {"context_generation": ..., "physical_instance": ..., "save_identity": {...}},
     "rom": "<final sha1>",
     "signals": <rby-engine-signals-v1 batch or null>,
     "acquisitions": [{"kind": "capture" | "grant", "receipt": {...}}, ...],
     "inventory": <rby-initial-observation-v1 checkpoint or null>}

The batch is settled the way gen1_frame_journal.returned settles a compound frame bundle,
minus the frame ledger: each part is staged by the module that owns its evidence on ONE
detached stage/document, and one journal commit carries every record and both outboxes.
Order: inventory (the stable checkpoint acquisitions settle against), engine signals (ball
activation, faints, the starter source), then acquisition receipts. Nothing here decides a
rule and nothing here grants execution; the per-player sequence record is the only new
evidence, and it only orders the batches.
"""
import copy

from server.gen1_initial_observation import COMPONENT as INITIAL
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier

COMPONENT = 'gen1-observation-progress'
EVENT = 'observation'
SCHEMA = 'rby-observation-v1'
FIELDS = frozenset({'schema', 'event', 'frame', 'sequence', 'context', 'rom', 'signals', 'acquisitions', 'inventory'})
CONTEXT = frozenset({'context_generation', 'physical_instance', 'save_identity'})
ENTRY = frozenset({'sequence', 'operation_id', 'frame'})
MAX_RECEIPTS = 16
MAX_INT = 2**53 - 1
# gen1_source_receipts.ACQUISITION_KINDS. Static, exchange, wild and evolution rows belong to
# runtimes still welded to frame_complete (P10 section 5): refused fail-closed, never dropped.
SETTLED_KINDS = ('capture', 'grant')


def key(player):
    return digest({'component': COMPONENT, 'player': player})[:32]


def typed(request):
    if not isinstance(request, dict) or set(request) != FIELDS or request['schema'] != SCHEMA or request['event'] != EVENT:
        raise JournalError('typed free-run observation required')
    if (any(type(request[name]) is not int or not 0 <= request[name] <= MAX_INT for name in ('frame', 'sequence'))
            or request['sequence'] < 1):
        raise JournalError('integral observation frame and sequence required')
    if not isinstance(request['context'], dict) or set(request['context']) != CONTEXT or not isinstance(request['rom'], str):
        raise JournalError('complete observation context required')
    if any(request[name] is not None and not isinstance(request[name], dict) for name in ('signals', 'inventory')):
        raise JournalError('typed observation signals and inventory required')
    rows = request['acquisitions']
    if not isinstance(rows, list) or len(rows) > MAX_RECEIPTS:
        raise JournalError('bounded observation receipt list required')
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'kind', 'receipt'} or not isinstance(row['receipt'], dict):
            raise JournalError('typed observation receipt required')
        if row['kind'] not in SETTLED_KINDS:
            raise JournalError('observation receipt kind has no free-run settlement yet')
    return request


def record(runtime, player, operation, request):
    previous = runtime.journal.event(player, operation, request)
    if previous is not None:
        return previous.result
    typed(request)
    stage = runtime.state()
    document = stage.document()
    staged = stage_observation(runtime, stage, document, player, operation, request)
    return runtime.journal.commit(player, operation, request, expected_revision=stage.journal_revision, state=document,
        commands=staged['commands'], result=staged['result'], records=staged['records']).result


def stage_observation(runtime, stage, document, player, operation, request):
    """Stage every part of one batch on caller-owned state; return entry/result/commands/records.

    Only the detached stage/document change; discard both if this raises.
    """
    typed(request)
    initial = document['components'].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError('free-run observation requires initial enrollment')
    session = runtime.gate.sessions.get(player)
    if session is None:
        raise JournalError('free-run observation needs its admitted owner')
    metadata = session.metadata
    context = request['context']
    if (request['rom'] != metadata['gen1_metadata']['cartridge']['final_rom_sha1']
            or context['context_generation'] != initial['binding']['context_generation']
            or context['physical_instance'] != metadata['gen1_metadata']['physical_instance']
            or context['save_identity'] != metadata['save_identity']):
        raise JournalError('observation differs from admitted cartridge/context')
    if player in document['components'].get('gen1-frame-progress', {}):
        raise JournalError('frame-accounted player cannot publish free-run observations')
    entries = document['components'].setdefault(COMPONENT, {})
    old = entries.get(player)
    if request['sequence'] != (old['sequence'] + 1 if old else 1):
        raise JournalError('observation sequence skipped or repeated')
    if request['frame'] < (old['frame'] + 1 if old else initial['observation']['frame']):
        raise JournalError('observation frame moved backwards')
    result = {'ack': 'ACK', 'ordinary_execution': False}
    commands, records = {'a': [], 'b': []}, []

    def merge(staged, field):
        records.extend(staged['records'])
        for recipient in ('a', 'b'):
            commands[recipient].extend(staged['commands'][recipient])
        result[field] = staged['result'][field]

    # 1. Inventory. A standalone checkpoint may not cross an open physical obligation
    # (gen1_inventory_observation.stage_observation, gen1_starter_settlement.settle_ready): the
    # obligation's receipt carries its own checkpoint, so the heartbeat one is deferred, not refused.
    recorded_inventory = False
    if request['inventory'] is not None:
        if any(runtime.journal.pending_ids(p) for p in ('a', 'b')):
            result['inventory_deferred'] = True
        else:
            from server.gen1_inventory_observation import (
                COMPONENT as INVENTORY,
                stage_observation as stage_inventory,
            )
            before = document['components'].get(INVENTORY, {}).get(player)
            payload = {'sequence': before['sequence'] + 1 if before else 1,
                       'previous_operation_id': before['operation_id'] if before else initial['operation_id'],
                       'observation': copy.deepcopy(request['inventory'])}
            merge(stage_inventory(runtime, stage, document, player, operation,
                                  {'event': 'inventory_observation', 'payload': payload}), 'inventory_transition_digest')
            recorded_inventory = True
    # 2. Engine signals: ball activation, faints and the starter source, exactly as the standalone event.
    if request['signals'] is not None:
        from server.gen1_engine_signal_runtime import stage_observation as stage_engine
        merge(stage_engine(runtime, stage, document, player, operation,
                           {'event': 'engine_signals', 'payload': copy.deepcopy(request['signals'])}), 'engine_evidence_digest')
    # 3. Acquisition receipts, plus pending facts a fresh checkpoint may now settle (gen1_frame_acquisitions.stage).
    from server.gen1_acquisition_runtime import COMPONENT as ACQUISITIONS
    pending = document['components'].get(ACQUISITIONS, {}).get(player, {}).get('pending')
    if request['acquisitions'] or (pending and recorded_inventory):
        from server import event_reference
        from server.gen1_acquisition_runtime import decode_receipts, source_rom, stage_acquisitions
        provider = getattr(runtime, 'prepared_cartridges', None)
        rom = source_rom(initial['metadata'], player, provider.rom if provider is not None else None)
        facts = decode_receipts(request['acquisitions'], initial['metadata'], initial['binding'],
                                reference=event_reference.make(player, operation, request), rom=rom)
        merge(stage_acquisitions(runtime, stage, document, player, operation, facts, frame_request=request, rom=rom),
              'acquisition_digest')
    entry = {'sequence': request['sequence'], 'operation_id': operation, 'frame': request['frame']}
    entries[player] = entry
    result['observation_digest'] = digest(entry)
    records.append({'namespace': COMPONENT, 'key': key(player), 'value': entry})
    return {'entry': entry, 'result': result, 'commands': commands, 'records': records}


def verify_state(stage):
    entries = stage.document()['components'].get(COMPONENT, {})
    if not isinstance(entries, dict) or set(entries) - {'a', 'b'}:
        raise JournalError('invalid observation progress component')
    for entry in entries.values():
        if (not isinstance(entry, dict) or set(entry) != ENTRY
                or any(type(entry[name]) is not int or not 0 <= entry[name] <= MAX_INT for name in ('sequence', 'frame'))
                or entry['sequence'] < 1):
            raise JournalError('incomplete observation progress record')
        _identifier(entry['operation_id'])


def verify_journal(journal, stage):
    verify_state(stage)
    entries = stage.document()['components'].get(COMPONENT, {})
    for player in ('a', 'b'):
        stored = journal.record(COMPONENT, key(player))
        entry = entries.get(player)
        if (stored is None) != (entry is None) or stored is not None and stored.value != entry:
            raise JournalError('observation progress differs from its atomic journal record')
        if entry is None:
            continue
        event = journal.event_snapshot(player, entry['operation_id'])
        if (event is None or event.revision != stored.revision or event.request.get('event') != EVENT
                or event.request.get('sequence') != entry['sequence'] or event.request.get('frame') != entry['frame']
                or event.result.get('observation_digest') != digest(entry)):
            raise JournalError('observation progress lacks its exact committed event')
