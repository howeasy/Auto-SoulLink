# RR priority-trainer roster regen -- 2026-09-26 (card RR-PT)

Owner ruling (2026-09-26): regenerate `data/games/gen3_frlge/rr_priority_trainers.json`
from today's pinned community sheet, replacing the committed copy, instead of carrying
the drift `tools/gen_rr_priority_trainers.py --check` reported in
`docs/gen3/research/f7_check_receipt_db4b6f81.txt`.

## What changed

- Pin: `data/gen3_rr_sources.lock.json`'s `rr_priority_trainers_sheet_xlsx`,
  `content_sha256 = 641a3e4f...9572b` (already fetched into
  `data/.rr_src_cache/` before this card started; not re-pinned here).
- HEAD before regen: `0c1aaf13`.
- Generator: `tools/gen_rr_priority_trainers.py` (one fix, see below).
- Output: `data/games/gen3_frlge/rr_priority_trainers.json` regenerated in place.
  `calc/src/js/data/sets/slink_priority.js` and
  `calc/dist/js/data/sets/slink_priority.js` were also regenerated but came out
  byte-identical to the committed copies (no diff).
- `python tools/gen_rr_priority_trainers.py --check` now exits 0 (byte-for-byte
  match, 443 trainers, 52 areas).

## The area spelling (vermilion_city / vermillion_city)

The RR/FRLG client only ever reports the id from `data/games/gen3_frlge/area_map.json`
(mirrored in `gen3_frlge_areas.lua`) as `area_id` for Vermilion City:
`"3:5": "vermilion_city"` (one L). `lua/gen3/client.lua`'s `area_now()` sends this
value straight through; `server/adapters/gen3_frlge.py`'s `trainers_for_area()` does
an exact dict lookup against `rr_priority_trainers.json`'s `trainers_by_area` -- no
normalisation. So any key spelled `vermillion_city` (two Ls) can never match and that
area's trainers would silently never appear in the Upcoming Key Trainers widget.

Today's pinned sheet's "Trainer Order" tab spells the city with two Ls in its plain
(non-"...GYM") form: `D99`/`D275` both read `VERMILLION CITY`. The generator's
`_AREA_OVERRIDES` table already special-cased `"VERMILION CITY GYM"` /
`"VERMILLION CITY GYM"` (both spellings) for boss-sheet headers, but had no entry for
the plain city name used by the Trainer Order tab, so it fell through to the default
normaliser and minted a new, wrong `vermillion_city` key.

Fix (`tools/gen_rr_priority_trainers.py`, `_AREA_OVERRIDES`): added
`"VERMILION CITY"` and `"VERMILLION CITY"` (plain, no "GYM" suffix), both mapping to
`vermilion_city`, next to the existing GYM-suffixed pair. Regenerating now produces
`vermilion_city` (not `vermillion_city`) again.

Regression guard: `tests/unit/test_gen3_rr_generators.py::test_priority_trainers_areas_are_client_emittable`
asserts every `trainers_by_area` key is either an id in `area_map.json` /
`gen3_frlge_locations.lua` (the two tables the client can ever emit an `area_id`
from) or in a small, named, pre-existing-gap allowlist (see "Other finding" below).
It would have caught `vermillion_city` outright.

## Per-area content diff (old committed vs regenerated)

Party data (species/level/moveset/etc.) is unaffected everywhere; the only changes
are to `trainers_by_area` (which runtime trainer IDs a city's widget lists) and, for
one area, which trainer belongs where.

| Area | Old | New | Note |
|---|---|---|---|
| `celadon_city` | Erika (rematch, id 65), Erika (id 417) | Erika (id 417) | rematch copy no longer area-tagged (see below) |
| `celadon_city_game_corner` | Boss Giovanni Set 1 (id 350), Grunt (id 382) | Grunt (id 382) | Giovanni's Set-1 fight re-tagged to `rocket_hideout` instead |
| `cerulean_city` | Misty ×2 rematch variants (32, 48), 3 Rival branches, Misty (415), Champion Rival (436) | 3 Rival branches, Misty (415), Champion Rival (436) | both Misty rematch copies no longer area-tagged |
| `pewter_city` | Brock (id 56), Brock (id 414) | Brock (id 414) | rematch copy no longer area-tagged |
| `rocket_hideout` | Giovanni (69), Grunts (385, 538) | + Boss Giovanni Set 1 (350), Giovanni (69), Grunts (385, 538) | gained the Set-1 Giovanni fight moved from `celadon_city_game_corner` |
| `vermilion_city` | Lt. Surge (rematch, id 51), Lt. Surge (416) | Lt. Surge (416) | rematch copy no longer area-tagged (spelling now correct; see above) |
| `viridian_city` | Clair (rematch, id 38), Clair (74) | Clair (74) | rematch copy no longer area-tagged |

**No gym leader, rival, or Elite Four/Champion trainer was removed from the roster**
-- `parties` still has all of them (ids 32, 38, 48, 51, 56, 65 all still resolve to
full party data). What changed is that 5 of the 6 gym-city areas lost the *area
tag* for that gym leader's post-Elite-Four rematch variant (the base, first-visit
fight for the same leader is still tagged and still shows). This falls out of the
generator's "one unassigned trainer id per name, claimed in Trainer-Order-sheet row
order" matching (`gen_rr_priority_trainers.py` §6, "(b) Nuzlocke Redux" / "(c)
Trainer Order") -- it is order/row-count sensitive, and today's sheet edit shifted
enough rows that these five rematch-name claims no longer land. This is a sheet-driven
side effect, not something either the vermilion fix or this regen touched directly
(reproduces identically with or without the `_AREA_OVERRIDES` fix above). Flagged
as a separate finding below rather than patched here -- no owner ruling covers
redesigning that matching, and it's a cosmetic widget gap (both areas still show
that leader), not a data-correctness issue.

## Other finding from RR-PT — fixed by card RR-PT2 (2026-09-27)

`_KNOWN_UNRESOLVABLE_AREA_KEYS` (added by card RR-PT, removed by RR-PT2) documented 11
**pre-existing** `trainers_by_area` keys that don't match either `area_map.json` or
`gen3_frlge_locations.lua`: `celadon_hotel`, `cinnabar_gym`, `cinnabar_isl`,
`dig_house`, `joyful`, `mansion_f4`, `nugget_bridge`, `pewter_museum`,
`rocket_hideout`, `ss_anne`, `treasure_bea`. See the addendum below for how each was
resolved and the current (post-RR-PT2) state of the roster.

---

# Addendum — card RR-PT2 (2026-09-27): making the 11 dead keys reachable

## The mechanism (why a bare building name is never client-emittable)

`lua/gen3/client.lua`'s `area_now()` reports `area_map[bank:num] or ""` for the coarse
`area_id` (from `data/games/gen3_frlge/area_map.json`) and `locations[bank:num] or ""`
for the fine `loc_name` (from `gen3_frlge_locations.lua`, DISPLAY-only per that file's
own header comment). `server.py`'s handlers make `player_area_id` **sticky**: the
`hello`/`area_enter` handlers only overwrite it when the wire message's `area_id` is
non-empty (`if area: self.player_area_id[player_id] = area`). So while a player stands
in a building with no `area_map.json` entry of its own (a gym, a hideout floor, a
hotel, a museum), `player_area_id` keeps whatever coarse area the player last walked
in **from** — and `_trainer_panel_html`'s effective area
(`player_area_id.get(pid) or player_area.get(pid)`, `server.py`) resolves to that
sticky coarse value, never the fine per-room name. This is exactly the rule
`tools/gen_gen3_trainers.py`'s `area_of_map()` already encodes for vanilla FR/LG
(BFS over `area_map.json` + pret's map warps/connections to the nearest mapped
ancestor; see that generator's module docstring) — vanilla Brock, standing in
`PewterCity_Gym` (no `area_map.json` entry), is tagged `pewter_city` for the same
reason.

## Per-dead-key mapping (fix landed in `tools/gen_rr_priority_trainers.py`'s
`_AREA_OVERRIDES`)

Verified against the pinned pret pokefirered clone
(`data/gen3_sources.lock.json` commit `c75f352304d529f6ba92d4f74b9cf8b5c3810788`,
`E:/Google Drive/SLink/.cache/pret/pokefirered`, confirmed at that exact commit)
by running the real `area_of_map()`/`map_jsons()`/`map_keys()` helpers against every
map involved — not by inspection.

| Dead key (sheet text) | Real map(s) | `area_of_map()` result | Reachable area now |
|---|---|---|---|
| `celadon_hotel` ("CELADON HOTEL"/"CELADON CITY HOTEL") | `CeladonCity_Hotel` | 1 hop to `MAP_CELADON_CITY` | `celadon_city` |
| `cinnabar_gym` ("CINNABAR GYM") | `CinnabarIsland_Gym` | 1 hop to `MAP_CINNABAR_ISLAND` | `cinnabar_island` |
| `cinnabar_isl` ("CINNABAR ISL.") | `CinnabarIsland` itself | direct `area_map.json["3:8"]` hit, no BFS needed | `cinnabar_island` (already existed; just a truncated-spelling miss) |
| `dig_house` ("DIG HOUSE") | `DiglettsCave_NorthEntrance`/`_SouthEntrance` | direct `area_map.json["1:36"/"1:38"]` hit | `digletts_cave` (community name for the cave's entrance building; sheet position — right after Cerulean/Misty, right before S.S. Anne — and level_cap 27 both fit the Diglett's Cave detour) |
| `joyful` ("JOYFUL" 4-line header) | `TwoIsland_JoyfulGameCorner` | 1 hop to `MAP_TWO_ISLAND` | `two_island` |
| `mansion_f4` ("MANSION F4"/"POKEMON MANSION 4F") | one of `PokemonMansion_1F/2F/3F/B1F` (vanilla has only 4 floors; whichever RR numbers "4F", all four already share one id) | direct `area_map.json` hit on every floor | `pokemon_mansion` |
| `nugget_bridge` ("NUGGET BRIDGE"/"NUGG. BRIDGE") | `Route24` (pret has no separate map for the bridge segment — it's part of the one Route 24 map) | direct `area_map.json["3:43"]` hit | `route_24` |
| `pewter_museum` ("PEWTER MUSEUM") | `PewterCity_Museum_1F`/`_2F` | 1 hop to `MAP_PEWTER_CITY` | `pewter_city` (same bucket as Brock's gym — both report the town while inside) |
| `rocket_hideout` ("ROCKET HIDE."/"ROCKET HIDE"/"ROCKET HIDEOUT") | `RocketHideout_B1F..B4F` | 2 hops (hideout floor → `CeladonCity_GameCorner`, itself unmapped → `MAP_CELADON_CITY`) | `celadon_city` |
| `ss_anne` ("S.S. ANNE") | every `SSAnne_*` map (26 rooms) | 1 hop to `MAP_VERMILION_CITY` | `vermilion_city` |
| `treasure_bea` ("TREASURE BEA.") | `OneIsland_TreasureBeach` | direct `area_map.json["3:46"]` hit | `treasure_beach` (already existed; just a truncated-spelling miss, same class of bug as `vermilion_city`/`vermillion_city`) |

All 11 keys are gone from `trainers_by_area` after the regen; their trainers now live
under the real reachable buckets above (e.g. `rocket_hideout`'s `[69, 350, 385, 538]`
moved into `celadon_city`, which already had Erika's `417`).

**Related finding, not changed by this card:** `celadon_city_game_corner` (Grunt id
`382`) is subject to the exact same sticky-coarse mechanism — the Game Corner has no
`area_map.json` entry either, so by the same rule it should also report `celadon_city`
while the player stands there, not its own fine name. It currently "passes" the
client-emittable test only because it happens to string-match
`gen3_frlge_locations.lua`'s fine per-room table, but per the mechanism above that
fine name is not what `player_area_id` actually holds except in the narrow edge case
of a hello arriving before any coarse `area_enter` has ever fired this session (e.g.
a save file that boots directly inside that room). Not one of the 11 keys card RR-PT
flagged, and not touched here — flagging for an owner ruling on whether to fold it
into `celadon_city` too, consistent with `rocket_hideout` above.

## Rematch-tag fix (item 2)

Root cause: `trainers_by_area` assignment step (c) ("Trainer Order — same
one-unassigned-rt_id-per-name rule") claims **one** unassigned same-named `rt_id` per
`Trainer Order` sheet row. That sheet is a single first-playthrough-progression pass
with exactly one row per gym leader name — it never lists a post-Elite-Four rematch
tier — so the rematch copy (sourced from the separate "Kanto Rematch"/"Postgame"
sheets, itself carrying no location header) was left permanently unassigned. (The
generator's optional `redux_page.html` input, referenced in a code comment as a
second source for exactly this kind of hint, isn't a tracked/pinned file and isn't
present in this worktree, so it can't be relied on to supply it either.)

Fix: a new step (d) in `tools/gen_rr_priority_trainers.py` (`build()`, after step (c))
gathers every already-assigned `class == "Gym Leader"` trainer's area by name, then
attaches any still-unassigned `Gym Leader` with the same name to that same area.
Scoped strictly to class `"Gym Leader"` — a name-only match across all classes would
be wrong for names reused across many unrelated fights (`"Grunt"`, `"Rival"`).

Restored exactly the 5 areas card RR-PT's diff table flagged:

| Area | Base id | Rematch id(s) |
|---|---|---|
| `pewter_city` | 414 (Brock) | 56 |
| `cerulean_city` | 415 (Misty) | 48, 32 |
| `vermilion_city` | 416 (Lt. Surge) | 51 |
| `celadon_city` | 417 (Erika) | 65 |
| `viridian_city` | 74 (Clair) | 38 |

## Key-fight coverage confirmation (item 3)

Every key-fight category has at least one reachable `rt_id`:

- **Gym leaders + rematches**: all 8 Kanto leaders + the 3 Johto/RR-crossover leaders
  (Falkner, Chuck, Whitney/Morty/Jasmine ×3/Pryce — several already had their own
  header area) are reachable; the 5 rematch tiers above are now reachable alongside
  their base fight.
- **Rival**: 12 of 18 `Rival`/`*Rival`-class ids are reachable (the rest are
  calc-only alternate-moveset duplicates of an already-reachable route battle).
- **Elite Four / Champion**: the base Elite Four fights (Lorelei/Bruno/Agatha/Lance,
  ids `77/80/83/86`) are reachable at `indigo_plateau`; the Champion fight is
  reachable via its `"Rival"`-named `Champion`-class ids (`435/436/437`) at
  `cerulean_city`. (The `*Elite Four` post-game alt-set ids and the vanilla-rival-named
  `Champion`/`Rival`-class ids for "Blue"/"Lance" are calc-only duplicates with no
  sheet location at all — same "duplicate set, not a separate encounter" shape as the
  Rival case above, not something this card's area-mapping fix reaches.)
- **Giovanni's sets**: reachable at `rocket_hideout`'s new home `celadon_city`
  (ids `69`, `350`), `silph_co` (id `348`), and `cerulean_cave` (id `349`).

New regression tests (`tests/unit/test_gen3_rr_generators.py`):
`test_priority_trainers_key_fight_families_have_reachable_area` (per-family floor —
gym leaders, rival, Elite Four, Champion, Giovanni's sets each need >=1 reachable id)
and `test_priority_trainers_gym_leader_rematches_inherit_base_area` (pins the exact
5-area table above). `test_priority_trainers_areas_are_client_emittable`'s
`_KNOWN_UNRESOLVABLE_AREA_KEYS` allowlist is removed entirely (no exceptions remain).
`tests/unit/test_trainer_panel.py`'s `pewter_museum`-specific test is renamed/rewritten
to `test_trainers_for_area_pewter_city_has_falkner`, since Falkner now (correctly)
answers under `pewter_city`, and it also asserts `pewter_museum` itself returns `[]`.

## Exit checks

```
SLINK_RR_SRC_CACHE=data/.rr_src_cache python tools/gen_rr_priority_trainers.py --check
OK: regenerated roster matches ... byte-for-byte (443 trainers)

SLINK_RR_SRC_CACHE=data/.rr_src_cache python -m pytest tests/unit/test_gen3_rr_generators.py -q
30 passed

python -m pytest tests/unit/test_trainer_panel.py -q
14 passed
```

Full suite: see the run this receipt accompanies.
