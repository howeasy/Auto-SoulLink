# 20: Qualify reads on running cartridges

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.3a, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Show that reported records and displayed game facts match on the actual admitted cartridges.

**Blocked by:** 19; all eight 18 fixtures qualified; owner-signed G2/G3a as applicable; sole emulator lane and exact receipt-transport dependency granted.

**Prospective file set:** tests/live/test_gen2_new_gates.py inspect rows; tests/unit/test_gen2_reads.py dump replays; exact fixture receipt paths. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Consume shared scanning and receipt transport. If §5.15e transport is not ready, obtain its separate exact extraction/rebind grant before this gate; do not wait for ticket 24's later duo completion.

**First red falsifier:** A different-frame/domain dump or missing title-specific dump accepted as equal must fail.

**Acceptance:**

- [ ] Capture same-frame raw WRAM/SRAM bytes on all eight running fixtures; record frame/domain/ranges and compare Lua against independent PYDEC from those exact bytes.
- [ ] Check trainer class/id, Johto+Kanto badges, held items and box index against the game's displays.
- [ ] Check both gender/shiny outcomes against status symbols and palette/animation, with exact fixture/provenance receipts; missing reachable controls remain OPEN.
- [ ] Arrange the frame-alignment probe before ticket 21's first site qualification; checkpoint liveness belongs to 22.

**Evidence:** R-1 PHYSICAL, R-3 and R-5g; fixture-only equality cannot close these rows. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Non-author review of raw dumps, controls and receipts.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
