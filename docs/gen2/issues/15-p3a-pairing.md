# 15: Admit every authorized Gen 2 title pairing

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3a.1, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Allow any Gold/Silver/Crystal title pair while preserving run compatibility and refusal integrity.

**Blocked by:** 09–14 complete under G2; owner-signed G2; adopted shared cut and drift watch verified.

**Prospective file set:** server/adapters/__init__.py foundation rows; tests/unit/test_gen2_pairing_matrix.py; base.py/server.py only under a separate justified exact claim if adopted hooks are insufficient. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Generic pairing machinery stays shared; title and artifact-kind compatibility are adapter facts.

**First red falsifier:** Admit Gen 2 with Gen 1/3, miss a title-case alias, or mutate state/cache/disk on a rejected hello: each control must fail.

**Acceptance:**

- [ ] Map Crystal/crystal, Gold/gold and Silver/silver to one gen2_gsc foundation; cover all title pairs and arrival orders.
- [ ] Enumerate each supported clean/overlay artifact-kind combination against the adopted generic contract; unknown, AP and randomized artifacts remain refused.
- [ ] Cover reconnect, persisted runs and contradictory hello without introducing game_id branches; Gen 3 then Gen 1 regressions pass.

**Evidence:** C-6g SOURCE/MODEL components; physical pairings belong to 24. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Non-author review plus slink-adapter-guard; owner signs G3a.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
