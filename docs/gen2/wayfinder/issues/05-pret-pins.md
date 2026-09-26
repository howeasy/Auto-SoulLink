# Which pret commits are the Gen 2 pins

Type: grilling
Status: resolved
Blocked by: none

## Question

Keep the cached .cache/pret shas (3438c70 / e78abb8) or move to fresh upstream HEAD?

## Answer

Fresh upstream HEAD: pokecrystal `7a7881d0d62e0ddbd82dcf10e7116807487ac651`, pokegold `656583c939d30f920a316177311a502dd222b57c` (git ls-remote 2026-09-21). Archipelago Crystal pinned to gerbiljames/Archipelago-Crystal release `6.0.0-rc.1` (commit `0b11931c`). A scratch RGBDS build showed zero address changes for every symbol the plan uses vs the cached shas (docs/gen2/research/pret_gen2_symbols.md, Delta section). owner ruling in chat 2026-09-21, recorded in docs/gen2/REVIEW_RECORD.md, row O-5.
