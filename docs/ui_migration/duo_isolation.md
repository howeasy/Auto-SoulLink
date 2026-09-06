# Shared duo runner isolation

Gen 1 and RR released this bounded shared-harness correction to the UI task. `tools/emulator_sandbox.py` is the inspected helper from RR commit `e95902eceb6bc30abf3d90dd0badfaa4b41fac81`; the unrelated RR probe work was not imported.

## Changes

Each invocation creates a fresh run directory under `patch/build`, with separate `duo_a` and `duo_b` roots. Configuration, staged ROM/state inputs, SaveRAM, Lua stubs, result files and synchronization files stay inside those roots. Both players are prepared and input identities rechecked before either emulator starts. Relative emulator arguments avoid the BizHawk command-line issue with spaces; Lua strings use the shared encoder.

All configured emulator paths are rebased. Saved tools, autoloads and recent paths are removed from the copy; the user's configuration is unchanged. Gen 3 savestate sync settings must identify mGBA, and that core/settings combination is retained. Existing Gen 1/2 battery seeding and Gen 1 Player B's saved-identity preparation remain before launch. This is isolation and format validation, not a ROM/savestate provenance certification.

The runner hashes source ROMs, fixtures, configuration and original SaveRAM files/backups. It checks those hashes and the original save-directory file sets again during cleanup. Input changes fail the run. `input-manifest.json` and `input-verification.json` retain the evidence. Gen 1 default wire-v1 remains selected; this does not activate the unpublished configured durable route.

Process ownership is exact PID plus creation time, using the shared helper's descendant capture and termination. The server's parent log handle closes after spawn. Emulator/server handles must finish before success. Process or input-verification failures remain failures. Successful results and verification files are retained under `patch/build/duo-results`; temporary-directory locks are separately reported in `cleanup.json` with the retained path, rather than discarding the result evidence.

## Evidence

- Eight isolated unit cases cover disjoint invocations, stale markers, unknown core rejection, changed inputs/save directories, parent handle closure, partial launch cleanup, PID reuse and locked artifact directories. Existing Gen 1/2 seeding tests remain covered. Generated Lua stubs are compile-checked.
- Full unit/integration suite: **3905 passed, 2 skipped**. Portable selection: **3599 passed, 308 explicit deferrals**. Ruff is clean.
- A live Red/Blue natural-capture smoke test passed in **23.51 seconds** after the artifact-lock handling correction. It checked **74 input files and two original save directories**, all unchanged.
- Full `SLINK_E2E=1 pytest tests/e2e/test_duo_gen1.py -q -rA`: **15 passed, 30 failed**, **no skips or deselections**, **1150.27 seconds**.
- The passing scenarios are playthrough, deadzone and dupes, across Red/Blue, Blue/Yellow, Red/Red, Yellow/Red and Yellow/Yellow.
- Every failing case reports HTTP409 from `/api/debug/set_pokeballs`, with `reason_code=rby_operation_interface_unavailable`. Manual-seeded scenarios remain outstanding until Gen 1 supplies its qualified operation/fixture initialization boundary. No exception to that guard was introduced.
- All **135 recorded process identities** had exited after the full run. Natural-capture passes do not certify storage recovery, native trade or the new durable service; retained server logs include existing storage/reconciliation warnings for owner review.

Local evidence is under `.cache/ui-gen1-full-e2e.log`, `.cache/ui-gen1-full-e2e-summary.json`, `.cache/ui-gen1-full-e2e-source.json`, and the per-invocation directories/results. Private ROM/save artifacts are not committed.

The Gen 3 E2E suite still lacks an owner-qualified ROM/savestate provenance pair. Its referenced savestates report the installed BizHawk 2.11.1 version, but version agreement alone is not qualification. The root ROM is only an identified RR audit baseline; no full Gen 3 E2E verdict is claimed. Verified Gen 1 randomizer publication is a separate outstanding dependency.
