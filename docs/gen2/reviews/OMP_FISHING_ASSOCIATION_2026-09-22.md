# Fishing map association: source rule (OMP Gen2-Base, cx-1518cecd, 2026-09-22)

Resolves the source side of the OPEN obligation `fishing_map_association`
(`server/adapters/gen2_rom_scan.py` OPEN_OBLIGATIONS; review finding F3 in
`P3_GEN2_BINDERS_REVIEW_2026-09-22.md`). SOURCE only: no ROM, no emulator. Coordinator
spot-checked F1 and the Cerulean Gym bug against the pinned clones.
Pins: pokecrystal 7a7881d0 (C), pokegold 656583c9 (G, Gold and Silver).

## Findings

- **F1 Rod gate (both titles, same code).** Item effect -> UseRod -> FishFunction
  (C `engine/items/item_effects.asm:2268-2281`, G `:2252-2265`; FishFunction C
  `engine/events/overworld.asm:1423-1483`, G `:1400-1457`). Three checks, in order:
  (a) not surfing (`wPlayerState` PLAYER_SURF/PLAYER_SURF_PIKA fail, C `:1446-1449`, G `:1423-1426`);
  (b) the FACED tile: GetFacingTileCoord -> GetTilePermission must equal WATER_TILE ($01)
  (C `:1451-1454`, G `:1428-1431`; low nybble of CollisionPermissionTable, C
  `home/map_objects.asm:88-108`). No `CheckWaterTile` exists in either repo;
  (c) GetFishingGroup = MAP_FISHGROUP of the current map (C `home/map.asm:2265-2277`, G
  `:2616-2628`); 0 exits with "no fish" (C overworld.asm `:1460-1463`, G `:1436-1440`).
- **F2 Water collisions the check accepts:** every COLL_* whose permission low nybble is 1:
  $20-$22, $24-$26, $28-$2a, $2c-$2e, $30-$3f, $c0-$cf (`data/collision/collision_permissions.asm`).
  COLL_ICE ($23/$2b) is land, COLL_BUOY ($27/$2f) is wall. Metatile id 0 short-circuits to
  $ff (`home/map.asm:1713-1716`): treat block byte 0 as wall.
- **F3 Bite and species selection** happen after the gate and never gate reachability
  (`engine/events/fish.asm:24-90`, identical in both repos; time-of-day only picks species).
- **F4 Swarms are runtime and differ by title.** C checks DAILYFLAGS1_FISH_SWARM_F and only
  Qwilfish is wired (Ralph, `engine/phone/scripts/ralph.asm:48-56`); no Crystal map uses
  FISHGROUP_REMORAID, so that branch is dead in Crystal. G has no daily gate in fish.asm
  (`:92-119`) and wires Remoraid (Route44 FISHGROUP_REMORAID, `data/maps/maps.asm:73`; Wilton,
  `engine/phone/scripts/trainers.asm:592-601`). Lake of Rage is FISHGROUP_GYARADOS
  (C `maps.asm:250`, G `:242`); the red Gyarados is a scripted static
  (`maps/LakeOfRage.asm:87-89`), not a rod outcome.
- **F5 Association is the current map header only.** No parent/outdoor inheritance; one
  GetFishingGroup call site per title. Indoor maps carry their own group.
- **F6 Reachability rule for a generator.** Per 16x16 quadrant:
  collision = tilecoll[metatile(x>>1,y>>1)][(x&1)+2*(y&1)], permission = table[collision] & $f
  (C `home/map.asm:1711-1740`, G `:2064-2093`; quadrant order TL,TR,BL,BR).
  A map's rod rows are reachable iff fishing_group != 0 AND some water quadrant has a
  4-neighbour quadrant that is standable (permission low nybble 0 and collision high nybble
  not $a0 ledges, $b0 side walls, $c0 side buoys, $60 pits; GetMovementPermissions
  C `home/map.asm:1591-1650`). "Contains a water metatile" alone over-reports: Route16,
  Route18 (C and G) and Gold NationalPark, NationalParkBugContest, Route4 have only walled water.
  Files: `constants/map_constants.asm`, `data/maps/maps.asm`, `data/maps/blocks.asm` (stacked
  labels share blockdata), `maps/*.blk`, `gfx/tilesets.asm` (collision label aliases, e.g. Gold
  DarkCave -> cave_collision, `:106-108`), `data/tilesets/*_collision.asm`,
  `data/collision/collision_permissions.asm`, `constants/collision_constants.asm`.
  OMP scan (do not hard-code; regenerate): C 388 maps, 62 reachable; G 368 maps, 64 reachable.
- **F7 Spot checks.** NewBarkTown (OCEAN) fishable; ElmsLab and PlayersHouse1F (SHORE) have no
  water, not fishable; Route32 (QWILFISH) fishable; UnionCave1F (LAKE, indoor) fishable, so
  "indoor means no fishing" is WRONG. CeruleanGym is FISHGROUP_NONE in C (`maps.asm:218`) but
  FISHGROUP_SHORE in G (`:210`), a documented pret bug (`pokegold docs/bugs_and_glitches.md:119`):
  Gold/Silver rod rows there are real and reachable.
- **F8 Impact on the Crystal pack today:** 96 of 97 area_ids emit rod rows; 46 have no
  fishable member map and 34 are partial. The loop is `server/adapters/gen2_gsc.py:372-392`
  (`map_association="UNQUALIFIED"` at `:392`).

## Unverified

- U1 Connection strips: edge water may be fished from a neighbouring map's strip; resolving it
  needs `data/maps/attributes.asm` connection offsets plus the neighbour's blocks.
- U2 Story-time blockdata changes (Radio Tower, Ruins puzzles) are not modelled.
- U3 Source only; no ROM or emulator check.

## Disposition (coordinator)

Accepted. Next card: generate a per-map `fishing_water` boolean with the F6 adjacency rule
(plus U1 if cheap) in the Gen 2 generators, gate rod rows on it in the adapter, keep swarm rows
as runtime. `fishing_map_association` stays OPEN until a fixture actually fishes.
