# Restricted Phase 0 acceptance

The UI owner accepted immutable runtime handoff
`bc880025edc06885defdc3300b247b95b6724dcc` for the early UI migration phases.
This is not complete RBY gameplay/recovery or release approval.

## Evidence checked independently

- Commit tree matches `c683b66eb14a90a24ad7dd6605f0752e23762fe5`.
- All **159 committed-content SHA-256 hashes** match the supplied publication
  manifest. The original raw-source manifest also matches: 104 exact files and
  55 differing only in CRLF/LF representation, with no semantic/binary mismatch.
- The supplied JUnit files report 3,640 full-suite tests (zero failures/errors,
  two Windows symlink-privilege skips) and 643 focused tests without skips.
- Independently reproduced **662 focused tests without skips**, covering Gen3
  state/adapter/rival/Explode behavior, launchers, detached readers, RBY refusal,
  manager hardening, immutable cartridge binding and unavailable publication.
- Required Ruff checks passed and **216 Lua files** parsed in the frozen checkout.
- The three local clean cartridge fixtures were checked against the committed
  admission profiles' SHA-1 and SHA-256 before copying into ignored paths. Initial
  failures from their absence were prerequisite failures, then resolved and rerun.

The accepted read seam is documented in [ui-runtime-handoff.md](../ui-runtime-handoff.md):
`read_rule_state`, `read_runtime_facts`, and the two `read_saved_run` wrappers.
Readers return detached data and do not repair, restore, dispatch, drain queues,
renew liveness, or invent a durable revision. Requested settings survive refusal.

## Restrictions that remain

RBY mutation controls covered by the handoff return 409 before mutation. Their
availability/reasons must be reflected by the UI. The legacy delivery mode is
explicit; pending/recovery/receipt/liveness facts remain unknown where unbound.
The Phase 3 normalized status projection remains UI-owned.

Verified UPR catalog/publication, final-output admission, and unfinished native
operations retain their separate gates. Component tests or this acceptance do
not advertise those operations as available or establish RBY release readiness.

Runtime owners retain core protocol/state/admission and `runtime_boundary.py`.
UI owns status/overlay presentation and templates. Future runtime changes preserve
the accepted accessors and types or publish a new boundary revision.

## Integration work

The isolated `codex/ui-phase0-integration` branch combines the accepted handoff,
later Track A lint fixes/prep, and reviewed mockup commit `121fb1c`.
Only `tools/inject_full_mocks.py` conflicted during the mockup merge. Gen1's
fixture/helper structure and the mockup's pending/PC/low-HP/HOLD behavior are
retained. Live RBY mock injection refuses before HTTP/TCP I/O; it cannot bypass
the new admission/mutation restrictions.

Archived reviewed captures are retained under `tests/fixtures/ui/source/`.
`python tools/capture_ui_fixtures.py` hydrates isolated state and runs the current
serializer to regenerate the display fixtures. It rebuilds real link indexes,
party/box caches and death/pending data, corrects old Gen1 key suffixes using the
cartridge index table, and does not reconstruct absent admission, timestamps,
command queues, or receipts. Rendering attempts to mutate that state fail.
These are reproducible rendering scenarios, not authentic live-admission proof.

The mockup brief's obsolete section 9 points to the approved plan. The original
layout and approved mild refinements remain unchanged in scope.
Browser inspection confirmed the integrated Gen3 reference at 1600 px and Gen1
reference in light theme at 1100 px still render the reviewed pair composition,
battle/at-stake relationship, pending and box zones after fixture regeneration.
The known narrow-layout adjustment remains Phase5 work.

After integration and fixture regeneration, the full unit/integration suite
passed **3665 tests with three skips**. Two require Windows file-symlink privilege
(the junction variants ran); one requires the optional built `slink_red.gb`
companion-component artifact. Canonical-source verification passed **103 checks**
after copying hash-verified ignored build/tool inputs and creating independent
checkouts of the pinned local source repositories. No expected hashes were
changed to accommodate missing inputs, and no ROM/tool binaries were committed.

The runtime owner's CI policy commit `2a8c700` now explicitly separates portable
verification from private/canonical-input gates. UI reviewed and added exactly
28 tracked/synthetic fixture, hydration and inventory cases to the portable
group; no existing deferral classification changed. The isolated portable run
passed **3386 selected tests**, with **308 named deferrals** and
`release_approved: false`. The unchanged local full-release runner remains
authoritative for its complete gate. Public CI is not full RBY validation.
