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
@pytest.mark.parametrize('rules',[{'native_messages':True},{'native_sounds':True}])
async def test_unsupported_rules_cannot_start_or_register_a_prepared_run(tmp_path,monkeypatch,rules):
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:[])
    monkeypatch.setattr(manager,'_save_registry',lambda value:pytest.fail('invalid run registered'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:contract('red','blue'))
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'invalid','rom_a':'a.gb','rom_b':'b.gb','rules':rules,'start':True}))
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


@pytest.mark.asyncio
async def test_manager_native_run_stages_the_canonical_pair_from_clean_inputs_and_selects_native_trade(tmp_path,monkeypatch):
    """`native: true` keeps clean_contract's admission of the user's CLEAN cartridges, derives the
    hash-pinned canonical companion pair inside the run, selects native_trade with it, persists the
    selection, and the run's launcher then carries the native manifest."""
    import json as _json
    from pathlib import Path
    from server.gen1_cartridge_profiles import companion_profiles
    from server.gen1_launcher import configuration
    lock=_json.loads((Path(manager.__file__).resolve().parents[1]/'data/pret_sources.lock.json').read_text())
    clean=Path(manager.__file__).resolve().parents[1]/lock['clean_roms']['pokeyellow']['filename']
    if not clean.is_file():pytest.skip('legal clean Yellow cartridge required')
    runs=[]
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:runs.__setitem__(slice(None),value))
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'Native Yellow pair','rom_a':str(clean),'rom_b':str(clean),'rules':{},'start':False,'native':True}))
    result=_json.loads(response.text)
    assert response.status==200 and result['ok'] and result['native_trade'] is True and runs[0]['native_trade'] is True
    expected=companion_profiles()['yellow']['final_rom_sha1']
    assert all(c['final_rom_sha1']==expected for c in runs[0]['cartridges'].values())   # the companion pair, not the clean inputs
    directory=tmp_path/runs[0]['run_id']
    assert (directory/'prepared/prepared-artifacts.json').is_file() and (directory/'prepared/final/a/slink_yellow.gb').is_file()
    runtime=open_runtime(directory)
    try:
        assert runtime.native_trade and runtime.free_service and runtime.prepared_cartridges.provenance=='canonical_companion'
        launch=configuration(runtime,'b')
        assert launch['mode']=='free_service' and launch['native_manifest']['final_sha1']==expected
        assert launch['native_manifest']['output']=='final/b/slink_yellow.gb'
    finally:runtime.close()


@pytest.mark.asyncio
async def test_manager_native_run_refuses_a_patched_input_and_leaves_no_run_directory(tmp_path,monkeypatch):
    runs=[]
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:pytest.fail('invalid run registered'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:contract('yellow','yellow'))   # admission stubbed...
    bogus=tmp_path/'not-clean.gbc';bogus.write_bytes(b'\0'*1024)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'bad','rom_a':str(bogus),'rom_b':str(bogus),'rules':{},'start':False,'native':True}))
    assert response.status==400 and 'admitted clean cartridge' in _json_text(response)        # ...the staging is not
    assert [p.name for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith('run_')]==[]


def _json_text(response):
    import json as _json
    return _json.loads(response.text)['error']
