"""Duo fixture identities must agree with the Lua mutation before cartridge boot."""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import e2e_duo as duo
import gen1_playthrough as play
import run_gb_gate as gb_gate


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "work tree"
    build = root / "patch/build"
    build.mkdir(parents=True)
    monkeypatch.setattr(duo, "REPO", str(root))
    monkeypatch.setattr(duo, "BUILD", str(build))
    monkeypatch.setattr(duo, "WT_FWD", root.as_posix())
    config = tmp_path / "emulator" / "config.ini"
    config.parent.mkdir()
    config.write_text(json.dumps({"PathEntries": {"Paths": [
        {"System": system, "Type": kind, "Path": "/user/original"}
        for system in ("GBA", "GB_GBC_SGB")
        for kind in ("Base", "ROM", "Save RAM", "Savestates", "Screenshots", "Cheats")]}}))
    monkeypatch.setattr(duo, "BIZHAWK_CONFIG", str(config))
    (root / "data").mkdir()
    wrapper = root / "lua/tests/duo/duo_gb_main.lua"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("if D.mutate_otid then\n M.write_u16_be(M.PLAYER_ID_ADDR, 0x7B0B)\nend\n")
    records, sources = {}, {}
    # Deliberately synthetic geometry differs from real offsets: this checks
    # derivation instead of merely agreeing with a copied 0x2605 constant.
    text = ("01:a600 sGameData\n01:a630 sMainData\n01:b500 sGameDataEnd\n"
            "01:b500 sMainDataCheckSum\n00:d200 wMainDataStart\n00:d355 wPlayerID\n")
    for source, target in (("pokered", "pokered"), ("pokered", "pokeblue"), ("pokeyellow", "pokeyellow")):
        commit = "a" * 40 if source == "pokered" else "b" * 40
        sources[source] = {"commit": commit}
        path = root / ".cache/pret" / source / f"{target}.sym"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        records[target] = {"source_commit": commit,
                           "raw_symbols_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (root / "data/pret_sources.lock.json").write_text(json.dumps({"sources": sources}))
    (root / "data/pret_build_provenance.json").write_text(json.dumps({"roms": records}))
    return root, build


def valid_save(root, build):
    data = bytearray((i * 7 + 3) % 256 for i in range(0x8000))
    data[0x2785:0x2787] = b"\x12\x34"
    data[0x3500] = (~sum(data[0x2600:0x3500])) & 0xFF
    fixture = root / "tests/fixtures/gen1/blue_town.SaveRAM"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_bytes(data)
    isolated = build / "saveram_memorialize_b"
    isolated.mkdir(exist_ok=True)
    copied = isolated / "copied.SaveRAM"
    copied.write_bytes(data)
    return fixture, copied, bytes(data)


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_changes_only_copied_player_id_and_its_checksum(workspace, variant):
    root, build = workspace
    fixture, copied, before = valid_save(root, build)
    assert duo.prepare_gen1_duo_saved_identity(copied, variant, copied.parent) == 0x7B0B
    after = copied.read_bytes()
    assert fixture.read_bytes() == before
    assert after[0x2785:0x2787] == b"\x7b\x0b"
    assert after[0x3500] == (~sum(after[0x2600:0x3500])) & 0xFF
    assert {i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b} == {0x2785, 0x2786, 0x3500}
    # Applying the identity twice is a stable operation, including the checksum.
    duo.prepare_gen1_duo_saved_identity(copied, variant, copied.parent)
    assert copied.read_bytes() == after


def test_reads_the_actual_lua_player_id(workspace):
    root, build = workspace
    _, copied, _ = valid_save(root, build)
    wrapper = root / "lua/tests/duo/duo_gb_main.lua"
    wrapper.write_text("M.write_u16_be(M.PLAYER_ID_ADDR, 0x4321)\n")
    assert duo.prepare_gen1_duo_saved_identity(copied, "blue", copied.parent) == 0x4321
    assert copied.read_bytes()[0x2785:0x2787] == b"\x43\x21"


@pytest.mark.parametrize("failure", ["checksum", "truncated", "symbol_drift", "commit_drift", "missing_id", "gen2"])
def test_invalid_inputs_fail_without_rewriting_copied_save(workspace, failure):
    root, build = workspace
    fixture, copied, original = valid_save(root, build)
    variant = "blue"
    if failure == "checksum":
        data = bytearray(copied.read_bytes())
        data[0x2600] ^= 1
        copied.write_bytes(data)
    elif failure == "truncated":
        copied.write_bytes(original[:200])
    elif failure == "symbol_drift":
        path = root / ".cache/pret/pokered/pokeblue.sym"
        path.write_bytes(path.read_bytes() + b"; drift\n")
    elif failure == "commit_drift":
        path = root / "data/pret_sources.lock.json"
        data = json.loads(path.read_text())
        data["sources"]["pokered"]["commit"] = "c" * 40
        path.write_text(json.dumps(data))
    elif failure == "missing_id":
        (root / "lua/tests/duo/duo_gb_main.lua").write_text("-- no verified mutation\n")
    else:
        variant = "crystal"
    before = copied.read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        duo.prepare_gen1_duo_saved_identity(copied, variant, copied.parent)
    assert copied.read_bytes() == before
    assert fixture.read_bytes() == original
    assert not copied.with_suffix(".SaveRAM.identity.tmp").exists()


def test_source_fixture_cannot_be_passed_as_the_output(workspace):
    root, build = workspace
    fixture, copied, original = valid_save(root, build)
    with pytest.raises(RuntimeError, match="outside the isolated"):
        duo.prepare_gen1_duo_saved_identity(fixture, "blue", copied.parent)
    assert fixture.read_bytes() == original


def test_cleanup_refuses_to_remove_data_outside_worktree(workspace, monkeypatch, tmp_path):
    monkeypatch.setattr(duo, "free_port", lambda: 32123)
    run = duo.DuoRun("memorialize", SimpleNamespace(game="gen1", keep_data=False))
    external = tmp_path / "external-data"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_text("owned by user")
    run.data_dir = str(external)
    with pytest.raises(RuntimeError, match="outside the worktree"):
        run.cleanup(True)
    assert sentinel.read_text() == "owned by user"


@pytest.mark.parametrize("game,expected", [("gen1", "blue"), ("gen1_yellow", "red"), ("gen2", None)])
def test_only_gen1_b_is_prepared_before_its_emulator_launch(workspace, monkeypatch, game, expected):
    root, build = workspace
    events = []
    monkeypatch.setattr(duo, "free_port", lambda: 32123)
    roms = {key: key + ".gb" for key in ("red", "blue", "yellow", "crystal")}
    for key, filename in roms.items():
        (root / filename).write_bytes(b"synthetic ROM " + key.encode())
        (root / (key + ".SaveRAM")).write_bytes(b"fixture")
    monkeypatch.setattr(duo.importlib, "import_module", lambda name: SimpleNamespace(
        ROMS=roms, fixture_path=lambda key, target: root / (key + ".SaveRAM")))
    monkeypatch.setattr(duo.DuoRun, "_remember_process", lambda self, process: None)
    def seed(key, target, dest_dir):
        directory = Path(dest_dir)
        directory.mkdir(parents=True, exist_ok=True)
        assert directory.is_relative_to(build)
        inst = directory.name[-1]
        events.append(("seed", inst))
        path = directory / "copy.SaveRAM"
        path.write_bytes(b"fixture")
        return str(path)
    monkeypatch.setattr(gb_gate, "seed_saveram", seed)
    monkeypatch.setattr(duo, "prepare_gen1_duo_saved_identity",
                        lambda path, variant, directory: events.append(("identity", variant)))
    def launch(args, **kwargs):
        events.append(("launch", "b" if "duo_cfg_b.ini" in args[1] else "a"))
        return SimpleNamespace(pid=1234)
    monkeypatch.setattr(duo.subprocess, "Popen", launch)
    run = duo.DuoRun("memorialize", SimpleNamespace(game=game))
    assert Path(run.data_dir).is_relative_to(build)
    run.start_instances()
    wanted = [("seed", "a"), ("seed", "b")]
    if expected:
        wanted.append(("identity", expected))
    assert events == wanted + [("launch", "a"), ("launch", "b")]
