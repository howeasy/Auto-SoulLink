# 22: Apply writes through proven ownership windows

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.5, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Apply partner effects and PC operations safely while preserving the game's storage ownership.

**Blocked by:** 21 and 10; all eight fixtures qualified; owner-signed G2/G3a as applicable; sole emulator lane.

**Prospective file set:** lua/gen2/writes.lua; lua/gen2/boxes.lua; lua/gen2_write_safety.lua; tests/unit/test_gen2_writes.py; tests/unit/test_gen2_boxes.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Separate §5.15b permit, §5.15c GB checkpoint and §5.15e SRAM-address grants with named Gen 1 consumers/rebind lanes; prospective write_permit.lua, gb_checkpoint.lua and gb_sram_addr.lua are not authorized by this game-file scope.

**First red falsifier:** Unarmed/out-of-bounds writes, pre-first-SAVE writes and memorial backing writes with Box 14 active must refuse with zero writes; a refused ordinary current-box deposit/withdraw is also red.

**Acceptance:**

- [ ] Validate complete payload before first byte; record observed write-site/sink provenance during physical forbidden-state controls and independently decode it. End-state equality alone cannot prove W-1 timing.
- [ ] Prove current-box deposit/withdraw positive controls and source-derived shadow/backing ownership; verify live CartRAM Box 14 offset and memorial survival across SAVE.
- [ ] Qualify textbox/menu/battle/warp/Elm negatives plus idle liveness; reverify ROM anchors each attempt and refuse unavailable bank/stack context.
- [ ] Force faint at battle-loop head; tail retries only for party-full/last-party-mon; whiteout uses shared rebuild ordering. Conditional explode/swap remain disabled absent owner enablement.

**Evidence:** W-1/W-2/W-5/W-6/W-7 and R-4; W-3/W-4 conditional only. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent writes/storage review plus separate shared extraction/rebind reviews.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
