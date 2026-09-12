"""Real generated final cartridges, original native animation and verified saves."""
import json
import os
from pathlib import Path

import pytest

from server.gen1_companion_patch import apply_to_candidate
from server.gen1_upr_policy import build_preset
from server.upr_runner import run_pair_pinned
from tests.integration.test_upr_pinned import PRESETS,ROOT,user_jar
from tests.live.test_gen1_paired_native_trade import run_native_pair
from tools.run_gb_gate import run_gate

pytestmark=[pytest.mark.live,pytest.mark.slow,
            pytest.mark.skipif(os.environ.get("SLINK_LIVE")!="1",reason="explicit live emulator lane required")]


def final_pair(variants,directory):
    settings=build_preset(PRESETS["combined"])
    paths={p:ROOT/f"patch/build/gen1_{v}{'.gbc' if v=='yellow' else '.gb'}" for p,v in zip(("a","b"),variants)}
    pair=run_pair_pinned(user_jar(),settings,paths,directory/"randomized",seeds={"a":"123456789","b":"987654321"},generations={"a":1,"b":1})
    artifacts={}
    for player,info in pair["players"].items():
        final,report=apply_to_candidate(paths[player].read_bytes(),Path(info["output"]).read_bytes(),settings=settings)
        path=directory/("final-"+player+".gbc");path.write_bytes(final)
        artifacts[player]=report["manifest"]
        artifacts[player]["output"]=path.relative_to(ROOT).as_posix()
        (directory/("candidate-"+player+".json")).write_text(json.dumps(report,indent=2))
    return artifacts


@pytest.mark.parametrize("variants",[("red","blue"),("blue","yellow"),("yellow","yellow")],ids=lambda pair:"-".join(pair))
def test_randomized_final_pair_boots_and_runs_both_original_trade_animations(variants,tmp_path):
    artifacts=final_pair(variants,tmp_path)
    assert artifacts["a"]["final_sha1"]!=artifacts["b"]["final_sha1"]
    run_native_pair(variants,native_ui=True,companion=True,bounded_host=True,prepared_artifacts=artifacts)


@pytest.mark.parametrize("dex",[64,67,75,93])
@pytest.mark.parametrize("variants",[("red","blue"),("yellow","yellow")],ids=lambda pair:"-".join(pair))
def test_native_trade_obeys_randomized_evolution_methods_on_final_cartridges(variants,dex,tmp_path):
    # Combined settings replace all four trade methods with level methods. The
    # original trade pass must therefore retain these species, even at level50.
    artifacts=final_pair(variants,tmp_path)
    run_native_pair(variants,native_ui=True,companion=True,bounded_host=True,prepared_artifacts=artifacts,party_dex=dex)


def test_yellow_pair_plays_original_animation_at_cartridge_speed(tmp_path):
    artifacts=final_pair(("yellow","yellow"),tmp_path)
    run_native_pair(("yellow","yellow"),native_ui=True,companion=True,bounded_host=True,
        prepared_artifacts=artifacts,party_dex=64,paced_host=True)


@pytest.mark.parametrize("variant",["red","blue"])
def test_randomized_final_panel_keeps_all_native_protocol_scenarios(variant,tmp_path):
    artifacts=final_pair((variant,variant),tmp_path)
    manifest=artifacts["a"]
    source=tmp_path/"panel-manifest.json";source.write_text(json.dumps(manifest))
    output=tmp_path/"panel-result.json"
    passed,path,log=run_gate("lua/tests/test_gen1_companion_panel_gate.lua",rom_key=variant+"_companion",quiet=True,timeout=65,
        cartridge_override={"path":str(ROOT/manifest["output"]),"sha256":manifest["companion"]["final_sha256"],"saveram_name":"candidate.SaveRAM"},
        extra_env={"SLINK_COMPANION_MANIFEST":str(source),"SLINK_COMPANION_PANEL_RESULT":str(output)})
    assert passed,f"{path}\n{log[-6000:]}"
    observed=json.loads(output.read_text())
    assert observed["passed"] and len(observed["cases"])==12 and observed["native_trade_calls"]==0
