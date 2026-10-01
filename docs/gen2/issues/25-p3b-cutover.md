# 25: Package the rewrite and retire legacy files

Status: ready-for-agent

**Current status (2026-09-26): DONE.** legacy Gen 2 adapter/client retired (`server/adapters/__init__.py:138`, see ticket 19); `tools/make_release.py` manifest rows and `tests/unit/test_make_release_manifest.py` present.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.8, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Boot the new client from the actual distribution and preserve a usable rollback before cutover.

**Blocked by:** 24; independent frozen-client review; owner-signed G2/G3a as applicable.

**Prospective file set:** tools/make_release.py manifest rows; tests/unit/test_make_release_manifest.py; exact extracted-bundle test path; PLAN §4 REMOVE/REPLACE inventory expanded into exact dispatch paths. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Reuse packaging machinery; per-game manifest facts remain literal rows.

**First red falsifier:** Missing pack, failed extracted boot or a missing/wrong-hash REPLACE path must fail.

**Acceptance:**

- [ ] Build packaging before reference/import/launcher/test census; freeze previous runnable bundle and untouched per-attempt saves.
- [ ] Execute current PLAN §4's complete inventory, including legacy shim and all 15 legacy Lua probes/tests; regenerate REPLACE paths and preserve expected hashes.
- [ ] After deletion, rerun extracted-bundle boot for admitted titles/pairings, eight-fixture qualification, unit suite and quick runner.
- [ ] Submit owner-played Crystal duo and complete cutover receipt for G3; G3 is an internal milestone, never RC permission.

**Evidence:** Phase obligation G3 protecting every earlier receipt; rollback restores artifacts and saves. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent cutover review; owner signs G3.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
