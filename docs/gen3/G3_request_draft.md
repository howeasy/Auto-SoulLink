# Gen 3 (P3) Shadow observer gate request — G3 evidence assembly

Refreshed 2026-09-23 at HEAD `eb97f457` from checkpoint-7 evidence. The previous revision was
reconciled at `583517b`; §0 lists what changed. Every PASS below names the receipt file it comes
from, and §7 lists the claims that are **not** tied to a receipt.

---

## 0. Changes since the last draft (583517b → eb97f457)

| # | Change | Evidence |
|---|---|---|
| 1 | **FR `capture_wild` is PHYSICAL** — the previous draft's only blocking lane item. FR run 25 reached the Route 1 catch: observer `capture_wild` ×1 with `callback_address == address` (`shadow_fr_play_run25_2026-09-23.shadow.log:57`), plus `mon_given` ×1 in the same frame (`:56`). | `shadow_fr_play_run25_2026-09-23.txt`, `.shadow.log` |
| 2 | **RR whole-lane PASS at the pointer-correction cut** — `battle_to_field`, `wild_faint`, `wild_catch`, `door_warp`, `pc_ops`, `pc_release`, `save`, with `pc_move_full_party` open. The cut is `09c051d0` (C3-31 driver + C3-33 ROM-derived pointers + the `saveblocks_setter` anchor) and the observer registered 19 sites with 0 rejected, so this run is also the lane smoke of the anchor. | `shadow_rr_play_r9_2026-09-23.txt:43`, `.shadow.log` |
| 3 | **RR `save` PASS on the fixed helper** (C3-30, `30d13c63`): counter 4→5, slot 14/14, dialog closed. | `shadow_rr_play_r8_save_2026-09-23.txt:13` |
| 4 | **FR checkpoint controls re-scored on non-IRQ samples** (C3-32, `2b4e0c68`): idle 276/276 non-IRQ accepted, all 24 refusals IRQ-mode. | `checkpoint_fr_clean_2026-09-23_nonirq.txt:9` |
| 5 | **Positive checkpoint rows need a non-IRQ denominator floor** (C3-35, `eb97f457`): `max(min_samples, 30)`; the receipt now states `floor=`. | `lua/tests/probe_gen3_checkpoint.lua:115-142`; §4 |
| 6 | **RR save-block pointers corrected** (C3-33, `09c051d0`): the packs name `0x03005008` / `0x0300500C` / `0x03005010`, read out of the ROM's `SetSaveBlocksPointers` literal pool. The legacy `0x03003840` / `0x03003838` are literal-pool constants inside `IntrMain_Buffer`, correct only because RR's relocation offset is hard 0. Fact-check `cx-77ee4cb6`. | `data/games/gen3_rr/write_checkpoint.json` `pointers`; `docs/gen3_write_checkpoint.md` §4.4 |
| 7 | **Peer ghost removed from the RC** (owner ruling 2026-09-22): N-2 and the `ghost` scenario are not RC rows; the RR companion set is **eight**. | `docs/gen3/PLAN.md` §0/§10; `docs/gen3_requirements.md` "Not in this release" |
| 8 | **Negative-row clause attribution is enforced** (C3-24, `3040b91a`): a refusal that does not name an expected clause fails the row, so the previous draft's caveat on that point is closed. The receipt's write line is `WRITE_SURFACE none (predicate-only probe)` — still not write evidence. | `lua/tests/probe_gen3_checkpoint.lua` `P.tally`/`P.verdict`; `checkpoint_fr_clean_2026-09-23_nonirq.txt:18` |
| 9 | **FR PC kinds remain pending** — not claimed anywhere in this draft: `viridian_pc_deposit_withdraw` failed again in run 25 (25d path start, 25e incidental-encounter loop), blocked on **C3-36**; FR run 27 pending. C3-34 (`78f2a29e`) landed the incidental-battle FIGHT steering. | `shadow_fr_play_run25_2026-09-23.txt` (25d/25e tails) |
| 10 | FR driver fixes landed that the previous draft listed as in-flight: whiteout destination from `lastHealLocation`, story oracles, door-destination settling, viridian grass-origin step-back. | `d18a6080`, `3ef34edc`, `a1c53f31`, `c06970f3`; `docs/gen3_resume.md` checkpoint 7 |

---

## 1. What G3 signs

G3 (from `docs/gen3/PLAN.md:§6 P3`) requires the owner to sign each exercised signal kind and the
checkpoint predicate as **PHYSICAL** (real cartridge in BizHawk with independent oracles: ENGINE
hook fire, GAME state readback, PYDEC codec agreement). Uncovered kinds and deferred artifacts
(LG clean, RR clean) are listed as OPEN.

---

## 2. Kinds signed PHYSICAL

Receipts cite frozen cuts. **FR clean**: `shadow_fr_play_run17_2026-09-21`, `run18_2026-09-21`,
`run19_2026-09-22`, **`run25_2026-09-23`** (this round). **RR companion**:
`shadow_rr_play_r5_2026-09-21`, `r5d_pc_ops_2026-09-21`, `r6_pc_release_2026-09-22`,
**`r8_save_2026-09-23`**, **`r9_2026-09-23`** (this round). Positive = the observer's SHADOW line
for the kind with `callback_address == address` (`mode=thumb`, raw R15 = +2). Negative =
EXPECTED-ZERO receipt from the same run.

| Kind (requirement) | FR clean positive | RR companion positive | Negative receipt(s) |
|---|---|---|---|
| `battle_begin` / `battle_end` (S-2) | `run25_2026-09-23.shadow.log`: battle_begin 7, battle_end 6 (run17: 8/7; run18: 8/8) | `r9_2026-09-23.shadow.log`: battle_begin 4, battle_end 7 (r5: 4/7) | `negatives_report_2026-09-22.txt` lines 3-4, 85-86: expected-zero PASS ×4 |
| `faint` (S-3) | `run25_2026-09-23.shadow.log`: faint 1 (`run25_2026-09-23.txt:37` route1_faint `playerFaintCounter=1`); run18: 1 | `r9_2026-09-23.shadow.log`: faint 6 (`r9.txt`: `playerFaintCounter 0 -> 1`, HP positive→0, same battler); r5: 6 | `negatives_report_2026-09-22.txt` lines 5, 87: expected-zero PASS ×2 |
| `capture_wild` (S-4) | **✓ PHYSICAL — `run25_2026-09-23.shadow.log:57` capture_wild ×1, `callback_address == address`; same frame `mon_given` ×1 (`:56`); `run25_2026-09-23.txt:31` `outcome=7`, leg-done `:33`** | `r9_2026-09-23.shadow.log:40` capture_wild ×1 (site `0x0907DD88`); `r9.txt`: `outcome=7, party 1 -> 2 after 1 throw(s)`; r5: 1 | `negatives_report_2026-09-22.txt` lines 6, 88, 102: expected-zero PASS ×3 |
| `mon_given` (S-3 gift branch; S-4 catch complement) | `run25_2026-09-23.shadow.log:56` ×1 (inside the catch); run17: 1 (starter); run18: 1 | `r9_2026-09-23.shadow.log` ×1 (inside the catch, frame 2739); r5: 1 | `negatives_report_2026-09-22.txt` lines 7, 90, 109: expected-zero PASS ×3 |
| `pc_move` aggregate (S-5; deposit/withdraw/box_place/release branches) | **pending, not claimed** — the FR `viridian_pc` leg is blocked on C3-36 (run 25d/25e), FR run 27 pending | **✓** `r9_2026-09-23.shadow.log`: `pc_deposit` ×1 (`:47`), `pc_withdraw` ×1 (`:50`), `pc_box_place` ×2 (`:46`,`:51`), `pc_release_begin` ×1 (`:56`), `pc_release` ×1 (`:57`), all `callback_address == address`; `r9.txt`: deposit 3→2 key 91BCEDE1…, withdraw 2→3 same key with the other records byte-identical, release 3→2 key 76A4B39A… gone from party and every box, boxes unchanged. r5d/r6: the same four branches at earlier cuts | `negatives_report_2026-09-22.txt` lines 1-2, 83-84: expected-zero PASS ×2 |
| `whiteout` (S-6) | `run18_2026-09-21.shadow.log`: whiteout 1 (after the faint); run 25 had no whiteout | `r9_2026-09-23.shadow.log`: whiteout 1; r5: 1 | `negatives_report_2026-09-22.txt` lines 8, 89, 107: expected-zero PASS ×3 |
| `map_load` (S-7) | `run25_2026-09-23.shadow.log`: map_load 6 (run17: 8; run18: 8; run19: 1) | `r9_2026-09-23.shadow.log`: map_load 1 (`r9.txt`: door 769→1284 at (7,8)); r5: 1 | `negatives_report_2026-09-22.txt` lines 13, 91, 106: expected-zero PASS ×3 |
| `save` (S-10) | UNVERIFIED as a hook fire (fixture boot-check re-save at counter completion witnesses persistence, not the site); FR run 25 did not reach the FR save leg (it stopped at `viridian_pc`) | **✓** `r8_save_2026-09-23.shadow.log` save ×1 + `r8_save_2026-09-23.txt:13` RESULT PASS (counter 4→5, slot 14/14, dialog closed); `r9_2026-09-23.shadow.log:63` save ×1; r5/r6: 1 each | `negatives_report_2026-09-22.txt` lines 2, 84: expected-zero PASS ×2 |
| `evolved_species_store` (S-8) | OPEN | OPEN | — |
| `trade_done` (S-9) | OPEN (no NPC trade reached in fixture) | OPEN (native trade = duo command, not natural play) | — |
| `poison_faint` (S-11) | OPEN (no poison/field faint scenario) | OPEN (no RR poison site emitted; disabled HP path documented in `docs/gen3_engine_sites.md:15,44,54`) | — |
| `borrowed_party` / `nature_change` (S-12, RR only) | n/a | OPEN (site UNVERIFIED; no authorized natural-play source) | — |

---

## 3. Kinds listed OPEN

| Kind (requirement) | Reason | Where to close it |
|---|---|---|
| `evolve_species_store` (S-8) | No evolution leg scripted in the FR fixture or the RR lane. | Scripted leg: catch → nickname → evolution; natural engine-site fire with a SHADOW line + readback of the evolved species in party/box |
| `trade_done` (S-9) | Vanilla FRLG has no trade executor (PLAN §0, §5.6); the RR native trade is duo-commanded, not natural play. | P5 `native.lua`: RR `trade` scenario with GAME readback of the traded-away species in the partner's party + PYDEC verification |
| `poison_faint` (S-11) | No FR/RR field-poison damage scenario. FR site exists (`0x0807D8C0`), RR site disabled (documented). | Scripted leg or test mode: poison status → faint while walking in grass |
| `borrowed_party` (S-12, RR only) | RR mock-battle party swap/restore sites not authorized (site UNVERIFIED; `docs/gen3_engine_sites.md:45` "proposed"). | RR source or a controlled test: swap, verify both records, restore, verify unchanged |
| `nature_change` (S-12, RR only) | RR nature-changer NPC sites not authorized (`docs/gen3_engine_sites.md:46`); no instance reached. | RR leg: visit the nature-changer; verify the nature field changed in party/storage |
| `pc_move_full_party` (RR) | `SendMonToPC` (RR compressed-storage detour `090B6E38`) only runs on an acquisition that cannot fit a six-mon party; no savestate in the family carries a full party. `r9_2026-09-23.txt:21` prints the `skip-open` row. | Full-party fixture + the `wild_catch` leg on it; then the `pc_move` full-party branch |
| native-op staged (`native_idle`) | Predicate is MODEL-covered but has no production supplier; the probe's mailbox slot check is probe-only, and the client outbox / staged buffers / ghost are not covered. `native_idle=opcode_queue_only`. | P5 `native.lua` (C5-1) supplies the production staged-op state; §4's unreachable table carries the SOURCE+MODEL row |

---

## 4. Checkpoint predicate

Requirement (from `docs/gen3/PLAN.md:§5.3,§6 P3`): checkpoint must be true in town and false in
every forbidden state (script running, save in progress, PC menu open, evolution, link, native op
staged, mid-relocation), with an empty write log in all false cases.

**RR companion** — `checkpoint_rr_companion_2026-09-22b.txt` (9/9 states PASS):
- idle town positive: `:10` sampled=300 true=300 false=0 (liveness)
- walking positive: `:11` sampled=120 true=120 false=0
- start menu `:12` 120 / 0 true; save dialog `:13-14` 120/758 / 0 true; battle `:15` 120 / 0 true;
  palette fade `:16` 76 / 0 true; PC menu `:17` 122 / 0 true; script running `:18` 123 / 0 true
- native op staged: `:19` `native_idle=opcode_queue_only` (marker only — see §3)

**FR clean** — `checkpoint_fr_clean_2026-09-23_nonirq.txt`, `RESULT: PASS all checkpoint controls`,
scored over non-IRQ samples (C3-32):
- idle positive: `:9` sampled=300 non_irq_sampled=276 non_irq_true=276 (all 24 non-accepted frames
  are IRQ mode, refused by the parked-CPU clause) — floor 30, so a PASS by a wide margin
- walking positive: `:10` 120 / 109 / 109
- start menu `:11` 120 / 111 / 0 true; dialog `:12` 120 / 114 / 0 true; save in progress `:13`
  244 / 215 / 0 true; battle `:14` 120 / 120 / 0 true; fade `:15` 43 / 40 / 0 true;
  script running `:17` 123 / 115 / 0 true; pc_menu `:16` SKIP (RR-only row)
- every negative row's refusals carry its expected clause (C3-24 attribution) and the probe warns
  per row if a refusal is unattributed

**Positive-sample floor (C3-35, `eb97f457`)**: a positive row needs
`non_irq_samples >= max(min_samples, 30)` before its 90% rate counts; the refusal is named
`non-IRQ samples N < floor F` and the receipt prints `floor=`. The 2026-09-23 receipt predates the
floor line (produced at `37f3043b`); idle's 276 non-IRQ samples clear the floor by 9×, as do the
other recorded idles (275/300, 300/300).

**FR parcel lineage liveness**: `checkpoint_fr_parcel_lineage_2026-09-22.txt` idle 0/300 FAIL
before the link-predicate fix (sticky `gWirelessCommType`, the wrong predicate);
`…2026-09-22b.txt` idle 275/300 PASS after C3-22 (`gReceivedRemoteLinkPlayers`).

**Unreachable states (SOURCE+MODEL disposition, no PHYSICAL receipt):** carried from
`docs/gen3/research/checkpoint_unreached_states.md:§7` with the C3-22 errata and the C3-33 pointer
resolution — evolution (FR/LG/RR), link (all), native-op staged (RR, GAP), mid-relocation
(FR/LG/RR; RR's pack pointers are now ROM-derived, and the clause is structurally vacuous because
the offset is fixed at 0), PC menu (FR), empty write log (MODEL; `write_log count=0` is
tautological on a predicate-only probe — the receipt says `WRITE_SURFACE none`).

---

## 5. Reconciliation of `docs/gen3/research/g3_evidence_gap_audit.md` §5 (R10 checklist, `870a0f2`)

Reconciled at HEAD `eb97f457`. Rows unchanged from the previous revision are marked with their new
evidence only.

| Obligation | R10 status | Current status (2026-09-23) | Evidence file(s) |
|---|---|---|---|
| Bad/absent anchors refuse build and arm nothing | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt:14` |
| Bounded queue | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt:42` |
| Callback-address mismatch rejection | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt:40-41` |
| Every observer mutation sink throws | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt:99-102` |
| Observer isolation: mode, network, HUD, unique hooks, own teardown | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt:105-111` |
| DROP/DUPLICATE/MISORDER mutations falsify reducer | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt:114-116` |
| Injected-HP faint is commanded, not engine faint | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt:120` |
| Overhead ≤5%, both callback orders | PARTIAL | **PARTIAL** — RR: real-time 0.00% wall delta with the observer and 0 semantic wire deltas against the real old client; FR: diagnostics only (stand-in, no wire side). The unthrottled +98% CPU cost is informational, not a budget claim. | `overhead_rr_{throttled,unthrottled}_2026-09-21.txt`, `wire_delta_rr_explode_2026-09-21.txt`, `overhead_fr_*` (diagnostics) |
| Natural-play sources complete | PARTIAL (FR/RR runs failed at legs) | **PARTIAL** — FR run 25: `parcel_deliver`, `route1_catch`, `route1_faint` complete; `viridian_pc` blocked (C3-36). RR r9: whole lane PASS except `pc_move_full_party` (OPEN). | `shadow_fr_play_run25_2026-09-23.txt`, `shadow_rr_play_r9_2026-09-23.txt` |
| One positive per semantic branch | PARTIAL (six FR/eight RR) | **PARTIAL** — pc_move branches ✓ (deposit/withdraw/box_place/release, `r9`); `capture_wild` now ✓ on FR too; missing: trade_begin / evolve_species_store / pc_move_full_party | `negatives_report_2026-09-22.txt`; `r9_2026-09-23.shadow.log` |
| One expected-zero negative per semantic branch | MISSING | ✓ **DONE** (fork-level: 79/79 expected-zero PASS over 10 receipts; per-branch negatives for trade, evolution, poison remain MISSING) | `negatives_report_2026-09-22.txt:114-116` |
| Natural-play differential per-artifact, zero unexplained, reason ledger | PARTIAL | **PARTIAL** (RR r5/r5d/r6 within instrument scope; FR run 17 scope < full pair; ledger has open branches). The r8/r9 runs are lane receipts, not differentials — no wire side by design. | `shadow_ledger/*_2026-09-21.json` |
| Checkpoint positives in town | PARTIAL; RR DONE | ✓ **RR DONE**, ✓ **FR DONE** | `checkpoint_rr_companion_2026-09-22b.txt:10-11`; `checkpoint_fr_clean_2026-09-23_nonirq.txt:9-10` |
| Every forbidden state false + empty write log | PARTIAL | ✓ **RR DONE**; ✓ **FR DONE** (per-row clause attribution enforced, C3-24) | `checkpoint_rr_companion_2026-09-22b.txt:1-19`; `checkpoint_fr_clean_2026-09-23_nonirq.txt:1-19` |
| reads == PYDEC on dumped RAM | PARTIAL | ✓ **DONE** (RR real Treecko; FR real party record) | `reads_pydec_rr_2026-09-21.txt:2-7`, `reads_pydec_fr_party_2026-09-22.txt:3-6` |

**Summary:** 11/15 DONE (7 model gates + negatives + 2 checkpoint + reads), 4/15 PARTIAL
(natural-play coverage, per-branch positives, the differential, overhead), 0 MISSING.

---

## 6. Deferred artifacts

| Artifact | Status | Why deferred |
|---|---|---|
| **LG clean** | Not signed | No LG fixture cycle yet (dump placed at G0). LG is byte-identical to FR at the engine sites, so one natural-play run on LG (e.g. `route1_catch` paired with FR) would close the equivalence. Queued for P3 wrap-up. |
| **RR clean** | Not signed | No natural-play receipts on the RR clean base (md5 `8529f3a4…`); no observer run. PLAN §6 P5 covers it as the `native_absent` conditional scenario (clean RR beside companion RR: native refused cleanly, storage via the Lua fallback), not a full qualification. Site anchors match the companion at P2, but there is no PHYSICAL natural-play receipt. |

---

## 7. Summary for the owner

G3 evidence assembly, refreshed at `eb97f457`:

- **7 kinds PHYSICAL-signed on FR clean**: `battle_begin`, `battle_end`, `faint`, **`capture_wild`
  (new, run 25)**, `mon_given`, `whiteout`, `map_load`. **`save` remains UNVERIFIED as a hook fire**
  on FR (the fixture boot-check re-save is a persistence witness, not the site), and no FR receipt
  covers it; FR run 25 stopped before the FR save leg.
- **9 kinds PHYSICAL-signed on RR companion**: the seven above plus `pc_move` with all four
  sub-branches (`pc_deposit`, `pc_withdraw`, `pc_box_place`, `pc_release`) and `save` (the
  dedicated r8 receipt plus r9).
- **7 kinds OPEN**: `evolve_species_store`, `trade_done`, `poison_faint`, `borrowed_party`,
  `nature_change`, `pc_move_full_party`, native-op-staged (§3).
- **FR PC kinds (`pc_deposit`/`pc_withdraw`/`pc_box_place`/`pc_release`) are NOT claimed on FR**:
  blocked on C3-36, FR run 27 pending.
- **Checkpoint predicate**: RR PASS (9/9 rows, receipt at the 2026-09-22b cut — not re-run this
  round); FR PASS on the non-IRQ scoring with per-row clause attribution and the positive-sample
  floor of §4.
- **Deferred artifacts**: LG clean, RR clean (§6) — `·`, not signed.

Blocking items for the request:

1. FR PC kinds (C3-36 + FR run 27) — the only lane work left for the FR artifact's PC row.
2. LG clean and RR clean remain deferred, as stated in §6.

Stated limits (go to the owner as limits, not as DONE): the four PARTIAL rows in §5 (natural-play
coverage, per-branch positives for trade/evolution, the differential's missing wire side, overhead
measured on stand-ins and without a wire side on FR), the seven OPEN kinds in §3, the FR `save`
hook fire, and the FR run-25 passes being leg-level (`leg-done` + the observer's fire in a resumed
sub-run) rather than a run-level `RESULT: PASS`.

---

**File prepared:** `docs/gen3/G3_request_draft.md`
**Current head:** `eb97f457`
**Counts:** 11 DONE (7 model gates + negatives + 2 checkpoint rows + reads), 4 PARTIAL, 0 MISSING;
7 kinds OPEN.
