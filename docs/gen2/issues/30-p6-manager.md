# 30: Expose one admitted Gen 2 run family

Status: ready-for-agent

**Current status (2026-09-26): DONE (built ahead of the gate).** `server/manager.py:73` already has the one `("gen2", "Gold · Silver · Crystal", [...])` family row. Formal G6 sign-off (owner tags/ships) has not happened -- G4 itself is still open (ticket 29) and this ticket's own blocker.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P6.1, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Choose Gold, Silver and Crystal cartridges within one Manager run family.

**Blocked by:** 29 and owner-signed G4; P5 is not a prerequisite.

**Prospective file set:** server/manager.py Gen 2 rows; exact template and generated capability output paths, enumerated before dispatch. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Presentation/launcher lifecycle stays shared; per-game names and capability/admission rows are adapter data.

**First red falsifier:** Offering an unadmitted artifact in the picker must fail.

**Acceptance:**

- [ ] Show one family named Gold · Silver · Crystal with permitted title/artifact choices from the qualified matrix.
- [ ] Verify the real Manager/browser launch path and extracted bundle for each admitted title; inspect UI rather than infer success from backend tests.
- [ ] Refuse AP, unselected Crystal revision and unsupported/randomized artifacts; preserve other families' shared UI behavior.

**Evidence:** Phase obligation G6; real browser/launch evidence, separately from unit checks. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent frozen-source/UI reviewer.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
