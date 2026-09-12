import json

import pytest

from server import gen1_admission, manager
from server.gen1_run_config import open_runtime
from tests.unit.test_gen1_sessions import contract


class Request:
    def __init__(self,body):self.body=body
    async def json(self):return self.body


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
    assert bool(started)==start and runs[0]['status']==('running' if start else 'stopped')
    runtime=open_runtime(tmp_path/runs[0]['run_id'])
    try:
        assert runtime.initial_observations and runtime.state().rules.species_lock and runtime.state().rules.gender_lock
        assert not runtime.state().rules.battle_calc and not runtime.state().rules.native_messages
        assert not runtime.state().rules.links and not runtime.state().identities.document()['members']
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
