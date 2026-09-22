# 09: Generate byte-verified engine-site facts

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P2.2, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Define where every required natural engine event can be witnessed for each title.

**Blocked by:** 08; owner-signed G1; coordinate layout-check ownership with 11.

**Prospective file set:** tools/gen_gen2_engine_signals.py; three engine_signals.json packs; docs/gen2/gen2_engine_sites.md; tests/unit/test_gen2_engine_sites.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Per-game site facts; shared hook registry is ticket 21's separate extraction.

**First red falsifier:** Alter expected_hex and require refusal; a script-bytecode label offered as a CPU site must also be rejected.

**Acceptance:**

- [ ] Cover every F-3 event, including save completion, CONTINUE/New Game/reset, PC operations, acquisitions and hatch.
- [ ] Derive whiteout's CPU site before HealParty, capture party/box forks, and faint's wCurBattleMon context separately for each pret repo.
- [ ] Validate expected bytes at each ROM offset for every admitted artifact; source tables do not close runtime ENGINE obligations.

**Evidence:** F-2/F-3 SOURCE components; PHYSICAL sites belong to 21 and overlay reclosure to 29. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent adversarial site-table review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
