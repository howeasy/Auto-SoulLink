"""Exact pre-fix live-artifact replay and stale-private-pack refusal controls."""

import copy
import hashlib
import json
import uuid
from pathlib import Path

import pytest
from lupa import lua54

from tools import gen3_trade_duo as t5

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "tests/fixtures/gen3/t5_stale_projection"


def captured():
    receipt = json.loads((CAPTURE / "receipt.json").read_text())
    for name, expected in receipt["files"].items():
        assert hashlib.sha256((CAPTURE / name).read_bytes()).hexdigest() == expected
    return {name: json.loads((CAPTURE / name).read_text()) for name in receipt["files"]}


def test_exact_live_pack_reproduces_refusal_and_is_rejected_before_boot():
    data = captured()
    manifest = data["manifest.json"]
    rom_path = ROOT / manifest["rom"]
    if not rom_path.exists():
        pytest.skip("T5 private FR candidate build absent")
    rom = rom_path.read_bytes()
    assert hashlib.sha1(rom).hexdigest() == manifest["rom_sha1"]
    lua = lua54.LuaRuntime(unpack_returned_tuples=True)
    signals = lua.execute((ROOT / "lua/gen3/signals.lua").read_text())
    sites = data["sites.json"]["titles"]["firered"]["artifacts"]["companion"]["sites"]
    io = lua.table(
        rom_read=lambda at, n: lua.table(*rom[at : at + n]),
        read_bytes=lambda at, n: lua.table(*rom[at - 0x8000000 : at - 0x8000000 + n]),
        register=lambda *_: 0,
        framecount=lambda: 0,
    )
    hooks = []
    events = lua.table(
        on_bus_exec=lambda *args: hooks.append(args) or "hook", unregister=lambda *_: None
    )
    with pytest.raises(lua54.LuaError, match="engine sites differ from the ROM: battle_begin"):
        signals.new(
            lua.table_from(data["profile.json"]["titles"]["firered"], recursive=True),
            lua.table_from(sites, recursive=True),
            io,
            events,
        )
    assert hooks == []
    carrier = lua.execute((ROOT / "lua/tests/duo/gen3_trade_candidate.lua").read_text())
    d = lua.table(game="gen3_fr_trade", title="firered", scenario="native_trade_firered")
    with pytest.raises(lua54.LuaError, match="stale T5 manifest"):
        carrier.authorize(
            lua.table_from(manifest, recursive=True), d, manifest["nonce"], manifest["rom_sha1"]
        )


@pytest.fixture
def prepared():
    if not (ROOT / "patch/build/candidate-firered-trade/probe.gba").exists():
        pytest.skip("T5 private FR candidate build absent")
    directory = ROOT / ("patch/build/t5-integrity-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    for name in ("manifest.json", "profile.json", "sites.json", "checkpoint.json"):
        (directory / name).write_bytes((CAPTURE / name).read_bytes())
    assert (directory / "sites.json").read_bytes() == (CAPTURE / "sites.json").read_bytes()
    manifest = t5.prepare(ROOT, directory)
    assert manifest["nonce"] != captured()["manifest.json"]["nonce"]
    t5.validate_prepared(ROOT, manifest)
    return directory, manifest


def test_prepare_overwrites_the_exact_existing_live_pack_and_starts_all_sites(prepared):
    directory, manifest = prepared
    sites = json.loads((directory / "sites.json").read_text())["titles"]["firered"]["artifacts"][
        "companion"
    ]["sites"]
    assert all(row["expected_hex"] == row["expected_hex"].upper() for row in sites.values())
    rom = (ROOT / manifest["rom"]).read_bytes()
    lua = lua54.LuaRuntime(unpack_returned_tuples=True)
    module = lua.execute((ROOT / "lua/gen3/signals.lua").read_text())
    hooks = []
    module.new(
        lua.table(),
        lua.table_from(sites, recursive=True),
        lua.table(
            rom_read=lambda at, n: lua.table(*rom[at : at + n]),
            read_bytes=lambda *_: lua.table(),
            register=lambda *_: 0,
            framecount=lambda: 0,
        ),
        lua.table(
            on_bus_exec=lambda *args: hooks.append(args) or "hook", unregister=lambda *_: None
        ),
    )
    assert len(hooks) == 21


def test_each_preparation_has_an_isolated_journal_and_preserves_prior_evidence(prepared):
    directory, first = prepared
    old = ROOT / (first["journal_path"] + ".log")
    evidence = (ROOT / "tests/fixtures/gen3/t5_832_failure/slink_gen3_trade.log").read_bytes()
    old.write_bytes(evidence)
    second = t5.prepare(ROOT, directory)
    assert second["journal_path"] != first["journal_path"]
    assert old.read_bytes() == evidence
    assert not (ROOT / (second["journal_path"] + ".log")).exists()


@pytest.mark.parametrize("part", ["manifest", "sites", "source"])
def test_prelaunch_refuses_changed_file_digest_and_revert_restores_pass(
    prepared, tmp_path, monkeypatch, part
):
    _, original = prepared
    manifest = copy.deepcopy(original)
    paths = {manifest["path"], *manifest["source_sha1"], *manifest["pack_files"].values()}
    for relative in paths:
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / relative).read_bytes())
    monkeypatch.setattr(
        t5.subprocess, "check_output", lambda *args, **kwargs: manifest["source_commit"] + "\n"
    )
    t5.validate_prepared(tmp_path, manifest)
    path = tmp_path / (
        manifest["path"]
        if part == "manifest"
        else manifest["pack_files"]["sites"]
        if part == "sites"
        else "lua/gen3/run.lua"
    )
    before = path.read_bytes()
    path.write_bytes(before + b"\n")
    with pytest.raises(ValueError, match="stale T5"):
        t5.validate_prepared(tmp_path, manifest)
    path.write_bytes(before)
    t5.validate_prepared(tmp_path, manifest)


@pytest.mark.parametrize("part", ["sites", "source"])
def test_lua_refuses_changed_bound_files_before_entry_selection(part):
    from tests.unit.test_gen3_trade_duo import model_bound_file, model_manifest

    manifest = model_manifest()
    lua = lua54.LuaRuntime(unpack_returned_tuples=True)
    mod = lua.execute((ROOT / "lua/tests/duo/gen3_trade_candidate.lua").read_text())
    changed = manifest["pack_files"]["sites"] if part == "sites" else "lua/gen3/run.lua"

    def read(path):
        return model_bound_file(path) + ("\n" if path == changed else "")

    with pytest.raises(lua54.LuaError, match="stale T5"):
        mod.authorize(
            lua.table_from(manifest, recursive=True),
            lua.table(game="gen3_fr_trade", title="firered", scenario="native_trade_firered"),
            manifest["nonce"],
            manifest["rom_sha1"],
            read,
            lambda raw: hashlib.sha1(raw.encode()).hexdigest(),
        )
