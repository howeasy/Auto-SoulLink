import json
import os
import tempfile
from pathlib import Path

import pytest

from server.gen1_command_receipts import verify_force_faint_receipt
from server.gen1_engine_signals import validate_signal
from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_party_codec import make_blob
from tools.run_gb_gate import run_gate

ROOT=Path(__file__).resolve().parents[2]
pytestmark=[pytest.mark.live,pytest.mark.slow,
    pytest.mark.skipif(os.environ.get('SLINK_LIVE')!='1',reason='explicit live emulator lane required')]


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_original_inventory_outcomes_and_physical_faint_executor(variant):
    directory=Path(tempfile.mkdtemp(prefix='ball-faint-',dir=ROOT/'.cache'))
    spec=directory/'input.json';result=directory/'result.json'
    spec.write_text(json.dumps({'party_hex':party_point(variant,[make_blob(PartyCodec(variant))])['fields']['party']}))
    passed,path,log=run_gate('lua/tests/test_gen1_ball_activation_gate.lua',rom_key=variant,quiet=True,timeout=100,
        extra_env={'SLINK_BALL_INPUT':str(spec),'SLINK_BALL_RESULT':str(result)})
    assert passed,f'{path}\n{log[-4000:]}'
    value=json.loads(result.read_text());assert value['passed'] and len(value['cases'])==5
    for case in value['cases']:
        assert case['unchanged']
        for event in case['events']:
            signal=event['payload']['payload']['signals'][0];point=signal['point']
            identity={'ot_id':point['player_id_hex'],'trainer_name':display_name(bytes.fromhex(point['trainer_hex']))}
            assert validate_signal(signal,variant,identity)['kind']=='pokeballs_obtained'
    before=value['receipt']['before']
    verify_force_faint_receipt(value['command'],value['receipt'],variant=variant,
        identity={'ot_id':before['save_id'],'trainer_name':before['save_name']})
