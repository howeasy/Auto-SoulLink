"""Replay assembly must agree with the pinned callback continuation and literal."""
import json
from pathlib import Path
import pytest
from tests.unit.test_patch_targets import build

ROOT=Path(__file__).resolve().parents[2]

def inputs():
    spec=build.target_spec("emerald")
    facts=json.loads((ROOT/"patch/src/trade_targets/emerald_lifecycle.json").read_text())
    rom=bytearray(0x1000)
    for row in [facts["entries"][0],*facts["continuations"]]:
        at=row["address"]-0x08000000;raw=bytes.fromhex(row["bytes"]);rom[at:at+len(raw)]=raw
    at=spec["FRAME_GMAIN_LITERAL"]-0x08000000;rom[at:at+4]=spec["GMAIN"].to_bytes(4,"little")
    return spec,facts,bytes(rom)

def test_replay_selects_symbol_not_list_order():
    spec,facts,rom=inputs()
    facts["continuations"].insert(0,{"symbol":"unrelated"})
    assert build.validate_frame_replay(spec,facts,rom)["address"]==0x08000525

@pytest.mark.parametrize("fault",["gmain_asm","resume_asm","missing","duplicate","offset"])
def test_inconsistent_replay_is_refused(fault):
    spec,facts,rom=inputs()
    if fault=="gmain_asm":spec["FRAME_REPLAY_ASM"]=spec["FRAME_REPLAY_ASM"].replace("030022c0","030022c4")
    elif fault=="resume_asm":spec["FRAME_REPLAY_ASM"]=spec["FRAME_REPLAY_ASM"].replace("08000525","08000527")
    elif fault=="missing":facts["continuations"]=[]
    elif fault=="duplicate":facts["continuations"]*=2
    else:facts["continuations"][0]["offset"]=10
    with pytest.raises(ValueError,match="callback"):
        build.validate_frame_replay(spec,facts,rom)
