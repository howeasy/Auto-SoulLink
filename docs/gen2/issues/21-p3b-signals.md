# 21: Bind and qualify natural engine signals

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `lua/gen2/signals.lua`, `tests/unit/test_gen2_signals.py` + `test_gen2_signals_v2.py` present; engine-signal PHYSICAL evidence is the same inspect_run receipt as ticket 20 plus the duo receipts of ticket 24.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.4, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Observe complete natural event sequences at verified CPU sites without polling guesses.

**Blocked by:** 20 and 09; frame-alignment probe passed per admitted title; owner-signed G2/G3a as applicable; sole emulator lane.

**Prospective file set:** lua/gen2/signals.lua; tests/unit/test_gen2_signals.py; signal rows of tests/live/test_gen2_new_gates.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** §5.15a separate exact claim: lua/hook_registry.lua, lua/gb_hook_binding.lua, docs/shared-hook-registry.md and Gen 1 signals/entry consumers. Preserve owned handles, queue order, error latch and transactional cleanup; platform bank/PC mapping is explicit.

**First red falsifier:** Wrong expected_hex, wrong bank or a script-bytecode address offered as a CPU hook must refuse to start/fire.

**Acceptance:**

- [ ] Prove each required engine sequence per title with bank checks and same-frame alignment; include F-3's full event inventory.
- [ ] Observe party and box capture independently of BOX_FULL with non-final/twentieth-slot controls; capture faint/poison snapshots before healing; mask battle result.
- [ ] Publish hatch at hatch completion as gift_daycare, never GiveEgg; observe roamer and contest zones; preserve evolution/NPC-trade key-change ownership.
- [ ] Rebind Gen 1 with its required live-new-gates, duo-pairs, inspect-purergb and duo-pairs-purergb evidence; only ENGINE obligations close from hook firing.

**Evidence:** F-2/F-3 PHYSICAL; S-1–S-10g ENGINE components; behavior/persistence receipts remain in 24. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent adversarial frozen signal-binder review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
