# Normal ghost resource component probe

`ghost_resource_probe.lua` is a synthetic single-cartridge component test. It uses the actual
production mailbox for spawn, avatar/position publication and clear, then observes the native
engine at frame boundaries. It does not start a client/server session, simulate both players,
write object/sprite/palette/tile memory directly, or approve visual/gameplay correctness.

Run it only through the reviewed `tools.rr.native_gate` private-instance runner with a fixture
whose battery/state and exact patched ROM have already been independently verified. An earlier
candidate's savestate/fixture contract cannot be silently reused with another candidate.
For a battery, `config.frames` includes the sidecar's reviewed boot input frames. No discovery,
unbounded wait, interactive prompt, in-game save or global bus callback is used here.

Declare the source closure:

- `lua/tests/rr/ghost_resource_probe.lua` (automatically included as the selected script)
- `lua/mailbox.lua`
- `lua/memory_gba.lua`
- The native manifest also causes the runner to bind its declared native inputs.

Probe options must contain an exact symbol contract from the **bound candidate's** linked ELF:

```json
{
  "native_contract": {
    "build_id": "<64 lowercase hexadecimal characters from native_manifest.json>",
    "ghost_callback": 137865584
  },
  "cycles": 3,
  "phase_frames": 60,
  "visible_frames": 12,
  "quiet_frames": 6
}
```

The example callback is frozen03 `ghost_cb = 0x0837A970`. Obtain each candidate's symbol with
the pinned toolchain's `arm-none-eabi-nm -n handlers.elf`; do not infer it from a nearby address.
The script checks the full immutable descriptor against the runner's bound ROM bytes and the
symbol contract's build ID against that descriptor. The runner must supply this contract from
reviewed artifacts, not from the sprite callback being tested.

Required script assertion IDs for preparation are:

- `descriptor_matches_bound_rom`
- `resource_cycles_completed`
- `resource_screenshots_complete`
- `resource_frame_budget`
- `resource_normal_lifetime_complete`

Retain native_gate's built-in system/ROM/emulator/fixture assertions. A typical reviewed battery
boot of 1,656 frames plus three normal cycles fits a 2,200-frame budget, but actual completion
and all resource/screenshot assertions must pass. Phase or total timeout is a failure.

The fixture must be a quiet field with a stopped on-foot player and no active script, borrowed
party, native UI/notification, known postbattle writer task, existing ghost/PC NPC, sentinel
object or private type6 palette reference. The mailbox must already be idle; the probe never
drops native events or resets a pending owner to make admission succeed.

Stopped means heldMovementFinished with matching current/previous coordinate pairs. A face
animation or facing-matched paused standard locomotion animation4..19 is accepted. Actual RR
`UpdateMovementNormal` at `0x08064788` calls `ShiftStillObjectEventCoords` on completion and sets
Sprite `+0x2C` bit `0x40` at `0x080647B2..B6`, retaining animNum. A captured field player with
avatar flags `0x21`, facing1, anim4 and delay/pause byte `0x48` is therefore a stopped walker.
Unpaused, wrong-facing, special animation or divergent current/previous coordinates are refused.
Rejected animation prerequisites retain the raw reference and a separately labeled, unqualified
diagnostic screenshot; these do not count as completed resource-cycle evidence.

Each cycle confirms the exact owned OE/sprite/callback/marker, allocation size and geometry;
publishes the player's own known-valid avatar two tiles to the right; waits for native avatar
acceptance; requires a visible in-screen sprite at that position; and clears through the same
production mailbox. Existing active object/sprite identities and registered palette colors
stay unchanged. Only the ghost's initially free contiguous tile range and private palette slot
may appear. Native clear must restore the entire allocation bitmap and palette-reference table.
Released free-slot palette color bytes need not be zeroed: their allocator reference is gone.

Allocation is independently read from the direct graphics record's `size` field at `+6`.
The first image's `size` is only its transfer length. For actual RR gfx0, bank0 table
`0x08EB1000[0]` selects record `0x08EB140C`, reserving512 bytes while image table
`0x08EB3810` frame0 transfers256. Spawn instruction `0x0805E76C` loads the record size
into a temporary frame descriptor used by CreateSprite. The probe verifies the record's
image/animation association and distinguishes these two sizes; it refuses dynamic graphics
aliases until their variable context is independently qualified. Each cycle records raw OE,
sprite, allocation, images, geometry and callback values before ownership assertions.

The observed tile bitmap is RR `0x02021B48` (128 bytes) and reserved tile count `0x02021B46`.
These locations are confirmed by the pinned RR `AllocSpriteTiles` entry `0x08007434`, bitmap
operation `0x08007550` and free routine `0x080075C0`; the latter frees tiles from OAM tileNum
and the original image allocation size. Palette type/count/tag entries are `0x0203B7D4`,
16 entries of four bytes, as documented in `patch/src/NATIVE_PRESENCE.md`.

Before, per-cycle visible, and per-cycle after PNGs are mandatory. Every path is a constant
suffix under the runner's result path. Existing files are refused; capture exceptions/false,
missing files, malformed chunk boundaries, missing image/end chunks, or wrong dimensions fail.
The script records path/size/dimensions/frame; the runner/evidence collector must hash these
contained artifacts and an assessor must inspect them. PNG structure checks do not decode or
establish the correctness of the displayed ghost. `visual_review` stays `pending` and
`release_ready` stays false even on a structural component pass.

Failure remains failure after any best-effort cleanup. Cleanup can only issue ordinary ghost
clear while the field remains qualified, the mailbox is idle and time remains. Unknown scene,
mailbox uncertainty or exhausted budget prevents extra mutations and is recorded for review.

Self-test (a toy native producer, not actual engine evidence):

```powershell
python -m pytest -q tests/unit/test_rr_ghost_resource_probe.py tests/unit/test_rr_mailbox_v2.py
python -m ruff check tests/unit/test_rr_ghost_resource_probe.py
```

Separate required gates still include physical two-player transport/gameplay, scene and bulk
resource resets, exhausted resources, reflections/surf/fishing, animation/motion/freshness,
long soaks and ownership of the disputed native arena. This component cannot satisfy those cases.
