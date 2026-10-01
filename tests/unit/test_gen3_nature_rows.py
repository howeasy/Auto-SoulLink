"""Producer-shaped receipt/save controls; no emulator."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import gen3_nature_rows as n
from server.adapters import gen3_codec as c
ROOT = Path(__file__).resolve().parents[2]

@pytest.fixture
def producer():
    from e2e_duo import gen3_decode, gen3_key
    before = gen3_decode((ROOT/'tests/fixtures/gen3/rr_battle2.sav').read_bytes(), rr=True)
    partner = gen3_decode((ROOT/'tests/fixtures/gen3/rr_battle2_b.sav').read_bytes(), rr=True)
    old = deepcopy(before[0][1]); new = deepcopy(old)
    target=n.own_facts(type('R',(),{'_gen3_rom':lambda s,i:'E:/Google Drive/SLink/patch/build/slink_RR.gba'})())['target_nature']
    new['personality'] += (target - old['personality'] % 25) % 25 or 25
    raw = c.encode_party_mon(old, rr=True)
    post = c.decode_party_mon(c.encode_party_mon(new, rr=True), rr=True)
    after = deepcopy(before); after[0][1] = post
    rom = Path('E:/Google Drive/SLink/patch/build/slink_RR.gba')
    sha = hashlib.sha1(rom.read_bytes()).hexdigest()
    pre = dict(key=gen3_key(old),slot=1,raw_hex=raw.hex(),raw_sha1=hashlib.sha1(raw).hexdigest(),rom_sha1=sha)
    change = dict(event='key_change',old_key=gen3_key(old),new_key=gen3_key(post),reason='nature_change')
    signals = [dict(kind='nature_change_begin',point={'R4':0x02024284+100}),
               dict(kind='nature_change',point={'R4':0x02024284+100})]
    text = 'NATURE_BASELINE '+json.dumps(dict(key=pre['key']))+'\n'
    text += 'NATURE_CANCEL '+json.dumps(dict(key=pre['key'],unchanged=True))+'\n'
    text += 'NATURE_PREIMAGE '+json.dumps(pre)+'\n'
    text += ''.join('NATURE_SIGNAL '+json.dumps(s)+'\n' for s in signals)
    text += 'TX key_change '+pre['key']+' '+json.dumps(change)+'\n'
    text += 'NATURE_ACK '+json.dumps(dict(old_key=pre['key'],new_key=change['new_key'],migrated=True))+'\n'
    text += 'NATURE_CHANGED '+change['new_key']+'\nSAVE_WITNESS nature counter=2->3\n'
    class Run:
        _gen3_rr=True
        def __init__(self):
            self.saved={'a':after,'b':deepcopy(partner)}
            self.links=[dict(status='alive',a={'key':change['new_key']},b={'key':gen3_key(partner[0][1])})]
            self._link_keys={'a':pre['key'],'b':gen3_key(partner[0][1])}
        def _gen3_rom(self, inst): return str(rom)
        def _gen3_flush_boundary(self): pass
        def _gen3_saved(self, inst): return self.saved[inst]
        def _gen3_fixture_saved(self, inst): return before if inst=='a' else partner
        def _links_json(self): return self.links
        def _pydec_note(self, msg): self.note=msg
    return Run(), {'a':text,'b':'SAVE_WITNESS nature counter=2->3\n'}, pre

def test_real_result_mapping_and_saved_codec_records_are_accepted(producer):
    run, results, _ = producer
    n.nature_oracle(run, results)

def test_transit_no_catch_is_allowed_but_operation_capture_is_refused(producer):
    run,results,_=producer
    results['a']='TX no_catch transit '+json.dumps({'event':'no_catch','area_id':'route_1'})+'\n'+results['a']
    n.nature_oracle(run,results)
    results['a']+='TX capture late '+json.dumps({'event':'capture','key':'late'})+'\n'
    with pytest.raises(RuntimeError,match='gameplay churn'): n.nature_oracle(run,results)

def test_orchestration_uses_real_per_player_linked_lines_and_go(producer,tmp_path,monkeypatch):
    from e2e_duo import DuoRun
    run,_,_=producer
    monkeypatch.setattr(n,'own_facts',lambda run:{'map':[5,4],'target_nature':3})
    native=DuoRun.__new__(DuoRun)
    native._link_keys=run._link_keys
    native.go_files={i:str(tmp_path/(i+'.go')) for i in ('a','b')}
    calls=[]
    native._gen3_prelude=lambda link_slot: calls.append(('prelude',link_slot))
    native._gen3_area_control=lambda: calls.append(('area',))
    native._gen3_mark=lambda *a: calls.append(('mark',a[0]))
    native._append_reconnect_marker=lambda *a: calls.append(('save',*a))
    n.orchestrate(native)
    for inst in ('a','b'):
        lines=Path(native.go_files[inst]).read_text().splitlines()
        assert lines[0]=='LINKED '+run._link_keys[inst]
        assert json.loads(lines[1].removeprefix('NATURE '))=={'map':[5,4],'target_nature':3}
    assert calls==[('prelude',1),('area',),('mark','a'),('save','a','SAVE'),('save','b','SAVE')]

@pytest.mark.parametrize('fault',['moves','species','ivs','evs','ot_id','partner','link','ack','signal','cancel','hash','raw_hash','unmigrated','save','bad_checksum','duplicate'])
def test_producer_faults_fail_closed(producer,fault):
    run, results, pre = producer
    mon=run.saved['a'][0][1]
    if fault in ('moves','ivs','evs'): mon[fault]=[999]*len(mon[fault])
    elif fault in ('species','ot_id'): mon[fault]+=1
    elif fault=='partner': run.saved['b'][0][0]['species']+=1
    elif fault=='link': run.links=[]
    elif fault=='ack': results['a']=results['a'].replace('NATURE_ACK','RX unrelated')
    elif fault=='signal': results['a']=results['a'].replace('nature_change_begin','unrelated')
    elif fault=='cancel': results['a']=results['a'].replace('"unchanged": true','"unchanged": false')
    elif fault=='hash': results['a']=results['a'].replace(pre['rom_sha1'],'0'*40)
    elif fault=='raw_hash': results['a']=results['a'].replace(pre['raw_sha1'],'0'*40)
    elif fault=='unmigrated': results['a']=results['a'].replace('"migrated": true','"migrated": false')
    elif fault=='save': results['a']=results['a'].replace('counter=2->3','counter=2->2')
    elif fault=='bad_checksum': mon['checksum_ok']=False
    elif fault=='duplicate': results['a']+=next(l for l in results['a'].splitlines() if l.startswith('TX key_change'))+'\n'
    with pytest.raises((RuntimeError,ValueError)): n.nature_oracle(run,results)
