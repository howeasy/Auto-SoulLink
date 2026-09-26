# 29: Requalify and admit the overlay artifacts

Status: ready-for-agent

**Current status (2026-09-26): OPEN -- the actual current G4 blocker.** `tools/verify_gen2_release.py --lane release-evidence` (run 2026-09-26) reports exactly 4 gaps: the `crystal_overlay`/`gold_overlay`/`silver_overlay` admitted-artifact rows are `status='BUILT'`, not `ADMITTED` at their published hashes, and `docs/gen2/PLAN.md` §6.1's G4 ledger row carries no owner signature. The promotion tool exists (`tools/gen_gen2_admission.py --promote-overlays`, gated on a signed G4 row) but has not been run. Every other input this ticket depends on (26-28) is green.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P4.4, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Admit each patched cartridge only after its own behavior and persistence evidence is complete.

**Blocked by:** 26, 27 and 28 complete; owner-signed G3; sole emulator lane for reopened qualification.

**Prospective file set:** Overlay rows of the admitted-artifact matrix; coordinator alone updates PLAN §6.1 G4 and guide/register evidence. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Reuse generic runner/coverage validation; per-artifact facts and equivalence decisions remain explicit.

**First red falsifier:** Promoting an overlay to ADMITTED with any reopened obligation still open must fail.

**Acceptance:**

- [ ] Reopen build, admission, sites, checkpoint and natural-rules obligations on each patched artifact.
- [ ] Share a clean receipt only with proven byte/offset and reachability-context equivalence; otherwise rerun against the overlay.
- [ ] Record real hashes only on properly qualified matrix states; owner plays panel, native sound and trade before signing G4.
- [ ] G4 is the first RC-eligible gate; ghost remains post-G6 and does not block this sign-off.

**Evidence:** Phase G4 reclosure, including F-2/F-3/W-6/C-1 and all affected physical receipts. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Frozen-source non-author evaluator; owner signs G4.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
