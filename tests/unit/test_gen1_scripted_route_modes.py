"""Route-mode staging/registration for the scripted host's test-only launcher wrapper.

Pure: only tests.live.gen1_scripted_host.prepare_scripted_plan() and the
SelectedRun constructor's route_mode validation. No emulator, no product
process lease acquisition (gen1_scripted_host.main()'s CLI path is untouched),
no directory outside tmp_path.
"""
import hashlib
import json
from pathlib import Path

import pytest

from tests.live.gen1_scripted_host import ROOT, prepare_scripted_plan
from tests.live.gen1_selected_scenario import SelectedRun
from tests.live.test_gen1_selected_rb_ball_gate import verify_parcel_checkpoint

RB_MODULE = ROOT / "lua/tests/gen1_rb_ball_gate_inputs.lua"
PARCEL_MODULE = ROOT / "lua/tests/gen1_rb_parcel_inputs.lua"


def _inputs(tmp_path, player="a"):
    root = tmp_path / "root"
    root.mkdir()
    rom_bytes = b"\x00" * 32768
    rom = tmp_path / "slink_red.gb"
    rom.write_bytes(rom_bytes)
    launcher_text = "-- launcher\n"
    launcher = tmp_path / "launcher.lua"
    launcher.write_text(launcher_text)
    base_config = tmp_path / "base_config.json"
    base_config.write_text(json.dumps({"PathEntries": {"Paths": [
        {"Type": "Save RAM", "System": "GB", "Path": str(tmp_path / "saves")}]}}))
    spec = {"schema": "slink-bizhawk-launch-v1", "run_id": "a" * 32, "player": player,
            "profile": "gambatte", "rom_sha1": hashlib.sha1(rom_bytes).hexdigest(),
            "launcher_sha256": hashlib.sha256(launcher_text.encode()).hexdigest()}
    return root, spec, rom, launcher, base_config


def test_route_none_stages_no_route_files(tmp_path):
    root, spec, rom, launcher, base_config = _inputs(tmp_path)
    plan = prepare_scripted_plan(root, spec, rom=rom, launcher=launcher, base_config=base_config)
    assert "route" not in plan and "rb_route_sha256" not in plan and "route_module_sha256" not in plan
    staged = Path(plan["cwd"])
    assert not (staged / RB_MODULE.name).exists()
    assert not (staged / PARCEL_MODULE.name).exists()


def test_route_rb_starter_rival_stages_one_module(tmp_path):
    root, spec, rom, launcher, base_config = _inputs(tmp_path)
    plan = prepare_scripted_plan(root, spec, rom=rom, launcher=launcher, base_config=base_config,
                                  route_mode="rb-starter-rival")
    staged = Path(plan["cwd"])
    route = json.loads((staged / "scripted_input.json").read_text())["route"]
    assert route["mode"] == "rb-starter-rival"
    assert route["module"] == str(staged / RB_MODULE.name)
    assert route["chain"] == []
    assert not (staged / PARCEL_MODULE.name).exists()
    expected_hash = hashlib.sha256(RB_MODULE.read_bytes()).hexdigest()
    assert plan["rb_route_sha256"] == expected_hash
    assert plan["route_module_sha256"] == {RB_MODULE.name: expected_hash}
    assert (staged / RB_MODULE.name).read_bytes() == RB_MODULE.read_bytes()


def test_route_rb_parcel_stages_both_modules_chained(tmp_path):
    root, spec, rom, launcher, base_config = _inputs(tmp_path)
    plan = prepare_scripted_plan(root, spec, rom=rom, launcher=launcher, base_config=base_config,
                                  route_mode="rb-parcel")
    staged = Path(plan["cwd"])
    for module in (RB_MODULE, PARCEL_MODULE):
        assert (staged / module.name).read_bytes() == module.read_bytes(), module.name
    route = json.loads((staged / "scripted_input.json").read_text())["route"]
    assert route["mode"] == "rb-parcel"
    assert route["module"] == str(staged / RB_MODULE.name)
    assert route["chain"] == [{"module": str(staged / PARCEL_MODULE.name),
                               "after": "lab-loss-complete", "terminal": "first-ball-readback"}]
    rb_hash = hashlib.sha256(RB_MODULE.read_bytes()).hexdigest()
    parcel_hash = hashlib.sha256(PARCEL_MODULE.read_bytes()).hexdigest()
    assert plan["route_module_sha256"] == {RB_MODULE.name: rb_hash, PARCEL_MODULE.name: parcel_hash}
    assert plan["rb_route_sha256"] == rb_hash


def test_route_bogus_rejected(tmp_path):
    root, spec, rom, launcher, base_config = _inputs(tmp_path)
    with pytest.raises(ValueError, match="unsupported scripted route"):
        prepare_scripted_plan(root, spec, rom=rom, launcher=launcher, base_config=base_config,
                              route_mode="bogus")


def test_selected_run_rejects_parcel_route_off_pair_or_product_cli(tmp_path):
    with pytest.raises(ValueError, match="route requires the scripted Red/Blue pair"):
        SelectedRun(tmp_path / "yellow", ("yellow", "yellow"), emulator=tmp_path / "emu",
                    base_config=tmp_path / "cfg", limit=60, input_mode="scripted-normal-buttons",
                    launch_mode="scripted-selected-launcher", route_mode="rb-parcel")
    with pytest.raises(ValueError, match="route requires the scripted Red/Blue pair"):
        SelectedRun(tmp_path / "rb", ("red", "blue"), emulator=tmp_path / "emu",
                    base_config=tmp_path / "cfg", limit=60, input_mode="human",
                    launch_mode="product-cli", route_mode="rb-parcel")


def test_selected_run_accepts_parcel_route_for_scripted_rb_pair(tmp_path):
    run = SelectedRun(tmp_path / "rb", ("red", "blue"), emulator=tmp_path / "emu",
                      base_config=tmp_path / "cfg", limit=60, input_mode="scripted-normal-buttons",
                      launch_mode="scripted-selected-launcher", route_mode="rb-parcel")
    assert run.route_mode == "rb-parcel"


def test_route_rb_parcel_tampered_second_module_refused(tmp_path):
    root, spec, rom, launcher, base_config = _inputs(tmp_path)
    plan = prepare_scripted_plan(root, spec, rom=rom, launcher=launcher, base_config=base_config,
                                  route_mode="rb-parcel")
    staged = Path(plan["cwd"])
    tampered = staged / PARCEL_MODULE.name
    tampered.write_bytes(tampered.read_bytes() + b"\n-- tampered")
    with pytest.raises(ValueError, match="existing R/B route module differs"):
        prepare_scripted_plan(root, spec, rom=rom, launcher=launcher, base_config=base_config,
                              route_mode="rb-parcel")


def _parcel_document(pokeballs_obtained, activations):
    return {"rules": {"core": {"links": [{"status": "alive"}],
                               "pokeballs_obtained": pokeballs_obtained}},
            "components": {"gen1-faint-settlement": {"activations": activations, "deaths": {}}}}


def _parcel_marker(ball_count=5):
    return {"stage": "first-ball-readback",
            "point": {"oak_got_parcel": True, "parcel_count": 0, "ball_count": ball_count}}


def test_verify_parcel_checkpoint_passes_with_both_activations_and_pokeballs():
    document = _parcel_document({"a": True, "b": True},
                                {"a": {"engine_record": {}, "index": 0},
                                 "b": {"engine_record": {}, "index": 1}})
    markers = {"a": _parcel_marker(), "b": _parcel_marker()}
    evidence = verify_parcel_checkpoint(document, markers)
    assert set(evidence["activations"]) == {"a", "b"}


def test_verify_parcel_checkpoint_refuses_missing_activation():
    document = _parcel_document({"a": True, "b": True},
                                {"a": {"engine_record": {}, "index": 0}})
    markers = {"a": _parcel_marker(), "b": _parcel_marker()}
    with pytest.raises(AssertionError):
        verify_parcel_checkpoint(document, markers)
