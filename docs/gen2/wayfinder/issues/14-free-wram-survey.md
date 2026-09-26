# Free WRAM/SRAM for a Gen 2 companion-patch mailbox

Type: research
Status: open
Owner: unclaimed
Blocked by: 11

## Question

Gen 1's companion patch needs a mailbox in free WRAM (Yellow had none, so Yellow trade/panel are recorded limits). Survey pokecrystal@7a7881d / pokegold@656583c for provably unused WRAM (unused section tails, `wUnused*`, union slack) and free ROM space, per title, with the same evidence shape as `docs/gen1_reference` used for Red/Blue. Output: candidate address + size per title, cited, and whether Gold/Silver and Crystal can share one mailbox address. Gates the panel, native trade overlay, native sound and peer ghost designs.

## Answer (source survey complete; allocation dependency open)

Research lane R6 is complete ([source survey](../../research/free_wram_survey.md);
[REVIEW_RECORD](../../REVIEW_RECORD.md), R6). Its negative SOURCE result is that the survey
did not establish a persistent free mailbox in pokecrystal@7a7881d or pokegold@656583c.
In particular, `wUnusedMapBuffer` is cleared on warp; no common mailbox address was established.
This does not prove allocation impossible, and it is not a live feasibility or PHYSICAL pass.

The remaining dependency is **open and unclaimed**: [the pinned-build ticket](11-pinned-rom-build.md)
must supply the P1 per-title linker maps/slack report. Per [PLAN §11](../../PLAN.md), allocation
then needs an explicit banking/ownership/lifecycle contract and complete writer exclusion,
or a separately reviewed patch that establishes them. No fallback mailbox is selected;
`sScratch` is actively used. A live memory watch alone cannot prove absence of writers.
Without that allocation evidence, P4 stops for an owner decision; O-4's first-RC native scope
remains unchanged. Ghost remains post-G6 under O-13. All gates remain unsigned.

## Comments

2026-09-21 history: R6 surveyed the Gen 1 30-byte mailbox precedent (14 bytes used),
labelled unused WRAM/SRAM/HRAM, and union slack. It reported no qualifying source-only
candidate and deferred linker slack/ROM placement to P1; seven questions were recorded in
the source note. The earlier ticket said "Ticket stays claimed until P1 reports the linker map"
without naming a current owner.

2026-09-22 reconciliation: the prior coordinator closed all research lanes. The stale claim
is released; only the existing linker-map/allocation dependency remains open and unclaimed.
This preserves the research result and adds no research or implementation grant.
