# Shared frame accounting and evidence references

`server/frame_progress.py` accounts for finite ranges supplied by an independent
generation policy. `initial` binds a physical-context digest and starting frame;
`reserve` records one outstanding typed `VerifiedExecutionWindow`; `complete`
checks exact scope, sequence and consumed steps and retires unused capacity.
`covers` accepts only frames in the consumed interval. An unresolved grant
prevents an overlapping reservation. The active state stays bounded.

The helper owns no clock, emulator, network, eligibility decision, or durable
commit. Callers must verify policy and physical evidence, enforce the grant
lifetime, persist before delivery, and atomically retain completion records.
Zero consumed steps retire a grant without advancing the frame. Replay cannot
reset a deadline or manufacture consumption.

`server/event_reference.py` binds a compact reference to a player, operation and
canonical request digest. `resolve` uses the checked `event_snapshot` API and
returns the stored event, without duplicating its payload in every component.
This is an evidence read, not execution authority.

`server/admission_context.py` compares validated metadata while ignoring only
transport session id, admission epoch and binding digest. Physical identity,
context generation and every other field remain significant. Current connection
ownership must still be checked separately before issuing authority.

The RBY adapters live in `gen1_frame_runtime.py`, `gen1_frame_journal.py`, and
`gen1_observation_provenance.py`. They bind enrollment, preserve original grant
records, validate held returns and source-frame coverage, and stage source and
inventory effects in one commit. Sparse frame returns carry an explicit owned
boundary without inventing a stable inventory while a menu/battle/script owns
it. These adapters remain a private integration API; importing them does not
enable ordinary gameplay or remove recovery holds.

Source/command attribution, the live network policy and the unified native/client
owner are the next integration work. Initial-save after-images must be accounted
for separately from the immutable pre-save enrollment baseline.
