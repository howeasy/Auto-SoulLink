import json
import os
from pathlib import Path
import tempfile

import pytest

from server.gen1_capture_receipt import decode_capture
from server.gen1_initial_observation import display_name
from server.gen1_party_codec import PartyCodec
from tests.unit.test_gen1_capture_receipt import owned, party_bytes, box_bytes
from tools.run_gb_gate import run_gate
from tools.verify_canonical_sources import verify

ROOT=Path(__file__).resolve().parents[2]
pytestmark=[pytest.mark.live,pytest.mark.slow,pytest.mark.skipif(os.environ.get('SLINK_LIVE')!='1',reason='explicit live emulator lane required')]


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_original_party_and_box_delivery_match_source_receipts(variant):
    assert not verify()['failures']
    directory=Path(tempfile.mkdtemp(prefix='capture-live-',dir=ROOT/'.cache'));input_path=directory/'input.json';output=directory/'result.json'
    codec=PartyCodec(variant);cases=[]
    for destination,count in [('party',5),('box',6)]:
        old=bytearray(owned(codec,1,start=20)[0]);old[3]=old[33]
        cases.append({'destination':destination,'species':153,'party_hex':party_bytes(owned(codec,count)).hex().upper(),
            'box_hex':box_bytes([bytes(old[:33]+old[44:])]).hex().upper()})
    if variant=='yellow':cases.append({**cases[-1],'species':0x26})
    input_path.write_text(json.dumps({'cases':cases}))
    passed,path,log=run_gate('lua/tests/test_gen1_capture_gate.lua',rom_key=variant,quiet=True,timeout=100,
        extra_env={'SLINK_CAPTURE_INPUT':str(input_path),'SLINK_CAPTURE_RESULT':str(output)})
    assert passed,f'{path}\n{log[-3000:]}'
    result=json.loads(output.read_text());assert result['passed'] and len(result['cases'])==len(cases)
    for expected,case in zip(cases,result['cases'],strict=True):
        assert case['observer_equal'] and case['frames']>0
        signals={row['kind']:row for row in case['signals']};where=case['destination']
        before=signals[where+'_begin'];after=signals[where+'_end'];point=before['point']
        identity={'ot_id':point['player_id_hex'],'trainer_name':display_name(bytes.fromhex(point['trainer_hex']))}
        decoded=decode_capture({'destination':where,'begin':before,'end':after},variant,identity)
        assert decoded['destination']==where and decoded['species_index']==expected['species']
