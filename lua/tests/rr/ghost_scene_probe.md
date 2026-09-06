# Running and natural wild-battle ghost probe preparation

Checkpoint status: **read-only observation22 passed; running-only executor is staged
for review and has not launched**. The natural-battle executor remains unimplemented.
No running, natural encounter, battle/field-return, recording or duo gameplay pass
is claimed.

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

## Staged running-only executor

`ghost_running_probe.lua` uses `viridian_west_running_route.json`, bound to actual
observation22 SHA256 `600f94c88972995f1e337a8908303674dda7c475e0be52f55b71cfaa0727c4e3`.
The reviewed row34 corridor, grid x26..45, contains only collision0/elevation3/plain
terrain. The player's segment x33→27 avoids all five warp entries and all twelve
coordinate-script entries in actual map events `0x0872BDC4`. Their complete bytes
and pointers are pinned in the route artifact; the actual ROM contract test checks
them. The observed NPC at40,33 is off the route; a new blocking actor aborts before
the next step rather than being treated as static empty space.

The executor first runs the existing three-cycle normal ghost-resource control and
reuses its settled production mailbox instance through a test-only return value.
It then spawns a synthetic peer, stages the known-valid avatar and keeps its target
two tiles east of the westbound player. Samples publish every two frames. It holds
actual B/Left until the final tile's movement begins, releases input, and waits for
the native step to finish. The input segment is limited to120 frames; no coordinate,
battle, party, RNG or controller-function field is written directly.

Success requires the actual endpoint, at least six consecutive observed two-pixel
westward native frames with running animation22, and observed ghost running frames.
RR's real running-animation lookup at `0x08063520` reads table `0x083A6493`, whose
left-facing entry is22. Holding B or setting the synthetic peer's run bit alone
cannot pass the oracle. Field/map/party identity and ghost/actor palette, callback,
allocation and tile ownership are checked during movement. Clear must leave no
ghost sentinel or private type6 reference. Unexpected scene/battle or a timeout fails
and retains trace/capture attempts; cleanup never forces a write into unknown context.

Every trace frame retains complete party bytes, while the gate requires the original
count and ordered PID/OT identities. Field steps can legitimately change friendship
or other gameplay fields, so byte equality is not used as a running-motion oracle.
Any party-byte difference remains explicitly `party_review=pending`; no party/storage
correctness is claimed by a graphics component pass.

Full resource restoration also remains `resource_review=pending`. Final checks
require no ghost object sentinel or private palette reference, but camera movement
can cull/create ordinary actors and change their sprite/tile allocations. The retained
resource snapshots require independent orphan-sprite/tile attribution; absence of a
type6 palette alone does not establish that all ghost tiles or sprites were released.
`running_component_complete` certifies its bounded motion, owned-frame and coarse
cleanup assertions only, not complete resource restoration.

Use a total budget of2,200 frames, including the1,656-frame battery boot and normal
resource controls. Required executor assertion IDs are `running_component_complete`,
`running_endpoint_reached`, `running_native_motion_observed`,
`running_ghost_animation_observed`, `running_recording_complete`, plus
`resource_normal_lifetime_complete` and native_gate's built-ins. The native symbol
contract/options are the same frozen03 contract as the normal resource probe.

Declared source closure, in addition to normal host/native-manifest dependencies:

- `lua/tests/rr/ghost_running_probe.lua`
- `lua/tests/rr/ghost_resource_probe.lua`
- `lua/tests/rr/viridian_west_running_route.json`
- `lua/mailbox.lua`
- `lua/memory_gba.lua`
- `lua/json_codec.lua`

Every frame from ready-to-run through cleanup has a new240×160 framebuffer PNG and
an exact frame number. The ordered recording manifest uses the pinned host's nominal
GBA timing262144/4389 fps. It can be encoded after the run without generated or
interpolated frames, for example from the private result directory:

```powershell
ffmpeg -framerate 262144/4389 -start_number 0 -i result_running_frame_%06d.png -c:v libx264rgb -crf 0 running.mp4
```

Retain/hash the original PNG sequence and result alongside any video derivative.
The component always reports `release_ready=false`, `visual_review=pending`, and
`natural_battle_tested=false`; it cannot close the battle-transition or duo lanes.
The observer/native route and running/resource self-tests pass, but the running
executor still needs parent review, private-host ownership qualification and an
explicit coordinated launch. Frozen03 has not been rebuilt or modified.

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

At this checkpoint the running-only executor/route are staged; its actual running
and recording outcome, natural battle, battle/field return and live scene assertions
remain outstanding.
Bike/surf/fishing, broader motion/freshness, allocator reservation, durable recovery,
campaigns and soaks are separate unresolved work.

Self-tests for the completed read-only observer:

```powershell
python -m pytest -q tests/unit/test_rr_ghost_route_observation.py
python -m ruff check tests/unit/test_rr_ghost_route_observation.py
```

Staged executor self-tests and ROM contract:

```powershell
python -m pytest -q tests/unit/test_rr_ghost_running_probe.py tests/unit/test_rr_ghost_resource_probe.py tests/rr/native/test_running_route_contract.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
python -m ruff check tests/unit/test_rr_ghost_running_probe.py tests/rr/native/test_running_route_contract.py
```
