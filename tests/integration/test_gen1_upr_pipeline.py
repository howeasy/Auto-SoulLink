"""Actual final-file production and fail-closed publication boundaries."""
import hashlib
import json
from pathlib import Path

import pytest

from server.gen1_upr_pipeline import prepare_pair
from server.gen1_upr_policy import build_preset
from server.protocol import digest
from server.upr_runner import UprRunError
from tests.integration.test_upr_pinned import PRESETS,ROOT,user_jar


@pytest.mark.parametrize("variants",[("red","blue"),("blue","yellow"),("yellow","yellow")])
def test_full_producer_publishes_both_exact_final_files_and_preserves_inputs(variants,tmp_path):
    sources={p:ROOT/f"patch/build/gen1_{v}{'.gbc' if v=='yellow' else '.gb'}" for p,v in zip(("a","b"),variants)}
    before={p:hashlib.sha256(path.read_bytes()).hexdigest() for p,path in sources.items()}
    directory=tmp_path/"prepared"
    settings=build_preset(PRESETS["combined"])
    result=prepare_pair(user_jar(),settings,sources,directory,seeds={"a":"123456789","b":"987654321"})
    assert json.loads((directory/"prepared-artifacts.json").read_text())==result
    assert result["status"]=="prepared_requires_runtime_admission" and result["runtime_ready"] is False
    for p,info in result["players"].items():
        final=(directory/info["rom"]).read_bytes()
        assert hashlib.sha256(final).hexdigest()==info["rom_sha256"]
        report=json.loads((directory/info["candidate"]).read_text())
        assert digest(report)==info["candidate_sha256"]
        assert report["generation"]["source_sha256"]==before[p]==hashlib.sha256(sources[p].read_bytes()).hexdigest()
        assert report["manifest_sha256"]==digest(report["manifest"])
    with pytest.raises(UprRunError,match="new final"):
        prepare_pair(user_jar(),settings,sources,directory,seeds={"a":"123456789","b":"987654321"})


def test_failure_before_second_final_never_commits_preparation(tmp_path,monkeypatch):
    from server import gen1_upr_pipeline as pipeline
    original=pipeline.apply_to_candidate
    calls=[]
    def fail_second(*args,**kwargs):
        calls.append(True)
        if len(calls)==2:raise ValueError("injected final audit failure")
        return original(*args,**kwargs)
    monkeypatch.setattr(pipeline,"apply_to_candidate",fail_second)
    source=ROOT/"patch/build/gen1_red.gb";directory=tmp_path/"incomplete"
    with pytest.raises(ValueError,match="injected"):
        prepare_pair(user_jar(),build_preset(),{"a":source,"b":source},directory,seeds={"a":"1","b":"2"})
    assert not (directory/"prepared-artifacts.json").exists()
    assert (directory/"final/a/candidate.json").exists()
