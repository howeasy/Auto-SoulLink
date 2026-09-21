# G3 evidence gap audit — gen3-P3-R10

Source cut: `870a0f2cc62cfe595cdaf569dfd179deff05b75c`, verified with `git rev-parse HEAD` at audit start and before writing. Task `cx-6855edce`; coordinator Claude; worker Codex. Exclusive output: this file. No Python, emulator, production edits, or commits. Concurrent dirty play-driver files were not used as frozen evidence.

**Cutoff:** all source citations refer to `870a0f2`, retrievable with `git show 870a0f2:<path>`. HEAD advanced during final verification (observed `1ec91f8`, then `47c0b69`); the added FR run17, RR r5d PC-ops, and RR withdrawal-census receipts and updated requirements table are **outside this audit**. A comparison of the named input paths showed those additions and `docs/gen3_requirements.md` changed; the cited reducer, packs, original receipts and tests did not. Reconcile the new receipts separately before using this document as a current-head verdict.

**Disposition: PARTIAL, not ready for the complete G3 claim.** The packet supports callback-presence positives for six FR clean kinds and eight RR companion kinds, as enumerated below. It does not supply the complete natural-play differential, semantic-branch negatives, checkpoint-state matrix, or production overhead evidence required by `docs/gen3/PLAN.md:157-164,196`. An owner may sign explicitly bounded exercised kinds with the rest OPEN under `docs/gen3/PLAN.md:196`; that is not a full artifact qualification.

## 1. Scope, method, and citation key

This is a SOURCE audit of existing PHYSICAL receipts, not a new PHYSICAL run. Searches covered the committed `docs/gen3/probes/*.txt`, `*.shadow.log`, all six `probes/shadow_diff/*.json`, and all six `shadow_ledger/*.json` plus README. PowerShell parsed both engine-signal packs and the JSON reports/ledgers. Searches for SHADOW lines and `NEGATIVE|negative|must.not|must NOT|forbidden|WRITE_LOG|faulty` supplied the bounded absence checks. **UNVERIFIED** means no qualifying receipt located in that packet, not proof the event cannot occur.

Abbreviations below are literal repository paths; `alias:line` is a file:line citation:

| Alias | File |
|---|---|
| FR9 | `docs/gen3/probes/shadow_fr_play_run9_2026-09-21.txt` |
| FR11 | `docs/gen3/probes/shadow_fr_play_run11_2026-09-21.txt` |
| FR14 | `docs/gen3/probes/shadow_fr_play_run14_2026-09-21.txt` |
| FR15 | `docs/gen3/probes/shadow_fr_play_run15_2026-09-21.txt` |
| FRfirst | `docs/gen3/probes/shadow_fr_play_2026-09-21.txt` |
| RRplay | `docs/gen3/probes/shadow_rr_play_2026-09-21.txt` |
| RRfaint | `docs/gen3/probes/shadow_rr_faint_2026-09-21.txt` |
| RR5 | `docs/gen3/probes/shadow_rr_play_r5_2026-09-21.txt` |
| RR5log | `docs/gen3/probes/shadow_rr_play_r5_2026-09-21.shadow.log` |
| PCcensus | `docs/gen3/probes/census_rr_pc_deposit_2026-09-21.txt` |
| CPrr | `docs/gen3/probes/checkpoint_rr_companion_2026-09-21.txt` |
| FRsites | `data/games/gen3_frlg/engine_signals.json` (firered/clean) |
| RRsites | `data/games/gen3_rr/engine_signals.json` (radical_red/companion) |
| Diff | `tools/gen3_shadow_diff.py` |
| Ledger | `docs/gen3/shadow_ledger/README.md` |
| Req | `docs/gen3_requirements.md` |
| PLAN | `docs/gen3/PLAN.md` |
| bootcheck | `docs/gen3/probes/bootcheck_firered_town_2026-09-21.txt` |
| FRthrottled | `docs/gen3/probes/overhead_fr_throttled_2026-09-21.txt` |
| RRthrottled | `docs/gen3/probes/overhead_rr_throttled_2026-09-21.txt` |
| FRunthrottled | `docs/gen3/probes/overhead_fr_unthrottled_2026-09-21.txt` |
| RRunthrottled | `docs/gen3/probes/overhead_rr_unthrottled_2026-09-21.txt` |

Receipt equality means the logged `callback_address` equals the effective JSON site, `address + capture_offset`, not merely the anchor address. That is the producer's registration contract (`lua/gen3/signals.lua:92-114,132-134`). The receipt's `address` already contains that effective address. Callback presence alone does not establish the capture contract's success, side, identity, caller, or completion semantics (`docs/gen3_engine_sites.md:4,17`; Ledger:98-101).

## 2. Kind × artifact positive/negative matrix

**P** = a SHADOW line whose callback equals the effective site, checked against the indicated JSON row. **U** = UNVERIFIED positive. **N-U** = no qualifying *semantic-branch negative* located. All N-U cells use the bounded search above and the negative-control distinction immediately after the table. Decimal numbers are actual logged callback addresses.

| Kind | FR clean positive | FR negative | RR companion positive | RR negative |
|---|---|---|---|---|
| battle_begin | P: FR9:22, `134282652`; FRsites:14-17 | N-U | P: RRplay:22, `134282652`; RRsites:578-581 | N-U |
| battle_end | P: FR11:27, `134306768`; FRsites:42-45 | N-U | P: RRplay:21, `134306768`; RRsites:606-609 | N-U |
| faint | P: FR14:28, `134353864`; FRsites:129-132 | N-U | P: RRfaint:25, `151645906`; player positive-to-zero witness RRfaint:6; RRsites:690-693 | N-U; see obsolete-pin caveat below |
| capture_wild | U: FR15:25-26 ends without the catch; Req:158 still pending | N-U | P: RR5log:40, `151510408`; catch outcome 7 and party 1→2 RR5:17-19; RRsites:635-638 | N-U |
| mon_given | P: FR9:18, `134482826`; starter party=1 FR9:11; FRsites:214-217 | N-U | P: RR5log:39, `151508992`; RRsites:770-773. This is inside the catch, not a separately proven gift branch (RR5:17-19) | N-U |
| pc_move (semantic aggregate) | U: Req:159 pending | N-U | U: Req:159 pending; RR5:27 fails deposit readback | N-U |
| whiteout | P: FR14:29, `134571774`; FRsites:586-589 | N-U | P: RRfaint:27, `134571774`; RRsites:1108-1111 | N-U |
| map_load | P: FRfirst:11, `134571896`; FRsites:186-189 | N-U | P: RR5log:42, `134571896`; map 769→1284 RR5:23; RRsites:742-745 | N-U |
| evolve_species_store | U: Req:162 OPEN | N-U | U: Req:162 OPEN | N-U |
| trade_done | U: Req:163 OPEN | N-U | U: Req:163 OPEN; native-route explanations remain OPEN in `docs/gen3/shadow_ledger/trade.json:3-6,21-24` | N-U |
| save | U for SHADOW: Req:164 cites only `docs/gen3/probes/bootcheck_firered_town_2026-09-21.txt:5-10`, a counter/sector re-save receipt with no callback | N-U | P: RRplay:82, `135111586`; counter/sector witness RRplay:73-77; RRsites:993-996 | N-U |
| poison_faint | U: Req:165 OPEN; source site FRsites:413-416 | N-U | U: no emitted RR poison site; disabled HP-mutation path documented in `docs/gen3_engine_sites.md:15,44,54` | N-U; disabled-source fact is not a live negative |
| borrowed_party | n/a in Req:166; no authorized site (`docs/gen3_engine_sites.md:45`) | n/a | U: Req:166 OPEN; site UNVERIFIED (`docs/gen3_engine_sites.md:45`) | N-U |
| nature_change | n/a in Req:166; no authorized site (`docs/gen3_engine_sites.md:46`) | n/a | U: Req:166 OPEN; site UNVERIFIED (`docs/gen3_engine_sites.md:46`) | N-U |

The physical evidence definition in Req:152 includes a SHADOW line and callback equality. FR15:29-32 contains aggregate counts, not those equality fields; the earlier FR9/FR11/FRfirst lines above supply the missing direct evidence for battle/gift/map. FR14:19 and FR15:26 are failed route verdicts: individual retained positive fires survive, but neither is a completed natural-play gate. Req:154-169 omits a standalone `mon_given` row although Diff:27 requires it, and Req:164 overstates FR save under its own legend.

### What does not count as the missing negative

- The literal `NEGATIVE` at RRplay:85 describes an expected real faint **failing to fire at the old vanilla pin**. It is a false-negative discovery, not a run where the current kind must remain silent. RRfaint:1,25 binds the subsequent positive to the replacement pin.
- `docs/gen3/probes/hooks_fr_clean_2026-09-21.txt:19` and `hooks_rr_companion_2026-09-21.txt:19` register a deliberately unrelated address. They test the callback mechanism, not each semantic branch; the plan likewise scopes these P1 controls as mechanism evidence (`docs/gen3/PLAN.md:111,196`).
- PCcensus:55 reports silent `CB2_ReturnToPokeStorage,Task_WithdrawMon`, but the watched functions are not the current withdrawal completion site. Compare PCcensus:47-55 with RRsites:966-969. It cannot close the `pc_withdraw` negative.
- RR duo silence is bounded evidence for those captures, not an all-branch negative suite: Ledger:29-45 distinguishes commanded/native routes and explicitly leaves trade attribution OPEN. Idle overhead observations are stand-in scoped and leave wire evidence UNVERIFIED (`docs/gen3/probes/overhead_fr_throttled_2026-09-21.txt:120-121`; RR counterpart:120-121). No per-kind armed-window/expected-zero receipt set was found.

### Raw branches hidden by an aggregate pc_move/evolution/trade row

All these branch positives and their negatives remain **UNVERIFIED** in the searched packet; this is narrower than asserting they are unreachable. The listed JSON lines establish the branch to qualify, not PHYSICAL proof (`docs/gen3_engine_sites.md:4`).

| Raw branch | FR clean site citation | RR companion site citation | Existing bounded evidence / gap |
|---|---|---|---|
| pc_deposit | FRsites:271-274 | RRsites:844-847 | PCcensus:54 observes function ENTRY `0x080930E4`; current capture is decimal `134820196` (`0x08093164`). No SHADOW completion or success/identity receipt; RR5:27 fails readback |
| pc_withdraw | FRsites:385-388 | RRsites:966-969 | No completion receipt located; Req:159 pending and RR5:27 stops PC leg |
| pc_box_place | FRsites:243-246 | RRsites:807-820 | No completion receipt located; distinguish origin/box rearrangement, not blanket deposit (FRsites:245) |
| pc_release_begin | FRsites:357-360 | RRsites:938-941 | No pre-removal identity receipt located; Req:159 / RR5:27 |
| pc_release | FRsites:330-333 | RRsites:911-914 | No paired completion receipt located; Req:159 / RR5:27 |
| pc_move (raw SendMonToPC) | FRsites:300-303 | RRsites:873-876 | Distinct full-party acquisition branch, not ordinary deposit; explicitly skipped in RR5:20 |
| trade_begin | FRsites:500-503 | RRsites:1022-1025 | No natural swap-begin receipt located; Req:163 |
| trade_evolve_species_store | FRsites:558-561 | RRsites:1080-1083 | No trade evolution store receipt located; Req:162-163 |
| poison_hp_before | FRsites:442-445 | no emitted RR row (`docs/gen3_engine_sites.md:15,54`) | FR poison pair absent; Req:165 |

`frame_control` is liveness rather than a semantic branch: FR14:21 and RR5log:2-3 have nonzero counts; the observer puts it in STATUS instead of SHADOW (`lua/gen3/shadow_run.lua:291-302`). These counts cannot close any row above.

## 3. Observer / reducer / ledger vocabulary reconciliation

**No unknown emitted-site kind remains at this cut.** Parsed inventory: FR clean has 21 JSON site names (FRsites:13-613); RR companion has 19 (RRsites:577-1135). Their union is the same 21 names: RR omits the two poison sites. Diff:26-38 accepts those names plus the two supplemental research kinds, 23 raw names total. The observer forwards the signal kind and scalar fields and suppresses frame_control lines (`lua/gen3/shadow_run.lua:291-317`). Thus the task's example `pc_deposit` is no longer a parser blocker. The semantic ledger still accepts only KINDS, not raw-only names (Diff:307-344).

| Observer/raw kind not itself a ledger kind | Current differ behavior | Ledger kind to use |
|---|---|---|
| frame_control | dropped, Diff:203-206 | none |
| pc_deposit / pc_withdraw / pc_box_place | pc_move with deposit / withdraw / place, Diff:202,246-253 | pc_move |
| pc_release_begin + pc_release | pair and retain pre-removal key; missing begin/completion diagnostics, Diff:199-245,275-278 | pc_move |
| trade_begin | paired with trade_done; changed-key same-slot support; begin-only diagnostic, Diff:199-242,275-278 | trade_done |
| trade_evolve_species_store | evolve_species_store; complementary fold, Diff:248-269 | evolve_species_store |
| poison_hp_before | pair with poison_faint; HP checks when available, cause=poison; unmatched-begin diagnostic, Diff:199-240,275-278 | faint |

Other important outcomes, all SOURCE deductions rather than an executed reducer result:

1. A genuinely unknown raw name raises `unknown SHADOW kind`, and main emits `passed:false`/error then exits 1 (Diff:282-304,414-423). A raw-only ledger entry fails validation against KINDS (Diff:337-344). Existing ledgers use faint, trade_done, pc_move and mon_given; empty files are `boxsync.json:1`, `ghost.json:1`, `infopanel.json:1`; populated examples are `faint.json:3-6`, `explode.json:3-6`, `trade.json:3-36` under `docs/gen3/shadow_ledger/`.
2. Empty/missing SHADOW key becomes `-` (Diff:299). The actual RR catch emits **both** mon_given and capture_wild at frame 2739 with empty keys (RR5log:39-40). They therefore **do not fold**, because nearby requires a known key (Diff:190-193,259-266). These earn presence counts, but not independent gift proof or a matched keyed wire acquisition. This is the remaining integration gap, not an unknown-kind exception.
3. The comparator requires 12 coverage rows, with borrowed_party/nature_change supplemental (Diff:26-38,354-385). Historical reports retain 14 rows: e.g. `docs/gen3/probes/shadow_diff/trade_rr_2026-09-21.json:2,100-115` is failed and includes those two rows. Ledger:65-101 explicitly supersedes its earlier 14-row statements. Regenerate reports at the frozen code cut; do not silently read their schema as current.
4. Coverage is counted by kind, not artifact or PC action (Diff:351-357). Comparison partitions by sink only (Diff:359-363), and the CLI concatenates files (Diff:405-409). Run artifact reports separately; one pc_move/deposit presence cannot establish withdrawal/release/full-party coverage, and combining FR poison with RR events can hide RR's absent poison row. Req:152-171 requires an artifact distinction the CLI does not enforce.
5. The required poison_faint row has no emitted RR counterpart at this cut (Diff:33,351-357 versus `docs/gen3_engine_sites.md:15,44,54`). An honest RR-only packet cannot make that coverage row nonzero via the admitted sites. This needs an explicit artifact applicability/OPEN disposition, not an invented positive or an explanatory ledger waiver (Diff:380-381; `docs/gen3/PLAN.md:138,196`). Supplemental treatment likewise does not make RR borrowed-party/nature qualification DONE (Req:166).
6. Parsing does not validate callback==site; normalization and comparison use kind/key/action and optional frames (Diff:67-68,282-304,362-370). The receipt table's JSON cross-check is a separate necessary audit. `timing_unavailable` is counted, not a gate failure (Diff:367-381). Zero unexplained deltas alone cannot prove old-client wire timing.

## 4. Checkpoint predicate evidence

The explicit forbidden-state list is script running, save in progress, PC menu open, evolution, link, native op staged, and mid-relocation (`docs/gen3/PLAN.md:125`; Req:93). Every such state must produce false with an empty write log; the gate also needs a positive in town (`docs/gen3/PLAN.md:196`).

| State / obligation | RR companion | FR clean |
|---|---|---|
| Idle town positive | DONE for predicate-only liveness: CPrr:8, 300/300 true | UNVERIFIED predicate result; boot-check field arrival is not safety output (`docs/gen3/probes/bootcheck_firered_town_2026-09-21.txt:4`; Req:167) |
| Walking positive | DONE for sampled motion: CPrr:9, 120/120 true | UNVERIFIED; Req:167 |
| START menu locked | DONE bounded negative: CPrr:10, 120/120 false | UNVERIFIED; Req:167 |
| Save dialog | DONE bounded negative: CPrr:11, 120/120 false | UNVERIFIED; save dialog reached in boot-check:6, but no predicate sample |
| Save in progress | DONE bounded negative: CPrr:5,12, partial counter then 14 sectors; 757/757 false | UNVERIFIED predicate result; boot-check:7-8 has save/sector evidence only |
| Battle | DONE bounded negative: CPrr:6,13, 120/120 false | UNVERIFIED; Req:167 says battle state pending |
| Palette fade / door | DONE bounded negative: CPrr:7,14, 76/76 false | UNVERIFIED; Req:167 says states made, not predicate run |
| Script running | PARTIAL proxy only: CPrr:10-12 establishes field_controls_locked; no separate script-running terminal/count | UNVERIFIED; required by PLAN:125, no corresponding receipt in packet |
| PC menu open | MISSING: CPrr:1-16 has no PC state; PCcensus:47-54 has hooks, not safety output | UNVERIFIED; PLAN:125 / Req:167 |
| Evolution | MISSING: not among CPrr:1-16 samples; PLAN:125 | UNVERIFIED; PLAN:125 / Req:167 |
| Link | MISSING: not among CPrr:1-16 samples; PLAN:125 | UNVERIFIED; PLAN:125 / Req:167 |
| Native operation staged | MISSING: CPrr:15 explicitly says native_idle=opcode_queue_only; no staged-operation negative | UNVERIFIED/not yet dispositioned for this artifact; PLAN:125 |
| Mid-relocation | MISSING: not among CPrr:1-16 samples; PLAN:125 | UNVERIFIED; PLAN:125 / Req:167 |
| Empty write log | PARTIAL: CPrr:15 says count=0, **predicate_only, no_writes_instance=true** | UNVERIFIED; no predicate/write-log receipt |

Consequently Req:220's phrase “every forbidden state false” and the unqualified RR checkmark at Req:167 exceed CPrr:1-16. The receipt proves a read-only predicate returned false in five named contexts; it does not exercise an armed writer refusing a write. For dialog/save/fade the first refusal is field_controls_locked (CPrr:11-14), so these runs also do not independently isolate every internal predicate. An always-false implementation is ruled out for the RR idle/walking contexts by CPrr:8-9, but safe-write completion within a bound remains a separate obligation (`docs/gen3/PLAN.md:138`).

## 5. Exact remaining G3 checklist

Statuses refer to the full stated obligation unless qualified in the row. A proposed closure path below is a **future evidence artifact, not an existing receipt**. The coordinator should keep the claim, source/ROM hash, harness revision, input fixture, and raw logs in each such receipt (`docs/gen3/PLAN.md:138,157-164,196`).

| Obligation / authority | Status | Evidence and what remains | File that would close it |
|---|---|---|---|
| Bad/absent anchors refuse build and arm nothing — PLAN:196 | PARTIAL | Source test exists at `tests/unit/test_gen3_entry.py:279-289`; frozen-cut execution receipt not located in this packet | Proposed `docs/gen3/probes/g3_model_controls_870a0f2.txt`: test selection, no skips, verdict and source pin |
| Bounded queue — PLAN:196 | PARTIAL | `tests/unit/test_gen3_signals.py:90-102` exists; execution unverified here | Same proposed model receipt |
| Callback-address mismatch rejection — PLAN:196 | PARTIAL | `tests/unit/test_gen3_signals.py:67-88` covers mismatch and bus recheck; execution unverified here | Same proposed model receipt |
| Every observer mutation sink throws — PLAN:157,196 | PARTIAL | Tests at `tests/unit/test_gen3_shadow_isolation.py:96-118`; current execution receipt unverified | Same proposed model receipt |
| Observer construction/isolation: observer mode, no network/HUD, unique hooks and own teardown, load after old client — PLAN:157,162 | PARTIAL | Bootstrap/naming/teardown tests exist at `tests/unit/test_gen3_shadow_isolation.py:158-181,223-269`; physical observers are present in FR11:4 and RR5:2, but these receipts alone do not verify every isolation property | Same proposed model receipt plus live isolation/load-order receipt with old-client output/state witnesses |
| DROP/DUPLICATE/MISORDER falsify reducer — PLAN:160,196 | PARTIAL | Parametrized source test `tests/unit/test_gen3_shadow_diff.py:55-69`; run at current normalization revision needed | Same proposed model receipt plus mutation diff outputs |
| Injected-HP faint is commanded, not engine faint — PLAN:160 | PARTIAL | Hash-bound test `tests/unit/test_gen3_shadow_diff.py:104-116`; recaptured scenario remains ledgered faint instead (Ledger:29-30,38; Diff:49-54,145-150). Do not claim filename-based/general attribution | Same model receipt plus exact input hashes and explicit recapture disposition |
| Live faulty observer cannot change old-client state/output — PLAN:157 | MISSING | `tests/unit/test_gen3_shadow_isolation.py:121-137` is fake-memory MODEL; no live faulty-observer receipt located | Proposed `docs/gen3/probes/g3_observer_fault_control_<artifact>.txt` with attempted mutation and unchanged state/wire witnesses |
| Production overhead ≤5%, both callback orders — PLAN:158,196 | PARTIAL | FRthrottled:117-121 and RRthrottled:117-121 say PASS but **standin_only**, wire timing/deltas UNVERIFIED. RRunthrottled:32-36 fails 84.693%/88.582% C/E,D/E; FRunthrottled:71-72 says diagnostics only. Throttled FPS does not close production frame cost | Proposed `docs/gen3/probes/g3_overhead_old_client_<artifact>.txt` with actual client, both orders, agreed measured frame-time definition and raw windows |
| Zero old-client wire deltas/timing regression with observer off/on — PLAN:158 | PARTIAL | `docs/gen3/probes/wire_delta_rr_explode_2026-09-21.txt:1-4` reports zero **semantic** deltas but different tick/ghost counts; no both-order timing comparison or FR wire receipt | Proposed `docs/gen3/probes/g3_wire_off_on_<artifact>.txt` plus bound raw transcripts for both orders and explicit treatment of periodic counts |
| Natural-play sources complete on FR and RR companion — PLAN:161 | PARTIAL | FR15:26 and RR5:27 fail; RR5:20 skips full-party path. Catch/nickname, all PC operations, battle/poison faint, gift, NPC trade, evolution and save must each have a reached source or explicit OPEN disposition | Proposed `docs/gen3/probes/g3_natural_play_<artifact>.txt` plus full `.shadow.log` and wire capture |
| One positive per semantic branch — PLAN:196 | PARTIAL | Six FR/eight RR raw-kind positives in §2; missing branches in the raw-branch table; RR mon_given during catch is not independent gift qualification | Same natural-play receipt plus branch-specific identity/success/readback witnesses |
| One expected-zero negative per semantic branch — PLAN:196 | MISSING | No qualifying per-branch suite located; §2 distinguishes mechanism negatives, failed delivery and unknown native paths | Proposed `docs/gen3/probes/g3_semantic_negatives_<artifact>.txt` with armed hook/window, reached control, zero fires and liveness |
| Natural-play differential, per-artifact coverage, zero unexplained, reason+owner ledger — PLAN:159,196 | PARTIAL | Existing six JSON reports all `passed:false`; e.g. `docs/gen3/probes/shadow_diff/trade_rr_2026-09-21.json:2,100-115,209`. They are duo characterization, not the FR/RR natural-play pairs (Ledger:3,19,29-45). Raw catch keys are empty (RR5log:39-40); current code requires 12 rows, not report's 14 (Diff:33,354-385) | Proposed `docs/gen3/probes/shadow_diff/g3_<artifact>_870a0f2.json` and `docs/gen3/shadow_ledger/g3_<artifact>.json`, with raw input hashes; separate reports per artifact and branch appendix |
| Checkpoint positives in town — PLAN:196 | PARTIAL overall; RR subset DONE | CPrr:8-9 true; FR predicate receipt absent (§4) | Proposed `docs/gen3/probes/checkpoint_fr_clean_<date>.txt`; retain RR receipt's bounded claim |
| Every forbidden state false + empty write log — PLAN:125,196 | PARTIAL | RR missing state rows and predicate-only log; FR entirely unverified (§4) | Proposed `docs/gen3/probes/checkpoint_<artifact>_full_<date>.txt`, every named state and real write-gate log |
| reads == PYDEC on same dumped RAM — PLAN:164,196 | PARTIAL | FR receipt:3-6 is empty party/box, truncated hex; RR receipt:2-7 has one real Treecko, empty box, truncated hex and reported match/mutation rc=1. Good bounded pipeline evidence, not a replayable full payload or populated-box differential | Proposed `docs/gen3/probes/reads_pydec_<artifact>_populated_<date>.txt` plus complete address/length/frame-tagged RAM dumps and decoder output/control receipt |
| Owner G3 signature, exact exercised/OPEN kinds and artifact applicability — PLAN:196 | MISSING | `docs/gen3/PLAN.md:308` G3 row blank. LG/RR clean deferred in Req:171; cannot transfer FR/RR companion receipts without equivalence (PLAN:138). RR poison and supplemental rows need explicit disposition (§3) | Coordinator-owned `docs/gen3/PLAN.md` G3 gate row and `docs/gen3_requirements.md` X.1 with links to the frozen packet |

The `reads_pydec_*` references in the final data row are `docs/gen3/probes/reads_pydec_fr_2026-09-21.txt:3-6` and `docs/gen3/probes/reads_pydec_rr_2026-09-21.txt:2-7`. Their `hex=` strings do not contain the declared nonzero lengths, so full dumped bytes cannot be recovered from these committed summaries. `OK` and mutation `rc=1` are retained receipt assertions, not a re-executed result of this audit.

## 6. Handoff, reuse, and verification

- **Reuse:** retain the §2 callback positives and §4 RR predicate samples at their stated scope. Reuse the existing reducer and shared observer plumbing; this task needs evidence/normalization reconciliation, not a new lifecycle, transport, state, or presentation module. ROM-specific site/applicability facts stay in the game packs (FRsites:13-613; RRsites:577-1135); normalized vocabulary remains in Diff:26-38.
- **First falsifier / outcome:** test the strongest X.1 claims against their cited raw receipts. FR save fails its own callback-equality definition (Req:152,164 versus bootcheck:5-10); RR “every forbidden state” fails the explicit state list (PLAN:125 versus CPrr:1-16). The anticipated unknown-PC-kind claim is disproved by current Diff:34-38,202,246-253.
- **Next action:** coordinator corrects scope labels, records artifact/OPEN dispositions, and assigns missing receipts from §5 in the single emulator lane. Finish natural-play identity and PC branch evidence before generating a purported closing differential (RR5:20,27; RR5log:39-40; Diff:190-193).
- **Independent review:** this document is a worker evidence audit, not an owner signature or an independent review of its author's earlier reducer implementation. A nonauthor should check this document's citations and the final frozen G3 packet; review receipt is UNVERIFIED/pending. Coordinator alone updates the guide/checkpoint/register.
- **Checks performed:** read-only `git rev-parse HEAD`, `git status --short`, `rg` searches, numbered-file reads, PowerShell JSON parsing and site-address arithmetic. No Python, pytest, Ruff, emulator, or live run was attempted for R10. Final whitespace/scope verification is recorded in the inline handoff. Closure tests/runs listed in §5 are required future work, not results claimed here.
