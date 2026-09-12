# P7: stop refusing Explode deaths in the Gen 1 durable runtime

Status: patch ready, applies cleanly. Apply together with the item-2 fold-back or on its own
once the `force_explode` executor (P5) exists; on its own it changes a hard refusal into the
shared engine selecting `force_explode` for the peer, which the current held executor would
leave pending (no write), so sequence it after P5.

## Defect

`server/gen1_faint_runtime.py:126-127` raises `Explode death requires its qualified physical
receipt binding` whenever a run was created with `explode_mode`, while run creation accepts
the option (`server/gen1_run_config.py:114`). A run can be configured into a state the first
death rejects.

## Change

Delete the two lines. The shared engine already decides Explode versus faint per death:
`_propagate_faint` (`server/state.py:2699-2704`) emits `force_explode` when
`explode_mode` is on and `adapter.supports_explode_mode()` is true, and the Gen 1 adapter
returns true (`server/adapters/gen1_rby.py:301-305`). Under the item-2 fold-back the faint
translator hands the engine signal to `_handle_faint` and this branch disappears entirely.

## Verification

`python -m pytest tests/unit/test_gen1_faint_runtime.py -q` after applying; add one case
asserting that a faint under `explode_mode` records a death whose command is
`force_explode` for the peer.
