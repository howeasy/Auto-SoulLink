"""RBY cartridge admission and connection-bound envelopes.

This boundary authenticates cartridge agreement, not the remote user. Clean ROMs
are proved by complete canonical hashes. No partial encounter fingerprint can
authorize a modified ROM. Durable semantic replay/command completion is a separate
layer; session-local retry below must never be described as durable delivery.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from server.gen1_party_codec import PartyCodec, PartyCodecError
from server.protocol import (
    ProtocolError as AdmissionError,
    SessionGate as ProtocolSessionGate,
    canonical_json,
    decode_frame,
    digest,
    nack as protocol_nack,
)

PROTOCOL = "slink-gen1-session-v1"
CONTRACT_SCHEMA = "slink-gen1-contract-v1"
CATALOG = Path(__file__).resolve().parents[1] / "data/games/gen1_rby/admission_profiles.json"
VARIANTS = {"red", "blue", "yellow"}


def clean_profiles():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if data.get("schema") != "gen1-rby-admission-catalog-v1" or set(data.get("profiles", {})) != VARIANTS:
        raise AdmissionError("invalid installed admission catalog")
    for variant, profile in data["profiles"].items():
        body = {k: v for k, v in profile.items() if k != "content_profile_hash"}
        if profile.get("variant") != variant or digest(body) != profile.get("content_profile_hash"):
            raise AdmissionError("installed admission profile hash mismatch")
    return data["profiles"]


def cartridge_metadata(profile):
    return {"variant": profile["variant"], "final_rom_sha1": profile["final_rom_sha1"],
            "content_profile_schema": profile["schema"], "content_profile_hash": profile["content_profile_hash"],
            "patch_version": profile["patch_version"], "capabilities": copy.deepcopy(profile["capabilities"]),
            "party_codec": profile["party_codec"]}


def clean_contract(rom_paths):
    """Inspect both actual local files before constructing a Manager contract."""
    if not isinstance(rom_paths, dict) or set(rom_paths) != {"a", "b"}:
        raise AdmissionError("select a local ROM for both players")
    catalog = clean_profiles()
    players = {}
    for player, path in rom_paths.items():
        if not isinstance(path, (str, Path)):
            raise AdmissionError(f"invalid ROM path for player {player}")
        with Path(path).open("rb") as stream:
            rom = stream.read(1024 * 1024 + 1)
        if len(rom) != 1024 * 1024:
            raise AdmissionError(f"player {player}: unsupported ROM size")
        sha1 = hashlib.sha1(rom).hexdigest()
        profile = next((p for p in catalog.values() if p["final_rom_sha1"] == sha1), None)
        if profile is None or hashlib.sha256(rom).hexdigest() != profile["rom_sha256"]:
            raise AdmissionError(f"player {player}: ROM needs a verified full semantic scan; only canonical clean RBY is currently admitted")
        players[player] = cartridge_metadata(profile)
    return {"schema": CONTRACT_SCHEMA, "players": players}


def validate_contract(contract):
    if not isinstance(contract, dict) or contract.get("schema") != CONTRACT_SCHEMA:
        raise AdmissionError("configure verified cartridges for both players in Manager")
    players = contract.get("players")
    if not isinstance(players, dict) or set(players) != {"a", "b"}:
        raise AdmissionError("the cartridge contract must name both players")
    catalog = clean_profiles()
    for player, expected in players.items():
        if not isinstance(expected, dict) or expected.get("variant") not in VARIANTS:
            raise AdmissionError(f"player {player}: invalid expected variant")
        actual = cartridge_metadata(catalog[expected["variant"]])
        # Serialized comparison distinguishes bool from int (False != 0 on the wire).
        if canonical_json(expected) != canonical_json(actual):
            raise AdmissionError(f"player {player}: unsupported or unverified cartridge provenance")
    return players


def write_contract(path, contract):
    """Publish only a fully verified contract. An existing binding is immutable."""
    validate_contract(contract)
    path = Path(path)
    if path.exists():
        existing = decode_frame(path.read_bytes())
        if canonical_json(existing) == canonical_json(contract):
            return
        raise AdmissionError("this run is already bound to different cartridges; use a new run")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", delete=False,
                                         dir=path.parent, prefix=".cartridge-", suffix=".tmp") as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(contract, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_hello(contract, player, msg, identity=None):
    expected = validate_contract(contract).get(player)
    if expected is None:
        raise AdmissionError("invalid player slot")
    if not isinstance(msg.get("rom_type"), str) or msg["rom_type"].lower() != expected["variant"]:
        raise AdmissionError("ROM title differs from this player's contract")
    reported = {key: msg.get(key) for key in expected}
    if canonical_json(reported) != canonical_json(expected):
        raise AdmissionError("cartridge hash, profile, codec or capabilities differ from this player's contract")
    ot_id = msg.get("ot_id")
    name = msg.get("trainer_name")
    if not isinstance(ot_id, str) or not re.fullmatch(r"[0-9A-F]{4}", ot_id):
        raise AdmissionError("a valid save player ID is required")
    if not isinstance(name, str) or not name.strip() or len(name) > 10 or any(ord(c) < 32 for c in name):
        raise AdmissionError("a live save trainer name is required")
    if identity and identity.get("ot_id") != ot_id:
        raise AdmissionError("save player ID differs from the identity bound to this player slot")
    if not isinstance(msg.get("party"), list) or len(msg["party"]) > 6:
        raise AdmissionError("invalid HELLO party snapshot")
    if msg["party"]:
        codec = PartyCodec(expected["variant"])
        keys = set()
        try:
            for slot, entry in enumerate(msg["party"]):
                if not isinstance(entry, dict):
                    raise AdmissionError("invalid HELLO party entry")
                encoded = entry.get("blob_hex")
                if not isinstance(encoded, str) or not re.fullmatch(r"[0-9a-fA-F]{132}", encoded):
                    raise AdmissionError("HELLO needs an exact 66-byte party blob")
                mon = codec.validate_blob(bytes.fromhex(encoded), expected_key=entry.get("key"))
                facts = {"key": mon.key, "species_id": mon.species_id, "hp": mon.hp, "maxHP": mon.max_hp,
                         "level": mon.level, "slot": slot, "status_cond": mon.status}
                if canonical_json({key: entry.get(key) for key in facts}) != canonical_json(facts):
                    raise AdmissionError("HELLO party fields differ from the complete cartridge blob")
                if mon.key in keys:
                    raise AdmissionError("duplicate HELLO party key")
                keys.add(mon.key)
        except PartyCodecError as exc:
            raise AdmissionError("invalid HELLO party: " + str(exc)) from exc
    return copy.deepcopy(expected)


class SessionGate(ProtocolSessionGate):
    """RBY cartridge policy on the shared transport session boundary."""
    def __init__(self):
        super().__init__(protocol=PROTOCOL, hello_validator=validate_hello)


def nack(msg, reason, *, pending=False):
    return protocol_nack(msg, reason, pending=pending, protocol=PROTOCOL)
