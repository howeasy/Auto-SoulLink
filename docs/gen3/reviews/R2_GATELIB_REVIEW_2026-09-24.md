# R2 review: RR opcode gates on gen3_gatelib (C5-4, C5-4b, C5-4c)

Reviewer: R2 (independent, did not author). Date: 2026-09-24. Branch `claude/gen3-migration-planning-5d8e45` @ 21dfa6e7.
Scope: 2aad8e2a, 6daea62d, 2f26742d, 21dfa6e7. `lua/tests/gen3_gatelib.lua`, `lua/tests/test_live_*.lua` / `test_mailbox_*.lua`,
`lua/tests/archive/gen3_old_client/`, `tests/live/test_lua_gates.py`, `tests/unit/test_gen3_gatelib.py`.
Truth: `patch/src/handlers.c` (C5-FMS-FIX), `lua/gen3/native.lua`, `lua/gen3/safety.lua` / `writes.lua`, `data/games/gen3_rr/*`.

Emulator not run (per the brief). `pytest tests/unit -q -k "gate or native or gen3_entry"` gave 372 passed and 7 skipped.
Note: the worktree has another session's uncommitted edits to `lua/gen3/safety.lua` / `writes.lua` (battle reasons).
None of them touches the `native` clause set, so they do not affect this review.

**Verdict: ACCEPT-WITH-FIXES.** HIGH 0 / MEDIUM 3 / LOW 9. No port weakened a decisive oracle, and the raw poster matches native.lua's ABI.
The fixes needed are test coverage for the stale-ack path, the ghost "spawned" oracle, and treating skips as green.

## What holds (verified)

- **Raw poster ABI = native.lua.** `gen3_gatelib.lua:274-307` against `native.lua:113-171`:
  - the order is the same: stages, then args, then `ack = seq-1`, then `seq`, then the opcode LAST;
  - the allow window is the same: `BASE+6 .. BASE+48` plus each stage.
  - The seq source differs, and the difference is benign. Raw uses `MB.seq + 1`; native.lua keeps its own counter. The patch only echoes `MB->seq` (`handlers.c:596-602, 629, 651`).
- **The busy check is not bypassed.** `writes:arm("native", allow)` runs `safety.lua` `native()` (`:312-336`), which checks that:
  - the kind is companion, the SIG and ABI match, `opcode == 0`, `status ~= BUSY`, and the panel handshake is equal;
  - `writes.lua:36-41` re-runs these checks before every write.
  - The raw `assert(opcode == 0)` (`gatelib:287`) is redundant, which is why removing it survives mutation (an equivalent mutant).
- **No race with native.lua or with itself.**
  - `t.raw` asserts `t.native == nil` and `t.raw_job == nil` (`:324-325`).
  - `t.boot` clears both (`:238`).
  - `t.step` services exactly one of the two (`:88-97`).
- **No production reach.**
  - No file under `lua/gen3`, `lua/core` or `lua/*.lua` loads the gatelib; the only matches are in comments.
  - `tools/make_release.py:59-130` is an explicit allowlist with no `lua/tests`.
  - `native.lua` is unchanged across the four commits.
- **Oracles kept.** Old and new check lists match gate by gate (boxsync, createmon, enemyparty, givemon, memorialize, events, partyevents, infoscreen, menu, choices, choosepartymon, pcnpc, tradescene, setpartymon, playse, enemyparty_route, ping, battle, absent). Every port adds a posted receipt and/or an ack receipt.
- **The FMS gates are stronger than before.**
  - `test_live_forcemove.lua` adds the ST_OK ack, the hand-back check (`RUN_COMMAND` at ack), the 0-PP refusal with reason 11 and the menu left parked, and no exec-flag clearing. This matches `handlers.c:615-661`.
  - `test_live_explode_route.lua` adds the ST_OK ack.
  - Both are stale-seq safe: the ack is pre-written as seq-1, and ST_OK for FORCE_MOVE_SLOT comes only from `slink_force_controller`.
- **Archive and manifest.**
  - `gate_files()` lists `lua/tests/` only, and the unit test pins it.
  - Each deferred gate skips with its reason unless `SLINK_GATES_DEFERRED=1`. GAP is empty.
  - The file count is 43: 26 PORTED + 11 DEFERRED + 6 archived (42 original files plus the split `choices_guards`).

## Findings

### MEDIUM

1. **The raw poster's stale-ack and receipt logic is untested.** Location: `tests/unit/test_gen3_gatelib.py:73-106` (FAKE_PATCH acks in the same frame).
   - Three mutations in a scratch copy all left 134/134 green:
     - (a) pre-write `ack = seq` (`gen3_gatelib.lua:292`);
     - (b) drop `ack == job.seq` (`:313`);
     - (c) accept any status, including ST_BUSY, as a receipt (`:313`).
   - Failure scenario for (c): FORCE_MOVE_SLOT arms with `status = ST_BUSY` (`handlers.c:2142`). The raw job then gets `why = nil` on the arm frame.
     - explode_route's "driver acked ST_OK" would then pass without the driver firing.
     - Its only other decisive check (PP drop) is satisfied by any slot-0 pick, and slot 0 is the default cursor.
   - Fix: add a unit fake that behaves like FMS. It should:
     - set BUSY, clear the opcode and ack N frames later;
     - start from a stale `ack == next seq, status = OK` pre-state.
   - The test then asserts that no receipt arrives before the real ack.
2. **The ghost "spawned" oracle can pass without a spawn.** Location: `test_live_ghostshow.lua:40-42`, `ghostlayer.lua:33-35`, `ghostavatar.lua:33-36`, `ghosttint.lua:42-45`, `ghostwarp.lua:22-30`, `peerinteract.lua:25-32`, via `gatelib:375`.
   - The check is `GH->oeId < 16`, and it ignores the OP_GHOST_SPAWN receipt.
   - Probe: with the unit fake refusing every op (status 3), `ghostshow` and `ghostlayer` report **RESULT: PASS**, because zeroed EWRAM gives `oeId = 0`.
   - Live mitigation:
     - an acked spawn resets `oeId = 0xFF` (`handlers.c:2121`);
     - an un-acked spawn leaves `raw_job` set, so the next raw call asserts.
   - Remaining hole: a ST_FAIL spawn receipt clears `raw_job` and leaves `oeId` as it was. The stale value comes from the savestate, or from a battle or cold-boot EWRAM where `drive_ghost` never ran.
   - These gates are DEFERRED, so this does not block the RC.
   - Fix:
     - `t.check("spawn acked", t.acked_ok(t.ghost_spawn(...)))`;
     - have `ghost_oe()` also require `gObjectEvents[oe]` to be active with `localId == P.LOCALID`.
3. **Skips count as green.** Location: `tests/live/test_lua_gates.py:148-159`.
   - A stale savestate, missing EmuHawk or a missing ROM makes a PORTED gate `pytest.skip`. `SLINK_LIVE=1 pytest` can therefore exit 0 with no gate executed.
   - 20 of the 26 PORTED gates load a savestate, and savestate rot is a known recurring event.
   - Combined with PLAN P5's "39 opcode gates green", a run where every gate skipped reads as a signed receipt.
   - Fix: under `SLINK_LIVE=1`, turn a PORTED gate's prerequisite skip into a failure (or add a strict flag), and print the count of executed gates.

### LOW

4. **The gate count in the plan is out of date.** Location: `docs/gen3/PLAN.md:67,101,207`, which says "39 opcode gates green via gen3_gatelib". The actual layout is 26 run, 11 deferred-skip and 6 archived. Amend the P5 exit criterion so it can be verified.
5. **A raw job never times out.** Location: `gen3_gatelib.lua:120-137, 308-319`.
   - After `wait_posted` or `wait` gives up, `raw_job` stays set. `try_post` then retries every `t.step`, so a zombie post can land later in the gate.
   - The next `t.raw` asserts, and the Lua error leaves no RESULT line. `run_gate` then waits out the 300 s timeout.
   - This fails closed, but it is slow and opaque. Clear the job with a logged FAIL when a wait gives up.
6. **Stages can land anywhere in the BASE span.** Location: `gen3_gatelib.lua:269-273, 329`.
   - `span_of` accepts a stage anywhere in the BASE span, including SIG, ABI and `result` (`BASE+0..63`); native.lua never stages there.
   - No gate does this today. Exclude the BASE span from stages.
7. **A partial post is not treated as poison.** Location: `gen3_gatelib.lua:298-305`.
   - A partial post (a per-write safety refusal mid-post) clears the job, and the next post goes ahead. native.lua poisons in this case (`native.lua:167-171`).
   - While a job is pending, raw also skips native.lua's checks for an overwritten stage or seq. Test-only: document the difference, or mirror it.
8. **"Beacon alive" cannot detect a hang.** Location: `test_live_calctoggle.lua:22,29,44` and `test_mailbox_ping.lua:21-27`.
   - `t.present()` reads a RAM word that persists when the game hangs. The weakness predates the port.
   - The probe shows `calctoggle` PASSes against a fake patch that does nothing, and also against one that refuses.
   - Fix: clobber the SIG and require the hook to rewrite it, as `test_live_ewramtail.lua:88` already does, or watch a frame counter.
9. **explode_route is weaker than forcemove.** Location: `test_live_explode_route.lua:29-44`.
   - It forces slot 0, which is also the default cursor slot, and it lacks forcemove's hand-back check.
   - The ack keeps it decisive once finding 1 is covered. Add `RUN_COMMAND[ctrl]` at the ack for parity.
10. **The FMS drive can race the menu.** Location: `test_live_forcemove.lua:40` and `explode_route:27`.
    - A is pressed on frames where the menu is not parked. If the menu parks within that frame, the player's own handler can consume the A.
    - The result is a false FAIL (slot 0 fires), never a false pass.
    - Neither FMS gate has a live receipt yet under the new rule that the gate never clears exec flags, so liveness is unproven.
11. **The unit tests promise more than they check.** Location: `test_gen3_gatelib.py:193-196, 231-236`.
    - "fails without the companion" is parametrized over 36 gates, but every one fails at the same `t.boot` beacon line.
    - "runs to a verdict" accepts FAIL.
    - Mutating all five decisive forcemove checks to `true` keeps the suite green.
    - The module docstring ("PASS only against a fake patch that really performs the op") holds only for the 5 `COLD_BOOT_OP_GATES`. Narrow the claim.
12. **The `mv` semantics of `ghost_set_pos` changed.** Location: `gen3_gatelib.lua:379`.
    - A Lua `0` now writes idle; the old code wrote 1. The change is intentional, but the deferred gates' inputs now differ from their last live runs.
    - Re-baseline the screenshots when the ghost returns.

## Mutation log (scratch copy outside the repo; baseline 134/134)

| Mutation | Result |
|---|---|
| raw pre-writes `ack = seq` | survived |
| raw drops `ack == job.seq` | survived |
| raw accepts any status (incl. BUSY) | survived |
| raw drops `opcode == 0` assert | survived (equivalent: safety clause) |
| forcemove decisive checks -> `true` | survived |

Probe: every bound gate run under the fake patch with ack OK and with ack FAIL.
- **Unexpected PASS under both:** calctoggle, ghostlayer, ghostshow.
- **Expected PASS under ack OK only:** playse, setpartymon, enemyparty_route, ping, battle.
