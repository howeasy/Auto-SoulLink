# 24: Qualify rules with independent duo oracles

Status: ready-for-agent

**Current status (2026-09-26): DONE (PHYSICAL).** `tools/e2e_duo.py` Gen 2 rows + `tools/gen2_duo_oracles.py`, `tests/e2e/test_duo_gen2_new.py`, `tests/gen2_release_requirements.json` (66 `gen2_trade*`/scenario registrations across C-C/G-S/C-G) all present. `tools/verify_gen2_release.py --lane duo-pairs` and `--lane duo-link` both PASS (run 2026-09-26); 98/98 sweep cells pinned at code digest `e8ca0067`, tag `gen2-rc-evidence-2026-09-25`.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3b.7, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Demonstrate that real cartridge actions produce correct linked behavior and durable saves.

**Blocked by:** 23; 20–22 physical prerequisites closed; 13 coverage map and 14 runner; owner-signed G2/G3a as applicable; sole emulator lane.

**Prospective file set:** tools/e2e_duo.py Gen 2 rows/oracles; tools/run_gb_gate.py rows; tests/e2e/test_duo_gen2_new.py; tests/live/test_gen2_new_gates.py; runner lanes; tests/gen2_release_requirements.json; requirements evidence cells. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Separate §5.15i descriptor-driven duo pipeline and §5.15e witness transport grants/rebinds; required stages apply to every migrated family. Game save kind, success site, checksum/recovery and delta oracle remain injected per game.

**First red falsifier:** Missing post-result oracle/witness, stale attempt bytes or a client RESULT-derived verdict must fail.

**Acceptance:**

- [ ] Run C↔C and G↔S plus C↔G link with per-instance SaveRAM paths; requalify fixtures each lane.
- [ ] Cover link, ball_gate, boxed_capture, linked_faint_bench/active, poison, whiteout, pc_ops/release, changebox, species/gender/type clauses, shiny_bonus, reconnect same/wrong-save/WRAM-clear, soft_reset, evolution, npc_trade, gift, egg_hatch and admit_wrong_rom.
- [ ] Prove roamer non-consumption/non-locking, contest-specific link and hatch gift namespace; require scenario deltas and untouched-region preservation.
- [ ] Bind save witnesses to attempt/artifact/frame/exact bytes at success-only boundaries; cold-boot bad-primary/good-backup, inverse and both-bad controls must behave correctly.
- [ ] Collect permitted HUD transient evidence or explicit limits; conditional D-11 remains inapplicable absent enablement.

**Evidence:** C-2/C-6g; D-1/D-2/D-3/D-5/D-6/D-7/D-12/D-14; acquisition behavior S-2/3/5/6/7/8/9g/10g; W-5/W-7; F-6. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent non-author oracle/receipt review; shared Gen 1/pureRGB regression evidence retained.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
