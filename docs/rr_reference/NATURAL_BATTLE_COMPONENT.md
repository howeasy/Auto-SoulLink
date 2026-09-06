# Route 1 natural-battle and ghost component evidence

This lane uses frozen native candidate03 and a private copy of the observed
Player B / Treecko level6 / Default / MGM-on Viridian battery checkpoint. It is
component evidence, not duo, campaign, mode-combination, arena-ownership or
release approval. Original saves/configuration are never launch inputs.

## Grounded route and retained failures

`encounter_route_observation.lua` verifies the ROM's expanded-variable and south
coordinate-script anchors, then observes variable507E. Actual run38 read1, so
the two south-path coordinate events requiring0 are disabled in this save.
The script neither writes that variable nor disables an encounter.

The ordinary-input traversal is `(33,34) -> (33,36) -> (29,36) -> (29,46)`,
then the south connection. Run39 reached Route1 but failed because its oracle
used the player object's retained spawn-map bytes. That failed result remains
unchanged. The corrected run40 read current map3:19 from SaveBlock1+4/+5,
layout082E55CC, current/previous grid17,7, script lock0 and callback080565B5 at
frame1931. The object still reported spawn map3:1. Run40 passed4375 assertions;
its process exited normally and original file hashes matched.

Run40's result SHA256 is
`4addaa88d7e3a72d0302ef23b8f3342cd6f19d773acd68887173331c281f5f4c`.
The checked-in `lua/tests/rr/route1_grass_route.json` records its exact tile words,
metatile attributes and ROM/fixture binding. The next route walks17,7 to17,10,
right to23,10, then down to23,13, bypassing the ledge. The two grass destinations
23,13 and24,13 are collision0/elevation3 with attribute01000202. This map has no
coordinate events. Actor current/previous occupancy is checked before each step.

Run43 refused a3800-frame launcher configuration before any boot input because
the frozen observer accepts at most3600. The launcher was corrected to3600;
the combined planned1931-frame arrival plus1600-frame encounter bound fits it.
No assertion was removed.

Run44 naturally encountered a level3 Zigzagoon after11 grass steps. It stopped
at the intro text without sending any Run input. The failed oracle incorrectly
required battle flags0 and enemy-count byte1, and did not advance waiting intro
text. The actual flags were4 (`IS_MASTER`, set for offline battles); CFRU left
the enemy-count byte0. These are probe errors, not a cartridge failure. The645
captured PNGs and full failed result remain attributed to that original source.

## Battle input contract

The corrected no-ghost probe records the count byte but requires actual enemy
party HP/maxHP and two populated battle battlers. The action gate requires
ordinary-wild flags4, unchanged party identity/HP, the exact player action
controller0802E439 and cursor0..3. Each Right/Down cursor change is checked before
the next input. A is sent only at verified cursor3; one escape attempt is allowed.
Any HP loss, other outcome or return to the action menu after a failed escape
terminates the probe with its trace and screenshot. A successful escape requires
outcome4 followed by the same current map/layout and an idle field player.

Intro/result text uses a one-frame B pulse only with battle callback08011101,
controller08030611 and printer0 active in wait/clear/scroll-start states1..3 at
02020034. Pulses are separated by a neutral frame and bounded to8. The probe pins
the actual ROM controller, printer table and RR wait-hook bytes. The RR wait
routines090C0E58/090C0EA4 check A/B new keys; this is not a menu-selection shortcut.

The action hook0802E438 redirects to090A9EA0. The escape hook08016748 redirects
to0909053C, whose success path writes outcome4. Reference source is the vendored
FireRed `battle_controller_player.c`, `text.h`, `text.c` and `constants/battle.h`;
RR hook bytes and observed controllers constrain their applicability.

## Reproduction and limits

Use `tools.rr.native_gate.GateSpec` with explicit executable/base configuration,
frozen03 ROM/native manifest, immutable observed battery/sidecar, source closure,
fresh output directory and fresh run ID. Select3600 frames and a100-second outer
process deadline. The private source closure includes the route observer,
encounter observer, traversal probe, grass JSON, JSON codec, peer-position helper,
host-identity helper and selected battle probe. Future layout-era sources must not
silently replace candidate03's frozen dependencies.

The local task launcher is
`C:/Users/howar/AppData/Local/Temp/slink-rr-native-probes-01a072f9/run_natural_battle.py`.
It records exact child PID/create-time, execution/result bindings and original
save/configuration hashes; it refuses reused run directories. Completed and
failed artifacts live beneath that task root's `runs` directory.

Probe self-tests run with:

```text
python -m pytest tests/unit/test_rr_route1_traversal_probe.py tests/unit/test_rr_natural_battle_probe.py -q
```

These tests model movement/menu faults and cannot establish actual emulator
behavior. No ghost transition or release result is implied by the no-ghost lane.

## Completed component captures and retained failures

Run46 used actual movement, encountered a level3 Zigzagoon after11 grass steps,
verified the native action controller and Run cursor, escaped, and returned to
idle field at2818. Party identity and HP22 stayed unchanged. It has13832 structural
assertions and a lossless711-frame recording; the engine count byte remains0 as
documented above. No encounter, RNG, party or battle state was injected.

The separate `ghost_natural_battle_probe.lua` publishes a synthetic same-avatar
peer32 pixels beside the player through ordinary companion requests. It starts
at the observed idle23,12 checkpoint, checks the target tiles and real resource
ownership, and publishes no native requests during battle. It uses the same
actual-input encounter/menu scenario. This is not a second player's transport or
gameplay evidence.

Run52 encountered Pidgey, then stopped before Run because normal Frisk animation
and text exceeded the480-frame intro allowance. The next source allows720 intro
frames within the unchanged1600 post-arrival/3600 overall frame bounds. Run53
escaped and restored the ghost but failed the original all-old-tiles-free oracle.
Both original failures remain unchanged.

The four remaining tiles20..23 in53 belong to native player tall grass: sprite60,
template083A5420, callback080DB3ED, image table083A53DC, five128-byte frames and
palette tag1005. Its FF local owner resolves the real player through the actual
09042B08/0805DF68/0805E044 path, and its coordinates match the player's current and
previous23,13. The callback retains the effect while that player occupies grass.
The new oracle permits this exact attributable stock effect only, accounts for
every tile/refcount delta, and still rejects wrong owners or extra leaked tiles.
All observed ghost allocations, including hidden resources before avatar
acceptance, remain tracked. No private palette, F0 object or ghost callback/marker
may remain after cleanup.

Run56 passed structural checks but **did not complete visual acceptance**. Review
of every unique framebuffer showed the test clearing immediately when native
ownership returned, before the ghost appeared on screen. The revised test retains
a checked owner through12 additional frames before recording returned presence
and clearing. Loss of ownership in this interval fails a focused regression.

Run57 passed that bounded component: real Pidgey encounter, exact Run selection,
HP/identity preservation, visible ghost before battle and after return, and fully
accounted cleanup. Both original config and SaveRAM remained unchanged; the exact
child exited normally. Its941 consecutive frames2107..3047 decode byte-for-byte
to the original PNGs. Root reviewed all557 unique RGB images, reusing hash-identical
images already inspected from56 plus the one newly visible return image. No
unexplained sprite corruption was observed in this capture. Timing cadence at
normal playback, other modes, other scenes and the full ghost feature remain
separate acceptance work.

[Evidence and recording identities](natural_ghost_evidence.json) retain the five
results, failures, source bindings, exact process outcomes and visual disposition.
The original result files retain their initial `visual_review=pending`; the
separate review record records the later assessment without rewriting them.
Current native candidate07 has no gameplay acceptance from these frozen03 runs.

## Strict recording generation

`python -m tools.rr.frame_recording --help` creates a lossless recording and
contact sheets from an explicitly selected1..3600-frame interval. It requires
every240×160 opaque PNG, rejects contradictory same-frame captures, verifies every
decoded RGB frame, preserves an exact renderer-source copy and fingerprints the
encoder, inputs and outputs. It never emits a visual PASS; a separate review is
required. Missing screenshot files fail instead of becoming placeholder images.

```powershell
python -m pytest -q tests/unit/test_rr_route1_traversal_probe.py tests/unit/test_rr_natural_battle_probe.py tests/unit/test_rr_ghost_natural_battle_probe.py tests/unit/test_rr_frame_recording.py
```

The32 focused tests passed. The legacy frozen route reader still uses its known
IRQ-copy address; the new battle trace also records read-only canonical/alias
SaveBlock1/2 comparisons. Those agree in this admitted fixture, consistent with
RR's disabled displacement, and do not replace the independent canonical-pointer
proof in `CURRENT_MAP_CONTEXT.md`.
