"""Required real-browser gate; no fake DOM and no ROM uploads."""
import asyncio
import json
import os
import shutil
import struct
import zlib
from pathlib import Path

import pytest
from aiohttp import web

from patch.tools.make_ups import _ups_encode
from server.patcher import TARGETS,patch_path,setup_patcher_routes
from server.templating import setup_templating

ROOT=Path(__file__).resolve().parents[2]


def corrupt_fixture(name,header,body,expected):
    source=b"abc"
    raw=b"UPS1"+header+body+struct.pack("<II",zlib.crc32(source),zlib.crc32(source))
    raw+=struct.pack("<I",zlib.crc32(raw))
    return {"name":name,"source":list(source),"patch":list(raw),"expected":expected}


@pytest.mark.asyncio
async def test_actual_browser_canonical_patching_downloads_and_refusal_matrix(tmp_path):
    await run_browser(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("variants",[("red","blue"),("blue","yellow"),("yellow","yellow")])
async def test_actual_browser_patches_only_the_reproduced_player_specific_upr_input(tmp_path,variants):
    from tests.integration.test_gen1_prepared_cartridges import prepared
    from server.gen1_prepared_cartridges import PreparedCartridges
    from server.gen1_patcher_targets import prepared_targets
    from tests.integration.test_upr_pinned import PRESETS
    directory=await asyncio.to_thread(prepared,tmp_path,variants,settings_changes=PRESETS["combined"])
    cartridges=await asyncio.to_thread(PreparedCartridges,directory)
    targets=prepared_targets(cartridges)
    await run_browser(tmp_path,prepared_data=targets,cartridges=cartridges)


async def run_browser(tmp_path,*,prepared_data=None,cartridges=None):
    node=os.environ.get("SLINK_NODE") or shutil.which("node")
    assert node,"required Node/Playwright browser runtime is unavailable"
    app=web.Application();setup_templating(app)
    setup_patcher_routes(app,sidebar_builder=lambda active:'',prepared_targets=lambda request:prepared_data or {})
    runner=web.AppRunner(app);await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
    try:
        targets=[]
        for slug,target in (prepared_data or {key:TARGETS[key] for key in ('rb-red','rb-blue','yellow')}).items():
            variant=target['variant']
            if prepared_data:
                source=cartridges.directory/'generation'/slug[-1]/'randomized.gbc'
                patch=tmp_path/(slug+'.ups');patch.write_bytes(target['patch_bytes'])
            else:
                source=ROOT/f"patch/build/gen1_{variant}{'.gbc' if variant=='yellow' else '.gb'}"
                patch=Path(patch_path(slug))
            targets.append({'slug':slug,'variant':variant,'source':str(source),
                'patch':str(patch),'final_sha256':target['patched_sha256']})
        codec=[corrupt_fixture('truncated variable integer',b'\0\0',b'', 'Truncated'),
            corrupt_fixture('oversized output',_ups_encode(3)+_ups_encode(64*1024*1024+1),b'','output size'),
            corrupt_fixture('wrong source length',_ups_encode(4)+_ups_encode(3),b'','source size'),
            corrupt_fixture('unterminated XOR run',_ups_encode(3)+_ups_encode(3),_ups_encode(0)+b'\x01','terminator'),
            corrupt_fixture('out-of-bounds XOR run',_ups_encode(3)+_ups_encode(3),_ups_encode(3)+b'\x01\0','outside')]
        config=tmp_path/'input.json'
        config.write_text(json.dumps({'url':f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}',
            'output':str(tmp_path),'targets':targets,'codec':codec,'prepared':prepared_data is not None}))
        env=dict(os.environ,TEMP=str(tmp_path),TMP=str(tmp_path),TMPDIR=str(tmp_path))
        process=await asyncio.create_subprocess_exec(node,str(ROOT/'tests/browser/gen1_patcher.cjs'),str(config),
            cwd=ROOT,env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await asyncio.wait_for(process.communicate(),120)
        (tmp_path/'browser.log').write_bytes(stdout+b'\n'+stderr)
        assert process.returncode==0,stderr.decode(errors='replace')
        result=json.loads((tmp_path/'result.json').read_text())
        assert result['passed'] and result['uploads']==0 and not result['page_errors']
        assert len(result['cases'])==(5 if prepared_data else 16)
    finally:await runner.cleanup()
