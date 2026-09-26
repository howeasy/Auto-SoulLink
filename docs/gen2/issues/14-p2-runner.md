# 14: Bind the fail-closed release runner

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P2.7, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Ensure incomplete or unrun Gen 2 qualification cannot be reported as a release pass.

**Blocked by:** 13; owner-signed G1; adopted release_lanes core verified in 01.

**Prospective file set:** tools/verify_gen2_release.py skeleton and exact lane-registration files named at dispatch. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Bind tools/release_lanes.py from the approved base; one shared execution core.

**First red falsifier:** A skip, xfail/xpass, deselection, collection error, missing prerequisite or --quick result treated as release success must fail a control.

**Acceptance:**

- [ ] Register unit, rom-layout, lua-parse, per-title generated profiles, fixtures, patch-build, live-gates, live-new-gates and duo-pairs.
- [ ] Empty or unrun required lanes fail closed; pre-runner checks are named and enforced.
- [ ] Keep quick feedback distinct from the full release verdict; no second Gen 2 runner core.

**Evidence:** Phase obligation G2; runner success alone closes no behavior row. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent runner and failure-accounting review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
