"""Complete RBY rules, identity registry and recovery in one journal aggregate."""

from __future__ import annotations

import copy

from server.gen1_cartridge_profiles import validate_runtime_contract
from server.gen1_runtime_admission import validate_hello, validate_pair
from server.gen1_staged_state import StagedGen1State
from server.gen1_trade_recovery import (
    COMPONENT as TRADE_COMPONENT,
    REASON as TRADE_REASON,
    blockers,
    transactions,
)
from server.identity_registry import IdentityRegistry
from server.json_value_copy import copy_json
from server.paired_recovery import RecoveryBarrier
from server.protocol import digest
from server.protocol_journal import JournalError, _encode
from server.trade_coordinator import SCHEMA, TradeCoordinator

COMPONENT = "gen1-runtime"
COMPONENT_SCHEMA = "slink-gen1-runtime-state-v1"


def recovery_history(rules, identities, active_trade, trade_component=None):
    # Display/stat/party caches alone do not change semantic rule history.
    core = {k: v for k, v in rules["core"].items() if k != "mon_stats"}
    history = {
        "rules": core,
        "memorial": rules["memorial"],
        "identities": identities,
        "active_trade": active_trade,
    }
    if trade_component is not None:
        history["trade"] = trade_component
    return digest(history)


class Gen1RuntimeState:
    validate_contract=staticmethod(validate_runtime_contract)

    def __init__(self, document, *, data_dir):
        _encode(document)
        if (
            set(document) != {"schema", "rules", "identities", "active_trade", "components"}
            or document["schema"] != SCHEMA
            or not isinstance(document["components"], dict)
        ):
            raise JournalError("explicit coordinated RBY state required")
        self._document = copy_json(document)
        self.rules = StagedGen1State.restore(document["rules"], data_dir=data_dir)
        if any(self.rules.queued_commands.values()):
            raise JournalError(
                "RBY runtime bootstrap/snapshots require commands already published to the journal"
            )
        identities = document["identities"]
        self.identities = IdentityRegistry.restore(identities, run_id=identities.get("run_id"))
        component = self._document["components"].get(COMPONENT)
        if (
            not isinstance(component, dict)
            or set(component) != {"schema", "contract", "admissions", "recovery"}
            or component["schema"] != COMPONENT_SCHEMA
            or not isinstance(component["admissions"], dict)
            or set(component["admissions"]) != {"a", "b"}
        ):
            raise JournalError("complete RBY runtime component required")
        self.component = component
        expected = self.validate_contract(component["contract"])
        if self.rules.rom_type and self.rules.rom_type.lower() != expected["a"]["variant"]:
            raise JournalError("RBY primary rule variant differs from the paired contract")
        # from_document rebuilt the adapter from the primary variant alone; the partner
        # cartridge decides the starter clause policy (Yellow/Yellow is a fixed-species gift).
        self.rules.adapter.bind_peer(expected["b"]["variant"])
        self.barrier = RecoveryBarrier.restore(component["recovery"])
        expected_blockers = blockers(self._document)
        actual_blockers = {
            key: reason
            for key, reason in self.barrier.document()["blockers"].items()
            if reason == TRADE_REASON
        }
        if actual_blockers != expected_blockers:
            raise JournalError("RBY trade recovery obligations differ from committed phases")
        for player, record in component["admissions"].items():
            if record is None:
                continue
            if not isinstance(record, dict) or set(record) != {"metadata", "binding"}:
                raise JournalError("invalid persisted RBY admission")
            metadata = record["metadata"]
            checked = validate_hello(
                component["contract"],
                player,
                {"gen1_metadata": metadata.get("gen1_metadata"), "run_id": metadata.get("run_id")},
                run_id=identities["run_id"],
                contract_validator=self.validate_contract,
            )
            if checked != metadata:
                raise JournalError("persisted RBY admission differs from its contract")
            RecoveryBarrier._validate_binding(record["binding"])
            if self.barrier.document()["bindings"][player] != record["binding"]:
                raise JournalError("persisted RBY admission and recovery binding differ")
        if all(component["admissions"].values()):
            validate_pair(*(component["admissions"][p]["metadata"] for p in ("a", "b")))
        if self.barrier.document()["history_digest"] != self.history_digest():
            raise JournalError("RBY recovery history differs from committed rules/identities")
        from server.gen1_initial_observation import verify_state
        verify_state(self)
        from server.gen1_inventory_observation import verify_state as verify_inventory
        verify_inventory(self)
        from server.gen1_bootstrap_runtime import verify_state as verify_bootstrap
        verify_bootstrap(self)
        from server.gen1_initial_save_runtime import verify_state as verify_initial_save
        verify_initial_save(self)
        from server.gen1_native_frame_accounting import (
            validate_ledger,
            validate_state as verify_native_frames,
        )
        validate_ledger(self.document())
        verify_native_frames(self.document())
        from server.gen1_engine_signal_runtime import verify_state as verify_signals
        verify_signals(self)
        from server.gen1_starter_settlement import verify_state as verify_starters
        verify_starters(self)
        from server.gen1_faint_runtime import verify_state as verify_faints
        verify_faints(self)
        from server.gen1_whiteout import verify_state as verify_whiteouts
        verify_whiteouts(self)
        from server.gen1_memorial_runtime import verify_state as verify_memorials
        verify_memorials(self)
        from server.gen1_acquisition_runtime import verify_state as verify_acquisitions
        verify_acquisitions(self)
        from server.gen1_native_observation import verify_state as verify_native_observations
        verify_native_observations(self)
        from server.gen1_native_windows import verify_state as verify_native_windows
        verify_native_windows(self)
        from server.gen1_native_preparation import verify_state as verify_native_preparation
        verify_native_preparation(self)
        from server.gen1_static_lifecycle import (
            COMPONENT as STATICS,
            verify_state as verify_statics,
        )
        verify_statics(self._document['components'].get(STATICS, {}))
        from server.gen1_static_lifecycle import HOLD_REASON as STATIC_HOLD, held_blockers
        if {k: v for k, v in self.barrier.document()['blockers'].items() if v == STATIC_HOLD} != held_blockers(self._document):
            raise JournalError('ambiguous static captures lost their recovery holds')
        from server.gen1_npc_exchange_runtime import verify_state as verify_exchanges
        verify_exchanges(self)
        from server.gen1_wild_encounter_runtime import verify_state as verify_encounters
        verify_encounters(self)
        from server.gen1_storage_runtime import verify_state as verify_storage
        verify_storage(self)
        from server.gen1_evolution_runtime import verify_state as verify_evolutions
        verify_evolutions(self)

    @classmethod
    def initial(cls, rules, identities, contract, *, data_dir):
        """Explicit bootstrap input only; never called from a received HELLO."""
        document = TradeCoordinator.initial_state(rules, identities)
        document["components"][COMPONENT] = {
            "schema": COMPONENT_SCHEMA,
            "contract": copy.deepcopy(contract),
            "admissions": {"a": None, "b": None},
            "recovery": RecoveryBarrier(recovery_history(rules, identities, None)).document(),
        }
        return cls(document, data_dir=data_dir).document()

    @classmethod
    def restore(cls, document, *, data_dir):
        return cls(document, data_dir=data_dir)

    def history_digest(self):
        return recovery_history(
            self.rules.document(),
            self.identities.document(),
            self._document["active_trade"],
            self._document["components"].get(TRADE_COMPONENT),
        )

    def admit(self, player, metadata, binding):
        old = self.component["admissions"][player]
        known_save = self.rules.player_identity.get(player)
        if (
            (old and old["metadata"]["save_identity"] != metadata["save_identity"])
            or known_save
            and known_save != metadata["save_identity"]
        ):
            raise JournalError("RBY saved identity requires explicit reconciliation/migration")
        peer = "b" if player == "a" else "a"
        other = self.component["admissions"][peer]
        if other:
            records = {player: metadata, peer: other["metadata"]}
            validate_pair(records["a"], records["b"])
        self.barrier.bind(player, **binding)
        self.component["admissions"][player] = {
            "metadata": copy.deepcopy(metadata),
            "binding": dict(binding),
        }

    def handle_event(self, player, message, **options):
        if message["event"] == "hello":
            # Metadata admission is intentionally not the legacy HELLO rule
            # handler: no party adoption, Pokeball inference or queued writes.
            if (
                set(message) != {"event", "gen1_metadata", "run_id"}
                or message["run_id"] != self.identities.document()["run_id"]
            ):
                raise JournalError("RBY durable HELLO cannot carry gameplay observations")
            return []
        if message["event"] == "sync":
            if set(message) != {"event"}:
                raise JournalError("sync cannot carry gameplay observations")
            return []
        if any(entry["phase"] != "offered" for entry in transactions(self._document).values()):
            raise JournalError("native trade owns parties until verified closure")
        return self.rules.handle_event(player, message, **options)

    def take_commands(self, player, immediate):
        commands = self.rules.take_commands(player, immediate)
        self.barrier.set_history(self.history_digest())
        return commands

    def document(self):
        document = copy_json(self._document)
        document["rules"] = self.rules.document()
        document["identities"] = self.identities.document()
        document["components"][COMPONENT]["recovery"] = self.barrier.document()
        return document


def state_type_for(cartridges=None):
    """Bind one reproduced local pair without widening the installed catalog."""
    if cartridges is None:return Gen1RuntimeState
    from server.gen1_prepared_cartridges import PreparedCartridges
    if not isinstance(cartridges,PreparedCartridges):raise JournalError("reproduced prepared cartridge set required")
    class PreparedRuntimeState(Gen1RuntimeState):
        validate_contract=staticmethod(cartridges.validate_contract)
    return PreparedRuntimeState
