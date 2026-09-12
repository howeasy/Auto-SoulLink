# Proposal: finish the Gen 1 RC against its own manifest in one collaboration session

Status: proposal for the project owner and root (`codex:Gen1`), written 2026-09-10 by the
Claude peer while root was unavailable, revised the same day after the owner corrected its
first draft. Companion to `EXECUTION_MODEL_PROPOSAL.md`. No code changed. Decisions
requested in section 7.

Revision note. The first draft proposed a cut list (in-battle faint, native trade, UPR,
browser patcher, Explode and Rival Swap on Gen 1, recovery). Every one of those is a
registered requirement in the owner's release manifest, and several exist to prevent bugs
the manifest names. That draft was wrong and is withdrawn. This revision proposes no cuts.
It proposes an order, a budget and rules for finishing the manifest as written.

## 0. Summary

The release is already defined, precisely: `tests/gen1_release_requirements.json`, 388
requirements in ten stages, verified fail-closed by `tools/verify_gen1_release.py`, ending in
a staged two-player human session. Today 187 requirements have registered proof and 201 do
not. The work is not to decide what the release is. It is to close 201 proofs in an order
that lets each closed stage carry the next, without letting the surrounding documentation and
estimate churn eat the session.

Two things make the 201 tractable. Most of them are per-title rows of one mechanism, so one
real driver closes three at once. And the largest block, the 60 single-player gameplay rows
and the 5 duo rows, is blocked by one technical decision, the frame-credit loop, which
`EXECUTION_MODEL_PROPOSAL.md` proposes to replace with the loop every other generation
already uses.

## 1. Where the release stands

Registered versus missing proof, from `verify_gen1_release.py --list` on 2026-09-10
(`.cache/junit/release_list_2026-09-10.txt`):

| Stage | Registered | Missing | What the missing rows are |
| --- | ---: | ---: | --- |
| canonical-validation | 9 | 3 | constants, rom-layout, generated-data proofs |
| unit-protocol | 110 | 7 | the seven umbrella rows: unit, transport, admission, transactions, server, dom, ap-regression |
| live-memory | 44 | 10 | per-title write-safe, storage and codec-cartridge rows plus AP cold-boot |
| single-player | 0 | 60 | 20 gameplay axes x 3 titles: ball gate, clauses, dupes, dead zones, safari, storage, grants, game corner, Yellow retirement, NPC exchanges, statics, ghosts, evolution, faint/whiteout/rebuild, memorial overflow, reconnect, Rival Swap, Explode, encounters |
| live-duos | 7 | 5 | the five pairings' "existing core scenarios" and Yellow/Yellow full coverage |
| ordered-contracts | 0 | 18 | nine pairings x two HELLO orders |
| manager-isolation | 2 | 2 | same-hash Blue/Blue and Yellow/Yellow Manager launches |
| patch-browser | 2 | 40 | UPR categories x 3 titles, browser clean/randomized x 3, panel and SFX gates |
| trade-receptionist | 13 | 55 | 18 trade axes x 3 titles plus the oracle rows |
| human-session | 0 | 1 | the staged two-player session |
| **Total** | **187** | **201** | |

Two facts about this table matter for planning:

- The single-player stage is zero for sixty because ordinary gameplay is not qualified: the
  frame-credit path refuses every grant once a player has Poké Balls
  (`server/gen1_frame_control.py:51-54`), and the legacy client is not the production runtime.
  No amount of per-axis work closes this stage until a production ordinary loop exists.
- The trade and patch-browser stages are large but their mechanisms are mostly proven: all
  nine receptionist-to-animation pairs pass, the UPR producer and browser downloads pass, the
  panel matrix passes. What is missing is registration against the production runtime and
  the per-title matrix rows, not invention.

## 2. In-battle force faint: where it actually stands

The owner asked why a basic rule has not been tested. The precise answer:

1. **Legacy client.** `lua/clients/gen1_rby_client.lua` writes the party HP immediately and,
   since the sweep branch's first commit, mirrors the write into `wBattleMonHP` for the active
   battler. That is unit-tested against the real Lua profile
   (`tests/unit/test_gen1_force_faint_battle.py`, requirement `runtime.force-faint-unit`,
   registered). It has never been proven against a real battle turn: the duo faint scenario
   stages the battle by poking `wIsInBattle`, so the engine loop that overwrites the party
   struct never runs. That is exactly the hole the audit in CLAUDE.md describes.
2. **RC durable runtime.** The production write path is the held overworld checkpoint
   (`HELD_FAINT_AUTHORITY.md`), which refuses battle by design. So the RC runtime today has no
   in-battle faint at all.
3. **Prototype.** The instruction-authority path (`instruction_authority.py`,
   `battle_force_authority.py`, `lua/instruction_executor.lua`) writes the battle HP at a
   pinned engine instruction under the bounded owner. It has been proven live on the original
   engine in three rounds (`BATTLE_FORCE_FAINT_WINDOW.md` §10-§12): loop-head faint, benched
   faint with the engine's own refusal to send the mon back out, Transform recognition, and,
   on 2026-09-10, the active-mon write at `ExecutePlayerMove+0` on Red, Blue and Yellow with
   the engine printing the faint. Server-verified rows, SRAM unchanged.
4. **Production wiring.** `BATTLE_FORCE_INTEGRATION.md` is a reviewed proposal for wiring the
   prototype into the durable runtime, about 210 lines across root-owned files, awaiting
   root's review. Its two hard blockers (§4 items 0 and 1) are inside the frame-credit loop:
   frames are never issued while a death exists, and the client freezes on any pending
   command, which is a live deadlock for a death delivered mid-battle.

So it has been tested, three rounds live, and the reason it is not in production is the
execution model, not the mechanism. Under the free-run model the wiring is a short hold
armed when a death is pending in battle, which is what the live gate already does.

The owner's yardstick is "behave like Gen 3 does today". Measured against the Gen 3 client
as it is in this tree (`lua/clients/gen3_frlge_client.lua:781-798`, flush `:2543-2568`):

| Situation when `force_faint` arrives | Gen 3 today | Gen 1 legacy client | Gen 1 RC held path | Gen 1 prototype (proven live) |
| --- | --- | --- | --- | --- |
| Out of battle | immediate HP=0 write | immediate | at the next qualified overworld checkpoint (same frame or within a few) | not used |
| In battle, target benched | immediate party-struct write, "KO'd" toast | immediate | **refused until the battle ends** (`gen1_held_faint.lua:38-40`, server `battle_flag==0`) | party HP+status written at the next pinned site; the engine then refuses to send the mon out |
| In battle, target is the active battler | **deferred** to switch-out or battle end, "KO pending" toast; the player keeps using the mon until then | immediate, mirrored into `wBattleMonHP` (unit-tested, never proven against a real turn) | refused until the battle ends | `wBattleMonHP` zeroed at `ExecutePlayerMove+0`; the engine prints the faint that turn |

So relative to Gen 3 the RC runtime misses the benched-in-battle case outright and handles
the active case only after the battle rather than at switch-out. That is a real scope miss in
the RC runtime, and it is one wiring task, not a research problem: the prototype already
covers both rows better than Gen 3 does, and the manifest asks for exactly that
(`runtime.battle-write-slot-bounds`: "active fainting mirrors battle"). The gap exists because
the held overworld checkpoint was built first as the safe write path and the battle path was
left as a prototype behind the frame-credit policy.

## 3. Where the scope churn actually comes from

Not from the feature list. From five habits around it:

1. **Documentation accretion.** 49 reference documents and a status page that appends every
   cutoff and never deletes. `CURRENT_TRUTH_2026-09-10.md` lists 14 contradictions between
   them. Every session pays to re-read them.
2. **Re-estimation instead of registration.** The estimate has been re-cut at least five
   times. The manifest already is the estimate: 201 rows, each either registered or not.
3. **Contracts without a consolidated reference.** The shared framework is the product goal
   and it already has consumers: Gen 2 production records adoption of 20 shared modules in a
   machine-checkable `docs/gen2/shared_adoption.json` (with no production GSC binding
   selected yet), and the UI rework merged 17 shared cuts. What is missing is one place that
   says, per shared module, what the contract is and who binds it. Today that is 37 separate
   `shared-*.md` files on 29 `codex/shared-*` branches, each re-cut when Gen 1 learns
   something, with no Gen 3 binding plan. Frame credits are bound by nobody but Gen 1.
4. **One technical decision blocking sixty rows.** Per-frame server credits make ordinary
   gameplay half speed, fragile (the cold route died on a 0.75 s client deadline while the
   server had already answered, `COLD_ROUTE_FORENSICS_2026-09-10.md`), and unwired past the
   first Mart. Everything in the single-player stage waits on it.
5. **Never committing.** 63 modified and 604 untracked files on an Aug 30 HEAD, the reference
   docs included. Nothing since then is reviewable or revertable.

## 4. Session rules

1. **The manifest is the scope.** No requirement is cut. A requirement is closed only by a
   registered proof that `verify_gen1_release.py` accepts. Anything not in the manifest is
   post-RC by definition, and a new requirement needs the owner's word.
2. **Freeze the churn, not the work.** No new proof documents; results go into the existing
   evidence document for that stage and into the ledger. No new `shared-*.md` files: a shared
   mechanism is a row in `docs/FRAMEWORK.md` with its Gen 1 binding and its planned Gen 3
   binding, and the 37 existing files fold into it. Historical cutoffs move to `archive/`.
   No re-estimates: the status page becomes the registration table above, regenerated from
   the gate.
3. **Commit at the end of every closed item.** Root commits on the sweep branch. An
   uncommitted tree older than one working day stops feature work.
4. **Budget with a stop rule.** Each item below carries a token budget. At 100% the item is
   done or escalated to the owner with a one-paragraph decision. A second budget requires the
   owner's yes.
5. **Reading budget.** A session starts from `RC_CHECKLIST.md` (the table above) and
   `CLAUDE.md`. Other documents are opened when an item names them.
6. **Review scope is the requirement.** A peer review answers whether the gate proves the
   row. Architecture opinions go to the post-RC list unless they block a row.

## 5. The session plan

Ordered so that each item unblocks the next. Budgets are tokens across root, peer and
workers. The order is fixed.

| # | Item | Closes (manifest rows) | Gate | Budget |
| --- | --- | --- | --- | ---: |
| 1 | Adopt the execution-model proposal; commit the tree; fold status into `RC_CHECKLIST.md`; fold shared contracts into `FRAMEWORK.md`; archive cutoffs | none directly | commit exists; checklist regenerates from `--list` | 100M |
| 2 | Free-run observation loop and batch consumer (execution model phases 1-2), writes on hold from the free loop | unblocks single-player, duos, ordered-contracts | bedroom Y/Y at cartridge rate; held-faint and memorial launcher cases pass from the free loop | 500M |
| 3 | Delete the credit path, its tests and its four contracts (phase 3) | none; net lines negative | broad suite, CI ruff selection, Lua gate green | 150M |
| 4 | Wire the in-battle faint as a short hold (the `BATTLE_FORCE_INTEGRATION.md` diff minus its two credit-loop blockers) | `faint-whiteout-rebuild` x3, `runtime.battle-write-slot-bounds` live | the three fight_first gates pass from the production loop; a death delivered mid-battle faints the active mon in the original engine | 250M |
| 5 | Natural-play drivers on the production loop: playthrough, deadzone, dupes, whiteout, evolution, storage, encounters per title | single-player 60 rows, duo 5 rows | each row's registered proof; zero skips | 700M |
| 6 | Ordered HELLO contracts and Manager same-hash launches | 18 + 2 rows | `--list` shows them registered | 100M |
| 7 | Trade-receptionist matrix on the production loop (mechanisms already pass; register per title, add busy-queued and recovery rows) | 55 rows | the nine-pair live matrix plus the recovery and busy cases | 400M |
| 8 | Patch-browser matrix: UPR categories per title, browser E2E (needs `playwright` installed; four integration tests fail today only on that), panel and SFX gates | 40 rows | `--list` shows them registered | 300M |
| 9 | Remaining canonical, unit-protocol and live-memory umbrella rows; fix the five acquisition-policy tests that still assert the pre-Sept-9 outcome | 20 rows | broad suite green, zero failures | 150M |
| 10 | Gen 3 binding plan: one page naming, per `FRAMEWORK.md` row, the Gen 3 file that binds it or "new" | framework deliverable | owner and root accept it | 60M |
| 11 | Full release gate run, then the staged human session and its defect loop | human-session 1 | `verify_gen1_release.py` green, attestation bound | 400M |
| | Reserve (30%) | | | 950M |
| | **Total** | | | **4.06B** |

That is more than "a few billion" by roughly a third, and the honest reason is item 5: sixty
gameplay rows have zero registered proof and need real play on a production loop that does
not exist yet. The reserve is there because item 5 is where defects will surface. If the
session must fit under 3B, the only lever that does not cut a requirement is running items 5
and 7 with three workers in parallel after item 4, which trades tokens for wall-clock and
review load, not scope.

## 6. What this costs

- The framework stays and gains its Gen 3 binding plan. The one shared mechanism removed is
  frame credits, which Gen 3 could not bind anyway (mGBA has no qualified bounded host).
- Documentation stops growing: one checklist, one framework reference, existing evidence
  documents updated in place.
- The owner does the human session, which the manifest already makes the final gate.

## 7. Decisions requested

1. Confirm the manifest is the complete scope and nothing in it is negotiable, or name what is.
2. Adopt the execution-model proposal as the way to unblock the single-player stage.
3. Accept the budget and stop rule, and the owner as the escalation point.
4. Confirm root commits the current tree at the start of the session, before other work.
5. Confirm the framework's core loop is "observe free, hold to write" for every generation.
