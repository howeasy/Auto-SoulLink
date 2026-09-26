# 18: Create eight saves through scripted play

Status: ready-for-agent

**Current status (2026-09-26): DONE.** all required PLAYED fixtures present under `tests/fixtures/gen2/`: `crystal_town`/`crystal_battle` (+ `_ot2` A/B pair), `gold_town`/`gold_battle`, `silver_town`/`silver_battle`, plus numerous O-33 SYNTH-disclosed fixtures built from them; `tools/gen2_fixtures.py`, `tools/gen2_synth_fixtures.py`, `tests/unit/test_gen2_fixtures.py` present.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.2, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Provide cold-bootable, independently qualified starting saves for every admitted title and two Crystal identities.

**Blocked by:** 17; owner-signed G2/G3a as applicable; coordinator grants the sole emulator lane.

**Prospective file set:** tools/gen2_fixtures.py; exact lua/tests/gen2_scripted_play_*.lua routes; eight tests/fixtures/gen2/*.SaveRAM outputs; exact tests/fixtures/gen2/receipts paths; tests/unit/test_gen2_fixtures.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** §5.15j binds run_gb_gate; separately claim only the bounded input-step runner/timeout/evidence extraction and Gen 1 consumers. §5.15g qualification orchestration is shared; Elm state oracle remains Gen 2.

**First red falsifier:** A fixture that fails checksum, CONTINUE, re-save or reload must fail qualification.

**Acceptance:**

- [ ] Play New Game, naming, Mom, Elm and starter; save town inside the lab and battle on Route 29 for Crystal/Gold/Silver plus Crystal town/battle _ot2.
- [ ] Use distinct played OTs for Crystal A/B; assert same-OT/different-full-key and identical-full-key policies separately downstream.
- [ ] Inject only owner-authorized Ball-pocket Poké Balls; starter/walk remain played. Assert the bag before captures; no errand or other game-data staging.
- [ ] Qualify all eight by PYDEC plus GAME through cold boot → CONTINUE → re-save → reload; pin CGB mode and per-title SaveRAM names. Route work requests 300%; explicit qualification uses 100%.

**Evidence:** F-6 PHYSICAL and S-7 input; per-lane requalification continues in 24. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Non-author fixture/driver review; coordinator owns scripted emulator execution.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
