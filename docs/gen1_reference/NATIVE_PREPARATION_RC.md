# Native preparation and suspension continuation

All implementation and evidence remains in gen1-rby-code-sweep-8d06e2.
These components advance the RC; generated clients still use held_service.

## Preparation

`lua/gen1_trade_preparation.lua` captures the actual party and complete party
storage, raw trainer name, map, active WRAM box, current-box flag and full CartRAM.
It uses the existing profile and readers, persists an intent through the shared
command executor/journal, and emits typed `trade_ready` without RAM writes or
emulated frames. Changed context, box or save after preparation refuses completion.

`server/gen1_trade_preparation.py` independently checks the proposed member,
complete party storage, valid canonical save/checksum and save trainer identity.
It derives occupied keys from the active WRAM box and the other initialized SRAM
boxes, including box12. It ignores the active box's stale SRAM slot and inactive
storage before the cartridge's first ChangeBox initialization. Box checks here
cover identity/list structure and collisions; full boxed stats/save-engine
qualification remains a separate gate.

Preparation derives the evolution species from the exact recipient ROM through
`TradeResultRules`. Move-learning alternatives are retained for native input;
preparation does not pick a replacement move. Partner text uses the observed
trainer's actual eleven raw name bytes instead of the previous fixture name.
The validated receipt produces a checkpoint digest. The native adapter rechecks
that digest before staging COMMIT, so accepted readiness cannot survive changed
party/save/box bytes. Existing isolated legacy mechanism fixtures can still omit
this field; the new preparation verifier always supplies it.

The paired native driver now uses these real preparation modules and typed
journal events. Offer/partner UI, animation, save flush and readback remain actual
cartridge operations. File transport, bootstrap and private host authority are
still explicit test fixtures; these tests do not activate the production router.

## Suspension

The shared `DurableRuntime._before_suspend(reason)` hook runs after its hold
notice and before the final suspended-state commit. Its default does nothing.
Failures retain the shared lifecycle's unconditional owner/challenge invalidation.
The RBY binding uses it to journal the existing coordinator's interrupt transition;
reopening a configured runtime also records unfinished-trade interruption.

| Persisted phase | On disconnect, watchdog expiry or reopen |
| --- | --- |
| Offered, preparing, both prepared | Cancel; retain existing commands and queue both abort obligations |
| COMMIT persisted or partially verified | Preserve phase, COMMIT commands, applied/verified receipts and ownership; require native recovery |
| Terminal with pending closure | Retain closure obligations; do not manufacture a new abort or release |

The internal suspension capability authorizes only interrupt, never commit,
delivery or gameplay. Reconnecting sockets does not qualify physical recovery.
There are separate atomic commits for interruption and final runtime suspension;
the interrupted trade already carries its recovery blocker if the process ends
between them. Journaling failure clears connection authority and requires reopen.

## Native release

The arming lease now retains the full prepared intent independently of the
command inbox. Acknowledging and pruning the COMMIT cannot lose the token/context
needed by later paired finalization. `native.release_executor()` composes with the
existing command executor and typed journal callbacks. It persists a release
intent before the native return, retains a command-bound releasing/released lease,
then publishes exact closure readback. The server checks that receipt against the
finalized transaction and previously verified native party/save result.

Both release commands are now acknowledged through real typed journal events in
the paired test. A failed local release-receipt publication can reopen its stores
and reproduce that receipt from the already released checkpoint without another
trade or release write. This narrowly qualifies receipt persistence/replay in the
same owned physical test context. It is not controlled recovery from an arbitrary
reset/load, a replaced emulator core, or an ambiguous partially published release.

## Evidence cutoff

- `.cache/preparation-unit-final.xml`:34 portable checks passed,2.60s.
- `.cache/preparation-pairs.xml`:all9 ordered RBY pairs passed,111.60s; both
  actual animations and separate verified SaveRAM files, including Yellow/Yellow.
- `.cache/preparation-upr-paced-second.xml`:4 cases passed,139.27s; combined
  UPR R/B,B/Y,Y/Y plus Yellow/Yellow at cartridge speed.
- `.cache/suspension-second.xml`:88 server lifecycle/trade regressions passed,
  23.51s, including18 new interruption/refusal/failure cases.
- `.cache/preparation-upr-methods.xml`:8 final-ROM cases passed,212.51s; all four
  trade-evolution species under combined UPR on R/B and Y/Y.
- `.cache/native-release-pairs.xml`:12 cases passed,155.19s; all9 ordered pairs
  plus3 release-receipt publication failures with reopen, retained native intent,
  both typed closure ACKs and no pending server commands. Both original animations
  execute once, including identical Yellow/Yellow parties.
- `.cache/native-release-regression.xml`:9 native entry/identical-byte/arming and
  receipt-failure regressions passed,62.03s.
- `.cache/native-release-unit.xml`:47 preparation/closure checks passed,2.65s.
- `.cache/preparation-full.xml`:4,604 unit/integration tests passed,2 existing
  Windows symlink skips,189.09s. These skips do not waive any required RC lane.
- `.cache/native-release-upr-final.xml`:4 final combined-UPR cases passed after
  the typed release integration,141.19s; R/B,B/Y,Y/Y and paced Y/Y now also retire
  both server release obligations through verified closure receipts.

An initial UPR invocation used the system pytest temp directory and failed before
emulator launch because generated ROM paths must remain inside the worktree.
The corrected invocation used an explicit unique `.cache` basetemp. This was a
test invocation error, not evidence of cartridge failure.

Next: production physical command verification, router and frame scheduler;
ordinary observation/bootstrap; actual cancellation/closure scheduling and controlled
recovery; campaign/storage/acquisition gates; final packaging and human session.
The shared suspension hook is published at e1d2acf9edeb6fabd059854a399caef92e1c1d67
on codex/shared-suspension-hook-v1. The RBY preparation/release/controller APIs
remain unfrozen. The actual worktree HEAD and index were not moved by publication.
