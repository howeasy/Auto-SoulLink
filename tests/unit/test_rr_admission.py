"""Standalone RR policy/provider tests; no main binding or emulator activation."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from lupa import LuaRuntime

from server import rr_admission as rr
from server.protocol import ProtocolError, digest
from server.save_identity import SaveIdentity

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def native_manifest():
    capabilities = dict.fromkeys(rr.CAPABILITIES, True)
    return {"schema_version": 1, "base_rom_sha256": rr.BASE_ROM_SHA256,
            "base_rom_sha1": rr.BASE_ROM_SHA1, "base_rom_md5": rr.BASE_ROM_MD5,
            "rom_sha256": "a" * 64, "rom_sha1": "b" * 40, "patch_sha256": "c" * 64,
            "descriptor_version": 1, "descriptor_size": 156, "descriptor_address": 0x0837B5CC,
            "abi": 2, "build_id": "d" * 64, "layout_sha256": "e" * 64,
            "mailbox_address": 0x0203F800, "mailbox_size": 64, "storage_guard": 0xA2,
            "capability_mask": 31, "capabilities": capabilities,
            "capabilities_sha256": digest(capabilities), "arena_ownership": "unresolved"}


@pytest.fixture
def contract(native_manifest):
    return rr.build_contract(native_manifest, client_bundle_sha256="f" * 64, data_bundle_sha256="1" * 64)


def hello(contract, *, player="a", mgm=False, trainer_id=0x12345678, name="ALICE"):
    return {"event": "hello", "protocol": rr.PROTOCOL, "player": player,
            "client_nonce": ("a" if player == "a" else "b") * 32, "seq": 0,
            "operation_id": ("a" if player == "a" else "b") * 32,
            "rr_metadata": {"schema": rr.METADATA_SCHEMA,
                            "loaded_rom_sha1": contract["rom_sha1"], "trainer_id": trainer_id,
                            "trainer_name": name, "native_descriptor": copy.deepcopy(contract["native_descriptor"]),
                            "bundle_hashes": dict(contract["bundle_hashes"]),
                            "mode_flags": {key: mgm if key == "minimal_grinding" else False for key in rr.MODE_FLAGS}}}


def test_contract_reads_actual_artifact_schema_without_claiming_physical_ready(native_manifest, tmp_path):
    path = tmp_path / "native_manifest.json"
    path.write_text(json.dumps(native_manifest), encoding="utf-8")
    contract = rr.build_contract(path, client_bundle_sha256="f" * 64, data_bundle_sha256="1" * 64)
    assert contract["rom_sha1"] == native_manifest["rom_sha1"]
    assert contract["rom_sha256"] == native_manifest["rom_sha256"]
    assert contract["native_manifest_digest"] == digest(native_manifest)
    assert contract["scope"] == "metadata_only_no_physical_readiness"
    assert contract["companion_required_both_players"] is True


@pytest.mark.parametrize("field,value", [
    ("base_rom_sha256", "a" * 64), ("base_rom_sha1", "b" * 40), ("base_rom_md5", "a" * 32),
    ("rom_sha1", None), ("rom_sha256", rr.BASE_ROM_SHA256), ("descriptor_size", 155),
    ("descriptor_address", 0x0A000000), ("abi", True), ("abi", 1),
    ("capability_mask", 31.0), ("capability_mask", 63), ("capabilities_sha256", "b" * 64),
])
def test_invalid_or_stale_build_contract_is_rejected(native_manifest, field, value):
    native_manifest[field] = value
    with pytest.raises(ProtocolError):
        rr.build_contract(native_manifest, client_bundle_sha256="f" * 64, data_bundle_sha256="1" * 64)


@pytest.mark.parametrize("client,data", [(None, "1" * 64), ("f" * 64, None), (True, "1" * 64),
                                        ("0" * 64, "1" * 64), ("F" * 64, "1" * 64)])
def test_client_data_bundles_are_explicit(client, data, native_manifest):
    with pytest.raises(ProtocolError):
        rr.build_contract(native_manifest, client_bundle_sha256=client, data_bundle_sha256=data)


def test_valid_hello_returns_plain_save_identity_and_detached_metadata(contract):
    message = hello(contract)
    metadata = rr.validate_hello(contract, "a", message, SaveIdentity("12345678", "ALICE"))
    assert metadata["save_identity"] == {"ot_id": "12345678", "trainer_name": "ALICE"}
    assert metadata["mode"] == "default_mgm_off"
    assert metadata["rom_sha256"] == contract["rom_sha256"]
    message["rr_metadata"]["native_descriptor"]["capabilities"]["receipts_v2"] = False
    assert metadata["rr_metadata"]["native_descriptor"]["capabilities"]["receipts_v2"] is True
    json.dumps(metadata)  # No SaveIdentity value object or other runtime object leaks onto the wire.


@pytest.mark.parametrize("trainer_id", [0, 0xFFFFFFFF])
def test_full_uint32_save_identity_range_is_not_confused_with_missing(trainer_id, contract):
    metadata = rr.validate_hello(contract, "a", hello(contract, trainer_id=trainer_id))
    assert metadata["save_identity"]["ot_id"] == f"{trainer_id:08X}"


def test_traded_lead_does_not_change_save_identity(contract):
    message = hello(contract)
    message["party"] = [{"key": "AAAAAAAA:DEADBEEF", "ot_id": "DEADBEEF"}]
    message["ot_id"] = "DEADBEEF"
    metadata = rr.validate_hello(contract, "a", message, {"ot_id": "12345678", "trainer_name": "ALICE"})
    assert metadata["save_identity"]["ot_id"] == "12345678"


def test_existing_identity_is_compared_without_rewriting_legacy_value(contract):
    identity = SaveIdentity("abcdef01", "ALICE")
    metadata = rr.validate_hello(contract, "a", hello(contract, trainer_id=0xABCDEF01), identity)
    assert metadata["save_identity"]["ot_id"] == "ABCDEF01"
    assert identity.ot_id == "abcdef01"


@pytest.mark.parametrize("identity", [SaveIdentity("87654321", "ALICE"),
                                     SaveIdentity("12345678", "BOB"),
                                     SaveIdentity("12345678", ""), {"ot_id": "1234", "trainer_name": "ALICE"}])
def test_wrong_or_incomplete_expected_save_identity_is_rejected(contract, identity):
    with pytest.raises(ProtocolError):
        rr.validate_hello(contract, "a", hello(contract), identity)


@pytest.mark.parametrize("field,value", [("schema", "old"), ("loaded_rom_sha1", "c" * 40),
                                        ("native_descriptor", None), ("bundle_hashes", None),
                                        ("trainer_id", True), ("trainer_id", -1),
                                        ("trainer_id", 2**32), ("trainer_id", 42.0),
                                        ("trainer_name", ""), ("trainer_name", "TOO LONG"),
                                        ("trainer_name", "A\nB"), ("trainer_name", "ALICE ")])
def test_malformed_or_mismatched_metadata_is_rejected(contract, field, value):
    message = hello(contract)
    message["rr_metadata"][field] = value
    with pytest.raises(ProtocolError):
        rr.validate_hello(contract, "a", message)


@pytest.mark.parametrize("field", rr.MODE_FLAGS[1:])
def test_each_non_default_or_randomizer_flag_is_rejected(contract, field):
    message = hello(contract)
    message["rr_metadata"]["mode_flags"][field] = True
    with pytest.raises(ProtocolError, match=field):
        rr.validate_hello(contract, "a", message)


@pytest.mark.parametrize("value", [0, 1, "false", None, []])
def test_mode_flags_are_not_truthiness_coerced(contract, value):
    message = hello(contract)
    message["rr_metadata"]["mode_flags"]["minimal_grinding"] = value
    with pytest.raises(ProtocolError):
        rr.validate_hello(contract, "a", message)


@pytest.mark.parametrize("change", ["build", "layout", "caps_bool", "mask", "wrong_client", "wrong_data"])
def test_native_and_bundle_mismatch_is_rejected(contract, change):
    message = hello(contract)
    native = message["rr_metadata"]["native_descriptor"]
    if change == "build":
        native["build_id"] = "2" * 64
    elif change == "layout":
        native["layout_sha256"] = "2" * 64
    elif change == "caps_bool":
        native["capabilities"]["receipts_v2"] = 1
    elif change == "mask":
        native["capability_mask"] = 15
    else:
        key = "client_bundle_sha256" if change == "wrong_client" else "data_bundle_sha256"
        message["rr_metadata"]["bundle_hashes"][key] = "2" * 64
    with pytest.raises(ProtocolError):
        rr.validate_hello(contract, "a", message)


@pytest.mark.parametrize("mgm", [False, True])
def test_homogeneous_default_pair_is_metadata_valid(contract, mgm):
    a = rr.validate_hello(contract, "a", hello(contract, mgm=mgm))
    b = rr.validate_hello(contract, "b", hello(contract, player="b", mgm=mgm, trainer_id=0x1234, name="BOB"))
    assert rr.validate_pair(a, b)["mode"] == ("default_mgm_on" if mgm else "default_mgm_off")


def test_mixed_mgm_pair_is_rejected_without_changing_either_record(contract):
    a = rr.validate_hello(contract, "a", hello(contract))
    b = rr.validate_hello(contract, "b", hello(contract, player="b", mgm=True))
    before = copy.deepcopy((a, b))
    with pytest.raises(ProtocolError, match="mixed Minimal Grinding"):
        rr.validate_pair(a, b)
    assert (a, b) == before


def test_session_gate_reuses_shared_durable_envelopes(contract):
    gate = rr.new_session_gate()
    message, owner = hello(contract), object()
    session = gate.admit(contract, "a", message, owner, SaveIdentity("12345678", "ALICE"))
    assert gate.durable_ids is True
    assert gate.owns("a", owner)
    assert session.metadata["scope"] == "metadata_only_no_physical_readiness"
    with pytest.raises(ProtocolError, match="wrong save"):
        gate.admit(contract, "b", hello(contract, player="b"), object(), SaveIdentity("87654321", "ALICE"))
    assert "b" not in gate.sessions


def lua_provider(contract, *, mgm=False, trainer_id=0x12345678):
    runtime = LuaRuntime(unpack_returned_tuples=True)
    reads = []
    pointer = 0x02025000
    ram = {pointer + i: byte for i, byte in enumerate([0xBB, 0xC6, 0xC3, 0xBD, 0xBF, 255, 255, 255])}
    for i in range(4):
        ram[pointer + 0xA + i] = (trainer_id >> (8 * i)) & 255
    ram.update({0x0203B25A: 4 if mgm else 0, 0x0203B25B: 0, 0x0203B17B: 0, 0x0203B17C: 0})

    def read8(address):
        reads.append(address)
        return ram[address]

    runtime.globals().read8 = read8
    runtime.globals().read32 = lambda address: pointer if address == 0x0300500C else -1
    runtime.globals().romhash = lambda: "SHA1:" + contract["rom_sha1"].upper()
    runtime.globals().root = ROOT.as_posix()
    runtime.globals().native_json = json.dumps(contract["native_descriptor"])
    runtime.globals().bundle_json = json.dumps(contract["bundle_hashes"])
    runtime.execute("""
        package.path=root..'/lua/?.lua;'..root..'/lua/?/init.lua;'..package.path
        JSON=require('json_codec'); RR=require('rr.admission')
        M={profile_name='radical_red',CFRU_NO_ENCRYPT=true,SB2_PTR_ADDR=0x0300500C,
            CHARSET={[0xBB]='A',[0xC6]='L',[0xC3]='I',[0xBD]='C',[0xBF]='E',[0]=' '}}
        IO={read_u8=function(a) return read8(a) end,
            read_u32_le=function(a) return read32(a) end,
            getromhash=function() return romhash() end,
            write_u8=function() error('ADMISSION MUST NOT WRITE') end}
        native=assert(JSON.decode(native_json)); bundles=assert(JSON.decode(bundle_json))
        function read_report()
            local result,why=RR.read_metadata(M,IO,native,bundles)
            if not result then return nil,why end
            return JSON.encode(result),nil
        end
    """)
    return runtime, ram, reads, pointer


@pytest.mark.parametrize("mgm", [False, True])
def test_lua_reads_loaded_hash_own_save_id_and_exact_mode_flags(contract, mgm):
    runtime, ram, reads, pointer = lua_provider(contract, mgm=mgm)
    text, error = runtime.globals().read_report()
    assert error is None
    report = json.loads(text)
    metadata = rr.validate_hello(contract, "a", report, SaveIdentity("12345678", "ALICE"))
    assert metadata["rr_metadata"]["mode_flags"]["minimal_grinding"] is mgm
    assert metadata["save_identity"]["ot_id"] == "12345678"
    assert {pointer + 0xA + i for i in range(4)} <= set(reads)
    assert set(reads) <= set(ram)  # No party/lead OT or unrelated memory is consulted.


def test_lua_reports_unsupported_flags_without_pretending_default(contract):
    runtime, ram, _, _ = lua_provider(contract)
    ram[0x0203B25A] = 0x08
    text, error = runtime.globals().read_report()
    assert error is None
    report = json.loads(text)
    assert report["rr_metadata"]["mode_flags"]["easy"] is True
    with pytest.raises(ProtocolError, match="easy"):
        rr.validate_hello(contract, "a", report)


@pytest.mark.parametrize("change", ["missing_bundle", "bad_bundle", "missing_descriptor", "stale_abi",
                                     "bad_capability_bool", "wrong_profile", "bad_hash", "bad_mode_read", "blank_name"])
def test_lua_provider_fails_missing_or_malformed_evidence(contract, change):
    runtime, ram, _, pointer = lua_provider(contract)
    edits = {"missing_bundle": "bundles=nil", "bad_bundle": "bundles.client_bundle_sha256=true",
             "missing_descriptor": "native=nil", "stale_abi": "native.abi=1",
             "bad_capability_bool": "native.capabilities.receipts_v2=1",
             "wrong_profile": "M.SB2_PTR_ADDR=0x03003838",
             "bad_hash": "IO.getromhash=function() return 'unknown' end"}
    if change in edits:
        runtime.execute(edits[change])
    elif change == "bad_mode_read":
        ram[0x0203B25A] = True
    else:
        for i in range(8):
            ram[pointer + i] = 0
    text, error = runtime.globals().read_report()
    assert text is None and error


def test_lua_rejects_save_or_mode_drift_between_reads(contract):
    runtime, _, _, _ = lua_provider(contract)
    runtime.execute("""
        local prior=IO.read_u8; local reads=0
        IO.read_u8=function(a)
            if a==0x0203B25A then reads=reads+1;return reads==1 and 0 or 4 end
            return prior(a)
        end
    """)
    text, error = runtime.globals().read_report()
    assert text is None and "changed while reading" in error


def test_lua_rejects_loaded_rom_change_during_metadata_read(contract):
    runtime, _, _, _ = lua_provider(contract)
    runtime.execute("""
        local prior=IO.getromhash;local reads=0
        IO.getromhash=function() reads=reads+1;return reads==1 and prior() or string.rep('2',40) end
    """)
    text, error = runtime.globals().read_report()
    assert text is None and "ROM changed while reading" in error


def test_lua_and_shared_session_accept_only_matching_admission_echo(contract):
    runtime, _, _, _ = lua_provider(contract)
    runtime.execute("""
        Core=require('client_session')
        session=Core.new({player='a',protocol=RR.PROTOCOL,durable_ids=true,
            new_nonce=function() return string.rep('a',32) end,
            read_metadata=function() return RR.read_metadata(M,IO,native,bundles) end,
            metadata_matches=RR.metadata_matches})
        assert(session:begin())
        event={event='hello'};assert(session:decorate(event));session:queued(event)
        hello_json=assert(JSON.encode(event))
        function receive(text)
            local commands,why=session:receive(assert(JSON.decode(text)))
            return commands,why
        end
    """)
    message = json.loads(runtime.globals().hello_json)
    gate, owner = rr.new_session_gate(), object()
    gate.admit(contract, "a", message, owner)
    response = gate.response("a", message, [], hello=True)
    commands, error = runtime.globals().receive(json.dumps(response))
    assert error is None and len(commands) == 0
    assert runtime.globals().session.state == "admitted"
    response["admission"]["save_identity"]["ot_id"] = "87654321"
    runtime.globals().response_json = json.dumps(response["admission"])
    assert runtime.execute("return RR.metadata_matches(assert(JSON.decode(response_json)),session.report)") is False
