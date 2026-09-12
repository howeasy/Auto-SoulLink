"""Exact installed companion agreement; neither this nor metadata grants frames."""

import copy
import json
from itertools import product
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server.gen1_admission import (
    CONTRACT_SCHEMA,
    AdmissionError,
    cartridge_metadata,
    clean_profiles,
    validate_contract,
)
from server.gen1_cartridge_profiles import companion_profiles, validate_runtime_contract
from server.gen1_runtime_state import Gen1RuntimeState
from server.identity_registry import IdentityRegistry
from server.journal_reader import read_journal
from server.protocol import digest
from server.protocol_journal import JournalError
from tests.unit.test_gen1_runtime_server import RUN_ID, RuntimeCase

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("variants", list(product(("red", "blue", "yellow"), repeat=2)))
@pytest.mark.parametrize("mixed", [False, True])
def test_all_companion_and_clean_mixed_runtime_contracts_admit_metadata_only(
    tmp_path, variants, mixed
):
    case = RuntimeCase(tmp_path, variants)
    try:
        case.close()
        companions, clean = companion_profiles(), clean_profiles()
        case.contract = {
            "schema": CONTRACT_SCHEMA,
            "players": {
                p: cartridge_metadata((clean if mixed and p == "b" else companions)[v])
                for p, v in case.variants.items()
            },
        }
        # A separate explicitly bootstrapped run, not mutation of the original journal's contract.
        case.path = tmp_path / "companion-run"
        case.path.mkdir()
        case.initial = Gen1RuntimeState.initial(
            case.rules, IdentityRegistry(RUN_ID).document(), case.contract, data_dir=case.path
        )
        case.open(initial=True)
        for p in ("a", "b"):
            response = case.admit(p)
            assert (
                response["commands"] == []
                and response["admission"]["scope"] == "metadata_only_no_physical_readiness"
            )
            assert (
                response["admission"]["gen1_metadata"]["cartridge"] == case.contract["players"][p]
            )
        assert case.runtime.state().barrier.ticket() is None
        assert case.runtime.journal.snapshot().state["rules"] == case.rules
    finally:
        case.close()


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_lua_and_python_profiles_agree_including_null_manifest_fields_and_legacy_refusal(variant):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().root = ROOT.as_posix()
    profiles = companion_profiles()
    lua.globals().hash = profiles[variant]["final_rom_sha1"]
    lua.globals().variant = variant
    lua.execute("""
        package.path=root..'/lua/?.lua;'..root..'/data/games/gen1_rby/?.lua;'..package.path
        gameinfo={getromhash=function()return hash end}
        JSON=require('json_codec');Runtime=require('gen1_runtime_profiles')
        Legacy=require('gen1_session')
    """)
    metadata = json.loads(lua.eval("JSON.encode(assert(Runtime.metadata(variant)))"))
    assert metadata == cartridge_metadata(profiles[variant])
    assert lua.eval("select(1,Legacy.metadata(variant))==nil")
    manifest = json.loads(
        lua.eval("JSON.encode(require('gen1_companion_profiles').profiles[variant].manifest)")
    )
    assert manifest == profiles[variant]["manifest"]
    spec = {"schema": CONTRACT_SCHEMA, "players": {"a": metadata, "b": metadata}}
    assert validate_runtime_contract(spec)
    with pytest.raises(AdmissionError):
        validate_contract(spec)
    lua.globals().hash = "f" * 40
    assert lua.eval("select(1,Runtime.metadata(variant))==nil")


@pytest.mark.parametrize(
    "field,value",
    [
        ("patch_version", True),
        ("final_rom_sha1", "f" * 40),
        ("content_profile_hash", "f" * 64),
        ("capabilities", {"panel": True, "sfx": True, "pc_trade": True}),
    ],
)
def test_claimed_capabilities_or_unverified_rom_do_not_create_admission(field, value):
    metadata = cartridge_metadata(companion_profiles()["yellow"])
    changed = copy.deepcopy(metadata)
    changed[field] = value
    with pytest.raises(AdmissionError):
        validate_runtime_contract(
            {"schema": CONTRACT_SCHEMA, "players": {"a": changed, "b": metadata}}
        )


def test_catalog_retains_explicit_semantic_build_identity_and_no_runtime_authority():
    for variant, profile in companion_profiles().items():
        assert digest(profile["manifest"]) == profile["manifest_sha256"]
        assert profile["manifest"]["runtime_ready"] is False
        assert profile["capabilities"] == {
            "panel": variant != "yellow",
            "sfx": False,
            "pc_trade": True,
        }
        assert (profile["manifest"]["companion"]["panel"] is None) == (variant == "yellow")


def test_runtime_writer_lease_precedes_mutation_and_does_not_block_readers(tmp_path):
    case = RuntimeCase(tmp_path)
    try:
        before = case.runtime.journal.snapshot()
        with pytest.raises(RuntimeError, match="another server"):
            case.open()
        assert case.runtime.journal.snapshot() == before
        assert read_journal(case.runtime.journal.path, run_id=RUN_ID).snapshot == before
        case.close()
        case.open()
        assert case.runtime.journal.snapshot().revision > before.revision
    finally:
        case.close()


def test_failed_runtime_construction_releases_its_server_lease(tmp_path):
    case = RuntimeCase(tmp_path)
    original = copy.deepcopy(case.contract)
    try:
        case.close()
        case.contract["players"]["a"]["final_rom_sha1"] = "f" * 40
        with pytest.raises(JournalError, match="different run or cartridge contract"):
            case.open()
        case.contract = original
        case.open()
        assert case.runtime.state().component["contract"] == original
    finally:
        case.close()
