# 12: Generate the complete title packs

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `tools/gen_gen2_{area_map,encounters,statics,trainers,admission}.py` and the generated per-title packs under `data/games/gen2_{crystal,gold,silver}/` all present, with `tests/unit/test_gen2_{area_map,encounters,statics,trainers,admission}.py`.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P2.5, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Give Gold, Silver and Crystal the correct encounters, locations, gifts and admission facts.

**Blocked by:** 08 and 11; 06 matrix ownership handoff; owner-signed G1.

**Prospective file set:** tools/gen_gen2_{area_map,encounters,statics,trainers,admission}.py; exact per-title pack JSONs including gifts; tests/unit/test_gen2_{encounters,admission}.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** ROM/story/acquisition facts remain in packs/adapters; shared rules receive their outputs.

**First red falsifier:** A Gold-versus-Silver encounter control must fail if one shared encounter pack is substituted.

**Acceptance:**

- [ ] Complete all three title packs before G2; Crystal is the first increment, not the only gate product.
- [ ] Keep time of day within one area; hatch uses gift_daycare, roamers use standalone legend_<species> without consuming/locking the map, contest uses national_park_contest.
- [ ] Preserve 06's selected Crystal revision and artifact dispositions; refuse unsupported data.

**Evidence:** F-7g SOURCE-only; S-8/S-9g/S-10g/D-1 SOURCE components. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent pack and acquisition-policy review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
