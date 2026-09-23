# OMP Gold errand source facts (card gen2-O-gold-errand), 2026-09-23

Peer reply for task `cx-a9462f1e` (peer omp, orchestrator claude). READ-ONLY: this file is the only
thing written; not committed. Pins: pokegold `656583c` (`.cache/gen2-build/pokegold`; Gold and Silver
share the tree). Every source citation is `pokegold/<path>:<line>`; the passability numbers below were
re-derived from the pinned ROM through the fixture machinery (`tools/gen2_fixtures.route_facts`).

---

## SUMMARY

The errand is walkable with three real interactions: Mr. Pokémon's house scene, Elm's lab handoff, and
the Route 29 catching-tutorial coord event — which the *passability data* shows is unavoidable once the
handoff arms it (the tutorial tiles are the only east-west crossing of Route 29's x=53 column). The
Mystery Egg is a **bag item**, not a party egg (`giveitem`/`takeitem`), so the party stays at one mon;
the one unavoidable phone call is Elm's ROBBED call, which is text-only (no yes/no) and ends with a
single `waitbutton`. The rival battle sets no flags, is avoidable (a one-column coord trigger), and is
safe to lose (`BATTLETYPE_CANLOSE`: no whiteout, party healed, scene → NOOP).

## FINDINGS

### F1 — the card's EVENT_ROUTE_30_BATTLE claim: VERIFIED, with the polarity proven

The three Route 30 objects are flag-gated (`maps/Route30.asm:338` Joey's important-battle script,
`:343`/`:344` the two SPRITE_MONSTER scenery objects) and an object whose trailing EVENT_* flag is SET
is **masked** (hidden) — `engine/overworld/map_objects_2.asm:32-63` (`CheckObjectFlag` → `EventFlagAction`
→ `jr nz, .masked`). The flag is set by the lab handoff (`maps/ElmsLab.asm:304`), and the trainer Joey
is *cleared* there too (`:303`), so after the errand: scene objects gone, trainer Joey present, Route 31
reachable (Route 30's north side is a *connection*, `data/maps/attributes.asm:184`). Confidence: high.

### F2 — the Mystery Egg is a bag item; the party stays at one mon

- Mr. Pokémon's house: `maps/MrPokemonsHouse.asm:31` `giveitem MYSTERY_EGG` (an item, not a party mon).
- Elm's lab: `maps/ElmsLab.asm:290` `takeitem MYSTERY_EGG`.
So the U1 driver's "party count 1" holds through the whole errand. The egg item is `MYSTERY_EGG`
(constants/item_constants.asm) — the Route30 scout reported id `$45` (not independently re-checked).
Confidence: high (both commands read directly).

### F3 — the walk: warps and connections per map

| map | facts | source |
|---|---|---|
| New Bark → Route 29 | map *connection* west/east (no warp) | `data/maps/attributes.asm:179` (Route29 west→Cherrygrove), Cherrygrove east→Route29 `:125` |
| Route 29 | one warp: `warp_event 27,1, ROUTE_29_ROUTE_46_GATE, 3` | `maps/Route29.asm:419` |
| Route 29 ↔ Cherrygrove | connections only | as above |
| Cherrygrove | 5 interior warps (mart, center, gym-speech house, Guide Gent's house, evolution house) at (23,3)/(29,3)/(17,7)/(25,9)/(31,11) | `maps/CherrygroveCity.asm:551-555` |
| Cherrygrove ↔ Route 30 | connections: Cherrygrove north→Route30 (`attributes.asm:124`), Route30 south→Cherrygrove (`:184`) | — |
| Route 30 | two warps: berry house (7,39), Mr. Pokémon's house (17,5) | `maps/Route30.asm:325-326` |
| Mr. Pokémon's house | two warps back to Route 30 (2,7)/(3,7) | `maps/MrPokemonsHouse.asm:374-375` |
| Elm's lab | two warps to New Bark (4,11)/(5,11) | `maps/ElmsLab.asm:1222-1223` |

Collision: the fixture's own grid (tiles, 60×18 for Route 29) shows the east-west corridor on Route 29
is **y=8/9 only** in the x=44..59 region (y=6/7 passable at x≤53 but blocked east of it; y=10/11
passable at x=48..53 only; grass from y=12). The tutorial coord events sit at **(53,8) and (53,9)** —
i.e. exactly on that corridor — `maps/Route29.asm:423-424`. Ledges are not in `PASSABLE_COLLISION`, so
the driver routes around them. Confidence: high (grid re-derived from the pinned ROM).

### F4 — the scenes, in order, with prompts and presses

1. **Cherrygrove, outbound** (scene NOOP): the Guide Gent is a *talk* NPC at (32,6)
   (`maps/CherrygroveCity.asm:568`), one `yesorno` (`:30`) with the default cursor on **YES**
   (`home/menu.asm:429-443`, default option byte 1), declining is free (`:95-99`) and skipping him
   changes nothing (the gift is the #GEAR Map Card, `setflag ENGINE_MAP_CARD :72`). His tile's
   solidity is UNVERIFIED here, but he is avoidable (talk-only).
2. **Route 30 → Mr. Pokémon's house**: no scene scripts, no coord events (`maps/Route30.asm:327-329`
   empty blocks); the trainers' sight lines (Joey 4, Mikey 1, Don 3 — `:339/:340/:341`) are only live
   where the walk passes their rows; the house door is at (17,5).
3. **Mr. Pokémon's house** (`sdefer` scene, `maps/MrPokemonsHouse.asm:14-16`): A-press waits only —
   `waitbutton` `:24`, the player is walked `:26`, `promptbutton` `:29`, the egg `:31`, then `:39`,
   `:42` promptbutton, `:46` waitbutton — and then `sjump MrPokemonsHouse_OakScript` `:48`.
4. **Oak's scene** (`:84-141`): `promptbutton` `:90`; **`setflag ENGINE_POKEDEX` `:95`**;
   `waitbutton` `:97`; Oak exits; `waitbutton` `:109`; **`special HealParty` `:113`** (the party is
   healed here); `waitbutton` `:120`; then the flag block `:122-127` (`EVENT_RIVAL_NEW_BARK_TOWN`,
   scene NOOP, `setmapscene CHERRYGROVE_CITY, MEET_RIVAL` `:124`, `setmapscene ELMS_LAB, MEET_OFFICER`
   `:125`, **`specialphonecall SPECIALCALL_ROBBED` `:126`**, `clearevent EVENT_COP_IN_ELMS_LAB` `:127`)
   and the rival's starter pick `:128-137` (Totodile player → `EVENT_CHIKORITA_POKEBALL_IN_ELMS_LAB`
   `:136`). No yes/no anywhere.
5. **Return through Cherrygrove**: the rival coord trigger at (33,6)/(33,7) gated on MEET_RIVAL
   (`maps/CherrygroveCity.asm:558-559`) — see F6. Avoidable by crossing at x≠33.
6. **The Elm call**: `SPECIALCALL_ROBBED` = 2 (`constants/phone_constants.asm:46`), whose list entry is
   **Elm** (`data/phone/special_calls.asm:10-17`), fires on the first step outdoors
   (`SpecialCallOnlyWhenOutside`, `engine/phone/phone.asm:306-317`: TOWN/ROUTE only) — i.e. on Route 30
   right outside the house, **unavoidable**; special calls are step-triggered and bypass the timer /
   phone-service / random-roll gates the ordinary call path needs (`engine/overworld/events.asm:854-862`,
   `engine/phone/phone.asm:249-294`). The script is text-only (`engine/phone/scripts/elm.asm:75-79`
   — no yesorno in the whole file) and the call ends with a `waitbutton` (`phone.asm:431-439`) — one
   A/B press, plus the ring's fixed waits.
7. **Elm's lab**: the cop coord event at (4,5)/(5,5) (`maps/ElmsLab.asm:1228-1229`) is **optional** —
   approach Elm at (5,2) from x=6 (the aisle at x=4/5 is the only trigger column). If taken, the script
   contains `special NameRival` (`MeetCopScript`, `maps/ElmsLab.asm:228-241`), a `_NamingScreen`
   (letter grid, `engine/menus/naming_screen.asm:7`): A on the END button is the exit (cursor command
   `$3`, `naming_screen.asm:396-399`), START only toggles the letter case (`:404-418`), and the default
   name "SILVER" is applied after (`engine/events/specials.asm:80-89`). The existing UI hooks cover
   `NamePlayer` (the intro's preset menu) only, so taking the cop scene would need a new origin + grid
   navigation.
8. **Talking to Elm** (`ProfElmScript` → `ElmCheckGotEggAgain`, `maps/ElmsLab.asm:94-102`): with
   `EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON` set, `iftrue ElmAfterTheftScript` — **no cop-scene
   dependency** (the dispatch is by events). `ElmAfterTheftScript` `:283-309`: `promptbutton` `:287`,
   `waitbutton` `:289`, `takeitem MYSTERY_EGG` `:290`, the jump-back texts `:291-297`, then
   **`setevent EVENT_GAVE_MYSTERY_EGG_TO_ELM` `:299`**, **`setmapscene ROUTE_29, SCENE_ROUTE29_CATCH_TUTORIAL`
   `:303`**, **`clearevent EVENT_ROUTE_30_YOUNGSTER_JOEY` `:303`** (line 303 is the clearevent; the
   setevent is 304 — see the block at :299-304), `waitbutton` `:305`, `setscene SCENE_ELMSLAB_AIDE_GIVES_POKE_BALLS`
   `:308`. A-press waits only.
9. **Leaving the lab**: the aide's coord events at (4,8)/(5,8) (`:1232-1233`) give **5 Poké Balls**
   (`AideScript_GiveYouBalls`, `giveitem POKE_BALL, 5` `:461`) — **avoidable** by exiting via x=3
   (the warp is (4,11)/(5,11)). If taken, the ball count becomes 15 with the O-10 injection.
10. **Final leg to (53,12)**: the Route 29 tutorial coord events are now live (scene = CATCH_TUTORIAL,
    `maps/Route29.asm:13-14`, `:423-424`) and the passability data says they are **unavoidable** (F3):
    the walk from New Bark to the grass crosses x=53 at y=8/9. The script asks a **yesorno**
    (`Route29Tutorial1`, `:47`; `Route29Tutorial2`, `:72`) — **answer NO** → `Script_RefusedTutorial1`
    (`:89-95`, texts + waitbutton, sets the scene to NOOP `:94`) → no tutorial battle, no party change.
    Answering YES runs `catchtutorial BATTLETYPE_TUTORIAL` (`:54`), which is a *fully auto-input* battle
    (`engine/events/catch_tutorial.asm:1-53`: the player's name is swapped for "DUDE", `StartAutoInput`,
    `StartBattle`) — and the caught Rattata follows the normal catch path, so it would land in the
    party (INFERENCE: no party exclusion exists anywhere in the catch path; `BATTLETYPE_TUTORIAL`
    appears only in `core.asm`, `returntobattle_useball.asm` and `item_effects.asm:243`).

### F5 — the rival battle (item 3)

- Trigger: coord events (33,6)/(33,7) gated on `SCENE_CHERRYGROVECITY_MEET_RIVAL`
  (`maps/CherrygroveCity.asm:558-559`), armed at `maps/MrPokemonsHouse.asm:124` — so it happens on the
  **return** trip, and **not** on first entry. No flags are set or cleared by the scene (its only
  effects are `disappear` + `setscene NOOP`, `:171-173`).
- Party with a Totodile player: `loadtrainer RIVAL1, RIVAL1_1_CHIKORITA` (`:133`) = **Lv 5 CHIKORITA**
  (`data/trainers/parties.asm:76-81`, class RIVAL1 = 9, id 1). Moves are the Lv-5 level-up set:
  TACKLE + GROWL (`data/pokemon/evos_attacks.asm:2059-2060`). Player's Totodile: SCRATCH + LEER
  (`:2148-2149`; `givepoke TOTODILE, 5, BERRY` at `maps/ElmsLab.asm:172`). Winnable by a scripted
  fight (better Attack/HP on the player side), but RNG-dependent; **a loss costs nothing**:
- `BATTLETYPE_CANLOSE` before every branch (`:123/:134/:145`) → the loss path does not black out
  (`engine/battle/core.asm:2761-2782`), the party is healed at battle end (`core.asm:2314-2317`) and
  again in `.FinishRival` (`:173`), the script continues, and the scene goes NOOP (`:172`) so there is
  no re-trigger. The post-battle branch is inverted relative to its labels (`iftrue .AfterVictorious`
  is taken on a LOSS — `Script_startbattle` stores WIN=0/LOSE=1, `engine/overworld/scripting.asm:1065-1071`,
  `:1217-1221`), but the two texts are byte-identical (`maps/CherrygroveCity.asm:459-468` vs `:475-484`)
  — harmless.
- Because the trigger is a single column and the scene sets no flags, the battle can also be **skipped**
  entirely by crossing Cherrygrove at x≠33.

### F6 — clock/RTC (item 4)

No time-of-day gate exists anywhere on the path. The only clock conditions in the two route maps are
the fruit trees' daily reset (`engine/events/fruit_trees.asm`, `DAILYFLAGS1_ALL_FRUIT_TREES_F`) and
Route 29's Tuscany (a *talk* NPC gated on Tuesday, `maps/Route29.asm:430`) — both avoidable/irrelevant.
The phone calls that can raise a **yes/no** are Mom's (her callee script) — armed only by
`SPECIALCALL_WORRIED` on Route 31 (`maps/Route31.asm:22`), *not* on this path; the errand's own call is
Elm's text-only one (F4.6). A random call needs at least 20 RTC minutes since the map load
(`engine/overworld/time.asm`, the `.ReceiveCallDelays db 20,10,5,3` table) — far beyond a scripted
route at 300% (the existing gold_battle play is ~17k frames).

### F7 — the cheapest end state (item 5)

`gold_battle`'s state (one L5 Totodile, the O-10 ball injection of 10, a native save at Route 29 (53,12))
plus these flags/effects, all set by walking the route above and answering the two prompts (tutorial NO;
rival battle either skipped or won/lost):

| effect | source |
|---|---|
| `EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON` | `maps/MrPokemonsHouse.asm:36` |
| `ENGINE_POKEDEX` flag | `maps/MrPokemonsHouse.asm:95` |
| `EVENT_RIVAL_NEW_BARK_TOWN` | `maps/MrPokemonsHouse.asm:122` |
| `EVENT_ELM_CALLED_ABOUT_STOLEN_POKEMON` (after the call) | `engine/phone/scripts/elm.asm:78` |
| `EVENT_GAVE_MYSTERY_EGG_TO_ELM` | `maps/ElmsLab.asm:299` |
| `EVENT_ROUTE_30_BATTLE` set / `EVENT_ROUTE_30_YOUNGSTER_JOEY` cleared | `maps/ElmsLab.asm:303-304` |
| Route 29 scene = CATCH_TUTORIAL (→ NOOP if the tutorial is declined) | `maps/ElmsLab.asm:303`, `maps/Route29.asm:94` |
| Elm's lab scene = AIDE_GIVES_POKE_BALLS (→ NOOP if the exit avoids the aide) | `maps/ElmsLab.asm:308` |
| `EVENT_CHIKORITA_POKEBALL_IN_ELMS_LAB` (the rival's pick) | `maps/MrPokemonsHouse.asm:136` |
| the party is fully healed (Oak's scene + possibly the rival battle) | `maps/MrPokemonsHouse.asm:113`, `core.asm:2314-2317` |

Party: unchanged at 1 (F2). Balls: 10 if the aide is avoided, 15 if not. Totodile level: a won rival
battle yields roughly 68 exp at L5 (base 64 × 5 / 7 × 1.5) versus the 91 needed for L6 (level³), so a
single battle should keep L5 — but a wild encounter on the final grass step could add more; RUN from
any wild battle to keep the level exact.

## DISAGREEMENTS

1. If the plan assumes the tutorial can be avoided, the passability data says otherwise: the coord
   tiles are the only east-west crossing of Route 29's x=53 column, and the scene is armed *before*
   the final leg (the handoff), so the fixture must answer the tutorial's yesorno. Answer NO.
2. If the plan assumes the cop scene (and the rival-name screen) must be handled, it does not: Elm's
   handoff is event-dispatched, not scene-gated, and the cop's trigger column (x=4/5) is avoidable.
3. If the plan expects the rival battle to be mandatory or story-flagged, it is neither: it sets no
   flags and is triggered by one column of coord events.

## UNKNOWN / UNVERIFIED

- The Guide Gent's tile solidity (needs the .blk collision; the fixture's grid can decide it).
- Whether the tutorial's caught Rattata is added to the party (inference from the absence of any
  exclusion in the catch path; a live check would settle it — another reason to answer NO).
- The Route 29/30 trainer sight-line rows relative to the walk (sight ranges cited; the exact rows the
  route passes were not plotted here).
- The whiteout details for this path: `GetWhiteoutSpawn` (`engine/events/whiteout.asm:59-71`),
  `HalveMoney` (`:45-56`) and `blackoutmod CHERRYGROVE_CITY` (`maps/MrPokemonsHouse.asm:37`) are cited
  but unreachable on this route (CANLOSE for the rival; no other battles except optional wild ones).
- The item id of MYSTERY_EGG (scout-reported `$45`, not re-checked).

## RECOMMENDATION

1. Add `CherrygroveCity`, `Route30`, `MrPokemonsHouse` to `tools/gen2_fixtures.MAPS` and extend
   `_observer_facts`' `scene_symbols` with their scene variables (e.g. `wCherrygroveCitySceneID`,
   `data/maps/scenes.asm:32`), plus prompt anchors for the tutorial yesorno and the phone call.
2. Route the final leg along y=8/9 to x=53 (the tutorial fires there by construction), answer NO,
   then step down to (53,12); approach Elm from x=6; exit the lab via x=3; cross Cherrygrove at x≠33
   (skip the rival) or take it and let CANLOSE handle a loss.
3. Do not take the cop scene: it is the only path that needs a `_NamingScreen` UI origin and grid
   navigation.
4. Keep RUN as the answer to any wild encounter on the final grass step.

## CLAIMS

| # | claim | verdict | evidence | confidence |
|---|---|---|---|---|
| 1 | EVENT_ROUTE_30_BATTLE must be set to remove the Route 30 objects and reach Route 31 | VERIFIED | `maps/Route30.asm:338/343/344`; polarity `engine/overworld/map_objects_2.asm:32-63`; set at `maps/ElmsLab.asm:304` | high |
| 2 | The save can end at Route 29 (53,12) with one L5 Totodile and 10 balls | VERIFIED (party) / route-dependent (balls) | (53,12) is grass (grid); the egg is an item (F2); balls 10 only if the aide is avoided (`maps/ElmsLab.asm:461`) | high |
| 3 | The errand route can be played with normal inputs, no save editing | VERIFIED (source) | every interaction above is a script prompt; no memory write required | high |
| 4 | The rival battle is winnable by a scripted L5 Totodile | PLAUSIBLE, RNG-dependent | matchup from `evos_attacks.asm:2059-2060/2148-2149`; no deterministic guarantee | medium |
| 5 | A rival-battle loss breaks nothing | VERIFIED | `BATTLETYPE_CANLOSE` `maps/CherrygroveCity.asm:123`; `core.asm:2761-2782`, `:2314-2317`; `.FinishRival` `:166-175` | high |
| 6 | The path needs no specific time of day | VERIFIED | no clock gate on the path; only fruit trees/Tuscany | high |
| 7 | The path raises a yes/no phone call | FALSE for the errand call (Elm's is text-only); the Mom yes/no call is Route 31+ | `data/phone/special_calls.asm:10-17`; `engine/phone/scripts/elm.asm:64-79`; `maps/Route31.asm:22` | high |
| 8 | The party stays at one mon through the errand | VERIFIED | `giveitem`/`takeitem MYSTERY_EGG` (`maps/MrPokemonsHouse.asm:31`, `maps/ElmsLab.asm:290`) | high |
| 9 | The tutorial coord event is unavoidable after the handoff | VERIFIED (grid) | `maps/Route29.asm:423-424`; passability grid re-derived from the pinned ROM | high |
| 10 | The cop scene (rival naming) can be skipped | VERIFIED | coord trigger column x=4/5 (`maps/ElmsLab.asm:1228-1229`) vs Elm's event dispatch (`:94-102`) | high |
