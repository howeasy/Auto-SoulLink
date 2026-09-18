# pureRGB fact derivation — gen1 scripted-harness drivers

Sources: W/ = `E:\Google Drive\SLink\.claude\worktrees\gen1-master-release-plan-6b4279` (read-only,
the shared drivers). P/ = pureRGB source at
`...\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad\purergb\`, commit `7e7a4653`. All P/ line
numbers below were read directly out of that tree this pass; the `const_def`/`const`/
`const_skip`/`const_next`/`dw_const` macro chains (macros/const.asm, macros/scripts/maps.asm) were
simulated by hand (or with a small script) rather than assumed, since a naive "count the named
lines" approach silently gives wrong ordinals wherever `const_skip N` or `const_next $XX` appears.

## The two failures, explained

**(a) SAVE route — "START menu row count disagrees with the SAVE row" (`gen1_rb_save_inputs.lua:62`)**

`engine/menus/draw_start_menu.asm:9-10` sets wTopMenuItemY=2/X=11 (SAME as vanilla). The row text
(`:64-76`) is the SAME 6 rows without the Pokedex / 7 with it, in the SAME order
(POKEMON/ITEM/name/SAVE/OPTION/EXIT, Pokedex prepended when owned), so the SAVE row's own 0-based
index is unchanged: **3 without the Pokedex, 4 with it** — identical to vanilla.

The divergence is in what gets stored to `wMaxMenuItem`. Vanilla (per the driver's own citation)
stores the row **count** (6 / 7). pureRGB stores the **last 0-based row index** (5 / 6):

```
draw_start_menu.asm:26   ld a, 5                    ; 5 = last index of the 6 no-Pokedex rows
draw_start_menu.asm:...  jr z, .storeMenuItemCount  ; branch on CheckEvent EVENT_GOT_POKEDEX
draw_start_menu.asm:...  inc a                       ; 5 -> 6 when the Pokedex row is prepended
draw_start_menu.asm:34   ld [wMaxMenuItem], a
```

`home/start_menu.asm:21` ("`inc a ; adjust position to account for missing pokedex menu item`")
confirms the same "Pokedex is a prepended row" indexing convention is used consistently.

Net effect: `wMaxMenuItem - save_index` is a constant either way (Pokedex adds 1 to both), but a
**different** constant than the vanilla-derived driver assumes:

| | vanilla | pureRGB |
|---|---|---|
| SAVE index (no dex / dex) | 3 / 4 | 3 / 4 (same) |
| wMaxMenuItem (no dex / dex) | 6 / 7 (row count) | 5 / 6 (row count − 1) |
| `menu_max − save_index` | **3** | **2** |

The driver's assertion (`gen1_rb_save_inputs.lua:62`) is
`(save==3 or save==4) and (menu_max==save+3 or menu_max==save+4)` — the `+4` case is the SLink
companion-cartridge's own appended SLINK row (`patch/gen1/tools/manifest.py:114-117`), which does
not exist on a bare pureRGB ROM. So on pureRGB the assertion needs `menu_max == save_index + 2`,
not `+3`. This is the complete, exact explanation of the failure.

**(b) Parcel route — "parcel removed outside Oak delivery script" (`gen1_rb_parcel_inputs.lua:164`)**

The Oak's-lab delivery script table itself is **identical** to vanilla — see the OaksLab row in
the table below; indices 15/16/17 with NOOP 18 are unchanged, and the item/Mart-side of the
delivery is unchanged too. The real divergence is a flag, not an index.

`constants/event_constants.asm:50`: `const_skip ; used to be EVENT_OAK_GOT_PARCEL but it's no
different from EVENT_GOT_POKEDEX`. That is: **`EVENT_OAK_GOT_PARCEL` (the flag the parcel driver
reads as `point.oak_got_parcel`) does not exist in pureRGB.** Its old bit position is a bare,
unused `const_skip`; grepping `scripts/` and `data/` for `EVENT_OAK_GOT_PARCEL` returns nothing —
no `SetEvent`, no `CheckEvent`. Reading that bit will always read 0/false.

pureRGB's actual "delivery complete" signal is `EVENT_GOT_POKEDEX` (bit 37, unchanged ordinal),
set inside `OaksLabOakGivesPokedexScript` (script 16) — the line `SetEvent EVENT_GOT_POKEDEX`
appears immediately before the script counter is advanced to `SCRIPT_OAKSLAB_RIVAL_LEAVES_
WITH_POKEDEX` (17). So the flag flips strictly **before** the script counter reaches 17, and
certainly before it reaches NOOP (18).

With a driver that reads a permanently-false `oak_got_parcel`, the delivery-in-progress branch
(`gen1_rb_parcel_inputs.lua:159-193`) never exits: it keeps demanding `lab_script` be 15, 16 or 17
for as long as `parcel_count==0`, but the moment the cutscene finishes and `wOaksLabCurScript`
settles at NOOP (18) — with the parcel already removed from the bag — the assertion at line 164
fires. This is airtight from source alone; no live frame is needed to confirm the mechanism, only
to confirm the exact frame the assertion fires on (which the harness already has).

**Fix for both**: swap the vanilla-literal reads for the pureRGB-derived ones in
`gen1_pure_facts.lua`: `oak_got_parcel` → `EVENT_GOT_POKEDEX` (bit 37) instead of the phantom bit
56, and the SAVE assertion's `save+3`/`save+4` → `save+2`.

## Literal table

| Literal | Driver file:line | Vanilla | pureRGB | Citation | Status |
|---|---|---|---|---|---|
| PALLET_TOWN map id | gen1_rb_center_inputs.lua:5 | 0x00 | 0x00 | P/constants/map_constants.asm:19 | SAME |
| VIRIDIAN_CITY map id | gen1_rb_center_inputs.lua:5 | 0x01 | 0x01 | map_constants.asm:20 | SAME |
| ROUTE_22 map id | gen1_rb_route22_inputs.lua:109 | 0x21 | 0x21 | map_constants.asm:54 | SAME |
| OAKS_LAB map id | gen1_rb_center_inputs.lua:5 | 0x28 | 0x28 | map_constants.asm:62 | SAME |
| VIRIDIAN_POKECENTER map id | gen1_rb_center_inputs.lua:5 | 0x29 | 0x29 | map_constants.asm:63 | SAME |
| VIRIDIAN_MART map id | gen1_rb_parcel_inputs.lua (map==0x2A) | 0x2A | 0x2A | map_constants.asm:64 | SAME |
| VIRIDIAN_FOREST_SOUTH_GATE | gen1_rb_forest_inputs.lua:155 | 0x32 | 0x32 | map_constants.asm:72 | SAME |
| VIRIDIAN_FOREST | gen1_rb_forest_inputs.lua:155 | 0x33 | 0x33 | map_constants.asm:73 | SAME |
| ROUTE_1 / ROUTE_2 map ids | gen1_rb_parcel_inputs.lua (map==0x0C/…) | 0x0C / 0x0D | (uncontradicted) | not directly grepped this pass | UNVERIFIED — settle with `grep -n "ROUTE_1 \|ROUTE_2 " constants/map_constants.asm` |
| POKE_BALL item id | gen1_rb_point_fields.lua:5 | 0x04 | 0x04 | P/constants/item_constants.asm:13 | SAME |
| OAKS_PARCEL item id | gen1_rb_point_fields.lua:6 | 0x46 | 0x46 | item_constants.asm:79 | SAME |
| ANTIDOTE / BURN_HEAL / PARLYZ_HEAL | gen1_rb_mart_signature.lua:7-8 | 0x0B/0x0C/0x0F | 0x0B/0x0C/0x0F | item_constants.asm:20,21,24 | SAME |
| Viridian Mart stock+order | gen1_rb_mart_signature.lua:7-8 | POKE_BALL,ANTIDOTE,PARLYZ_HEAL,BURN_HEAL | same list, same order | P/data/items/marts/viridian.asm:1-5 `script_mart` | SAME (parcel route's purchase flow already passed live, consistent) |
| EVENT_GOT_OAKS_PARCEL ordinal | gen1_rb_point_fields.lua:4 | 57 | 57 | P/constants/event_constants.asm:51 (const chain simulated) | SAME |
| EVENT_GOT_POKEDEX ordinal | gen1_scripted_play.lua:113 | 37 | 37 | event_constants.asm:37 (const chain simulated) | SAME |
| EVENT_OAK_GOT_PARCEL ordinal/flag | gen1_rb_point_fields.lua:3 (bit 56) | 56, set during scripts 15-17 | **does not exist** — dead `const_skip` at event_constants.asm:50, never Set/CheckEvent anywhere | event_constants.asm:50 comment + grep of scripts/,data/ (no hits) | **MECHANISM DIFFERS** — root cause of failure (b); substitute EVENT_GOT_POKEDEX (bit 37), set inside OaksLabOakGivesPokedexScript before script 17 |
| OaksLab script table (0-18, delivery 15/16/17, noop 18) | gen1_rb_parcel_inputs.lua:9-17, gen1_scripted_play.lua:80-190 | 0=DEFAULT..18=NOOP, same names | identical 19-entry table, same names/order | P/scripts/OaksLab.asm:6-26 (`dw_const` auto-numbers in table order, macros/const.asm:47-50) | SAME |
| PalletTown script table (0-6) | gen1_scripted_play.lua:65-76,96 | 0=DEFAULT..6=NOOP | identical | P/scripts/PalletTown.asm:9-15 | SAME |
| ViridianMart script table (0-2) | gen1_rb_parcel_inputs.lua (`mart_script==2`) | 0=DEFAULT,1=OAKS_PARCEL,2=NOOP | identical | P/scripts/ViridianMart.asm:6-10 | SAME |
| Oak-delivery text trigger (talk to Oak with parcel in bag) | gen1_rb_parcel_inputs.lua:173-179 | `.got_parcel` branch sets script=15 and removes parcel in the same call, no frame gap | identical order: `call OaksLabScript_RemoveParcel` then `ld a, SCRIPT_OAKSLAB_RIVAL_ARRIVES_AT_OAKS_REQUEST` | P/scripts/OaksLab.asm:918-925 (`OaksLabOak1Text`) | SAME |
| Rival opponent id (OPP_RIVAL1) | gen1_rb_ball_gate_inputs.lua:110, gen1_rb_route22_inputs.lua:110 | 225 (= OPP_ID_OFFSET 200 + RIVAL1 $19) | **221** (= OPP_ID_OFFSET **197** + RIVAL1 **$18**) | P/constants/trainer_constants.asm:1 (`OPP_ID_OFFSET EQU 197`), :40 (`trainer_const RIVAL1 ; $18`) | DIFFERS (already fixed by the harness; exact two-part cause confirmed) |
| Charmander lvl-1/lvl-5 moves (Growl slot 2) | gen1_rb_ball_gate_inputs.lua:93,146 | SCRATCH, GROWL | SCRATCH, GROWL (unchanged through level 5: next move LEER is level 7) | P/data/pokemon/base_stats/charmander.asm:13; P/data/pokemon/evos_moves.asm `CharmanderEvosMoves` (first learn at 7) | SAME |
| Bulbasaur lvl-1/lvl-5 moves | (starter species 8, gen1_rb_ball_gate_inputs.lua:93) | TACKLE, GROWL | TACKLE, GROWL (next move LEECH_SEED at level 7) | P/data/pokemon/base_stats/bulbasaur.asm:13; evos_moves.asm `BulbasaurEvosMoves` | SAME |
| Squirtle lvl-1/lvl-5 moves | (starter species 6, gen1_rb_ball_gate_inputs.lua:93) | TACKLE, TAIL_WHIP | TACKLE, TAIL_WHIP (next move BUBBLE at level 8) | P/data/pokemon/base_stats/squirtle.asm:13; evos_moves.asm `SquirtleEvosMoves` | SAME |
| GROWL move id | gen1_rb_ball_gate_inputs.lua:146 (`move2==0x2d`) | 0x2D | 0x2D | P/constants/move_constants.asm (const chain simulated) | SAME |
| START menu wTopMenuItemY/X | gen1_rb_save_inputs.lua:3-4 | Y=2, X=11 | Y=2, X=11 | P/engine/menus/draw_start_menu.asm:9-10 | SAME |
| START menu row order/count of names | gen1_scripted_play.lua:78-84 (glyph probe) | POKeDEX/POKeMON/ITEM/name/SAVE/OPTION/EXIT, 6 rows (no dex) / 7 (dex) | identical row text/order; SAME row **count** (6/7) | P/engine/menus/draw_start_menu.asm:64-76 | SAME (row text/order/count) |
| START menu SAVE row 0-based index | gen1_rb_save_inputs.lua:62 | 3 (no dex) / 4 (dex) | 3 / 4 | draw_start_menu.asm:64-76 + home/start_menu.asm:21 (Pokedex-offset convention) | SAME |
| START menu wMaxMenuItem value | gen1_rb_save_inputs.lua:62 | row **count**: 6 (no dex) / 7 (dex) → `menu_max == save+3` | last 0-based **index**: 5 (no dex) / 6 (dex) → `menu_max == save+2` | draw_start_menu.asm:26,34 (`ld a,5` / `inc a` / `ld [wMaxMenuItem],a`) | **DIFFERS (mechanism: count vs. last-index convention)** — root cause of failure (a) |
| SAVE prompt (TWO_OPTION_MENU) geometry | gen1_rb_save_inputs.lua:10-11,68 | text_box=0x14, Y=8, X=1, max=1, YES=index 0 | identical | P/constants/menu_constants.asm:25 (`$14`); P/engine/menus/save.asm:150-153,178 (`hlcoord 0,7`/`lb bc,8,1`) | SAME |
| YES/NO box position | gen1_rb_pc_inputs.lua:71-74 | hlcoord 14,7 | hlcoord 14,7 | P/home/yes_no.asm:6 | SAME |
| "Now saving..." text / save delay | (not asserted by drivers; timing only) | ~30-frame delay, "Now saving..." shown | text removed, delay cut to 1/3 (10 frames) | P/engine/menus/save.asm comments "PureRGBnote: CHANGED: remove 'now saving' text…" / "…reduce artificial save delay to 1/3 of original", `ld c, 10` | DIFFERS (mechanism/timing only; well within the driver's 1800-frame bound, does not affect correctness) |
| Battle menu (DisplayBattleMenu) template id/geometry | gen1_battle_driver.lua:8-11,52-53 | text_box=0x0B, box (8,12)-(19,17), cursor Y=14, X=9/15 | text_box=0x0B, same box, cursor Y=14 (X column set by BattleMenuText logic, not in the static table) | P/constants/menu_constants.asm:16; P/data/text_boxes.asm `text_box_text BATTLE_MENU_TEMPLATE, 8, 12, 19, 17, BattleMenuText, 10, 14` | SAME (also empirically confirmed: the lab route's rival battle — FIGHT, Growl — already ran this menu successfully live) |
| Bill's PC main/Bill's-PC menu geometry (Y=2,X=1; rows 42/82/122/162/202) | gen1_rb_pc_inputs.lua:35-44,93-95 | Y=2,X=1; rows at 42/82/122/162/202 | identical, same source line numbers as the driver's own citation | P/engine/pokemon/bills_pc.asm:77,79 (wTopMenuItemY/X) and :32,36,40,49,57,60,64 (hlcoord 2,2/2,4/2,6/2,8/2,10) | SAME |
| Deposit/withdraw sub-box (offset 251) | gen1_rb_pc_inputs.lua:50-53,94 | hlcoord 11,12 → 251 | hlcoord 11,12 → 251 | P/engine/pokemon/bills_pc.asm:474 | SAME |
| Change Box menu location | gen1_rb_pc_inputs.lua:65-70 | inline in engine/menus/save.asm `ChangeBox` | **moved** to its own file P/engine/menus/change_box_menu.asm (supports the new SELECT-to-change-box START-menu shortcut) | P/engine/menus/draw_start_menu.asm:8 comment; P/home/start_menu.asm `.selectPressed` handler; P/engine/menus/change_box_menu.asm (exists) | UNVERIFIED (file moved; geometry not re-read from the new file this pass — settle with a read of change_box_menu.asm or one live CHANGE BOX frame) |
| Catch-rate formula / encounter-slot assumptions | gen1_rb_hunt_inputs.lua:43-49 | ItemUseBall formula, Route 1 grass table | not independently re-derived this pass | P/engine/items/item_effects.asm, P/data/wild/maps/Route1.asm (not read) | UNVERIFIED — out of scope for the two reported failures; settle by reading those two files if the hunt driver is exercised on pureRGB |
| Poison cadence (1 HP/4 steps, PSN mask $08) | gen1_rb_forest_inputs.lua:119-128 | mask $08, 1 HP/4 overworld steps | not independently re-derived this pass | P/engine/events/poison.asm, P/constants/battle_constants.asm (not read) | UNVERIFIED — out of scope for the two reported failures |
| Bank $0F PC-hook filter (gen1_battle_driver) | gen1_battle_driver.lua:76 | hooks fire only when `hLoadedROMBank==0x0F` | not independently re-derived this pass | would need P/engine/battle/core.asm bank placement confirmed | UNVERIFIED — likely SAME (core.asm is bank-mapped identically in most ROM hacks of this era), not confirmed |

## Notes on method

- `dw_const`/`const`/`const_skip`/`const_next` in pureRGB are byte-for-byte the same macros as
  pret's (`P/macros/const.asm:1-51`), so any ordinal or script-table index can be recomputed
  exactly by walking the file top to bottom and simulating those four operations — counting named
  `const` lines alone (ignoring `const_skip`/`const_next`) gives silently wrong numbers wherever
  those appear, which is why the event-flag ordinals needed a small interpreter rather than a
  `grep -c` guess.
- Every "SAME" row above was confirmed by reading the actual pureRGB source line(s) cited, not by
  assuming a hack leaves engine code untouched. pureRGB is, on the evidence gathered this pass, a
  content/balance hack (new NPCs, a SELECT-to-swap-box shortcut, faster saving, rebalanced trainer
  ids) rather than an engine rewrite — nothing found this pass touches the menu-input engine
  (`home/list_menu.asm`, `home/window.asm`, `engine/battle/core.asm`'s menu machinery) itself.
