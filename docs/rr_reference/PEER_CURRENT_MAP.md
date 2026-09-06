# RR peer map tagging across connections

The peer sender and receiver used the player's ObjectEvent map fields as its
current map. A natural Viridian-to-Route1 connection preserves those fields as
the object's spawn map. That mislabeled outgoing world positions and caused
incorrect same-map decisions in the receiver.

## Actual observation and reproduction

Private run `route1_traversal_40` used ordinary game input, frozen03 ROM SHA256
`3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301`,
and the reviewed MGM-on Viridian battery fixture. Its result SHA256 is
`4addaa88d7e3a72d0302ef23b8f3342cd6f19d773acd68887173331c281f5f4c`.
The exact source/fixture/emulator bindings and three selected observations are
retained in `tests/rr/fixtures/route40_map_connection.json`.

| Frame | Current SB1 map | Player OE spawn map | Layout | Player grid |
|---|---|---|---|---|
| 1913 | 3:1 (Viridian) | 3:1 | `082DE3E4` | 29,46 aligned |
| 1914 | 3:19 (Route1) | 3:1 | `082E55CC` | 17,7; previous17,6 |
| 1931 | 3:19 (Route1) | 3:1 | `082E55CC` | 17,7 aligned |

SaveBlock1 was at `0202572C`, obtained through the RR profile pointer `03003840`.
Its current group/number are bytes`+4/+5`, matching the existing
`games.gen3_frlge.profiles.radical_red.SB1_PTR_ADDR` and `memory_gba.getCurrentMap`
reader. At frame1931 the old position sampler correctly reconstructed pixels
`272,112` but still labeled them map3:1. This is independently visible in the
recorded trace; no battle flag or map coordinate was injected for the observation.

Before correction, three tests executing the unchanged actual Lua sender/receiver
reproduced outgoing map3:1 instead of3:19, refusal to show a Route1 peer, and
acceptance of a Viridian peer while the local player was on Route1. These are
controlled-RAM reproduction tests, distinct from the recorded game observation.

## Bounded correction

`rr.peer_position.current_map` now reads current location through the checked RR
SaveBlock1 pointer. Invalid, unaligned or truncated pointers return unknown. The
sampler binds its calibration to current map, layout and SaveBlock1 identity, and
the wire sender uses that same sampled map. A connected transition seen midstep
still waits for an aligned position anchor.

The receiver shares this read-only map reader and compares the peer's current map
with it. On a local map/layout/saveblock change, it drops pending old-map Lua
interaction state and requests ordinary native ghost cleanup. Before publishing
new-map avatar/position data it requires both the retained successful CLEAR receipt
and native `ghost_oe == 0xFF`. CLEAR acceptance only sets native desired activity
to zero; actual resource removal occurs on a later field frame. An unrelated
mailbox completion cannot erase the retained receipt. Refused/failed cleanup blocks
the receiver, and an unknown current map publishes no native state. Debug state
exposes whether the map is unknown or cleanup is pending/failed.

Cancellation and disable/re-enable preserve an in-flight map cleanup and its
retained receipt. They do not enqueue a second untracked clear. Cleanup may finish
on a qualified field frame while presence is disabled; new ghost state remains
disabled. Repeated `PG.init()` is idempotent and cannot discard that obligation or
enable the feature. Resetting the map latches the current interaction counter, and
clear/disable/other-map cancellation drops pending old-peer interaction events.
A nil position packet remains invalid input, not an implicit cancellation. A fresh
module reload still needs the separate host/session reconciliation authority.

The wire schema, native renderer, mailbox implementation and frozen native
candidates remain unchanged. This adds no EWRAM allocation and grants no durable
session or recovery authority. The helper stays specific to the pinned RR profile.

## Validation limits and follow-ons

Tests cover current-map tagging, reciprocal receiver decisions, same-layout map
changes, stale spawn-map changes, pointer rejection, old-map interactions, delayed
and failed native cleanup, receipt survival, and replay of the recorded aligned
positions. The intermediate recorded sample omitted raw sprite pixels because its
old sampler rejected the midstep; the replay checks its map facts without inventing
those missing pixels. No new emulator or duo run is claimed by this Lua correction.

Native `drive_ghost` and native storage preparation context still read OE map
fields. Their current-map/scene-generation migration requires a separate native
candidate and validation; the Lua receiver cleanup does not establish their full
safety. Peer packet freshness, battle/warp resources, surf/fishing effects and
physical corrected-client duo behavior also remain separate acceptance gates.

Reproduce the selected checks from the RR worktree:

```powershell
python -m pytest -q tests/rr/runtime tests/unit/test_rr_peer_maps.py tests/unit/test_rr_peer_position.py tests/unit/test_rr_mailbox_v2.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
```
