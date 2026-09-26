# 28: Trade through the cartridge receptionist

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P4.3, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Complete or decline a native trade with correct records, held items and durable saves on both halves.

**Blocked by:** 26; historical wayfinder native-trade design 15 resolved; owner-signed G3; panel/client/test file handoffs recorded.

**Prospective file set:** Exact trade ASM; lua/gen2/trade_overlay.lua; client trade-phase blocks; test_gen2_client trade cases; tests/live/test_gen2_trade_gates.py; test_gen2_overlay trade rows. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Bind the shared trade lifecycle through native_trade_ui; Gen 2 owns receptionist ABI and game commit facts. Reusable lifecycle additions need their own exact shared claim.

**First red falsifier:** A stale token completing trade or an invalid held item committed must fail.

**Acceptance:**

- [ ] Cover every Center receptionist entry, waiting, payload/patch/mail exchange, YES/NO, both animations, sync and acknowledgment; no one-byte connection bypass.
- [ ] Validate/carry/read back held items and trade evolution on both halves; decline leaves both saves unchanged; cover success/decline/timeout/reset C↔C and G↔S duos.
- [ ] Witness SaveAfterLinkTrade plus the following full scenario save; reload the exact traded record and item, not a same-species substitute.
- [ ] Time Capsule and mail remain explicit limits; clean/overlay kind combinations follow ticket 15's matrix.

**Evidence:** T-1/T-2/T-3/T-4 PHYSICAL; first-RC native feature. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent non-author ASM/Lua and persistence-oracle review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
