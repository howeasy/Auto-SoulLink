# Proposals for root (`codex:Gen1`), 2026-09-10

Each proposal is self-contained and reversible. Patches apply from the sweep worktree root
with `git apply docs/gen1_reference/proposals/<name>.patch` (all were checked with
`git apply --check` today). New files were added in place because they are additive and
outside the reserved set; root accepts them by keeping them, or drops them by deleting them.
The decisions these serve are recorded in `../CODEX_HANDOFF_2026-09-10.md` section 0.

| # | Proposal | Form | Verified today | Apply after |
| --- | --- | --- | --- | --- |
| P1 | Restore the Gen 3 native trade staging gate (`gen3_frlge_client.lua:2221-2241`) | patch, one inserted line | applies cleanly; patched file compiles; live command given (root checkout has the ROM) | nothing; first easy win |
| P3 | Gen 1 translators into the shared rule engine (`server/gen1_semantic_events.py`) | new module + tests | 13 tests green against the real `SoulLinkState` with the Gen 1 adapter; ruff clean | nothing to apply; wire per `P3-semantic-events.md` during handoff item 2 |
| P4 | Free-running observation loop (`lua/gen1_observation_loop.lua`) | new module + lupa tests | 11 tests green; Lua gate 301 files OK | handoff item 3, with the `free_service` mode and the two boundary-predicate lines in `P4-observation-loop.md` |
| P5 | `force_explode` executor (`P5-explode-executor.md`), `replace_rival_team` executor (`P5-rival-team-executor.md`), whiteout detection (`P5-whiteout-detection.md`) | design notes with sketches, source-cited | designs only; key finding: a whiteout can never be seen from the post-battle inventory because HealParty runs at blackout, so detection comes from the faint signal party bytes | handoff item 4 |
| P8 | Faint call site decides through the shared engine (`gen1_faint_runtime.py`) | patch | scratch-copy run: 34 faint tests + 743 death/memorial/ball tests green; ruff clean | with item 2; independent of P7 |
| P9 | Acquisition call site decides through the shared engine (`gen1_acquisition_runtime.py`; the adapter hunk moved to P13) | patch | scratch-copy run: 155 passed, only the five pre-existing failures remain | with item 2 |
| P10 | Free-run server half and wiring: new `server/gen1_observation_runtime.py` consumes the P4 `observation` event (sequence, ROM, context checks; inventory, then engine signals, then acquisitions in one commit); patch adds the `free_service` flag and routing (`gen1_runtime.py`, `gen1_run_config.py`, `gen1_launcher.py`), the `free_service` client mode built on the P4 loop (`gen1_client_entry.lua`) and the boundary-predicate relaxation (`gen1_initial_observation.lua:52`); companion patch `P10-free-run-server-verifiers.patch` (provenance and acquisition verifiers keyed on the committing event; rebased onto P9, so apply it after P9) | new module + tests + two patches | 16 new tests green; in the shared scratch copy with P8, P9, P10 and P13 applied the acquisition, frame, launcher and translator suites show only the five pre-existing failures; Lua gate 302 OK; all eight patches apply in sequence in a scratch git repo | handoff item 3; the credit-path deletion is a separate step (file set in the note) |
| P10-live | Free-run live gate (`tests/live/test_gen1_free_service.py`, `lua/tests/test_gen1_free_service_gate.lua`) and two P10 wiring fixes in `lua/gen1_client_entry.lua` (`P10-free-run-live.patch`: the held-faint executor no longer asserts a hold on unheld control turns; the core is released only after every held-phase command and event is acknowledged, so the initial-save image command is not refused) | new tests + patch | LIVE PASS 2026-09-11, Yellow/Yellow bedroom through two real downloaded `free_service` launchers, cold New Game, 1200 free frames per player: 53.2 / 53.0 FPS throttled at cartridge rate (89 % of 59.7; the whole shortfall is the 30-frame heartbeat carrying `cart_hex`, 95 ms per heartbeat iteration against 16.2 ms ordinary), 128.8 / 131.6 FPS unthrottled against 31.05 / 31.25 for the credit loop under the same harness condition (4.2x); 40 / 39 observation batches, 0 sequence gaps, 0 deferrals, 72 ms server cost per batch, backlog at most 1; receipts identical to the credit-path bundle `.cache/gen1-bootstrap-launcher-ehtld3qv`; evidence `.cache/free-service-yy-wwp2qsfl/` and `.cache/junit/free_service_live.xml` (1 test, 0 failures, 26.4 s) | after P10 and P10-verifiers |
| P11 | `force_explode` executor as a second instruction-authority binding (`rby-battle-force-explode`): moveset and PP rewritten to Explosion at the loop head, selected move at ExecutePlayerMove; new `tests/unit/test_battle_force_explode.py` (81 tests) and gate scenario `explode_first` | patch + new tests | 283 unit tests green across the four battle-force suites; Lua gate OK; live gate PASSED on Red, Blue and Yellow (explode_armed at both sites, engine executed Explosion, SRAM unchanged; P11 note section 7) | handoff item 4/5; P7 after this |
| P12 | `replace_rival_team` executor (`lua/gen1_held_rival_team.lua`, `server/gen1_held_rival_team.py`, battle-init checkpoint profile `data/games/gen1_rby/rival_team_checkpoint.json` with its Lua twin and generator) and whiteout detection from the faint signal party bytes (`server/gen1_whiteout.py`, called from the faint settlement); patch adds the executor dispatch in `gen1_held_faint.lua` and the whiteout call in `gen1_faint_runtime.py` | new modules + tests + patch | 77 tests green in the scratch copy (whiteout, rival executor, faint runtime); `gen1_faint_runtime.py` hunk written against P8, so apply after P8 | handoff item 4; trainer-battle detection input from the observation loop still to wire |
| P13 | Remaining rule call sites through the shared engine: starter, no-catch, evolution, NPC exchange, memorial completion, via the new `server/gen1_engine_bridge.py`; adapter fixed-species policy (Eevee, and starters flagged for an owner decision) | patch + new module | scratch-copy run: 185 passed across the eight suites; P1+P7+P8+P9+P13 apply in sequence in a scratch git repo | with item 2, after P8 and P9 |
| P14 | Starters under the clauses in every generation, Yellow/Yellow exempt (owner decision 2026-09-11): pair-aware `is_fixed_species_gift` in the Gen 1 adapter with the pair declared at run creation and restore; `starter_grant` surfaces the engine rejection; the settlement records and verifies it (schema v2); new `tests/unit/test_gen1_starter_clauses.py` | patch + new tests | scratch-copy run: 62 passed across the starter settlement and clause suites; sequence re-verified with P14 last; resolves the P13 flag; Gen 1 unit run over the scratch copy with every patch applied (`python -m pytest tests/unit -k "gen1 or test_state or gen3_adapter or semantic_events or engine_bridge"`): 4,801 passed, 7 skipped, 5 failed in 850 s, the five failures being exactly the pre-existing acquisition-policy tests of the 2026-09-10 broad run (`test_gen1_acquisition_runtime` x3, `test_gen1_frame_acquisitions` x2: `exempt_grant` vs `boxed_deferred`, identity missing from pairs, physical commands before ordinary frame authority); evidence `.cache/junit/p14_gen1_unit.{xml,log}` | after P13 and P10 |
| P7 | Drop the Explode refusal (`gen1_faint_runtime.py:126-127`) | patch, two deleted lines | applies cleanly; no test asserts the refusal | after P5's Explode executor, or with item 2 |

Apply order that was verified by applying every patch in sequence in a scratch git repository seeded with the worktree originals (re-run 2026-09-11 after the live gate): P1, P7, P8, P12, P9, P10, P10-verifiers, P10-free-run-live, P11, P13, P14. P12 depends on P8, P10-verifiers on P9, P10-free-run-live on P10 (its hunks sit inside the `free_service` code P10 adds, so it does not apply to the bare worktree) and P14 on P13 and P10 (adapter and run-config hunks); the rest also apply standalone.

Full unit and integration run over the scratch copy with every patch and every new file in place (2026-09-11, `.cache/junit/broad_all_patches.{xml,log}` copied into the worktree): 7,319 passed, 14 skipped, stopped at the 80-failure cap with 38 failures and 42 errors. Every failure and error is one of three known kinds: the five pre-existing acquisition-policy tests; the four browser-patcher tests that need the `playwright` module; and generator, UPR, prepared-cartridge, companion-build and canonical-source reproduction tests that read `.cache` inputs the scratch copy does not have (`test_gen1_upr_semantics`, `test_gen1_acquisition_sources`, `test_gen1_prepared_*`, `test_gen1_companion_build`, the `*_receipt` generator checks, `test_gen1_sessions`, `test_gen1_identity_guard`, `test_gen1_party_codec`, `test_gen1_native_run_configuration`), all of which passed in the worktree's own broad run of 2026-09-10 (`.cache/junit/broad_2026-09-10.xml`, 7,317 passed / 9 failed). No failure is attributable to a patch.

P8 and P9 were verified in a scratch copy of the worktree (`tar` copy minus `.cache`, with junctions to `.cache/pret` and `.cache/battle-fixtures`); only tests that verify generated artifacts against further `.cache` inputs could not run there, and those pass in the worktree.

Not proposed, and why:

- **P2, late-grant replay** (`lua/gen1_frame_client.lua:309-310`): the correct fix needs the
  same pending challenge re-sent inside its 1,000 ms lifetime, which touches the durable
  runtime's request plumbing; the whole path is deleted by handoff item 3. Only worth doing if
  a cold-route run is attempted before item 3 lands (`COLD_ROUTE_FORENSICS_2026-09-10.md`).
- **P6, memorial box from the adapter** (`server/gen1_memorial_policy.py:20`): `GRAVE_BOX`
  is read at seven sites in that module and mirrored by `reserved_boxes=(11,)` in
  `gen1_storage.py:189`. The value equals `Gen1Adapter.memorial_box_index()` today, so the
  change is a refactor with no behaviour: thread `stage.rules.adapter.memorial_box_index()`
  through those sites when item 2 gives the module a `stage`.
- **`playwright`**: environment, not code. `npm install playwright` under `tests/browser/`
  before the patch-browser rows; four integration tests fail on the missing module alone.

Verification commands used:

```bash
git apply --check docs/gen1_reference/proposals/P1-gen3-trade-gate.patch
git apply --check docs/gen1_reference/proposals/P7-drop-explode-refusal.patch
python -m pytest tests/unit/test_gen1_semantic_events.py tests/unit/test_gen1_observation_loop.py -q
python tools/lua_syntax_check.py
ruff check . --select E9,F6,F7,F81,F82
```

## Reference pages added 2026-09-11 (not proposals; new files only)

- `docs/FRAMEWORK.md`: the checkable form of the framework goal. 91 shared-module rows in 19 subsystem
  groups, each with its contract note, its Gen 1 binding (file:line) and its Gen 3 binding today or
  `new` with a pointer to the Gen 3 code that does the job inline; then what both generations already
  share, what Gen 1 built that Gen 3 must bind, the unapplied proposal series in apply order, and five
  corrections to `docs/shared-subsystem-map.md`. Every file:line was read at HEAD `79d5172`.
- `docs/gen1_reference/GEN3_BINDING_PLAN.md`: the ordered plan to port Gen 3 onto the shared runtime
  after the Gen 1 RC (steps 0, a, f1, b, d, c, e, g, f2, each with what is bound, wrapped, kept in the
  adapter, its evidence gate, effort and risk), what must not move into the shared layer, nine owner
  decisions and a 28-row size table of the Gen 3 client by concern. Not Gen 1 release work; the
  manifest is untouched by it.
- `docs/gen1_reference/RC_CHECKLIST.md`: the 388-row release manifest rendered as one status page
  (187 registered, 201 missing, per-stage closure plan), regenerated by
  `docs/gen1_reference/render_rc_checklist.py` and checked row by row against
  `python tools/verify_gen1_release.py --list`.
