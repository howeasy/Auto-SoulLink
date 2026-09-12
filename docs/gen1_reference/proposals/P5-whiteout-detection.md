# P5: whiteout detection (Gen 1 R/B/Y)

Status: design only. Emits the shared engine event `{"event": "whiteout", "area_id"}` consumed by
`_handle_whiteout` (`server/state.py:1992-2077`).

## 1. The fact that decides it: the post-battle checkpoint never sees a whiteout

`HandlePlayerMonFainted` calls `AnyPartyAlive` and jumps to `HandlePlayerBlackOut` when no HP is
left (`.cache/pret/pokered/engine/battle/core.asm:969-975`, `:1455-1470`). Back in the overworld
the loop goes straight to `HandleBlackOut` (`home/overworld.asm:354-358`; the poison path via
`wOutOfBattleBlackout`, `:316-320`), which calls `ResetStatusAndHalveMoneyOnBlackout`
(`:756-772`): it zeroes `wIsInBattle` (`engine/events/black_out.asm:6`) and ends in
`predef_jump HealParty` (`:46`). Its frames are delayed from inside `HandleBlackOut`, so no
frame between the last faint and the heal satisfies the overworld checkpoint, whose second
stack word must be the overworld loop (`server/gen1_held_faint.py:38-40`;
`lua/gen1_write_safety.lua:60-66`). The client captures inventory only at that checkpoint
(`lua/gen1_client_entry.lua:152-156`; `lua/gen1_observation_loop.lua:71`), so the first
post-battle inventory shows a healed party at the Center. P3 line 53 (whiteout "after the
post-battle checkpoint shows every party HP at zero") cannot work and must be corrected.

## 2. Recommendation: server-side, from the faint engine signal

Every `battle_faint` and `poison_faint` signal carries `point.party_hex` (the 404-byte party
region, HP at struct offset 1..2), `active_slot`, `battle_hp`, `which`, `map_id`, `battle_flag`
(`server/gen1_engine_signals.py:53-56`; captured by `lua/gen1_engine_signals.lua:29-35` at the
hook). The battle site is `RemoveFaintedPlayerMon+0`
(`data/games/gen1_rby/engine_signals.json`, `battle_faint`), before the copy-down at
`core.asm:1023`, so the active slot may still hold stale HP in `party_hex`; `battle_hp == 0` is
validated instead (`gen1_engine_signals.py:76-77`), and for poison the slot named by `which`
is validated at zero (`:80-81`). Earlier faints of the battle are already copied down. The
predicate is the engine test itself, `AnyPartyAlive`: whiteout iff every party slot has HP zero
once the fainting slot is forced to zero. The evidence survives `HealParty`
(`docs/gen1_reference/ENGINE_SIGNALS.md:64-66`).

Client-side (legacy `check_whiteout`, `lua/clients/gen1_rby_client.lua:1069-1082`, run on every
party diff `:1278` with a per-battle latch `:907,1606`) would also work under the free loop, but
it re-creates a rule in the client and adds a second observation kind for data the signal
already carries. Rejected.

## 3. Which RC data carries the party HP

* Trigger: the signal row `payload.signals[i]` of the `gen1-engine-signal-observations` entry,
  kept verbatim (`server/gen1_engine_signal_runtime.py:83-94`) and re-validated per signal by
  `settle` (`server/gen1_faint_runtime.py:104-109`). Party decode as `:63-70`: slot `s` is
  `party[8+44s : 52+44s]`, HP big-endian at `party[9+44s : 11+44s]`.
* Context: inventory rows `{"location": "party", "box": None, "slot", "key", "blob_hex",
  "evidence_digest"}` (`server/gen1_initial_observation.py:68-69,73`; HP = blob bytes 1..2) from
  the last stable observation (`gen1-inventory-observations[player].observation`, decoded by
  `validate`, `server/gen1_inventory_observation.py:155`). `previous_inventory` supplies the
  party keys of record; `current_inventory` is the post-blackout witness (every party HP at
  max, `wCurMap == wLastBlackoutMap` `0xD719`/`0xD718`), corroboration only, never the trigger.
* `area_id`: `point.map_id` through the adapter area map
  (`server/adapters/gen1_rby.py:292-301`; expose `Gen1Adapter.area_for_map(map_id)`). The legacy
  sent `last_area_id` (`gen1_rby_client.lua:1080`). `_handle_whiteout` does not read it; it is
  dashboard context.

## 4. Translator

`server/gen1_semantic_events.py` now exists with `whiteout_event(*, area_id)` (`:45-46`), so the
detector feeds it instead of replacing it:

```python
# dict | None. last_faint_signal: one validated engine signal {kind, frame, pc, bank, sp, point}
# of kind battle_faint or poison_faint. previous_inventory: the party keys of record (identity
# only). current_inventory: the post-blackout witness, None until it exists; never the trigger.
def whiteout_from_faint(previous_inventory, current_inventory, last_faint_signal, *, area_id):
    point = last_faint_signal["point"]
    party = bytes.fromhex(point["party_hex"])
    count = party[0]
    if count == 0:
        return None
    fainted = point["active_slot"] if last_faint_signal["kind"] == "battle_faint" else point["which"]
    hp = [int.from_bytes(party[9 + 44 * s:11 + 44 * s], "big") for s in range(count)]
    hp[fainted] = 0
    if any(hp):
        return None
    return whiteout_event(area_id=area_id)
```

## 5. Ordering and idempotency

Faint first, then whiteout, inside the same staging: `stage_observation` calls `settle` at
`gen1_engine_signal_runtime.py:95-96`; the detector runs immediately after, over the same
signals, only for a signal whose faint settled (under item 2: `handle_event(faint_event)` then
`handle_event(whiteout_event)`). `_handle_whiteout` iterates ALIVE links whose player mon is
still in `party_keys` (`state.py:1992-2004,2028-2036`), so the fainted mon must already be DEAD
and discarded by `_propagate_faint` (`:2704-2706`), or the whiteout would queue a second
`force_faint` to the same partner. Whiteout deaths queue plain `force_faint` (`:2038`), closed
by the existing overworld executor. Gate: `pokeballs_obtained[player]` (`settle :123`).
Once per signal: record `whiteouts[identifier(player, operation, index)]`
(`gen1_faint_runtime.py:20-21`) in `gen1-faint-settlement` and let `verify_state` recompute it;
the legacy latch is not needed. An Explosion under P5 explode that ends the last mon takes the
same path.

## 6. What Codex must edit

* `server/gen1_semantic_events.py`: add `whiteout_from_faint`.
* `server/gen1_faint_runtime.py` `settle :96-192`: after each settled faint, call the detector,
  record once, hand the event to the engine (`stage.rules.handle_event`) or queue it beside the
  faint command.
* `server/adapters/gen1_rby.py:292-301`: `area_for_map`.
* `docs/gen1_reference/proposals/P3-semantic-events.md:53`: replace the post-battle checkpoint
  wording with the signal predicate.
* `server/state.py`: nothing.

## 7. Tests to add

* `tests/unit/test_gen1_engine_signals.py` fixture `signal()` (`:19-28`): all slots at zero with a
  stale active slot returns the event; one living slot returns None; `poison_faint` with
  `which`; count 0; `area_id` from `map_id`.
* `tests/unit/test_gen1_faint_runtime.py`: faint then whiteout in one batch queues one
  `force_faint` per partner, no duplicate; replay recomputes the same record; suppressed before
  balls.
* Live: the existing whiteout duo scenario (`gen1_rby_client.lua:1797`) through the production
  loop, plus a poison whiteout in the overworld on Yellow.
