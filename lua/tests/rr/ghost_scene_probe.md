# Running and natural wild-battle ghost probe preparation

Checkpoint status: **read-only route observation is implemented and ready**.
`ghost_route_observation.lua` and its six self-tests exist. A movement/battle
executor has not been completed or launched at this checkpoint. No running,
natural encounter, field-return, recording or duo gameplay pass is claimed.

Frozen03 and all original save/config inputs remain unchanged. Any later component
probe must use a fresh private instance prepared by `tools.rr.native_gate` from
the exact reviewed battery fixture. Component evidence against03 is diagnostic;
campaign/soak release evidence must wait for the final native arena/layout contract.

## Verified starting point

The reviewed fixture is player B outside Viridian City's Pokemon Center, Default
Mode with MGM on. Map group3/number1, SaveBlock1 coordinates26,27, player OE0
current and previous coordinates33,34 (the engine's seven-tile border), facing1.
The actual player has on-foot flags `0x21` and a completed, paused walking animation.
Treecko277 is level6, HP22/22, PID `EBEF11DA`, OT `2BDDC8BF`.

The private fixture sidecar and initial image were independently produced by the
actual mGBA boot; source/raw identity checks and their limits remain in that sidecar.
The route observer does not manufacture a new save/state or change encounter flags.

## Read-only route observation

Runner script: `lua/tests/rr/ghost_route_observation.lua`.
Use the reviewed03 battery, the existing native manifest/descriptor and host checks,
and a total budget of1,800 frames (the reviewed boot consumes1,656).

Required script assertion IDs:

- `descriptor_matches_bound_rom`
- `map_grid_captured`
- `snapshot_context_stable`
- `map_observation_complete`

Retain the runner's built-in system, ROM, emulator and fixture assertions. The
script needs its own source file and the runner's normal host/native-manifest
closure. It does not load the mailbox or issue any native command.

It captures the current stitched map grid, all1,024 metatile-attribute records,
map header/layout/tileset pointers, active object events, player state and a newly
created PNG. Data/range/context failures stop the observation. The only controls
are the exact reviewed fixture boot inputs; map sampling itself advances no frames.

Pinned RR decoder evidence:

| Observation | Actual RR source of the contract |
|---|---|
| Stitched grid width/height/pointer | `MapGridGetCollisionAt 0x08058DC4` loads `0x03005040`, dimensions at+0/+4 and map pointer at+8 |
| Grid word | u16 indexed by `y*width+x`; collision bits10..11, elevation bits12..15, metatile bits0..9 |
| Undefined grid word | `0x03FF` is explicitly treated as collision, despite its zero collision bitfield; a planner must preserve this exception |
| Terrain attributes | `0x08059080` reads32-bit attributes from primary tileset for IDs0..639, secondary for640..1023 |
| Tileset attributes pointer | Tileset `+0x14`; primary/secondary tilesets come from layout `+0x10/+0x14` |
| Attribute interpretation | Behavior bits0..8 and encounter-type bits24..26; special behavior and wild-map eligibility still require validation |
| Current map layout | Pointer at `gMapHeader 0x02036DFC` |

ROM-only location aids: group3/1 has a48×40 map layout at `0x082DE3E4`.
Neighbor candidates are Route1 (group3/19) to the south and Route22 (group3/41)
to the west. These are **candidate destinations**, not a reviewed route. The
observed RAM grid, actual connections, coordinate scripts, warps and actor positions
must determine the route before movement is authorized in the component script.
Do not guess a button sequence from a familiar vanilla map or a screenshot alone.

## Planned bounded component executor

The next implementation should consume a reviewed route artifact bound to the
observation result, fixture, ROM and native build. It must retain every planned
input, observed tile/subtile position, map, callback, script lock and battle-state
transition. Route steps need bounded expected endpoints; unexpected collision,
script, trainer encounter, map or timeout must fail and preserve the trace.

1. Revalidate the fixture and clean native/field ownership, then spawn a synthetic
   peer with the production `MB.ghost_spawn`, `ghost_set_avatar`, `ghost_set_pos`
   and `ghost_snap` APIs. Keep the known-valid current-player avatar reference and
   graphicsInfo allocation contract from `ghost_resource_probe.lua`.
2. Drive actual B-plus-direction input on a reviewed clear stretch. Confirm native
   displacement consistent with running across several consecutive frames; setting
   the synthetic peer's `run` bit or merely holding B is not a running oracle.
   Publish a coherent synthetic peer sample only while the field and player sprite
   are valid. Keep it behind/to the side so the fixture's peer does not manufacture
   its own collision obstruction. Label this as a synthetic single-cartridge peer.
3. Reach a reviewed encounter tile using ordinary input. Require the actual engine
   battle transition and wild battle identity. No encounter, battle/outcome flag,
   controller pointer, party or RNG RAM write is allowed. An unreachable encounter
   within the route/step/total budget is a failed case, not a skipped prerequisite.
4. Capture the transition and battle screen with the ghost previously present.
   Observe the native presence writer entries and require positive field controls
   plus no unqualified non-field writer execution. This is scoped execution evidence,
   not a claim that it watches every arbitrary VRAM/OAM/DMA write.
5. Return through actual battle UI input, preferably the verified Run action.
   Require a proven wild action-selection controller and observed cursor before
   each navigation/A press. Preserve failed escape attempts and any damage; bound
   retries. Unexpected loss, another scene or unavailable controller fails the case.
6. On actual field return, require a fresh valid ghost OE/sprite/callback, bounded
   original tile allocation, registered private palette ownership and no duplicate
   sentinel. Clear through production MB and check remaining private resources,
   actor/party identities and the relevant current-scene baseline. Map/scene resets
   can legitimately reorder engine resources; do not compare arbitrary slot numbers
   against an unrelated earlier map as the sole oracle.

## Battle-input and native-symbol evidence already checked

- The RR action-selection controller is `0x0802E439`; its entry at `0x0802E438`
  redirects to actual RR handler `0x090A9EA0`. That routine reads new keys from
  `gMain+0x2E`, and at `0x090A9ED8` uses `0x02023FF8` for the action cursor.
- The cursor is a **direct four-byte array**, not a pointer to another allocation.
  The relevant controller-function array is `0x03004FE0`. The general dispatcher
  `0x0802E3B5` must not be treated as proof that an action menu is ready.
- RR battle metadata for this pinned profile remains `gBattleTypeFlags=0x02022B4C`,
  `gBattleOutcome=0x02023E8A`, `gBattleMons=0x02023BE4`. Some historical test scripts
  contain shifted addresses; do not copy those into this probe.
- Run outcome is RR/CFRU4; the actual run routine entry `0x08016748` redirects to
  `0x0909053C`, whose success branch writes4 to `0x02023E8A` at `0x090905B8..BE`.
  A future executor must observe the result rather than write it.
- Frozen03 symbols from its linked ELF: ghost callback `0x0837A970`,
  `apply_avatar=0x0837AB2C`, `drive_ghost=0x0837AC98`,
  `rr_place_ghost=0x0837BAA4`, `rr_adopt_ghost_sprite=0x0837BB50`,
  `rr_remove_presence=0x0837BC6C`. Bind every symbol to the selected build; do not
  reuse these addresses after a rebuild.

## Recording and assertions still required

Capture a contiguous sequence of actual framebuffer PNGs with exact frame numbers
through the short running/battle/return component sequence, plus named before,
running, battle and returned-field screenshots. Each file must be new and verified
as a captured image. Preserve an ordered manifest so a video can be assembled from
the actual frames; do not generate replacement frames or infer graphical correctness
from a visible-bit assertion. Installed ffmpeg is available for later encoding.
The captured images/video still require review; structural success cannot set
`visual_review=passed` by itself.

Runtime instrumentation must fail if required callbacks cannot register or lack
positive controls. Existing arena callback limitations must not be hidden by a
zero-count result. The result should remain `release_ready=false` and classified
as synthetic single-cartridge component evidence even if this bounded case passes.

At this checkpoint the movement executor, reviewed route, natural battle, field
return, continuous recording and live running/scene assertions remain outstanding.
Bike/surf/fishing, broader motion/freshness, allocator reservation, durable recovery,
campaigns and soaks are separate unresolved work.

Self-tests for the completed read-only observer:

```powershell
python -m pytest -q tests/unit/test_rr_ghost_route_observation.py
python -m ruff check tests/unit/test_rr_ghost_route_observation.py
```
