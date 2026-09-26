# 27: Play native sound within qualified deadlines

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P4.2, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Play each native sound request reliably in every qualified game context.

**Blocked by:** 26; historical wayfinder sound design 16 resolved; owner-signed G3; shared panel-file ownership handed off.

**Prospective file set:** Exact sound ASM under patch/gen2/src; SE table/request_sfx blocks in lua/gen2/panel.lua; sound rows in tests/live/test_gen2_trade_gates.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Bind existing lua/sfx_arbiter.lua with Gen 2 SE facts; panel owns request queue, no new sound.lua wrapper.

**First red falsifier:** A request exceeding its defined service deadline in any qualified context must fail.

**Acceptance:**

- [ ] Qualify movement, idle START menu, text, battle and transitions separately with main-thread caller/context ABI.
- [ ] Preserve banks/registers; test busy channels, request consumption, reset/cancel and bounded service.
- [ ] IRQ may signal only unless separately proven safe for game-code execution; GetJoypad and DelayFrame source reachability alone do not prove universal coverage.
- [ ] Record transient sound-service evidence against the patched artifact and reopen affected receipts through 29.

**Evidence:** N-2 PHYSICAL; first-RC native feature. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent non-author sound/reentrancy review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
