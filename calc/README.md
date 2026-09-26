# SLink Damage Calculator

This is a fork of the [RadicalRedShowdown damage calculator](https://github.com/RadicalRedShowdown/damage-calc), embedded in the SLink server and served at `/calc/`. It started out Radical Red / CFRU-only; it now also calculates for FireRed/LeafGreen, Emerald, Red/Blue/Yellow, pureRGB and Crystal/Gold/Silver runs (see "Generation, Dex & Trainer Sets" below), with live party integration via the SLink Bridge Panel.

---

## Active Pages

Only two pages are built and served:

| File | URL (relative to server) | Description |
|---|---|---|
| `dist/normal.html` | `/calc/normal.html` | Normal-difficulty trainer sets |
| `dist/hardcore.html` | `/calc/hardcore.html` | Hardcore-difficulty trainer sets |

All other upstream pages (`index.html`, `randoms.html`, `honkalculate.html`, `oms.html`) have been removed — they are not reachable from the SLink server and were unused.

`server/calc_files.py` resolves both pages (`calc/src/` wins over `calc/dist/` for any path both have, so `src/` edits go live without a build step). The run server also serves the calc from inside the Manager's own chrome at `/runs/{id}/calc/…` — a bare `/calc/…` request there redirects to that per-run path — so the same `normal.html`/`hardcore.html` entry points can appear either standalone or wrapped in the Manager's page frame.

---

## Generation, Dex & Trainer Sets

One calc build now serves every supported game; which rules, dex and trainer sets it uses for a given run comes entirely from the server, not from a page the user picks:

1. `/api/calc/mons` includes `"calc": adapter.calc_profile()` — a small dict shaped `{"gen": <1-9>, "dex": <str>, "sets": {"file": ..., "var": ...}?}` that each game's adapter builds (e.g. `server/adapters/gen1_purergb.py`'s `calc_profile()` returns `{"gen": 1, "dex": "purergb", "sets": {"file": "PureRGB.js", "var": "CUSTOMSETDEX_PURERGB"}}`). `dex` is only meaningful for Gen 1, which has more than one dex flavour (`"vanilla"` vs `"purergb"`); other gens just send `gen`.
2. `src/js/slink_bridge.js`'s `_applyCalcGen()` reads that `calc` field on every payload: it switches the calc's gen radio (`#gen<N>`), and for Gen 1 calls `calc.useDex('purergb')` or `calc.useDex('vanilla')` (exported by `calc/calc/src/data/purergb.ts`) *before* the gen switch loads the pokedex, so the right species/moves/type chart are already live.
3. A `sets` entry names the trainer-set file to load from `src/js/data/sets/games/` (vendored for Gen 1/2/3, generated for pureRGB — see the "Vendored Trainer Sets" section below) and the global variable it exports.
4. RR-only bridge features (the Prep tab, the HC/Normal difficulty badge, trainer-set-composition enrichment) key off `dex === 'rr'` rather than sniffing species or gen, and stay RR-only regardless of what else the bridge learns about a run.

The wire shape of one enemy-party entry (`enemy_party`, an element of which the bridge matches against trainer sets) is `docs/protocol.md` §4.3's `FoeEntry` — not restated here.

Per-game status (what's wired, what's verified, what's still open for each game) is tracked in [`docs/calc_multigen/HANDOFF.md`](../docs/calc_multigen/HANDOFF.md), not here; this section only documents the *mechanism*.

---

## SLink Bridge Panel

A floating draggable panel (`src/js/slink_bridge.js`) is injected into both active pages. It:

- Connects to the SLink server via **Server-Sent Events** on `/api/events` (same origin by default; pass `?slink=http://host:port` to override)
- Shows live party data for both players (Player A / Player B tabs)
- Displays enemy battle mons with matched trainer sets and difficulty badges
- Highlights the active battler with an orange indicator
- **One-click import**: clicking any mon row loads its full Showdown paste into the calc attacker (`#p1`) or defender (`#p2`) slot

The panel position and collapse state persist in `localStorage`. On SSE disconnect, it reconnects automatically after 3 seconds.

---

## Search

All dropdowns use **full substring matching** — not starts-with:

- **Pokémon / set selector**: searches both the species name and the trainer/set name. Typing `"Blue"` finds all of Rival Blue's mons; typing `"zard"` finds Charizard.
- **Move selector**: searches anywhere in the move name. Typing `"bolt"` finds Thunderbolt.

Matched characters are highlighted in the calc's accent colour using `<mark>` elements, making it immediately clear which part of the result matched the query.

Results display the full `"Pokémon (Trainer Set Name)"` string — so searching by trainer name shows the Pokémon species alongside it.

---

## Result Description

The calc result line (e.g., `"Lvl 50 Charizard Flamethrower vs. Lvl 50 Blastoise: 45-53%"`) does **not** show EV investment numbers. `calc/calc/src/mechanics/*.ts` still populate `RawDesc.attackEVs` / `.defenseEVs` / `.HPEVs` for gens with EVs, but `buildDescription()` in `calc/calc/src/desc.ts` never reads those fields when assembling the line, so the `"252 SpA"` / `"0 HP / 0 SpD"` annotations (always `0` since all mons in our runs assume maximum EVs) never make it into the output.

---

## Build

```bash
# Install dependencies (run once)
npm install
cd calc && npm install && cd ..

# Full build: TypeScript compile → bundle → copy assets → hash HTML
node build

# Fast rebuild: only copy assets and rehash HTML (use after editing src/ files, not .ts)
node build view
```

Output goes to `dist/`. Always run `node build` (not `node build view`) after any changes to `calc/calc/src/` TypeScript files — `node build view` does **not** recompile TypeScript.

---

## Directory Structure

```
calc/
├── calc/                   # @smogon/calc TypeScript package (upstream fork)
│   └── src/
│       ├── desc.ts         # Result description builder — never renders EVs (see below)
│       ├── data/purergb.ts # pureRGB's Gen 1 species/moves/type chart + useDex() swap
│       └── ...             # Mechanics, data types, formula
├── src/                    # UI source files
│   ├── normal.template.html    # Normal-difficulty page template
│   ├── hardcore.template.html  # Hardcore-difficulty page template
│   ├── css/                    # Stylesheets (dark theme, main) — no per-type colouring; type
│   │                            # selects are plain <option> text for every game, RR included
│   ├── img/                    # Static images
│   └── js/
│       ├── slink_bridge.js         # SLink bridge panel (live party integration, gen/dex switching)
│       ├── moveset_import.js       # Showdown paste → calc field populator
│       ├── shared_controls.js      # Core UI logic, search, trainer set matching
│       ├── index_randoms_controls.js  # Mode switching (Normal/Hardcore)
│       ├── data/
│       │   └── sets/
│       │       ├── normal.js / hardcore.js    # RR trainer sets (SETDEX_SV / SETDEX_HC)
│       │       ├── gen1.js … gen9.js          # Generation move/species/ability/item tables
│       │       ├── slink_priority.js          # RR priority-set overrides
│       │       └── games/
│       │           ├── RedBlue.js / Yellow.js     # Vendored Gen 1 trainer sets
│       │           ├── Crystal.js                 # Vendored Gen 2 trainer sets
│       │           ├── FRLG.js / Emerald.js        # Vendored Gen 3 trainer sets
│       │           └── PureRGB.js                  # Generated (`tools/gen_purergb_setdex.py`)
│       └── vendor/                 # jQuery, Select2, etc.
├── dist/                   # Build output (served by SLink HTTP server)
│   ├── normal.html
│   ├── hardcore.html
│   ├── calc/               # Compiled @smogon/calc (from calc/calc/dist, copied by `node build`)
│   └── ...
└── build                   # Build script (Node.js, no extension)
```

---

## Removed Upstream Features

The following were present in the upstream fork but have been removed from this SLink integration:

| Removed | Reason |
|---|---|
| `randoms.html` / `index.html` / `honkalculate.html` / `oms.html` | Not linked from SLink server; unused |
| `oms_controls.js` / `honkalculate_controls.js` | Only used by removed pages |
| `index_randoms_controls.js` randoms/one-vs-one/oms branches | Dead code after page removal |
| Google Analytics (`googletagmanager.com` script) | Not applicable for a local-only tool |
| `makeCachebuster` calls for removed pages in `build` script | Would fail with deleted templates |

---

## Upstream

- Base: [RadicalRedShowdown/damage-calc](https://github.com/RadicalRedShowdown/damage-calc)
- Original: [smogon/damage-calc](https://github.com/smogon/damage-calc) by Honko, maintained by Austin and Kris

---

## Vendored Trainer Sets

`src/js/data/sets/games/{RedBlue,Yellow,Crystal,FRLG,Emerald}.js` are trainer-set dumps vendored from [KinglerChamp/VanillaNuzlockeCalc](https://github.com/KinglerChamp/VanillaNuzlockeCalc) @ `54ed9713ca0fed4d92fb50ee153e9e9c5f4bb4a8` (MIT licensed). Ruby/Sapphire were not carried over since SLink's calc doesn't support those games at all (no adapter). Gold/Silver *are* supported (Gen 2 rules run fine for them, `server/adapters/gen2_gsc.py`), but their trainer rosters differ from Crystal's, so they get no `sets` file rather than Crystal's mismatched one — `calc_profile()` omits `sets` entirely for Gold/Silver runs. `games/PureRGB.js` is not vendored at all — it's generated by `tools/gen_purergb_setdex.py` (see "Generation, Dex & Trainer Sets" above).

We don't trust vendored data blindly: `tests/unit/test_calc_trainer_sets.py` parses each file independently and checks species, level, and (where pret encodes them) movesets and trainer-class DVs against the [pret](https://github.com/pret) decompilations (`pokered`, `pokeyellow`, `pokecrystal`, `pokefirered`) in `.cache/pret`. A handful of confirmed vendor mistakes (wrong DVs, wrong levels) were fixed directly in these files — see each file's own header comment for the specifics. `Emerald.js` isn't cross-checked by that test (`pokeemerald` isn't one of its four `_PRET` entries, whether or not a local checkout exists), so it's vendored as-is and unchecked — Emerald is correspondingly still gated off in live runs (see HANDOFF.md).

