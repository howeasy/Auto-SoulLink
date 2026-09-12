# Shared review reconciliation

UI/Claude review identified one configuration defect in the shared trade driver:
an explicit invalid `new_id` could fail late or, if falsey, silently select the
default. The constructor now rejects noncallables before reading state or
advancing a trade, and retains valid falsey callable objects. Eight added cases
cover both behaviors.

`frame_pacer` deliberately clears its deadline on lost permission or user pause.
An executable reproduction schedules twice at the same timestamp when permission
is toggled between calls. The shared contract now explicitly describes it as a
cadence helper, not an independent rate limit across those transitions. Production
pacing behavior is unchanged.

The reported execution-window diagnostic overwrite does not occur in the current
published code. `scope()` clears the grant when ownership disappears; `live()`
then reads that cleared grant and returns before its scope-changed branch.
The reproduction preserves `no owned operation`. No production change was made.
Evidence: `.cache/helper-review-findings.json` and its reproduction script.

`9b3e1fd4f92d36ef10493d57f678e385c44830fa` remains the owner test-normalization
baseline. Its two frame test files were AST-identical to the prior local copies
and were adopted byte-for-byte. The new correction cut carries exactly those
blobs, not another test normalization.

The six-file cut `20b80e31c32d6902084dd8201df14e90866486ac` is published on
`codex/shared-driver-validation-v1`, directly after `bc3ad9de`. It contains the
driver, its tests, the two normalized frame tests and the two shared contracts.
No production Lua frame module changed. All 70 local driver/window/pacer cases
pass; the exact isolated tree passes 3,106 tests with 15 existing skips and
11 subtests in 35.72s, required Ruff and 228 Lua 5.4 parses. GitHub run
34249924036 is green on the exact published head.

The UI's finalized `tests/unit/test_runtime_suspension.py` was adopted exactly
from `0c250cfc8100ad85e00a5e6c81809e9da4fe3992`. All 11 cases pass in 0.48s.
They cover real journal, constructor, admitted TCP and first-frame paths:
hold-before-hook ordering, interruption commit preservation, SQL rollback,
session/writer revocation, failure latch, NACK/EOF and ticket invalidation on
reopen. No production suspension fix was needed.

Failure replies currently use `contract_pending` with a reason even when the
runtime requires reopening. That label alone does not establish recoverability
through retries or authorize gameplay. A distinct machine-readable failure code
is a future protocol improvement; the frozen wire vocabulary is unchanged here.

These are focused shared corrections and adopted tests. They do not constitute
a rerun or approval of the full Gen1 release gate. Ordinary gameplay remains held;
memorial/save and controlled startup/recovery work remains.
