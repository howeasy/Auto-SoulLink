"""Manager creates a real RBY journal before its real server starts."""
import asyncio
import io
import json
import socket
import tempfile
from pathlib import Path
import zipfile

import aiohttp
import psutil
import pytest
from lupa.lua54 import LuaRuntime

from server import manager

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_manager_prepared_run_starts_real_server_and_serves_bound_bundle(monkeypatch):
    directory=Path(tempfile.mkdtemp(prefix='manager-gen1-',dir=ROOT/'.cache'))
    runs=[];ports=[];owned_pid=None
    for _ in range(2):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));ports.append(probe.getsockname()[1])
    monkeypatch.setattr(manager,'MANAGER_DIR',str(directory))
    monkeypatch.setattr(manager,'_load_registry',lambda:runs.copy())
    monkeypatch.setattr(manager,'_save_registry',lambda value:runs.__setitem__(slice(None),value))
    monkeypatch.setattr(manager,'_next_ports',lambda value:tuple(ports))
    class Request:
        async def json(self):
            return {'name':'Managed RBY qualification','rom_a':str(ROOT/'patch/build/gen1_red.gb'),
                    'rom_b':str(ROOT/'patch/build/gen1_yellow.gbc'),'start':True,'rules':{'type_lock':True}}
    try:
        response=await manager.RunManager('127.0.0.1',manager_port=0).handle_create_gen1(Request())
        result=json.loads(response.text)
        assert response.status==200,result
        assert result['runtime_mode']=='free_service'
        run=result['run'];owned_pid=run['pid'];run_dir=directory/run['run_id']
        spec=json.loads((run_dir/'gen1_runtime.json').read_text())
        assert spec['initial_observations'] is True and spec['free_service'] is True
        async with aiohttp.ClientSession() as session:
            deadline=asyncio.get_running_loop().time()+20
            while True:
                try:
                    async with session.get(f'http://127.0.0.1:{ports[1]}/launcher/a?bundle=1') as reply:
                        assert reply.status==200
                        raw=await reply.read()
                    break
                except aiohttp.ClientConnectionError:
                    assert asyncio.get_running_loop().time()<deadline,(run_dir/'spawn.log').read_text(errors='replace')
                    await asyncio.sleep(.05)
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            manifest=json.loads(bundle.read('launch.json'))
            launcher=bundle.read('launcher.lua').decode()
            assert manifest['run_id']==spec['run_id'] and manifest['player']=='a'
            assert manifest['rom_sha1']==spec['contract']['players']['a']['final_rom_sha1']
            line=next(row for row in launcher.splitlines() if row.startswith('SLINK_RUNTIME_LAUNCH_JSON='))
            configuration=json.loads(LuaRuntime().eval(line.split('=',1)[1]))
            assert configuration['mode']=='free_service'
            assert 'lua/gen1_observation_loop.lua' in {entry['path'] for entry in configuration['files']}
        assert not (run_dir/'links.json').exists()
    finally:
        if owned_pid and psutil.pid_exists(owned_pid):
            process=psutil.Process(owned_pid);args=process.cmdline()
            assert 'server.server' in args and Path(args[args.index('--data-dir')+1]).resolve().is_relative_to(directory)
            await asyncio.to_thread(manager._kill_run,owned_pid)
