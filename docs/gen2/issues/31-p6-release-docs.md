# 31: Publish precise release scope and limits

Status: ready-for-agent

**Current status (2026-09-26): OPEN -- blocked on G4 (ticket 29).** current top-level docs are stale against the Gen 2 rewrite: `README.md:17` still reads 'Gen 2 is partially verified... Gen 2 coverage is Crystal only -- Gold, Silver and Archipelago Crystal have no ROM dump to gate against', and `docs/REFERENCE.md:103` still reads 'Gold, Silver and Archipelago Crystal remain ⚠️ Experimental' -- both describe the pre-rewrite legacy adapter, not the current G1-admitted `gen2_gsc` foundation (AP is REFUSED per O-25, not experimental). `README.md`/`docs/REFERENCE.md` are outside this worker's file grant; flagged separately for the owning worker.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P6.2, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Tell players exactly which artifacts, behavior and exclusions this release qualifies.

**Blocked by:** 30; owner-signed G4.

**Prospective file set:** README.md and docs/REFERENCE.md Gen 2 blocks; docs/historical/release_notes.md; tools/make_release.py later release changes only. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Reuse existing release/package structure; game-specific facts stay in the Gen 2 sections.

**First red falsifier:** Omitting any approved exclusion or recorded limitation must fail the scope comparison.

**Acceptance:**

- [ ] Match the requirements ledger and admitted matrix, including Ball-pocket fixture injection, Time Capsule, mail and unselected Crystal revision.
- [ ] Name post-G6 ghost, AP, non-US/VC, Battle Tower, Mobile Adapter and closed playthrough/deadzone/dupes scope accurately; conditional explode/swap/UPR need explicit dispositions.
- [ ] Keep native panel, sound and trade in first RC; do not promote SOURCE/MODEL checks into physical behavior claims.
- [ ] Preserve literal pack manifest completeness and rollback pointers after release changes.

**Evidence:** Phase obligation G6; documentation reflects verified receipts, not anticipated results. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Owner review and independent scope check.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
