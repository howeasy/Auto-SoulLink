# Gen 2 peer ghost design research

Status: research only, post-RC feature (owner ruling, ticket 17). Builds on the FEASIBLE-WITH-PATCH
verdict already recorded in `docs/gen2/wayfinder/issues/17-peer-ghost-feasibility.md` and
`docs/gen2/research/sound_sites_and_peer_ghost.md` §B (R7). Those establish, and this doc does not
re-derive: `NUM_OBJECT_STRUCTS = 13`, `NUM_OBJECTS = 16` (`constants/map_object_constants.asm:38,100`),
`NOCLIP_OBJS` is `OBJECT_FLAGS1` bit 6 (`:54`), and there is no `sMapObjects` in SRAM.

Pins: `C` = pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651 (`scratchpad/pret_head/pokecrystal`),
`G` = pokegold@656583c939d30f920a316177311a502dd222b57c (`scratchpad/pret_head/pokegold`).

## Pins

- `C` pokecrystal@7a7881d, `G` pokegold@656583c (see above).
- Gen 3 precedent: `lua/peer_ghost_npc.lua` (whole file, this worktree).
- Prior Gen 2 research, cited not re-derived: ticket 17; R7 §B
  (`docs/gen2/research/sound_sites_and_peer_ghost.md:149-313`).

## Gen 3 precedent (what the ghost needs)

`lua/peer_ghost_npc.lua` is the RR companion-patch receiver, not the actor: the C-side patch
(`handlers.c`, not in this worktree) owns spawn/despawn/map-change/gfx-change lifecycle and drives
the ghost at constant engine velocity between broadcast samples (`peer_ghost_npc.lua:1-16`). The
Lua side's job, replicated frame-by-frame, is four things a Gen 2 design must also do somewhere:

1. **Gate on being in the walkable field**, not menus/battle — RR gates on
   `gMain.callback2 == CB2_Overworld` (`:62`); Gen 2's analogous gate is "only while `HandleMap`'s
   jumptable is dispatching `HandleMap` itself" (see Hazards below), no direct `wBattleMode`-style
   flag needed on the Lua side since the callback simply isn't invoked during battle.
2. **Re-verify ownership of the slot every frame before writing avatar/position data** — RR checks
   the object-event's `localId == 0xF0` before every re-assert because a warp can silently
   reallocate the slot to a real NPC (`:139-141`). Gen 2's analogous risk is worse (see Patch
   surface B1): nothing re-arms the ghost automatically, so the check must be "is my claimed
   struct still marked as mine" every frame, not just after a warp.
3. **Post position as sub-pixel world coordinates, not raw tile pokes**, and snap on a large jump
   or first frame on a map (`:174-186`, `SNAP_PX`). Gen 2's `OBJECT_SPRITE_X`/`OBJECT_SPRITE_Y`
   fields already store the pixel remainder against `OBJECT_MAP_X`/`OBJECT_MAP_Y`
   (`constants/map_object_constants.asm:17-24` — see Motion fields), so the same design pattern
   maps directly, no new field needed.
4. **Forward the partner's own avatar (sprite id + palette), never the local player's** — RR
   spawns with the partner's own `graphicsId` so OAM geometry matches their mount/state
   (`:82-105`). Gen 2's analogue is `GetPlayerSprite` picking `SPRITE_CHRIS`/`SPRITE_KRIS` by state
   (`overworld.asm:55-85`, see Sprite and palette) — the ghost must be told the partner's
   `wPlayerState`/gender, not read the local player's.

The single biggest structural difference: RR's `gObjectEvents` pool is dynamic and the companion
patch can allocate/free a slot at any time without touching persistent state. Gen 2's
`wObjectStructs`/`wMapObjects` pools are *part of the save file* (see Save exclusion below) and are
only rebuilt wholesale on a subset of map-entry paths — the ghost's lifecycle is bound to those
specific hooks, not to an arbitrary "spawn now" call.

## Object slot budget

- `wObjectStructs` / `NUM_OBJECT_STRUCTS = 13` (`constants/map_object_constants.asm:38`) is the
  active/animatable pool; struct 0 is the player (`wPlayerStruct`, `ram/wram.asm:3038-3039` C).
  12 non-player slots.
- `wMapObjects` / `NUM_OBJECTS = 16` (`:100`) is the per-map placement pool; object 0 is the player
  (`PLAYER_OBJECT EQU 0`, `:99`).
- **The engine's own free-slot predicate** is `FindFirstEmptyObjectStruct`
  (`home/map_objects.asm:420-448` C, `:420-448` G — identical logic in both): scans
  `wObjectStructs` in `OBJECT_LENGTH` strides, tests byte 0 (`OBJECT_SPRITE`) `== 0`
  (not a sprite-entry count, and not `-1`: `-1` is what `DeleteMapObject` writes into the
  *map-object* placement pool's `OBJECT_SPRITE` field at `engine/overworld/map_objects.asm:5-24`
  to mark a placement slot vacated, distinct from the struct pool's own "unused" sentinel `0`).
  A Gen 2 ghost implementation must probe with this exact predicate — call
  `FindFirstEmptyObjectStruct` itself (native) or replicate its byte-0-is-0 test (Lua) — not count
  populated map-object sprite entries as R7 originally suggested.
- **Static per-map maximum `object_event` counts** (grep `^\tobject_event` in every `maps/*.asm`,
  both repos, this pass):

  | Rank | `C` map | count | `G` map | count |
  |---|---|---|---|---|
  | 1 | GoldenrodCity | 15 | TeamRocketBaseB2F | 14 |
  | 2 | TeamRocketBaseB3F | 14 | Route32 | 14 |
  | 3 | TeamRocketBaseB2F | 14 | NationalPark | 14 |
  | 4 | Route32 | 14 | IlexForest | 14 |
  | 5 | NationalPark | 14 | GoldenrodCity | 14 |

  All of these are below `NUM_OBJECTS = 16` (raw placement capacity headroom exists everywhere
  checked), but every one of them exceeds `NUM_OBJECT_STRUCTS - 1 = 12` non-player active structs.
  As R7 already noted, most of GoldenrodCity's 15 are event-flag-gated alternates
  (`sound_sites_and_peer_ghost.md:170-182`) so simultaneous saturation is unproven either way; this
  pass adds no new evidence on mutual exclusivity (still `†UNVERIFIED`, see Open questions), but it
  does establish that a *static* "there is always a free struct" guarantee cannot be assumed on
  these five maps and the runtime `FindFirstEmptyObjectStruct` check is mandatory, not a
  belt-and-braces extra.
- Ghost placement recommendation: **do not consume a `wMapObjects` slot at all** for the steady
  state. `wMapObjects` entries are only meaningful as the *source* `CopyMapObjectToObjectStruct`
  reads from (`player_object.asm:165-225`); an injected ghost has no backing `object_event`, so
  writing a synthetic `wMapObjects` slot buys nothing a direct `wObjectStructs` write doesn't
  already give, and it doubles the surface that must be excluded from save (see below). Claim one
  `wObjectStructs` slot via `FindFirstEmptyObjectStruct` and set its
  `OBJECT_MAP_OBJECT_INDEX` (`constants/map_object_constants.asm:2`) to a sentinel value (e.g.
  `$FF`, not a real map-object index) so nothing that walks `wMapObjects`→struct back-references
  misinterprets it.

## Patch surface

Numbered hooks, each routine + file:line + what it does:

1. **`LoadMapObjects` tail** (`engine/overworld/map_setup.asm:78-83`, both repos) — runs
   `MAPCALLBACK_OBJECTS`, `farcall LoadObjectMasks`, `farcall InitializeVisibleSprites`. This is
   the re-arm point on every path that reaches it: call `FindFirstEmptyObjectStruct`, populate the
   claimed struct's `OBJECT_SPRITE`/`OBJECT_PALETTE`/`OBJECT_MAP_X`/`OBJECT_MAP_Y`/
   `OBJECT_FLAGS1` (set `NOCLIP_OBJS_F`) directly (no `wMapObjects` intermediary — see above),
   mirroring what `CopyTempObjectToObjectStruct` does for a normal NPC
   (`engine/overworld/player_object.asm:415-463`).
2. **`ClearObjectStructs`** (`home/map.asm:636-650` C — zero-fills `wObject1Struct..` up to
   `NUM_OBJECT_STRUCTS - 1`) is called from `ReadObjectEvents`
   (`home/map.asm:566-568`, part of `ReadMapEvents` unless `skip object events` is set,
   `home/map.asm:412-416`), which runs on every map-entry path *except* `MapSetupScript_Continue`
   (see hook 4). Any struct the ghost claimed is wiped here — this is the re-arm trigger, not
   something to work around: hook 1 must run again after this on every one of those paths.
3. **Per-frame position/direction/step write** — `HandleMapObjects` → `farcall HandleNPCStep` /
   `farcall _HandlePlayerStep` (`engine/overworld/events.asm:151,203-207`, called from `HandleMap`
   unconditionally when `wMapStatus == MAPSTATUS_HANDLE`, `:140-152`). A Lua/patch hook writing
   `OBJECT_MAP_X`/`OBJECT_MAP_Y`/`OBJECT_SPRITE_X`/`OBJECT_SPRITE_Y`/`OBJECT_DIRECTION`/
   `OBJECT_FACING` into the claimed struct once per frame (or every other frame for ~30 Hz) is
   cheap and needs no engine change — same "poke object struct fields externally" recipe as Gen 1.
4. **`MapSetupScript_Continue`** (`data/maps/setup_scripts.asm:161-179` C,
   `:161-179` G) calls `LoadMapAttributes_SkipObjects` (`home/map.asm:385-391`), which calls
   `ReadMapEvents` with the skip flag set (`TRUE`) — `ReadMapEvents` then returns *before*
   `ReadObjectEvents`/`ClearObjectStructs` run at all (`home/map.asm:412-416`). Compare
   `MapSetupScript_Continue`'s command list (`data/maps/setup_scripts.asm:161-179`) against
   `MapSetupScript_Warp`'s (`:32-54`, includes `mapsetup LoadMapObjects` at `:45`): **CONTINUE never
   calls `LoadMapObjects` either.** On boot from a save, `wObjectStructs`/`wMapObjects` are
   whatever the SRAM→WRAM player-data restore left there (see Save exclusion below), completely
   unrebuilt, until the player's first warp. A ghost struct that survived into the save file
   reappears verbatim at boot and is never cleaned up until that first warp fires hooks 1/2. The
   patch/client must independently clear or re-validate the ghost's claimed struct on the
   continue path, since neither hook 1 nor hook 2 fires there.
5. **Suspend on battle entry** — no explicit object-struct teardown call was found in
   `engine/battle/core.asm`; the mechanism is architectural, not a flag check. `HandleMap` is only
   reached via `OverworldLoop`'s `wMapStatus` jumptable (`engine/overworld/events.asm:3-21`); when
   a battle starts, the main loop's `callback`/mode switches away from `OverworldLoop` entirely
   (standard pret main-loop dispatch, not separately re-traced against `home/main.asm` in this
   pass — `†UNVERIFIED` exact call site, but `HandleMapObjects`/`HandleMap` simply do not execute
   while battle owns the frame). A Lua-side driver should gate its own per-frame write on
   `wBattleMode` (`ram/wram.asm:2720` C) as belt-and-braces, matching R7's B5 recommendation,
   but the primitive guarantee is "the engine doesn't touch `wObjectStructs` during battle either."
6. **Remove on disconnect / map change away** — same predicate as hook 2's aftermath: once the
   struct is known clobbered (either genuinely by a real map load, or deliberately by the
   patch/client), just stop writing to the claimed index and forget it; `DeleteMapObject`
   (`engine/overworld/map_objects.asm:5-24`) is the engine's own analogous cleanup for a
   *map-object*-backed entry, but since the ghost has no `wMapObjects` counterpart (see Object
   slot budget), the client only needs to zero the claimed `wObjectStructs` entry itself
   (`OBJECT_SPRITE = 0`, matching what `FindFirstEmptyObjectStruct` treats as free) rather than
   calling engine deletion machinery built for the map-object case.

## Sprite and palette

- **Partner sprite selection.** `GetPlayerSprite` (`engine/overworld/overworld.asm:55-85` C) picks
  `ChrisStateSprites` vs `KrisStateSprites` by `wPlayerGender`'s `PLAYERGENDER_FEMALE_F` bit (or a
  forced-male override, `PLAYERSPRITESETUP_FEMALE_TO_MALE_F`), then indexes by `wPlayerState`
  (biking/surfing/etc., `:66-68`), defaulting to `SPRITE_CHRIS` for any unmapped state (`:77-81`).
  **`G` (pokegold) has only `ChrisStateSprites`** — `GetPlayerSprite`
  (`pokegold/engine/overworld/overworld.asm:46-71`) never branches on gender, there is no
  `KrisStateSprites` table reference in that function. Treat "load the partner's own
  Chris-vs-Kris choice" as a Crystal-only design item; on Gold every player (local and ghost) is
  Chris.
- A ghost must be told the *partner's* `wPlayerState` + (on Crystal) gender, not read the local
  player's globals — same principle as RR forwarding `graphicsId` rather than reusing the local
  player's (`lua/peer_ghost_npc.lua:87-90`).
- **VRAM tile budget.** `wUsedSprites` has `SPRITE_GFX_LIST_CAPACITY = 32` entries of 2 bytes each
  (`constants/gfx_constants.asm:22`, `ram/wram.asm:2489` C: `wUsedSprites:: ds
  SPRITE_GFX_LIST_CAPACITY * 2`). It is populated once per map load by `RefreshSprites` →
  `AddMapSprites` (walks the map's static NPC sprite ids, `overworld.asm:94-118`) plus
  `GetPlayerSprite`'s own player-sprite id, then `LoadAndSortSprites` → `LoadSpriteGFX` DMAs the
  actual tile data (`overworld.asm:304-308`). `AddSpriteGFX` (`:310-`) already dedupes by sprite
  id and returns carry when the 31-remaining-slot list (`SPRITE_GFX_LIST_CAPACITY - 1`, slot 0 is
  reserved for the player, `:317-318`) is full — so loading the partner's `SPRITE_CHRIS`/
  `SPRITE_KRIS` costs **one more `wUsedSprites` entry, not zero**, since the partner's own
  Chris/Kris choice may differ from the local player's and from every visible map NPC's sprite id.
  This is a one-time-per-map-load cost, not a per-frame one: it must be injected into the
  `AddMapSprites`/`RefreshSprites` sequence (a call around `overworld.asm:94-103`, or a `mapsetup`
  hook alongside `RefreshMapSprites`), not into the per-frame struct-poke hook. Whether 32 slots
  ever actually fill on a real map load (evicting an NPC to make room) is `†UNVERIFIED` — not
  checked map-by-map in this pass.
- **Palette.** `MAPOBJECT_PALETTE`/`OBJECT_PALETTE` fields carry a 4-bit OAM-palette index plus
  flag bits (`SWIMMING`/`STRENGTH_BOULDER`/`BIG_OBJECT`, `constants/map_object_constants.asm:69-72`);
  `SpawnPlayer` sets the local player's own struct to `PAL_NPC_RED` or `PAL_NPC_BLUE` by gender
  (`engine/overworld/player_object.asm:19-52`, `ln e, PAL_NPC_RED/BLUE, OBJECTTYPE_SCRIPT` at
  `:32,39`). The ghost's `OBJECT_PALETTE` byte should be set the same way from the *partner's*
  gender/state, reusing the existing `PAL_NPC_RED`/`PAL_NPC_BLUE` constants — no new palette slot
  needed, this is a value already resolved elsewhere in the engine for exactly this purpose.

## Motion fields

Gen 3 ghost fields → Gen 2 `object_struct` equivalents (`constants/map_object_constants.asm:1-33`):

| Gen 3 (`lua/peer_ghost_npc.lua`) | Gen 2 field | Offset (C/G identical) |
|---|---|---|
| world-px position (`g.x`,`g.y`, `:177`) | `OBJECT_MAP_X`/`OBJECT_MAP_Y` (tile) + `OBJECT_SPRITE_X`/`OBJECT_SPRITE_Y` (pixel remainder) | `0x10`/`0x11`, `0x17`/`0x18` |
| facing (`g.f`) | `OBJECT_FACING` | `0x0d` |
| moving/anim (`g.mv`,`g.an`) | `OBJECT_STEP_TYPE` + `OBJECT_ACTION` | `0x09`, `0x0b` |
| — (RR has no discrete "step timer") | `OBJECT_STEP_DURATION` | `0x0a` |
| sub-pixel LERP done in the patch (`:174-186`) | `OBJECT_SPRITE_X_OFFSET`/`OBJECT_SPRITE_Y_OFFSET` | `0x19`/`0x1a` |

`CopyTempObjectToObjectStruct`'s `.InitXCoord`/`.InitYCoord` (`player_object.asm:465-501`) show how
the engine itself derives `OBJECT_SPRITE_X/Y` from `OBJECT_MAP_X/Y` minus the current
`wXCoord`/`wYCoord` (player's screen-relative tile) and the BG scroll offset, `swap`ped into a
pixel value — i.e. `OBJECT_SPRITE_X/Y` is **relative to the player's own screen position**, not an
absolute world pixel. A Lua/patch driver writing the ghost's position must replicate this same
relative computation every frame (recompute from the ghost's own `OBJECT_MAP_X/Y` vs the current
`wXCoord`/`wYCoord`), not just copy a cached world-pixel value the way RR's flat world-pixel scheme
does — this is the single largest arithmetic difference from the Gen 3 precedent.

**Coherence with `ObjectStep`:** `OBJECT_STEP_TYPE` drives a jumptable
(`StepTypesJumptable`/`STEP_TYPE_*`, `constants/map_object_constants.asm:169-`) inside
`HandleObjectStep` (`engine/overworld/map_objects.asm:29-`, not walked line-by-line in this pass —
`†UNVERIFIED` internals). Writing raw position fields from Lua between engine frames is coherent
only if `OBJECT_STEP_TYPE` is left at a passive state (`STEP_TYPE_STANDING`/`STEP_TYPE_RESET`) so
the engine's own step machinery doesn't also try to mutate the same fields the external write just
set, racing the external driver — the same principle Gen 1's clone technique and RR's "neutralize
its callback" (`lua/peer_ghost_npc.lua:3`) both rely on. Whether Gen 2's `HandleObjectStep`
internals tolerate a same-frame external overwrite of `OBJECT_MAP_X/Y` without also needing
`OBJECT_LAST_MAP_X/Y` (`:0x12/0x13`) kept in sync was not traced in this pass.

## Hazards and controls

| Hazard | Control |
|---|---|
| Wild encounters — driven by the player's own step/tile counters, not iteration over `wMapObjects`/`wObjectStructs` (not separately re-verified against `engine/overworld/wildmons.asm` this pass, `†UNVERIFIED`, matches R7 B4) | Low risk by construction; ghost is a passive struct, no code path was found that would need to skip it |
| Collision: the ghost being walked *into* by the local player | `NOCLIP_OBJS_F` (`OBJECT_FLAGS1` bit 6) only suppresses the check on the **moving** object's own side: `WillObjectBumpIntoSomeoneElse` is skipped when the *mover's* `NOCLIP_OBJS_F` is set (`engine/overworld/npc_movement.asm:20-41` C & G, identical). It says nothing about whether the **local player**, walking with `NOCLIP_OBJS_F` clear as normal, treats the ghost's struct as an obstacle when the player is the mover. `WillObjectBumpIntoSomeoneElse`'s own logic (whether it checks the *target* struct's flags, or blindly treats any occupied struct/tile as blocking) was not traced in this pass — symmetric non-blocking (ghost never obstructs the local player either) is `†UNVERIFIED` and must be confirmed before shipping, not assumed from the mover-side bit alone |
| Map connection loads / warps clobber the injected struct | Hooks 1+2 above: re-arm in the `LoadMapObjects` tail on every path that calls it |
| **CONTINUE (boot from save) never calls `LoadMapObjects` or `ReadObjectEvents`** | Hook 4: the client/patch must independently validate or clear the ghost's claimed struct on the continue path — no engine call does it |
| **Save**: `wObjectStructs`/`wMapObjects` are inside `wPlayerData`/`wPlayerDataEnd`
  (`ram/wram.asm:2993→3378` C: `wGameData::`/`wPlayerData::` at `:2993`, `wObjectStructs` at
  `:3038`, `wMapObjects` at `:3049`, `wPlayerDataEnd::` at `:3378`; G:
  `wPlayerData::`/`wPlayerData1::` header then `wObjectStructs` inside a `UNION`/`NEXTU` block,
  `wPlayerDataEnd::` at `:2720`) and `SavePlayerData` (`engine/menus/save.asm:497-508` C,
  `:396-407` G) `CopyBytes`'s the **entire** `wPlayerData..wPlayerDataEnd` span to `sPlayerData`
  verbatim — an injected ghost struct/map-object entry that is live at save time **is written into
  the SRAM save file**, not just runtime WRAM | See dedicated section below |
| Suspend in battle | Hook 5: no explicit teardown call found; `HandleMap`/`HandleMapObjects` simply are not invoked while battle owns the main loop (architectural, `†UNVERIFIED` exact dispatch site — see Patch surface #5); gate the Lua-side write on `wBattleMode` as belt-and-braces |
| Pokégear/phone scripts, NPC scripted movement walking other objects | Not traced in this pass; scripted movement iterates specific object indices by design (`movement.asm`), so a ghost occupying an index no script references should be inert, but this was not independently confirmed — `†UNVERIFIED` |

### Save exclusion and restore lifecycle

Because `wObjectStructs`/`wMapObjects` sit inside the exact byte range `SavePlayerData` copies
wholesale (`ram/wram.asm:2993-3378` C, `SavePlayerData` at `engine/menus/save.asm:497-508` C /
`:396-407` G), an injected ghost is not automatically excluded from the save the way R7's "no
`sMapObjects` in SRAM" framing implied — that framing was about a *dedicated* map-object save
region not existing, not about the *general* player-data save region also not covering this range.
It does. Concretely:

- **Before any save-triggering menu action reaches `SavePlayerData`**, the patch/client must either
  (a) clear the ghost's claimed `wObjectStructs` entry back to all-zero (matching
  `FindFirstEmptyObjectStruct`'s free predicate) so the save captures a clean slot, or (b) accept
  that the ghost's last-known position/sprite/palette bytes get written into `sPlayerData` and
  design the load path to treat them as inert on restore. (a) is simpler and matches "the ghost
  doesn't persist across sessions" (the desired semantics per the peer-ghost feature generally —
  it's a live-session artifact, not game state).
- **On load (CONTINUE)**: per hook 4, `LoadMapObjects`/`ReadObjectEvents` do not run, so whatever
  `sPlayerData`→`wPlayerData` restore put into `wObjectStructs` (option (a): a clean zeroed slot;
  option (b): stale ghost bytes) is exactly what sits in WRAM until the first warp. If (a) was
  done before save, CONTINUE is safe with no further action. If (b), the client must actively scan
  for and clear any struct whose `OBJECT_MAP_OBJECT_INDEX` matches the ghost's sentinel value
  (see Object slot budget) immediately after boot, before the first `HandleMap` tick, or a stale
  ghost sprite could render at the wrong position on the title-continue screen transition.
- Gold's `UNION`/`NEXTU` layout (`wObjectStructs` sharing physical WRAM with `wPlayerData2` when
  the union's other member is active, `ram/wram.asm` G, cited above) is a structural difference
  from Crystal's flat layout worth flagging for implementation but was not traced further in this
  pass — which other data legitimately overlaps `wObjectStructs`' bytes in Gold, and whether that
  creates an additional clobber window beyond the ones already covered by hooks 1/2/4, is
  `†UNVERIFIED`.

## Gold/Silver deltas from Crystal

| Area | Crystal (`C`) | Gold (`G`) | Citation |
|---|---|---|---|
| Object struct/map-object constants, `NUM_OBJECT_STRUCTS`/`NUM_OBJECTS`, field offsets | as above | **identical** field-for-field | `C constants/map_object_constants.asm:1-100`; `G` same path, same line range, diffed no changes found |
| `FindFirstEmptyObjectStruct` | `home/map_objects.asm:420-448` | byte-identical logic | `G home/map_objects.asm:420-448` |
| `NOCLIP_OBJS_F` check site in movement | `engine/overworld/npc_movement.asm:20-41` | identical | `G engine/overworld/npc_movement.asm:33` |
| `MapSetupScript_Warp` calls `LoadMapObjects`; `MapSetupScript_Continue` does not | same | same | `G data/maps/setup_scripts.asm:161-179` mirrors `C:161-179` (line numbers coincide) |
| `SavePlayerData` copies the whole `wPlayerData` span | `engine/menus/save.asm:497-508` | `engine/menus/save.asm:396-407` (different line numbers, same logic) | both cited above |
| **Player sprite table** | `GetPlayerSprite` branches Chris/Kris by gender (`overworld.asm:55-85`) | **`GetPlayerSprite` is Chris-only**, no gender branch, no `KrisStateSprites` (`overworld.asm:46-71`) | `G engine/overworld/overworld.asm:46-71` |
| `wObjectStructs` WRAM placement | flat, inside `wPlayerData..wPlayerDataEnd` (`ram/wram.asm:3038-3049`) | inside a `UNION`/`NEXTU` block within `wPlayerData1` (`ram/wram.asm`, cited above) — same save-inclusion outcome, different physical-overlap risk, `†UNVERIFIED` extent | both cited above |

Every hook in Patch surface (1, 2, 3, 4, 6) and the Save exclusion section was independently
verified against `G`, not asserted by analogy — the only Gen 2-general (not Crystal-specific)
claim not re-checked against `G` in this pass is the battle-dispatch architecture in hook 5
(`engine/battle/core.asm` was read only in `C`).

## Gate list

Bounded live-gate list for the post-RC implementation phase (not run in this pass — this is
research only, per the owner's post-RC ruling):

1. Runtime probe: on a map from the top-5 list above (e.g. Route32/NationalPark), confirm
   `FindFirstEmptyObjectStruct` returns non-zero-with-carry (a free slot exists) under normal play
   with all that map's `object_event`s active simultaneously if reachable.
2. Spawn the ghost via hook 1, confirm it renders with `NOCLIP_OBJS_F` set and does not block the
   local player's movement (resolves the "symmetric non-blocking" open question empirically even
   if the source trace is skipped).
3. Confirm the local player CAN or CANNOT walk into the ghost's tile — whichever the trace above
   leaves open, this closes it operationally.
4. Trigger a warp/map connection while the ghost is active; confirm hook 2 fires
   (`ClearObjectStructs` wipes it) and hook 1 re-arms it on the new map without a stale sprite
   frame.
5. Save with the ghost active, then load (CONTINUE); confirm no stale ghost struct renders before
   the first warp, using whichever save-exclusion control (a) or (b) above is implemented.
6. Enter and exit a battle while the ghost is active; confirm it freezes in place (no updates)
   during battle and resumes correctly on return, with no leftover struct corruption.
7. Confirm the ghost is not consumable/talkable in a way that corrupts scripted state (an `A`
   press on it should be a no-op or flavor text only, per RR's `interact_text` precedent).

## Open questions

- Are `WillObjectBumpIntoSomeoneElse`'s internals symmetric — does it also skip when the
  **target** struct (not just the mover) has `NOCLIP_OBJS_F` set, or only when the mover does?
  Not traced past the call site (`engine/overworld/npc_movement.asm:20-41`).
- `HandleObjectStep`/`STEP_TYPE_*` jumptable internals (`engine/overworld/map_objects.asm:29-`)
  were not walked; whether a passive `STEP_TYPE_STANDING`/`RESET` struct is fully inert against
  external per-frame field writes, or whether `OBJECT_LAST_MAP_X/Y` must also be kept in sync to
  avoid a stale-comparison glitch, is unconfirmed.
- Exact main-loop dispatch site that switches away from `OverworldLoop`/`HandleMap` on battle
  entry was not located in this pass (asserted architecturally from `HandleMap`'s jumptable
  structure and the absence of an object-struct teardown call in `engine/battle/core.asm`, not
  from reading `home/main.asm`).
- Whether `engine/overworld/wildmons.asm` iterates `wMapObjects`/`wObjectStructs` in any way an
  injected ghost could perturb — not read in this pass (carried over from R7, still open).
- Whether the top-5 static `object_event` maps (GoldenrodCity's 15, etc.) can ever have more than
  12 non-player entries concurrently true — needs a trace through each map's `MAPCALLBACK_OBJECTS`
  gating, not done here (carried over from R7).
- Gold's `UNION`/`NEXTU` overlap of `wObjectStructs` with `wPlayerData2` — what else physically
  shares those bytes, and whether that creates a clobber window beyond the ones already identified
  — not traced.
- Whether Pokégear/phone scripts or other scripted-movement systems reference object-struct
  indices by a fixed number that could collide with whichever index the ghost claims at runtime
  (`FindFirstEmptyObjectStruct` returns whatever is first free, not a fixed slot) — not checked.
