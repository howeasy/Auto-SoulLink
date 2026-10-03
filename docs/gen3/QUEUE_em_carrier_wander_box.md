# QUEUE: Emerald trade-NPC wander box covers the only approach to the Center PC

Status: **needs-triage**. Opened 2026-10-03 from the final-cut row `frlgc_whiteout_gen3_em_as_a_companion` (cut b6cd75c6).

## What happened

`python tools/e2e_duo.py --game gen3_emerald --scenario whiteout_gen3 --gen3-companion` failed with
`step Up stalled at (10,4)` (receipt `docs/gen3/probes/fc_frlgc_whiteout_gen3_em_as_a_companion_b6cd75c6.txt`).
The companion's Center trade NPC (the "carrier") stood on (10,3). The harness recovery tapped A at it,
the server logged `trade_request -> action menu (Trade/Say hey)`, and the field stayed locked. The same
walk passed in the same session on `boxsync_gen3` (`fc_frlgc_boxsync_gen3_em_as_a_companion_b6cd75c6.txt`),
and the clean-Emerald whiteout rows (10 receipts, `fc_whiteout_gen3_em_as_a_*.txt`) have no NPC.

The retained logs cannot show the NPC's object-event position (the a-client log carries no
object-event line and `gen3_stuck.png` is a 242-byte stub), so "NPC on (10,3)" is inferred from the
geometry, the facing requirement of `slink_carrier_interaction`, and the `trade_request` log line.

Harness side is fixed in this worktree: `lua/tests/em_carrier_walk.lua` (waits, never presses A, backs
a menu out with B, fails by name). That only makes the test robust. It does not change what a player meets.

## The product question (owner decision)

The carrier spawns at `SLINK_TARGET_CARRIER_X/Y` (`patch/src/trade_targets/emerald.h:147-148`, 0x11,0xb,
which is map tile (10,4) after the -7 object-event offset), movement type 2 (wander,
`emerald.h:145`), range byte set to 0x11 in `patch/src/trade_targets/native_carrier.h:~165`, so it roams
x 9..11, y 3..5.

In Emerald's Pokemon Center layout the PC is at (10,1) and its only approach tile is (10,2), reached
only through (10,3). From the decomp (`data/layouts/PokemonCenter_1F/map.bin`, map.json object events, BFS
over collision plus static NPC tiles), the wander box is a cut point of the door-to-PC route: **no
route from the door to the PC avoids it**. So the NPC can stand in a real player's way and, until it
wanders off, block the PC. Pressing A at it opens its Trade menu, so a player can also hit it by accident.

FR/LG are off-route: the spawn is (10,9) minus 7 = (3,2) (`firered.h:139-140`, `leafgreen.h:133-134`),
box x 2..4, y 1..3, and the Viridian door-to-PC route (`(6,8)` ... `(11,4)`, `(11,3)`, `(11,2)`) never touches
it (checked the same way against pokefirered).

Decision needed: accept the occasional block (the NPC wanders off in a few seconds), or move the Emerald
spawn/box (for example a spawn and range that leave (10,3) and the row y=3..4 corridor clear). Moving
it means a `patch/` rebuild, new pins/hashes for the Emerald companion, and a re-cut of every Emerald
companion row. Not done here; `patch/` is untouched.

## Every Emerald target Center (`slink_target_pokecenters`, `emerald.h:175`)

Key = (map group << 8 | map num). All use the spawn (10,4). "Box on route" = the shortest door-to-PC
route enters x 9..11, y 3..5; "cut" = no route avoids the box. Door = warp (7,8); PC = (10,1), approach (10,2)
in every one.

| key | map | layout | box on route | cut |
|---|---|---|---|---|
| 0x202 | OldaleTown_PokemonCenter_1F | POKEMON_CENTER_1F | yes (10,4),(10,3) | yes |
| 0x301 | DewfordTown_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0x405 | LavaridgeTown_PokemonCenter_1F | LAVARIDGE_TOWN_POKEMON_CENTER_1F | yes | yes |
| 0x504 | FallarborTown_PokemonCenter_1F | POKEMON_CENTER_1F | n/a: a static NPC stands on the approach tile (10,2), so the PC is not reachable from the floor at all (unrelated to the carrier) | n/a |
| 0x604 | VerdanturfTown_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0x700 | PacifidlogTown_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0x804 | PetalburgCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0x90b | SlateportCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0xa05 | MauvilleCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0xb05 | RustboroCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0xc02 | FortreeCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0xd06 | LilycoveCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0xe03 | MossdeepCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes (route via (9,5),(9,4)) | yes |
| 0xf02 | SootopolisCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |
| 0x100c | EverGrandeCity_PokemonCenter_1F | POKEMON_CENTER_1F | yes (route via (10,5),(10,4)) | yes |
| 0x1a35 | BattleFrontier_PokemonCenter_1F | POKEMON_CENTER_1F | yes | yes |

Method (reproducible, read-only): for each key resolve the map name from `data/maps/map_groups.json`,
read its map.json warps and object events, read the layout's `map.bin` collision bits, find the PC as
the metatile with behaviour 0x83 (primary/secondary `metatile_attributes.bin`), BFS from the first warp
over collision-free tiles minus object-event tiles, with and without the box tiles removed. Lavaridge uses its own
layout (same PC and approach tiles). The spawn tile (10,4) is in-map, collision-free and unoccupied in all 16.

## Evidence

- Failing receipt: `docs/gen3/probes/fc_frlgc_whiteout_gen3_em_as_a_companion_b6cd75c6.txt`
- Server line: `trade_request -> action menu (Trade/Say hey)` in `F:/slink-work/tmp/duo_b1omq4p5/slink.log` (04:26:17.843, 0.84 s after `area_enter oldale_town_pokemon_center_1f`)
- Carrier code: `patch/src/trade_targets/native_carrier.h` (`nc_drive_npc`, interaction call)
- Spawn constants: `patch/src/trade_targets/emerald.h:144-148`; FR/LG `firered.h:136-140`, `leafgreen.h:130-134`
- Walk path and fix: `lua/tests/gen3_scripted_play.lua` `PATHS.em_oldale_center_to_pc`; `lua/tests/em_carrier_walk.lua`; `lua/tests/duo/duo_gen3_main.lua` `em_center_walk`
- Tests: `tests/unit/test_gen3_em_carrier_wait.py`
