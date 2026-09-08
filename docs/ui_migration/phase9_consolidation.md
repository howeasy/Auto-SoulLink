# Consolidation progress

## Shared-helper adoption, 2026-09-08

The [integration map](gen1_integration_map.md#shared-helper-review-2026-09-08) now distinguishes adopted corrected helpers from published prerequisites that still lack a qualified generation consumer. Imported the default suspension hook, private state-store snapshot copies, trade driver, JSON scan improvement, corrected frame windows/pacing and explicit Lua 5.4 syntax runner. Added shared SQLite suspension failure/order tests for reuse by Gen 1. No generation-owned activation or producer code changed.

Current local validation: 4126 full-suite passes / two existing skips; 3820 portable passes / 308 explicit deferrals; 16 JavaScript cases, 220 Lua 5.4 parses and 103 canonical-source checks pass; required Ruff is clean. These counts supersede earlier local counts below, without closing the recorded emulator/randomizer qualification gaps.

## Polling refresh follow-up

Explicit refresh requests from saved-source edits and OBS controls now coalesce into one immediate follow-up when a poll is already running. Reads remain serial, and refresh/subscription calls cannot restart timers while the document is suspended. The coordinator regression test covers immediate follow-up scheduling, return to the normal interval, failure isolation and browser back navigation.

Validation: 4054 unit/integration tests passed, two existing skips (68.50 seconds); all 16 JavaScript cases passed, including the extended coordinator regression; Ruff E9/F6/F7/F81/F82 is clean.

Owner coordination reconfirmed that Gen 1's latest reusable cut is the typed client journal `26aee43`, already adopted. Generation activation, the fixture initializer and verified randomizer publication remain unpublished. RR's private candidate08 field checkpoint does not qualify the shared full-duo ROM/savestate inventory. No generation-owned implementation is duplicated by this follow-up.

Working checkout: `E:\Google Drive\SLink\.claude\worktrees\ui-phase7b-sources`, branch `codex/ui-rework`. Root switched externally back to `codex/gen2base`; no additional UI checkout was created. The UI phase branches and reviewed mockup branches are already ancestors. No active checkout was pruned. Gen 2 confirmed root ownership was released and its separate investigation caches must be preserved.

## Completed cleanup

- Register all 23 real legacy overlay aliases and their fragments from the shared catalog. The synthetic gallery is excluded. Removed the middleware interception and the superseded per-preset Python handlers/context builders.
- Removed 35 retired stream templates, four retired operator-page templates and their three obsolete bootstrap scripts. Their HTTP redirects, shared operator partials and actual stream routes remain covered.
- Static route inventory explicitly expands the reviewed catalog registration; tests compare it against both actual routers without starting runs. HTTP method/path contracts did not change.
- Replaced checks against obsolete event CSS classes with checks against emitted runtime events and the real filter catalog. Command rejection is now selectable as a default-off event type. The force-explode default remains enabled.
- Updated the HTTP reference with Run/Broadcast/Tools, explicit run URLs, saved-source revisions, stopped behavior and compatibility redirects.

## Root checkout verification

The root now has its own `.venv`, Calc dependencies and rebuilt browser bundle. Existing mismatched canonical-input files were backed up under `.cache/ui-input-backup-1788730029` before copying the already hash-verified UI inputs. The tracked ROM-symbol JSON only required LF normalization under the existing `.gitattributes`. The stale Red companion build was preserved and rebuilt from current source; its structural-injector comparison passes. No ROM or private build cache is committed.

Full unit/integration suite: **3897 passed, 2 skipped**, 75.80 seconds. The collected inventory removes three obsolete stream-partial icon checks and retargets three page marker checks to `broadcast/source.html`; it does not remove route or gameplay cases. JavaScript: **13 passed**. Ruff is clean. Canonical input verification: **103 passed**.

The original Phase 7B evidence remains in `phase7b_sources.md`. Final migration qualification still needs the verified Gen 1 randomizer publisher and both required emulator E2E paths. Remaining consolidation includes the shared image-processing utilities, final CSS/dependency review, and any owner-released checkout cleanup after private-input dependencies are resolved.

## Shared assets and dependency follow-up

The board, retained sidebar widgets and broadcast sources now load `images.js` for sprite chroma-key and badge alpha cleanup. The duplicate implementations and old auto-fit/marquee utility are removed. Browser checks observed 73 board sprites and all 16 representative Gen 2 badges processed, with no failed images. Tests cover cached pixels, CORS failures, the badge alpha threshold and temporary URL cleanup.

Removed the obsolete overlay-family CSS while retaining markers still used by Python/Jinja widgets. Layout normalization retains whitespace/case compatibility. Runtime requirements no longer install pytest; development requirements include the runtime group and test/Lua/lint tools. The root Calc bundle rebuilds without the duplicate Barb Barrage warning after the owner-confirmed bounded import `9e315fe` (source `b70b62f`); its eight actual calculator-source regression cases pass.

Latest full suite: **3897 passed, 2 skipped** in 58.81 seconds. Portable selection: **3591 passed, 308 explicit deferrals**. JavaScript: **16 passed**. Ruff is clean. An intermittent MutationObserver error appeared in browser-automation logs during navigation; a temporary main-page error listener did not receive it, and fresh-page polling/interaction checks stayed clean. Keep this observation for the final browser pass; no runtime-code workaround was added.

The required emulator runs are still outstanding. Both owners released the bounded shared-runner isolation correction to this task: the existing Gen3 duo path copies the user's config unchanged, so SaveRAM and several generated test files can collide. Isolate those before launch; the frozen Gen1 default wire-v1 duo remains meaningful for its existing scope and does not need the unpublished configured durable route. Verified randomizer publication remains separately gated.

## Shared duo runner and required E2E evidence

The owner-approved isolation correction is documented in [duo_isolation.md](duo_isolation.md). Full unit/integration verification after this correction: **3905 passed, 2 skipped**. The complete Gen 1 E2E file ran with `SLINK_E2E=1`: **15 passed, 30 failed, zero skips/deselections**, 1150.27 seconds. All 30 failures report the frozen `rby_operation_interface_unavailable` refusal from `/api/debug/set_pokeballs`; the guard was not bypassed. Playthrough, deadzone and dupes passed for every required pair. All 135 recorded process identities had exited after the run.

The Gen 3 E2E file is still outstanding. RR identified the local ROM SHA256 `1e8f6e8957c1e8eb7ce2d2e349a7c335e48f13b7dd44bf81350dc1ade1a1ec04` as its audit baseline but has no provenance binding it to the shared savestates. It must not be substituted for a qualified fixture set. The advertised patcher MD5 also differs; this remains RR's existing U05 finding. No Gen 3 E2E pass is claimed.
