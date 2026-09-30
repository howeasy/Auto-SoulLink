# T5 native carrier and FR/LG pairings

Branch `codex/gen3-t5-fr-duo`, worktree `C:/slink-wt/g3-t5-fr-duo`.
This card runs no emulator. Its new native-carrier rows remain **UNRUN** until
the coordinator runs the commands below and their independent oracles pass.

The preceding `d0fee98a` FR/FR rows passed on the coordinator's lane, attempt 1,
including cold reloads and PYDEC. Both `C:/slink-wt/t5-trade.log` and
`C:/slink-wt/t5-decline.log` bind their source to that commit and report PASS.
Those receipts retain their HARNESS_ONLY selection disclosure. They are not
native-carrier or mixed-title evidence.

## Composition and private artifacts

Integration `66184e35595578da7c8edbd00b08daf32015542d` was merged first as
`daaa93cd`. The only conflict was adjacent method additions in `e2e_duo.py`;
both the T5 and clause/gift methods were retained. Merge controls: 367 passed,
1 skip. The integration's clause, release, gift/egg and rival changes remain.

Emerald confirmed producer `f8371d274f721063eee7d8b23ac85565925bc387`; it was
merged cleanly as `c218ee4`. ABI2 mailbox/witness/CONTROL layouts are unchanged.
The private candidates advertise mask 23 (trade/panel/sound/rival), READY 0 and
`production:false`. The later Emerald lifecycle/Match Call MODEL files from
that branch add no Emerald candidate or physical claim. Producer checks: 15 pass.

Both candidates were rebuilt offline from the owner's pinned clean ROMs:

| Title | ROM SHA1 | ROM SHA256 |
| --- | --- | --- |
| FireRed | `10109d33a937af6182827a5b0b36abccfaabd1c9` | `421f72aa88f3eda47bbf316cde7a1aac8369aaabae3188987123f1bb7a990007` |
| LeafGreen | `e651983a7e0d3cbd8810c76252755d2f09bd9bf0` | `a0e5fe73b888f86abf8d9722703334a3afd1ee5f68d56ed7f8e6ef08eec48db0` |

No ROM or UPS is committed. Preflight undoes the exact source-bound patch spans
and requires the clean title's SHA1. A manifest for each player binds that
player/title, candidate, private packs, hooks and source files. Both manifests
share one nonce and isolated real journal; SaveRAM remains per player and run.
The ordinary bootstrap still refuses both candidates with the nonce set.
The harness alone selects the private production projection. Schema v3 refuses
the old selection-seam manifests.

## Native input and evidence path

`gen3_fr_trade` is A=FR/B=LG; `gen3_lg_trade` is A=LG/B=FR. Both retain the two
scenario names `native_trade_firered` and `native_trade_decline_firered` for the
existing runner interface. These rows are absent from normal game selections.
Each title uses its own `*_party_town{,_b}.sav`, with the previous disclosed
SYNTH edit confined to slot 1's species/item/mail/ability. No map/story/identity
or box edit is introduced.

The native adapter binds CONTROL.session_epoch to the mailbox epoch, queues
TN_ENABLE at the normal write checkpoint, and reads PI_COUNT as u32. It emits
trade_request only for a new counter edge with the configured epoch and no
owned transaction. Counter baselines/discontinuities do not manufacture talks.
LG construction retains the same explicit production metadata requirement as FR.

The driver walks A from Viridian's south edge into the Center, faces the native
NPC and presses A. It selects Trade in opcode 22, the linked slot in opcode 20,
and uses A/B for B's opcode-17 offer. Only joypad input answers the native UI.
The harness no longer sends trade_request/menu_result/mon_chosen or suppresses
server prompts. Native PREPARE consent/save, SCENE/evolution/post-save, real host
flush, journal settlement and cold reload remain mandatory.

The Center NPC auto-arms in this producer. These rows do not claim manual
opcode-13 peer-object arming or ghost interaction. The normal-input route reuses
the FR/LG helper exercised by the producer's single-cartridge carrier tests;
title-shifted chooser/save addresses come from each title's pinned pret symbols.

Python independently reads dumped CONTROL/object/avatar bytes, mailbox and
carrier-state bytes, copied text/options, field callbacks and script state.
It requires the native counter edge before trade_request, matching ownership
and ACK sequences, the actual chooser engine entry, safe field return, and wire
answers matching both the native result and server command. UI epoch/token are
bound to the durable transaction. The chooser's multi-frame initialization is
recorded once per command. Missing or altered witnesses fail by name.

The existing saved-flash/party/evolution/journal/final/reload oracles remain.
A reload which starts another NPC/UI/trade/save operation fails. The receipt
reports native carrier completion only after observing the role's native UI
ownership; the final Python gate independently checks its bytes. Candidate-only
admission remains disclosed separately from the native UI evidence.

## Review follow-ups included

- F1/F2: hello_fields records actual visibility. A terminal report waits for a
  visible HELLO and the normal field checkpoint. Borrowed/hidden parties and
  a closed checkpoint retain the report; the model observes no HELLO spin.
  Uncertainty declarations intentionally precede the later visible recovery
  HELLO and remain exempt. A replayed apply during hidden-journal recovery
  cannot invent an unchanged report ahead of that declaration.
- F6/F7: held trade jobs yield via `ready`, preserving cheap per-frame ownership,
  capability and deadline checks. Expensive party/witness validation runs at
  most every 30 held frames, and runs fresh on dispatch. Caller dispatch
  deadlines are carried into the native queue. Published scenes are not retried.
- The write-sink prose now states per-write-call revalidation in a frame-bound
  window. A state change during staging refuses the next write call. Dispatch
  refuses staging that overlaps the opcode, publishes it last and immediately
  closes the window. Mid-write throws record partial attempted/completed extents
  before rethrowing, including the partial entry of a whole-plan write.

Emerald-2's separate RR recovery opt-out and optional per-report outbox predicate
are not imported by this card. Their integration must preserve this card's
visible-HELLO check and the declaration-before-visible-recovery exception.

## Unit receipt and coordinator commands

The focused client/native/entry/safety/trade/server/harness gate passed **1,492
tests in 72.63s**, no skips. Log `.cache/t5-native-carrier-focused.txt`, SHA256
`0d316f2e7159e86cc9edea08fc63b8cf8016b3a931f3b27e462c4c904134eeb9`.
Additional oracle/observer controls cover missing/altered native witnesses,
foreign epoch/token, wrong title/player, duplicate chooser initialization and
quiet cold reload. Red controls reproduced the old absent CONTROL/LG binding,
counter truncation, hidden terminal report, blocked queue, missing partial
receipt and early opcode staging before their fixes. Full-suite result follows
in the final receipt; focused passes do not qualify physical behavior.

Run one emulator lane, after checking out the completed source commit. The
builds below are offline; the two runner commands execute four live rows, once
each, and preserve their isolated data. Only the coordinator launches them.

```powershell
$env:SLINK_ARMGCC='E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin'
python patch/tools/build.py --target firered --trade-candidate --rom 'E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba'
python patch/tools/build.py --target leafgreen --trade-candidate --rom 'E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba'
python tools/e2e_duo.py --game gen3_fr_trade --scenario all --lane t5-frlg-native --keep-data --wire-log
python tools/e2e_duo.py --game gen3_lg_trade --scenario all --lane t5-lgfr-native --keep-data --wire-log
```

Both orientations use the same legacy top-level result-file names. Cleanup
archives each nonce-bound initial/reload receipt byte-for-byte under the retained
data directory's `receipts/`, with SHA256s, before another orientation reuses the
top-level names. Foreign/stale nonce files are not adopted. Initial PASS alone is insufficient: both cold reloads and the
Python witness/save oracle must pass. READY stays 0, and this card publishes no
production admission or release qualification.

## Final full-unit receipt — 2026-09-27

Implementation `5e823a73`; test-only compatibility follow-up
`8fd5ce71eea256725108c014258cf4c93d8b19ed`. The latter was the source HEAD for
the completed full gate. No implementation changed between those commits.

```text
source /c/slink-wt/g3-env.sh
python -m pytest tests/unit -q -p no:randomly -n 2 --dist=loadfile --maxfail=1 -o tmp_path_retention_policy=failed
15395 passed, 1519 skipped, 2 warnings in 1433.01s (0:23:53)
Exit code: 0
```

Additional process-local bindings: `PYTHONPATH=C:/slink-wt/g3-t5-fr-duo/.cache/test-deps`
(pytest-xdist 3.8.0/execnet 2.1.1), `SLINK_ARMGCC` as above, and
TEMP/TMP/TMPDIR=`D:/slink-wt/g3-t5-fr-duo-test-temp`.
Full output: `.cache/t5-native-carrier-full-unit-retry.txt`, SHA256
`fdd8dc2f311b5d5a3fc12361bc941fa40d5721acab34ad80929ef0d4031c03c5`.
The skips are not qualification passes. Both warnings are existing invalid
`\c` string escapes observed by the legacy-runtime AST check; they are not failures.

The first full run stopped at 11,606 passes/1,311 skips because
`test_core_deferred.py` required an empty log after a sink throw. The requested
partial-write logging intentionally changes that expectation. `8fd5ce71` checks
the partial receipt (one completed byte/two attempted) and retains the same
uncertain/no-retry outcome. Its 135 related controls passed before rerunning the
entire suite. The first-run log remains `.cache/t5-native-carrier-full-unit.txt`,
SHA256 `f8b433f5db28b67066f62d2db6dd407b1107b417509031e93223032c3672a068`.

The final targeted carrier/oracle/observer gate passed 111 tests. Ruff passed;
all 311 Lua files parsed, including all eight changed modules under Lua 5.4.
Generated profiles are current. Both candidate identities still match the table
above, with mask 23, READY 0 and `production:false`. The four coordinator-generated
wire files remain untracked and untouched. No emulator, master merge, or push was
performed by this card. All four new native-carrier live rows remain **UNRUN**.
