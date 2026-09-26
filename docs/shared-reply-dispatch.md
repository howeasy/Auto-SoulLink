# Shared reply dispatch

`lua/reply_dispatch.lua` pumps server reply lines into command handlers. It knows no
transport, codec, envelope shape, command set or logging. Those are injected.

## Interface

`ReplyDispatch.new(policy)` fails construction unless every callback is a function
and `budget` is a positive integer or `math.huge`.

| Policy field | Contract |
| --- | --- |
| `budget` | Most lines pulled per `step`. `math.huge` drains the source. |
| `receive()` | Next queued line, or `nil` when none. Errors propagate out of `step`. |
| `decode(line)` | Envelope value. May raise. |
| `validate(envelope)` | The command list, or `nil, reason`. May raise. |
| `handle(command, index, envelope)` | Runs one command. May raise. |
| `on_error(stage, why, subject)` | Stage is `decode`, `validate` or `handle`. Its own errors are swallowed. |

`dispatch:step()` returns `lines_consumed, stopped_by_budget`.

## Rules

- A line is decoded and validated as a whole before any handler runs. The command
  list must be a dense sequence (keys exactly `1..n`); a sparse or keyed list refuses
  the entire line, so no line is ever partly dispatched.
- Each command is handled in order and isolated: a handler error is reported and the
  remaining commands and lines still run.
- The budget limits `receive()` calls. Lines past it are never pulled, so they stay in
  the source in their original order for the next step.
- `step` is not reentrant. A handler calling `step` gets an error, and the outer pump
  keeps its order.

## Gen 1 binding

`lua/gen1/client.lua` injects `net.receive`, `json.decode`, the `{commands=[...]}`
envelope check, `handle_command`, the existing log lines, and `budget = math.huge`
(the drain-all-per-frame policy it had before the extraction).
`lua/gen1/entry.lua` loads this module and injects it as `reply_dispatch`.
