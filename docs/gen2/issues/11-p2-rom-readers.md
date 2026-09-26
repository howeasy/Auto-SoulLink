# 11: Compare independent ROM readers

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `server/adapters/gen2_rom_scan.py`, `lua/gen2/rom.lua`, `tools/verify_gen2_rom_layout.py` and `tests/unit/test_gen2_rom_tables.py` all present (independent Lua/Python two-path reader comparison).

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P2.4, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Produce consistent game data from independent Lua and Python interpretations of each admitted ROM.

**Blocked by:** 08; owner-signed G1.

**Prospective file set:** server/adapters/gen2_rom_scan.py; read-only lua/gen2/rom.lua; tools/verify_gen2_rom_layout.py; tests/unit/test_gen2_rom_tables.py. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Per-game layouts and table addresses; reuse only generation-neutral bounded mechanics with explicit inputs.

**First red falsifier:** Deliberately change one decoded byte in either reader and require the equality check to fail.

**Acceptance:**

- [ ] Compare every title and time-of-day table for wild, headbutt, rock-smash, fishing and roaming encounters plus base stats.
- [ ] Validate range/bank bounds and malformed-table refusal; the Lua reader writes nothing.
- [ ] Keep independent decoding paths; agreement obtained by calling the same production parser is not an oracle.

**Evidence:** F-4 SOURCE-only obligation; MODEL differential checks do not establish physical behavior. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent reader/layout review; slink-adapter-guard for server changes.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
