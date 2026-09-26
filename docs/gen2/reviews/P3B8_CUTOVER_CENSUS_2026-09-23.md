# P3b.8 cutover census (2026-09-23)

Worker P3b.8a. Scope: packaging + census only (`docs/gen2/GEN2_BINDING_PLAN.md:344,429`). **No
files were deleted or edited outside `tools/make_release.py`,
`tests/unit/test_make_release_manifest.py`, and the new
`tests/unit/test_gen2_release_bundle_boot.py`.** This is a report of what PLAN §4
(`docs/gen2/PLAN.md:126-142`) lists as REPLACE/REMOVE, whether each path is still referenced
today, and whether it looks safe to act on once the owner clears the two blockers below.

## P3b.8b outcome (2026-09-23): REMOVE executed

Owner ruling O-25 (`ae769e1e`, docs/gen2/REVIEW_RECORD.md) refused Archipelago Crystal. That
cleared blocker 1. Blocker 2 was already closed by `49a5c69d` and now also covers a run
whose rom_type routes nowhere. Worker P3b.8b executed the REMOVE half in three commits:

- `aa9c960b`: **refuse loudly.**
  - `lua/slink.lua` refuses every Game Boy cartridge the Gen 1 and Gen 2 routes do not
    recognise. `AP_CRYSTAL` gets "Archipelago Crystal is not supported (O-25)".
  - The server refuses a `crystal_ap` / "Crystal (AP)" hello, citing O-25
    (`_REFUSED_ROM_TYPES`, `unrouted_rom_type_reason`).
  - A run persisted under `gen2_crystal` is refused with `UnsafeGameMigration` whatever its
    rom_type resolves to (`_RETIRED_GAME_IDS`). This includes none at all, and the
    refusal does not need the adapter to be registered.
  - The Manager's "Crystal (Archipelago)" game row is dropped.
- `d8028dbf`: removes the legacy Lua runtime, its tests and its tooling (27 files).
- `c6201179`: removes `server/adapters/gen2_crystal.py` and its registry line.

Current verdict for every row in the tables below. The older rows keep their original
text as the evidence trail.

| Path | Verdict |
|---|---|
| `tests/fixtures/gen2/crystal_town.SaveRAM`, `data/games/gen2_crystal/*` (REPLACE) | DONE (unchanged from the table below). Some pack files were read only by the removed adapter, see "Kept" |
| `tests/unit/test_gen2_adapter.py` (REPLACE) | **DONE** `d8028dbf`: now only `TestGen2GSCAdapter` + `TestGen2GSCPackRefusal`. The legacy tests are gone |
| `lua/slink_gen2.lua` | **DONE** `d8028dbf` (also dropped from `tools/make_release.py` `_LUA_ROOT`/`_LAUNCHER_SCRIPTS`) |
| the 15 legacy `lua/tests/*gen2*` probe/test scripts | **DONE** `d8028dbf` |
| `lua/clients/gen2_crystal_client.lua` | **DONE** `d8028dbf` (the launcher row went in `aa9c960b`) |
| `lua/memory_gb.lua` | **DONE** `d8028dbf`. **Not shared**: every Gen 1 / Gen 3 hit is a comment citing line numbers. The one remaining runtime `require` is in the legacy e2e chain (follow-up below) |
| `lua/games/gen2_crystal.lua`, `lua/games/gen2_crystal_trainers.lua` | **DONE** `d8028dbf` (also left `lua/game_detect.lua`'s registry and the release manifest) |
| `lua/gen2_crystal_locations.lua`, `lua/gen2_crystal_areas.lua` | **DONE** `d8028dbf` (manifest rows dropped in the same commit) |
| `server/adapters/gen2_crystal.py` | **DONE** `c6201179`. Before it went, the O-24 worker (`25bfca25`) moved `tests/unit/test_state_faint_repair.py` to `Gen2GSCAdapter`. `test_gen2_moves.py` and `test_gen3_adapter.py` were repointed in `d8028dbf` |
| `tests/unit/test_gen2_{ap_addresses,ball_items}.py` | **DONE** `d8028dbf` |
| `tests/live/test_gen2_gates.py` | **DONE** `d8028dbf` |
| `tools/verify_profile_addresses.py` (+ `tests/unit/test_profile_addresses.py`) | **DONE** `d8028dbf`, the whole tool. The census finding above is stale: `tools/verify_gen1_release.py` no longer has a `profile-addresses` lane (grep: no hit outside historical receipt logs), so nothing live used it |
| `tools/gen2_playthrough.py` | **KEPT, follow-up.** `tests/e2e/test_duo_gen2.py` imports it at module level, and `tests/unit/test_e2e_duo_scenario_selection.py` imports that module. Deleting it would break test collection, and both files are under Codex's H5 lease |
| `tests/e2e/test_duo_gen2.py` | **KEPT, follow-up** (`tests/e2e/*` is under Codex's H5 lease) |

### Follow-up: retire the legacy e2e_duo `gen2` row (not done: other workers' leases)

`tools/e2e_duo.py`'s `GAMES["gen2"]` row (`"main": "lua/tests/duo/duo_gb_main.lua"`,
`"game": "gen2_crystal"`, `"play": "gen2_playthrough"`) and its `EvidenceContract` entry
`"gen2_crystal"` drive the removed legacy client. It is dead at runtime: `duo_gb_main.lua`
requires `memory_gb` and dofiles `lua/tests/gatelib.lua`, whose `GAMES.gen2_crystal` names
`games.gen2_crystal` and `gen2_crystal_client.lua`. All of those are gone. It fails only if
someone runs `--game gen2` under `SLINK_E2E=1`, and nothing in the unit suite runs it. Remove
these together, once H5/H1c release `tools/e2e_duo.py`, `tests/e2e/*` and `lua/tests/duo/*`:

- the e2e_duo `gen2` row and `EvidenceContract["gen2_crystal"]`
- the legacy `gen2` game cases in `tests/unit/test_e2e_duo_scenario_selection.py` (`scenarios_for("gen2")`, the `test_duo_gen2` wrapper check)
- `tests/e2e/test_duo_gen2.py`
- `lua/tests/duo/duo_gb_main.lua` and `lua/tests/duo/scenario_gb_{faint,boxsync,memorialize}.lua`
- `lua/tests/gatelib.lua`
- `tools/gen2_playthrough.py`

### Kept, and why

- `lua/tests/gatelib.lua`: its only runtime consumer is `lua/tests/duo/duo_gb_main.lua`
  (H1c lease), so it goes with the follow-up above.
- `data/games/gen2_crystal/{gender_ratios,species_types,item_names}.json` were read only by
  the removed adapter. `data/games/gen2_*` is outside this card, so they are left for the
  pack owner. `server/data/items/__init__.py:13` and `data/games/gen2_crystal/README.md`
  still describe the old loader in prose.
- Stale prose that names removed files, left for a doc sweep:
  - `lua/games/README.md`, `lua/tests/README.md`, `tests/TESTING.md`
  - `.github/copilot-instructions.md`, `data/games/gen1_rby/README.md:9`
  - the example in the `tools/run_gb_gate.py:6` docstring
  - line-number comments citing `memory_gb.lua` in `lua/gen1/panel.lua` and the Gen 1 panel tests

## Blockers to any REMOVE (read this first) — HISTORICAL, both cleared (see above)

1. **`crystal_ap` still runs on the legacy client + adapter, live.** `lua/slink.lua:84-104`'s
   Gen 2 route only recognises the three admitted titles (`Entry.detect_title` matches
   `PM_CRYSTAL` / `POKEMON_GLD` / `POKEMON_SLV`); the Archipelago fork's header
   (`AP_CRYSTAL`) is not one of them, so it falls through to `game_detect.detect()` and
   `lua/slink.lua:116`'s `_CLIENT_MAP.gen2_crystal = "clients/gen2_crystal_client.lua"` —
   the OLD client is still what a `crystal_ap` player's launcher loads today. Server-side,
   `server/adapters/__init__.py:77` still maps `"crystal_ap"` to the `"gen2_crystal"`
   foundation, and `server/adapters/__init__.py:225-229` registers
   `Gen2CrystalAdapter` for it. None of the REMOVE-listed Lua/Python files can go while this
   routing stands (O-8, confirmed live in this checkout, not just in the plan text).
2. **A pre-cutover persisted run can still resurrect `Gen2CrystalAdapter` after restart.**
   `server/state.py`'s restore path re-derives the adapter from the persisted `game_id`
   (`game_id_for_rom_type` / `persisted_migration_refusal`, referenced around
   `server/state.py:912-920`) and `server/server.py:1406-1414` does the same on a hello that
   changes `rom_type` mid-run. A save from before U5 still says `game_id: "gen2_crystal"`
   and will keep loading `Gen2CrystalAdapter` until that migration path is closed. **Another
   worker owns this migration now** (git status shows `server/state.py` and
   `tests/unit/test_gen2_persisted_cutover.py` modified in this worktree as of this
   session) — P3b.8's REMOVE half must wait for it to land, exactly as the coordinator's
   card says.

Both are load-bearing today, not just documented risk: grep evidence for each REMOVE-listed
path below traces back to one or both of these two live routes.

## REPLACE (same path, regenerated content) — PLAN §4 / `docs/gen2/PLAN.md:126`

| Path | Status | Evidence |
|---|---|---|
| `tests/fixtures/gen2/crystal_town.SaveRAM` | **DONE.** Played + qualified fixture committed at `398aef48` ("first played + qualified Gen 2 fixture (crystal_town)"). 32790 bytes on disk, dated this rewrite. | `git log --oneline -- tests/fixtures/gen2/crystal_town.SaveRAM` |
| `data/games/gen2_crystal/*` (regenerated packs, P2) | **DONE.** These are the exact files `lua/gen2/entry.lua`'s `Entry.PACK_FILES.gen2_crystal` loads in production (task 1 of this card re-derived the closure and it matches byte-for-byte); `tests/unit/test_make_release_manifest.py` and the new bundle-boot test both exercise them from the built release ZIP. | `lua/gen2/entry.lua:19-36`; this card's manifest/bundle-boot work |
| `tests/unit/test_gen2_adapter.py` (new adapter tests, P3b.6) | **NOT DONE.** The file still imports and tests only the legacy adapter: `from server.adapters.gen2_crystal import Gen2CrystalAdapter` (line 9), 98 `test_*` functions, all against `Gen2CrystalAdapter`. `python -m pytest tests/unit/test_gen2_adapter.py -q` is currently **230 passed** (green, not red as an older resume note suggested — re-verified live in this session). P3b.6 has not yet swapped this file's content to the new Gen2GSCAdapter tests; nothing to REMOVE here until it does. | `tests/unit/test_gen2_adapter.py:1-25`; pytest run this session |

## REMOVE (path goes away) — PLAN §4 / `docs/gen2/PLAN.md:127-142`

| Path | Still referenced? | Referenced by (file:line) | Depends on it | Safe to delete after the duo matrix + persisted migration? |
|---|---|---|---|---|
| `lua/slink_gen2.lua` | **No** live dofile. `lua/slink.lua` no longer routes through it (U5 replaced the route at `lua/slink.lua:84-104` with a direct `dofile(_dir .. "gen2/entry.lua")` / `dofile(_dir .. "gen2/run.lua")`). The only remaining hit is a comment in `lua/clients/gen2_crystal_client.lua:1483` (`event.onframeend(on_frame_safe, "slink_gen2")` — an event tag string, not a load of this file) plus doc mentions. | none (dead launcher) | — | **Yes**, independent of both blockers — nothing loads it anymore. Lowest-risk single-file removal in this list. |
| The 15 legacy Lua probe/test scripts (`lua/tests/gen2_playthrough.lua`, `probe_gen2_boot.lua`, `probe_gen2_safestate.lua`, `probe_gen2_save.lua`, `test_gen2_enemy_moves.lua`, `test_gen2_force_faint.lua`, `test_gen2_memory.lua`, `test_gen2_memory_gate.lua`, `test_gen2_moves.lua`, `test_gen2_profile_audit.lua`, `test_gen2_server.lua`, `test_gen2_sfx.lua`, `test_gen2_stat_stages.lua`, `test_gen2_trainer_info.lua`, `test_gen2_writes_gate.lua`) | **Yes**, from outside the set. `tests/live/test_gen2_gates.py` and `tests/e2e/test_duo_gen2.py` shell out to some of these by path (e.g. `test_gen2_memory_gate.lua`, `test_gen2_writes_gate.lua`); `tools/run_gb_gate.py`'s own docstring names `lua/tests/test_gen2_memory_gate.lua` as its usage example (line 6). Cross-references within the set itself (`test_gen2_memory.lua` / `test_gen2_server.lua` both `require("gen2_crystal_areas")` / `require("gen2_crystal_locations")`) are internal, not external blockers. | `tests/live/test_gen2_gates.py`, `tests/e2e/test_duo_gen2.py`, `tools/run_gb_gate.py` (doc example only) | **Only together with** `tests/live/test_gen2_gates.py` and `tests/e2e/test_duo_gen2.py` (both themselves REMOVE-listed) — removing the scripts alone would leave those two test files pointing at nothing. Both currently pass/skip cleanly (10 passed, 5 skipped when run together this session), so there is no red to inherit. |
| `lua/clients/gen2_crystal_client.lua` | **Yes, live.** `lua/slink.lua:116`'s `_CLIENT_MAP.gen2_crystal` still dofiles it for any Gen 2 header `Entry.detect_title` doesn't recognise (i.e. `crystal_ap`). | `lua/slink.lua:116,128` | crystal_ap (blocker 1) | **No** — blocked on blocker 1. |
| `lua/memory_gb.lua` | **Yes, live** — but ONLY from the legacy client. `lua/clients/gen2_crystal_client.lua:97` (`local M = require("memory_gb")`) is the sole real `require`; every other hit in the tree (`lua/gen1/*`, `lua/memory_gba.lua`, `lua/memory_nds.lua`, `lua/mailbox.lua`, `lua/clients/gen3_frlge_client.lua`, `lua/games/gen2_crystal.lua`) is a **comment** citing the shared byte-pattern lineage, not a `dofile`/`require`. Confirmed by grepping each hit individually, not just a substring match. | `lua/clients/gen2_crystal_client.lua:97` | crystal_ap (blocker 1) | **No** — blocked on blocker 1, but it is the ONLY runtime consumer, so it goes the moment the legacy client does. |
| `lua/games/gen2_crystal.lua` | **Yes, live.** Required by `lua/clients/gen2_crystal_client.lua`; it is also `PROFILE_GEN2` in `tools/verify_profile_addresses.py:35` (see the separate finding below). | `lua/clients/gen2_crystal_client.lua`; `tools/verify_profile_addresses.py:35` | crystal_ap (blocker 1) | **No** — blocked on blocker 1 **and** on deciding `tools/verify_profile_addresses.py`'s fate (below). |
| `lua/games/gen2_crystal_trainers.lua` | **Yes, live.** `lua/clients/gen2_crystal_client.lua:101` does `require("games.gen2_crystal_trainers")` unconditionally at module load (this is the exact file `tools/make_release.py`'s manifest comment at line 139-144 warns about — its absence used to break the release build silently). | `lua/clients/gen2_crystal_client.lua:101` | crystal_ap (blocker 1) | **No** — blocked on blocker 1. |
| `lua/gen2_crystal_locations.lua`, `lua/gen2_crystal_areas.lua` | **Yes, live.** `lua/games/gen2_crystal.lua:597` does `pcall(require, "gen2_crystal_areas")`; also required by two of the 15 REMOVE-listed test scripts (`test_gen2_memory.lua`, `test_gen2_server.lua`) — self-contained within this REMOVE set. Also still shipped today in `tools/make_release.py`'s `_LUA_ROOT` (lines 94-96). | `lua/games/gen2_crystal.lua:597`; `lua/tests/test_gen2_memory.lua:26-27`; `lua/tests/test_gen2_server.lua:40-41` | crystal_ap (blocker 1) | **No** — blocked on blocker 1; also requires a `tools/make_release.py` manifest edit (drop these two rows from `_LUA_ROOT`) in the same change that removes them, or the release build's own pre-flight check goes red. |
| `tools/gen2_playthrough.py` | **Yes, live**, but only from the OLD e2e family. `tools/e2e_duo.py:1070` has `"play": "gen2_playthrough"` in its game-family dispatch table (the legacy `gen2` family, distinct from the H3 `gen2_new` family this rewrite ships); `tests/e2e/test_duo_gen2.py` and `tests/live/test_gen2_gates.py` also reference it. | `tools/e2e_duo.py:1070` (**owned by another worker — out of scope for this card**), `tests/e2e/test_duo_gen2.py`, `tests/live/test_gen2_gates.py` | crystal_ap indirectly (it is the OLD family's driver; the old family is what the legacy client speaks) | **No** — needs `tools/e2e_duo.py`'s legacy `"gen2"` family row retired first, which is out of this card's file scope; flag for whoever owns the REMOVE half of P3b.8. |
| `server/adapters/gen2_crystal.py` | **Yes, live and heavily depended on.** Registered at `server/adapters/__init__.py:225-227` for the `"gen2_crystal"` foundation (`"crystal_ap"` maps to it at line 77). Imported directly by `tests/unit/test_gen2_adapter.py` (98 tests, still legacy-only — see REPLACE table above), `tests/unit/test_gen2_moves.py`, `tests/unit/test_gen2_persisted_cutover.py` (**currently being edited by the persisted-migration worker**), and `tests/unit/test_gen3_adapter.py` (cross-adapter pairing rules). | `server/adapters/__init__.py:77,225-229`; `tests/unit/test_gen2_adapter.py`; `tests/unit/test_gen2_moves.py`; `tests/unit/test_gen2_persisted_cutover.py`; `tests/unit/test_gen3_adapter.py` | crystal_ap (blocker 1) **and** the persisted-run migration (blocker 2) | **No** — blocked on both. This is the highest-fan-in item in the whole REMOVE list; do it last, and only after `tests/unit/test_gen2_adapter.py` has been replaced (P3b.6) so nothing still imports `Gen2CrystalAdapter` by name. |
| `tests/unit/test_gen2_ap_addresses.py`, `tests/unit/test_gen2_ball_items.py` | Self-contained; they test Lua **profile facts** (`lua/games/gen2_crystal.lua`'s address table, the AP apworld's own `ram_addresses`), not the Python adapter. Currently **green**: `10 passed, 5 skipped` together with the live/e2e files below, this session. | own file only | crystal_ap's profile data (same blocker 1 lineage, since the profile they check belongs to the legacy client) | **No** — same blocker as the client itself; not currently red, no urgency beyond the cutover. |
| `tests/live/test_gen2_gates.py`, `tests/e2e/test_duo_gen2.py` | **Yes**, they drive the 15 legacy Lua scripts and `tools/gen2_playthrough.py` above; both skip cleanly without `SLINK_LIVE`/`SLINK_E2E` and hardware, no red. | see the two rows above | crystal_ap (blocker 1) | **No** — remove together with the 15 legacy scripts and `tools/gen2_playthrough.py`, once blocker 1 clears. |
| The Gen 2 rows of `tools/verify_profile_addresses.py` | **Finding, not in the plan text:** the ENTIRE tool is Gen-2-only now, not just "rows". `PROFILE_TO_PRET` has exactly one non-Crystal-address entry point (`PROFILE_GEN2`); the Gen 1 mapping was already migrated away (comment at line 56-57: superseded by `tests/unit/test_gen1_profile.py` against the generated `data/games/gen1_rby/*.json`). There are no Gen 3/4/5 rows to strip around. **But the tool is still wired into `tools/verify_gen1_release.py:97`** as the `"profile-addresses"` release-verification lane — removing the tool (or gutting it to nothing) would need that lane definition updated too, in a file this card does not own. `tests/unit/test_profile_addresses.py` (3 tests) currently passes green against it. | `tools/verify_profile_addresses.py:35,174` (self); `tools/verify_gen1_release.py:97` (lane wiring); `tools/verify_gen1_rom_layout.py:4` (doc comment only, not a real dependency); `tests/unit/test_profile_addresses.py` | crystal_ap (the content) **and** `tools/verify_gen1_release.py`'s lane list (the wiring) | **Not a simple "drop the Gen 2 rows"** — PLAN §4's own hedge ("or goes with a separate card if nothing else uses it") applies: something DOES still use it (the Gen 1 release lane), so this needs its own decision/card, not a P3b.8 sub-item. Recommend the coordinator open a separate ticket rather than fold it into this REMOVE batch. |

## Bottom line

- Nothing in this census was deleted; this is read-only evidence for whoever executes the
  REMOVE half of P3b.8.
- Every REMOVE-listed path still traces to one of the two live blockers above (crystal_ap's
  legacy routing, or the persisted-run migration), except `lua/slink_gen2.lua`, which is
  already dead and could be removed independently today.
- One item is outright NOT DONE yet on the REPLACE side (`tests/unit/test_gen2_adapter.py`
  still needs its P3b.6 content swap) — the REMOVE of `server/adapters/gen2_crystal.py`
  cannot happen before that lands, on top of the two blockers.
- One item (`tools/verify_profile_addresses.py`) does not fit the REMOVE list as PLAN §4
  wrote it and should be its own card.
