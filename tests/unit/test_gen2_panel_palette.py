"""The native palette restore oracle stays strict after clock-input normalization."""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def oracle():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    panel = lua.execute((ROOT / "lua/tests/gen2_panel_gate.lua").read_text(encoding="utf-8"))
    return lua, panel


def snapshot(lua):
    return lua.table_from({
        "bgp1": list(range(64)), "bgp2": list(range(64)),
        "obp1": list(range(64)), "obp2": list(range(64)),
        "attr": [i % 256 for i in range(2048)],
    }, recursive=True)


def test_probe_forwards_caller_resolved_paths_to_the_lane_worker(tmp_path, monkeypatch):
    """The worker runs with cwd=<lane> and the lane is dropped afterwards, so a relative --out must be resolved
    against the CALLER before it crosses the subprocess boundary, or its evidence is written inside the lane."""
    import subprocess
    import sys

    sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
    import probe_gen2_panel_palette as probe

    from tools import gen2_final_sweep as sweep

    lane = tmp_path / "lane"
    (lane / "tools").mkdir(parents=True)
    (lane / Path(probe.GATE)).parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sweep, "make_lane", lambda n, sha: lane)
    monkeypatch.setattr(sweep, "drop_lane", lambda path: None)
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["cwd"] = argv, kwargs["cwd"]
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    caller = tmp_path / "caller"
    caller.mkdir()
    monkeypatch.chdir(caller)
    monkeypatch.setattr(sys, "argv", ["probe", "--lane", "lanes", "--out", "evidence/run1"])
    assert probe.main() == 0
    out = Path(seen["argv"][seen["argv"].index("--out") + 1])
    assert out.is_absolute() and out == (caller / "evidence/run1").resolve()
    assert Path(seen["argv"][seen["argv"].index("--lane") + 1]).is_absolute()
    assert (caller / "evidence/run1/driver.log").is_file()


@pytest.mark.parametrize("field,index", [("bgp1", 1), ("bgp1", 64), ("bgp2", 1), ("attr", 2048)])
def test_native_restoration_rejects_corruption_at_buffer_boundaries(oracle, field, index):
    lua, panel = oracle
    before, after = snapshot(lua), snapshot(lua)
    assert panel.same(before, after) is True
    after[field][index] ^= 1
    assert panel.same(before, after) == f"{field}[{index - 1}]"
