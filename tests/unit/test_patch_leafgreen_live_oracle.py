"""LG harness address/ROM-table guards, no emulator."""
import pytest

from tests.unit.test_patch_leafgreen_live import lg_transform
from tests.unit.test_patch_sound_live import sound_problems

SOUND_CAPTURE = 'HELPER: [gen3] phase field frame=778 map=(3,1)\nSOUND_CALL kind=se seq=1 id=25\nSOUND_CALL kind=m4a seq=1 id=25\nSOUND_ACTIVE op=19 id=25 seq=1 player=03007340 header=086B548C status=00000001 clock=1->2\nSOUND_CALL kind=fanfare seq=2 id=257\nSOUND_CALL kind=m4a seq=2 id=257\nSOUND_ACTIVE op=9 id=257 seq=2 player=03007380 header=086BC674 status=0000001F clock=1->2\nFANFARE_RELEASE counter=77->0 paused=1->0 task=1->0\nSOUND_REFUSED case=invalid_se seq=3 status=3 reason=2 se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch=7\nSOUND_REFUSED case=invalid_fanfare seq=4 status=3 reason=2 se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch=7\nSOUND_REFUSED case=unarmed_epoch seq=5 status=3 reason=13 se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch=0\nSOUND_REFUSED case=stale_epoch seq=6 status=3 reason=12 se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch=8\nSOUND_SCOPE: native routine/player/task RAM evidence only; no audible-output or LG client-toggle claim\nSCOPE: LG sound native calls/player state; no audible-output qualification\nRESULT: PASS \n'

def test_leafgreen_translates_verified_symbols_and_keeps_platform_memory():
    text,audit=lg_transform("local a=0x080DA364;local b=0x081DD0F4;local c=0x084A32CC;local v=0x06000000;local token=0x13572468", "sound")
    assert "0x080DA338" in text and "0x081DD0D0" in text and "0x084A2BA8" in text
    assert "0x06000000" in text and "0x13572468" in text
    assert audit["0x080DA364"]["symbol"]=="TrySavingData"
    with pytest.raises(AssertionError):
        lg_transform("local unknown=0x09000000", "sound")

def test_leafgreen_sound_oracle_requires_leafgreen_tables():
    rom=bytearray(0x4A4000)
    def put(address,value,size=4):
        offset=address-0x08000000
        rom[offset:offset+size]=value.to_bytes(size,"little")
    for song,header,index,player in ((25,0x086B548C,1,0x03007340),(257,0x086BC674,2,0x03007380)):
        put(0x084A2BA8+song*8,header)
        put(0x084A2BA8+song*8+4,index,2)
        put(0x084A2B78+index*12,player)
    assert not sound_problems(SOUND_CAPTURE,rom,song_table=0x084A2BA8,mplay_table=0x084A2B78)
    assert sound_problems(SOUND_CAPTURE,rom)
