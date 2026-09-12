# P1: restore the Gen 3 native trade staging gate

Status: patch ready, applies cleanly (`git apply --check`), patched file compiles under lupa.
Owner: root accepts by `git apply docs/gen1_reference/proposals/P1-gen3-trade-gate.patch`.

## Defect

`lua/clients/gen3_frlge_client.lua:2221-2241`. Since commit `134f007` the trade staging step
(`relocate_trade_slot` + `MB.set_enemy_party({ p.blob })` -> phase `stage`) sits inside the
`if not patch_present() then` branch, after `pending_trade_apply = nil`. On a patched ROM,
the only ROM the flow can start on, phase `pending` therefore never stages; it waits 1,800
frames and takes `fallback("field never cleared")`, a silent `OP_SET_PARTY_MON` swap with no
trade animation. On an unpatched ROM the branch aborts and then still calls
`MB.set_enemy_party` into EWRAM nobody reads.

The pre-regression source (`git show 134f007^:lua/clients/gen3_frlge_client.lua`, lines
2149-2157) had the staging under
`elseif memory.read_u8(0x03000F9C) == 0 and not pending_ui then` (field clear: no script
context, no native box in flight).

## Change

One inserted line: the `elseif memory.read_u8(0x03000F9C) == 0 and not pending_ui then`
branch head between `pending_trade_apply = nil` and `relocate_trade_slot(p)`. The staging
lines and the 1,800-frame timeout branch are unchanged and now sit in the correct branches.
`pending_ui` is the existing native-box-in-flight table (`:534`); `0x03000F9C` is
`sScriptContext2Enabled`, the same address the message path uses (`:128-135`).

## Verification (root checkout, has the ROM and states)

```bash
SLINK_LIVE=1 pytest tests/live/test_lua_gates.py -q -k tradescene
SLINK_E2E=1 pytest tests/e2e/test_duo.py -q -k trade
```

Expect the client log to reach `trade: staging partner mon -> gEnemyParty[0]` and then
`running native trade scene` (phase `scene`), not `silent swap fallback`. The duo `trade`
scenario should complete in well under 1,800 frames after `apply_trade` arrives.

## Risk

None beyond restoring behaviour that shipped before `134f007`. The unpatched branch keeps its
abort. No server change.
