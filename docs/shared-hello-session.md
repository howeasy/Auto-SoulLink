# Shared hello session

`lua/hello_session.lua` schedules one hello per connection and save identity. It is
synchronous and knows no transport, game, save layout, payload or retry cadence.
"Ready" means a hello was queued for the current connection and identity. It is not
server admission or an acknowledgement.

## Interface

`HelloSession.new(policy)` fails construction unless every callback is a function.

| Policy callback | Contract |
| --- | --- |
| `connected()` | Exact `true` when the transport is up. Anything else invalidates (`disconnected`). |
| `identity()` | Opaque nonempty string or finite number naming the save, or `nil, reason`. |
| `ready(identity)` | Exact `true` when the game may hello now, else `false, reason`. |
| `send(identity)` | Queues the hello. Exact `true` means queued; anything else is a refusal. |
| `retry_delay(attempts, why)` | Nonnegative integer frames until the next attempt. |
| `on_invalidate(reason, identity)` | Binder cleanup for the ended session. May raise; cleanup is retried. |
| `on_error(stage, why)` | Reporting only. Its own errors are swallowed. |

`session:step(now)` takes a nonnegative integer clock and returns `true` once a hello is
queued, else `false, reason`. `session:invalidate(reason)` ends the session and returns
whether cleanup completed. `session:status()` returns a detached copy of `ready`,
`connected`, `identity`, `attempts`, `generation`, `reason`, `next_attempt`,
`last_error` and `cleanup_pending`.

## Rules

- A stable identity never re-hellos. A disconnect, clock rewind, identity change,
  explicit invalidation or callback error each require a new hello.
- Identity change is detected across disconnects (the last identity is retained).
- `send` is followed by re-checking `connected()` and `identity()`. A change during
  the send never publishes readiness.
- A refused `ready`/`send` and a throwing callback both wait `retry_delay` frames.
  A failure in the clock or in `retry_delay` itself retries on the next step.
- A failed `on_invalidate` holds every later step until cleanup succeeds.

## Gen 1 binding

`lua/gen1/client.lua` supplies `net.connected`, a save identity key (player, foundation,
artifact kind, ROM SHA-1, wPlayerID, wGameInternalVersion), the overworld checkpoint or
battle readiness gate, the pureRGB version hold, the hello payload and a one-frame retry.
`lua/gen1/entry.lua` loads this module and injects it as `hello_session`.
