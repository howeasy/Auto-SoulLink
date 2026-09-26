# 35: Qualify the ghost overlay in live play

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P5.3, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Show accurate partner movement while preserving game and save behavior across the complete lifecycle.

**Blocked by:** 34; G6 shipped; 33 design signature; sole emulator lane.

**Prospective file set:** tests/live/test_gen2_ghost_gates.py; ghost matrix rows; exact transient and reopened receipt outputs. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Bind existing gate, witness and coverage orchestration; title-specific ghost oracle remains independent.

**First red falsifier:** A displayed ghost frame without its transient receipt, or a save/reload ghost leak, must fail.

**Acceptance:**

- [ ] Run both representative pairings with position 1:1, correct sprite/palette and battle suspension plus transition/disconnect/reset controls.
- [ ] Prove save exclusion and restoration through save/CONTINUE/reload, including interruption and original-object preservation.
- [ ] Reopen and rerun ticket 29's affected artifact obligations on the ghost overlay; promote only after all required receipts close.
- [ ] Owner sees partner movement and signs post-release G5; preserve the shipped first-RC artifact's independent history.

**Evidence:** N-3 PHYSICAL and affected ghost-overlay reclosure; G5 follows G6. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent non-author receipt review and owner G5 signature.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
