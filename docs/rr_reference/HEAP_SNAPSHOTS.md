# Read-only RR heap snapshots

`lua/rr/heap_snapshot.lua` reads the actual game's heap root/size and16-byte
block headers into a detached observation. It reports free bytes, largest free
block, allocated payload bytes, header overhead and individual block extents.
Total free space is distinct from the largest allocatable block under fragmentation.

The reader validates aligned in-EWRAM bounds, flags, magic, previous/next links,
contiguous partitioning and exact termination at the declared heap end. It rechecks
the frame and root/size after traversal. Invalid, unavailable or changing snapshots
return `nil, reason`; they never become a zero-filled capacity report. The default
512-block budget is explicit and an exceeded budget remains unavailable.

Callers must supply a coherent stopped-instruction or frame-boundary observation
context. Rechecking frame/root values cannot authenticate ownership, exclude an
independent host writer or identify an ABA reset. The module makes no writes,
allocations, reservations, gameplay/admission decisions or claim that GPU tiles and
palettes are available. Both `capacity_proof` and `ownership_proof` remain false.
It is currently selected only by diagnostic tests/probes.

Nine controlled-RAM checks cover fragmentation and invalid/changed/bounded reads.
An additional unstubbed exact-ROM CPU case runs InitHeap, Alloc and Free, verifies
the reader against real split/coalesced headers, and checks reduced initialization.
All10 cases pass. This is a parser/primitive result, not peak gameplay pressure or
approval of the proposed heap-tail arena.

```powershell
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
python -m pytest -q -p no:faulthandler tests/unit/test_rr_heap_snapshot.py tests/rr/native/test_heap_snapshot_cpu.py --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
```
