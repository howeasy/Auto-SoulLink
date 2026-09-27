"""Pinned detour replay: native register-save prologues cannot be guessed."""
import re
import struct
from pathlib import Path

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


def test_fr_carrier_calls_match_pinned_vanilla_symbols():
    root = Path(__file__).resolve().parents[2]
    symbols = {}
    for line in (root / "data/gen3/pret/pokefirered.sym").read_text().splitlines():
        words = line.split()
        if len(words) == 4:
            symbols[words[3]] = int(words[0],16)
    spec = build.target_spec("firered")
    for field, symbol in (("CARRIER_SPAWN","SpawnSpecialObjectEventParameterized"),
                          ("CARRIER_REMOVE","RemoveObjectEvent"),
                          ("CARRIER_CHOOSE","ChoosePartyMonByMenuType"),
                          ("CARRIER_OBJECTS","gObjectEvents"),
                          ("CARRIER_AVATAR","gPlayerAvatar")):
        assert spec[field] == symbols[symbol]
