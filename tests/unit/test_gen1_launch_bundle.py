import hashlib
import io
import json
from types import SimpleNamespace
import zipfile

import pytest
from lupa.lua54 import LuaRuntime

from server import manager
from server.gen1_run_config import create_runtime
from server.server import SLinkServer
from tests.unit.test_gen1_sessions import contract


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint',['server','manager'])
async def test_launcher_bundle_binds_the_run_and_keeps_initial_observation_selection(tmp_path,monkeypatch,endpoint):
    runtime=create_runtime(tmp_path/'run-test',contract('yellow','yellow'),free_service=endpoint=='manager')
    try:
        request=SimpleNamespace(match_info={'player':'b','run_id':'run-test'},host='127.0.0.1:8080',query={'bundle':'1'})
        before=runtime.journal.snapshot()
        if endpoint=='server':
            srv=SLinkServer(data_dir=str(tmp_path/'run-test'),gen1_runtime=runtime)
            srv._tcp_port=54321
            response=await srv.handle_launcher(request)
        else:
            monkeypatch.setattr(manager,'MANAGER_DIR',str(tmp_path))
            monkeypatch.setattr(manager,'_load_registry',lambda:[{'run_id':'run-test','name':'Test','tcp_port':54321}])
            response=await manager.RunManager('127.0.0.1').handle_launcher(request)
        assert response.status==200 and response.content_type=='application/zip'
        with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
            assert set(archive.namelist())=={'launch.json','launcher.lua','README.txt'}
            spec=json.loads(archive.read('launch.json'));script=archive.read('launcher.lua')
            assert spec['run_id']==runtime.journal.run_id and spec['player']=='b'
            assert spec['rom_sha1']==runtime.contract['players']['b']['final_rom_sha1']
            assert spec['launcher_sha256']==hashlib.sha256(script).hexdigest()
            line=next(line for line in script.decode().splitlines() if line.startswith('SLINK_RUNTIME_LAUNCH_JSON='))
            configuration=json.loads(LuaRuntime().eval(line.split('=',1)[1]))
            assert configuration['initial_observations'] is True
            assert configuration['mode']==('free_service' if endpoint=='manager' else 'held_service')
        assert runtime.journal.snapshot()==before
    finally:runtime.close()
