"""Read-only runtime inputs for UI extraction, without a presentation endpoint.

The running bindings remain explicit: importing durable primitives does not turn
legacy queues into a journal. Missing operation/recovery evidence stays unknown.
UI Phase3 owns normalization and rendering; this module owns backend facts and
the restrictions actually enforced by the HTTP mutation handlers.
"""
from __future__ import annotations

import copy
import math
import time
from pathlib import Path

from server import gen1_admission
from server.protocol import decode_frame
from server.state import SoulLinkState

SCHEMA = "slink-runtime-boundary-v1"
MAX_SAVED_DOCUMENT_BYTES = 4 * 1024 * 1024
PLAYERS = ("a", "b")
MUTATIONS = ("reset", "restore", "manual_link", "debug_mutation", "attempts_edit")
RESTRICTED_REASON = "RBY run changes are unavailable until the operation and recovery interface is connected."
UPR_REASON = "Randomized RBY setup is unavailable in this integration build."
PROFILE_FIELDS = ("variant", "final_rom_sha1", "content_profile_schema", "content_profile_hash",
                  "party_codec", "patch_version", "capabilities")


def restricted_rby(server) -> bool:
    contract = getattr(server, "_rom_contract", None)
    if isinstance(contract, dict) and contract.get("schema") == gen1_admission.CONTRACT_SCHEMA:
        return True
    state = server.state
    return state.adapter.game_id == "gen1_rby" and not state.rom_type.lower().endswith("_ap")


def operation_decision(server, operation: str) -> dict:
    if operation not in MUTATIONS:
        raise ValueError("unclassified runtime operation")
    if restricted_rby(server):
        return {"available": False, "reason_code": "rby_operation_interface_unavailable",
                "reason": RESTRICTED_REASON}
    # Existing generation handlers retain their own validation and execution.
    # This does not certify durable completion or override their preconditions.
    return {"available": True, "reason_code": None, "reason": None}


def randomization_decision() -> dict:
    return {"available": False, "reason_code": "rby_provenance_publisher_unavailable", "reason": UPR_REASON}


def _age(stamp, now):
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0:
        return None
    return max(0.0, now - stamp)


def _optional_call(obj, name):
    method = getattr(obj, name, None)
    return method() if callable(method) else method


def read_rule_state(server) -> dict:
    """Detached live rules. A live document is not a durable commit receipt."""
    runtime = getattr(server, "gen1_runtime", None)
    if runtime is not None:
        stage = runtime.state()
        return {"schema": SCHEMA, "source": "protocol_journal", "document": stage.rules.to_document(),
                "committed_revision": stage.journal_revision}
    return {"schema": SCHEMA, "source": "live_memory", "document": server.state.to_document(),
            "committed_revision": None}


def read_runtime_facts(server, *, now: float | None = None) -> dict:
    """No dispatch, admission, queue draining, file writes, or liveness renewal."""
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError("finite observation clock required")
    runtime = getattr(server, "gen1_runtime", None)
    stage = runtime.state() if runtime is not None else None
    state = stage.rules if stage is not None else server.state
    contract = getattr(server, "_rom_contract", None)
    expected = contract.get("players", {}) if isinstance(contract, dict) else {}
    gate = runtime.gate if runtime is not None else getattr(server, "_gen1_sessions", None)
    sessions = getattr(gate, "sessions", {})
    players = {}
    for player in PLAYERS:
        info = getattr(server, "connected_players", {}).get(player, {})
        admission = getattr(server, "admission", {}).get(player, {"state": "contract_pending", "reason": "No admission evidence."})
        session = sessions.get(player)
        profile = (session.metadata["gen1_metadata"]["cartridge"] if runtime is not None else session.metadata) if session else None
        if runtime is not None:
            admission = {"state": "admitted" if session else "contract_pending",
                "reason": "verified metadata; paired control is separate" if session else stage.barrier.status()["reason"]}
        adapter = server.adapter_for(player)
        is_rby = restricted_rby(server)
        admitted = admission.get("state") == "admitted"
        active_rby_session = is_rby and admitted and session is not None
        adapter_facts = {
            "game_id": adapter.game_id,
            "supports_info_panel": _optional_call(adapter, "supports_info_panel"),
            "supports_explode_mode": _optional_call(adapter, "supports_explode_mode"),
            "has_rival_trainers": bool(adapter.rival_trainer_ids()),
            "supports_abilities": _optional_call(adapter, "supports_abilities"),
            "mons_per_box": _optional_call(adapter, "mons_per_box"),
            "party_blob_size": _optional_call(adapter, "party_blob_size"),
        }
        # These are existing backend gates, not per-command safety permission.
        feature_gates = {
            "panel": server._player_has_panel(player),
            "explode_mode": bool(state.explode_mode and adapter.supports_explode_mode()),
            "rival_team_swap": bool(state.rival_team_swap and adapter.rival_trainer_ids()),
            "pc_trade_npc": False if is_rby else None,
            "native_sounds": None,
        }
        if is_rby:
            if not active_rby_session:
                feature_gates = dict.fromkeys(feature_gates, False)
                adapter_facts = None
            else:
                feature_gates["panel"] = bool(server._player_has_panel(player) and profile["capabilities"]["panel"])
                feature_gates["native_sounds"] = bool(state.native_sounds and profile["capabilities"]["sfx"])
        players[player] = {
            "bound_save_identity": copy.deepcopy(state.player_identity.get(player)),
            "admission": copy.deepcopy(admission),
            "identity_error": state.identity_error.get(player, ""),
            "expected_cartridge": copy.deepcopy(expected.get(player)),
            "declared_cartridge": {name: copy.deepcopy(info.get(name)) for name in ("rom_type", "panel", "panel_abi")},
            "verified_cartridge": copy.deepcopy(profile) if active_rby_session else None,
            "session": {"admission_epoch": gate.epoch, "session_id": session.session_id} if active_rby_session else None,
            "observation": {"connected": info.get("connected", False), "last_event": info.get("last_event"),
                            "last_received_unix": info.get("last_seen_ts"), "age_seconds": _age(info.get("last_seen_ts"), now),
                            "clock": "server_wall_clock", "paired_liveness": None},
            "adapter": adapter_facts, "feature_gates": feature_gates,
            "feature_readiness": None,
        }
    result = {
        "schema": SCHEMA,
        "players": players,
        "requested_rules": copy.deepcopy(state.to_document()["rules"]),
        "persistence": {"mode": "legacy_links_file", "committed_revision": None,
                        "last_write_error": getattr(state, "save_failed", ""), "restore_is_read_only": False},
        "operations": {"delivery": "legacy_volatile", "durable_events": False, "durable_commands": False,
                       "journal_revision": None, "pending_operations": None, "receipts": None,
                       "legacy_queued_count": {p: len(state.queued_commands.get(p, [])) for p in PLAYERS},
                       "http": {name: operation_decision(server, name) for name in MUTATIONS}},
        "recovery": None, "liveness": None,
        "randomization": {**randomization_decision(), "verified_catalog": None, "verified_publisher": None},
        "provenance": {"contract_schema": contract.get("schema") if isinstance(contract, dict) else None,
                       "expected_contract": copy.deepcopy(contract), "complete_hash_chain": None},
    }
    if runtime is not None:
        result["persistence"] = {"mode": "protocol_journal", "committed_revision": stage.journal_revision,
            "last_write_error": runtime.status()["failed"] or "", "restore_is_read_only": False}
        result["operations"].update(delivery="durable_journal", durable_events=True, durable_commands=True,
            journal_revision=stage.journal_revision,
            pending_operations={p: len(runtime.journal.pending(p)) for p in PLAYERS}, legacy_queued_count=None)
        result["recovery"] = stage.barrier.status()
        # Physical host/liveness qualification is not inferred from a metadata
        # session, a durable queue or the existence of a resume ticket.
    return result


def read_saved_run(data_dir) -> dict:
    """Read a stopped legacy run without starting a server, repair, or restore.

    A future durable journal cannot silently fall back to stale links.json.
    Runtime owners must supply a reviewed journal reader before that mode opens.
    """
    directory = Path(data_dir)
    unavailable = {"schema": SCHEMA, "source": "saved_file", "available": False,
                   "document": None, "reason_code": None, "committed_revision": None}
    from server.gen1_run_config import FILENAME, read_configuration
    if (directory/FILENAME).exists():
        try:
            from server.gen1_runtime_state import Gen1RuntimeState
            from server.journal_reader import read_journal
            from server.protocol import digest
            prepared = read_configuration(directory)
            stored = read_journal(directory/prepared["journal"], run_id=prepared["run_id"], contract_hash=digest(prepared["contract"]))
            state = Gen1RuntimeState.restore(stored.snapshot.state, data_dir=str(directory))
            return {"schema": SCHEMA, "source": "protocol_journal", "available": True,
                "document": state.rules.to_document(), "reason_code": None, "committed_revision": stored.snapshot.revision}
        except (OSError, ValueError, RuntimeError, TypeError, KeyError):
            return {**unavailable, "reason_code": "durable_saved_state_invalid"}
    if any(directory.glob("*.sqlite*")):
        return {**unavailable, "reason_code": "durable_saved_reader_unavailable"}
    path = directory / "links.json"
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_SAVED_DOCUMENT_BYTES + 1)
        if len(data) > MAX_SAVED_DOCUMENT_BYTES:
            raise ValueError("saved rule document exceeds the read limit")
        document = decode_frame(data)
        if (not isinstance(document.get("links"), list) or not isinstance(document.get("rules"), dict)
                or not isinstance(document.get("rom_type"), str)):
            raise ValueError("incomplete saved rule document")
        # Strict, side-effect-free restoration validates known rule/adapter data.
        # Return the actual file document, not defaults synthesized by restoration.
        SoulLinkState.from_document(document, data_dir=str(directory))
    except FileNotFoundError:
        return {**unavailable, "reason_code": "saved_state_missing"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {**unavailable, "reason_code": "saved_state_invalid"}
    return {"schema": SCHEMA, "source": "saved_file", "available": True,
            "document": copy.deepcopy(document), "reason_code": None, "committed_revision": None}
