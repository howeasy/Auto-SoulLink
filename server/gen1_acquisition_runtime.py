"""Durable acquisition settlement: source receipts -> stable identity, pairing, ordinals.

A capture or scripted-grant receipt is decoded by its own module into a fact. The
fact stays PENDING until a stable inventory checkpoint at or after its return frame
shows the delivered key where the source said it went; only then is a logical
identity acquired, an ordinal assigned and a rule staged. Receipts that never
stabilize, and purchases that never produced a receipt, therefore never consume an
ordinal. Every pending and settled record keeps an exact reference to its raw
receipt inside its committed event so restore re-decodes evidence, not facts.

`stage_acquisitions` mutates only the detached stage/document and publishes nothing;
root folds it into the compound frame commit. `record` is the standalone handler.
"""
import copy
import hashlib
from functools import lru_cache

from server import event_reference
from server.adapters.gen1_rby import _MAP_ID_TO_AREA
from server.admission_context import same_admitted_context
from server.gen1_initial_observation import COMPONENT as INITIAL, display_name, inventory
from server.gen1_party_codec import PartyCodec
from server.gen1_semantic_events import capture_event
from server.gen1_starter_settlement import context as identity_context
from server.identity_registry import IdentityWitness
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier
from server.state import DEATH_COMMANDS, LinkStatus, MonInfo

COMPONENT = 'gen1-acquisition-settlement'
ORDINALS = 'gen1-acquisition-ordinals'
EVENT = 'acquisition_observation'
SCHEMA = 'rby-acquisition-observation-v1'
INVENTORY = 'gen1-inventory-observations'
MAX_RECEIPTS = 16
ENTRY_FIELDS = {'sequence', 'operation_id', 'previous_operation_id', 'pending', 'settled'}
CONSTRAINT_REASON = 'Acquisition requires verified physical constraint or retirement settlement'
RETIREMENT_REASON = 'Yellow-only scripted grant has no counterpart in this mixed-title run'


def constraint_id(player, acquisition_id):
    return digest({'component': COMPONENT, 'player': player, 'acquisition': acquisition_id})[:32]


@lru_cache(maxsize=1)
def _canonical_cartridges():
    from server.gen1_admission import cartridge_metadata, clean_profiles
    from server.gen1_cartridge_profiles import companion_profiles

    return tuple(cartridge_metadata(profile) for profile in (
        *clean_profiles().values(), *companion_profiles().values()))


def source_rom(metadata, player, provider=None):
    """A changed admitted cartridge never falls back to clean species operands."""
    cartridge = metadata['gen1_metadata']['cartridge']
    if provider is None:
        if cartridge not in _canonical_cartridges():
            raise JournalError('admitted acquisition ROM bytes are required for randomized content')
        return None
    rom = provider(player)
    if not isinstance(rom, bytes) or hashlib.sha1(rom).hexdigest() != cartridge['final_rom_sha1']:
        raise JournalError('acquisition ROM differs from the exact admitted cartridge')
    return rom


def record_key(player):
    return digest({'component': COMPONENT, 'player': player})[:32]


def result_for(entry):
    return {'ack': 'ACK', 'acquisition_digest': digest(entry), 'ordinary_execution': False}


def _typed(request):
    if set(request) != {'event', 'payload'} or request['event'] != EVENT or not isinstance(request['payload'], dict):
        raise JournalError('typed acquisition observation required')
    payload = request['payload']
    if set(payload) != {'schema', 'variant', 'context_generation', 'final_sha1', 'sequence', 'receipts'} or payload['schema'] != SCHEMA:
        raise JournalError('complete acquisition observation required')
    if not isinstance(payload['receipts'], list) or len(payload['receipts']) > MAX_RECEIPTS:
        raise JournalError('bounded acquisition receipt list required')
    for row in payload['receipts']:
        if not isinstance(row, dict) or set(row) != {'kind', 'receipt'} or row['kind'] not in ('capture', 'grant'):
            raise JournalError('typed acquisition receipt required')
    return payload


def decode_receipts(receipts, metadata, binding, *, reference, rom_bytes=None, rom=None):
    """Decode raw capture/grant receipts with the admitted context; each fact keeps its source reference.

    A thin caller of `gen1_source_receipts.decode`: indices are positions in `receipts` as given, so
    pass the whole raw list (or `[raw[i]]` to re-decode one row against its stored reference).
    """
    from server.gen1_source_receipts import ACQUISITION_KINDS, decode

    return decode(receipts, metadata, binding, reference=reference, rom=rom, rom_bytes=rom_bytes, kinds=ACQUISITION_KINDS)


def receipts_of(request):
    """Raw receipt list inside a standalone event or a compound frame bundle."""
    if request.get('event') == EVENT:
        return _typed(request)['receipts']
    if request.get('event') == 'frame_complete':
        rows = request.get('bundle', {}).get('acquisitions')
        return rows or []
    if request.get('event') == 'observation':  # free-run batch (P10)
        return request.get('acquisitions') or []
    raise JournalError('acquisition source event is neither standalone nor a compound frame')


def area_of(adapter, fact, attributions=None):
    """The rule area a fact pairs under; `attributions` (capture key -> static id) names a static's own capture."""
    if fact['kind'] == 'capture' and attributions and fact['key'] in attributions:
        # A static's own capture pairs with the partner's same static, never with a wild catch on that map.
        return attributions[fact['key']]
    area = _MAP_ID_TO_AREA.get(fact['map_id'])
    if fact['kind'] == 'scripted_grant':
        # A grant pairs by its title-neutral source; an unmapped grant map must not
        # collide with any encounter area, so it takes its pairing id as the rule area.
        return adapter.gift_link_area(area) if area is not None else fact['pairing_id']
    if area is None:
        raise JournalError('capture map has no area mapping; reconciliation required')
    return area


def pairing_of(fact, area):
    if fact['kind'] == 'scripted_grant' and fact['group'] == 'game_corner_purchase':
        return 'grant:game_corner_purchase'
    if fact['kind'] == 'scripted_grant':
        return fact['pairing_id']
    # ponytail: verify_state re-derives pairing ids without the static attributions, so a capture's
    # ordinal id stays its map area even when its rule area is a static; the static-origins row is the proof.
    return 'capture:' + _MAP_ID_TO_AREA[fact['map_id']]


def _mon_info(codec, fact, blob):
    if fact['location']['kind'] == 'party':
        mon = codec.validate_blob(blob)
        return MonInfo(key=mon.key, level=mon.level, species=mon.species_id, nickname=display_name(mon.nickname)), mon.sha256
    species = codec.profile['species'][str(blob[0])]['dex']
    return MonInfo(key=fact['key'], level=blob[3], species=species, nickname=display_name(blob[44:55])), hashlib.sha256(blob).hexdigest()


def _stable_member(document, player, fact, initial):
    """The delivered mon as the latest stable checkpoint shows it, or None if not yet stable."""
    checkpoint = document['components'].get(INVENTORY, {}).get(player)
    if checkpoint is None or checkpoint['observation']['frame'] < fact.get('settlement_frame',fact['return_frame']):
        return None
    if checkpoint['observation']['host'] != initial['observation']['host']:
        raise JournalError('acquisition checkpoint changed host; reconciliation required')
    roster = inventory(checkpoint['observation']['source'], initial['metadata']['save_identity'])
    rows = [row for row in roster['members'] if row['key'] == fact['key']]
    if not rows:
        raise JournalError('stable inventory after delivery lacks the delivered key; reconciliation required')
    row = rows[0]
    delivered = bytes.fromhex(fact['blob_hex'])
    if row['location'] != fact['location']['kind']:
        raise JournalError('acquisition moved containers before its physical disposition was settled')
    if row['location']=='box' and row['box']!=fact['location']['box']:
        raise JournalError('acquisition moved boxes before its physical disposition was settled')
    if row['location'] == 'party':
        blob = bytes.fromhex(row['blob_hex'])
        same = blob[0] == delivered[0] and blob[33] == delivered[33] and blob[12:14] == delivered[12:14] and blob[44:55] == delivered[44:55]
    else:
        blob = bytes.fromhex(row['box_blob_hex'])
        same = blob[0] == delivered[0] and blob[3] == delivered[3] and blob[12:14] == delivered[12:14] and blob[33:44] == delivered[33:44]
    if not same:
        raise JournalError('stable inventory shows a different mon under the delivered key')
    return {'operation_id': checkpoint['operation_id'], 'location': row['location'], 'blob': blob}


def stage_acquisitions(runtime, stage, document, player, operation, facts, frame_origin=None, *, frame_request=None, rom=None, attributions=None):
    """Stage new facts as pending, then settle every pending fact a stable checkpoint proves.

    Returns entry/result/commands/records for the caller's atomic commit. Only the
    detached stage/document change. `facts` come from decode_receipts.
    """
    if not isinstance(facts,list) or len(facts)>MAX_RECEIPTS:
        raise JournalError('bounded decoded acquisition facts required')
    initial = document['components'].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError('acquisition settlement requires initial enrollment')
    session = runtime.gate.sessions.get(player)
    if session is None or not same_admitted_context(session.metadata, initial['metadata']):
        raise JournalError('acquisition settlement needs its current admitted owner')
    if document['active_trade']:
        raise JournalError('native trade owns acquisition settlement until verified closure')
    if frame_origin is not None:
        origin = event_reference.validate(frame_origin)
        if origin['player'] != player or origin['operation_id'] != operation:
            raise JournalError('acquisition frame origin differs from the staged operation')
        from server.gen1_observation_provenance import stage_origin

        stage_origin(document, player, operation,
                     {'event':EVENT,'payload':{'receipts':receipts_of(frame_request)}},
                     frame_origin=frame_origin, frame_request=frame_request)
    elif player in document['components'].get('gen1-frame-progress', {}):
        raise JournalError('frame-accounted acquisitions require a compound frame origin')
    entries = document['components'].setdefault(COMPONENT, {})
    old = entries.get(player)
    entry = {'sequence': (old['sequence'] + 1) if old else 1, 'operation_id': operation,
             'previous_operation_id': old['operation_id'] if old else initial['operation_id'],
             'pending': copy.deepcopy(old['pending']) if old else [], 'settled': copy.deepcopy(old['settled']) if old else []}
    if frame_origin is not None:
        entry['frame_origin'] = copy.deepcopy(frame_origin)
    known = {row['fact']['key'] for row in entry['pending'] + entry['settled']}
    for row in facts:
        if set(row) != {'kind', 'fact', 'source_ref'} or row['fact']['key'] in known:
            raise JournalError('acquisition fact is malformed or repeats a delivered key')
        reference = row['source_ref']
        if not isinstance(reference,dict) or set(reference)!={'event','index'} or type(reference['index']) is not int or reference['index']<0:
            raise JournalError('acquisition fact lacks its exact source row')
        current_ref = event_reference.make(player, operation, frame_request) if frame_request is not None else None
        source_request = frame_request if reference['event']==current_ref else event_reference.resolve(runtime.journal, reference['event']).request
        raw = receipts_of(source_request)
        if reference['index'] >= len(raw):
            raise JournalError('acquisition source index leaves its receipt list')
        checked = decode_receipts([raw[reference['index']]], initial['metadata'], initial['binding'], reference=reference['event'],rom=rom)[0]
        if checked['kind'] != row['kind'] or checked['fact'] != row['fact']:
            raise JournalError('acquisition staging refuses caller-forged decoded facts')
        known.add(row['fact']['key'])
        entry['pending'].append(copy.deepcopy(row))
    codec = PartyCodec(initial['metadata']['gen1_metadata']['cartridge']['variant'])
    own_context = identity_context(initial, player)
    still_pending = []
    for row in entry['pending']:
        fact = row['fact']
        stable = _stable_member(document, player, fact, initial)
        if stable is None:
            still_pending.append(row)
            continue
        mon, evidence = _mon_info(codec, fact, stable['blob'])
        acquisition_id = digest({'run_id': runtime.journal.run_id, 'player': player, 'acquisition': row['source_ref']})[:32]
        # One identity event per acquisition transaction, as the starter settlement does.
        acquired = stage.identities.acquire(acquisition_id, acquisition_id, IdentityWitness(own_context, fact['key'], evidence, 1))
        area = area_of(stage.rules.adapter, fact, attributions)
        pairing = pairing_of(fact, area)
        # Ordinals exist only once a delivery has stabilized; pending receipts consume none.
        counts = document['components'].setdefault(ORDINALS, {}).setdefault(pairing, {'a': 0, 'b': 0})
        counts[player] += 1
        if fact['kind'] == 'scripted_grant' and fact['group'] == 'game_corner_purchase':
            # Repeatable source: each purchase pairs under its own ordinal, never the shared prize room.
            area = f'{pairing}#{counts[player]}'
        settled = {'kind': row['kind'], 'source_ref': row['source_ref'], 'fact': fact, 'acquisition_id': acquisition_id,
                   'member_id': acquired['member_id'], 'inventory_operation': stable['operation_id'], 'area': area,
                   'pairing_id': pairing, 'ordinal': counts[player], 'pairing_key': f'{pairing}#{counts[player]}',
                   'rule': None, 'violation': None, 'link_id': None}
        linked = None
        if fact['kind']=='scripted_grant' and fact['yellow_only'] and runtime.contract['players']['a']['variant'] != runtime.contract['players']['b']['variant']:
            settled['rule'] = 'retirement_required'
            settled['retirement_reason'] = RETIREMENT_REASON
        else:
            exempt = fact['kind'] == 'scripted_grant'
            outcome = _decide_through_engine(stage.rules, player, area, mon, stable, exempt=exempt)
            settled['rule'] = 'exempt_grant' if exempt else 'clause_checked'
            settled['violation'] = outcome['violation']
            linked = outcome['linked']
        if settled['rule'] == 'retirement_required' or settled['violation'] is not None:
            blockers = stage.barrier.document()['blockers']
            blockers[constraint_id(player,acquisition_id)] = CONSTRAINT_REASON
            stage.barrier.set_blockers(blockers)
            stage.rules.party_keys[player].discard(fact['key'])
            if settled['violation'] is not None:
                for p, pending in stage.rules.pending_captures.get(area,{}).items():
                    stage.rules.party_keys[p].discard(pending.key)
        if linked is not None:
            members = _link_members(entries, player, linked, acquired['member_id'], stage.identities,
                                    document['components'][INITIAL])
            settled['link_id'] = stage.identities.create_link(player, digest({'link': settled['pairing_key'], 'members': members})[:32], members)['link_id']
        entry['settled'].append(settled)
    entry['pending'] = still_pending
    entries[player] = entry
    checkpoint = document['components'].get(INVENTORY,{}).get(player)
    if checkpoint is not None:
        roster = inventory(checkpoint['observation']['source'], initial['metadata']['save_identity'])
        party = [codec.validate_blob(bytes.fromhex(mon['blob_hex'])) for mon in roster['members'] if mon['location']=='party']
        stage.rules.party_size[player] = len(party)
        stage.rules.partner_blobs[player] = [{'slot':index,'key':mon.key,'species_id':mon.species_id,
            'level':mon.level,'blob':mon.raw} for index,mon in enumerate(party)]
    document['rules'] = stage.rules.document()
    document['identities'] = stage.identities.document()
    from server.gen1_runtime_state import recovery_history
    stage.barrier.set_history(recovery_history(document['rules'], document['identities'], document['active_trade'],
        document['components'].get('gen1-trade')))
    document['components']['gen1-runtime']['recovery'] = stage.barrier.document()
    from server.gen1_retirement_runtime import schedule as schedule_retirement
    commands, extra_records = ({'a': [], 'b': []}, [])
    if frame_request is not None:
        commands, extra_records = schedule_retirement(document,player,
            {'player':player,'operation_id':operation,'message':frame_request})
    return {'entry': entry, 'result': result_for(entry), 'commands': commands,
            'records': [{'namespace': COMPONENT, 'key': record_key(player), 'value': entry}, *extra_records]}


def _decide_through_engine(rules, player, area, mon, stable, *, exempt):
    """The shared rule engine decides pending/link/violation exactly as it does for Gen 3
    (SoulLinkState._handle_capture). Three RBY adapter policies stay around it:
    usability is published only by the proved physical disposition (the party mask is
    restored, as before), ball activation comes only from the bag_received engine signal
    (the flag is restored), and physical effects are executed by the storage and memorial
    runtimes from the rules state, so the engine's queued commands are drained here."""
    partner = "b" if player == "a" else "a"
    # area_of already namespaced grants (gift_<area> or the pairing id), so the engine gets gift=False and
    # therefore keeps the id as given; a real gift area still maps through _is_gift_capture unchanged.
    peer = rules.pending_captures.get(area, {}).get(partner)
    violation = None
    if peer is not None and not rules.adapter.is_fixed_species_gift(area):
        halves = {player: mon, partner: peer}
        found = rules._check_link_violation(halves["a"], halves["b"])
        if found is not None:
            violation = list(found)
    masks = copy.deepcopy(rules.party_keys)
    activated = dict(rules.pokeballs_obtained)
    own = rules.handle_event(player, capture_event(key=mon.key, area_id=area, species_id=mon.species, level=mon.level,
                                                   nickname=mon.nickname or "", gift=False,
                                                   in_box=stable["location"] == "box"))
    # handle_event returns the caller's own queue (state.py:403-411), so the captured key's death command
    # is read there, never from queued_commands[player].
    if violation is None and any(c.get("cmd") in DEATH_COMMANDS and c.get("key") == mon.key for c in own):
        # The engine's own pre-check rejects a single half before it pends (the family already sits in an
        # alive link or a pending capture elsewhere, _handle_capture): the death command for the captured
        # key is its universal rejection signal, and the consequence is the pair path's (hold, retry area,
        # memorial obligation kept); it never reaches _check_link_violation, so the text is a stable one.
        violation = [f"Species clause: {rules.adapter.species_name(mon.species)} family already held", ""]
    rules.queued_commands = {"a": [], "b": []}
    rules.party_keys = masks
    rules.pokeballs_obtained = activated
    linked = rules.find_link(player, mon.key)
    if linked is not None and linked.status != LinkStatus.ALIVE:
        linked = None
    return {"linked": linked, "violation": violation}


def _link_members(entries, player, link, own_member_id, identities, initials):
    """Logical member ids [a, b] for a just-formed rule link; the peer settled earlier."""
    partner = 'b' if player == 'a' else 'a'
    peer_key = getattr(link, partner).key
    peer_member = identities.resolve(identity_context(initials[partner],partner),peer_key)
    rows = [row for row in entries.get(partner, {}).get('settled', []) if row['member_id'] == peer_member]
    if peer_member is None or len(rows)!=1:
        raise JournalError('linked peer lacks its settled acquisition identity')
    return [own_member_id, peer_member] if player == 'a' else [peer_member, own_member_id]


def record(runtime, player, operation, request):
    previous = runtime.journal.event(player, operation, request)
    if previous is not None:
        return previous.result
    payload = _typed(request)
    stage = runtime.state()
    document = stage.document()
    initial = document['components'].get(INITIAL, {}).get(player)
    if initial is None:
        raise JournalError('acquisition settlement requires initial enrollment')
    metadata = runtime.gate.sessions[player].metadata
    old = document['components'].get(COMPONENT, {}).get(player)
    if payload['sequence'] != ((old['sequence'] + 1) if old else 1):
        raise JournalError('acquisition observation sequence skipped or repeated')
    cartridge = metadata['gen1_metadata']['cartridge']
    if (payload['variant'] != cartridge['variant'] or payload['final_sha1'] != cartridge['final_rom_sha1']
            or payload['context_generation'] != initial['binding']['context_generation']):
        raise JournalError('acquisition observation differs from admitted cartridge/context')
    reference = event_reference.make(player, operation, request)
    provider = getattr(runtime, 'prepared_cartridges', None)
    rom = source_rom(initial['metadata'], player, provider.rom if provider is not None else None)
    facts = decode_receipts(payload['receipts'], initial['metadata'], initial['binding'], reference=reference,rom=rom)
    staged = stage_acquisitions(runtime, stage, document, player, operation, facts,frame_request=request,rom=rom)
    return runtime.journal.commit(player, operation, request, expected_revision=stage.journal_revision, state=document,
        commands=staged['commands'], result=staged['result'], records=staged['records']).result


def verify_state(stage):
    document = stage.document()
    entries = document['components'].get(COMPONENT, {})
    ordinals = document['components'].get(ORDINALS, {})
    if not isinstance(entries, dict) or set(entries) - {'a', 'b'} or not isinstance(ordinals, dict):
        raise JournalError('invalid acquisition settlement component')
    counted = {}
    for player, entry in entries.items():
        initial = document['components'].get(INITIAL, {}).get(player)
        if initial is None or not isinstance(entry, dict) or not set(entry) >= ENTRY_FIELDS or set(entry) - ENTRY_FIELDS - {'frame_origin'}:
            raise JournalError('incomplete acquisition entry')
        _identifier(entry['operation_id'])
        _identifier(entry['previous_operation_id'])
        if type(entry['sequence']) is not int or entry['sequence'] < 1:
            raise JournalError('invalid acquisition sequence')
        if 'frame_origin' in entry:
            origin=event_reference.validate(entry['frame_origin'])
            if origin['player']!=player or origin['operation_id']!=entry['operation_id']:
                raise JournalError('acquisition frame origin differs from its current owner')
        if not isinstance(entry['pending'],list) or not isinstance(entry['settled'],list):
            raise JournalError('ordered pending and settled acquisitions required')
        keys = set()
        for row in entry['pending']:
            if set(row) != {'kind', 'fact', 'source_ref'} or row['fact']['key'] in keys:
                raise JournalError('invalid pending acquisition')
            event_reference.validate(row['source_ref']['event'])
            if type(row['source_ref']['index']) is not int or not 0<=row['source_ref']['index']<MAX_RECEIPTS:
                raise JournalError('invalid acquisition source index')
            keys.add(row['fact']['key'])
        for row in entry['settled']:
            if set(row) - {'retirement_reason'} != {'kind', 'source_ref', 'fact', 'acquisition_id', 'member_id', 'inventory_operation', 'area', 'pairing_id',
                            'ordinal', 'pairing_key', 'rule', 'violation', 'link_id'} or row['fact']['key'] in keys:
                raise JournalError('invalid settled acquisition')
            keys.add(row['fact']['key'])
            event_reference.validate(row['source_ref']['event'])
            for field in ('acquisition_id', 'member_id', 'inventory_operation'):
                _identifier(row[field])
            if type(row['source_ref']['index']) is not int or not 0<=row['source_ref']['index']<MAX_RECEIPTS:
                raise JournalError('invalid acquisition source index')
            record = document['identities']['acquisitions'].get(player + ':' + row['acquisition_id'])
            if record is None or record['member_id'] != row['member_id'] or record['origin']['key'] != row['fact']['key']:
                raise JournalError('settled acquisition lost its logical identity')
            if row['pairing_key'] != f"{row['pairing_id']}#{row['ordinal']}":
                raise JournalError('acquisition pairing key differs from its ordinal')
            counted.setdefault(row['pairing_id'], {'a': 0, 'b': 0})[player] += 1
            if (type(row['ordinal']) is not int or row['ordinal']!=counted[row['pairing_id']][player]
                    or row['pairing_id']!=pairing_of(row['fact'],area_of(stage.rules.adapter,row['fact']))):
                raise JournalError('acquisition ordinal is not its successful-purchase order')
            if row['rule'] not in ('exempt_grant', 'clause_checked', 'retirement_required'):
                raise JournalError('unknown acquisition rule outcome')
            if row['rule']=='retirement_required' and (row.get('retirement_reason')!=RETIREMENT_REASON or row['link_id'] is not None):
                raise JournalError('Yellow-only retirement lost its permanent physical obligation')
            if (row['rule'] == 'retirement_required' or row['violation'] is not None) and row['fact']['key'] in stage.rules.party_keys[player]:
                raise JournalError('constrained acquisition remains enabled as a usable party member')
            if row['link_id'] is not None and row['link_id'] not in document['identities']['links']:
                raise JournalError('settled acquisition names an unknown link')
    for pairing, counts in ordinals.items():
        if counted.get(pairing, {'a': 0, 'b': 0}) != counts:
            raise JournalError('acquisition ordinals differ from settled history')
    if set(counted) - set(ordinals):
        raise JournalError('settled acquisitions lack their ordinal record')
    from server.gen1_retirement_runtime import (
        completed as retired,
        verify_state as verify_retirements,
    )
    verify_retirements(stage)
    expected_holds={constraint_id(player,row['acquisition_id']):CONSTRAINT_REASON
        for player,entry in entries.items() for row in entry['settled']
        if (row['rule'] == 'retirement_required' and not retired(document,player,row['acquisition_id']))
        or row['violation'] is not None}
    actual={key:reason for key,reason in stage.barrier.document()['blockers'].items() if reason==CONSTRAINT_REASON}
    if expected_holds!=actual:
        raise JournalError('acquisition physical constraints lost their recovery holds')


def verify_journal(journal, stage, *, rom_provider=None):
    document = stage.document()
    from server.gen1_retirement_runtime import verify_journal as verify_retirements
    verify_retirements(journal,stage)
    entries = document['components'].get(COMPONENT, {})
    for player in ('a', 'b'):
        stored = journal.record(COMPONENT, record_key(player))
        entry = entries.get(player)
        if (stored is None) != (entry is None) or stored is not None and stored.value != entry:
            raise JournalError('acquisition component differs from its atomic journal record')
        if entry is None:
            continue
        initial = document['components'][INITIAL][player]
        rom = source_rom(initial['metadata'], player, rom_provider)
        current = journal.event_snapshot(player,entry['operation_id'])
        if current is None or current.revision!=stored.revision:
            raise JournalError('acquisition current entry lost its exact committed event/revision')
        if entry.get('frame_origin') is not None:
            if event_reference.resolve(journal,entry['frame_origin'])!=current or current.request.get('event')!='frame_complete':
                raise JournalError('acquisition current frame origin differs')
            if current.result.get('acquisition_digest')!=digest(entry) or current.result.get('observations_settled') is not True:
                raise JournalError('acquisition current frame result differs from its entry')
        elif current.request.get('event')=='observation':
            if current.result.get('acquisition_digest')!=digest(entry):
                raise JournalError('acquisition current observation result differs from its entry')
        elif current.request.get('event')!=EVENT or current.result!=result_for(entry):
            raise JournalError('acquisition current standalone result differs')
        else:
            payload=_typed(current.request)
            cartridge=initial['metadata']['gen1_metadata']['cartridge']
            if (payload['sequence']!=entry['sequence'] or payload['variant']!=cartridge['variant']
                    or payload['final_sha1']!=cartridge['final_rom_sha1']
                    or payload['context_generation']!=initial['binding']['context_generation']):
                raise JournalError('current acquisition event differs from its admitted sequence/context')
        for row in entry['pending'] + entry['settled']:
            reference = row['source_ref']
            snapshot = event_reference.resolve(journal, reference['event'])
            receipts = receipts_of(snapshot.request)
            if (reference['event']['player']!=player or type(reference['index']) is not int
                    or not 0 <= reference['index'] < len(receipts) or snapshot.revision>stored.revision):
                raise JournalError('acquisition source reference leaves its receipt list')
            # Re-decode the authoritative raw receipt; the stored fact is never trusted on its own.
            decoded = decode_receipts([receipts[reference['index']]], initial['metadata'], initial['binding'], reference=reference['event'],rom=rom)[0]
            if decoded['kind'] != row['kind'] or decoded['fact'] != row['fact']:
                raise JournalError('acquisition fact differs from its authoritative receipt')
            if row in entry['settled']:
                stable_event=journal.event_snapshot(player,row['inventory_operation'])
                if stable_event is None or not snapshot.revision<=stable_event.revision<=stored.revision:
                    raise JournalError('settled acquisition lost its stable inventory event')
                if stable_event.request.get('event')=='frame_complete':
                    observed=stable_event.request.get('bundle',{}).get('inventory')
                elif stable_event.request.get('event')=='inventory_observation':
                    observed=stable_event.request.get('payload',{}).get('observation')
                elif stable_event.request.get('event')=='observation':
                    observed=stable_event.request.get('inventory')
                else:
                    observed=None
                from server.gen1_initial_observation import validate

                validate(observed,initial['metadata'],initial['binding'])
                view={'components':{INVENTORY:{player:{'operation_id':row['inventory_operation'],'observation':observed}}}}
                stable=_stable_member(view,player,row['fact'],initial)
                if stable is None:
                    raise JournalError('settled acquisition inventory predates delivery/payment')
                witness=document['identities']['events'].get(player+':'+row['acquisition_id'],{}).get('request',{}).get('witness',{})
                if witness.get('evidence_digest')!=hashlib.sha256(stable['blob']).hexdigest():
                    raise JournalError('acquisition identity differs from its stable physical witness')
