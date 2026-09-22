# 08: Generate profile and static facts for all titles

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P2.1, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Read the correct title-specific addresses and species facts from reproducible packs.

**Blocked by:** 05, 06, 07 and owner-signed G1.

**Prospective file set:** tools/gen_gen2_{profile,species,evos,items,charmap,map_names}.py; exact output JSONs under data/games/gen2_{crystal,gold,silver}/; tests/unit/test_gen2_{profile,species,evos}.py; tools/verify_profile_addresses.py Gen 2 rows only. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Cartridge facts stay per game; identical helpers require a separate shared claim and unchanged Gen 1 packs.

**First red falsifier:** Move one address in the lock and require generation --check to fail.

**Acceptance:**

- [ ] Every generated address names the pinned pret symbol; Gold/Silver WRAM equality and Crystal differences are derived, not copied.
- [ ] Read the complete species list through NUM_POKEMON; exclude the later EGG sentinel from dex indices; generate evolution families and item IDs from source.
- [ ] Regeneration is deterministic; unpinned legacy symbol JSON is rejected.

**Evidence:** F-1 and F-5 SOURCE-only obligations; MODEL checks carry no PHYSICAL claim. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent OMP address audit.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
