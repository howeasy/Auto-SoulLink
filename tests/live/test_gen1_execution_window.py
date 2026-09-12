"""Real Gambatte frames; scope and issuer proof are explicit local fixtures."""
import json
import os
from pathlib import Path
import pytest
from tools.run_gb_gate import BIZHAWK_CONFIG,run_gate

pytestmark=[pytest.mark.live,pytest.mark.slow,
            pytest.mark.skipif(os.environ.get("SLINK_LIVE")!="1",reason="explicit live emulator lane required")]


@pytest.mark.parametrize("variant",["red","blue","yellow"])
def test_renewed_operation_credits_bound_actual_frames_and_expiry(variant,tmp_path):
    run_window(variant,tmp_path)


@pytest.mark.parametrize("variant",["red","blue","yellow"])
def test_operation_frames_follow_the_actual_cartridge_video_clock(variant,tmp_path):
    run_window(variant,tmp_path,pace=True)


def run_window(variant,tmp_path,*,pace=False):
    config=json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"));config["Rewind"]["Enabled"]=False
    private=tmp_path/"config.ini";private.write_text(json.dumps(config))
    result=tmp_path/"result.json";spec=tmp_path/"input.json";spec.write_text(json.dumps({"output":result.as_posix(),"pace":pace}))
    passed,path,log=run_gate("lua/tests/test_gen1_execution_window_gate.lua",rom_key=variant,quiet=True,timeout=55,
        config_base=str(private),extra_env={"SLINK_EXECUTION_WINDOW_INPUT":str(spec)})
    (tmp_path/"gate.log").write_text(log)
    assert passed,f"{path}\n{log[-6000:]}"
    value=json.loads(result.read_text())
    assert value["passed"] and value["callbacks"]==value["frames"]==value["window"]["consumed"]==30
    assert value["window"]["remaining"]==0 and value["host"]["host"]["physical_stop_verified"]
