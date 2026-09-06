# CPU replay of the observed run65 heap schedule

The observed allocation schedule fits the original heap and the proposed reduced
heap in a CPU-only **allocator metadata replay**. All234 operation pairs replayed
without an allocator assertion or unknown free. This does not approve an arena
reservation, execute gameplay, or establish a complete memory peak.

| Measured schedule result | Original `0x1C000` | Inactive guard: `0x1B800` |
|---|---:|---:|
| Heap size | 114,688 | 112,640 |
| Lowest sampled free bytes | 11,608 | 9,560 |
| Lowest sampled largest free block | 11,608 | 9,560 |
| Highest sampled allocated bytes | 102,232 | 102,232 |
| Allocation pointers differing from run65 | 0 | 0 |
| Final free bytes / largest free block | 103,072 | 101,024 |
| Final allocated bytes / header bytes | 11,520 / 96 | 11,520 / 96 |

These figures describe this one boot, route, natural battle, Run and return
schedule from the MGM-on fixture. The minimum is not a global bound. Other
settings, party/species combinations, menus, trade, battles, campaign stages,
fragmentation histories and unobserved direct callers remain untested here.

## Observed workload and baseline qualification

`tests/rr/fixtures/heap_workload_65.json` is an approximately50KB derived fixture containing all
234 pairs from the immutable run65 result. Each row retains the call ID, frame,
operation, caller, source arguments, returned allocation pointer and before/after
heap metrics. The shared `metric_fields` array defines the compact metric order.
It also retains the run's full identity (ROM, fixture, source closure, observer,
emulator/config and binding hashes) and the unavailable initial observation.

The test requires the exact derived fixture hash after canonicalizing CRLF to LF,
the exact base RR ROM, and Unicorn2.1.4. The frozen03 ROM used by run65 was read
independently and its allocator region `08002800..08002BFF` and assertion/CpuSet
region `081E3B14..081E3B67` were byte-identical to the pinned base ROM. Their hashes
are retained in the derived fixture and checked against the CPU-test ROM.

The original-size replay must reproduce every available entry snapshot, every
post-call snapshot and every returned allocation pointer exactly. The test uses
the actual ROM's InitHeap, Alloc and Free instructions, with no routine stubs.
The baseline's117 allocation pointers match the physical trace; each of110 frees
must refer to a currently live allocation identity. All seven InitHeap calls clear
the logical allocation map. The frame723 initializer discards two still-live
title allocations, as the observed reset requires; old identities never carry
across that reset.

Pre-Init unavailable snapshots stay unknown. The replay does not manufacture the
raw save-copy contents responsible for invalid pre-Init headers. It executes the
actual initializer to build the next header, then requires the exact observed
poststate. Available pre-Init snapshots must still agree. An unobserved metadata
change affecting those boundaries, a missing allocation, unknown free, pointer
drift, metric drift or unsupported initializer causes failure. Matching these
boundaries does not exclude transient/direct/raw activity between them.

## Explicit AllocZeroed abstraction

The schedule uses actual `Alloc` for each of the42 `AllocZeroed` entries, retaining
the requested size and expected pointer. It does **not** implement a BIOS stub,
zero the payload in Python, advance past an unimplemented service, or fabricate
a return from the original Zeroed routine.

Each of those42 baseline states is independently copied to a separate CPU model.
That model executes actual `AllocZeroed` at `08002BB0`, through
`AllocZeroedInternal` at `08002AE8`, and stops immediately before the actual SWI0B
instruction at `081E3B64`. The check requires:

- Exactly one execution of `AllocInternal` at `0800295C`.
- Full heap bytes identical to the corresponding completed Alloc call.
- A zero word at the supplied source address and the expected allocation as
  destination; the control value is `0x05000000 | (rounded_size / 4)`.
- A positive rounded fill length wholly inside that allocated payload, excluding
  all headers, plus the exact register/stack-only return suffix after CpuSet.

The actual RR instructions round size to four bytes, construct a word-fill
control and pass the retained pointer. The pinned mGBA
[CpuSet implementation](https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/gba/hle-bios.s#L190)
uses the fill and word flags to repeat one source word across the destination
count while preserving r4/r5. This source contract supports the payload-only
abstraction; that BIOS implementation is **not executed** in this replay.
Any actual CPU interrupt or allocator assertion outside the deliberate prefix
stop is an unsupported-service failure. The results explicitly set
`zeroed_gameplay_execution=false`.

## Reduced schedule and memory boundary

The reduced test first runs the full original-size baseline. It then compiles the
existing inactive `patch/research/heap_tail_guard.S` into pytest scratch space and
installs its detour only in Unicorn's private ROM mapping. Every observed InitHeap
still receives the original arguments. The actual guard clips the pool before
the stock initializer writes its metadata. No cartridge artifact or production
source is changed. The test helper's `0x0A100000` address is outside this harness's
stock-ROM mapping, not a proposed production code location or a claim about GBA
mirror windows.

The schedule maps old allocation identities to new returned pointers before
Free. This run happened to retain every pointer; that equality is checked rather
than assumed by the mapping. A byte-pattern canary covers the entire proposed
tail, and a write hook rejects any executed allocator write there. All heap
headers must form a valid, bounded, contiguous linked list after every operation.

The first test attempt incorrectly required all upper EWRAM to stay unchanged.
It found the allocator's legitimate search globals at `02020004`, `02020008` and
`0202000C`. Actual literals at `08002998..080029A3` and executed stores at
`08002962`, `08002966`, `080029AE` and `080029E6` establish their use. The final
test permits only those exact address/instruction/width combinations outside the
pool; it does not silently omit the entire upper region. Both schedules executed
3,024 such verified scratch writes. Every other upper-EWRAM byte, including the
retained libc area, stayed unchanged in this CPU test.

This is not raw-writer coverage: no game payload consumers, DMA, callbacks,
interrupts, save-copy routines, whole-RAM reset, state-load or JOYBUS route run in
the model. Nor does successful allocation show that a companion's pending
receipts/resources would survive those paths. `capacity_proof`, `ownership_proof`,
`complete_peak_coverage` and `release_ready` remain false.

## Validation and provenance

Seven focused cases cover the complete baseline/Zeroed-prefix proof, reduced
guard replay, and five deliberate schedule faults. Missing ROM/toolchain/Unicorn
inputs fail; the selected lane has no skip or xfail path. The JUnit result records
the compiler, assembler, linker, objcopy/nm/size hashes, inactive guard source and
binary hashes, harness source hashes and both replay summaries. Toolchain
fingerprints describe the actual tools used; they are not a global host trust or
release attestation.

The final source-bound run `patch/build/heap-workload-replay-03.xml` passed all
seven cases in12.49 seconds; Ruff passed. No emulator was launched for this task.

```powershell
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
$env:SLINK_ARMGCC = 'E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin'
python -m pytest -q -p no:faulthandler tests/rr/native/test_heap_workload_replay.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba' -o junit_family=legacy --junitxml=patch/build/heap-workload-replay-review.xml
python -m ruff check tests/rr/native/test_heap_workload_replay.py
```

The explicit dependency is `tests/rr/native/requirements-cpu.txt`; the command
above uses the already installed isolated runtime. Choose a fresh JUnit output
name for each evidence attempt.

| Artifact | SHA-256 |
|---|---|
| Actual65 result JSON | `2c3d2c472ebb1cf926f5ce9d6d2e784b33fab2e4371218d25e51628012d0c251` |
| Final source-bound JUnit, `heap-workload-replay-03.xml` | `5d3435f679efa42211f69cbe2d1396f1cdd918c987fb846988e52fa324f698f5` |
| Derived fixture, canonical LF | `9e92051e5d06b5bdaf8cb192cf532ed2c489bc1d8b9cd79e7353e40beb480a23` |
| Frozen03/base allocator-region bytes | `92456228cc92274e40ee0865f864c9987f2329ee5da0a737300c27639f9e5b28` |
| Frozen03/base assertion/CpuSet-region bytes | `b0af88298af37480a4d7f749bae805c6c611364e73995ca800606c490decc047` |
| Inactive guard source, canonical LF | `f9b83df16a19435683e08f8751f51d4f8216a798ccf82bdef7f9177e64ba69bd` |
| Compiled inactive guard bytes | `248454f22fbf963936e1d7491148d51b407550897296d2959788e5b9bf5ff8ea` |

The source result remains at
`C:/Users/howar/AppData/Local/Temp/slink-rr-native-probes-01a072f9/runs/heap_battle_65_a/results/result.json`.
The retained first JUnit attempt, `patch/build/heap-workload-replay-01.xml`, failed
the overly broad non-pool canary condition; it is not a workload allocation
failure. Later attempts preserve that failure rather than overwrite it.
