# Read-only heap observations during the frozen03 battle component

`lua/tests/rr/heap_battle_observation.lua` wraps the frozen03
`ghost_natural_battle_probe.lua` scenario. It adds no game frames, inputs, memory
writes, allocator calls, heap clipping or execution hold. The existing inner
scenario still drives its ordinary boot, route, natural wild battle, Run and field
return, including its synthetic peer requests. The wrapper does not change those
gameplay helpers or replace their runtime evidence.

Heap observations live in `report.evidence.heap`; the inner scenario retains
`report.evidence.runtime`. This is wrapper-boundary evidence, with
`capacity_proof=false`, `ownership_proof=false`, `complete_peak_coverage=false` and
`release_ready=false` even when the observation component succeeds.

## Hook contract

The exact frozen03 ROM/build is required, and each wrapper's complete instruction
and literal bytes are verified before hook installation:

| Operation | Entry | After internal call, before wrapper return |
|---|---|---|
| InitHeap | `08002B80` | `08002B8E` |
| Alloc | `08002B9C` | `08002BA8` |
| AllocZeroed | `08002BB0` | `08002BBC` |
| Free | `08002BC4` | `08002BD0` |

The other two hooks are the frame positive control at `0800051A` and AGBAssert at
`081E3B14`. Registration uses `event.on_bus_exec(callback,address,name,'System Bus')`.
All ten hooks install in the same emulated frame, with no yield or hold changes.
Every registration result must be a unique, nonzero UUID. Names are recorded
before each attempt, because a failed/zero-ID registration can still create a
managed callback name.

The installed host exports these methods as callable `userdata`, not Lua
`function` values. Preflight records each binding's type and presence, accepts
only function/userdata candidates, then actually invokes the register reader
under `pcall` and validates all five required registers before installation.
Registration and removal still require their checked actual results. A userdata
value alone is never capability evidence. `event.can_use_callback_params` is a
pure callback-argument support query in the
[pinned EventsLuaLibrary](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/lua/LuaHelperLibs/EventsLuaLibrary.cs#L61),
not a callback opt-in; this wrapper does not call it.

Each operation record captures R0, R1, R14, R15 and CPSR. Entry R14 is retained as
the caller when pairing the later post-call observation; post-call R14 is normally
the wrapper's internal BL return and is not substituted for that caller. R0 is
reported as a result pointer only for Alloc/AllocZeroed. InitHeap and Free have no
specified result-pointer semantics. Pairing uses a bounded LIFO stack and rejects
unmatched or unfinished operations. Raw PC/CPSR are retained without inventing a
pipeline adjustment.

`lua/rr/heap_snapshot.lua` supplies the checked read-only heap scan through explicit
System Bus reads. Records retain only the compact capacity/header counts, not a
copy of every scanned block. Uninitialized or transitional invalid headers remain
`available=false` with a reason and no free-capacity fields. Read failures, frame
changes, scan-budget overflow, trace overflow, pairing failures or any AGBAssert
hit fail the observation. Required positive controls include paired Init/Alloc/
Free observations with at least one available post-call snapshot for each.

Available-sample minima are grouped by `(heap root, heap size)` so different heap
extents are never mixed into one capacity number. These samples omit direct
internal allocator calls, raw CPU/DMA writes and the separate libc allocator.
Unavailable snapshots and unobserved transitions prevent a complete peak claim.

## Failure retention and cleanup

The first fatal failure is checkpointed immediately through guarded
`ctx.checkpoint`, using a distinct `heap_observation_fatal_<reason>` phase. The
failure latch and callback registers/context are present before checkpoint IO.
AGBAssert can stop the guest before the parent returns, so final-only reporting
would lose the most important failure. Checkpoint attempts occur once; checkpoint
exceptions and reentrant callbacks do not create recursive checkpoint loops.

If Lua control returns, cleanup calls `event.unregisterbyname` for **every attempted
name**, including partial registrations, and continues after a cleanup exception
or false return. Parent failure is retained and never changes into a success.
An owned-process timeout may retain only the fatal checkpoint; it does not claim
that Lua's later cleanup ran. The outer runner remains responsible for its private
process lifecycle. This wrapper grants no broader host execution authority.

Default limits are 8,192 operation records, 512 blocks per heap scan, 16 nested calls
and 16 distinct heap extents. The optional `probe_options.heap_observation` object
can set `max_records` (1–32768), `max_blocks` (1–8192) and `max_depth` (1–64).
Malformed values are rejected rather than silently defaulted.

Read-only scans add wall-clock cost even though this wrapper adds no emulated
frames. The prepared runner's outer deadline and exact-process cleanup remain
required; an incomplete or timed-out observation is not a capacity result.

Required wrapper assertion names for a new prepared run are:

```text
heap_observation_frame_control
heap_observation_no_agb_assert
heap_observation_init_observed
heap_observation_alloc_observed
heap_observation_free_observed
heap_observation_callbacks_removed
heap_observation_complete
```

## Modeled validation

The tests execute the actual wrapper and heap reader with modeled host APIs and a
modeled parent. They cover statistics/caller pairing, unavailable initial headers,
registration faults/races, cleanup failures, heap/register read errors, trace/scan
overflow, parent failure, missing controls, malformed budgets, immediate fatal
checkpoints, checkpoint failure/reentrancy, and missing checkpoint support. Direct
Lupa Python callables exercise the userdata path without a Lua-function adapter;
noncallable userdata, malformed reader results and absent/nonsensical bindings
must fail. No emulator is launched, and modeled positive cases are not physical
release proof. The focused command below passed 62 cases (50 wrapper and 12 heap
reader cases) after the callable-binding correction.

```powershell
python -m pytest -q tests/unit/test_rr_heap_battle_observation.py tests/unit/test_rr_heap_snapshot.py
python -m ruff check tests/unit/test_rr_heap_battle_observation.py
```

## Retained preflight failures

The first private attempt (`heap_battle_63_a`) failed before registration or the
inner scenario because an overly strict function-type predicate rejected the
host bindings. A diagnostic-only second attempt (`heap_battle_64_a`) retained the
same failure and recorded all four queried bindings as present userdata. These
failures are preserved, not rewritten as passing capacity observations. Their
result files are under
`C:/Users/howar/AppData/Local/Temp/slink-rr-native-probes-01a072f9/runs/<run>/results/result.json`.

| Run | Result SHA-256 | Evidence limit |
|---|---|---|
| `heap_battle_63_a` | `d7d5f216d1c5a338508707ab54a9b7f988b1a67dcc2d70d5ee540a2b95a2f946` | Failed preflight, zero hook attempts, parent not started. |
| `heap_battle_64_a` | `42fb62fa24ea4f65b40e9dda97bb89fd71239b14956526d6d820c7509c034cdb` | Same failure plus actual binding type/presence diagnostics. |

These two results provide no heap capacity, allocator coverage, ghost or battle
acceptance. The corrected observer was exercised in the separate run below.

## Actual frozen03 observation: run65

`heap_battle_65_a` completed the existing single-cartridge synthetic-peer scenario
on the actual MGBAHawk core, from boot through a natural Pidgey battle, Run, field
return and ghost cleanup. The result retains the inner runtime separately;
its `visual_review` is still `pending`. This heap review does not certify that
visual review or duo gameplay. The launcher reported a normal exit after
56.125 seconds and unchanged original inputs; this observer added no frame or
host-control operations.

All ten registrations returned different nonzero UUIDs; every recorded name had
a matching successful removal. Installation and observation began at frame1;
observation ended at3047. The frame hook had2,880 hits at frames12–3046. These
are positive observations, not an assertion that this instruction runs once on
every boot or gameplay frame.

An independent read of the retained JSON verified all468 sequential trace rows
as234 complete entry/post pairs, including entry arguments, caller identities
and ordered frame boundaries. It recomputed the operation counts and byte
accounting rather than relying only on the summary flags. Every post-call scan
was available. No pending pair, read error, overflow, outside-phase callback or
AGBAssert hit was reported.

| Wrapper | Entry/post pairs | Available post-call snapshots |
|---|---:|---:|
| InitHeap | 7 | 7 |
| Alloc | 75 | 75 |
| AllocZeroed | 42 | 42 |
| Free | 110 | 110 |

There were465 available snapshots and five unavailable samples. Two unavailable
samples were the initial frame1 observation and first InitHeap entry at frame12
(`uninitialized_or_invalid_extent`). The other three were InitHeap entries at
frames1563,2330 and2937, all with caller `0804C125` and reason `invalid_header`.
Each immediately paired post-call scan was valid. The record preserves these
pre-initialization states without inventing zero free capacity or identifying
their preceding writers from the snapshot alone.

Every available sample used root `02000000`, size114,688 (`0x1C000`). The smallest
observed free total and largest-free-block value were both11,608 bytes, at
frames2347 and2633. Those snapshots contain53 headers (848 bytes) and102,232
allocated bytes; the three terms sum to the declared heap size. The final sample
had103,072 free bytes and11,520 allocated bytes across six headers. These are
wrapper-boundary observations in this one MGM-on route, not a complete peak,
global fragmentation bound, reservation approval or proof that subtracting a
proposed arena size preserves all supported allocations. Direct internal calls,
raw CPU/DMA users, other scenes/modes and reset/load ordering remain separate
ownership and capacity gates.

All paths below are relative to the private run directory
`C:/Users/howar/AppData/Local/Temp/slink-rr-native-probes-01a072f9/runs/heap_battle_65_a`.

| Evidence | SHA-256 |
|---|---|
| `results/result.json` | `2c3d2c472ebb1cf926f5ce9d6d2e784b33fab2e4371218d25e51628012d0c251` |
| `prepared.json` | `b1a9c9ff8a381e7d713e5dd6fbaff04de496aeafe0c0e46f48af8bab84d39fbf` |
| `source/lua/tests/rr/heap_battle_observation.lua` | `af050eedfd2f048f620b263ab2c6bc22c9031112ea338d224b474299392b3698` |
| `source/lua/rr/heap_snapshot.lua` | `07092c71645cefee76a8fe3df4f05a1d7e7ba6977b318a72e0ff6e87ece334dd` |
| Bound frozen03 ROM | `3b69f1c2518fb4487d53f56d6003f328f91d05a9603de7278d9bbce488546301` |
| Source-closure aggregate in run identity | `65412a81f081a5e2637792ebad3e576838588d916914885fb2933e4a70a1e52e` |
| Fixture manifest | `75837c3f53b1fca7713d9277279d9c9d21d388d882fca636e1e60e06df6ad357` |
| Fixture battery | `c8eb84b434b80dc5c7cac7b84a9a8106d78088078d277a860fb6e4b067b43d13` |

The result's observed host identifies process22300 as
`BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk`, with core-assembly SHA-256
`444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5`
and loaded `mgba.dll` SHA-256
`ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1`.
The actual ROM SHA-1 is `65C6B2739BAB54F8FFDA590D79BA551A0B7BAEC8`.
The observed heap component is complete; `capacity_proof`, `ownership_proof`,
`complete_peak_coverage` and `release_ready` remain false.
