# 06: Freeze the admitted-artifact matrix

Status: ready-for-agent

**Readiness:** specification-ready only; execution is unclaimed and requires the stated gate plus a coordinator-recorded exact file grant and ACK. This ticket grants no permission to sign a gate.

**Binding substep:** P1.3, [binding plan §5](../GEN2_BINDING_PLAN.md#5-binding-steps-in-order). Read [spec](../spec.md), [PLAN](../PLAN.md) and [requirements](../gen2_requirements.md) for the authoritative contract.

**Source:** planning cut `9c7e7ac`; pin the actual implementation cut from ticket 01's receipt before execution.

**What to build:** Accept only explicitly admitted cartridges and retain distinct future overlay slots.

**Blocked by:** 04; local Crystal dump actually hashed; owner-signed G0.

**Prospective file set:** data/games/gen2_{crystal,gold,silver}/admission.json matrix rows only; coordinate later pack owners. These are planning bounds, not an active lease; expand patterns and identify blocks before dispatch. Workers report ledger changes to the coordinator.

**Shared-module decision:** Per-game catalog feeds shared admission; framework extraction occurs at ticket 19.

**First red falsifier:** A BUILT/ADMITTED row without an exact hash, or a PLANNED row carrying a hash, fails validation.

**Acceptance:**

- [ ] Build all four ROMs but admit Gold, Silver and only the locally selected Crystal revision at G1.
- [ ] Refuse the other Crystal revision, unknown/AP/randomized artifacts unless separately authorized and qualified.
- [ ] Keep overlay and ghost slots PLANNED without hashes; enumerate artifact-kind compatibility separately from the authorized title pairings.

**Evidence:** F-7g and C-1 SOURCE components; Pins; no PHYSICAL admission claim. Record SOURCE, MODEL and PHYSICAL separately; legacy Gen 2 code/fixtures and a client RESULT line establish none of the required independent physical proof.

**Independent review:** Independent catalog audit and owner G1 signature.

**Exit receipt and next action:** report frozen source/artifact hashes, exact changed paths, falsifier and positive-control results, commands/receipt paths, remaining limits and review outcome. The coordinator reconciles the receipt and chooses the next authorized frontier; completion never signs a gate.
