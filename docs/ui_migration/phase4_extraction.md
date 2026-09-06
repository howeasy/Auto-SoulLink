# Phase 4 equivalent template extraction

The dashboard now renders from `server/dashboard.py` and Jinja templates under
`server/templates/dashboard/`. The context contains detached data and explicitly
trusted existing widget output; templates cannot access the server, state, or
adapters. Both split and combined views retain their roster selection, thresholds,
badges, DOM selectors, unique disclosure identities, and warning behavior.
Encounter/trainer widgets and the shared move/type/status widgets remain in Python.

Seven original `#content` subtrees were captured before removing the generator:
empty, populated Gen 3, populated Gen 1, warnings, split roster, doubles, and HP
boundaries. Their source commit, method hash, and individual hashes are recorded
in `tests/fixtures/ui/legacy_dashboard/manifest.json`. Tests compare normalized
structure, attributes, and text with the captured output. The only deliberate
exceptions are the formerly double-escaped pending trainer name and RR-U02's
conversion from numeric move IDs to names. Independent assertions cover the new
move-name contract. A separate test renders the context after clearing runtime
caches, proving the renderer is detached.

The old full-document slicing and injected phase-header string are gone. Jinja
owns the page shell. HTMX and idiomorph still load before dashboard behavior,
and the existing two-second coordinator preserves encounter expansion. Debug,
OBS, and Twitch HTML, CSS, and JavaScript constants are now templates/assets.
Launcher Lua encoding and runtime dispatch are unchanged.

Dynamic Debug renderers now build DOM nodes and assign text/attributes directly.
This covers datalists, links and action parameters, backups, identity errors,
memorials, and manual-link warnings. Twitch activity text uses the same browser
text behavior. Existing escaped OBS rows and static-only icon markup remain
safe. No new HTML parser or sanitizer is introduced. Operator input focus rings
are visible after extracting their stylesheets.

## Calculator findings

RR-U01 was reproduced beyond a successful build: the old generated browser data
bundle still threw `require is not defined`. Its bundler uses fixed line slices
of compiled modules. The preview now loads a separately named browser bundle
built from the actual TypeScript entry with pinned esbuild. The entry's legacy
global `exports` shim is guarded when no CommonJS/browser shim exists. Existing
standalone Calc pages, loading order, and real SSE bridge are retained.
Build flags follow the [official browser bundling documentation](https://esbuild.github.io/getting-started/#bundling-for-the-browser).

RR-U02 is fixed by resolving move names in the presentation context. Damage
percentages use maximum HP, while KO checks use current HP. Complete input checks
reject numeric move IDs, missing data, and unselected doubles targets. The preview
does not populate missing observations from static trainer sets or guess difficulty.
Calc links keep the selected server's `?slink=` base.

RR confirmed that no complete effective-battle/stat/form/mode/freshness envelope is
published yet. Live previews therefore say unavailable. A clearly labeled synthetic
fixture supplies complete inputs solely to exercise the real engine: level-50
Rattata using Tackle against Rattata produces 33–39 damage, 31.4–37.1% of 105 max HP,
and an OHKO at 10 current HP. At 60 current HP the same percentage range is a 2HKO.
These are calculator execution checks, not live RR verification. Transport age is
not promoted to emulator-sample freshness.

## Validation

- Full local unit/integration suite: **3768 passed, 3 skipped**. The known skips
  are the unbuilt optional Red companion component and two Windows file-symlink
  privilege cases. Canonical private input verification passed before the run.
- Exact portable inventory: **3463 passed, 308 unchanged named deferrals**;
  no selected skips or xfails. Eight new Python cases were individually reviewed.
- Five Node tests execute real Debug rendering functions with hostile text and
  the actual browser calculator bundle without Node `require`/`exports` globals.
  CI builds that bundle and runs these tests with a provisioned Node runtime.
- Required Ruff checks passed; all 216 Lua files parsed; extracted scripts pass
  JavaScript syntax checks.
- Hosted CI exposed a platform-dependent asset-copy bug: Windows path separators
  skipped the JSON-set optimization, while Linux tried to parse the executable
  `slink_priority.js` extension as JSON. The copier now normalizes the path and
  minifies only complete SETDEX JSON assignments. An isolated build regression
  verifies JSON compaction and byte-preserved executable extensions on both hosts.
- Browser inspection verified the actual synthetic damage output, a correct
  `?slink=` link, preserved disclosure state across completed refreshes, and zero
  injected probe elements in Debug. The hostile labels remained visible as text.
- Screenshots cover Gen 3/default at 1600 px, Gen 1/light at 1100 px, and Gen 3/
  Funtastic Grape at 700 px. The checked layouts had no horizontal overflow;
  keyboard Tab reached a visible focus outline. Images are in
  `.cache/phase4-review/` in the isolated implementation checkout.

This finishes extraction and the browser integration fixes. The reviewed pair
board, complete Debug drawer focus management, new run routing, saved broadcast
sources, and verified randomizer workflow remain subsequent phases.
