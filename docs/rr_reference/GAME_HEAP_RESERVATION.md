# RR game heap and proposed top-of-heap reservation

Status: **candidate for further proof; no arena address or relocation is approved**.
The companion C/mailbox and frozen03 ROM are unchanged. All binary evidence below
uses RR4.1 base SHA256
`679d112cdfe699c2793d82c7e7999ac9dfca9e222ad5a85d4f8f1e457cd0283f`.
Available pret/CFRU sources supplied names and structure interpretations; the actual
RR bytes take precedence.

An inactive entry wrapper and 33 additional checks now exist under
`patch/research/heap_tail_guard.S` and `tests/rr/native/test_heap_tail_guard_cpu.py`.
They are excluded from the production build. The later GameCube/JOYBUS section
records a real conditional raw conflict and its narrower pinned-mGBA qualification.

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
| `0x09EC112C` | `0x0201BDE0` | Audio-like data with a plausible sample header nearby; no consumer established |

The tests preserve the exact ten-value inventory and validate seven containing LZ77
streams. Compressed-data classifications prevent treating arbitrary asset bytes as
confirmed RAM references; they do not establish that the proposed tail is free or
immune to raw writes.

Further inspection found a plausible GBA WaveData header at `0x09EBFAD0`:
type 1/status 0, frequency `0x02B11000` (44,100×1,024), loopStart 0 and size 98,676.
The candidate word occurs after that header among audio-like packed bytes. No direct
reference to the header or verified sound consumer has been established. This is
additional classification evidence, **not a resolved pointer-use/ownership claim**.
Do not close the `0x09EC112C` item from byte appearance or missing references.

## Inactive InitHeap entry-wrapper proof

`patch/research/heap_tail_guard.S` proposes an eight-byte literal detour at
`0x08002B80..87`. It uses only r2/r3 before replaying the displaced original
instructions: push caller LR, store heap root, load the size-global address, then
branch to original continuation `0x08002B88`. The stock routine performs the size
store, header construction and return. The helper has no `.data`, `.bss`, mailbox
initialization or arena writes and is not referenced by `patch/tools/build.py`.

Supported synthetic inputs have aligned start/size, at least a 16-byte header and an
overflow-free range wholly within EWRAM. Nonoverlapping ranges pass unchanged;
overlapping ranges beginning before the candidate are clipped to its start. A range
beginning inside the candidate or leaving less than header space is rejected.
Rejection is an observable, non-returning loop before any RAM or stack write.
That loop is a research fail-closed behavior, not an approved user-facing recovery
policy; the void original API must not falsely return after a refused initialization.

Private CPU-memory tests patch only their in-memory copy of the stock entry and
map the compiled helper at `0x0A100000`. That address is outside this harness's
stock-ROM mapping, **not universally outside GBA cartridge space**; hardware ROM
mirror windows exist. It is not a proposed production code location.

The tests compare r0-r12, final SP, full EWRAM/IWRAM contents and final NZCV flags
against the unmodified routine called with the effective size. Both four- and
eight-byte-aligned caller stacks pass. All seven decoded caller BL instructions
enter the detour and return to their original next instruction. Rejection cases
preserve caller LR, callee-saved registers and all RAM. The original API is void;
matching r0's original return-address residue is compatibility evidence, not a new
result-code API.

This is function-level ABI evidence. InitHeap and the underlying allocator are not
made interrupt-safe by the wrapper; the original search globals are non-reentrant.
Ordinary save-block reset clears VBlank/HBlank callbacks before copying, but pending
DMA and other interrupt consumers still require contextual proof. The wrapper does
not prove startup admission, runtime allocation pressure or safe receipt lifetime.

## Conditional GameCube raw writes and pinned-mGBA scope

The prior source search for the `gHeap` symbol missed a real assembly user of literal
`0x02000000`: the retained GameCube multiboot subsystem.

At `0x081DBF58..64`, the actual receiver accepts a size word below `0x4000` and
stores `2*(value+1)` as the remaining word count. Destination starts at `0x02000000`.
At `0x081DBF88..92`, it reads `JOY_RECV`, stores a word through the current
destination and advances. The accepted bound can cover `0x20000` bytes, including
the entire proposed tail. CPU tests execute the real size parser and an actual
receiver store into the tail **after reduced InitHeap**. These tests supply synthetic
peripheral state; they do not claim ordinary GBA buttons can create a GameCube peer.

There is another conditional bypass: on successful progress 2 and received game code
`0x65366347`, copyright setup calls CpuSet at `0x080EC7D6` to copy `0x28000` bytes
from the bundled Colosseum image into EWRAM. This application handoff also overlaps
the tail and is not governed by InitHeap. A CPU breakpoint test captures these actual
call arguments from the stock branch; it stops before BIOS execution and does not
claim a real mGBA transfer occurred.

The actual startup contract is visible in RR:

- `sGcmb` is `0x0203AAD4`, progress byte at `+2`.
- Copyright setup installs the GCMB serial callback at `0x080EC726..28` and calls
  `GameCubeMultiBoot_Init` at `0x080EC72E`; main processing runs at `0x080EC746/77C`.
- The normal progress 0 path calls `GameCubeMultiBoot_Quit` at `0x080EC7F4`, restoring
  ordinary `SerialCB 0x0800B799` at `0x080EC7F8..FA` before intro/field entry.
- `GameCubeMultiBoot_ExecuteProgram` is selected at `0x080EC7DE` only on successful
  transfer progress. Generic post-intro admission cannot be inferred from a payload
  signature alone; normal completion/progress 0 is an explicit qualification point.

The supported target is the pinned standalone BizHawk mGBA peer, not hardware
multiboot. The installed `mgba.dll` was read and matched **byte-for-byte** to the
official BizHawk 2.11.1 asset: 775,680 bytes, SHA256
`ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1`.
That release pins mGBA submodule `94b1578f8545d8ad17bb4036dba908612d5731e2`.
The source/DLL correspondence was checked; the DLL was not independently rebuilt.
URLs and exact source hashes are in `mgba_joybus_source_manifest.json`.

The pinned [BizHawk native bridge](https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/platform/bizhawk/bizinterface.c)
creates a standalone core and attaches rotation, rumble and luminance peripherals,
not a link-port driver. Its frontend frame API carries buttons/sensors, not JOYBUS
messages. The [build list](https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/platform/bizhawk/base.mak)
includes GBP/lockstep support but not the Dolphin transport.

The pinned [SIO implementation](https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/gba/sio.c)
initializes the driver to NULL. Its dummy completion path covers normal 8/32 and
multiplayer, not JOYBUS. External `GBASIOJOYSendCommand(JOY_RECV)` is the path that
sets received status/data and raises its interrupt. Ordinary CPU writes to JOYCNT
clear relevant status bits; unhandled receive-register writes retain the old value.
The [GBP driver](https://github.com/TASEmulators/mgba/blob/94b1578f8545d8ad17bb4036dba908612d5731e2/src/gba/sio/gbp.c)
handles only NORMAL32, not a GameCube JOYBUS transport.

The reviewed private config independently reads `OverrideGbPlayerDetect=false`,
`SubframeInput=false`; the current host adapter exposes no serial-injection API.
Under a fresh/reset state, this pinned host/bridge and no externally attached or
injected peripheral state, no supported producer for the GCMB receive stream was
identified. The hardware counterexample therefore does **not** by itself make the
mGBA-scoped reservation impossible. It does require explicit host/config and normal
post-intro qualification. Imported/mutated serial state, other frontends/hardware,
native peripheral injection or changed driver bindings invalidate that argument.
Direct runtime SIO-driver inspection and scene/admission enforcement remain gates.

## Capacity and the retained libc path

The extended-ROM numeric match at `0x09EC112C` now has stronger bounded data
classification in [PCM_LITERAL_REVIEW.md](PCM_LITERAL_REVIEW.md): two exact
compressed-wave boundaries and actual RR decoder execution consume its bytes as
DPCM data without dereferencing the EWRAM-looking word. The natural sample
consumer remains unidentified; this does not close the global raw-access gate.

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
7. Preserve the scoped GameCube exclusion above and handle any unsupported transfer
   state before companion admission. Do not silently claim hardware compatibility or
   let a native frame hook write a supposedly exclusive tail during a raw handoff.

The candidate is more defensible than an unexplained gap because it can be explicitly
reserved from a known pool. The allocator-bound tests support continued investigation;
the remaining raw-access, reset, capacity and protocol gates prevent an approval now.

## Reproduce the 53 CPU/static checks

```powershell
python -m pip install --target patch/build/native-cpu-deps -r tests/rr/native/requirements-cpu.txt
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
$env:SLINK_ARMGCC = 'E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin'
python -m pytest -q -p no:faulthandler tests/rr/native/test_game_heap_cpu.py tests/rr/native/test_heap_tail_guard_cpu.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
python -m ruff check tests/rr/native/test_game_heap_cpu.py tests/rr/native/test_heap_tail_guard_cpu.py
```

All 53 checks passed during this review (20 original allocator/static checks plus
33 inactive-wrapper/conditional-conflict checks). The Windows faulthandler convention and
CPU-only limitations are documented in `patch/src/NATIVE_GHOST_MOTION.md`.
