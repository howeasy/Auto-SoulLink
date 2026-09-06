# RR reset/load interlock: pinned source feasibility

**No general reset/load/rewind interlock is enabled.** The pinned host offers
useful interception points, but post-load/post-frame callbacks and the existing
execution-hold adapter do not cover every restoration or core-execution path.
`platform_execution.lua` remains unchanged while its separate validation runs.

The required ordering is:

```text
revoke paired execution authority
acquire and verify the independent execution hold
persist the transition/uncertainty boundary while held
perform the explicitly controlled restore/reset
keep the hold on both success and failure
validate the new context and reconcile before any restored native instruction
```

This requirement is about preventing the first resumed native effect, including
a restored BUSY command. Pausing after a frame, detecting a changed frame count,
or clearing a mailbox afterward is insufficient.

Local revocation and the verified hold come before persistence, which can fail
or yield. A persistence failure retains the hold. Controlled reset/load may
proceed only after both the hold and persisted transition are established.

## Exact host ordering

All host source below is pinned to BizHawk2.11.1 commit
`bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5`; mGBA is
`94b1578f8545d8ad17bb4036dba908612d5731e2`. Installed binary bindings are in
[BIZHAWK_MGBA_CALLBACKS.md](BIZHAWK_MGBA_CALLBACKS.md).

### Ordinary loop and the too-late preframe hook

In [MainForm.ProgramRunLoop](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/MainForm.cs#L946):
input/hotkey processing occurs at946, controller chaining at1000,
`ResumeScripts(false)` at1005, external-tool general updates at1008, and
`StepRunLoop_Core` at1010. Windows messages are processed afterward.

Inside `StepRunLoop_Core`:

1. Rewind restoration is attempted at2920.
2. `BlockFrameAdvance` is checked at2927.
3. Tool preframe updates occur at2944–2955.
4. The actual core's `FrameAdvance` is called at3020.

LuaConsole's preframe update invokes Lua `onframestart` callbacks. There is no
second hold check between that event and3020. Setting the flag from that event
does not retract the already-admitted frame. Execution-address callbacks are
even later, within core execution; they cannot provide an immediate CPU-stop
barrier by changing a flag read only by the outer loop.

An `emu.yield()` control loop has an earlier observation opportunity than
`onframestart`, but it is followed by other script/tool callbacks and execution
paths. That opportunity alone is not an exclusive execution broker.

### Normal named/quick load

[MainForm.LoadState](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/MainForm.cs#L4091)
calls `SavestateFile.Load` at4096, then invokes `SavestateLoaded` at4106 and
Lua `CallStateLoadCallbacks` at4110. Thus a synchronous event handler can set a
hold before the next **ordinary outer-loop** frame after a successful UI load.
It cannot claim to run before restoration itself, and a load initiated inside
an already-admitted preframe callback retains the late-check problem above.

`LoadQuickSave` has the cancellable `QuicksaveLoad` event before loading
(4137–4143). It can veto a quickload before the core is touched. It does not
intercept generic named, API, memory-state, rewind or direct-core restoration.

### Failed load can already have restored the core

[SavestateFile.Load](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/savestates/SavestateFile.cs#L200)
loads the core at204. It can subsequently return false after movie metadata
handling at216–219, or throw during UserData parsing at243. MainForm then has
no successful-load callback to invoke. `savestate.load()` catches exceptions
and returns false. **False does not prove the old core state remained intact.**

This is why the hold must be established before an owned load attempt and kept
on every exit path. A post-load event alone cannot close the failure boundary.

### Direct restoration bypasses the load event

| Path | Exact source behavior |
|---|---|
| `MemorySaveStateApi.LoadCoreStateFromMemory` | Calls `IStatable.LoadStateBinary` directly at31, catches errors, and has no MainForm/Lua load notification. |
| `Zwinder.Rewind` | Direct state loads at76/84. |
| `ZeldaWinder.Rewind` | Direct state loads at240/244/253. |
| MainForm future-frame preview | Direct extra `Emulator.FrameAdvance` calls at3089, then a direct state restore at3097; no ordinary hold recheck or load callback. |
| Tools/debugger/other .NET callers | Can hold an `IStatable`/`IEmulator` reference and bypass MainForm routing entirely. This interface is not a security boundary. |

Rewind runs before the outer hold gate and intentionally may advance after
restoring to refresh a framebuffer. Consequently a held frame counter can still
change due to restoration, and a late pause may already follow a restored native
effect. The pre-existing frame hold does not itself disable rewind.

`PreFutureFrameCallback` and nonzero preview behavior must be explicitly excluded
from any claimed exclusive scope. Checking only visible forms does not detect
that callback or extra Lua execution inside the already open LuaConsole.

## mGBA state load and power/reset

[MGBAHawk.LoadStateBinary](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/GBA/MGBAHawk.IStatable.cs#L37)
calls `BizPutState`, then restores host frame/cycle counters. The native bridge
calls `mCoreLoadStateNamed`; the GBA implementation deserializes CPU registers,
prefetch state, timing and RAM. The reviewed load path does not call the normal
frame/CPU-run routine. This supports a **controlled pre-held load experiment**,
not a claim that all entry points are intercepted or every failure is atomic.

[MGBAHawk.FrameAdvance](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/GBA/MGBAHawk.IEmulator.cs#L15)
handles the `Power` controller button by calling `BizReset` and rewiring memory
pointers, then proceeds into `BizAdvance`/`BizSubAdvance` **in the same call**.
There is no Lua boundary between reset and those CPU instructions. The controller
definition has Power, not a Reset button. MainForm's hard-reset action queues
Power; soft reset is unavailable for this controller. An in-game reset key chord
is another input-driven path requiring its own explicit policy/proof.

Power does not call `ResetCounters` here; the host frame counter increments
normally. A monotonically increasing frame count is not a reset detector.

MainForm's **Reboot Core** is different: it routes through `LoadRom`, replaces the
core at3712–3713, and restarts tools at3799. Manual reboot normally stops/recreates
Lua files. `client.reboot_core()` sets the special `IsRebootingCore` flag;
LuaConsole.Restart then reinjects dependencies and returns without rebuilding the
Lua environment (221–225). That is a possible controlled route to investigate.
It still needs an explicit lease-preserving new-core transition and renewed
admission; the current actuator deliberately rejects replacement core identity.
It must not be taught to adopt an arbitrary pre-existing hold.

## Feasibility without patching the host binary

A limited controlled route is feasible from source, but a complete admitted-run
interlock is **not yet proved by the existing stock Lua hooks**.

| Proposed measure | Feasible scope | Remaining limitation |
|---|---|---|
| Pre-held explicit `savestate.load` | Holds before both successful and late-failed loads, if invoked between frames under exclusive ownership. | Does not intercept manual or direct API loads elsewhere; must retain uncertainty on false/error. |
| `QuicksaveLoad` veto | Cancels quick slots before restoration. | Other restoration routes remain. |
| An exact reviewed `IControlMainform` tool | The supported host interface can own savestate, rewind and reboot routing before their default actions. Generic LoadState, quick/named dialogs and .State drag-drop ultimately route through these MainForm methods. | Requires a separately reviewed tool/owner scope, lifecycle and callback ordering. Current actuator allows only MainForm/LuaConsole. Does not wrap arbitrary IStatable/IEmulator calls. |
| Disable rewind / own `WantsToControlRewind` | Can prevent stock rewind restoration when actually enforced before the call. | A read-only check of Active is not prevention; UI/config reenabling and tool-controlled rewind require coverage. |
| Disable menu items | Can remove normal click routes. | Hotkey dispatch calls reset/load methods directly; disabled menu state is not consulted. |
| Disable drag-drop and clear relevant hotkeys | Can reduce UI routes as an explicitly verified scope restriction. | Needs tests for context menus, alternate shortcuts, config reload, ROM reboot, IPC and restoration of user settings; not an arbitrary-code barrier. |
| Inspect queued Power/reset-chord input before frame admission | The controller chain runs before yielding scripts. | Must cover controller/movie/script overrides and prevent changes after the inspection; postframe detection is too late. |
| Detect extra scripts/tools before allowing a frame | Necessary for exclusive scope. | A script/tool may execute later in the same host iteration or directly advance the core before the next check. Detection alone is insufficient. |

The supported `IControlMainform` interface exposes `WantsToControlSavestates`,
`WantsToControlRewind` and `WantsToControlReboot`. It does not provide a universal
pre-call hook around every `IStatable.LoadStateBinary` or `IEmulator.FrameAdvance`.
A future external control tool could mediate normal UI operations without
patching EmuHawk, but must demonstrate complete coverage of its **explicitly
restricted** host surface. That is additional implementation/validation, not a
capability inferred from this investigation.

### Extra scripts and the REPL must not be silently trusted

LuaConsole exposes public LoadLuaFile/RemoveLuaFile by exact path. Its internal
LuaImp field is private. `LuaLibraries.ResumeScripts` iterates a live filtered
ScriptList rather than a snapshot. Mutating that list from a currently resumed
observer can invalidate the enumerator; source-backed private tests must queue
such public UI methods or carefully separate stopping from list removal.

The console REPL executes strings immediately via `ExecuteString` and forbids
yielding, not state/native API access in general. An additional script can also
call memory-state/direct-core APIs. Merely allowing the LuaConsole form therefore
does not establish that only the SLink owner can execute code. A production scope
must explicitly prevent or mediate those execution surfaces before their first
run, not assume new scripts honor the SLink semaphore.

Likewise, `GeneralUpdateActiveExtTools` occurs after the yielding control script,
and preframe callbacks occur after the hold gate. A purported "last check" in an
ordinary Lua loop does not cover those later execution opportunities. No broad UI
changes are implemented here; the remaining bypasses stay explicit.

## Executable safe private probe plan

Use disposable private copies, exact host/ROM/fixture/source hashes, an already
validated execution owner, bounded wall time and read/execute controls. The
native marker should be **BUSY OP_PING**, not a party/storage mutation. Its only
intended command effect is the harmless native receipt, so a deliberately exposed
failure case cannot corrupt an original party/save. Never inject this marker into
a live user's process.

Prepare a valid private state with BUSY PING while a hold is already verified.
Capture its full mailbox bytes/reservation, ROM identity and core-state hash.
Build a separate late-failure copy using the pure helper:

```python
from tools.rr.reset_probe_fixture import failed_after_restore_copy

bad_state_bytes, manifest = failed_after_restore_copy(valid_private_busy_state_bytes)
# Only the validated private runner writes these bytes to its disposable directory.
```

The helper changes only `UserData.txt` to malformed JSON and preserves all other
decompressed ZIP members, including Core.bin and SyncSettings.json. The exact
pinned `BinaryStateLump` names that text member, and ConfigService.LoadWithType
deserializes it after core restoration. The helper does not claim that its input
ROM or BUSY marker was verified; the producer/runner must do that independently.
It never loads a state or launches an emulator.

Run separate, clearly labeled cases:

1. **Controlled valid load under an existing hold.** Register the synchronous
   load notification and independently verified native execution/receipt
   controls. Hold before `savestate.load`, keep it throughout, and observe the
   restored BUSY marker without dispatch/ACK or any game-frame progress across
   real held yields. Do not let an event handler release the hold.
2. **Controlled late-failed load under that hold.** Load the malformed-UserData
   copy. Expected evidence: false/error result, restored BUSY core bytes, no
   successful-load notification, no native dispatch while held. This directly
   tests failure-after-restore rather than equating false with "unchanged".
3. **Post-load notification alone, disposable negative control.** Only after
   root review, use harmless PING to demonstrate the specific late-failure gap.
   A callback miss plus subsequent receipt is a reproduced unsafe ordering, not
   a passing interlock. Preserve the failed artifact and end the private host.
4. **Rewind and future-frame routes.** First prove they bypass ordinary load
   callbacks and identify exact timing. Do not expose a real storage command.
   Do not enable these in production or infer that an outer hold prevents the
   restoration itself.
5. **Controlled reboot/power.** Separate manual Reboot Core, controlled
   `client.reboot_core`, queued Power, and any supported reset chord. Observe
   core/Lua/lease identity, native callback survival and first-execution ordering.
   A replacement core cannot inherit old paired authority automatically.

For any event-only experiment, a frame-entry watcher is an observation, not the
interlock. A snapshot of BUSY remaining intact is also insufficient without
working positive controls, bounded execution observations and pre-held ordering.
Keep the owner held at teardown when continuity is invalid; do not reset or
clear native uncertainty merely to finish the test.

## Evidence and implementation status

The source analysis now has a runnable, inactive private experiment:
`lua/tests/rr/controlled_load_probe.lua`, `tools/rr/controlled_load.py` and their
focused modeled tests. The existing fault-copy helper accepts exactly one
`Core.bin` or `Core.bin.zst`; it never changes that member. No controlled-load
emulator experiment has yet run, and no production interlock or broad UI
restriction was activated.

### Bounded producer/consumer workflow

The validation owner runs each case in its own disposable process using the
reviewed frozen03 **battery**, not an auto-loaded experimental state. Required
ROM SHA-256 is `3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301`;
battery SHA-256 is `c8eb84b434b80dc5c7cac7b84a9a8106d78088078d277a860fb6e4b067b43d13`.
The existing native gate binds the installed host, core, fixture and explicit
source inputs. Include `host_identity.lua`, `platform_execution.lua`,
`platform_clock.lua`, `mailbox.lua`, and the new probe in the source snapshot.
Keep the actual adapter hash and native manifest inputs unchanged during a run.

All three modes require `frames=1659`, the reviewed 1656 boot frames, a fresh
32-hex `owner_id`, exact `expected_host` from the pinned adapter profile, and
`hold_ms=250` (accepted bound 100..1000). The host must be unpaused; no movie,
future-frame callback, rewind, conflicting form or pre-existing hold is allowed.
The private runner must load only the wrapper/probe script and retain an outer
100-second process deadline, polled in short intervals with progress artifacts.
The probe never changes user pause. The forward-frame budget counts actual calls
independently from the restored frame counter.

1. Set `probe_options.mode="produce"`. The probe claims/holds its process before
   registering exact execution watchers at `0x0800051A` and frozen03 native frame
   entry `0x08378F70` (eight-byte anchor `f0b5b84bb84c89b0`). It posts only actual
   mailbox `OP_PING`, releases its hold for one positive-control frame, re-holds,
   and requires both execution controls plus the exact native descriptor receipt.
   Two extra idle frames distinguish the saved and consumer frame anchors. It
   posts a second PING while held, saves only `results/busy_ping.State`, and records
   full 64-byte BUSY header/reservation, frame and file hash. It requires no
   native dispatch while saving/observing and exits held without polling that PING.
   Include every `PRODUCER_ASSERTIONS` ID from `tools.rr.controlled_load` as required
   native-gate assertions, in addition to the gate's built-in fixture/host checks.
2. Review the producer's result and exact probe hash, then freeze the two copies:

   ```powershell
   python -m tools.rr.controlled_load --prepared <private-producer/prepared.json> --probe-sha256 <reviewed-sha256>
   ```

   The helper revalidates the gate/source/result binding and frozen03 identity.
   It refuses incomplete assertions, non-PING BUSY bytes, changed state bytes,
   duplicate/ambiguous ZIP members, wrong BizHawk version, or non-exact typed
   mGBA/SkipBios sync settings. It creates a new private
   `results/controlled_load_artifacts` directory containing `busy_ping.State`,
   `busy_late_failure.State` and `experiment.json`. Every non-UserData member must
   remain byte-identical; the core and raw sync-member hashes are recorded.
3. Prepare separate `mode="valid"` and `mode="late_failure"` consumers, each still
   admitted against the same reviewed battery. In a private staged source root,
   copy the frozen state artifacts beneath `probe_artifacts/`; select those exact
   relative files as native-gate `source_files` so their copied/original hashes
   become part of the run binding. Pass the frozen `experiment.json` object as
   `probe_options.experiment` (also covered by the options binding). Never place
   the experimental state in `GateSpec.fixture` or auto-load it in the wrapper.
4. Each consumer proves its own positive execution/PING receipt control before
   loading. It verifies the selected artifact's hash and establishes/records the
   physical hold before calling `savestate.load(path,true)`. The existing owner
   must reject its restored frame anchor. Its retained lease/emergency STOP must
   verify physical holding; the owner remains failed. The probe then uses direct
   held `emu.yield()` iterations with repeated stop/readback checks. It never
   invokes mailbox poll/pump/reset, constructs a replacement owner, closes the
   lease or clears the flag after load.
5. Require return true plus one pre-held successful-load callback for `valid`;
   require false/error plus zero successful-load callbacks for `late_failure`.
   Both must restore the exact saved frame and BUSY header, retain those bytes
   through the measured held interval, and record **zero** execution dispatch
   since immediately before load. Require `controlled_old_owner_invalidated`,
   `controlled_load_return`, `controlled_success_notifications`,
   `controlled_restored_frame`, `controlled_restored_busy`,
   `controlled_zero_restored_dispatch`, `controlled_retained_busy`,
   `controlled_trace_complete`, `controlled_callbacks_removed`,
   `controlled_exit_held`, `controlled_no_failures` and the two positive-control
   assertions in each consumer gate. Cleanup removes only this probe's named
   callbacks under the held owner; all failures are retained and the process
   exits held. Never manufacture release authority to make teardown succeed.

`SaveStateLuaLibrary.Load` in the exact pinned source catches ordinary load
exceptions and returns false; `Save` returns a Boolean but delegates to an API
whose canceled/deferral cases need the independent output existence/hash checks.
The malformed UserData case therefore expects a false result after native
restoration rather than relying on an exception reaching Lua. Source:
[SaveStateLuaLibrary.cs](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/lua/CommonLibs/SaveStateLuaLibrary.cs),
[SaveStateApi.cs](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/Api/Classes/SaveStateApi.cs).

The 51 focused tests execute the real probe, actuator and mailbox Lua with
modeled host/ARM-dispatch/state boundaries, plus strict Python artifact tests.
They cover both load modes, missing positive evidence, altered artifact/header,
no restoration, dispatch during load/quarantine, callback registration/cleanup
failure, and all production memory writes constrained to the 64-byte PING
mailbox. No product source rewriting, skip or xfail is used. These tests prove
the probe's refusal/hold bookkeeping; they do not replace the private live runs.

```powershell
python -m pytest tests/unit/test_controlled_load.py tests/unit/test_controlled_load_probe.py tests/unit/test_reset_probe_fixture.py -q
python -m ruff check tools/rr/controlled_load.py tools/rr/reset_probe_fixture.py tests/unit/test_controlled_load.py tests/unit/test_controlled_load_probe.py tests/unit/test_reset_probe_fixture.py
```

| Pinned host source | SHA-256 |
|---|---|
| MainForm.cs | `ee5a40726b9af9e98fe0ad0c08861eeb4a5dfb7e040cc0759b1fbd7c3fbda000` |
| MainForm.Hotkey.cs | `50b3d36d12953544e6c99618647deafb5dd397c3011506cc5d6126e4608e1ed6` |
| SavestateFile.cs | `282b5cbd6c8397bdf59a344a301b46fe1b87300e4ceb7ad7ec87150fe41e7708` |
| MemorySaveStateApi.cs | `16a6dbebb9b6bc046e42380c4ebad260725b662dbed38dc660937178a73d3f3d` |
| LuaConsole.cs | `677f3646839d3030149c9986c78d8422c6ff9c18fbbd19eff24aad5746506c7e` |
| Zwinder.cs | `f68f0586963523e72b4a8a4bc396b565ce7164fefb1c037186897d2e70b7c9b1` |
| MGBAHawk.IEmulator.cs | `6b95b80f77fd9671645e3ef3e601f87370ac51906879a7f8eefcbdc868eed827` |
| MGBAHawk.IStatable.cs | `90cd3291a89cf20c2dcd1552ae139fabf442edf365c67c0eb35fcd799f1e6971` |
| BinaryStateLump.cs | `b87ab4ca09d8eabced716182aa3fafcfd3ca9f53ccd6a79b0094f7994aa986ce` |
