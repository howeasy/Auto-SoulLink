"""Adversarial corruption of real produced ROMs, with a canonical input oracle."""
from pathlib import Path
import pytest

from server.gen1_upr_policy import build_preset
from server.gen1_upr_scan import LAYOUT,scan_candidate,scan_generated
from server.gen1_companion_patch import apply_to_candidate
from server.rom_change_audit import RomAuditError
from server.upr_runner import run_pinned
from tests.integration.test_upr_pinned import PRESETS,ROOT,user_jar


@pytest.fixture(scope="module",params=["red","blue","yellow"])
def cartridge(request,tmp_path_factory):
    variant=request.param
    source=ROOT/f"patch/build/gen1_{variant}{'.gbc' if variant=='yellow' else '.gb'}"
    original=source.read_bytes();settings=build_preset(PRESETS["combined"])
    parent=tmp_path_factory.mktemp("upr-corruption-"+variant)
    result=run_pinned(user_jar(),settings,source,parent/"produced",seed="123456789",generation=1)
    candidate=Path(result["output"]).read_bytes()
    scan_generated(original,candidate,settings)
    return variant,original,candidate,settings


@pytest.mark.parametrize("domain",["header","unrelated_code","base_stats","types","catch_rate","moves","move_pp",
    "compatibility","hm","npc_trade","wild_root","wild_level","static_level","ghost","trainer_move",
    "starter_alias","tm_text","evolution_pointer","evolution_padding","field_key_item"])
def test_forbidden_or_invalid_mutations_are_rejected(cartridge,domain):
    variant,original,candidate,settings=cartridge
    cfg=LAYOUT["profiles"][variant]["settings"]
    changed=bytearray(candidate);value=None
    offsets={"header":0x147,"unrelated_code":0,"base_stats":cfg["PokemonStatsOffset"]+1,
        "types":cfg["PokemonStatsOffset"]+6,"catch_rate":cfg["PokemonStatsOffset"]+8,
        "moves":cfg["MoveDataOffset"]+2,"move_pp":cfg["MoveDataOffset"]+5,
        "compatibility":cfg["PokemonStatsOffset"]+20,"hm":cfg["TMMovesOffset"]+50,
        "npc_trade":cfg["TradeTableOffset"],"wild_root":cfg["WildPokemonTableOffset"],
        "wild_level":cfg["OldRodOffset"]+2,"static_level":LAYOUT["profiles"][variant]["statics"][0]["Level"][0],
        "ghost":LAYOUT["profiles"][variant]["statics"][-1]["Species"][0],
        "trainer_move":cfg["ExtraTrainerMovesTableOffset"],"starter_alias":cfg["StarterOffsets1"][-1],
        "tm_text":LAYOUT["profiles"][variant]["tm_text"][0]["offset"],
        "evolution_pointer":cfg["PokemonMovesetsTableOffset"]+1,
        "evolution_padding":cfg["PokemonMovesetsTableOffset"]+380+cfg["PokemonMovesetsDataSize"]-1}
    if domain=="field_key_item":
        report=scan_candidate(original,candidate)
        offset=next(item["offset"] for item in report["profile"]["items"] if item["item"]<200)
        value=5  # TOWN MAP is a protected key item, not a random field item.
    else:offset=offsets[domain]
    changed[offset]=value if value is not None else changed[offset]^1
    with pytest.raises(RomAuditError):scan_generated(original,bytes(changed),settings)


def test_disabled_domains_cannot_be_laundered_with_another_settings_file(cartridge):
    _,original,candidate,_=cartridge
    with pytest.raises(RomAuditError,match="disabled"):scan_generated(original,candidate,build_preset())


def test_clean_identity_and_whole_image_are_required(cartridge):
    _,original,candidate,_=cartridge
    with pytest.raises(RomAuditError):scan_candidate(original[:-1],candidate)
    with pytest.raises(RomAuditError):scan_candidate(original,candidate[:-1])
    assert scan_candidate(original,original)["bytes_changed"]==0


def test_structural_companion_rechecks_semantics_and_refuses_reapply(cartridge):
    variant,original,candidate,settings=cartridge
    final,report=apply_to_candidate(original,candidate,settings=settings)
    assert len(final)==len(original) and final[0x100:0x150]==original[0x100:0x150]
    assert report["capabilities"]=={"panel":variant!="yellow","pc_trade":True,"sfx":False}
    assert report["semantic_audit"]==report["final_semantic_audit"]
    assert report["runtime_ready"] is False
    with pytest.raises((RomAuditError,ValueError)):apply_to_candidate(original,final,settings=settings)
    altered=bytearray(candidate);altered[1]^=1
    with pytest.raises((RomAuditError,ValueError)):apply_to_candidate(original,bytes(altered),settings=settings)
