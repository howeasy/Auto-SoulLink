# N12b open static-capture source facts (Opus worker, read-only)

Scope: the four items left OPEN by commit `7ce1105` ("scripted static-battle
captures publish as their own gift area"). Sources are ONLY the pinned clones
`.cache/gen2-build/pokecrystal` (7a7881d0d62e0ddbd82dcf10e7116807487ac651,
Crystal 1.0 / `pokecrystal.gbc`) and `.cache/gen2-build/pokegold`
(656583c939d30f920a316177311a502dd222b57c, builds both `pokegold.gbc` and
`pokesilver.gbc`), matched against `data/games/gen2_{crystal,gold,silver}/
static_encounters.json` and `engine_signals.json`. No screenshots, no vision,
no RR data.

## Summary table

| # | Item | Crystal | Gold | Silver | Confidence |
|---|------|---------|------|--------|------------|
| 1 | Celebi reachability | **Not reachable** in normal play on the pinned 1.0 ROM; GS Ball never becomes obtainable without VC/mobile hooks that don't run on this build | N/A — no Celebi/GS-Ball-shrine script exists in pokegold | N/A — same as Gold | High (source-complete negative) |
| 1b | Pack row honesty | Row already says `"basis":"source occurrence; runtime reachability OPEN"` and the pack-level `open_obligations` lists `runtime_script_reachability` unresolved — **consistent**, does not overclaim | — | — | High |
| 2 | Whiteout/re-fight | See per-static table below; policy is **per-script**, not uniform | same scripts, same policy | same scripts, same policy | High for scripts read; Union Cave day-gate topology not re-derived |
| 3 | Box-full on wild catches | Party-full **and** box-full silently **drops the catch** (no insert), but the game still runs the full "Gotcha!"/nickname UI and later shows the Bill "box full" call — the player is never told the mon was lost | identical code path | identical (shares pokegold source) | High |
| 4 | Hardware firing | Capture signal hooks **`PokeBallEffect`** in `engine/items/item_effects.asm`, ROM bank 3, at 4 sites shared with *every* wild catch (no static-only CPU site exists); classification is done in the MODEL layer (`lua/gen2/signals.lua:410-439`), not on the ROM. **None of the 8 fixtures sit on a map with a publishable static** | same | same | High |

## 1. Celebi reachability (US/international Crystal 1.0, pinned build)

The pinned lock (`tools/build_gen2_syms.py:29-31,66`) builds Crystal via the
`pokecrystal`/`pokecrystal11` make targets only (`pokecrystal.gbc` /
`pokecrystal11.gbc`, Makefile:75-81); `Entry.PACKS.crystal.revision == "1.0"`
(lua/gen2/entry.lua:10) selects the `pokecrystal.gbc` (rev 0) build, **not**
`pokecrystal11_vc`/`pokecrystal11.patch` (Makefile:81).

Chain traced:
- `IlexForestShrineScript` only offers the Celebi fight if
  `EVENT_FOREST_IS_RESTLESS` is true and the player holds `GS_BALL`
  (maps/IlexForest.asm:429-435).
- The only places `GS_BALL` is ever given to the player are
  `maps/GoldenrodPokecenter1F.asm:17-45,49-77`, both gated on
  `ifequal GS_BALL_AVAILABLE, .gsball` (GS_BALL_AVAILABLE = `$b`,
  constants/battle_tower_constants.asm:47) after
  `special BattleTowerAction` with `wScriptVar` loaded from SRAM byte
  `sGSBallFlag` (`BattleTowerAction_GSBall`,
  engine/events/battle_tower/battle_tower.asm:1179-1185).
- `sGSBallFlag` (ram/sram.asm:140) is only ever **written** by
  `BackupGSBallFlag`/`RestoreGSBallFlag`/`ClearGSBallFlag`
  (mobile/mobile_41.asm:515-556), which copy/clear the flag but never set it
  to `GS_BALL_AVAILABLE`, and by the `vc_hook Enable_GS_Ball_mobile_event`
  comment block in `engine/menus/save.asm:164-175`.
- `vc_hook` (macros/vc.asm:3-7) only emits a label — it is a no-op unless
  `_CRYSTAL11_VC` is defined, which is true only for the
  `pokecrystal11_vc`/`pokecrystal11.patch` build target
  (Makefile:78,81,134,172-175), not the pinned `pokecrystal.gbc`.
- No other write site to `sGSBallFlag` exists anywhere in the pinned source
  (full-repo grep). It is written to a nonzero "available" value only by the
  Virtual Console binary-patch tooling (post-2023 Switch/3DS re-release) or,
  historically, Japan-only Mobile Adapter GB network events — neither of
  which executes on this pinned retail ROM/BizHawk target.

**Conclusion:** on the pinned build, `sGSBallFlag` never becomes
`GS_BALL_AVAILABLE` through any in-game script or event; the GS Ball, and
therefore the Ilex Forest Celebi fight, is unreachable without an external
cheat device or a differently-pinned VC artifact. This matches the
well-documented real-world fact that the international/US Crystal cartridge
never legitimately grants Celebi.

The Crystal pack row (`data/games/gen2_crystal/static_encounters.json`,
`IlexForest:IlexForestShrineScript.CelebiEvent:466`) marks
`"selected": true, "source_unused": false` — that field only encodes
"this script occurrence applies to Crystal" (see
`tools/gen_gen2_statics.py:142-154` `applicability()`, whose `basis` string
is literally `"source occurrence; runtime reachability OPEN"`), and the
pack's `open_obligations` (tools/gen_gen2_statics.py:270-272) still lists
`"runtime_script_reachability"` as unresolved. **The row does not claim
reachability and is consistent with this finding.** Gold/Silver have no
Celebi-shrine script at all (grep of `.cache/gen2-build/pokegold` for
`CelebiShrineEvent`/`IlexForestShrineScript` returns nothing) — not
applicable to those titles.

## 2. Whiteout / re-fight policy

Shared engine mechanism (applies to every row below): `startbattle`
(`Script_startbattle`, engine/overworld/scripting.asm:1159-1165) always
returns control to the calling map script and stores the outcome in
`wScriptVar` (WIN=0 = caught-or-defeated,
`engine/battle/core.asm:8614` "caught_or_defeated_roam_mon"; LOSE=1 =
whiteout; DRAW=2 = a fled battle, `engine/battle/core.asm:3810-3825`),
**regardless of the result** — whiteout does not abort script execution by
itself. The whiteout redirect happens later, specifically inside
`Script_reloadmapafterbattle` (engine/overworld/scripting.asm:1174-1185):
if `wBattleResult == LOSE` it jumps straight to `Script_BattleWhiteout`
(engine/events/whiteout.asm:1-22, heal + halve money + warp to last
Pokémon Center) and **never falls through to any script line written after
the `reloadmapafterbattle` op**. Any `setevent`/`disappear`/`setflag` line
placed **before** `reloadmapafterbattle` in the source still runs even on a
whiteout; only lines placed **after** it are skipped on a LOSE.

| Static (map:script) | Consumption line(s) vs. `reloadmapafterbattle` | Re-fightable after LOSE (whiteout)? | Re-fightable after DRAW (flee)? | Re-fightable after WIN (catch or defeat) without catching? |
|---|---|---|---|---|
| IlexForest Celebi (Crystal only) | `clearevent EVENT_FOREST_IS_RESTLESS` + `setevent EVENT_AZALEA_TOWN_KURT` fire **before** `special CelebiShrineEvent`/`startbattle` even runs (maps/IlexForest.asm:449-451) | No — consumed before the fight starts | No | No | 
| LakeOfRage RedGyarados | `ifequal LOSE, .NotBeaten` **skips** `disappear` on LOSE (maps/LakeOfRage.asm:79-83); reward (`giveitem RED_SCALE`) also skipped since `.NotBeaten`→`reloadmapafterbattle` still redirects away on LOSE | **Yes** | No (disappear+reward run) | No |
| Route36 Sudowoodo (WateredWeirdTreeScript) | `setevent EVENT_FOUGHT_SUDOWOODO` fires **unconditionally right after** `startbattle`, before the `ifequal DRAW` branch (maps/Route36.asm:71-73); both branches (`DidntCatchSudowoodo` and fallthrough) disappear+twin-sprite the tree before their own `reloadmapafterbattle` | No — flag already set pre-branch | No | No |
| TeamRocketBaseB1F exploding traps (Voltorb/Geodude/Koffing ×22 numbered traps) | Wrapper (`ExplodingTrap1..22`) calls `reloadmapafterbattle` **then** `setevent EVENT_EXPLODING_TRAP_n` (maps/TeamRocketBaseB1F.asm:272-445) | **Yes** | No | No |
| TeamRocketBaseB2F RocketElectrode1/2/3 | `iftrue TeamRocketBaseB2FReloadMap` skips `disappear` on LOSE/DRAW (maps/TeamRocketBaseB2F.asm:224-274); on WIN, `disappear` is session-only — **no `setevent` for `EVENT_TEAM_ROCKET_BASE_B2F_ELECTRODE_{1,2,3}` exists anywhere in the pinned source** (full-repo grep of both `checkevent`-only usage), so the follow-through `checkevent…iffalse TeamRocketBaseB2FReloadMap` chain always falls through to the same reload, and `RocketBaseElectrodeScript` (which gives HM06 Whirlpool) is **unreachable in this source** | **Yes** | **Yes** | **Yes — infinitely re-fightable in the pinned source; no consumption flag is ever set** |
| TinTowerRoof TinTowerHoOh(.Silver) | `setevent EVENT_FOUGHT_HO_OH` fires **before** `startbattle` (maps/TinTowerRoof.asm:26-29); map callback hides the object once that flag is set (TinTowerRoofHoOhCallback, maps/TinTowerRoof.asm:6-13) | No — consumed before the fight starts | No | No |
| WhirlIslandLugiaChamber Lugia(.Silver) | Same pattern: `setevent EVENT_FOUGHT_LUGIA` **before** `startbattle` (maps/WhirlIslandLugiaChamber.asm:26-29) | No | No | No |
| TinTower1F Suicune (Crystal only, `legend_245`) | `setevent EVENT_FOUGHT_SUICUNE` + roaming-Suicune flags fire **after** `startbattle` but **before** `reloadmapafterbattle` (maps/TinTower1F.asm:119-127) | No — flags already set pre-`reloadmapafterbattle` | No | No |
| UnionCaveB2F UnionCaveLapras | `disappear` + `setflag ENGINE_UNION_CAVE_LAPRAS` fire **unconditionally, unbranched, before** `reloadmapafterbattle` (maps/UnionCaveB2F.asm:26-30) | No | No | No |
| VermilionCity VermilionSnorlax.Awake | `disappear` + `setevent EVENT_FOUGHT_SNORLAX` fire **unconditionally, unbranched, before** `reloadmapafterbattle` (maps/VermilionCity.asm:44-47) | No | No | No |
| BurnedTowerB1F UnusedEnteiScript (Gold/Silver) | `; unreferenced` (maps/BurnedTowerB1F.asm:68) — no caller anywhere in source | N/A — dead code, unreachable regardless of outcome | | |
| Route29 tutorials (Route29Tutorial1/2, CatchingTutorialDudeScript) | Use `catchtutorial` (Script_catchtutorial, engine/overworld/scripting.asm:1167-1172), a scripted guaranteed catch with no wild-battle loss path; `kind:"tutorial"` rows are explicitly excluded from static classification (`lua/gen2/signals.lua:418`) regardless | Out of scope — no loss is possible and the model never publishes these as static | | |

**Net grouping:**
- **Gone forever regardless of outcome (consumption flag set before or
  unconditionally-before the whiteout check):** Celebi, Ho-Oh, Lugia,
  Suicune, Sudowoodo, Lapras, Snorlax.
- **Re-fightable after a whiteout loss specifically, consumed after
  anything else:** Red Gyarados, the three Team Rocket Base exploding traps.
- **Re-fightable indefinitely, never consumed by source (a latent/unfixed
  flag gap in the pinned pret decompile):** the three `RocketElectrode`
  duos in Team Rocket Base B2F.

## 3. Box-full on ordinary wild catches

Same code in Crystal (`engine/items/item_effects.asm`,
`engine/pokemon/move_mon.asm`) and Gold/Silver (identical file/routine
names and near-identical line numbers, verified separately in
`.cache/gen2-build/pokegold`).

- `PokeBallEffect` checks `wPartyCount == PARTY_LENGTH` (party full);
  if the party has room the mon goes to `TryAddMonToParty`
  (engine/items/item_effects.asm:548-556 Crystal / :548-552 Gold) — box-full
  logic is never touched.
- If the party is full, control always goes to `.SendToPC`
  (item_effects.asm:609-612 Crystal / :607-610 Gold) and calls
  `predef SendMonIntoBox`.
- `SendMonIntoBox` (engine/pokemon/move_mon.asm:942-950) checks the
  **active** box's `sBoxCount` against `MONS_PER_BOX` (20); if already full
  it jumps to `.full` (move_mon.asm:1069-1072), which does
  `CloseSRAM; and a; ret` — **it writes nothing**: no species/OT/DV data is
  stored and `sBoxCount` is left unchanged.
- Critically, the caller in `item_effects.asm` **never checks the carry
  flag** `SendMonIntoBox` returns (`scf` on success vs. plain `ret` on
  `.full`) — it falls straight through to `farcall SetBoxMonCaughtData`
  and the post-check `cp MONS_PER_BOX` / `set BATTLERESULT_BOX_FULL, [hl]`
  (item_effects.asm:614-623 Crystal / :612-619 Gold) regardless of whether
  anything was actually inserted, and continues the same "Gotcha!"/nickname
  UI flow used for a real capture (item_effects.asm:508-551 area).
- `BATTLERESULT_BOX_FULL` (constants/battle_constants.asm:268-269) has
  exactly one consumer: `Script_reloadmapafterbattle`'s `.was_wild` branch
  (engine/overworld/scripting.asm:1192-1198), which loads
  `Script_SpecialBillCall` — the "Bill" phone call reminding the player
  their box is full. It carries no information distinguishing "this catch
  filled the last slot" from "the box was already full and nothing was
  stored".

**Exact outcome inserting nothing:** party full (6/6) **and** the active PC
box already full (20/20) at the moment `SendMonIntoBox` runs. The wild mon
is silently discarded — the player sees the full capture animation, the
nickname prompt, and later Bill's "box is full" call, with no indication
the Pokémon was never stored anywhere. Party-has-room and
party-full-but-box-has-room both insert successfully (into the party or as
the new box slot 1, respectively).

## 4. Hardware firing

The capture signal is **not** a static-specific ROM hook. Per
`data/games/gen2_{title}/engine_signals.json` and
`lua/gen2/signals.lua:387-458`, every capture (static or ordinary wild) is
observed at the same four `PokeBallEffect` sites in
`engine/items/item_effects.asm`, **ROM bank 3**:

| site id | Crystal symbol\@addr | Gold symbol\@addr | Silver symbol\@addr |
|---|---|---|---|
| `capture_party` | `PokeBallEffect.not_celebi`\@0x6adb | `PokeBallEffect.skip_pokedex`\@0x6b50 | `PokeBallEffect.skip_pokedex`\@0x6b4e |
| `capture_box` | `PokeBallEffect.SendToPC`\@0x6b44 | `PokeBallEffect.SendToPC`\@0x6bb3 | `PokeBallEffect.SendToPC`\@0x6bb1 |
| `capture_party_finalized` / `capture_box_finalized` | `PokeBallEffect.return_from_capture`\@0x6be2 | `PokeBallEffect.return_from_capture`\@0x6c4b | `PokeBallEffect.return_from_capture`\@0x6c49 |

These are the same addresses I traced directly in
`engine/items/item_effects.asm` (Crystal lines ~508-624; the `.not_celebi`/
`.skip_pokedex` label pair is the Celebi-vs-non-Celebi branch at
item_effects.asm:539-546). The static/ordinary-wild distinction is made
entirely in the MODEL layer, not on the ROM: `final_event` in
`lua/gen2/signals.lua:405-439` reads `wBattleScriptFlags` bit 7 (set for
*every* scripted `loadwildmon`, including tutorials — see
`Script_loadwildmon`, engine/overworld/scripting.asm:1141-1148) plus
`wBattleType` against `STATIC_TYPES` (signals.lua:81) and matches the
generated pack row for `(map_group, map_number, species,
runtime_battle_type)`. A random tall-grass encounter never runs
`Script_loadwildmon`, so bit 7 is never set for it — that absence, not a
distinct address, is what separates "ordinary wild" from "scripted
static/tutorial" at these same four sites.

**Fixture proximity:** none of the eight fixtures in `tests/fixtures/gen2`
sit on a map with a *publishable* static. `tools/gen2_fixtures.py:48-50`
defines only two map targets: `town` (inside `ElmsLab`,
tools/gen2_fixtures.py:812) and `battle` (`Route29` tall grass,
tools/gen2_fixtures.py:812, with an O-10 Poké Ball injection). Route 29's
only `loadwildmon` scripts are `Route29Tutorial1`, `Route29Tutorial2`, and
`CatchingTutorialDudeScript` (all `kind:"tutorial"` in the pack) — these
*do* set `wBattleScriptFlags` bit 7 and *do* run through the same
`PokeBallEffect` sites, but `runtime_battle_type` is `BATTLETYPE_TUTORIAL`
(3), which is outside `STATIC_TYPES` (signals.lua:81), and
`final_event`'s row match additionally rejects `row.kind == "tutorial"`
(signals.lua:418) — so a scripted encounter on the `battle` fixture's own
map can never publish as `acquisition="static"` no matter what a live run
does. ElmsLab hosts no `loadwildmon` script at all.

**Nearest real static per title (route prerequisites sourced from the
scripts themselves; map-graph adjacency to Route 29/New Bark Town is
*not* re-derived here and is marked UNVERIFIED):**
- Sudowoodo (Route36, all three titles): gated on
  `checkitem SQUIRTBOTTLE` (maps/Route36.asm:51 `SudowoodoScript`), which
  is given at `maps/GoldenrodFlowerShop.asm:13-26` — a Goldenrod City
  side errand.
- Snorlax (VermilionCity, all three titles): gated on
  `special SnorlaxAwake` requiring `wMapMusic == MUSIC_POKE_FLUTE_CHANNEL`
  (engine/events/specials.asm:324-334) — i.e. playing the Poké Flute next
  to it, an item obtained well into the main story.
- Lapras (UnionCaveB2F, all three titles): gated only on
  `readvar VAR_WEEKDAY; ifequal FRIDAY` in the map object callback
  (maps/UnionCaveB2F.asm:15-22) — no item/event check found in the script
  itself; reaching Union Cave B2F only requires ordinary map traversal
  (badge/HM prerequisites for that traversal are UNVERIFIED here — not
  re-derived from map connection/header data in this pass).
- Red Gyarados (LakeOfRage, all three titles): no `checkitem`/`checkevent`
  gate found in `RedGyarados` itself (maps/LakeOfRage.asm:79-90); reaching
  Lake of Rage requires unspecified main-story progress toward Mahogany
  Town (UNVERIFIED — route/badge chain not traced from map headers in this
  pass).

Given no item gate is visible in-script, Lapras and Red Gyarados are the
best-supported "nearest normally-reachable static" candidates from the
source read here, but the actual map-graph distance from Route 29/New Bark
Town to Union Cave vs. Lake of Rage was not traced in this pass (see
UNVERIFIED list).

## UNVERIFIED

- Exact map-graph adjacency/badge-gating chain from New Bark Town/Route 29
  to Union Cave B2F, Lake of Rage, Route 36, Vermilion City, Team Rocket
  Base, Tin Tower, and Whirl Islands (would require tracing
  `data/games/gen2_*/area_map.json` connections and warp/HM gates, not
  done in this pass).
- Whether the Union Cave B2F Lapras room additionally requires Surf/an HM
  to physically reach within the cave (only the Friday day-of-week gate
  was confirmed from the script itself).
- Whether any other engine path besides `mobile_41.asm`'s
  Backup/Restore/Clear routines and the VC hook ever touches `sGSBallFlag`
  in a way not caught by the full-repo grep performed here.
- Bug-for-bug status of the `RocketElectrode1/2/3` "never consumed" finding
  against the actual retail Gold/Silver/Crystal cartridges (this is a
  pinned-source finding, not independently cross-checked against a second
  disassembly or hardware capture).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
