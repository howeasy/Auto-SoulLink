"""Emerald addresses come from its own pinned symbols and ROM."""
import hashlib
import json
from pathlib import Path

from tests.unit.test_patch_targets import build

ROOT=Path(__file__).resolve().parents[2]


def test_emerald_native_bindings_have_own_symbol_provenance():
    spec=build.target_spec("emerald")
    proof=json.loads((ROOT/"patch/src/trade_targets/emerald_bindings.json").read_text())
    path=ROOT/"data/gen3/pret/pokeemerald.sym"
    assert proof["source_commit"]=="c65e93f20a5275ab03b07d6f6411096a82a60ffd"
    assert proof["symbols_sha256"]==hashlib.sha256(path.read_bytes()).hexdigest()
    symbols={}
    for line in path.read_text().splitlines():
        p=line.split()
        if len(p)==4 and not p[3].startswith("."):
            symbols.setdefault(p[3],set()).add(int(p[0],16))
    for key,item in proof["bindings"].items():
        assert symbols[item["symbol"]]=={item["symbol_address"]},key
        assert spec[key]==item["symbol_address"]+item["offset"],key
    # Source APIs with different semantics cannot inherit the FR/LG entries.
    assert proof["bindings"]["ASK_SAVE"]["symbol"]=="SaveGame"
    assert proof["bindings"]["CARRIER_CHOOSE"]["symbol"]=="ChoosePartyMon"
    assert proof["bindings"]["CALL_SHOW"]["symbol"]=="ShowPokenavFieldMessage"
    assert "SAVE_QUEST" not in spec and "PANEL_DESC_TABLE" not in spec
    assert spec["ARENA_CANDIDATE"]==spec["HEAP_BASE"]+spec["HEAP_SIZE"]-spec["ARENA_SIZE"]
    assert spec["READY"]==0
