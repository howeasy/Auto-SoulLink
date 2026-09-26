# Gen 3 (P4) FRLG RC cutover gate request — G4 evidence assembly

**Status: G4 is ready for the owner's signature.** The frozen-cut final pass ran at `a2985d5a`
and PASSed all 43 rows (`docs/gen3/probes/fc_SUMMARY_a2985d5a.txt`, §1a) — every item this draft
tracked as REHEARSED (2b's P+H rows, item 3's probe rows, item 4's cold boots, item 5's zip boot)
is now a DONE final-gate row taken on the frozen cut itself. **Nothing is released until G5 is
also signed** (ruling 22, §6 item 22); G5's own frozen-cut RR pass PASSed 19/19 at the same cut
(`docs/gen3/probes/fc_SUMMARY_a2985d5a_rr.txt`, `docs/gen3/G5_request_draft.md`). §2 below is the
per-item state as tracked through the rehearsal passes; §1a has the final-cut table of record. §2 is the current per-item state: items 1, 2, 3 and 4 carry
citable receipts, item 2a is **PASS on both titles** (the 1F write and the 2F
controls on FR-as-A and LG-as-A, both archived; LG 2F at clean cut `10e4a702`), and 2b's nine probe rows are
**DONE live on FR+LG**; what remains open or rehearsal-only is 2b's P+H carriers (mechanism P+H, rulings 15-16/19,
supersedes the old T2/A2 hold plan — A1/A2 plus the new whiteout/trainer rows are wired at `923de234`/`4240248a`/`28e48c9c`,
**REHEARSED**: 8/8 live receipts PASS at `b0483efe`/`28e48c9c`, committed `6d6227c6`, ahead of the code
that now judges the P+H hand-off (`4a91daeb`/`9e227101`/`904c134c`), so they must be re-taken at the
frozen cut — `tools/gen3_final_cut.py`'s §5 item2b rows do this), 4, 5, 7 and 8. **Item 6 is now DONE** (route-differential, ruling 10, receipts
@ `b0483efe`, no regression vs master). §3 is the product defect this cut also has to requalify — the stale-`sSaveDialogCB`
and `gLinkCallback` clauses that held every overworld write after a save or a cancelled link — fixed
in C4-SAVE (`5923c4dd` + `0e7f89e7`), with the harness follow-up C4-6t (`10e4a702`), and **proven live on
both titles** by `save_then_write_gen3` (two saves, a keyed write landing on an idle field, PYDEC PASS;
receipts @ `0c2f384a`); the rows §3.2 still marks owed are the remainder. **All five** scope decisions are settled with
the owner (§6 items 10–14): (a)–(d) as recorded, and (e) — the in-battle lag-frame window — as a **limit for the RC with
no clause added** (`docs/gen3/research/battle_lag_frame_census_design_2026-09-23.md` @ `7f004813`: the only commit that
can straddle a frame end while the tuple reads parked is the action-menu commit, which records the action type alone —
`src/battle_controller_player.c:238` — so the switch target, move and item are chosen later under controllers the permit
refuses; a bench faint there cannot become a switch into the fainted mon, and a forced commit there simply wins, which is
Explode Mode's intended outcome; RR's `battle_commit` is already held at `a1bbc686`).

**Remaining lane work, recomputed 2026-09-23 after the 2b probe rows landed.** The 2b advanced rows are no longer a run
cost — the nine probe rows and `A1` are DONE live on both titles at `f58c8dd5` / `c13cf7c7` — so what is left is:
(a) **4 launches** for the T2/A2 duo carriers once 2B-INTEGRATE-DUO registers them; (b) the **final-cut re-takes** the
runbook enumerates (`docs/gen3/G4_final_cut_runbook.md` @ `23b27065`: item 4's eight cold boots, item 5's pinned zip +
boot, §3.2's rows 1/3/6/9 and the 2a pair, plus the optional item-1/2 regression re-runs the receipt audit calls
sensible); and (c) **item 6's route-differential** (34 invocations as written, or the split ruling's cheaper form).
The draft's last figure (**28–38** without item 6, i.e. **62–72** with it as written) minus the **7 launches now spent** —
the five qualification duos at `c13cf7c7` (rows 1/3/6/9 + `A1`) and the two bw-row probes at `f58c8dd5` — leaves **about
21–31 launches without item 6**; with item 6 as written (34) it would be 55–65, but ruling (a) replaces those with the
route-differential above. The status file's own base figure (**22–29** / **56–63**) predates both adjustments. Excluded
either way:
RNG retries, any rewind-crash loss (§5), and D1–D5/N3/U3 (signed limits under (d)). It rises if the owner opts into the
optional re-runs or changes item 6.

**Update, 2026-09-24 (P+H lands, item 6 closes):** two changes since the count above. First, **item 6 is now DONE** at
zero launches owed — ruling 10 (§6 item 10) split the item, and the route-differential itself ran as the split's cheaper
form (`b0483efe`, item 2 row 6 above); the 34-invocation figure for item 6 "as written" no longer applies. Second,
**mechanism P+H (rulings 15-16, 19) replaces the T2/A2 carrier plan**: the two rows this draft previously counted as
"T2/A2, 4 launches" are now **A1** (`linked_faint_active_gen3`) and **A2** (`active_end_gen3`) under P+H, plus two new
rows (**whiteout**, **trainer**) that did not exist in the 2026-09-23 count. All four are wired
(`923de234`/`4240248a`/`28e48c9c`) and the live run landed **8/8 PASS** on both orientations
(`docs/gen3/probes/ph_*_gen3_{fr,lg}_as_a_{b0483efe,28e48c9c}.txt`, committed `6d6227c6`) — 8 launches,
matching the row-count change (2 old + 2 new, not the prior 2). **These receipts are REHEARSED, not a
final gate row**: `4a91daeb`/`9e227101`/`904c134c` rewrote the hand-off clause they exercise (`safety.lua`
+140 lines, `battle.handoff.head` added to the FRLG pack) after `b0483efe`/`28e48c9c`, so the row must
be re-taken on the frozen final cut (`tools/gen3_final_cut.py`'s §5 item2b rows; audit
`docs/gen3/reviews/F1_G4_AUDIT_2026-09-24.md` @ `40b863bd`, finding H2). Net effect on the **21–31
launches without item 6** figure: subtract item 6 entirely (it is closed, not merely cheaper), and the
T2/A2 component is superseded rather than removed — the 2b P+H component is 0 launches owed pre-final-cut
(8/8 REHEARSED PASS already spent) but is re-run in full by the final-cut pass regardless — the remaining
open-before-final-cut launches are items 4, 5, 7 and 8.

Reconciled against `docs/gen3/G4_status_2026-09-23.md` (Codex REV-g4-draft-1 at `cc807cf3`) and
`docs/gen3/probes/RECEIPT_AUDIT_2026-09-23.md` (Codex REV-receipt-audit-1). Receipts live in
`docs/gen3/probes/`; every commit named below is in `git log --oneline`.

Every claim is tagged **S** (source: a file/commit in this repo), **M** (model: a unit-level suite
or an independent review), or **P** (physical: a receipt from a real cartridge in BizHawk).

---

## 1. What G4 signs

From `docs/gen3/PLAN.md:206` (§6 P4 row: "New client + FRLG cutover", vanilla RC) and §14's P4
row, G4 is the gate at which the **owner runs a live FireRed↔LeafGreen duo from the Run Manager**
— link, faint propagation, dead zone, box sync, save/reload — and signs it. **S**

The gate check the owner sees, per the P4 row's gate-check cell `docs/gen3/PLAN.md:305` (`:297` defines "Gate check" = the receipt set the owner sees): **S**

1. the conformance suite green (67 tests, §4);
2. duo receipts that carry `SAVE_WITNESS_SHA256` **and** a counter delta;
3. the FR and LG coverage rows closed;
4. the extracted release zip booting FR on the new client;
5. the rollback bundle frozen (`docs/gen3/PLAN.md` §9 (`:229-231`): the previous release bundle — old client +
   `SLink-RR.ups` — frozen as an artifact, because a route flag alone is not a rollback once saves
   have been mutated). **S** — the frozen record is `docs/gen3/rollback_bundle.md` (`2cd9f993`);
   it pins master `7957c24c`, the old client's blob shas, and the companion md5 **measured from the
   shipped artifact**: `bf8e94a0…` from applying `patch/dist/SLink-RR.ups` (md5 `84082ec3…`) to the
   clean base `8529f3a4…`. `PLAN.md` §9's `8dcffce7…` (`:231`) and `server/patcher.py`'s master pin are both
   stale against that artifact; the measured apply is the number to freeze. **S**

G4 is a cutover gate, not RC approval and not G5 (the RR cutover, whose patch rebuild is its own
card). **S**

---

## 1a. Status at checkpoint 17 (2026-09-24) and the final cut

Since the last full pass through this draft, four things changed:

- **The old Gen 3 client is deleted.** Its last version is tagged `archive/gen3-old-client`
  (`f9171b9a`) before removal, per ruling 24 (§6). RR now routes to `lua/gen3` like FR/LG. **S**
- **Emerald and Archipelago FireRed are refused by name**, not silently mis-admitted — the old
  client was their only code path and neither is in this release (ruling 24, §6). **S**
- **FR/LG P+H is 8/8 PASS**, not merely built — see item 2b below and ruling 15-16/19 (§6). This
  is REHEARSED evidence (finding H2), re-taken on the frozen cut, not a final gate row yet. **S**/**P**
- **The 2b trainer rows now boot from cached-native trainer fixtures.** This is a harness
  speed-up, not a behaviour change; the trainer row's verdict is unaffected
  (`ph_linked_faint_active_trainer_gen3_{fr,lg}_as_a_2b926be1.txt` @ `248d6ee9`). **UNVERIFIED**:
  the 80 s (FR) / 67 s (LG) figures and the "23-42 min" prior cost are from `248d6ee9`'s own commit
  message, not a timed receipt line — no wall-clock field in the receipts themselves was checked
  against them. **S**

**The final-cut runner (`tools/gen3_final_cut.py`) went through three rehearsal passes before the
frozen cut.** Three rehearsal passes are committed: `docs/gen3/probes/fc_zip_*` / `fc_probe_gates_*` /
`fc_bootcheck_*` @ `6e85ddfc` (zip chain + probe_gates PASS), `fc_bootcheck_*` @ `d0a4bba5`
(cold-boot 8/8 PASS). `fc_release_gate_quick_*` is **not** a clean three-for-three: only
`fc_release_gate_quick_2b926be1.txt` PASSes (`2629 passed, 0 skipped (0 unexplained), 0 failed`);
`fc_release_gate_quick_6e85ddfc.txt` is a **FAIL** (`33 failed, 2571 passed, 3 skipped, 4 errors`)
and `fc_release_gate_quick_d0a4bba5.txt` is also a **FAIL** (`12 failed, 2608 passed`) — both were
taken at HEADs mid-edit by concurrent lane work, not the runner's own defect; neither should be
read as "the gate passed unit at that cut." None of these three is the frozen cut the gate signs:
they rehearse the runner itself at whatever HEAD was current (`6e85ddfc`, `d0a4bba5`, `2b926be1`).

`fc_SUMMARY_157e1ef7.txt` is a **dress rehearsal of the fast-mode path** (`--carry`/`--shard`/
`--merge-summary`), not the pre-cut collection stage `--carry` later reuses — commit `58f5c684`
(after `157e1ef7`) changed `tools/e2e_duo.py` itself (a torn-read fix in `read_result`/
`_read_receipt`/`_reconnect_events`), so none of `157e1ef7`'s duo receipts carry forward to a cut
taken after `58f5c684`; the runner would re-take them. As run, it shows `17/22 PASS`, but 5 of the
7 "FAIL"s are a runner scoring bug, not product failures: `reconnect_gen3_fr_as_a`,
`center_controls_gen3_fr_as_a`, `center_controls_gen3_lg_as_a`, `active_end_gen3_fr_as_a` and
`active_end_gen3_lg_as_a` were marked `FAIL skipped` because the verdict regex matched the
SAVE_WITNESS line's own `saves=0 skipped (no_save)` text as a pytest skip; the receipts themselves
show both halves PASSing. Fixed in `160bd75a` (`\b\d+ skipped\b` now requires a whitespace/comma
lead, not a bare substring match); on the fixed scorer those 5 rows rejudge as PASS, leaving
`22/22` at that dress rehearsal. Not re-run post-fix; the coordinator's real final pass supersedes
it regardless. **S**/**P**

**The coordinator has since frozen a cut and run the real final pass** — the three rehearsals
above are kept as the record of what the runner itself needed fixing before that pass, not as the
gate's own evidence:

- Final cut sha: `a2985d5a` (`a2985d5ad068c1afcaa9ef8eb8ebf402c52c4e28`, committed `622aa7f5`)
- Final-cut result table (`docs/gen3/probes/fc_SUMMARY_a2985d5a.txt`, written 2026-09-25T14:35:06Z, RUN 43 / CARRIED 0 / CACHED 0 / FAIL 0 — **OVERALL: PASS (43/43 rows)**):

| # | row | runbook | verdict | receipt |
|---|---|---|---|---|
| 1 | states_firered_town | §1.1 build | PASS | fc_states_firered_town_a2985d5a.txt |
| 2 | states_firered_battle | §1.1 build | PASS | fc_states_firered_battle_a2985d5a.txt |
| 3 | states_firered_trainer | §1.1 build | PASS | fc_states_firered_trainer_a2985d5a.txt |
| 4 | states_leafgreen_town | §1.1 build | PASS | fc_states_leafgreen_town_a2985d5a.txt |
| 5 | states_leafgreen_battle | §1.1 build | PASS | fc_states_leafgreen_battle_a2985d5a.txt |
| 6 | states_leafgreen_trainer | §1.1 build | PASS | fc_states_leafgreen_trainer_a2985d5a.txt |
| 7 | tutorials_firered | §1.2 build | PASS | fc_tutorials_firered_a2985d5a.txt |
| 8 | tutorials_leafgreen | §1.2 build | PASS | fc_tutorials_leafgreen_a2985d5a.txt |
| 9 | faint_cmd_gen3_fr_as_a | §2-3 item1-2 | PASS | fc_faint_cmd_gen3_fr_as_a_a2985d5a.txt |
| 10 | link_gen3_fr_as_a | §2-3 item1-2 | PASS | fc_link_gen3_fr_as_a_a2985d5a.txt |
| 11 | boxsync_gen3_fr_as_a | §2-3 item1-2 | PASS | fc_boxsync_gen3_fr_as_a_a2985d5a.txt |
| 12 | reconnect_gen3_fr_as_a | §2-3 item1-2 | PASS | fc_reconnect_gen3_fr_as_a_a2985d5a.txt |
| 13 | deadzone_gen3_fr_as_a | §2-3 item1-2 | PASS | fc_deadzone_gen3_fr_as_a_a2985d5a.txt |
| 14 | whiteout_gen3_fr_as_a | §4 item2a | PASS | fc_whiteout_gen3_fr_as_a_a2985d5a.txt |
| 15 | whiteout_gen3_lg_as_a | §4 item2a | PASS | fc_whiteout_gen3_lg_as_a_a2985d5a.txt |
| 16 | center_controls_gen3_fr_as_a | §4 item2a | PASS | fc_center_controls_gen3_fr_as_a_a2985d5a.txt |
| 17 | center_controls_gen3_lg_as_a | §4 item2a | PASS | fc_center_controls_gen3_lg_as_a_a2985d5a.txt |
| 18 | linked_faint_active_gen3_fr_as_a | §5 item2b | PASS | fc_linked_faint_active_gen3_fr_as_a_a2985d5a.txt |
| 19 | linked_faint_active_gen3_lg_as_a | §5 item2b | PASS | fc_linked_faint_active_gen3_lg_as_a_a2985d5a.txt |
| 20 | active_end_gen3_fr_as_a | §5 item2b | PASS | fc_active_end_gen3_fr_as_a_a2985d5a.txt |
| 21 | active_end_gen3_lg_as_a | §5 item2b | PASS | fc_active_end_gen3_lg_as_a_a2985d5a.txt |
| 22 | linked_faint_active_whiteout_gen3_fr_as_a | §5 item2b | PASS | fc_linked_faint_active_whiteout_gen3_fr_as_a_a2985d5a.txt |
| 23 | linked_faint_active_whiteout_gen3_lg_as_a | §5 item2b | PASS | fc_linked_faint_active_whiteout_gen3_lg_as_a_a2985d5a.txt |
| 24 | linked_faint_active_trainer_gen3_fr_as_a | §5 item2b | PASS | fc_linked_faint_active_trainer_gen3_fr_as_a_a2985d5a.txt |
| 25 | linked_faint_active_trainer_gen3_lg_as_a | §5 item2b | PASS | fc_linked_faint_active_trainer_gen3_lg_as_a_a2985d5a.txt |
| 26 | checkpoint_firered | §6 item3 | PASS | fc_checkpoint_firered_a2985d5a.txt |
| 27 | checkpoint_leafgreen | §6 item3 | PASS | fc_checkpoint_leafgreen_a2985d5a.txt |
| 28 | save_then_write_gen3_fr_as_a | §7 save-rows | PASS | fc_save_then_write_gen3_fr_as_a_a2985d5a.txt |
| 29 | save_then_write_gen3_lg_as_a | §7 save-rows | PASS | fc_save_then_write_gen3_lg_as_a_a2985d5a.txt |
| 30 | bootcheck_firered_party_town | §8 item4 | PASS | fc_bootcheck_firered_party_town_a2985d5a.txt |
| 31 | bootcheck_firered_party_town_b | §8 item4 | PASS | fc_bootcheck_firered_party_town_b_a2985d5a.txt |
| 32 | bootcheck_firered_party_battle | §8 item4 | PASS | fc_bootcheck_firered_party_battle_a2985d5a.txt |
| 33 | bootcheck_firered_party_battle_b | §8 item4 | PASS | fc_bootcheck_firered_party_battle_b_a2985d5a.txt |
| 34 | bootcheck_leafgreen_party_town | §8 item4 | PASS | fc_bootcheck_leafgreen_party_town_a2985d5a.txt |
| 35 | bootcheck_leafgreen_party_town_b | §8 item4 | PASS | fc_bootcheck_leafgreen_party_town_b_a2985d5a.txt |
| 36 | bootcheck_leafgreen_party_battle | §8 item4 | PASS | fc_bootcheck_leafgreen_party_battle_a2985d5a.txt |
| 37 | bootcheck_leafgreen_party_battle_b | §8 item4 | PASS | fc_bootcheck_leafgreen_party_battle_b_a2985d5a.txt |
| 38 | zip_build | §9 item5 | PASS | fc_zip_build_a2985d5a.txt |
| 39 | zip_check | §9 item5 | PASS | fc_zip_check_a2985d5a.txt |
| 40 | zip_boot_firered | §9 item5 | PASS | fc_zip_boot_firered_a2985d5a.txt |
| 41 | item6_route_diff | §10 item6 | PASS | fc_item6_route_diff_a2985d5a.txt |
| 42 | release_gate_quick | §11 gate | PASS | fc_release_gate_quick_a2985d5a.txt |
| 43 | probe_gates | §11 gate | PASS | fc_probe_gates_a2985d5a.txt |

`release_gate_quick` (row 42) FAILed on its first attempt in lane 2 — 11 unit failures, all a lane
defect, not a code defect: 21 `.gitattributes`-pinned LF files were still CRLF on disk from before
the `eol=lf` attribute was added (git does not rewrite an unchanged-blob file's line endings on
its own), which fed a stale `pokefirered.sym` provenance hash and CRLF-content assertions in
`test_gen3_profile.py`/`test_gen3_syms_build.py`. Fixed by rewriting the 21 files from their index
blobs and refreshing the index; the lane was tracked-clean at `a2985d5a` before the re-run PASSed
(43/43 above). The FAILing attempt is kept as its own receipt, not discarded:
`docs/gen3/probes/fc_release_gate_quick_a2985d5a_LANE2_CRLF.txt`. **P**/**S** (commit `622aa7f5`)

### Other changes since the previous checkpoint

- **Master merged into the Gen 3 branch**: local master `96ae536d`, via scratch branch
  `claude/gen3-master-sync` (`597c52d2`), merged as `e33b03b1` (G4-MASTER-SYNC) — 9 conflicts
  resolved by intent (`hud.lua`, `server.py`, the Manager's name-limit/game-refusal order,
  `manager.html` radio a11y, `make_release`'s `BIZHAWK_MIN`); `test_protocol_citations` repaired
  (289 citations re-anchored). The merge was independently reviewed and found clean. Two Sonnet reviewers checked every conflicted file
  against both parents: server.py and gen3_frlge.py across 28 commits, then manager.py, manager.html,
  make_release.py, REFERENCE.md and lua/gen1/client.lua across 33 commits. Both reported no dropped or
  garbled hunk (recorded in `docs/gen3_resume.md`, "Merge review"). The OMP attempts (`cx-cd3f4189`,
  `cx-4334eae0`, `cx-c36d9987`) timed out on the diff size and produced no verdict. **S**
- **FR/LG item names fixed after the frozen cut** (`5f050857`, owner: "Just fix it. No re run."): the vanilla item table dropped 15 non-Gen-3 ids and gained the 55 FRLG key items, from pret pokefirered `c75f3523`. It is display-only (board held-item names) and is not covered by the a2985d5a pass; it has unit tests only. **S**
- **HUD: the GBA screen draws notices in the fceux pixel font too** (`f1cc6038`) — Gen 3 now
  matches the Gen 1/2 HUD font instead of BizHawk's default. **S**
- **HUD: held commands never reach the HUD** (`870e5e5d`) — console log only, once per hold; owner
  ruling was no pending counter on the HUD. **S**
- **RR rival-id off-by-one fixed** (`e729abdb`) — `rival_trainer_ids()` matched the trainer
  *before* each rival instead of the rival itself; see §5 of `docs/gen3/G5_request_draft.md` for
  the full fix and its `gTrainers[k+1]` derivation. **S**
- **The in-game panel's Badges row fix** (`17608b51`) — it was popcounting the hello/tick bitmask
  (showing 0/8) after the old client's deletion instead of the badge flags. **S**
- **RR zip boot wired into the final-cut runner** (`58a8951f`, `c0e1e98e`) — the RR plan now
  builds, checks and boots the release zip on the RR companion (`rr_zip_build`, `rr_zip_check`,
  `zip_boot_radicalred`), replacing the earlier TODO row; the rows get their own summary
  (`fc_SUMMARY_<cut8>_rr.txt`). This is what let the frozen-cut RR pass run to 19/19 (§1a above,
  `docs/gen3/G5_request_draft.md`). **S**

---

### Open qualifiers carried into this gate

These are recorded limits, not blockers, and the receipts behind them are cited where they land
(§2, §5):

1. **The RR *test harness* (not a product checkpoint) uses a looser PC-owner-list-exit check than
   FR/LG.** `lua/tests/gen3_scripted_play.lua`'s `owner_list_closed()` reads `gSpecialVar_Result`
   (`sym:231`, `0x020370D0`) to witness the PC owner-list closing; on FR/LG a cancel writes the
   sentinel `SCR_MENU_CANCEL` (127) there and the harness waits for it, but on RR the live PC-exit
   trace reads `result=0` at every step, including right after the cancel
   (`docs/gen3/research/rr_harness_syms_2026-09-24.md` §"gSpecialVar_Result on RR (G5-RR-LAST)").
   The harness therefore falls back to "the list closed and no PC task took over" on RR
   (`owner_list_closed` in `lua/tests/gen3_scripted_play.lua:1954-2001`) instead of the byte-exact
   127 check FR/LG gets. This is a *scripted-play driver* limitation, not a checkpoint predicate or
   a write-safety gate — nothing in `lua/gen3/safety.lua` or either pack's `write_checkpoint.json`
   reads `gSpecialVar_Result`. Carried here because it is an FR/LG-vs-RR asymmetry in how PC-exit is
   proven, even though it costs nothing at G4 (FR/LG use the strict check). Correction
   (OMP cx-72da0fae, verified 2026-09-25): the latch starts sampling only after `G.tap("B")`'s
   3 + 13 frames (`lua/tests/gen3_boot_check.lua:329-331`, `lua/tests/gen3_scripted_play.lua:1998-2002`),
   so "RR overwrites 127 in the same frame" is unproven. On RR the value may simply be gone
   within those 16 frames. OPEN: sample during the tap, or arm a write watchpoint on `0x020370D0`
   before B, then decide whether RR can take the strict check. **S**
2. **An AP build with every pinned anchor intact would be admitted.** This is by design — the
   admission check is anchor-based so a randomizer that reshuffles content but keeps the pinned
   bytes still boots — not a gap found late. Archipelago FRLG is refused today because no
   AP-patched dump exists to test against: **none known** on disk in this worktree (a negative,
   not a receipt); a future AP FRLG dump with intact anchors would pass admission on its own merits
   (ruling 24, §6). **S**
3. **UNVERIFIED — the post-battle stage chip can reportedly read stale for up to 30 frames.** No
   receipt in this tree measures it; it is carried here as a known claim, cosmetic in nature (a
   display value, not a checkpoint predicate or a write gate) but not confirmed by this draft's own
   evidence pass. **S**

---

## 2. Per-item status

Status vocabulary: **DONE** = a citable receipt exists (its cut named); **REHEARSED** = a receipt
exists but must be re-taken on the frozen final cut; **OPEN** = not started or incomplete;
**BLOCKED** = cannot run with current hardware/fixtures.

| Item | Status | Evidence (receipt @ commit; cut) | Still owed |
|---|---|---|---|
| **1** FR↔LG faint on a clean cut | **DONE** | `duo_frlg_faint_cmd_gen3_clean_2026-09-23b.txt` @ `8deddf23`, cut `d199da32`: `faint_cmd_gen3: a=PASS b=PASS` | a re-take by the final-cut pass (`tools/gen3_final_cut.py`'s `§2-3 item1-2` row `faint_cmd_gen3_fr_as_a`), not merely optional: the cut predates P+H's changes to the shared write path (`armed_write`/`writes.lua`); caveat: the receipt proves an *injected-event overworld* faint, not a natural battle faint (audit F1 `40b863bd`, finding M2) **P** |
| **2** the seven FRLG scenarios | **DONE at their cuts** | link + boxsync @ `d074bda2` (cut `d199da32`); reconnect + wrong-save @ `60a9ce18` (cut `fb255a05`, `source=fb255a05`); deadzone + whiteout @ `ac1a5490` (cut `059da756`); `linked_faint_active_gen3` @ `4ec51ed0` (cut `eaa96787`) — `a=PASS b=PASS`, with `SAVE_WITNESS_SHA256 match=true` and counter deltas on each saving side (reconnect's A does not save) | a final frozen-cut re-take of faint/link/boxsync/reconnect, not merely optional regression evidence: `RECEIPT_AUDIT_2026-09-23.md`'s "OPTIONAL" call predates P+H's changes to the shared write path (`armed_write` now sets `args.plan`; `writes:write_plan`; `safety.battle()`'s new clause insertion) — `tools/gen3_final_cut.py`'s §2-3 item1-2 rows treat these as mandatory, and this draft follows the runner (audit F1 `40b863bd`, finding M2) **P** |
| **2a** writes inside a Pokémon Center | **DONE on both titles** | 1F write — `center_receipt_whiteout_fr_as_a_2026-09-23.txt` (FR-as-A) and `center_receipt_whiteout_lg_as_a_2026-09-23.txt` (LG-as-A) @ `5a8064f3`, cut `fb255a05`: `whiteout_gen3: a=PASS b=PASS`, "the write landed in the Center", `CONTROL_LIVE nurse map=5.4 at=(7,4)`, `CONTROL_REFUSED nurse box_mon clause=field_controls_locked attempted=0 writes=0 bytes=unchanged`, witness match + counters, PYDEC PASS. 2F controls — `center_controls_fr_as_a_2026-09-23.txt` (FR-as-A, port 55634) @ `3fefbee7`, cut `f5d92327`: `center_controls_gen3: a=PASS b=PASS`, each control's keyed probe refused with a named clause then released and settled, `PYDEC: PASS asserted scenario facts`; `center_controls_lg_as_a_2026-09-23.txt` (LG-as-A) @ `0c2f384a`, clean cut `10e4a702`, rewind off: `center_controls_gen3: a=PASS b=PASS`, same three controls, witness match `saves=1 counter=4->5`, PYDEC PASS. `5923c4dd` + `0e7f89e7` are ancestors of both cuts, so both halves are post-fix | nothing for the gate row. The Union-Room entry/return row stays the (b) case, unreachable while `IsWirelessAdapterConnected` is observed false **P** |
| **2b** in-battle faint window | **REHEARSED on both titles** — mechanism P+H supersedes the hold on FR+LG (rulings 15-16, 19); A1/A2 rewired, plus the new whiteout/trainer rows, all **8/8 live receipts PASS**, committed at `6d6227c6` (`docs/gen3/research/g4_2b_matrix_plan_2026-09-23.md` @ `082b33a9`) | `checkpoint_{fr,lg}_clean_2b_rows_2026-09-23.txt` @ `f58c8dd5`, lane `fbfae6fa`: **N1, N4, N5, N6, N7, N8, N9, U1, U2** all PASS on both titles, unaffected by P+H (none touches the active-battler window); header caveat unchanged (see prior text). **A1** (`linked_faint_active_gen3`) and **A2** (`active_end_gen3`) no longer assert the old hold — `923de234` moves both carriers to mechanism P+H: the subject parks with its linked lead as battler 0, takes `force_faint`, presses nothing; the carrier reads the engine directly (the 5-line `battle_commit` ending in the hand-off, `PlayerBufferExecCompleted`→`PlayerBufferRunCommand` within 2 frames with exec bit 0 clear, no press and `heldKeysRaw==0` until the KO, PP/`lastUsedMovePlayer` unchanged, no SLink HP write, Perish flag cleared, faint site with `gActiveBattler 0` and `playerFaintCounter+1`). Carrier/oracle model in `4240248a` (chain oracle, red checks); `28e48c9c` makes HANDOFF/ACTIVE_KO print measured values (exec bit, press count, `heldKeysRaw`, HP-write count) instead of fixed text, names watcher errors, and makes the FR-as-A whiteout walk flee incidental battles. Two rows are new alongside A1/A2: **whiteout** (`linked_faint_active_whiteout_gen3`) and **trainer** (`linked_faint_active_trainer_gen3`, route to Rick 102) — R1's L3/L4 fixes and W3 in `28e48c9c` are already folded into these. Review: R1 `docs/gen3/reviews/R1_PH_REVIEW_2026-09-24.md` @ `26c7e281`, ACCEPT-WITH-FIXES (0H/1M/9L); every code finding fixed in `4a91daeb` and `9e227101` (L3/L4 in `28e48c9c`). **The 8 PASS receipts, one per row × orientation, committed `6d6227c6`:** `ph_linked_faint_active_gen3_fr_as_a_b0483efe.txt` (A1 FR), `ph_linked_faint_active_gen3_lg_as_a_b0483efe.txt` (A1 LG), `ph_active_end_gen3_fr_as_a_b0483efe.txt` (A2 FR), `ph_active_end_gen3_lg_as_a_b0483efe.txt` (A2 LG), `ph_linked_faint_active_whiteout_gen3_fr_as_a_28e48c9c.txt` (whiteout FR — PASS is at `28e48c9c`, **not** at `b0483efe`, see the FAIL record below), `ph_linked_faint_active_whiteout_gen3_lg_as_a_b0483efe.txt` (whiteout LG), `ph_linked_faint_active_trainer_gen3_fr_as_a_b0483efe.txt` (trainer FR), `ph_linked_faint_active_trainer_gen3_lg_as_a_28e48c9c.txt` (trainer LG — previously missing from this list, audit F1 `40b863bd` finding L3). **One FAIL record is also committed and must not be cited as a PASS** (finding M6): `ph_linked_faint_active_whiteout_gen3_fr_as_a_b0483efe.txt` — `RESULT_LINE b: RESULT: FAIL (scenario error: table: …)`, an instrument/carrier problem (an incidental wild battle on the post-deposit walk whited B out before the scenario's own assertions ran; the product behaved correctly — B's faint propagated, A got `force_faint`+memorialize+`game_over`), fixed by W2 (flee incidental battles on a one-mon walk) and re-taken PASS at `28e48c9c` | **REHEARSED, not a final gate row** (finding H2): the 8 receipts above predate `4a91daeb`/`9e227101`/`904c134c`, which rewrote the hand-off clause they exercise (`safety.lua` +140 lines: head-row match, mirror canonicalisation, battler-0 assert, Explode+H reshape; `battle.handoff.head` added to the FRLG pack) — a head-row mismatch between `perish_plan` and the pack's `head` would refuse P+H live and none of these 8 receipts would show it, since they were taken before that clause existed. `tools/gen3_final_cut.py`'s `§5 item2b` rows re-take all 8 on the frozen final cut; nothing further is owed before that pass runs. The D1–D5 doubles rows, N3 the target menu and U3 Safari are **signed limits** under ruling (d) in §6, so no invocation is owed for them **S**/**P** |
| **3** FRLG probe rows | **REHEARSED on both titles** — the four C4-PROBE2 rows, and since `f58c8dd5` the full probe with the nine 2b rows (27 PASS + 4 not-selected SKIP per title at `f58c8dd5`; the earlier `03ab26e7` receipts were 18 PASS + 4 SKIP); `battle_link` stays the (b) limit; re-labelled from DONE because the pack and the predicate module changed after `f58c8dd5` (`data/games/gen3_frlg/write_checkpoint.json` gained `battle.handoff.head`; `safety.lua`) — audit F1 `40b863bd`, finding M3 | `docs/gen3/probes/checkpoint_fr_clean_c4probe2_2026-09-23.txt` and `checkpoint_lg_clean_c4probe2_2026-09-23.txt` @ `03ab26e7`, lane `gen3-lane-clean` @ `b0511ff2`: **22 probe rows per title: 18 PASS and 4 SKIP (not selected for the clean artifact: `pc_menu`, `battle_link`, `native_idle_field`, `native_idle_battle`), 0 FAIL**, ending `RESULT: PASS all checkpoint controls` (FR :62, LG :61). New rows there: `battle_input_trainer` (the Route 22 early rival; a trainer battle parked at the action menu, flags `0xC` = TRAINER/IS_MASTER), `battle_faint_prompt` (Tail Whip until the lead faints, then the forced send-out prompt `ctrl == WaitForMonSelection`), LG `script_running` (`slink_script.State`, the woman at Viridian (20,12)) and LG `battle_commit_state3`. **Full probe (item 3 + 2b together):** `checkpoint_{fr,lg}_clean_2b_rows_2026-09-23.txt` @ `f58c8dd5`, lane `fbfae6fa` — **27 rows per title PASS** (31 `PROBE …` lines each, incl. the same four not-selected SKIPs), ending `RESULT: PASS all checkpoint controls`, header `tracked_clean=False` with the coordinator's note (see the 2b row). Code: `6bc722bd` / `a256450e` / `b0511ff2` / `fbfae6fa` / `f58c8dd5` | re-taken by the final-cut pass (`tools/gen3_final_cut.py`'s `§6 item3` rows, via `gen3_probe_receipt.py`), not "nothing owed": the C4-PROBE2 rows stay covered by the full-probe receipts, and REV-PROBE2-SAVEROWS reported — its fixes landed at `b261d045` (rows 1/3/6/9 re-taken there, §3.2) |
| **4** cold-boot admission | **REHEARSED** | `bootcheck_frlg_rehearsal_keys_2026-09-23.txt` @ `3327720c`, lane cut `fb255a05`: **8/8 PASS** (FR and LG × town/battle × a/b) with the PID:OTID key oracle, counters advancing, 14/14 sectors | re-take on the frozen final cut **P** |
| **5** extracted release zip boots FR on the new client | **REHEARSED** | the zip-boot rehearsal and its correction @ `c8f0c804` (which also lands `tools/check_release_zip.py`, the standing hygiene gate: every member's blob equal to its `git show <rev>:<path>`, no dev-only paths, the 23-file FRLG closure present) | rebuild a **pinned** zip from the final cut, run `python tools/check_release_zip.py <zip> --rev <cut>`, boot it, and record the rev beside the artifact **P** |
| **6** Gen 1 / Gen 2 lanes after the `slink.lua` route change | **DONE, route-differential, no regression vs master** | Gen 2 route boot DONE @ `cc807cf3` (`gen2_route_boot_crystal_2026-09-23.txt`); per ruling 10 (§6 item 10), the split route-differential ran paired master-vs-branch (card G4-LANE-1): `docs/gen3/probes/item6_route_diff_master_2026-09-24.txt` (master `a20d4886`) and `item6_route_diff_branch_2026-09-24.txt` (branch `f6d503f4`), both committed @ `b0483efe`. **Case 1** (Gen 1 command-ordering, `3941198c`'s named case): FAIL x2 runs on both sides, identical assertion — unchanged, left to the post-G4 convergence card per ruling 10. **Case 2** (Gen 1 SFX town gate): FAIL on master (case A: stale request-code expectation), **PASS on branch** (`44bf25d6`/`48709f39` already on this branch per ruling 10) — branch strictly better. **Case 3** (legacy Gen 2 duo, faint/boxsync/memorialize): FAIL x2 runs on both sides, identical failure (never boots into the overworld from the battery save) — unchanged. **Load caveat**: both lanes ran on a machine shared with a live Gen 2 session (0-2 concurrent Gen 2 EmuHawk instances, `cpu=82-97%`, `python=11-13` processes per the receipts' `LOAD` lines); each master run was paired back to back with its branch counterpart to control for that. Nothing owed | nothing owed as a gate row — decision (a) is closed by ruling 10 (split): `44bf25d6` is on this branch, `3941198c` and the legacy Gen 2 duo boot failure are deferred to the post-G4 convergence card as unchanged-vs-master limits **S**/**P**
| **7** rollback bundle freeze | **OPEN (definition)** | the frozen record exists: `docs/gen3/rollback_bundle.md` @ `2cd9f993` (cut master `7957c24c`, old-client blob shas, the measured companion md5, the rollback procedure and its checklist) | decision (c): does that SHA + manifest count as the freeze, or must a named archive be built and hashed? **S** |
| **8** owner's own Manager run | **OPEN** | — | two BizHawk instances, the FR↔LG pair, launched from the Manager's run page, exercising link, faint propagation, dead zone, box sync and save/reload by hand. The rows above exist so this run is the confirmation, not the first contact **S** |

What the OPEN rows still need, in lane order (one emulator lane at a time, `PLAN.md:23`/`:297`): the
Union-Room row (2a, a recorded limit); **updated 2026-09-24** — the 2b T2/A2 carrier plan is superseded by mechanism
P+H (rulings 15-16, 19): the nine N/U probe rows are DONE live (`f58c8dd5`) and D1–D5/N3/U3 are signed limits under
(d); **A1/A2 plus the new whiteout/trainer rows under P+H**, wired at `923de234`/`4240248a`/`28e48c9c`, are
**REHEARSED** — 8/8 live receipts PASS, committed `6d6227c6` — and open only in the sense that the final-cut pass
re-takes them on the frozen cut (finding H2); the final boot-check (4)
and the pinned zip (5) are open the same way (REHEARSED); for (2) the frozen-cut re-runs are no longer optional
(finding M2), the reconnect wrong-save
having been re-taken at `fb255a05`. **Item 3 is done twice over** (18 PASS + 4 not-selected SKIP per
title at `03ab26e7`, then the full 27-row probe at `f58c8dd5`), but is likewise **REHEARSED** (finding M3); its independent review
REV-PROBE2-SAVEROWS reported and its fixes landed at `b261d045`. The checkpoint change carries its own
rows, §3.2 — ten, of which rows 1, 3, 6 and 9 are **DONE live on both titles at `b261d045`**
(`c13cf7c7`; earlier passes at `24d6cf6a` and lane `0feb9383`), row 6 closed as its limit form; the
estimate in the header folds in those runs. Estimates live in
`docs/gen3/G4_status_2026-09-23.md`. **S**

---

## 3. The stale-save / link product defect and its fix (C4-SAVE)

Two clauses in the G3-signed checkpoint predicate tested engine pointers the game never clears, so
each held **every** overworld SLink write for the rest of a session:

- **`save_dialog_cb == 0`.** `sSaveDialogCB` is assigned by every save-dialog step
  (`start_menu.c:608-842`) and never reset, so after the player's first save it rests on
  `SaveDialogCB_ReturnSuccess`. Live LG evidence on an idle field:
  `STALE_SAVE_DIALOG save_dialog_cb=0x0806F9E1:SaveDialogCB_ReturnSuccess(no save dialog task)`,
  with 404 holds logged in that run (`0e7f89e7`'s message). **P**
- **`gLinkCallback == 0`.** `gLinkCallback` survives `CloseLink` after a no-partner Cable Club link
  (`link.c:394/419-426`), so writes stayed held after a cancelled link (live FR `center_controls`
  r9, `5923c4dd`). **P**

What landed: `0e7f89e7` (C4-SAVE part 2) drops the `save_dialog_cb` key from
`lua/gen3/safety.lua`'s required list (**one line**) and moves the pointer into a pack `witnesses`
block the checkpoint never evaluates — read by `gen3_boot_check` (`M.pred` falls back to it) and by
the probe's dialog row; a mid-save world is still refused by the named clauses (the START-menu task
allow-list, `field_controls_locked`, `task50_save_game` + script lock + `CONTEXT_WAITING`), while
the finished-save world is admitted. `5923c4dd` (part 1) makes `link_callback` read `sLinkOpen`
(set only by `InitLink` via `OpenLink`'s cable branch; cleared by `CloseLink` including the error
path) and allows `Task_RunPokemonLeagueLightingEffect` on FR/LG (`field_specials.c:2133-2185`,
palettes only; RR is gated on `InitLink`/`OpenLink`/`CloseLink`/`LinkMain2` staying byte-identical).
Both commits touch `data/games/gen3_{frlg,rr}/write_checkpoint.json`; 10 falsifiers were red on the
old packs. **S**

This is a **change to the G3-signed predicate**, so it is re-qualified rather than assumed.
`docs/gen3/research/checkpoint_predicate_audit_2026-09-23.md` carries the independent audit
(read-only headless Codex; pret pin `c75f3523`, SLink `328e5ab8`), the persistent-task census, and
Codex's adversarial review of the fix at `0e7f89e7` (`160c2508`): **runtime fixes RETAINED, no
unsafe write frame found** in any vanilla save or link path — START save (both overwrite/replace
prompts, cancel, success and error text, the unlock-to-destroy interval), Cable Club/script save,
flash-failure recovery, Hall of Fame, `Task_LinkFullSave` and its minigame callers, post-link-battle
and trade incremental saves, Mystery Gift, chat, e-reader, erase-save — and on link, cable callbacks
run only behind `sLinkOpen`, with wireless relying on the other exclusions
(`gReceivedRemoteLinkPlayers` can clear before RFU teardown completes, so it is not a universal
teardown witness). Two things it does **not** close: the probe's dialog row is rejected as a witness
(after an earlier save it can pass on a different START submenu) and is routed to C4-6t together
with the save helper's second-save detection; and RR is not qualified (`HandleSavingData` and
`RunSaveFailedScreen` differ from FR). **S**/**M**

C4-6t landed at `10e4a702`: the probe's dialog row and the save helper now use one START-menu save
witness (`gen3_boot_check.start_menu_witness`: wait for `Task_StartMenuHandleInput` with the menu
callback on `StartCB_HandleInput`, then require *this* A press to move it onto
`StartCB_Save1`/`StartCB_Save2` under the live task — `start_menu.c:376-392` draws the window before
input is read, which is why the old helper's second-save A was dropped); RR keeps a
pointer-must-move fallback. It also forces BizHawk rewind off in every generated run config (§5).
Falsifiers red on the parent. **S**

### 3.1 Physical evidence so far

| Row | State | Receipt |
|---|---|---|
| **A keyed write LANDS after an in-game save, then a second save (FR-as-A and LG-as-A)** | **PASS on both titles.** FR: `WRITE_LANDED box_mon 263620B6:99DE0D8A map=3.1 at=(24,39)` after the first save, second save witnessed, `SAVE_WITNESS_SHA256 match=true saves=2 counter=4->6`. LG: `WRITE_LANDED box_mon F6B6A64D:1C600D89` at the same spot, `match=true saves=2 counter=3->5`. Both on an idle field with every predicate zero (`field_controls_locked=0x0`, `link_callback=0x0`, `script_status=2`), `PYDEC: PASS asserted scenario facts`, attempt 1 of 1, no emulator fault (rewind off). Supersedes the earlier partial LG run (`save_then_write_lg_as_a_partial_2026-09-23.txt` @ `3fefbee7`, whose second save failed in the harness) | `save_then_write_{fr,lg}_as_a_2026-09-23.txt` @ `0c2f384a`, clean cut `10e4a702`; wire goldens `save_then_write_gen3_{a,b}_gen3_new.jsonl` **P** |
| **FR Center controls (2F): welcome message, cable-link wait, Union Room attendant** | **PASS.** Each control's `CONTROL_LIVE` is source-pinned (`adapter_connected=false` observed) and each keyed probe is `CONTROL_REFUSED` with a named clause, then `CONTROL_RELEASED`/`CONTROL_SETTLED` — the cable-link row on the **new** clause (`link_callback=0x1`, i.e. refused while `sLinkOpen` was set, landed after the cancel), the other two on `field_controls_locked` — and `PYDEC: PASS asserted scenario facts` | `center_controls_fr_as_a_2026-09-23.txt` @ `3fefbee7`, cut `f5d92327` **P** |
| **LG-as-A Center controls (same clauses)** | **PASS.** `center_controls_gen3: a=PASS b=PASS` — the cable menu, the cable link wait and the Union Room attendant each held a keyed probe and each landed once released; `adapter_connected=false` observed; witness `match=true saves=1 counter=4->5`; `PYDEC: PASS asserted scenario facts`; post-fix | `center_controls_lg_as_a_2026-09-23.txt` @ `0c2f384a`, clean cut `10e4a702` **P** |

### 3.2 Physical rows still owed for this change

Codex's review lists them; each is marked **runnable** on this machine as the harness stands, or a
**recorded limit** with its reason, so a limit can be signed instead of quietly left open.

| # | Row | Runnable or recorded limit |
|---|---|---|
| 1 | START save: first and repeated saves, both overwrite prompts, cancel, success dismissal | **DONE live on both titles** — first and repeated saves are the §3.1 `saves=2` PASS; the overwrite prompts, cancel and dismissal were implemented as driver steps — **IMPLEMENTED** at `c9e2b695` (`beeea4ff`'s design): a `SAVE_DISMISSAL <tag> by=a_press or timeout delay=N` line read from `sSaveDialogDelay` (`scenario_gen3_save_then_write.lua:44-48`) distinguishes the two dismissals; the different-file prompt is a **recorded limit** — `start_menu.c:731` is an OR, so the fixture's one valid save always takes the same-file overwrite prompt and `gDifferentSaveFile` can never be true here — **live: PASS on both titles**, re-taken after the review fixes at `b261d045` (`c13cf7c7`; first pass at lane `0feb9383`, see the results block below) |
| 2 | START save: error/recovery (flash failure) | **recorded limit** — needs a forced flash failure the harness cannot inject; statically covered by the audit ("the task persists") |
| 3 | script / Cable Club save | **runnable** — `center_controls_gen3`'s own save is the Cable Club's (`EventScript_AskSaveGame`); it needs its own witness row — **IMPLEMENTED** at `c9e2b695` as the `cable_save` control (the runner queues its probe at `CONTROL_LIVE`) — **DONE live on both titles** (`24d6cf6a`; re-taken at `b261d045`/`c13cf7c7`): refused `clause=field_controls_locked` at 600 frames, then released and settled |
| 4 | Hall of Fame | **recorded limit** — needs the Elite Four; unreachable from the town fixture |
| 5 | link incremental saves (`Task_LinkFullSave`, post-link-battle, trade) | **recorded limit** — needs a real link battle, i.e. the same hardware limit as decision (b) |
| 6 | cable: open before exchange, null callback while open, established, cancel, disconnect, then resumed writes | **CLOSED as its limit form** (re-taken at `b261d045`, `c13cf7c7`) — cancel → resumed writes is the FR PASS above; *open before exchange* is a **recorded limit** (`link.c:373` then `:394`, no frame boundary) and the *null callback while open* window is **logged its limit form live** (`24d6cf6a`, re-taken at `b261d045`) (`CABLE_CALLBACK_NULL limit=no-cable-partner`, `scenario_gen3_center_controls.lua:188`), because the callbacks are cleared only after a partner connects (`link.c:746-757`; the linkup task returns while `playerCount < 2`, `cable_club.c:208-214`) |
| 7 | wireless background / exchange / teardown | **recorded limit** — no adapter: both Center receipts observe `adapter_connected=false` (`IsWirelessAdapterConnected`'s VAR_RESULT) |
| 8 | League rooms: admission, plus refusal in scripts, save and battle | **recorded limit on hardware, static proof in the audit** — `Task_RunPokemonLeagueLightingEffect` persists in the Elite Four rooms (PROVEN on FR/LG, inferred for RR); the rooms are unreachable from the town fixture |
| 9 | a previously-saved fixture with the START cursor on another submenu, where the dialog witness must stay false | **DONE live on both titles** (re-taken at `b261d045`/`c13cf7c7`; first pass at lane `0feb9383`) — the C4-6t witness (`10e4a702`) has unit falsifiers for exactly this — **IMPLEMENTED** at `c9e2b695`: the row-9 refusal line forbids `save_dialog_cb`, and the driver gained seven `start_menu` statics in SYMS plus a read-only `ctx.peek` — **live: PASS on both titles** at `b261d045`/`c13cf7c7` (first pass at lane `0feb9383`) |
| 10 | positive recovery writes with readback | **DONE** — §3.1's `save_then_write_gen3` on both titles (keyed write landed, PYDEC PASS) |

The four rows above are implemented by **`c9e2b695`** (design `beeea4ff`,
`docs/gen3/research/c4_save_rows_design_2026-09-23.md`), with **14 falsifiers red on its parent**
(the commit's own count; the diff adds 12 new test functions, some parametrized). **The live runs are
IN FLIGHT** (`save_then_write_gen3` and `center_controls_gen3`, FR-as-A and LG-as-A, lane `03ab26e7`):

**Live results (lane `03ab26e7`, clean):**

- **Rows 1, 3, 6 and 9 — re-taken on both titles at `b261d045` (`c13cf7c7`).**
  `save_then_write_{fr,lg}_as_a_b261d045_2026-09-23.txt` and `center_controls_{fr,lg}_as_a_b261d045_2026-09-23.txt`:
  `a=PASS b=PASS`, PYDEC PASS, witness `match=true` on both titles — the same four rows after
  REV-PROBE2-SAVEROWS's fixes (`b261d045`: row 6 judged field by field, a flash-counter guard, chain lows).
  Row 6 stays closed as its **limit form** (`CABLE_CALLBACK_NULL limit=no-cable-partner`: no partner ever
  connects, so the null-callback window cannot be produced here). **P**
- **Rows 3 + 6 — DONE.** `center_controls_gen3` **PASS on FR-as-A and LG-as-A** @ `24d6cf6a`, receipts
  `docs/gen3/probes/center_controls_{fr,lg}_as_a_c4saverows_2026-09-23.txt` (`RESULT: PASS (the cable menu,
  the Cable Club save prompt, the cable link wait and the Union Room attendant each held a keyed probe; each
  landed once released)` on both titles). Row 3: `CONTROL_REFUSED cable_save … clause=field_controls_locked
  held_frames=600 attempted=0 writes=0 bytes=unchanged` (`:29`) — the save prompt refuses on the lock, not on
  a save-dialog clause. Row 6 logged its **limit form**, as predicted: `CABLE_CALLBACK_NULL
  limit=no-cable-partner open_frames=601 null_frames=0 callback=0x0800A721:LinkCB_RequestPlayerDataExchange`
  (`:33`) — no window exists because no partner ever connects.
- **Rows 1 + 9 — PASS on both titles.** `save_then_write_{fr,lg}_as_a_c4saverows_2026-09-23.txt`, clean lane
  `0feb9383` (`source=0feb9383`), `save_then_write_gen3: a=PASS b=PASS`, `PYDEC: PASS asserted scenario facts`,
  witness `match=true`. Markers: `SAVE_DISMISSAL by=a_press` for both saves, `DIALOG_WITNESS_FALSE` off SAVE,
  the probe refused at the overwrite prompt and the redrawn menu (600 frames, `attempted=0`), then
  `SAVE_CANCEL_WRITE_FRAME … field_free=true start_menu_task=false` (FR frame 5686, LG 5536). The first run at
  `03ab26e7` failed PYDEC only on an oracle ordering bug — the client applies the write on the first free frame,
  inside that frame's pump, before the scenario could log `SAVE_CANCEL_FIELD_FREE` — fixed at `0feb9383` by
  ordering the landing on the write's own frame (falsifier red on `c9e2b695`). **P**


---

## 4. MODEL evidence

| Area | Evidence | Tag |
|---|---|---|
| Unit suites | `python -m pytest tests/unit -q -p no:randomly --deselect tests/unit/test_gen1_trade_patch.py::test_defs_match_committed_red_and_blue_symbols_and_pret_tables` → **5671 passed, 300 skipped, 1 deselected, 0 failed** at the `3327720c` tree (measured with the concurrent workers' uncommitted edits in place). The deselected test needs `.cache/pret/pokered` and is environment-only in a worktree, which is why it is deselected rather than reported as a failure | **M** |
| Gen 3 suites | the Gen 3 gate set (client, native, entry, safety, writes ownership, profile, checkpoint, fixtures, patch sources) is green at `3327720c`; `python tools/lua_syntax_check.py` → 235 Lua files parse; `ruff` clean on every touched file | **M** |
| Conformance | `tests/unit/test_protocol_conformance.py` → **67 passed** over the `gen3_new` goldens, with the doc-sync meta-tests that keep `docs/protocol.md` §9 and `conformance_map.py` in step; the citation-drift rules (three of them now) run in `tests/unit/test_protocol_citations.py` with sha-pinned falsifiers | **M** |
| Write ownership | `tests/unit/test_gen3_write_ownership.py` + the static leak test and the intercepted-sink run required by `docs/gen3/PLAN.md:171` ("write ownership is not proven by `writes.log` alone") | **M** |
| Duo harness | `tests/unit/test_e2e_duo_*.py` (386 tests across the eleven files) incl. the strictness rounds `50d580c9` / `32e0e469` / `2cace0a9`, and the C4-6n provenance work (`fb255a05`: full markers, rename-safe dirty check) | **M** |
| Release-zip hygiene | `tools/check_release_zip.py` @ `c8f0c804`: blob equality per member, no dev-only paths, the FRLG closure present | **M** |
| Independent reviews (Codex, "Review Gen 3 Part 2") | ACCEPT: `writes.lua`, `deferred.lua`, `identity.lua`, the Entry binding, `native.lua`, `core/session.lua` (REV6); `client.lua` quiet-timer; the trade lifecycle at `78908fe8` (REV7, with the receipt caveat since closed by C5-7's per-job dispatch receipt); the duo harness REV4 ACCEPT at `2cace0a9` — narrow: receipt order, RR move-0 PP, duplicate party key, with the RR extension and the explode/rival controls left OPEN/NON-QUALIFYING (`RC_MASTER_GUIDE.md`, row `gen3-P4-C4-6d`). REJECT-then-fixed: `boxes.lua` (Opus review, fixed `d1d4fcec`); the client core (REV2/REV3, fixed `aa062f61`/`690e1c63`/`f3575ff5`) | **M** |
| Independent reviews (R1/R2, in-repo, 2026-09-24) | **R1** `docs/gen3/reviews/R1_PH_REVIEW_2026-09-24.md` @ `26c7e281` — mechanism P+H (`9719b519`, `274fa486`, `375cb963`, `cdc571f1`, `82f707c3`, `998666b6`, `923de234`, `4240248a`). ACCEPT-WITH-FIXES, 0 HIGH / 1 MEDIUM / 9 LOW; every code finding fixed in `4a91daeb` and `9e227101` (L3/L4 fixed separately in `28e48c9c`). **R2** `docs/gen3/reviews/R2_GATELIB_REVIEW_2026-09-24.md` @ `2ebfdf1f` — the `gen3_gatelib` RR opcode-gate port (`2aad8e2a`, `6daea62d`, `2f26742d`, `21dfa6e7`). ACCEPT-WITH-FIXES, 0 HIGH / 3 MEDIUM / 9 LOW; fixed in `dfd8a96d` | **M** |
| Independent review (F1, in-repo, 2026-09-24) | **F1** `docs/gen3/reviews/F1_G4_AUDIT_2026-09-24.md` @ `40b863bd` — audit of this draft plus the independent adversarial review of `904c134c` (RR Explode+H, the hand-off policy reshape landed after R1). Verdict on `904c134c`: **ACCEPT for G4 purposes** (FR/LG byte-identical to pre-commit behaviour; the shared files it touches change only behind data the FRLG packs do not carry) — this is now that commit's review of record, superseding the draft's prior implication that the R1 fix chain (`4a91daeb`/`9e227101`) was the last review of `safety.lua` (finding H1). No code HIGH found; **M4** (Explode+H trusts the pack's row grouping — a pack whose every explode row carries `group: "moves"` would admit a stale-replay plan) and **M5** (the generator's Explosion-PP-5 pin is a decorative tripwire, not a proof, and fails silently) are recorded as **G5 fixes**, not G4 blockers. F1 also carries 1 BLOCKER (B1, resolved moot by owner ruling 22, §6) and 3 HIGH (H1 here; H2 and H3, both applied in this draft and in `rollback_bundle.md`) | **M** |
| RR opcode gates, live (G5 evidence) | **R2**'s reviewed `gen3_gatelib` port ran live on hardware: `docs/gen3/probes/rr_gates_live_06724759_2026-09-24.txt` @ `0995a82e` (G5-GATES-LIVE) — **26/26 PASS** at cut `06724759` (rebuilt companion md5 `6cf77ba4…`), plus `forcemove` and `explode_route` PASS. This is G5 evidence (the RR cutover is not on the G4 cut, owner ruling 22, §6), cited here because R2 is the review that qualifies it | **P** |
| The C5 stack | **committed** as `2dc1b750` (C5-10/10b/11a/11b/11c/11d: battle identity, patch-enforced window, fail-closed session counter), and its run/client/entry and session-counter changes are part of the tested G4 cut: `2dc1b750` is an ancestor of both `d199da32` and `fb255a05`, so the scenario receipts carry it. Only RR native-feature and patch qualification stays at G5 | **S** |
| **The battle clause set is required, both ways** | `safety.lua`'s `battle()` validates the `gen3-battle-v1` block before it evaluates anything (`a1bbc686`): a missing, duplicated, unknown or malformed clause (compare outside `eq`/`eq_rom`/`eq_symbol`/`nonzero`, or an `eq` without an `expect`) refuses as `{"pack"}`, and the generator raises `SystemExit` on a dropped battle clause instead of writing a weaker block. The RR pack additionally carries `battle.commit_hold`, so `battle_commit` on RR is refused by the named clause `battle_commit_hold` (CFRU's parked controller stays live after `comm = 3`; an L press runs `RemoveBagItem 0x090AA114`) | **S**/**M** |
| **The RR battle permit + the FORCE_MOVE_SLOT driver (G5 items)** | The RR parked-menu permit was UNSAFE (`765beb48`: CFRU keeps the exec bit set while the menu is parked) and is fixed in `97082a62` (parked-menu permit = `exec_flags_input == 1` + a ROM-pool controller pin) with the clause-set work in `a1bbc686`. `FORCE_MOVE_SLOT` is **source-only**: `15a274ec` (0-based comm enum — the menu parks at 1, the move menu at 2 — comm 3 instead of 4, and the `PlayerBufferExecCompleted` hand-back) plus `21df5314` (the second action-menu spelling `0x090A9EA1`, a link-battle guard, a PP-zero refusal at the gate, the `target` staging bound, and ADDRESSES.md stating that the menu's own Disable/Encore/Taunt/Choice checks are overridden by contract). **Done (C5-3, `998666b6`, owner-approved):** the companion ROM was rebuilt from current `patch/src` and `patch/dist/SLink-RR.ups` regenerated; the admitted companion is now md5 `6cf77ba4a63634a0fd452be6f206bfc3` / sha1 `ea5352f8a3b9073f8ae20870ad12857925d442cd` (was `bf8e94a0…`/`b7d1e075…`), re-pinned everywhere in code (`82f707c3`, `9cc82f12` for the doc/note pins) and verified by R1 (no code pin still carries the old hash). Still owed: a live re-run of `test_live_forcemove.lua` proving the turn completes, not just the PP drop (`patch/src/ADDRESSES.md`'s note). RR's flash-writer caller census is `76bc4486` (17 PROVEN / 1 INFERRED / 1 OPEN) | **S**/**M** |
| **The LG frame-end CPU census** | `168fde14` + `b21a3431`: the first LeafGreen overworld frame-end census (`docs/gen3/probes/census_lg_overworld_2026-09-23.txt`) — 1675/1800 frame ends inside `WaitForVBlank`'s LG range `[0x08000890,0x080008BF]` with mode `0x1F`, T=1, the other 125 on the BIOS IRQ vector and refused by the clause on purpose — is now pinned in the pack's `leafgreen` cpu block (`census` + `observed_pc 0x080008AC`) by the same generator path FR uses, with the pack/test/generator equality asserted (`tests/unit/test_gen3_write_checkpoint.py`). The FR and gen3_rr packs are byte-identical after the regeneration | **S**/**P** |
| Receipt `clause=` names before `13b11907` | not comparable on that field: C4-ORDER (`dc855dda`, `13b11907`) made the checkpoint's first-failure reason deterministic (priority = `lua/gen3/safety.lua`'s fixed `predicates` list) and made a pack predicate outside that list refuse the whole check. On a frame where several clauses fail, older receipts may name a different one (the FR receipt's `clause=link_callback` was recorded where `field_controls_locked` also failed). Diff receipts across that boundary on the clause name only with this in mind; the *set* was and is complete | **S** |

---

## 5. Limits carried forward (not signed by G4)

| Limit | Why it is not a G4 row | Tag |
|---|---|---|
| The seven OPEN signal kinds and the four PARTIAL checklist rows from G3 | unchanged since G3 signed them as limits (`docs/gen3/PLAN.md:318`, the G3 signature row); the FRLG-relevant subset is §2 item 3, the rest stay OPEN | **S** |
| **RR clean artifact** | G3 carried it as deferred and it still has no duo receipt; **LG clean now exists** — fixtures (`0978a5be`, `fc0e45b2`), boot-check 8/8 @ `3327720c` and the FR-as-A and LG-as-A Center receipts @ `5a8064f3` | **S** |
| `explode_gen3` and `rival_swap_gen3` | labelled **NON-QUALIFYING controls** (`2cace0a9`): their witnesses sit at action-start / an unverified RR offset, so they cannot qualify a row | **S** |
| The RR extension evidence | OPEN in the harness (`2cace0a9`); the RR save extension is compared to a live-RAM copy or reported OPEN | **S** |
| The RR cutover, the patch rebuild, `patch/dist/SLink-RR.ups`, `server/patcher.py`'s pin, the companion re-pin, **and the four landed RR fixes** — the parked-menu battle permit (`97082a62` + `a1bbc686`), the source-only `FORCE_MOVE_SLOT` (`15a274ec` + `21df5314`; companion **rebuilt** `998666b6`, re-pinned `82f707c3`/`9cc82f12`, md5 `6cf77ba4`/sha1 `ea5352f8`), the flash-writer caller census (`76bc4486`), and RR P+H + RR Explode's hand-off (rulings 15-19; built in source, live rows pending the `rr_battle2` fixture, `8103ddec`), all in §4 | **G5**, not G4 (`docs/gen3/PLAN.md:207`, the P5 row). The C5 stack (`2dc1b750`) is on the tested cut (see §4); only RR native-feature and patch qualification stays at G5 | **S** |
| Archipelago FRLG, RR native text, the peer ghost | removed from this RC by owner ruling (`PLAN.md` §0, `docs/gen3/TODO.md`) | **S** |
| **The C4-SAVE checkpoint change on RR** | FR/LG only: the audit finds RR's `HandleSavingData` and `RunSaveFailedScreen` differ from FR, and the four gated link bodies being byte-identical is the generator's gate, not a proof. RR re-qualification is G5, with RR's parked-battle tuple (`docs/gen3/research/checkpoint_predicate_audit_2026-09-23.md` finding 2) | **S**/**M** |
| **BizHawk's rewind capture crashes the mGBA lanes** | environment, not product: `MainForm.CaptureRewind` → `ZwinderBuffer.Capture` → `MGBAHawk.SaveStateBinary` → `BizInvokeProxyLibmGA.BizStartGetState` threw `System.AccessViolationException` and killed **both** instances of run 61569 (`patch/build/duo_61569_{a,b}.out`). C4-6t disables it in every generated run config (`Rewind.Enabled = false`; BizHawk's own default is `true`, so a config that omits the key would still rewind). **Any EmuHawk launched with the machine's base `E:/Howard/Bizhawk/config.ini` still rewinds** — the fix is per-copy, not machine-wide, and that is worth telling the owner. Runs lost this way are not in the estimate | **P**/**S** |
| Gen 4/Gen 5 (HGSS/Pt/BW) | out of this release entirely | **S** |

---

## 6. Owner decisions

### Settled (recorded; not reopened here)

1. **Center writes are in scope and need their own PHYSICAL receipt on FR and LG** (owner ruling
   2026-09-23; `5ecfae3b`, Codex REV-center-tasks-1 ACCEPT as SOURCE/MODEL). The receipts at
   `5a8064f3` are the 1F half of it and `3fefbee7` (`center_controls_fr_as_a_2026-09-23.txt`) plus `0c2f384a`
   (`center_controls_lg_as_a_2026-09-23.txt`) are the 2F half — PASS on both titles. **S**/**P**
2. **In-battle faint must work on vanilla, with RR parity** (`PLAN.md:16`) — that is why `linked_faint_active_gen3`
   is a required row (now PASS at `4ec51ed0`) and why 2b's matrix is owed rather than optional. **S**/**P**
3. **The generations converge after G4**: the Gen 1 SFX gate (`44bf25d6`) and the Gen 1 ordering
   fix (`3941198c`) live on the Gen 2 branch and are not this cut's work. What is *open* is only how
   item 6 records that (decision (a) below). **S**
4. **FRLG vanilla is the RC**, RR flips at G5; every P4 card is pack-neutral (`PLAN.md:17`, the RR-under-the-new-standard row). **S**
5. **The companion artifact is what the shipped UPS produces** (`bf8e94a0…`, §1 item 5) and the
   `codex/rr-foundation` branch is archived rather than merged (`PLAN.md:315`, the G0 row's archive-tag decision). **S**
6. **Peer ghost removed from the RC; RR native text removed/disabled; Archipelago FRLG deferred
   post-RC** (`PLAN.md` §0; `docs/gen3/TODO.md:6-32`). **S**
7. **Two-reviewer precedent at G6** is kept. **S**
8. **Rival swap gets a wire request id and a patch-side consumption-time window check** (`122d003e`,
   `PLAN.md` §0); the additive opcode does not bump the mailbox ABI (C5-8d). G5, not G4. **S**
9. **The LG intro is the same engine as FR's** (owner, 2026-09-23): LG fixtures were built through
   the FireRed scripted path with pret-sym RAM witnesses replacing frame counts (`0978a5be`). **S**

10. **Item 6 is split** (owner, 2026-09-23, decision (a)): take `44bf25d6` (the Gen 1 SFX-gate stale test expectation; applies cleanly, test files only) into this cut; judge the Gen 1 command-ordering case and the legacy Gen 2 failure by route-differential evidence against master's baseline, and leave `3941198c` to the post-G4 convergence card (`docs/gen3/research/item6_integration_feasibility_2026-09-23.md`, `21234c4f`). **S**
11. **The rollback freeze is the SHA + manifest** (owner, 2026-09-23, decision (c)): `docs/gen3/rollback_bundle.md` @ `2cd9f993` is the frozen rollback; no separate archive is built. **S**
12. **Doubles, the target menu and Safari are signed as current-fixture limits** (owner, 2026-09-23, decision (d)): 2b rows D1-D5, N3 and U3 are recorded G4 limits; every other 2b row still runs. **S**

13. **The cartridge's own link features are signed as limits** (owner, 2026-09-23, decision (b)): the real in-game link battle (`battle_link`) and Union Room entry/return are recorded G4 limits. SLink never uses the game's link cable or a wireless adapter — its trades and link events go through the SLink server (`docs/protocol.md` §6) — so these rows only test that SLink stays hands-off if a player uses the cartridge's own Cable Club link battle or Union Room, which cannot be produced here (no cable partner; `IsWirelessAdapterConnected` observed false). The 2F Cable Club controls that do run here stay PASS (`c13cf7c7`). **S**

14. **The in-battle lag-frame window is a signed limit, no clause added** (owner, 2026-09-23, decision (e)): the window is real and observable (a frame end can land between the action-menu choice reaching `gBattleBufferB` and `PlayerBufferExecCompleted`), but it has no harmful outcome on FR/LG. The action-menu commit records only the action *type* (pret `battle_controller_player.c:238`); the switch target, move and item are chosen later under controllers the permit refuses, so a bench faint in the window cannot produce a switch into the fainted mon, and a forced commit there simply wins (Explode Mode's intended result). The RR L-throw exception is already closed by `battle_commit_hold` (`a1bbc686`). Analysis: `docs/gen3/research/battle_lag_frame_census_design_2026-09-23.md` (`9ffa8c6d`, coordinator notes incl. `7f004813`). The owner asked for a small check if one fit; after the trace there is nothing for it to guard. **S**/**M**

All five owner scope decisions (a)–(e) are settled and recorded above.

15. **Mechanism P, active faint in battle** (owner, 2026-09-23, "A"): when a linked partner dies while our linked mon is the active battler on FR/LG singles, the mon faints in battle through the engine's own Perish KO (`docs/gen3/research/active_faint_in_battle_scope_2026-09-23.md`; built `1b3943e3`/`39bcc4f8`/`66595498`). Explode Mode is not changed. RR gets the same behaviour (owner: "RR is meant to have parity"; G5, `docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md`). **S**
16. **P hands off the battle controller on every title** (owner, 2026-09-24): the plan ends by setting `gBattlerControllerFuncs[0] = PlayerBufferExecCompleted`, so no A press is needed on FR, LG or RR (RR scope §3.2, §5.1). **S**
17. **The RR lag-frame lost-ball window is a signed limit** (owner, 2026-09-24): about 1e-4 to 1e-3 per commit, and only when L is newly pressed on that exact frame (RR scope §3.5). This is the same class as ruling 14. The companion opcode (§5.6) is not built. **S**
18. **The DREW edge is accepted** (owner, 2026-09-24): if our last usable mon takes the Perish KO on the same turn that the foe's last mon faints at end of turn, the engine scores a draw and we white out through the normal Center heal and rebuild (active-faint scope §2.1). P is not held on the last mon. **S**
19. **RR Explode gains the controller hand-off** (owner, 2026-09-24): on RR, `force_explode`'s commit plan ends in the same `battle.handoff` tail as P, so Explode fires immediately again, as it did on the old RR client, and protocol item 34 holds on RR. FR/LG Explode is untouched. G5. **S**
20. **RR row R5 (no mega evolution during the forced faint in a trainer battle) is a signed G5 limit** (owner, 2026-09-24): no Mega Ring or stone holder can be reached by normal inputs early in RR, and the source shows the Perish path reads no mega state (RR scope §4). The row stays in the tree as a named SKIP. **S**
21. **The whiteout-with-only-pair outcome is accepted as intended** (owner, 2026-09-24): when the last linked pair dies, the server's `game_over` ends the run. B's in-game whiteout heal and the dropped last-mon memorial do not matter after game over. The whiteout row asserts exactly this. **S**
22. **Nothing is released until G4 and G5 are both done** (owner, 2026-09-24: "None of this is getting released until it's all done."). G4 is an internal gate. No build ever ships RR the rebuilt companion (`6cf77ba4`) with the old client, so audit F1's blocker B1 (`docs/gen3/reviews/F1_G4_AUDIT_2026-09-24.md`, `40b863bd`) is moot. The RR cutover and the old-client deletion (C5-6) land before any release. **S**
23. **RR's CPU checkpoint also accepts the BIOS IRQ entry taken from the halt** (owner, 2026-09-24): with the client's per-frame hooks active, RR's frame ends at the BIOS interrupt vector (IRQ mode, R15 = 0x1C), and the signed System-mode halt clause refuses every frame, so hello never fires (`docs/gen3/probes/rr_rows_hello_cpu_park_6d6227c6_2026-09-24.txt`, `7d730a89`). The clause also admits IRQ-vector entry only when the banked return address (R14_irq) lies inside the BIOS halt loop. An interrupt taken from game code stays refused. G5. **S**
24. **C5-6 archives the old Gen 3 client and drops Emerald and Archipelago FireRed support** (owner, 2026-09-24): the old client is their only code path. Its last version is tagged `archive/gen3-old-client` before deletion, so they can be ported onto the new client later. Until then they are unsupported (C5-6 plan `6ed149b0`, risk 1). **S**
25. **RR (G5) needs "a decent amount" of coverage, not full coverage** (owner, 2026-09-25: "We don't need full test coverage for RR but we need a decent amount", then "Do it then" on the proposal):
    - **(a) Clean RR:** ONE more clean-side row (a basic link+faint on the clean ROM) beside `native_absent_gen3` and `linked_faint_active_clean_gen3`, once that row's driver is fixed, is sufficient. Full clean S-1..S-11 coverage is not required.
    - **(b) Rival Team Swap:** needs ONE qualifying row, a real swap with enemy-party readback.
    - **(c) Opcode gates:** the 12 deferred gates are a signed limit; the 26 ported live gates cover the opcodes in use.
    - **(d) Per-item evidence:** the P2 anchor/md5/deleted-file/write-guard/native-control items are satisfied by the existing unit/model evidence (the pin tests, test_gen3_write_ownership, the test_gen3_native control tests). No separate live receipts are needed.
    G5. **S**
28. **Trainer names, Upcoming Key Trainers and the calc Prep tab are mandatory for the RC on vanilla FR/LG too** (owner, 2026-09-26: "trainer names, Upcoming Key Trainers, the calc's Prep tab are mandatory for RC"; asked whether that bar applies to vanilla FR/LG: "Yes." The ruling was relayed by the Emerald lane and confirmed directly in the Gen 3 session, together with "Gen 3 builds FR/LG now"). Today all three are RR-only: every adapter hook in `server/adapters/gen3_frlge.py` returns empty unless `_is_rr`. The contract is `docs/gen3_emerald/research/rc_trainer_contract_2026-09-26.md` (claude/gen3-emerald 9abfe322). The Gen 3 lane builds the FR/LG half from pinned pret pokefirered, with a generator Emerald reuses. G4 needs it. **S**

27. **FR/LG in-game trade is IN this RC, on patched ROMs** (owner, 2026-09-26, relayed by the Emerald lane and confirmed directly in the Gen 3 session: "In game trade is supposed to work for FRLG"; "Supported on patched ROMs only"; trade evolution "Evolve on receipt"; reset-without-save "Look at how other patched gen1/2 do it"). It reverses the G0-era scope row (`docs/gen3/PLAN.md:13`). It needs FR and LG companion builds (none exist today; only RR has one), a `companion` kind for `gen3_frlg`, FR/LG trade duos and a new FR/LG frozen cut, so **G4 cannot be signed on the a2985d5a cut alone**. Sequenced after the RR companion fix batch, as one shared Gen 3 implementation that Emerald binds. **Built in the Emerald worktree** (`.claude/worktrees/gen3-emerald`, branch `claude/gen3-emerald`; owner 2026-09-26: "Make sure this work is being done in the Emerald worktree"), after it merges master with the RR fix batch; the Gen 3 lane supports and reviews. **S**

26. **Land Gen 3 on master now** (owner, 2026-09-25: "Lets just merge it"). The owner directed the Gen 3 → master merge after the frozen cut a2985d5a (FR/LG 43/43, RR 19/19) and before a formal G4/G5 signature. Master is fast-forwarded to a verified merge of master (with Gen 2) into the Gen 3 line; it is local and not pushed. Nothing is released or tagged (G6 is still the owner's). **S**

---

## 7. How to verify this draft

- Every receipt path above exists under `docs/gen3/probes/`; every commit hash is in
  `git log --oneline`: the scenario receipts land at `8deddf23`, `d074bda2`, `4ec51ed0`, `059da756`, `ac1a5490`, `fb255a05`, `5a8064f3`, `60a9ce18`, `3327720c`, `3fefbee7` (FR Center controls + the partial LG save-then-write, cut `f5d92327`), `0c2f384a` (save-then-write FR+LG and LG Center controls, clean cut `10e4a702`), `5923c4dd` / `0e7f89e7` / `160c2508` (C4-SAVE and its adversarial review), `10e4a702` (C4-6t) and `b56c3b50` (the persistent-task census); the C4-SAVE-ROWS chain is `beeea4ff` (design), `c9e2b695` (implementation, 14 falsifiers red on its parent) and `24d6cf6a` (rows 3+6 live); the item-3 probe chain is `6bc722bd`/`a256450e`/`b0511ff2` with the receipts at `03ab26e7`; C4-ORDER is `dc855dda`+`13b11907`; the 2b plan is `082b33a9` and the item-6 feasibility `21234c4f`.
- The final-cut re-take plan is `docs/gen3/G4_final_cut_runbook.md` @ `23b27065` — one invocation per G4
  item, with the receipt it produces, the PASS line to look for and the approximate wall-clock — and the receipt
  plumbing it depends on is `tools/gen3_bw_hashes.py` + `tools/gen3_probe_receipt.py` @ `587453bf` (the bw-hash
  producer closes runbook §12 item 2, the receipt wrapper item 3), reviewed with fixes at `e8497461`.
- The per-item status and the open decisions are Codex's reconciliation
  (`docs/gen3/G4_status_2026-09-23.md`) plus the receipts that landed after it (`5a8064f3`,
  `60a9ce18`, `3327720c`); where this draft disagrees it says so rather than quietly restating.
- The scenario names and the FR↔LG pairing come from `tools/e2e_duo.py` itself (`--list` output;
  the pairing is the `"b": ("leafgreen", "leafgreen_party_{target}")` row).
- The review verdicts come from the RC ledger's `gen3-P4*` / `gen3-REV*` rows
  (`C:/Users/howar/.claude/hooks/slink/RC_MASTER_GUIDE.md`), not from this draft's prose. §3's audit,
  census and adversarial review are `docs/gen3/research/checkpoint_predicate_audit_2026-09-23.md`
  (magi `cx-7e8b52f4`, `cx-45b6df45`, `cx-3e10776a`), likewise read in full rather than paraphrased.
- **2026-09-24 additions.** Item 6's route-differential receipts: `docs/gen3/probes/item6_route_diff_master_2026-09-24.txt`
  and `item6_route_diff_branch_2026-09-24.txt`, both @ `b0483efe`. Mechanism P+H (item 2b, PLAN §0): built at
  `1b3943e3`/`39bcc4f8`/`66595498`/`9719b519`/`375cb963`/`cdc571f1`; the RR companion re-pins at `82f707c3`/`998666b6`/`9cc82f12`
  (md5 `6cf77ba4`, sha1 `ea5352f8`); the carrier move to P+H at `923de234`/`4240248a`, with review fixes at `28e48c9c`. R1
  review `docs/gen3/reviews/R1_PH_REVIEW_2026-09-24.md` @ `26c7e281`, fixed by `4a91daeb`/`9e227101`/`28e48c9c`. R2 review
  `docs/gen3/reviews/R2_GATELIB_REVIEW_2026-09-24.md` @ `2ebfdf1f`, fixed by `dfd8a96d`. The 2b P+H live receipts
  (`docs/gen3/probes/ph_*_gen3_{fr,lg}_as_a_*.txt`) landed 8/8 PASS and are committed at `6d6227c6`
  (G4-LANE-2); they are REHEARSED evidence, re-taken by `tools/gen3_final_cut.py`'s `§5 item2b` rows on
  the frozen cut (audit F1 `docs/gen3/reviews/F1_G4_AUDIT_2026-09-24.md` @ `40b863bd`, finding H2; §2's
  2b row lists all 8 by name and flags the one committed FAIL instrument record).
