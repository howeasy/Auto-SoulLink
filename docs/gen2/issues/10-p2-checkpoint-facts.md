# 10: Define the source-qualified write checkpoint

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `tools/gen_gen2_write_checkpoint.py`, `data/games/gen2_{crystal,gold,silver}/write_checkpoint.json` and `tests/unit/test_gen2_write_checkpoint.py` all present.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P2.3, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Describe a safe, caller-bound write boundary without admitting heuristic single-byte checks.

**Blocked by:** 08; owner-signed G1; layout-check consumption from 11 before exit.

**Prospective file set:** tools/gen_gen2_write_checkpoint.py; three write_checkpoint.json packs; tests/unit/test_gen2_write_checkpoint.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Game ownership predicates remain per game; ticket 22 separately extracts only the GB evaluator.

**First red falsifier:** Corrupt an anchor or reduce the predicate to one state byte and require refusal.

**Acceptance:**

- [ ] Derive OWPlayerInput immediately before CheckAPressOW independently for Crystal and Gold/Silver, with caller context.
- [ ] Name script-running/flags, map-event status, joypad disable, battle mode and first-save/New Game ownership constraints.
- [ ] Keep halted-frame alternatives conditional on actual stack/IRQ proof; physical liveness and negative controls remain in 22.

**Evidence:** W-6 and R-4 SOURCE components. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent checkpoint-source review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
