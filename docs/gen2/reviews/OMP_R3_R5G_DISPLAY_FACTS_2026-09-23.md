# R-3 / R-5g GAME-oracle display facts (OMP Gen2-Base card gen2-O5, cx-c3c976ec, 2026-09-23)

READ-ONLY source card; recorded by the coordinator. Pinned clones `.cache/gen2-build/pokecrystal` (7a7881d)
and `.cache/gen2-build/pokegold` (656583c). Input for a future card that closes R-3/R-5g in
`lua/tests/gen2_inspect_gate.lua` + `tests/live/test_gen2_new_gates.py` with a byte oracle over the game's
own `wTilemap`. Screenshots are not an oracle.

## Tilemap-resident targets (C and G/S coordinates identical)

| Target | Screen / path | hlcoord | Bytes | Cites |
|---|---|---|---|---|
| Player ID (5 digits, leading zeros, `wPlayerID`) | Trainer Card page 1: START -> Status (`StartMenu_Status` -> `farcall TrainerCard`) | (5,4) | digits `$F6`-`$FF` | C `engine/menus/trainer_card.asm:228-240`, `engine/menus/start_menu.asm:450-458`; G `trainer_card.asm:230-240` |
| Player name | Trainer Card page 1 | (7,2) | charmap | same |
| Gender symbol | Stats screen (party -> mon -> STATS), any page | (18,0) | ♂ `$EF`, ♀ `$F5` | C `engine/pokemon/stats_screen.asm:443-445,474-486`; G `:307` |
| Shiny marker (drawn in all three titles) | Stats screen | (19,0) | `⁂` `$3F` (stats tileset tile 14) | C `stats_screen.asm:522-526`, `constants/charmap.asm:97`; G `:545-549` |
| Held item name | Stats screen GREEN page (`.Item` label at (0,8)) | (8,8) | item name | C `stats_screen.asm:726-733`; G `:567-577` |

Charmap values are from Crystal `constants/charmap.asm:193,199,201-210`. **Gold/Silver charmap values are
UNVERIFIED**: re-read `pokegold/constants/charmap.asm` before comparing a Gold/Silver fixture.

Frame-stable read sites: the per-page joypad states `TrainerCard_Page1_Joypad`/`Page2`/`Page3`
(C `trainer_card.asm:118,157,205`) and `MonStatsJoypad` (C `stats_screen.asm:117,120`). The tilemap is
written in the preceding `_LoadGFX` state and stays up while the joypad state waits.

## Not tilemap targets

- **Badges** (Johto page 2, Kanto page 3) are VRAM tiles animated as OAM (`BadgeGFX`/`BadgeGFX2`,
  `TrainerCard_JohtoBadgesOAM`, C `trainer_card.asm:149-158,197-207`). A `wTilemap` oracle cannot see them:
  the badge half of R-3 needs an OAM/VRAM witness or stays out of scope.
- **PC box header:** Elm's lab has no PC (bg_events: healing machine, bookshelves, travel tips;
  C `maps/ElmsLab.asm:1388-1399`). Unreachable from the town and Route 29 fixtures.
- Party-menu item line: UNVERIFIED (not found); the verified item display is the stats GREEN page.

Coordinator status: accepted 4 targets, 2 corrections (badges, box header). R-3/R-5g stay OPEN until the
oracle card lands.
