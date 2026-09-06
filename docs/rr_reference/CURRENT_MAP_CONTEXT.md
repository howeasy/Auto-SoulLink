# Current RR map and canonical SaveBlocks

The connection captured in route40 changes the current map from3:1 to3:19 while
the player's ObjectEvent keeps its spawn map3:1. The sender/receiver correction
in67ac824 fixed those tags. Native ghost bookkeeping and guarded storage still
used the stale object fields. Compiled05 reproduced both rejection of a prepared
current-map transaction and acceptance of a stale spawn-map transaction.

The follow-on now reads the current map through canonical SaveBlock1 in the Lua
sampler, durable mailbox context and native participant. A missing/unaligned or
out-of-bounds pointer refuses preparation and guarded application; it cannot
downgrade a durable preparation to the compatibility path. The Lua preparation
also retains the SaveBlock1 address and layout, so either changing blocks later
submission. Native execution rechecks the current map on the actual write frame.
This is one prerequisite, not proof of complete storage effect or recovery.

## Binary pointer proof

`03003840` and `03003838` were incorrectly described as relocated pointer globals.
Actual RR `InitIntrHandlers` at08000688 programs DMA3 to copy08000248 to03003580
with control84000200. The copied interval includes ROM literals08000508 and
08000500, containing the initial SaveBlock1/2 bases0202552C and02024588.
Their RAM copies land at03003840 and03003838 inside IRQ code.

Actual `SetSaveBlocksPointers` at0804C058 writes globals03005008,0300500C and
03005010. Four independently seeded executions leave the IRQ aliases unchanged.
RR's two `mov r1,0` instructions at0804C062/64 disable randomized displacement,
explaining why the wrong aliases happened to contain usable base values.

Actual `LoadCurrentMapData` at08055274 follows03005008, including when a synthetic
IRQ alias disagrees. It selects the exact Viridian/Route1 layouts. The real RR
connection detour0904368C calls ApplyCurrentWarp08055198 and returns through
08055888 to this loader. Tests execute these primitives without routine stubs;
DMA register programming is observed, not simulated as a hardware DMA transfer.

The RR profile and inactive admission reader now use canonical SaveBlock1/2.
Because these globals share vanilla FireRed's addresses, RR profile selection
also checks the supported ROM's immutable base-stat and species-name pointers
(097B98EC and094042CC at080001BC and08000144). This recognizes supported RR before
save pointers exist without mistaking a plausible vanilla save for RR. These
markers select a reader profile; exact build/save/mode admission remains required.

## Candidate and validation

Candidate `patch/build/current-map-07-review` retains ABI2 and the2048-byte arena.
It adds no native `.data`, `.bss`, COMMON storage or arena relocation. The code is
12432 bytes; descriptor address is0837BF64. Native build provenance now also
includes the read-only Lua map helper used by the mailbox.

| Identity | Value |
|---|---|
| ROM SHA256 | `d77635218962ffe0ff0b44d7c797f514f896e6e54281f8d17a703f4e1ecc7c37` |
| Native build ID | `217a610a94bc6f602664d8a185417859e28b6b0326c0f8e0a551fb72217dd3e1` |
| Layout SHA256 | `3c10dcd8af7e5dc91684a6a14bc888f66f348464e463ab11db70b2b6d299885d` |
| UPS SHA256 | `1b08c8d233c5341fdc1522d365cf013b23ab1090ec4e0e4144851666f806b7d9` |

The195-test native suite passed on07, including15 current-map tests. Its layout
extraction equivalence test explicitly uses preserved05 against03; it still
requires whole-ROM equality after masking only the two original fingerprint
strings. A functional07 rewrite is not an equivalent-byte layout extraction.
Five older ghost-driver models were updated to provide a valid canonical pointer;
all their existing placement/cleanup assertions remain. No skip or deselection
replaced those cases. Set these explicit artifact selections:

```powershell
$env:SLINK_ARMGCC = 'E:/Google Drive/SLink/patch/vendor/armgcc/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin'
$env:PYTHONPATH = (Resolve-Path patch/build/native-cpu-deps).Path
$env:SLINK_RR_NATIVE_OUTPUT = (Resolve-Path patch/build/current-map-07-review).Path
$env:SLINK_RR_NATIVE_BASELINE = (Resolve-Path patch/build/ghost-probe-03).Path
$env:SLINK_RR_LAYOUT_EQUIVALENCE_OUTPUT = (Resolve-Path patch/build/layout-contract-05-review).Path
python -m pytest -q -p no:faulthandler tests/rr/native --rr-repo . --rr-rom 'E:/Google Drive/SLink/Pokemon - Radical Red.gba'
```

The two rival-stage CPU cases were added and passed separately afterward. The
combined unit/runtime run passed2896 tests,15 existing skips and11 subtests. Those
skips are not RR release evidence. Current07 has the narrow live case below;
the natural battle/ghost captures remain explicitly frozen03. Arena ownership,
full scene generations, rollback reconciliation and production admission are open.

## Live current-candidate follow-up

Run59 independently booted the copied battery on07 as an **unverified fixture
discovery**, then observed the exact player, party, mode and canonical pointers at
frame1657. Root reviewed the actual field screenshot and froze a separate07
fixture. The earlier03 fixture was not relabeled as07 evidence. Preparation58
failed before launch because its explicit generated-layout source list was
incomplete; that diagnostic is retained with the07 inputs.

`connection_context_probe.lua` then traverses the observed Viridian connection
using ordinary input. Only after reaching Route1 does it initialize the actual
production `peer_ghost_npc` receiver and publish a synthetic same-avatar packet.
Run60 retained a missing-`memory_gba` source-closure failure after traversal; the
isolated process did not fall back to repository files. Runs61 and62 completed.

Run62 has4676 structural assertions. Lua preparation and native ghost bookkeeping
both report current map3:19 while the player's OE still reports spawn map3:1.
The ghost has the expected512-byte allocation, allocated tile bits, private palette
kind/count/tag, owner binding, callback, marker, image/animation pointers and
matching OAM geometry. It remains owned through12 displayed frames. After clear,
tile/refcount maps equal their original snapshots and no active ghost object,
callback or marker remains. Every advanced frame checks field context, layout,
SaveBlock1, party count/bytes and mailbox health. Root reviewed the14 screenshots;
the ghost appears and disappears cleanly. The exact child exited normally and
original config/SaveRAM hashes stayed unchanged.

[Bound results and review](connection07_evidence.json) preserve each attempt.
The durable PING preparation remains **unsubmitted**, demonstrating context
sampling only. This case does not cover an existing ghost crossing the connection,
the live map-clear barrier, production sender/network transport, storage execution,
other avatars/MGM settings, or current07 battle behavior. Those gates remain open.
