"""Actual savestate and native reset-input faults against the bounded owner."""
import json
import os
from pathlib import Path

import pytest

from tools.run_gb_gate import BIZHAWK_CONFIG,run_gate

pytestmark=[pytest.mark.live,pytest.mark.slow,
            pytest.mark.skipif(os.environ.get("SLINK_LIVE")!="1",reason="explicit live emulator lane required")]


@pytest.mark.parametrize("variant",["red","blue","yellow"])
@pytest.mark.parametrize("case",["same_frame_load","older_state_load","menu_power","controller_power"])
def test_context_changes_revoke_before_the_next_owned_frame(variant,case,tmp_path):
    config=json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"));config["Rewind"]["Enabled"]=False
    private=tmp_path/"config.ini";private.write_text(json.dumps(config))
    spec={"case":case,"output":(tmp_path/"result.json").as_posix(),"state":(tmp_path/"owned.State").as_posix()}
    source=tmp_path/"input.json";source.write_text(json.dumps(spec))
    passed,path,log=run_gate("lua/tests/test_gen1_host_context_gate.lua",rom_key=variant,quiet=True,timeout=55,
        config_base=str(private),extra_env={"SLINK_HOST_CONTEXT_INPUT":str(source)})
    (tmp_path/"gate.log").write_text(log)
    assert passed,f"{path}\n{log[-6000:]}"
    result=json.loads(Path(spec["output"]).read_text())
    assert result["passed"] and result["before"]==result["after"]
    assert result["final"]["failed"] and result["final"]["host"]["physical_stop_verified"]
