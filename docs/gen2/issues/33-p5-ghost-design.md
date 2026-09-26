# 33: Sign the ghost save-exclusion design

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P5.1, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Define a partner ghost that cannot enter saved game data or interfere with local play.

**Blocked by:** 32 with G6 actually shipped; 26 proven mailbox; historical wayfinder 17/R9 feasible design and owner post-RC sign-off.

**Prospective file set:** Decision section of docs/gen2/research/peer_ghost_design.md; PLANNED ghost matrix rows only. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Gen 2 object facts remain per game; generic lifecycle/transport portions must use shared contracts where applicable. Gen 3 object-event code is not a portable binder.

**First red falsifier:** A design lacking explicit save-exclusion and restore ownership must be refused.

**Acceptance:**

- [ ] Address saved wObjectStructs/wMapObjects and CONTINUE's skipped object reload, including save interruption, reset, warp and cleanup.
- [ ] Use the engine's byte-0 free-struct predicate and title-specific sprite facts, including Gold's Chris-only table.
- [ ] Record mailbox/object ownership, writer exclusions, artifact reopen set and exact next implementation scope; no ghost hash/admission is invented.
- [ ] Obtain owner design signature and non-author review after G6 shipment.

**Evidence:** N-3 SOURCE component, exclusively post-RC. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent non-author design review and owner post-RC authorization.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
