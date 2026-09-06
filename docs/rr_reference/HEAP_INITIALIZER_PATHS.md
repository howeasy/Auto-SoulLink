# RR heap initializer entry and bypass audit

The pinned base ROM contains **seven** direct Thumb BL patterns targeting InitHeap
at `08002B80`, not nine. The first-header builder has one such caller, inside
InitHeap. No additional natural initializer bypass is established by this audit.
The absence of additional branch/pointer patterns is not a complete call graph
or ownership proof.

There is a concrete capability that qualification must account for: directly
calling either header builder can enlarge the allocatable heap while leaving
the stored root and size unchanged. Actual stock `CheckHeap` accepts that state.
The checked `lua/rr/heap_snapshot.lua` reader rejects its out-of-bounds header.
This is a constructed CPU counterexample, not evidence that normal gameplay
currently invokes that bypass.

## Confirmed direct branch inventory

| Call instruction | Target | Reviewed context |
|---|---|---|
| `080003F4` | `08002B80` InitHeap | Startup |
| `0800ACF6` | `08002B80` InitHeap | Link-error setup |
| `0804C120` | `08002B80` InitHeap | Save-block move and heap reset |
| `08078956` | `08002B80` InitHeap | Title initialization |
| `0807928E` | `08002B80` InitHeap | Title scene transition |
| `08079BDC` | `08002B80` InitHeap | ReloadSave |
| `080EC8B4` | `08002B80` InitHeap | Intro setup |
| `08002B8A` | `08002948` PutFirstMemBlockHeader | InitHeap's header construction |
| `08002952` | `0800292C` PutMemBlockHeader | First-header construction |
| `080029BA` | `0800292C` PutMemBlockHeader | AllocInternal's split-header construction |

The earlier inactive-guard CPU suite exercised all seven InitHeap BL instructions
and their returns. Actual run65 observed five distinct InitHeap call sites:
startup, intro, both title sites and save-block reset. The reset site executed
three times, producing seven observed initialization pairs. Link-error and
ReloadSave initialization are static/CPU evidence here, not claimed live run65
coverage. Context/call-path research is retained in
[GAME_HEAP_RESERVATION.md](GAME_HEAP_RESERVATION.md).

## Entry aliases, ARM patterns and literal values

The scan checks every halfword-aligned Thumb BL pair, short unconditional branch
and short conditional branch over the full32MB ROM. It also checks aligned ARM
B/BL encodings. Targets include InitHeap's instruction span `08002B80..08002B91`
and the header-builder spans `0800292C..0800295B`. There are no additional Thumb
targets in those spans. ARMv5-only immediate BLX encodings are not treated as
ARM7TDMI instructions.

One ARM B pattern at `08507FDC`, raw word `EAEBEAEB`, numerically targets
`08002B90`. That word falls within the PCM payload of a bounded WaveData header
at `08506C68` (type0, status`4000`, frequency27400192, loop5495, size13006).
The payload ends at `08509F46`; another valid wave header begins at the next
aligned address `08509F48`. A tone-like data pointer at `0848C534` references the
first header. This supports a data classification, not a verified ARM caller or
a complete natural audio-consumer trace. A plain ARM branch would also retain
ARM state rather than switch to the Thumb InitHeap epilogue.

The byte-level literal search includes both even addresses and Thumb-tagged odd
values at every byte offset, including unaligned occurrences. No literal pointer
to the entry or interior of InitHeap or PutFirstMemBlockHeader was found. Three
pointer-like values refer to the generic PutMemBlockHeader interior:

| Literal value | ROM occurrence | Interpretation |
|---|---|---|
| `08002930` | `0870467B` | Unaligned occurrence; operand/asset consumer unresolved. |
| `08002935` | `0982A331` | Unaligned occurrence; operand/asset consumer unresolved. |
| `08002940` | `09588268` | Inside a complete2048-byte LZ stream `09587FD4..09588499`; stream pointer occurs at `097FCA94`. |

These values are not silently removed from the inventory. An interior value in a
blob is not itself proof of an executable call; the two unresolved occurrences
remain research items. Conversely, compressed bytes or missing literal references
cannot rule out calculated control flow or malicious/corrupted pointers.

## Heap root and size access

The canonical globals are root `03000A38` and size `03000A3C`. All literal
occurrences and their matching PC-relative loads are retained:

| ROM literal | Value | Thumb load | Use |
|---|---|---|---|
| `08002B94` | `03000A38` | `08002B82` | InitHeap writes root at `08002B84`. |
| `08002B98` | `03000A3C` | `08002B86` | InitHeap writes size at `08002B88`. |
| `08002BAC` | `03000A38` | `08002BA0` | Alloc reads root at `08002BA2`. |
| `08002BC0` | `03000A38` | `08002BB4` | AllocZeroed reads root at `08002BB6`. |
| `08002BD4` | `03000A38` | `08002BC8` | Free reads root at `08002BCA`. |
| `08002BE8` | `03000A38` | `08002BDC` | CheckMemBlock reads root at `08002BDE`. |
| `08002C10` | `03000A38` | `08002BEE` | CheckHeap reads root at `08002BF0/2BF4/2C04`. |
| `08DAF836` | `03000A38` | None found | Unaligned compressed asset bytes. |

The last occurrence lies in a complete2048-byte LZ stream from `08DAF770` to
`08DAFA21`. A descriptor at `08235684` contains pointer`08DAF770`, size2048 and
tag187. The test decompresses the entire stream and checks every backreference;
it does not claim that a natural current RR graphics path selects this descriptor.
No aligned ARM PC-relative load to any of these pools was found.

An aligned literal-value scan across IWRAM mirror encodings found only the seven
canonical table entries above. It does not cover calculated addresses, bytewise
assembly or every possible unaligned mirrored encoding. Actual InitHeap/Alloc/
Free/CheckMemBlock/CheckHeap CPU execution records only the two expected root/size
stores, at `08002B84` and `08002B88`, for that tested operation sequence. This is
positive instruction evidence, not a claim that those are the only possible global
writers throughout RR.

## Actual header-builder counterexample

The new CPU cases install only the existing inactive guard in private Unicorn
memory. After InitHeap, the actual globals contain `(02000000,0001B800)` and the
stock initializer creates a reduced first header. Each case then deliberately
invokes one existing header builder directly:

1. `PutFirstMemBlockHeader(02000000,0001C000)`, or
2. `PutMemBlockHeader(02000000,02000000,02000000,0001BFF0)`.

Both produce a single free header covering the original larger pool. The globals
still contain the reduced size. Actual `CheckHeap()` returns1 because it checks
magic/link consistency and does not bound the ring by `sHeapSize`. The checked Lua
reader returns `nil,"invalid_block_extent"`. Actual `Alloc(0x1BFF0)` then returns
`02000010`, whose payload extends through `0201C000`, overlapping the whole
proposed reserved tail. No routine stubs or fabricated returns are used.

This proves why qualification must check the real header extent and why an
InitHeap-only detour cannot intercept arbitrary direct header reconstruction.
The reviewed direct caller of PutFirst is inside InitHeap, so that normal path
does pass through the guard. The normal PutMemBlockHeader split caller partitions
an existing free block; it is not independently shown to restore a larger pool.
No new natural caller is claimed from these synthetic invocations.

## Remaining coverage and release conditions

The direct pattern inventory does not exclude computed BX targets, calls through
RAM, address arithmetic, alternate entry points outside the declared spans,
copied/decompressed code, raw first-header stores, heap metadata corruption,
DMA/BIOS copies or whole-RAM resets. Save-block backup lengths, conditional
GameCube writes and hardware/host state-load semantics retain their separate
gates. A root/size pair or stock CheckHeap result cannot be used as a shortcut for
the checked extent proof. No production detour or arena relocation is activated
by this audit, and live raw-writer observation remains separate work.

## Reproduce

```powershell
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
$env:SLINK_ARMGCC = 'E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin'
python -m pytest -q -p no:faulthandler tests/rr/native/test_heap_initializers_cpu.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba' -o junit_family=legacy --junitxml=patch/build/heap-initializers-review.xml
python -m ruff check tests/rr/native/test_heap_initializers_cpu.py
```

Eight cases passed in4.79 seconds; Ruff passed. The selected lane requires the
exact base ROM and isolated Unicorn dependency; guard compilation uses pytest
scratch output. The second exploratory JUnit attempt retained an overly strong
empty-interior-pointer assumption that the expanded byte scan disproved. Its
failure is preserved; the final inventory explicitly includes those three values.

| Evidence | SHA-256 |
|---|---|
| Base RR ROM | `679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f` |
| Tested source bytes, `test_heap_initializers_cpu.py` | `8bbc2c56a2120fcaa1f30af752e9a2e7349832732b7892baba27260c5eabe304` |
| `patch/build/heap-initializers-03.xml` | `e580c60e5d234e215b34922915ad276f299228af05f646405a3693c60e3d963c` |

The source hash is the actual tested checkout-byte hash; Git EOL normalization
can change it on another checkout. Reproduction must report the new source and
result hashes rather than claim identity from modification time. No emulator
was launched in this task. These tests are function/pattern evidence; complete
call-graph, memory-ownership and release approval remain unresolved.
