import copy
import hashlib
import io
import json
import zipfile

import pytest

from server.bizhawk_launch import (
    bundle,
    isolated_configuration,
    manifest,
    prepare,
    validate_manifest,
)
from tools.gen_bizhawk_host_profiles import TARGET, generated


def config():
    return {'PathEntries':{'Paths':[{'Type':'Save RAM','System':'GB_GBC_SGB','Path':'old'},
        {'Type':'Save RAM','System':'GBA','Path':'gba'},{'Type':'ROM','System':'GB_GBC_SGB','Path':'roms'}]},
        'Rewind':{'Enabled':True},'SoundEnabled':True,'Unrelated':{'user':'preference'}}


def inputs(tmp_path):
    rom=tmp_path/'user game.gb';rom.write_bytes(b'owned game fixture')
    launcher=tmp_path/'launcher.lua';launcher.write_text('-- owned launcher\n')
    base=tmp_path/'base.ini';base.write_text(json.dumps(config()))
    spec=manifest(run_id='a'*32,player='a',profile='gambatte',rom_sha1=hashlib.sha1(rom.read_bytes()).hexdigest(),
                  launcher=launcher.read_text())
    return spec,{'rom':rom,'launcher':launcher,'base_config':base}


def test_exported_pins_are_generated_from_the_shared_actuator():
    assert TARGET.read_text()==generated()


@pytest.mark.parametrize('profile',['gambatte','mgba'])
def test_private_config_changes_only_qualified_family_paths_and_required_controls(tmp_path,profile):
    source=config();before=copy.deepcopy(source);result=isolated_configuration(source,profile,tmp_path/'SaveRAM')
    assert source==before and result['Unrelated']==before['Unrelated'] and result['SoundEnabled'] is True
    paths=result['PathEntries']['Paths']
    assert paths[0 if profile=='gambatte' else 1]['Path']==(tmp_path/'SaveRAM').as_posix()
    assert paths[1 if profile=='gambatte' else 0]==before['PathEntries']['Paths'][1 if profile=='gambatte' else 0]
    assert paths[2]==before['PathEntries']['Paths'][2] and result['Rewind']['Enabled'] is False


def test_same_rom_players_get_separate_saves_and_original_inputs_are_preserved(tmp_path):
    spec,paths=inputs(tmp_path);before={name:path.read_bytes() for name,path in paths.items()};root=tmp_path/'clients'
    a=prepare(root,spec,**paths);b=prepare(root,{**spec,'player':'b'},**paths)
    assert a['save_directory']!=b['save_directory'] and a['cwd']!=b['cwd']
    assert a['arguments']==['--config=config.ini','--lua=launcher.lua','game.gb']
    from pathlib import Path
    save=Path(a['save_directory'])/'owned.SaveRAM';save.write_bytes(b'progress')
    assert prepare(root,spec,**paths)==a and save.read_bytes()==b'progress'
    assert all(path.read_bytes()==before[name] for name,path in paths.items())
    assert a['environment']['SLINK_SAVERAM_DIRECTORY']==a['save_directory']


@pytest.mark.parametrize('fault',['rom_hash','launcher_hash','player','run_id','profile','config','occupied','different_manifest'])
def test_unverified_or_unowned_setup_refuses_without_overwriting_sources(tmp_path,fault):
    spec,paths=inputs(tmp_path);root=tmp_path/'clients'
    if fault=='rom_hash':spec['rom_sha1']='0'*40
    elif fault=='launcher_hash':spec['launcher_sha256']='0'*64
    elif fault=='player':spec['player']='../elsewhere'
    elif fault=='run_id':spec['run_id']='../elsewhere'
    elif fault=='profile':spec['profile']='unknown'
    elif fault=='config':paths['base_config'].write_text('{}')
    elif fault=='occupied':
        directory=root/spec['run_id']/spec['player']/'emulator';directory.mkdir(parents=True)
        (directory/'other.txt').write_text('owned by someone else')
    else:
        prepare(root,spec,**paths);spec['launcher_sha256']='f'*64
        # Manifest mismatch is checked after current input verification.
        paths['launcher'].write_text('different');spec['launcher_sha256']=hashlib.sha256(b'different').hexdigest()
    before={name:path.read_bytes() for name,path in paths.items()}
    with pytest.raises(ValueError):prepare(root,spec,**paths)
    assert all(path.read_bytes()==before[name] for name,path in paths.items())


def test_bundle_contains_only_launch_metadata_script_and_instructions():
    raw=bundle(run_id='a'*32,player='b',profile='gambatte',rom_sha1='b'*40,launcher='-- bound\n')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist())=={'launch.json','launcher.lua','README.txt'}
        spec=json.loads(archive.read('launch.json'))
        assert spec['player']=='b' and spec['launcher_sha256']==hashlib.sha256(archive.read('launcher.lua')).hexdigest()


# --- P2A-2C: resumed runs import the predecessor's exact save under the run's own manifest ---
RESUME_PROJECTION='cartram-0498-8000-v1'


def save_bytes(seed=b'progress'):
    return bytes((seed[i%len(seed)]+i)%256 for i in range(0x8000))


def projection(data):
    return hashlib.sha256(data[0x0498:0x8000].hex().upper().encode()).hexdigest()


def resume_record(data,player='a'):
    return {'from_run':'b'*32,'required':{player:{'digest':projection(data),'projection':RESUME_PROJECTION}}}


def resumed_inputs(tmp_path,data):
    spec,paths=inputs(tmp_path)
    spec=manifest(run_id=spec['run_id'],player='a',profile='gambatte',rom_sha1=spec['rom_sha1'],
                  launcher=paths['launcher'].read_text(),resume=resume_record(data))
    source=tmp_path/'Pokemon - Red Version (USA, Europe).SaveRAM';source.write_bytes(data)
    return spec,paths,source


def test_manifest_carries_the_player_resume_contract_and_validates_it():
    data=save_bytes()
    spec=manifest(run_id='a'*32,player='a',profile='gambatte',rom_sha1='b'*40,launcher='x',resume=resume_record(data))
    assert spec['resume']=={'from_run':'b'*32,'required_digest':projection(data),'projection':RESUME_PROJECTION}
    validate_manifest(spec)
    for broken in ({**spec['resume'],'required_digest':'zz'},{**spec['resume'],'projection':'whole-file'},
                   {**spec['resume'],'extra':1},{'from_run':'b'*32}):
        with pytest.raises(ValueError):validate_manifest({**spec,'resume':broken})
    with pytest.raises(ValueError):  # the record lacks this player
        manifest(run_id='a'*32,player='b',profile='gambatte',rom_sha1='b'*40,launcher='x',resume=resume_record(data))
    raw=bundle(run_id='a'*32,player='a',profile='gambatte',rom_sha1='b'*40,launcher='x',resume=resume_record(data))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert json.loads(archive.read('launch.json'))['resume']==spec['resume']


def test_resume_save_import_copies_exact_bytes_under_the_owned_manifest_and_records_the_receipt(tmp_path):
    data=save_bytes();spec,paths,source=resumed_inputs(tmp_path,data);root=tmp_path/'clients'
    plan=prepare(root,spec,**paths,resume_save=source)
    from pathlib import Path
    copy_path=Path(plan['save_directory'])/source.name
    assert copy_path.read_bytes()==data and source.read_bytes()==data
    assert plan['resume_save']=={'source_path':str(source.resolve()),'source_sha256':hashlib.sha256(data).hexdigest(),
        'copy_sha256':hashlib.sha256(data).hexdigest(),'projection_digest':projection(data)}
    assert json.loads(Path(plan['manifest']).read_text())['resume']==spec['resume']  # the manifest binds the copy to this run
    assert prepare(root,spec,**paths,resume_save=source)==plan   # relaunch with the same file is idempotent
    assert prepare(root,spec,**paths)=={k:v for k,v in plan.items() if k!="resume_save"}  # without it, the import stays
    copy_path.write_bytes(save_bytes(b'played'))                 # played since: never overwritten by a re-import
    with pytest.raises(ValueError,match='already'):prepare(root,spec,**paths,resume_save=source)
    assert copy_path.read_bytes()==save_bytes(b'played')


@pytest.mark.parametrize('fault',['digest','size','no_contract','name','unowned_nonempty'])
def test_resume_save_import_refuses_without_touching_source_or_destination(tmp_path,fault):
    data=save_bytes();spec,paths,source=resumed_inputs(tmp_path,data);root=tmp_path/'clients'
    if fault=='digest':source.write_bytes(save_bytes(b'other'))
    elif fault=='size':source.write_bytes(data[:-1])
    elif fault=='no_contract':spec={k:v for k,v in spec.items() if k!='resume'}
    elif fault=='name':source=source.with_name('renamed.sav');source.write_bytes(data)
    else:
        saves=root/spec['run_id']/spec['player']/'SaveRAM';saves.mkdir(parents=True)
        (saves/'stray.SaveRAM').write_bytes(b'unowned')
    before=source.read_bytes()
    with pytest.raises(ValueError):prepare(root,spec,**paths,resume_save=source)
    assert source.read_bytes()==before
    saves=root/spec['run_id']/spec['player']/'SaveRAM'
    assert not (saves/source.name).exists() and not (root/spec['run_id']/spec['player']/'emulator'/'launch.json').exists()


def test_launch_tool_passes_the_resume_save_through_to_prepare(tmp_path,monkeypatch):
    import sys

    import tools.launch_bizhawk as tool
    data=save_bytes();spec,paths,source=resumed_inputs(tmp_path,data)
    (tmp_path/'launch.json').write_text(json.dumps(spec))
    seen={}
    monkeypatch.setattr(tool,'prepare',lambda root,spec,**kw:seen.update(kw) or {'ok':1})
    class Done:
        def wait(self):return 0
    monkeypatch.setattr(tool,'launch',lambda plan,exe:Done())
    monkeypatch.setattr(sys,'argv',['launch_bizhawk','--manifest',str(tmp_path/'launch.json'),'--rom',str(paths['rom']),
        '--emuhawk',str(tmp_path/'EmuHawk.exe'),'--root',str(tmp_path/'clients'),'--resume-save',str(source)])
    assert tool.main()==0 and seen['resume_save']==source
