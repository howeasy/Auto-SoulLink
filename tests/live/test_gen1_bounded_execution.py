"""Actual one-frame host primitive; generation/recovery authorization is modeled."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from tools.run_gb_gate import BIZHAWK_CONFIG, REPO, run_gate

pytestmark=[pytest.mark.live,pytest.mark.slow,
            pytest.mark.skipif(os.environ.get('SLINK_LIVE')!='1',reason='explicit live emulator lane required')]


@pytest.mark.parametrize('variant',['red','blue','yellow'])
@pytest.mark.parametrize('paused',[False,True])
def test_one_frame_then_verified_hold_preserves_pause_callbacks_and_refusal(variant,paused):
    directory=Path(tempfile.mkdtemp(prefix='bounded-frame-',dir=Path(REPO)/'.cache'))
    config=json.loads(Path(BIZHAWK_CONFIG).read_text(encoding='utf-8-sig'))
    config['Rewind']['Enabled']=False
    private=directory/'config.ini';private.write_text(json.dumps(config))
    output=directory/'result.json'
    spec=directory/'input.json';spec.write_text(json.dumps({'paused':paused,'output':output.as_posix()}))
    passed,path,log=run_gate('lua/tests/test_gen1_bounded_execution_gate.lua',rom_key=variant,quiet=True,timeout=50,
        config_base=str(private),extra_env={'SLINK_BOUNDED_INPUT':str(spec)})
    (directory/'gate.log').write_text(log)
    assert passed,f'{directory}\n{path}\n{log[-6000:]}'
    result=json.loads(output.read_text())
    assert result['passed'] and len(result['checks'])==30 and result['bus_callbacks']==30
    assert result['final']['host']['physical_stop_verified'] and result['final']['host']['user_paused'] is paused


@pytest.mark.parametrize('variants',[('red','blue'),('blue','yellow'),('yellow','yellow')],ids=lambda pair:'-'.join(pair))
def test_original_native_trade_runs_through_owned_single_frame_steps(variants):
    from tests.live.test_gen1_paired_native_trade import run_native_pair
    run_native_pair(variants,native_ui=True,companion=True,bounded_host=True)
