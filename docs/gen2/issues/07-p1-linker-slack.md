# 07: Report mailbox allocation candidates

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `data/gen2/linker_slack.json` is present (per-title mapped/free WRAM intervals from the built `.map` files).

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P1.4, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Expose whether a persistent native-feature mailbox can be allocated safely.

**Blocked by:** 04; owner-signed G0.

**Prospective file set:** tools/build_gen2_syms.py report output; exact report path must be claimed; coordinator records the G1 receipt. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Per-title RAM layout facts; no copied Gen 1 mailbox address or scratch-memory fallback.

**First red falsifier:** Reject any proposed free span overlapping a linker symbol or known writer.

**Acceptance:**

- [ ] Report mapped/free intervals from each built .map with bank and address provenance.
- [ ] Distinguish slack candidates from proven persistent ownership; do not select the mailbox here.
- [ ] Feed wayfinder research 14 and ticket 26; complete writer exclusion and lifecycle remain required before native implementation.

**Evidence:** Phase obligation G1; SOURCE feasibility input for N-1/N-2. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent Codex review.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
