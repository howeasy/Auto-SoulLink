"""Metadata-only RBY admission for the durable runtime, separate from wire v1."""
from __future__ import annotations

import copy
import re

from server.gen1_cartridge_profiles import validate_runtime_contract
from server.protocol import ProtocolError, SessionGate, canonical_json, digest
from server.save_identity import SaveIdentity

PROTOCOL = "slink-gen1-durable-v1"
HOLD_EVENT = "gen1_hold"
METADATA_SCHEMA = "slink-gen1-runtime-metadata-v1"
FIELDS = {"schema", "cartridge", "save_identity", "physical_instance"}
SCOPE = "metadata_only_no_physical_readiness"


def validate_hello(contract, player, message, identity=None, *, run_id,contract_validator=validate_runtime_contract):
    if player not in ("a", "b") or not isinstance(message, dict):
        raise ProtocolError("RBY player and HELLO metadata required")
    # Do not silently ignore old snapshots at this boundary: they must be
    # journaled and explicitly reconciled after metadata admission.
    allowed = {"protocol", "player", "event", "seq", "operation_id", "client_nonce", "context_generation", "gen1_metadata", "run_id"}
    if set(message) - allowed:
        raise ProtocolError("durable RBY HELLO must contain metadata only")
    if message.get("run_id") != run_id:
        raise ProtocolError("RBY launcher belongs to a different run")
    expected = contract_validator(contract)[player]
    payload = message.get("gen1_metadata")
    if not isinstance(payload, dict) or set(payload) != FIELDS or payload["schema"] != METADATA_SCHEMA:
        raise ProtocolError("complete RBY runtime metadata required")
    if canonical_json(payload["cartridge"]) != canonical_json(expected):
        raise ProtocolError("RBY cartridge differs from this player's verified contract")
    instance = payload["physical_instance"]
    if not isinstance(instance, str) or not re.fullmatch(r"[0-9a-f]{32}", instance):
        raise ProtocolError("RBY physical instance identity required")
    save = payload["save_identity"]
    if (not isinstance(save, dict) or set(save) != {"ot_id", "trainer_name"}
            or not isinstance(save["ot_id"], str) or not re.fullmatch(r"[0-9A-F]{4}", save["ot_id"])
            or not isinstance(save["trainer_name"], str) or not 1 <= len(save["trainer_name"]) <= 10
            or not save["trainer_name"].strip() or not save["trainer_name"].isprintable()):
        raise ProtocolError("RBY save trainer identity required")
    SaveIdentity(**save)
    if identity is not None and save != identity:
        raise ProtocolError("RBY save trainer ID/name differs from the established player")
    return {"game_id": "gen1_rby", "rom_type": expected["variant"], "player": player, "run_id": run_id,
            "contract_digest": digest(contract), "save_identity": copy.deepcopy(save),
            "gen1_metadata": copy.deepcopy(payload), "scope": SCOPE}


def validate_pair(a, b):
    if (a["player"] != "a" or b["player"] != "b" or a["contract_digest"] != b["contract_digest"]
            or a["gen1_metadata"]["physical_instance"] == b["gen1_metadata"]["physical_instance"]):
        raise ProtocolError("RBY requires distinct physical instances in one paired contract")


def new_session_gate(*, run_id, nonce_registry=None,contract_validator=validate_runtime_contract):
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ProtocolError("durable RBY run identity required")
    def validate(contract, player, message, identity=None):
        return validate_hello(contract, player, message, identity, run_id=run_id,contract_validator=contract_validator)
    return SessionGate(protocol=PROTOCOL, hello_validator=validate, durable_ids=True, nonce_registry=nonce_registry)
