> **Coordinator correction (Codex `cx-51f03e2d`, 2026-09-21, verified on both HEAD clones):** (1) `GetJoypad` is not reached on every overworld tick: `HandleMapTimeAndJoypad` returns without it when `wMapEventStatus == MAPEVENTS_OFF` (`events.asm:193-199`), which `CheckPlayerState` sets during ordinary stepping (`:215-232`); text loops (`home/text.asm:891,968`) and the idle scrolling menu (`home/joypad.asm:313-314`) do reach it. (2) `wOverworldDelay` is a reset-to-2 per-iteration residual budget (`events.asm:177-191`), not an armed flag. (3) `_PlaySFX` ends with `wSFXPriority = 0` (`audio/engine.asm:2566-2568`), not 1; `_UpdateSound` returns while `wMusicPlaying` is clear (`:79-89`). (4) **`wObjectStructs`/`wMapObjects` are INSIDE `wPlayerData` and are saved to `sPlayerData`** (`ram/wram.asm:2993-3378`, `save.asm:498-508`; pokegold `:2397-2720`, `:396-406`): the 'never persisted' conclusion is FALSE. (5) CONTINUE uses `LoadMapAttributes_SkipObjects` and does not re-run `LoadMapObjects`. (6) The free-struct predicate is `FindFirstEmptyObjectStruct` (byte 0 == 0, `home/map_objects.asm:420-435`), not the sprite-entry count. (7) Gold selects `ChrisStateSprites` only (`overworld.asm:46-62`). Pokegold line map: Joypad stub `home/joypad.asm:1-6` both; `UpdateJoypad :16` both; `_UpdateSound` G `home/vblank.asm:143,205,256,297,317,396`.

# Native sound sites and peer-ghost feasibility for Gen 2

Resolves wayfinder tickets 16 (`docs/gen2/wayfinder/issues/16-native-sound-sites.md`) and 17
(`docs/gen2/wayfinder/issues/17-peer-ghost-feasibility.md`). Both are read-only; not edited.
Ticket 14 (the mailbox address itself) is out of scope — this assumes a mailbox exists
somewhere in always-mapped WRAM and answers only the site/feasibility questions.

## Pins

- `C` = **pokecrystal@7a7881d0d62e0ddbd82dcf10e7116807487ac651** (clone at
  `scratchpad/pret_head/pokecrystal`).
- `G` = **pokegold@656583c939d30f920a316177311a502dd222b57c** (clone at
  `scratchpad/pret_head/pokegold`). Not separately walked below — the brief's citable questions
  are all answered from `C`; every `G` claim would need its own file:line pass, so Gold is left
  as an open question rather than asserted-by-analogy.
- Gen 1 precedent: `patch/gen1/README.md`, `patch/gen1/src/slink.asm`, `lua/gen1/panel.lua`.
- Gen 3 precedent: `lua/peer_ghost_npc.lua:1-45`.
- Already-established Gen 2 facts (do not re-derive, cite instead): `docs/gen2/research/codex_checkpoint_and_linktrade.md`
  §A "DelayFrame, Joypad and native sound" (line ~81-85).

## A. Native sound

### A1. Entry points, bank, and SFX ids

`PlaySFX`, `PlayCry`, `PlayMusic`, `WaitSFX`/`WaitPlaySFX` are all bank-0 wrappers in
`home/audio.asm` (C `home/audio.asm:64-127` PlayMusic/PlayMusic2, `:129-178` PlayCry,
`:180-223` PlaySFX/WaitPlaySFX, `:225-245` WaitSFX). Each wrapper saves `hROMBank`, switches to
`BANK(_PlaySFX)` etc., calls the underlying `_PlaySFX`/`_PlayCry`/`_PlayMusic` in
`audio/engine.asm`, then restores the bank — the same call-through-bank-0 shape as Gen 1's
`PlaySound`, so it is always safe to call from bank 0 regardless of the caller's current bank.
`_PlaySFX` itself lives in `audio/engine.asm:2472`, inside `SECTION "Audio", ROMX`
(`audio.asm:1-3`, a floating linker-assigned bank, hence the bank-switch dance in the wrapper —
do not hardcode a bank number).

`constants/sfx_constants.asm` is the id table (211 lines, ids `$00`-`$d2`). There is **no
Gen-1-shaped small enum of "link / faint / dead-zone / memorial / trade / error"** — that framing
does not describe what the Gen 1 patch actually carries. The Gen 1 mailbox's `+7` byte carries
exactly **three** semantic codes, not six (`patch/gen1/README.md:47-71`,
`lua/gen1/panel.lua:31-34`):

| Gen 1 semantic code | Gen 1 played id (overworld bank) | Nearest Gen 2 `SFX_` analogue | Fit |
|---|---|---|---|
| `SFX_SUCCESS` (1) | `GET_ITEM_2 $89` | `SFX_ITEM` (`constants/sfx_constants.asm:4`) or `SFX_CAUGHT_MON` (`:5`) | Good — both are Gen 2's existing "got something good" cues, same semantic slot as Gen 1's item jingle. |
| `SFX_FAILURE` (2) | `DENIED $A5` | `SFX_WRONG` (`constants/sfx_constants.asm:28`, id `$19`) | Good — `SFX_WRONG` is Gen 2's own "invalid menu action" buzz, the same role `DENIED` plays in Gen 1. |
| `SFX_BOO` (3) | `TINK $8C` | No confirmed 1:1 analogue. `SFX_BUMP` (`:39`, id `$24`) is the closest "negative, low-stakes" candidate; `†UNVERIFIED` — this is a guess from the id's usual overworld role (bumping a wall/ledge), not a listened-to audio comparison. | Open — see Open questions. |

The Gen 1 patch also **re-resolves the id per audio bank at play time** because raw sound ids
are bank-local (`patch/gen1/README.md:56-59`, e.g. `GET_ITEM_2 $89` becomes `LEVEL_UP $86` in
the battle bank). Gen 2's `SFX_*` constants are a single flat namespace already resolved by
`sfx_pointers.asm` inside the one floating `"Audio"` ROMX bank (`audio.asm:1-8`), so **this
per-bank remapping problem does not exist in Gen 2** — a native SFX request only ever needs one
constant, not a per-bank table. This is a real simplification versus the Gen 1 design, not a gap.

### A2. Main-thread hook sites — the two-site rule does not carry over unchanged

Gen 1 needed two sites (`DelayFrame` bridge + `Joypad` reti-hijack) specifically *because* a
menu waiting on input in Gen 1 spins in `HandleMenuInput_`/`JoypadLowSensitivity` and **never
reaches `DelayFrame`** (`patch/gen1/README.md:49-54`). The already-established Gen 2 fact is the
opposite: **"Do not import 'menus never reach DelayFrame': Crystal's party-menu route within
StartMenu explicitly calls it... and text waits call GetJoypad/DelayFrames"**
(`docs/gen2/research/codex_checkpoint_and_linktrade.md` §A "DelayFrame, Joypad and native
sound"). Two more Gen-2-specific facts, verified directly against `C` for this ticket:

1. **`Joypad::` has no Gen 2 analogue to hijack.** It is a bare `reti` placeholder exactly as in
   Gen 1 (C `home/joypad.asm:1-6`, comment: "Replaced by UpdateJoypad, called from VBlank
   instead of the useless joypad interrupt"). Nothing calls it on the main thread, so there is no
   `call _Joypad` site to redirect the way Gen 1 redirected `$01A4`. The Gen 1 "second site" has
   no Gen 2 counterpart at all.
2. **`GetJoypad` is the actual per-frame, all-contexts site.** `HandleMap` — the overworld's main
   per-frame dispatch — calls `HandleMapTimeAndJoypad` unconditionally as its *first* action
   (C `engine/overworld/events.asm:140-142`), which calls `GetJoypad` directly
   (`:193-199`), skipped only when `wMapEventStatus == MAPEVENTS_OFF` (a scripted-freeze state,
   not ordinary walking). Text box waits also call `GetJoypad` on every spin
   (`home/text.asm:891,968`, `TextCommand_PAUSE`/`TextCommand_DOTS`). So `GetJoypad` is reached
   both from the ordinary overworld tick and from text/dialogue — the same two contexts Gen 1
   needed two separate hooks for.
3. **`DelayFrame` is NOT reached every overworld frame.** `HandleMap`'s tail calls
   `NextOverworldFrame`, which "returns immediately if `wOverworldDelay == 0`"
   (`docs/gen2/research/codex_checkpoint_and_linktrade.md` §A anchor 2, citing C
   `engine/overworld/events.asm:190-191`) — i.e. `DelayFrame` fires only when something has
   explicitly armed a delay, not on every idle walking frame. It is, however, reached from the
   `StartMenu` party route (`engine/menus/start_menu.asm:518`) and pervasively from text
   (`home/text.asm` `DelayFrames` calls, e.g. `:896,973`).

**Conclusion: the Gen 1 two-site pattern collapses to effectively one usable site in Gen 2 —
`GetJoypad`** (via a bank-0 redirect of its `call`/`ret`, the same "wrap and re-issue" technique
the Gen 1 bridge used at `patch/gen1/README.md:145-162`, since `GetJoypad::` is a plain bank-0
label in `home/joypad.asm:106`, no floating-bank complication). `DelayFrame` remains a secondary,
belt-and-braces site for the party-menu/text cases GetJoypad also happens to cover, but is not
load-bearing on its own because it is skipped during ordinary movement. This is a stronger
position than Gen 1's, not a weaker one: Gen 1 needed two hooks to *union* two disjoint
coverages; Gen 2's `GetJoypad` already unions them in one place.

†UNVERIFIED: whether `GetJoypad` is also reached while sitting idle inside the **StartMenu's own
list cursor** (`.GetInput`/`.loop` in `engine/menus/start_menu.asm:95-116`) — that loop reads
`hJoyLast`/`hJoyPressed` via `GetScrollingMenuJoypad` → `GetMenuJoypad`
(`home/menu.asm:30-48`), which does **not** itself call `GetJoypad` inside the loop body; the
mirrors it reads must be kept fresh by whatever drives the outer redraw loop. This was not
traced to a per-iteration `GetJoypad` call within the time budget of this pass and is listed
under Open questions.

### A3. Is a VBlank-time `PlaySFX` safe? No — same hazard class as Gen 1

`VBlank_Normal` (and every other VBlank handler variant — Cutscene, CutsceneCGB, Serial,
Credits, DMATransfer, SoundOnly) calls `_UpdateSound` unconditionally, every frame, already
(C `home/vblank.asm:137-144` for Normal; `:156-158`, `:212-216`, `:291-295`, `:339-343`,
`:381-385`, `:419-423` for the rest). This is **not** evidence that calling `PlaySFX` (a
one-shot "start a new sound" call, distinct from `UpdateSound`'s per-frame channel-tick) from
VBlank would be safe. `PlaySFX`/`_PlaySFX` bank-switches and mutates `wCurSFX`/channel flags
with no `DI`/`EI` guard around the sequence (C `home/audio.asm:180-218`,
`audio/engine.asm:2472` onward). If VBlank fires while the main thread is already mid-way
through a `PlaySFX`/`PlayMusic` call (interrupts are enabled during ordinary play — see the
explicit `ei`/`di` bracketing VBlank_Cutscene's own `_UpdateSound` call at
`home/vblank.asm:211-217`, which exists only because that variant needs it, implying interrupts
are otherwise live), a **second** `PlaySFX` invoked from inside that same VBlank would be
exactly the Gen 1 reentrancy hazard (`patch/gen1/README.md:84-89`): corrupting `wCurSFX`,
channel flags, or the `hROMBank` save/restore stack. The two failure modes documented for Gen 1
`PlaySound` (fade-swallow, reentrant corruption) were diagnosed from Gen 1's specific
`wNewSoundID` guard-clear window and have not been separately confirmed in Gen 2's engine, but
the structural precondition for the reentrancy hazard — main-thread callers of a
non-interrupt-safe `PlaySFX` with interrupts enabled — is confirmed present. **Recommendation
unchanged from Gen 1: service the mailbox's SFX request on the main thread (`GetJoypad` hook),
never call `PlaySFX` from VBlank.**

### A4. State to respect

- **`wCurSFX`** (`ram/wram.asm:101`) — id of the sfx currently playing on channels 5-8.
  `PlaySFX`'s own priority arbitration (C `home/audio.asm:180-218`) already compares the
  requested id against `wCurSFX` with `cp e` / `jr c, .done` — **lower numeric id wins**
  (`SFX_DEX_FANFARE_50_79 = $00` is highest priority, `SFX_...` near `$d2` is lowest). A native
  SFX request should pick a low-numbered id if it must not be silently dropped by a busier
  higher-priority effect already playing.
- **`wSFXPriority`** (`ram/wram.asm:82`) — set to 1 by `_PlaySFX` (`audio/engine.asm:2468`) and
  read by the music-restart path (`:143`) to decide whether to resume music after an SFX
  finishes; a native SFX request going through `PlaySFX` already participates in this
  bookkeeping correctly and needs no extra handling.
- **`wMusicPlaying`** (`ram/wram.asm:12`) — nonzero while music plays; `PlaySFX`'s internal
  `MusicOff`/channel-clear sequence (`audio/engine.asm` around `_PlaySFX`) already coordinates
  with this, again as long as the call goes through `PlaySFX` and not a hand-rolled
  channel write.
- **`CheckSFX`/channel-busy flags** (`wChannel5Flags1`.. `wChannel8Flags1`,
  `SOUND_CHANNEL_ON` bit — `home/audio.asm:504-523`, `constants/audio_constants.asm:82`) —
  `PlaySFX` already checks these before playing; a caller does not need to re-check them, but
  should be aware a request can be silently dropped (not queued) if a higher-priority id is
  currently on a channel. The Gen 1 240-frame stamped hold existed to survive exactly this drop
  case across a fade/bank-change; whether Gen 2 needs an equivalent retry/hold loop is answered
  in the verdict below.

## B. Peer ghost

### B1. Map object model

- `wObjectStructs` / `NUM_OBJECT_STRUCTS = 13` (`constants/map_object_constants.asm:38`,
  declared `ram/wram.asm:3038-3039`) — the **active, animatable** struct pool. `wPlayerStruct`
  is struct 0 (`wram.asm:3039`, `object_struct wPlayer`). Fields: `OBJECT_SPRITE`,
  `OBJECT_MAP_OBJECT_INDEX`, `OBJECT_FLAGS1`, `OBJECT_FLAGS2`, `OBJECT_PALETTE`,
  `OBJECT_DIRECTION`, `OBJECT_MAP_X`/`OBJECT_MAP_Y`, `OBJECT_SPRITE_X`/`OBJECT_SPRITE_Y`, etc.
  (`constants/map_object_constants.asm:1-33`, 33 fields, `OBJECT_LENGTH` padded to `_RS`).
- `wMapObjects` / `NUM_OBJECTS = 16` (`constants/map_object_constants.asm:100`, declared
  `ram/wram.asm:3049-3050`) — the **placement** pool (per-map object-event data once loaded).
  `wPlayerObject` is object 0 (`PLAYER_OBJECT EQU 0`, `:99`). Fields: `MAPOBJECT_SPRITE`,
  `MAPOBJECT_Y_COORD`/`MAPOBJECT_X_COORD`, `MAPOBJECT_MOVEMENT`, `MAPOBJECT_PALETTE`,
  `MAPOBJECT_TYPE`, `MAPOBJECT_SCRIPT_POINTER`, `MAPOBJECT_EVENT_FLAG`
  (`constants/map_object_constants.asm:80-97`).
- Loading: `LoadMapObjects` (`engine/overworld/map_setup.asm:78-83`) runs a
  `MAPCALLBACK_OBJECTS` map callback, then `farcall LoadObjectMasks` and
  `farcall InitializeVisibleSprites`. The per-map `object_event` list itself
  (`macros/scripts/maps.asm` `def_object_events`/`object_event`) is declared inline in each
  `maps/*.asm` file, e.g. `maps/GoldenrodCity.asm:587-602`.
- **Is a spare slot guaranteed on every map?** Not by raw count. `GoldenrodCity.asm` declares
  **16** `object_event` lines (`:588-602` plus the header), i.e. exactly `NUM_OBJECTS` if all
  fired at once — but most are gated by mutually-relevant `EVENT_GOLDENROD_CITY_CIVILIANS` /
  `EVENT_GOLDENROD_CITY_ROCKET_TAKEOVER` / `EVENT_RADIO_TOWER_ROCKET_TAKEOVER` flags
  (`:588-601`) that correspond to different story phases and are unlikely to be concurrently
  true; whether they are ever *provably* mutually exclusive was not traced through
  `CheckEventFlag`/`MAPCALLBACK_OBJECTS` in this pass — `†UNVERIFIED`. The **tighter** and
  simpler constraint is `NUM_OBJECT_STRUCTS = 13` (12 non-player struct slots): even if all 16
  raw map objects on a map could coexist, only 12 NPCs (plus the player) can hold an active,
  rendered/animated struct at once. Whether any shipped map actually saturates 12 concurrent
  NPCs was not checked map-by-map; treat "a spare struct exists on the player's current map" as
  needing a runtime check (count non-`-1` `OBJECT_SPRITE` entries in `wObjectStructs`) rather
  than a static guarantee.
- **Player sprite/palette selection.** `GetPlayerSprite` (`engine/overworld/overworld.asm:55-75`)
  picks `ChrisStateSprites` or `KrisStateSprites` based on `wPlayerGender`
  (`PLAYERGENDER_FEMALE_F` bit) — or forced male via `wPlayerSpriteSetupFlags`'
  `PLAYERSPRITESETUP_FEMALE_TO_MALE_F` (`:58-63`) — then indexes by `wPlayerState` (biking,
  surfing, etc., `:66-68`). This confirms Gen 2 already has a working "pick an arbitrary
  player-shaped avatar by gender+state" mechanism; a peer ghost showing the partner's own
  Chris/Kris choice is a straightforward reuse of this table, not new machinery.

### B2. Per-frame hook

`HandleMap` calls `HandleMapObjects` → `farcall HandleNPCStep` /
`farcall _HandlePlayerStep` every overworld tick (`engine/overworld/events.asm:151`,
`:203-207`), i.e. at the game's native ~60 Hz. A Lua frame hook writing `OBJECT_MAP_X`/
`OBJECT_MAP_Y`/`OBJECT_SPRITE_X`/`OBJECT_SPRITE_Y`/`OBJECT_DIRECTION` directly into one
`wObjectStructs` entry every frame (or every other frame for the ghost's ~30 Hz feed) is cheap —
the same "poke object struct fields from Lua each frame" recipe the Gen 1 clone used
(`docs_gen2_wayfinder` cites Gen 3's engine-object approach; the Gen 1 clone technique note in
memory describes the same direct-struct-write pattern). No engine change is required for this
part: BizHawk's Lua can already read/write `wObjectStructs`/`wMapObjects` at their known
addresses once a profile pins the map's WRAM base.

### B3. Collision

`OBJECT_FLAGS1` carries `NOCLIP_TILES` (bit 4) and `NOCLIP_OBJS` (bit 6)
(`constants/map_object_constants.asm:48-56`: `INVISIBLE`(0), `WONT_DELETE`(1),
`FIXED_FACING`(2), `SLIDING`(3), `NOCLIP_TILES`(4), `MOVE_ANYWHERE`(5), `NOCLIP_OBJS`(6),
`EMOTE_OBJECT`(7)). Setting `NOCLIP_OBJS` on the injected ghost's struct should make it
non-blocking to the player's own collision the same way Gen 1/Gen 3 ghosts avoid trapping the
local player. `OBJECTTYPE_SCRIPT`/`OBJECTTYPE_ITEMBALL`/`OBJECTTYPE_TRAINER`/`OBJECTTYPE_3..6`
(`constants/script_constants.asm:139-145`) select the object's *interaction* behavior on `A`
press, not its collision; a ghost wanting no trainer-battle-style interaction should avoid
`OBJECTTYPE_TRAINER` and likely wants `OBJECTTYPE_SCRIPT` pointed at a no-op, mirroring the Gen 3
`peer_ghost_npc.lua` header's "interact_text" flavor-text-only interaction
(`lua/peer_ghost_npc.lua:29,37`).

### B4. What breaks

- **Wild encounters**: driven by the player's own tile/step counters, not by other map objects;
  an injected non-interactive ghost object should not affect encounter rolls. Not separately
  re-verified against `engine/overworld/wildmons.asm` in this pass — `†UNVERIFIED` but low risk
  by construction (encounter code has no reason to iterate `wMapObjects`).
- **Map connection loads / warps**: `DeleteMapObject` (`engine/overworld/map_objects.asm:5-24`)
  zero-fills an `OBJECT_LENGTH`-sized struct and marks the corresponding map object's
  `OBJECT_SPRITE` as `-1`; it is called from object-step handling and movement code
  (`engine/overworld/map_objects.asm:95,1516,1711,1749`; `engine/overworld/movement.asm:240`).
  A `LoadMapObjects` re-run on warp (`engine/overworld/map_setup.asm:78-83`) will re-populate
  `wMapObjects`/`wObjectStructs` from the new map's static `object_event` list — an
  injected/foreign ghost struct not backed by a real `object_event` entry will almost certainly
  be **clobbered or orphaned** across a map transition and must be explicitly re-injected by the
  driving Lua/patch after every warp, exactly as Gen 3's companion patch owns "spawn/despawn/
  map-change/gfx-change lifecycle" per `lua/peer_ghost_npc.lua:15-16`. This is the single
  biggest lifecycle cost of the Gen 2 approach versus Gen 3's engine-native object-event pool.
- **Save**: `ram/sram.asm` has **no** `sMapObjects`/`sObjectStructs` declaration (full-file
  grep, zero hits) — map objects are pure runtime WRAM, rebuilt from each map's static data on
  load, never persisted. An injected ghost struct is therefore never accidentally saved into the
  player's SRAM, but also never survives a save/reload — again matching the "re-inject after
  every map/session boundary" lifecycle already assumed above.

### B5. Suspend in battle

Not independently traced for Gen 2 in this pass. Gen 1/Gen 3 precedent both suspend the ghost
while `wIsInBattle`/`wBattleMode`-equivalent is set; Gen 2's `wBattleMode`
(`ram/wram.asm:2720`, values documented in
`docs/gen2/research/codex_checkpoint_and_linktrade.md` §A predicate table, wild/trainer =1/2) is
the natural equivalent gate — the overworld's own `wObjectStructs` are not iterated by the
battle engine, so a ghost simply stops receiving frame updates while `wBattleMode != 0` and
resumes on return, no different from how Gen 1's peer ghost is "suspended in battle" per the
shipped feature summary. `†UNVERIFIED` against Gen 2 battle-entry source directly.

## Verdicts

**A (native sound): FEASIBLE, single main-thread site, simpler than Gen 1.** Hook `GetJoypad`
(`home/joypad.asm:106`) with the same wrap/re-issue technique as Gen 1's `DelayFrame` bridge;
this single site already covers both the ordinary overworld tick (via `HandleMapTimeAndJoypad`)
and text/menu waits, which is why Gen 1 needed two sites and Gen 2 plausibly needs only one. Do
not call `PlaySFX` from VBlank — same reentrancy class of hazard as Gen 1, structurally present
(interrupts live, no `DI`/`EI` guard in `PlaySFX`), not separately measured. Semantic-code
mapping: success/failure map cleanly onto existing `SFX_ITEM`/`SFX_CAUGHT_MON` and `SFX_WRONG`;
the "boo" analogue is unresolved (see Open questions). Whether the 240-frame stamped hold is
needed at all in Gen 2 is **open** — it existed in Gen 1 to survive a specific fade-swallow bug
and a per-bank id remap, neither of which has a confirmed Gen 2 analogue; `PlaySFX`'s own
priority arbitration (drop-if-busier, not hold-and-retry) may already be sufficient if the
native cue is given a low (high-priority) id, or a simple bounded retry loop at the `GetJoypad`
hook site may be substituted for the stamped counter. Minimal patch surface: one `home/joypad.asm`
call-site redirect (bank 0, no floating-bank complication) plus a small resolver mapping
semantic code → `SFX_*` constant → `PlaySFX` call.

**B (peer ghost): FEASIBLE-WITH-PATCH, lifecycle cost concentrated at map transitions.** The
struct/object model (`wObjectStructs`/`wMapObjects`, `NUM_OBJECT_STRUCTS=13`,
`NUM_OBJECTS=16`), the `NOCLIP_OBJS` collision-disable bit, the existing Chris/Kris
sprite-selection table, and the per-frame `HandleMapObjects` hot path all support a Lua-driven
ghost analogous to the Gen 1 clone technique (direct WRAM struct pokes each frame) without
requiring a Gen 2 companion patch for the steady-state motion/render path. What **does** need
patch-level (or at minimum, disciplined Lua-side) ownership is the lifecycle Gen 3's companion
patch already owns: re-acquiring/re-writing a free struct+map-object pair after every warp and
every `LoadMapObjects` re-run (since nothing persists the injected object across those), and
gating updates on `wBattleMode`. Minimal patch surface, if a native (not pure-Lua) approach is
preferred: a hook into `LoadMapObjects`'s tail (`engine/overworld/map_setup.asm:78-83`) to
re-arm the ghost's struct/object pair on every map load, mirroring Gen 3's frame-hook spawn but
targeting Gen 2's static-map-data model instead of RR's dynamic `gObjectEvents` pool. Whether a
free struct/object slot is available on every map is unverified by static analysis alone
(`NUM_OBJECT_STRUCTS=13` is the binding constraint, not `NUM_OBJECTS=16`) and should be checked
at runtime (BizHawk probe scanning `wObjectStructs` for an all-`-1` `OBJECT_SPRITE` entry) before
committing to the approach on any specific map.

## Open questions

- Which Gen 2 `SFX_*` id best matches Gen 1's `TINK`/"boo" semantic (negative, low-stakes,
  distinct from the "wrong menu action" buzz)? `SFX_BUMP` (`constants/sfx_constants.asm:39`) is
  a guess, not a verified audio match.
- Does Gen 2's `PlaySFX`/fade path have a Gen-1-shaped "swallowed during fade" bug (the specific
  `wNewSoundID` guard-clear window that motivated Gen 1's 240-frame stamped hold)? Not traced
  through `wMusicFade`/`FadeToMapMusic` handling in this pass.
- Is `GetJoypad` actually refreshed every frame inside the `StartMenu` list-cursor loop itself
  (`engine/menus/start_menu.asm:95-116`, via `GetScrollingMenuJoypad`/`GetMenuJoypad`,
  `home/menu.asm:30-48`), or only on entry/exit? If only on entry/exit, a native SFX request
  posted while the cursor sits idle in the list could stall until the next A/B/D-pad edge.
- Are `EVENT_GOLDENROD_CITY_CIVILIANS`, `EVENT_GOLDENROD_CITY_ROCKET_TAKEOVER`, and
  `EVENT_RADIO_TOWER_ROCKET_TAKEOVER` (`maps/GoldenrodCity.asm:588-601`) actually mutually
  exclusive at every point a player can stand on that map, or can more than 12 non-player
  `object_event`s be concurrently true (exceeding `NUM_OBJECT_STRUCTS - 1`)? Needs a trace
  through `MAPCALLBACK_OBJECTS`/`CheckEventFlag`, not done here.
- Does wild-encounter code (`engine/overworld/wildmons.asm`, not read in this pass) iterate
  `wMapObjects`/`wObjectStructs` in any way an injected ghost object could perturb?
- Is `wBattleMode` (or an equivalent) actually sufficient to gate ghost frame-updates safely, or
  does Gen 2 have its own battle-entry object-struct teardown (paralleling `DeleteMapObject`)
  that would race a still-running Lua frame hook? Not traced through Gen 2 battle-entry source.
- Pokegold (`G`) was not independently walked for either ticket; every citation above is `C`
  only. If Gen 2 support must cover Gold/Silver as well as Crystal, re-verify file:line pins
  against `G` before implementation — Gold's overworld/audio file layout is expected to be
  close but was not diffed here.
