"""Pinned detour replay: native register-save prologues cannot be guessed."""
import re
import struct

from tests.unit.test_patch_targets import build


def test_fr_entry_gate_replays_exact_verified_bytes_and_resumes_after_them():
    spec = build.target_spec("firered")
    for symbol, code in (("TRADE_MON","TRADE_GATE_ASM"),("EVO_GETTER","EVO_GATE_ASM")):
        asm=spec[code]
        words=asm.split(".hword ",1)[1].split("\n",1)[0].split(",")
        assert struct.pack("<4H",*(int(word,16) for word in words)).hex()==spec[symbol+"_BYTES"]
        target=int(re.search(r"ldr r3,=(0x[0-9a-fA-F]+)",asm)[1],16)
        assert target==(spec[symbol]+8)|1
    assert spec["SCRIPT_IDLE"]==2  # pret script.c:21-23, not zero/running
