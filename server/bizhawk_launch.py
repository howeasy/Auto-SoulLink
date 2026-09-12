"""Prepare isolated emulator files; never edit a user's base config or save."""
import copy
import hashlib
import json
import os
import re
import subprocess
import io
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROFILES=json.loads((ROOT/'data/bizhawk_host_profiles.json').read_text())['profiles']
PATH_SYSTEMS={'gambatte':{'GB_GBC_SGB','GBL','GB','GBC','SGB'},'mgba':{'GBA'}}
SCHEMA='slink-bizhawk-launch-v1'


def isolated_configuration(source, profile, save_directory):
    if profile not in PATH_SYSTEMS or not isinstance(source,dict):
        raise ValueError('supported emulator profile and complete base config required')
    directory=Path(save_directory).resolve()
    config=copy.deepcopy(source)
    entries=config.get('PathEntries',{}).get('Paths')
    if not isinstance(entries,list):raise ValueError('base config lacks path entries')
    selected=[entry for entry in entries if isinstance(entry,dict) and entry.get('Type')=='Save RAM'
              and entry.get('System') in PATH_SYSTEMS[profile]]
    if not selected:raise ValueError('base config lacks this core family SaveRAM path')
    for entry in selected:entry['Path']=directory.as_posix()
    rewind=config.setdefault('Rewind',{})
    if not isinstance(rewind,dict):raise ValueError('invalid rewind configuration')
    rewind['Enabled']=False
    if profile=='gambatte':
        sync=config.setdefault('CoreSyncSettings',{}).setdefault(PROFILES[profile]['core_type'],{})
        if not isinstance(sync,dict):raise ValueError('invalid Gambatte sync settings')
        sync.setdefault('$type','BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy+GambatteSyncSettings, BizHawk.Emulation.Cores')
        sync['EqualLengthFrames']=False
    return config


def manifest(*,run_id,player,profile,rom_sha1,launcher):
    result={'schema':SCHEMA,'run_id':run_id,'player':player,
            'profile':profile,'rom_sha1':rom_sha1,
            'launcher_sha256':hashlib.sha256(launcher.encode('utf-8')).hexdigest()}
    validate_manifest(result)
    return result


def bundle(*,run_id,player,profile,rom_sha1,launcher):
    spec=manifest(run_id=run_id,player=player,profile=profile,rom_sha1=rom_sha1,launcher=launcher)
    output=io.BytesIO()
    instructions=('Extract these files into a folder inside your SLink installation.\n'
        'Run: python tools/launch_bizhawk.py --manifest PATH/TO/launch.json\n'
        'Choose your own cartridge and EmuHawk when prompted.\n'
        'The launcher uses a private configuration and SaveRAM directory for this run and player.\n'
        'The bundle contains no ROM, emulator, randomizer or saved game.\n')
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('launch.json',json.dumps(spec,indent=2)+'\n')
        archive.writestr('launcher.lua',launcher)
        archive.writestr('README.txt',instructions)
    return output.getvalue()


def validate_manifest(spec):
    if (not isinstance(spec,dict) or set(spec)!={'schema','run_id','player','profile','rom_sha1','launcher_sha256'}
            or spec['schema']!=SCHEMA or spec['profile'] not in PROFILES or spec['player'] not in ('a','b')
            or not isinstance(spec['run_id'],str) or not re.fullmatch('[0-9a-f]{32}',spec['run_id'])):
        raise ValueError('complete run/player emulator launch manifest required')
    for field,length in (('rom_sha1',40),('launcher_sha256',64)):
        if not isinstance(spec[field],str) or not re.fullmatch('[0-9a-f]{'+str(length)+'}',spec[field]):
            raise ValueError('complete admitted file digests required')


def prepare(root, spec, *, rom, launcher, base_config):
    validate_manifest(spec)
    rom_path,launcher_path,config_path=map(lambda value:Path(value).resolve(),(rom,launcher,base_config))
    data=rom_path.read_bytes()
    if not 0<len(data)<=64*1024*1024 or hashlib.sha1(data).hexdigest()!=spec['rom_sha1']:
        raise ValueError('ROM differs from the admitted final cartridge')
    script=launcher_path.read_text(encoding='utf-8').replace('\r\n','\n').encode('utf-8')
    if not 0<len(script)<=1024*1024 or hashlib.sha256(script).hexdigest()!=spec['launcher_sha256']:
        raise ValueError('launcher differs from its run manifest')
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    root=Path(root).resolve();home=root/spec['run_id']/spec['player'];directory=home/'emulator';saves=home/'SaveRAM'
    if not directory.resolve().is_relative_to(root) or not saves.resolve().is_relative_to(root):
        raise ValueError('launch outputs leave their owned root')
    generated=isolated_configuration(config,spec['profile'],saves)
    marker=directory/'launch.json'
    if marker.exists():
        if json.loads(marker.read_text())!=spec:raise ValueError('existing emulator directory belongs to another launch')
    elif directory.exists() and any(directory.iterdir()):
        raise ValueError('unowned nonempty emulator directory')
    elif saves.exists() and any(saves.iterdir()):
        raise ValueError('existing saves require their owned launch manifest')
    suffix='.gba' if spec['profile']=='mgba' else '.gbc' if rom_path.suffix.lower()=='.gbc' else '.gb'
    destination=directory/('game'+suffix)
    if any(path in (destination,directory/'launcher.lua',directory/'config.ini') for path in (rom_path,launcher_path,config_path)):
        raise ValueError('launch inputs cannot alias their outputs')
    if destination.exists() and destination.read_bytes()!=data:
        raise ValueError('staged cartridge changed outside its owner')
    directory.mkdir(parents=True,exist_ok=True);saves.mkdir(parents=True,exist_ok=True)
    if not destination.exists():destination.write_bytes(data)
    (directory/'launcher.lua').write_bytes(script)
    (directory/'config.ini').write_text(json.dumps(generated,indent=2)+'\n',encoding='utf-8')
    marker.write_text(json.dumps(spec,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return {'schema':SCHEMA,'cwd':str(directory),'profile':spec['profile'],
        'arguments':['--config=config.ini','--lua=launcher.lua',destination.name],
        'environment':{'SLINK_ROOT':str(ROOT),'SLINK_CLIENT_STORAGE_ROOT':str(root),'SLINK_SAVERAM_DIRECTORY':str(saves)},
        'save_directory':str(saves),'manifest':str(marker)}


def launch(plan, executable):
    path=Path(executable).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest()!=PROFILES[plan['profile']]['emulator_sha256']:
        raise ValueError('emulator executable differs from the qualified host')
    environment={**os.environ,**plan['environment']}
    return subprocess.Popen([str(path),*plan['arguments']],cwd=plan['cwd'],env=environment)
