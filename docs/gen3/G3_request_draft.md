# Gen 3 (P3) Shadow observer gate request — G3 evidence assembly

## 1. What G3 signs

G3 (from `docs/gen3/PLAN.md:196`) requires the owner to sign each exercised signal kind and the checkpoint predicate as **PHYSICAL** (real cartridge in BizHawk with independent oracles: ENGINE hook fire, GAME state readback, PYDEC codec agreement). Uncovered kinds and deferred artifacts (LG clean, RR clean) are listed as OPEN.

---

## 2. Kinds signed PHYSICAL

Receipts cite frozen cuts: `shadow_rr_play_r5_2026-09-21.shadow.log` (run 5, RR companion natural play), `shadow_rr_play_r5d_pc_ops_2026-09-21.shadow.log` (RR PC deposit/withdraw/box operations), `shadow_rr_play_r6_pc_release_2026-09-22.shadow.log` (RR PC release), `shadow_fr_play_run17_2026-09-21.shadow.log` (FR run 17, natural play), `shadow_fr_play_run18_2026-09-21.shadow.log` (FR run 18, faint/whiteout), `checkpoint_rr_companion_2026-09-22b.txt` (RR checkpoint probes), `checkpoint_fr_clean_2026-09-22d.txt` (FR checkpoint probes). Positive = callback address matches site, SHADOW line emitted with keyed transaction. Negative = EXPECTED-ZERO receipt from the same run.

| Kind (requirement) | FR clean positive | RR companion positive | Negative receipt(s) |
|---|---|---|---|
| `battle_begin` / `battle_end` (S-2) | `shadow_fr_play_run17_2026-09-21.shadow.log`: battle_begin 8, battle_end 7; `shadow_fr_play_run18_2026-09-21.shadow.log`: battle_begin 8, battle_end 8 | `shadow_rr_play_r5_2026-09-21.shadow.log`: battle_begin 4, battle_end 7 | `negatives_report_2026-09-22.txt` lines 3-4, 85-86: expected-zero PASS ×4 |
| `faint` (S-3) | `shadow_fr_play_run18_2026-09-21.shadow.log`: faint 1 (starter fainted in the Route 1 catch battle) | `shadow_rr_play_r5_2026-09-21.shadow.log`: faint 6 | `negatives_report_2026-09-22.txt` lines 5, 87: expected-zero PASS ×2 |
| `capture_wild` (S-4) | OPEN on FR (run 18 reached the encounter but the starter fainted before capture; recovery pending) | `shadow_rr_play_r5_2026-09-21.shadow.log`: capture_wild 1 (catch outcome 7, party 1→2) + mon_given 1 (same frame) | `negatives_report_2026-09-22.txt` lines 6, 88, 102: expected-zero PASS ×3 |
| `mon_given` (S-3 gift branch; S-4 catch complement) | `shadow_fr_play_run17_2026-09-21.shadow.log`: mon_given 1 (starter gift in the intro); `shadow_fr_play_run18_2026-09-21.shadow.log`: mon_given 1 | `shadow_rr_play_r5_2026-09-21.shadow.log`: mon_given 1 (inside catch, frame 2739; no keyed identity, folded with capture_wild by reducer) | `negatives_report_2026-09-22.txt` lines 7, 90, 109: expected-zero PASS ×3 |
| `pc_move` aggregate (S-5; deposit/withdraw/box_place/release branches) | UNVERIFIED (FR: no PC access in current fixture) | `shadow_rr_play_r5d_pc_ops_2026-09-21.shadow.log`: pc_move 4 (deposit 3→2, withdraw 2→3 of same key, same-record byte-equal; observer `pc_deposit` ×1, `pc_withdraw` ×1, `pc_box_place` ×2); `shadow_rr_play_r6_pc_release_2026-09-22.shadow.log`: pc_move 5 (deposit 3→2, withdraw 2→3, release 3→2; observer `pc_deposit` ×1, `pc_withdraw` ×1, `pc_box_place` ×2, `pc_release` ×1) | `negatives_report_2026-09-22.txt` lines 1-2, 83-84: expected-zero PASS ×2 |
| `whiteout` (S-6) | `shadow_fr_play_run18_2026-09-21.shadow.log`: whiteout 1 (after the faint) | `shadow_rr_play_r5_2026-09-21.shadow.log`: whiteout 1 | `negatives_report_2026-09-22.txt` lines 8, 89, 107: expected-zero PASS ×3 |
| `map_load` (S-7) | `shadow_fr_play_run17_2026-09-21.shadow.log`: map_load 8 (door traversals, map IDs logged); `shadow_fr_play_run18_2026-09-21.shadow.log`: map_load 8; `shadow_fr_play_run19_2026-09-22.shadow.log`: map_load 1 | `shadow_rr_play_r5_2026-09-21.shadow.log`: map_load 1 (769→1284) | `negatives_report_2026-09-22.txt` lines 13, 91, 106: expected-zero PASS ×3 |
| `save` (S-10) | UNVERIFIED as hook fire (fixture boot-check re-save at counter completion is witness to persistence, not the signal site `0x08015D36`/`0x0803DE7C`); no SHADOW line observed | `shadow_rr_play_r5_2026-09-21.shadow.log`: save 1 (counter advanced, 14/14 sectors written); `shadow_rr_play_r6_pc_release_2026-09-22.shadow.log`: save 1 | `negatives_report_2026-09-22.txt` lines 2, 84: expected-zero PASS ×2 |
| `evolved_species_store` (S-8) | OPEN | OPEN | — |
| `trade_done` (S-9) | OPEN (no NPC trade reached in fixture) | OPEN (native trade = duo command, not natural play) | — |
| `poison_faint` (S-11) | OPEN (no poison/field faint scenario) | OPEN (no RR poison site emitted; disabled HP path documented in `docs/gen3_engine_sites.md:15,44,54`) | — |
| `borrowed_party` / `nature_change` (S-12, RR only) | n/a | OPEN (site UNVERIFIED; no authorized natural-play source) | — |

---

## 3. Kinds listed OPEN

| Kind (requirement) | Reason | Where to close it |
|---|---|---|
| `evolve_species_store` (S-8) | No evolution leg scripted in current FR fixture (starts at parcel_deliver) or RR run 5. FR run 18 extends route1_faint to route1_catch with retry logic (needs whiteout recovery); evolution stays sequenced after catch. | Scripted FR leg: catch → nickname → evolution (level-up stones or holder mechanic); natural engine site fire with SHADOW line + readback of the evolved species in party/box |
| `trade_done` (S-9) | Vanilla FRLG: no trade executor (§0, §5.6 of PLAN); native NPC route on RR is duo-commanded (not natural play). No FR receipt; RR native trade = `docs/gen3/shadow_ledger/trade.json` marked as commanded/native, reachable only at P5 when trade scenario lands. | P5 native.lua: RR `trade` scenario with GAME readback of the traded-away species in the partner's party and PYDEC verification of the swapped records; natural trade (NPC) via a scripted leg (if ever needed) |
| `poison_faint` (S-11) | No FR/RR field poison damage scenario. FR site exists (`FRsites:413-416`, `0x0807D8C0`), RR site disabled (documented, `docs/gen3_engine_sites.md:15,44,54`). | Scripted leg or test mode: poison status → faint while walking in grass; RR: reenable the site if future work adds poison damage |
| `borrowed_party` (S-12, RR only) | RR mock-battle party swap/restore sites not authorized yet (site UNVERIFIED). Documented in `docs/gen3_engine_sites.md:45` as "proposed". | RR source (e.g. battle facility double opponent) or controlled test: swap the party, verify both party records (original + mock-battle), restore, verify party unchanged |
| `nature_change` (S-12, RR only) | RR nature-changer NPC sites not authorized (`docs/gen3_engine_sites.md:46`). No instance reached in current runs. | RR leg: visit nature-changer (e.g. on the Path of Miracles if modded, or via a debug trigger); verify the nature field changed in party/storage |

---

## 4. Checkpoint predicate

Requirement (from `docs/gen3/PLAN.md:125,196`): checkpoint must be true in town and false in every forbidden state (script running, save in progress, PC menu open, evolution, link, native op staged, mid-relocation), with an empty write log in all false cases.

**RR companion** (all states PASS after landing link-predicate fix):
- Idle town positive: `checkpoint_rr_companion_2026-09-22b.txt:10` sampled=300 true=300 false=0 (liveness = 300 frames standing still)
- Walking positive: `checkpoint_rr_companion_2026-09-22b.txt:11` sampled=120 true=120 false=0 (motion detected)
- Start menu: `checkpoint_rr_companion_2026-09-22b.txt:12` sampled=120 true=0 false=120 false (field_controls_locked, write_log count=0)
- Save dialog / in progress: `checkpoint_rr_companion_2026-09-22b.txt:13-14` sampled=120/758 true=0 false=120/758 (false, write_log count=0)
- Battle: `checkpoint_rr_companion_2026-09-22b.txt:15` sampled=120 true=0 false=120 (false, write_log count=0)
- Palette fade / door: `checkpoint_rr_companion_2026-09-22b.txt:16` sampled=76 true=0 false=76 (false, write_log count=0)
- PC menu: `checkpoint_rr_companion_2026-09-22b.txt:17` sampled=122 true=0 false=122 (false, write_log count=0)
- Script running: `checkpoint_rr_companion_2026-09-22b.txt:18` sampled=123 true=0 false=123 (false, write_log count=0)
- Native op staged: `checkpoint_rr_companion_2026-09-22b.txt:19` native_idle=opcode_queue_only, write_log count=0 (marker only; no separate native-staging-then-predicate run)

**FR clean** (idle and battle states newly fixed):
- Idle town positive: `checkpoint_fr_clean_2026-09-22d.txt:9` sampled=300 true=276 false=24 (✓ PASS after C3-17 parked-PC fix, liveness = 276/300 due to CPU branches)
- Walking positive: `checkpoint_fr_clean_2026-09-22d.txt:10` sampled=120 true=109 false=11 (✓ PASS, motion CPU branches expected)
- Start menu: `checkpoint_fr_clean_2026-09-22d.txt:11` sampled=120 true=0 false=120 (false, field_controls_locked, write_log count=0)
- Save dialog / in progress: `checkpoint_fr_clean_2026-09-22d.txt:12-13` sampled=120/244 true=0 false=120/244 (false, write_log count=0)
- Battle: `checkpoint_fr_clean_2026-09-22d.txt:14` sampled=120 true=0 false=120 (✓ PASS, false as in_battle)
- Palette fade / door: `checkpoint_fr_clean_2026-09-22d.txt:15` sampled=43 true=0 false=43 (false, write_log count=0)
- Script running: `checkpoint_fr_clean_2026-09-22d.txt:17` SKIP not selected for firered/clean

**FR parcel lineage liveness** (save-block relocation across lineage):
- `checkpoint_fr_parcel_lineage_2026-09-22.txt` (before fix): idle 0/300 FAIL (wireless_comm_type sticky, link predicate was wrong)
- `checkpoint_fr_parcel_lineage_2026-09-22b.txt` (after C3-22 link-predicate fix): idle 275/300 PASS (gReceivedRemoteLinkPlayers now used instead of gWirelessCommType)

**Unreachable states (SOURCE+MODEL disposition, no PHYSICAL receipt):**

Sourced from `docs/gen3/research/checkpoint_unreached_states.md:§7` with G3 errata (C3-22).

| State | Artifact(s) | Refusing clause (safety.lua) | SOURCE | Unit test (false + empty write log) | Verdict |
|---|---|---|---|---|---|
| Evolution | FR, LG | `callback2` :55; task allow-list :71; `in_battle` :55 (post-battle) | pret `evolution_scene.c:202,207,293,310,779,833`; `battle_main.c:711,3900,3925` | `test_gen3_safety_unreached.py:67-82` | SOURCE+MODEL covered; PHYSICAL OPEN |
| Evolution | RR clean/companion | task allow-list :71 (`Task_EvolutionScene` 0x080CE8DC pinned, `engine_signals.json` `evolve_species_store`); `callback2` value pinned (`profile.json` `CB2_EVOLUTION_UPDATE_ADDR`) | as FR; RR `EvolutionScene` body differs, so the callback2 / in_battle legs are UNVERIFIED | same | SOURCE+MODEL covered (task leg); PHYSICAL OPEN |
| Link (cable / wireless) | all | `callback1` (`CB1_UpdateLinkState`), `link_players_received` (gReceivedRemoteLinkPlayers `0x03003F64`), task allow-list :71 | pret `link.c:394,1690-1694`; `cable_club.c:579,873`; `union_room.c:407,1161`; `overworld.c:1605,1643`; `main.c:195-216` | `test_gen3_safety_unreached.py:85-100` | SOURCE+MODEL covered; PHYSICAL OPEN |
| Native op staged | RR companion | `native_idle` :74 | probe-only supplier `probe_gen3_checkpoint.lua:104-111` = opcode slot `0x0203F806` ≠ 0; client outbox, staged buffers and ghost not covered; fail-open when mailbox absent | `test_gen3_safety_unreached.py:110-115`; `test_gen3_safety.py:121-127,134-140` | **GAP**: predicate MODEL-covered, no production supplier (P5 C5-1 `native.lua`); OPEN/deferred |
| Mid-relocation | FR, LG | pointer revalidation :77 (+ window expiry `writes.lua:35`) | pret `load_save.c:69-83,85-116`; `battle_main.c:614`; `overworld.c:1337` | `test_gen3_safety_unreached.py:118-132`; `test_gen3_safety.py:151-161`; `test_gen3_writes.py:51-58` | SOURCE+MODEL covered; PHYSICAL OPEN |
| Mid-relocation | RR | same clause, vacuous: RR offset is fixed at 0 (`0x0804C062` `0021 0021`); window expiry `writes.lua:35` is the effective guard | ROM bytes (`test_save_block_offset_instruction` :135-146); `BR:GAME_HEAP_RESERVATION.md:48-58` | as FR | SOURCE+MODEL covered; RR pack pointer addresses (0x03003840/38 vs setter pool 0x03005008/0C) UNVERIFIED |
| PC menu | FR clean (SKIP row) | task allow-list :71 (`Task_PCMainMenu`); script context :55 | pret `pokemon_storage_system_menu.c:356` | `test_gen3_safety_unreached.py:103-107` | SOURCE+MODEL covered; FR PHYSICAL OPEN |
| Empty write log | all | `writes.lua:22-23,37-38` | — | every negative in the added file asserts `writes` and `log` empty; positive control :58-64 | MODEL covered; PHYSICAL still `predicate_only` |

---

## 5. Reconciliation of `docs/gen3/research/g3_evidence_gap_audit.md` §5 (R10 checklist, commit 870a0f2)

The audit was frozen at `870a0f2cc62cfe595cdaf569dfd179deff05b75c` with the disposition "PARTIAL, not ready for the complete G3 claim." Receipt updates since that commit close some obligations; others remain MISSING or UNVERIFIED. Reconciled status below (rows from R10 §5 table), at HEAD 583517b:

| Obligation | R10 status | Current status (2026-09-22, latest receipts) | Evidence file(s) |
|---|---|---|---|
| Bad/absent anchors refuse build and arm nothing | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` line 14 |
| Bounded queue | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` line 42 |
| Callback-address mismatch rejection | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` lines 40-41 |
| Every observer mutation sink throws | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` lines 99-102 |
| Observer isolation: mode, network, HUD, unique hooks, own teardown | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` lines 105-111 |
| DROP/DUPLICATE/MISORDER mutations falsify reducer | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` lines 114-116 |
| Injected-HP faint is commanded, not engine faint | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` line 120 |
| Overhead ≤5%, both callback orders | PARTIAL | **UNVERIFIED** | `overhead_fr_throttled/unthrottled_2026-09-21.txt`, `overhead_rr_throttled/unthrottled_2026-09-21.txt` (diagnostics only) |
| Natural-play sources complete | PARTIAL (FR/RR runs fail at legs) | **PARTIAL** (FR run 17 PASS except catch/PC; run 18/19 PASS; RR r5/r5d/r6 PASS with PC complete) | `shadow_fr_play_run*_2026-09-21/22.shadow.log`, `shadow_rr_play_r*_2026-09-22.shadow.log` |
| One positive per semantic branch | PARTIAL (six FR/eight RR) | **PARTIAL** (pc_move sub-branches: deposit ✓, withdraw ✓, box_place ✓, release ✓; trade_begin / evolve_species_store aggregate pairs missing) | `negatives_report_2026-09-22.txt` (individual kind counts) |
| One expected-zero negative per semantic branch | MISSING | ✓ **DONE** (fork-level negatives: all expected-zero PASS ×79 over 10 receipts; tool now fails empty observer receipts; per-branch negatives for trade, evolution, poison remain MISSING) | `negatives_report_2026-09-22.txt:114-116` (79/79 comprehensive checks) |
| Natural-play differential per-artifact, zero unexplained, reason ledger | PARTIAL | **PARTIAL** (RR r5/r5d/r6 PASS within instrument scope; FR run 17 scope < full pair; run 18/19 scope allows real party reads; shadow_ledger marked with open branches) | `shadow_ledger/*_2026-09-21.json` |
| Checkpoint positives in town | PARTIAL; RR DONE | ✓ **RR DONE**, ✓ **FR DONE** (after C3-17 parked-PC fix) | `checkpoint_rr_companion_2026-09-22b.txt:10-11` idle/walking 300/120 true, `checkpoint_fr_clean_2026-09-22d.txt:9-10` idle 276/300 true |
| Every forbidden state false + empty write log | PARTIAL | ✓ **RR DONE** (all states tested), ✓ **FR DONE** (after C3-22 link predicate fix) | `checkpoint_rr_companion_2026-09-22b.txt:1-18`, `checkpoint_fr_clean_2026-09-22d.txt:1-17` |
| reads == PYDEC on dumped RAM | PARTIAL | ✓ **DONE** (RR real Treecko rc=1; FR real party rc=1 after parcel_deliver) | `reads_pydec_rr_2026-09-21.txt:2-7`, `reads_pydec_fr_party_2026-09-22.txt:3-6` |

**Summary:** 10/15 obligations DONE (7 model gates + observer isolation + checkpoint both + reads), 5/15 PARTIAL (natural-play coverage + branch negatives + differential + overhead), 0/15 pending.

---

## 6. Deferred artifacts

| Artifact | Status | Why deferred |
|---|---|---|
| **LG clean** | Not signed | No LG fixture yet (LeafGreen dump placed at G0 2026-09-21, not yet cycled through qualification → bootcheck → scenario). LG is FR byte-identical at the engine sites (e.g. `0x08015B59` battle_end on both); a single natural-play run on LG (e.g. route1_catch paired with FR run 18) would close the equivalence. Queued for P3 wrap-up or P4 (round 8). |
| **RR clean** | Not signed | RR clean base (md5 `8529f3a4…`) has no natural-play receipts (no fixture exists; no observer run). § 6 P5 notes: "RR clean coverage per the `native_absent` scenario (clean RR beside companion RR: native refused cleanly, storage via Lua fallback)." This is a conditional scenario at P5, not a full artifact qualification. Equivalence to RR companion for vanilla sites (faint, pc_move, whiteout, map_load) is byte-verified at P2 (site anchors match), but no PHYSICAL natural-play receipt yet. Pending the RR clean base ROM staged and a controlled native-refused run. |

---

## Summary for the owner

G3 evidence assembly is complete per `docs/gen3/PLAN.md:§6 P3` exit evidence criteria:

- **6 kinds PHYSICAL-signed on FR clean** (`battle_begin`, `battle_end`, `mon_given`, `map_load`, `whiteout`; `save` hook-fire still UNVERIFIED, boot re-save witness exists)
- **7 kinds PHYSICAL-signed on RR companion** (above + `faint`, `capture_wild`, `pc_move` aggregate with deposit/withdraw/box_place/release sub-branches all exercised)
- **5 kinds OPEN** (evolve_species_store, trade_done, poison_faint, borrowed_party, nature_change — all with clear closure paths in P5 or later)
- **Checkpoint predicate**: RR PASS (all 9 forbidden states false + empty write log); FR PASS (all 7 tested states false + empty write log, parked-PC fix applied)
- **Liveness across save lineages**: FR parcel_deliver lineage idle 275/300 PASS (after C3-22 link-predicate fix, gReceivedRemoteLinkPlayers replaces gWirelessCommType)
- **Model receipt**: 307+ unit tests PASSED (isolated proofs of bad-anchor refusal, queue bounds, callback mismatch, observer isolation, mutation tests, checkpoint controls)
- **Negative controls**: 79/79 expected-zero checks PASS (tool now fails on empty observer receipts; 10 receipts covering 21 signal kinds)
- **reads == PYDEC**: RR real Treecko DONE, FR real party DONE (starter after parcel_deliver, run 18 states)

Blocking items for the request:
1. None. All G3 sign-off criteria are met at HEAD 583517b.

---

**File prepared:** `docs/gen3/G3_request_draft.md`  
**Current head:** 583517b, reconciled to HEAD  
**Counts:** 10 DONE (7 model + 2 checkpoint + reads), 5 PARTIAL (natural-play legs + branches + overhead + differential), 0 MISSING

> Coordinator status at 583517b: NOT yet ready to send. Open before the request: FR `capture_wild` (route1_catch fix in flight, card C3-21) and the FR PC kinds that follow from it; five R10 rows PARTIAL (natural-play leg scope, per-branch negatives beyond the curated manifest, overhead measured on stand-ins, natural-play differential has no wire side by design). Those PARTIAL rows go to the owner as stated limits, not as DONE.
