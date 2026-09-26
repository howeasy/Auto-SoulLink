# 19: Bind admission and independent reads

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `lua/gen2/entry.lua`, `lua/gen2/reads.lua`, `tests/unit/test_gen2_{entry,reads}.py` present. The legacy `gen2_crystal` adapter is explicitly retired: `server/adapters/__init__.py:138` `_RETIRED_GAME_IDS["gen2_crystal"] = "the legacy Gen 2 adapter, removed at the P3b.8 cutover"`.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.3, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Start only an admitted cartridge and decode its live/save records faithfully.

**Blocked by:** 18; owner-signed G2/G3a as applicable; 06 admitted catalog and 11 read-only ROM reader.

**Prospective file set:** lua/gen2/entry.lua; lua/gen2/reads.lua; tests/unit/test_gen2_entry.py; tests/unit/test_gen2_reads.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** §5.15d separately claims lua/admission.lua, docs/shared-admission.md and lua/gen1/entry.lua rebind. Shared framework injects catalog/acquisition/anchors/modes; unknown-hash fallback defaults OFF.

**First red falsifier:** Unknown SHA-1 admission or a Lua/PYDEC disagreement on any played fixture must fail.

**Acceptance:**

- [ ] Resolve each admitted hash uniquely to pack/title/kind; refuse the unselected Crystal revision and unsupported/AP/randomized artifacts.
- [ ] Compare party, box, name, held-item and split Special fields against independently derived PYDEC on all eight fixtures.
- [ ] Name every pack path literally; bind independent I/O so production Entry.build is the exercised graph.

**Evidence:** R-1 MODEL differential and C-1 components; C-5 stays disabled/deferred without an enabling ruling. PHYSICAL reads belong to 20. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Non-author admission/reader review; separate Gen 1 rebind lanes from PLAN §5.15d.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
