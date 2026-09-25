# Handoff: make the damage calc work for every supported game

You are taking over one piece of work on SLink: make the bundled damage calculator give correct
numbers for every supported game, not only Radical Red. Read this whole file before you start.
Everything here was checked at source on master `96ae536d` (2026-09-25) unless marked *inferred*.

## What SLink is (30 seconds)

SLink automates a Pokémon Soul Link Nuzlocke across two BizHawk emulators. Lua clients read game
RAM and send JSON over TCP to a Python server (`server/server.py`), which enforces the rules and
serves a web UI (aiohttp + Jinja2 + HTMX). Game-specific behaviour lives in adapters
(`server/adapters/`). A fork of the Smogon damage calculator lives in `calc/`; the run server
serves it at `/calc/normal.html`, and `calc/src/js/slink_bridge.js` pulls live party and enemy data
into it from `GET /api/calc/mons`.

Read `CLAUDE.md` (repo root, gitignored, local only) first. Its adapter rules are hard rules.

## The goal

| Game | Adapter | Calc today | Target |
|---|---|---|---|
| Radical Red (RR) | `gen3_frlge.py` (RR mode) | Works | Close the four gaps (task 9) |
| FireRed/LeafGreen/Emerald vanilla | `gen3_frlge.py` | Loads, wrong numbers | Correct under Gen 3 rules |
| Crystal | `gen2_crystal.py` | Loads, wrong numbers | Correct under Gen 2 rules |
| Red/Blue/Yellow | `gen1_rby.py` | Loads, wrong numbers | Correct under Gen 1 rules |
| pureRGB (Red/Blue hack) | `gen1_purergb.py` | Loads, wrong numbers | Correct, including its custom data (owner decides scope; see task 7) |

Gen 4/5 adapters exist but have never worked and are hidden from the UI. Ignore them.

## Why it is wrong today (verified)

1. **Generation is locked to 9.** `calc/src/normal.template.html:50` has a single gen radio,
   `value="9" id="gen9"`. The upstream gen selector code is still there
   (`calc/src/js/shared_controls.js:1246-1292` change handler, `:1600-1602` reads `?gen=`), but
   `?gen=1` looks for `#gen1`, which doesn't exist. `server/static/calc-preview.js:116` hard-codes
   `Generations.get(9)`. The engine (`calc/calc/src/mechanics`, `calc/calc/src/data`) still has
   Gen 1-3 rules and data (a node check confirmed the Generations data loads).
2. **RR data lives in the Gen 9 tables.** `RR_PATCH` is merged into Gen 9 in
   `calc/calc/src/data/species.ts:~10650`, `moves.ts:~5109`, `abilities.ts:~342,363`, and
   `items.ts:~516`. Vanilla FRLG on Gen 9 therefore gets RR typings and stats (Arbok Poison/Dark,
   Clefairy Fairy) and the per-move physical/special split.
3. **No generation in the payload.** `_build_mon_entry` (`server/server.py:~158-204`) and the
   enemy path (`server.py:~2560-2636`) send no game or generation field. The bridge never reads
   one.
4. **Nature invented from DVs.** `_nature_from_key` (`server.py:127`) takes the key's first hex
   field mod 25. That is the personality value on Gen 3, but DVs on Gen 1 (key `DVs:OT:species`,
   `lua/gen1/reads.lua:218`) and Gen 2 (`DV1DV2:OTID:species`, `lua/memory_gb.lua:324`). The paste
   always carries a nature and an ability line (`server.py:~183-184`).
5. **Names only mapped for RR.** `calc_name` (`server/adapters/base.py:479`) is a passthrough;
   only `gen3_frlge.py:549` overrides it (via `data/games/gen3_frlge/calc_names.json`). Moves the
   calc doesn't know become "(No Move)" silently (`slink_bridge.js:~846-852`). Missing move counts
   against the calc's own tables for the right generation: Gen 1 13/165 (ThunderShock,
   Sand-Attack, Hi Jump Kick, SolarBeam…), Crystal 18 (DynamicPunch, ExtremeSpeed, Faint
   Attack…), vanilla Gen 3 20 (Thunderpunch, Vicegrip, Smellingsalt, Featherdance…), pureRGB 19.
   Items too: BrightPowder, TwistedSpoon, BlackBelt vs the calc's spaced names (`items.ts:11,13,66`).
6. **No real stats.** No IVs/EVs, DVs, stat experience or computed stats are sent. The Gen 1 Lua
   reads DVs and stat exp (`lua/gen1/reads.lua:~100-114`) and the Gen 1 codec's
   `decode_party_mon` (`server/adapters/gen1_codec.py`) returns them, but `_build_mon_entry`
   drops them. Gen 3 IVs/EVs are only inside the encrypted `blob_hex`.
7. **Gen 1 stat stages land in the wrong row.** Gen 1 sends `[atk,def,spd,spc,6,acc,eva]`
   (`lua/gen1/client.lua:~132`); the bridge maps index 3 to `.sa` (`slink_bridge.js:~1750`), but in
   Gen 1 mode Special is `.sl` (`normal.template.html:~336`).
8. **RR-only bridge features.**
   - Matched trainer sets are injected into `window.SETDEX_SV` (`slink_bridge.js:~784`), but
     outside Gen 9 the calc reads `SETDEX[gen]` (`shared_controls.js:~1270`).
   - `normal.js`, `hardcore.js` and `slink_priority.js` are all RR trainer sets. "Normal" and
     "Hardcore" are RR difficulty modes.
   - The Prep tab (`slink_bridge.js:~1115`) and the HC badge show RR trainers for every game.
   - `_enrichEnemyMons` (`slink_bridge.js:~323-420`) overwrites enemy moves, nature, ability and
     item with RR sets whenever the trainer label, or its species+level fallback, matches.
9. **Gen 1 enemy is thin.** The Gen 1 client sends only species, level, hp and stages for the
   active foe (`lua/gen1/client.lua:~249-255`). The server defaults `maxHP` to 1, so HP% clamps to
   100 (`server.py:~2611,2623`).
10. **Wrong adapter in a two-adapter run.** `handle_calc_mons` uses the run-wide `self.adapter`
    (`server.py:~2563/2590/2619`), not `self.adapter_for(pid)`.
11. **Ungated.** The Calc link shows for every game: `server/templates/dashboard.html:31`,
    `_rail.html:67`, `server.py:~1082`, `manager.py:~1857`. The dashboard battle preview is
    RR-only via `if not self.state.is_rr: return None` at `server.py:978`. That line also breaks
    the no-`is_rr`-in-shared-code rule.

A previous reviewer claimed the Crystal held item never reaches the calc. That is **wrong**: the
server maps the client's `held_item` to `held_item_id` (`server.py:1659`, `:1824`). Don't "fix" it.

The `battle_calc` Manager option is unrelated: it toggles the in-game calc in RR's companion
patch (`state.py:~1178`), not the web calc.

## Tasks

Do them in this order. Each ends with the unit suite green and the calc rebuilt where it changed.

1. **Gate the calc per game (S).** Add an adapter method, e.g. `supports_web_calc()` (base default
   False; `gen3_frlge` True for RR; later tasks flip the others to True as each becomes correct).
   Use it for the Calc tab/links and the dashboard preview. Replace the `is_rr` check at
   `server.py:978` with it.
2. **Send the generation (M).** Add a `calc_gen()` adapter method (base None; Gen 1 → 1, Crystal
   → 2, vanilla Gen 3 → 3, RR → 9). Put `gen` in the `/api/calc/mons` payload and in the
   calc-preview data. Restore the gen radios in `normal.template.html` (and `hardcore` if it has
   its own template). The bridge sets the calc's generation from the payload on load, and
   `calc-preview.js` uses it instead of `Generations.get(9)`.
3. **Name tables (S each).** Give `gen1_rby`, `gen2_crystal` and vanilla-Gen-3 `gen3_frlge` a
   `calc_name` override backed by small JSON tables in each `data/games/<gen>/`. Put the Gen 3 table
   beside RR's, keyed by variant. Copy the shape of `tests/unit/test_rr_calc_names.py`: parse the
   calc's tables for the matching generation and assert every name the adapter can emit resolves.
   Also make the bridge log a console warning when a move falls back to "(No Move)".
4. **Real stats for Gen 1/2 (M).** Nature and ability become adapter facts:
   - Gen 1/2 send no nature and no ability.
   - Gen 3 keeps the personality nature.
   - Move `_nature_from_key` behind an adapter method.

   For stats, send DVs and stat experience for Gen 1/2, decoded from what the client already
   sends (the Gen 1 codec has it; Crystal needs a decoder). The bridge fills the calc's DV/stat
   fields in Gen 1/2 mode. For Gen 3 vanilla, decode IVs/EVs from the blob if that stays small;
   otherwise send the in-game computed stats and have the bridge override. Pick whichever the
   calc supports cleanly and say which you chose.
5. **Generation-aware bridge (M).**
   - Map Gen 1 Special stages to `.sl`.
   - Inject matched sets into `SETDEX[gen]`, not always `SETDEX_SV`.
   - Hide the Prep tab and the HC badge, and skip `_enrichEnemyMons` RR matching, when the game
     isn't RR (read a flag from the payload; don't sniff species).
6. **Gen 1 enemy data (M).** Send enemy max HP, moves and status from `lua/gen1/client.lua`, and
   stop the server defaulting `maxHP` to 1 when it's missing. Also use `adapter_for(pid)` in
   `handle_calc_mons` (item 10 above).
7. **pureRGB custom data (L, confirm scope with the owner first).**
   - pureRGB adds 6 types (Crystal, Bonemerang, Tri, Floating, Magma, Typeless), 5 custom moves
     (Filthy Slam, Heat Rush, Siphon Snag, Firewall, Dust Claw), 5 spirit species and alternate
     forms (see `data/games/gen1_purergb/`).
   - The RR approach is a patch compiled into the TypeScript tables. A `PURERGB_PATCH` on the Gen 1
     tables, with its own generation id, is the likely route.
   - The engine's type code may not accept new types without surgery (*inferred*). Prototype that
     first and report before building the rest.
8. **Trainer teams outside RR (L, optional, ask first).** Trainer parties from the pret
   disassembly data feeding `trainer_party`/`trainer_brief` and a per-game setdex. Until this
   exists, task 5 keeps RR sets out of other games.
9. **RR gaps (S).**
   - These have no calc entry: Leech Fang, Metal Bash, the As One ability, Primal Palkia (see
     `UNRESOLVABLE` in `tests/unit/test_rr_calc_names.py:~39-105`).
   - Add them to the RR patch in the calc tables if the calc can model them, else keep them on the
     allowlist with a reason.
   - Enemy natures are always Hardy; send the real one if the client has it.

Flip each game's `supports_web_calc()` to True only once its numbers are right. Check that by
comparing a few hand-worked damage rolls, e.g. a Gen 1 critical hit, a Gen 3 special-by-type
move.

## Rules

- **Adapter isolation (CLAUDE.md).**
  - Never add `is_rr` or a `game_id` branch to `server.py`, `state.py`, `adapters/base.py` or
    `pokemon_data.py`.
  - Add a base-class method with an inert default and override it per game.
  - Adapters never import `server.server`.
  - After a shared-code change, run the Gen 3 tests first (`/slink-test 3`), then the rest.
- **Git.**
  - Work in your own worktree on a `claude/calc-*` branch outside Google Drive, e.g. under
    `C:/Users/howar/AppData/Local/Temp/`. Use `git -c maintenance.auto=false -c gc.auto=0` for
    every command.
  - Commit with pathspecs only, never `git add -A`. Never stash: the stash stack is shared and a
    hook blocks it.
  - Keep each file's line endings; most are CRLF.
  - End commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - No push. Merging to local master is fine once the suite is green and it merges cleanly.
- **Other lanes are active.**
  - The Gen 2 session owns `lua/gen2/**`, `lua/clients/gen2_*`, `server/adapters/gen2_crystal.py`,
    and has a freeze on `server/**/*.py` and `lua/*.lua` for its branch. Tell it before you land
    changes to those.
  - The Gen 3 session ("Gen3 migration planning") owns the Gen 3 Lua client and
    `rival_trainer_ids`. It will merge master into its branch, so keep your server edits small and
    separate.
  - The pureRGB lane owns `lua/gen1/*`. Tell it before touching those (task 6).
  - Message the other sessions with SendMessage; `ListAgents` shows who is live.
- **Emulators.** Don't start BizHawk unless a task needs it, and never kill EmuHawk by image
  name; other lanes run emulators on this machine. Kill only PIDs you started.
- **Testing.**
  - One sensible test per feature (owner preference); no review ceremony for small changes.
  - Full suite: `python -m pytest tests/unit -q -p no:cacheprovider`. In a worktree add
    `--ignore=tests/unit/test_gen1_trade_patch.py`, which fails there for an unrelated toolchain
    warning.
  - Lint: `ruff check server tests tools`.
  - Lua syntax: use `lupa` (Lua 5.5), not the system `luac` 5.1.
- **Calc build.** `calc/dist` is not in git. After changing `calc/src` or `calc/calc/src`, run
  `npm run build` in `calc/`. That runs `subpkg run build` (tsc + bundle) then `node build view`.
  The engine has jest tests (`npm test` in `calc/calc`).
- **Verifying in the browser.** Run a server with `python -m server.server`, then
  `python tools/inject_full_mocks.py` for realistic mock state, and open `/calc/normal.html`.
  Mocks are Gen 3; for other games, construct a payload or use a fixture from `tests/`.

## Done when

- Each supported game opens the calc in its own generation, with its party's names, moves, items
  and stats correct.
- Unknown names warn instead of vanishing.
- RR-only features don't appear in other games, and the Calc tab only shows where the numbers are
  right.
- The unit suite and lint are green.
- Report back to the owner with:
  - a per-game table;
  - what you verified by hand;
  - what's left (pureRGB and non-RR trainer teams are expected to be decisions, not surprises).
