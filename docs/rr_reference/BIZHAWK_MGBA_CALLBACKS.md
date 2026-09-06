# Pinned BizHawk2.11.1/mGBA instrumentation contract

**Exact-address read, write and execute callbacks are supported. Wildcard
callbacks and address masks are not.** The arena17 zero GUID is explained by
the selected core's explicit wildcard refusal; it does not prove that mGBA lacks
all memory instrumentation. No production host/runtime or arena assertion was
changed by this research.

## Binding to the installed runtime

The installed `E:/Howard/Bizhawk/EmuHawk.exe` and core assembly embed
`2.11.1+bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5`, the exact
[BizHawk2.11.1 commit](https://github.com/TASEmulators/BizHawk/tree/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5).
The native DLL's computed Git blob hash also matches that commit's release asset.

| Installed file | SHA-256 |
|---|---|
| `EmuHawk.exe` | `f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd` |
| `dll/BizHawk.Emulation.Cores.dll` | `444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5` |
| `dll/mgba.dll` | `ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1` |

The775680-byte `mgba.dll` has Git blob SHA-1
`32ddf4885e5d02aae207c72065d4e034913cace4`, exactly the pinned
`Assets/dll/mgba.dll` object. That host commit pins
`TASEmulators/mgba` commit `94b1578f8545d8ad17bb4036dba908612d5731e2`.
These checks bind this analysis to actual installed binaries rather than merely
a release label or a current upstream branch.

## Managed API contract

In the pinned
[MGBAMemoryCallbackSystem](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/GBA/MGBAMemoryCallbackSystem.cs#L48),
`Add` rejects null addresses at lines57–59 and non-`0xFFFFFFFF` masks at62–64.
Read/write registrations call native `BizSetWatchpoint`; execute registrations
enable `BizSetExecCallback`. Only `System Bus` is an available scope.

| Lua operation | Exact supported contract |
|---|---|
| `event.on_bus_read(fn, address, name, "System Bus")` | Exact numeric address required. |
| `event.on_bus_write(fn, address, name, "System Bus")` | Exact numeric address required. |
| `event.on_bus_exec(fn, address, name, "System Bus")` | Exact numeric instruction address required; use its actual even address, not a Thumb function-pointer bit. |
| `event.on_bus_exec_any(...)` / null read/write address | Rejected; a wildcard is not implemented. |
| Managed callback with a range/address mask | Rejected unless mask is all ones. |
| `event.availableScopes()` | Scope enumeration, not proof of wildcard support. |
| `event.can_use_callback_params("memory")` | Lua-version argument support only; not core read/write/wildcard capability. |

The pinned
[EventsLuaLibrary](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/lua/LuaHelperLibs/EventsLuaLibrary.cs#L222)
catches `NotImplementedException` and returns `Guid.Empty`. This matches arena17:
the call succeeded under `pcall`, with scope `System Bus`, but returned
`00000000-0000-0000-0000-000000000000`. Keep the nonzero-GUID assertion.
Successful registration must additionally be checked against real positive hits.

[MGBAHawk.IDebuggable](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/GBA/MGBAHawk.IDebuggable.cs#L8)
exposes R0–R15, CPSR and SPSR and a callback-cycle offset for total cycles.
Public instruction stepping is unavailable (`CanStep=false`, `Step` throws),
so a Lua single-step fallback is not supported by this interface.

The private capability probe did not capture Lua cycle values because its
`type(emu.totalexecutedcycles)=="function"` guard did not pass. This is not an
independent proof that the underlying cycle service is absent. If event-cycle
identity is required, verify callable binding behavior with a bounded `pcall`
probe and record the returned type/error rather than depending on that guard.

## Native watchpoint semantics and information loss

The pinned
[BizHawk mGBA bridge](https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/platform/bizhawk/bizinterface.c#L248)
creates each watchpoint over `[address,address+1)`. It forwards the native access
address/type/old value/new value. The managed wrapper dispatches by the **actual
access-start address**, not the registered watchpoint address, and passes only
new value plus a read/write flag to Lua. Width, old value, access source and
watchpoint identity are discarded.

The ARM
[memory-debugger shim](https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/arm/debugger/memory-debugger.c#L85)
matches overlapping access ranges, accounting for1/2/4-byte alignment. Therefore:

- Watching only `base+1` inside a32-bit access at `base` can trigger native code
  but lose the Lua event: no callback dictionary entry exists at `base`.
- Registering `base` and `base+1` can deliver two calls to the **base callback**
  and none to the interior callback. A hit count is not an access count.
- Read shims pass new value0; the useful old/read value is not exposed by the
  managed callback. Multiple-register stores also pass new value0. Do not treat
  callback value as universally authoritative data.
- Watch callbacks occur before the original memory operation. Reading bytes in
  the callback does not establish the completed write's resulting state.

The core tracks DMA/system/program access source, but the bridge drops it.
[DMA transfers](https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/gba/dma.c#L251)
do use the shimmed CPU memory functions, so relevant DMA accesses can be seen;
their contemporaneous CPU PC is not automatically the instruction that caused
the DMA transfer. Several BIOS/HLE memory paths use the same interface. Preserve
unknown origin rather than attributing every write to the sampled R15.

## Execute callbacks and PC attribution

The bridge's execute hook reports
`_ARMPCAddress(cpu) + _ARMInstructionLength(cpu)`. Its debugger loop invokes the
hook after the previous step, identifying the next instruction before execution.
Use the **execute callback's address** for allocator entry identification. The
raw R15 value is a pipeline register and must be retained separately.

Inside an ordinary CPU data-access hook, candidate instruction PC is raw R15
minus4 in Thumb mode or8 in ARM mode. This is an attribution candidate, not a
universal identity for DMA/system accesses. Record CPSR, R0–R15, total cycles,
callback address/value/flags, frame and event ordinal. Match candidate PC against
actual decoded instruction behavior and known allocator-call intervals. Never
label a write benign solely because a plausible raw PC points near patch code.

## Sound bounded measurement on the supported runtime

1. First run a **capability-only** private probe with exact natural controls:
   read `0x030030F4`, native beacon write `0x0203F800`, and execution at the
   already reviewed frame control `0x0800051A`. Require nonzero registration
   IDs, actual hits and successful callback removal. An interior write point at
   `0x0203F801` is a diagnostic for overlap routing, not a required positive hit.
2. Register exact allocator/logging entry addresses. Capture argument registers,
   LR/SP/CPSR and the corrected callback address. This directly establishes entry
   reachability for the observed scene; absence is limited to that scene/window.
3. For conflicting-region accesses, explicitly cover every possible access-start
   address in the measured union. The current aligned canonical ranges combine
   to `0x0203F76C..0x0203FFFF`,2196 byte addresses. One point per word or only an
   interior byte is insufficient for arbitrary byte/halfword stores. Read and
   write coverage require separate registrations.
4. Retain raw overlap duplicates, or deduplicate only with a validated native
   event-identity rule. Report registration coverage, event/drop counts and
   instrumentation start/end. Keep strict trace-completeness checks. Native
   watchpoint matching scans its watchpoint list on every memory access, so
   begin with short windows and measure overhead; do not silently reduce coverage
   when performance is inconvenient.
5. Canonical-address coverage does not automatically cover all mirrored EWRAM
   bus addresses. State the observed address-domain limit. A byte watchpoint
   range is an instrumentation configuration, not a global allocator ownership
   proof. Host direct-memory writes, reset/load-state bulk changes and pre-hook
   boot activity also need separate treatment if included in a claimed scope.
6. If complete writer attribution cannot be recovered from this interface,
   keep `all_arena_accesses_attributed` unresolved. A future **private diagnostic
   core build** could expose width, accessSource, normalized address and native
   watchpoint identity with a range callback; that would be a separately hashed
   validation runtime requiring review. It is not a production-host change made
   by this task and cannot be presented as evidence from the unmodified host.

Allocator entry hits and observed conflicting writes can establish concrete
collisions. Zero hits or unchanged/zero RAM snapshots cannot establish that the
arena is unowned. Existing arena assertions must retain that distinction.

## Actual private capability measurement

The validation agent ran `callback_capability_19_a` after the reviewed private
battery boot, frames1657–1658. This used the actual installed binaries above,
natural game/companion activity, no RAM mutation commands, and two measured
frames. All four registration IDs were nonzero, all were successfully removed,
and the trace had no drops. The result has 50 passing assertions and is classified
`exact_callback_capability_only`, with `arena_ownership="unresolved"`.

| Registered callback | Observed hits | Interpretation |
|---|---:|---|
| Read `0x030030F4` | 10 | Exact read callback works; raw callback value is0, matching the native shim limitation. |
| Write `0x0203F800` | 4 | Native signature written once per frame, with duplicate delivery from the overlapping interior watchpoint. |
| Write `0x0203F801` | 0 | Nonzero registration is insufficient to prove this interior callback sees a wider access. |
| Execute `0x0800051A` | 2 | Exact execution callback works once per measured frame. |

Execute observations report callback address `0x0800051A` and rawR15
`0x0800051C`, CPSR `0x6000003F`. Beacon writes report rawR15 `0x08378F7C`;
the actual bound candidate instruction at rawR15−4, `0x08378F78`, is
`23 60` (`str r3,[r4]`). This directly corroborates the PC distinction for the
measured CPU store. It does not resolve DMA/system writer attribution generally.

Result path:
`C:/Users/howar/AppData/Local/Temp/slink-rr-native-probes-01a072f9/runs/callback_capability_19_a/results/result.json`.
Its independently checked SHA-256 is
`bbf2ca3659dead35d22bbe4456c30cd05f4fadaddef7c378aa436c884489b116`.
The validation agent reported owned process41664 exited normally and original
save/config inputs remained unchanged. This source-research agent launched no
emulator and made no production code or host changes.

## Source fingerprints

| Pinned source | SHA-256 |
|---|---|
| BizHawk `MGBAMemoryCallbackSystem.cs` | `68b6537dd33a687de222e8649b0ea78ba53ecac18ebdf21f26d0222b83f87ff8` |
| BizHawk `MGBAHawk.IDebuggable.cs` | `5d8c04ff8e6549922266193cf4fc82506842aa2510ae3be5836d5cf811c588a3` |
| BizHawk `LibmGBA.cs` | `a6b7f4a89b57c5ba3dbb66cf80e0bea7ebc90f7e92346c9be7c5efa33c398620` |
| BizHawk `EventsLuaLibrary.cs` | `3b17d351117e1a3f8e54a01ae0c4b8920c0590568544befd8bb524deb0af66a7` |
| mGBA `src/platform/bizhawk/bizinterface.c` | `3c720eb1ff5d33c62ece48563231f990a64ddc34a7f7bb9213eac429e74e2179` |
| mGBA `src/arm/debugger/memory-debugger.c` | `a48581dc22e16340a8411607913a9670dde7a093d61c1ed40e56c4cd6ab10f22` |
| mGBA `src/debugger/debugger.c` | `b7eff1786cacd559ab8f1448c64a268d49e5a6e90ca93c30306931a976f756a6` |
| mGBA `src/gba/dma.c` | `01711e3079fa3fd1ae3d09271b7b4f4784326c739d460ef5376e013e60142545` |
