# Peer Ghost — handoff notes (READ THIS FIRST)

Branch: `feat/rom-patch-companion` (worktree `condescending-bassi-9175e6`). Companion patch for
Radical Red. The peer ghost shows your soul-link partner as a walking NPC in your RR overworld.

## ✅ RESOLVED (2026-06-01) — read this first; the rest is historical

The two real defects are fixed (patched md5 `b73022dbda3f467ccce4a3ea155b1b4c` — re-apply the UPS):

1. **Uneven/unnatural movement — FIXED by abandoning held movements for the clone's sub-pixel-LERP
   model, ported into C.** The held-movement (tile-quantized) driver could not match a sampled feed
   (it oscillated walk→catchup-run→empty→freeze; a `test_live_ghoststutter` repro showed a 10-frame
   freeze at every tile boundary). The patch now spawns the OE only for its sprite slot / collision /
   palette, **neutralizes its sprite callback**, and each frame **LERPs `pos1` toward the partner's
   broadcast sub-pixel WORLD-PIXEL position** (continuous + speed-agnostic) + plays the partner's
   live `animNum`. `test_live_ghoststutter` now slides ~1px/frame, longest frozen run = **1** (was 10).

2. **Ghost showed YOU, not the partner — FIXED.** The partner is another real player; the ghost now
   renders **their** avatar: the sender broadcasts their live sprite `images`/`anims` ROM ptrs +
   their true 16-colour palette (`pcol`); the patch points the ghost sprite at those ptrs and paints
   the colours into a **dedicated OBJ palette slot (15)**, so the player's own slot 0 is never
   touched (no corruption). `test_live_ghostavatar` verifies the override + slot isolation.

Wire (per ~20 Hz): `{mg,mn, x,y=WORLD-PIXELS, f, mv, an=animNum, run, gfx, imgs, anim, pcol}`. C
driver = `drive_ghost()` (LERP) + `apply_avatar()` in `handlers.c`. GhostState is now LERP-shaped
(wx/wy/face/mv/an/snap/dispx/dispy/cx/cy/imgs/anims; no step ring). Lua: `MB.ghost_set_pos/snap/
set_avatar` (`mailbox.lua`); `peer_ghost_npc.lua` forwards world-px + avatar. Live tests green:
`ghoststutter, ghostavatar, ghostreceiver, ghostwarp, peerinteract, msgboxdismiss`. The old
tile-walk tests (`ghostdrive/ghostslide/ghostanim/ghostmove`) were retired (driver replaced).

**Deferred:** bike/surf/fishing avatar variants (size-matched re-spawn + bigger VRAM tiles);
day/night tint on the avatar palette (true colours show, un-tinted at night). **Final gate = the
two-instance visual run** (two BizHawk, different avatars each side).

---

## (HISTORICAL) TL;DR for the next agent — pre-fix

The architecture (engine-driven held-movement NPC) is sound and all the lifecycle bugs are fixed
(spawns, palette-safe, survives warps, dismissable talk). **The one REMAINING, UNSOLVED problem is
that the ghost's walk looks "uneven and unnatural" compared to the player** — reported repeatedly by
the user, still present as of md5 `09c21212a856b820ae6618ba4b7d3161`.

**I have been chasing this against headless tests that PASS while the real bug PERSISTS.** That is the
trap to escape. See "Why the tests lie" below. The most likely real cause and the recommended fix are
in "Root-cause hypothesis" and "Recommended fix" — start there. Do NOT keep tuning the single-instance
slide/anim tests; they are green and they are not measuring the thing the user sees.

The user's exact words across iterations: *"They are not using any animations"* → *"Theres no subpixel
movement"* → (after each "fix" + green test) → **"Its literally the same."**

---

## Data path (end to end)

Partner A's client broadcasts A's position; Partner B's patch walks an NPC ("ghost of A") around B's
overworld to mirror it. Symmetric.

1. **Sender** — `lua/clients/gen3_frlge_client.lua` ~line 1470, inside `on_frame`, RR + overworld only,
   **every 3rd frame (`frame_count % 3 == 0`, ~20 Hz)**:
   ```lua
   send({ event="ghost_pos",
          mg=u8(OE+0x0A), mn=u8(OE+0x09),          -- map group, num
          x=s16(OE+0x10), y=s16(OE+0x12),          -- TILE coords (currentCoords)
          f=facing(1..4), mv=(moving?1:0),
          run=(anim>=8 ? 1:0),                     -- GO_FAST+ (dash/bike) -> ghost runs
          gfx=u8(OE+0x05) }, "ghost_pos", true, true)
   ```
   `OE = MB.player_oe()` (player is NOT always slot 0 — read `gPlayerAvatar.objectEventId` @
   `0x02037078 + 0x05`). NOTE: it broadcasts only the player's **current integer tile**, not the
   sub-tile pixel position and not the discrete step history.

2. **Server** — `server/state.py` `_handle_ghost_pos` relays `{mg,mn,x,y,f,gfx,mv,run}` to the partner,
   **ephemeral + coalesced** (only the latest is kept if the partner is behind). `_handle_peer_interact`
   notifies the partner with a "waved at you" msgbox.

3. **Receiver parse + dispatch** — `gen3_frlge_client.lua` ~line 197 parses the JSON, ~line 594
   dispatches `cmd=="ghost_pos"` → `PG.on_ghost_pos({mg,mn,x,y,f,gfx,mv,run})`.

4. **Receiver driver (Lua)** — `lua/peer_ghost_npc.lua`. `on_frame`: read local player map via
   `MB.player_oe()`; if partner on **same map**, spawn once (`MB.ghost_spawn(mygfx)`, using the LOCAL
   player's gfx — see "Known issue: avatar") and **each tick** post the partner's tile into the shared
   EWRAM block via `MB.ghost_set_target(g.x, g.y, g.f, g.run, mygfx)`. If not same map, `ghost_clear()`.
   Polls `MB.peer_interact_count()` for talk-to-ghost.

5. **Driver (C, the real engine work)** — `patch/src/handlers.c` `drive_ghost()`, called every frame
   from `slink_hook`. Reads the EWRAM `GhostState` and walks a real object-event toward the target tile
   using the engine's native held-movement API. THE ENGINE owns animation, sub-pixel slide, palette,
   day/night tint, culling, collision. See the function in full below.

---

## `GhostState` shared EWRAM block @ `0x0203F850`

Patch reads it every frame; Lua writes it. In the free gap between the mailbox (ends `0x0203F840`) and
`AM`@`0x0203F8C0`.

| off | field      | meaning |
|-----|------------|---------|
| 0   | active     | 1 = ghost should exist + be driven |
| 1   | oeId       | object-event id the hook owns (`0xFF` = not spawned) |
| 2   | gfxId      | graphicsId Lua wants (change ⇒ re-spawn: bike/surf/fish) |
| 3   | curGfx     | graphicsId currently spawned |
| 4   | localId    | sentinel localId (`0xF0`) marking "this is our ghost" |
| 5   | catchup    | hysteresis: 1 = running to catch up (set ≥3 behind, clear ≤1) |
| 6   | tx (s16)   | target tile x (object-event currentCoords space) |
| 8   | ty (s16)   | target tile y |
| 10  | tface      | target facing 1=S 2=N 3=W 4=E (idle facing on arrival) |
| 11  | run        | speed hint: 1 = partner dashing → run |
| 12  | pmapGroup  | player's last map group the hook recorded |
| 13  | pmapNum    | player's last map num |

Opcodes: `OP_GHOST_SPAWN=14` (args [0]=gfxId [1]=localId; hook spawns next frame), `OP_GHOST_CLEAR=15`
(hook does the clean `RemoveEventObject`). Per-tick target is written by Lua directly into the struct
(no opcode churn). Lua mirror: `lua/mailbox.lua` (`MB.GH=0x0203F850`, field offsets, `MB.player_oe()`,
`MB.ghost_spawn/clear/oe/set_target`).

---

## The C driver as it stands (`drive_ghost()`), annotated

```c
static void drive_ghost(void) {
    if (!GH->active) { if (GH->oeId != 0xFF) ghost_remove(); return; }
    u32 player = player_oe();
    u8 pg = R8(player+0x0A), pn = R8(player+0x09);
    // (a) map change -> warp rebuilt OE slots; clean-remove ours, re-spawn on new map
    if (GH->oeId != 0xFF && (pg != GH->pmapGroup || pn != GH->pmapNum)) ghost_remove();
    GH->pmapGroup = pg; GH->pmapNum = pn;
    // (b) gfx change (bike/surf/fish) -> re-spawn with the new sprite
    if (GH->oeId != 0xFF && GH->gfxId != GH->curGfx) ghost_remove();
    // (c) spawn once adjacent to the player
    if (GH->oeId == 0xFF) {
        if (R8(sScriptContext2Enabled)) return;            // not mid-dialogue/fade
        s16 px=R16(player+0x10), py=R16(player+0x12); u8 elev=R8(player+0x0B)&0x0F;
        int oe = SpawnSpecialObjectEventParameterized(GH->gfxId, 0, GH->localId, px, py+1, elev);
        if (oe >= 16) return;                              // no free slot; retry next frame
        GH->oeId=oe; GH->curGfx=GH->gfxId; fixup_palette(oe);
        SS->pi_oe=oe; SS->pi_armed=1;                      // auto-arm talk-to-ghost
        return;
    }
    u32 g = gObjectEvents + GH->oeId*OE_STRIDE;
    // (d) slot freed/reassigned under us -> forget
    if (!(R8(g)&1) || R8(g+0x08)!=GH->localId) { GH->oeId=0xFF; return; }
    // (e) only act once the previous step FINISHED  (st: 0=finished 16=idle else=busy)
    u8 st = EventObjectClearHeldMovementIfFinished((void*)g);
    if (st != 0 && st != 16) return;
    s16 gx=R16(g+0x10), gy=R16(g+0x12);
    int dx=GH->tx-gx, dy=GH->ty-gy, adx=abs(dx), ady=abs(dy);
    // (f) too far -> snap (warp/desync)
    if (adx > GHOST_SNAP_TILES || ady > GHOST_SNAP_TILES) {        // GHOST_SNAP_TILES = 10
        MoveEventObjectToMapCoords((void*)g, GH->tx, GH->ty);
        EventObjectTurn((void*)g, GH->tface); return;
    }
    // (g) arrived -> idle, FACE the partner's facing      <<<<<< the stutter lives here
    if (dx==0 && dy==0) {
        GH->catchup=0;
        EventObjectSetHeldMovement((void*)g, GetFaceDirectionMovementAction(GH->tface));
        return;
    }
    // (h) step toward target on larger-gap axis; match partner gait, hysteresis catch-up >=3 tiles
    u32 gap = adx+ady;
    if (gap>=3) GH->catchup=1; else if (gap<=1) GH->catchup=0;
    u32 dir = (adx>=ady) ? (dx>0?DIR_EAST:DIR_WEST) : (dy>0?DIR_SOUTH:DIR_NORTH);
    u8 action = (GH->run||GH->catchup) ? GetWalkFastMovementAction(dir)
                                       : GetWalkNormalMovementAction(dir);
    EventObjectSetHeldMovement((void*)g, action);   // plain Set; engine animates + alternates legs
}
```

Engine fn pointers + offsets are in `patch/src/ADDRESSES.md` (cross-validated BPRE.ld ↔ capstone-on-RR).
Key: `EventObjectSetHeldMovement` 0x8063CA5, `...ClearHeldMovementIfFinished` 0x8063D7D,
`...ClearHeldMovementIfActive` 0x8063D1D, `GetFaceDirectionMovementAction` 0x8063EB9,
`GetWalkNormalMovementAction` 0x8063F2D, `GetWalkFastMovementAction` 0x8063FB1, `RemoveEventObject`
0x805E4B5, `MoveEventObjectToMapCoords` 0x805F725, `EventObjectTurn` 0x805F219,
`SpawnSpecialObjectEventParameterized` 0x805E831. DIR_SOUTH=1 NORTH=2 WEST=3 EAST=4.

---

## Root-cause hypothesis for "uneven/unnatural" (READ)

**The ghost chases the partner's latest INTEGER TILE; it does not reproduce the partner's STEP STREAM.**
Consequences that produce visible stutter:

1. **Stop-at-tile (branch g).** The partner moves continuously (sub-tile) but broadcasts only its
   current integer tile, ~20 Hz, and the tile value changes only once per ~16 frames (walk) / ~8 (run).
   So the ghost: walks one tile → `dx==dy==0` → branch (g) → **STOPS and faces** → waits for the next
   tile to arrive → walks one tile → stops … = walk-stop-walk-stop. The player never stops between
   tiles because real input is continuous. **This is the most likely "uneven/unnatural" cause.**

2. **Quantization + jitter.** Network coalescing + 20 Hz sampling means the target tile can jump by 0
   for several frames then by 1–2 at once; combined with the per-tile "finished" gate, the cadence is
   irregular.

3. **Atomic held-movement steps don't pipeline.** Each step runs to completion before the next is
   issued (branch e gate). There is no look-ahead, so even with a moving partner the ghost cannot start
   the next tile early — there is a micro-pause at every tile boundary.

The player avatar, by contrast, is driven by `MOVEMENT_TYPE_PLAYER`/input which chains steps with no
re-decision gap. So "compared to the player character" it will always look worse until the ghost is fed
a continuous step stream rather than a sampled position.

### Why the headless tests lie
`test_live_ghostslide` / `test_live_ghostanim` post the SAME far target (`px+7`) **every frame**. The
ghost therefore ALWAYS has somewhere to go and never hits branch (g), so it slides continuously and
animates fully → tests PASS. The real feature almost never has a 7-tile-away static target; it has a
0–1-tile target updated in bursts → branch (g) fires constantly → stutter. **The tests do not exercise
the failure mode.** Any further work MUST first build a test that reproduces it (see below).

---

## Recommended fix (CFRU's actual model — we only half-adopted it)

CFRU `follow_me.c` is smooth because the follower walks a **logged breadcrumb trail** of the player's
ACTUAL discrete steps, exactly one step behind, consuming one queued step each time it finishes one
(`PlayerLogCoordinates` + `DetermineFollowerDirection/State`). It never "chases a sampled position" and
never stops mid-trail while the leader is moving. We adopted the held-movement *mechanism* but kept a
"chase the latest tile" *policy*, which is the part that stutters.

Two ways to close the gap, in order of preference:

**Option A — broadcast discrete steps, queue + consume them (closest to CFRU, best result).**
- Sender: detect each time the player's tile changes (a committed step) and send a `step` event with the
  direction + run flag (one message per tile actually walked), instead of/in addition to sampled
  position. Cheap and exact.
- Receiver/patch: maintain a small ring buffer of pending steps in `GhostState`; `drive_ghost` consumes
  one per "finished", so the ghost reproduces the partner's exact path + cadence one step behind. No
  stop-at-tile because there is always a queued step while the partner is moving; the ghost naturally
  comes to rest only when the partner does (queue drains). Add a max-queue clamp → snap if it overflows
  (desync). This is the canonical fix and will look right.

**Option B — keep position broadcast, add look-ahead extrapolation (smaller change, decent result).**
- In branch (g)/(h): when `GH->mv` (partner moving) is set and the ghost has reached the last target
  tile, DON'T stop — issue one more step in `GH->tface` (predicted next tile) to keep continuous motion,
  and only fall to "face/idle" after N frames with `mv==0` (partner actually stopped). Requires
  broadcasting/threading the `mv` flag all the way into `GhostState` (today `mv` is sent and parsed but
  is NOT written into `GhostState`/consumed by `drive_ghost` — wire it through). Risk: over-shoot past
  where the partner stopped, corrected next tile (a small jiggle on stop). Tune with a 1-tile lead cap.

Either way: the fix is about **continuity of the target stream**, not about animation flags or snap
thresholds (both already correct).

---

## What has ALREADY been tried (don't repeat)

- **Lua "puppet" approach (original, ~700 lines, deleted).** Hand-wrote sprite pos/anim/visibility +
  OE coords every frame. Caused vanishing, corrupt palette, post-warp "stray trainer with collision",
  un-dismissable message. ROOT CAUSE of all of those: fighting the engine. Replaced by the
  engine-driven held-movement model. **Do not go back to puppeting.**
- **player not always slot 0** → `player_oe()` reads `gPlayerAvatar.objectEventId`. Fixed "ghost spawned
  oeId=0 but invisible".
- **Palette corruption for non-matching avatars** → ghost uses the LOCAL player's gfx (same palette
  slot, correct colors). Partner's real avatar deferred (known issue below).
- **Warp orphan** → `drive_ghost` owns clean removal on map change (branch a).
- **Un-dismissable wave** → `run_sign_msgbox()` builds a 9-byte field script
  (`loadword 0,SLINK_TEXT_BUF ; callstd MSGBOX_SIGN(3) ; end`) via `ScriptContext1_SetupScript`
  (lockall→message→waitbuttonpress→releaseall), guarded on `sScriptContext2Enabled`. Verified
  dismissable. Shared by talk-to-ghost and `OP_SHOW_MESSAGE`.
- **"No animation"** → was previously "fixed" by force-writing `animBeginning` (sprite+0x3F|=0x04) +
  clearing `animPaused` each step. **REMOVED** — it marched on one lead foot (stiff). Plain
  `SetHeldMovement` + the finished-gate lets the engine play its full native walk cycle (test now shows
  `animCmdIndex 0,1,2,3` / 6 distinct frame images vs the forced version's `0,1` / 4). Animation is
  GOOD now in isolation.
- **"No subpixel movement"** → was the snap threshold; raised `GHOST_SNAP_TILES` 4→10. Slide verified
  2px/frame, 0 jumps in isolation.
- **Walk/run flicker** → replaced ">1 tile behind ⇒ run" with gait-match + hysteresis (`GH->catchup`,
  set ≥3, clear ≤1). Even pace in isolation.
- A stray `ClearHeldMovementIfActive` in the gated step path **stalled travel** (ghost moved only 1
  tile toward a far target) — removed.

ALL of the above are committed and green in headless tests. NONE of them changed the user's verdict:
"Its literally the same." → strongly implies the remaining issue is the target-stream continuity
(Option A/B), which no test or change so far has touched.

---

## Build / test / patch workflow

- **Build:** `python patch/tools/build.py` → rebuilds `patch/build/slink_RR.gba` (the patched ROM) +
  `patch/dist/SLink-RR.ups/.ips`, prints the new patched md5. Update that md5 in `patch/README.md`
  (apply-the-patch section) every rebuild.
- **Base ROM (clean):** `E:/Google Drive/SLink/Pokemon - Radical Red.gba`, md5
  `8529f3a45d32bce4da637976fcf269d4`. DO NOT modify it.
- **Patched ROM (current build):** `patch/build/slink_RR.gba`, md5
  `09c21212a856b820ae6618ba4b7d3161` (as of this handoff). **This is the file to load in BizHawk for the
  two-instance test** — loading it directly avoids a stale hand-patch. If the user keeps a separate
  play-ROM, copy the fresh build over it after every rebuild (this was a live source of "no change"
  confusion — always confirm the running ROM's md5 matches the latest build).
- **Headless live tests:** `EmuHawk --lua=lua/tests/test_live_<name>.lua patch/build/slink_RR.gba`,
  savestate `E:/Howard/Bizhawk/GBA/State/slink_overworld.State` (on THIS state the player IS slot 0),
  each writes `RESULT: PASS/FAIL` to `patch/build/<name>_result.txt` then `client.exit()`. Run headless
  and `sleep ~22-25s` then kill. Current green: `ghostdrive, ghostwarp, ghostslide, ghostanim,
  peerinteract, msgboxdismiss`. **These pass but do not reproduce the user's bug — see "Why the tests
  lie".**
- **Lua syntax:** `python tools/lua_syntax_check.py` (uses `lupa`/Lua 5.5, NOT system luac 5.1).
- Commit on `feat/rom-patch-companion` only; never edit the main checkout `E:\Google Drive\SLink`
  directly. Commit messages end with
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

### A test that WOULD reproduce the bug (build this first)
Write `test_live_ghoststutter.lua` that drives the target the way the real feed does: hold the target on
the ghost's CURRENT tile, and only advance it by +1 tile every ~16 frames (walk) — i.e. simulate a
partner walking continuously while only integer tiles arrive in bursts. Sample the ghost sprite's
`pos1.x` every frame and assert it advances ~monotonically with NO multi-frame stalls (no runs of
identical pos1.x while the partner is "moving"). Today's driver WILL fail that (it stops at each tile).
Make THAT test pass via Option A/B, then ship.

---

## Known issue (deferred, documented in patch/README.md)

**Partner's chosen RR avatar is not rendered** — the ghost uses YOUR trainer sprite. Rendering the
partner's avatar collides on the shared `PALSLOT_PLAYER` slot and corrupts colors. `fixup_palette()` is
a stub. Real fix: assign the ghost a reserved OBJ palette slot + `PatchObjectPalette(paletteTag,
RESERVED_SLOT)` and set `gSprites[sprId].oam.paletteNum = RESERVED_SLOT` for player-class gfx only.
User accepted "your sprite" as a fallback; revisit after movement feels right.

---

## Quick orientation map

| concern | file |
|---|---|
| C driver / opcodes / GhostState / msgbox | `patch/src/handlers.c` |
| engine addresses (validated) | `patch/src/ADDRESSES.md` |
| build pipeline | `patch/tools/build.py` |
| apply-patch md5 + feature docs | `patch/README.md` |
| Lua opcode/GhostState mirror | `lua/mailbox.lua` |
| receiver (spawn/post target/clear) | `lua/peer_ghost_npc.lua` |
| sender + parse + dispatch | `lua/clients/gen3_frlge_client.lua` (~1470 send, ~197 parse, ~594 dispatch) |
| server relay | `server/state.py` (`_handle_ghost_pos`, `_handle_peer_interact`) |
| live tests | `lua/tests/test_live_ghost*.lua`, `test_live_msgboxdismiss.lua`, `test_live_peerinteract.lua` |
| re-arch plan | `C:\Users\howar\.claude\plans\this-task-is-purely-sequential-twilight.md` |

Memory: `…/memory/project_rom_patch_companion.md`, `…/reference_peer_ghost_clone_techniques.md`,
`…/reference_rr_object_events.md`.
