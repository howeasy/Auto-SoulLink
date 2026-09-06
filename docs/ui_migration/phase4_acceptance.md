# Phase 4 extraction acceptance

Start from the tested Phase 3 producer `5817e26`. Retain both dashboard views,
selectors, encounter identities, thresholds, badges, and warning behavior while
moving presentation to a detached context and Jinja templates. Compare normalized
markup, including text content and safe HTML fields, against the legacy output
before removing the generator. Encounter and trainer widgets may remain in Python
temporarily. Later board changes remain a separate phase.

## Calculator requirements carried from RR

The RR owner rechecked these existing defects against the published Phase 3
baseline on 2026-09-06. They remain open renderer integration requirements.
Projection and HTTP route tests do not close either issue.

| RR finding | Current trigger | Required acceptance evidence |
|---|---|---|
| RR-U01 | `_CALC_PREVIEW_JS._init` loads only `/calc/calc/calc.js`; that entry's browser dependency assumptions have not been satisfied. | Load the actual built browser engine in an isolated rendered RR page, prove initialization without module/dependency errors, and execute a real damage calculation. |
| RR-U02 | Battle-row `_amoves` contains raw numeric IDs while `_calcMove` passes each value into the name-based `window.calc.Move` constructor. | Resolve moves through the owning player's adapter and demonstrate known nonzero damage results for observed moves; do not accept a swallowed exception or an empty preview as success. |

Preserve the distinction between extraction equivalence and deliberate Calc
fixes: characterize existing output first, then record the intentional behavior
change with browser evidence. Missing calculator build inputs leave that evidence
outstanding.

RR owns admitted per-player runtime data, including effective battle stats,
forms, abilities, items, battle mode, and observation freshness. The UI consumes
those observations. Static trainer preparation sets must not overwrite observed
battle inputs. Unknown inputs stay unknown and doubles must not imply invented
opponent targeting.

Keep standalone Calc in a new tab with the selected run's existing `?slink=`
parameter and its real SSE connection. The later manager migration removes only
the dummy manager SSE handler. These requirements extend preparation scenario
`C04` and do not require importing the RR owner's active worktree.
