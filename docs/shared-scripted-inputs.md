# Shared scripted inputs

`lua/scripted_inputs.lua` is a synchronous host for scripted button input. It advances
the emulator one frame at a time under explicit bounds and returns a receipt. It knows
no game, route, memory layout, emulator global or button vocabulary; the caller supplies
all of them. It is test/harness infrastructure, not part of the player client.

## Construction

`Scripted.new(io)` fails construction unless:

| `io` field | Contract |
| --- | --- |
| `step(buttons)` | Applies the complete button map and advances **exactly one** frame. |
| `frame()` | Returns the frame clock, an integer in `[0, 2^53-1]`. |
| `idle` | Nonempty map of button name to `false`. It defines the whole button vocabulary. |

## Button maps

Every map passed to `step` is complete: each `idle` button is present, `false` unless
the driver set it. A driver map may name only `idle` buttons, with boolean values;
anything else raises. After each `step` the host requires `frame()` to have advanced by
exactly one, or it raises.

## `host.idle(frames)`

Steps `frames` idle frames (integer `0..1000000`) and returns `frames`.

## `host.run(spec, decide, on_phase, on_request)`

`spec` fields:

| Field | Rule |
| --- | --- |
| `name` | Nonempty string, used in every error. |
| `terminal` | Nonempty phase name that ends the run. |
| `max_frames` | Total iteration bound, integer `1..1000000`. Required. |
| `max_phase_frames` | Iterations allowed in one phase, `1..max_frames`. Required. |
| `settle_frames` | Consecutive terminal iterations needed, `1..max_frames`. Default 1. |
| `max_phase_changes` | Bound on the phase trace, `1..1000000`. Default 256. |
| `terminal_idle` | Required boolean: step one idle frame after settling. |
| `phase_callback_may_advance` | Optional boolean, default `false`. See below. |

Each iteration calls `decide(frame, iteration)`, which must return
`buttons, phase[, point[, request]]` without advancing the clock. `phase` is a nonempty
string of at most 256 bytes. On a phase change the host appends
`{phase, frame, iteration}` to the trace and calls `on_phase(name, phase, frame, point)`.
A non-nil `request` must be a table, requires `on_request`, and `on_request(request,
point, frame)` must return exactly `true`. Neither callback may advance the clock,
unless the spec opts in for `on_phase`.

### Parking in `on_phase`

With `phase_callback_may_advance = true`, `on_phase` may step frames itself, for example
to hold one player at a phase until an external release. The host then:

- counts the whole park as the one iteration it happened in, so parked frames count
  against neither `max_frames` nor `max_phase_frames`;
- keeps the point, phase and buttons that `decide` returned before the callback, and
  steps those buttons next;
- records the trace entry with the pre-callback frame;
- still raises if the clock went backwards.

The host cannot interrupt a synchronous callback, so the callback must bound its own
wait. The receipt's `frames`/`end_frame` include parked frames and `iterations` does
not. `decide` and `on_request` stay strict.

When the terminal phase has held for `settle_frames` iterations the run returns
`{name, terminal, iterations, frames, start_frame, end_frame, trace, requests}` without
applying that iteration's buttons (then one idle frame if `terminal_idle`). Otherwise the
iteration's buttons are stepped and the loop continues.

## Failure

Every violation raises: a phase exceeding `max_phase_frames`, a trace exceeding its
bound, an unacknowledged request, a callback or driver that advanced the clock, a step
that did not advance exactly one frame, and running out of `max_frames` ("route made no
bounded progress"). There is no retry or recovery; the caller owns cleanup, the meaning
of the terminal phase and any request policy.

## Bindings

`lua/tests/gen1_scripted_play.lua` binds `step` to a one-`frameadvance` driver step,
`frame` to `emu.framecount()` and `idle` to the Gen 1 lane's button map. Its route
chain is the only caller that sets `phase_callback_may_advance`. It does this so master
`8f6a986` semantics still hold: the duo `ball_gate_new` parks in `on_phase` under
`wait_until`'s 900 s wall-clock limit. Master had no other bound on those frames.
`lua/tests/gen2_scripted_play.lua` receives the host by injection, with its game observer. The unit
controls are in `tests/unit/test_scripted_inputs.py`.
