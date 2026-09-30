# XG3 gift, egg and scripted-static SOURCE census (2026-09-29)

This card adds `expansion_gifts.json` for the unrouted `gen3_exp` build `28877d73`. It is a declaration census, not a checkpoint gift-area list or a live observer qualification. `write_checkpoint.json` still has `gift_areas: []` and the open XG3 entry; no routing changes were made.

## Pin and method

- Integration starting HEAD: `6815908c9a514d7e509a8ed1f7ee443504c09f59`. The read-only `.cache/expansion-src` junction's Git HEAD is `e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7` (expansion/1.17.0). The generator refuses another source commit. It also uses the existing trainer generator's area-map digest check against `gen3_exp_areas.lua`; source map-group order and the existing `area_map.json` must agree before producing areas.
- `asm/macros/event.inc:1068-1102` makes `givemon` a `ScrCmd_createmon` player-party grant; `:1133-1167` makes `createmon` choose player or opponent from its first argument (zero concrete script declarations in this source); `:1198-1202` makes `giveegg` the `SCR_OP_GIVEEGG` command. `src/script_pokemon_util.c:368-468` and `src/scrcmd.c:2272-2278` establish the native grant endpoints. The generator scans concrete declarations, not macro definitions or API function definitions.
- For scripted static encounters it records `setwildbattle` declarations. It does not turn these into gifts: they are battles that may result in a capture. Other scripted or runtime wild battles need their own coverage audit.
- `data/event_scripts.s:603-1050` wraps FRLG map scripts in `.if IS_FRLG`; this reference is `GAME_VERSION=EMERALD`, so those declarations are retained as `excluded` with the branch reason. `data/event_scripts.s:1059` includes `data/scripts/debug.inc`, but the reference has `DEBUG=0` and disabled debug menu (`include/config/debug.h:5`); those declarations and `src/debug.c`'s native grant calls are retained as excluded debug actions. `data/mystery_gift.s:20` includes `gift_pichu.inc` as a separately delivered mystery-gift payload, retained as excluded from ordinary map script reachability.
- Map ids come from `data/maps/map_groups.json` through the existing `map_keys` helper. Own map or nearest connected area comes from the existing `area_of_map` BFS and `area_map.json`. Every active map declaration keeps `map_group_num`; unmapped locations have a named `unresolved_area`. `enum_values` resolves constant species IDs; `starterMon` and other expressions stay literal with `species_resolution: runtime expression`. No interior area id is invented.

## Output and limits

The 61 ordered rows comprise 58 script declarations and 3 direct native call sites. By status and kind: active gift 8, egg 1, static 14; excluded gift 25, egg 3, static 10. Examples include Beldum at `data/maps/MossdeepCity_StevensHouse/scripts.inc:86`, Wynaut egg at `data/maps/LavaridgeTown/scripts.inc:245`, Regirock static encounter at `data/maps/DesertRuins/scripts.inc:64`, and runtime starter grant at `src/battle_setup.c:1009`. The FRLG Game Corner's `VAR_TEMP_1` rows are retained, excluded, and unresolved by species expression.

Four active rows have no single resolved area: Kyogre at `data/maps/MarineCave_End/scripts.inc:36` and Groudon at `data/maps/TerraCave_End/scripts.inc:36` have no connected mapped area in this area graph; shared `data/scripts/kecleon.inc:74` is called from multiple maps and needs per-caller expansion; `src/battle_setup.c:1009` chooses a starter at runtime outside a single map script. The mystery-gift Pichu egg is kept as an external payload, not assigned a map. The direct native scan found the starter caller and two disabled debug callers; this is not proof that every acquisition route is covered. Capture, daycare, battle rewards, and other script/native paths must be classified before declaring the list complete.

## Verification and next action

The first new missing-census test failed RED with `FileNotFoundError` for `expansion_gifts.json`. After generating the pack it passed with the parity test (`2 passed in 0.70s`). The generator's `--check` compares the artifact byte for byte against the pinned source. No emulator, new build, full suite, or live claim was made.

Next: independently review source reachability, expand shared Kecleon caller maps, resolve the two cave maps without inventing areas, and decide which gifts/eggs belong in checkpoint `gift_areas`. Only then add checkpoint consumption in its own scoped card and obtain PHYSICAL observer receipts for representative gifts, eggs, and statics.
