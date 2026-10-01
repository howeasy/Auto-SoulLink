"""Literal native sound receipt with ROM-table falsifiers; no emulator."""
from tests.unit.test_patch_sound_live import sound_problems

CAPTURE = 'HELPER: [gen3] phase field frame=778 map=(3,1)\nSOUND_CALL kind=se seq=1 id=25\nSOUND_CALL kind=m4a seq=1 id=25\nSOUND_ACTIVE op=19 id=25 seq=1 player=03007340 header=086B5BB0 status=00000001 clock=1->2\nSOUND_CALL kind=fanfare seq=2 id=257\nSOUND_CALL kind=m4a seq=2 id=257\nSOUND_ACTIVE op=9 id=257 seq=2 player=03007380 header=086BCD98 status=0000001F clock=1->2\nFANFARE_RELEASE counter=77->0 paused=1->0 task=1->0\nSOUND_REFUSED case=invalid_se seq=3 status=3 reason=2 se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch=7\nSOUND_REFUSED case=invalid_fanfare seq=4 status=3 reason=2 se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch=7\nSOUND_REFUSED case=unarmed_epoch seq=5 status=3 reason=13 se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch=0\nSOUND_REFUSED case=stale_epoch seq=6 status=3 reason=12 se=1 fanfare=1 m4a=2 configured_epoch=7 request_epoch=8\nSOUND_SCOPE: native routine/player/task RAM evidence only; no audible-output or FR client-toggle claim\nSCOPE: FR sound native calls/player state; no audible-output qualification\nRESULT: PASS \n'

def test_sound_receipt_requires_calls_active_players_and_refusals():
    rom=bytearray(0x4A3E00)
    def put(address,value,size=4):
        offset=address-0x08000000
        rom[offset:offset+size]=value.to_bytes(size,"little")
    for song,header,index,player in ((25,0x086B5BB0,1,0x03007340),(257,0x086BCD98,2,0x03007380)):
        put(0x084A32CC+song*8,header)
        put(0x084A32CC+song*8+4,index,2)
        put(0x084A329C+index*12,player)
    assert not sound_problems(CAPTURE,rom)
    for old,new in (("header=086B5BB0","header=086B5BB4"),("clock=1->2","clock=1->1"),
                    ("status=00000001","status=80000001"),("kind=se seq=1 id=25","kind=se seq=1 id=26"),
                    ("case=stale_epoch","case=missing"),("paused=1->0","paused=1->1")):
        assert sound_problems(CAPTURE.replace(old,new),rom)
