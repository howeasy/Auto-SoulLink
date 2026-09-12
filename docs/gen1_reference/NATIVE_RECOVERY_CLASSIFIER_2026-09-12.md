# Native trade post-COMMIT recovery: classifier matrix (B2), 2026-09-12

Branch `claude/gen1-native-free-service` at 838af24. Status: **proposal for Codex review, no forward action
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
| 3 | Before-window only, routine not entered | 0 | not armed (`4`!=1 or `5`!=5) or `n/a` after reboot | B | B | `credits_unused` | Forward as 1 after the overlay is confirmed clear (emulator alive) or the reboot is confirmed (fresh initial observation, R==S==B). Non-equal-byte trades only. |
| 4 | Before-window only, overlay armed, routine not started | 0 | `5` | B | B | `armed_pending` | Hold the free loop (rule 0). Forward: re-issue windows for the same command; the client resumes bounded stepping and the routine starts under ownership. Requires C lease armed with the same token; else class 10. |
| 5 | Routine entered, emulator alive, CPU inside the routine or at DONE | >=1 | tiles (mid) or `7` (DONE) | B or A | partial/A | `in_progress` / `done_unreleased` | Forward: re-issue armed windows for the same command with the same intent; continue stepping to DONE, collect the execution receipt (hooks already fired are in C; the server accepts only prefix >= HW), then release. Requires emulator framecount >= HW `host.frame`, same ROM/save identity, C present and consistent. Any mismatch: class 10. |
| 6 | Emulator restarted, save never written | any <4 | n/a | B | B (reboot) | `process_replaced` | Hold, owner decision. The run's physical owner is bound at enrollment: every held write and every durable window requires the enrolled emulator process (`gen1_held_faint.verify_owned_host` process_id check; `gen1_native_progress.durable_progress`, 838af24), so a replaced emulator can obtain no authority in this build. Physically S==B would make a re-run safe (WRAM lost, non-equal-byte only), but that needs a controlled re-enrollment design that does not exist. |
| 7 | Emulator restarted, save written, server saw the save hook | 4 | n/a | A | A (reboot) | `process_replaced_saved` | Hold, owner decision (same reason as 6). The durable prefix 4 plus S==A is server-durable, once-only evidence that the save step was reached; whether it may count as operation-bound proof for a replaced process is the owner's call. |
| 8 | Emulator restarted, save written, server never saw the save hook | <4 | n/a | A | A | `saved_unwitnessed` | Hold. Bytes alone; no once-only provenance; and the process is replaced (6). |
| 9 | Peer already `verified`/`link_committed` on the other side; this side any of 1-7 | | | | | as above | The peer's completion never changes this side's class; forward completion is per side. Releases (`native_trade_release`) stay pending until both are done; preparation evidence is retained until then (08faa13). |
| 10 | Lease missing or rolled back (revision below the server high-water), armed lease after process replacement with no emulator continuity, O in an unexpected state, R/S == X, result byte8 == 2, or equal-byte trade in any class other than 6-with-fresh-reboot | | | | | `unknown` | Hold both sides. Record the class and the evidence digests durably; report; no mutation, no release, no rollback. |
| 11 | Savestate load / file rollback detected (framecount < durable window frame with the same process, or S older than the prepared image) | | | | | `rolled_back` | Hold both sides permanently for this build; owner decision. |

Pre-COMMIT (`preparing`, `both_prepared`): interruption cancels and aborts as today (`_interrupt_trades`);
the retained preparation stays until the aborts close (08faa13) so a client can restore its overlay.

## 4. Rules before any forward action (must be true of the implementation)

0. **Reattach reads O before the loop free-runs.** With a native manifest, the free_service client must take
   the writer hold at reattach, read the 16 overlay bytes plus the lease, publish them in its first observation
   (`native_checkpoint.union_hex` + lease summary), and stay held until the server classifies. An armed overlay
   with no window must never see a free frame (fact 3).
1. Server-durable prewrite witness: the `before` window (`armed:false`) is issued before the overlay write and
   is journaled (d28bd4a); the lease token is bound through `intent_digest`. Every forward re-issue uses the
   same command id and the same intent digest; a different token is refused.
2. High-water monotonicity: windows for a command never regress (`gen1_native_windows.persist` refuses), and a
   client-reported prefix below HW is refused.
3. Equal-byte trades: only classes 1, 3, 4, 5 (emulator alive, overlay/CPU evidence) and 6 (fresh reboot with
   S==B) are decidable; 7/8 are unknown regardless of bytes.
4. Both-peer gate: forward actions on one side may run while the other side holds, but finalize requires both
   sides `verified`; a held side keeps the trade in `recovery_required` and the release commands pending.
5. Nothing is released (`byte5=8`) until the server has the verified receipt; `.waitForReceipt` keeps the
   cartridge halted otherwise (fact 2), which is the intended fail-closed state.

## 5. What remains unknown until the controlled probe (exclusive EmuHawk lane, Codex-granted)

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
