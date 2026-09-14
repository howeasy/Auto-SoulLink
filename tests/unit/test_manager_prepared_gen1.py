import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server import (
    gen1_admission,
    gen1_prepared_cartridges,
    gen1_run_config,
    gen1_run_resume,
    gen1_upr_pipeline,
    manager,
)
from server.adapters.gen1_rom_scan import GEN1_ROM_SIZE
from server.gen1_run_config import create_runtime, open_runtime
from server.gen1_runtime_admission import METADATA_SCHEMA, PROTOCOL
from server.protocol_journal import JournalError
from tests.unit.test_gen1_sessions import contract


class Request:
    def __init__(self,body,match_info=None):
        self.body=body
        self.match_info=match_info or {}
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
    rom_a,rom_b=_cartridges(tmp_path)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'Fresh Yellow pair','rom_a':rom_a,'rom_b':rom_b,'rules':{'species_lock':True,'gender_lock':True},'start':start}))
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
    rom_a,rom_b=_cartridges(tmp_path)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'invalid','rom_a':rom_a,'rom_b':rom_b,'rules':rules,'start':True}))
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


@pytest.mark.asyncio
async def test_manager_serves_the_final_cartridge_only_for_a_native_run(tmp_path,monkeypatch):
    """The remote player needs the exact admitted bytes: the run's own verified prepared pair
    serves them, and a run with no native pair has nothing to hand over."""
    runs=[{'run_id':'run_native','name':'Native','tcp_port':5001,'http_port':8081,'status':'stopped',
        'native_trade':True,'cartridges':{'a':{'variant':'red'},'b':{'variant':'blue'}}}]
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(gen1_prepared_cartridges,'PreparedCartridges',_PreparedPair)
    (tmp_path/'run_native'/'prepared').mkdir(parents=True)
    handler=manager.RunManager('127.0.0.1')
    response=await handler.handle_run_cartridge(Request({},match_info={'run_id':'run_native','player':'b'}))
    expected=_PreparedPair(tmp_path/'run_native'/'prepared').rom('b')
    assert response.status==200 and response.body==expected
    assert response.headers['X-SLink-ROM-SHA1']==hashlib.sha1(expected).hexdigest()
    assert response.headers['Content-Disposition']=='attachment; filename="slink_blue_b.gb"'
    runs[0]['native_trade']=False
    assert (await handler.handle_run_cartridge(Request({},match_info={'run_id':'run_native','player':'b'}))).status==404
    runs[0]['native_trade']=True
    assert (await handler.handle_run_cartridge(Request({},match_info={'run_id':'run_native','player':'c'}))).status==404
    assert (await handler.handle_run_cartridge(Request({},match_info={'run_id':'run_missing','player':'a'}))).status==404


def test_the_startup_banner_names_the_partner_address_and_the_firewall(monkeypatch):
    """Two humans, two machines: 'localhost' is useless to the partner, so a 0.0.0.0 bind has
    to print the LAN URL and say which ports the firewall must allow."""
    monkeypatch.setattr(manager,'_lan_addresses',lambda:['192.168.1.50'])
    lines=manager.startup_banner('0.0.0.0',8090)
    assert lines[0]=='SLink Manager running at http://localhost:8090/'
    assert 'Partner joins at: http://192.168.1.50:8090/' in lines
    assert any('firewall' in line and '8090' in line for line in lines)
    monkeypatch.setattr(manager,'_lan_addresses',lambda:[])
    assert not any('Partner joins at:' in line for line in manager.startup_banner('0.0.0.0',8090))
    assert not any('Partner joins at:' in line for line in manager.startup_banner('127.0.0.1',8090))
    assert manager.startup_banner('10.0.0.7',9000)[0]=='SLink Manager running at http://10.0.0.7:9000/'


@pytest.mark.asyncio
async def test_manager_refuses_a_cartridge_path_that_does_not_exist(tmp_path,monkeypatch):
    """A mistyped path is the caller's error: 400 naming it, and admission never runs (it used to
    surface as a 500 from the FileNotFoundError raised inside clean_contract)."""
    runs=[]
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:pytest.fail('nothing may be registered'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:pytest.fail('admission must not run'))
    missing=str(tmp_path/'never-written.gb')
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request(
        _fastest_text_request({}, missing, str(tmp_path/'b.gb'))))
    error=_json_text(response)
    assert response.status==400 and 'cartridge file not found' in error and missing in error
    assert runs==[] and _run_directories(tmp_path)==[]


@pytest.mark.asyncio
async def test_manager_refuses_a_directory_as_a_cartridge_path(tmp_path,monkeypatch):
    runs=[]
    directory=tmp_path/'cartridge-dir'
    directory.mkdir()
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:pytest.fail('nothing may be registered'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:pytest.fail('admission must not run'))
    _rom_a,rom_b=_cartridges(tmp_path)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request(
        _fastest_text_request({}, str(directory), rom_b)))
    error=_json_text(response)
    assert response.status==400 and 'cartridge file not found' in error and str(directory) in error
    assert runs==[] and _run_directories(tmp_path)==[]


def _run_directories(tmp_path):
    """The run directories under the patched MANAGER_DIR (tests/conftest.py always makes `data`)."""
    return sorted(p.name for p in tmp_path.iterdir() if p.name.startswith('run_'))


def _cartridges(tmp_path):
    """Real (if minimal) cartridge paths: the handler refuses a path that is not an existing file,
    so the happy paths must hand it files even though admission itself is stubbed."""
    paths = []
    for name in ('a.gb', 'b.gb'):
        path = tmp_path / name
        path.write_bytes(b'\x00' * 16)
        paths.append(str(path))
    return paths


class _PreparedPair:
    """A synthetic prepared pair: contract-shaped metadata and a placeholder image, no real ROM.

    `manifest`/`rom` exist so the runtime's native binding gets as far as reading the pair; what
    it then refuses is the image itself (see test_create_runtime_needs_a_real_cartridge_image).
    """

    def __init__(self,directory):self.directory=Path(directory)
    def contract(self):
        published=contract('red','blue')
        for player in published['players'].values():   # a native pair must claim the trade capability
            player['capabilities']={**player['capabilities'],'pc_trade':True,'panel':True,'sfx':True}
        return published
    def validate_contract(self,value):
        assert value==self.contract()
        return value['players']
    def manifest(self,player):return {'final_sha1':self.contract()['players'][player]['final_rom_sha1']}
    def rom(self,player):return bytes(GEN1_ROM_SIZE)   # blank: not a cartridge, only the right size


_RULE_KEYS=('species_lock','gender_lock','type_lock','explode_mode','rival_team_swap','overworld_presence',
    'native_messages','native_sounds','battle_calc','pc_trade_npc')


class _Runtime:
    """The runtime the create handler reads rules from and closes; no journal is opened."""

    def __init__(self):self.closed=False
    def state(self):return SimpleNamespace(rules=SimpleNamespace(**dict.fromkeys(_RULE_KEYS,False)))
    def close(self):self.closed=True


def _fastest_text_request(body, rom_a='a.gb', rom_b='b.gb'):
    return {
        'name':'Fastest text pair','rom_a':rom_a,'rom_b':rom_b,'rules':{},'start':False,'native':True,
        **body}


def _manager_with_runtime(monkeypatch,tmp_path,runs,runtime_calls,create_runtime=None):
    """Wire the registry, admission and runtime fakes the create handler needs."""
    def record(directory,contract,**options):
        runtime_calls.append((Path(directory),contract,options))
        return _Runtime()
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:runs.__setitem__(slice(None),value))
    monkeypatch.setattr(manager,'_spawn_run',lambda *args,**kwargs:pytest.fail('this run must not start'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:contract('red','blue'))
    monkeypatch.setattr(gen1_run_config,'create_runtime',create_runtime or record)
    monkeypatch.setattr(gen1_prepared_cartridges,'PreparedCartridges',_PreparedPair)


@pytest.mark.asyncio
async def test_manager_fastest_text_plumbs_the_policy_preset_pair_into_the_runtime(tmp_path,monkeypatch):
    """Handler plumbing for `fastest_text: true`: which producer runs, with which settings and
    seeds, and what the handler then hands the runtime. The runtime itself is stubbed here on
    purpose — it cannot be satisfied by a synthetic pair (see
    test_create_runtime_needs_a_real_cartridge_image_for_a_native_pair), so this test pins the
    handler's half of the contract and nothing more."""
    from server.gen1_upr_policy import build_preset
    preset=build_preset({'currentMiscTweaks':8})
    calls=[]
    runtime_calls=[]
    runs=[]
    def prepare_pair(jar,settings,sources,directory,*,seeds,java='java',custom_names=None):
        calls.append((jar,settings,sources,Path(directory),seeds))
        Path(directory).mkdir(parents=True)
        return {'status':'prepared_requires_runtime_admission'}
    monkeypatch.setattr(gen1_upr_pipeline,'prepare_pair',prepare_pair)
    monkeypatch.setattr(gen1_prepared_cartridges,'stage_canonical_pair',
        lambda *args,**kwargs:pytest.fail('the canonical pair must not be staged for fastest text'))
    monkeypatch.setenv('SLINK_UPR_JAR','C:/dummy/upr.jar')
    _manager_with_runtime(monkeypatch,tmp_path,runs,runtime_calls)
    rom_a,rom_b=_cartridges(tmp_path)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request(
        _fastest_text_request({'fastest_text':True}, rom_a, rom_b)))
    result=json.loads(response.text)
    assert response.status==200 and result['ok'] is True and len(runs)==1
    assert runs[0]['fastest_text'] is True and runs[0]['native_trade'] is True
    assert len(calls)==1
    jar,settings,sources,directory,seeds=calls[0]
    assert jar=='C:/dummy/upr.jar' and settings==preset and sources=={'a':rom_a,'b':rom_b}
    assert directory==tmp_path/runs[0]['run_id']/'prepared' and seeds=={'a':'123456789','b':'987654321'}
    assert (tmp_path/runs[0]['run_id']/'fastest-text.rnqs').read_bytes()==preset   # the exact settings stay with the run
    assert len(runtime_calls)==1 and runtime_calls[0][2]['native_trade'] is True
    assert isinstance(runtime_calls[0][2]['prepared_cartridges'],_PreparedPair)


@pytest.mark.asyncio
async def test_manager_refuses_fastest_text_without_native_and_leaves_no_run_directory(tmp_path,monkeypatch):
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:[])
    monkeypatch.setattr(manager,'_save_registry',lambda value:pytest.fail('invalid run registered'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:contract('red','blue'))
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request(_fastest_text_request(
        {'fastest_text':True,'native':False}, *_cartridges(tmp_path))))
    assert response.status==400 and 'fastest_text requires native' in _json_text(response)
    assert [p.name for p in tmp_path.iterdir() if p.is_dir() and p.name.startswith('run_')]==[]


@pytest.mark.asyncio
async def test_manager_without_fastest_text_still_stages_the_canonical_pair(tmp_path,monkeypatch):
    staged=[]
    runtime_calls=[]
    runs=[]
    def stage_canonical_pair(directory,clean_paths):
        staged.append((Path(directory),clean_paths))
        Path(directory).mkdir(parents=True)
        return Path(directory)
    monkeypatch.setattr(gen1_prepared_cartridges,'stage_canonical_pair',stage_canonical_pair)
    monkeypatch.setattr(gen1_upr_pipeline,'prepare_pair',
        lambda *args,**kwargs:pytest.fail('UPR must not run without fastest text'))
    _manager_with_runtime(monkeypatch,tmp_path,runs,runtime_calls)
    rom_a,rom_b=_cartridges(tmp_path)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request(
        _fastest_text_request({}, rom_a, rom_b)))
    result=json.loads(response.text)
    assert response.status==200 and result['ok'] is True
    assert len(staged)==1 and staged[0][1]=={'a':rom_a,'b':rom_b}
    assert runs[0]['native_trade'] is True and runs[0]['fastest_text'] is False
    assert len(runtime_calls)==1 and runtime_calls[0][2]['native_trade'] is True


@pytest.mark.asyncio
async def test_manager_plumbs_the_exact_body_the_gen1_create_ui_posts(tmp_path,monkeypatch):
    """Handler plumbing for the body manager.html createRun() posts verbatim for a filled Gen 1
    pair: the six rule keys create_runtime allows (native_sounds forced off), native, start and
    fastest_text. The runtime is stubbed here for the same reason as the fastest_text test."""
    rules={'species_lock':True,'gender_lock':False,'type_lock':True,'explode_mode':False,
        'rival_team_swap':True,'pc_trade_npc':False,'native_sounds':False}
    staged=[]
    runtime_calls=[]
    runs=[]
    def stage_canonical_pair(directory,clean_paths):
        staged.append((Path(directory),clean_paths))
        Path(directory).mkdir(parents=True)
        return Path(directory)
    monkeypatch.setattr(gen1_prepared_cartridges,'stage_canonical_pair',stage_canonical_pair)
    _manager_with_runtime(monkeypatch,tmp_path,runs,runtime_calls)
    async def spawn(*args,**kwargs):return 12345   # the UI body starts the run
    monkeypatch.setattr(manager,'_spawn_run',spawn)
    rom_a,rom_b=_cartridges(tmp_path)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'Gen 1 pair','rom_a':rom_a,'rom_b':rom_b,'rules':rules,'start':True,'native':True,
        'fastest_text':False}))
    result=json.loads(response.text)
    assert response.status==200 and result['ok'] is True and result['native_trade'] is True
    assert len(staged)==1 and len(runtime_calls)==1
    options=runtime_calls[0][2]
    assert options['rule_options']==rules and options['native_trade'] is True
    assert runs[0]['status']=='running' and runs[0]['native_trade'] is True


class _Audit:
    """A predecessor audit that passed; the mismatch refusal must fire before it matters."""
    ok=True
    reasons=()
    details=None
    def resume_record(self):return {'from_run':'run_pred','contract_hash':'deadbeef','required':[]}


@pytest.mark.asyncio
async def test_manager_refuses_a_resume_that_changes_the_fastest_text_setting(tmp_path,monkeypatch):
    """A resume inherits the predecessor's prepared pair, so switching fastest_text at resume
    time is refused before any staging - and the real create_runtime is never reached."""
    predecessor={'run_id':'run_pred','name':'Predecessor','tcp_port':5000,'http_port':8080,
        'status':'stopped','native_trade':True,'fastest_text':False}
    runs=[predecessor]
    staged=[]
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:pytest.fail('no run may be registered'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:contract('red','blue'))
    monkeypatch.setattr(gen1_run_resume,'audit_predecessor',lambda *args,**kwargs:_Audit())
    monkeypatch.setattr(gen1_prepared_cartridges,'stage_canonical_pair',lambda *args,**kwargs:staged.append('canonical'))
    monkeypatch.setattr(gen1_upr_pipeline,'prepare_pair',lambda *args,**kwargs:staged.append('upr'))
    rom_a,rom_b=_cartridges(tmp_path)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'Changed setting','rom_a':rom_a,'rom_b':rom_b,'rules':{},'start':False,'native':True,
        'fastest_text':True,'resume_from':'run_pred'}))
    assert response.status==400 and 'must keep the predecessor fastest_text' in _json_text(response)
    assert staged==[] and runs==[predecessor]
    assert _run_directories(tmp_path)==[]   # no run directory was ever made


@pytest.mark.asyncio
async def test_manager_removes_the_staged_directory_when_runtime_creation_fails(tmp_path,monkeypatch):
    """The window from staging to the registry commit owns the directory: a create_runtime
    failure must leave neither the half-built run nor a registry entry."""
    runs=[]
    runtime_calls=[]
    def create_runtime(directory,contract,**options):
        runtime_calls.append((Path(directory),contract,options))
        raise ValueError('runtime creation failed after staging')
    def stage_canonical_pair(directory,clean_paths):
        Path(directory).mkdir(parents=True)
        return Path(directory)
    monkeypatch.setattr(gen1_prepared_cartridges,'stage_canonical_pair',stage_canonical_pair)
    _manager_with_runtime(monkeypatch,tmp_path,runs,runtime_calls,create_runtime=create_runtime)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request(
        _fastest_text_request({}, *_cartridges(tmp_path))))
    assert response.status==400 and 'after staging' in _json_text(response)
    assert len(runtime_calls)==1 and runs==[]
    assert _run_directories(tmp_path)==[]   # the half-built run directory is gone


def test_create_runtime_needs_a_real_cartridge_image_for_a_native_pair(tmp_path,monkeypatch):
    """Why the plumbing tests stub the runtime: `native_trade=True` makes Gen1Runtime install the
    native binding (server/gen1_runtime.py:184 -> gen1_native_binding.py:41-46), which reads the
    pair's ACTUAL cartridge bytes through TradeResultRules.from_rom. Measured refusals as the fake
    image gets less blank: a blank 1 MiB image -> "not a supported Gen 1 title"; a titled one ->
    "HM move table terminator differs"; that byte patched too -> "EvosMovesPointerTable entry 0
    points outside the bank window". Passing it means counterfeiting a whole pret cartridge, so
    the boundary is documented here instead of assumed by the tests above."""
    run=tmp_path/'run_boundary'
    (run/'prepared').mkdir(parents=True)
    pair=_PreparedPair(run/'prepared')
    monkeypatch.setattr(gen1_prepared_cartridges,'PreparedCartridges',_PreparedPair)
    with pytest.raises(JournalError,match="native ROM differs from the admitted contract") as refusal:
        create_runtime(run,pair.contract(),prepared_cartridges=pair,native_trade=True,free_service=True)
    assert 'not a supported Gen 1 title' in str(refusal.value)   # the fake image is not a cartridge


@pytest.mark.asyncio
async def test_manager_refuses_a_rule_key_the_gen1_runtime_does_not_accept(tmp_path,monkeypatch):
    """The allowed rule set belongs to the runtime (gen1_run_config.py:117-123), so an extra key
    is refused by the REAL create_runtime as a 400 - the handler forwards rules untouched, and
    the F4 window removes the half-staged directory on the way out."""
    runs=[]
    staged=[]
    def stage_canonical_pair(directory,clean_paths):
        staged.append((Path(directory),clean_paths))
        Path(directory).mkdir(parents=True)
        return Path(directory)
    monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:pytest.fail('nothing may be registered'))
    monkeypatch.setattr(gen1_admission,'clean_contract',lambda paths:contract('red','blue'))
    monkeypatch.setattr(gen1_prepared_cartridges,'PreparedCartridges',_PreparedPair)
    monkeypatch.setattr(gen1_prepared_cartridges,'stage_canonical_pair',stage_canonical_pair)
    rom_a,rom_b=_cartridges(tmp_path)
    response=await manager.RunManager('127.0.0.1').handle_create_gen1(Request({
        'name':'Extra rule key','rom_a':rom_a,'rom_b':rom_b,'rules':{'species_lock':True,'overworld_presence':True},
        'start':False,'native':True}))
    assert response.status==400 and 'explicit supported Gen1 rule options required' in _json_text(response)
    assert len(staged)==1 and runs==[]
    assert _run_directories(tmp_path)==[]   # the refusal happens before anything is kept
