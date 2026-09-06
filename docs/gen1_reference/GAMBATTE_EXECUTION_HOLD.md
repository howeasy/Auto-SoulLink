# Pinned Gambatte execution-hold component

The final explicit-profile `lua/platform_execution.lua` passed 18 actual-host
cases: Red, Blue and Yellow, each with the lifecycle, emergency re-hold and
stopped/reloaded-owner scenarios, both initially paused and initially unpaused.
The pytest run completed in 102.96 seconds with no failures, skips or deselection.

The module source SHA-256 is
`14e981d42872294e555a09d603fdb74afb55cdb9aa3cea7d7eb665dbe47b1fea`.
The [observation manifest](gambatte_execution_observations.json) records the
raw and LF-normalized source hashes, all 18 cases, process/thread identities, constructor outcomes,
actual held-yield periods, status readback, and input/result/log hashes. Its
SHA-256 is `da794e82e11be44d77a6a5b11e7a9936cce97db9470ac3bde6a63f8ba0e4fd5d`.
Full per-case artifacts remain in the recorded worktree-relative `.cache` paths.
No ROM, save, JAR or executable bytes are included in that manifest.

## What was exercised

| Mode | Cases | Evidence |
|---|---:|---|
| Lifecycle | 6 | Same-thread second owners, repeated tokens and module reloads refuse; the lease stays exclusive while unheld, held and released; healthy close permits replacement; a stale owner cannot affect it. |
| Emergency re-hold | 6 | A controlled private flag clear is detected; re-hold verifies the physical stop; failure remains latched and release/close refuse. |
| Stopped/reloaded owner | 6 | Stopping a separate owner LuaFile retains the flag and constant frame count; a replacement refuses the abandoned hold. |

Every held period lasted at least 250 ms, performed actual `emu.yield()` calls on
the original UI thread, and retained the exact frame count and pause state.
Initially paused cases change pause only as explicit private fixture setup.
The actuator itself never changes user pause. Healthy unpaused lifecycle cases
also advance one ordinary frame after release/close.

These use the common probe and owner-helper implementations in
`lua/tests/platform_execution_probe.lua` and
`lua/tests/platform_execution_owner_helper.lua`. They preserve the shared
ownership, pause, emergency and stopped-owner cases from the RR probe, with an
explicit profile selection and memory domain for the cartridge-header check.
The wrapper and Python runner supply the Gen1 fixture and identity evidence.

## Scope and refused discovery attempt

The actual wrapper type is
`BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy`, with one `libgambatte.DLL`.
The native library SHA-256 is
`320d615454af44bbe586bcb53afa14a64e834a4156c0d4a731d59cda30ce0722`.
The pinned 2.11.1 executable and core assembly match the shared contract.

The first private candidate correctly refused construction while rewind was
enabled, leaving the flag and frame count unchanged. That failure is retained
separately in the manifest. Positive runs disable rewind only in a private
configuration copy. The constructor's rewind refusal remains intact, and the
user's configuration and SaveRAM are never changed by the harness.

This proves only the exclusive between-frame hold actuator. General reset,
load-state, rewind/debugger interception, unheld-owner garbage collection,
native recovery execution, and full execution safety remain unavailable. No
production client selects the adapter. Setting a flag between frames does not
prove interruption of an already-running instruction or frame. A re-hold cannot
undo a frame that escaped before the stop was re-established.

## Reproduction

The complete dependency-closed Gen1 harness is published at
[0465438](https://github.com/howeasy/Auto-SoulLink/tree/0465438c3ab9464034f498f49c871d2d554c7274).
Use that checkout for the live commands below. This separate shared profile
commit contains only the adapter, modeled tests, contract and recorded evidence.


With the exact pinned host, native DLL and canonical local RBY inputs available:

```text
python tools/run_gen1_execution_hold.py --variant yellow --mode lifecycle
python tools/run_gen1_execution_hold.py --variant yellow --mode lifecycle --paused
python tools/run_gen1_execution_hold.py --variant yellow --mode external_clear
python tools/run_gen1_execution_hold.py --variant yellow --mode stopped_reload
```

The complete matrix is `tests/live/test_gen1_execution_hold.py`, invoked with
`SLINK_LIVE=1`. Each process receives a distinct input, generated script, result
name, configuration and SaveRAM directory, with a 60-second external deadline.
All sources and inputs are hashed before execution and checked again afterward.
Failed and partial results are retained. Fixture boot uses actual CONTINUE and
overworld movement before the host-control probe starts.
