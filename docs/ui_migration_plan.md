# SLink UI migration — from two apps to one board, on master

*Handoff document. Rewritten 2026-09-14 by the session that built the mockups. Assume the
reader has none of that conversation.*

**Status (2026-09-14, session 3, later):** Phases 0–9 (7 now actually complete) are committed on
`claude/soul-link-ui-mockups-40f67b` (worktree `dreamy-pike-09f3e3`, based on `79d5172`,
suite 2 603 green). Phase 8b shipped: every SLink-compatible UPR option is exposed from one
table (`upr_settings.OPTIONS`), proven against the real jar (trainers +50 % → Youngster #1
Lv11→17, all fully evolved; wild −20 %; catch rate 3). Phase 9 closed: `sidebar.css` is the
one rail stylesheet (`dashboard.css` @imports it, −566 lines of duplicate rules),
`calc/src/js/slink_bridge.js` reads the slink.css tokens, `server/html_render.py` deleted
(nothing but tests called it; the status tests now render the `status_pill` macro).
**Not flipped, on purpose:** `--font-ui` stays Pixelify for the run pages and the 25 OBS
overlays — the board already sets Jersey 20 for itself (`body.board`), every page has the
font picker, and re-fonting overlays users have sized in OBS is the owner's call, not a
cleanup. **Phase 7 finished properly (session 3):** Twitch and OBS are on the Manager at
`/broadcast/twitch` and `/broadcast/obs` (rail sub-items under Broadcast), in the board chrome,
scoped to the pinned run: the panels are Jinja partials (`_twitch_panel.html`,
`_obs_panel.html`, tokenised, style-scoped) shared with the run server's own `/twitch` and
`/obs`, and the Manager relays `/api/bot/*` + `/api/obs/*` verbatim to that run
(`handle_proxy_api`). Earlier sessions had marked Phase 7 done with those two panels still
only on the run server and unlinked from the Manager — that was under-reported. **Session 4 sweep — one chrome everywhere:** the run's debug tools and damage
calculator are Manager pages (`/runs/{id}/debug`, `/runs/{id}/calc/*.html`, template
`run_panel.html`, partials `_debug_panel.html` / `_calc_panel.html`, both style-scoped and
tokenised), reached through a **per-run relay** `/runs/{id}/api/{tail}` that pipes SSE
too (`handle_run_api`); `server/calc_files.py` is the calc resolver both apps share; the
patcher wears the rail (`setup_patcher_routes(app, chrome)`); and **a run the Manager
spawned redirects every page it used to render to the Manager** (`SLinkServer._to_manager`:
`/`, `/memorial`, `/debug`, `/twitch`, `/obs`, `/calc/*.html`, `/patcher`, `/stream` →
`/broadcast`), keeping overlays, the API, the calc's files and the `_smoke=1` harness. The
run server's own pages remain only for standalone `python -m server.server` — and since
2026-09-17 those wear the same shell too: `_rail.html` has a `standalone` mode (one run,
its own pages), `panel_page.html` is the one-panel page for both apps, `dashboard.html` is
the `.mk` shell around the board, and `chrome.py`, `dashboard.css`, `sidebar.css`, the
sidebar-collapse code and the six old wrappers are deleted. One chrome in the tree. Not a drawer
in the end: the debug JS is 700 lines of page-scoped script that expects a load, so it is
a page with Board · Calc · Debug tabs, which the owner accepted. Deliberately not done: the
Manager owning `obs_config.json`.
**Gen 1 session (2026-09-14) acknowledged the randomizer requirements** and found one real
gap from them: their rewritten client (`lua/gen1/client.lua`) was not sending `rom_content`
in the hello — card ROM-CONTENT-1 is adding it with a test that
`content_fingerprint(payload) == fingerprint_rom(dump)` on all three clean dumps; the live
"admitted" boot of a randomized ROM is queued on their emulator lane. Owner to force-delete the three
`claude/ui-mockup-track-b*` branches (a hook blocks it here). **Merged:** master is `e2fefa9` (the owner fast-forwarded master to `79d5172`; this branch
was then fast-forwarded onto it in the root checkout, 2 630 green there; nothing pushed). The
Gen 1 release branch rebases onto it next — their conflicts are the three listed in the
Sequencing section. Two Gen 1-owned docstrings still name `html_render.
status_icon_html` (`adapters/gen1_rby.py:476`, `adapters/gen3_frlge.py:326`) — tell that
session; the decoder is now `templates/_macros.html::status_pill`.
**Follow-ups (2026-09-20, on master):** sprites flickered every poll — idiomorph re-synced each
`<img src>` from the server HTML, undoing the onerror fallback and the chroma-key; the
idiomorph attribute hook in `dashboard.js` now leaves `src`/`style`/`data-bg-removed` alone
while `data-species` is unchanged (the funnotbun-only regex patch is gone). The rail's runs
scroll between the pinned top and the pinned destinations, archived runs fold under a count.
The randomizer's cartridges are found, not typed (Phase 8 item 4; `GET/POST /api/roms`),
described in plain words with their family, and a run's game names the family it takes
(`GAME_FAMILY`; `handle_randomize` refuses the other by name — a pure run had been built from
vanilla dumps with nothing objecting). A randomized run offers its cartridges on the empty
board and under *Launchers ▾*. Presets and `.rnqs` export/import: Phase 8 item 8.

## Read this first

- **The design is built and shipped.** The pair board is `server/board.py` +
  `server/templates/_board.html`; the Manager shell is `server/templates/manager.html`; the
  styling is `server/static/board.css` on the `slink.css` tokens. It was ported from a mockup
  refined over six rounds of owner feedback (the mockup itself was deleted in Phase 9a and is
  in history at `aa246f6^`). Rationale: `docs/ui_mockup_brief.md` §3–4. **Do not redesign
  it.** Run it: `python -m server.manager --host 127.0.0.1` → `http://localhost:8090/`.
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
| `dreamy-pike-09f3e3` → `claude/soul-link-ui-mockups-40f67b` @ `6a66b57` | **This work.** Clean, based on `79d5172`. |
| `gen1-master-release-plan-6b4279` @ `e653e86`+ | The parallel Gen 1 release (adapter rewrite from pret, on `79d5172` + `07ba1ca`). Coordinate, don't touch. |
| `gen1-rby-code-sweep-8d06e2` → `gen1/rc` @ `827b810` | On hold. **Read-only** — cherry-pick source for Phase 0 only. Never check anything out in it. |
| 16 other `gen1-*` / `codex/*` worktrees | On hold. Ignore. |
| (removed) `claude/ui-mockup-track-b*` | Track B branches; the worktree is gone, the three branches await the owner's force-delete. |
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

# Phase 6 — One origin *(done)*

The Manager is the UI. Selection is a URL, not client state:

| Route | What |
|---|---|
| `GET /` | shell with the first running run (or the first run), else the New-run form |
| `GET /runs/{id}` | shell + that run's header (start/stop/pin/launchers/archive/delete) + its board |
| `GET /runs/{id}/board` | the `#content` fragment the shell polls every 2 s |
| `GET /new` | the New-run form: game family first, options greyed with reasons |
| `GET /api/runs/{id}/live` | the run's payload as JSON (kept) |

`board_context()` in `server/board.py` takes the payload only, so the Manager renders
`_board.html` for a **stopped** run from what it persisted (a throwaway `SLinkServer`
on the run's directory rebuilds the payload; no writes happen on construct). `live=False`
turns "waiting for hello" into "run not running".

`server/manager.py` gained the game-family table (`GAMES`) and the option table
(`OPTIONS`, `OPTION_SUPPORT`, `option_support()`, `new_run_form()`); `/api/runs/new`
stores `game`. `_update_run()` closes the start/new registry lost-update; `_active_stream_run()`
no longer reconciles on every overlay poll; `handle_proxy_events` is gone; `manager.css` is
gone (rail switcher rules moved into `board.css`). The old manager page and its 400 lines
of Alpine live-status code are gone with it.

**Not done here, deliberately:** the `/stream/{slug}` proxy is unchanged — `fragment_url`
is the same path on both origins, so no prefix problem exists; Broadcast and Tools rail
items point at the existing pages until Phase 7.

# Phase 7 — Collapse the pages *(done — Twitch and OBS landed in session 3; see Status)*

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
4. **File picker.** ~~`GET /api/browse` directory listing~~ — superseded 2026-09-20: the
   creator lists what is in the SLink folder (`GET /api/roms`, each file with the scanner's
   verdict, the first two clean dumps preselected) and anything else comes in through the
   browser's own file dialog (`POST /api/roms`, multipart streamed through
   `request.multipart()`, which the 1 MiB `client_max_size` does not apply to; 64 MiB cap of
   its own). Uploads land in `<repo>/roms/`, which .gitignore already refuses.
5. **Progress.** Job id + `GET /api/randomizer/jobs/{id}` poll — **not** SSE, for the reason
   `_STATUS_HTML` documents. `prepare_pair` grows an optional `progress(stage)` callback
   (`"a"`, `"b"`, `"verify"`), three lines.
6. **Per-player download.** `GET /api/runs/{id}/rom/{player}`, mirroring `handle_launcher`,
   `web.FileResponse`, renaming `.gbc` → `.gb` on the way out so BizHawk picks the DMG core
   and finds the battery save. Wrong-file mixups are already caught by `rom_contract.json`.
7. **A re-randomize path** — the form stays reachable when `current.randomizer` is set, and
   re-running rewrites `rom_contract.json` and the `randomizer` record together.
8. **Presets, and the `.rnqs` back** *(2026-09-20)*. Named specs on the Manager
   (`data/runs/presets.json`, `GET/POST /api/presets`, validated by `build_spec`). The
   interchange file is UPR's own `.rnqs`, not a format of ours: `POST
   /api/randomizer/settings/export` writes the bytes `randomize` would write for the spec,
   `POST /api/randomizer/settings/import` admits a GUI-built or another run's file through
   `upr_pipeline.admit_settings` — the version check, `forbidden_enabled` and the
   `unexpected_settings` envelope lifted out of `prepare_pair`, so a file that randomizes
   types is refused by name rather than read back as "unchanged" — and `GET
   /api/runs/{id}/settings.rnqs` serves the file a pair was built with.

Note `ALL_CATEGORIES` is hardcoded in three test files, duplicating `_CATEGORY_MODES`; make
them import it.

---

# Phase 8b — Expose the rest of the randomizer *(done)*

Owner (2026-09-14): *"we need to expose more of the randomizer settings, such as level curve
and other difficulty adjustments. If it's compatible with SLink, we should allow it."*

## What "compatible" means here

The pipeline's refusal rule (`upr_settings.forbidden_enabled`) is the definition: anything
that changes **types, evolutions, level-up movesets, base stats or move data** is out,
because the species and type clauses must mean the same thing on both cartridges and
`_check_content` verifies base stats + the evolution graph survived. Everything that only
changes *which* species appears where, at what level, with what items/TMs, is in. Two
extra exclusions found while researching: **`standardizeEXPCurves` / `selectedEXPCurve`**
write the growth-rate byte inside Gen 1's base-stats table, so `_check_content` would
refuse the ROM; and **`ALLOW_PIKACHU_EVOLUTION`** (Yellow) changes an evolution. In-game
trade randomization is left out too: the Gen 1 client's NPC-trade `key_change` path and the
gift-area logic reason about specific species, and nobody has tested them on randomized
trades.

## The byte layout, from the primary source

`Settings.toString()` in UPR ZX **v4.6.1** — fetched and read this session from
`https://raw.githubusercontent.com/Ajarmar/universal-pokemon-randomizer-zx/v4.6.1/src/com/dabomstew/pkrandom/Settings.java`
(2 389 lines; `toString()` starts at line 364). `makeByteSelected(a, b, c, …)` puts argument
*i* at bit *i*. The bytes the new options touch, verbatim from that method:

| Byte | Layout | Options it carries |
|---|---|---|
| 0 | bit3 `randomizeTrainerNames`, bit4 `randomizeTrainerClassNames` (bits 0,1,2,5,6 are forbidden evo/move tweaks) | trainer names |
| 4 | bit0 CUSTOM, bit1 COMPLETELY_RANDOM, bit2 UNCHANGED, bit3 RANDOM_WITH_TWO_EVOLUTIONS, bit4 `randomizeStartersHeldItems`, bit5 `banBadRandomStarterHeldItems`, bit6 `allowStarterAltFormes` | starters mode |
| 13 | bit0 UNCHANGED, bit1 RANDOM, bit2 DISTRIBUTED, bit3 MAINPLAYTHROUGH (Gen 5 only — `tweakForRom` demotes it), bit4 TYPE_THEMED, bit5 TYPE_THEMED_ELITE4_GYMS | trainers mode |
| 14 | `(trainersForceFullyEvolved ? 0x80 : 0) \| trainersForceFullyEvolvedLevel` | force fully evolved from level N |
| 15 | bit0 CATCH_EM_ALL, bit1 AREA_MAPPING, bit2 restriction NONE, bit3 TYPE_THEME_AREAS, bit4 GLOBAL_MAPPING, bit5 wild RANDOM, bit6 wild UNCHANGED, bit7 `useTimeBasedEncounters` | wild mode + restriction |
| 16 | bit0 `useMinimumCatchRate`, bit1 `blockWildLegendaries`, bit2 SIMILAR_STRENGTH, bit3/4 held items (Gen 1: cleared by `tweakForRom`), bit7 `balanceShakingGrass` | min catch rate, legendaries, similar strength |
| 17 | bit0 UNCHANGED, bit1 RANDOM_MATCHING, bit2 COMPLETELY_RANDOM, bit3 SIMILAR_STRENGTH, bit4 `limitMainGameLegendaries`, bit5 `limit600`, bit6/7 alt formes / megas | statics mode |
| 18 | bit0 compat COMPLETELY_RANDOM, bit1 RANDOM_PREFER_TYPE, bit2 compat UNCHANGED, bit3 tms RANDOM, bit4 tms UNCHANGED, bit5 `tmLevelUpMoveSanity`, bit6 `keepFieldMoveTMs`, bit7 compat FULL | TM moves + compatibility |
| 24 | bit0 RANDOM, bit1 SHUFFLE, bit2 UNCHANGED, bit3 `banBadRandomFieldItems`, bit4 RANDOM_EVEN | field items |
| 27 | bit0 `trainersUsePokemonOfSimilarStrength`, bit1 `rivalCarriesStarterThroughout`, bit2 `trainersMatchTypingDistribution`, bit3 `trainersBlockLegendaries`, bit4 `trainersBlockEarlyWonderGuard` (Gen 1: cleared), bit5 swap megas, bit6 `shinyChance`, bit7 `betterTrainerMovesets` | trainer difficulty |
| 32–35 | misc tweaks, big-endian int (`MISC_TWEAKS` already transcribed) | fastest text, PC potion, lower-case names, nerf X Accuracy, fix crit rate, update type effectiveness |
| 36 | `(trainersLevelModified ? 0x80 : 0) \| (trainersLevelModifier + 50)` | **trainer level curve −50…+50 %** |
| 38 | `(wildLevelsModified ? 0x80 : 0) \| (wildLevelModifier + 50)` | wild level curve |
| 47 | `(staticLevelModified ? 0x80 : 0) \| (staticLevelModifier + 50)` | static level curve |
| 50 | `eliteFourUniquePokemonNumber \| ((minimumCatchRateLevel − 1) << 3)` | min catch rate level 1–5 |

**Why the level modifier probes "did nothing":** the session's first experiment set bit 7 of
*byte 13* — the boolean lives in byte 36's own top bit (`0x80 | (mod+50)`), and likewise
byte 38 / 47 / 14 carry their own enable bit. Every byte in the table above was read from
`toString()`, not guessed; the existing `FLAGS` dict in `upr_settings.py` is consistent with
it (bytes 13, 15, 16, 17, 18, 24, 27 match exactly).

`tweakForRom()` (Settings.java:904) for `Gen1RomHandler` clears: `limitPokemon`, wild and
starter held items, `trainersBlockEarlyWonderGuard`, time-based encounters, move tutors,
in-game trade items/IVs, abilities. Offering those to a Gen 1 run is harmless but pointless;
the form should not.

## The option set to expose

| Group | Option | Bytes | Compatible | UI |
|---|---|---|---|---|
| Wild | mode: random / 1-to-1 area mapping / global 1-to-1 | 15 | ✓ | choice |
| Wild | restriction: none / similar strength / catch 'em all / type-themed areas | 15, 16 | ✓ | choice |
| Wild | block legendaries (default on) | 16 | ✓ | bool |
| Wild | minimum catch rate level 0(off)…5 | 16, 50 | ✓ | int |
| Wild | **level curve** −50…+50 % | 38 | ✓ | int |
| Starters | random / random with two evolutions | 4 | ✓ | choice |
| Statics | random / random matching / similar strength; level curve | 17, 47 | ✓ | choice + int |
| Trainers | mode: random / distributed / type-themed / type-themed gyms+E4 | 13 | ✓ (not MAINPLAYTHROUGH) | choice |
| Trainers | similar strength · rival carries starter · block legendaries (default on) · match typing distribution | 27 | ✓ | bools |
| Trainers | **level curve** −50…+50 % | 36 | ✓ | int |
| Trainers | force fully evolved from level 1…100 (0 = off) | 14 | ✓ | int |
| Trainers | randomize trainer names / class names | 0 | ✓ (cosmetic; killfeed shows whatever the cartridge says) | bools |
| TMs | TM moves random; compatibility unchanged / random / prefer type / full; level-up sanity; keep field-move TMs | 18 | ✓ (TM compat is not a learnset) | choice + bools |
| Field items | random / shuffle / random even; ban bad items | 24 | ✓ | choice + bool |
| Misc | fastest text (on) · randomize PC potion · lower-case names · nerf X Accuracy · fix crit rate · update type effectiveness | 32–35 | ✓ (none touch species/types/evos; Gen 1 has no calc to mislead) | bools |
| — | in-game trades, held items, EXP curves, `ALLOW_PIKACHU_EVOLUTION`, movesets/types/evos/base stats/move data | | ✗ | not offered |

## What was built (2026-09-14)

- `server/upr_settings.py`: **`OPTIONS`** — 29 options in 7 groups, each `kind`
  bool/choice/int with how it lands (`flag`/`misc`/`choices`→flags/`byte`+`encode`+`decode`).
  `build_spec(spec)` validates (unknown key, bad choice, out-of-range int, non-bool →
  `UprSettingsError` naming the option) and writes; `spec_from_parsed` is the exact inverse;
  `summarize(spec)` is the one-line record ("wild encounters 1-to-1 per area, trainer level
  curve +30%, fully evolved from level 36"); `option_form()` is the JSON the page renders;
  `build_categories` is a wrapper (old callers untouched). `permitted_byte_values()` now
  enumerates per-byte products over the options that touch each byte — exact, ~1 000
  builds, still cached. `trainersMatchTypingDistribution` (27,2) added to `FLAGS`.
- `server/upr_pipeline.py`: the base-stats comparison ignores `catch_rate` (Gen 1 keeps it
  in the base-stats record and the minimum-catch-rate option legitimately raises it; no rule
  reads it). Players are compared on the full effective `spec`, not just categories; the
  result carries `spec` and `summary`.
- `server/manager.py`: `POST …/randomize` takes `spec`; the run record and the page's
  "randomized: …" line carry `summary`; `_randomizer_form` ships `options`.
- `_randomizer_fields.html` renders `rform.options` by group (`fieldset.mk-rgroup`, chips
  for choices, `.mk-opt` for bools, `<input type=range>` + `.num` readout for the curves;
  double-click a slider to reset it; "Reset to defaults"); `randomizer.js` keeps
  `rdraft.spec`, seeded from the run's last pair on the rebuild page. `board.css`: the
  `.mk-r*` block (CSS columns pack the uneven groups).
- Tests: every option value round-trips and is admitted; the full spec round-trips; the
  level-curve/force-evolved/catch-rate bytes are pinned to the `Settings.toString()` layout;
  a two-mode-bits file is refused; bad specs are 400s naming the option; the manager writes
  `settings.rnqs` from a `spec` body.

## How it was built (the shape)

1. **`upr_settings.py`:** an `OPTIONS` table — name → `{kind: bool|choice|int, default, choices|range, group, label, help, writes}` where `writes` is how a value lands (flag names, or `(byte, mask, fn)` for the numeric bytes). Extend `build(flags, misc, rom_name, *, bytes_override)` to take raw byte values for 14/36/38/47/50. `build_spec(spec) -> bytes` validates against `OPTIONS` and writes; `build_categories(enabled, fastest_text)` becomes a thin wrapper (its callers — `manager.handle_randomize`, four test files — keep working). `spec_from_parsed(parsed) -> dict` is the inverse, so the run's `randomizer` record and the "randomized: …" line can say *trainers +30 %, force evolved from 36* instead of a category list.
2. **The envelope stays exact:** `permitted_byte_values()` currently enumerates 2⁶×2 whole files. Replace with per-byte products: for each byte, the options that touch it (discover by building each single-option variant against the default and diffing), then enumerate the product of their value sets for that byte only. The level-modifier bytes each have 1 option × 102 values; byte 15 has 3 × 4; byte 16 has 2 × 2 × 6; nothing explodes. `unexpected_settings()` needs no change — it reads the envelope.
3. **`handle_randomize`:** accept `spec: {...}` (the form's state) as the third alternative to `settings`/`categories`; `categories` stays for the tests and for `tools/`.
4. **`_randomizer_fields.html` + `static/randomizer.js`:** render `OPTIONS` by group (chips for choices, `.mk-opt` for bools, a range or number input for the curves with the value shown in `.num`); `rdraft` becomes the spec; the preflight and browse parts are unchanged. Ship `OPTIONS` to the page inside `SLINK_RANDOMIZER` (from `_randomizer_form`).
5. **Tests:** `tests/unit/test_upr_settings.py` — round-trip every option through `build_spec` → `load` → `spec_from_parsed`; the envelope accepts every `build_spec` output and still refuses the hand-built forbidden files; `test_manager_randomize.py` — a `spec` body. **Then one real run against the jar with trainers +50 % and force-evolved-from-1, reading the log's `#1 (YOUNGSTER)` line** (baseline Lv11 → expect Lv16, all evolved) — the log lists every trainer's team and every wild slot, which is how each option's effect is provable in seconds (`scratchpad/upr_probe.py` from this session did exactly that; 0.5 s per randomize).

# Phase 9 — Cleanup *(done; see Status for what was left alone and why)*

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

**Gen 1 wire facts the board honours** (from the Gen 1 release session, 2026-09-14): every
`species_id` on the Gen 1 wire is the game-INTERNAL index (internal 1 = Rhydon, 153 =
Bulbasaur), so names, sprites and types come only from the adapter — the board reads
`species_name` / `sprite_html` the server already resolved and never treats `species_id` as a
dex number (`grep species_id server/board.py server/templates/_board.html` is empty by
design); `stat_stages` is a 7-slot list whose 5th label is blank on Gen 1 (`capabilities.
stat_stage_labels`); `pp_ups` is a list; `status_cond` uses the Gen 3 bit layout. The Gen 1
hello adds `ot_id`, `rom_sha1`, `pc_boxes`, `writes_enabled`, which the server may ignore. The
trade port touches only `state.py`; no trade UI is needed for the release. A "randomized
pair" badge, if ever built, keys off the run's ROM contract, never the client hello.

**What the randomizer needs from Gen 1-owned code** (sent to the Gen 1 session 2026-09-14):
`gen1_rom_scan.identify/scan/scan_base_stats/evolution_graph/profile_hash/fingerprint_rom`
with `fingerprint_rom` client-reproducible (it is the contract value);
`Gen1Adapter.rom_content_fingerprint(payload)` returning the same string for the same
cartridge (that equality *is* admission, `server.py::_decide_admission`, re-run on every
hello) and `ingest_rom_content` feeding the board the randomized encounter tables; the
client hello carrying `rom_content` + `rom_sha1`. Randomized cartridges differ in wild/
static/trainer species and levels, starters, TMs, field items, trainer names, catch rates
and misc tweaks — never in types, evolutions, movesets, base stats, move data, EXP curves
or in-game trades, so shipped species/type/evo tables stay valid and trade logic may
assume vanilla.

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
  hello is admitted (the `rom_contract.json` path). **Done 2026-09-14 by the Gen 1 session**
  (scenario `admit_randomized_new`, their commit `c451218`, receipts under
  `tests/fixtures/gen1/receipts/`): A booted the unpatched randomized Red output on the clean
  save → `admitted`, "cartridge matches the contract"; B booted clean Blue as the negative
  control → `rejected`, "this is not the cartridge built for player b (reported …, expected
  …)", no identity or party adopted. The randomized output loads the clean cartridge's
  battery save unchanged. Not yet exercised: the companion patch on top of a randomized ROM.
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
