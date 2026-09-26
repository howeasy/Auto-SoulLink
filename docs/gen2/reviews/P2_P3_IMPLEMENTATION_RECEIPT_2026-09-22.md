# Gen 2 source and component receipt — 2026-09-22

This records the reviewed P2 source frontier and local P3 candidates. It is not a
gate signature, runtime admission or PHYSICAL qualification. The sole dispatch
ledger remains the sweep RC_MASTER_GUIDE checkpoint.

## P2 source cut

Base is P1 commit93ccb8ee5a12ad892b9db04bbf7341572fc63675 on codex/gen2-foundation.
The P1 four-ROM reproduction and two successful GitHub runs are recorded separately
in [P1_BUILD_RECEIPT_2026-09-22.md](P1_BUILD_RECEIPT_2026-09-22.md).

The coordinator ran19 focused source suites together: **381 passed, zero skipped**
in245seconds. Log: implementation .cache/gen2-build/receipts/p2-source-suite.txt.
This included actual pinned-source/ROM generator checks and all three-title reader
comparisons. The separate final release-runner suite passed40tests; the shared
accounting/Gen1/Gen2 wrappers previously passed74tests with zero skips.

| Component | Accepted source/model evidence | Independent review |
| --- | --- | --- |
| Source helper and profiles | Immutable pinned Git blob reads; 48/32-byte geometry; source constants and bank facts; additive save spans and16flat-storage facts per title | p1_build_runner found and closed source-read race; p1_refusal_tests reviewed save facts; coordinator and box consumer checked all42backing/3active flat positions directly against raw pinned symbols |
| Species/evolution | 251species per title, native Egg marker253,113evolving species/122methods/129families; source and actual ROM pointers/records agree | p1_build_runner checked753base rows,753pointers and366evolution branches |
| Items/moves/charmap/map names | All three title packs regenerate; source glyph aliases retained; moves list remains compatible with shared adapter import | p0_regression ACCEPT,20-file review digest e61e555e4849ea73802e954b90631e75d438255f5c2c164c66072b3c89fa06f5 |
| Areas/encounters | C388/G368/S368maps; ordered time/slot data; wild/tree/fishing/roamer parity with independent reader; contest source records preserved | stat_note_fix ACCEPT; area CLI import correction independently closed by stat_note_fix and p1_lock_admission |
| Static/gift/trainer catalogs | C/G/S statics17/18/18; gifts14/16/16; NPC trades7/6/6; trainers541/495/495 | p1_lock_admission independently decoded132script witnesses, NPC/Odd Egg tables and all1531trainer parties; direct CLI blocker closed |
| Independent Python/Lua ROM readers | Three canonical ROMs agree; valid HP divergence is caught; final RoamMaps terminator must stay within its bank | p1_build_runner found cross-bank terminator bug and independently closed fix4d6993b7/test46f18c47 |
| Engine sites | 43typed CPU candidates per title,25signal families; success/return latches explicit | p0_spec_review checked129sites and11refusal mutations; ACCEPT as SOURCE candidates only |
| Checkpoint packs | Fresh source/ROM slices; Crystal25:6983 and G/S25:68B6 caller/stack expectations; runtime authorization false | p0_regression independently reproduced all three packs; ACCEPT as SOURCE candidates |
| Coverage validator | PLANNED target slots map but cannot support CLOSED evidence; scopes and hashes are independently injected | p0_regression ACCEPT neutral9559ba4e/tests5d2c5e06/contract40a894ab after26delta controls and8additional probes |
| Coverage runner/map | Six explicit future target slots;102MAPPED/0UNMAPPED; all197evidence cells OPEN; F-3 has22family witness plans under unchanged ENGINE + PYDEC/GAME contract | p0_regression ACCEPT runner1e2b91fc/testsab1d4049/mapc7301de8; actual mapping command passes and closure refuses |

## Corrective controls

- A clean-check/read race changed source happiness220to1 while retaining pinned provenance.
  The helper now reads the immutable commit blob. The original reviewer closed the replay.
- Direct static/gift CLI invocations failed importing tools. A package/direct import branch
  in the shared area helper fixed the observed failure. Red2fail/1pass became green; all
  direct checks passed with PYTHONPATH cleared and no pack mutations.
- A144-byte RoamMaps body ending at a bank boundary accepted FF from the next bank in Lua.
  A bank-local one-byte span check closes this while preserving the same-bank positive.
- Shared release accounting accepted exit-zero collection-only output. It now requires
  positive executed-test accounting, including controls for inherited PYTEST_ADDOPTS and
  misleading parameter names. The Gen2 manifest also checks moves regeneration.
- Requiring P4 hashes merely to map P2 obligations created a dependency cycle. Neutral
  target descriptors now distinguish planned mapping from built evidence eligibility;
  no game-specific exemption or evidence promotion was introduced.

## P3 candidates, separate from P2 integration

| Candidate | Current bounded result | Remaining work |
| --- | --- | --- |
| Independent Python codec df169556 |50tests; reviewer ACCEPT after full DV:OT:species key and explicit Egg-marker fixes | Played fixtures, RTC-tail/save durability qualification |
| Lua record reader b78fcbe4 |139tests; independent90level-boundary controls PASS; source1..100 checked | Production Entry composition and physical I/O |
| External record comparison7fb3a77c |30tests, valid semantic HP divergence detected before raw hex | Independent test-oracle review; played fixtures remain absent |
| Shared write permit | Original12-file extraction reviewed; numeric interval fix7b2592aa independently accepted | Batch preflight follow-up for known-invalid second span, then re-review; Gen1 physical rebind OPEN |
| Gen2 writes70bd56e7 |24binder tests,51with neutral permit; active faint/explode explicitly refuse | Review found status-before-HP-policy validation; assigned shared batch fix |
| Gen2 boxes f24f755f |31tests; current-box plans, first-save/memorial guards and sealed-plan controls | Independent review; party coordination, native gate, save/reload and memorial record |
| Gen2 adapter dd2af5b3 |28new tests pass; native capabilities disabled, no registry activation | Independent review and production cutover |
| Shared token scanner8d4b1d11 |105scanner/Gen1 read/box tests pass; game maps and independent Python oracle retained | Independent review and Entry/bundle composition |
| Shared checkpoint/admission/hook and fixture orchestration | Active exact-file authoring grants | Frozen review, Gen1 rebind, Gen2 production composition and physical evidence |

The adapter file currently has190passes and17legacy encounter expectations failing from
the earlier P2 pack-shape replacement. Those failures existed before the new adapter edit,
but are changes in this branch relative to the legacy implementation. They are not called
pre-existing master defects or ignored as a green regression. The planned adapter cutover
must resolve them before production acceptance.

## OMP source support

Gen2-Base task cx-b7c20f32 was reconciled5accepted/0rejected/0open against pinned ASM:
roaming uses battle type5; fixed Crystal Suicune uses12; the shared capture tail alone
does not prove capture; a prior successful insertion/context latch is required; roaming
cleanup removes caught OR defeated roamers and cannot serve as the catch oracle.
No emulator or write claim was held. OMP is contextual source support, not a blind review.

## Boundaries

All current catalogs remain BUILT/G1=PENDING. Candidate sites and code do not produce
ADMITTED status. No emulator run, eight played fixtures, PHYSICAL proof, master merge or
release is claimed. Only the exact P1 commit had remote push authority. P2/P3 integration
is local until separately authorized. All worker ownership and next actions are in the
sole guide, not in this receipt.
