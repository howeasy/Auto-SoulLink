# P3: Gen 1 translators into the shared rule engine

Status: implemented as two new, non-reserved files, 13 tests green against the real
`SoulLinkState` with the Gen 1 adapter. Nothing existing was edited.

- `server/gen1_semantic_events.py` (new): pure functions that turn decoded RBY receipts and
  engine signals into the semantic events `SoulLinkState.handle_event` already consumes for
  Gen 3. Field names match the handlers in `server/state.py` exactly (cited in the module
  docstring).
- `tests/unit/test_gen1_semantic_events.py` (new): drives the shared engine with translated
  events and asserts the Gen 3-standard outcomes.

```bash
python -m pytest tests/unit/test_gen1_semantic_events.py -q     # 13 passed
```

## What the tests prove about the fold-back (handoff item 2)

| Test | Standard behaviour confirmed through the shared engine with the Gen 1 adapter |
| --- | --- |
| two captures in one area | pending after the first, `LinkStatus.ALIVE` and `AreaStatus.LINKED` after the second |
| scripted grant in a real area | links under `gift_route_1`, never consumes `route_1`, never activates the ball gate |
| no_catch after the partner caught | `DEAD_ZONE`, `force_faint` and `memorialize` queued for the partner's catch |
| faint | pair DEAD, `force_faint` for the peer, `memorialize` for both (own via the return value) |
| faint with `explode_mode` | `force_explode` for the peer: the engine selects it because the Gen 1 adapter opts in |
| faint before Poké Balls | ignored, exactly as Gen 3 |
| evolution `key_change` | link, party keys and species migrate to the new key |
| whiteout with nothing boxed | peer force-fainted, `run_over`, `game_over` to both |
| deposit | `box_mon` for the partner half |
| rival trainer battle, swap on | `replace_rival_team` with the partner's cached 66-byte blob |
| memorialize_done from both | pair reaches `MEMORIAL` |

Two facts the tests surfaced that the fold-back must respect:

1. `handle_event` returns the caller's own commands and queues only cross-player ones
   (`server/state.py:241-246`). `StagedSoulLinkState.take_commands(player, immediate)`
   already merges both into the transaction (`server/staged_state.py:159-167`), so the
   translators must pass the return value through, never drop it.
2. `pallet_town` is itself a gift area for Gen 1 (`adapter.is_gift_area`), so a starter
   grant keeps `pallet_town` as its link area while a grant received on a route links under
   `gift_<route>`. `capture_from_fact` leaves that to the adapter, as Gen 3 does.

## What Codex edits to consume it (root-owned files)

| Call site | Replace | With |
| --- | --- | --- |
| `server/gen1_acquisition_runtime.py:251-256` | `record_disposition(...)` and the `exempt_grant`/`clause_checked` outcome | `immediate = stage.rules.handle_event(player, capture_from_fact(fact, mon, area))`; keep `settled` as evidence; delete the `CONSTRAINT_REASON` blocker at `:258-265` |
| `server/gen1_starter_settlement.py:126` | `record_exempt_party_grant(...)` | `handle_event(player, capture_event(..., gift=True, area_id="intro"))` |
| `server/gen1_wild_encounter_runtime.py:340-348` | `no_catch_rules.record(...)` | `handle_event(player, no_catch_event(area_id=area, species_id=begin["species_id"], level=begin["level"]))`; drop the dead-zone retirement job |
| `server/gen1_faint_runtime.py:126-160` | the Explode refusal and `record_linked_death(...)` | `own = handle_event(player, faint_event(key=row["key"], level=mon.level, cause=row["cause"]))`; the death record tracks the one peer command it finds in `stage.rules.queued_commands[partner]` |
| `server/gen1_evolution_runtime.py:210-220`, `gen1_npc_exchange_runtime.py:188` | `member_identity_rules.rekey` | `handle_event(player, key_change_event(...))` next to the identity-registry migration |
| `server/gen1_memorial_runtime.py:284` | `record_memorial_completion` | `handle_event(player, memorialize_done_event(key=...))` from the verified receipt |
| new (P5 whiteout design) | none | `handle_event(player, whiteout_event(area_id=...))` from the faint engine signal's party bytes (`point.party_hex`): the post-battle inventory can never show a whiteout because the engine heals the party at blackout (`P5-whiteout-detection.md`) |
| `server/gen1_run_config.py:84-87` | `validate_event=no_new_observations` | a validator that accepts these event names from an admitted session |

Then delete `capture_rules.py`, `no_catch_rules.py`, `linked_death_rules.py`,
`party_grant_rules.py`, `member_identity_rules.py`, `acquisition_disposition_rules.py` and
their tests. `tests/unit/test_state.py` remains the rule oracle.

## One standard change this exposes

`_propagate_faint` records `cause="battle"` for every death (`server/state.py:2711`). The
translator carries `_cause` ("battle" or "poison") so that one line can become
`entry.cause = msg.get("_cause", "battle")` for every generation when root wants it.
