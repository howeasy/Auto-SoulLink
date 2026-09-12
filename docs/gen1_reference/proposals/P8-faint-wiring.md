# P8: the faint call site decides through the shared rule engine

Status: patch ready, applies cleanly (`git apply docs/gen1_reference/proposals/P8-faint-wiring.patch`).
Verified in a scratch copy of the worktree (nothing in the worktree was edited): the wired
`server/gen1_faint_runtime.py` passes its own 34 tests unchanged, and the wider death, memorial,
deferred-faint, atomic-frame, ball-activation and engine-signal suites (743 tests) pass; ruff clean.
This is handoff item 2 applied to one call site, as the shape for the rest.

## What changes (`server/gen1_faint_runtime.py`, `settle`)

Before: `record_linked_death(stage.rules, ...)` from `server/linked_death_rules.py`, a detached
copy of `_propagate_faint`, returned the peer command and the runtime raised for `explode_mode`.

After:

```python
stage.rules.handle_event(player, faint_event(key=row["key"], level=mon.level, cause=row["cause"]))
if link.status != LinkStatus.DEAD:
    raise JournalError("shared rule engine did not settle the linked death")
link.cause = row["cause"]            # RBY knows battle versus poison; _propagate_faint records "battle" for every generation
at = link.killed_at                  # the engine's own death timestamp is the record's timestamp
physical = [c for c in stage.rules.queued_commands[partner]
            if c.get("cmd") in ("force_faint", "force_explode") and c.get("key") == getattr(link, partner).key]
if len(physical) != 1:
    raise JournalError("shared rule engine did not select exactly one peer death command")
stage.rules.queued_commands = {"a": [], "b": []}
effect = {"player": partner, "command": dict(physical[0])}
effect["command"]["death_id"] = death_id
```

The shared engine (`_handle_faint` -> `_propagate_faint`, `server/state.py:1704`, `:2685`) now
does what the copy did: pair DEAD, both party keys released, both memorial obligations added,
the peer command selected, run-over checked. Everything downstream is untouched: the death
record, its phases, the deferral behind storage jobs, the receipt-verified ACK, the memorial
scheduling and every invariant in `verify_state` / `verify_journal`.

## Three facts the wiring had to respect

1. **Evidence checks stay outside the engine.** Ball activation history, the identity-registry
   link match and the no-active-trade rule run before `handle_event`, exactly as before.
2. **The engine queues more than the RC executes.** Besides the peer death command it queues
   `play_sound` (no RBY sound path; `sfx` is false on every profile), `memorialize` for both
   halves (executed on Gen 1 by `gen1_memorial_runtime` after the physical faint receipt; the
   obligation is already in `pending_memorials`) and, when the run ends, `game_over` (the RC
   exposes `run_over`). Those are drained deliberately and the reason is in the code comment.
   Under handoff item 4 the executor map replaces the drain.
3. **`verify_state` compares `link.cause` to the engine signal.** `_propagate_faint` writes
   `cause="battle"` for every generation, so the wiring sets the RBY cause afterwards. The
   one-line standard change (`entry.cause = msg.get("_cause", "battle")` in `_propagate_faint`)
   removes that adjustment; the translator already carries `_cause`.

## Deliberately not in this patch

- The Explode refusal at the top of the loop stays (P7 removes it once the P5 executor exists).
  The engine would already select `force_explode`; the wiring accepts either command name.
- `linked_death_rules.record_linked_death` is no longer imported here but the module stays
  until `gen1_memorial_runtime` (which still uses `record_memorial_completion`) is wired
  through `memorialize_done_event`.

## Verification

```bash
python -m pytest tests/unit/test_gen1_faint_runtime.py -q                                   # 34 passed
python -m pytest tests/unit -q -k "faint or memorial or death or engine_signal or atomic_frame or deferred or ball or control_view or operation_runtime"
ruff check server/gen1_faint_runtime.py
```

In the scratch copy the second command showed 743 passed; its only failures were tests that
read `.cache/pret` sources, which the copy did not include, and they pass in the worktree.
