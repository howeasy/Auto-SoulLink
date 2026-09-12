import copy
import secrets
from itertools import product
from pathlib import Path

import pytest

from server.gen1_full_save import SYMBOLS
from server.gen1_party_codec import PartyCodec
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_state import Gen1RuntimeState
from server.gen1_starter_settlement import COMPONENT, AREA
from server.protocol_journal import JournalError
from server.state import AreaStatus
from tests.unit.test_gen1_sessions import contract
from tests.unit.test_gen1_initial_observation import admit, observation, send
from tests.unit.test_gen1_inventory_observation import deliver as inventory_event, party_point
from tests.unit.test_gen1_engine_signal_runtime import deliver as engine_event, payload as engine_payload
from tests.unit.test_gen1_party_codec import make_blob


def enroll(runtime):
    owners={};initials={};operations={}
    for player in ('a','b'):
        owners[player]=admit(runtime,player);initials[player]=observation(runtime,player)
        operations[player]=secrets.token_hex(16)
        send(runtime,player,owners[player],initials[player],operations[player])
    return owners,initials,operations


def source_and_checkpoint(runtime,player,initial,previous,*,dv=0x1234,species=None):
    variant=runtime.contract['players'][player]['variant']
    # Internal species bytes: Yellow always hands out Pikachu (0x54); Red and Blue default to
    # Bulbasaur (0x99) unless the case picks another starter.
    birth=bytearray(make_blob(PartyCodec(variant),species=species or (84 if variant=='yellow' else 153),otid=0,dv=dv))
    birth[44:55]=bytes.fromhex(initial['source']['fields']['name'])
    source=engine_payload(runtime,player,['starter_begin','starter_end'])
    for row in source['signals']:row['point']['cur_species']=birth[0]
    source['signals'][1]['point']['party_hex']=party_point(variant,[bytes(birth)])['fields']['party']
    stable=copy.deepcopy(initial);stable['frame']=110
    if variant=='yellow':birth[7]=0xA3
    stable['source']['fields']['party']=party_point(variant,[bytes(birth)])['fields']['party']
    syms=SYMBOLS['pokeyellow' if variant=='yellow' else 'pokered']
    main=bytearray.fromhex(stable['source']['fields']['main']);main[syms['wStatusFlags4']-syms['wMainDataStart']] |=8
    stable['source']['fields']['main']=main.hex().upper()
    return source,{'sequence':1,'previous_operation_id':previous,'observation':stable}


# Starters are under the clauses in every generation (owner decision 2026-09-11, the Gen 3 rule);
# Yellow/Yellow is the one exemption because both scripts hand out Pikachu with no choice.
# A mixed pair always links (Pikachu shares no family or type with the Kanto starters); a pair
# with a choice on both sides links when the starters differ and is rejected when they match.
BULBASAUR,CHARMANDER=153,176   # internal species bytes
STARTER_CASES=[]
for _variants in product(('red','blue','yellow'),repeat=2):
    if _variants.count('yellow')==2:STARTER_CASES.append((_variants,'same','exempt_link'))
    elif _variants.count('yellow')==1:STARTER_CASES.append((_variants,'different','link'))
    else:STARTER_CASES.extend([(_variants,'same','rejected'),(_variants,'different','link')])


@pytest.mark.parametrize('variants,starters,outcome',STARTER_CASES)
@pytest.mark.parametrize('order',[('a','b'),('b','a')])
def test_stable_starters_settle_owned_identities_and_the_engine_pairs_or_rejects_them_atomically(tmp_path,variants,starters,outcome,order):
    runtime=create_runtime(tmp_path,contract(*variants))
    try:
        owners,initials,operations=enroll(runtime)
        snap=runtime.journal.snapshot();stage=runtime.state()
        for flag in ('species_lock','gender_lock','type_lock'):setattr(stage.rules,flag,True)
        stage.barrier.set_history(stage.history_digest());document=stage.document()
        runtime.journal.commit('a',secrets.token_hex(16),{'event':'explicit-rule-options-fixture'},expected_revision=snap.revision,
            state=document,commands={'a':[],'b':[]},result={'ack':'ACK'})
        keys={}
        for index,player in enumerate(order):
            variant=runtime.contract['players'][player]['variant']
            species=None if variant=='yellow' else (CHARMANDER if starters=='different' and index==1 else BULBASAUR)
            source,checkpoint=source_and_checkpoint(runtime,player,initials[player],operations[player],species=species)
            engine_event(runtime,player,owners[player],source)
            assert len(runtime.state().identities.document()['members'])==index
            op=secrets.token_hex(16);inventory_event(runtime,player,owners[player],checkpoint,op)
            before=runtime.journal.snapshot();inventory_event(runtime,player,owners[player],checkpoint,op)
            assert runtime.journal.snapshot()==before
            stage=runtime.state();settled=stage.document()['components'][COMPONENT]['settled'][player]
            keys[player]=stage.rules.partner_blobs[player][0]['key']
            assert stage.rules.party_size[player]==1
            assert bytes.fromhex(settled['blob_hex'])==stage.rules.partner_blobs[player][0]['blob']
            if index==0:
                assert stage.rules.area_states[AREA]==(AreaStatus.PENDING_B if player=='a' else AreaStatus.PENDING_A)
                assert not stage.rules.links
        stage=runtime.state();document=stage.document();component=document['components'][COMPONENT]
        first,second=order
        assert len(document['identities']['members'])==2
        if outcome=='rejected':
            assert not stage.rules.links and not document['identities']['links'] and component['link_id'] is None
            assert component['rejection']=={'player':second,'key':keys[second],'member_id':component['settled'][second]['member_id'],
                'reason':'Species clause: both are Bulbasaur','at':component['rejection']['at']}
            assert stage.rules.area_states[AREA]==(AreaStatus.PENDING_A if second=='a' else AreaStatus.PENDING_B)   # the lab waits on the rejected player
            assert set(stage.rules.pending_captures[AREA])=={first} and AREA in stage.rules.retry_areas[second]
            assert keys[second] not in stage.rules.party_keys[second] and not stage.rules.pending_memorials[second]
        else:
            assert len(stage.rules.links)==len(document['identities']['links'])==1 and component['rejection'] is None
            assert not stage.rules.pending_captures and not any(stage.rules.retry_areas.values())
            assert stage.rules.links[0].area_id==AREA and stage.rules.area_states[AREA]==AreaStatus.LINKED
            if outcome=='exempt_link':
                assert stage.rules.links[0].a.species==stage.rules.links[0].b.species==25   # two Pikachu, exempt
            else:
                assert stage.rules.links[0].a.species!=stage.rules.links[0].b.species
        assert not any(stage.rules.pokeballs_obtained.values()) and stage.barrier.ticket() is None
        assert not runtime.journal.pending_ids('a') and not runtime.journal.pending_ids('b')
    finally:runtime.close()
    runtime=open_runtime(tmp_path)
    try:
        restored=runtime.state().document()
        assert restored['rules']==document['rules'] and restored['identities']==document['identities']
        assert restored['components'][COMPONENT]==document['components'][COMPONENT]
        assert runtime.state().barrier.ticket() is None
    finally:runtime.close()


@pytest.mark.parametrize('fault',['identity','birth_name','completion_flag','yellow_catch_rate','extra_party',
                                'box_collision','initial_nonempty','unrelated_peer','snapshot_before_return'])
def test_invalid_or_ambiguous_starter_checkpoint_creates_no_partial_rule_or_identity_state(tmp_path,fault):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners,initials,operations=enroll(runtime)
        source,checkpoint=source_and_checkpoint(runtime,'a',initials['a'],operations['a'])
        if fault=='birth_name':
            blob=bytearray.fromhex(source['signals'][1]['point']['party_hex']);blob[272]=0x91
            source['signals'][1]['point']['party_hex']=blob.hex().upper()
        engine_event(runtime,'a',owners['a'],source)
        point=checkpoint['observation'];party=bytearray.fromhex(point['source']['fields']['party'])
        if fault=='identity':party[35]^=1
        elif fault=='yellow_catch_rate':party[15]=45
        elif fault=='completion_flag':point['source']['fields']['main']=initials['a']['source']['fields']['main']
        elif fault=='snapshot_before_return':point['frame']=100
        elif fault=='extra_party':
            another=make_blob(PartyCodec('yellow'),dv=0x4321)
            original=party[8:52]+party[272:283]+party[338:349]
            party=bytearray.fromhex(party_point('yellow',[bytes(original),another])['fields']['party'])
        elif fault=='box_collision':
            box=bytearray(1122);box[:3]=bytes((1,party[8],255));box[22:55]=party[8:41]
            box[682:693]=party[272:283];box[902:913]=party[338:349];point['source']['fields']['box']=box.hex().upper()
        elif fault in ('initial_nonempty','unrelated_peer'):
            # Exercise stopped-source revalidation separately instead of forging
            # a second initial event, which the enrollment route already refuses.
            snapshot=runtime.journal.snapshot();doc=copy.deepcopy(snapshot.state)
            if fault=='initial_nonempty':
                doc['components']['gen1-initial-observations']['b']['inventory']['members']=[{}]
            else:doc['components'][COMPONENT]['sources']['a']['transaction']['key']='different'
            with pytest.raises((JournalError,KeyError)):
                Gen1RuntimeState.restore(doc,data_dir=tmp_path)
            return
        point['source']['fields']['party']=party.hex().upper()
        before=runtime.journal.snapshot()
        with pytest.raises((JournalError,ValueError)):
            inventory_event(runtime,'a',owners['a'],checkpoint)
        assert runtime.journal.snapshot()==before
        assert not runtime.state().identities.document()['members']
    finally:runtime.close()


def test_later_engine_batches_do_not_lose_the_unsettled_starter_source(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners,initials,ops=enroll(runtime);source,checkpoint=source_and_checkpoint(runtime,'a',initials['a'],ops['a'])
        engine_event(runtime,'a',owners['a'],source)
        engine_event(runtime,'a',owners['a'],engine_payload(runtime,'a',['battle_faint'],2))
        inventory_event(runtime,'a',owners['a'],checkpoint)
        assert len(runtime.state().identities.document()['members'])==1
    finally:runtime.close()


def test_valid_existing_peer_inventory_is_not_imported_as_a_fresh_starter_run(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners={};initials={};ops={}
        for player in ('a','b'):
            owners[player]=admit(runtime,player);initials[player]=observation(runtime,player,occupied=player=='b')
            ops[player]=secrets.token_hex(16);send(runtime,player,owners[player],initials[player],ops[player])
        source,checkpoint=source_and_checkpoint(runtime,'a',initials['a'],ops['a'])
        engine_event(runtime,'a',owners['a'],source);before=runtime.journal.snapshot()
        with pytest.raises(JournalError,match='pre-starter'):
            inventory_event(runtime,'a',owners['a'],checkpoint)
        assert runtime.journal.snapshot()==before
        assert not runtime.state().identities.document()['members']
    finally:runtime.close()


@pytest.mark.parametrize('variant',['red','yellow'])
def test_stable_level_and_hp_are_kept_instead_of_writing_back_the_birth_blob(tmp_path,variant):
    runtime=create_runtime(tmp_path,contract(variant,variant))
    try:
        owners,initials,ops=enroll(runtime);source,checkpoint=source_and_checkpoint(runtime,'a',initials['a'],ops['a'])
        engine_event(runtime,'a',owners['a'],source)
        current=bytearray(make_blob(PartyCodec(variant),species=84 if variant=='yellow' else 153,level=6,otid=0,dv=0x1234))
        current[1:3]=b'\0\x01';current[44:55]=bytes.fromhex(initials['a']['source']['fields']['name'])
        if variant=='yellow':current[7]=0xA3
        checkpoint['observation']['source']['fields']['party']=party_point(variant,[bytes(current)])['fields']['party']
        inventory_event(runtime,'a',owners['a'],checkpoint)
        stage=runtime.state()
        assert stage.rules.pending_captures[AREA]['a'].level==6
        assert stage.rules.partner_blobs['a'][0]['blob']==bytes(current)
        assert not runtime.journal.pending_ids('a')
    finally:runtime.close()


@pytest.mark.parametrize('changed_key',[False,True])
def test_pairing_rechecks_the_first_players_latest_inventory(tmp_path,changed_key):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners,initials,ops=enroll(runtime)
        first_source,first=source_and_checkpoint(runtime,'a',initials['a'],ops['a'])
        engine_event(runtime,'a',owners['a'],first_source)
        first_op=secrets.token_hex(16);inventory_event(runtime,'a',owners['a'],first,first_op)
        current=bytearray(make_blob(PartyCodec('yellow'),species=84,level=6,otid=0,dv=0x4321 if changed_key else 0x1234))
        current[7]=0xA3;current[44:55]=bytes.fromhex(initials['a']['source']['fields']['name'])
        later=copy.deepcopy(first);later['sequence']=2;later['previous_operation_id']=first_op
        later['observation']['frame']+=1
        later['observation']['source']['fields']['party']=party_point('yellow',[bytes(current)])['fields']['party']
        inventory_event(runtime,'a',owners['a'],later)
        source,checkpoint=source_and_checkpoint(runtime,'b',initials['b'],ops['b'])
        engine_event(runtime,'b',owners['b'],source);before=runtime.journal.snapshot()
        if changed_key:
            with pytest.raises(JournalError,match='identity differs'):
                inventory_event(runtime,'b',owners['b'],checkpoint)
            assert runtime.journal.snapshot()==before
        else:
            inventory_event(runtime,'b',owners['b'],checkpoint)
            stage=runtime.state()
            assert stage.rules.links[0].a.level==6 and stage.rules.partner_blobs['a'][0]['blob']==bytes(current)
    finally:runtime.close()


def test_partial_inventory_commit_failure_rolls_back_rules_identity_and_link(tmp_path):
    runtime=create_runtime(tmp_path,contract('yellow','yellow'))
    try:
        owners,initials,ops=enroll(runtime)
        for player in ('a','b'):
            source,checkpoint=source_and_checkpoint(runtime,player,initials[player],ops[player])
            engine_event(runtime,player,owners[player],source)
            if player=='a':inventory_event(runtime,player,owners[player],checkpoint)
        before=runtime.journal.snapshot()
        runtime.journal._db.execute("CREATE TRIGGER fail_inventory BEFORE INSERT ON records WHEN NEW.namespace='gen1-inventory-observations' BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        import sqlite3
        with pytest.raises(sqlite3.DatabaseError):inventory_event(runtime,'b',owners['b'],checkpoint)
        assert runtime.journal.snapshot()==before
        assert len(before.state['identities']['members'])==1 and not before.state['rules']['core']['links']
    finally:runtime.close()


def test_settlement_constants_match_pinned_cartridge_sources():
    root=Path(__file__).resolve().parents[2]
    for variant in ('pokered','pokeyellow'):
        text=(root/'.cache/pret'/variant/'constants/ram_constants.asm').read_text()
        assert 'const BIT_GOT_STARTER             ; 3' in text
        source=(root/'.cache/pret'/variant/'scripts/OaksLab.asm').read_text()
        assert 'set BIT_GOT_STARTER, [hl]' in source
    yellow=(root/'.cache/pret/pokeyellow/scripts/OaksLab.asm').read_text()
    assert 'call AddPartyMon\n\tld a, LIGHT_BALL_GSC\n\tld [wPartyMon1CatchRate], a' in yellow
    assert 'DEF LIGHT_BALL_GSC   EQU $a3' in (root/'.cache/pret/pokeyellow/constants/item_constants.asm').read_text()
