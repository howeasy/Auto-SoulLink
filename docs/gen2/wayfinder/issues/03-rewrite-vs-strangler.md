# Rewrite the Gen 2 client or strangle it

Type: grilling
Status: resolved
Blocked by: none

## Question

Gen 1 rewrote into lua/gen1/*; Gen 3 chose a strangler. Which for Gen 2?

## Answer

Rewrite into `lua/gen2/*` mirroring `lua/gen1/*`; the old Gen 2 client, profile and adapter are deleted at cutover. Gen 1 is canonical. owner ruling in chat 2026-09-21, recorded in docs/gen2/REVIEW_RECORD.md, row O-3.
