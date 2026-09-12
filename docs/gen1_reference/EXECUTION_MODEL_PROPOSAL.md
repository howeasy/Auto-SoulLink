# Proposal: run Gen 1 free, hold only to write

Status: proposal for root (`codex:Gen1`) and the project owner, written 2026-09-10 by the Claude
peer while root was unavailable. No code changed. Decision requested in section 8.

## 0. Summary

The RC runtime routes every ordinary gameplay frame through a server-granted credit
(60 frames, 1000 ms, strict stop-and-wait). That single decision is what most of the
remaining Gen 1 cost hangs off: it caps the game at roughly half speed by construction, it
turns every network hiccup into a stalled player, it forced a 64-frame mitigation into the
battle path, and it is still only wired for pre-Pokéball gameplay. Nothing in the Soul Link
rules needs it.

This is a framework decision, not a Gen 1 shortcut. The owner wants a shared runtime that
future generations bind, with Gen 3 the first port. Gen 3 free-runs on mGBA today, and the
bounded host has Gambatte-only qualification, so a framework whose core loop is a
server-granted frame credit is one Gen 3 cannot bind. The core loop has to be the one every
generation can share.

Proposed replacement: **observe free, hold to write.** The cartridge runs at its own rate.
The existing read-only bus-exec observers and the atomic journal keep producing exactly the
receipts they produce today. The exclusive execution hold, the one-use held-write permit and
the qualified overworld checkpoint are kept unchanged and are taken only when SLink has a
write to make. Deleting the credit loop removes about 2,800 lines across ten modules and
about 35 unit test files, and the "vanilla speed" RC item closes by construction.

## 1. Evidence

### 1.1 Measured cost of the credit loop

From `ORDINARY_FRAME_TURNOVER_PROFILE.md` (Yellow/Yellow bedroom, real launcher and server):

| Measurement | Before caches | After caches |
| --- | ---: | ---: |
| End-to-end FPS (player a / b) | 11.46 / 10.97 | 28.99 / 28.24 |
| Mean grant reply delay | 494 / 508 ms | 203 / 231 ms |
| Mean publication-to-ACK delay | 497 / 535 ms | 318 / 279 ms |
| Mean bounded host step (the emulator) | 3.69 ms | 3.89 ms |
| Mean frame-client step (SLink bookkeeping per frame) | 11.35 ms | 11.29 ms |
| Mean full inventory capture at range close | n/a | 27.97 ms |

The cartridge frame period is 16.74 ms. The emulator itself uses under a quarter of it. The
rest is protocol turnover that the model requires.

### 1.2 Why it cannot reach cartridge rate

The loop is strictly stop-and-wait (`lua/gen1_frame_client.lua:183`: no new request while the
outbox is non-empty or a command is pending; `:245`: signals must be persisted before the next
frame is authorized). One range costs:

1. request to grant, about 200 ms (`:230`: the 1000 ms deadline starts at the client challenge,
   so the reply delay is spent from the window itself);
2. up to 60 frames at 16.74 ms, but only about 48 fit in what is left of the second
   (the profile records ranges consuming 21 to 26 of 60 credits in the slow trace);
3. close: inventory capture 28 ms, publication 60 ms, ACK about 300 ms.

That is roughly 48 frames per 1.5 s, a ceiling near 32 FPS, which is what was measured.
Worse, a range closes early on **any** captured engine signal or acquisition receipt
(`:347`). Battles, scripts and menus fire signals constantly, so ranges shrink to a few
frames exactly where gameplay is busiest, and each shrunken range pays the full round trip.
The cold route "reached the end of the rival battle, then stopped on a grant-response
deadline" (`RC_STATUS_AND_ESTIMATE.md`). That is the model failing at its predicted weak point.

The only way to lift the ceiling is to pipeline grants ahead of consumption. A pipelined
grant that is always ahead of the emulator is a free-running emulator with extra steps.

### 1.3 It is not even the production path yet

`server/gen1_frame_control.py:51-54` refuses every grant once either player has obtained
Pokéballs. Ordinary gameplay after the first town has no frame authority at all. The
remaining estimate (25 to 45 hours, "unified frame ownership/policy") is largely the cost of
extending this model to the whole game.

### 1.4 The mitigation tell

`server/instruction_authority.py` grew a 64-frame window (`MAX_WINDOW_FRAMES`) so the
in-battle faint would not need one network round trip per emulated frame. A core loop that
needs a mitigation for its own round trip is the wrong core loop.

## 2. What the credits protect, and what protects it without them

| Property | How the credit loop provides it | Without credits |
| --- | --- | --- |
| Every observation names an exact frame | The ledger anchors each range to a frame | Every hook already reads `emu.framecount()` at capture (`lua/gen1_engine_signals.lua:62`); receipts carry their own frames. Unchanged. |
| Observations are not lost | A range is not ACKed until its bundle is journaled | The client journal is already atomic and has an outbox with ACK (`lua/client_journal.lua`); publish per frame batch instead of per range. Same mechanism, different cadence. |
| Nothing is stepped that the server has not accounted for | Grant before step | Never a Soul Link rule. The server refuses grants only for its own bookkeeping reasons (pending observation, pending ids, blockers; `gen1_frame_control.py:44-69`), never for a gameplay reason. Drop. |
| Writes happen only at a verified safe checkpoint | The hold plus `gen1_held_faint.py:verify_checkpoint` (PC at the IRQ vector, stack in the overworld loop, no battle/text/serial owner) | Identical. The checkpoint verifier never reads the frame ledger. Keep. |
| A write is one-use, bound to a command | `held_write_permit` (no frame API by design) | Identical. Keep. |
| Cartridge and context identity | ROM hash and `context_generation` checked at every hook and publication (`gen1_engine_signals.lua:21`) | Identical. Keep. |
| Recovery after reset/load/rewind | `RecoveryBarrier`, control_service hold policy | Identical. Keep; the barrier does not need a ledger to refuse. |
| Two players stay "in step" | Nothing. Each player's ledger is independent. | Nothing needed. Soul Link is event-driven, not frame-locked. |

The credits buy no rule and no safety that the hold, the permit, the journal and the hooks do
not already buy.

## 3. Proposed model

Principles:

1. The emulator free-runs. The Lua main loop is `emu.frameadvance()` as in every other
   generation's client. No pacer, no grant, no per-frame persistence.
2. Bus-exec observers stay exactly as they are. Their pending buffers are drained once per
   frame into a journal batch when non-empty, plus a periodic heartbeat with the inventory
   digest (every 30 frames is plenty). Each batch carries `frame`, a monotonic `sequence`,
   `context_generation` and the ROM hash. The server settles batches in sequence order.
3. Acquisition facts keep their "pending until a stable inventory checkpoint" rule. The
   checkpoint is the next heartbeat inventory at or after the witness return frame, which is
   what the current bundle's `inventory` field is.
4. A command that writes (force_faint, memorialize, initial_save, storage apply, retirement)
   takes the exclusive hold at the next frame boundary, waits at most N frames for the
   qualified overworld checkpoint, runs exactly the current held-permit flow, releases.
   `gen1_held_faint.lua` and its server verifier are unchanged. The only new code is "take
   the hold when a write command is pending", and `control_service` already exposes that.
5. The in-battle faint becomes a short hold: on a pending death while `wIsInBattle` is set,
   take the hold, arm the instruction authority with a bounded window, step frame by frame
   with `step_one` until the pinned site fires or the window ends, release. This is the only
   gameplay use of `step_one`, and it is exactly what the live gate does today. It is a
   release requirement, not an enhancement: the manifest's `faint-whiteout-rebuild` rows
   demand active and benched HP behaviour under a real faint on every title, and
   `BATTLE_FORCE_INTEGRATION.md` §4 shows its two hard blockers are the credit loop itself
   (frames are never issued while a death exists; the client freezes on a pending command).
   Under the free loop neither blocker exists: the hold is taken because a death is pending,
   not granted in spite of it.
6. Native trade keeps its borrowed-owner sequences. It borrows the hold, not a credit.

Loop sketch (client):

```
while true do
  emu.frameadvance()
  local signals = engine:peek(); local rows = observers:prepare(state)
  if #signals > 0 or #rows.receipts > 0 or frame % 30 == 0 then
    journal:append({event="observation", frame=emu.framecount(), sequence=next(), signals=signals,
                    acquisitions=rows.receipts, inventory=(frame % 30 == 0) and inventory() or nil})
    engine:drain(signals); observers:drain(rows)
  end
  if journal:pending_write_command() then held_writer:service() end  -- takes and releases the hold
  session:pump()   -- send outbox, receive ACKs and commands; never blocks the frame
end
```

Latency budget: a faint command is delivered on the next pump after the partner's death
settles, and executes at the next qualified overworld frame, which is the same as today.

## 4. Keep, delete, change

### Keep unchanged

`lua/platform_execution.lua`, `lua/control_service.lua`, `lua/held_write_permit.lua`,
`lua/gen1_held_faint.lua` and the held memorial/initial-save/retirement/storage adapters,
`lua/gen1_engine_signals.lua`, all `gen1_*_observer.lua` and `gen1_acquisition_observers.lua`,
`lua/client_journal.lua`, `lua/client_session.lua`, `lua/durable_runtime.lua`,
`server/protocol_journal.py`, `server/held_write_permit.py`, `server/gen1_held_faint.py`,
`server/gen1_command_receipts.py`, every `gen1_*_receipt.py` and `gen1_*_runtime.py` decoder,
`server/source_receipts.py`, `server/gen1_source_receipts.py`, `server/identity_registry.py`,
`server/gen1_admission.py`, `server/gen1_cartridge_profiles.py`, the native trade runtime,
`server/instruction_authority.py` and `battle_force_authority.py` (as the short-hold tool).

### Delete (about 2,800 lines)

| Module | Lines | Role today |
| --- | ---: | --- |
| `server/frame_progress.py` | 216 | frame ledger |
| `server/execution_window.py` | 42 | grant codec |
| `server/gen1_frame_control.py` | 92 | grant policy (pre-ball only) |
| `server/gen1_frame_journal.py` | 527 | grant/return persistence and settlement |
| `server/gen1_frame_runtime.py` | 238 | boundary validation for ranges |
| `server/gen1_native_frame_accounting.py` | (in total) | credit borrow/hand-back for native |
| `lua/execution_window.lua` | 154 | client-side credits |
| `lua/frame_pacer.lua` | 38 | cartridge-rate pacing of granted frames |
| `lua/gen1_frame_client.lua` | 367 | the credit loop |
| `lua/gen1_native_frame_client.lua` | (in total) | credit hand-back |

Plus the `frame_grant` / `frame_complete` protocol events, the "frames" and "ttl" fields of
the runtime contract, and the docs `shared-execution-window.md`, `shared-frame-progress.md`,
`shared-runtime-latency.md`, `shared-held-runtime-latency.md`. About 35 unit test files under
`tests/unit/` reference these modules directly (`test_frame_progress.py`,
`test_execution_window*.py`, `test_frame_pacer.py`, `test_gen1_frame_*.py`,
`test_gen1_native_frame_*.py`, and the settlement tests that build bundles through them).

### Change

| Piece | Change |
| --- | --- |
| `gen1_observation_provenance.py` and the settlement that consumes `frame_complete` bundles | Consume `observation` batches keyed by sequence instead of ledger ranges. The receipt decoders are untouched. |
| `gen1_frame_journal.enroll/grant` callers in `gen1_runtime.py` | Remove; enrollment stays (initial observation and initial save are already separate components). |
| `lua/gen1_client_entry.lua` `mode="held_service"` | Add a `free_service` mode; the held loop remains available for tests and for the native lane. |
| `docs/shared-subsystem-map.md` "Bounded frame scheduling" row | Retire the row; "Holds and recovery" and "Held writes" rows absorb it. |

## 5. Migration, each phase demoable

| Phase | Work | Gate that proves it |
| --- | --- | --- |
| 0 | Accept this proposal. Freeze further credit-path work (the window API from cx-803bd6f1 is kept as the short-hold tool; no further generalization). | Decision recorded in `RC_STATUS_AND_ESTIMATE.md`. |
| 1 | Free-run observation: a small `gen1_observation_loop.lua` (target under 120 lines) and a server `observation` batch consumer that feeds the existing decoders. | Bedroom Yellow/Yellow through the real launcher at 59.7 FPS, and the acquisition receipts for the starter route byte-identical to the credit-path bundle of the same inputs (`STARTER_SETTLEMENT.md` cases re-run). |
| 2 | Writes on hold from free-run: `control_service` takes the hold when a write command is pending. | The ten held-faint launcher cases and the seven memorial cases from `HELD_FAINT_AUTHORITY.md` and `MEMORIAL_SAVE_PROOF.md` pass unchanged, launched from the free loop. |
| 3 | Delete the credit modules, their tests and docs. Rewrite the subsystem map. | Broad suite green with the deletions; `ruff` and the Lua parse gate green. |
| 4 | Cold route end to end: New Game, starters, rival battle, Pokémon Center, receptionist trade, back to play. | The run that stopped on the deadline completes. |
| 5 | In-battle faint as a short hold using the existing instruction authority (required by the manifest's `faint-whiteout-rebuild` rows; the `BATTLE_FORCE_INTEGRATION.md` diff minus its two credit-loop blockers). | The three fight_first live gates pass from the free loop (they passed under step_one on 2026-09-10 on R/B/Y), and a death delivered while the peer is mid-battle faints the active mon in the original engine. |

Phases 1 and 2 can be built by two workers in parallel. Phase 3 is deletion. Phase 4 is the
RC blocker and is unreachable under the current model without further mitigation work.

## 6. Risks and their checks

| Risk | Check |
| --- | --- |
| A hook fires while the Lua is busy and its signal is lost | BizHawk bus-exec callbacks run synchronously inside emulation; free-run does not drop them. Measured 2026-09: callbacks fire for call, jump and linear addresses in all banks under both `frameadvance` and `step_one`, hook frame offset 0. Buffer bound `MAX_PENDING` 32 is drained every frame. |
| Observation batches arrive out of order or twice after a reconnect | Sequence numbers and the journal outbox already give exactly-once delivery; the server refuses a gap. Same as the current command path. |
| The player loads a savestate, rewinds or resets mid-run | The context checks in every hook and batch (ROM hash, `context_generation`) and the `RecoveryBarrier` already refuse; add `event.onloadstate` as a barrier trigger. Rewind is disabled in the production config today. |
| A write lands on a frame the server never saw | Writes are only under the hold, after the qualified checkpoint, with pre/post-image receipts. The frame ledger never participated in that check. |
| The hold cannot be taken from an unpaused core | `GAMBATTE_EXECUTION_HOLD.md`: 18 actual-host cases including initially unpaused, emergency re-hold and release, with frame count retained. |
| Two players drift apart | They already do; nothing in Soul Link needs frame lockstep. Gen 3 has run this way for the whole project. |
| Losing the "server accounted every frame" narrative in the docs | It was never a rule. Say so once in the subsystem map and move on. |

## 7. Effect on scope and on the framework

The RC row "Ordinary execution: full owner/transport timing and practical vanilla-speed
behavior remain open" closes. "Reconnect/recovery: moving-frame interruption matrix" shrinks
to the command path, which already has its matrix. The estimate stops being dominated by
frame ownership.

For the shared framework the proposal is a subtraction, not a redesign. Of the 37
`docs/shared-*.md` contracts, four retire (`shared-execution-window`, `shared-frame-progress`,
`shared-runtime-latency`, `shared-held-runtime-latency`) and the runtime contract loses its
frame fields. Every other shared mechanism keeps its contract and gains a clearer Gen 3
binding, because the new core loop is the shape Gen 3 already has:

| Shared mechanism | Gen 1 binding today | Gen 3 binding under this proposal |
| --- | --- | --- |
| Execution hold (`platform_execution`, `control_service`) | Gambatte profile, held-service loop | mGBA profile already pinned in `platform_execution.lua`; taken only around writes, so no bounded-host qualification is needed for ordinary play |
| Held-write permit and staged command | force_faint, memorialize, initial_save, storage, retirement at the verified overworld checkpoint | The existing deferred `force_faint` / `box_mon` / `party_mon` / `memorialize` commands, executed under the hold at Gen 3's own safe-state predicate (`isPartyWriteSafe` in `gen3_frlge.lua`) |
| Observation checkpoints and keyed inventory | Party/box snapshots at each published batch | Gen 3's per-frame decrypted party diff, published as the same batch shape |
| Engine signals and source receipts | Bus-exec hooks at pret-pinned sites, `{kind, receipt}` rows | mGBA exec hooks at the FR/LG/RR sites the companion patch already names, same row shape; the generic `source_receipts.decode_rows` needs no change |
| Identity registry, staged rules, linked death, party grants | Gen 1 keys `DVS:OTID:SP` | Gen 3 keys (personality/OT id), same registry |
| Protocol journal and client journal | durable events and commands | Same; the free loop pumps it once per frame |
| Instruction authority | In-battle faint prototype (short hold) | Available for Explode Mode or any future in-battle write; not required for the port |
| Admission and cartridge profiles | Full-hash R/B/Y, UPR pipeline | FR/LG/Emerald/RR hashes, which the ROM-type detection already computes |
| Frame credits, frame ledger, pacer | Ordinary pre-ball frames | None. Gen 3 could not bind these without a qualified mGBA bounded host, which is the strongest reason they do not belong in the framework's core. |

The written Gen 3 binding plan (`SCOPE_CONTROL_PROPOSAL.md`, item 10) is the check on this
table: any row with no credible Gen 3 binding is a boundary to revisit before the port.

Blast radius of the deletion, checked on 2026-09-10: neither `codex/gen2-production` nor
`codex/ui-rework` references `execution_window`, `frame_progress` or `frame_pacer` anywhere
under `server/` or `lua/` (`git grep` on both branches). Gen 2's adoption manifest
(`docs/gen2/shared_adoption.json`) lists 20 shared modules and none of these. The credit
loop is bound by Gen 1 alone.

## 8. Decision requested

1. Adopt "observe free, hold to write" as the Gen 1 execution model. Yes or no.
2. If yes: freeze credit-path work now, and start phases 1 and 2 in parallel.
3. Disposition of the in-flight window API from cx-803bd6f1: keep as the short-hold tool for
   the optional phase 5, do not generalize further.
