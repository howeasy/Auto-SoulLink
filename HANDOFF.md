# Handoff — Gen 1 + Gen 2 parity work — **PHASES 0-11 COMPLETE**

## Current status (as of commit b4a869c)

**Branch**: `gen1-gen2-parity` — **15 commits ahead of master**, ready for runtime smoke testing then merge.
**Worktree path**: `E:\Google Drive\SLink\.claude\worktrees\gen1-gen2-parity`.
**Full plan (with revision history)**: [`~/.claude/plans/read-the-handoff-file-mellow-crown.md`](file:///C:/Users/howar/.claude/plans/read-the-handoff-file-mellow-crown.md)

**Test state**:
- `pytest tests/unit/` → **897 passing** (was 853 baseline; +44 new tests)
- `python tools/verify_profile_addresses.py` → **156 ok / 0 fail / 0 warn / 79 skip**
- Gen 3 regression: 207 Gen 3 adapter tests still pass

**What's still required**: a 30–60 minute runtime smoke session in BizHawk — see [tests/PHASE9_BATCH.md](tests/PHASE9_BATCH.md). The original day-long Phase 0 address audit is gone (replaced by Phase 10 automation).

---

## What was delivered (commits in chronological order)

| Commit | Phase | What it adds |
|---|---|---|
| `7be27e4` | 0 | pret address audit doc + diagnostic Lua scripts for every profile address |
| `0a3dcd0` | 1 | Gen 2 egg-gift detection (Route 34 reclassified daycare, not gift); memorialize routing → dedicated Box 12/14 |
| `033a4d2` | 2 | Stat stages for Gen 1 (R/B/Y) + Gen 2 Crystal; 1..13 → 0..12 normalization for Gen 3 renderer compatibility |
| `0bb3186` | 3 | Moves + PP from party — 165 Gen 1 + 251 Gen 2 moves.json + `move_data`/`move_name` adapter; Gen 2 PP-Up bit unpacking |
| `f2bafb9` | 4 | Enemy moves + PP in battle (both gens) |
| `ac99a8e` | 5 | Trainer class + named gym leaders/E4/rivals; Lua-side resolution; server.py opponent_class fallback widened |
| `8006a5c` | 6 | Wild encounter tables JSON + adapter `encounter_table()` (partial coverage; expandable) |
| `9b6822b` | 7 | SFX infrastructure (`M.playSfx`) — disabled by default; diagnostics for live discovery |
| `71c7523` | 8 | Archipelago variant detection: RB AP (Alchav) + Crystal AP (gerbiljames fork) |
| `4cde85c` | 9 | Docs handoff: REFERENCE.md + per-game READMEs |
| `0c9291a` | 10 tools | pret .sym extraction pipeline (RGBDS v1.0.1 auto-installed; rgbasm/rgblink driven directly, no `make` / w64devkit) + pytest-gated verifier |
| `a494317` | 10 fixes | 7 pret-authoritative address corrections (Gen 1 box_nicks, Yellow stat-stages, Crystal stat-stages, Crystal trainer addresses) |
| `208050d` | 10 docs | PHASE9_BATCH.md trimmed to runtime-only Phase 9-smoke; phase0_address_audit.md archived |
| `b4a869c` | 11 | Gold + Silver support via pret/pokegold; ~45 min wall-clock thanks to Phase 10 infrastructure |

---

## Supported games after this branch

| Game | Variant string(s) | ROM title at 0x134 |
|---|---|---|
| Red | `red`, `red_ap` | `POKEMON RED` + seed-name at 0xFFDB → `red_ap` |
| Blue | `blue`, `blue_ap` | `POKEMON BLUE` + seed-name at 0xFFDB → `blue_ap` |
| Yellow | `yellow` | `POKEMON YELLOW` (no upstream AP world) |
| Crystal | `crystal`, `crystal_ap` | `PM_CRYSTAL` / `AP_CRYSTAL` (gerbiljames fork) |
| Gold | `gold` | `POKEMON_GLD` |
| Silver | `silver` | `POKEMON_SLV` |

All share `game_id = "gen1_rby"` (R/B/Y) or `"gen2_crystal"` (C/G/S) → single adapter per gen handles all variants.

---

## Files to know

**For the runtime smoke check** (see `tests/PHASE9_BATCH.md` for the full protocol):
- `lua/clients/gen1_rby_client.lua` — Gen 1 client (used for R/B/Y, including AP variants)
- `lua/clients/gen2_crystal_client.lua` — Gen 2 client (used for Crystal, Gold, Silver, and Crystal AP)
- `lua/games/gen1_rby.lua` — Gen 1 profiles (red/blue/yellow + red_ap/blue_ap)
- `lua/games/gen2_crystal.lua` — Gen 2 profiles (crystal + crystal_ap + gold + silver)
- `lua/memory_gb.lua` — shared GB/GBC memory helpers (used by Gen 1/2 only — never touched by Gen 3)

**For address verification** (Phase 10 pipeline):
- `tools/_build_tools_bootstrap.py` — auto-installs RGBDS v1.0.1 to `.cache/build-tools/` on Windows
- `tools/build_pret_syms.py` — clones pret/pokered/pokeyellow/pokecrystal/pokegold, drives rgbasm+rgblink directly, emits `data/pret_syms.json`
- `tools/verify_profile_addresses.py` — diffs Lua profile addresses vs pret authority
- `tests/unit/test_profile_addresses.py` — pytest gate (skipped if pret_syms.json missing)
- `data/pret_syms.json` — 33,686 symbols across 4 repos (~14MB pretty-printed, committed so contributors without RGBDS can still run pytest)

**For the adapters** (Python side, server-rendered features):
- `server/adapters/gen1_rby.py` — Gen 1 adapter (move_data, encounter_table, item_name, etc.)
- `server/adapters/gen2_crystal.py` — Gen 2 adapter (same + is_daycare_area, gender from DVs, shinies)
- `data/games/gen1_rby/` — moves.json, trainers.json, encounter_tables.json
- `data/games/gen2_crystal/` — same set

**Diagnostic Lua scripts (Phase 9 reference)** in `lua/tests/`:
- `test_gen{1,2}_profile_audit.lua` — Phase 0 raw address dumps
- `test_gen{1,2}_stat_stages.lua` — Phase 2
- `test_gen{1,2}_moves.lua` — Phase 3
- `test_gen{1,2}_enemy_moves.lua` — Phase 4
- `test_gen{1,2}_trainer_info.lua` — Phase 5
- `test_gen{1,2}_sfx.lua` — Phase 7 (SFX dispatch discovery)

---

## Server interaction surface (regression-safe)

The only modification to shared server code is **server/server.py:2818-2825** — a one-block widening of the opponent_class fallback path. The widening is behind an `elif` that only fires when `adapter.trainer_info(tid)` returns empty `("", "")`. Gen 3's adapter always returns non-empty for trainer battles → Gen 3 path is bit-identical to master.

Everything else flows through the adapter:
- `stat_stages` field in party/enemy snapshots → rendered by `server/server.py:_stat_stages_html()` (gen-agnostic).
- `moves[]` / `pp[]` / `pp_bonuses` → `_enrich_party()` / `_enrich_battle_state()` resolve to `move_details` via `adapter.move_data()`.
- `is_egg` capture flag → `state.py:_is_gift_capture(area_id, is_egg)` checks `adapter.is_daycare_area()` (Gen 1/2 had `is_daycare_area` added in Phase 1; Gen 3 already had it).
- `opponent_class` / `opponent_name` → set via the widened fallback OR adapter `trainer_info`.

No other shared code (server.py, state.py, stream_overlays.py, pokemon_data.py, move_data.py) was modified.

---

## What remains (Phase 9-smoke — for the human user)

Open `tests/PHASE9_BATCH.md` and work through 6 sections (~30-60 min total):
1. **Memorialize routing** — load a ROM, faint a linked mon, confirm body ends up in Box 12 (Gen 1) or Box 14 (Gen 2)
2. **Egg-gift classification (Crystal)** — wild Route 34 capture, Mystery Egg from Mr. Pokemon, daycare-bred egg, box pickup
3. **Status page rendering** — Moves(N) badges, stat-stage badges, trainer name header, encounter overlay
4. **AP variant detection (optional)** — only if user has Alchav RB AP / gerbiljames Crystal AP patched ROMs
5. **SFX dispatch (optional)** — Phase 7 is disabled by default; the diagnostic lets the user probe candidate addresses
6. **Gen 3 regression** — load FireRed, walk 10 paces, confirm no visual differences from master

After verification, branch is ready to merge to master via squash or merge — user's call.

---

## How to continue work in a fresh agent session

```
# Enter the worktree
cd "E:/Google Drive/SLink/.claude/worktrees/gen1-gen2-parity"

# Verify state
git log --oneline master..HEAD          # 15 commits
python -m pytest tests/unit/ -q          # 897 passing
python tools/verify_profile_addresses.py # 156 ok / 0 fail

# Re-run address verification (if pret upstream changed)
python tools/build_pret_syms.py --update # ~30s
python tools/verify_profile_addresses.py # confirm still all-OK

# To add a new variant (e.g. Crystal_AU localization), pattern from Phase 11:
# 1. Add repo entry to tools/build_pret_syms.py PRET_REPOS dict
# 2. Run build_pret_syms.py
# 3. Inspect symbols vs existing profile
# 4. Add variant profile to lua/games/gen{1,2}_*.lua
# 5. Update detect_variant() / rom_type_for_variant()
# 6. Add variant mapping to tools/verify_profile_addresses.py PROFILE_TO_PRET
# 7. Run verifier; commit
```

## Plan-file revision history

The plan at `~/.claude/plans/read-the-handoff-file-mellow-crown.md` has the full design discussion with the user across this session, including:
- Original Phases 1-6 plan
- Scope expansion (Phase 7 sound, AP variants, testing-at-end)
- Phase 10 investigation (5 approaches evaluated; pret .sym extraction chosen)
- Phase 10 → supersede Phase 9 reframing
- RGBDS direct-invocation rationale (no `make` / w64devkit needed)
- Cross-generation scope analysis (Gen 3 feasible, Gen 4 deferred)

It's the canonical record. The HANDOFF.md you're reading is the execution summary.

---

## Original handoff context (preserved for reference)

The pre-execution handoff (replaced by this document) is in commit `e625364` — git show that commit to see the original phase plan. The exec turned out close to the original plan with three additions:
- Phase 7 (sound effects) re-included after being initially deferred
- Phases 8 (AP variants) + 10 (pret automation) + 11 (Gold/Silver) added during execution
- Phase 9 collapsed from day-long to 30-60 min smoke check

Gen 3 / Radical Red / Emerald — strictly untouched. The hard constraint held throughout.
