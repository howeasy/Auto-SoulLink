# Isolated native gate evidence

`tools.rr.native_gate` prepares an explicit emulator, ROM, source closure and
fixture in a new private directory. Its CLI prepares and verifies; the separate
`launch_prepared()` API launches only that preparation. Each run/player receives
its own ROM copy, immutable fixture copy, mutable battery seed, configuration,
paths, Lua launcher, logs and result. No newest-save discovery is available.

The runner clears saved tools, Lua sessions, recents, cheats and autoload paths,
disables single-instance forwarding, background controller input, rewind and
firmware discovery, pins 100% speed with no frame skipping,
and starts Windows processes hidden. Cleanup uses captured PID/creation-time
pairs. It never closes other emulators by executable name. Original and immutable
copy hashes are checked again after execution; the runtime config and battery
seed may change. A native manifest requires the exact ROM and every declared
native source input. Additional script dependencies must be explicitly selected.
This is a declared source closure, not a dynamic-loader attestation.

## Script interface

A probe returns `function(ctx)`. `ctx.config` supplies the private paths, bound
identity, `frames`, `probe_options`, fixture metadata and an optional descriptor
snapshot. The descriptor contains `address`, `size`, `hex`, `build_id` and
`manifest_sha256`. `ctx.check(id, actual, expected)` records a structural assertion
and raises on inequality. Scripts put observations in `ctx.report.evidence`.
The wrapper records actual loaded ROM SHA1, emulator version and system and
writes a JSON result even when the probe raises. `ctx.checkpoint(phase)` also
writes incomplete progress to a separate fixed path, preserving observations if
a process deadline intervenes. Progress cannot satisfy result validation.
No result can set release ready.

Select `lua/tests/rr/host_identity.lua` explicitly for actual core observations.
It supplies `ctx.host` and `ctx.main_form` to the probe and records the evidence
under `report.observed.host`. A reviewed fixture containing `host` evidence
requires this dependency and exact runtime comparisons for core type, core
assembly SHA256 and loaded mGBA native-library SHA256. The discovery probe uses
these same host values. Host holds additionally require the explicit
`lua/platform_clock.lua` dependency. Probe options and frame budget are part of
the run identity.

For a battery, the script must apply the sidecar's reviewed `boot_inputs`, check
every `ram_assertions` row, and only then assert `fixture_loaded`. The wrapper
does not claim that copying SaveRAM proves the game loaded it. Screenshots use
constant suffixes beneath `config.result_path`; a screenshot requires independent
visual review in addition to structural checks.

## Historical battery discovery

An unverified historical battery uses purpose `fixture_discovery`, schema
`slink-rr-fixture-candidate-v1`, and `lua/tests/rr/fixture_probe.lua`. It includes
its original provenance and checksum uncertainties. It cannot claim an exact ROM
compatibility binding, `fixture_loaded`, or pass `validate_result()`.
`validate_observation()` accepts only a completed observation that retains
`compatibility = unverified`.

After an assessor reviews the actual boot, scene, own save identity, mode and
party, a separate `slink-rr-fixture-v1` sidecar can bind the same battery bytes to
that exact ROM and named checkpoint. It records the observed result and image
hashes, actual input frame deltas, RAM preconditions, core identity and limits.
Successful Continue does not establish the RR save-section checksum algorithm,
prove all saves compatible, or mean the engine wrote a fresh battery.

## Host and arena observations

The discovery probe reads `MainForm.Emulator` through the running host and records
its exact type, core assembly and loaded mGBA DLL hashes. Optional bounded host
holds require that evidence, exclusive private tools, inactive rewind and an
unowned `BlockFrameAdvance`. They compare constant emulator frames across
`emu.yield()` resumes against `lua/platform_clock.lua`'s monotonic host clock.
The probe releases only its own hold. When initially unpaused, it checks a
subsequent frame step. A separate private-pause option establishes the
already-paused scenario and observes constant frames through live host yields
after release; it never unpauses or waits for a game frame in that branch.
These are component observations, not production
control-service activation or proofs about rewind, load, reset, debugger force,
TAStudio, concurrent tools or every host version.

The arena probe registers callbacks only after battery boot and checkpoint
assertions. Actual mGBA rejects wildcard callbacks; the successor requires the
explicit `writes_exec_v1` lane, full padded write-start address coverage and a
single measured frame. Verified execution holds protect registration and cleanup.
It rejects empty, all-zero and duplicate registration IDs and requires positive
write and execute controls. Read capability is a separate observation, not silently
included in this write-only lane. See [the exact probe contract](ARENA_EXACT_PROBE.md).
Static candidates, runtime traces and unresolved attribution remain distinct.
Zero hits never prove free RAM; setup/trace bounds and an outer process deadline
are mandatory.

`callback_capability_probe.lua` is a separate two-frame exact-address capability
probe. It uses natural game reads, the native signature beacon's writes, and a
frame-loop execute control. A neighboring byte watchpoint records overlap
dispatch behavior without treating its hit count as a required control. It
retains raw callback addresses/values/flags, R15, CPSR and cycle counts when
available, then removes its callbacks. Passing this probe cannot satisfy arena
ownership or wildcard/masked callback coverage. Callback read values are not
assumed to contain the loaded word, and raw R15 is not labeled an instruction PC.

## Verification

```powershell
python -m pytest tests/unit/test_rr_native_gate.py -q
python -m ruff check tools/emulator_sandbox.py tools/rr/native_gate.py tests/unit/test_rr_native_gate.py
```

The unit suite uses temporary synthetic fixtures and controlled Lua/process
providers. It does not launch emulators. Actual probes require explicit paths and
preserve their failed as well as successful artifacts. Their scope is always the
specific ROM, emulator, fixture, script and checkpoint observed.
