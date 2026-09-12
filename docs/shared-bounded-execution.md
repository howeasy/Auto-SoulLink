# Bounded frame mechanism checkpoint

`lua/platform_bounded_execution.lua` layers a single-frame owner over the unchanged
shared `platform_execution.lua`. It is currently qualified for pinned Gambatte on
BizHawk 2.11.1 only. It grants neither ordinary gameplay nor recovery authority.

Each `step_one(authority)` requires an unchanged verified hold and an explicit
per-step caller validator. It temporarily suppresses Lua update/resume callbacks,
synchronously invokes the source-pinned private `MainForm.StepRunLoop_Core(true)`,
and immediately restores the physical hold. It checks exactly one frame elapsed
and preserves the user's initial pause. Memory bus callbacks remain active;
ordinary Lua frame callbacks are suppressed to avoid recursively resuming the
currently running coroutine. The owned runtime must run its observations between
steps. The mechanism never exposes an unbounded release.

It requires the same core, library and input manager objects, one enabled Lua
script, inert disabled entries, no capture/movie/cheats/future-frame callback or
frame-advance conflict, and the original actuator's form/core/rewind/OS ownership
checks. Exceptions latch failure and request a hold. A failed request must not be
reported as a verified physical stop.

Evidence: `.cache/bounded-native-matrix.xml` contains 9 passes in 91.24 seconds:
R/B/Y with initial pause on and off, each taking exactly 30 steps, firing exactly
30 VBlank memory callbacks, returning to a verified hold at every yield, and
refusing expired authority; plus complete real R/B, B/Y and Y/Y trades from the
receptionist through native prompts, original animations, saves and receipts.
The trade cases still use file transport and explicit fixture authority. The
first full Y/Y attempt failed because the test used P1-prefixed buttons with the
single Game Boy controller. Correcting that test mapping passed without changing
the cartridge animation or the host step.

The next context-invalidation cut adds expected-frame continuity, pinned native
input-layer Power/Reset checks, and load-state/owner-exit callbacks. Actual
`same_frame_load`, `older_state_load`, native `HardReset` menu implementation and
Lua controller Power faults passed for R/B/Y: 12 cases in 36.35 seconds,
`.cache/host-context-first.xml`. No frame runs after invalidation, and the
independent hold remains verified. The preceding nine native/pause cases passed
again on this code in 100.31 seconds (`.cache/bounded-context-third.xml`). NLua
controller calls require explicit bound signatures, and its registered event
functions are callable userdata, not necessarily Lua `function` values.

This detects the normal load-state callback after the state is loaded; it does
not claim to prevent that load or to implement controlled restore/rebind. Raw
core-state APIs bypassing that callback still need qualification. Core/tool object
changes refuse rather than silently adopting the new context.

Not qualified: mGBA; controlled reset/load recovery; debugger and tool lifecycle
rebind; ordinary runtime selection; server-issued operation-specific frame budgets;
native cancellation/recovery authority; all fault injection and real network timing.
This module is not a frozen publication cut or production activation.

Source evidence is the existing pinned BizHawk 2.11.1 MainForm/LuaConsole/
LuaLibraries/EventsLuaLibrary code. In particular, `StepRunLoop_Core` would resume
scripts through tool updates without `LuaLibraries.IsUpdateSupressed`. Future-frame
callbacks can run additional frames and must be absent. The ordinary public frame
advance action changes pause/input state and is not used here.
