"""Free-running Gen 1 observation batches: one client event, one atomic settlement.

Proposal P10 (docs/gen1_reference/proposals/P10-free-run-server.md), the server half of
handoff item 3. lua/gen1_observation_loop.lua (P4) publishes ONE ``observation`` event
whenever an engine signal, a source receipt or the heartbeat exists::

    {"schema": "rby-observation-v1", "event": "observation", "frame": 4821, "sequence": 17,
     "context": {"context_generation": ..., "physical_instance": ..., "save_identity": {...}},
     "rom": "<final sha1>",
     "signals": <rby-engine-signals-v1 batch or null>,
     "acquisitions": [{"kind": <gen1_source_receipts.KINDS>, "receipt": {...}}, ...],
     "inventory": <rby-initial-observation-v1 checkpoint or null>}

``acquisitions`` is the ONE source-receipt list gen1_acquisition_observers.lua assembles in
frame order: captures, scripted grants, static origins and battle ends, NPC exchanges, wild
begins and ends, ordinary evolutions. The batch is settled the way the retired frame-credit
loop settled a compound frame bundle, minus the frame ledger: each part is staged by the
module that owns its evidence on ONE detached stage/document, and one journal commit carries
every record and both outboxes. Order: inventory (the stable checkpoint acquisitions settle
against), engine signals (ball activation, faints, the starter source), the trainer
engagement, then the receipt list decoded once (raw indices kept): static origins/ends
first, so an origin is known before its own capture pairs and ambiguous evidence is held;
acquisitions; NPC exchanges and evolutions, which migrate members the acquisitions settled;
the wild-encounter lifecycle (no_catch through the engine bridge); storage; the in-battle
instruction. Nothing here decides a rule and nothing here grants execution; the per-player
sequence record is the only new evidence, and it only orders the batches.
"""
import copy

from server.gen1_initial_observation import COMPONENT as INITIAL
from server.gen1_source_receipts import KINDS
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier

COMPONENT = 'gen1-observation-progress'
EVENT = 'observation'
SCHEMA = 'rby-observation-v1'
FIELDS = frozenset({'schema', 'event', 'frame', 'sequence', 'context', 'rom', 'signals', 'acquisitions', 'inventory'})
# The loop's polled battle byte (wIsInBattle) and its debounced trainer engagement ({trainer_id, frame} or null):
# optional on the wire so the live-proven P10 batches stay valid; the loop always sends both.
OPTIONAL = frozenset({'battle', 'trainer'})
TRAINER = frozenset({'trainer_id', 'frame'})
CONTEXT = frozenset({'context_generation', 'physical_instance', 'save_identity'})
ENTRY = frozenset({'sequence', 'operation_id', 'frame'})
MAX_RECEIPTS = 16
MAX_INT = 2**53 - 1


def key(player):
    return digest({'component': COMPONENT, 'player': player})[:32]


def typed(request):
    if not isinstance(request, dict) or set(request) - OPTIONAL != FIELDS or request['schema'] != SCHEMA or request['event'] != EVENT:
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
        if row['kind'] not in KINDS:  # every catalogued kind settles below; anything else fails closed
            raise JournalError('unknown observation receipt kind')
    if 'battle' in request and (type(request['battle']) is not int or not 0 <= request['battle'] <= 255):
        raise JournalError('observation battle byte required')
    trainer = request.get('trainer')
    if trainer is not None and (not isinstance(trainer, dict) or set(trainer) != TRAINER
                                or type(trainer['trainer_id']) is not int or not 1 <= trainer['trainer_id'] <= 255
                                or type(trainer['frame']) is not int or not 0 <= trainer['frame'] <= request['frame']):
        raise JournalError('typed trainer battle start required')
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
        from server.gen1_hud_feedback import pending_physical_ids

        if any(pending_physical_ids(runtime.journal, p) for p in ('a', 'b')):
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
    # 2b. Trainer engagement: the shared engine decides Rival Swap (_handle_trainer_battle_start) and queues
    # replace_rival_team for this player; the held rival-team executor writes it at the battle_init checkpoint.
    if request.get('trainer') is not None:
        from server.gen1_faint_runtime import synchronize
        from server.gen1_semantic_events import trainer_battle_start_event
        trainer_id = request['trainer']['trainer_id']
        # handle_event returns the player's own immediate commands and clears them; take_commands drains both queues.
        immediate = stage.rules.handle_event(player, trainer_battle_start_event(trainer_id=trainer_id))
        taken = stage.rules.take_commands(player, immediate)
        # replace_rival_team is the only Gen 1 command this event queues; anything else the engine might add here is
        # executed elsewhere on Gen 1 (gen1_faint_runtime.settle drops sounds and memorials the same way).
        swaps = [c for c in taken[player] if c.get('cmd') == 'replace_rival_team']
        for swap in swaps:
            swap['source_frame'] = request['trainer']['frame']
        commands[player].extend(swaps)
        result['trainer_battle'] = {'trainer_id': trainer_id, 'rival_team': len(swaps)}
        synchronize(stage, document)
    # 3. The source-receipt list, decoded ONCE so every fact keeps its raw index, then staged kind by kind in
    # the order the retired compound frame used (gen1_frame_acquisitions.stage, gen1_frame_journal.returned).
    from server import event_reference
    from server.gen1_acquisition_runtime import (
        COMPONENT as ACQUISITIONS,
        source_rom,
        stage_acquisitions,
    )
    from server.gen1_npc_exchange_runtime import COMPONENT as EXCHANGES, stage_exchanges
    from server.gen1_source_receipts import (
        ACQUISITION_KINDS,
        EVOLUTION_KINDS,
        EXCHANGE_KINDS,
        LIFECYCLE_KINDS,
        decode,
    )
    from server.gen1_wild_encounter_runtime import (
        COMPONENT as ENCOUNTERS,
        KINDS as ENCOUNTER_ROWS,
        stage as stage_encounters,
    )
    components = document['components']
    pending = {name: bool(components.get(name, {}).get(player, {}).get('pending')) for name in (ACQUISITIONS, EXCHANGES)}
    reference = event_reference.make(player, operation, request)
    facts, rom = [], None
    if request['acquisitions'] or recorded_inventory and any(pending.values()):
        provider = getattr(runtime, 'prepared_cartridges', None)
        rom = source_rom(initial['metadata'], player, provider.rom if provider is not None else None)
        facts = decode(request['acquisitions'], initial['metadata'], initial['binding'], reference=reference, rom=rom)

    def of(kinds):
        return [fact for fact in facts if fact['kind'] in kinds]

    # 3a. Statics first, in list order, so origins and ends are known before any capture pairs: a static's own
    # capture pairs under the static id, and evidence that is neither provably the static's nor provably wild
    # is HELD (a recovery hold, kept out of acquisition settlement until reconciliation).
    held, attributions = set(), None
    if of(LIFECYCLE_KINDS):
        from server.gen1_faint_runtime import synchronize
        from server.gen1_static_lifecycle import held_blockers, stage as stage_statics
        statics = stage_statics(document, player, of(LIFECYCLE_KINDS), reference)
        held, attributions = set(statics['held']), statics['attributions']
        stage.barrier.set_blockers({**stage.barrier.document()['blockers'], **held_blockers(document)})
        synchronize(stage, document)
        records.extend(statics['records'])
        result['static_digest'] = digest(statics['records'][0]['value'])
    # 3b. Acquisition receipts, plus pending facts a fresh checkpoint may now settle.
    if of(ACQUISITION_KINDS) or pending[ACQUISITIONS] and recorded_inventory:
        merge(stage_acquisitions(runtime, stage, document, player, operation,
                                 [fact for fact in of(ACQUISITION_KINDS) if fact['fact']['key'] not in held],
                                 frame_request=request, rom=rom, attributions=attributions), 'acquisition_digest')
    # 3c. NPC exchanges migrate identities and rule halves acquisitions settled (bridge rekey, npc_trade): no ordinal,
    # no acquisition. Pending until a stable checkpoint shows the incoming mon, exactly as acquisitions are.
    if of(EXCHANGE_KINDS) or pending[EXCHANGES] and recorded_inventory:
        merge(stage_exchanges(runtime, stage, document, player, operation, of(EXCHANGE_KINDS), frame_request=request),
              'exchange_digest')
    # 3d. Ordinary evolutions: the source witness is a complete physical result, so the collector migrates at once
    # (bridge rekey, evolution) even before an overworld checkpoint.
    if of(EVOLUTION_KINDS):
        from server.gen1_evolution_runtime import stage_evolutions
        merge(stage_evolutions(runtime, stage, document, player, operation, of(EVOLUTION_KINDS), frame_request=request, rom=rom),
              'evolution_digest')
    # 3e. Wild encounters: begins, captures and ends in this batch, and either player's end deferred behind an
    # unsettled peer capture. A wild end without its capture is the no_catch Gen 3 sends after its post-battle grace
    # window (gen3_frlge_client.lua no_catch); here the capture is source-witnessed, so no grace timer is inferred.
    # The lifecycle decides through the bridge (dead zones, paired no-catch retirement); it needs both owners.
    if of(ENCOUNTER_ROWS) or ENCOUNTERS in components:
        encounter = stage_encounters(runtime, stage, document, player, operation, request, frame_request=request)
        if encounter is not None:
            merge(encounter, 'wild_encounter_digest')
    # 4. Storage compensation (boxed deliveries, PC moves) for the checkpoint this batch recorded.
    if recorded_inventory:
        from server.gen1_storage_runtime import stage as stage_storage
        storage = stage_storage(runtime, stage, document, player, operation, request)
        records.extend(storage['records'])
        for recipient in ('a', 'b'):
            commands[recipient].extend(storage['commands'][recipient])
    # 5. In-battle death delivery (handoff item 5): while this player's oldest pending command is a death
    # command and the batch shows a battle, hand it the one-instruction authority as its own
    # battle_instruction command; its ACK receipt (gen1_faint_runtime) verifies, enforces or re-issues.
    if request.get('battle'):
        from server.battle_force_authority import pending_instruction
        issued = pending_instruction(runtime, stage, document, player, frame=request['frame'] + 1, seed=operation,
                                     binding=metadata['control_binding'])
        if issued is not None:
            commands[player].append(issued)
            result['instruction_issued'] = issued['authority']['challenge']
    entry = {'sequence': request['sequence'], 'operation_id': operation, 'frame': request['frame']}
    entries[player] = entry
    result['observation_digest'] = digest(entry)
    records.append({'namespace': COMPONENT, 'key': key(player), 'value': entry})
    from server.gen1_hud_feedback import feedback_last

    commands = feedback_last(commands)
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
