# 01: Freeze the implementation base

Status: ready-for-agent

**Current status (2026-09-26): DONE.** implementation worktree established (local master now `1d02702f`, Gen 1+2+3 merged); Gen 2 built through P4 (tickets 04-29 below). The `docs/gen2/PLAN.md` §6.1 G0 row is still blank (`PLAN.md:202`) -- coordinator-owned, unsigned by the owner.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P0.1, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Provide an isolated, reproducible starting cut whose shared pairing and release machinery are known.

**Blocked by:** None for authorized P0 preparation; G0 remains unsigned until the owner signs the reviewed base.

**Prospective file set:** Implementation worktree; coordinator-owned PLAN §6.1 G0 evidence cell. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Reuse the adopted Gen 3 pairing and release-lane core; record drift instead of inventing a parallel implementation.

**First red falsifier:** A missing cherry-pick or an unexplained shared-file drift makes the base receipt fail.

**Acceptance:**

- [ ] Record local master 8f6a986 and the resulting integrated SHA after 80261f3, 959c578 and 910dbdd; verify ancestry and patch content, never infer ancestry from a cherry-pick.
- [ ] Record the Gen 3 tip and a diff of the adopted shared files; preserve any drift decision.
- [ ] Run the required Gen 1 regression baseline on the frozen cut; unavailable or unrun physical lanes remain OPEN.

**Evidence:** Phase obligation G0; SOURCE cut proof and separately classified regression receipts. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent Codex reviewer; owner signs G0.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
