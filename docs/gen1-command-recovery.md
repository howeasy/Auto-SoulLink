# Gen 1 prepared command recovery

This implementation is a component of the planned durable RBY binding. The
production client and `_gen1_wire_response` still select wire v1 and volatile
dispatch. The component does not enable a new write context or patch capability.

`lua/command_executor.lua` and `lua/client_journal.lua` own reusable preparation,
replay and receipt publication. `lua/gen1_force_faint_executor.lua` supplies RBY
policy; `lua/gen1_command_receipts.lua` captures and predicts the physical data.
`server/gen1_command_receipts.py` independently checks the result. Its
`Gen1ReceiptPolicy` callback selects the receiver's admitted variant and persisted
save identity when called by `DurableDispatcher`.

The versioned force-faint intent stores the complete before and expected after
party: every 66-byte record, count, exact species/$FF list, save identity, battle
flag, active slot and active battle HP. Only the target party HP may change;
active battle HP must also become zero when the target is the active battler.
All other recorded bytes and context must agree. The executor rechecks live
admission/checkpoint policy immediately before applying the write.

Preparation is immutable and persists before the effect. On recovery, an exact
poststate completes without another write. An exact prestate can finish the
prepared effect only when the binding still permits that write context. Any
other state, exception or storage failure retains the command and emits a
retryable NACK diagnostic. An ambiguous diagnostic is never a terminal receipt.
The server confirms an ACK only after its own receipt validation; journal state,
receipt and event/outbox changes commit together. The original rule already
marked the pair dead, so the receipt does not emit another faint event.

Current evidence:

- Controlled-memory tests cover all party counts, targets and active slots on
  Red, Blue and Yellow, plus malformed/changed records, identity and context drift,
  missing battle HP writes and exceptions around actual Lua memory writes.
- All nine ordered title pairs compose real rules, SQLite, the Lua journal and
  executor across simulated client/server restarts. Invalid readback and injected
  SQL failure leave the command pending; an exact replay does not repeat effects.
- A live gate on each clean title uses a cartridge-produced party record and the
  verified overworld checkpoint, a real flushed local file store, and injected
  exceptions immediately before/after the HP write. Reopen/recovery performs two
  HP-byte writes total and changes no unrelated byte in the full WRAM range.
  Python validates the current run's receipt independently.

The live gate's old town fixture has inconsistent level/experience data. It
explicitly supplies boxed experience 1000 and runs cartridge `_MoveMon` and
`_RemovePokemon` to obtain a valid party record, then restores the original core
checkpoint and installs that exact record. The shared test-only SM83 oracle
never supplies execution-safety evidence from its injected scratch program.

Remaining binding work includes all other command policies, actual two-player
transport recovery, ordered replay before reconciliation, gameplay suspension,
save-state/reset detection, authoritative journal bootstrap and presentation
after commit. Force-faint's live receipt proof currently covers overworld RAM;
it does not establish a battle checkpoint, battery-save persistence, process-kill
recovery, native trading or complete Yellow/Yellow release coverage. Unsupported
receipt kinds and terminal NACKs are refused until their physical and recovery
rules are implemented.

SLink trading must invoke the cartridge's original trade animation/sequence on
both endpoints for every supported pairing, including Yellow/Yellow. Native
animation entry, progression and completion must be demonstrated in the live
trade gates alongside verified physical delivery and save persistence. The
force-faint machinery here does not implement that scene.

The separate `test_gen1_original_trade_animation` live gate now invokes the
unaltered `InternalClockTradeAnim` on each clean title. It derives all16 expected
phases from the pinned source and verifies every top-level phase in order,
including both transfer directions and cleanup, across more than2400 real
frames. Outgoing, cable and incoming snapshots have distinct VRAM and were
visually checked. The oracle explicitly loads the canonical font first, matching
native cable-club setup, and verifies its expanded pixels; an overworld caller
otherwise displays trade text with map graphics. The isolated scene leaves party
data unchanged and restores options. This is original-animation evidence only;
receptionist reachability, two-player physical trades and saving remain open.
