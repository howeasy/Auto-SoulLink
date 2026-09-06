# Exact-address arena probe: private one-frame lane

`lua/tests/rr/arena_probe.lua` now implements the explicit
`writes_exec_v1` lane. It measures canonical write access starts and allocator/
logging execution entries for exactly one frame. It does not register wildcard
callbacks, claim read coverage, write RAM, post mailbox commands or certify arena
ownership. No production client, companion C code or mailbox API is changed.

The [pinned callback contract](BIZHAWK_MGBA_CALLBACKS.md) explains why the preceding
wildcard probe refused. The exact capability19 run demonstrated working callbacks
and overlapping-watchpoint duplication; it did not establish arena ownership.

## Explicit scope and inputs

The runner must select:

```python
frames = 1
probe_options = {"arena_lane": "writes_exec_v1"}
source_files = (
    "lua/tests/rr/host_identity.lua",
    "lua/platform_clock.lua",
    # Other dependencies explicitly required by the selected native-gate manifest.
)
```

Use the private validated fixture/descriptor/core-identity workflow already
provided by `tools.rr.native_gate`. A missing/different lane or a frame budget
other than1 is rejected. This is an intentional new contract, not a silent
replacement of an old read/write/wildcard requirement. Full read coverage needs
a separately named, measured and reviewed lane.

| Coverage | Bound |
|---|---|
| Logical libc metadata | `[0x0203F76C,0x0203FBB0)` |
| Logical companion arena | `[0x0203F800,0x02040000)` |
| Registered write starts | **Every byte** in `[0x0203F769,0x02040000)`, including3 bytes of lower boundary padding |
| Write registration count | **2199**, with no duplicate address registration in the overlap |
| Exact execute entries | **11**, including frame control, allocator functions and logging candidates |
| Total registrations | **2210** |
| Measured game frames | **1** |
| Registration/measurement/cleanup budgets | **15 seconds each** |
| Total instrumentation budget | **45 seconds**, excluding fixture boot |
| Trace capacity | **8192 raw callbacks**, leaving room for registration/removal evidence under the runner's8MiB result bound; overflow is retained and fails validation |

The private runner needs a separate hard process deadline sufficient for reviewed
boot plus the45-second instrumentation budget and startup/shutdown margin. The
current1656-frame battery boot takes roughly31 seconds, so the validation owner
proposed about100 seconds total with short host polls. Inner limits are strict
validation bounds. Lua cannot safely interrupt a native frame in progress;
the outer private-process deadline remains the hard bound for a non-returning
core/host call. A killed or partial run cannot pass.

## Registration and cleanup ownership

Before registration the probe requires the bound actual mGBA core evidence,
exclusive private MainForm/LuaConsole surfaces, inactive rewind, an unowned
`BlockFrameAdvance`, and an unpaused host. It never calls `client.unpause`.
An already paused or foreign-held host is rejected unchanged.

The probe sets its own `MainForm.BlockFrameAdvance`, then calls `emu.yield()` and
verifies constant emulator frame count, unchanged pause state, the still-owned
flag, and no tool/rewind conflict. It checks those conditions throughout both
registration and removal, servicing `emu.yield()` every32 operations. Progress
checkpoints are written every256 operations and at each phase boundary.

Every registration is an exact numeric System Bus address. Empty, malformed,
all-zero and repeated GUIDs are failures; all attempted registrations and returned
values are retained. A partially registered range never advances the measured
frame. Registration exceptions are recorded alongside zero/duplicate-ID failures
instead of discarding earlier evidence.

Cleanup uses the probe's unique registration **names**, including failed-ID
attempts. This matters because EventsLua can create a named function before the
core rejects `Add`. All removal results/exceptions are retained. Removal happens
under the verified cleanup hold, or the still-valid registration hold after a
registration failure. A lost/conflicting hold prevents unverified cleanup.

If removal is incomplete or ownership becomes uncertain, the probe leaves its
remaining own hold in place for the runner's private-process exit/deadline. It
does not resume gameplay with uncertain callbacks. It never releases a flag it
did not acquire. Successful cleanup releases only its own flag and preserves the
original unpaused state.

## Measurement and attribution limits

After complete registration, the probe releases the registration hold, advances
one frame, and immediately acquires/verifies a cleanup hold. Only that frame is
the declared measured window. Callback delivery during registration/cleanup is
counted separately and fails the declared-window check.

The probe stores raw addresses, values, flags, frames and register snapshots.
Execution-entry names identify exact watched instruction addresses. Raw R15 is
never relabeled as definitive writer provenance. DMA/system access source,
width, old value and native watchpoint identity are not provided by this bridge.
Some stores, including STM, have an uninformative callback value. No callback
value is substituted for a completed-memory readback.

Full byte watchpoint registration duplicates some callbacks for wider accesses.
The probe retains those deliveries. Consecutive matching observations are marked
only as `duplicate_candidate`; they are not removed or treated as a proven
physical-event identity. `raw_write_callbacks` therefore is not a count of
physical writes.

The scope excludes EWRAM bus mirrors, host direct-memory modifications, reset/
load-state bulk effects and pre-registration boot. Any claim about those needs
additional instrumentation. Zero hits and zero/unchanged snapshots never prove
free RAM. The result always keeps `ownership="unresolved"` and
`release_ready=false`, even when every instrumentation assertion passes.

## Required result checks

The runner should require the complete explicit lane contract, including:

```text
arena_explicit_lane
arena_requested_one_frame
arena_no_failures
arena_write_start_coverage_complete
arena_exec_coverage_complete
arena_registration_hold_verified
arena_cleanup_hold_verified
arena_measurement_one_frame
execute_control_observed
write_hook_observed
arena_no_unmeasured_callbacks
arena_declared_starts_only
arena_trace_complete
arena_register_reads_complete
arena_all_callbacks_removed
arena_own_hold_released
arena_pause_preserved
arena_wall_bounds
```

Also retain the runner's ROM, fixture, descriptor, actual host/core, source and
configuration assertions. Do not reuse `read_hook_observed` from the obsolete
wildcard contract while presenting this lane as read coverage. The source records
`read_coverage` as explicitly not requested rather than reporting zero reads.

All operational failures and all final failed predicates are collected in the
runtime evidence before the fatal aggregate assertion. Phase/frame bounds, trace
overflow, register failures and multiple cleanup errors therefore remain visible
together. The normal wrapper writes a failed result and exits the private host;
progress files are incomplete evidence only.

## Focused verification

```powershell
python -m pytest tests/unit/test_rr_arena_probe.py -q
python -m ruff check tests/unit/test_rr_arena_probe.py
```

The19 focused tests execute the actual Lua probe and `platform_clock.lua` using
modeled private host/core surfaces. They cover all2199 start addresses, two
verified holds, one measured frame, duplicate retention, zero/duplicate/throwing
registrations, all-name cleanup, frame/flag/pause/tool/rewind hold loss, multiple
cleanup failures, each phase deadline, trace overflow, simultaneous measurement
failures, missing controls and rejection of old/widened scope. They do not launch
an emulator or stand in for the pending private runtime measurement.
