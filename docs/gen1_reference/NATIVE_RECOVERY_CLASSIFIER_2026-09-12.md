# Native trade post-COMMIT recovery: classifier matrix (B2), 2026-09-12

Branch `claude/gen1-native-free-service`. Status: **revision 2 after Codex review, no forward action
enabled**. Everything below is derived from current source; nothing here has been exercised live.

## 1. Evidence layers (each independent; none may stand in for another)

| Layer | Source of truth | What it can and cannot say |
| --- | --- | --- |
| S1 server phase | `paired-trade` record (`trade_coordinator.py`): `commit_persisted` .. `link_committed`, `applied[p]`, `verified[p]`, `recovery_required` | Authoritative COMMIT ordering. Says nothing about the cartridge. |
| S2 server high-water | `gen1-native-windows[p][commit command]` (d28bd4a): `armed`, `sequence_length` = confirmed original-routine prefix of `SEQUENCE` = service, InternalClockTradeAnim, TryEvolvingMon, SavePartyAndDexData (`gen1_native_trade_receipts.py:15`); `host.frame`, `intent_digest` (binds the lease token) | A **lower bound** on progress: a window is issued only after the client proved the previous prefix, so prefix n means at least hook n fired. It lags reality by up to one 60-frame window; mutation can occur after the last renewal. `armed:false` (the `before` window) means credits were granted before any write. No window at all means no credits were ever granted for this command. |
| S3 server preparation | `gen1-native-preparation[tx][p]` (08faa13): full B checkpoint (`cart_hex`, party, storage, map, name), full-save point, prompt closure | The exact prepared image B; the predicted A comes from `TradeResultRules` (`gen1_trade_result.py`) applied to the proposal. |
| C lease | `native.json` (`gen1-native-trade-lease-v1`, `state_store.lua`): `idle` / `armed` (intent + token, persisted BEFORE the RAM write, `gen1_native_trade_executor.lua:191-209`) / execution receipts per hook / `releasing` | Client-durable only. Missing or checksum-valid-but-older revision is indistinguishable from never-armed (`state_store.lua:53-63` idle-inits a missing file; no `context_generation`/`physical_instance` binding, `gen1_native_runtime.lua:129-143`). |
| O overlay | 16 WRAM bytes at `foreground.overlay` (`0xC508` on Red, outside the observed main-data range `wMainDataStart..End` = `0xD2F7..0xDA80`), byte4 `1`=published, byte5 `5`=APPLY armed / `7`=DONE waiting for release / `8`=RELEASE, byte6/7 generation published/completed, byte8 result (`0` ok, `2` uncertain append), bytes 12-15 token (`trade_service.asm:69-160`, `gen1_native_trade_executor.lua:107-111,156-168,207-208,234`) | The cartridge's own progress word, WRAM only. NOT in today's inventory/native checkpoint: the classifier needs an explicit `union_hex` readback (the executor already reads it, `:142`). While the routine runs the overlay is swapped with the tile backup (`trade_service.asm:88-95`), so mid-routine it reads as tiles. |
| R readback | party readback + storage + save region at the next write-safe checkpoint, or at reattach if the CPU is inside the routine | Physical shape now. Compared to B (S3) and A_pred (S3 + rules). Equal bytes only prove shape, never operation. |
| S SaveRAM | `readback.save` region of CartRAM / the save file | The ONLY state that survives an emulator restart. `SavePartyAndDexData` writes it as the last routine step (`native_trade.asm:203`). |
| F file | `save_file_receipt` (`slink-saveram-file-v1`, owned frame, flushed, readback) | Durability of the file on the host, only for a frame inside an owned window (`gen1_native_policy.verified`, now durable-window aware, 170a69c). |

Rules the matrix applies (Codex decisions of 2026-09-12): post-COMMIT never rolls back, never re-runs the
mutating routine from before-looking bytes alone, never synthesizes `trade_applied`/`trade_verified` from
bytes; `unknown -> hold` is a terminal outcome for this build, reported as such, not as recovery.

## 2. Physical facts that shape the classes (source)

1. The routine is monolithic and cannot be resumed midway: metadata copies, Yellow happiness, `RemovePokemon`,
   `AddEnemyMonToPlayerParty` (party mutated), 100 delay frames + `InternalClockTradeAnim`, `TryEvolvingMon`,
   screen restore, `SavePartyAndDexData` (`native_trade.asm:120-203`). Only WRAM changes until the final save.
2. After completion the cartridge spins in `.waitForReceipt` inside DelayFrame until byte5 becomes `8`
   (`trade_service.asm:118-160`, "a disconnected client stays in this foreground lease for recovery"): a
   completed-but-unreleased side is physically halted at DONE, not playing.
3. The routine enters only when byte4==1, byte5==5 and byte6!=byte7 at the DelayFrame bridge (`:69-83`); under
   bounded stepping no frame runs without a server window. **Hazard:** if a client restarts into ordinary
   free_service with an APPLY-armed overlay still in WRAM, the next free frame runs the trade routine with no
   ownership. The reattach must read O before the loop may free-run (see §4, rule 0).
4. A full emulator restart loses WRAM: the game reboots from SaveRAM, so R == S at the first checkpoint and O is
   empty. Anything the routine did before `SavePartyAndDexData` is physically gone.
5. Equal-byte trade (both halves identical bytes): B == A_pred for party and save region; R/S can never
   distinguish applied from not applied.

## 3. Classes per player (post-COMMIT, `recovery_required` set on reopen)

Inputs: HW (S2 prefix: `none` no window, `0` before-only, `1..4`), O (overlay word when the emulator process
survived, else `n/a`), R, S, C, F. "A" means equals A_pred, "B" equals the prepared image, "X" anything else.

| # | Situation | HW | O | S | R | Class | Permitted action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Commit dispatched, no window ever issued | none | not armed / n/a | B | B | `never_issued` | Forward: re-deliver the same pending `native_trade_commit` (same command id, same intent digest); the client re-prepares from the durable intent. Safe because `authorize_apply` needs a window and none existed. Requires C not `applied/releasing`; if C claims progress, class 10. |
| 2 | No window, but O armed (`5`) | none | `5`, token == intent | B | B | `armed_without_authority` | Hold. A client wrote the overlay without a window (bug/tamper). Disarm only under an explicit held write after review. |
| 3 | Before-window only, same emulator process, overlay not armed | 0 | `4`!=1 or `5`!=5, read under the reattach hold | B | B | `credits_unused` | Forward as 1 only with operation-bound proof that the routine never ran: overlay never consumed (byte6==byte7 or byte4!=1) AND the client lease has no execution receipt AND the CPU is at the DelayFrame bridge / overworld loop (PC, SP and stack words per `gen1_write_safety.lua:53-66`). HW=0 is a lower bound only (one window may have run up to 60 frames), so B-looking bytes alone never decide. Non-equal-byte only. After an emulator reboot this row does not apply (row 6). |
| 4 | Before-window only, overlay armed, same emulator process | 0 | `5`, byte6!=byte7, token == intent | B | B | `armed_pending` | Hold the free loop (rule 0). Forward only when the CPU provably has not entered the service: PC/SP inside the overworld DelayFrame path (`gen1_write_safety.lua:53-66` invariant) or at the bridge before `save_overlay_on_stack` (`trade_service.asm:88`); then re-issue windows for the same command and let the routine start under ownership. If the CPU is anywhere else, row 5 or row 10. Requires C lease armed with the same token. |
| 5 | Routine entered, emulator alive, CPU inside the routine or at DONE | >=1 | tiles (mid) or `7` (DONE) | B or A | partial/A | `in_progress` / `done_unreleased` | Forward: re-issue armed windows for the same command with the same intent; continue stepping to DONE, collect the execution receipt (hooks already fired are in C; the server accepts only prefix >= HW), then release. Requires emulator framecount >= HW `host.frame`, same ROM/save identity, C present and consistent. Any mismatch: class 10. |
| 6 | Emulator process replaced (ordinary crash), save region == B at the witnessed reboot | any <4 | n/a (WRAM lost) | B | B (boot) | `process_replaced` | Hold in this build: the physical owner is bound at enrollment (`gen1_held_faint.verify_owned_host` process_id; `gen1_native_progress.durable_progress`), so a replaced emulator can obtain no authority. Forward path exists only through the controlled re-enrollment of section 6, which makes S==B at a witnessed boot a durable proof of non-application (WRAM was the only place the routine had written) and then re-runs the same commit. Non-equal-byte only; equal-byte is row 10. |
| 7 | Emulator process replaced, save region == A_pred, server witnessed the save hook | 4 | n/a | A | A (boot) | `process_replaced_saved` | Hold in this build; through section 6 re-enrollment: operation proof = the durable prefix-4 window (server-durable, once-only per lease) + S==A_pred + the file the new process booted from; forward = file readback receipt under a new window on the new process (a read, not a flush), then verified/finalize. Non-equal-byte only. |
| 8 | Emulator process replaced, save region == A_pred, server never witnessed the save hook | <4 | n/a | A | A | `saved_unwitnessed` | Hold, owner decision. Bytes alone; no once-only provenance for the save step. |
| 9 | Peer already `verified`/`link_committed` on the other side; this side any of 1-7 | | | | | as above | The peer's completion never changes this side's class; forward completion is per side. Releases (`native_trade_release`) stay pending until both are done; preparation evidence is retained until then (08faa13). |
| 10 | Lease missing or rolled back (revision below the server high-water), armed lease after process replacement with no emulator continuity, O in an unexpected state, R/S == X, result byte8 == 2, or an equal-byte trade in ANY row whose proof is a byte shape (every row except 1 and 5, where the proof is the absence of a window or the live CPU/overlay state) | | | | | `unknown` | Hold both sides. Record the class and the evidence digests durably; report; no mutation, no release, no rollback. |
| 11 | Savestate load / file rollback detected (framecount < durable window frame with the same process, or S older than the prepared image) | | | | | `rolled_back` | Hold both sides permanently for this build; owner decision. |

Pre-COMMIT (`preparing`, `both_prepared`): interruption cancels and aborts as today (`_interrupt_trades`);
the retained preparation stays until the aborts close (08faa13) so a client can restore its overlay.

## 4. Rules before any forward action (must be true of the implementation)

0. **Hold before the first frame.** `gen1_client_entry.lua` free-runs (`emu.yield()`, `:451`) until the first
   write-safe visible overworld frame before `begin()` builds the host (`:376-378`); with a native manifest and an
   APPLY-armed overlay in WRAM that first free frame runs the routine unowned (fact 3). The native composition
   must construct the host and take a hold at script start, before any yield/frameadvance, read the 16 overlay
   bytes, the lease and the CPU registers, and keep the hold until the server has classified; admission and
   control already run under a hold (`:320`), so classification does not need a free frame. Source/test proof
   of this start-of-script hold precedes any forward code.
1. Server-durable prewrite witness: the `before` window (`armed:false`) is issued before the overlay write and
   is journaled (d28bd4a); the lease token is bound through `intent_digest`. Every forward re-issue uses the
   same command id and the same intent digest; a different token is refused.
2. High-water monotonicity: windows for a command never regress (`gen1_native_windows.persist` refuses), and a
   client-reported prefix below HW is refused.
3. Equal-byte trades: decidable only by operation-bound proof, never by B/A shape: row 1 (no window ever
   issued), row 5 (live CPU inside the routine or overlay DONE with the token), and rows 3/4 only through the
   CPU/overlay invariants named there. Rows 6-8 are unknown for equal-byte trades.
4. Both-peer gate: forward actions on one side may run while the other side holds, but finalize requires both
   sides `verified`; a held side keeps the trade in `recovery_required` and the release commands pending.
5. Nothing is released (`byte5=8`) until the server has the verified receipt; `.waitForReceipt` keeps the
   cartridge halted otherwise (fact 2), which is the intended fail-closed state.

## 5. What remains unknown until the controlled probe (exclusive lane) (exclusive EmuHawk lane, Codex-granted)

- Whether a client can be killed and reattached with the CPU inside `SlinkTradeApply` and the bounded stepper
  resumed (class 5). Probe: arm, step to a known hook, kill the Lua client (not the emulator), relaunch the
  checked launcher, verify framecount and overlay, resume windows, reach DONE, release.
- Whether a full emulator restart before `SavePartyAndDexData` really lands on R==S==B with a clean overlay
  (class 6), on R/B and Y/Y: informative only, since a replaced process holds in this build.
- Whether the file receipt after class 5 (DONE, unreleased, same process) can be produced inside a fresh
  window without a new mutation; 838af24 proves only that the receipt produced INSIDE the original window
  verifies after a reopen.
- The owner decision in classes 6/7 (a replaced emulator process: permanent hold for this build, or a
  controlled re-enrollment design).

Nothing in §3 is implemented; the classifier code will encode exactly this table, with a test per row and a
recorded durable decision (class, evidence digests, action) so every hold is auditable and every forward step
is traceable to a row.

## 6. Controlled re-enrollment of a replaced emulator process (design, not implemented)

Full process replacement is an ordinary crash and cannot stay a permanent hold if the blocker is to close.
What makes it tractable: after a reboot the cartridge's only durable state is SaveRAM, and the game re-derives
WRAM from it, so a witnessed boot turns "bytes look like B" into "the durable store IS B and nothing else
survived". The design:

1. **Reboot witness (client).** With a native manifest the entry installs `gen1_bootstrap_observer` (already
   present for New Game, `gen1_client_entry.lua:64-70`) on the CONTINUE path too, proving the normal source
   entry/return of the boot into the overworld, then takes the first write-safe checkpoint under the writer
   hold with the full SaveRAM image, the party readback, the overlay (expected cleared) and the lease. It
   publishes this as a `reenrollment` event, not an `observation`: no rule settlement rides on it.
2. **Server acceptance (new component `gen1-reenrollment`).** Accepted only when: same run, player, cartridge
   sha1 and save identity as the enrollment; a non-terminal or `recovery_required` trade exists or every
   obligation is closed; the boot witness verifies; the SaveRAM image equals either the retained prepared
   full-save point B (08faa13) or the A_pred image derived from it by `TradeResultRules` (save region) with
   every other byte equal to B (the same equality `verified()` applies today). Anything else: `unknown -> hold`.
   The record binds old process -> new process with the witness digests; `verify_owned_host`
   (`gen1_held_faint.py:88-116`) and `durable_progress` consult it and accept the new process from then on.
   Neither of the two files frozen for lane A is touched (`gen1_runtime.py`, `gen1_runtime_state.py` only
   register the audit later, as with the other components).
3. **Classification after re-enrollment** is rows 6-8 with the witness in hand: S==B -> re-run the same
   commit (same command id, same intent; the client re-prepares from the retained preparation; the ROM
   routine runs once under fresh windows); S==A_pred with prefix 4 -> file readback receipt under a new window
   (a read of the file the process booted from, never a flush), then verified/finalize; S==A_pred with prefix
   <4 -> hold, owner decision; equal-byte -> hold.
4. **Both peers** re-enroll independently; the trade stays `recovery_required` until both sides reach
   `verified` or one is held; releases stay pending meanwhile (08faa13 keeps the preparation).

Impasse to bring to the owner if (2) is not accepted: without it a replaced emulator has no authority by
design, so a permanent hold is the only honest outcome for any crash that takes the emulator with it.
