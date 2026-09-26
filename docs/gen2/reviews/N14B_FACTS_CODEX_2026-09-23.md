# N14b source facts: strict re-save oracle rules (Codex Gen2-Part2, 2026-09-23)

Card `gen2-N14b-facts` (read-only; delivered in the Codex transcript because its approval review blocked the
Magi handoff; copied here verbatim in substance by the coordinator). Answers R6 rows #3 and S1
(`R6_R4FIXES_REVIEW_2026-09-22.md`) for `tools/gen2_fixtures.py` (`RESAVE_RULED_WRAM`, the rule loop, the
map-object spans). Pinned clones: Crystal `7a7881d0`, Gold/Silver `656583c9` (`.cache/gen2-build`, NOT
`.cache/pret`). Addresses from `data/gen2/{pokecrystal,pokegold,pokesilver}.sym`. `C`/`G` = those clones.
SOURCE only; implementation card N14b is still to do, then re-qualify all eight fixtures.

## Rules

| Rule | Crystal | Gold/Silver | Required transition |
|---|---|---|---|
| S1a timer | `wGameTimerPaused` `00:CFBC` | `01:D8B8` | CONTINUE sets counting bit 0 in all titles; Crystal also clears mobile bit 7 (C `engine/menus/intro_menu.asm:459-469`; G `:343-349`). **Crystal's byte is outside saved player data**: no SRAM delta rule. Gold/Silver save it: `after = before \| 0x01`, other bits preserved (C `engine/menus/save.asm:498-508`; G `:396-406`). |
| S1b daily timer | `wDailyResetTimer` `01:DC1C-DC1D`; `wCurDay` `01:D4CB` | `01:D966-D967`; `wCurDay` `01:D1F2` | Valid 0-139 day stamps; `d = (current day - old stamp) mod 140`. Each check stamps the current day. If `old count > d`: new count `old count - d`; else reset fires and count becomes 1 (C `engine/overworld/time.asm:61-81,99-106,288-309,399-408`; G `:47-67,85-92,243-264,354-363`). |
| S1b daily flags | `01:DC1E-DC21` and `01:DC4C-DC57` | `01:D968-D969` | If reset fires, **every byte in each span becomes zero**; otherwise unchanged. Crystal's spans include daily, swarm and rematch/phone flag arrays. Crystal `wKenjiBreakTimer` first byte `01:DC58` separately decrements if >= 2, or is resampled to 3-6; second byte unchanged (C `engine/overworld/time.asm:103-142`; G `:89-97`). |
| S1c roamer history | `wRoamMons_CurMapNumber`..`LastMapGroup` `01:DFE4-DFE7` | `01:DD2F-DD32` | Every successful CONTINUE calls `JumpRoamMons` -> `_BackUpMapIndices`: `[cur num, cur grp, last num, last grp]` becomes `[wMapNumber, wMapGroup, old cur num, old cur grp]`, even with no active roamer (C `engine/menus/intro_menu.asm:372`, `engine/overworld/wildmons.asm:672-703,743-752`; G `:283`, `:677-708,748-757`). An unchanged but stale value must not bypass this. |
| #3a player map-object Y/X | `01:D720/D721`; saved `wYCoord/wXCoord` `01:DCB7/DCB8` | `01:D447/D448`; saved `01:DA02/DA03` | `RefreshPlayerCoords` derives `(saved Y/X + 4) & 0xFF` (C `engine/overworld/player_object.asm:102-123`; G `:87-108`), but **ordinary CONTINUE does not call it**: it loads saved objects via `LoadMapAttributes_SkipObjects` (C `data/maps/setup_scripts.asm:164-182`, `home/map.asm:385-417`; G `:161-179`, `:754-786`). For a no-movement re-save compare map-object Y/X byte-for-byte; later movement/warps need their own witness. |
| #3b NPC struct IDs | map objects 1-15 `01:D72E..D80E`, stride `0x10` | objects 2-15 `01:D465..D535`, stride `0x10`; object 1 reserved at `01:D455` | CONTINUE copies saved IDs and skips object init: preserve them unless a visibility/deletion event is witnessed. On init visible NPCs get IDs 1-12, unseen/deleted `$FF` (C `home/map.asm:568-634`, `engine/overworld/player_object.asm:227-283`; G `:937-1005`, `:223-279`; `constants/map_object_constants.asm:38`). G/S skip object 1 at init: preserve its saved byte without imposing that value set. |

The daily check runs only when overworld event processing reaches `CheckTimeEvents` with `wLinkMode = 0` and
`wStatusFlags2` bug-contest timer bit 2 clear (C `engine/overworld/events.asm:449-465`; G `:436-453`; status
bytes C `01:D84D`, G/S `01:D572`). The oracle must establish that path before requiring the reset transition.

## Fresh-fixture input guards (refuse unsupported input instead of passing it)

| Guard | Crystal | Gold/Silver | Source reason |
|---|---|---|---|
| No released roamers | species `01:DFCF/DFD6/DFDD` = 0; groups `01:DFD1/DFD8/DFDF` and numbers `01:DFD2/DFD9/DFE0` = `$FF` | species `01:DD1A/DD21/DD28` = 0; groups `01:DD1C/DD23/DD2A`, numbers `01:DD1D/DD24/DD2B` = `$FF` | New game initializes them so (C `engine/menus/intro_menu.asm:163-173`; G `:78-88`). `GROUP_N_A = -1` makes `JumpRoamMons` skip movement, not history backup (`constants/map_data_constants.asm:1-2`). |
| No active Pokerus | one-mon party (`wPartyCount` `01:DCD7`), `wPartyMon1PokerusStatus` `01:DCFB` = 0 | count `01:DA22`; status `01:DA46` = 0 | `ApplyPokerusTick` touches only active records (`engine/events/pokerus/apply_pokerus_tick.asm:1-25`). |
| No Mystery Gift state | `sMysteryGiftItem` `00:ABE2` = 0, `sMysteryGiftUnlocked` `00:ABE3` = `$FF`, decoration flags `00:ABF0-ABF5` = 0 | same | New game sets item/unlocked (C `intro_menu.asm:175-183`; G `:90-98`); erase clears decoration flags (C `save.asm:386-393`; G `:357-364`); CONTINUE copies set flags into PC decorations (C `engine/link/mystery_gift.asm:1327-1348`; G `:1170-1191`). |
| No recorded RTC fault | `sRTCStatusFlags` `00:AC60` = 0 | same | Useful input refusal, **but cannot prove a later overflow is absent**: `ClockContinue` checks current RTC status and can clear daily timers after loading (C `engine/rtc/rtc.asm:116-145`; G `:139-158`). Bind the emulator RTC state or require a runtime witness excluding that branch. |
| No Battle Tower carry | `sBattleTowerChallengeState` `01:BE45` = 0 | no symbol | Crystal rewrites it on load/save when it holds `BATTLETOWER_RECEIVED_REWARD`; new-save erase sets zero (C `engine/menus/save.asm:286-295,427-432,745-753`). |

## Corrections to the current oracle

- Crystal's `wGameTimerPaused` is unsaved: no SRAM rule for Crystal.
- Ordinary CONTINUE does not re-derive map-object coordinates or rebuild NPC IDs: those fields must be preserved
  byte-for-byte on a no-movement re-save (tighter than today's free spans), with later object movement
  treated separately.
