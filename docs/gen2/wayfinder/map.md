# Gen 2 wayfinder map

Tracker: local markdown (`docs/agents/issue-tracker.md`). Charted 2026-09-21 by the Gen 2 planning
coordinator (session df123a) in worktree `claude/gen2-planning-kickoff-a18801` at `4bf0f3b`.
The 22 original wayfinder tickets live in `issues/` and remain linked below. This is the
research/decision index; implementation tickets live separately in `docs/gen2/issues/`.
Reconciled 2026-09-22 from planning cut `9c7e7ac` against the latest owner rulings in
[PLAN §0](../PLAN.md#0-owner-decisions-already-taken-2026-09-21) and
[REVIEW_RECORD](../REVIEW_RECORD.md#owner-rulings-chat-2026-09-21), which supersede older ticket text.

**2026-09-26 status note:** this map is a HISTORICAL record of the 2026-09-21/22 planning and
research phase. Every dependency this map once left open or unclaimed (P1 build/linker-map
evidence, ticket 11; the mailbox allocation, ticket 14; P2 site pins, ticket 12) has since closed
in implementation, current through P4: Gold/Silver/Crystal are all built, G1-ADMITTED, and carry
committed PHYSICAL receipts (98/98 duo sweep cells at code digest `e8ca0067`, tag
`gen2-rc-evidence-2026-09-25`). The one open item is the owner's G4 signature promoting the three
overlay artifacts from `BUILT` to `ADMITTED` -- see [`docs/gen2/issues/29-p4-overlay-evidence.md`](../issues/29-p4-overlay-evidence.md)
for the current, code-verified gap list. Read the individual answers below for the research they
still hold; read `docs/gen2/issues/*.md` for current implementation status.

## Destination

An owner-approved Gen 2 plan set under `docs/gen2/` (PLAN.md with gates requiring signatures, the
requirements ledger skeleton, comparison and binding plan) collapsed by `/to-spec` into
`docs/gen2/spec.md` and by `/to-tickets` into `docs/gen2/issues/`, so that implementation
sessions can start from tickets off a signed G0. The map is done when no decision remains
before someone builds Gen 2 the way Gen 1 was built. No owner decision remains open before G0;
all gates remain unsigned. Planning/research resolution is not implementation or release approval.

## Notes

- Gen 1 is canonical (`docs/gen1_requirements.md`, `docs/gen2/GEN1_STANDARD_DIGEST.md`).
  Every Gen 2 decision cites its Gen 1 precedent; deviations carry a reason.
- Existing Gen 2 code is a hypothesis, never evidence (brief rule 0.8). pret at the pins in
  ticket 05 is the authority; SOURCE / MODEL / PHYSICAL stay distinct; MODEL never closes a row.
- Historical research and peer assignments are recorded in `REVIEW_RECORD.md`; those lanes
  are closed. Current ownership and dispatch follow the sweep worktree's
  `docs/agents/orchestration.md` and sole checkpoint in `RC_MASTER_GUIDE.md`.
- Reuse decision: follow PLAN §5.15; reusable lifecycle, transport, state and presentation
  belong in shared modules, while adapters own game facts. This reconciliation adds no implementation.
- A resolved research ticket records an answer, not a PHYSICAL pass. Outstanding build,
  allocation and qualification dependencies remain explicit; this map opens no new research.

## Decisions so far

- [Name the destination of the Gen 2 map](issues/01-destination.md): plan -> spec -> tickets, then implementation off signed gates.
- [Which Gen 2 titles are in scope](issues/02-title-scope.md): Gold, Silver and Crystal all full targets; Crystal first.
- [Rewrite the Gen 2 client or strangle it](issues/03-rewrite-vs-strangler.md): rewrite into `lua/gen2/*`; old code deleted at cutover.
- [Native features in the first Gen 2 RC](issues/04-native-features.md): trade, START-menu panel and sound in the first RC; peer ghost is post-RC, P5 only after G6 (O-4, O-13).
- [Which pret commits are the Gen 2 pins](issues/05-pret-pins.md): pokecrystal `7a7881d`, pokegold `656583c`, Archipelago-Crystal `6.0.0-rc.1`.
- [Own ledger and runner or rows in the Gen 1 runner](issues/06-ledger-identity.md): own ledger, manifest, runner and tag.
- [Fixture strategy and the New Bark lock](issues/07-fixtures-new-bark.md): eight played fixtures: town + Route 29 battle for each title, plus Crystal `town_ot2` / `battle_ot2` controls; the playthrough decision stays closed.
- [Archipelago Crystal scope](issues/08-archipelago-scope.md): documented now, post-RC project.
- [Which duo pairings the lanes run](issues/09-duo-pairing.md): all GSC pairings allowed by O-16: G↔G, G↔S, G↔C, S↔S, S↔C, C↔C, symmetrically, under one `gen2_gsc` foundation. Representative duo lanes stay C↔C and G↔S, plus one C↔G `link` scenario; runtime qualification remains pending.
- [Gen 2 overworld-safe checkpoint predicate from pret](issues/10-overworld-checkpoint-source.md): anchor in `OWPlayerInput` before `CheckAPressOW` + strict predicates; live gate open.
- [Reproducible pinned ROM builds and .sym files for Gen 2](issues/11-pinned-rom-build.md): P1 build/hash/linker-map dependency remains open; no build result is inferred from closed research.
- [Candidate Gen 2 execution-site table](issues/12-engine-sites.md): research informs P2; bank/address/expected-byte pins still depend on the pinned build, and physical site qualification is pending.
- [Where Gen 2 writes the received mon in a link trade](issues/13-link-trade-routine.md): SOURCE sequence `LinkTrade` -> `AddTempmonToParty` -> `EvolvePokemon` -> `SaveAfterLinkTrade` (`link.asm:1994-2044`); not a host-durability pass.
- [Free WRAM/SRAM for a Gen 2 companion-patch mailbox](issues/14-free-wram-survey.md): source survey complete; remaining P1 linker-map/persistent-allocation dependency **open and unclaimed**. No mailbox or live feasibility is established.
- [Native trade entry point for Gen 2](issues/15-native-trade-design.md): two takeover sites (receptionist specials + `LinkTrade` selection/animation); commit chain reused; mailbox awaits the allocation dependency.
- [Native sound sites for Gen 2](issues/16-native-sound-sites.md): `GetJoypad` is a conditional design candidate, not every-tick service: the overworld path skips it when `wMapEventStatus == MAPEVENTS_OFF`, including ordinary stepping; text/idle-menu loops reach it. Context-specific proofs remain at P4 (PLAN §5.12; Codex `cx-51f03e2d`).
- [Peer ghost feasibility in Gen 2](issues/17-peer-ghost-feasibility.md): completed SOURCE design research, not a live feasibility pass; P5 starts only after G6 and its signed design/allocation prerequisites. Save-exclusion/restore and CONTINUE lifecycle remain required by PLAN §5.12/§6.
- [CGB vs DMG mode for Gold/Silver in BizHawk](issues/18-cgb-mode-and-gamedb.md): gamedb says GBC for all four sha1s; `Auto` boots CGB; pin `ConsoleMode` anyway.
- [Crystal 1.0 vs 1.1 admission](issues/19-crystal-revision.md): use the local dump's revision, hashed at P1; the other revision is a recorded limit (O-12).
- [Known-positive stat control for Gen 2](issues/20-stat-control.md): `CalcMonStats` formula, DV gender/shiny/Unown, 12 recompute sites.
- [Gen 2 encounter and area-map generation from pret](issues/21-encounter-tables.md): per-title `_GOLD/_SILVER` branches; time of day never splits an area. Roamers are standalone extra catches under `legend_<species>`, never consuming/locking the map; the Bug-Catching Contest owns zone `national_park_contest` (O-17/O-18).
- [Fixture bootstrapper frame budget and the Poke Ball source](issues/22-fixture-frame-budget.md): no ball before the Mr. Pokemon errand; owner: inject balls for the fixture; starter stays played.
- Trade extras: no Time Capsule; held items validated and carried; mail a recorded limit (O-14).
- Keys retain `DVs:OT:species`; a hatched egg is a gift capture under `gift_daycare` using the hatchling's key (O-15; PLAN §5.14). Gender/shininess and acquisition namespaces are adapter facts.
- Manager: one family **Gold · Silver · Crystal** (O-16).

## Not yet specified

The prior coordinator closed all research lanes. As of 2026-09-26, the P1 build/linker-map
evidence, the persistent-allocation dependency and P2 site pins have all closed in
implementation (see the 2026-09-26 status note above and `docs/gen2/issues/{04,09,11,12,14,26}*.md`).
The remaining gap before G4 is the owner's overlay-admission signature (`docs/gen2/issues/29-p4-overlay-evidence.md`).
UPR randomizer scope remains the recorded P6 owner question in PLAN §10; no new ruling is made here.

## Out of scope

- Archipelago Crystal full rules support and native features (post-RC, ticket 08).
- Peer ghost in the first RC: post-G6 work only (O-13).
- Time Capsule trades and mail (recorded limits, O-14); Mobile Adapter and Battle Tower (PLAN §10).
- `playthrough`, `deadzone` and `dupes` scenarios on Gen 2 (owner decision recorded in
  `docs/gen1_gen2_runtime_checks.md:205-213`, reaffirmed 2026-09-21).
- The Crystal revision other than the local dump selected and hashed at P1 (O-12).
- Non-US ROMs (Japanese, European, Australian Crystal) and Virtual Console builds.
- Yellow-specific Gen 1 work (deferred by the owner, unrelated to this map).
