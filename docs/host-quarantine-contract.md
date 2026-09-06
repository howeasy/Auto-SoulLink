# Inactive host quarantine guard

`host/QuarantineGuard.cs` is an experimental external tool for a process that is
**already held throughout reconciliation**. It denies the pinned host's ordinary
savestate, stock rewind and Reboot Core routes while it remains selected. It has
no release, resume, disarm, reset, load or native-execution operation. It does not
enable normal unheld gameplay or select itself in a production client.

This is an additional routing guard, not a replacement for
[`platform_execution.lua`](../lua/platform_execution.lua), its process lease, or
paired execution authority. The caller must establish its independently verified
hold and revoke paired authority before arming. Accepting an existing hold here
does **not** authorize an actuator to adopt that hold, manufacture a new lease or
release it. The guard's nonce identifies a local request; it is not a secret,
cryptographic identity, lease or proof of exclusive ownership.

## Pinned experimental scope

The source targets the installed .NET Framework 4.8 BizHawk2.11.1 host, with
C# 5-compatible syntax and public host interfaces. Host analysis is pinned to
BizHawk commit `bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5`.

Arming hashes the actual process executable, current core assembly and exactly
one loaded native module named `mgba.dll` (case-insensitive). It also requires the
loaded MainForm assembly path to equal the process executable path.

| Input | Required value |
|---|---|
| Executable SHA-256 | `f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd` |
| Core type | `BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk` |
| Core assembly SHA-256 | `444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5` |
| Native module SHA-256 | `ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1` |

These file checks happen once per successful arming. Replacing executable,
assembly or native files out of band is unsupported. The private runner must
also bind the exact guard source and compiled DLL hashes; the guard does not
hash its own DLL. File pins and flag readback do not independently prove native
CPU quiescence, cartridge admission or permission to perform native recovery.

## Loading and explicit arming

The entry class is `SLink.Host.QuarantineGuard`, with a public parameterless
constructor and `ExternalTool` attribute. It implements `ToolFormBase`,
`IExternalToolForm` and the full pinned `IControlMainform` interface.

Use the host's external-tool loader. Constructing the class alone does not
register it. The public method is
`ToolManager.LoadExternalToolForm(string toolPath, string customFormTypeName,
bool focus = true, bool skipExtToolWarning = false)`. Loading only creates the
inactive tool; it does not arm it or change the hold. The inherited injected
`Tools` and `MainForm` properties and public `MainForm.Emulator` provide the
required host references without guessed reflection fields.

`QuarantineArm(string requestNonce)` accepts exactly 32 lowercase hexadecimal
characters and returns a Boolean. It requires:

- Initialized injected MainForm and ToolManager, live tool/host handles, and the
  owning UI thread;
- The exact supported host/core/native pins and `BlockFrameAdvance == true`;
- Selection of this exact object for all three controlled categories, with no
  other active tool requesting any of those categories;
- Unchanged core object and existing hold through the arming checks.

It retains the original host, ToolManager, core, UI thread, frame and request
nonce. Repeated arm requests are refused. No public operation disarms the guard.
Failed arming does not claim ownership or change the existing flag.

The host selects the first active matching tool in insertion order. The guard
temporarily participates in selection during the synchronous arming check and
then continues requesting control while armed, including after a fault. Removal
or disposal can still defeat selection. There is no general
exclusive-registration API. A hidden form with a live handle remains active;
visibility alone does not prove registration. See
[ToolManager registration](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/tools/ToolManager.cs#L150),
[selector](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/tools/ToolManager.cs#L474),
[ToolFormBase activity/injection](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/tools/ToolFormBase.cs#L15).

## Public observation protocol

Arm, verify and status calls belong on the original UI thread. Record polling
only copies the bounded log and does not touch host objects.

| Method | Behavior |
|---|---|
| `QuarantineArm(string requestNonce)` | Explicit, one-time successful arming under the pre-existing hold. |
| `QuarantineVerify()` | Rechecks injected and retained identities, selection, competing controllers, hold and constant held frame. Returns false on any latched fault; attempts only to retain/reassert the hold. |
| `QuarantineStatus()` | Verifies an armed guard and returns a fresh scalar/string status object; can latch a newly observed fault and reassert the hold. |
| `QuarantinePoll(long afterSequence)` | Returns a new array of immutable records whose sequence exceeds the cursor. Does not drain or mutate the log. |

Status exposes `Armed`, `Failed`, `Failure`, `RequestNonce`,
`HoldReadbackVerified`, `HostBlocked`, `HoldReadbackAvailable`, `OriginalCore`,
`SelectedForAllControls`, `InitialFrame`, `CurrentFrame`, `LastSequence`,
`DroppedRecords` and `FirstRetainedSequence`. `QuarantineOnly` is always true;
`FullExecutionSafety` and `ProductionSelected` are always false.

`Failed` and `HoldReadbackVerified` are deliberately separate. A failed guard
may successfully retain the flag, or may be unable to verify it. `HostBlocked`
is actual flag readback when `HoldReadbackAvailable` is true. Flag readback is
not a claim that arbitrary direct core calls cannot execute. An unavailable or
false readback must never be reported as a successful physical stop.

The log retains at most 256 records, with monotonically increasing sequences
starting at one. Each record has `Sequence`, `Action`, `Slot`, `Frame`, `Outcome`,
`HostBlocked`, `HoldReadbackVerified`, `Failed` and `Failure`. A slot/frame of
`-1` means absent/unavailable. Dropping old records increments `DroppedRecords`;
callers detect a cursor gap through `FirstRetainedSequence`. It is a bounded
in-memory diagnostic log, not durable transition persistence. Returned records
have no public setters and expose no host, core, collection or mutable payload.

## Routed actions

Armed `WantsToControlSavestates`, `WantsToControlRewind` and
`WantsToControlReboot` remain true after faults. The guard denies named, named
dialog and quick loads, and returns false from their load methods. It also denies
stock rewind and Reboot Core. Each request records `denied_not_performed`, actual
readback and any latched failure. Save requests are refused and recorded too.
Slot selection is handled without changing the host's selected slot.
`CaptureRewind()` is a no-op because the host calls it on every admitted frame.

Named-load interception receives no filename: MainForm calls parameterless
`LoadState()`. Quickload carries a slot, but existing quickload event handlers
run before the tool selector. `.State` drag-drop routes through MainForm's named
load. The ordinary rewind branch returns before invoking the stock rewinder
when a controlling tool is selected. See
[IControlMainform](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/IControlMainform.cs),
[load/save routing](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/MainForm.cs#L4091),
[rewind routing](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/MainForm.cs#L4387),
[state-file routing](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/MainForm.FileLoader.cs#L102).

**Host return values can be misleading.** The host returns true after the void
broker reboot method, and success-shaped write results after void broker save
methods. Those results do not mean that a reboot/save happened. Consumers must
inspect the guard record and independently verify any expected output. The
guard never calls the original operation or exposes a temporary pass-through.

Movie/read-only control flags remain false. Their required interface methods
perform no action if called directly, but this does not intercept normal movie
or read-only routing.

## Failure and lifecycle

Loss of hold, frame continuity, core identity, selection, UI-thread access or
injected dependencies latches failure. The only flag assignment in the guard is
`BlockFrameAdvance = true`. It never changes user pause, and a hold write verifies
that pause did not change. A successful emergency hold does not repair the fault,
restore authority, undo any execution, or permit subsequent release.

Closing, disposal and restart latch failure and attempt hold-only retention
using the original MainForm, even when tool registration is already gone.
The guard permits closure; form-close cancellation would not preserve host
registration reliably. `ToolManager.Close(Type)` removes the tool regardless of
form cancellation, and `ToolManager.Close()` clears its registry before calling
the forms. Thus emergency retention intentionally does not require current
selector ownership. See
[ToolManager lifecycle](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/tools/ToolManager.cs#L585).

An unexpected replacement core is never adopted. The guard may still set the
retained MainForm's hold flag while recording the identity fault; this does not
assert that the old lease covers the new core. An unavailable/disposed host or
wrong thread produces an unverified hold outcome. Disposal/GC on a non-UI thread
is not proof of a successful stop. No finalizer releases the hold.

`AskSaveChanges()` refuses while armed, but the host can bypass all such hooks
when `Config.SuppressAskSave` is true. It is a conditional additional refusal,
not a universal ROM/exit veto. Stopping the Lua owner does not transfer its
authority to this guard. The admitted private workflow must retain its original
owner and independent hold evidence for the entire reconciliation interval.

The unchanged `platform_execution.lua` adapter rejects the additional tool form
when checking its original exclusive tool scope. The private routing probe
establishes its hold before loading the guard, retains the original object and
lease, and makes no further adapter calls after tool loading. This does not
validate that adapter for an expanded tool scope or authorize it to release.

## Exclusions and validation limits

The supported workflow keeps the process held. This guard does not authorize
unheld gameplay, native recovery, paired execution, production selection or a
universal reset/load interlock. In particular:

- Power and soft-reset controller input bypass `IControlMainform`. In-game reset
  chords and controller/movie/script overrides need separate treatment.
- ROM open/replace, configuration reload and single-instance forwarding use
  other entry points. Restart/fault detection is not a pre-restoration veto.
- Starting a movie from savestate can still restore the movie's core state:
  MainForm sees apparent success from a denied reboot and continues to
  `RunQueuedMovie`, which calls direct state-loading extensions. A held guard
  does not make that restoration an authorized transition.
- Direct memory-state API loads, direct `IStatable`/`IEmulator` calls, future-frame
  preview, debugger/tools, additional Lua scripts, callbacks and REPL execution
  are outside this routing interface. A check performed later cannot undo a
  native instruction already executed through one of those paths.
- Existing quickload event handlers precede this selector. Competing tools'
  getters are ordinary .NET code. No arbitrary-code security is claimed.

Primary source:
[Power/reset](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/MainForm.cs#L2470),
[movie start](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.EmuHawk/MainForm.Movie.cs#L43),
[queued movie](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/movie/MovieSession.cs#L220),
[direct movie restore](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/movie/interfaces/IMovie.cs#L237),
[memory-state API](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/Api/Classes/MemorySaveStateApi.cs#L26),
[REPL execution](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/lua/LuaLibraries.cs#L386).

The interface descriptions above cover reviewed source behavior. The bounded
actual-host evidence below covers only its named cases. Compilation and host-route
probes must bind the exact built DLL. Further required checks include inactive and
unheld-arm refusal, selected-object/competitor cases, routed named/quick/API/UI
denials, active stock rewind, save/reboot false-success behavior, bounded copied
records, stop/close/remove/restart behavior and hold-readback failures. Separate
negative controls must preserve excluded movie/direct-state paths as exclusions.
No results should be inferred from tool names, successful compilation, or direct
calls to broker methods alone.

## Actual held-host component evidence

Private runs54 and55 loaded the guard through the real `ToolManager` on the pinned
BizHawk/mGBA host, under the original shared actuator's already-established hold.
Both used frozen03 RR ROM `3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301`
and the reviewed MGM-on Viridian battery fixture. The loaded guard DLL hash was
`32cb063769c110d3a4301fb748d02156ba005aa2769d1a7db1560ae358e70e9b`.
Guard03, its independent repeat, and guard04 build produced these identical bytes;
guard04 additionally fingerprints the builder source.

Both cases invoked actual MainForm named-load, quickload3, named-dialog, Reboot
Core and named-save routes. Every route generated the expected explicit denial
receipt. The named dialog entry is private in this host, so the test invokes its
source-verified `MethodInfo`; it does not claim a physical menu click. The named
load points to a different valid state containing an armed PING. No load applies:
the current frame1657, core object, complete600-byte party and64-byte mailbox stay
unchanged, and the refused save creates no file. The reboot route returns true
despite the denial, confirming why that return value is not a success receipt.

Run54 began without user pause and retained the hold for16 yielded checks over
253.5168ms. Run55 preserved an existing user-owned pause, checked the exact quick
slot, and retained the hold over15 yields/263.1796ms. It then cleared the flag
once under that user pause and called guard verification on the same thread
without yielding. Verification reasserted the hold, latched `existing_hold_lost`,
and returned false; the failed guard still denied a further named load. Neither
case released the original actuator lease. Public manager removal left the guard
failed and unselected with the hold still set. Both exact child processes exited
normally, and the original configuration/SaveRAM hashes remained unchanged.

[Machine-readable evidence](rr_reference/host_quarantine_evidence.json) binds the
two cases, original results, preparation, source/ROM/fixture identities, outcomes,
and eight retained failed preparation/interop attempts. The private script is
`lua/tests/rr/quarantine_guard_probe.lua`. It does not test active stock rewind,
general unheld gameplay, arbitrary direct-core calls, movie restoration, paired
reconciliation, production selection or the full release matrix. Those gates
remain open. No structural assertion count substitutes for those missing cases.

### Pinned NLua call-cache regression

The failed attempts exposed a bundled-host interop bug. On a repeated named
instance-method call, `CallMethodFromName` fills cached arguments with stack offset0
before removing the receiver, although the argument offset is1. See the pinned
[LuaMethodWrapper](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/ExternalProjects/NLua/src/Method/LuaMethodWrapper.cs#L208).
The failure is independent of Int64 width: a temporary string bridge failed too.
Explicit `luanet.get_method_bysig` uses a retained target and the MethodInfo path,
avoiding the faulty name-cache branch. The host probe binds repeated public methods
this way; it changes neither the installed NLua DLL nor shared execution adapter.

`tests/host/NLuaBindingSmoke.cs` reproduces the failure using the actual installed
NLua in a standalone process. The first named call enters `Echo`, the second fails
before entering it, then100 signature-bound calls deliver the exact requested
values. The test launches no emulator. Its source/executable/result and actual
NLua/lua54 hashes are included in the evidence JSON. It is a separate diagnostic
from the unarmed guard smoke runner below.

## Reproducible offline probe build

Create a fresh guard build from explicit local dependencies:

```powershell
python tools/build_host_guard.py --repo . --host E:/Howard/Bizhawk --toolchain patch/build/host-toolchain/roslyn-4.8.0 --framework C:/Windows/Microsoft.NET/Framework64/v4.0.30319 --output patch/build/host-guard-review
```

The toolchain directory contains the locked NuGet archive as `toolset.nupkg` and
the extracted `tasks/net472` files at its root. The builder verifies package and
extracted bytes before invoking the compiler. It downloads and installs nothing.

After creating a guard build with `tools/build_host_guard.py`, compile both
private C# probe programs and run the unarmed protocol smoke test with:

```powershell
python -m tools.build_host_guard_probes --repo . --guard-manifest patch/build/host-guard-04/manifest.json --output patch/build/host-probes-review
```

The output directory must not exist. Choose a new directory for every attempt;
failed output and earlier candidates are preserved. The runner requires a guard
manifest containing the guard source, toolchain lock and guard builder source
fingerprints. Older manifests missing the builder fingerprint are refused.

Before executing a compiler, the runner revalidates every recorded guard source,
compiler, reference and DLL fingerprint; verifies the extracted compiler against
the locked package; and checks the original compiler command against the reviewed
builder's exact command shape. It constructs its own two compilation commands,
without executing command text supplied by the manifest. The host directory
comes only from the validated, locked `EmuHawk.exe` reference. Framework reference
hashes are recorded and rechecked, rather than treated as additional lock-file
pins. The selected manifest and repository remain reviewed inputs, not signed
attestations against arbitrary replacement of every input and its claimed hash.

The outputs are `GuardProtocolSmoke.exe`, `SLink.QuarantineProbe.dll`, per-step
logs, `execution.json` and, on success only, `manifest.json`. Fingerprints of both
C# test sources, the executing probe builder and original guard build inputs are
retained alongside commands, outcomes and artifact hashes. Source bytes are not
copied by this runner; retain the matching commit or private source closure for
later reconstruction. Inputs and completed artifacts are rechecked before
and after each step. Compiler steps have 60-second deadlines; the smoke executable
has a 30-second deadline. Nonzero exits, timeouts, changed inputs, malformed smoke
results, fewer than 22 checks or a different declared scope refuse success and
retain failure evidence. Additional checks in a reviewed smoke source are allowed.

Only the compiler and newly built **unarmed** smoke executable run. The loader DLL
is compiled for a separate private host experiment and is not executed here. The
smoke process loads managed host assemblies to construct an uninitialized guard;
it does not launch EmuHawk, load a ROM, install a tool, change host configuration or
perform any network operation. Its result covers constructor/protocol behavior,
refusals without an initialized host, immutable copied records and bounded log
cursors. It provides no armed MainForm routing, physical execution-hold, native
recovery or production-release evidence. Both output manifests and execution
records explicitly set `emulator_launched`, `routing_proved`,
`production_selected` and `release_ready` to false.

Two actual offline builds against guard04 and the restored loader source produced
byte-identical smoke and loader artifacts, and each smoke run passed 22 checks.
The current retained manifests are in `patch/build/host-probes-03/manifest.json`
and `patch/build/host-probes-03-repeat/manifest.json`. The earlier01 builds retain
the exploratory `PollSince` helper's fingerprints and are historical evidence;
their source paths no longer match the restored loader. These are separate
offline results; they do not change the private emulator experiment's verdict.
