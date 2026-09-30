# RR gObjectEvents: ROM byte anchor (card RR-SYNTH, 2026-09-27)

`gObjectEvents` on Radical Red is **0x02036E38**, the same EWRAM base as FireRed/LeafGreen
(pokefirered.sym). Proof from the ROM bytes, no .sym (RR has none):

- The literal word `0x02036E38` occurs at **303** word-aligned offsets in
  `gen3_Pokemon_-_FireRed_Version_(USA).gba` and at **378** in `patch/build/slink_RR.gba`.
- **301 of FireRed's 303** offsets hold the same word in the RR ROM (the vanilla code CFRU kept),
  2 are FireRed-only (code CFRU replaced), and the 77 RR-only hits are CFRU's own code
  referencing the same base.
- Independent live confirmation (anchor walk + byte dump, stride 0x24, slot 0 = player) is the
  old-client overworld discovery work behind the peer ghost.

Method (reproducible): scan each ROM for the 4-byte little-endian word at 4-byte alignment and
intersect the offset sets.

Used by `lua/tests/gen3_title_syms.lua` OBJ_EVENTS_ADDR (radical_red), which the duo harness's
`ctx.player_idle`/`ctx.facing` read on RR rows (evolve_gen3).
