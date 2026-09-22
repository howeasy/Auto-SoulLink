# 03: Record gate authority and worker ownership

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P0.3, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Make the next authorized action and its owner unambiguous.

**Blocked by:** 01 verified base; 02 reviewed specification and ticket coverage before G0 sign-off.

**Prospective file set:** Coordinator alone: docs/gen2/PLAN.md §6.1 and the active guide/register rows. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Use the sole existing guide checkpoint; no second work ledger.

**First red falsifier:** A signed gate with empty evidence, cut, owner signature or drift-watch fields fails the ledger check.

**Acceptance:**

- [ ] Record G0, G1, G2, G3a, G3, G4, G6 and post-release G5 with actual owner signatures only.
- [ ] Record exact worker files, ACK, source cut, prerequisite, first falsifier, receipt and non-author review; expand prospective globs before dispatch.
- [ ] Reserve one emulator lane; release shared files before another writer claims them.

**Evidence:** Phase obligation G0; authorization records are distinct from SOURCE/MODEL/PHYSICAL evidence. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Coordinator reconciliation and owner G0 signature.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
