# Native features in the first Gen 2 RC

Type: grilling
Status: resolved
Blocked by: none

## Question

Rules-only RC first, or native trade, panel and sound in the first RC?

## Answer

Companion-patch native trade, START-menu panel and native sound are required in the first
Gen 2 RC (O-4). Peer ghost is post-RC (O-13): P5 starts only after G6 and its signed design
and allocation prerequisites. The current ruling is recorded in
[PLAN §0/§6](../../PLAN.md) and [REVIEW_RECORD O-4/O-13](../../REVIEW_RECORD.md).

Resolved means the scope decision is settled. Mailbox allocation and P4 sound/context
qualification remain dependencies; no PHYSICAL pass, live feasibility or gate signature is implied.

2026-09-26 update: those dependencies have since closed -- panel (ticket 26), native sound
(ticket 27) and native trade (ticket 28) are all built with PHYSICAL PASS receipts
(`tools/verify_gen2_release.py --lane live-gates` / `--lane live-trade-gates`). The remaining
gap before the first RC is the owner's G4 signature promoting the overlay artifacts to
ADMITTED (`docs/gen2/issues/29-p4-overlay-evidence.md`); no gate signature is implied here.

## Comments

2026-09-21 history: round 2 Q9 said peer ghost "if possible, implement". O-13 superseded
that timing with post-RC work; the subsequent source/design research is complete.
