# Gen 1 current truth, 2026-09-10

Reconciliation of the 49 files in `docs/gen1_reference/` (48 plus today's interim ledger), `../gen1_gen2_runtime_checks.md`, `../shared-subsystem-map.md`, `../shared-*.md` (titles only), `../../README.md` and the repo-root `CLAUDE.md` (gitignored; not present in this worktree) against the code in this worktree. Read-only: no existing doc was edited. Links are relative to this directory.

## 0. Two facts that frame every other claim

| Fact | Evidence |
| --- | --- |
| **Two Gen 1 runtimes coexist.** *Legacy*: `lua/clients/gen1_rby_client.lua` (routed by `../../lua/slink.lua:83`), legacy server dispatcher, `tests/live/test_gen1_gates.py`, `tests/e2e/test_duo_gen1.py`. README, CLAUDE.md, `gen1_gen2_runtime_checks.md` and `docs/REFERENCE.md` describe **this one**. *Durable RC*: `lua/gen1_client_entry.lua` (`slink.lua:27`, protocol `slink-gen1-durable-v1`), `server/gen1_runtime*.py`, `server/gen1_launcher.py` closures. Everything in `docs/gen1_reference/` describes **this one**. | `../../lua/slink.lua:12-27,83`; [RC_NOTES.md:88-93](RC_NOTES.md) |
| **Nothing from Sept 6-10 is committed.** HEAD `79d5172` is dated 2026-08-30. The worktree carries 63 modified tracked files (+6534/-2876) and 604 untracked files (197 unit tests, 47 Lua tests, 29 live tests, 9 integration, 31 data, 5 patch, ~40 tools). The entire `docs/gen1_reference/` directory is itself untracked. The only copy outside git is the Sept 10 snapshot. | `git log -1`, `git status`; [INTERIM_LEDGER_2026-09-10.md](INTERIM_LEDGER_2026-09-10.md) item 8 |

Default durable launchers are **held service**: `create_runtime(..., ordinary_frames=False)` (`../../server/gen1_run_config.py:97`); ordinary frames and native trade are opt-in flags. The complete Gen 1 release gate is **NO-GO** ([RC_STATUS_AND_ESTIMATE.md:5-6](RC_STATUS_AND_ESTIMATE.md)).

## 1. Proven live (emulator ran, evidence path exists)

| Feature | Runtime | Cartridges | Doc | Evidence | Date |
| --- | --- | --- | --- | --- | --- |
| Gate suite: keys, PP-Up mask, bag gate, `force_faint`, box round-trip, 404-byte rival write, patch beacon, AP detection + vanilla controls | legacy | R/B/Y, R/B patched, R/B AP | [../gen1_gen2_runtime_checks.md](../gen1_gen2_runtime_checks.md) | `tests/live/test_gen1_gates.py` (24 nodes at HEAD, 56 in worktree) | 08-30 |
| Duo E2E, 9 scenarios (faint, boxsync, memorialize to Box 12, rivalswap, explode_g1, whiteout, playthrough, deadzone, dupes); `KNOWN_FAILING = {}` | legacy | Red/Blue, Yellow/Red; Route 1 only (1 of 39 areas) | README:16; runtime_checks:37-40 | `tests/e2e/test_duo_gen1.py:79,99` | 08-30 |
| Gambatte execution hold, 18 host cases | durable | R/B/Y | [GAMBATTE_EXECUTION_HOLD.md](GAMBATTE_EXECUTION_HOLD.md) | `gambatte_execution_observations.json` | 09-06 |
| Native trade: receptionist, partner YES/NO, both animations, both verified 32 KiB saves, all 9 ordered pairs incl. Y/Y; 16-case receptionist/save matrix; 6-case TCP wiring | durable | all 9 pairings + UPR Y/Y | [NATIVE_UI_CLIENT.md](NATIVE_UI_CLIENT.md), [RECEPTIONIST_SAVE_RUNTIME.md](RECEPTIONIST_SAVE_RUNTIME.md), [NATIVE_RUNTIME_WIRING.md](NATIVE_RUNTIME_WIRING.md) | `.cache/native-ui-pairs.xml`, `.cache/receptionist-save-live.xml`, `.cache/full-rule-paired-current.xml` | 09-06/07 |
| Full-save oracle, 24 SaveGameData comparisons | durable | R/B/Y | RECEPTIONIST_SAVE_RUNTIME.md:29-33 | `.cache/full-save-oracle.xml` | 09-07 |
| Panel ABI-3: 12 scenarios per cart + 144-scenario map/Pokedex matrix; browser patcher 31 Chrome scenarios; UPR final-cartridge 13 | durable | R/B (panel), R/B/Y (UPR) | [PANEL_ABI3.md](PANEL_ABI3.md), [BROWSER_PATCHER_RC.md](BROWSER_PATCHER_RC.md), [UPR_RC_PIPELINE.md](UPR_RC_PIPELINE.md) | `.cache/panel-map-matrix.xml`, `.cache/browser-patcher-final.xml` | 09-07 |
| Cold New Game + initial SaveRAM write/readback, screenshots inspected | durable | Y/Y, R/B, B/Y | [BOOTSTRAP_PROOF.md](BOOTSTRAP_PROOF.md), [SEPT8_EVIDENCE_REGISTRATION.md:106-111](SEPT8_EVIDENCE_REGISTRATION.md) | `.cache/initial-save-launcher-live.xml`, `tests/live/test_gen1_bootstrap_launcher.py` | 09-08 |
| Held overworld faint write via one-use permit, 10 launcher cases | durable | Y/Y, R/B, B/Y | [HELD_FAINT_AUTHORITY.md](HELD_FAINT_AUTHORITY.md) | `.cache/held-faint-final-live.xml` | 09-08 |
| Paired memorial (compact delta, flush, readback, ACK), 7 cases | durable | incl. Y/Y | [MEMORIAL_SAVE_PROOF.md](MEMORIAL_SAVE_PROOF.md) "Production integration completed" | `.cache/memorial-bounded-final-live.xml` | 09-08 |
| Capture delivery observer (party/box, Yellow boxed Kadabra); engine faint/starter signals; ball activation | durable | R/B/Y | [CAPTURE_DELIVERY_PROOF.md](CAPTURE_DELIVERY_PROOF.md), [ENGINE_SIGNALS.md](ENGINE_SIGNALS.md), [BALL_AND_FAINT_SETTLEMENT.md](BALL_AND_FAINT_SETTLEMENT.md) | `.cache/capture-delivery-final-live.xml`, `.cache/ball-live.xml` | 09-08 |
| Input-only cold route: both Oak tutorials, both starters source-settled and linked, into the rival battle | durable | Y/Y | [TRAINER_IDENTITY_BORROW.md:47-53](TRAINER_IDENTITY_BORROW.md) | `.cache/cold-native-launcher-03kuvxcx` | 09-09 |
| Ordinary bedroom frames through the real launcher/server: 323/310 frames at about 28 FPS | durable | Y/Y | [ORDINARY_FRAME_TURNOVER_PROFILE.md](ORDINARY_FRAME_TURNOVER_PROFILE.md) | `.cache/ordinary-turnover-profile.json` | 09-09 |
| Battle force-faint **prototype**: `loop_head`, benched, Transform, and (today) `player_action` under the bounded owner | prototype, not shipped | R/B/Y | [BATTLE_FORCE_FAINT_WINDOW.md](BATTLE_FORCE_FAINT_WINDOW.md) sections 10-11 | `.cache/junit/fight_first_{red,blue,yellow}.xml` (1 pass each, 20:43-20:46), `.cache/battle-force-{red-_szi2_ql,blue-aw5pdf5q,yellow-jrkjd73j}/summary.json` `passed: true` | 09-10 |

## 2. Unit/integration only (no emulator for the feature)

| Feature | Tests | Live check still missing |
| --- | --- | --- |
| Scripted grants (`GivePokemon`) + acquisition settlement | `test_gen1_grant_receipt.py` (168), `test_gen1_acquisition_runtime.py` (13), `test_gen1_grant_observer.py` (12) | A real NPC grant (Celadon Eevee), per [GRANT_DELIVERY_PROOF.md](GRANT_DELIVERY_PROOF.md) "Not covered" |
| Static battle origin; NPC in-game exchange | `test_gen1_static_*`, `test_gen1_npc_exchange_*` | "no emulator ran" in [STATIC_ORIGIN_PROOF.md](STATIC_ORIGIN_PROOF.md) and [NPC_EXCHANGE_PROOF.md](NPC_EXCHANGE_PROOF.md) |
| Wild encounter / no-catch / paired retirement | modeled memory + real journal | Root dispatcher registration and a live no-catch campaign, [WILD_ENCOUNTER_LIFECYCLE.md:94-102](WILD_ENCOUNTER_LIFECYCLE.md) |
| Storage disposition (quarantine, archive return, Box 12 relocation) | `.cache/storage-rc-consolidated.xml` | Live PC campaign, reset/reload, [STORAGE_DISPOSITION_PROOF.md:91-99](STORAGE_DISPOSITION_PROOF.md) |
| Ordinary evolution lane | all R/B/Y kernels, Y/Y and R/B handlers | "the existing old evolution gate is research, not evidence this lane ran", [ORDINARY_EVOLUTION.md:83-87](ORDINARY_EVOLUTION.md) |
| Trainer-name borrow guard | 96 focused (`.cache/gen1-identity-guard.xml`) | Only the partial cold route above |
| Initial-save kernel/lifecycle, bootstrap enrollment | 49 + 29 + 34 (SEPT8 table) | New-game **reload** unqualified, SEPT8:110-111 |
| Battle force-faint production integration | none; the test list is a proposal | Everything: [BATTLE_FORCE_INTEGRATION.md](BATTLE_FORCE_INTEGRATION.md) "No production file was edited" |

## 3. Open / NO-GO

| Item | Named by |
| --- | --- |
| Ordinary frames are refused once **any player has Poke Balls**, or any command is pending, or any non-initial blocker exists | `../../server/gen1_frame_control.py:44-53`; BATTLE_FORCE_INTEGRATION.md section 4.0 |
| Cold route never reached the Center: grant-response deadline at player b frame 13942 | [COLD_ROUTE_RESPONSE_TIMING.md](COLD_ROUTE_RESPONSE_TIMING.md); RC_STATUS:13 |
| 28 FPS is not vanilla speed; continuous gameplay unqualified | ORDINARY_FRAME_TURNOVER_PROFILE.md:79-82; RC_STATUS:12 |
| Battle force-faint: no production enable; Explode Mode and Rival Swap refused in the durable path | RC_STATUS:17-18; BALL_AND_FAINT_SETTLEMENT.md:32-33 |
| Reset/load/rewind recovery matrix; new-core rebind | RC_STATUS:19; ../shared-subsystem-map.md:44 |
| UI E2E: 30 cases fail on the guarded `/api/debug/set_pokeballs` initializer | RC_STATUS:256-257; RC_NOTES:145-147 |
| Live grant / static / NPC / wild / storage / evolution campaigns | table 2 |
| Human two-player session: `human.two-player: MISSING PROOF`; the release lane cannot start on this machine: `verify_gen1_release.py --verify-inputs` FAIL (no `SLINK_EMUHAWK`, no `SLINK_UPR_JAR`) | `.cache/junit/pins_2026-09-10.log` |
| Fresh broad unit/integration run after the Sept 9 changes | INTERIM_LEDGER item 2 (no `.cache/junit/broad_2026-09-10.xml`) |
| Legacy client: 1 of 39 areas, no map transition, whiteout/gender/type clauses injected | ../gen1_gen2_runtime_checks.md:161-172 |
| SFX: closed, will not ship | ../gen1_gen2_runtime_checks.md:26,95-122 |

## 4. Contradictions and stale claims

| # | Sources | Current | How determined |
| --- | --- | --- | --- |
| 1 | **Memorial box.** `../../README.md:85` "Box 14"; root `CLAUDE.md:143` "Box 13 (UI Box 14)"; `../REFERENCE.md:248,690,723` same | Gen 1 = **Box 12 (index 11)**; Gen 2 = Box 14 (index 13); Gen 3 = index 13. README/CLAUDE quote the Gen 3 number as if universal | `../../server/adapters/gen1_rby.py:609-615` returns 11; `gen1_memorial_policy.py:19` `GRAVE_BOX = 11`; `gen1_memorial.py:20` `GRAVE = 0x75EA`; `lua/clients/gen1_rby_client.lua:644`; `lua/games/gen1_rby.lua:81-82`; `gen2_crystal.py:390-391`. `gen1_gen2_runtime_checks.md:22,39,86` is right |
| 2 | `../../server/adapters/base.py:486-492` docstring: "Returns -1 if the game has no dedicated memorial box (Gen 1/2)" | Stale: both override (11, 13) | code |
| 3 | **Unit counts.** CLAUDE.md:28 "~1450"; README:261 "~1600"; runtime_checks:14 and REFERENCE:849 "1595 passed"; RC_STATUS:42 "5,902"; SEPT8 "5,904 nodes" | Both right for different trees: HEAD-tracked = 1500 `def test_` in 69 files (about 1595 collected); worktree = 2779 defs in 266 files, i.e. 5,756 unit + 148 integration (`tests/gen1_release_inventory.json`) | `git ls-files` vs working-tree grep |
| 4 | **Gate counts.** CLAUDE.md:49 "8 gates"; runtime_checks:16 "18: 4 gates x 3 + patched + AP"; README:265 "Gen 1 (24)" | HEAD `test_gen1_gates.py` = 5 gates x 3 + 2 + 2 + 4 + 1 = **24** (README current); the worktree file = 56 nodes; the whole live lane = 267 | `git show HEAD:tests/live/test_gen1_gates.py` |
| 5 | **Explode Mode.** README:99-101 and CLAUDE.md:147 "only active on Radical Red; vanilla no-op" vs CLAUDE.md:11 and runtime_checks:40 "Explode Mode proven on Gen 1" | Legacy Gen 1 supports it (`gen1_rby.py:367-371` returns True; duo `explode_g1` with `--explode-mode`, `tools/e2e_duo.py:160`); the durable path refuses it (BALL_AND_FAINT:32-33). README/CLAUDE "RR-only" is stale | code |
| 6 | `runtime_checks.md:172` "`red_ap`/`blue_ap` never launched under an emulator" vs `:16` "+ AP" in the live lane | The live gate exists at HEAD (`test_gen1_archipelago`, `test_gen1_gates.py:141-145`); line 172 is stale. Whether it passed is not shown by any artifact here | code |
| 7 | [MEMORIAL_SAVE_PROOF.md:3-5](MEMORIAL_SAVE_PROOF.md) "not yet connected to the durable command router"; `../shared-subsystem-map.md:11` "prepared execution and durable reservation integration still required" | Stale: MEMORIAL_SAVE_PROOF:82-84 says integrated Sept 8; `server/gen1_memorial_runtime.py` exists and is imported by `gen1_runtime.py`, `gen1_runtime_state.py`, `gen1_faint_runtime.py` | grep |
| 8 | [GRANT_DELIVERY_PROOF.md:142-145](GRANT_DELIVERY_PROOF.md) "observer not yet wired into the client; `acquisitions` bundle field unknown" | Stale: `lua/gen1_frame_client.lua:191-193` wires `options.acquisitions`; `server/gen1_frame_acquisitions.py` (09-09); `gen1_launcher.py` `ORDINARY_FILES` ships the grant/capture observers; RC_STATUS:14 | grep |
| 9 | [BATTLE_FORCE_FAINT_WINDOW.md:3-10](BATTLE_FORCE_FAINT_WINDOW.md) "nothing here prototypes one; only this document and a pinning test are delivered" vs its own sections 9-11 | The head is stale; sections 9-11 plus `lua/instruction_executor.lua`, `lua/battle_force_authority.lua`, `tests/live/test_gen1_battle_force.py` exist. Still **not shipped**: in no `gen1_launcher.py` tuple, not required by `gen1_client_entry.lua`; the `PROTOTYPE, not wired` file headers are accurate | grep |
| 10 | Launcher closure: [LAUNCHER_SELECTION.md:30](LAUNCHER_SELECTION.md) "25-file"; [COMPANION_ADMISSION.md:25](COMPANION_ADMISSION.md) "27-file"; [RC_INTEGRATION.md:47](RC_INTEGRATION.md) "28-file" | `FILES` = 28 (+23 observation, +20 ordinary, +11 native) | `gen1_launcher.py:8-45` |
| 11 | RC_STATUS:13 cold route "reached the end of the rival battle" vs COLD_ROUTE_RESPONSE_TIMING:3-4 and TRAINER_IDENTITY_BORROW:50-51 "stopped **during** the rival battle at frame 13942" | "during"; the detailed docs are primary | text |
| 12 | RC_STATUS:258 "346 acceptance requirements: 36 current / 109 stale / 201 no proof" | `tests/gen1_release_requirements.json` now has 388; the split is unrefreshed | JSON |
| 13 | [INTERIM_LEDGER_2026-09-10.md](INTERIM_LEDGER_2026-09-10.md) items 1 and 7 "todo" | Item 1 done: `fight_first` passed red/blue/yellow at 20:43-20:46. Item 7 ran: addresses 600/600 and 702/702 ok, constants 87/87, canonical sources 103 checks, ROM layout exit 0 (`.cache/junit/pins_2026-09-10.log`) | file mtimes vs the ledger's 20:42 |
| 14 | [TEMPORAL_INVENTORY.md:4-6](TEMPORAL_INVENTORY.md) "the launcher still fixes its frame; a future execution binding must own later checkpoints" | True for held launchers only; the ordinary frame client now publishes inventory per closed range (BATTLE_FORCE_INTEGRATION section 0.4) | code |

No future or mis-ordered dates were found; the only date oddity is fact 0.2 (docs dated Sept 6-10 on an Aug 30 HEAD).

## 5. Concerns

- `../../server/gen1_frame_control.py:50-53`: the pre-ball ceiling makes every "ordinary gameplay" claim end at the first Mart; it is a policy line, not a bug, but nothing past it can be qualified until root lifts it.
- `../../lua/gen1_frame_client.lua:146-150`: `commands_pending()` freezes request/authorize/step while any inbox command lacks an outcome, and a `force_faint` delivered mid-battle can never become safe (`gen1_held_faint.lua:38-40`): a live deadlock (BATTLE_FORCE_INTEGRATION section 4.1), unfixed.
- `tests/unit/test_gen1_acquisition_runtime.py:180` asserts `boxed_deferred`; `server/gen1_acquisition_runtime.py:256` now yields `exempt_grant`/`clause_checked`, and STORAGE_DISPOSITION_PROOF:87-89 says new acquisitions no longer enter that placeholder. The ledger's "root-owned regression" is the test encoding the pre-Sept 9 policy; root must pick a side.
- `../../server/adapters/base.py:486-492`: the base contract lies about Gen 1/2 (item 4.2).
- `lua/instruction_executor.lua:90` marks the challenge used even on `not_reached`; wiring it as-is would need a fresh challenge per frame (BATTLE_FORCE_INTEGRATION section 4.2).
- The grant deadline is fixed at 60 frames / 1000 ms (`gen1_frame_control.py:88`) while the journal grows (24 MB when the cold route timed out); expect the frame-13942 failure to recur on long runs.
- 604 untracked files on an Aug 30 HEAD: one `git clean` loses eleven days; the Sept 10 snapshot is the only other copy.
