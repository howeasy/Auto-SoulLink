# Gen 2 grounding and P0 restart receipt — 2026-09-22

Status: current bounded work frozen at the owner's request to restart Codex with new settings.
This is a receipt, not another dispatch ledger. The sole grant/checkpoint remains the sweep
RC_MASTER_GUIDE.md and WORKTREE_REGISTER.md.

## Verified cuts and coverage

- Planning checkout: E:/Google Drive/SLink, branch claude/gen2-planning-kickoff-a18801,
  HEAD 9c7e7acfef1a5c2e1dc7111e8dfdb0c71610b043.
- Former planning worktree remains detached at that same cut; it was not edited.
- All 49 original Markdown files under docs/gen2 were read in full across the coordinator
  and three acknowledged Codex readers before P0 drafting. Coverage is the complete inventory
  below, not a claim to have reread every unrelated historical Markdown file in SLink.
- Coordinator read PLAN, binding plan, requirements, open questions, review record, resume,
  and applicable orchestration/tracker instructions. Readers covered 18 research reports,
  22 Wayfinder tickets, the map, digest and comparison, plus referenced shared contracts.
- Independent document/source checks followed; no emulator or ROM build ran.

## Current outputs

- spec.md: 340-line draft, all 53 requirement IDs once; SHA256
  3DB3314167B1D4763128D3572E662ED3466CD63A3B1250998A9FA0A6FE92C6DE.
  Independent review pending.
- issues/: 35 files, 35 unique binding substeps, 1136 total lines; links and exact lease checked.
  Aggregate SHA256 7E6CE409767F5DCA49A19BF3662CD8AAD6E4706651C84FBD3349F373AA7BC126
  over sorted filename + space + file SHA256 records joined by LF, UTF-8.
  Independent review pending. Specification readiness does not grant execution.
- Binding-plan cleanup frozen: de414dce9529f883cc9b2ef0b96aa58359c1aa75fd83f5cd1d3e9482d3851d22;
  35 substeps / 53 mapped IDs preserved. Independent review pending.
- Four Wayfinder edits independently ACCEPTED by a non-author Codex worker.
- Requirement normalization independently accepted on S-5/S-8/C-0/D-12. The attempted
  conjunctive F-3 oracle was REJECTED; coordinator restored the entire F-3 row byte-for-byte
  to the 9c7e7ac source. PYDEC/GAME applicability remains explicit unresolved work;
  no behavior/evidence requirement was silently strengthened or weakened. All 53 IDs
  and 159 SOURCE/MODEL/PHYSICAL cells were preserved by the worker's comparison.
- The original O-1..O-20 decisions remain closed; no G0 or other signature was invented.
  The user's Magi approval concerned config only. The later get-to-work instruction moved
  this session into P0 preparation.

## Isolated shared base

E:/Google Drive/SLink/.claude/worktrees/gen2-foundation, branch codex/gen2-foundation:

| Selected source | Integrated commit |
| --- | --- |
| master 8f6a9863e668569ff9647eaff3748c790d46c4a1 | unchanged base |
| 80261f392598f8af3a223e6e5e7811e2d4f3cae9 | 644b3b8 |
| 959c5780e1338e631eccdf8d1b2b65b39843d6d3 | fa8c2f8 |
| 910dbdd81d01794098d919fb3947d70afed9e334 | 1d1171a6dde131d6b6b7d6402824fcacb26596d1 |

The hello-boundary cherry-pick conflicted because its parent contained an unselected
_WireTap class. The resolution retained only the selected _FOUNDATION_ABSENT insertion.
A separate Codex review verified all 127 added/deleted lines of the original/imported
selected patch match in order and that no wire-tap references entered the consuming cut.

Focused pairing/protocol tests: 49 passed.
The four-suite import check then produced 70 passed / 1 failed: the imported Gen3-only
manifest invokes absent tools/gen3_pins.py from unselected ancestry.

Frozen correction by an isolated worker removes only tools/verify_gen3_release.py and
tests/unit/test_verify_gen3_release_lanes.py, and adds tests/unit/test_release_lanes.py
(18 neutral behavior cases; SHA256 BF6202FCE5328B101B98B3F90A56452FD7F112D374FCB3639C84616471FA9FC0).
Shared release_lanes.py and the Gen1 wrapper are unchanged. Red replay: 18 passed / 1 failed;
after correction: 78 passed / zero skips, ruff and diff whitespace checks passed.
Independent review ACCEPT is recorded in .cache/gen2-orchestration-20260922/shared_runner_review.report.md.
The reviewed correction is committed as 645bc73468df11c9d1e60caf405ce73e21d04937; the isolated tree is clean.
The review's nonblocking neutral --list test follow-up is deferred to restart.
These are MODEL/source integration results, not a Gen1 physical regression or Gen2 release gate.

Gen3 drift baseline: 293542283c62526c3ee40be138ac9a1b5a67b297.
The designated shared-file comparison differs only in server/server.py at this cut;
the unselected wire-log instrumentation is intentionally not adopted.

## Source findings to carry directly into implementation

- Local clean inputs exist: Crystal v1.0 f4cd194bdee0d04ca4eac29e09b8e4e9d818c133,
  Gold d8b8a3600a465308c9953dfa04f0081c05bdcb94,
  Silver 49b163f7e57702bc939d642a18f591de55d92dae. File/source evidence only.
- Stat CONTROL pseudocode in research/stat_control_and_fixture_budget.md and Wayfinder
  ticket20 is WRONG. The independent exact-pin report establishes 2*(base+DV), capped
  ceiling square root before dividing by4, integer level scaling, HP/non-HP constants,
  and the999 clamp. Discriminating non-HP cases: base50/DV15/exp0/level100 ->135, not120;
  base50/DV0/exp10/level100 ->106, not105. The new codec ticket names these falsifiers.
  Correcting the old research note/ticket remains for restart; no production codec exists yet.
- Both source recipes specify RGBDS1.0.3. Existing bootstrap supports it, but overrides
  must be version-validated; root cached1.0.1 is not an acceptable substituted pin.
- Mailbox allocation, built-ROM sites, checkpoint liveness/negatives, CGB frame/domain
  checks, RTC witness contract, eight played fixtures and native/duo physical evidence
  remain real phase obligations.

## Workers, ownership, and restart

Ten Codex lanes were used: three built-in workers plus seven headless Codex workers.
No additional OMP workers were launched. OMP Gen2-Base supplied contextual handoff
cx-ecd3ba04: no file/emulator claim, prior cards finished; outcome6accepted/0rejected/1open.
Its clean-tree/spec-absent observations predate the P0 writes and are not current status.
REVIEW_RECORD lacks symmetric A5/A6 entries; the guide/report artifacts already record
completion. This is a nonblocking documentation note, not an outstanding old audit.

Host CLI IDs/PIDs/outputs are in .cache/gen2-orchestration-20260922/host-launches.json.
Initial sandboxed CLI launches had no host credentials and were stopped before edits;
host launches kept workspace-write or read-only sandboxes and automatic review.

Codex config now has Magi approval for both magi and magi-omp, and
agents.max_concurrent_threads_per_session =10 (excluding coordinator). Both changes have
timestamped backups beside config.toml. The current task still rejected a fourth built-in
worker with 'agent thread limit reached'; reload/resume is required to test the new capacity.

Preserve unrelated untracked server/templates/randomizer.html. Preserve pre-existing dirty
sweep guide/register history. No push, master merge, parked-worktree deletion, live run,
or release claim occurred.

Next: after restart, read RESUME.md and the sole checkpoint; verify worker processes are
finished, review the frozen spec/tickets/binding edits, reconcile the shared-runner review,
then record concrete G0 evidence/authority before starting gated implementation. Do not
repeat the49-file grounding pass.

## Original complete Markdown inventory

Git blob IDs below identify the exact9c7e7ac source, independent of later working-tree edits.

| Path under docs/gen2 | Git blob at9c7e7ac | Reader |
| --- | --- | --- |
| GEN1_STANDARD_DIGEST.md | fe91b138974c9518c8fdc72819215c836a667fdf | Codex Wayfinder reader |
| GEN2_BINDING_PLAN.md | 699d58886bf8e96ec1531fbf74f63003d7004aaa | coordinator |
| GEN2_STANDARD_COMPARISON.md | 29b6f17103cfeb852a7454d15e388cef86597e0c | Codex Wayfinder reader |
| OPEN_QUESTIONS.md | e660b7f77d385aff2849f887c826c4b75ec195ba | coordinator |
| PLAN.md | f537d25010c750dcb6a847e9d83b55cb291d6582 | coordinator |
| RESUME.md | b570d50a88ec54285ffcb0b17273812c3d2b3c78 | coordinator |
| REVIEW_RECORD.md | e37df28611bcb97daede9a2333e95a57e004e451 | coordinator |
| gen2_requirements.md | a35a45c87e8ddb9dc43ea8d309f06b32cc22c11d | coordinator |
| research/archipelago_crystal.md | 3e99ccaa24763c68f870f5d7be036814c9f8626e | Codex research reader |
| research/bizhawk_gambatte_gbc.md | 354d0854ca342ce65a87a6895a0e1ecd2736fc0c | Codex research reader |
| research/codex_checkpoint_and_linktrade.md | 21e084cf6ff41bb4de7b2c6ff802db2ffd09fdfc | Codex research reader |
| research/codex_engine_site_audit.md | 576bb6bde97d1b8380c7d870aabc643ff58b3010 | Codex research reader |
| research/free_wram_survey.md | b22913370ae8fbc6e7d65cac0d5d158d41c8fa4d | Codex research reader |
| research/gamedb_and_encounters.md | 4dbc80fc3655b4322f626c119fa7aa4b8c7e6acd | Codex research reader |
| research/native_trade_entry.md | f4fd122954c83c1e80cade8323e7ce35bbff63ac | Codex research reader |
| research/omp_address_audit.md | d973d73d405950e00ce9466eac67d0ef68a36170 | Codex audit reader |
| research/omp_citation_audit.md | 45c1d7db14dbebed0470fbd4b50dda6848373089 | Codex audit reader |
| research/omp_citation_audit_2.md | 8a2360a432b7360b0cfd29073fa5e1d1c41aaef3 | Codex audit reader |
| research/omp_citation_audit_3.md | 28168d1402c07db065d85a37b9a71171c0bdaf32 | Codex audit reader |
| research/omp_layout_lease_audit.md | fe8ef8548bf9c0958a7435adfa1bf32f652ce640 | Codex audit reader |
| research/omp_symbol_lines.md | 202fe536d54dc9d2e074b8e0c6c02a56fd16f9f5 | Codex audit reader |
| research/peer_ghost_design.md | de185e82bf6699a56404517a06c85b95099c8a32 | Codex research reader |
| research/pret_gen2_symbols.md | 19304cde3ad92835e3e0b533721beffec150d24d | Codex research reader |
| research/rom_hashes.md | ac858fb29d06e00bd62a8a5f07928fefcbfc41da | Codex research reader |
| research/sound_sites_and_peer_ghost.md | 42de6be7ed9163d911d57ab16849104381dc88cd | Codex research reader |
| research/stat_control_and_fixture_budget.md | ca1ec2105c03f1a44b921c760259302c151be87a | Codex research reader |
| wayfinder/issues/01-destination.md | 1b2f3d3e736d5f271adf594c2c75c46d4aeaacd0 | Codex Wayfinder reader |
| wayfinder/issues/02-title-scope.md | ff29c2fc16d923e83d33b11f07f1b59e66e5a260 | Codex Wayfinder reader |
| wayfinder/issues/03-rewrite-vs-strangler.md | 0e830f424735c8cc6242a00b1c263f60ab3edb62 | Codex Wayfinder reader |
| wayfinder/issues/04-native-features.md | eb3f53291cb887e9db4fcd7b38fd6c1d46dbe12a | Codex Wayfinder reader |
| wayfinder/issues/05-pret-pins.md | c471e39f2656746edbf82410a9b50d0c885d69cd | Codex Wayfinder reader |
| wayfinder/issues/06-ledger-identity.md | 8b85d55ef8d31bf498bdb663b68f96e4b407e2aa | Codex Wayfinder reader |
| wayfinder/issues/07-fixtures-new-bark.md | 3ca41205b7823df41f57e2f646a3996fe1d53e45 | Codex Wayfinder reader |
| wayfinder/issues/08-archipelago-scope.md | 7b914f16b2f3c0f832e0d556be389630fb770b1c | Codex Wayfinder reader |
| wayfinder/issues/09-duo-pairing.md | dcd81ea6131cedb4dd6ed84c48760097de239b9a | Codex Wayfinder reader |
| wayfinder/issues/10-overworld-checkpoint-source.md | a823a30bc93069fc8162d6ebb8b33a5a771879f6 | Codex Wayfinder reader |
| wayfinder/issues/11-pinned-rom-build.md | 54ae6db1bf63c50819e519ea2015ab0cf8bcb946 | Codex Wayfinder reader |
| wayfinder/issues/12-engine-sites.md | cc507b105280279fadfd369009326439c593e3e9 | Codex Wayfinder reader |
| wayfinder/issues/13-link-trade-routine.md | 0b41e4ed73881b2e015908660e884c955f8c3583 | Codex Wayfinder reader |
| wayfinder/issues/14-free-wram-survey.md | 6c027f1a756917fea7cc639f1d8fe54b6e551a42 | Codex Wayfinder reader |
| wayfinder/issues/15-native-trade-design.md | 440294940ee1e1da220d8032a2e14168afec0295 | Codex Wayfinder reader |
| wayfinder/issues/16-native-sound-sites.md | 959ebe9e62c45cfb82976505e6b35d8239f3b2b4 | Codex Wayfinder reader |
| wayfinder/issues/17-peer-ghost-feasibility.md | 75088ef04acb0c957120c7fd62a1b292858bdb31 | Codex Wayfinder reader |
| wayfinder/issues/18-cgb-mode-and-gamedb.md | 038243075821e502a16f3ab95a6f44638e80256e | Codex Wayfinder reader |
| wayfinder/issues/19-crystal-revision.md | 370af39eca726d54c3a74b7e8a596c66ddbb86b7 | Codex Wayfinder reader |
| wayfinder/issues/20-stat-control.md | ca910a112f765962edfee94a1173f60a2b0dcb36 | Codex Wayfinder reader |
| wayfinder/issues/21-encounter-tables.md | a1b86f6d0109277374119e9db029091855add161 | Codex Wayfinder reader |
| wayfinder/issues/22-fixture-frame-budget.md | ddcfd16847ecf15602e04c92bbcb18097aafac11 | Codex Wayfinder reader |
| wayfinder/map.md | 050d28f990ed2a17e41ade6191e7c9e368953bfc | Codex Wayfinder reader |
