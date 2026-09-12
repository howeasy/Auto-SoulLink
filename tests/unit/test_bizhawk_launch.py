import copy
import hashlib
import io
import json
import zipfile

import pytest

from server.bizhawk_launch import bundle, isolated_configuration, manifest, prepare
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
