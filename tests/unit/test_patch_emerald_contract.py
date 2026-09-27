"""Emerald source bindings do not imply a built or admitted producer."""
import hashlib
import json
from pathlib import Path

from tests.unit.test_patch_targets import build

ROOT=Path(__file__).resolve().parents[2]


def test_emerald_requires_relocated_callback_prologue_and_own_save_call():
    spec=build.target_spec("emerald")
    assert spec["FRAME_REPLAY_REQUIRED"]==1
    assert spec["FRAME_ENTRY"]==0x0800051C
    assert spec["FRAME_RESUME"]==0x08000525
    assert spec["FRAME_GMAIN_LITERAL"]==0x0800053C
    assert spec["GMAIN"]==0x030022C0
    assert spec["FRAME_BYTES"]=="10b5074c20680028"
    assert "ldr r4,=0x030022c0" in spec["FRAME_REPLAY_ASM"]
    assert spec["READY"]==1
    facts=json.loads((ROOT/"patch/src/trade_targets/emerald_lifecycle.json").read_text())
    assert facts["source_commit"]=="c65e93f20a5275ab03b07d6f6411096a82a60ffd"
    assert facts["symbols_sha256"]==hashlib.sha256((ROOT/"data/gen3/pret/pokeemerald.sym").read_bytes()).hexdigest()
    symbols={}
    sizes={}
    for line in (ROOT/"data/gen3/pret/pokeemerald.sym").read_text().splitlines():
        p=line.split()
        if len(p)==4:
            symbols[p[3]]=int(p[0],16)
            sizes[p[3]]=int(p[2],16)
    for item in facts["entries"]:
        assert item["address"]==symbols[item["symbol"]]
    continuation=facts["continuations"][0]
    assert continuation["symbol"]=="CallCallbacks"
    assert continuation["symbol_address"]==symbols[continuation["symbol"]]
    assert continuation["offset"]==8
    assert continuation["address"]==continuation["symbol_address"]+continuation["offset"]
    assert continuation["thumb_address"]==(continuation["address"]|1)==spec["FRAME_RESUME"]
    assert continuation["offset"]+len(bytes.fromhex(continuation["bytes"]))<=sizes[continuation["symbol"]]
    assert continuation["bytes"]=="01d0e6f2d3fd6068"
    assert facts["status"]=="SOURCE_PINNED"
