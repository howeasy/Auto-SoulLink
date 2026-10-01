# 02: Publish the specification and implementation tickets

Status: ready-for-agent

**Current status (2026-09-26): DONE.** this deliverable is `docs/gen2/spec.md` plus exactly these 35 `docs/gen2/issues/*.md` files -- self-evidently published, since they exist and are being read.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P0.2, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Give each worker one bounded ticket for each reviewed binding substep.

**Blocked by:** 01 base receipt before finalizing source bindings; documentation drafting may run during base preparation.

**Prospective file set:** docs/gen2/spec.md and exactly these 35 docs/gen2/issues/*.md files, with separate authorship claims. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Preserve PLAN §5.15 reuse decisions; each extraction needs its own exact claim and Gen 1 rebind where applicable.

**First red falsifier:** A missing or duplicate binding-substep ticket, an unmapped requirement, or an Archipelago implementation ticket fails coverage.

**Acceptance:**

- [ ] Map all 35 binding substeps and all 53 requirement IDs to ticket acceptance without inventing new scope.
- [ ] Preserve all G/S/C title pairings, first-RC panel/sound/trade, post-G6 ghost, and AP exclusion.
- [ ] Keep SOURCE, MODEL and PHYSICAL distinct; specification readiness grants no execution authority; source pseudocode is independently rederived.

**Evidence:** Phase obligation G0; documentation coverage only. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Non-author review of spec and ticket set, then owner at G0.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
