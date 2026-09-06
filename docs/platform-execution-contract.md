# Inactive pinned execution-hold adapter

`lua/platform_execution.lua` extracts the independently proved MainForm hold
mechanism into a reusable actuator. Its scoped actual-host ownership, pause,
emergency-hold and stopped-held-script checks are now recorded in
[the private probe evidence](rr_reference/PLATFORM_EXECUTION_PROBE.md). Earlier
manual MainForm/arena probes remain separate supporting evidence.
No RR, RBY, shared state, UI or existing client selects it automatically.

The initial capability is only
`bizhawk-2.11.1-mgba-exclusive-hold-v1`. The module checks actual installed
executable/core/native files against explicit caller-selected pins. Other cores,
host versions or builds are refused. A shared interface does not imply an
unperformed Gambatte/RBY proof.

## Selection and API

The caller must provide a32-character lowercase hexadecimal `owner_id`,
`exclusive_ownership="emulator_process"`, `control_context="between_frames"`,
and an `expected_host` containing every field returned by `supported_profile()`.
These declarations are required but are not accepted as sufficient proof by
themselves: the module checks live host identity, process ownership, UI surfaces,
rewind state, flag/pause readback, and the original core object.

```lua
local Execution = require("platform_execution")
local actuator, reason = Execution.new({
    owner_id = caller_owned_nonce,
    exclusive_ownership = "emulator_process",
    control_context = "between_frames",
    expected_host = caller_selected_and_reviewed_host_pins,
})
```

`new` claims an exclusive process lease but does not alter emulation's hold flag.
It refuses an already-set `BlockFrameAdvance`; a replacement must never adopt
such a flag merely because a previous Lua owner disappeared. Actual run29
verified this refusal after stopping and reloading a separate owner LuaFile.

| Method | Contract |
|---|---|
| `set_held(true, reason)` | Set/reassert the independent flag and verify readback; do not modify user pause. |
| `set_held(false, reason)` | Release only this healthy instance's verified hold; refuse failed/foreign ownership. |
| `verify()` | Recheck the lease, original host/core, permitted tools, rewind state, hold readback, and constant held-frame count. |
| `yield_held()` | Service `emu.yield()` while held and verify before/after; no frame-advance call. |
| `status()` | Return copied diagnostics, actual flag/pause readback, failure state and separately qualified physical-stop verification. |
| `close()` | Require healthy, explicitly released state, then release the lease and dispose the handle. Never release a hold as cleanup. |

Methods use dot-call semantics, matching `control_service.lua`'s `host.set_held`
interface. Invalid arguments return false. An ownership/actuator fault latches
failure and blocks future releases. This is an actuator; it does not grant paired
execution authority or decide whether a game command is safe.

## Exact pinned scope

| Evidence | Required value |
|---|---|
| Host | BizHawk2.11.1 |
| Executable SHA-256 | `f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd` |
| Core type | `BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk` |
| Core assembly SHA-256 | `444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5` |
| Single loaded `mgba.dll` SHA-256 | `ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1` |

The constructor hashes actual process/core/module files and requires one
MainForm and one LuaConsole, without other open tool forms. Subsequent control
calls recheck the original MainForm/core reference, UI-thread access, disposal,
tools and rewind state. Initial file hashes are not repeatedly recomputed in
every control-loop iteration. The supported process assumes those loaded
assemblies/modules are not replaced out of band.

Only between-frame invocation from the exclusive control loop is supported.
There is no claim that setting the flag interrupts an instruction or an already
running frame. Do not call this API from a bus callback and treat it as immediate
CPU interruption.

## Process ownership, including same-thread callers

The module retains a named `System.Threading.Semaphore(1,1)` for its full
lifetime. Its name is derived from the actual process ID:
`Local\SLink.PlatformExecution.v1.<pid>`. Callers cannot choose a different
lock path/name and thereby claim a second owner for the same host.

This is not a Mutex. A semaphore is not reentrant by OS thread: a second Lua
caller on the same UI thread must fail a nonblocking `WaitOne(0)`, even when it
reuses the first caller's owner token or reloads the Lua module. Construction
checks a second same-name handle, and subsequent verification checks that another
handle cannot acquire the lease. The lease remains acquired while the adapter's
hold flag is false; permission to run frames does not transfer actuator ownership.

This mechanism coordinates participating owners. It is not a security boundary
against arbitrary external code deliberately changing the semaphore count or
forcing the emulator through other APIs. Such interference invalidates the
proved scope and must not be hidden by a success status.

The adapter has no exit callback or finalizer that clears `BlockFrameAdvance`.
Healthy cleanup is explicit: first release the owned hold, then close. Closing a
held/failed instance is refused. On failure, the handle remains retained by the
adapter rather than being silently released. The caller must keep the object
alive while it owns the process. Host/script shutdown and managed GC may affect
handle lifetime; a remaining pre-existing host flag still cannot be adopted by
a replacement. Stopped-while-held behavior passed the narrow actual run29;
unheld-owner garbage-collection behavior remains unproved.

## Failure after release and emergency re-hold

A failure can occur after the setter clears the real flag but before bookkeeping
finishes. An internal `held=true` value is therefore not physical-stop evidence.
The adapter attempts an emergency **hold only** when all of the following remain
valid: its process lease, the original host/core, and exclusive tool/rewind scope.
It reasserts `BlockFrameAdvance=true` if needed and verifies flag, pause and frame
readback. It never clears a flag through this emergency path.

The original error remains latched. A failed instance may accept
`set_held(true, reason)` as another emergency-stop attempt, so the shared control
service's error handler can stop a failed release. It still refuses every
release and close. Reacquiring a stop does not undo any frames that already ran;
it cannot stand in for reconciliation or state rollback.

If the scope/lease or setter cannot be verified, `physical_stop_verified=false`
and `emergency_error` remain explicit. `host_blocked` reports the actual flag
separately from internal state. A failed adapter with `host_blocked=false` is an
unsupported actuator failure, not a fail-closed success. The caller must surface
that failure and cannot claim that gameplay is paused.

User pause is never written. A user pause change during a hold is observed and
preserved; releasing the adapter's flag does not undo it. Each setter also checks
that its own operation did not change the pause property.

## Capabilities deliberately unavailable

The status explicitly keeps these false:

- Reset and load-state control/interlocks;
- Rewind and debugger control/interlocks;
- Native recovery execution;
- Full execution safety;
- Production client selection.

Checking for an already active rewind/tool conflict does not prove interception
of every future reset/load/debugger path. Admission, identity continuity,
policy scheduling and native mutation prerequisites remain separate work.

## Tests, actual private-host validation and remaining limits

`tests/unit/test_platform_execution.py` executes the actual Lua module with
modeled .NET/UI/OS surfaces. It includes same-thread second-owner and same-token
refusal, independent module reloads, bad semaphore exclusion, identity/tool/core
conflicts, both pause states, pause changes during holds, pre-existing flags,
stale owners, lost flags/frames, setter/readback failure, post-release failure,
unverifiable emergency-stop failure, and actual `control_service.lua` error-path
integration. These modeled tests alone do not prove the real named semaphore
works through the installed NLua/.NET binding; actual runs21/23/24/29 supply
the narrow physical evidence separately.

```powershell
python -m pytest tests/unit/test_platform_execution.py tests/unit/test_control_service.py -q
python -m ruff check tests/unit/test_platform_execution.py
```

Current result: **31 adapter tests;61 combined tests passed**, Ruff clean.

The following private checks have now run against the pinned actual binaries and
freshly attributed fixture. Exact source/result/execution hashes and the retained
failed attempts are linked above; the adapter code itself did not change:

1. Load this exact module with caller-supplied pins and a new owner nonce; record
   process ID, UI thread ID, module/source hashes and semaphore name.
2. Prove a different owner, a replayed owner token and a second module instance
   on the **same actual UI thread** are refused while the lease is retained,
   including while `BlockFrameAdvance=false`.
3. Acquire a hold, service bounded real `emu.yield()` calls, and prove frame
   count remains constant. Verify pause preservation first unpaused, then in a
   separately controlled private paused scenario. No production user is unpaused.
4. Verify closing while held refuses without clearing the flag. Verify explicit
   release/close and successful replacement ownership only after healthy cleanup.
5. In a separately labeled private fault probe, clear the owned flag under the
   retained lease and verify emergency re-hold/readback, latched failure and
   refusal of release. End that private host with the failed owner held rather
   than inventing a cleanup authority. Real post-setter exceptions are not yet
   induced; their current evidence is the modeled test only.
6. Check stopped-script/reload behavior with a retained flag in an isolated
   process. A replacement must refuse it; do not silently clean up an abandoned
   hold to make the test continue. Process teardown is the bound for this case.

Runs21/23 cover the constructor/lease, pause and healthy lifecycle checks; run24
covers the deliberately cleared flag; run29 covers stopping and reloading a
separate owner LuaFile. Failed orchestration attempts25–28 remain failures.
The success does not establish unheld garbage collection or arbitrary other-script
cooperation. No production binding has selected the adapter.

Use independent hard wall deadlines and preserve partial/failed artifacts. These
checks validate only this actuator and lease. Reset/load/rewind/debugger barriers
and full paired execution remain unavailable until their own evidence exists.
