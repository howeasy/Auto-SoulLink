"""Gate descriptor/process models: no emulator, ROM/save/fixture data writes."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("gen2_gate_host_test", ROOT / "tools/run_gb_gate.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.fixture
def host(tmp_path, monkeypatch):
    title, artifact = "crystal", "pokecrystal"
    image = (ROOT / ".cache/gen2-build/pokecrystal/pokecrystal.gbc").read_bytes()
    descriptor = dict(runner.describe_gen2(title + "_cold"))
    assert hashlib.sha1(image).hexdigest() == descriptor["rom_sha1"]
    binary = tmp_path / "emulator/EmuHawk.exe"
    binary.parent.mkdir()
    binary.write_text("model executable never run")
    database = binary.parent / "gamedb/gamedb_gbc.txt"
    database.parent.mkdir()
    database.write_text(descriptor["rom_sha1"].upper() + "\tG\t" + descriptor["saveram_name"][:-8] + "\tGBC\n")
    config = tmp_path / "base.ini"
    config.write_text(json.dumps({"PathEntries": {"Paths": [{"System": "GB_GBC_SGB", "Type": "Save RAM", "Path": "unused"}]}}))
    script = tmp_path / "gate.lua"
    script.write_text('local t=G.start("model_gen2_gate")')
    build = tmp_path / "patch/build"
    source = tmp_path / ".cache/gen2-build/pokecrystal"
    virtual_rom = source / "pokecrystal.gbc"
    fixture = tmp_path / "candidate.SaveRAM"
    original_bytes, original_is_file = Path.read_bytes, Path.is_file
    model = {"image": image, "launches": [], "copies": [], "deletes": [], "result": "RESULT: PASS (model)\n", "exit": 0}

    def read_bytes(path):
        return model["image"] if path == virtual_rom else original_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "is_file", lambda path: True if path == fixture else original_is_file(path))
    monkeypatch.setattr(runner, "REPO", str(tmp_path))
    monkeypatch.setattr(runner, "BUILD", str(build))
    monkeypatch.setattr(runner, "EMUHAWK", str(binary))
    monkeypatch.setattr(runner, "BIZHAWK_CONFIG", str(config))
    monkeypatch.setattr(runner, "SAVERAM_DIR", str(tmp_path / "user-save-directory"))
    monkeypatch.setattr(runner, "load_gen2_context", lambda wanted, root: SimpleNamespace(
        title=title, artifact=artifact, rom=image, source_dir=source,
        lock={"outputs": {artifact: {"filename": "pokecrystal.gbc"}}}))
    monkeypatch.setattr(runner.shutil, "copyfile", lambda src, dst: model["copies"].append((str(src), str(dst))))
    original_unlink = Path.unlink

    def unlink(path, *args, **kwargs):
        if path.suffix == ".SaveRAM":
            model["deletes"].append(str(path))
        else:
            original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)

    class Process:
        def poll(self):
            return model["exit"]

        def kill(self):
            model["killed"] = True

        def wait(self, timeout):
            model["waited"] = timeout
            return -1

    def launch(command, **kwargs):
        model["launches"].append((command, kwargs))
        (build / "model_gen2_gate_result.txt").write_text(model["result"])
        return Process()

    monkeypatch.setattr(runner.subprocess, "Popen", launch)
    model.update(root=tmp_path, database=database, config=config, fixture=fixture,
                 directory=tmp_path / ".cache/gen2-fixtures/attempt/case/saveram")
    return model


def invoke(host, **kwargs):
    return runner.run_gate("gate.lua", kwargs.pop("rom_key", "crystal_cold"), quiet=True,
        saveram_dir=host["directory"], speed_percent=300, **kwargs)


@pytest.mark.parametrize("title,sha", [
    ("crystal", "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133"),
    ("gold", "d8b8a3600a465308c9953dfa04f0081c05bdcb94"),
    ("silver", "49b163f7e57702bc939d642a18f591de55d92dae"),
])
def test_metadata_is_explicit_selected_title_cgb_and_immutable(title, sha):
    cold = runner.describe_gen2(title + "_cold")
    assert cold["title"] == title and cold["rom_sha1"] == sha
    assert cold["core_mode"] == "CGB" and cold["cold"] is True
    assert runner.describe_gen2(title)["cold"] is False
    with pytest.raises(TypeError):
        cold["title"] = "another"
    with pytest.raises(ValueError):
        runner.describe_gen2("crystal11")


def test_cold_gate_reuses_one_runner_with_cgb_rtc_speed_and_isolated_save(host):
    passed, _, _ = invoke(host, env_overrides={"SLINK_GEN2_FIXTURE_CASE": '{"attempt_id":"model"}'})
    assert passed and len(host["launches"]) == 1 and not host["copies"]
    assert host["deletes"] == [str(host["directory"] / runner.describe_gen2("crystal")["saveram_name"])]
    command, options = host["launches"][0]
    assert command[-1] == ".cache/gen2-build/pokecrystal/pokecrystal.gbc"
    assert options["env"]["SLINK_GEN2_TITLE"] == "crystal"
    assert options["env"]["SLINK_GEN2_CORE_MODE"] == "CGB"
    assert options["env"]["SLINK_GEN2_COLD"] == "1"
    config_path = host["root"] / next(arg[len("--config="):] for arg in command if arg.startswith("--config="))
    config = json.loads(config_path.read_text())
    sync = config["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]
    assert sync["ConsoleMode"] == 2 and sync["RealTimeRTC"] is False and config["GbAsSgb"] is False
    assert config["SpeedPercent"] == config["SpeedPercentAlternate"] == 300
    assert config["Unthrottled"] is False
    assert Path(config["PathEntries"]["Paths"][0]["Path"]).resolve() == host["directory"]


@pytest.mark.parametrize("field", ["cold", "core_mode", "title", "rom_sha1", "saveram_name"])
def test_missing_descriptor_field_refuses_before_staging_or_launch(host, monkeypatch, field):
    descriptors = dict(runner.GENS["gen2"]["descriptors"])
    broken = dict(descriptors["crystal_cold"])
    del broken[field]
    descriptors["crystal_cold"] = broken
    monkeypatch.setitem(runner.GENS["gen2"], "descriptors", descriptors)
    with pytest.raises(ValueError, match="descriptor"):
        invoke(host)
    assert not host["launches"] and not host["copies"] and not host["deletes"]


def test_wrong_rom_hash_or_gamedb_binding_refuses(host):
    original = host["image"]
    host["image"] = original[:-1] + bytes([original[-1] ^ 1])
    with pytest.raises(ValueError, match="actual ROM"):
        invoke(host)
    host["image"] = original
    host["database"].write_text("no verified entry")
    with pytest.raises(ValueError, match="gamedb"):
        invoke(host)
    assert not host["launches"] and not host["deletes"]


def test_cold_cannot_seed_and_warm_requires_explicit_candidate(host):
    with pytest.raises(ValueError, match="cannot seed"):
        invoke(host, fixture_path=host["fixture"])
    with pytest.raises(ValueError, match="explicit existing"):
        invoke(host, rom_key="crystal")
    assert invoke(host, rom_key="crystal", fixture_path=host["fixture"])[0]
    assert len(host["copies"]) == 1 and not host["deletes"]


def test_global_save_directory_and_legacy_seed_path_are_refused(host):
    host["directory"] = Path(runner.SAVERAM_DIR)
    with pytest.raises(ValueError, match="isolated"):
        invoke(host)
    with pytest.raises(ValueError, match="no implicit"):
        runner.seed_saveram("crystal", "town")
    assert not host["copies"] and not host["deletes"] and not host["launches"]


@pytest.mark.parametrize("result,exit_code", [("RESULT: PASSENGER\n", 0), ("RESULT: PASS\n", 1),
                                              ("RESULT: FAIL\n", 0), ("", 0)])
def test_failed_process_or_nonterminal_result_never_passes(host, result, exit_code):
    host["result"], host["exit"] = result, exit_code
    assert not invoke(host)[0]


def test_timeout_kills_and_waits_without_accepting_a_pass_marker(host, monkeypatch):
    host["exit"] = None
    ticks = iter((0, 0, 2))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    assert not invoke(host, timeout=1)[0]
    assert host["killed"] and host["waited"] == 10


@pytest.mark.parametrize("overrides", [{"PATH": "anything"}, {"SLINK_ROOT": "elsewhere"},
                                       {"SLINK_GEN2_ROM_SHA1": "0" * 40}, {"SLINK_CASE": 4}])
def test_environment_cannot_replace_verified_bindings(host, overrides):
    with pytest.raises(ValueError, match="overrides"):
        invoke(host, env_overrides=overrides)
    assert not host["launches"]


def test_shared_harness_names_no_generation():
    import inspect
    import re
    for function in (runner.seed_saveram, runner.run_gate):
        # A generation key, a generation-named helper or a "Gen N" branch message.
        assert re.search(r"[\"']gen\d[\"']|_gen\d_|Gen \d", inspect.getsource(function)) is None, function.__name__


def test_gen2_refusals_are_driven_by_explicit_descriptor_fields(host, monkeypatch):
    entry = runner.GENS["gen2"]
    assert entry["implicit_staging"] is False and entry["plan"] is runner._gen2_plan
    assert runner.GENS["gen1"]["implicit_staging"] is True and runner.GENS["gen1"]["plan"] is None
    with pytest.raises(ValueError, match="no implicit"):
        runner.seed_saveram("crystal_cold", "town")
    # Known-positive control: flipping the field removes the refusal (the entry has no play module).
    monkeypatch.setitem(entry, "implicit_staging", True)
    with pytest.raises(KeyError):
        runner.seed_saveram("crystal_cold", "town")
    # run_gate reaches the plan only through the descriptor callable.
    calls = []

    def plan(*args):
        calls.append(args)
        raise ValueError("descriptor plan refused")

    monkeypatch.setitem(entry, "plan", plan)
    with pytest.raises(ValueError, match="descriptor plan refused"):
        invoke(host)
    assert calls and not host["launches"] and not host["copies"] and not host["deletes"]
