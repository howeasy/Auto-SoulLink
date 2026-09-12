import copy
import secrets
from itertools import product

import pytest

from server.gen1_inventory_observation import COMPONENT, record_key
from server.gen1_inventory_transition import transition
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_full_save import SYMBOLS
from server.gen1_party_codec import PartyCodec
from server.protocol_journal import JournalError
from tests.unit.test_gen1_initial_observation import admit, observation, send, source
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_party_codec import make_blob

SAVE = {'ot_id': '0000', 'trainer_name': 'SAME'}


def faint(point):
    point = copy.deepcopy(point)
    party = bytearray.fromhex(point['fields']['party'])
    party[9:11] = b'\0\0'
    point['fields']['party'] = party.hex().upper()
    return point


def deliver(runtime, player, owner, payload, operation=None):
    session = runtime.gate.sessions[player]
    return runtime.process({'protocol': runtime.protocol, 'player': player, 'session_id': session.session_id,
        'admission_epoch': runtime.gate.epoch, 'seq': session.last_seq+1, 'event': 'inventory_observation',
        'operation_id': operation or secrets.token_hex(16), 'payload': payload}, owner)


def advance(initial, previous, sequence=1):
    point = copy.deepcopy(initial)
    point['frame'] += sequence
    point['source'] = faint(point['source'])
    return {'sequence': sequence, 'previous_operation_id': previous, 'observation': point}


@pytest.mark.parametrize('variants', list(product(('red', 'blue', 'yellow'), repeat=2)))
def test_temporal_evidence_is_atomic_ordered_replayable_and_does_not_grant_gameplay(tmp_path, variants):
    runtime = create_runtime(tmp_path, contract(*variants))
    try:
        for player in ('a', 'b'):
            owner = admit(runtime, player)
            initial = observation(runtime, player, occupied=True)
            first = secrets.token_hex(16)
            send(runtime, player, owner, initial, first)
            operation = secrets.token_hex(16)
            payload = advance(initial, first)
            deliver(runtime, player, owner, payload, operation)
            snapshot = runtime.journal.snapshot()
            deliver(runtime, player, owner, payload, operation)
            assert runtime.journal.snapshot() == snapshot
            entry = runtime.state().document()['components'][COMPONENT][player]
            assert len(entry['transition']['party_hp_zero']) == 1
            assert runtime.journal.record(COMPONENT, record_key(player)).value == entry
            second = advance(initial, operation, 2)
            deliver(runtime, player, owner, second)
            entry = runtime.state().document()['components'][COMPONENT][player]
            assert entry['sequence'] == 2 and entry['transition']['party_hp_zero'] == []
            assert len(runtime.journal.record_history(COMPONENT, record_key(player))) == 2
        state = runtime.state().document()
        assert not state['identities']['members'] and not state['rules']['core']['links']
        assert runtime.state().barrier.ticket() is None
        assert not runtime.journal.pending_ids('a') and not runtime.journal.pending_ids('b')
    finally:
        runtime.close()
    reopened = open_runtime(tmp_path)
    try:
        assert reopened.state().document()['components'][COMPONENT] == state['components'][COMPONENT]
    finally:
        reopened.close()


@pytest.mark.parametrize('fault', ['sequence', 'bool_sequence', 'predecessor', 'frame', 'rewind', 'context',
    'host', 'variant', 'identity', 'duplicate', 'extra', 'missing'])
def test_invalid_temporal_evidence_commits_nothing(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        owner = admit(runtime, 'a'); initial = observation(runtime, 'a', occupied=True)
        first = secrets.token_hex(16); send(runtime, 'a', owner, initial, first)
        payload = advance(initial, first)
        point = payload['observation']
        if fault == 'sequence': payload['sequence'] = 2
        elif fault == 'bool_sequence': payload['sequence'] = True
        elif fault == 'predecessor': payload['previous_operation_id'] = 'f'*32
        elif fault == 'frame': point['frame'] = 100
        elif fault == 'rewind': point['frame'] = 99
        elif fault == 'context': point['context_generation'] = 'f'*32
        elif fault == 'host': point['host']['process_id'] += 1
        elif fault == 'variant': point['source']['variant'] = 'red'
        elif fault == 'identity': point['source']['fields']['name'] = '9184835000000000000000'
        elif fault == 'extra': payload['grant'] = 'starter'
        elif fault == 'missing': del point['source']
        else:
            raw = bytearray.fromhex(point['source']['fields']['party'])
            raw[0:4] = bytes((2, raw[8], raw[8], 255))
            raw[52:96] = raw[8:52]; raw[283:294] = raw[272:283]; raw[349:360] = raw[338:349]
            point['source']['fields']['party'] = raw.hex().upper()
        before = runtime.journal.snapshot()
        with pytest.raises((JournalError, ValueError)):
            deliver(runtime, 'a', owner, payload)
        assert runtime.journal.snapshot() == before
        assert runtime.journal.record(COMPONENT, record_key('a')) is None
    finally:
        runtime.close()


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_box_movement_is_not_a_capture_or_faint(variant):
    before = source(variant, occupied=True); after = copy.deepcopy(before)
    party = bytes.fromhex(before['fields']['party']); box = bytearray(1122)
    box[:3] = bytes((1, party[8], 255)); box[22:55] = party[8:41]
    box[682:693] = party[272:283]; box[902:913] = party[338:349]
    after['fields']['box'] = box.hex().upper()
    after['fields']['party'] = (b'\0\xff'+b'\0'*402).hex().upper()
    delta = transition(before, after, SAVE)
    assert not delta['added'] and not delta['removed'] and not delta['party_hp_zero']
    assert delta['movements'][0]['after'] == {'location': 'box', 'box': 0, 'slot': 0}
    reverse = transition(after, before, SAVE)
    assert not reverse['added'] and not reverse['removed'] and not reverse['party_hp_zero']


@pytest.mark.parametrize('fault', ['delta', 'before', 'sequence', 'orphan'])
def test_stopped_state_restore_revalidates_temporal_evidence(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        owner = admit(runtime, 'a'); initial = observation(runtime, 'a', occupied=True)
        first = secrets.token_hex(16); send(runtime, 'a', owner, initial, first)
        deliver(runtime, 'a', owner, advance(initial, first))
        state = runtime.state().document(); entry = state['components'][COMPONENT]['a']
        if fault == 'delta': entry['transition']['party_hp_zero'] = []
        elif fault == 'before': entry['before']['frame'] -= 1
        elif fault == 'sequence': entry['sequence'] = True
        else: del state['components']['gen1-initial-observations']
        with pytest.raises(JournalError):
            Gen1RuntimeState.restore(state, data_dir=tmp_path)
    finally:
        runtime.close()


def test_sql_failure_cannot_publish_only_half_a_transition(tmp_path):
    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        owner = admit(runtime, 'a'); initial = observation(runtime, 'a', occupied=True)
        first = secrets.token_hex(16); send(runtime, 'a', owner, initial, first)
        before = runtime.journal.snapshot()
        runtime.journal._db.execute("CREATE TRIGGER fail_record BEFORE INSERT ON records BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        import sqlite3
        with pytest.raises(sqlite3.DatabaseError):
            deliver(runtime, 'a', owner, advance(initial, first))
        assert runtime.journal.snapshot() == before
        assert runtime.journal.record(COMPONENT, record_key('a')) is None
    finally:
        runtime.close()


def party_point(variant, blobs):
    point = source(variant); party = bytearray(404)
    party[0] = len(blobs); party[1+len(blobs)] = 255
    for slot, raw in enumerate(blobs):
        party[1+slot] = raw[0]; party[8+44*slot:52+44*slot] = raw[:44]
        party[272+11*slot:283+11*slot] = raw[44:55]; party[338+11*slot:349+11*slot] = raw[55:]
    point['fields']['party'] = party.hex().upper()
    return point


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_faint_follows_key_across_slots_once_and_key_replacement_is_unresolved(variant):
    codec = PartyCodec(variant)
    one = make_blob(codec, dv=0x1234); two = make_blob(codec, dv=0x2345)
    dead = bytearray(one); dead[1:3] = b'\0\0'
    before = party_point(variant, [one, two]); after = party_point(variant, [two, bytes(dead)])
    delta = transition(before, after, SAVE)
    assert delta['party_hp_zero'] == [codec.validate_blob(one).key]
    assert len(delta['movements']) == 2 and not delta['added'] and not delta['removed']
    assert transition(after, after, SAVE)['party_hp_zero'] == []
    assert transition(after, before, SAVE)['party_hp_zero'] == []
    replacement = party_point(variant, [two, make_blob(codec, dv=0x3456)])
    delta = transition(after, replacement, SAVE)
    assert len(delta['added']) == len(delta['removed']) == 1 and not delta['party_hp_zero']


@pytest.mark.parametrize('variant', ['red', 'blue', 'yellow'])
def test_initialized_box_switch_uses_wram_and_both_sram_banks_without_false_additions(variant):
    point = source(variant, occupied=True)
    symbols = SYMBOLS['pokeyellow' if variant == 'yellow' else 'pokered']
    offset = symbols['wCurrentBoxNum']-symbols['wMainDataStart']
    main = bytearray.fromhex(point['fields']['main']); main[offset] = 0x80
    point['fields']['main'] = main.hex().upper()
    cart = bytearray.fromhex(point['cart_hex'])
    for index in range(12):
        start = (2+index//6)*0x2000+(index%6)*1122
        cart[start:start+1122] = b'\0\xff'+b'\0'*1120
    stored = bytearray(1122); raw = make_blob(PartyCodec(variant), dv=0x5678)
    stored[:3] = bytes((1, raw[0], 255)); stored[22:55] = raw[:33]
    stored[682:693] = raw[44:55]; stored[902:913] = raw[55:]
    start = 3*0x2000+1122  # Box 7 lives in the second storage bank.
    cart[start:start+1122] = stored
    point['cart_hex'] = cart.hex().upper()
    changed = copy.deepcopy(point); main[offset] = 0x87
    changed['fields']['main'] = main.hex().upper()
    changed['fields']['box'] = stored.hex().upper()
    cart[start:start+1122] = b'\0\xff'+b'\0'*1120
    changed['cart_hex'] = cart.hex().upper()
    delta = transition(point, changed, SAVE)
    assert not any(delta[key] for key in ('added', 'removed', 'movements', 'party_hp_zero', 'changed'))
    main[offset] = 7; changed['fields']['main'] = main.hex().upper()
    with pytest.raises(JournalError, match='initialized storage disappeared'):
        transition(point, changed, SAVE)


@pytest.mark.parametrize('fault', ['pending', 'reconnect', 'record_removed'])
def test_obligations_replacement_and_missing_atomic_records_prevent_continuation(tmp_path, fault):
    runtime = create_runtime(tmp_path, contract('yellow', 'yellow'))
    try:
        owner = admit(runtime, 'a'); initial = observation(runtime, 'a', occupied=True)
        first = secrets.token_hex(16); send(runtime, 'a', owner, initial, first)
        if fault == 'pending':
            snapshot = runtime.journal.snapshot()
            runtime.journal.commit('a', secrets.token_hex(16), {'event': 'explicit-command-fixture'},
                expected_revision=snapshot.revision, state=snapshot.state,
                commands={'a': [{'cmd': 'force_faint', 'key': '1234:9999:99'}], 'b': []}, result={'ack': 'ACK'})
        elif fault == 'reconnect':
            runtime.disconnect('a', owner)
            owner = admit(runtime, 'a')
        else:
            deliver(runtime, 'a', owner, advance(initial, first))
            runtime.journal._db.execute('DELETE FROM records WHERE namespace=?', (COMPONENT,))
        before = runtime.journal.snapshot()
        with pytest.raises(JournalError):
            deliver(runtime, 'a', owner, advance(initial, first))
        assert runtime.journal.snapshot() == before
    finally:
        runtime.close()
