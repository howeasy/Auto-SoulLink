# 32: Evaluate the frozen release cut

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P6.3, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Produce a release verdict that fails on every missing applicable obligation.

**Blocked by:** 31; 29 overlay reclosure and all required coverage receipts; owner-signed G4.

**Prospective file set:** Frozen implementation cut and exact runner receipt outputs; coordinator alone writes G6 ledger/guide/register entries. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Bind shared release_lanes core and neutral coverage validator; game manifests supply applicability/oracles.

**First red falsifier:** Any skip, xfail/xpass, deselection, collection error, missing prerequisite or --quick invocation yielding release success must fail.

**Acceptance:**

- [ ] Run verify_gen2_release.py without --quick on the frozen cut with all required admitted artifacts covered and zero skips.
- [ ] Evaluate applicability first: F-1/F-4/F-5/F-7g are SOURCE-only; C-0/C-4/D-13 MODEL-only by design; W-3/W-4/C-5/D-11 need enabling rulings or signed disabled/deferred dispositions; N-3 is post-G6.
- [ ] Derive the required physical count from applicability (41 at the default first G6); require zero unclosed REQUIRED obligations and quote every permitted recorded limit.
- [ ] Require extracted-bundle boots, real Manager verification, independent evaluation and two-person attestation. Only the owner authorizes tagging/shipping.

**Evidence:** Whole 53-row ledger by declared layers; full evidence does not itself grant release authority. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Frozen-source independent evaluator, two-person attestation and owner G6 signature.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
