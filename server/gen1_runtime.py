"""Configured RBY binding of the shared durable server service."""

import copy
import secrets
import sqlite3
from pathlib import Path

from server.durable_runtime import TIMEOUT, DurableRuntime
from server.gen1_runtime_admission import HOLD_EVENT, PROTOCOL, new_session_gate
from server.gen1_runtime_state import Gen1RuntimeState,state_type_for
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
        ordinary_frames=False,
        native_trade=False,
        **options,
    ):
        self.trade = None
        self.trade_driver = None
        self.receptionist = None
        self._memorial_verified=set()
        if type(initial_observations) is not bool:raise JournalError('explicit initial-observation selection required')
        self.initial_observations=initial_observations
        if type(ordinary_frames) is not bool or ordinary_frames and not initial_observations:
            raise JournalError('ordinary frame selection requires initial observations')
        self.ordinary_frames=ordinary_frames
        if type(native_trade) is not bool or native_trade and (
                not ordinary_frames or prepared_cartridges is None or trade_policy is not None):
            raise JournalError('composed native trade requires ordinary frames and the reproduced cartridge pair')
        self.native_trade = native_trade
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
                        state_type=self._stage_type,
                    ),
                )
                if native_trade:
                    from server.gen1_native_binding import install_native_driver, install_native_execution
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
        verify_journal(self.journal, stage.document())
        from server.gen1_receptionist_runtime import verify_state
        verify_state(self.journal,stage)
        from server.gen1_inventory_observation import verify_journal as verify_inventory
        verify_inventory(self.journal,stage)
        from server.gen1_bootstrap_runtime import verify_journal as verify_bootstrap
        verify_bootstrap(self.journal,stage)
        from server.gen1_initial_save_runtime import verify_journal as verify_initial_save
        verify_initial_save(self.journal,stage)
        from server.gen1_frame_journal import verify_journal as verify_frames
        verify_frames(self, stage.document())
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
        if getattr(self, '_control_cache_active', False):
            self._control_state_cache = (stamp, copy.deepcopy(stage))
        return stage

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
        if event == 'native_frame_return':
            if not self.ordinary_frames:
                raise ProtocolError('native frame accounting is not selected')
            from server.gen1_native_frame_accounting import returned
            return returned(self, player, message['operation_id'], self._semantic(message))
        if event == 'native_frame_handoff':
            if not self.ordinary_frames:
                raise ProtocolError('native frame accounting is not selected')
            from server.gen1_native_frame_accounting import handoff
            return handoff(self, player, message['operation_id'], self._semantic(message))
        if event == 'frame_complete':
            if not self.ordinary_frames:
                raise ProtocolError('ordinary frame integration is not selected')
            from server.gen1_frame_journal import returned
            return returned(self, player, message['operation_id'], self._semantic(message), settle_observations=True)
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
            return self._control_checked(player, message)
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
                if not self.ordinary_frames:
                    raise ProtocolError('native frame accounting is not selected')
                from server.gen1_native_frame_accounting import handoff_status
                response['operation_execution'] = handoff_status(self, player, request)
            elif isinstance(request,dict) and isinstance(request.get('window'),dict) and isinstance(request['window'].get('scope'),dict) and request['window']['scope'].get('phase')=='ordinary':
                if not self.ordinary_frames:
                    raise ProtocolError('ordinary frame integration is not selected')
                from server.gen1_frame_control import issue_for_control
                response['operation_execution']=issue_for_control(self,player,request)
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
            self._notify_holds(self._failed)
            self.gate.sessions.clear()
            self._control_seen.clear()
            self._control_challenges.clear()
            raise
