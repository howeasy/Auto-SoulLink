# 17: Build the independent byte and stat oracle

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `server/adapters/gen2_codec.py` and `tests/unit/test_gen2_codec.py` present (independent stat/decode oracle).

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.1, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Independently decode and qualify every supported Gen 2 save and stat result.

**Blocked by:** 13–16 and owner-signed G2; G3a where shared changes apply. Historical wayfinder research 10/13/20/22 must have their required source answers, distinct from these implementation numbers.

**Prospective file set:** server/adapters/gen2_codec.py; tests/unit/test_gen2_codec.py. Shared extraction files require a separate exact grant. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** §5.15g shares bounded charmap scanning/qualification orchestration only; prospective server/gb_charmap.py and lua/gb_charmap_scan.lua need exact contracts, Gen 1 consumers, rebind receipts and non-author review. PYDEC derivation stays independent.

**First red falsifier:** Source-derived non-HP vectors base=50,dv=15,exp=0,level=100 =>135 and base=50,dv=0,exp=10,level=100 =>106 must reject stale 120/105 formulas; deliberately wrong Sp.Def must also fail.

**Acceptance:**

- [ ] Rederive CalcMonStats from pinned pret and the coordinator's stat_derivation.report.md: 2*(base+dv), ceil sqrt(stat-exp) capped at 255 then integer division by 4, scaling floor, HP/non-HP constants and final cap 999. Treat research pseudocode as a hypothesis.
- [ ] Decode 48-byte party, 32-byte box, names and 14×20 boxes; cover both save layouts and all five Gold/Silver backup spans.
- [ ] Separate GAME-style recovery from strict success-witness validation; independent positive/negative controls preserve integer order, rounding, Special sharing and boundaries.

**Evidence:** R-1 MODEL component; R-2 CONTROL with its declared PHYSICAL obligation still required; F-6 qualifier component. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Non-author codec/stat derivation review; slink-adapter-guard and Gen 1 rebind review for separate shared changes.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
