# 34: Implement the qualified partner ghost

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P5.2, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Render the partner's position without changing encounters, collision or saved objects.

**Blocked by:** 33 signed design; G6 shipped; exact post-RC implementation grant.

**Prospective file set:** Exact patch/gen2/src/ghost*.asm files; lua/gen2/ghost.lua; tests/unit/test_gen2_ghost.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Game object engine bindings stay Gen 2; reusable transport/lifecycle behavior remains shared and requires separate extraction grant if missing.

**First red falsifier:** Ghost participation in encounter/collision paths or leakage into a save must fail.

**Acceptance:**

- [ ] Implement complete allocation/update/suspend/save-exclusion/restore/reset/warp/cleanup sequence from the signed design.
- [ ] Exercise occupied-slot, malformed/stale position, disconnect and interruption refusal controls; restore original owned bytes correctly.
- [ ] Generate the ghost overlay reproducibly and retain its matrix state as PLANNED pending 35; reopened obligations remain explicit.

**Evidence:** N-3 MODEL component; unit lifecycle evidence alone admits no ghost artifact. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent non-author frozen ASM/Lua review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
