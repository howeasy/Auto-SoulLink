import json
from types import SimpleNamespace

import pytest

from server import gen1_admission, manager
from server.gen1_run_config import open_runtime
from server.gen1_runtime_admission import METADATA_SCHEMA, PROTOCOL
from tests.unit.test_gen1_sessions import contract


class Request:
    def __init__(self,body):self.body=body
    async def json(self):return self.body


def first_controls(runtime):
    owners={player:object() for player in ('a','b')};admissions={}
    for index,player in enumerate(('a','b'),1):
        operation=f'{index:032x}'
        admissions[player]=runtime.process({
            'protocol':PROTOCOL,'run_id':runtime.journal.run_id,'player':player,'event':'hello','seq':0,
            'client_nonce':operation,'operation_id':operation,'context_generation':player*32,
            'gen1_metadata':{'schema':METADATA_SCHEMA,'cartridge':runtime.contract['players'][player],
                'save_identity':{'ot_id':'0000','trainer_name':'SAME'},'physical_instance':str(index)*32}},owners[player])
    responses=[]
    for index,player in enumerate(('a','b'),3):
        binding=admissions[player]['admission']['control_binding'];challenge=f'{index:032x}'
        session=runtime.gate.sessions[player]
        responses.append(runtime.process({'protocol':PROTOCOL,'player':player,'event':'control',
            'seq':session.last_seq+1,'operation_id':challenge,'session_id':session.session_id,
            'admission_epoch':runtime.gate.epoch,'control':{**binding,'challenge':challenge}},owners[player]))
    return responses


@pytest.mark.asyncio
@pytest.mark.parametrize('start',[False,True])
async def test_manager_prepares_a_fresh_runtime_before_optional_server_start(tmp_path,monkeypatch,start):
    runs=[];started=[]
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:runs.__setitem__(slice(None),value))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:contract('yellow','yellow'))
    async def spawn(run,*args,**kwargs):
        path=tmp_path/run['run_id']
        assert (path/'gen1_runtime.json').exists() and (path/'runtime.sqlite3').exists()
        started.append(run['run_id']);return 12345
    monkeypatch.setattr(manager,'_spawn_run',spawn)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'Fresh Yellow pair','rom_a':'a.gbc','rom_b':'b.gbc','rules':{'species_lock':True,'gender_lock':True},'start':start}))
    result=json.loads(response.text)
    assert response.status==200 and result['ok'] and len(runs)==1
    assert result['runtime_mode']=='free_service'
    assert bool(started)==start and runs[0]['status']==('running' if start else 'stopped')
    runtime=open_runtime(tmp_path/runs[0]['run_id'])
    try:
        assert runtime.initial_observations and runtime.free_service
        assert runtime.status()['service']['recovery_required'] is False
        assert runtime.state().rules.species_lock and runtime.state().rules.gender_lock
        assert not runtime.state().rules.battle_calc and not runtime.state().rules.native_messages
        assert not runtime.state().rules.links and not runtime.state().identities.document()['members']
        first,second=first_controls(runtime)
        assert first['control']['authority']=='hold'
        assert second['control']['authority']=='hold'
        assert runtime.paired_control_current() and not runtime.service_current()
    finally:runtime.close()


@pytest.mark.asyncio
async def test_unsupported_rules_cannot_start_or_register_a_prepared_run(tmp_path,monkeypatch):
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:[])
    monkeypatch.setattr(manager,'_save_registry',lambda value:pytest.fail('invalid run registered'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:contract('red','blue'))
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'invalid','rom_a':'a.gb','rom_b':'b.gb','rules':{'native_messages':True},'start':True}))
    assert response.status==400


@pytest.mark.asyncio
async def test_manager_refuses_a_pre_free_service_gen1_launcher(tmp_path,monkeypatch):
    from server.gen1_run_config import create_runtime

    run_id='run-test'
    runtime=create_runtime(tmp_path/run_id,contract('red','blue'))
    runtime.close()
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:[{'run_id':run_id,'name':'Held legacy run','tcp_port':5000}])
    request=SimpleNamespace(match_info={'run_id':run_id,'player':'a'},host='127.0.0.1:8000',query={})
    response=await manager.RunManager('127.0.0.1').handle_launcher(request)
    assert response.status==409
    assert json.loads(response.text)['error']=='Manager cannot launch a held-service Gen1 run; create a new Gen1 run'
