# UI presentation contract, revision 1

This freezes the consumer boundary agreed by the UI, Gen1 Readiness, and RR task
owners on 2026-09-05. It is an interface agreement, **not a claim that the new
projection exists or has passed integration tests**. The producer is UI migration
Phase 3. Restricted runtime handoff `bc880025` has now been accepted; its detached
readers are documented in [ui-runtime-handoff.md](ui-runtime-handoff.md). Unknown
or restricted runtime features retain that status until their bindings are ready.

Independent RR context/native-storage work does not depend on a completed board.
RR presentation integration must wait for the tested projection commit and the
authoritative provenance/recovery fields supplied by Gen 1. Neither task should
introduce a competing endpoint or renderer to fill that gap.

## Compatibility

- Keep existing `/api/status` keys and their types. New fields are additive.
- Keep the run API, debug API, TCP behavior, and legacy overlay URLs compatible.
- A field absent from the currently running producer is unavailable; it is not
  evidence of support, readiness, completion, or failure.
- UI builders use detached projections. Rendering must not mutate coordinator
  state, shared cached dictionaries, rules, sessions, or pending operations.

## Per-player capabilities

The Phase 3 field is `players[pid].capabilities[feature]`, with this shape:

```text
supported: boolean | null
requested: boolean | null       # omitted for intrinsic, non-configurable features
ready: boolean | null
effective: boolean | null
reason: string | null
```

- `supported` describes adapter/cartridge feature support established by the
  backend; it does not establish that a required patch is installed or an
  operation is currently safe.
- `requested` reflects the authoritative requested run option. Omission means
  the feature is intrinsic; null means the requested setting is unknown.
- `ready` reflects authoritative readiness evidence for that individual feature.
- `effective` reflects the existing effective backend gate, not a new UI-side
  permission calculation.
- `reason` is the backend's displayable explanation when one is available.
- Null always means unknown. Do not coerce it to false or infer one dimension
  from another.

Resolve these values from each player's admitted cartridge/patch metadata,
adapter, requested settings, and readiness evidence. Do not infer them from
generation alone or a run-global cartridge string. Evaluate features separately:
do not alias rival swap to Explode Mode or every native feature to info-panel
support. Preserve effective ghost/PC-NPC exclusivity where the binding reports it.

Numerical limits and presentation lists are not boolean capability entries.
Continue using existing fields and adapter results until their additive public
projection names are agreed during Phase 3.

## Identity, telemetry, and operations

- Keep exact per-player cartridge identity and persistent Pokemon identity
  separate from effective battle forms/stats and trainer-preparation estimates.
- Preserve existing admission, admission reason, identity error, and observation
  age fields. Recompute age per response; a responsive HTTP server or connected
  socket does not establish a fresh emulator observation.
- Keep paused, stale, disconnected, rejected, and unknown states distinct.
- Durable operation/recovery metadata remains a separate projection. Transport
  receipt, delivery, game application, verified completion, and durable ACK are
  different events. `queued`, `save_failed`, or capability readiness cannot
  establish completion or permission to resume gameplay.
- Final provenance and durable-lifecycle field names await the authoritative
  Gen 1 handoff. Preserve unknown rather than manufacturing substitutes.
- Keep raw ROM pointers, opcodes, and party blobs internal to the runtime.

Phase 3 also adds mon keys, held-item names, and pending-capture names/sprite HTML
through existing presentation adapters. Display text must be escaped at its
output context; only trusted renderer-generated HTML fields may bypass escaping.

## Broadcast consumer boundary

Every new saved OBS source has its own explicit run/player binding and stable
source URL. Rendering and fragment polling resolve that binding, never a global
pin fallback. Existing `/stream/` URLs retain their compatibility behavior.
Automatic scene-change rules select their source run independently.

The shared preset components consume this same projection across games. Missing
data stays unavailable; absent capabilities must not become empty or fabricated
panels. Existing preset contents and controls remain covered by regression tests.
