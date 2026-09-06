# Shared durable client runtime composition

`lua/durable_runtime.lua` composes the existing connector, session, journal,
control service and command executor. It contains no cartridge addresses,
generation-specific admission policy, frame advancement or production selection.
`lua/rr/runtime.lua` is its RR binding: protocol `slink-rr-durable-v1`, hold notice
`rr_hold`, variant `rr`, and mandatory transient `ghost_pos` refusal. RR callers
keep the same constructor and returned methods.

## Reuse prerequisites and constructor

Use this module only with the matching durable versions of
`client_session`, `client_journal`, `command_executor`, `control_service`,
`connector`, `json_codec` and their dependencies. The executor must implement
command-bound prepared intents and `armed`/`PENDING`; the session must support
32-hex durable IDs; the connector must implement discard-on-disconnect and all
queue diagnostics. The durable journal must already be opened against the
binding's exclusive, checked storage. This composition does not migrate a v1
session, create the journal, qualify the host, or establish cartridge ownership.

```lua
local Runtime = require("durable_runtime")
local runtime, why = Runtime.new({
    protocol = "slink-gen1-durable-v1", -- explicit binding/server agreement
    hold_event = "gen1_hold",
    variant = "red",                  -- optional; forwarded to client_session
    reserved_events = {hud_ping=true}, -- optional transient-event set
    transport = connector,
    server_host = "127.0.0.1", server_port = 9000, player = "a",
    journal = opened_journal, clock = monotonic_clock, host = qualified_hold_host,
    read_hello = read_owned_metadata,
    metadata_matches = admission_matches_current_metadata,
    operation_ready = operation_specific_readiness,
    executor_adapter = prepared_command_adapter,
    reconciliation = verified_local_evidence_or_nil,
    new_nonce = fresh_nonce,           -- optional platform default
})
```

The protocol names in this example exercise the common interface; the example
does not establish a selected or qualified Gen1 client/server deployment.

Protocol, hold-event, variant and reserved-event names have 1–64 characters,
start with a lowercase letter and otherwise contain lowercase letters, digits,
underscore, period or hyphen. `hold_event` cannot be `hello`, `control`, `sync`
or `command_ack`. `reserved_events` is a set of names mapped to `true`; it cannot
reserve `sync` or `command_ack`. Protocol, hold-event and reserved-event membership
are captured at construction. RR's protocol/hold constants cannot be retargeted
through caller options or the informational module fields. Caller callback lookup
remains live through the RR wrapper's option delegation.

`new` establishes the independent hold and calls the supplied connector's dot API
`init(server_host, server_port, {discard_on_disconnect=true})` exactly once.
It checks cleared delivery queues. Endpoints require a nonempty host string
without whitespace/control characters, at most 255 characters, and integer port
1–65535. `player` is `a` or `b`. Construction returns the runtime or `nil, reason`;
failure attempts the supplied hold and disconnect. The caller must treat a failed
constructor as failure, including any inability to verify the hold.

## Required callbacks and authority

`clock()` supplies finite, nonnegative, monotonic wall time. `host.set_held(held,
reason)` is a dot callback that must independently verify its hold/release request
and return exactly `true`. Preserving user pause and the actual qualified host
interlock belongs to that adapter. Runtime status reports the adapter's latest
verification separately from the control service's requested state.

`read_hello()` must classify current ownership before returning detached metadata.
It returns an object including 32-character lowercase-hex `context_generation`, or
`nil, reason` when not ready. It cannot supply delivery fields, `event`,
`client_nonce`, `commands`, `control` or `reconciliation`. The runtime invokes it
again during admission and command readiness. `metadata_matches(admission,
report)` must return exactly `true` only when the binding's validated admission
matches that current report. The runtime preserves admission fields such as
`mode`; it adds no cartridge policy.

`operation_ready(body, intent_or_nil, control_status)` must return a Boolean,
with an optional deferral reason. It receives detached inputs before preparation
and again before any apply. Readiness may permit read-only classification and
receipt publication while held. Physical `adapter.apply` additionally requires
fresh ordinary execution authority from `control_service`, independently of that
callback. This composition provides no native recovery execution authority.
All preparation/classification/receipt callbacks must themselves be read-only
with respect to the emulated game; only `apply` may perform the intended effect.
The adapter's prepared intent, identity checks, poststate and receipt remain its
responsibility. See [the native executor contract](shared-executor-native-contract.md).

Ordinary authorized `armed`/`PENDING` keeps the oldest command outstanding and
blocks newer commands. It preserves an independently valid run ticket so ordinary
native completion can occur; PENDING grants no ticket or frames. When held,
PENDING cannot authorize recovery frames. An already-proven `after` observation
may be acknowledged while held if the readiness callback admits that read-only
work. Exceptions, ambiguous readback and uncertain durable publication latch
failure and retain the obligation rather than automatically retrying an effect.

## Wire and durable boundaries

The matching server must use the common durable session envelope and these paths:

* HELLO carries the metadata, context generation and nonce-derived operation ID.
  Its response contains `admission.control_binding` with matching `session_id`,
  `admission_epoch`, `context_generation` (32 hex each) and `binding_digest`
  (64 hex). HELLO responses contain an empty command array. An optional recovery
  object can supply the first reconciliation attempt.
* Semantic responses atomically retire the oldest durable operation and stage
  every returned command. Commands arrive flat with their delivery envelope;
  the runtime strips `protocol`, `player`, `admission_epoch`, `session_id`, `seq`,
  `operation_id`, `command_index`, `command_id` and `command_sequence` from the
  stored body, retaining the last two as the journal record identity.
* Transient control requests use `event="control"`, the shared sequence and a
  fresh challenge as `operation_id`. They include the challenge/binding object
  and optional reconciliation evidence. Responses have `commands=[]`, a `control`
  authority packet and an object `recovery` document. Control never calls journal
  `accept_response` or retires a semantic event.
* A configured hold notice contains current protocol/player/epoch/session,
  `event=hold_event`, a bounded reason and `commands=[]`. It can only revoke;
  a notice for a stale session is ignored. A current notice discards socket
  delivery state and requires fresh HELLO.

`reconciliation(recovery_document)` receives a detached object and returns an
evidence object or nil. A Boolean success flag is refused. This callback and the
wire packet do not establish proof: the server must verify local evidence against
its trusted recovery barrier and binding before issuing control authority.

There is one in-flight request. Control has priority at the next request boundary
(default 0.25 seconds, configurable 0.05–0.5). Response timeout defaults to 0.75
seconds (0.05–1). The independent control watchdog is fixed at 2 seconds. With an
empty semantic outbox, the runtime appends durable `{event="sync"}` polls at most
once per sync interval (default 0.5 seconds, configurable 0.05–2). Sync does not
change observation baselines. The caller must continue servicing `step()` while
held; no timer can preempt a blocked callback or an unserviced Lua loop.

## Returned methods and evidence boundary

* `runtime:observe(payloads, baseline)` atomically calls journal `append_many`
  before any send, returning stable IDs or `nil, reason`. HELLO, control, the
  configured hold event and binding-reserved transients are refused before
  journaling; preexisting reserved outbox entries also refuse construction.
  This module adds no transient gameplay sender or detector-baseline inference.
* `runtime:step()` services control/network and the oldest eligible command even
  while held. It returns true or `false, reason` for latched failure.
* `runtime:revoke(reason)` holds, revokes session/binding and clears delivery
  queues without discarding the journal. Disconnect, response timeout, metadata
  change and rejected/malformed replies also require fresh admission. A socket
  close during the final outgoing flush revokes in that same step.
* `runtime:status()` returns a detached snapshot of admission/binding availability,
  pending counts, in-flight request, command diagnostics, control state and hold
  verification. `production_selected`, `host_qualification_proved` and
  `native_recovery_execution` remain false.

`tests/unit/test_rr_runtime_client.py` runs the real shared Lua primitives with
modeled storage backend, host and physical adapter, plus an actual connector
fragmentation/disconnect case. Its generic-protocol case exercises the same durable
handoff, receipt confirmation and configurable hold notice. These tests prove the
composition contract, not a Gen1/RR cartridge implementation, paired live release,
host interlock qualification or production launch. Reproduce with:

```text
python -m pytest tests/unit/test_rr_runtime_client.py -q
python -m ruff check tests/unit/test_rr_runtime_client.py
```
