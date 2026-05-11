# SLink Damage Calculator

This is a fork of the [RadicalRedShowdown damage calculator](https://github.com/RadicalRedShowdown/damage-calc), embedded in the SLink server and served at `/calc/`. It provides damage calculation for Radical Red / CFRU Pokémon runs with live party integration via the SLink Bridge Panel.

---

## Active Pages

Only two pages are built and served:

| File | URL (relative to server) | Description |
|---|---|---|
| `dist/normal.html` | `/calc/normal.html` | Normal-difficulty trainer sets |
| `dist/hardcore.html` | `/calc/hardcore.html` | Hardcore-difficulty trainer sets |

All other upstream pages (`index.html`, `randoms.html`, `honkalculate.html`, `oms.html`) have been removed — they are not reachable from the SLink server and were unused.

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

The calc result line (e.g., `"Lvl 50 Charizard Flamethrower vs. Lvl 50 Blastoise: 45-53%"`) does **not** show EV investment numbers. Since all mons in our runs assume maximum EVs, the original `"252 SpA"` / `"0 HP / 0 SpD"` annotations were always `0` and have been removed from `calc/src/desc.ts` to reduce clutter.

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
│       ├── desc.ts         # Result description builder — EV display suppressed
│       └── ...             # Mechanics, data types, formula
├── src/                    # UI source files
│   ├── normal.template.html    # Normal-difficulty page template
│   ├── hardcore.template.html  # Hardcore-difficulty page template
│   ├── css/                    # Stylesheets (dark theme, main, type colours)
│   ├── img/                    # Static images
│   └── js/
│       ├── slink_bridge.js         # SLink bridge panel (live party integration)
│       ├── moveset_import.js       # Showdown paste → calc field populator
│       ├── shared_controls.js      # Core UI logic, search, trainer set matching
│       ├── index_randoms_controls.js  # Mode switching (Normal/Hardcore)
│       ├── data/
│       │   └── sets/
│       │       ├── normal.js       # Normal-mode RR trainer sets (SETDEX_SV)
│       │       └── hardcore.js     # Hardcore-mode RR trainer sets (SETDEX_HC)
│       └── vendor/                 # jQuery, Select2, etc.
├── dist/                   # Build output (served by SLink HTTP server)
│   ├── normal.html
│   ├── hardcore.html
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

