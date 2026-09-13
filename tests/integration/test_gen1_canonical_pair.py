"""The canonical companion pair as a prepared pair: staged inside the run from the admitted CLEAN
cartridges, pinned to the installed catalog, selected by create_runtime(native_trade=True), persisted,
rebuilt by the plain PreparedCartridges(artifacts) readback, and emitted as the launcher's native
manifest. No UPR, no seeds; never a randomized patch target."""
import hashlib
import json
from pathlib import Path

import pytest

from server.gen1_cartridge_profiles import companion_profiles
from server.gen1_launcher import build_configuration, configuration
from server.gen1_patcher_targets import prepared_targets
from server.gen1_prepared_cartridges import CANONICAL_SCHEMA, PreparedCartridges, stage_canonical_pair
from server.gen1_run_config import configure_runtime, create_runtime, open_runtime, read_bound_configuration
from server.protocol_journal import JournalError

ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "data/pret_sources.lock.json").read_text())
CLEAN = {"red": ROOT / LOCK["clean_roms"]["pokered"]["filename"], "blue": ROOT / LOCK["clean_roms"]["pokeblue"]["filename"],
         "yellow": ROOT / LOCK["clean_roms"]["pokeyellow"]["filename"]}
pytestmark = pytest.mark.skipif(not all(p.is_file() for p in CLEAN.values()), reason="legal clean RBY cartridges required")


def staged(tmp_path, variants=("yellow", "yellow")):
    run = tmp_path / "run"
    run.mkdir(parents=True)
    return run, stage_canonical_pair(run / "prepared", {"a": CLEAN[variants[0]], "b": CLEAN[variants[1]]})


@pytest.mark.parametrize("variants", [("red", "blue"), ("yellow", "yellow")])
def test_staged_pair_is_the_installed_canonical_companion_and_reopens_by_plain_constructor(tmp_path, variants):
    run, directory = staged(tmp_path, variants)
    cartridges = PreparedCartridges(directory)  # the same call gen1_run_config.read_bound_configuration makes
    assert cartridges.provenance == "canonical_companion"
    contract = cartridges.contract()
    assert cartridges.validate_contract(contract) == contract["players"]
    for player, variant in zip(("a", "b"), variants):
        installed = companion_profiles()[variant]
        entry = contract["players"][player]
        assert entry["variant"] == variant and entry["content_profile_schema"] == "gen1-rby-canonical-companion-content-v1"
        assert entry["final_rom_sha1"] == installed["final_rom_sha1"] == hashlib.sha1(cartridges.rom(player)).hexdigest()
        manifest = cartridges.manifest(player)
        assert manifest["final_sha1"] == installed["final_rom_sha1"] and manifest["output"] == f"final/{player}/slink_{variant}.gb"
        assert (directory / manifest["output"]).read_bytes() == cartridges.rom(player)
        with pytest.raises(ValueError):
            cartridges.unpatched_rom(player)
        with pytest.raises(ValueError):
            cartridges.patch(player)
    assert prepared_targets(cartridges) == {}


@pytest.mark.parametrize("kind", ["patched_input", "rom_byte", "manifest_field", "descriptor_hash", "not_empty", "aliased_paths", "no_descriptor"])
def test_staging_and_readback_refuse_wrong_inputs_or_tampered_artifacts(tmp_path, kind):
    run = tmp_path / "run"
    run.mkdir()
    if kind == "patched_input":
        _run, directory = staged(tmp_path / "other")
        with pytest.raises(ValueError, match="admitted clean cartridge"):
            stage_canonical_pair(run / "prepared", {"a": directory / "final/a/slink_yellow.gb", "b": CLEAN["yellow"]})
        return
    if kind == "not_empty":
        (run / "prepared").mkdir()
        (run / "prepared" / "stale").write_text("x")
        with pytest.raises(ValueError, match="must be empty"):
            stage_canonical_pair(run / "prepared", {"a": CLEAN["yellow"], "b": CLEAN["yellow"]})
        return
    directory = stage_canonical_pair(run / "prepared", {"a": CLEAN["yellow"], "b": CLEAN["yellow"]})
    index = json.loads((directory / "prepared-artifacts.json").read_text())
    if kind == "rom_byte":
        path = directory / index["players"]["a"]["rom"]
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        index["players"]["a"]["rom_sha256"] = hashlib.sha256(data).hexdigest()  # a re-hashed descriptor does not launder it
        index["players"]["a"]["rom_sha1"] = hashlib.sha1(data).hexdigest()
    elif kind == "manifest_field":
        path = directory / index["players"]["a"]["manifest"]
        manifest = json.loads(path.read_bytes())
        manifest["foreground"]["overlay"] += 1
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(encoded)
        index["players"]["a"]["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
    elif kind == "aliased_paths":
        # Both players pointed at player a's (valid, catalog-exact) files: every hash matches, the path does not.
        index["players"]["b"]["rom"] = index["players"]["a"]["rom"]
        index["players"]["b"]["manifest"] = index["players"]["a"]["manifest"]
    elif kind == "no_descriptor":
        (directory / "prepared-artifacts.json").unlink()  # a partial stage (artifacts, no descriptor) is refused
        with pytest.raises(FileNotFoundError):
            PreparedCartridges(directory)
        return
    else:
        index["players"]["a"]["content_profile_hash"] = "0" * 64
    (directory / "prepared-artifacts.json").write_text(json.dumps(index))
    with pytest.raises(ValueError, match="differs"):
        PreparedCartridges(directory)


def test_native_runtime_selects_persists_and_reopens_the_canonical_pair_and_launcher_emits_its_manifest(tmp_path):
    run, directory = staged(tmp_path)
    cartridges = PreparedCartridges(directory)
    with pytest.raises(JournalError, match="reproduced prepared cartridges"):
        create_runtime(tmp_path / "without", cartridges.contract(), native_trade=True, free_service=True)
    runtime = create_runtime(run, cartridges.contract(), prepared_cartridges=cartridges, native_trade=True, free_service=True)
    try:
        assert runtime.native_trade is True and runtime.free_service is True and runtime.trade is not None
        value = configure_runtime(runtime)
        assert value["native_trade"] is True and value["free_service"] is True and value["prepared_artifacts"] == "prepared"
        launch = configuration(runtime, "a")
        assert launch["mode"] == "free_service" and launch["native_manifest"]["final_sha1"] == companion_profiles()["yellow"]["final_rom_sha1"]
        assert launch["native_manifest"]["output"] == "final/a/slink_yellow.gb"
        assert any(str(row.get("path", row)).endswith("gen1_native_runtime.lua") for row in launch["files"])
    finally:
        runtime.close()
    stored, rebuilt = read_bound_configuration(run)
    assert stored["native_trade"] is True and rebuilt.provenance == "canonical_companion"
    assert rebuilt.contract() == cartridges.contract() and rebuilt.rom("b") == cartridges.rom("b")
    reopened = open_runtime(run)
    try:
        assert reopened.native_trade is True and reopened.prepared_cartridges.provenance == "canonical_companion"
        assert build_configuration(reopened.journal.run_id, reopened.contract, "b", prepared_cartridges=reopened.prepared_cartridges,
                                   initial_observations=True, native_trade=True, free_service=True)["native_manifest"]["output"] == "final/b/slink_yellow.gb"
    finally:
        reopened.close()
    # A run whose staged pair was tampered with after publication does not reopen as native.
    index_path = directory / "prepared-artifacts.json"
    index = json.loads(index_path.read_text())
    index["players"]["b"]["content_profile_hash"] = "0" * 64
    index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match="differs"):
        read_bound_configuration(run)
    assert index["schema"] == CANONICAL_SCHEMA
