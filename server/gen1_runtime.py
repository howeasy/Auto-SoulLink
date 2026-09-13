"""Configured RBY binding of the shared durable server service."""

import copy
import secrets
import sqlite3
from pathlib import Path

from server.durable_runtime import TIMEOUT, DurableRuntime
from server.gen1_runtime_admission import HOLD_EVENT, PROTOCOL, new_session_gate
from server.gen1_runtime_state import Gen1RuntimeState, state_type_for
from server.gen1_trade_recovery import compose, transactions, verify_journal
from server.protocol import ProtocolError
from server.protocol_journal import JournalError
from server.runtime_lease import RuntimeLease
from server.trade_coordinator import COMMANDS, TERMINAL, TradeCoordinator

TRADE_EVENTS = {
    "trade_offer",
    "trade_cancel",
    "trade_decision",
    "trade_ready",
    "trade_applied",
    "trade_verified",
    "trade_ack",
}


class _OwnedTradePolicy:
    """Session ownership is checked here in addition to physical policy authority."""

    def __init__(self, runtime, policy):
        self.runtime, self.policy = runtime, policy

    def __getattr__(self, name):
        return getattr(self.policy, name)

    def authorize(self, action, player, authority, state, trade):
        runtime = self.runtime
        runtime.state()  # refuse stale/corrupt component records before any transition or replay
        if authority is runtime._suspension_authority:
            # This capability exists only inside the server lifecycle. It can
            # record loss of authority; it cannot prepare, commit, deliver or resume.
            return action == "interrupt" and player is None
        if player is not None and not runtime.gate.owns(player, authority):
            return False
        if action == "trade_offer" and set(runtime.gate.sessions) != {"a", "b"}:
            return False
        if action != "interrupt":
            for participant in ("a", "b"):
                session = runtime.gate.sessions.get(participant)
                if session is None:
                    return False
                cartridge = session.metadata["gen1_metadata"]["cartridge"]
                if (
                    cartridge["capabilities"]["pc_trade"] is not True
                    or cartridge["party_codec"] != "gen1-rby-party-v1"
                ):
                    return False
        if trade is not None and action != "interrupt":
            for p, participant in trade["proposal"]["participants"].items():
                session = runtime.gate.sessions.get(p)
                if session is None:
                    return False
                context, metadata = participant["context"], session.metadata
                if (
                    context["game_id"] != "gen1_rby"
                    or context["save_identity"] != metadata["save_identity"]
                    or context["physical_instance"]
                    != metadata["gen1_metadata"]["physical_instance"]
                    or context["context_generation"]
                    != metadata["control_binding"]["context_generation"]
                ):
                    return False
        return self.policy.authorize(action, player, authority, state, trade)

    def offer(self, player, payload, state):
        if transactions(state):
            raise JournalError("prior RBY trade closure must finish before another offer")
        proposal = self.policy.offer(player, payload, state)
        if not self.authorize(
            "trade_offer",
            player,
            self.runtime.gate.sessions[player].owner,
            state,
            {"proposal": proposal.document(), "recovery_required": False},
        ):
            raise JournalError("RBY offer differs from current paired admission")
        return proposal


class Gen1Runtime(DurableRuntime):
    def __init__(
        self,
        path,
        *,
        contract,
        data_dir,
        validate_event,
        validate_receipt,
        verify_reconciliation,
        run_id,
        trade_policy=None,
        trade_clock=None,
        verify_operation_execution=None,
        prepared_cartridges=None,
        initial_observations=False,
        native_trade=False,
        free_service=False,
        **options,
    ):
        self.trade = None
        self.trade_driver = None
        self.receptionist = None
        self._memorial_verified=set()
        if type(initial_observations) is not bool:raise JournalError('explicit initial-observation selection required')
        self.initial_observations=initial_observations
        if type(native_trade) is not bool or native_trade and (
                not initial_observations or prepared_cartridges is None or trade_policy is not None):
            raise JournalError('composed native trade requires initial observations and the reproduced cartridge pair')
        self.native_trade = native_trade
        if type(free_service) is not bool or free_service and not initial_observations:
            raise JournalError('free-run observation requires initial observations')
        self.free_service = free_service
        if native_trade:
            from server.gen1_native_policy import NativeTradePolicy
            trade_policy = NativeTradePolicy()
        self._suspension_authority = object()
        self.prepared_cartridges=prepared_cartridges
        stage_type=state_type_for(prepared_cartridges)
        if verify_operation_execution is not None and not callable(verify_operation_execution):
            raise JournalError("operation execution verifier must be callable")
        self.verify_operation_execution=verify_operation_execution
        if not callable(validate_event):
            raise JournalError("RBY semantic event policy required")

        def event_policy(player, message, state):
            if message["event"] == "hello":
                return  # The metadata-only gate already validated it.
            return validate_event(player, message, state)

        def gate_factory(*, nonce_registry):
            return new_session_gate(run_id=run_id, nonce_registry=nonce_registry,contract_validator=stage_type.validate_contract)

        self._run_lease = RuntimeLease(Path(data_dir) / ".server.lock")
        self._run_lease.__enter__()
        try:
            super().__init__(
                path,
                contract=contract,
                data_dir=data_dir,
                protocol=PROTOCOL,
                hold_event=HOLD_EVENT,
                run_id=run_id,
                stage_type=stage_type,
                new_session_gate=gate_factory,
                validate_event=event_policy,
                validate_receipt=validate_receipt,
                verify_reconciliation=verify_reconciliation,
                **options,
            )
            self.journal.enable_verified_row_cache()
            if trade_policy is not None:
                self.trade = TradeCoordinator(
                    self.journal,
                    _OwnedTradePolicy(self, trade_policy),
                    clock=trade_clock,
                    compose_components=lambda state, trade, commands, acknowledgements: compose(
                        self.journal,
                        state,
                        trade,
                        commands,
                        acknowledgements,
                        data_dir=self.data_dir,
                        native=trade_policy,
                        state_type=self._stage_type,
                    ),
                )
                if native_trade:
                    from server.gen1_native_binding import (
                        install_native_driver,
                        install_native_execution,
                    )
                    from server.gen1_native_observation import candidate_checkpoints, checkpoints
                    execution = install_native_execution(self)
                    trade_policy.configure(execution, read_checkpoints=lambda: checkpoints(self),
                                           read_candidate_checkpoints=lambda player: candidate_checkpoints(self, player))
                    trade_policy.install_receptionist()
                    install_native_driver(self, authority=trade_policy.control)
                self._interrupt_trades("runtime reopened; native recovery requires fresh verification")
        except Exception:
            try:
                if hasattr(self, "journal"):
                    self.journal.close()
            finally:
                self._run_lease.__exit__()
            raise

    def close(self):
        super().close()
        self._run_lease.__exit__()

    def _process(self, message, owner):
        response = super()._process(message, owner)
        if message.get("event") == "native_reattach" and response.get("ack") == "ACK":
            # DurableRuntime ignores the dispatch result; the committed verdict rides the ACK and the
            # enriched response is re-cached for byte-identical retries (as observation_result below).
            from server.gen1_native_reattach_runtime import attach_result
            return attach_result(self, message["player"], message, response)
        if message.get("event") != "observation" or response.get("ack") != "ACK":
            return response
        # A transport ACK alone cannot tell the free client whether its exact
        # inventory point entered the stream or was deferred behind a physical
        # obligation. Resolve the immutable committed result under this same
        # operation ID, including on a session-local retry.
        player, operation = message["player"], message["operation_id"]
        recorded = self.journal.event(player, operation, self._semantic(message))
        if recorded is None:
            raise JournalError("acknowledged observation lacks its committed result")
        outcome = recorded.result
        has_inventory = message.get("inventory") is not None
        deferred = outcome.get("inventory_deferred") is True
        settled = "inventory_transition_digest" in outcome
        if has_inventory and deferred == settled or not has_inventory and (deferred or settled):
            raise JournalError("observation inventory settlement is inconsistent")
        response["observation_result"] = {
            "schema": "rby-observation-result-v1", "operation_id": operation,
            "sequence": message["sequence"], "frame": message["frame"],
            "inventory_status": "deferred" if deferred else "recorded" if settled else "absent",
        }
        # SessionGate caches the response before this generation-owned field is
        # attached. Keep exact retries byte-for-byte identical.
        self.gate.sessions[player].last_response = copy.deepcopy(response)
        return response

    def _service_release_ready(self, stage):
        """Cold free-run starts only after both owned enrollment saves settled."""
        if not self.free_service:
            return True
        components = stage.document()["components"]
        initial = components.get("gen1-initial-observations", {})
        bootstrap = components.get("gen1-new-game-bootstrap", {})
        saves = components.get("gen1-initial-save", {})
        return (set(initial) == {"a", "b"}
                and set(bootstrap) == {"a", "b"}
                and set(saves) == {"a", "b"}
                and all(isinstance(saves[player], dict)
                        and saves[player].get("receipt_operation") is not None
                        for player in ("a", "b")))

    def _service_release_reason(self, stage):
        return "waiting for both initial observations, new-game bootstraps, and initial-save receipts"

    def _verify_service_continuity(self, player, evidence, stage, binding):
        from server.gen1_service_continuity import verify

        return verify(self, player, evidence, stage, binding)

    def _service_continuity_enabled(self):
        # The native-selected free service is still the free service: continuity is offered, and
        # gen1_service_continuity refuses it unless the player's held reattach read was released
        # and nothing native is owed (terminal-only).
        return self.free_service

    def _presentation_state(self):
        # The journal checks the committed snapshot hash. Displaying that state
        # does not require replaying physical save/ROM proofs after every poll.
        # Authority paths still use state(), including its full record audit.
        from types import SimpleNamespace

        from server.gen1_staged_state import StagedGen1State
        from server.paired_recovery import RecoveryBarrier
        snapshot = self.journal.snapshot()
        return SimpleNamespace(
            rules=StagedGen1State.restore(snapshot.state['rules'], data_dir=self.data_dir),
            barrier=RecoveryBarrier.restore(snapshot.state['components']['gen1-runtime']['recovery']),
            document=lambda: copy.deepcopy(snapshot.state),
        )

    def state(self):
        if getattr(self, '_control_cache_active', False):
            snapshot = self.journal.snapshot()
            from server.protocol import digest
            stamp = (snapshot.revision, digest(snapshot.state))
            cached = getattr(self, '_control_state_cache', None)
            if cached is not None and cached[0] == stamp:
                return copy.deepcopy(cached[1])
        stage = super().state()
        stage._begin_validation_document()
        try:
            self._verify_state_journal(stage)
        except BaseException:
            stage._cancel_validation_document()
            raise
        stage._end_validation_document()
        if getattr(self, '_control_cache_active', False):
            self._control_state_cache = (stamp, copy.deepcopy(stage))
        return stage

    def _verify_state_journal(self, stage):
        verify_journal(self.journal, stage.document())
        from server.gen1_receptionist_runtime import verify_state
        verify_state(self.journal,stage)
        from server.gen1_inventory_observation import verify_journal as verify_inventory
        verify_inventory(self.journal,stage)
        from server.gen1_observation_runtime import verify_journal as verify_observations
        verify_observations(self.journal,stage)
        from server.gen1_bootstrap_runtime import verify_journal as verify_bootstrap
        verify_bootstrap(self.journal,stage)
        from server.gen1_initial_save_runtime import verify_journal as verify_initial_save
        verify_initial_save(self.journal,stage)
        from server.gen1_native_frame_accounting import verify_journal as verify_native_frames
        verify_native_frames(self, stage.document())
        from server.gen1_engine_signal_runtime import verify_journal as verify_signals
        verify_signals(self.journal,stage)
        from server.gen1_starter_settlement import verify_journal as verify_starters
        verify_starters(self.journal,stage)
        from server.gen1_faint_runtime import verify_journal as verify_faints
        verify_faints(self.journal,stage)
        from server.gen1_memorial_runtime import verify_journal as verify_memorials
        verify_memorials(self.journal,stage,self._memorial_verified)
        from server.gen1_acquisition_runtime import verify_journal as verify_acquisitions
        verify_acquisitions(self.journal, stage, rom_provider=(
            self.prepared_cartridges.rom if self.prepared_cartridges is not None else None))
        from server.gen1_native_observation import verify_journal as verify_native_observations
        verify_native_observations(self.journal, stage)
        from server.gen1_native_windows import verify_journal as verify_native_windows
        verify_native_windows(self.journal, stage)
        from server.gen1_native_preparation import verify_journal as verify_native_preparation
        verify_native_preparation(self.journal, stage)
        from server.gen1_native_reattach_runtime import verify_journal as verify_native_reattach
        verify_native_reattach(self.journal, stage)
        from server.gen1_static_lifecycle import verify_journal as verify_statics
        verify_statics(self.journal, stage, rom_provider=(
            self.prepared_cartridges.rom if self.prepared_cartridges is not None else None))
        from server.gen1_npc_exchange_runtime import verify_journal as verify_exchanges
        verify_exchanges(self.journal, stage)
        from server.gen1_wild_encounter_runtime import verify_journal as verify_encounters
        verify_encounters(self.journal, stage)
        from server.gen1_storage_runtime import verify_journal as verify_storage
        verify_storage(self.journal, stage)
        from server.gen1_evolution_runtime import verify_journal as verify_evolutions
        verify_evolutions(self.journal, stage, rom_provider=(
            self.prepared_cartridges.rom if self.prepared_cartridges is not None else None))

    def _interrupt_trades(self, reason):
        if self.trade is None:
            return
        for identifier, entry in transactions(self.state().document()).items():
            if entry["phase"] not in TERMINAL:
                self.trade.control("interrupt", identifier, secrets.token_hex(16),
                    authority=self._suspension_authority, details={"reason": str(reason)[:256]})

    def _before_suspend(self, reason):
        # The shared lifecycle already sent its hold notice and guarantees
        # owner invalidation even if this atomic journal transition fails.
        self._interrupt_trades(reason)

    def _dispatch_semantic(self, player, message, owner):
        event = message["event"]
        if event in ('acquisition_observation', 'npc_exchange_observation', 'wild_encounter_observation', 'evolution_observation'):
            raise ProtocolError('acquisition receipts require an accounted frame completion')
        if event == 'observation':
            if not self.free_service:
                raise ProtocolError('free-run observation is not selected')
            from server.gen1_observation_runtime import record
            return record(self, player, message['operation_id'], self._semantic(message))
        if event == 'native_reattach':
            # The native client's start-of-script held read (B3): recorded with the server's own verdict;
            # it never mutates a trade, window or command (gen1_native_reattach_runtime).
            if not (self.free_service and self.native_trade):
                raise ProtocolError('native reattach evidence requires the native-selected free service')
            from server.gen1_native_reattach_runtime import record
            return record(self, player, message['operation_id'], self._semantic(message))
        if event == 'native_frame_return':
            if not self.native_trade:
                raise ProtocolError('native frame accounting is not selected')
            from server.gen1_native_frame_accounting import returned
            return returned(self, player, message['operation_id'], self._semantic(message))
        if event == 'native_frame_handoff':
            if not self.native_trade:
                raise ProtocolError('native frame accounting is not selected')
            from server.gen1_native_frame_accounting import handoff
            return handoff(self, player, message['operation_id'], self._semantic(message))
        if event=='engine_signals':
            if not self.initial_observations:raise ProtocolError('engine signal observation is not selected')
            from server.gen1_engine_signal_runtime import record
            return record(self,player,message['operation_id'],self._semantic(message))
        if event=='inventory_observation':
            if not self.initial_observations:raise ProtocolError('inventory observation enrollment is not selected')
            from server.gen1_inventory_observation import record
            return record(self,player,message['operation_id'],self._semantic(message))
        if event=='bootstrap_observation':
            if not self.initial_observations:
                raise ProtocolError('new-game bootstrap enrollment is not selected')
            from server.gen1_bootstrap_runtime import record
            return record(self,player,message['operation_id'],self._semantic(message))
        if event=='initial_observation':
            if not self.initial_observations:raise ProtocolError('initial observation enrollment is not selected')
            from server.gen1_initial_observation import record
            return record(self,player,message['operation_id'],self._semantic(message))
        if event=='receptionist_entered':
            if self.receptionist is None:raise ProtocolError('native receptionist is not selected')
            return self.receptionist.start(player,message['operation_id'],self._semantic(message))
        if event in TRADE_EVENTS:
            if self.trade is None:
                raise ProtocolError("RBY native trade policy is not configured")
            result = self.trade.handle(
                player, message["operation_id"], self._semantic(message), owner=owner
            )
            if self.trade_driver is not None:
                self.trade_driver.step()
            return result
        if event.startswith("trade_") or event.startswith("native_trade_"):
            raise ProtocolError("RBY trade control is private to the runtime")
        if event == "command_ack":
            command = self.journal.command(player, message.get("command_id"))
            if command["body"].get("cmd") in ("hud_notice", "hud_state"):
                semantic = self._semantic(message)
                # The shared dispatcher verifies the exact no-write receipt, but
                # deliberately does not impose FIFO on other generations. Gen 1's
                # physical-before-HUD journal ordering is a release invariant.
                # An already committed operation or identical completed receipt
                # remains replayable after the command leaves the pending index.
                if self.journal.event(player, message["operation_id"], semantic) is None:
                    if command["outcome"] is None:
                        pending = self.journal.pending_ids(player)
                        if not pending or pending[0] != message["command_id"]:
                            raise JournalError("Gen 1 HUD ACK must own the oldest pending command")
                    elif (command["outcome"] != "ACK" or semantic.get("outcome") != "ACK"
                          or command["receipt"] != semantic.get("receipt")):
                        raise JournalError("Gen 1 HUD replay differs from the completed receipt")
            if command['body'].get('cmd') in ('retirement_observe','acquisition_retire'):
                from server.gen1_retirement_runtime import acknowledge
                return acknowledge(self, player, message['operation_id'], self._semantic(message))
            if command['body'].get('cmd') in ('storage_observe','storage_apply'):
                from server.gen1_storage_runtime import acknowledge
                return acknowledge(self, player, message['operation_id'], self._semantic(message))
            if command['body'].get('cmd')=='initial_save':
                from server.gen1_initial_save_runtime import acknowledge
                return acknowledge(self,player,message['operation_id'],self._semantic(message))
            if 'death_id' in command['body']:
                if command['body'].get('cmd') in ('memorial_observe','memorialize'):
                    from server.gen1_memorial_runtime import acknowledge
                    return acknowledge(self,player,message['operation_id'],self._semantic(message))
                from server.gen1_faint_runtime import acknowledge
                return acknowledge(self,player,message['operation_id'],self._semantic(message))
            if command['body'].get('cmd')=='native_receptionist':
                if self.receptionist is None:raise ProtocolError('native receptionist is not selected')
                return self.receptionist.acknowledge(player,message['operation_id'],self._semantic(message))
            if command["body"].get("cmd") in COMMANDS:
                raise ProtocolError("native trade commands require typed coordinator receipts")
        return super()._dispatch_semantic(player, message, owner)

    def delivery_commands(self, player):
        commands = super().delivery_commands(player)
        for command in commands:
            if command["cmd"] in COMMANDS:
                if self.trade is None:
                    raise ProtocolError("RBY native trade policy is not configured")
                session = self.gate.sessions.get(player)
                self.trade.authorize_delivery(
                    player, command["command_id"], owner=session.owner if session else None
                )
        return commands

    def _control(self,player,message):
        # This serialized control turn has one checked view per committed state.
        # Return detached stages; a commit or changed snapshot invalidates it.
        # Semantic events and subsequent control turns always re-audit records.
        self._control_cache_active = True
        self._control_state_cache = None
        try:
            response = self._control_checked(player, message)
            # A scheduling hint only: CONTROL still delivers no commands. Query
            # after all Gen1 control/native side effects in this serialized turn,
            # so a newly committed obligation cannot be hidden by an older view.
            response["pending_delivery"] = bool(self.journal.pending_ids(player))
            return response
        finally:
            self._control_cache_active = False
            self._control_state_cache = None

    def _control_checked(self,player,message):
        response=super()._control(player,message)
        if self.trade_driver is not None and self.trade_driver.step() is not None:
            stage=self.state()
            response["recovery"]=stage.barrier.document()
            response["control"]={**self.gate.sessions[player].metadata["control_binding"],
                "challenge":message["control"]["challenge"],"authority":"hold",
                "reason":stage.barrier.status()["reason"]}
        request=message.get("operation_execution")
        if request is not None:
            if isinstance(request,dict) and isinstance(request.get('window'),dict) and request['window'].get('schema') == 'rby-native-handoff-query-v1':
                if not self.native_trade:
                    raise ProtocolError('native frame accounting is not selected')
                from server.gen1_native_frame_accounting import handoff_status
                response['operation_execution'] = handoff_status(self, player, request)
            else:
                from server.gen1_execution_authority import issue_for_control
                response["operation_execution"]=issue_for_control(self,player,request,self.verify_operation_execution)
                if response['operation_execution'] is not None and request['evidence'].get('schema') == 'rby-native-window-evidence-v1':
                    from server.gen1_native_frame_accounting import persist_grant
                    persist_grant(self, player, request['window'], response['operation_execution'], request['evidence'])
        return response

    def trade_control(self, action, transaction_id, operation_id, *, authority, details=None):
        """Owned server controller only; never accepted as a network event.

        The caller must serialize with the runtime socket lock. The generation
        policy still validates current native/hold/save evidence for each phase.
        """
        if self.trade is None or self._failed:
            raise JournalError("RBY trade controller is unavailable")
        now = self._now()
        if action != "interrupt" and (
            set(self.gate.sessions) != {"a", "b"}
            or set(self._control_seen) != {"a", "b"}
            or any(now - seen >= TIMEOUT for seen in self._control_seen.values())
        ):
            raise JournalError("fresh paired connections required for trade control")
        try:
            return self.trade.control(
                action, transaction_id, operation_id, authority=authority, details=details
            )
        except (OSError, sqlite3.DatabaseError):
            self._failed = "RBY trade persistence failed; reopen and reconcile"
            self._revoke_service(self._failed)
            self._notify_holds(self._failed)
            self.gate.sessions.clear()
            self._control_seen.clear()
            self._control_challenges.clear()
            raise
