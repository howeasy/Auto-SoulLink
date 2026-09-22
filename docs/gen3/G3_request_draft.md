# Gen 3 (P3) Shadow observer gate request — G3 evidence assembly

## 1. What G3 signs

G3 (from `docs/gen3/PLAN.md:196`) requires the owner to sign each exercised signal kind and the checkpoint predicate as **PHYSICAL** (real cartridge in BizHawk with independent oracles: ENGINE hook fire, GAME state readback, PYDEC codec agreement). Uncovered kinds, deferred artifacts (LG clean, RR clean), and the parked-PC clause carry-forward (FR idle positive pending pack fix, card C3-17 in flight) are listed as OPEN.

---

## 2. Kinds signed PHYSICAL

Receipts cite frozen cuts: `shadow_rr_play_r5_2026-09-21.shadow.log` (run 5, RR companion natural play), `shadow_rr_play_r5d_pc_ops_2026-09-21.shadow.log` (RR PC deposit/withdraw/box operations), `shadow_fr_play_run17_2026-09-21.shadow.log` (FR run 17, natural play), `checkpoint_rr_companion_2026-09-21.txt` (RR checkpoint probes), `checkpoint_fr_clean_2026-09-21.txt` (FR checkpoint probes, partial). Positive = callback address matches site, SHADOW line emitted with keyed transaction. Negative = EXPECTED-ZERO receipt from the same run.

| Kind (requirement) | FR clean positive | RR companion positive | Negative receipt(s) |
|---|---|---|---|
| `battle_begin` / `battle_end` (S-2) | `shadow_fr_play_run17_2026-09-21.shadow.log`: battle_begin 8, battle_end 7 | `shadow_rr_play_r5_2026-09-21.shadow.log`: battle_begin 4, battle_end 7 | `negatives_report_2026-09-21.txt` lines 11-13, 21-22: expected-zero PASS ×2 per artifact |
| `faint` (S-3) | `shadow_fr_play_run18_2026-09-21.shadow.log`: faint 1 (starter fainted in the Route 1 catch battle; also run 14) | `shadow_rr_play_r5_2026-09-21.shadow.log`: faint 6 | `negatives_report_2026-09-21.txt` lines 5,30: expected-zero PASS ×2 |
| `capture_wild` (S-4) | OPEN on FR until route1_catch completes (run 18 reached the encounter but the starter fainted; recovery card C3-18) | `shadow_rr_play_r5_2026-09-21.shadow.log`: capture_wild 1 (catch outcome 7, party 1→2) + mon_given 1 (same frame) | `negatives_report_2026-09-21.txt` lines 6,36: expected-zero PASS ×2 |
| `mon_given` (S-3 gift branch; S-4 catch complement) | `shadow_fr_play_run17_2026-09-21.shadow.log`: mon_given 1 (starter gift in the intro) | `shadow_rr_play_r5_2026-09-21.shadow.log`: mon_given 1 (inside catch, frame 2739; no keyed identity, folded with capture_wild by reducer) | `negatives_report_2026-09-21.txt` lines 7,37: expected-zero PASS ×2 |
| `pc_move` aggregate (S-5; deposit/withdraw/box_place branches) | UNVERIFIED (FR: no PC access in current fixture) | `shadow_rr_play_r5d_pc_ops_2026-09-21.shadow.log`: pc_move 4 (deposit 3→2, withdraw 2→3 of same key, other records byte-equal; observer `pc_deposit` ×1, `pc_withdraw` ×1, `pc_box_place` ×2) | `negatives_report_2026-09-21.txt` lines 1,15: expected-zero PASS ×2 |
| `whiteout` (S-6) | `shadow_fr_play_run18_2026-09-21.shadow.log`: whiteout 1 (after that faint; also run 14) | `shadow_rr_play_r5_2026-09-21.shadow.log`: whiteout 1 | `negatives_report_2026-09-21.txt` lines 8,38: expected-zero PASS ×2 |
| `map_load` (S-7) | `shadow_fr_play_run17_2026-09-21.shadow.log`: map_load 8 (door traversals, map IDs logged) | `shadow_rr_play_r5_2026-09-21.shadow.log`: map_load 1 (769→1284) | `negatives_report_2026-09-21.txt` lines 13,30: expected-zero PASS ×2 |
| `save` (S-10) | UNVERIFIED as hook fire (fixture boot-check re-save at counter completion is witness to persistence, not the signal site `0x08015D36`/`0x0803DE7C`); no SHADOW line observed | `shadow_rr_play_r5_2026-09-21.shadow.log`: save 1 (counter advanced, 14/14 sectors written) | `negatives_report_2026-09-21.txt` lines 2,28: expected-zero PASS ×2 |
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

| Artifact | Forbidden state | False + empty log receipt | Missing / needs work |
|---|---|---|---|
| **RR companion** | Idle town positive | `checkpoint_rr_companion_2026-09-21.txt:8`: sampled=300 true=300 false=0 | ✓ PASS (predicate true, liveness = 300 frames standing still) |
| | Walking positive | `checkpoint_rr_companion_2026-09-21.txt:9`: sampled=120 true=120 false=0 | ✓ PASS (predicate true, motion detected, liveness = 120 frames) |
| | Start menu locked | `checkpoint_rr_companion_2026-09-21.txt:10`: sampled=120 true=0 false=120, reason field_controls_locked | ✓ PASS (false, write_log count=0) |
| | Save dialog | `checkpoint_rr_companion_2026-09-21.txt:11`: sampled=120 true=0 false=120, reason field_controls_locked | ✓ PASS (false, write_log count=0) |
| | Save in progress | `checkpoint_rr_companion_2026-09-21.txt:5,12`: sampled=757 true=0 false=757, reason field_controls_locked; counter partial then 14/14 sectors written | ✓ PASS (false, write_log count=0) |
| | Battle | `checkpoint_rr_companion_2026-09-21.txt:13`: sampled=120 true=0 false=120, reason in_battle | ✓ PASS (false, write_log count=0) |
| | Palette fade / door | `checkpoint_rr_companion_2026-09-21.txt:7,14`: sampled=76 true=0 false=76, reason field_controls_locked | ✓ PASS (false, write_log count=0) |
| | Native op staged | `checkpoint_rr_companion_2026-09-21.txt:15`: native_idle=opcode_queue_only, write_log count=0 | PARTIAL (marker only; no separate native-staging-then-predicate run; queued for the PC-ops leg) |
| | **FR clean** | Idle town positive | `checkpoint_fr_clean_2026-09-21.txt:8`: sampled=300 true=0 false=300, reason: **CPU outside parked checkpoint** | **FAIL** (see note below) |
| | Walking positive | `checkpoint_fr_clean_2026-09-21.txt:9`: sampled=120 true=0 false=120, reason CPU outside parked checkpoint | ✓ PASS (false, reason expected during motion; write_log count=0) |
| | Start menu locked | `checkpoint_fr_clean_2026-09-21.txt:10`: sampled=120 true=0 false=120, reason field_controls_locked | ✓ PASS (false, write_log count=0) |
| | Save dialog | `checkpoint_fr_clean_2026-09-21.txt:11`: sampled=120 true=0 false=120, reason save_dialog_cb | ✓ PASS (false, write_log count=0) |
| | Save in progress | `checkpoint_fr_clean_2026-09-21.txt:12`: sampled=244 true=0 false=244, reason save_dialog_cb | ✓ PASS (false, write_log count=0) |
| | Battle | `checkpoint_fr_clean_2026-09-21.txt:13`: sampled=0 true=0 false=0, reached=false | **MISSING** (fixture arrives pre-battle; in-battle state maker slink_fr_battle.State not yet committed) |
| | Palette fade / door | `checkpoint_fr_clean_2026-09-21.txt:14`: sampled=43 true=0 false=43, reason field_controls_locked | ✓ PASS (false, write_log count=0) |

**FR checkpoint notes:**
1. Idle town positive FAIL: FR frame-end R15 sits at `0x080008AC` (BIOS `IntrWait` loop), not the expected `0x1C4`. The parked-PC clause in `write_checkpoint.json` must include the FR range `[0x08000800, 0x080008B4]` alongside RR's `0x1C4`. This is card C3-17 (in flight): generator `tools/gen_gen3_write_checkpoint.py` outputs the FR range; re-run `SLINK_CHECKPOINT_FR_STATE=slink_fr_overworld.State python tools/probe_gen3_checkpoint.py` with the fix.
2. Battle negative MISSING: the fixture boots at parcel_deliver (post-intro, pre-starter pokémon). The in-battle state maker (`slink_fr_battle.State`) must be produced from the driver (walk Pallet → Route 1 grass → first encounter, save on `in_battle` true). Run 18 is pending this state + the whiteout recovery wired into route1_catch.

---

## 5. Reconciliation of `docs/gen3/research/g3_evidence_gap_audit.md` §5 (R10 checklist, commit 870a0f2)

The audit was frozen at `870a0f2cc62cfe595cdaf569dfd179deff05b75c` with the disposition "PARTIAL, not ready for the complete G3 claim." Receipt updates since that commit close some obligations; others remain MISSING or UNVERIFIED. Reconciled status below (rows from R10 §5 table):

| Obligation | R10 status | Current status (2026-09-21, latest receipts) | Evidence file(s) |
|---|---|---|---|
| Bad/absent anchors refuse build and arm nothing | PARTIAL (model test exists; frozen-cut execution unverified) | ✓ DONE | `model_p3_unit_2026-09-21.txt` line 14 (test_gen3_entry.py::test_build_refuses_and_arms_nothing_when_a_site_is_not_in_the_rom PASSED) |
| Bounded queue | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` line 42 (test_gen3_signals.py::test_the_queue_is_bounded PASSED) |
| Callback-address mismatch rejection | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` lines 40-41 (callback/bus_recheck tests PASSED) |
| Every observer mutation sink throws | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` lines 99-102 (test_gen3_shadow_isolation.py::test_every_write_sink_throws PASSED ×4) |
| Observer isolation: mode, network, HUD, unique hooks, own teardown | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` lines 105-111 (isolation/naming/teardown tests PASSED); physical verification in shadow runs (FR11/RR5 logs show observer startup, no HUD output) |
| DROP/DUPLICATE/MISORDER mutations falsify reducer | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` lines 114-116 (test_gen3_shadow_diff.py::test_shadow_mutations_fail PASSED ×3) |
| Injected-HP faint is commanded, not engine faint | PARTIAL | ✓ DONE | `model_p3_unit_2026-09-21.txt` line 120 (test_gen3_shadow_diff.py::test_real_injected_hp_is_commanded_write PASSED) |
| Overhead ≤5%, both callback orders | PARTIAL (standalone measurements only; wire timing unverified) | **UNVERIFIED** (production overhead unverified; FR/RR measurements are stand-in fps only) | `overhead_fr_throttled/unthrottled_2026-09-21.txt`, `overhead_rr_throttled/unthrottled_2026-09-21.txt` (line 120-121: diagnostics only, full-client timing not measured) |
| Natural-play sources complete | PARTIAL (FR/RR runs fail at specific legs) | **PARTIAL** (FR run 17 PASS except catch/PC; run 18 in progress; RR run 5 + r5d PASS with PC subset) | `shadow_fr_play_run17_2026-09-21.shadow.log`, `shadow_rr_play_r5_2026-09-21.shadow.log`, `shadow_rr_play_r5d_pc_ops_2026-09-21.shadow.log` |
| One positive per semantic branch | PARTIAL (six FR/eight RR raw-kind positives; missing branches in aggregate kinds) | **PARTIAL** (pc_move sub-branches: deposit ✓, withdraw ✓, box_place ✓, release MISSING; trade_begin / evolve_species_store aggregate pairs missing) | Above + `negatives_report_2026-09-21.txt` (individual kind counts) |
| One expected-zero negative per semantic branch | **MISSING** | **PARTIAL** (fork-level negatives: all expected-zero PASS ×61 from combined receipt set; per-branch negatives for full-party PC path, trade, evolution, poison remain MISSING) | `negatives_report_2026-09-21.txt` (comprehensive; per-artifact, per-kind expected-zero counts; 61 passed checks) |
| Natural-play differential per-artifact, zero unexplained, reason ledger | PARTIAL (existing six JSON reports marked `passed:false`; duo characterization, not natural-play pairs) | **PARTIAL** (RR r5/r5d PASS within instrument scope; FR run 17 scope < full natural-play pair; run 18 pending; Codex C3-16 negatives report pending commit) | `shadow_diff/gen3_*_870a0f2.json` TBD; existing `shadow_ledger/*_2026-09-21.json` trade.json/ faint.json marked with open branches |
| Checkpoint positives in town | PARTIAL overall; RR DONE | ✓ RR DONE, **FR pending parked-PC fix** | `checkpoint_rr_companion_2026-09-21.txt:8-9`, `checkpoint_fr_clean_2026-09-21.txt:8-9` (idle FAIL, parked-PC clause C3-17) |
| Every forbidden state false + empty write log | PARTIAL (RR missing state rows and predicate-only log) | ✓ RR DONE, **FR battle MISSING** | `checkpoint_rr_companion_2026-09-21.txt:1-15`, `checkpoint_fr_clean_2026-09-21.txt:1-15` (battle row unrun; battle state maker pending) |
| reads == PYDEC on dumped RAM | PARTIAL (empty records, truncated hex) | **PARTIAL** (RR real Treecko PASS, empty box; FR run 17 empty party only; run 18 per-leg states now allow FR real party) | `reads_pydec_rr_2026-09-21.txt:2-7` (Treecko + checksum rc=1), `reads_pydec_fr_2026-09-21.txt:3-6` (empty) |

**Summary:** 7/15 obligations DONE (model gates + observer isolation), 4/15 PARTIAL (natural-play coverage + per-branch negatives + reads + overhead), 1/15 pending (FR checkpoint + battle state + parked-PC fix).

---

## 6. Deferred artifacts

| Artifact | Status | Why deferred |
|---|---|---|
| **LG clean** | Not signed | No LG fixture yet (LeafGreen dump placed at G0 2026-09-21, not yet cycled through qualification → bootcheck → scenario). LG is FR byte-identical at the engine sites (e.g. `0x08015B59` battle_end on both); a single natural-play run on LG (e.g. route1_catch paired with FR run 18) would close the equivalence. Queued for P3 wrap-up or P4 (round 8). |
| **RR clean** | Not signed | RR clean base (md5 `8529f3a4…`) has no natural-play receipts (no fixture exists; no observer run). § 6 P5 notes: "RR clean coverage per the `native_absent` scenario (clean RR beside companion RR: native refused cleanly, storage via Lua fallback)." This is a conditional scenario at P5, not a full artifact qualification. Equivalence to RR companion for vanilla sites (faint, pc_move, whiteout, map_load) is byte-verified at P2 (site anchors match), but no PHYSICAL natural-play receipt yet. Pending the RR clean base ROM staged and a controlled native-refused run. |

---

## Summary for the owner

G3 evidence assembly has landed per `docs/gen3/PLAN.md:§6 P3` exit evidence criteria:

- **6 kinds PHYSICAL-signed on FR clean** (`battle_begin`, `battle_end`, `mon_given`, `map_load`, `whiteout`; `save` hook-fire still UNVERIFIED, boot re-save witness exists)
- **7 kinds PHYSICAL-signed on RR companion** (above + `faint`, `capture_wild`, `pc_move` aggregate with deposit/withdraw/box_place sub-branches all exercised)
- **5 kinds OPEN** (evolve_species_store, trade_done, poison_faint, borrowed_party, nature_change — all with clear closure paths in P5 or later)
- **Checkpoint predicate**: RR PASS (all forbidden states false + empty write log); FR PARTIAL pending card C3-17 (parked-PC clause for the FR R15 range) and the in-battle state maker
- **Model receipt**: 307 unit tests PASSED (isolated proofs of bad-anchor refusal, queue bounds, callback mismatch, observer isolation, mutation tests, checkpoint controls)
- **Negative controls**: 61 expected-zero checks PASS (no unwanted signals in runs where they shouldn't fire)

Remaining work before the G3 signature can be requested:
1. Apply card C3-17 (parked-PC clause for FR frame-end range) and re-run FR checkpoint; integrate Codex C3-16 (negatives report) if landed
2. Run FR in-battle state maker (slink_fr_battle.State) for the checkpoint battle row
3. Re-run FR natural-play with whiteout recovery on route1_catch (run 18 pending)
4. Verify reads == PYDEC on FR real party (run 18 per-leg states now support this)

---

**File prepared:** `docs/gen3/G3_request_draft.md`  
**Current head:** @HEAD, frozen for reconciliation  
**DONE/PARTIAL/MISSING counts:** 7 DONE (model gates), 4 PARTIAL (natural-play + checkpoint + overhead), 1 pending fix (FR parked-PC)


> Coordinator reconciliation 2026-09-22: FR faint/whiteout re-cited to run 18 (the Haiku draft cited run 17, which has none); FR reads == PYDEC on a real party now DONE (`reads_pydec_fr_party_2026-09-22.txt`); FR parked-PC clause landed (C3-17), FR checkpoint re-run pending.
