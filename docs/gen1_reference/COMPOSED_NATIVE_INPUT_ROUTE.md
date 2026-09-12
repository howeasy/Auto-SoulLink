# Honest cold-start route to a composed native trade

The next live proof must start both reproduced native cartridges from blank
private SaveRAM, publish their real New Game receipts, and let the ordinary
controller obtain every subsequent frame credit. No fixture party, event-flag
write, direct routine call, or injected stop is part of this route.

The existing `lua/tests/gen1_playthrough.lua` is a fixture builder: it writes
options, starters, balls, and Oak flags. Reuse only its coordinate navigation
ideas through an input-only state machine driven by actual frame changes. Its
direction holds explain a useful detail: a turn tap alone does not walk; hold a
direction until the observed tile changes, with a bounded stall/detour rule.

Source-derived route, shared where the cartridges agree:

1. Bedroom stairs `(7,1)` → first floor; first-floor door `(2,7)` → Pallet.
2. Walk toward Pallet's north exit, around x10. Oak triggers at y1 in Red/Blue
   and y0 in Yellow. Advance scripted text with real A presses while the script
   owns input, then wait for the laboratory arrival.
3. Red/Blue: interact with the Charmander ball at `(6,3)` from its adjacent
   tile. Yellow: interact with the Eevee ball at `(7,3)`; the rival takes it and
   the original script gives Pikachu. Select the starter and handle naming
   through the native UI. Declining a nickname yields the cartridge's valid
   species name and is sufficient for a named record.
4. Permit the actual laboratory rival battle. Ordinary Fight/first-move inputs
   are enough; winning is unnecessary for route validity. Both source scripts
   explicitly call `HealParty` after this battle, including the loss path.
   Verify both starter source/owned inventory settlements and the resulting
   linked identities before attempting the trade.
5. Leave the lab at `(4,11)` or `(5,11)`, head through Route 1 to Viridian, and
   enter the Pokémon Center at `(23,25)`. Wild encounters must use real battle
   inputs (fight or run); no battle-state edits or damage rigging are allowed.
6. In the Center, approach the link receptionist at `(11,2)` from `(11,3)` and
   face up. The text pointer uses `script_cable_club_receptionist`, which is the
   actual dispatch intercepted by the native companion. Wait for the precise
   native query checkpoint and the acknowledged ordinary→native frame loan.
7. Select SLink and the linked starter through real input, then require both
   original trade animations, typed command/file receipts, native frame return,
   and acknowledged handoff before further ordinary movement.

Do not visit the Mart, do the Parcel/Pokédex errand, or trigger the old-man
tutorial. Those are unnecessary for reaching this receptionist. Keep balls
absent so the presently enabled pre-ball execution policy remains applicable.
The old fixture comment claiming Oak never gives balls is inaccurate: both
source trees contain a conditional five-ball gift after the Route 22 rival
event; this route never reaches that branch.

Read-only state to drive and diagnose the route: `wCurMap`, `wXCoord`, `wYCoord`,
`wJoyIgnore`, script indices, battle/menu state, party count, and the starter
completion flag. Derive addresses from the selected pinned symbols. Pulse menu
buttons using actual frame counts, not held-service polling iterations. At every
stage record its entry/exit frame, map/coordinates, and screenshots. A stuck
stage should produce evidence and hold; it must never repair progress by writing
game state.

Primary source locations under `.cache/pret/{pokered,pokeyellow}`:

- `data/maps/objects/RedsHouse{1F,2F}.asm`
- `scripts/PalletTown.asm` (`PalletTownDefaultScript`)
- `data/maps/objects/OaksLab.asm` and `scripts/OaksLab.asm`
- `engine/menus/naming_screen.asm` (`AskName`)
- `data/maps/objects/ViridianCity.asm` and `ViridianPokecenter.asm`
- `scripts/ViridianPokecenter.asm`
- `engine/battle/core.asm` (`DisplayBattleMenu`)

The route is source-grounded planning, not a completed gameplay test. Exact
grass avoidance, menu timing, and total duration still need live confirmation.
