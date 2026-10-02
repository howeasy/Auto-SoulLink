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

## N2 research (OMP cx-de3446b7, coordinator-verified against `lua/core/session.lua:173-204`)

**Conclusion: option (a), with no `lua/core` change.** `flush_battle_writes` runs every frame from `frame_end` and calls `battle_write` again for every held entry. That repeated call is the tick a completion latch needs:
- returning `"done"` retires the entry exactly once;
- returning `"hold"` keeps it, with its age, for the HUD;
- returning anything else on the ending frame defers it.

Reject option (b): it would stale the Gen 2 digest and buys nothing.

**Holes the coordinator confirmed: the core can stop consulting the driver while the hook is armed.**
1. **A party-resolution failure retires the entry** (`:182-184`, `why` → `res = "done"`) without calling `battle_write`.
2. **The core holds the entry itself, without asking the driver, in three cases:**
   - writes paused or not yet enabled (`:185-188`);
   - party unreadable (`:189-190`);
   - key not in the party (`:191-192`).
3. **`drop_battle_writes`** (`:166`) empties the set. Its only caller is `tests/unit/test_core_session.py:506`.

In every one of these cases an armed seam hook would still fire and write.

**Required client rule: the armed hook is a one-frame lease.**
- Each `battle_write` call for the entry renews the lease.
- A frame without a renewal disarms the hook. Check this in `pre_pump`, before `frame_advance`, so the hook can never fire unrenewed.
- The latch is keyed by `(entry, key)`, is consumed once, and is disarmed on every exit.

This closes all three holes without touching the core.

**Missed seam on the ending frame:** returning non-`"done"` defers the faint to the checkpoint executor as an overworld write. That is the Gen 3 precedent (`gen3/client.lua:983-989`). It is acceptable only if D12 allows it. D12 says there is no silent fallback, so the deferred write must carry a logged reason.

## c5cca903 review (OMP cx-b86e97a1), reconciled

- **F1 REJECTED:** "the live flag is a u8 read at u32 width". `BOOL` is `typedef int` (`.cache/pret/pokeheartgold/lib/include/nitro/types.h:39`), and `str` is a word store, so the u32 read is the correct width.
- **F6 accepted as verification:** the boxed-clone identity check is fail-closed (`gen4_codec.py:477-490` re-raises on a bad slot).
- **F2 stall risk REFUTED from source** (OMP cx-eb45b481): `sFieldSysPtr` is written only in the field overlay init (`pokeheartgold src/field_system.c:57,71`), and `unk6C` = `runningFieldMap` is set TRUE only at `FIELD_MAP_INIT_STATE_DONE` (`src/field/fieldmap.c:225`). So the gate cannot close at the title or CONTINUE screens. Residual risk: an input buffered before the gate closes could open a menu, but `idle()` then stays false and the boot fails cleanly at its bound. For player-in-control, the engine's own predicate is `FieldSystem_IsPlayerMovementAllowed` (`field_system.c:203-205`: not paused AND runningFieldMap AND no field task); prefer it for the client's idle. Original wording follows: gating on field-allocated plus `unk6C` might stop input before the overworld. A boot that reaches row l's idle at `c5cca903` refutes it; a boot timeout confirms it. The suggested narrower predicate is in `safety.lua:21-22`: field app alive AND no launched app.
- **F3 / F7 accepted as test follow-ups:**
  - F3: `live()` true from frame 1 while `idle()` is never reached must return `overworld=false` at the limit.
  - F7: build the ancestry fake from a real `Decoded`.

### Lease mechanics (OMP cx-28909757, coordinator-corrected)

- **The API is sufficient.** `signals:request(PHASE)` renews the lease. While armed it returns `nil, "busy: <phase> already armed"` (`phase_signals.lua:158`) before any cap test or registration, so a per-frame renew is free; treat that "busy" as held. `signals:disarm(PHASE)` releases it. The D7 phase must declare **no `active` predicate**, otherwise `poll()` (`:167-179`) re-arms it every frame and the lease never expires.
- **Frame order, CORRECTED.** The OMP placed `pre_pump` before `frameadvance`; the actual order is:
  1. `emu.frameadvance`, where the hook fires;
  2. then `frame_end`: `pre_pump` (`session.lua:409`) → drain (`:422`) → `frame_hooks` (`:435`) → `flush_battle_writes` (`:472`, last).

  So no driver code runs after the flush and before the next `frameadvance`. If the core skips `battle_write` on frame N (writes paused, party unreadable, key not in the party, or retired), the hook stays armed through frameadvance N+1. A `pre_pump` disarm on N+1 is one frame too late.
- **The guard is in the callback.** The hook callback writes only if the lease was renewed by the `flush_battle_writes` of the immediately preceding `frame_end` (`lease.renewed_frame == current_frame - 1`). Otherwise it writes nothing and disarms. The `pre_pump` disarm is then just cleanup.
- **Renew only on the frame_end write path.** Never call `request` from inside a bus callback, because that re-arms mid-frame.
- **Test:** the lupa test (text in the cx-28909757 reply) covers arm → no renew → fire → `hits == 0`, plus the reciprocal leg renew → fire → `hits == 1`. Its fire must happen *before* the `pre_pump` of the following frame, to model the real order.
- **Frame counter (OMP cx-3d691308, coordinator-reconciled).** Use `emu.framecount()` on both sides: as the Gen 4 `game.frame()`, the same as `gen3/client.lua:1057`, and read directly in the callback, never via `session.frame`.
  - **Supporting evidence:** `gen1/client.lua:1506` requires the frame stamped in a hook during frame X to equal the frame read in frame X's `frame_end`. So a renew in the `frame_end` of N stores N, and the callback during the next advance reads N+1. That gives `renewed_frame == current_frame - 1`.
  - **The OMP proposed `==`. That is rejected:** it inverts its own evidence.
  - **Confirm once, live, before relying on it:** append `emu.framecount()` in the hook (`probe_gen4_hooks.lua:899` already does) and around `emu.frameadvance()` in `step()` (`:540`), then compare.
- **Idle predicate data (OMP cx-3d2ee951).**
  - `FieldSystem_TaskIsRunning` is `taskman != NULL` (`pokeheartgold src/task.c:70-72`), and `taskman` = fs+0x10 is already in the pack as `probe_field.task`.
  - A launched application occupies `processManager->parent`/`child` (`task.c:74-76`, `field_system.c:118-128`), not a task.
  - OPEN: which mechanism the start menu, the PC and the Pokégear each use, and whether `safety.lua:21-22` excludes them. Note `sub_0203DF8C` = `parent != NULL && runningFieldMap`, so `parent` may be non-NULL in normal field play. Do not require `parent == NULL` until the source is read.
- **Idle predicate SETTLED (OMP cx-1a0f85d9, coordinator-composed).**
  - The start menu is a FieldTask (`pokeheartgold src/start_menu.c:111-125`), so `taskman != NULL` while it is open.
  - The PC is a launched app (`launch_application.c:406`, from `scrcmd_c.c:1995`), so it occupies the processManager child slot.
  - `processManager->parent` IS the field overlay (`field_system.c:95,101,147`) and is non-NULL in all normal play.
  - So: client idle = `runningFieldMap (fs+0x6C) != 0 AND taskman (fs+0x10) == 0 AND parent != NULL AND child == NULL`. This is `safety.lua:21-22`'s field_app/launched_app pair plus `probe_field.task`, with no new pack data.
  - The Pokégear is a launched app reached from the start menu (`start_menu.c` `Task_StartMenu_Pokegear` → `PokegearPhone_LaunchApp`). `Task_StartMenu_WaitApp` parks until no app is running, so `child == NULL` is the load-bearing term for the PC and the Pokégear, while `taskman == 0` covers only the menu itself (OMP cx-03006359). `child` as the launch slot is inferred; cite its writer when building the client.
