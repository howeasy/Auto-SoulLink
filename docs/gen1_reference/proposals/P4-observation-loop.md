# P4: free-running Gen 1 observation loop (execution model phase 1, client half)

Status: implemented as two new, non-reserved files; 11 lupa tests green; the Lua parse gate
and ruff green. Nothing existing was edited. Owner: root wires it as launch mode
`free_service` (section 3) and redefines the boundary predicate at two construction sites
(section 4). The server `observation` consumer (handoff item 3) is root's; the event shape
it receives is in section 1.

- `lua/gen1_observation_loop.lua` (new, 96 lines): `M.new(ctx)` returns `{tick, observe, run}`.
- `tests/unit/test_gen1_observation_loop.py` (new): sequencing proof with Lua fakes for the
  engine, the observers, the journal, the session and the writer; every fake refuses a call
  made outside `ctx.at_boundary`, so the tests already run the relaxed predicate.

```bash
python -m pytest tests/unit/test_gen1_observation_loop.py -q      # 11 passed in 0.26s
python tools/lua_syntax_check.py                                  # OK: 301 Lua files parsed cleanly
python -m ruff check tests/unit/test_gen1_observation_loop.py     # All checks passed!
```

## 1. What it is

The loop of `EXECUTION_MODEL_PROPOSAL.md` section 3, testable because one iteration
(`tick()`) never advances the emulator. Per tick:

1. `engine:peek()`, `observers:prepare(cursor)`. More than 32 signals or 16 receipts is an
   error (nothing dropped), the bounds `gen1_frame_client.lua:333,338` enforced.
2. If a signal, a receipt or the heartbeat (`frame % 30 == 0`) exists: build one
   `observation` event, set `baseline.observation_sequence`, `baseline.acquisition_source`
   and, when signals exist, `baseline.engine_signals` (its own contiguous counter, exactly
   `close_range` at `:259-265`); `journal:append(event, baseline)`.
   Otherwise, if a witness opened without returning (a `party_begin`/`box_begin` capture
   call, `gen1_acquisition_observers.lua:102-104`): `persist(baseline)`, which is
   `journal:append_many(JSON.array(), baseline)` (`client_journal.lua:129-139`), so the
   cursor is durable before the witness is acknowledged.
3. Only then `engine:drain(signals)` and `observers:drain(rows)`: the persist-before-drain
   invariant of `gen1_frame_client.lua:340-345`.
4. `writer:pending()` then `writer:service()`; `session:pump()`; `observers:ready(cursor)`.

The event:

```json
{"schema": "rby-observation-v1", "event": "observation", "frame": 4821, "sequence": 17,
 "context": {"context_generation": "...", "physical_instance": "...", "save_identity": {}},
 "rom": "<final sha1>",
 "signals": {"schema": "rby-engine-signals-v1", "sequence": 3, "signals": []},
 "acquisitions": [{"kind": "capture", "receipt": {}}],
 "inventory": {"schema": "rby-initial-observation-v1", "frame": 4821, "source": {}}}
```

`signals` is the batch `close_range` published as `bundle.engine_signals` (or `null`);
`acquisitions` holds the same `{kind, receipt}` rows the credit bundle carried (`:336`);
`inventory` is the heartbeat checkpoint (`:256-258`), `null` off-heartbeat or when
`inventory()` returns nil (party not write-safe). The server consumer therefore feeds
`gen1_source_receipts.decode` and `gen1_engine_signal_runtime.record` unchanged, checks
`sequence` contiguity per player, and checks `rom` and `context.context_generation`.

`ctx` fields. Required: `engine` (`peek`, `drain`, `batch`), `journal` (`append(event,
baseline)`; `append_many` for the cursor-only persist unless `persist` is given), `baseline`
(a table, or a function returning the current `store:read().observation`; the entry should
pass the function so an ACK-side baseline change, `client_journal.lua:210-217`, is never
overwritten by a stale copy), `session` (`pump()`), `owned()`, `rom_hash()`. Optional:
`observers` (`initial`, `prepare`, `drain`, `ready`), `inventory()`, `writer` (`pending()`,
`service()`), `persist(baseline)`, `heartbeat` (frames, default 30), `frame()` (default
`emu.framecount`).

Where the module departs from the handoff sketch, and the line that forced it:

| Sketch | Module | Why |
| --- | --- | --- |
| `seq` from `journal:last_observation_sequence()` | `(baseline.observation_sequence or 0) + 1`, read at publish time | the persisted baseline is the truth; no new journal API |
| `signals = engine:batch(signals, seq)` | separate `baseline.engine_signals.sequence` | the server refuses a skipped engine sequence (`server/gen1_engine_signal_runtime.py:87-88`); heartbeats would skip it |
| `ctx.state` | `baseline.acquisition_source` | `prepare` demands `frame == state.frame + 1` (`gen1_acquisition_observers.lua:96`): the cursor advances every frame in memory and is persisted with every publication |
| publish only on receipts | also `persist` on a witness without a receipt | `party_begin` changes `capture_open` and yields no receipt (`:102-104`); draining it unpersisted breaks the contract at `:4-5` |
| `ctx.boundary` in the event | dropped | beyond `context`, `rom` and `frame` it only adds a `host.held = true` stanza, which is false under free-run |
| `journal:pending_write_command()` | `writer:pending()` | the loop stays ignorant of command shapes; item 4 owns them |
| `ctx.persist(baseline)` | kept, defaulting to `journal:append_many(JSON.array(), baseline)` | that is what `save()` at `gen1_frame_client.lua:136` does today |
| `while true do emu.frameadvance() ... end` | `run()` kept; the entry should register `event.onframeend` | `gen1_rby_client.lua:2033-2039`: a blocking loop hangs the duo harness that `dofile()`s the client; `tick()` is the callback body |

`observe()` is `tick()` without the writer, the pump and `ready`, for a writer that steps
frames itself (item 5): call `loop:observe()` after every frame it steps, never `tick()`
(re-entrant). The `ready` at the end of `tick()` then fails closed if a writer stepped
frames without doing so.

Two consequences root should know:

- Heartbeat cost. `ORDINARY_FRAME_TURNOVER_PROFILE.md` measured the full inventory capture
  at 27.97 ms. At 30 frames that is two captures a second, 5.6% of wall time and a stall of
  about 1.7 frames each. `heartbeat = 60` halves it; the default stays at 30 as the
  proposal wrote it. Owner decision.
- Recovery. A persisted `acquisition_source` whose frame is not the current frame fails
  closed at the first `prepare` (as `gen1_frame_client.lua:112` does today). The recovery
  barrier clears `baseline.acquisition_source`, and the loop then takes a fresh
  `observers:initial(frame)`.

## 2. What the tests prove

| Test | Assertion |
| --- | --- |
| quiet non-heartbeat frame | no append, no persist, no drain; the tick is `peek, prepare, pending, pump, ready`; `ctx.at_boundary` is false afterwards |
| signals | `batch` then `append` then `drain` then `observers:drain`, in that order; the queue is empty afterwards; `inventory` is `null` |
| heartbeat | frame 120 appends inventory with `signals = null` and `acquisitions = []` (a JSON array, not `{}`); frame 121 is quiet again |
| sequence | events 1, 2, 3 carry `sequence` 1, 2, 3 and each baseline carries the same number; the engine batches carry 1, 2 (their own counter); `acquisition_source.frame` follows the frame |
| writer | `service` never runs while `pending()` is false; when true it runs after `append` and `drain`, before `pump` |
| pump | 45 ticks, 45 pumps, one heartbeat event |
| bounds | 33 signals or 17 receipts raise `frame ... batch exceeds source bounds`; nothing appended, nothing dropped, the flag cleared |
| capture call | a `party_begin` witness persists the cursor (no event) before the observers drain; the next `prepare` sees `capture_open` |
| persisted cursor | a `baseline.acquisition_source` is adopted; `initial` is not called |
| no observers | the loop runs with `observers = nil`; `acquisitions` is `[]` |

## 3. Wiring `free_service` in `lua/gen1_client_entry.lua` (root-owned, not edited)

Line numbers as read today.

| Line | Change |
| --- | --- |
| `:9` | accept `launch.mode == "free_service"` beside `held_service` |
| `:64-75` | free_service takes the plain `Execution.new` host of the `else` branch (`:77-78`); no bounded host, no `authorize` |
| `:80-125` | unchanged: hold at the first verified overworld checkpoint, open the store and journal, enrol the initial inventory, the bootstrap observer and the held faint executor under that hold |
| `:126-224` | skipped for free_service (no `gen1_frame_client`, no frame store); keep `self.acquisitions` (`:128-130`) with `held = at_boundary` (section 4) |
| `:225-241` | unchanged (`gen1_runtime.new`); `control_interval`/`sync_interval` as for ordinary frames |
| after `:241` | once `bootstrap_ready` holds (`gen1_frame_client.lua:165-169`: initial inventory and bootstrap acknowledged, engine signals present), build `self.loop_ctx` and `self.loop` (sketch below), then `self.host.set_held(false, "free-running observation")` |
| `:245-275` `step()` | when `self.loop` exists, `self.loop:tick()` replaces `:257-266` |
| `:308-321` `run()` | for free_service, `event.onframeend(function() local ok, why = service:step(); if not ok then ... end end, "slink_gen1")` and return, instead of the `yield_held` loop |

```lua
local at_boundary = function() return self.loop_ctx ~= nil and self.loop_ctx.at_boundary == true end
self.loop_ctx = {
    engine = self.observer.signals,   -- built at gen1_initial_observation.lua:50-52: give it owned = source_owned and held = at_boundary
    observers = self.acquisitions,
    inventory = function()            -- Observation.capture (:7-18) asserts the hold; this is the same capture without it
        if not memory.isPartyWriteSafe() then return nil end
        return {schema = "rby-initial-observation-v1", context_generation = generation,
            final_sha1 = launch.cartridge.final_rom_sha1, frame = emu.framecount(),
            source = require("gen1_full_save").capture(memory, launch.cartridge.variant)}
    end,
    journal = {                       -- durable_runtime.lua:386-399 validates and appends; the outbox is pumped by step()
        append = function(_, event, baseline)
            local ids, why = self.runtime:observe(JSON.array({event}), baseline); return ids and ids[1], why end,
        append_many = function(_, events, baseline) return self.runtime:observe(events, baseline) end},
    baseline = function() return assert(self.store:read()).observation end,
    session = {pump = function() assert(self.runtime:step()) end},   -- never blocks: connector.lua settimeout(0)
    writer = nil,                     -- item 4 supplies {pending = ..., service = ...}
    owned = source_owned,
    rom_hash = function() return gameinfo.getromhash():lower() end}
self.loop = require("gen1_observation_loop").new(self.loop_ctx)
```

`self.observer.signals` is constructed inside `gen1_initial_observation.lua:50-52` with
`owned = options.owned` (the hold-asserting `owned` of the entry, `:109-113`) and
`held = physical_stop_verified`. For free_service either hand `source_owned` and
`at_boundary` through those options or construct `gen1_engine_signals.new` in the entry and
give it to the observation. `check()` in both source modules calls `owned()` on every peek
and drain, so a hold-asserting `owned` stops the loop on its first tick.

## 4. The boundary predicate: one line at each construction site

`held` is not a two-file assertion. `gen1_acquisition_observers.lua:17` forwards it as
`common.held` into all six per-kind observers, each of which asserts it in `peek` and
`acknowledge`:

| File | `held()` assertion sites |
| --- | --- |
| `lua/gen1_engine_signals.lua` | `:13` (constructor), `:74` peek, `:78` drain, `:82` batch, `:89` and `:103` flush |
| `lua/gen1_acquisition_observers.lua` | `:13`, `:17` (forwarded), `:37` check (every method) |
| `lua/gen1_capture_observer.lua` | `:11`, `:48` peek, `:50` acknowledge |
| `lua/gen1_grant_observer.lua` | `:14`, `:82`, `:84` |
| `lua/gen1_static_observer.lua` | `:16`, `:89`, `:91` |
| `lua/gen1_npc_exchange_observer.lua` | `:16`, `:80`, `:82` |
| `lua/gen1_wild_encounter_observer.lua` | `:13`, `:55`, `:57` |
| `lua/gen1_evolution_observer.lua` | `:13`, `:55`, `:56` |

Renaming the predicate inside the sources is therefore 22 lines in eight files for no
behavioural gain. The relaxation the handoff asked for ("called between frames from the
main loop, a flag the loop sets") is one line at each of the two places the predicate is
constructed, and nothing else moves:

| File | Line | Today | Relaxed |
| --- | --- | --- | --- |
| `lua/gen1_initial_observation.lua` | `:52` | `held=function()return options.host.status().physical_stop_verified end` | `held=function()return options.host.status().physical_stop_verified or (options.at_boundary and options.at_boundary()==true) end` |
| `lua/gen1_client_entry.lua` | `:130` | `held=function()return self.host.status().physical_stop_verified==true end` | `held=function()return self.host.status().physical_stop_verified==true or at_boundary() end` |

The `or` keeps held_service and the tests that drive the sources under a real hold working
unchanged. `flush()` (`gen1_engine_signals.lua:88-107`) keeps demanding the hold: the free
loop never calls it (it uses `peek`, `batch`, `drain`). The hooks fire inside emulation
and never consult the predicate.

## 5. Not done here, by design

- No server consumer, no deletions (phases 1 server half, 2 and 3 of the proposal).
- No `writer`: item 4. Its `service()` takes and releases the hold itself and, if it steps
  frames, calls `loop:observe()` per frame.
- No `event.onloadstate` barrier trigger (proposal section 6): the recovery barrier is
  root's; the loop only fails closed on a stale cursor.
