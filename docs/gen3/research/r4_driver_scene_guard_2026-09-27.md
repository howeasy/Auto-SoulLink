# R4-DRIVER capture budget and shared scene guard

The failed [20-ball attempt](../probes/fc_link_gen3_rand_r4_2bd0ee22.txt) saved FireRed with
11 balls after eight logged throws. Its capture loop stopped at eight, then entered an
A-pressing scene helper while battle could still be active. The source/control replay proves
that fall-through; attribution of the physical ninth ball to it is an inference, since that
input was not logged.

`ctx.catch` now allows at most **20 instrumented throws**. Every throw still uses the existing
bag-input witnesses, throw helper, `THREW N` marker and battle-turn wait. Reaching the budget
with battle active and an empty pocket (the 20th throw was the last ball) returns the bare
`out-of-balls`, the same RNG-classified reason as the mid-hunt exhaustion path (R4-DRIVER-2,
OMP cx-d84db30c review of d998cc65: `tools/e2e_duo.py classify_gen1_result` only retries
`"hunt ended out-of-balls"`; the old unconditional `capture throw budget exhausted (20)` at
20/20 balls was FINAL and un-retryable). Reaching the budget with balls remaining still
returns `capture throw budget exhausted (20)`; neither path falls into scene advancement. A
completed catch also propagates a scene-settle refusal. The saved-ball oracle is unchanged.

`playlib.P.wait_scene_settled` now requires battle to be known inactive before evaluating the
scene and again before an input or success decision. Active or unreadable state returns a
named refusal (logged via `H.phase("scene-wait-refused", why)`, so a refusal is visible in
receipts even at the ~9 call sites that discard the boolean return). This protects **every
caller**, including a battle that begins during a wait or a predicate evaluation. It does not
press buttons or advance a frame on that refusal. The second, pre-decision recheck is a
forward-compat property of the contract -- `in_battle` may read `nil` (unreadable) per its
own signature -- not a response to any Gen 3 state this review observed changing between the
two calls: every production binding's `in_battle` is `not pred_ok(cp, ...)`, a pure memory
read that cannot itself flip mid-iteration.

## Registered duo rows with changed paths

The following inventory is for the current `tools/e2e_duo.py` registry. FR/LG includes its
`gen3_lgfr` orientation. These are source reachability/rerun candidates, not new live receipts.
Only `link_gen3_rand` is authorized for the R4-DRIVER physical run.

| Rows | Titles | Changed path |
|---|---|---|
| `link_gen3_rand` | FR/LG | Capture budget and post-capture scene guard. |
| `link_gen3`, `deadzone_gen3` | FR/LG, RR, Emerald | Same `ctx.catch`; dead-zone A also uses `ctx.run_away` → scene wait. |
| `trainer_bench_gen3` | FR/LG | `scenario_gen3_battle_window.lua` post-battle wait; trainer preparation through `gen3_routes.lua`. |
| `active_end_gen3`, `linked_faint_active_trainer_gen3` | FR/LG | Shared linked-active module: post-battle wait, retreat/fight policy, trainer preparation. |
| `linked_faint_active_gen3` | FR/LG, RR, Emerald | Shared linked-active module: post-battle wait and `ctx.lose_active` win/re-hunt path. |
| `linked_faint_active_whiteout_gen3` | FR/LG, RR | Shared linked-active module plus its PC/grass walks and recovery path. |
| `linked_faint_active_clean_gen3`, `linked_faint_active_lhammer_gen3`, `linked_faint_active_mega_gen3`, `explode_gen3` | RR | Variants of the same linked-active module. The mega row remains subject to its existing signed limit. |
| `whiteout_gen3` | FR/LG, RR, Emerald | `ctx.lose_active`, post-whiteout scene wait, PC/grass walks. |
| `rival_swap_gen3` | RR | `ctx.run_away` after the negative-control battle. |
| `boxsync_gen3` | FR/LG, RR, Emerald | Conditional incidental-battle policy during `ctx.walk_to_pc`; it uses the shared scene wait after the fight. |
| `center_controls_gen3` | FR/LG | Same conditional walk/incident-battle path. |

The other registered Gen 3 duo bodies (`admit_randomized_frlg`, `trainer_panel_gen3_rand`,
`faint_cmd_gen3`, `faint_cmd_clean_gen3`, `save_then_write_gen3`, `evolve_gen3`,
`npc_trade_gen3`, `poison_faint_gen3`, `reconnect_gen3`, `rival_swap_real_gen3`,
`native_absent_gen3`, `trade_gen3`, `trade_decline_gen3`, `infopanel_gen3`,
`infopanel_dex_gen3`) have no call to the changed capture/scene paths in their current bodies.
Their common boot and save helpers do not call `wait_scene_settled`. No Gen 1/2 production
client imports playlib; this remains a harness change.

## Other shared callers checked

- `duo_gen3_main.lua`: `ctx.run_away` waits only after its turn waiter says over; the
  `ctx.lose_active` re-hunt branch is reached after a won battle leaves the action menu.
- `gen3_scripted_play.lua`: incidental-battle policy explicitly checks battle ended before
  scene settling; `resolve_battle_and_check_whiteout` waits for inactive battle first.
  Nurse healing, rival-battle aftermath, parcel fetch/delivery, `route1_faint`, Emerald grass
  return, Route 102 catch/faint, whiteout and evolution all use the newly guarded helper.
  These cover standalone scripted-play legs and their fixture/probe callers as well as duos.
- `gen3_routes.lua`: trainer preparation asserts battle ended before its scene wait.
  This also covers the `trainer_fixture` module used by fixture preparation.
- `gen3_fixture_from_state.lua`: nurse-heal scene wait; relevant to `make-fr-party` fixtures.
- `gen3_rr_battle_fixture.lua`: escape checks inactive battle first; Mart parcel and Oak
  delivery waits are scripted-field scenes.
- `gen3_rr_scripted_play.lua`: incidental-battle policy first waits for inactive battle.
- `gen3_fr_newgame_inputs.lua`: binds playlib for walking/warps but has no scene-wait call.

Some legacy callers ignore the scene helper's boolean result. The central guard still blocks
their scene inputs; changing their higher-level failure handling is outside this card. A
caller that reaches the helper during a still-active battle now receives a refusal, not an
implicit battle policy. The coordinator should choose additional live reruns from this list.

## Unit evidence

`tests/unit/test_gen3_capture_driver_budget.py` commits the earlier lupa replay and checks the
ninth counted throw, catches at throws 1/8/20, named budget exhaustion with balls remaining,
and propagated scene refusal. `tests/unit/test_playlib.py` checks active/unreadable battle,
false quiet indications, a predicate starting battle, and battle beginning during a quiet
frame. The ordinary field-scene, debounce and budget tests remain in place.
