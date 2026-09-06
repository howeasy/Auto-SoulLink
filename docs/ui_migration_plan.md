# SLink: one board and reusable broadcast sources

Approved implementation plan, 2026-09-05. This document supersedes the mockup brief's section 9 once that branch is integrated.

## Summary and design direction

Deliver one origin with **Run, Broadcast, and Tools**, retaining Calc in a new tab and Debug as a drawer.

Use the reviewed Track A mockup (`server/static/mockups/a/index.html` on `claude/soul-link-ui-mockups-40f67b`) as the board's design baseline. Rendered review covered Gen 3, Gen 1, the new-run form, dark/light themes, desktop widths, and the narrow layout.

Preserve consistent player columns and one row per pair; mirrored HP bars facing the central bond; the foe beneath the fighting player and "at stake" beside the partner; state-based zones, Jersey typography, and the log beside the board on wide screens.

**Mild adjustments are authorized without further design approval:** spacing, alignment, responsive behavior, labels, contrast, focus handling, and accessibility. Preserve the board's composition and information hierarchy.

Include these specific adjustments during the port:

- Fix overlapping pair content around **700 px**. Below the stacked breakpoint, order each pair **Player A -> bond -> Player B**, with explicit player labels.
- Keep unavailable-option explanations readable rather than dimming the entire row.
- Use friendly cartridge names and "Game family"; replace implementation terminology with clear setup instructions.
- Add accessible selected/current states, visible keyboard focus, and complete Debug drawer focus management.

Broadcast uses the separately agreed **clean broadcast style**, with transparent canvases, readable sans-serif typography, restrained theme accents, and shared adaptive components.

## Coordination and interfaces

### Ownership and integration

Gen1 Readiness owns runtime, admission, persistence, and verified randomized-ROM preparation. This task owns presentation projections, templates, manager routing, broadcast configuration, and UI tests. RR work proceeds in isolation subject to the agreed Gen 1/UI dependencies.

Use isolated `codex/` worktrees and one independently working PR per phase. Only narrow HTTP hardening proceeds before Gen 1's published handoff. Recheck ownership, commits, and dirty state before integrating or pruning; preserve every active checkout.

After importing the mockup branch, replace the brief's obsolete section 9 with a pointer to this document.

### Presentation data

Preserve existing `/api/status` fields. Add:

`players[pid].capabilities[feature] = {supported, requested, ready, effective, reason}`

Project authoritative adapter, admission, and runtime evidence. Unknown values remain `null`; omit `requested` for intrinsic features without a configurable setting. Evaluate features independently. Capability readiness never implies completed operations or resolved recovery.

Add mon keys, held-item names, and pending-capture names/sprites. Preserve per-player cartridge identity, admission reasons, observation age, and the distinction between persistent identity and battle state. Agree exact provenance and durable-lifecycle field names with Gen 1 at its frozen handoff.

### Manager routing

Add `/runs/{run_id}/...` for explicit run access. Resolve upstreams from registered runs and expose an explicit route allowlist. Preserve query strings, theme cookies, conditional-response headers, downloads, and prefixed fragment/action URLs.

Managed run HTTP listeners use loopback through a separate HTTP-bind option. Preserve TCP allocation and standalone defaults. Calc uses its existing `?slink=` parameter for the selected run and retains its real SSE connection. Remove only the manager's dummy SSE handler.

### Saved broadcast sources

Each source has an immutable ID, editable name, explicit run, preset, player selection, layout, theme, and supported preset controls.

- CRUD lives under `/api/broadcast/sources`.
- Stable OBS pages and polling use `/broadcast/sources/{source_id}` and `/fragment`.
- Retargeting updates an already-open source. Configuration revisions prevent late responses from restoring the previous run; layout/theme changes refresh the shell when necessary.
- Stopped, unavailable, or deleted runs never cause automatic selection of another run. Source records survive run archival.
- Existing `/stream/{slug}` pages, fragments, query controls, and theme aliases remain supported. Legacy run resolution remains a compatibility path.

### OBS configuration

The manager owns global connection settings and rules. Each new rule explicitly names its source run, independently of saved overlay sources.

The manager serializes scene-change decisions per OBS endpoint. Existing rule order resolves competing matches within an event batch; accepted batches are processed in arrival order. Runs retain WebSocket execution. Private execution routes remain outside the public run proxy.

Configuration revisions and application failures are visible. Import legacy rules as unassigned until explicitly bound and enabled rather than guessing their run. Twitch configuration and controls remain per-run.

## Implementation phases

| Phase | Deliverable |
|---|---|
| **Track A - HTTP hardening** | Fix resolved-path containment for calc files; escape every affected dashboard text sink in both views; sanitize launcher comments and encode Lua strings; correct empty-status structure; add CSRF middleware; close parent subprocess handles explicitly; clean up OBS reconnect clients; make registry writes atomic while preserving malformed files; validate debug player IDs. Add theme cache headers without replacing existing `Vary` values. Defer patcher and runtime-persistence changes until Gen 1 integration. |
| **0 - Integration gate** | Wait for Gen 1's published commits, integrate the reviewed mockup branch, and resolve actual conflicts. Preserve script-safe JSON, cartridge labels, patcher targets, immutable bindings, and injector improvements. Obtain the frozen presentation/provenance boundary. |
| **1 - Guard rails** | Build isolated, hydrated rendering scenarios covering state indexes and caches as well as status JSON. Pin required route methods, paths, successful response statuses, DOM selectors, details identities, and safe HTML fields. Test the macro smoke harness. Keep color guards over templates and retained Python widgets. |
| **2 - Verified deletions** | Revalidate the handoff's dead-code list against the integrated tree, then remove unused helpers, guards, symbols, and CSS. Resolve CSS collisions with explicit component scope. |
| **3 - Presentation projection** | Implement additive capability and mon enrichments. Generate fixtures from isolated scenarios and add nested contract assertions. Reuse authoritative identity rejection and keep admission policy with Gen 1. Consolidate duplicated display helpers without changing rule behavior. |
| **4 - Equivalent template extraction** | Replace the dashboard string generator with Jinja and a detached dashboard context. Retain both existing views, selectors, thresholds, and badge behavior during extraction. Compare normalized DOM against the legacy generator before removing it. Keep encounter/trainer widgets in Python temporarily. Move remaining HTML/JS constants into templates/static assets and explicitly replace unsafe JavaScript HTML insertion. |
| **5 - Pair board and mild refinements** | Port the reviewed composition, retire the old views, and implement the responsive, wording, contrast, and accessibility refinements above. Include Now, In party, Pending link, Split, Boxed, unlinked mons, persisted-only Linked, Fallen, and Log. Preserve admission, save, staleness, and run-over warnings. Promote required fixtures and fonts before deleting mockups and Track B. |
| **6 - One origin and run rail** | Implement shared manager/standalone templates, guided creation, run rail, and explicit run proxy. Remove the iframe and repeated disk scraping. Centralize serialized registry mutations, use per-run lifecycle locks, and merge changes after awaited work rather than saving stale snapshots. Read stopped summaries without inventing live telemetry. |
| **7 - Three destinations** | Combine Broadcast settings and per-run Twitch; combine patcher and randomizer setup under Tools; expose Debug through the shared drawer. Add compatibility redirects for retired pages. Introduce manager-owned OBS configuration and arbitration. |
| **7B - Shared broadcast system** | Build all existing overlay capabilities as presets from common player, mon, pair, battle, badge, counter, encounter, memorial, and feed components. Add saved-source management, previews, revision handling, and independent run selection. |
| **8 - Randomizer workflow** | Wrap Gen 1's verified pipeline with local file selection, preflight, generated settings, asynchronous jobs, recoverable publication, and per-player downloads. Completion requires actual admission of both final outputs. |
| **9 - Consolidation** | Table-drive overlay registration, excluding the synthetic gallery entry. Consolidate polling infrastructure, chroma-keying, theme handling, rule flags, CSS, and dependency groups. Generate or verify route documentation. Remove obsolete assets and owner-released worktrees after dependency checks. |

Implementation rules across phases:

- **Board membership:** join through authoritative party keys. Retain unlinked active mons and caught halves of failed encounters. Support doubles without inventing opponent targeting.
- **HP:** compare the weaker half's raw ratio against **35%**; round only displayed numbers. Unknown HP stays unknown. After extraction, consolidate HP colors to high above 50%, medium above 20%, and low otherwise.
- **Stopped versus disconnected:** stopped runs show persisted links without Now cards, live HP, battle, or inferred party placement. Disconnected players retain labeled last observations.
- **Refresh:** use one polling coordinator per application page and one per OBS source document. Preserve encounter expansion with stable run/player identities. Recompute observation age on every response; optimize expensive enrichment only after measuring it.
- **Broadcast styling:** use locally vendored IBM Plex Sans, compact sprites, clear player labels, restrained motion, and reduced-motion support. Preserve doubles, full enemy teams, moves/PP, stat stages, badge variants, scrolling, pause, and event filters. Legacy URLs retain supported dimensions and controls.
- **CSRF:** combine Fetch Metadata with exact Origin/Referer validation when metadata is absent; reject explicit cross-origin and null-origin mutations. Preserve headerless native tooling. Plain HTTP LAN access needs this fallback because Fetch Metadata is restricted to trustworthy URLs. See the [W3C specification](https://www.w3.org/TR/fetch-metadata/) and [OWASP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
- **Assets and preferences:** move generated captures into test fixtures before removing mockups. Retain Jersey 20, IBM Plex Sans, required production fonts, and existing theme/font preference compatibility.

## Randomizer behavior and defaults

The picker, source inspection, and JAR configuration are **local-operator only**, using loopback and validated local Host checks. Browse regular local files; reject device/network paths and resolved escapes. Partners can download committed outputs.

Expose six categories plus Fastest Text through Gen 1's published settings catalog. Default them enabled and require at least one randomization category. This is a UI preset surface, not the complete validation contract: preserve effective evolution-method evidence, unchanged evolution targets/families, and scripted-grant/static scanning.

Discover and persist the approved JAR. Preflight Java and both source ROMs before starting either invocation.

Preparation returns `202` with a job ID. Polling reports named stages and `queued`, `running`, `succeeded`, `failed`, or `interrupted`. Use isolated staging, per-run locking, and recoverable publication through Gen 1's contract publisher. Preserve exact generated/effective settings, provenance, seeds, and final hashes. Restart never silently rerolls seeds.

Downloads resolve only committed player artifacts and verify their hashes. Gen 1 downloads use `.gb` filenames. Once a cartridge binding exists, re-randomization creates a fresh run and preserves old artifacts and history.

Gen 1 owns full semantic verification, provenance, structural injection, and randomized admission. The legacy fingerprint-only pipeline is not an acceptable fallback.

## Validation and completion

For every phase, verify Gen 3 first, then other generations. Run:

```text
pytest tests/unit tests/integration -q
ruff check . --select E9,F6,F7,F81,F82
```

Required additional evidence:

- Security failures, corrupt storage, concurrent lifecycle actions, subprocess cleanup, and OBS reconnect cancellation using isolated data paths.
- Equivalent extraction output, followed by board tests for empty, stopped, disconnected, stale, rejected admission, split pairs, unlinked mons, doubles, and HP boundaries.
- Screenshots at **700, 1100, and 1600 px**, using Gen 3 and Gen 1 scenarios in default, light, and a Funtastic theme. Confirm no overlapping content and unmistakable player ownership.
- Keyboard-only navigation through run selection, setup, encounter expansion, and Debug; readable unavailable-option explanations and visible focus across themes.
- Every overlay preset at catalog sizes, including representative Gen 2/4/5 capability data without claiming live support.
- Simultaneous board polling, multiple OBS sources, and Calc SSE. Retarget an open source and stop its run; polling must continue without switching to another run.
- A real JAR run and actual TCP admission of both final downloads. Cover swapped/modified outputs, non-wild category selections, partial failure, interrupted publication, and restart recovery.
- Both full E2E paths with `SLINK_E2E=1`: `tests/e2e/test_duo.py` and `tests/e2e/test_duo_gen1.py`. Missing prerequisites or skipped required cases remain outstanding evidence.

Completion requires the working board and refinements, reusable broadcast system, verified randomizer workflow, preserved compatibility, and updated documentation.

## Implementation ledger

| Stage | Status | Evidence |
|---|---|---|
| Plan recorded | Complete | This document; reviewed directly with the Gen1 and RR task owners. |
| Track A | Implemented; CI passed; PR open | [PR #1](https://github.com/howeasy/Auto-SoulLink/pull/1), head `965cc12`: Windows 1805 passed / 15 skipped; Linux CI 1802 passed / 18 skipped; required Ruff passed; 178 Lua files parsed. Browser checks covered Gen 3/Gen 1 dashboards, manager, themes, escaped text, and corrupt-registry recovery on isolated HTTP-only fixtures. |
| Consumer interface | Additive producer implemented | `docs/ui_projection_contract.md` and [projection evidence](ui_migration/phase3_projection.md) define the tested consumer boundary. |
| Phase 0 | Integrated in isolated phase branch | [Acceptance evidence](ui_migration/phase0_acceptance.md): `bc880025` plus Track A/prep and reviewed mockups; 159 committed hashes verified, 662 focused tests without skips, then 3665 full-suite passes / 3 documented skips. Required Ruff and 216 Lua parses passed. Verified UPR publication and unfinished RBY operations retain separate gates. |
| Phase 1 | Guard rails implemented and locally verified | [Rendering contracts](ui_migration/phase1_guards.md): 3703 full-suite passes / 3 documented skips; portable lane 3398 selected passes / 308 named deferrals; browser checks preserved disclosure/filter state across completed refreshes. |
| Phase 2 | Verified cleanup implemented | [Cleanup evidence](ui_migration/phase2_cleanup.md): unchanged hydrated render output; 3703 full-suite passes / 3 skips; portable 3398 selected passes / 308 named deferrals. |
| Phase 3 | Projection implemented; owner patches integrated | [Projection evidence](ui_migration/phase3_projection.md): per-player capabilities and mon enrichment, detached nested containers, unchanged unknown lifecycle facts; owner commits `8f97ea0` and `dbad8d5` merged without conflicts. |
| Phases 4-9 | Next: equivalent template extraction | [Extraction acceptance](ui_migration/phase4_acceptance.md) retains RR-U01/U02 calculator browser/move-name requirements. Phase 8 and unavailable runtime mutation controls retain their separate gates; no release-readiness claim. |
| Additional preparation | Prepared independently while waiting | [Preparation packet](ui_migration/prep.md), hashed route/overlay/mockup inventory, offline inventory comparison command, and acceptance scenarios agreed with Gen1/RR owners. No production behavior changes or Phase 1 dashboard guards. |

Track A skips: three battery-save scenario exclusions, five SVG/template exclusions,
two missing pret checkouts, three ROM files absent from this isolated checkout, and
two Windows symlink-privilege skips. Actual Windows junction-escape tests passed
against both calc roots. Linux CI covers the file-symlink cases. These results do
not establish cartridge release readiness or complete the later UI/E2E gates.

Track A deliberately leaves registry lost-update concurrency for Phase 6 and
patcher/runtime persistence for the Gen 1 integration boundary. It does not change
gameplay admission, TCP dispatch, randomization, or OBS configuration ownership.
