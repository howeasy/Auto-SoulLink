"""Join a verified starter source to stable inventory, then stage rules/identity."""
import copy
from dataclasses import asdict
from datetime import UTC, datetime

from server import event_reference
from server.admission_context import same_admitted_context
from server.gen1_engine_bridge import allowed_starters, starter_grant
from server.gen1_engine_signal_runtime import interpret
from server.gen1_full_save import SYMBOLS
from server.gen1_initial_observation import COMPONENT as INITIAL, display_name, validate
from server.gen1_observation_provenance import semantic_receipt
from server.gen1_party_codec import PartyCodec
from server.identity_registry import IdentityContext, IdentityWitness
from server.protocol import digest
from server.protocol_journal import JournalError, _identifier
from server.save_identity import SaveIdentity
from server.state import AreaStatus, MonInfo

COMPONENT = 'gen1-starter-settlement'
SCHEMA = 'rby-starter-settlement-v2'   # v2: a clause rejection is part of the settlement record
AREA = 'oaks_lab'
KANTO_STARTERS = (1, 4, 7)   # the lab's choice on Red and Blue; Yellow's Pikachu is scripted and never rejected
REJECTION_FIELDS = {'player', 'key', 'member_id', 'reason', 'at', 'allowed', 'receipt_ref'}


def initial_component():
    return {'schema': SCHEMA, 'sources': {}, 'settled': {}, 'link_id': None, 'rejection': None}


def remember_source(document, player, entry):
    grants = [row for row in entry['transactions'] if row.get('source_id') == 'grant:starter:0']
    if not grants:
        return
    component = document['components'].setdefault(COMPONENT, initial_component())
    if len(grants) != 1 or player in component['sources']:
        raise JournalError('starter source was repeated; explicit recovery required')
    component['sources'][player] = {'engine_record': copy.deepcopy(entry), 'transaction': copy.deepcopy(grants[0])}


def context(initial, player):
    metadata = initial['metadata']
    return IdentityContext(player, 'gen1_rby', SaveIdentity(**metadata['save_identity']),
        digest(metadata['gen1_metadata']['cartridge']), initial['binding']['context_generation'],
        metadata['gen1_metadata']['physical_instance'])


def starter_flag(source):
    # The pinned source's BIT_GOT_STARTER is bit 3 in both status layouts.
    symbols = SYMBOLS['pokeyellow' if source['variant'] == 'yellow' else 'pokered']
    return bool(bytes.fromhex(source['fields']['main'])[symbols['wStatusFlags4']-symbols['wMainDataStart']] & 8)


def checked_mon(initial, source, checkpoint):
    metadata = initial['metadata']; birth = source['transaction']
    observed = validate(checkpoint, metadata, initial['binding'])
    if initial['inventory']['members'] or starter_flag(initial['observation']['source']):
        raise JournalError('starter settlement requires an observed pre-starter inventory')
    if checkpoint['frame'] < birth['after']['frame'] or checkpoint['host'] != initial['observation']['host']:
        raise JournalError('starter checkpoint predates its source or changed host')
    if not starter_flag(checkpoint['source']):
        raise JournalError('starter script has not published its completion flag')
    if observed['party_count'] != 1 or len(observed['members']) != 1 or observed['members'][0]['location'] != 'party':
        raise JournalError('starter must be the sole observed member across party and boxes')
    mon = PartyCodec(checkpoint['source']['variant']).validate_blob(bytes.fromhex(observed['members'][0]['blob_hex']))
    old = PartyCodec(checkpoint['source']['variant']).validate_blob(bytes.fromhex(birth['blob_hex']))
    if old.ot_name != bytes.fromhex(initial['observation']['source']['fields']['name']):
        raise JournalError('starter birth trainer name differs from its original save')
    if mon.key != birth['key'] or mon.ot_name != old.ot_name or mon.nickname != old.nickname or mon.hp == 0:
        raise JournalError('stable starter identity differs from the source transaction')
    # Yellow's original script writes LIGHT_BALL_GSC ($a3) after AddPartyMon.
    expected_catch_rate = 0xA3 if checkpoint['source']['variant'] == 'yellow' else old.catch_rate
    if mon.catch_rate != expected_catch_rate:
        raise JournalError('starter post-return cartridge data differs')
    return mon


def mon_info(mon):
    return MonInfo(key=mon.key, level=mon.level, species=mon.species_id, nickname=display_name(mon.nickname))


def cache_party(rules, player, mon):
    rules.party_size[player] = 1
    rules.partner_blobs[player] = [{'slot': 0, 'key': mon.key, 'species_id': mon.species_id,
                                   'level': mon.level, 'blob': mon.raw}]
    hp, attack, defense, speed, special = mon.computed_stats
    rules.cache_stats(player, mon.key, {'level': mon.level, 'maxHP': hp, 'attack': attack,
        'defense': defense, 'speed': speed, 'spAtk': special, 'spDef': special})


def settle_ready(runtime, stage, document, *, frame_origin=None):
    component = document['components'].get(COMPONENT)
    initials = document['components'].get(INITIAL, {})
    if component is None or set(initials) != {'a', 'b'}:
        return
    # Do not adopt one side of an arbitrary pre-existing game into a new run.
    if any(row['inventory']['members'] or starter_flag(row['observation']['source']) for row in initials.values()):
        raise JournalError('paired starter settlement requires two observed pre-starter saves')
    if (frame_origin is None and any(runtime.journal.pending_ids(p) for p in ('a', 'b'))) or document['active_trade']:
        raise JournalError('starter settlement cannot cross physical obligations')
    checkpoints = document['components'].get('gen1-inventory-observations', {})
    for player in ('a', 'b'):
        if player in component['settled'] or player not in component['sources'] or player not in checkpoints:
            continue
        source = component['sources'][player]; entry = checkpoints[player]
        if entry['observation']['frame'] < source['transaction']['after']['frame']:
            continue
        session = runtime.gate.sessions.get(player)
        same_context = same_admitted_context if 'frame_origin' in entry else lambda a, b: a == b
        if session is None or not same_context(session.metadata, initials[player]['metadata']):
            raise JournalError('starter settlement needs its current admitted owner')
        mon = checked_mon(initials[player], source, entry['observation'])
        partner = 'b' if player == 'a' else 'a'
        other = component['settled'].get(partner)
        current_peer = None
        if other is not None:
            peer_session = runtime.gate.sessions.get(partner)
            peer_framed = partner in checkpoints and 'frame_origin' in checkpoints[partner]
            same_peer = same_admitted_context if peer_framed else lambda a, b: a == b
            if peer_session is None or not same_peer(peer_session.metadata, initials[partner]['metadata']) or partner not in checkpoints:
                raise JournalError('starter peer lacks its current owned inventory')
            current_peer = checked_mon(initials[partner], component['sources'][partner], checkpoints[partner]['observation'])
        own_context = context(initials[player], player)
        acquisition = digest({'run_id': runtime.journal.run_id, 'player': player,
            'starter_source': source['engine_record']['operation_id']})[:32]
        witness = IdentityWitness(own_context, mon.key, mon.sha256, 1)
        acquired = stage.identities.acquire(acquisition, acquisition, witness)
        linked, rejected = starter_grant(stage.rules, player, AREA, mon_info(mon))   # the shared engine pairs the starters
        cache_party(stage.rules, player, mon)
        component['settled'][player] = {'member_id': acquired['member_id'], 'acquisition_id': acquisition,
            'inventory_entry': copy.deepcopy(entry), 'blob_hex': mon.raw.hex().upper()}
        if rejected is not None:
            # The engine applied the clauses to the pair of starters and rejected one (Gen 3 does the
            # same; Gen 1 exempts Yellow/Yellow at the adapter). The rejected starter is not usable and
            # the lab stays pending for the other player; the pair has no logical link. The burial the
            # engine booked is executed by a starter_clause retirement job (gen1_retirement_runtime
            # schedules it from the rejected player's next batch) and receipt_ref closes it here.
            if rejected['player'] not in component['settled'] or component['link_id'] is not None:
                raise JournalError('starter clause rejection does not name a settled starter')
            component['rejection'] = {'player': rejected['player'], 'key': rejected['key'],
                'member_id': component['settled'][rejected['player']]['member_id'], 'reason': rejected['reason'],
                'at': datetime.now(UTC).isoformat(),
                'allowed': allowed_starters(stage.rules, rejected['player'], AREA, KANTO_STARTERS), 'receipt_ref': None}
        if linked is not None:
            setattr(linked, partner, mon_info(current_peer))
            cache_party(stage.rules, partner, current_peer)
            members = [component['settled'][p]['member_id'] for p in ('a', 'b')]
            event = digest({'starters': members, 'run_id': runtime.journal.run_id})[:32]
            component['link_id'] = stage.identities.create_link(player, event, members)['link_id']
    document['rules'] = stage.rules.document(); document['identities'] = stage.identities.document()
    from server.gen1_runtime_state import recovery_history
    stage.barrier.set_history(recovery_history(document['rules'], document['identities'], document['active_trade'],
        document['components'].get('gen1-trade')))
    document['components']['gen1-runtime']['recovery'] = stage.barrier.document()


def rejected_starter(document, player, acquisition_id):
    """Retirement source of the clause-rejected starter (gen1_retirement_runtime cause starter_clause)."""
    component = document['components'].get(COMPONENT) or {}
    rejection = component.get('rejection')
    settled = component.get('settled', {}).get(player)
    if (rejection is None or rejection['player'] != player or settled is None
            or settled['acquisition_id'] != acquisition_id or rejection['member_id'] != settled['member_id']):
        raise JournalError('starter clause retirement lacks its settlement rejection')
    return {'acquisition_id': acquisition_id, 'key': rejection['key'], 'member_id': rejection['member_id'],
            'reason': 'starter_clause'}


def complete_rejection(document, player, receipt_ref):
    """The verified retirement image of the rejected starter closes the rejection, once."""
    rejection = document['components'][COMPONENT]['rejection']
    event_reference.validate(receipt_ref)
    if rejection is None or rejection['player'] != player or receipt_ref['player'] != player or rejection['receipt_ref'] is not None:
        raise JournalError('starter clause retirement is already complete or names another player')
    rejection['receipt_ref'] = copy.deepcopy(receipt_ref)


def rejection_prompt(document, adapter):
    """The engine's clause prompt for the rejected player, extended with the starters the engine would
    accept now. Its delivery is the item-4 HUD executor: Gen 1's durable outbox carries physical
    obligations only (lua/gen1_held_faint handles them; durable_runtime.lua revokes on any other kind),
    so the bridges drain every engine prompt today and this one is recorded, not queued."""
    rejection = document['components'][COMPONENT]['rejection']
    names = ', '.join(adapter.species_name(species) for species in rejection['allowed'])
    return {'cmd': 'gui_prompt', 'text': '[x] ' + rejection['reason'] + ' -- allowed starters: ' + names,
            'r': 255, 'g': 200, 'b': 60, 'frames': 360}


def verify_state(stage):
    document = stage.document(); component = document['components'].get(COMPONENT)
    if component is None:
        return
    if not isinstance(component, dict) or set(component) != {'schema', 'sources', 'settled', 'link_id', 'rejection'} or component['schema'] != SCHEMA:
        raise JournalError('invalid starter settlement component')
    for field in ('sources', 'settled'):
        if not isinstance(component[field], dict) or set(component[field])-{'a', 'b'}:
            raise JournalError('invalid starter participant records')
    initials = document['components'].get(INITIAL, {})
    if component['settled'] and (set(initials) != {'a', 'b'} or any(
            row['inventory']['members'] or starter_flag(row['observation']['source']) for row in initials.values())):
        raise JournalError('settled starters lack paired pre-starter enrollment')
    for player, source in component['sources'].items():
        if player not in initials or not isinstance(source, dict) or set(source) != {'engine_record', 'transaction'}:
            raise JournalError('starter source lacks its initial context')
        record = source['engine_record']; _identifier(record['operation_id'])
        if record['prior_starter'] is not None:
            from server.gen1_engine_signals import validate_signal
            before = record['prior_starter']
            if (validate_signal(before, record['payload']['variant'], initials[player]['metadata']['save_identity'])['kind'] != 'starter_begin'
                    or before['frame'] < initials[player]['observation']['frame']):
                raise JournalError('starter origin lacks its valid source call')
        pending, transactions = interpret(record['payload'], initials[player]['metadata'], record['prior_starter'])
        if pending != record['pending_starter'] or transactions != record['transactions'] or transactions.count(source['transaction']) != 1:
            raise JournalError('starter source record differs from its evidence')
        if source['transaction'].get('source_id') != 'grant:starter:0':
            raise JournalError('source is not the starter grant')
    for player, settled in component['settled'].items():
        if player not in component['sources'] or set(initials) != {'a', 'b'} or not isinstance(settled, dict) or set(settled) != {
                'member_id', 'acquisition_id', 'inventory_entry', 'blob_hex'}:
            raise JournalError('incomplete starter settlement')
        mon = checked_mon(initials[player], component['sources'][player], settled['inventory_entry']['observation'])
        from server.gen1_inventory_observation import verify_entry
        verify_entry(settled['inventory_entry'], initials[player])
        if settled['blob_hex'] != mon.raw.hex().upper():
            raise JournalError('settled starter differs from stable inventory')
        _identifier(settled['member_id']); _identifier(settled['acquisition_id'])
        expected_id = digest({'run_id': stage.identities.document()['run_id'], 'player': player,
            'starter_source': component['sources'][player]['engine_record']['operation_id']})[:32]
        if settled['acquisition_id'] != expected_id:
            raise JournalError('starter acquisition ID differs from its source')
        record = document['identities']['acquisitions'].get(player+':'+settled['acquisition_id'])
        if record is None or record['member_id'] != settled['member_id'] or record['origin']['key'] != mon.key:
            raise JournalError('starter settlement lost its logical acquisition')
        member = stage.identities.member(settled['member_id'])
        if member['history'][0]['evidence_digest'] != mon.sha256:
            raise JournalError('starter identity origin differs from its stable witness')
        event = document['identities']['events'][player+':'+settled['acquisition_id']]
        if event['request']['witness']['context'] != asdict(context(initials[player], player)):
            raise JournalError('starter logical origin belongs to another context')
    if component['link_id'] is not None:
        _identifier(component['link_id'])
        link = document['identities']['links'].get(component['link_id'])
        if set(component['settled']) != {'a', 'b'} or link is None:
            raise JournalError('starter linkage is incomplete')
        # Later native trades may migrate current membership; preserve origin.
        origin = link['history'][0]['members'] if link['history'] else link['members']
        if set(origin) != {row['member_id'] for row in component['settled'].values()}:
            raise JournalError('starter logical link origin differs')
    elif len(component['settled']) == 2 and component['rejection'] is None:
        raise JournalError('paired settled starters lack logical linkage')
    rejection = component['rejection']
    if rejection is not None:
        if (not isinstance(rejection, dict) or set(rejection) != REJECTION_FIELDS
                or rejection['player'] not in component['settled'] or component['link_id'] is not None
                or not isinstance(rejection['reason'], str) or not rejection['reason']):
            raise JournalError('invalid starter clause rejection')
        settled = component['settled'][rejection['player']]
        mon = checked_mon(initials[rejection['player']], component['sources'][rejection['player']],
                          settled['inventory_entry']['observation'])
        if rejection['member_id'] != settled['member_id'] or rejection['key'] != mon.key:
            raise JournalError('starter clause rejection names another starter')
        partner = 'b' if rejection['player'] == 'a' else 'a'
        rules = stage.rules
        if (rules.find_link(rejection['player'], mon.key) is not None or mon.key in rules.party_keys[rejection['player']]
                or AREA not in rules.retry_areas[rejection['player']]
                or rules.area_states.get(AREA) != (AreaStatus.PENDING_A if rejection['player'] == 'a' else AreaStatus.PENDING_B)   # waiting on the rejected player
                or set(rules.pending_captures.get(AREA, {})) != {partner}
                or rejection['allowed'] != allowed_starters(rules, rejection['player'], AREA, KANTO_STARTERS)):
            raise JournalError('starter clause rejection differs from the rule state')
        # The engine booked the burial; the retirement job's verified image reports it exactly once.
        if rejection['receipt_ref'] is not None:
            event_reference.validate(rejection['receipt_ref'])
        if (mon.key in rules.pending_memorials[rejection['player']]) != (rejection['receipt_ref'] is None):
            raise JournalError('starter clause rejection differs from its memorial obligation')


def verify_journal(journal, stage):
    component = stage.document()['components'].get(COMPONENT)
    if component is None:
        return
    for player, source in component['sources'].items():
        record = source['engine_record']
        receipt = semantic_receipt(journal, player, record, 'engine_signals')
        if receipt is None or receipt.result != {'ack': 'ACK', 'engine_evidence_digest': digest(record), 'ordinary_execution': False}:
            raise JournalError('starter source lacks its committed engine event')
    from server.gen1_inventory_observation import result
    for player, settled in component['settled'].items():
        entry = settled['inventory_entry']; receipt = semantic_receipt(journal, player, entry, 'inventory_observation')
        if receipt is None or receipt.result != result(entry):
            raise JournalError('starter settlement lacks its committed inventory event')
    rejection = component['rejection']
    if rejection is not None and rejection['receipt_ref'] is not None:
        request = event_reference.resolve(journal, rejection['receipt_ref']).request
        command = journal.command(rejection['player'], request.get('command_id', ''))
        if (request.get('event') != 'command_ack' or request.get('outcome') != 'ACK' or command['outcome'] != 'ACK'
                or command['body'].get('cmd') != 'acquisition_retire' or command['body'].get('key') != rejection['key']):
            raise JournalError('starter clause rejection lacks its verified retirement receipt')
