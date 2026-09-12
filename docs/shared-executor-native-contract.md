# Native participation in the shared command executor

This additive executor contract preserves existing synchronous callbacks and results.
It does not activate an RR runtime, adopt an orphaned native operation, or authorize
emulator frames. `tests/unit/test_command_executor_native.py` runs the real Lua
executor and checked journal against independently simulated native state.

## Trusted command metadata

Every callback now receives a detached metadata object from the validated inbox:

```lua
prepare(body, metadata)
classify(body, intent, metadata)
apply(body, intent, metadata)
receipt(body, intent, observation, metadata)
-- metadata = {command_id = durable_hex32, command_sequence = exact_positive_integer}
```

Existing callbacks may ignore the extra argument. A callback cannot mutate the
metadata received by a later callback. The executor checks the requested command ID
against the inbox and validates the sequence before calling any adapter. It rereads
and checks the identity after preparation publication before allowing an effect.
An ID supplied inside the command body cannot replace this trusted metadata.

RR preparation uses this ID to construct a serializable native reservation and
bind it into its versioned intent before submission. The shared executor does not
invent a native opcode, truncate a durable ID, or hash an old delivery sequence into
a new semantic identity. Native correlation tags remain separate from durable IDs.

## Armed means pending, with no completion or frame grant

In addition to `before`, `after` and `diverged`, a cartridge classifier may return:

```lua
return "armed", {
    schema = "cartridge-specific-armed-evidence-v1",
    command_id = metadata.command_id,
    -- Current verified reservation/ownership/context evidence supplied by binding.
}
```

The evidence must be a JSON object with a nonempty schema (at most 64 characters)
and the exact command ID. This shape check cannot validate physical ownership;
that remains the cartridge classifier's responsibility. An elapsed timer, cached
Boolean, old native sequence or missing party slot cannot prove an armed operation.

The executor returns `false` (not completed) and a distinct diagnostic:

```lua
{outcome="PENDING", pending=true, phase="armed", evidence=...,
 command_id=..., command_sequence=..., native_execution_permitted=false}
```

It neither calls `apply` again nor stores a terminal receipt/ACK event. The prepared
intent stays in the durable inbox. This result is distinct from an uncertain-state
`NACK` diagnostic; neither is a terminal command acknowledgement. Callers must inspect
the outcome rather than treat every false result as the same failure.

After client restart, the classifier must freshly prove the native reservation and
context before reporting `armed`. A changed generation or uncertain owner reports
`diverged` and remains unresolved. A proven poststate reports `after`, allowing the
normal independently validated receipt and atomic receipt/ACK publication. The
executor does not recreate a volatile mailbox lease from a persisted phase string.

The control binding decides whether any native frames may run. During disconnection,
reset/load, or uncertain recovery, this requires the separate paired, bounded recovery
procedure with game input blocked. `PENDING` alone never lifts an execution hold.

Old synchronous adapters retain their previous behavior: prepared-before effects,
verified after-state, receipt persistence, completed receipt replay, and retryable
NACK diagnostics for exceptions or divergent states. Callback return codes from
`apply` still cannot prove success or failure.
