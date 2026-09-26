# 13: Map every evidence obligation

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `docs/gen2/gen2_coverage_map.md`, `tools/coverage_map.py` (the neutral shared validator), `docs/shared-coverage-map.md` and `tests/unit/test_gen2_coverage_map.py` all present; `tools/verify_gen2_release.py --list` runs a `coverage-map` lane consuming it.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P2.6, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Make missing stimuli, controls, artifacts or independent oracles block qualification visibly.

**Blocked by:** 09, 10 and 12; owner-signed G1.

**Prospective file set:** docs/gen2/gen2_coverage_map.md; tests/unit/test_gen2_coverage_map.py. Separate CREATE claim: tools/coverage_map.py and docs/shared-coverage-map.md. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** PLAN §5.15h creates a neutral validator with Gen 2 as first consumer; no invented Gen 1 rebind. Contract tests must run unchanged for a second binder.

**First red falsifier:** Delete a row, receipt, stimulus or artifact join, or invent a MODEL exemption, and require validation failure.

**Acceptance:**

- [ ] Map all 53 requirements and every protocol §9 assertion to stimulus, artifact, positive/refusal controls, oracle, receipt marker and lane.
- [ ] Separate natural engine behavior from command-executor tests; include C↔G link, all acquisitions, same-frame reads and temporal write provenance.
- [ ] Zero UNMAPPED allows G2 completeness sign-off only; mark SOURCE-only, MODEL-only, conditional and post-G6 obligations explicitly.

**Evidence:** C-0/C-4/D-13 mapping; all other requirement coverage. Default first-G6 required physical count is 41, derived from applicability. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent adversarial coverage review; separate exact shared CREATE grant before authoring.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
