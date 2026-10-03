# Gen 4 (HG/SS) companion — per-title sources (card C2)

`patch/src/nds/common/` owns the ABI and the producers. This directory owns **game facts
only**: where the mailbox is, when the service runs, and which module is compiled in.

| File | Role |
|---|---|
| `beacon.h` | Title-private block layout (D-C2-1), capability policy, the SysTask heap state block, `Slink_NDS_Register()` |
| `beacon.c` | Arena placement, cookie/liveness, the reset latch, the per-visit body |
| `dispatch.h` / `dispatch.c` | Every producer, every visit, no opcode pre-route |
| `README.md` | This file: integration points, addresses, resolved ambiguities |

`patch/src/nds/common/abi.h` is used **UNMODIFIED**. Nothing here includes it with a
game header in the same translation unit as `trade_targets/abi.h` (that pairing trips
`abi.h:31-33`).

## Build include paths

```
-I patch/src/nds/common -I patch/src/nds/gen4
```

`beacon.h` includes `"abi.h"`; `beacon.c` additionally includes `global.h`,
`sys_task_api.h`, `system.h`, `save.h`, `player_data.h`, `<nitro/os/arena.h>` and
`<nitro/os/tick.h>` from the pinned pret tree.

## The one integration point (HG/SS)

`src/main.c`, **after `InitSystemForTheGame()` (`src/main.c:51`) and before the first
`RegisterMainOverlay` (`src/main.c:77`)**:

```c
void NitroMain(void) {
    InitSystemForTheGame();
    Slink_NDS_Register();          // <-- SLink
    InitGraphicMemory();
    ...
```

and a declaration in `src/main.c`:

```c
void Slink_NDS_Register(void);
```

`InitSystemForTheGame()` creates `gSystem.mainTaskQueue` (`src/system.c:123-126`), so
the task is armed before any overlay runs, and the queue drains from `NitroMain`'s loop
(`src/main.c:111`) — outside every app, which is what makes the tick app-independent.

There is **no linker section and no static object**. Two consequences the coordinator
must plan for:

- The companion is **static ARM9 C**, not an overlay. It has to be added to the ARM9
  object list (`main.lsf`) so `main.c` can `bl` to it at `:51`, and the ARM9 image is
  BLZ-compressed, so the compressed size changes. That is the shared writer's job
  (card 1, Gen 5-led), not this card's.
- **Do not add a static `.bss` symbol.** `beacon.c`/`dispatch.c` have no file-scope
  object at all; a static would move `0x021E5900` and with it every overlay address and
  every pinned hook site.

## Mailbox address (C1's accepted span)

| Fact | Value |
|---|---|
| ITCM arena start (`SDK_SECTION_ARENA_ITCM_START`, census W1) | `0x01FF8620` |
| Accepted span (4 KiB, `SLINK_ARENA_SIZE`) | `0x01FFEC00 .. 0x01FFFC00` (end exclusive) |
| `SLINK_GEN4_ARENA_DELTA` in `beacon.c` | `0x65E0` |
| Host read window (BizHawk `"Instruction TCM"`) | domain offset `0x6C00` |
| Shared regions inside the span | mailbox `0x00`, witness `0x50`, blob `0x100`, text `0x360`, menu `0x560`, info `0x6E0`, control `0x800`, title-private `0xE00` |

The **absolute** span base is deliberately absent from the `.c`/`.h`: the C1 census's W2
row FAILs a build whose source carries a 7–8 hex-digit literal inside the span
(`tools/gen4_mailbox_census.py:83,188-197,217`), and this source is compiled into the
tree the census scans. `beacon.c` derives the base from `SDK_SECTION_ARENA_ITCM_START`
plus a delta and **fails closed** if that symbol is not the value the census recorded —
nothing is stamped and the host reads no beacon, which is the correct "not live" reading.

## Title-private block (`SLINK_GEN4_TITLE_OFFSET`, 64 bytes)

D-C2-1 rules: shared code never touches it, the title versions it itself, it is outside
the witness revision protocol, it never carries rules or write permission, and
everything past 64 bytes stays free.

| Offset | Size | Field | Writer |
|---|---|---|---|
| `+0x00` | `u32` | magic `"SLG4"` | ROM |
| `+0x04` | `u16` | layout version | ROM |
| `+0x06` | `u16` | `sizeof` (0x40) | ROM |
| `+0x08` | `u32` | published cookie | ROM |
| `+0x0C` | `u32` | published `PlayerProfile.id` | ROM |
| `+0x10` | `u32` | published engine-clock delta | ROM |
| `+0x14` | `u32` | published session epoch (mirror of mailbox `0x4C`) | ROM |
| `+0x18` | `u32` | published registration count | ROM |
| `+0x1C` | 36 B | zero headroom (C3–C5) | ROM |

Published **last**, so a host sampling mid-visit sees a valid header over a stale
payload rather than a valid header over a torn one.

## Ambiguities this module resolves (and how)

1. **`SysTaskFunc` arity.** The spec draft writes `static void Slink_NDS_Service(void *arg)`;
   at the pinned pret it is `void (*)(SysTask *task, void *data)` (`include/sys_task.h:8`).
   The real signature is used — the one-argument form would only work as a cast.
2. **ROM-private latches are NOT in the title window.** The draft's §2.4 table puts the
   identity latch, cookie latch and clock sample at `0x0C/0x10/0x14` of the reserved
   region. The decision block (`C2_BEACON_SPEC.md:5`) puts the private cookie in the
   SysTask heap block and §4.1:3 says that block "is ROM-private by construction … and
   needs no D-C2-1 carve-out". All private state therefore lives in the heap block; the
   title window carries published bytes only. That also removes the "a host write into a
   latch is indistinguishable from a ROM write" hazard entirely.
3. **The title window is versioned, so the draft's field offsets shift by 8.** D-C2-1
   requires "own magic/version/size in its first bytes"; the draft's `+0x00 = cookie`
   cannot coexist with that. The offsets above are the ones the host reader must use.
4. **`status`/`ack_seq` are not stamped every tick.** §3.3 lists them as per-tick writes,
   but C3 holds `status = BUSY` across visits and producers ack OK/FAIL through `tp_ack`;
   a per-tick stamp would erase both. They are written by the reset latch and by the
   owning producer only.
5. **`session_epoch` IS cleared by the latch.** §4.4's enumeration omits it, but
   `abi.h:156` says "zero unarmed, reset clears" and §3.1 lists it as a host-owned
   request field the registration clears. Leaving it would let a stale epoch survive a
   soft reset and read as armed.
6. **`producer_phase` is stamped only when the trade module is absent.** §3.3.4 says
   IDLE "at C2"; `slink_trade_service` brackets its own state machine with that field on
   every call (`trade_producer.h:310-317`), so the beacon drops the stamp rather than
   fighting it when C5 lands.
7. **Arena for the heap block is `OS_ARENA_MAIN`.** §4.1 says `OS_AllocFromArenaLo` but
   names no arena. `OS_ARENA_ITCM` is forbidden by census W2
   (`gen4_mailbox_census.py:79,209-210`); `OS_ARENA_MAIN` is what every other boot-time
   allocation uses (`src/heap.c:49-56`).
8. **Registration is latched per boot, without static storage, by looking for its own
   task.** `Slink_NDS_Register` returns if `Slink_NDS_Service` is already on
   `gSystem.mainTaskQueue`. That queue is placement-new'd by `InitSystemForTheGame`
   (`src/system.c:123`) and `SysTaskQueue_Init` resets it to the empty sentinel
   (`src/sys_task.c:56-80`), so a previous boot's task is unreachable and the latch
   cannot survive a reset. (An earlier draft latched on "valid title header with a
   nonzero published delta"; that header sits in the ITCM arena, which survives a soft
   reset per item 9, so the new boot would have returned early and never created the
   service task: a dead beacon after every soft reset. The title block must never decide
   this. `tests/unit/test_gen4_c2_beacon_source.py` pins it.) Because the decision block
   calls the registration "latched" and hge's `SaveData_New` replacement is a second
   possible call site, the latch is kept rather than dropped, even though
   `NitroMain` (`src/main.c:50`) runs once per boot.
9. **Epoch/registration seed across a soft reset.** The ITCM arena survives a soft reset
   (the main arena and the heap block do not), so both counters are seeded from the
   published block when its header validates; otherwise (hard reset, or a foreign
   writer) they restart at one. The epoch is re-stamped into the mailbox's `reserved`
   word every visit, so the host never reads a stale one.
10. **Cookie mixer.** §8 Q7 leaves it open. `OS_GetTick()` mixed with the generation,
    the previous session's cookie and a ROM salt; never zero. Cheap to revisit.
11. **Task priority 0** puts the beacon at the head of the frame
    (`src/sys_task.c:124-133`); game tasks use 0 and 1000+.

## Host side (not this card)

`lua/gen4/companion.lua` is a pure reader of the mailbox header plus
`+0x00/+8/+C/+10/+14/+18` of the title block. It must not require a capability bit for
liveness — the shared enum has no beacon member (`C2_BEACON_SPEC.md:436-442`) — and it
must read the `"Instruction TCM"` domain, not the ARM9 mirror of the same bytes
(`C2_BEACON_SPEC.md:411-415`).