import json
import os
import tempfile
from pathlib import Path

import pytest

from server.gen1_engine_signals import validate_signal
from tests.unit.test_gen1_inventory_observation import party_point
from tests.unit.test_gen1_party_codec import make_blob
from server.gen1_party_codec import PartyCodec
from server.gen1_initial_observation import display_name
from tools.run_gb_gate import run_gate

ROOT=Path(__file__).resolve().parents[2]
pytestmark=[pytest.mark.live,pytest.mark.slow,
    pytest.mark.skipif(os.environ.get('SLINK_LIVE')!='1',reason='explicit live emulator lane required')]


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_original_faint_sources_are_captured_before_original_healing(variant):
    directory=Path(tempfile.mkdtemp(prefix='engine-signal-',dir=ROOT/'.cache'))
    spec=directory/'input.json';result=directory/'result.json'
    party=party_point(variant,[make_blob(PartyCodec(variant))])['fields']['party']
    spec.write_text(json.dumps({'party_hex':party}))
    passed,path,log=run_gate('lua/tests/test_gen1_engine_signals_gate.lua',rom_key=variant,quiet=True,timeout=130,
        extra_env={'SLINK_SIGNAL_INPUT':str(spec),'SLINK_SIGNAL_RESULT':str(result)})
    assert passed,f'{path}\n{log[-5000:]}'
    value=json.loads(result.read_text());assert value['passed'] and len(value['cases'])==3
    for case in value['cases']:
        assert case['unchanged'] is True
        point=case['signals'][0]['point'];identity={'ot_id':point['player_id_hex'],
            'trainer_name':display_name(bytes.fromhex(point['trainer_hex']))}
        decoded=[validate_signal(row,variant,identity) for row in case['signals']]
        if case['cause']=='starter':
            assert [row['kind'] for row in decoded]==['starter_begin','starter_end']
            assert case['signals'][0]['sp']==case['signals'][1]['sp']
        else:assert decoded[0]['kind']=='faint' and decoded[0]['cause']==case['cause']
        assert int.from_bytes(bytes.fromhex(case['after_healing'])[9:11],'big')>0
