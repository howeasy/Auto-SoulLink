import copy
import secrets
from itertools import product

import pytest

from server.gen1_bag import decode_bag
from server.gen1_engine_signals import DATA, validate_signal
from server.gen1_faint_runtime import COMPONENT, REASON
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.protocol_journal import JournalError
from server.state import LinkStatus
from tests.unit.test_gen1_engine_signal_runtime import deliver, payload
from tests.unit.test_gen1_hud_feedback import acknowledge_hud
from tests.unit.test_gen1_inventory_observation import deliver as inventory_event
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_starter_settlement import enroll, source_and_checkpoint


def bag(variant,item=4,quantity=5):
    profile=DATA['titles'][variant];site=profile['sites']['bag_received']
    raw=bytes((1,item,quantity,255))+bytes(38)
    return {'kind':'bag_received','frame':120,'pc':site['address']+site['capture_offset'],'bank':site['bank'],'sp':0xDFF0,
        'point':{'bag_hex':raw.hex().upper(),'trainer_hex':'92808C8450000000000000','player_id_hex':'0000',
            'destination':profile['addresses']['wNumBagItems'],'flags':16,'item':item,'quantity':quantity}}


def paired(runtime):
    instant=runtime.clock();runtime.clock=lambda:instant  # Unit fixture has no heartbeat transport.
    owners,initials,operations=enroll(runtime)
    for player in ('a','b'):
        source,checkpoint=source_and_checkpoint(runtime,player,initials[player],operations[player])
        deliver(runtime,player,owners[player],source)
        inventory_event(runtime,player,owners[player],checkpoint)
        acknowledge_hud(runtime)
    return owners


def signal_batch(runtime,player,*,sequence=2,cause='battle_faint',activate=True):
    value=payload(runtime,player,[cause],sequence)
    current=runtime.state().rules.partner_blobs[player][0]['blob']
    point=value['signals'][0]['point'];raw=bytearray.fromhex(point['party_hex'])
    raw[:3]=bytes((1,current[0],255));raw[8:52]=current[:44];raw[272:283]=current[44:55];raw[338:349]=current[55:]
    raw[9:11]=b'\0\0'
    if cause=='poison_faint':raw[12]=8
    point['party_hex']=raw.hex().upper();point['battle_species']=current[0]
    value['signals'][0]['frame']=121
    if activate:value['signals'].insert(0,bag(runtime.contract['players'][player]['variant']))
    return value


def acknowledgement(runtime,player,command):
    raw=runtime.state().rules.partner_blobs[player][0]['blob'];variant=runtime.contract['players'][player]['variant']
    before={'schema':'gen1-party-readback-v1','variant':variant,'save_id':'0000','save_name':'SAME',
        'party_count':1,'party':[raw.hex().upper()],'species_list':[raw[0],255],
        'battle_flag':1,'active_slot':0,'battle_hp':int.from_bytes(raw[1:3],'big')}
    after=copy.deepcopy(before);post=bytearray(raw);post[1:3]=b'\0\0';after['party']=[post.hex().upper()];after['battle_hp']=0
    return {'event':'command_ack','command_id':command['command_id'],'command_sequence':command['command_sequence'],
        'outcome':'ACK','receipt':{'schema':'gen1-force-faint-receipt-v1','before':before,'after':after}}


def ack(runtime,player,owner,message,op=None):
    session=runtime.gate.sessions[player]
    return runtime.process({**message,'protocol':runtime.protocol,'player':player,'session_id':session.session_id,
        'admission_epoch':runtime.gate.epoch,'seq':session.last_seq+1,'operation_id':op or secrets.token_hex(16)},owner)


@pytest.mark.parametrize('variants',list(product(('red','blue','yellow'),repeat=2)))
@pytest.mark.parametrize('cause',['battle_faint','poison_faint'])
def test_activation_faint_and_physical_ack_are_atomic_and_do_not_claim_memorial_completion(tmp_path,variants,cause):
    runtime=create_runtime(tmp_path,contract(*variants))
    try:
        owners=paired(runtime);value=signal_batch(runtime,'a',cause=cause);op=secrets.token_hex(16)
        deliver(runtime,'a',owners['a'],value,op);before=runtime.journal.snapshot()
        deliver(runtime,'a',owners['a'],value,op);assert runtime.journal.snapshot()==before
        stage=runtime.state();assert stage.rules.links[0].status==LinkStatus.DEAD
        assert stage.rules.pokeballs_obtained=={'a':True,'b':False}
        assert not stage.rules.run_over and not runtime.journal.pending_ids('a')
        pending=runtime.journal.pending('b');assert len(pending)==1 and pending[0]['cmd']=='force_faint'
        command=runtime.journal.command('b',pending[0]['command_id']);message=acknowledgement(runtime,'b',command)
        receipt_op=secrets.token_hex(16);ack(runtime,'b',owners['b'],message,receipt_op)
        snapshot=runtime.journal.snapshot();ack(runtime,'b',owners['b'],message,receipt_op)
        assert runtime.journal.snapshot()==snapshot
        assert all([c['cmd'] for c in runtime.journal.pending(p)]==['memorial_observe'] for p in ('a','b'))
        assert runtime.state().rules.partner_blobs['b'][0]['blob'][1:3]==b'\0\0'
        death=next(iter(runtime.state().document()['components'][COMPONENT]['deaths'].values()))
        assert death['phase']=='pending_memorial' and REASON in runtime.state().barrier.document()['blockers'].values()
        assert all(runtime.state().rules.pending_memorials.values())
        deliver(runtime,'b',owners['b'],{**payload(runtime,'b',['battle_faint'],2),'signals':[bag(variants[1])]})
        assert runtime.state().rules.run_over is True
        # The partner engine's later faint callback does not create another command.
        deliver(runtime,'b',owners['b'],signal_batch(runtime,'b',sequence=3,activate=False))
        assert [c['cmd'] for c in runtime.journal.pending('a')]==['memorial_observe']
        assert len(runtime.state().document()['components'][COMPONENT]['deaths'])==1
    finally:runtime.close()
    reopened=open_runtime(tmp_path)
    try:assert reopened.state().rules.links[0].status==LinkStatus.DEAD and reopened.state().barrier.ticket() is None
    finally:reopened.close()


def test_faint_before_ball_delivery_in_same_batch_remains_suppressed(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners=paired(runtime);value=signal_batch(runtime,'a');value['signals'].reverse()
        for signal in value['signals']:signal['frame']=120
        before=runtime.state().rules.party_keys.copy()
        deliver(runtime,'a',owners['a'],value)
        assert runtime.state().rules.links[0].status==LinkStatus.ALIVE and runtime.state().rules.party_keys==before
        assert runtime.state().rules.pokeballs_obtained['a'] and not runtime.journal.pending_ids('b')
    finally:runtime.close()


@pytest.mark.parametrize('fault',['flags','destination','quantity','terminator','count','missing_ball'])
def test_invalid_ball_delivery_cannot_activate(fault):
    value=bag('yellow');point=value['point']
    if fault=='flags':point['flags']=0
    elif fault=='destination':point['destination']+=1
    elif fault=='quantity':point['quantity']=0
    else:
        raw=bytearray.fromhex(point['bag_hex'])
        if fault=='count':raw[0]=21
        elif fault=='terminator':raw[3]=0
        else:raw[1]=20
        point['bag_hex']=raw.hex().upper()
    with pytest.raises(JournalError):validate_signal(value,'yellow',{'ot_id':'0000','trainer_name':'SAME'})


def test_duplicate_item_stacks_are_valid_bag_geometry():
    rows=decode_bag((bytes((2,4,99,4,5,255))+bytes(36)).hex().upper())
    assert sum(row['quantity'] for row in rows)==104


@pytest.mark.parametrize('fault',['hp','mirror','sequence','nack'])
def test_bad_physical_ack_leaves_the_obligation_and_rules_unchanged(tmp_path,fault):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners=paired(runtime);deliver(runtime,'a',owners['a'],signal_batch(runtime,'a'))
        cmd=runtime.journal.command('b',runtime.journal.pending_ids('b')[0]);message=acknowledgement(runtime,'b',cmd)
        if fault=='hp':message['receipt']['after']['party']=message['receipt']['before']['party']
        elif fault=='mirror':message['receipt']['after']['battle_hp']=1
        elif fault=='sequence':message['command_sequence']+=1
        else:message['outcome']='NACK'
        before=runtime.journal.snapshot()
        with pytest.raises(JournalError):ack(runtime,'b',owners['b'],message)
        assert runtime.journal.snapshot()==before and runtime.journal.pending_ids('b')
    finally:runtime.close()


def test_corrupt_death_record_refuses_stopped_restore(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners=paired(runtime);deliver(runtime,'a',owners['a'],signal_batch(runtime,'a'))
        document=runtime.state().document();death=next(iter(document['components'][COMPONENT]['deaths'].values()))
        death['phase']='complete'
        with pytest.raises(JournalError):Gen1RuntimeState.restore(document,data_dir=tmp_path)
    finally:runtime.close()


def test_sql_command_publication_failure_rolls_back_activation_and_death_together(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners=paired(runtime);before=runtime.journal.snapshot()
        runtime.journal._db.execute("CREATE TRIGGER fail_commands BEFORE INSERT ON commands BEGIN SELECT RAISE(ABORT,'fixture'); END")
        import sqlite3
        with pytest.raises(sqlite3.DatabaseError):deliver(runtime,'a',owners['a'],signal_batch(runtime,'a'))
        assert runtime.journal.snapshot()==before and not runtime.journal.pending_ids('b')
    finally:runtime.close()


def test_same_death_label_on_an_unrelated_command_cannot_acknowledge_the_real_obligation(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners=paired(runtime);deliver(runtime,'a',owners['a'],signal_batch(runtime,'a'))
        original=runtime.journal.command('b',runtime.journal.pending_ids('b')[0]);snapshot=runtime.journal.snapshot()
        runtime.journal.commit('a',secrets.token_hex(16),{'event':'unrelated-command-fixture'},expected_revision=snapshot.revision,
            state=snapshot.state,commands={'a':[],'b':[original['body']]},result={'ack':'ACK'})
        other=runtime.journal.command('b',runtime.journal.pending_ids('b')[-1]);before=runtime.journal.snapshot()
        with pytest.raises(JournalError,match='original command'):ack(runtime,'b',owners['b'],acknowledgement(runtime,'b',other))
        assert runtime.journal.snapshot()==before
    finally:runtime.close()


def test_faint_ack_cannot_skip_an_older_pending_command(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners=paired(runtime);snapshot=runtime.journal.snapshot()
        runtime.journal.commit('a',secrets.token_hex(16),{'event':'explicit-older-command-fixture'},
            expected_revision=snapshot.revision,state=snapshot.state,
            commands={'a':[],'b':[{'cmd':'fixture_older_observation'}]},result={'ack':'ACK'})
        deliver(runtime,'a',owners['a'],signal_batch(runtime,'a'))
        command=runtime.journal.command('b',runtime.journal.pending_ids('b')[-1])
        before=runtime.journal.snapshot()
        with pytest.raises(JournalError,match='oldest'):
            ack(runtime,'b',owners['b'],acknowledgement(runtime,'b',command))
        assert runtime.journal.snapshot()==before
    finally:runtime.close()


def test_death_records_name_their_selected_command_and_a_force_explode_death_settles_through_its_ack(tmp_path):
    runtime = create_runtime(tmp_path, contract('red', 'red'), rule_options={'explode_mode': True})
    try:
        owners = paired(runtime)
        deliver(runtime, 'a', owners['a'], signal_batch(runtime, 'a'))
        death = next(iter(runtime.state().document()['components'][COMPONENT]['deaths'].values()))
        command = runtime.journal.command('b', runtime.journal.pending_ids('b')[0])
        assert death['command'] == 'force_explode' == command['body']['cmd'] and death['phase'] == 'pending_faint'
        message = acknowledgement(runtime, 'b', command)
        wrong = copy.deepcopy(message)
        wrong['receipt']['schema'] = 'gen1-force-faint-receipt-v1'
        with pytest.raises(JournalError, match='versioned'):
            ack(runtime, 'b', owners['b'], wrong)
        message['receipt']['schema'] = 'gen1-force-explode-receipt-v1'
        ack(runtime, 'b', owners['b'], message)
        death = next(iter(runtime.state().document()['components'][COMPONENT]['deaths'].values()))
        assert death['phase'] == 'pending_memorial' and runtime.journal.command('b', command['command_id'])['outcome'] == 'ACK'
    finally:
        runtime.close()


def test_enforce_records_a_terminal_window_verdict_once_and_ignores_the_rest():
    from server import event_reference
    from server.gen1_faint_runtime import enforce
    from server.protocol import digest
    origin = event_reference.make('b', '1' * 32, {'event': 'command_ack'})
    death = {'phase': 'pending_faint'}
    row = {'frame': 130, 'step': 31, 'site': 'loop_head', 'writes': []}
    for outcome in ('not_reached', 'refused', 'explode_armed', 'declined'):
        assert enforce(death, {'outcome': outcome, 'row': None}, origin=origin) is None and 'enforcement' not in death
    enforcement = enforce(death, {'outcome': 'fainted', 'row': row}, origin=origin)
    assert death['enforcement'] == enforcement == {'origin': origin, 'frame': 130, 'step': 31, 'site': 'loop_head', 'outcome': 'fainted',
                                                  'evidence_digest': digest(row)}
    assert death['phase'] == 'pending_faint'
    with pytest.raises(JournalError, match='already enforced'):
        enforce(death, {'outcome': 'benched', 'row': row}, origin=origin)
    with pytest.raises(JournalError, match='pending physical faint'):
        enforce({'phase': 'pending_memorial'}, {'outcome': 'fainted', 'row': row}, origin=origin)
