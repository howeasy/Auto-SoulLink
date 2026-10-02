# G2 client card: design proposal (OMP cx-c6d131d6, 2026-10-01)

**Status:** a read-only proposal from an independent OMP peer. It is input for the next session's `lua/gen4/client.lua` card and is NOT accepted design yet. The coordinator must resolve N2 before step 2.

## Shape

The card writes **one new driver file**, `lua/gen4/client.lua`, plus a lupa world model:
- **Exclusive files:** `lua/gen4/client.lua`, `tests/unit/gen4_world.py`, `tests/unit/test_gen4_client.py`.
- **Untouched:** `lua/core/*`, `lua/nds/*` and the existing `lua/gen4/*`.
- **Reuse:** D11 latches, the deferred FIFO and hook-budget policy already exist. The pattern to follow is the reference wiring in `lua/gen3/client.lua`:

  | Lines | Pattern |
  |---|---|
  | 1057-1065 | driver table |
  | 1538 | `frame_hooks` |
  | 2037 | `pre_pump` |
  | 358 | two-valued `box_generation` |
  | 569-573 | D11 |

## Contracts to compose against

- **Driver seam:** `lua/core/session.lua:11-37`. The required functions are `frame`, `read_party` (mons carry `.slot`), `game_is_live`, `hello_ready`, `hello_fields`, `tick_fields`, `in_battle` and `checkpoint_ok`. The optional hooks are `start`, `on_signal`, `frame_hooks`, `pre_pump`, `commands`, `battle_write`, `party_borrowed`, `box_generation` (which returns **two values**), `rescan_boxes`, and so on.
- **Frame order:** see `lua/nds/phase_signals.lua:8-15`. The order is `pre_pump` (`signals:poll()` goes here and **only** here) → `net.pump` → `signals:drain()` → `frame_hooks`.
- **Hook budget:** `phase_signals.lua:24-25`. The cap is 1, and an overrun is a non-latching refusal, so the D7 on-demand hook always remains armable.
- **Reducer:** `lua/gen4/poll_events.lua` is pure. The client builds the snapshot each frame, and events come from `pe:step`.

## Ordered build plan (each step has a falsifier)

0. **Admission + driver skeleton, no writes** (`Entry.admit_routed`, then `Session.new`).
   - Falsifier: exactly one hello, then a tick every 30 frames, and no `exec.*` or `battle_write` is ever reached.
1. **Snapshot + reducer in `pre_pump`**, using reads, safety and `poll_events`. `boxes.gen` bumps only on a complete scan.
   - Falsifier: a nil `boxes` frame does not bump `gen`, so the second value is false.
2. **D7 on-demand hook.** `battle_write` resolves the key and slot, arms the seam hook, and returns `"hold"`. The hook callback validates the overlay, `r0 == bs`, `r1 == ctx`, `ctx.command` and the pin. It then writes both HP copies plus the FAINTED bit, reads them back, and disarms (single-shot).
   - Seam: HG cmd 11 `0x0224A70C`; hge cmd 9 from the ROM dispatch table.
   - Falsifier: a stale `r1`, a wrong command or a wrong overlay each write zero bytes.
3. **900-frame effect window** for the D540 replacement flag, or the LOSE byte on a one-mon party.
   - Falsifier: a flag at +900 is satisfied; at +901 or +5000 it is not.
4. **Deferred box/party writes.** Gate on the save-driver state byte (`safety.lua` `save_busy`), **not** on the battery's modified word, because the battery keeps 1 permanently (`f426a76b`).
   - Falsifier: battery = 1 with an idle driver still arms; a busy driver refuses.
5. **D11 `key_change`**, copied verbatim from gen3 (`begin_alias` + `pending.msg`; the core handles ack/reject).
   - Falsifier: a rejected change plus a reorder retires nothing; two records on one key are refused.
6. **`hello_fields` / `tick_fields`** checked against `tests/unit/protocol_schema.py`.

## Open contract mismatch (N2), to resolve before step 2

`session.lua` gives the driver *frame*-granularity for battle writes, because the core flushes pending `battle_write` entries from the frame loop. The D7 seam needs *instruction*-granularity: the write must happen inside the bus-exec callback.

The proposal is that `battle_write` arms the hook and returns `"hold"`, and the hook callback performs the write. The problem is that the core never observes completion. A battle that ends first then gets its final `battle_write(..., true)` with the hook never having fired.

There are two options:
- **(a) A client-side completion latch** that `battle_write` reports on its next call.
- **(b) A small, shared-core addition**, for example a `when`/hook-id argument. This is a `lua/core` change, so it would stale the Gen 2 digest; batch it and ping Gen 2.

Read the hold-expiry path in `session.lua` before choosing.

Other cautions from the proposal:
- **N1:** polling in `frame_hooks` is one frame late and silently loses first-entry coverage.
- **N3:** a one-valued `box_generation` silently breaks the D11 resend.
- **N4:** treating the battery modified word as "write pending" never settles.
