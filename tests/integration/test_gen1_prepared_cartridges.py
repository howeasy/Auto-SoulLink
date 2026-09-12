"""Reproduction-backed preparation reads; editable JSON alone is not seed proof."""
import hashlib
import json
from pathlib import Path
import pytest

from server.gen1_prepared_cartridges import PreparedCartridges
from server.gen1_upr_pipeline import prepare_pair
from server.gen1_upr_policy import build_preset
from server.protocol import digest
from tests.integration.test_upr_pinned import ROOT,user_jar


def prepared(tmp_path,variants=("yellow","yellow"),*,settings_changes=None):
    sources={p:ROOT/f"patch/build/gen1_{v}{'.gbc' if v=='yellow' else '.gb'}" for p,v in zip(("a","b"),variants)}
    directory=tmp_path/"prepared"
    prepare_pair(user_jar(),build_preset(settings_changes if settings_changes is not None else {"wildPokemonMod":"RANDOM"}),sources,directory,
        seeds={"a":"123456789","b":"987654321"})
    return directory


@pytest.mark.parametrize("variants",[("red","blue"),("blue","yellow"),("yellow","yellow")])
def test_prepared_pair_reproduces_and_returns_detached_exact_contract(variants,tmp_path):
    directory=prepared(tmp_path,variants);cartridges=PreparedCartridges(directory)
    contract=cartridges.contract()
    assert cartridges.validate_contract(contract)==contract["players"]
    for player,variant in zip(("a","b"),variants):
        entry=contract["players"][player]
        assert entry["variant"]==variant and entry["content_profile_schema"]=="gen1-rby-scanned-companion-content-v1"
        assert hashlib.sha1(cartridges.rom(player)).hexdigest()==entry["final_rom_sha1"]
    contract["players"]["a"]["capabilities"]["sfx"]=True
    with pytest.raises(ValueError):cartridges.validate_contract(contract)
    assert cartridges.contract()["players"]["a"]["capabilities"]["sfx"] is False


@pytest.mark.parametrize("kind",["final_rom","capabilities","forged_seed"])
def test_rehashed_metadata_cannot_launder_wrong_artifacts_or_seed_claims(kind,tmp_path):
    directory=prepared(tmp_path)
    index_path=directory/"prepared-artifacts.json";index=json.loads(index_path.read_text())
    entry=index["players"]["a"];report_path=directory/entry["candidate"];report=json.loads(report_path.read_text())
    if kind=="final_rom":
        path=directory/entry["rom"];data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
        entry["rom_sha256"]=hashlib.sha256(data).hexdigest();entry["rom_sha1"]=hashlib.sha1(data).hexdigest()
    elif kind=="capabilities":report["capabilities"]["sfx"]=True
    else:
        # Keep JSON/log hashes self-consistent while falsely attributing the
        # unchanged output to another seed. Reproduction must detect this.
        run=report["generation"]
        log_path=directory/"generation/a/randomized.gbc.log"
        log=log_path.read_bytes().replace(b"Random Seed: 123456789",b"Random Seed: 123456788")
        log_path.write_bytes(log);run["seed"]="123456788";run["log_sha256"]=hashlib.sha256(log).hexdigest()
        entry["seed"]=run["seed"]
        pair_path=directory/"generation/pair-provenance.json";pair=json.loads(pair_path.read_text())
        pair["players"]["a"]=run;pair_path.write_text(json.dumps(pair))
    entry["candidate_sha256"]=digest(report)
    report_path.write_text(json.dumps(report));index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError):PreparedCartridges(directory)
