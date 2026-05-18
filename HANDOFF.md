# Handoff — Gen 1 + Gen 2 parity work

## What this worktree is for

Bring Gen 1 (Red/Blue/Yellow) and Gen 2 (Crystal) up to parity with Gen 3
(FRLG / AP / Radical Red) in this SLink Soul Link Nuzlocke tracker. Gen 3
is the production-stable gold standard; Gen 1/2 are marked ⚠️ experimental
in [docs/REFERENCE.md](../../../docs/REFERENCE.md) and need the missing
visible features (moves+PP display, stat stages, trainer names, encounter
tables, etc.) plus a few Gen 2 plumbing fixes.

**Branch**: `gen1-gen2-parity` (off `master` @ `c976065`).
**Worktree path**: `E:\Google Drive\SLink\.claude\worktrees\gen1-gen2-parity`.
**Full plan**: [`~/.claude/plans/gen1-gen2-parity-with-gen3.md`](file:///C:/Users/howar/.claude/plans/gen1-gen2-parity-with-gen3.md)
— read this in full before starting; the table below is just the
executive summary.

## HARD constraint — do not edit any Gen 3 code

Gen 3 just shipped 10 commits to master. Any regression there is
unacceptable. The following files / sections are off-limits:

- `lua/clients/gen3_frlge_client.lua`, `lua/memory_gba.lua`,
  `lua/games/gen3_frlge.lua`
- `server/adapters/gen3_frlge.py`
- Gen 3 / RR sections of `server/pokemon_data.py`
- Gen 3 branches inside `server/server.py`, `server/state.py`,
  `server/stream_overlays.py` — you may ADD new `if adapter.game_id in
  ("gen1_rby", "gen2_crystal"):` branches beside them, but do NOT modify
  the existing Gen 3 conditions or widen them
- `tests/unit/test_gen3_adapter.py`

**If a server-side renderer turns out to be Gen 3-gated**, add a parallel
Gen 1/2 branch beside it — never widen the Gen 3 condition. Goal: Gen 3
behavior stays bit-identical.

**Regression gate**: `pytest tests/unit/` must remain at 853 passing (plus
whatever new tests are added in the current phase) before any commit.

## Scope decisions locked in by the user

- Phases **1–6** in scope (in order). Phases 7 (sound effects), 8
  (Gold/Silver variants), 9 (calc bridge) deferred.
- Order: **1 → 2 → 3 → 4 → 5 → 6**.
- User available to run BizHawk diagnostic Lua scripts and report back.
- Pret repos as source-of-truth for addresses, cross-checked against
  user's live ROM via diagnostic scripts before profile edits:
  - [pret/pokered](https://github.com/pret/pokered)
  - [pret/pokeyellow](https://github.com/pret/pokeyellow)
  - [pret/pokecrystal](https://github.com/pret/pokecrystal)

## Gap matrix (executive view)

| Capability | Gen 1 | Gen 2 |
|---|---|---|
| Party diff / capture / faint / whiteout | ✅ | ✅ |
| Deposit / retrieve | ✅ | ✅ |
| Memorialize via `depositMemorialMon` | ✅ | ⚠️ falls back to `box_mon` |
| `force_faint` command | ✅ | ✅ |
| `force_whiteout` command | ✅ | ❌ not in dispatcher |
| Gift areas | ✅ | ✅ |
| Egg-gift detection (daycare-aware) | N/A (no eggs) | ❌ Route 34 daycare + eggs unhandled |
| ROM variants | R / B / Y all | ⚠️ Crystal only |
| Memory addresses verified | ✅ | ⚠️ 4 TODOs in profile |
| Moves + PP read from party | ❌ | ❌ |
| Stat stages read in battle | ❌ | ❌ |
| Enemy moves + PP in battle | ❌ | ❌ |
| Trainer class / name | ❌ adapter stub | ❌ adapter stub |
| Wild encounter tables | ❌ | ❌ |
| Held items / genders / shinies | N/A | ✅ |
| Abilities | N/A | N/A |

## Phase rollout protocol

Each phase is a discrete work session resulting in ONE commit. Steps within
a phase:

1. **Research** — fetch relevant pret tables/addresses, read affected
   client + adapter + profile files.
2. **Diagnostic Lua first** — write `lua/tests/test_gen{1,2}_<phase>.lua`
   that dumps candidate addresses. **Ask the user to F-key through it and
   report results before editing profiles.**
3. **Profile + client edits** — update `lua/games/gen{1_rby,2_crystal}.lua`
   profile and the client's `build_party_snapshot()` /
   `build_enemy_snapshot()`.
4. **Adapter + data** — extend `server/adapters/gen{1_rby,2_crystal}.py`,
   add data JSON in `data/games/gen{1_rby,2_crystal}/`.
5. **Tests** — extend `tests/unit/test_gen{1,2}_adapter.py`; add
   state-machine cases to `tests/unit/test_state.py` if applicable. Do
   NOT touch `test_gen3_adapter.py` fixtures.
6. **Docs** — flip the relevant row in
   [docs/REFERENCE.md](../../../docs/REFERENCE.md) Feature Status from ❌
   → ✅; update the per-game README; add to `tests/TESTING.md` checklist
   if manual.
7. **Manual smoke checklist** — provide the user a 5–10 min BizHawk
   play-through to confirm visible behavior.
8. **Regression gate** — `pytest tests/unit/` green (853 + new phase
   tests).
9. **Commit** — single commit, diff constrained to Gen 1/2/shared-non-Gen-3
   files. PR-shaped message.

## Phase 1 starting tactics (begin here)

**Goal**: unblock Gen 2 by verifying 4 TODO addresses, wiring two missing
commands, and adding egg-gift detection. Most plumbing; least risk.

### 1a. Verify Gen 2 battle memory addresses

[lua/games/gen2_crystal.lua:42-75](../../../lua/games/gen2_crystal.lua:42)
has these TODOs:

```lua
enemy_count_addr        = 0xD280  -- TODO: verify in BizHawk
enemy_base_addr         = 0xD288  -- TODO: verify in BizHawk
enemy_species_list_addr = 0xD281  -- TODO: verify in BizHawk
battle_flag_addr        = 0xD22D  -- TODO: verify (already gated as unreliable)
```

Pret cross-check: `pokecrystal/ram/wram.asm` — find `wOTPartyCount`,
`wOTPartyMon1Species`, `wOTPartySpecies`, `wInBattle`. Then write
`lua/tests/test_gen2_memory.lua` (model after the existing
[test_gen1_memory.lua](../../../lua/tests/test_gen1_memory.lua)) that
dumps reads of these addresses live during:
- overworld idle
- wild battle (e.g., grass on Route 29)
- trainer battle (e.g., Falkner)

User runs it with F-keys; verify the bytes you see match expectations
(party count 1–6, species 1–251, species-list 0xFF terminator). Update
profile, remove TODOs.

### 1b. Wire `force_whiteout` for Gen 2

[lua/clients/gen2_crystal_client.lua](../../../lua/clients/gen2_crystal_client.lua)
~line 212 is the dispatcher. Add a `force_whiteout` case modeled on
[gen1_rby_client.lua](../../../lua/clients/gen1_rby_client.lua)'s pattern:
loop slot 0..party_count-1 and call `M.forceFaint(slot)`.

### 1c. Route Gen 2 `memorialize` to `depositMemorialMon`

Currently Gen 2 memorialize uses regular `box_mon`. The shared helper
[memory_gb.lua:789 `M.depositMemorialMon`](../../../lua/memory_gb.lua:789)
already supports Gen 2 (Box 14 offset `0x79E0`). Switch the dispatcher
case to call it directly, mirroring Gen 1 client.

### 1d. Egg-gift detection (Gen 2)

Gen 2 has Daycare (Route 34) and eggs. Two-part wire-up:

- **Lua**: read the egg flag from the party mon struct. Per pret notes,
  Gen 2 marks eggs via a flag byte + species `0xFD`. Find the exact
  offset (probably the same general flag byte that holds the "is shiny"
  bit). Forward `is_egg=true|false` on capture events (mirroring Gen 3
  commit `be648eb` — see `git show be648eb -- lua/clients/gen3_frlge_client.lua`
  for the canonical wire-up shape).
- **Adapter**: override `is_daycare_area(area_id)` in
  [server/adapters/gen2_crystal.py](../../../server/adapters/gen2_crystal.py)
  to return `True` for the Route 34 daycare area_id. Look up the actual
  ID from
  [data/games/gen2_crystal/area_map.json](../../../data/games/gen2_crystal/area_map.json).
- **Tests**: mirror the three Gen 3 egg cases (egg-in-encounter-area-is-gift,
  egg-in-daycare-is-not-gift, capture-event-without-is_egg-field) that
  shipped in `be648eb` — see `tests/unit/test_state.py` for the
  pattern. Don't touch Gen 3 fixtures.

This leverages the existing
[`_is_gift_capture(area_id, is_egg)` in server/state.py:597](../../../server/state.py:597)
— zero Gen 3 paths touched.

### Phase 1 expected diff scope

- `lua/games/gen2_crystal.lua` — address fixes
- `lua/clients/gen2_crystal_client.lua` — dispatcher + egg flag read
- `lua/tests/test_gen2_memory.lua` — NEW (diagnostic)
- `server/adapters/gen2_crystal.py` — `is_daycare_area()` override
- `tests/unit/test_gen2_adapter.py` — daycare tests
- `tests/unit/test_state.py` — egg-gift state tests for Gen 2
- `docs/REFERENCE.md` — flip relevant rows ❌ → ✅
- `data/games/gen2_crystal/README.md` — note the new behavior

## Subsequent phases (one-line each)

- **Phase 2** — stat stages: add ATK/DEF/SPD/SPC/ACC/EVA reads in battle
  to both gens' `build_party_snapshot()` / `build_enemy_snapshot()`. Will
  light up the existing stat-stages renderer.
- **Phase 3** — moves + PP read from party struct for both gens. Generate
  `data/games/gen{1,2}/moves.json` from pret. Add `move_data()` /
  `move_name()` to adapters.
- **Phase 4** — enemy moves + PP in battle. Builds on Phase 3. Lights up
  the existing collapsible Moves(N) table.
- **Phase 5** — trainer class + name. Read trainer_class_id /
  trainer_id from RAM during trainer battles; implement
  `trainer_info()` on both adapters.
- **Phase 6** — wild encounter tables. Static JSON for R/B/Y and Crystal
  encounters; adapter `encounter_table()` impl lights up the existing
  `/stream/enc-table-{a,b}` overlay.

## Useful pre-existing Gen 3 reference commits

Look at these for the canonical shape of each feature when implementing
the Gen 1/2 equivalent (read-only — do not modify their code):

- `0c3a389` feat: doubles battle detection for Gen 3 status page
- `8d2e3f2` feat: detect enemy moves and PP in battle (Gen 3)
- `be648eb` feat: detect eggs in capture events to flag NPC egg-gifts as gifts
- `6b9d42f` feat: combined enemy-focus overlay + party-style enemy-trainer

## Key existing utilities (reuse, don't reinvent)

- `_is_gift_capture(area_id, is_egg)` —
  [server/state.py:597](../../../server/state.py:597)
- `M.depositMemorialMon(slot)` —
  [lua/memory_gb.lua:789](../../../lua/memory_gb.lua:789)
- `M.forceFaint(slot)` —
  [lua/memory_gb.lua:516](../../../lua/memory_gb.lua:516)
- `_enrich_party` / `_enrich_battle_state` in
  [server/server.py](../../../server/server.py) (already attaches move
  details when `moves[]` is present in the payload — should "just work"
  for Gen 1/2 once the Lua side emits the data)

## Open items / things to verify as you go

- Phase 2: Gen 1 vs Gen 2 stat-stage byte encoding (centered at 6? at 0?
  signed?). pret will clarify.
- Phase 3: Gen 2 PP byte high-2-bits hold PP Up count (similar to Gen 3)
  — verify formula matches Gen 3's `max_pp = base + base*pp_ups//5`.
- Phase 5: status page rendering of `bs.opponent_class` /
  `bs.opponent_name` — does it currently have a Gen 3 gate that would
  silently exclude Gen 1/2 even with real adapter data? Spot-check
  before starting Phase 5.
- Phase 6: `/stream/enc-table-*` overlay — does the current
  implementation have an `if is_rr:` guard? If yes, add a Gen 1/2
  parallel branch instead of widening the Gen 3 condition.

## Verification per phase

1. `pytest tests/unit/` green (currently 853 passing; growing per phase).
2. New phase tests pass.
3. User runs the manual BizHawk checklist (~5–10 min) and reports
   visible behavior.
4. Visual inspection of status page + relevant overlays.
5. docs/REFERENCE.md Feature Status table updated.

## When all six phases land

Final cleanup pass: update `README.md` if any newly-working features
warrant a one-line mention (likely yes for trainer names and encounter
tables). Update `tests/TESTING.md` end-to-end checklist if it diverged.
Merge `gen1-gen2-parity` → `master` via PR (squash or merge — user's
call).
