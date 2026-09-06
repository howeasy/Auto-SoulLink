# RR peer ground-position sampling

This is a bounded sender correction for RR4.1 Default Mode. It changes neither
the ghost wire schema nor native rendering, ABI, arena, C code or frozen03 ROM.
It does not complete ghost freshness, scene resources, bike/surf/fishing animation
or physical viewport-edge acceptance. MGM off/on remain separate live lanes.

## Finding and exact-binary evidence

The prior production sender calibrated a tile and `gSpriteCoordOffsetX/Y` while
idle, then sent `tile*16 + (offsetAtAnchor-offsetNow)`. That is camera displacement,
which only equals ground displacement while the camera follows the player without
independent panning. Running the **unchanged actual Lua sender fragment** before
this correction gave:

| Synthetic RAM case | Expected next ground pixel | Prior sender |
|---|---|---|
| Following camera, west two pixels | `(526,544)` | `(526,544)` |
| Fixed camera, west two pixels | `(526,544)` | `(528,544)` |
| Fixed X camera plus independent vertical pan | `(526,544)` | `(528,545)` |

This reproduces arithmetic faults under those stated inputs. It does **not** prove
that RR clamps its ordinary camera at a map viewport edge. No such clamp branch was
found in the inspected normal callback/update path, and the observed running route
below does not exercise one. Reachability of fixed-camera player movement and
independent panning needs a separately qualified physical scene.

Names were located with the [pret FireRed symbol map](https://raw.githubusercontent.com/pret/pokefirered/symbols/pokefirered.sym)
and local pret `src/event_object_movement.c` / `src/field_camera.c`; these are naming
and structural references, not RR source. All addresses and behavior below were
checked against the actual RR base SHA256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.

| Actual RR routine | Observed behavior relevant to the correction |
|---|---|
| `SetSpriteDataForNormalStep 08068B40`, `NpcTakeStep 08068B54` | Direction/speed/frame state lives in Sprite.data; the real dispatch calls the corresponding step function. |
| `Step2 08068AAC` | Stores the signed directional displacement directly into Sprite `+20/+22` (pos1); no camera offset participates. Speed0/1/2/3 advances a tile in 16/8/6/4 frames, with speed2 cadence 2,3,3,2,3,3. |
| `CameraObject_1 0805F9F8` | Copies followed Sprite.pos1 into the camera sprite and writes its difference into camera data2/3. |
| `CameraObject_2 0805FA30` | Copies followed Sprite.pos1 while explicitly zeroing both camera movement deltas. |
| `CameraUpdate 0805ABB0` | Uses those camera deltas, updates map/camera state, then subtracts them from total camera offsets at `0805AC88..98`. The inspected routine has no viewport-extent clamp. |
| `UpdateCameraPanning 0805AE28` | Writes coordOffsetX = totalX - horizontalPan and coordOffsetY = totalY - verticalPan - 8. Independent pan therefore contaminates the old ground-position formula. |
| `UpdateObjectEventCoordsForCameraUpdate 0805F82C` | When the connection flag at `02036E18` is set, subtracts its x/y deltas from all active OE initial/current/previous tile coordinates. It does not rebase Sprite.pos1. |
| `GetMapCoordsFromSpritePos 08063AD4` | Initial placement uses tile relative to SaveBlock1 position and total camera offset; pos1 is not an absolute world coordinate without calibration. |

The helper loads lazily only in RR frame handling; vanilla/AP startup does not
require this RR module. The read-only `lua/rr/peer_position.lua` anchors an owned player's Sprite.pos1
to its tile only when heldMovementFinished is set **and** current/previous tile
coordinates agree. Subsequent ground pixels use the signed16 modular pos1 delta.
Camera offset and visual pos2 offsets are deliberately absent from this formula.
The modular difference handles the native signed16 sprite-coordinate wrap; world
output remains bounded to the existing signed16 wire/native range.

Calibration is discarded on non-field/patch-loss observations, invalid OE/sprite
ownership, or a change in player OE, sprite ID, map, layout, graphics, images or
animation-table identity. It waits for an aligned sample if first seen midstep.
Every resulting pixel must lie in the current/previous tile rectangle; inconsistent
connection/reposition observations are suppressed until a new aligned anchor.
This catches the proven tile-only rebase and avoids inventing a midstep baseline.
It is an ephemeral observation guard, **not a durable epoch or savestate detector**.
Dropping a sample does not repair the receiver's separate stale-target lifetime.

## Recorded normal-route comparison

Validation run `running_component_33_a` used frozen03 SHA256
`3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301`
and the reviewed Viridian MGM-on battery fixture with probe source commit
`06473108f847b8691f89b975d0f4b012619c0cf5`. Its complete result SHA256 is
`7070bf6a54867a4c6f4d6d5cacc1af90fe980d41b292299697904b880e72e862`.
The original private result remains under the run's `results/result.json`.

`tests/rr/fixtures/running33_position_trace.json` retains all65 sampled raw player
tile/previous/pos1/coordOffset/flags/animation observations and the original probe
world position. Every consecutive frame changes `(pos1x,coordOffsetX,worldX)` by
either `(-2,+2,-2)` or `(0,0,0)`. The camera follows throughout; there is no clamp or
pan reproduction here. Replaying those observations through the corrected actual
sender preserves all65 world positions. This replay is not a new emulator run,
duo gameplay, or approval of the original run's screenshots/resources.

## Validation and remaining physical gates

`tests/unit/test_rr_peer_position.py` exercises the actual production sender
fragment with synthetic RAM: following/fixed/panned camera, wall bump, startup
midstep, ownership/context/rebase rejection, signed16 wrap, visual-only pos2 and
the recorded normal-route replay. Existing mailbox sender/gfx16 tests and real
full-client startup tests also run; ordinary field/battle admission stays unchanged.

`tests/rr/native/test_peer_position_cpu.py` explicitly requires pinned RR and
Unicorn. Its33 checks execute actual `NpcTakeStep`, selected CameraObject callback,
`UpdateCameraPanning`, and tile-rebase instructions without routine stubs. The
harness supplies synthetic RAM and integrates total camera scroll; it does not
execute a complete CameraUpdate, game frame, PPU or physical input sequence.

```powershell
python -m pytest -q tests/unit/test_rr_peer_position.py tests/unit/test_rr_mailbox_v2.py
python -m pytest -q tests/rr/runtime/test_harness.py --rr-repo .
$env:PYTHONPATH = 'E:/Google Drive/SLink/.claude/worktrees/rr-foundation/patch/build/native-cpu-deps'
python -m pytest -p no:faulthandler -q tests/rr/native/test_peer_position_cpu.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
```

Required future live checks include a grounded camera-fixed/panning scene, normal
camera follow, all four movement directions, stop/reverse/wall bump, field return,
map connection/hard reposition, and new avatar creation. Preserve raw pos1/pos2,
camera total/pan/offset, OE current/previous and scene identity in the trace. Do not
label a test "viewport clamp" from a fixed-offset synthetic fixture alone. The
physical updated-client sender/peer-renderer pair remains untested in this slice.

The later [current-map correction](PEER_CURRENT_MAP.md) uses SaveBlock1 location
for map tags and calibration identity after a connected-map observation proved
that the player's OE retains its spawn-map fields.
