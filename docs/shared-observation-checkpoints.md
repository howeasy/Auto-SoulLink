# Shared observation checkpoints

`lua/observation_stream.lua` sequences one durable checkpoint at a time on the
existing client journal. Construct it with `journal`, `key`, `event`, and four
callbacks:

- `owned()` returns the current physical context as a JSON object.
- `seed(baseline)` returns an acknowledged `{sequence, operation_id, observation}`
  cursor, or nil while enrollment is incomplete.
- `sample(previous)` returns a new JSON observation, or nil when none is ready.
- `verify(observation)` returns true only while that observation still belongs to
  the owned checkpoint. It runs before and after publication.

Call `step()` only from the binding's serialized owned service. It publishes
`{event, payload={sequence, previous_operation_id, observation}}` with a queued
baseline atomically. No subsequent sample is taken while that event is pending.
Use the instance's `acknowledge_event` callback with `client_journal`, or compose
`observation_stream.acknowledge(key, event, payload, operation_id, baseline)` with
other completion callbacks. The journal verifies the exact oldest operation
before invoking the callback. A matching ACK stores the new cursor atomically.

The helper detaches callback inputs/results, captures callback references, checks
context around callbacks and publication, and refuses a callback that changed
the journal baseline. A storage failure must hold the service; reconstruct it
over a reopened checked journal to resolve an uncertain publication. Nothing
here grants frames, performs memory writes, repairs context or infers events.

`server/keyed_inventory.py:compare(before, after, limit=...)` compares bounded
lists of already validated dictionaries with unique printable `key` strings.
It returns detached, deterministically ordered `added`, `removed`, and `matched`
rows. Each match contains `key`, `before` and `after`. The caller establishes
physical scope, completeness, capacity and generation-specific record validity.
Key equality does not itself establish logical identity; key changes are not
automatically classified as evolution, trades or acquisitions.

RBY uses these helpers for complete held inventory checkpoints. Its codecs,
storage geometry, frame rules and journal component remain generation-owned.
Other generations need their own evidence and rule bindings before activation.
