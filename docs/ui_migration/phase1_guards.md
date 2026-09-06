# Phase 1 rendering guard rails

The legacy renderer remains in place. The guard suite now renders both RR and
R/B scenarios through the actual HTTP template handler using fully hydrated,
isolated state rather than replacing `_build_status_dict` with a JSON stub.

## Contracts pinned

- Encounter table/search/filter IDs, sortable header-to-cell indices, allowed
  filter status values, and sortable cells in columns 0 and 3.
- Events excluded from global search; explicit table header sections.
- Stable disclosure IDs matching `d-{data-details-key}`, direct-child summaries,
  and no duplicate page IDs across split/combined views.
- Sprite HTML rendered as HTML, species attributes, and the existing polling
  attributes. Generation-specific stat stages exercise Gen1's single Special.
- Unique Calc preview IDs for each battling RR player, including two simultaneous
  battles; no Calc preview for the Gen1 scenario.
- Real macro-smoke examples through `/memorial?_smoke=1`.
- Exact run/manager method/path sets and the discovered concrete GET smoke list
  in `tests/fixtures/ui/routes-v1.json`.

Smoke assertions now require the expected 200 or Calc redirect 302 instead of
accepting arbitrary non-5xx responses. Parameterized calc/companion/static routes
use concrete tracked assets. Calc's built `normal.html` is not in a fresh source
checkout, so this phase verifies its redirect, source asset route and existing
HTML-wrapper tests; it does not claim the third-party bundle was built/exercised.
That remains an explicit prerequisite for the later one-origin Calc validation.

## Corrections exposed by the guards

The foe tables had headers directly under `table`; they now use explicit
`thead`/`tbody`. The RR rendering fixture now sets the legacy `state.is_rr` flag,
so the Calc preview branch actually participates in coverage.

Dashboard `.lp-area` and `.enc-lv` overrides are scoped to its body class. The
duplicate `.shiny-star` color rule was removed so the shared token rule remains
the source. Computed dashboard styling is preserved while shared components are
protected from unintended overrides.

Theme guards scan all templates plus the legacy/context builder and retained
Python widgets when present. They survive removal of `_build_status_html`, stay
nonempty, and recognize bare background colors as well as text colors.

## Verification

Gen3 checks ran first. The full local unit/integration suite and portable lane
were exercised separately; private-input/platform deferrals are not release
proof. Portable inventory changes are explicit: ten new dashboard scenario nodes,
two frozen-router checks, and six smoke parameter replacements from placeholder
paths to concrete assets. No deferral classification changes were made.

The final full local suite passed **3703 tests with three documented skips**
(two Windows symlink-privilege cases and one optional built companion component).
The portable lane passed **3398 selected tests with 308 named deferrals** and no
selected skips; its report explicitly declines release approval. Required lint
and full lint on the new/changed guard helpers passed.

Browser checks used isolated, read-only fixture servers: RR/default at 1600 px,
R/B/light at 1100 px, and RR/Funtastic Grape at 700 px. Server access logs confirmed
successful periodic GETs; the open encounter disclosure and two-row dead filter
remained set after those refreshes. The known reference-board narrow layout is
still a Phase5 port/refinement item, not changed by this legacy-renderer phase.
