# SLink UI migration — from two apps to one board, on master

*Handoff document. Rewritten 2026-09-14 by the session that built the mockups. Assume the
reader has none of that conversation.*

## Read this first

- **The design is already built and reviewed.** `server/static/mockups/a/index.html` on branch
  `claude/soul-link-ui-mockups-40f67b` is a working mockup of the target UI, refined over
  six rounds of feedback. Run `python -m server.manager --host 127.0.0.1` and open
  `http://localhost:8090/static/mockups/a/index.html` (the explicit `index.html` matters —
  `/static/` is mounted without `show_index`). Rationale: `docs/ui_mockup_brief.md` §3.
  **Do not redesign it.** Port it.
- **This is master work.** The `gen1/rc` durable-runtime line (135 `server/gen1_*.py`
  modules, `protocol.py`, `staged_state.py`, `rom_contract` admission) is **on hold** and is
  not a dependency of anything here. Ignore it and every `gen1-*` worktree.
- **The base commit is `79d5172`**, not `adf3362`. See "Sequencing" below — it is what master
  becomes as step 1 of the Gen 1 master release, and it carries the randomizer layer Phase 8
  wraps. Line numbers in this document are as-of `79d5172` where stated, otherwise as-of
  `adf3362` (the two differ only inside `SLinkServer` and `manager.py`); prefer the symbol
  names and re-derive numbers when you start.
- **Project convention** (`.github/copilot-instructions.md:85`): when changing shared code
  (`server.py`, `state.py`, `adapters/base.py`), verify Gen 3 first, then the other gens.
  `CLAUDE.md` is gitignored and local-only; `copilot-instructions.md` is the tracked
  agent-facing doc — 1 678 lines this migration will make stale (Phase 9).

## Context

SLink's browser UI is two apps on two ports, built two different ways, with nine
destinations between them:

| | Port | Built with | Size |
|---|---|---|---|
| Run Manager | 8090 | `templates/manager.html` + Alpine | 815 tmpl / 898 css |
| Run dashboard | 8081+ | Python string concatenation, `_build_status_html` | 1465 py / 1796 css |

**2 022 of `server.py`'s 8 231 lines are HTML/JS string literals** — `_DEBUG_HTML` (995),
`_OBS_PAGE_HTML` (481), `_TWITCH_PAGE_HTML` (260), `_CALC_PREVIEW_JS` (163),
`_LAUNCHER_TEMPLATE` (67), `_STATUS_HTML` (56). The Manager already embeds the run dashboard
in an `<iframe>`, which is the two pages admitting they want to be one.

**Outcome:** one origin, three destinations, the pair board as the run page, the Gen 1
randomizer wrapped so nobody opens UPR's GUI, ~2 500 lines deleted, ~1 900 moved out of
`server.py`, and a set of verified security bugs closed on the way.

---

## Sequencing against the Gen 1 master release

A parallel session ("Gen1 master release plan", worktree
`.claude/worktrees/gen1-master-release-plan-6b4279`, plan file
`~/.claude/plans/system-reminder-you-are-operating-gleaming-pretzel.md`) is releasing Gen 1
from master. Its step 1 is `git merge --ff-only 79d5172` — the first 50 commits of
`gen1/rc` (Aug 17–30), a linear bug sweep on master's own architecture, **0 conflicts against
master**. Its later steps (trade port, live verification, tag) touch `state.py`, `lua/`,
`patch/`, `adapters/`, `tests/live`, `tools/verify_gen1_release.py`. It explicitly does **not**
take anything from Sept 5 onward on `gen1/rc`.

What `79d5172` brings that this migration builds on:

| At `79d5172` | Used by |
|---|---|
| `server/upr_settings.py` (454) — `build_categories()`, `_CATEGORY_MODES`, `unexpected_settings()` allowlist | Phase 8 |
| `server/upr_pipeline.py` (269) — `prepare_pair()`, `randomize()`, `_check_content()` | Phase 8 |
| `server/adapters/gen1_rom_scan.py` — `identify()`, `scan_*` | Phase 8 (`_check_content`) |
| `manager.py:701 handle_randomize`, `manager.html:347-410` "Randomized ROMs" section, `tests/unit/test_manager_randomize.py` | Phase 8 — this is what gets wrapped |
| `manager.py:49 _json_for_script` + `tests/unit/test_manager_xss.py` | Keep |
| `variant_label(rom_type)` used at `manager.py:525` | Keep |
| `patcher.py:47 TARGETS` registry, `?game=`, `/companion/{name}` | Phase 7 Tools page |
| `tools/inject_full_mocks.py` `--game gen1` | Phase 0 conflict |

**Rule:** base this branch on `79d5172` now (Phase 0). Merge migration PRs to master only
after master contains `79d5172` — a trivial ordering, since that FF is the Gen 1 session's
first action. The two efforts then share no files:

| This migration owns | Gen 1 release owns |
|---|---|
| `server/server.py` (render path, `build_app`, HTML constants), `server/manager.py`, `server/templates/**`, `server/static/**`, `server/chrome.py`, `server/templating.py`, `server/obs_controller.py`, `tools/inject_full_mocks.py`, `tools/gen_ui_capabilities.py`, `tests/unit/test_{routes_smoke,theme_tokens,staleness,mockup_fixtures,dashboard_contract,manager_*}.py` | `server/state.py`, `server/adapters/**`, `lua/**`, `patch/**`, `tests/live/**`, `tests/e2e/**`, `tools/verify_gen1_release.py`, `docs/gen1_*`, `docs/REFERENCE.md` Gen 1 block |

The one shared seam: Phase 3 adds `capabilities` to the payload via `adapter_for(pid)` and
adds `gym_badge_slugs`-style predicates — **additive reads of the adapter, no edits to
`adapters/**`**. If a predicate is missing, add it in `adapters/base.py` as a default-returning
method in a one-line PR and tell the Gen 1 session.

---

## Worktree status — surveyed 2026-09-14

| Worktree / branch | State |
|---|---|
| `dreamy-pike-09f3e3` → `claude/soul-link-ui-mockups-40f67b` @ `121fb1c` | **This work.** Clean; 61 files / +6 375 over master: mockups, fixtures, brief, `inject_full_mocks` upgrades. |
| `gen1-master-release-plan-6b4279` @ `adf3362` | The parallel Gen 1 release. Coordinate, don't touch. |
| `gen1-rby-code-sweep-8d06e2` → `gen1/rc` @ `827b810` | On hold. **Read-only** — cherry-pick source for Phase 0 only. Never check anything out in it. |
| 16 other `gen1-*` / `codex/*` worktrees | On hold. Ignore. |
| `agent-a7f68e4f2daf34d8d` → `claude/ui-mockup-track-b` @ `05c419b` | Track B's failed first attempt, merged into this branch at `f309699`. Prunable (Phase 9). |
| `recursing-hopper-86c382` → `claude/codex-claude-connect-402b4e` @ `adf3362` | Unrelated. Ignore. |

---

## Decisions already taken

| Decision | Why |
|---|---|
| **Base on `79d5172`, phase per PR to master** | The FF is conflict-free and inevitable; each phase leaves the app working and demoable alone; regressions bisect to one phase. |
| **Track A = cherry-pick `064b57c` + `965cc12`, not a rewrite** | Someone on `gen1/rc` (Sept 5) already implemented every one of the nine verified bugs, with 1 086 lines of tests. Reuse beats rewrite. |
| **OBS points at the manager** (`:8090/stream/{slug}`) | Per-run HTTP ports become internal — but that URL must keep working forever. |
| **`Sec-Fetch-Site` middleware for CSRF** | Lua clients speak TCP; OBS issues same-origin GETs. No credentials. (`server/http_safety.py` from `064b57c`.) |
| **Delete `server/static/mockups/` once the board ships** | The board becomes the real UI; git history keeps the mockup. Takes Track B, the Svelte bundle and 24 unused fonts (453 KB). |
| **Randomizer targets Gen 1, wraps `handle_randomize` as it exists at `79d5172`** | That is the layer master gets; Gen 3 randomized already works without it (species read from RAM). Widening to other gens = adding a `_check_content` per adapter, later. |
| **Randomizer: server-side file picker, not upload** | Keeps the stated "nothing leaves this machine" policy (`manager.html:406`) and sidesteps that a Gen 1 ROM is *exactly* aiohttp's 1 MiB default body limit. |
| **Randomized ROMs get a per-player download** | Mirrors `handle_launcher`. Today the operator finds them on disk and hands them over out of band. |
| **Track A (the pair board), not Track B (Svelte SPA)** | Two independent agents built the SPA and both recommended against it: it retires nothing — the ~25 OBS overlays still need server-rendered fragments, so Jinja stays either way. |

## End state

| Destination | Absorbs |
|---|---|
| **Run** | Manager, Status, Memorial, Boxes — run rail + the pair board, one origin |
| **Broadcast** | Stream gallery, Twitch, OBS |
| **Tools** | Patcher (`TARGETS`, `?game=`), Randomizer |
| *(external)* Calc | unchanged, new tab |
| *(drawer)* Debug | `_DEBUG_HTML` + 15 endpoints |

`python -m server.server` keeps working: same templates, one run in the rail.

---

# Phase 0 — Rebase and harvest *(one PR: "base + security")*

1. `git rebase --onto 79d5172 master` on `claude/soul-link-ui-mockups-40f67b`. Verified
   in-memory (`git merge-tree`): **one conflict**, `tools/inject_full_mocks.py` — both sides
   added `--game gen1`. Take `79d5172`'s structure; keep this branch's `pc_boxes`, pending
   capture, low-HP mon, `HOLD` and single-socket fixes (they exist so the fixtures show a
   live run, not a half-disconnected one). Re-run `python tools/inject_full_mocks.py` for
   both games and confirm `tests/unit/test_mockup_fixtures.py` (14 tests) is green.
2. `git cherry-pick 064b57c 965cc12 dbad8d5` from `gen1/rc` (all three have `adf3362`-line
   parents; read them with `git show`, never check out that worktree):
   - `064b57c` **"harden HTTP boundaries and connection lifecycle"** — the whole of the
     old Track A: drive-letter escape in `handle_calc_files` (`ntpath.splitdrive` guard),
     `html.escape` on `rom_lbl`/`area_disp`/`last_event`, `_EMPTY_STATUS` from
     `status_payload.empty_status_payload()`, `lua_literals.lua_comment/lua_string` for the
     launcher, `http_safety._same_origin_request` middleware on both apps, `_errf` closed
     after spawn, `json_files.atomic_write_json` for the registry, OBS client disconnect
     before reconnect, the missing `player` guard at `server.py:7297`. Tests:
     `test_http_safety.py`, `test_http_server_security.py`, `test_manager_http_hardening.py`,
     `test_obs_lifecycle.py`. **Conflicts** (verified): `server/manager.py` (both sides edit
     `_EMPTY_STATUS`/registry/launcher — resolve by hand, keeping `79d5172`'s
     `handle_randomize` and `_json_for_script`) and `docs/ui_migration_plan.md`
     (modify/delete — **drop it**; this document replaces it). Also drop
     `docs/ui_projection_contract.md` from the pick: it describes a `capabilities` shape
     (`supported/requested/ready/effective`) tied to the on-hold runtime; Phase 3 defines
     the real one.
   - `965cc12` — its follow-up (printable legacy metadata survives escaping).
   - `dbad8d5` — `_party_snapshot()` shared between HELLO and tick, fixing the missing
     `stat_stages` on the hello frame, with `test_party_snapshot_dispatch.py`. Drop its
     `tests/portable_ci_inventory.json` hunk if it does not apply.
3. Pin `empty_status_payload()` to reality: extend `test_mockup_fixtures.py`'s
   `test_top_level_keys_match_build_status_dict` to also assert
   `set(empty_status_payload()) == set(_build_status_dict())` and the same per player.
   `status_payload.py` is a hand-maintained duplicate and will drift without this.
4. Also cheap here: `Cache-Control: no-cache` + `Vary: Cookie` on every theme-dependent
   handler (only `handle_calc_files` and `handle_patcher_page` have it, both with a comment
   explaining why the rest need it).

Gate: `pytest tests/unit tests/integration -q`, `ruff check .`. Expect ruff drift from the
sweep — the Gen 1 session's plan says the same; whoever hits it first fixes it in one commit.

---

# Phase 1 — Guard rails *(no behaviour change)*

Nothing pins the dashboard's markup, and one test will **start lying** the moment the
generator moves.

**New `tests/unit/test_dashboard_contract.py`.** Render from
`server/static/mockups/fixtures/gen3.json` — a generated capture with a populated party, PC
boxes, an active battle, a killfeed and per-player encounter tables, i.e. everything
`test_routes_smoke.py`'s fixture lacks. Assert every DOM contract `dashboard.js` depends on:

`#enc-table` · `#enc-filters` · `#dash-search-input` · `th.sortable[data-col]` **equal to the
`<td>` index** · `tr[data-status]` within the `FILTER_GROUPS` values · `td[data-sort]` on cols
0 and 3 · `table[data-no-search]` on the events log · header rows inside a real `<thead>` ·
`details[data-details-key]` **with a matching `id="d-{key}"`** (idiomorph matches by id first;
without it the veto never runs) · `<summary>` a **direct child** of its `<details>` ·
`img.mon-sprite[data-species]` · a unique `#calc-preview-{pid}[data-in-battle]` ·
pre-rendered HTML fields rendering `|safe` rather than escaped.

**Repoint `tests/unit/test_theme_tokens.py`.** It calls
`inspect.getsource(SLinkServer._build_status_html)` — an `AttributeError` at *collection*
once that method goes. Worse, its five hex-literal pins grep the whole of `server.py` and
will **pass vacuously** afterwards. Point both at `server/templates/**`, and add
`style="background:#…"` to the pattern — the gym-badge colours slip past a `color:#` regex today.

**Wire `_smoke.html` into a test.** The macro harness at `/memorial?_smoke=1` is exercised by
nothing. One async test asserting its known mock strings render.

**Add a route-count assertion** to `test_routes_smoke.py` (note `79d5172` already extends
this file by 73 lines). Routes are auto-discovered, so collapsing nine pages to three drops
~66 parametrized tests with nothing going red. Its per-route assertion is only
`status < 500` + non-empty body — it accepts a 404.

**Fix three live CSS collisions** where `dashboard.css` silently wins over `slink.css`
because `base.html` loads it second: `.lp-area`, `.enc-lv`, `.shiny-star`.

---

# Phase 2 — Free deletions

Verified dead against all Python and asset files, with dynamic dispatch and prefix
concatenation traced to their value domains. ~80 lines of Python, ~60 of CSS, 6 SVG symbols.

`_sse_heartbeat_loop` (its own body says the work happens in `handle_sse`) ·
`ALL_TRIGGER_EVENTS` (the dropdown it claims to drive is 18 hardcoded `<option>` tags) ·
`OBSController.get_config_safe` · `submit_trigger` · `_tio_bot` · `nuz_badge` ·
`obs_config_path`'s `pass` branch · the `sprite_html` `hasattr` guard the code itself labels
dead · six `hasattr(x, "value")` guards on enum members whose fallback is *wrong* if taken
(`str(AreaStatus.LINKED)` is `"AreaStatus.LINKED"`, not `"linked"`) · five `getattr` guards on
always-set attributes · six unused `<symbol id="i-*">` · the hard-dead CSS
(`.dash-sidebar-foot`, `.dash-sidebar-pulse`, `.chrome-card`, `.heading-glow`, `.et-sprite`,
`.mgr-preview-iframe`, `.phase-whiteout`, `.kf-unknown`).

Re-verify each against `79d5172` before deleting — the sweep added callers in `server.py`
(+373) and `manager.py` (+108).

---

# Phase 3 — The payload *(no UI change)*

In `_build_status_dict` and `_enrich_party`:

1. **`players.{pid}.capabilities`** via `adapter_for(pid)`, keyed per **rom_type** not per
   generation — `firered` and `firered_rr` differ on `explode_mode` and `info_panel`, because
   those come from the companion patch. A template asks `caps.abilities`, not "is this RR".
   `tools/gen_ui_capabilities.py` already probes exactly this set; its output is the shape:
   flat booleans/ints (`abilities`, `explode_mode`, `info_panel`, `stat_stage_labels`,
   `mons_per_box`, `info_panel_width`). Not the four-state `supported/requested/ready/
   effective` shape from the dropped `ui_projection_contract.md`.
2. **The mon key inside each `party_details` entry.** It is the dict key and is not repeated
   in the value; the mockup lost its entire partner column to this before it was noticed.
3. **`sprite_html` + `species_name` on `pending_captures`**, the way link halves get them, and
   a sprite that sizes itself via a class rather than a 40 px inline crop.
4. **Item names** — the payload carries `held_item_id` only, though the adapter resolves names.
5. **Make an unrecognised `rom_type` loud.** It currently leaves the server on whichever
   adapter it already had, silently. That gave the first Gen 1 fixture Gen 3 genders and
   abilities, and `server/adapters/__init__.py:53` records the same thing having happened to
   Gen 2. Reject the hello with an `identity_error` the UI already renders; log WARNING.
   (`8f97ea0` on `gen1/rc` does a version of this bound to the on-hold admission layer —
   do not pick it; write the ten-line version.)
6. **Delete the `leafgreen_rr` label** — nothing routes it and Radical Red has no LeafGreen
   build. Reword the README's "both players must run the **same game**": it means the same
   *family*; Red/Blue link fine.

Streamlining that belongs here because it is the same code:

- ~~Memoize `_build_status_dict` per tick.~~ **Dropped, measured:** 0.12 ms per build on the
  full Gen 3 cast (0.06 ms Gen 1); `_build_status_html` is 2.6 ms. Six OBS sources at 2 s is
  under 1 ms/s. A cache would have to survive every direct state mutation the tests and the
  API handlers make without `_notify_sse`, for no measurable gain.
- **Delete the `sprite_src` enrichment** — computed for every encounter entry on that hot
  path, read by nothing.
- **`_move_details()` helper** — `_enrich_party` and `_enrich_battle_state` carry 20
  byte-identical lines. (`_party_snapshot()` is already done by `dbad8d5` in Phase 0.)

Then regenerate the four fixtures (`docs/ui_mockup_brief.md` §7) and extend
`test_mockup_fixtures.py`. Items 1–3 fail `test_top_level_keys_match_build_status_dict` until
regenerated — by design; that test asserts set *equality*.

---

# Phases 4 + 5 — The board *(done as one step)*

**Merged, and why.** Phase 4 was "port 1 460 lines of f-strings into Jinja, same markup";
Phase 5 was "replace that markup with the board". Doing the first only to delete it in the
second was double work with no bisection value once the contract test was rewritten for
the board anyway. What survived from Phase 4's list: the pure-data context (now
`server/board.py`, ~200 lines, tested on the fixtures), `_STATUS_HTML` and
`_build_status_html` deleted (−1 846 lines from `server.py`), `_CALC_PREVIEW_JS` moved to
`server/static/calc-preview.js`, `test_staleness` retargeted, the GYM_BADGES palette gone
(the board draws badge pips from `capabilities.badges`), `_trainer_panel_html` kept in
Python and shipped in the payload as `players.{pid}.trainer_panel_html`.

**Server-rendered, not the mockup's Alpine.** The mockup fetched a fixture and rendered
client-side. The board is a Jinja template polled by htmx/idiomorph exactly as the old
dashboard was, because every page test in this suite renders in-process and CI has no
browser: a client-rendered board would have made `test_routes_smoke`,
`test_dashboard_contract` and `test_http_server_security` blind. `server/board.py` is the
port of `mockup.js`'s `pairs()` / `sections()` / `unlinkedBoxed()`, function for function.

What the payload gained for it: `players.{pid}.stale`, `last_seen_label`,
`trainer_panel_html`, `battle_state.calc_preview` (the data the calc script reads off
`#calc-preview-{pid}`, computed in `_calc_preview`).

Deleted with it: 224 lines of `dashboard.js` (encounter sort, filter, global search, the
Split|Combined toggle) and the `lp-view` bootstrap in `base.html`. **Not yet deleted:**
`dashboard.css` still carries the old dashboard's rules (player cards, tables, lp widget);
it goes in Phase 9 with `manager.css`/`sidebar.css`. `server/static/mockups/` stays until
Phase 6 has taken the rail and new-run form from it.

⚠ `data-details-key` values changed (`wild:{pid}` and the trainer panel's own); users lose
open/closed state once. Accepted.

# Phase 6 — One origin

- **Generalise the proxy.** `handle_run_live` is *already* the per-run proxy;
  `handle_proxy_status` differs only in run resolution and its empty-state fallback. Merge
  behind a `_run_http_port(run_id)` helper. Add `/runs/{run_id}/…` for the UI's own use and
  keep `/stream/{slug}` as a pin-resolving alias — OBS sources are bookmarked URLs.
- **Delete `handle_proxy_events`.** It contacts nothing and emits an unconditional ping every
  1.5 s. Nothing consumes it.
- **Pass the overlay prefix down.** `fragment_url` is generated by the *run* as a
  root-relative path, so a proxied overlay under a new prefix polls the wrong route after
  first paint. ~2 lines, a new context key.
- **`_active_stream_run()` stops calling `_get()`** — it reconciles, scans directories and can
  rewrite `registry.json` on every 2 s overlay poll, per browser source, on the event loop.
- **Fix the registry lost-update race.** `handle_start` reads the registry, awaits
  `_spawn_run`, then writes its stale snapshot. (`064b57c`'s `registry_errors` middleware
  and `_registry_runs` are the place to hang a single read-modify-write helper.)
- **Fix the pin indicator** — `manager.html` reads `j.run_id`; the endpoint returns
  `active_run_id`. It has never worked.
- Delete the iframe preview, `_augment_for_template`'s disk scraping (two `open()`s per run per
  index render), and the dead `_STATUS_BADGE`. Dedupe the 4-site run-lookup preamble (−24) and
  the 4-site proxy try/except (−30).
- The rail becomes runs + three destinations; the New run form lands here (mockup §3, game
  *families* — `variant_label` is on master already).

---

# Phase 7 — Collapse the pages

**Broadcast** = stream gallery + Twitch + OBS. The asymmetry to settle first:

| Panel | Config scope |
|---|---|
| Stream gallery | run-agnostic catalog + pin |
| Twitch bot | **per-run** (`data/runs/<id>/twitch_bot.json`) |
| OBS triggers | **global** (`data/obs_config.json`) |

**Decision: the manager owns `obs_config.json`; runs keep the WebSocket connections.** Today
two runs' OBS pages edit the same file with separate in-memory controllers — last writer wins.
Twitch scopes to the selected run and proxies its six `/api/bot/*` endpoints; its tokens come
from env vars read by the *run* subprocess, which inherits the manager's environment.

**Tools** = patcher (`TARGETS`, `?game=` — already at `79d5172`) + randomizer (Phase 8).
**Debug** becomes a drawer; its 709 lines of inline JS need one change — the fetch helper
gains a `/runs/{id}` prefix.

**Move ~1 900 lines of string literals out of `server.py`** — `_DEBUG_HTML` (995),
`_OBS_PAGE_HTML` (481), `_TWITCH_PAGE_HTML` (260) into `server/templates/`, `_CALC_PREVIEW_JS`
(163) into `server/static/`. Templating the debug page **also fixes its ~20 unescaped
`innerHTML` sites** — it is the one page with no `esc()` helper, and one of them pipes a
server error string straight in.

Then `server/chrome.py` `_NAV_ITEMS` 9 → 3, and update `HTML_ROUTES` in
`test_routes_smoke.py` by hand — the one route list that is not auto-discovered.

---

# Phase 8 — Wrap the randomizer *(Gen 1, on what `79d5172` ships)*

Today (`manager.py:701 handle_randomize`, `manager.html:382-410`): four typed absolute paths
(jar, `.rnqs`, two ROMs — `manager.html:865` says "paths rather than file pickers" on
purpose), a settings file the user must build in UPR's desktop GUI, a single blocking POST
with no progress, and outputs the operator hands over out of band. The form disappears once
`current.randomizer` is set, so there is no way back.

**What already exists at `79d5172` — most of the hard part:**
- `upr_settings.build_categories(enabled, fastest_text=True)` produces a byte-valid,
  CRC-correct `.rnqs` from a category set, proven against the real jar
  (`tests/unit/test_upr_settings.py`).
- Two-layer refusal: `forbidden_enabled()` blacklist plus `unexpected_settings()` — an
  allowlist computed via `permitted_byte_values()` *from* `build_categories` itself, so it
  cannot drift from what the pipeline supports.
- `upr_pipeline.prepare_pair(jar, settings_path, sources, out_dir)` drives the jar
  (`subprocess.run(timeout=600)` ×2, sequential), reads the seed from the log (UPR's CLI has
  no seed flag), re-reads the *effective* settings because `tweakForRom()` mutates them,
  `_check_content` verifies base stats and the evolution graph via `gen1_rom_scan.identify`,
  and refuses if the two seeds or content hashes match. Java presence is checked at
  `upr_pipeline.py:97`, *inside* the worker.
- `handle_randomize` writes `rom_contract.json` and `randomizer` into the run record;
  `test_manager_randomize.py` (172 lines) covers it with the jar stubbed.

The settings surface is exactly **six booleans plus Fastest Text**:

```python
_CATEGORY_MODES = {"wild", "starters", "statics", "trainers", "tms", "field_items"}   # upr_settings.py:259
```

deliberately excluding types, evolutions, movesets and base stats so species and type clauses
stay seed-independent. **Widening the UI means widening that one dict** — a UI offering
anything else produces a file its own allowlist rejects.

**What to build:**

1. **Settings from UI state.** Six checkboxes → `build_categories()` → write to
   `data/runs/{id}/settings.rnqs`; `handle_randomize` accepts `categories: [...]` as an
   alternative to `settings: <path>`. Keep the generated file, not just its hash — today the
   settings are unrecoverable after the fact. ~15 lines in `manager.py`.
2. **Jar discovery and persistence.** `find_upr_jar()` exists at `tests/conftest.py:111`
   (searches `$SLINK_UPR_JAR`, repo root, `tools/`, `.cache/upr/`, walking up through
   worktrees). Lift it into `server/upr_pipeline.py`, call it when `jar` is blank, and store
   the resolved path in the manager's config so it is typed once.
3. **Preflight endpoint.** `GET /api/randomizer/status` → jar found, `shutil.which("java")`,
   and for each ROM `gen1_rom_scan.identify(rom)["clean"]`. Today a missing Java or a dirty
   dump costs up to twenty minutes inside `to_thread` to discover.
4. **Server-side file picker.** `GET /api/browse?dir=…&ext=.gb,.gbc,.jar` returning entries,
   rooted at the user's home and refusing traversal with the same `ntpath.splitdrive` guard
   `064b57c` put in `handle_calc_files`. No upload, so the policy holds and the 1 MiB body
   limit stays irrelevant. (If uploads are ever wanted: `client_max_size` is unset, aiohttp's
   default is 1 MiB, a Gen 1 ROM is *exactly* 1 048 576 bytes, and the 413 surfaces to the
   user as a `SyntaxError`.)
5. **Progress.** Job id + `GET /api/randomizer/jobs/{id}` poll — **not** SSE, for the reason
   `_STATUS_HTML` documents. `prepare_pair` grows an optional `progress(stage)` callback
   (`"a"`, `"b"`, `"verify"`), three lines.
6. **Per-player download.** `GET /api/runs/{id}/rom/{player}`, mirroring `handle_launcher`,
   `web.FileResponse`, renaming `.gbc` → `.gb` on the way out so BizHawk picks the DMG core
   and finds the battery save. Wrong-file mixups are already caught by `rom_contract.json`.
7. **A re-randomize path** — the form stays reachable when `current.randomizer` is set, and
   re-running rewrites `rom_contract.json` and the `randomizer` record together.

Note `ALL_CATEGORIES` is hardcoded in three test files, duplicating `_CATEGORY_MODES`; make
them import it.

---

# Phase 9 — Cleanup

- **Table-drive the overlays** from `overlay_catalog.OVERLAYS`. 47 of 54 handler methods are
  ≤ 4 lines differing by one string; titles exist in **three** places and have drifted
  (catalog "Memorial Scroll" vs template "In Memoriam"). `_render_stream_overlay` is *already*
  the generic renderer, and `test_routes_smoke.py` walks the live router. **−200 lines.** Do
  **not** table-drive the builders — their 377 lines are real joins.
- **One poller.** Six today. Keep htmx polling — **do not reach for SSE**: `_STATUS_HTML`
  documents why (Chrome's 6-connections-per-origin cap), and a single origin makes it worse.
  `stream_index.html` loads **no htmx** and hand-rolls `fetch('/api/status')` as a result.
- **Load Alpine conditionally** — 44 KB ships on every templated page while three templates use
  a directive. `dashboard.js:380-511` is a second, vanilla theme switcher (−132).
- **Delete `manager.css` (898) and `sidebar.css` (328)** — 230 of `sidebar.css`'s lines are
  byte-identical to `dashboard.css` — plus the remainder of `dashboard.css` and ~300 lines of
  `stream_index.html`'s inline CSS. `.font-switcher` is defined three times; `.tomb-*` twice.
- **One chroma-keyer** — `dashboard.js:35` and `overlay-helpers.js:31` are the same function.
- **The 10-rule flag table** is written out by hand at 12 sites and **has drifted**:
  `handle_new` sets `verbose`, `_adopt_orphans` does not. One tuple table drives all 12. **−140.**
- **`requirements.txt` 8 → 3.** `pytest`/`pytest-asyncio` are test-only; `twitchio`,
  `simpleobsws`, `psutil` are already lazily imported or `ImportError`-guarded. Extras.
- **Docs.** 106 routes registered; 69 paths appear across `docs/REFERENCE.md` and
  `.github/copilot-instructions.md`; **29 registered routes appear in neither.** Generate the
  table from `build_app()`'s router, or test that documented matches registered (the
  `tests/unit/test_first_run.py` pattern). Then README's two-server table and diagram,
  `.claude/launch.json`, `tools/inject_full_mocks.py`'s default port. Leave the Gen 1 block
  of `REFERENCE.md` to the Gen 1 session.
- **Flip `--font-ui` in `slink.css`** to Jersey 20, after checking every overlay in
  `overlay_catalog.py` at its catalogue size — Jersey is condensed and moves overlay text
  widths inside fixed-size OBS browser sources.
- **`calc/src/js/slink_bridge.js`** reads its hardcoded `var C = {…}` palette from the tokens.
- **Prune** `claude/ui-mockup-track-b` and its `agent-a7f68e4f2daf34d8d` worktree
  (`shutil.rmtree` with the `S_IWRITE` onerror — Drive leaves read-only admin dirs; never
  `Remove-Item`). Touch no `gen1-*` worktree.

---

## Contracts — things that must not move

**API paths.** `tools/e2e_duo.py` hardcodes `/api/status`, `/api/inject_link`,
`/api/debug/set_pokeballs`, `/api/debug/queue_command`; `tools/inject_full_mocks.py` needs
`/api/reset` and `/api/attempts`; `tools/verify_gen1_release.py` (Gen 1's) drives the duo
runner over the same paths. E2E runs only under `SLINK_E2E=1` on Windows with BizHawk — **CI
will never tell you these broke.** The Debug *drawer* is a UI change; the run's
`/api/debug/*` paths stay exactly where they are. `POST /api/runs/{id}/randomize` keeps its
`jar/settings/rom_a/rom_b` body — `test_manager_randomize.py` pins it; Phase 8 adds fields.

**Overlay URLs.** 25 slugs × `?theme= &layout= &speed= &pause=` + event filters, pasted into
OBS once. `server/templating.py:56` already carries scar tissue from the last rename
(`_THEME_ALIASES = {"dark": "default"}`): **add aliases, never rename.** Both `/stream/{slug}`
and `/stream/{slug}/fragment` must survive.

**localStorage / cookie.** `slink-theme` (also read server-side by `resolve_theme`),
`slink-font`, `slink-sidebar-collapsed`, `slink-lp-view`, `slink-stream-rail-collapsed`,
`slink_prep_trainer`, `slink_prep_encounter`, and the per-`<details>` keys.

**Launcher `.lua` files** are on users' disks and connect over TCP — safe as long as TCP port
allocation is untouched. Two forked copies of that template exist (`server.py:~5845`,
`manager.py:~124`) and have **diverged** (different folder pickers); take the manager's.

**Lua clients reference no HTTP at all.** The emulator half — and therefore the whole Gen 1
release — is insulated from this work.

## Risk register

| Risk | Mitigation |
|---|---|
| A migration PR merges before master has `79d5172` | Phase 0 rebases onto it; PRs are FF-only over master, so the merge simply refuses |
| Gen 1's trade port (~25 lines in `state.py`) lands while Phase 3 edits `_build_status_dict` | Disjoint files by construction (table above); rebase per phase |
| `064b57c` cherry-pick resolved wrong in `manager.py` | Its own 335-line `test_manager_http_hardening.py` plus `test_manager_randomize.py` and `test_manager_xss.py` from the other side must all pass |
| `test_theme_tokens.py` silently stops guarding hex literals | Phase 1 repoints it *before* Phase 4 deletes the method |
| Route-smoke coverage shrinks invisibly as pages collapse | Phase 1 adds a count assertion |
| A page renders but is broken — smoke accepts 404 | Phase 1's contract test plus `_smoke.html` wired up |
| Dropping one dashboard view changes behaviour, not just markup | Do it in Phase 4 with the contract test green, not incidentally |
| Widening the randomizer UI past `_CATEGORY_MODES` | Produces files its own allowlist rejects; that dict is the single point of change |
| The file-picker endpoint becomes a directory-listing hole | Root at home, reuse the `064b57c` drive/traversal guard, list only, never read |
| `tests/conftest.py` patches data paths only in `server.state` and `server.server` | Do not add a new module holding a path constant — it would write into the real `data/` |

## Verification

Per phase: `pytest tests/unit tests/integration -q` (CI's exact command) and
`ruff check . --select E9,F6,F7,F81,F82` — `F821` is the cheapest early signal after a large
deletion. CI runs neither `tests/live` nor `tests/e2e`.

Per phase in the browser: `python -m server.manager --host 127.0.0.1`, walk the changed
surface at 1100 px and 1600 px, in `default` + `light` + one Funtastic theme, on both the
Gen 3 and Gen 1 fixtures. Confirm by screenshot.

- **Phase 0:** all four `064b57c` test files green alongside `test_manager_randomize.py`
  and `test_manager_xss.py`; `GET /calc/C:/Windows/win.ini` → 403.
- **Phases 4–5:** render both fixtures through the new templates and diff the DOM-contract
  set against Phase 1's baseline.
- **Phases 6–7:** load two overlays through the manager proxy and confirm they still poll
  after first paint — the `fragment_url` trap.
- **Phase 8:** one real randomize against the actual jar and two clean Red/Blue dumps;
  `tests/unit/test_upr_pipeline.py::TestAgainstTheRealJar` skips without `SLINK_UPR_JAR`, so
  it proves nothing in CI. Then boot one output in BizHawk with the launcher and confirm the
  hello is admitted (the `rom_contract.json` path).
- **Before the final merge, once:** `SLINK_E2E=1 pytest tests/e2e/test_duo.py`, machine
  idle, because nothing in CI exercises the four API paths it depends on. Coordinate the
  emulator lane with the Gen 1 session — one lane, and they are using it.

## Ledger

| | Lines |
|---|---|
| Deleted outright | ~2 500 |
| Moved out of `server.py` into templates/static | ~1 900 |
| Harvested from `gen1/rc` (3 commits, incl. 1 086 test lines) | +1 800 |
| Static assets removed | ~800 lines + 453 KB of fonts |
| `server.py` after | ~4 300, from 8 231 |

## First step

Phase 0 step 1. Then copy this file to `docs/ui_migration_plan.md` (replacing the `064b57c`
version) and point `docs/ui_mockup_brief.md` §9 at it.
