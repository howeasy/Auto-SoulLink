# Free WRAM/SRAM for a Gen 2 companion-patch mailbox

Type: research
Status: resolved (2026-09-26; was open/unclaimed)
Blocked by: 11 (closed)

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

2026-09-26 update: the dependency closed. Owner ruling O-27 (`docs/gen2/REVIEW_RECORD.md`)
allocated the mailbox as unused WRAM0: Crystal `$CFD8-$CFFF` (40 B), Gold/Silver `$C1D9-$C1FF`
(39 B), reserved as a fixed SECTION in the patched build, cleared by Init (not New Game), never
saved, never touched by link code. Writer exclusion is proven by the `w6_gate` rows of
`tools/verify_gen2_release.py --lane live-gates` (PASS for crystal/gold/silver, 2026-09-26).
Implementation: [ticket 26](../../issues/26-p4-panel-mailbox.md), `data/gen2/linker_slack.json`,
`patch/gen2/**`.
