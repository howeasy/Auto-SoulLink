# Gen 3 route speed: 300% default (2026-09-29)

## Decision

The Gen 3 duo driver default is now **300%**, not 1600. `100` is reserved for an explicit
qualification run and is never reached by accident, because nothing in the runner selects it.

Scope: harness only. `lua/tests/duo/duo_gen3_main.lua:104-111` is the whole change. No production
code, no `client.lua`/`run.lua`, no `tools/e2e_duo.py`.

## Why

The orchestration contract for route tests is "300 percent, 100 reserved for explicit
qualification". The driver hard-coded `D.speed or 1600`, so a route run that asked for nothing got
1600. `tools/e2e_duo.py` supplies **no** `speed` key on the Gen 3 path (the only `speed` uses in
that file are Gen 2: `gen2_speed()` at `:4275` and `gen2_frame_scale()` at `:2796`), so the default
was not a fallback in practice -- it was the value every FR/LG/EM/RR route run used.

`speedmode` is a BizHawk front-end capability (throttle policy), not emulator core state, so
asking for a different percentage does not change what the core computes. It changes how fast
frames are produced. 1600 was fast enough to starve the host when other lanes were resident;
300 keeps the same frame ordering and receipts while leaving the machine headroom.

## The diff

```lua
-- was: pcall(function() client.speedmode(D.speed or 1600) end)
local speed_requested = D.speed or 300
local speed_ok, speed_err = pcall(function() client.speedmode(speed_requested) end)
log(fmt("speedmode requested=%d call=%s", speed_requested, speed_ok and "ok" or tostring(speed_err)))
```

Three facts, deliberately:

1. **The default is a named local**, so the requested value and the value handed to
   `client.speedmode` are the same thing. A receipt can no longer imply a speed the driver did not
   ask for.
2. **The pcall result is captured, not discarded.** The old line swallowed any `speedmode` error
   entirely, so a front end without the call looked identical to a run that requested it. The log
   distinguishes `call=ok` from `call=<error>`, making a missing or erroring call visible in the
   receipt.

   **`call=ok` means only that the API call returned without error. It is not a readback.** It
   does not show that the front end accepted the throttle or is running at that rate. The token
   is `call=`, not `applied=`, because the difference matters exactly when a run is slow and the
   receipt still looks clean. Proving the real rate would need the front end's own speed state,
   which this driver does not read and this card does not add.
3. **`log`/`fmt` are the existing driver pair** (`duo_gen3_main.lua:40,47`), the same ones the
   adjacent instance banner at `:101` uses. No new helper, no table, no title fork.

`D.speed` still wins when a caller supplies it, so an explicit qualification run at 100 needs no
code change: pass `speed` on the stub.

## Verification

- `python tools/lua_syntax_check.py` — exit 0. This is the only check; there is deliberately **no**
  test asserting the literal 300. A mirror test would only restate the constant and would break
  on the next legitimate retune, which is the churn this card exists to avoid.
- The observable is the receipt line `[duoA] speedmode requested=300 call=ok`, emitted next to
  the existing `duo instance ...` banner on every Gen 3 duo run. Read it as "the call returned",
  not as "the emulator is at 300%".

## Open

- Whether 300 is enough headroom when two lanes run back to back. Settled by the next multi-lane
  cut: if a run is still slow, raise the default here rather than widening anything else.
- `100` qualification runs are not yet wired to a flag. `D.speed` accepts it today; a named
  `--speed` on `tools/e2e_duo.py` is a separate card and is not part of this cut.
