# Native sound sites for Gen 2

Type: research
Status: resolved
Blocked by: 14

## Question

Gen 1 native sound uses semantic codes at mailbox +7 and two main-thread sites (DelayFrame bridge + Joypad, because menus never reach DelayFrame). Find the Gen 2 equivalents (`DelayFrame`, `Joypad`, `PlaySFX`/`PlayCry`, sound-bank ids in `constants/sfx_constants.asm`) and whether the Gen 1 240-frame stamped hold pattern applies unchanged.

## Answer

Research lane R7 (`docs/gen2/research/sound_sites_and_peer_ghost.md` §A), coordinator-verified against pokecrystal@7a7881d: `Joypad::` is a `reti` stub (no second hook site as in Gen 1); `GetJoypad` is reached every overworld tick from `HandleMap` -> `HandleMapTimeAndJoypad` (`engine/overworld/events.asm:142, 193-199`) AND from text/menu waits, so the Gen 1 two-site scheme becomes ONE site (`GetJoypad`) in Gen 2. `DelayFrame` is skipped when `wOverworldDelay == 0` (`events.asm:182-186`) and cannot anchor the service alone. VBlank-time `PlaySFX` is unsafe (same reentrancy class as Gen 1; structural, not measured). Gen 1 carries three semantic codes (success/failure/boo), not six; candidate Gen 2 ids `SFX_ITEM`/`SFX_CAUGHT_MON`, `SFX_WRONG`, `SFX_BUMP` (unverified). Per Codex CR1 finding 6 this is the DESIGN CANDIDATE only: the P4 sound gate must still prove caller/context ABI, bank/register preservation, busy/request consumption and bounded overworld/menu/battle service with reset controls. Gold/Silver not independently verified (open).

CORRECTED 2026-09-21 (Codex cx-51f03e2d): GetJoypad is not an every-tick site (skipped when wMapEventStatus == MAPEVENTS_OFF, which ordinary stepping sets); text and idle-menu loops do reach it; wOverworldDelay is a per-iteration residual budget. PlaySFX reentrancy counterexample exists; sound service stays main-thread and is qualified per context at P4. See the correction header on the R7 note.

2026-09-26 update: built and PHYSICALLY qualified per context -- sound ASM under `patch/gen2/src`, the
SE table in `lua/gen2/panel.lua` (see [ticket 27](../../issues/27-p4-sound.md)); `tools/verify_gen2_release.py --lane live-gates`
PASSES (`sfx_gate` rows for crystal/gold/silver, 2026-09-26).
