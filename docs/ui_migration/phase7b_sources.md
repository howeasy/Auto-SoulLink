**Current working location (2026-09-06):** `E:\Google Drive\SLink`, branch `codex/ui-rework`. All UI phase and reviewed mockup branches are ancestors of this branch; Phase 7B is committed as `0d5ca74`. Older worktree instructions below are historical.

# Phase 7B — reusable broadcast sources

Implemented in the existing `ui-phase7b-sources` checkout on `codex/ui-phase7b-sources`, based on Phase 7 commit `7a38d5eaeab3375ab86935c5a2cb5202881fc318`. The user requested that further work remain in this checkout instead of adding more phase worktrees.

## Behavior and compatibility

The manager owns saved source records in `broadcast_sources.json`, independent of run archival. Each immutable source ID has a name, explicit run, preset, selected players, layout, theme, supported controls, and optimistic configuration revision. CRUD lives at `/api/broadcast/sources`; stable pages and fragments live at `/broadcast/sources/{source_id}` and `/fragment`. HEAD requests are supported on read routes.

Retargeting updates an already-open document. A revision conflict reloads its shell before applying another run's content. Stopped, archived, unavailable and deleted assignments never fall back to another run. Stopped pair presets display persisted links without party-placement inference, battle state or HP. Corrupt storage is preserved and reported rather than replaced. Source editor polling cannot overwrite a newer save; drafts require an explicit save or discard before switching, and unchanged polls preserve keyboard focus.

All 17 preset families share player, mon, pair, battle, badge, counter, encounter, memorial and feed components. All 23 legacy slugs retain their fragment URLs, supported layout/theme/query controls and catalog dimensions. The synthetic `all` gallery is not a preset. The remaining old handler/template registrations are intentionally retained for the separate Phase 9 deletion review.

Broadcast documents use local IBM Plex Sans and transparent canvases. Pair halves carry explicit player labels. Wide party cards place sprites above text; long pair histories scroll rather than shrinking text to illegibility. Pair presets expose speed/pause controls. Headers remain visible during scrolling. Reduced-motion preferences stop motion. Selecting both players recommends twice the single-player canvas width.

The projection follows authoritative party keys, retains unlinked active mons, leaves unknown HP unknown, and does not invent doubles targets. It preserves the full observed enemy team, moves/PP, stages, cartridge badge variants, disconnected observation labels, and legacy event-filter ordering. The encounter tracker selects the most recent committed link rather than the final board zone or pending row.

## Validation

- Full unit/integration suite: **3899 passed, 3 skipped**, 66.80 seconds. The later concurrent-SSE assertions were also rerun successfully in the two source HTTP tests.
- Portable CI inventory: **3594 passed, 308 explicitly deferred**. The 24 added Python cases use isolated fixtures and storage, without ROMs, emulators, Java or OBS accounts.
- JavaScript: **13 passed**, including stale-source revisions, deletion/recovery, reduced motion, draft preservation, delayed collection responses, shared polling and Calc behavior. Both new JS files are included in the CI command.
- Ruff `E9,F6,F7,F81,F82`: clean. Lua: **216 files parsed**. Canonical inputs: **103 checks passed**.
- Route contract review: one private run POST and eleven manager routes added; no existing method/path removed. Private projection remains excluded from the public run proxy.
- Real loopback HTTP test holds Calc's actual SSE endpoint open while board status, saved-source fragments and a second legacy overlay fragment complete concurrently.

Rendered review used disposable hydrated Gen 3 and Gen 1 scenarios, a Gen 3 doubles scenario, and explicitly disconnected Gen 2/4/5 capability samples. It inspected all 17 preset families at the 27 catalog dimensions. The review found and corrected horizontal party truncation, unreadable scaled pair histories, bright-background status text, scrolling ticker backplates and narrow pair ownership. Representative screenshots are in [`tests/fixtures/ui/broadcast_review`](../../tests/fixtures/ui/broadcast_review).

The saved-source editor was checked at 700, 1100 and 1600 CSS pixels in light, default and Grape. No horizontal overflow was observed. Keyboard focus remained on the source-run control across polling, showed a visible outline, and returned to Save after saving. The unavailable-player explanation stayed readable. The source changed from Gen 3 A to Gen 1 B while open; another pair source changed to Gen 1 while the page still selected Gen 3. Stopping that assigned run showed only its saved links; restarting restored live HP through the same URL and polling document.

Reproduce visual checks with `.venv/Scripts/python.exe tools/serve_manager_scenarios.py`. The helper prints its random loopback ports and exposes `/review/broadcast/{game}/{preset}` with optional `?theme=light`. Supported samples are gen3, gen1, doubles, gen2, gen4 and gen5. Review-only routes are registered by the helper, never the production manager. Screenshots of intermediate iterations and test logs remain under `.cache/phase7b-review` and `.cache/phase7b-*.log` locally.

## Remaining migration work and evidence

This phase does not qualify cartridge release readiness. The required Gen 3/Gen 1 emulator E2E paths remain outstanding, and the three full-suite skips remain skips. Representative Gen 2/4/5 data is presentation coverage only.

Gen 1's owner reconfirmed that no complete verified randomizer catalog/publisher handoff is available. Phase 8 remains gated; there is no fingerprint-only fallback. Phase 9 still needs table-driven production route registration, verified removal of duplicate handlers/templates/assets, final documentation and dependency consolidation, and coordinated cleanup of only owner-released checkouts. Continue these in this same working directory.
