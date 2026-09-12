# Shared durable server composition

server/durable_runtime.py composes SessionGate, ProtocolJournal,
DurableDispatcher, the generation's staged aggregate and its RecoveryBarrier.
It was extracted from the published RR runtime at120c80d. It contains no
cartridge addresses, ROM admission catalog, rule bootstrap policy, native
executor or frame actuator.

## Constructor

    DurableRuntime(path, contract=contract, data_dir=data_dir,
        protocol=protocol, hold_event=hold_event,
        stage_type=GenerationRuntimeState, new_session_gate=gate_factory,
        validate_event=event_policy, validate_receipt=receipt_policy,
        verify_reconciliation=reconciliation_policy,
        initial_state=None, run_id=None, clock=time.monotonic)

Protocol and hold-event names are explicit bounded identifiers. The gate factory
receives nonce_registry=journal.register_session and must return the matching
durable-ID SessionGate. The journal binds a complete contract digest and run ID.
An optional initial_state is an explicit authoritative bootstrap input; a
received HELLO never supplies it. Opening without a valid snapshot fails rather
than importing links.json. Reopening invalidates paired reconciliation.

## Generation stage

stage_type.restore(document, data_dir=...) returns a detached stage with rules,
identities, component and barrier properties, plus admit, handle_event,
take_commands and document methods. The component contains the exact contract,
per-player admissions and recovery data. Admissions retain metadata and binding;
normalized metadata must contain save_identity. The shared runtime verifies the
stage's contract representation and identity run ID against the journal.

The generation stage owns HELLO gameplay semantics. Gen1's implementation
accepts metadata only and never calls the legacy party-adopting rule HELLO.
The core itself always returns an empty HELLO command array. Durable commands
are fetched through journaled sync/semantic responses.

Event/receipt callbacks receive detached staged rules and must validate their
generation's evidence before allowing a transition. They must not write the
game or persist external state. verify_reconciliation receives a detached full
stage, evidence and control binding and must return VerifiedReconciliation or
None. It must inspect replay, physical obligations, context/rollback and host
qualification; raw success flags are not trusted proof.

## Wire, ownership and storage

handle_client(reader, writer, first_frame=None, on_change=None) owns a private
connection object. It fixes the player at HELLO, refuses another live owner and
serializes mutations under an asyncio lock. A failed secondary connection cannot
revoke the owning connection. Idle reads time out after two seconds even if no
further request arrives. Disconnect, expiry or clock/persistence failure revokes
both sessions; notices carry the configured hold_event and grant no authority.
Unexpected callback exceptions receive a NACK and close through the same owner
revocation path. Presentation callbacks run after commit; their failure cannot
replay a semantic transition.

process(message, owner) is the synchronous internal request method. Non-socket
callers must provide equivalent ownership, serialization and error/disconnect
handling. It is not a public endpoint and an owner is never decoded from JSON.

Session-local retries and durable semantic replay are separate. Reconnection
uses a fresh nonce/session/sequence while replaying the same semantic operation
ID. The journal commits rules, both outboxes and validated receipts atomically.
The complete stored command body is nested as {cmd, body} beneath its delivery
envelope, command_id and command_sequence. No body player/seq/protocol/operation_id
field is lost. Client generation adapters validate outer cmd==body.cmd and unwrap
once before their cartridge executor. This matches the frozen client pump.

Control uses the same session sequence but a fresh challenge operation ID and
does not retire semantic outbox events. Only callback-verified paired recovery
plus current request liveness can produce a run-authority packet. The independent
client watchdog/hold owner remains mandatory. The server cannot preempt a blocked
Lua callback, stop a disconnected emulator or qualify native recovery frames.

close requires connection owners to be closed before closing their journal.
status and rule_state return detached facts; they grant no execution permission.
Physical trade integration must keep the recovery component consistent with
coordinator transitions atomically; the shared service does not attach a trade
policy or invent that phase-specific behavior.

## Qualification

Gen1 tests exercise the core through the configured SLinkServer TCP route and
actual Lua/shared client pump:38 focused cases cover all nine cartridge contracts
in both HELLO orders, metadata-only admission, unchanged party/rule snapshots,
owner isolation, durable replay, exact body preservation, typed receipt/confirmation,
control refusal, idle expiry, callback failures and read-only journal facts.

Two actual-host cases passed on Yellow/Yellow and Red/Blue: separate Gambatte
processes and SaveRAM paths, actual LuaSocket/TCP, flushed local journals, constant
frame counts and unchanged WRAM under independently verified execution holds.
The faint input is a deliberate transport-test stimulus; physical execution and
production launcher/recovery qualification are not claimed. Gen1 remains the
qualified caller for these results; RR or another generation must verify its
own wrapper, admission, stage and cartridge policies before selecting it.
