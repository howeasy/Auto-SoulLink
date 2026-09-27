"""LeafGreen pointers are backed by its own symbols, not an assumed FR delta."""
import hashlib
import json
from pathlib import Path

from tests.unit.test_patch_targets import build

ROOT=Path(__file__).resolve().parents[2]


def test_leafgreen_complete_bindings_match_own_symbol_provenance():
    fr,lg=build.target_spec("firered"),build.target_spec("leafgreen")
    assert set(lg)==set(fr)
    proof=json.loads((ROOT/"patch/src/trade_targets/leafgreen_bindings.json").read_text())
    lock=json.loads((ROOT/"data/gen3_sources.lock.json").read_text())
    assert proof["source_commit"]==lock["source"]["commit"]
    assert proof["rom_sha1"]==lg["ROM_SHA1"]==lock["outputs"]["pokeleafgreen"]["sha1"]
    path=ROOT/"data/gen3/pret/pokeleafgreen.sym"
    assert hashlib.sha256(path.read_bytes()).hexdigest()==proof["symbols_sha256"]
    assert proof["symbols_sha256"]=="6a48f1b3f3cabea043074d5d94f16cdf8b727cb529f8eced142beaa410a9ebae"
    symbols={}
    for line in path.read_text().splitlines():
        fields=line.split()
        if len(fields)==4 and not fields[3].startswith("."):
            symbols.setdefault(fields[3],set()).add(int(fields[0],16))
    for key,item in proof["bindings"].items():
        assert symbols[item["symbol"]]=={item["symbol_address"]}
        assert lg[key]==item["symbol_address"]+item["offset"]
    for key,items in proof["table_references"].items():
        assert [int(value,0) for value in lg[key].split(",")]==[item["address"] for item in items]
        for item in items:
            assert symbols[item["symbol"]]=={item["symbol_address"]}
            assert item["address"]==item["symbol_address"]+item["offset"]
    assert lg["ARENA_CANDIDATE"]==lg["HEAP_BASE"]+lg["HEAP_SIZE"]-lg["ARENA_SIZE"]
    assert lg["READY"]==0
