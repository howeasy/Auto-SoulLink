# Gen 2 encounter and area-map generation from pret

Type: research
Status: resolved
Blocked by: none

## Question

Gen 1 generates wild tables, areas and statics from pret with two-path equality (F-4, F-5). Gen 2 has time-of-day grass/water tables per map (`data/wild/johto_grass.asm` differs between Gold and Silver: Codex cx-3569f8d9 finding 4), headbutt, rock smash, fishing, roaming legendaries, Bug-Catching Contest, and Kanto. Define the generator inputs (`data/wild/*.asm`, `data/maps/*.asm`, `constants/map_constants.asm`) and the area_id policy (does time of day split an area? no, per Gen 1 precedent: one area per map), per title, with the Gen 1 S-8 statics/fishing split as precedent.

## Answer

Resolved by research lane R5 (§B and 'Recommended generator inputs'). Sources per title: `data/wild/{johto_grass,kanto_grass,johto_water,kanto_water}.asm` with inline `IF DEF(_GOLD)`/`ELIF DEF(_SILVER)` per-map species swaps in pokegold (9+ blocks in `johto_grass.asm`) and no conditional in pokecrystal; `fish.asm`, `treemons.asm`/`treemon_maps.asm` (headbutt; Crystal adds `treemons_asleep.asm`), `roammon_maps.asm`, `swarm_grass.asm`/`swarm_water.asm`, `bug_contest_mons.asm`; statics from `maps/*.asm` `loadwildmon`/`givepoke` sites. The `map_id` macro encodes `(GROUP, MAP)` exactly as the composite id the existing `gen2_crystal_areas.lua` uses (hypothesis confirmed against source). Today's `tools/gen_gen2_encounters.py` covers Crystal grass/water only with unchecked rate assumptions. Area-id policy adopted for the plan: time of day never splits an area; headbutt/rock smash/fishing = the map (Gen 1 S-8 precedent); roamers and the Bug-Catching Contest are special cases and an OWNER QUESTION (`OPEN_QUESTIONS.md` A-7). Generator spec: one `gen_gen2_encounters.py` producing per-title packs from the pinned source with a Lua ROM-reader two-path equality check (Gen 1 F-4).
