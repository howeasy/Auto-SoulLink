# P13: the remaining rule call sites decide through the shared engine

Status: one patch plus one new module. Applies cleanly to the sweep worktree on its own and
in sequence after P1, P7, P8 and P9 (checked by applying all five in order in a scratch git
repository). Verified in the scratch copy of the worktree: starter settlement, wild encounter,
no-catch retirement flow, retirement runtime, evolution, NPC exchange, memorial runtime and
memorial interleaving suites all green (185 tests plus the 34 faint and 155 acquisition tests
of P8 and P9); ruff clean. Together with P8 and P9 this completes handoff item 2 for every
rule decision the RC makes.

## New module: `server/gen1_engine_bridge.py`

Four functions, one per remaining decision, each feeding `SoulLinkState.handle_event` the
event Gen 3 already sends and adapting the outcome to the record the runtime keeps:

| Function | Replaces | Engine handler |
| --- | --- | --- |
| `starter_grant(rules, player, area, info)` | `party_grant_rules.record_exempt_party_grant` | `_handle_capture` with `gift=True` in `oaks_lab` |
| `no_catch(rules, player, area, species, level, *, activated, proved_peers, decision)` | `no_catch_rules.record` | `_handle_no_catch` |
| `rekey(rules, player, outgoing, mon, *, reason)` | `member_identity_rules.rekey` | `_handle_key_change` |
| `memorial_completion(rules, player, key)` | `linked_death_rules.record_memorial_completion` | `_handle_memorialize_done` |

The bridge keeps the three RBY policies P8 and P9 established: usability comes only from the
proved physical disposition (callers own `party_keys`), ball activation only from the
`bag_received` signal (the flag is restored), and physical effects are executed by the held
executors from the rules state, so the commands the engine queues are drained with the reason
in the code. `no_catch` keeps naming the outcome through `no_catch_rules.decision`, a pure
function, so the encounter record keeps its vocabulary while the state change is the engine's.

## Patched call sites (`P13-fold-back-call-sites.patch`)

| File | Change |
| --- | --- |
| `server/gen1_starter_settlement.py:12,126` | import and one call: `starter_grant(...)` |
| `server/gen1_wild_encounter_runtime.py:12,340-350` | `gen1_engine_bridge.no_catch(..., decision=no_catch_rules.decision)`; the dead-zone timestamp is the engine's |
| `server/gen1_evolution_runtime.py:18,210-220` | `rekey(..., reason="evolution")` |
| `server/gen1_npc_exchange_runtime.py:37,188` | `rekey(..., reason="npc_trade")` |
| `server/gen1_memorial_runtime.py:13` | `memorial_completion` under the old name |
| `server/adapters/gen1_rby.py` | Eevee joins the fixed-species gifts (moved here from P9); the starter policy below |

## Two behaviours the engine surfaced, and what was decided for now

1. **Starters and the clauses.** Gen 3 applies the clauses to starters: `intro` is not in its
   fixed-species set (`server/adapters/gen3_frlge.py:48-52`), so two identical starters under
   species lock are a violation there. The RC exempted every scripted grant, and its starter
   tests force all three locks on and expect a link for every pairing, including Red/Red with
   two Bulbasaur. A violation at minute one has no retry, and Yellow has no choice at all. The
   patch keeps starters exempt as an explicit adapter policy (`is_fixed_species_gift` returns
   true for `oaks_lab`, with the decision flagged in the comment). **Owner decision (2026-09-11): apply the
   clauses in every generation; Yellow/Yellow is the one exemption, because both starters are
   Pikachu by script.** Delivered as `P14-starters-under-clauses.{md,patch}`, which replaces the
   `oaks_lab` line with the pair-aware policy and changes the starter tests.
2. **Dead zones and memorials.** Gen 3 buries a dead-zone casualty: `_handle_no_catch` queues
   `force_faint` and `memorialize` for the partner catch. The RC archives it through the
   retirement job, which keeps its own completion accounting, so the bridge releases the
   engine memorial obligation after the dead zone is recorded (comment at the release). The
   item-4 follow-up is to have the retirement job report `memorialize_done`, so the retired
   pair reaches `MEMORIAL` as in Gen 3, and to delete that release.

## What is now unused

`capture_rules.py`, `party_grant_rules.py`, `no_catch_rules.record` (its `decision` is still
used for naming), `linked_death_rules.record_linked_death` and `record_memorial_completion`,
`member_identity_rules.py`, `acquisition_disposition_rules.py`. `update_run_over` and
`no_catch_rules.decision` remain in use. Their tests still pass against the modules; deleting
the modules and folding those tests into `test_gen1_semantic_events.py` is a separate cleanup
patch once root accepts P8, P9 and P13.

## Verification

```bash
python -m pytest tests/unit/test_gen1_starter_settlement.py tests/unit/test_gen1_wild_encounter.py tests/unit/test_gen1_no_catch_retirement_flow.py tests/unit/test_gen1_retirement_runtime.py tests/unit/test_gen1_evolution_runtime.py tests/unit/test_gen1_npc_exchange_runtime.py tests/unit/test_gen1_memorial_runtime.py tests/unit/test_gen1_memorial_interleaving.py tests/unit/test_gen1_semantic_events.py -q
ruff check server/gen1_engine_bridge.py server/gen1_starter_settlement.py server/gen1_wild_encounter_runtime.py server/gen1_evolution_runtime.py server/gen1_npc_exchange_runtime.py server/gen1_memorial_runtime.py server/adapters/gen1_rby.py
```

The one failure in the scratch copy, `test_generated_sites_reproduce_pinned_original_sources`,
reads generated artifacts against `.cache` inputs the copy lacks; it passes in the worktree.
