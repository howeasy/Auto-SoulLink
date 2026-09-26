# 23: Connect the Gen 2 production client

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `lua/gen2/client.lua`, `lua/gen2/run.lua`, `server/adapters/gen2_gsc.py`, `tests/unit/test_gen2_{client,adapter}.py` present; `server/manager.py:73` already carries the `("gen2", "Gold · Silver · Crystal", ["gold", "silver", "crystal"])` family row.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.6, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Run the Soul Link lifecycle on the production graph with Gen 2 facts and shared behavior.

**Blocked by:** 22, 15 and 16; owner-signed G2/G3a as applicable.

**Prospective file set:** lua/gen2/client.lua; lua/gen2/run.lua; lua/slink.lua Gen 2 route; server/adapters/gen2_gsc.py; registry re-point; Manager GAMES rows; tests/unit/test_gen2_{client,adapter}.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Consume prior shared mechanisms. Generic reconnect/hello scheduling, queues, validation/dispatch and presentation lifecycle stay shared; any additional extraction needs a separate exact claim, explicit inputs, Gen 1 rebind/lanes and non-author review. Per-game client naming does not authorize copying lifecycle.

**First red falsifier:** Premature hello, unarmed write, fixture decode mismatch or identical-full-key collision accepted on production Entry.build must fail.

**Acceptance:**

- [ ] Require live-save identity plus checkpoint-or-running-battle for hello; pause safely across title/reset; exercise same-save, wrong-save, WRAM-clear and fault sequences.
- [ ] Run protocol §9 conformance on production Entry.build with stage/PP-Up/OT/blob/key-change controls; ambiguous keys write nothing on either lookup path.
- [ ] Bind shared server rule handling unchanged; adapters own DV gender/shiny and game facts; sanitize every displayed string.
- [ ] Route lua/slink.lua directly to lua/gen2/run.lua; no replacement shim. Record explicit GAME HUD measurement or the permitted D-12 limit.

**Evidence:** R-4; C-0/C-4/D-13 MODEL-only; C-2 MODEL; C-3 HUD; D-12. Physical reconnect remains 24. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Non-author frozen-client adversarial review; required limited-context second reviewer; slink-adapter-guard.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
