"""Complete 32KiB readbacks against each original cartridge SaveGameData routine."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from server.gen1_full_save import image
from tools.run_gb_gate import run_gate
from tools.verify_canonical_sources import verify

ROOT=Path(__file__).resolve().parents[2]
pytestmark=[pytest.mark.live,pytest.mark.slow,
            pytest.mark.skipif(os.environ.get('SLINK_LIVE')!='1',reason='explicit live emulator lane required')]


@pytest.mark.parametrize('variant',['red','blue','yellow'])
def test_held_full_save_matches_original_engine_for_every_cart_byte(variant):
    assert not verify()['failures']
    directory=Path(tempfile.mkdtemp(prefix='full-save-',dir=ROOT/'.cache'))
    result=directory/'result.json'
    passed,path,log=run_gate('lua/tests/test_gen1_full_save_gate.lua',rom_key=variant,quiet=True,
                             extra_env={'SLINK_FULLSAVE_RESULT':str(result)},timeout=100)
    assert passed,f'{path}\n{log[-4000:]}'
    document=json.loads(result.read_text())
    assert document['passed'] and len(document['cases'])==8
    for case in document['cases']:
        assert image(case['before']).hex().upper()==case['after_hex']==case['oracle_hex']
