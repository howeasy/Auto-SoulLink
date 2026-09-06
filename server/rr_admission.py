"""Standalone RR metadata policy for the shared durable SessionGate.

No main-server/client binding, pause actuator, journal, or execution coordinator is
installed here. Passing metadata admission is not physical readiness or proof of
arena ownership. The future coordinator constructs SaveIdentity only from the
returned plain ``save_identity`` and persists the established paired mode.

HELLO adds one ``rr_metadata`` object with schema, loaded_rom_sha1, trainer_id
(unsigned 32-bit), trainer_name, native_descriptor, bundle_hashes, and mode_flags.
SHA-1 identifies the loaded cartridge through BizHawk; SHA-256 remains the native
build artifact binding. Bundle hashes must come from caller-verified load-time
evidence: this adapter does not implement or claim a loader attestation mechanism.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from server.protocol import ProtocolError, SessionGate, decode_frame, digest
from server.save_identity import SaveIdentity

PROTOCOL = "slink-rr-durable-v1"
CONTRACT_SCHEMA = "slink-rr-admission-contract-v1"
METADATA_SCHEMA = "slink-rr-metadata-v1"
BASE_ROM_SHA256 = "679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f"
BASE_ROM_SHA1 = "964f951a0fdaf209e4ea1344883ef0d557bb3a80"
BASE_ROM_MD5 = "8529f3a45d32bce4da637976fcf269d4"
CAPABILITIES = {"receipts_v2": 1, "payload_leases": 2, "storage_guard_v2": 4,
                "descriptor_v1": 8, "reservation_echo_v2": 16}
MODE_FLAGS = ("minimal_grinding", "easy", "hardcore", "restricted", "species_randomizer",
              "learnset_randomizer", "ability_randomizer", "hard_mode_randomizer")
DESCRIPTOR_FIELDS = {"magic", "descriptor_version", "abi", "build_id", "layout_sha256",
                     "capability_mask", "mailbox_address", "mailbox_size", "storage_guard", "capabilities"}
METADATA_FIELDS = {"schema", "loaded_rom_sha1", "trainer_id", "trainer_name",
                   "native_descriptor", "bundle_hashes", "mode_flags"}


def _object(value, label, *, keys=None):
    if not isinstance(value, dict):
        raise ProtocolError(f"RR {label} must be an object")
    if keys is not None and set(value) != set(keys):
        raise ProtocolError(f"RR {label} has missing or unexpected fields")
    return value


def _uint(value, bits, label):
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise ProtocolError(f"RR {label} must be an unsigned {bits}-bit integer")
    return value


def _hash(value, length, label):
    if (not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value)
            or value == "0" * length):
        raise ProtocolError(f"RR {label} must be an explicit lowercase {length}-digit fingerprint")
    return value


def _trainer_name(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 7 or not value.strip()
            or value != value.rstrip() or not value.isprintable()):
        raise ProtocolError("RR trainer_name must be a decoded nonblank name of at most seven characters")
    return value


def _capabilities(value, mask):
    result = _object(value, "capabilities", keys=CAPABILITIES)
    for name, bit in CAPABILITIES.items():
        if type(result[name]) is not bool or result[name] != bool(mask & bit):
            raise ProtocolError(f"RR capability {name} differs from its native bit")
    return dict(result)


def _descriptor(value):
    value = _object(value, "native_descriptor", keys=DESCRIPTOR_FIELDS)
    if value["magic"] != "SLD2":
        raise ProtocolError("RR companion descriptor is missing or unknown")
    for name, expected, bits in (("descriptor_version", 1, 16), ("abi", 2, 16),
                                  ("capability_mask", 31, 32), ("mailbox_size", 64, 16),
                                  ("storage_guard", 0xA2, 16)):
        if _uint(value[name], bits, name) != expected:
            raise ProtocolError(f"RR native {name} is unsupported or stale")
    address = _uint(value["mailbox_address"], 32, "mailbox_address")
    if address % 4 or address < 0x02000000 or address + 64 > 0x02040000:
        raise ProtocolError("RR mailbox address is outside the supported aligned EWRAM range")
    result = dict(value)
    result["build_id"] = _hash(value["build_id"], 64, "native build_id")
    result["layout_sha256"] = _hash(value["layout_sha256"], 64, "native layout_sha256")
    result["capabilities"] = _capabilities(value["capabilities"], value["capability_mask"])
    return result


def _bundles(value):
    value = _object(value, "bundle_hashes", keys={"client_bundle_sha256", "data_bundle_sha256"})
    return {name: _hash(item, 64, name) for name, item in value.items()}


def _mode_flags(value):
    value = _object(value, "mode_flags", keys=MODE_FLAGS)
    if any(type(value[name]) is not bool for name in MODE_FLAGS):
        raise ProtocolError("RR mode flags must be actual booleans")
    for name in MODE_FLAGS:
        if name != "minimal_grinding" and value[name]:
            raise ProtocolError(f"RR mode unsupported: {name}; Default with internal randomizers off is required")
    return dict(value)


def build_contract(native_manifest, *, client_bundle_sha256, data_bundle_sha256):
    """Build a plain expected contract from an explicit generated native manifest.

    A Path is read with the shared strict JSON decoder. A dictionary is useful for
    already-verified artifacts and tests. This consumes build evidence; it does
    not independently rebuild the ROM or attest a remote client's file loader.
    """
    if isinstance(native_manifest, (str, Path)):
        native_manifest = decode_frame(Path(native_manifest).read_bytes())
    manifest = _object(native_manifest, "native build manifest")
    if _uint(manifest.get("schema_version"), 16, "native manifest schema") != 1:
        raise ProtocolError("RR native build manifest schema is unsupported")
    for field, expected in (("base_rom_sha256", BASE_ROM_SHA256), ("base_rom_sha1", BASE_ROM_SHA1),
                            ("base_rom_md5", BASE_ROM_MD5)):
        if manifest.get(field) != expected:
            raise ProtocolError(f"RR exact base build mismatch: {field}")
    rom_sha256 = _hash(manifest.get("rom_sha256"), 64, "patched ROM SHA-256")
    rom_sha1 = _hash(manifest.get("rom_sha1"), 40, "patched ROM SHA-1")
    if rom_sha256 == BASE_ROM_SHA256 or rom_sha1 == BASE_ROM_SHA1:
        raise ProtocolError("RR companion is required; the base image is not admissible")
    descriptor = _descriptor({"magic": "SLD2", **{
        name: manifest.get(name) for name in DESCRIPTOR_FIELDS - {"magic"}
    }})
    if digest(descriptor["capabilities"]) != manifest.get("capabilities_sha256"):
        raise ProtocolError("RR manifest capability hash mismatch")
    size = _uint(manifest.get("descriptor_size"), 32, "descriptor_size")
    address = _uint(manifest.get("descriptor_address"), 32, "descriptor_address")
    if size != 156 or address % 4 or address < 0x08000000 or address + size > 0x0A000000:
        raise ProtocolError("RR native descriptor range is unsupported")
    return {
        "schema": CONTRACT_SCHEMA, "protocol": PROTOCOL, "game_id": "gen3_frlge", "rom_type": "firered_rr",
        "base_rom_sha256": BASE_ROM_SHA256, "rom_sha256": rom_sha256, "rom_sha1": rom_sha1,
        "patch_sha256": _hash(manifest.get("patch_sha256"), 64, "UPS SHA-256"),
        "native_descriptor": descriptor, "descriptor_address": address, "descriptor_size": size,
        "bundle_hashes": _bundles({"client_bundle_sha256": client_bundle_sha256,
                                   "data_bundle_sha256": data_bundle_sha256}),
        "native_manifest_digest": digest(manifest), "allowed_mode": "default",
        "homogeneous_mgm_required": True, "companion_required_both_players": True,
        "scope": "metadata_only_no_physical_readiness",
    }


def _expected_identity(identity):
    if isinstance(identity, SaveIdentity):
        value = {"ot_id": identity.ot_id, "trainer_name": identity.trainer_name}
    else:
        value = _object(identity, "expected save identity", keys={"ot_id", "trainer_name"})
    ot_id = value["ot_id"]
    if not isinstance(ot_id, str) or not re.fullmatch(r"[0-9a-fA-F]{8}", ot_id):
        raise ProtocolError("RR expected save identity needs a verified 32-bit hexadecimal trainer ID")
    return {"ot_id": ot_id.upper(), "trainer_name": _trainer_name(value["trainer_name"])}


def validate_hello(contract, player, message, identity=None):
    """SessionGate callback: normalize read-only RR evidence, without state writes."""
    contract = _object(contract, "admission contract")
    if (contract.get("schema") != CONTRACT_SCHEMA or contract.get("protocol") != PROTOCOL
            or contract.get("game_id") != "gen3_frlge" or contract.get("rom_type") != "firered_rr"
            or contract.get("base_rom_sha256") != BASE_ROM_SHA256
            or contract.get("allowed_mode") != "default"
            or contract.get("homogeneous_mgm_required") is not True
            or contract.get("companion_required_both_players") is not True
            or contract.get("scope") != "metadata_only_no_physical_readiness"):
        raise ProtocolError("RR admission contract is missing or unsupported")
    if player not in ("a", "b"):
        raise ProtocolError("RR player slot must be a or b")
    message = _object(message, "HELLO")
    payload = _object(message.get("rr_metadata"), "metadata", keys=METADATA_FIELDS)
    if payload["schema"] != METADATA_SCHEMA:
        raise ProtocolError("RR metadata schema is stale or missing")
    loaded = _hash(payload["loaded_rom_sha1"], 40, "loaded ROM SHA-1")
    if loaded != _hash(contract.get("rom_sha1"), 40, "contract ROM SHA-1"):
        raise ProtocolError("RR loaded ROM differs from the required companion build")
    descriptor = _descriptor(payload["native_descriptor"])
    if descriptor != _descriptor(contract.get("native_descriptor")):
        raise ProtocolError("RR native build, layout, or capability contract mismatch")
    bundles = _bundles(payload["bundle_hashes"])
    if bundles != _bundles(contract.get("bundle_hashes")):
        raise ProtocolError("RR client or data bundle differs from the required build")
    flags = _mode_flags(payload["mode_flags"])
    trainer_id = _uint(payload["trainer_id"], 32, "SaveBlock2 trainer_id")
    name = _trainer_name(payload["trainer_name"])
    save_identity = {"ot_id": f"{trainer_id:08X}", "trainer_name": name}
    if identity is not None and save_identity != _expected_identity(identity):
        raise ProtocolError("RR wrong save: SaveBlock2 trainer identity differs from the established player")
    trusted_payload = {
        "schema": METADATA_SCHEMA, "loaded_rom_sha1": loaded, "trainer_id": trainer_id,
        "trainer_name": name, "native_descriptor": descriptor, "bundle_hashes": bundles, "mode_flags": flags,
    }
    return {"game_id": "gen3_frlge", "rom_type": "firered_rr", "player": player,
            "rom_sha256": _hash(contract.get("rom_sha256"), 64, "contract ROM SHA-256"),
            "contract_digest": digest(contract), "save_identity": save_identity,
            "mode": "default_mgm_on" if flags["minimal_grinding"] else "default_mgm_off",
            "rr_metadata": copy.deepcopy(trusted_payload), "scope": "metadata_only_no_physical_readiness"}


def validate_pair(player_a_metadata, player_b_metadata):
    """Validate two admitted records. The coordinator must persist the returned mode."""
    records = (player_a_metadata, player_b_metadata)
    for expected_player, record in zip(("a", "b"), records, strict=True):
        record = _object(record, "admitted player metadata")
        if (record.get("player") != expected_player or record.get("scope") != "metadata_only_no_physical_readiness"
                or record.get("game_id") != "gen3_frlge" or record.get("rom_type") != "firered_rr"):
            raise ProtocolError("RR pair requires correctly assigned admitted player records")
        _hash(record.get("contract_digest"), 64, "admitted contract digest")
        payload = _object(record.get("rr_metadata"), "admitted RR metadata", keys=METADATA_FIELDS)
        if payload["schema"] != METADATA_SCHEMA:
            raise ProtocolError("RR admitted metadata schema mismatch")
        _hash(payload["loaded_rom_sha1"], 40, "admitted loaded ROM SHA-1")
        _descriptor(payload["native_descriptor"])
        _bundles(payload["bundle_hashes"])
        expected_save = {"ot_id": f"{_uint(payload['trainer_id'], 32, 'admitted trainer_id'):08X}",
                         "trainer_name": _trainer_name(payload["trainer_name"])}
        if record.get("save_identity") != expected_save:
            raise ProtocolError("RR admitted identity differs from observed save metadata")
        flags = _mode_flags(payload["mode_flags"])
        if record.get("mode") != ("default_mgm_on" if flags["minimal_grinding"] else "default_mgm_off"):
            raise ProtocolError("RR admitted mode differs from observed flags")
    a, b = records
    if a["contract_digest"] != b["contract_digest"] or a.get("rom_sha256") != b.get("rom_sha256"):
        raise ProtocolError("RR players are bound to different release contracts")
    for name in ("loaded_rom_sha1", "native_descriptor", "bundle_hashes"):
        if a["rr_metadata"][name] != b["rr_metadata"][name]:
            raise ProtocolError("RR paired build evidence differs despite its claimed contract")
    if a["mode"] != b["mode"]:
        raise ProtocolError("RR mixed Minimal Grinding modes are unsupported; both players must match")
    return {"mode": a["mode"], "contract_digest": a["contract_digest"],
            "scope": "metadata_only_no_physical_readiness"}


def new_session_gate(*, nonce_registry=None):
    """Use shared durable IDs and envelopes; install no new journal or executor."""
    return SessionGate(protocol=PROTOCOL, hello_validator=validate_hello,
                       durable_ids=True, nonce_registry=nonce_registry)
