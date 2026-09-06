# Shared paired recovery and execution control

This additive layer is owned jointly through the RR/Gen1 handoff. It does not
activate the production dispatcher or provide a cartridge/host safety certificate.
Existing generation bindings keep their current behavior until deliberately
selected. `tests/unit/test_paired_recovery.py` and `test_control_service.py` exercise
the actual Python/Lua policies; mocked execution holds are not live pause proof.

## Durable reconciliation

`server.paired_recovery.RecoveryBarrier` is a detached staging object. Compose its
`document()` beside the staged rule document and serializable native transactions
inside the same `ProtocolJournal.commit` as the semantic event and both outboxes.
Do not persist it through an independent side file or publish it before that commit.

- Bind each player to a verified build/save/mode digest and a distinct context
  generation. A party slot, PID/OT, native mailbox sequence or transport sequence
  cannot substitute for either identifier. The binding includes the player and
  independently validated physical instance. Identical bindings for both halves
  are refused, and every trusted reconciliation proof explicitly names its player.
- Hash the semantic rules and native transactions as `history_digest`, excluding
  recovery proofs and transient telemetry. During an already-required recovery,
  changes to that history or outstanding obligations invalidate both proofs.
  Normal gameplay events are not required to create a new network pause each frame;
  the coordinator selects a stable reconciliation checkpoint when entering recovery.
- `invalidate(reason)` changes the recovery epoch and clears both proofs. Invoke it
  for connection loss, rejected admission, restart, rollback/load/reset evidence,
  uncertain effects and any change relevant to an in-progress reconciliation.
- `set_blockers({durable_id: reason})` records unresolved obligations. Neither adding
  nor clearing an obligation grants ordinary execution. Clearing the last blocker
  still requires new physical evidence from both players.
- A cartridge validator constructs the immutable `VerifiedReconciliation` result
  only after persisted observation replay, correct game ownership, native receipt
  validation and forward reconciliation. Passing an arbitrary JSON object is refused.
  A checkpoint digest identifies evidence; it does not assert battery-save persistence.
- `ticket()` returns a detached description only when both proofs match the current
  epoch, bindings and history and no blockers remain. It is not an authentication
  token, liveness signal or authorization for bounded native recovery frames.

Admission HELLO is metadata-only for the new runtime. Do not pass a raw midbattle
party snapshot into legacy HELLO rules. Replay the durable semantic outbox first;
then invoke an explicit cartridge-validated reconciliation transition. Transport
readmission cannot manufacture acquisition/death evidence or rewind durable history.

## Fresh authority and independent clocks

`server.paired_liveness.PairedLiveness` has no persistence. A restarted server starts
with no liveness even if a restored recovery document contains completed proofs.
The coordinator checks private connection ownership through `SessionGate` before
opening or answering a liveness session. Each challenge belongs to that admitted
session, may be answered once, and expires from issue time. Buffered replies cannot
extend their deadline. The default timeout is two wall-clock seconds.

Once an established lease expires it stays expired, even if a newer challenge was
already in flight. That player requires a newly admitted session, and the coordinator
must invalidate paired recovery before issuing a new ordinary-execution authority.
Explicit disconnect closes the current owner's liveness immediately. An obsolete
connection cannot close or renew a replacement. Clock reversal/failure revokes all
liveness. Only `barrier.ticket() != None AND liveness.status().paired_live`, current
admission, and committed coordinator state can support a run response.

`lua.control_service` supplies the corresponding local authority policy. The caller
provides a monotonic clock and independent `host.set_held(boolean, reason)` actuator.
`platform_clock` uses the .NET `Stopwatch`, independent of emulator frame speed.
The actuator must return exactly `true` after verifying the requested hold state,
or throw/refuse; false/nil cannot be mistaken for success. A failed hold is reported
as an actuator failure, not a claim that the emulator was physically stopped.

1. Construction establishes an execution hold before exposing the service.
2. `bind` takes the admitted session/epoch, binding digest and context generation.
3. `challenge` creates a session-bound request; only its matching fresh response
   can carry `authority=run` with a recovery epoch and ticket digest. The authenticated
   transport/coordinator validates the actual ticket and paired evidence separately.
4. `step(read_only_service)` runs networking/persistence/reconciliation while held,
   then releases only the independent host hold when authority remains valid.
5. `revoke(reason)` holds immediately and forgets the session. Disconnect, admission
   rejection, reset/load or uncertain mutation call it before any further execution.
6. An expired lease requires readmission. A ticket from before a hold cannot lift it;
   a new recovery epoch is required. Clock/service failure latches the hold until
   the service is reopened and authoritative state is reloaded.

All ordinary detection and physical-execution callers must check authority after
servicing and immediately before their effect. Read-only recovery remains available.
`status()` is a presentation snapshot, not a fresh clock/permission check.
The module never grants native recovery frames: those need a separate, bounded
operation-specific procedure with both participants and blocked game input.

## Pinned host integration still requires live proof

BizHawk 2.11.1 resumes `emu.yield` scripts in its outer host loop before choosing a
frame, including while paused. Its `BlockFrameAdvance` property is independent of
the user's pause Boolean and checked against normal/forced frame execution. These
are source findings from [MainForm.cs](https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Client.EmuHawk/MainForm.cs)
and [LuaLibraries.cs](https://github.com/TASEmulators/BizHawk/blob/2.11.1/src/BizHawk.Client.Common/lua/LuaLibraries.cs),
not a validated production adapter.

A host adapter must establish exclusive hold ownership and refuse conflicting tools,
including TAStudio ownership. A plain `client.pause()` in `onframestart` is too late
to cancel a frame the host already selected. Rewind runs before the frame block;
load/reset/debugger/forced-step paths need their own tested interlock. Never clear a
hold belonging to another tool, silently unpause the user's emulator, or treat a
post-frame callback as proof that restored native BUSY instructions were prevented.

UI Phase3 owns normalization into the additive presentation projection. `status()`
accessors expose detached facts; connected, reconciled, effective features, requested
settings, ordinary execution and operation recovery are separate dimensions.
