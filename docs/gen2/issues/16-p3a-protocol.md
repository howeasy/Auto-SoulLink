# 16: Specify Gen 2 wire conformance

Status: ready-for-agent

**Current status (2026-09-26): DONE.** `tests/unit/protocol_schema.py` carries `"gen2_gsc"` in `HELLO_DECLARES`/foundation checks and validates `foundation`/`artifact_kind` against `foundation_for_rom_type()` (`protocol_schema.py:94-248`); `tests/unit/test_protocol_schema.py` present.

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P3a.2, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Send a precise Gen 2 wire representation that shared consumers can interpret.

**Blocked by:** 15; owner-signed G2; shared-file handoff recorded.

**Prospective file set:** tests/unit/test_protocol_schema.py; tests/unit/protocol_schema.py; docs/protocol.md Gen 2 additions. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Extend the shared contract only where needed; wire schema is shared and game encodings are adapter inputs.

**First red falsifier:** A Gen 2 hello missing foundation or artifact_kind must fail the schema.

**Acceptance:**

- [ ] Answer every protocol Gen 3 assumption explicitly, including held items, sound IDs, stats/stages, PP-Ups, OT, blobs and evolution publication.
- [ ] Use production-graph conformance expectations and preserve unchanged Gen 1/Gen 3 behavior.
- [ ] Record any actual protocol change for independent review; existing source descriptions alone are not protocol authority.

**Evidence:** C-0 schema MODEL component; downstream live mappings remain required by 13. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent protocol reviewer; slink-adapter-guard if server code becomes necessary under a separate grant.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
