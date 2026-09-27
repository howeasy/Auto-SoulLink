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

## Other finding (not fixed here, flagged for follow-up)

`_KNOWN_UNRESOLVABLE_AREA_KEYS` in the new test documents 11 **pre-existing**
`trainers_by_area` keys that were already present before this card and don't match
either `area_map.json` or `gen3_frlge_locations.lua`: `celadon_hotel`, `cinnabar_gym`,
`cinnabar_isl`, `dig_house`, `joyful`, `mansion_f4`, `nugget_bridge`, `pewter_museum`,
`rocket_hideout`, `ss_anne`, `treasure_bea` (the last is also a truncated spelling of
`treasure_beach`, an id that DOES exist in `area_map.json`). Indoor areas only ever
report the *fine* per-room id from `gen3_frlge_locations.lua` (e.g.
`rocket_hideout_b1f`), never the bare building name, so these areas' Upcoming Key
Trainers widgets can never fire. Out of scope for RR-PT (regen + one spelling fix);
worth its own card since it spans 11 areas and needs a matching-design decision
(which room id per building, or a client-side prefix-collapse), not a one-line
override.

## Exit checks

```
SLINK_RR_SRC_CACHE=data/.rr_src_cache python -m pytest tests/unit/test_gen3_rr_generators.py -q
28 passed
```

Full suite: see the run this receipt accompanies.
