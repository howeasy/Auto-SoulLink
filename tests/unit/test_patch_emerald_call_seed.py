"""O-33 offline setup: only two unlock flags and their sector checksums change."""
from pathlib import Path

from server.adapters import gen3_codec as codec
from tests.unit import test_patch_emerald_live as live


def test_call_seed_only_changes_unlock_flags_and_checksums():
    original=(Path(live.ROOT)/"tests/fixtures/gen3/emerald_town.sav").read_bytes()
    seed,receipt=live.build_call_seed(original)
    before=codec.parse_flash(original,title="emerald")
    after=codec.parse_flash(seed,title="emerald")
    assert codec.qualify_flash(seed,title="emerald")[0]
    assert before["counter"]==after["counter"]
    expected=bytearray(before["sb1"])
    for flag in (0x862,0x12f):expected[0x1270+(flag>>3)]|=1<<(flag&7)
    assert after["sb1"]==bytes(expected)
    assert after["sb2"]==before["sb2"] and after["storage"]==before["storage"]
    assert receipt["setup"]=="SYNTH"
    assert receipt["registered_trainer_changes"]==[]
    actual=[{"offset":i,"before":a,"after":b} for i,(a,b) in enumerate(zip(original,seed)) if a!=b]
    assert receipt["exact_byte_changes"]==actual
    assert actual==[
        {"offset":0x3315,"before":0,"after":0x80},
        {"offset":0x33fc,"before":1,"after":5},
        {"offset":0x3ff6,"before":0xae,"after":0xb2},
        {"offset":0x3ff7,"before":0x2a,"after":0xaa},
    ]
    assert len(seed)==len(original)
