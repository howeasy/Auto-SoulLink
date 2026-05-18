# Gen 2 Game Data (Gold/Silver/Crystal)

Data files for Gen 2 Pokémon games (Game Boy Color).

## Status: Implemented (Crystal)

## Data Files

- `area_map.json` — Route/city → area_id mapping (124 entries)
- `species_types.json` — Species type data (251 species)
- `gender_ratios.json` — Species gender ratio data
- `item_names.json` — Item ID → name mapping

## Notes

- Mon identity: DVs + OT ID. Shiny determined by DVs (Atk DV = 2/3/6/7/10/11/14/15, others = 10).
- Gender: Determined by Atk DV vs species threshold.
- Platform: Game Boy Color (Gambatte core in BizHawk).
- Memory map: Well-documented via pret/pokecrystal decomp.
- Crystal only — Gold/Silver can be added later as variant profiles in `gen2_crystal.lua`.

## Phase 1 (gen1-gen2-parity branch) — egg-gift classification

Eggs in Gen 2 are flagged with `species == 0xFD` (constant `EGG` in
pret/pokecrystal). The Crystal Lua client reads the party species byte and
forwards `is_egg=true` on capture events. The server's existing
`_is_gift_capture(area_id, is_egg)` then routes:

- **Mystery Egg from Mr. Pokemon** (received in his house, joins party on
  Route 30 or wherever the player is at hatch time): `is_egg=True` +
  non-daycare area → treated as gift. Bypasses Pokéball gate, skips
  quarantine.
- **Daycare-bred egg / Odd Egg** (received from the Day-Care Man on
  Route 34): `is_egg=True` + daycare area (`route_34`) → normal capture
  flow. Player must have Pokéballs; the egg gets quarantined to the box
  until linked with the partner.
- **Wild capture on Route 34 grass**: `is_egg=False`, `is_gift_area=False`
  → normal capture flow (this corrects a pre-Phase-1 bug where Route 34
  was in `_GIFT_AREAS` and *every* capture there was misclassified as a
  gift).

## Phase 1 — memorialize routing

The Crystal client now routes `memorialize` to `M.depositMemorialMon`,
which writes dead pairs to Box 14 (the dedicated graveyard box at SRAM
offset 0x79E0). Previously it used `depositPartyMon`, which placed dead
mons in the *current* PC box and made the graveyard hard to find.

## Phase 0 audit — address verification pending

The 4 `TODO: verify` addresses in `lua/games/gen2_crystal.lua`
(enemy_count, enemy_base, enemy_species_list, battle_flag) — plus every
other address in the profile — have a diagnostic Lua probe at
`lua/tests/test_gen2_profile_audit.lua`. See
[`tests/phase0_address_audit.md`](../../../tests/phase0_address_audit.md)
for the audit doc and
[`tests/PHASE9_BATCH.md`](../../../tests/PHASE9_BATCH.md) for the live
verification checklist.
