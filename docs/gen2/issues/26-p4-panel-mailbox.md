# 26: Allocate the mailbox and open the native panel

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P4.1, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Open SLINK from the cartridge START menu using a proven persistent mailbox.

**Blocked by:** 25 and owner-signed G3; 07 slack input; historical wayfinder 14 mailbox, 15 trade design and 16 sound-site prerequisites resolved before phase entry.

**Prospective file set:** Exact panel ASM/build files under patch/gen2; tools/build_gen2_companion.py; three UPS outputs; overlay .sym/.map and catalog/pack blocks; server/patcher.py TARGETS; lua/gen2/panel.lua; tests/unit/test_gen2_overlay.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Separate §5.15f gb_panel.lua/contract and Gen 1 panel rebind grant. Mailbox address, ABI/capabilities/state, SE mapping, geometry, charmap and deadlines are required game inputs.

**First red falsifier:** Unpatched cartridge must report ABSENT and refuse painting; missing transient receipt or overlapping mailbox writer must fail.

**Acceptance:**

- [ ] Establish bank/ownership/lifecycle and complete writer exclusion before selecting a mailbox; if unresolved, stop P4 for owner decision without choosing a scratch fallback.
- [ ] Prove saved-region symbol and RAM/SRAM placement equality, clean↔overlay save round trip, deterministic UPS and GBC fade stress.
- [ ] Verify actual START-menu row and panel content with transient receipts; negotiate ABI/version and preserve publish-before-STAGED/timeout ownership.
- [ ] Keep overlay rows unadmitted until 29 closes reopened receipts.

**Evidence:** N-1 and C-3 panel PHYSICAL obligations; first-RC native feature. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Non-author ASM/Lua review and separate Gen 1 panel rebind qualification.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
