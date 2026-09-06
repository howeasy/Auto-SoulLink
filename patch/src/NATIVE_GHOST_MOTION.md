# RR ghost collision and remaining motion/effect defects

This records reverse engineering against RR4.1 Default Mode, clean ROM MD5
`8529f3a45d32bce4da637976fcf269d4`, SHA256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
MGM off/on remain separate live acceptance lanes. The N08 change below repairs placement;
it does not complete motion, surf/fishing effects, freshness, or arena ownership.

Function names were located using local pret/CFRU source and the official
[pret FireRed symbol map](https://raw.githubusercontent.com/pret/pokefirered/symbols/pokefirered.sym).
Those references are naming aids, not RR source. Addresses and behavior stated below were
checked in the pinned RR binary; patched branches were followed rather than assumed to match pret.

## N08: both collision coordinate pairs must move

`GetCollisionAtCoords` at `0x080636AC` calls the object collision loop `0x08063904`
at `0x08063752`; a positive result becomes collision code4. The object loop compares active
objects other than the moving object. After its current-coordinate path, instructions
`0x0806393C..0x08063946` read previousX/Y at OE `+0x14/+0x16` without a moving-state test.
The RR hook at `0x08063928` enters `0x090429A0`, calls `0x090965BC` (the follower exemption),
and otherwise resumes the same collision loop. A live reproduction must record follower state.

The loop calls `AreElevationsCompatible` at `0x0806835C`. That routine accepts equal
elevations **or either elevation zero**. Giving a hidden object elevation15 therefore does
not establish pass-through for a player at elevation0.

Before N08, `drive_ghost` updated only currentCoords when visible/offscreen, left both pairs
unchanged on invalid-avatar/no-camera-baseline returns, and spawned hidden one tile south of
the player. That can leave an invisible obstacle at the old spawn tile or a rejected avatar's
last visible tile. The offscreen branch also retained interaction arming.

`rr_place_ghost` now checks the field callback, exact owned OE/sprite/callback/marker,
allocation-size validity, elevation and visibility before any EWRAM write. It writes current
and previous coordinate pairs together, plus elevation and visibility. The driver uses it
for visible placement, offscreen placement, rejected avatars, missing camera baseline and
newly adopted spawn. Hidden objects park both pairs on the player's occupied current tile;
they never claim an adjacent hidden tile, and interaction is disarmed. Visible placement
alone arms interaction. GhostState remains44 bytes and no extra EWRAM allocation is introduced.

Parking does not prove universal noninteraction with other NPCs. It avoids an additional
hidden obstacle around the local player; real scripted movements and culling still need testing.

Required live assertions, with actual joypad input and an independently observed field fixture:

1. Baseline traversal of the future spawn tile succeeds; under the old candidate a ghost moved
   elsewhere leaves previousCoords there and blocks the same input. N08 must clear that block.
2. Test player elevation0 as well as differing/equal nonzero elevations. Visible ghosts still
   collide at the drawn tile and can be deliberately talked to.
3. Move peer offscreen, reject avatar evidence, and defer camera calibration while the local
   player moves. Both ghost coordinate pairs follow the local occupied tile, visibility stays
   off, and A at the old visible/spawn tile produces no peer interaction.
4. Exercise repeated reversal, map/door/connection changes, battle/menu return and slot reuse.
   Stale or non-field ownership causes no sprite/OE writes; every visible placement keeps both
   collision pairs coherent. Resource and arena gates from NATIVE_PRESENCE.md remain required.

## Remaining movement cadence defect

The sender still derives `run` from `animNum >= 8`, while `drive_ghost` limits motion to one
or two pixels per frame. Animation index is not a complete RR movement-speed description.

Verified RR chain:

| Behavior | Pinned RR evidence |
|---|---|
| Normal player run | `0x08065DF0` calls `0x08064758`; `0x08064762` selects speed1, table `0x083A714C` invokes `0x08068AAC`, two pixels/frame |
| Bike dispatch | Hook at `0x080BD338` enters `0x09042F7C`, calling RR routine `0x090B1E08` |
| Ordinary faster bike cadence | RR routine can choose `PlayerRideWaterCurrent` entry `0x0805C14D`; movement action `0x08065AF0` selects speed2 |
| Speed2 actual steps | Table `0x083A716C` selects `0x08068AAC/0x08068AD0` in the sequence2,3,3,2,3,3 pixels: one16-pixel tile in six frames |
| Faster bike branch | `0x090B1E42..0x090B1E60` tests flag `0x091F` or held B and chooses `PlayerWalkFaster` at `0x0805C165`; action `0x08065BF0` selects speed3 |
| Speed3 actual steps | Table `0x083A7184` invokes `0x08068AF8`, four pixels/frame |

The bike routine has additional collision and terrain handling; the flag's product-facing name
is not established here. The player movement wrappers at `0x08FFF454`, `0x08FFF48C` and
`0x08FFF4C4` also handle metatile behaviors `0xB0..0xB5`. Do not replace these branches with
a claim that every bike frame has one fixed speed.

The next motion contract must separate positional displacement from animation state and bind
samples to source scene generation/freshness. Use measured, timestamped displacement or a
verified movement cadence, bounded extrapolation and explicit stale-sample retirement. Maintain
teleport/map-change handling and test stop/reverse/bump cases. This needs a separate design and
memory-layout review; N08 does not change the wire format or allocate snapshot storage.

## Remaining stationary fishing animation and offsets

The current C driver and avatar validation select facing0..3 whenever `mv == 0`. RR fishing
uses other animation indices while the player is stationary:

- `Fishing12` at `0x0805D7C0` calls `GetFishingNoCatchDirectionAnimNum` at `0x08063500`, then
  `StartSpriteAnim` at `0x0800838C`. Its table `0x083A6481` returns4..7 for directions1..4.
- Bite-direction table `0x083A648A`, read by `0x08063510`, returns8..11. RR patches Fishing6
  at `0x0805D508`; its original downstream bite-animation branch remains at `0x0805D548..66`.
  Full RR task-path reachability of each outcome remains a live/targeted follow-up.
- `AlignFishingAnimationFrames` at `0x0805D9C4` calls `AnimateSprite`, reads animation frame
  state, and writes sprite x2/y2 at `+0x24/+0x26`. Instructions `0x0805DA4C..76` apply signed
  eight-pixel offsets for rod/frame types. It forwards surfing y2 through `0x080DC4A4` at
  `0x0805DA98` when the player avatar has the surfing bit.

The sender carries animNum, image/animation pointers and palette, but not x2/y2 or frame timing.
Forwarding animNum while still forcing stationary facing cannot show these phases correctly.
Calling the stock fishing alignment routine on a ghost is also unsafe: it reads the **local**
player's facing/avatar and may write the local player's surf child. Use validated peer snapshot
state and a ghost-owned presentation implementation instead. Required cases include take-out,
bite/no-bite, cancel, no-catch, battle entry and return, both on land and while surfing.

## Remaining surf child ownership

Surf presentation is not just a larger avatar graphics record:

- `UseSurfEffect4` at `0x08086AB4` changes the local avatar graphics, then at `0x08086B10`
  starts field effect8; it saves the returned child sprite ID in parent OE `+0x1A`.
- `FldEff_SurfBlob` at `0x080DC3D0` creates a sprite from actual template `0x083A556C`.
  The template callback is `0x080DC4F9`, its image table `0x083A54FC`, and both tags areFFFF.
- RR hook `0x080DC410 -> 0x09042748` acquires palette tag `0x1100` through `0x0908FF1C`.
  That routine uses type1 lookup/add plus reference increment. The child owns a separate
  type1/tag1100 reference, not the ghost's private type6 reference.
- Child Sprite.data[2] (`+0x32`) holds the parent OE ID. Callback `0x080DC4F8` resolves that
  OE and its sprite directly, without an active/owner check. It calls `0x080DC61C`, which
  writes the parent's y2 (`0x080DC68A`) and follows parent pos1 (`0x080DC69C..A4`).

The stock surf callback has no inactive-parent self-destruction branch. Merely allocating a
surf child for the ghost would create a stale parent/sprite write hazard on removal or reuse.
A safe implementation needs an owned child marker/callback, parent association validation before
native update, explicit teardown before parent reuse, original allocation-size accounting and
balanced release of the child's actual palette reference. Mode switches, bulk sprite resets,
palette-only resets, parent reconstruction and exhausted sprite/tile/palette capacity all need
independent assertions. Existing owned Sprite.data may be usable only after proving the selected
callback's data contract; no disputed EWRAM gap is declared available by this document.

## CPU verification lane and its limits

`tests/rr/native/test_ghost_placement_cpu.py` runs the compiled Thumb helper and driver in a
pure CPU harness with synthetic EWRAM/IWRAM. It checks exact allowed writes, negative ownership
guards and all placement branches. Spawn allocation and rejected-avatar return are explicitly
stubbed in their respective integration cases. A separate case executes RR's actual object
collision loop/elevation comparator, with only follower exemption stubbed to the no-follower
case. No game boots, emulated frames, PPU, audio, save or real gameplay assertions occur here.

Install the isolated test dependency and run from the worktree (PowerShell):

```powershell
python -m pip install --target patch/build/native-cpu-deps -r tests/rr/native/requirements-cpu.txt
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
$env:SLINK_ARMGCC = 'E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin'
$env:SLINK_RR_NATIVE_OUTPUT = (Resolve-Path patch/build/ghost-probe-03).Path
python -m pytest -q -p no:faulthandler tests/rr/native/test_ghost_placement_cpu.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
```

The Windows-only `-p no:faulthandler` prevents pytest from reporting Unicorn's internally
handled Windows access violation as a fatal Python stack trace; Unicorn documents this
behavior in its [FAQ](https://github.com/unicorn-engine/unicorn/wiki/FAQ#i-debug-my-application-but-soon-get-an-access-violation-inside-unicorn).
Unicorn errors, failed native returns, changed assertions and process failures still fail the
lane. This switch is not a skipped test and must not conceal actual game-emulator failures.
