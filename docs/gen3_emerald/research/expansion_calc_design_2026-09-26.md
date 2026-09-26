# Damage calc support for pokeemerald-expansion — research + phased plan

All paths relative to the gen3-emerald worktree (`E:/Google Drive/SLink/.claude/worktrees/gen3-emerald`)
unless marked `[em-x1]` or `[em-xa]` (the two unmerged worktrees under `C:/slink-wt/`).
Every code claim below has a `file:line` citation from a direct read; anything I could not
verify by reading source is marked **UNVERIFIED**.

## 1. How the calc plugs in today

**Serving.** The run server and the Manager both serve the same vendored calc tree.
`server/manager.py:1907-1935` (`handle_run_calc`) wraps `calc/dist` entry points in SLink's
chrome; `server/manager.py:1937-1940` (`handle_calc_asset`) serves its absolute-path assets.
`server/calc_files.py:22-45` (`resolve`) prefers `calc/src/` over `calc/dist/` so JS edits are
live without a build step. There is no per-game calc *file*; one bundle serves every game.

**Gating.** `server/manager.py:234-267` (`_calc_profile_for_run`) instantiates both players'
adapters via `get_adapter(...)` and calls `calc_profile()` on each, then
`server/adapters/__init__.py:114-124` (`shared_calc_profile`) intersects the two dicts: the
Calc tab and dashboard preview stay hidden unless both players' profiles agree on `gen` and
`dex` (line 121-124). `server/manager.py:171-173` also blocks `battle_calc` capability
entirely for `gen1_rby`/`gen1_purergb` ("pinned to modern mechanics").

**Adapter hook points** (`server/adapters/base.py:502-589`, all defaulted to inert):
- `calc_name(kind, name)` (base.py:502-508) — identity by default; a game whose ROM spelling
  differs from the calc's overrides it with a lookup table.
- `calc_species(species_id)` (base.py:510-523) — defaults to `calc_name("species", species_name(...))`.
- `calc_profile()` (base.py:525-532) — returns `None` (calc hidden) unless overridden; contract
  is `{"gen": 1|2|3|9, "dex": "rr"|"vanilla"|"purergb", "sets"?: {"file","var"}}`.
- `calc_nature(key)` (base.py:534-539) — `None` for Gen 1/2 (no natures).
- `calc_stats(detail)` (base.py:541-551) — decodes a party blob into IVs/EVs/computed stats
  in the calc's stat-id shape; `None` = "calc keeps its own guess".

**Reference implementation, `Gen3Adapter`** (`server/adapters/gen3_frlge.py`):
- `calc_name` (671-675) looks a name up in `_RR_CALC_NAMES` or `_VANILLA_CALC_NAMES`, loaded
  from `data/games/gen3_frlge/calc_names.json` / `calc_names_vanilla.json` (278-304).
- `calc_profile` (677-684): RR → `{"gen": 9, "dex": "rr"}`; vanilla FR/LG or Emerald →
  `{"gen": 3, "dex": "vanilla", "sets": {"file": "Emerald.js"|"FRLG.js", "var": "CUSTOMSETDEX_..."}}`.
  Confirmed by `tests/unit/test_calc_profile.py:17-25`.
- `calc_nature` (686-694) derives the nature from the personality value in the wire key.
- `calc_stats` (696-718) decodes the 100-byte party blob via `gen3_codec.decode_party_mon`.

**Trainer sets / Prep tab.** The calc's own "📋 Prep" tab (`calc/src/js/slink_bridge.js:1449-1456`)
is driven entirely by vendored JS files under `calc/src/js/data/sets/games/*.js` (RR uses its own
`SETDEX_SV`/`SETDEX_HC` pair; every other game uses the single file+var named in
`calc_profile()["sets"]`, loaded and indexed at `slink_bridge.js:192-228`). These files are
**not** generated from the adapter's `trainer_party()`/`trainers_for_area()` — those feed a
separate dashboard feature, the "Upcoming Key Trainers" panel (`server/server.py:965`). The
vendored sets are pulled from KinglerChamp/VanillaNuzlockeCalc and cross-checked against a pret
decomp checkout by `tests/unit/test_calc_trainer_sets.py` (header comment 1-15; Emerald's own
provenance header at `calc/src/js/data/sets/games/Emerald.js:1-9` — pinned to a pokeemerald
checkout at `c65e93f2`, 997 of 1,825 pret party slots covered, cross-checked for species+level,
held item, moves, IV).

**Mechanics generation per game.** `calc/calc/src/calc.ts:13-24` dispatches purely on `gen.num`:
gen 1/2 → `calculateRBYGSC`, gen 3 → `calculateADV`, gen 4 → `calculateDPP`, gen 5/6 →
`calculateBWXY`, **gen 7/8/9 → the same `calculateSMSSSV`** (`mechanics/gen789.ts`). RR already
runs at `gen: 9` (test_calc_profile.py:17-18); vanilla FR/LG/Emerald run at `gen: 3`
(gen3_frlge.py:684).

## 2. What an expansion build needs, and what we already have

**Species/move/item/ability data.** `[em-xa] server/adapters/gen3_expansion.py` (unmerged) is a
`Gen3Adapter` subclass that reads `data/games/gen3_exp/28877d73/data.json` (line 33, `PACK`) —
national-dex-numbered species with types/abilities/genderRatio/family, moves with
power/accuracy/pp and a **ROM-read** physical/special/status `category` (lines ~170-185,
`move_data`: `{1:0,2:1,3:2}.get(row.get("category"), 2)`), items, and abilities (names only —
`ability_description` returns `""`, line ~185). This is enough for `calc_name`/`calc_species`
name-mapping and for `move_data`'s split — **the move split does not need a config toggle at
all**, since expansion always stores the real category per move in the ROM; no gen789-vs-ADV
heuristic is needed here, unlike a hypothetical type-based fallback.

Currently `calc_profile()`, `calc_name()`, `calc_stats()`, `calc_nature()` are all stubbed
(`None`/identity) and `trainer_party`/`trainers_for_area`/`trainer_info` return
`[]`/`[]`/`("", "")` — the class-level comment says plainly "Expansion calc is unsupported."

**Config toggles (`include/config/battle.h` B_\* macros).** These are **not extracted anywhere**
today. `[em-x1] data/games/gen3_exp/28877d73/facts.json` (schema keys: `constants`,
`derived_addresses`, `headers`, `structs`, `symbol_checks`, `unavailable`, …) — its `constants`
dict (70 entries) is *runtime* enum values baked into the binary as data (`B_OUTCOME_WON=1`,
`B_TRAINER_PLAYER=0`, `BATTLE_TYPE_TRAINER=8`, …), not the compile-time `#if`-gated mechanics
knobs (`B_CRIT_MULTIPLIER`, `B_PHYSICAL_SPECIAL_SPLIT`, `B_ABILITY_WEATHER`, `B_TERRAIN_TYPES`,
etc.) — those never reach the ROM as symbols because the preprocessor consumes them.
`data/gen3_exp_sources.lock.json` (schema recorded in both this worktree and `[em-xa]`) confirms
this gap: `config_headers` (lines with `include/config/battle.h`) records only a **sha256 of the
header file**, not its parsed values. So: **the actual B\_\* values must be read from
`include/config/battle.h`'s source text at the pinned commit** (`e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7`,
tag `expansion/1.17.0`, per the lock file), on the build host (`~/slink-exp` on the pinned VM,
ssh alias `hgbox` per `[em-x1] tools/build_expansion.py:1-20`) — no ROM-side extraction can
recover them. **UNVERIFIED**: I have not read `include/config/battle.h`'s actual contents (only
its hash is pinned in this repo), so I cannot state expansion 1.17.0's actual
`B_CRIT_MULTIPLIER`/`B_PHYSICAL_SPECIAL_SPLIT`/etc. values here.

**Trainer sets for Prep.** No vendored/extracted trainer-party table exists for expansion
(`trainer_party`/`trainers_for_area` return empty, gen3_expansion.py). This is a real gap:
building an `EmeraldExpansion.js`-style set file needs the pinned source's `src/data/trainers/*`
tables, same category of work as `[em-x1]`'s facts/layout extraction but for `gTrainers[]`
rather than struct offsets — **UNVERIFIED** whether the existing compiler-layout tooling
(`gen_expansion_facts.py`/`extract_expansion_data.py`) already reaches trainer data; the current
data pack (`data.json`: species/moves/items/abilities only) does not include it.

## 3. Does the vendored calc already support Gen 8/9 mechanics?

Yes. `calc.ts:20-22` already routes gen 7/8/9 through one Showdown-derived mechanics module
(`mechanics/gen789.ts`), which implements Tera (`gen789.ts:63-64,112-114`), terrain-multiplier
generation gating (`gen789.ts:1063,1341`: `gen.num > 7`/`>= 9` → 5325 vs 6144), and
generation-gated ability behavior (`gen789.ts:1176,1363`: Heatproof gen ≤8 vs ≥9). This is the
real Showdown gen9 engine, not a stub.

**But the gen-9 *data tables* in this fork are not pure Scarlet/Violet.** Each of
`abilities.ts`, `moves.ts`, `species.ts` layers RR's homebrew content on top of the official
data at the gen-9 slot:
- `abilities.ts:342-363`: `const RR = SV.concat([...18 RR-only ability names...])`; `ABILITIES[9] = RR`.
- `moves.ts:5113,5115`: `const SV = extend(true, {}, SS, SV_PATCH, RR_PATCH); MOVES[9] = SV`.
- `species.ts:10657`: `const SV = extend(true, {}, SS, SV_PATCH, PLA_PATCH, RR_PATCH)`.
- `items.ts:492-599` is the one exception: `ITEMS[9] = SV` with **no** RR concat — gen-9 items
  are pure official SV.

Practically: gen 9's ability/move/species tables are a **superset** of real Gen 9 (official
names first, RR's fictional extras appended after), so as long as expansion doesn't invent its
own ability/species/move *names* that collide with RR's, mapping expansion → `gen: 9` should
resolve almost everything through the existing official-name entries, the same way
`gen3_frlge.py:671-675`'s `calc_name` table maps ROM spelling → calc spelling today (e.g.
`"BubbleBeam"` → `"Bubble Beam"`, per the vanilla equivalent
`tests/unit/test_calc_names_multigen.py:1-13`). A reusable name-set helper already exists for
this: `tools/gen_rr_priority_trainers.py:99-124` (`calc_name_sets(gen)`), which for `gen=9`
"scans the whole file per kind ... matching the calc's actual Gen 9 dex" (comment, lines 104-106)
— i.e. it already includes the RR-superset union, so it is the right oracle to validate an
expansion `calc_names.json` against.

**Mismatches to flag (config vs. engine), most severity-ranked:**
1. **No per-config mechanics knob exists in the calc at all** — `calc.ts` dispatches by `gen.num`
   only (13-24). If a given expansion build sets, e.g., `B_CRIT_MULTIPLIER` to a legacy
   generation's value instead of the modern default, or disables the physical/special split (not
   applicable here since split is read from data, not config, per §2), there is **no adapter lever
   to express that** — the calc always runs gen789's fixed modern crit/terrain/ability logic once
   `gen: 9` is selected. This must be accepted as a known limitation (documented, not silently
   wrong) unless/until a per-build override layer is built into the calc itself (out of scope for
   a first cut; RR does not need this since its whole balance is already baked into being "gen 9").
2. **Ability effects, not just names, are hardcoded in `gen789.ts` by literal string match** (e.g.
   `gen789.ts:1176`). If a hack built on expansion adds a brand-new ability with unique battle
   behavior, the calc will silently apply *no* effect for it (unknown ability name), the same
   failure mode RR already accepted for anything it appended past `SV.concat([...])` that the
   engine doesn't special-case. This is a per-hack risk, not one specific to the 1.17.0 reference
   build (which — **UNVERIFIED** — I believe ships only canonical abilities, since
   `[em-xa] gen3_expansion.py` extracts names only, no custom-ability marker in `data.json`).
3. **Type roster is compiled per-build, not fixed.** `[em-xa] gen3_expansion.py:32-34` hardcodes
   `TYPE_NAMES` with `Fairy` and `Stellar` present for *this* reference build — a different
   config (Fairy type off, or Tera off) would need its own `TYPE_NAMES`, already handled per the
   adapter-isolation pattern (it's adapter-local, not shared code) but confirms config toggles
   change even the type table, not just move/crit math.
4. Held items and natures are extracted/decodable already (§2) — no mismatch there **once** a
   `calc_stats`/blob-decode path exists (§4 XC3).

## 4. Phased plan (adapter-isolation: all new facts live under `data/games/gen3_exp/<rom_sha>/`
or `server/adapters/gen3_expansion.py`; no game-id branch enters `server/manager.py`,
`server/server.py`, `server/adapters/base.py`, or the calc's shared TS)

**XC0 — Extract the config header VALUES, not just their hash.** New
`tools/extract_expansion_config.py` (or extend `[em-x1] gen_expansion_facts.py`) runs on the
pinned build host and captures `include/config/battle.h`'s resolved macro values (e.g. via
`arm-none-eabi-gcc -E -dM` against the pinned checkout) into
`data/games/gen3_exp/28877d73/config.json`. *Falsifier*: `config.json["B_CRIT_MULTIPLIER"]`
matches a value hand-read from the checked-out header at commit `e8bd1cd7`. *Size*: S (one
script + one data file; no server code changes).

**XC1 — `Gen3ExpansionAdapter.calc_profile()` returns a real profile.** Map `config.json`'s
toggles to `{"gen": 9, "dex": "expansion", "sets": {...}}` (or `None` with a documented reason if
a config combination the calc can't represent is detected — see mismatch #1). Lives entirely in
`gen3_expansion.py`; base.py/manager.py untouched. *Falsifier*: new
`tests/unit/test_calc_profile.py::test_gen3_expansion_adapter_calc_profile` asserts the exact
dict, mirroring `test_rr_adapter_calc_profile` (test_calc_profile.py:17-18). *Size*: S.

**XC2 — Name-mapping table.** Generate `data/games/gen3_exp/28877d73/calc_names.json`
(species/ability/item/move: ROM spelling → calc spelling) by diffing `data.json`'s names against
`calc_name_sets(9)` (`tools/gen_rr_priority_trainers.py:99`); wire `Gen3ExpansionAdapter.calc_name`
the same way `gen3_frlge.py:671-675` does. *Falsifier*: new `test_gen3_expansion_calc_names.py`
mirrors `test_calc_names_multigen.py` — every name the adapter can emit for a real id resolves
(directly or via the table) against `calc_name_sets(9)`. *Size*: M (mechanical script + manual
review of the mismatch list it prints).

**XC3 — `calc_stats()` blob decode.** Confirm expansion's party-substructure layout against
`layout.json`'s struct offsets (`[em-x1] facts.json["structs"]`); if identical to vanilla Gen 3,
delegate to `gen3_codec.decode_party_mon` like `gen3_frlge.py:696-718`; if not, add an
expansion-local decode function (adapter-local, not shared `gen3_codec` changes unless the
struct is provably identical). *Falsifier*: unit test decodes a synthetic blob (SYNTH-labeled
per the O-33 convention) with known IVs/EVs and asserts the returned dict. *Size*: M.

**XC4 — Trainer sets for the Prep tab + "Upcoming Key Trainers".** Two related but separate
tracks per §1's finding that they're independent features:
  (a) Extract `gTrainers[]` party data from the pinned source into a new vendored
      `calc/src/js/data/sets/games/EmeraldExpansion.js`, cross-checked against the source the
      same way `Emerald.js`'s header (lines 1-15) documents its pret cross-check; wire
      `calc_profile()["sets"]` to it.
  (b) Implement `trainer_party`/`trainers_for_area`/`trainer_info` on `Gen3ExpansionAdapter`
      from the same extracted table, for the dashboard's "Upcoming Key Trainers" panel — required
      for an RC per the standing ruling that trainer panels are mandatory, not RR-only.
*Falsifier*: a `test_gen3_expansion_trainer_sets.py` mirroring
`test_calc_trainer_sets.py`'s species+level whole-file-multiset check against the pinned source's
trainer table. *Size*: L — this is the largest phase (new extraction + generation + two
verification suites).

**XC5 — Turn the Calc tab on for real.** Once XC1-XC4 land and their falsifiers are green,
nothing in `manager.py`/`adapters/__init__.py` needs to change — `shared_calc_profile`
(adapters/__init__.py:114-124) is already game-agnostic. *Falsifier*: a live-gate run pairing an
expansion run against itself shows the Calc tab and the dashboard preview. *Size*: S (gate run,
no new code beyond flipping on whatever XC1 left conditional).

**XC6 (repeat, not new code) — later open-source hacks built from expansion.** Each new pinned
build gets its own `data/games/gen3_exp/<rom_sha>/{config,calc_names,data}.json` and (if it adds
homebrew abilities/species/moves) its own concat-style extras analogous to `abilities.ts:342-363`'s
RR append — but that concat lives in the *vendored calc's* gen-9 table (shared file), so a
hack that adds genuinely new content needs a small, reviewed PR to `abilities.ts`/`moves.ts`/
`species.ts` (precedent: the RR concat already there), not a server-side branch. The
adapter-isolation rule is unaffected either way: `server/adapters/gen3_expansion.py` and its data
pack are the only per-build surface; `server/manager.py`, `server/server.py`,
`server/adapters/base.py`, and `calc/calc/src/calc.ts` need no per-game-id branch anywhere in
this plan.
