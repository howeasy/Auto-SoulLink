# Peer ghost feasibility in Gen 2

Type: research
Status: resolved
Blocked by: 14

## Question

Owner: implement if possible. Gen 3 renders the partner as an engine object-event. Does Gen 2 have a spare map-object slot (`wMapObjects` NUM_OBJECTS, `wObjectStructs`), a way to load an arbitrary player sprite/palette, and a per-frame hook cheap enough for 30 Hz position updates? Report feasible / infeasible with citations; if feasible, the minimal patch surface.

## Answer

Research lane R7 (§B), coordinator-verified: verdict FEASIBLE-WITH-PATCH. `NUM_OBJECT_STRUCTS = 13` (`constants/map_object_constants.asm:38`) is the binding concurrency limit (`NUM_OBJECTS = 16` map objects, `:100`); `NOCLIP_OBJS` (OBJECT_FLAGS1 bit 6, `:54`) disables collision; Chris/Kris sprite selection exists via `GetPlayerSprite`. The real patch surface is lifecycle: nothing persists an injected object across `LoadMapObjects` on every warp (no `sMapObjects` in SRAM), so the ghost must be re-armed on every map transition; the per-frame position write is cheap. Open: wild-encounter object iteration, battle-entry struct teardown race, Goldenrod event-flag exclusivity, zero pokegold verification. Owner decision A-2 (gate P5) stands: the plan keeps peer ghost as a conditional gate after G4.

Amended 2026-09-21 (O-13): peer ghost is POST-RC; design research continues now (R9, `docs/gen2/research/peer_ghost_design.md`).

CORRECTED 2026-09-21 (Codex cx-51f03e2d): object structs and map objects are INSIDE wPlayerData and are SAVED to sPlayerData; CONTINUE skips LoadMapObjects; the free-struct predicate is FindFirstEmptyObjectStruct (byte 0 == 0); Gold has a Chris-only sprite table. The design (R9) must add a save-exclusion/restore lifecycle. Still FEASIBLE-WITH-PATCH, post-RC.

DESIGN (R9, `docs/gen2/research/peer_ghost_design.md`, 331 lines, both repos): six hooks with file:line; runtime free-slot check mandatory (five maps carry 14-15 object_events against 12 non-player struct slots); `## Save exclusion and restore lifecycle` covers `SavePlayerData` copying `wPlayerData` verbatim and `MapSetupScript_Continue` skipping `LoadMapObjects`; `OBJECT_SPRITE_X/Y` are screen-relative; Gold is Chris-only and its `wObjectStructs` sits in a UNION; symmetric collision (player walking into the ghost) still open; seven post-RC gate checks. Post-RC P5 input.
