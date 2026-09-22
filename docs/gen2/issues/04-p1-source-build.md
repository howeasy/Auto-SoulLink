# 04: Build and lock the four source ROMs

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P1.1, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Make every Gen 2 generated fact traceable to an exact reproducible source build.

**Blocked by:** 03 and owner-signed G0.

**Prospective file set:** data/gen2_sources.lock.json; tools/build_gen2_syms.py; data/gen2/{pokecrystal,pokecrystal11,pokegold,pokesilver}.{sym,map}; tests/unit/test_gen2_build.py; tools/build_pret_syms.py pin-check block only. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Game facts remain per game; reuse identical build helpers only under a separate exact shared claim.

**First red falsifier:** Change the source SHA, assembler pin or committed symbol hash and require the build/lock check to fail.

**Acceptance:**

- [ ] Build both Crystal revisions, Gold and Silver from the owner-pinned pret commits with a pinned RGBDS version; all four ROM SHA-1 values match their pinned roms.sha1.
- [ ] Lock source, toolchain, ROM, .sym and .map hashes and retain reproducible commands.
- [ ] Reject unpinned builds and assert Gen 2 generators cannot consume data/pret_syms.json.

**Evidence:** F-1 SOURCE component and Pins; build success does not admit every artifact. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent OMP lock-versus-output audit.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
