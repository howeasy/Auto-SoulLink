# RR game heap and proposed top-of-heap reservation

Status: **candidate for further proof; no arena address or relocation is approved**.
The companion C/mailbox and frozen03 ROM are unchanged. All binary evidence below
uses RR4.1 base SHA256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
Available pret/CFRU sources supplied names and structure interpretations; the actual
RR bytes take precedence.

## Actual allocator and ownership

| Interface or state | Verified RR address / contract |
|---|---|
| `InitHeap(start,size)` | `0x08002B80`; stores root/size and constructs the first header |
| `Alloc(size)` | `0x08002B9C`; calls `AllocInternal` at `0x0800295C` |
| `AllocZeroed(size)` | `0x08002BB0`; calls `0x08002AE8`, then native CpuSet fill |
| `Free(pointer)` | `0x08002BC4`; calls `FreeInternal` at `0x08002A08` |
| `CheckMemBlock(pointer)` | `0x08002BD8`; structural checker `0x08002B28` |
| Heap root / size | IWRAM `0x03000A38` / `0x03000A3C` |
| Allocator search scratch | EWRAM `0x02020004`, `0x02020008`, `0x0202000C`; not spare storage |
| Standard heap | `[0x02000000,0x0201C000)`, size `0x1C000` / 112 KiB |

The 16-byte header is `{u16 allocated,u16 magic,u32 size,u32 previous,u32 next}`.
Magic is `0xA3A3`; `size` excludes the header. Requests are rounded to four bytes.
The first block's previous pointer and final block's next pointer identify the root.
If the unused remainder is less than 32 bytes, allocation absorbs it; otherwise it
creates another 16-byte header and a free remainder. `Free` coalesces adjacent free
blocks. None of the existing header fields is an unowned tag/generation field.

The game heap is separate from the retained newlib allocator and its disputed
metadata near `0x0203F754` and above. Finding a legitimate game-heap API does not
establish that the retained libc allocator is unused.

## Why an ordinary long-lived allocation fails

The following actual paths discard all ordinary heap allocations:

- `CB2_InitBattle 0x0800FD9C` calls `MoveSaveBlocks_ResetHeap 0x0804C0A4` immediately.
  `Task_BattleStart` selects that callback at `0x0807F672..74`.
- Map loaders call `InitOverworldBgs 0x080562B0` at `0x08056AB0/0x08056BD0`.
- Normal local field return runs `0x080567DC -> 0x08056808 -> 0x08056CD8`; its
  first stage calls `InitOverworldBgs` at `0x08056D04`.
- The two in-game-trade completion branches select `CB2_ReturnToField` at
  `0x0805230A..0C` and `0x08053766..68`.
- `InitOverworldBgs` calls wrapper `0x08056E74`, which calls the destructive save
  backup/reset routine. Credits use a separate no-reset initializer; this exception
  does not protect ordinary menu, trade, map or battle lifetimes.

`MoveSaveBlocks_ResetHeap` writes save backups into the heap **before** calling
`InitHeap` at `0x0804C120`. Hooking only `InitHeap` cannot rescue an ordinary
allocation already overwritten by those copies.

The executable reproduction in `test_game_heap_cpu.py` uses actual RR
InitHeap/Alloc/Free/CheckMemBlock with no routine stubs:

1. Initialize the normal heap and allocate 2,048 bytes: returned pointer `0x02000010`.
2. Store an old owner/generation token in that allocated payload.
3. An unrelated allocation/free leaves this block intact.
4. Reinitialize the heap: the first header becomes free, but the payload token remains.
5. `CheckMemBlock(oldPointer)` returns 1 even for that free block.
6. An ordinary subsequent allocation returns the same address, still containing the
   old token, with a valid allocated header and a successful structural check.

Thus payload magic, an allocated flag, a valid linked list and `CheckMemBlock` do
not identify which subsystem owns a reused block. An ordinary dynamic mailbox would
need a real owner registry and lifetime/generation contract, not a scan for stale bytes.

## Concrete reservation being assessed

Candidate arena: `[0x0201B800,0x0201C000)`, size `0x800` / 2 KiB.
Candidate game-heap limit: `0x0201B800`, leaving 110 KiB for the ordinary allocator.
This is a reservation from an existing, identified memory pool, not a claim that
these bytes were previously unused. Under the current ROM, normal `Alloc` can
legitimately allocate across the entire candidate range.

The proposed change would wrap the actual `InitHeap` entry and reduce **every
overlapping standard-heap initialization before the original routine writes its
root/header**. All currently decoded standard calls use start `0x02000000` and size
`0x1C000`; those arguments would become size `0x1B800`. A single missed unreduced
initializer gives the candidate back to the game's allocator, as a CPU test shows.

| Decoded direct InitHeap call | Naming / context |
|---|---|
| `0x080003F4` | Startup |
| `0x0800ACF6` | Link error |
| `0x0804C120` | Save-block move / heap reset |
| `0x08078956` | Title initialization |
| `0x0807928E` | Title scene transition |
| `0x08079BDC` | ReloadSave |
| `0x080EC8B4` | Intro setup |

The tests scan every aligned Thumb BL pair in the pinned ROM and assert this list.
No literal `InitHeap|1` pointer was found during the review. This remains a direct-call
inventory, not proof excluding computed calls, entry aliases, direct first-header
construction, ARM calls, self-modification or raw heap writes. Unexpected overlapping
initializer arguments need an explicit fail-closed policy; a void API cannot safely
pretend an unsupported initialization succeeded.

With a correctly initialized reduced heap, valid block metadata and ordinary
bounded requests, the existing allocator keeps all block headers and payloads below
the reduced end. Splits partition the existing block; coalescing recombines adjacent
blocks within it. Tests cover 13 alignment/end boundaries, four fragmented allocation
and coalescing cycles, a maximum-sized allocation and repeated reduced initialization.
The candidate tail is canaried and normal allocator writes into it are forbidden.
Original libc-region bytes are also canaried and remain unchanged in these tests.

These tests call the **unmodified** InitHeap with reduced arguments. They do not
implement or validate a new entry hook or approve the candidate address. Corrupt
metadata, invalid frees and overflowing allocation sizes are outside that bounded
allocator proof and remain ordinary game-memory failure risks.

## Raw users and clearing paths

Confirmed raw spans in the actual RR binary:

| User | Actual span / result |
|---|---|
| SaveBlock2 backup | `0x02000000 + 0xF24` bytes |
| SaveBlock1 backup | `0x02000F24 + 0x3D68` bytes |
| Storage backup | `0x02004C8C + 0x83D0` bytes |
| Combined save backups | Ends at `0x0200D05C`, below the candidate |
| Legacy battle frame table `0x08234698` | Sixteen `0x800`-byte spans from `0x02008000` through end `0x02010000`, below candidate |
| Legacy link-test send buffer | `0x02004000 + 0x2004` bytes, a source/read span below candidate |
| Decompression buffer | Starts `0x0201C000`, immediately above the candidate; neighboring-buffer correctness remains relevant |

All direct `gHeap` references in the available pret source are initializer calls,
these save backups, the legacy battle-picture table and link-test source. The CFRU
source search found no additional direct `gHeap` reference. RR source is unavailable;
this source inventory is not exhaustive proof about RR-specific calculated pointers.

Whole-EWRAM clears **do include the candidate** and bypass allocator limits:

- Startup passes `0xFF` to BIOS `RegisterRamReset` at `0x080003AC`.
- `ReloadSave` passes `RESET_EWRAM=1` at `0x08079B88`.
- The actual wrapper `0x081E3B80` executes SWI1. Soft reset eventually re-enters
  startup. Savestate loading can replace/rewind the whole arena and heap externally.

No separate whole-heap clear was found among the reviewed direct source users;
that is not a negative ownership certificate for unreviewed RR code or DMA paths.

## Raw pointer-value inventory

Ten aligned ROM words numerically fall inside the candidate. None had a matching
nearby Thumb PC-relative load in the reviewed scan. That fact alone proves nothing
about calculated/table-based consumers.

| ROM word | Value | Current classification |
|---|---|---|
| `0x08171C54` | `0x0201B925` | Script bytes `special 0x01B9; end`, not a 32-bit operand |
| `0x084087A4` | `0x0201BE63` | Inside valid LZ77 stream at `0x08407B9C` |
| `0x0853F778` | `0x0201BEDD` | Available pret map places this in Venonat cry data; RR consumer not exhaustively traced |
| `0x08D997AC` | `0x0201B800` | Inside valid LZ77 stream at `0x08D994D8` |
| `0x08EA24BC` | `0x0201BF02` | Inside valid LZ77 stream at `0x08EA1D68` |
| `0x0941DE40` | `0x0201BCE3` | Inside valid LZ77 stream at `0x0941DD68` |
| `0x0945E248` | `0x0201BE03` | Inside valid LZ77 stream at `0x0945E0B8` |
| `0x0961B5E8` | `0x0201B8FF` | Inside valid LZ77 stream at `0x0961B364` |
| `0x09626C90` | `0x0201BBFE` | Inside valid LZ77 stream at `0x09626AFC` |
| `0x09EC112C` | `0x0201BDE0` | Unclassified extended-ROM data; no pointer consumer established |

The tests preserve the exact ten-value inventory and validate seven containing LZ77
streams. Compressed-data classifications prevent treating arbitrary asset bytes as
confirmed RAM references; they do not establish that the proposed tail is free or
immune to raw writes.

## Capacity and the retained libc path

The reservation removes 2 KiB, approximately 1.79% of the original heap. Fragmentation
can make the practical cost larger than that fraction. Companion allocation success
alone is insufficient: ordinary battle/menu/trade allocations must still succeed.

Actual game allocation exhaustion at `0x080029EA..F2` calls
`AGBAssert 0x081E3B14 -> AGBPrintf 0x081E39D8 -> vsprintf 0x081E5FD4`.
The caller passes `nStopProgram=1`. After printing/flushing, RR's assertion contains
debug halfword `0xEFFF` at `0x081E3B38`; do not assume harmless NULL recovery merely
because `AllocInternal` has a later return-zero instruction.

A CPU reachability test stops deliberately at the actual vsprintf entry. It uses no
fabricated return and makes no claim about later formatter or `_malloc_r` execution.
An exploratory continuation reached formatter `0x081E60E6`, dereferencing reent+0x38
through `_impure_ptr` at `0x0203F754`, then failed because synthetic RAM had null
reent. That is not a claimed game crash or proof of native malloc reachability.
It is concrete evidence that a legitimate game-allocator error path enters retained
libc formatting. Its metadata must remain untouched by any companion reservation.

## Conditions before implementation or release

1. Complete and review the entry wrapper/trampoline contract, including all initializers,
   argument overflow/overlap rules, first-header alternatives and pre-initialization state.
   Check the actual reduced root/header before admitting companion writes. A legacy
   savestate with an unreduced heap cannot be clipped in place while allocations exist.
2. Prove the tail reservation against raw CPU/DMA writes through supported scenes,
   including battle entry/return, menus, maps, trade/evolution, reload, credits and postgame.
   Zero hits alone are insufficient; instrumentation needs verified positive controls
   and explicit coverage of all relevant writers.
3. Record free total, largest free block and allocation failures under peak battle,
   graphics, calculator, party/PC, native UI and trade load in both MGM states. Include
   fragmentation cycles and a contained failure-path test. The original allocator's
   stop assertion must not become a routine product behavior after the reduction.
4. Separate ownership from initialization. Ownership would come from the admitted
   reservation contract, never from stale payload magic. An immutable ROM descriptor
   can publish the reserved base/size/layout without native mutable `.data/.bss` or
   stolen allocator bits. All companion state, Lua address readers and admission
   manifests would need one coherent versioned layout change.
5. Ordinary heap resets should leave the reserved arena and outstanding native
   completion/payload leases intact. Whole-RAM resets and savestate loads must instead
   revoke the host context before CPU resumes and require durable reconciliation.
   A restored valid signature/receipt cannot authenticate the current command generation.
6. Verify native reader lifetimes and scene cleanup separately. Moving state does not
   repair stale engine sprite/window pointers or authorize pending async effects.

The candidate is more defensible than an unexplained gap because it can be explicitly
reserved from a known pool. The allocator-bound tests support continued investigation;
the remaining raw-access, reset, capacity and protocol gates prevent an approval now.

## Reproduce the 20 CPU/static checks

```powershell
python -m pip install --target patch/build/native-cpu-deps -r tests/rr/native/requirements-cpu.txt
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
python -m pytest -q -p no:faulthandler tests/rr/native/test_game_heap_cpu.py --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
python -m ruff check tests/rr/native/test_game_heap_cpu.py
```

All 20 checks passed during this review. The Windows faulthandler convention and
CPU-only limitations are documented in `patch/src/NATIVE_GHOST_MOTION.md`.
