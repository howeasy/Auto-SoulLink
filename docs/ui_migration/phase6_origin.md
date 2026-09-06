# Phase 6 — one origin and explicit run selection

The manager now renders the same pair board and navigation rail as a standalone
run. The iframe is removed. `/runs/{run_id}/` selects one registered run and
continues polling that URL when its run stops or becomes unavailable. The root
page lists runs and provides guided creation; it never guesses a selected run.

## Routing and rendering

- `server/run_proxy.py` is the explicit method/path allowlist. It resolves only
  registered integer HTTP ports on loopback. Private `/_ui/board-context`, future
  OBS execution, local file inspection, and arbitrary API paths are excluded.
- Managed HTTP listeners use `--http-host 127.0.0.1`. The existing `--host` TCP
  allocation and standalone listener defaults are preserved.
- The child supplies a detached, identity-checked board context over loopback.
  Only the named adapter/widget HTML fields regain `Markup`; registry names and
  other text remain autoescaped. Every explicit proxy response checks its run
  identity; a target header rejects wrong-run mutations before execution.
- Queries, theme cookies, conditional/range headers, download dispositions,
  multiple Set-Cookie headers, redirects, and fragment/action URLs survive the
  proxy. The HTML rewrite changes URL attributes only, leaving JSON and scripts
  alone. Run HTTP JavaScript uses an explicit prefix helper.
- Calc receives its existing `?slink=` URL for the selected run. Its real SSE
  bytes stream through the manager and close upstream on client cancellation.
  Only the manager's dummy `/api/events` handler was removed.
- Legacy `/stream/{slug}` pages/fragments, query controls, and active-run
  resolution remain supported. Gallery previews opened from an explicit run
  retain that run's prefix.

Existing child processes must be restarted with this version before they can
serve the new explicit routes: a missing identity/context response shows an
unavailable state, rather than trusting another process at a recycled port.

## Lifecycle and stopped state

Registry mutations serialize short reload/merge/atomic-write transactions.
Separate per-run locks order starts, stops, archival, deletion, and cartridge
binding; awaited work cannot overwrite unrelated registry edits. Concurrent
creations reserve distinct ports. New run IDs are UUID-based and never reuse a
deleted run's identifier. Browser cancellation cannot strand a spawned child
before its registry transaction finishes. Corruption during startup preserves
the malformed registry and stops the newly created child.

Stop and delete verify both the Python module and resolved run data directory
before terminating a recorded PID. Termination failures remain visible instead
of recording a false stopped state. Startup discovers orphan processes once;
ordinary reads use a detached registry cache and lightweight file signatures.

Stopped rendering uses Gen 1's frozen `read_saved_run` boundary, with a cache
invalidated by the saved file/directory signature. Missing, corrupt, or unsupported
durable storage remains visibly unavailable. Persisted identities, links, and
caught halves remain, without Now cards, inferred party locations, live HP,
battle values, runtime readiness, or inferred per-player cartridge identity.

Gen 1 creation opens Setup without automatically starting by default. Existing
clean-cartridge verification/binding is exposed with local-operator checks;
randomized publication retains its 409 gate. The unreachable fingerprint-only
publication branch was removed. The verified publisher remains a Phase 8
dependency, not a fallback implemented here.

## Validation

Gen 3 checks ran first. Final full unit/integration suite: **3851 passed, 3
skipped**. The skips remain the optional unbuilt Red companion component and two
Windows file-symlink privilege cases; junction containment cases pass. Portable
CI: **3546 passed, 308 named deferrals**, with no selected skips or xfails and
`release_approved: false`. The inventory reviews 56 additions and 13 retired or
replaced nodes; existing resource deferrals are unchanged.

Required Ruff passes, 216 Lua files parse, and canonical inputs pass 103 checks.
The actual Calc bundle builds and seven Node cases pass. HTTP tests exercise
cross-origin rejection, loopback/Host validation, private route exclusion,
wrong-run status/mutation rejection, binary/range/conditional responses, SSE
streaming/cancellation, concurrent lifecycle actions, corrupt storage, failed
startup, and process ownership. Both Gen 3 and Gen 1 scenarios exercise concurrent
board, two overlay fragments, and Calc queries while a real run SSE stays open.

Browser evidence is in `tests/fixtures/ui/review/phase6/`: 18 board captures cover
Gen 3 then Gen 1, default/light/Funtastic Grape, and 700/1100/1600 px. Pair order
and overlap checks pass throughout. Additional captures cover creation, setup,
and the 375 px rail. Keyboard review covers run selection, setup fields,
encounter expansion across polls, and Debug's focus trap/Escape restoration.
Nineteen unavailable Gen 1 Debug actions have readable reasons. Stable rail
anchor identities and an idiomorph out-of-band swap preserve focused links.
Stopping/restarting a disposable run preserves selection; stopping removes Now
and HP and disables Debug. The browser also ran a board, two overlay documents,
and the selected run's Calc concurrently.

These are isolated presentation/HTTP fixtures. `tools/serve_manager_scenarios.py`
creates no emulator or game TCP listener and touches no real run directory.
This evidence does not complete live cartridge admission, emulator E2E, the
verified randomizer, saved broadcast sources, or manager-owned OBS arbitration.
Broadcast/Tools consolidation and those remaining gates continue in Phases 7–9.
