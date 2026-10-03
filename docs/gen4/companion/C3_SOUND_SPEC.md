> **Status: DRAFT** (OMP cx-95e28acd, 2026-10-02). The coordinator's review decisions are below; where they conflict with the draft, the decisions WIN.
>
> - **No SE handle is reservable (ACCEPTED, verified):** `PlaySE` (`asm/unk_02005D10.s` @0x0200604C) resolves its handle via `GF_GetPlayerNoBySeq` -> `GF_GetSndHandleByPlayerNo` from the sound-archive data. C3 resolves the handle at runtime and polls it. FEATURE_BAR's "reserves one handle" line is corrected.
> - **C3 does NOT use the shared `sound_producer.h`** (verified: it acks on the same visit, `:22-23`, so it cannot hold), but reuses `tp_ack` only. The hold state lives in the C2 SysTask heap block, not the 0xE00 title window.
> - **C2 review checklist gains:**
>   1. The dispatcher calls **every** producer on **every** visit, and each producer ignores
>      foreign opcodes. The shared trade producer now does exactly that (Gen 4 commit
>      `efc76dd9`, branch `claude/gen4-tp-gate`): its state machine still runs each visit for the
>      save watchdog, and only the trade opcodes `{29 PREPARE, 21 SCENE, 30 WITHDRAW, 31 STATUS}`
>      reach dispatch. **Neither producer gates the other.**
>   2. Leave `status = BUSY` while a request is held.
>   3. `capabilities` stays ROM-owned.
>   (corrected 2026-10-03: "Route producers by opcode before any producer runs" is retired — that
>   was the C2 workaround for the trade producer's catch-all `else` ack, and the `else` arm is now
>   gated on trade-owned opcodes. Producer isolation is per producer, not in the dispatcher.)
> - **Host depth for sound = 1 in flight** (one opcode slot); the GB queue of 4 does not port.
> - **D-C3-1 / D-C3-2 RULED by the ABI owner (Gen 5, 2026-10-02):**
>   - Title-private capability bits are **16..31** (bits 7..15 are reserved for future shared caps), so Gen 4 gates NOTIFY on its own title bit **1<<16** in its host adapter, and NATIVE_SOUND (1<<2) keeps its shared meaning.
>   - Title-private reason codes are **32..63** (16..31 are reserved for future shared reasons), so Gen 4 refuses sound code 2 with reason **32 = SOUND_CODE_REFUSED**, decoded only by the Gen 4 adapter.
>   - The trade_producer else-ack issue is confirmed and is now **fixed** in the shared header on the Gen 4 branch, for Gen 5 to import (commit
>     `efc76dd9`, branch `claude/gen4-tp-gate`): the `else` arm is gated on the trade-owned opcode
>     set, so a foreign opcode is left alone instead of acked. The C2 dispatcher does **not** route.
>     (corrected 2026-10-03: "Until then the C2 dispatcher routes by opcode" is obsolete.)
>   - Cite this ruling until the abi.h comments land.
> 
> **Status: DRAFT** (OMP cx-95e28acd, 2026-10-02). Peer spec draft for coordinator review and
> owner sign-off. Nothing here is built. Every fact carries a `file:line`. Anything I could not
> read is marked **UNVERIFIED**; anything I reasoned to but did not read is marked **INFERRED**.
>
> - Reads the coordinator decision block of `docs/gen4/companion/C2_BEACON_SPEC.md:1-14`; those
>   decisions WIN over anything below. In particular: the ABI is used **unmodified**
>   (`C2_BEACON_SPEC.md:47-49`) and the C3 request state lives in the **service SysTask's own
>   heap data block** (`C2_BEACON_SPEC.md:5`), not in DTCM and not in the ABI.
> - **Owner ruling, honoured verbatim:** code 2 FAILURE is **PENDING** and must not be filled
>   with a guess; C3 may ship without it and must say so
>   (`docs/gen4/reviews/DECISIONS_2026-10-02_companion.md:16`, `FEATURE_BAR.md:262`).
> - **Citation drift against `FEATURE_BAR.md:44`** (the "companion reserves one [SE handle]"
>   claim) is corrected in §2.2. It is a mechanism error, not a line-number slip.
> - Citation drift against `FEATURE_BAR.md:45` ("Service tick: the field task frame") is
>   corrected in §2.1: the C2 main-queue SysTask supersedes it
>   (`C2_BEACON_SPEC.md:166-181`, `FEATURE_BAR.md:205-211`).
> - The NDS caps byte does **not** reuse the GB caps numbering. §3.3 is the correction.

# Gen 4 companion C3: native sound codes (SPEC draft, 2026-10-02)

**Card:** C3 (`docs/gen4/companion/PLAN.md:64`), bar item 2
(`docs/gen4/companion/FEATURE_BAR.md:12`), sound direction `FEATURE_BAR.md:42-47`, code mapping
`FEATURE_BAR.md:168-185`, service tick `FEATURE_BAR.md:203-216`.

**Card inputs and outputs (`PLAN.md:64`):** exclusive files `patch/src/nds/gen4/sound.*`,
`tests/unit/test_gen4_sound_codes.py`. Exit evidence **S**: code table and `PlaySE` call site;
**P**: audible and trace-verified SE on all three artifacts. Shared? **No** — except the host
seam, which is batched to C7 (§3.6).

**All citations to the pret are to the pinned tree at `ad7a3afa`** (`FEATURE_BAR.md:135`), unless
marked hge.

---

## 1. Scope

**A semantic-code table on the ROM side, four integers wide, of which three are wired.**

| Code | Name | SEQ id | Status | Evidence |
|---|---|---|---|---|
| 1 | SUCCESS | `SEQ_SE_DP_DECIDE` 1501 | wired | `include/constants/sndseq.h:499`; called at `view_photo.c:209`, `view_rankings.c:779` (`FEATURE_BAR.md:174`) |
| 2 | FAILURE | **none** | **NOT WIRED — owner PENDING** | `DECISIONS_2026-10-02_companion.md:16`; `FEATURE_BAR.md:175,262` |
| 3 | BOO | `SEQ_SE_DP_WALL_HIT` 1536 | wired, **provisional** (needs a listen test at C3 PHYSICAL) | `include/constants/sndseq.h:534`; `FEATURE_BAR.md:176` |
| 4 | NOTIFY | `SEQ_SE_DP_SELECT` 1500 | wired | `include/constants/sndseq.h:498`; called at `yes_no_prompt.c:156`, `main_menu.c:229` (`FEATURE_BAR.md:177`) |

The code integers are the shared semantic set, unchanged from GB: `1,2,3,4`
(`lua/gb_panel.lua:23`, `patch/gb/slink_abi.inc:14`). **The transport does not.** GB has a
dedicated request byte at mailbox `+7` (`slink_abi.inc:14`, `gb_panel.lua:18`). NDS has one
opcode slot (`abi.h:150`, `opcode` u16 @`0x06`). That single difference drives most of §3.

**This spec ships with code 2 unwired.** The ROM's code table has three entries and a hole at
index 2. The ROM **refuses** code 2 with title-private reason **32 = `SOUND_CODE_REFUSED`**
(§4 F5) rather than playing something else. (corrected 2026-10-03: the decision block pins the
refusal at reason 32; the draft's "title-private reason ≥ 16" phrasing is superseded — the title
range is 32..63.)
`SEQ_SE_DP_DECIDE2` 1694 (`include/constants/sndseq.h:692`) is **not** used as a stand-in
(`FEATURE_BAR.md:175` offers it only as a *recorded substitution*, which requires an owner
ruling that does not exist). Until the owner rules, the host has no code 2 to send either, and a
code-2 request is a client bug, not a missing feature.

### OUT

| Excluded | Why |
|---|---|
| `SLINK_OP_PLAY_FANFARE` (9) | The four semantic codes are all SE, "with no jingle" (`FEATURE_BAR.md:170`). The opcode exists in the ABI (`abi.h:75`) and `sound_producer.h:17` accepts it; C3 leaves that arm unwired. |
| Any `PlaySE` from the vblank queue or `gSystem.vBlankIntr` | Forbidden (`FEATURE_BAR.md:212`); both are IRQ context (`src/system.c:20-25`, `main.c:127-128`). Falsifier F3. |
| `lua/memory_nds.lua` `M.playSE` | That is the host-side SDAT-injection stub and it is a hard `return false` (`lua/memory_nds.lua:1206-1210`). C3 plays the SE **from the ROM** through `PlaySE`. The stub stays a no-op and must not be mistaken for the C3 path. |
| The panel overlay, the trade commit, the start-menu row | C4 / C5 (`PLAN.md:65-66`). |
| Choosing the FAILURE id, or "improving" 1536 without a listen test | Owner content decisions (`PLAN.md:96`, `FEATURE_BAR.md:176`). |

---

## 2. ROM side

### 2.1 The request path — `SLINK_OP_PLAY_SE` in the shared mailbox, served from the C2 SysTask

**One path, one thread.** The host writes the code into the shared mailbox and the C2 service
SysTask resolves it. There is no second service, no second tick, no hook.

| Step | What | Evidence |
|---|---|---|
| Request carrier | `opcode = SLINK_OP_PLAY_SE` (19), u16 at mailbox `+0x06` | `abi.h:79,150` |
| Payload | `args[0]` = the semantic code (u8), `args[32]` @`+0x10` | `abi.h:153` |
| Publish order | `args` first, `opcode` **last** | `abi.h:22-24`: *"Lua records its queue job.posted when it publishes opcode LAST"* |
| Dispatch thread | the C2 `SysTask` on `gSystem.mainTaskQueue`, created by `SysTask_CreateOnMainQueue` | `C2_BEACON_SPEC.md:166,178-181`; `src/sys_task_api.c:7-9` |
| Drain point | `SysTaskQueue_RunTasks(gSystem.mainTaskQueue)` inside `NitroMain` | `src/main.c:111` |
| Per-request state | the SysTask's own heap data block (allocated in NitroMain init, freed by any reset) | `C2_BEACON_SPEC.md:5` |
| New ABI fields | **none** | `C2_BEACON_SPEC.md:47-49`; every static assert at `abi.h:261-286` still holds |

**The `if (sub_02036144())` guard at `main.c:106` is not a gate.** New evidence, read at the
pinned pret: `sub_02036144` has a single exit and it is `mov r0, #1` /
`pop {r4, pc}` (`asm/unk_02035900.s:1143-1144`); the `[_021D4140+8] == 0` path at `:1057-1060`
falls through to `_020361FE: mov r0, #0; bl sub_020355C8` (`:1136-1138`) and then to the same
`:1139-1144` exit. So `mainTaskQueue` drains on **every** loop iteration, with or without a comm
session — not merely "in single-player" as `FEATURE_BAR.md:210` puts it. That strengthens the
per-frame service claim for C2 and C3 alike, and it means C3's hold counter is a **service-visit**
counter that advances at least once per frame.

**Consequence for the bounded hold:** the counter is visits, not wall clock, and carries the Gen 2
caveat verbatim — *"This is a 240-visit bound, not a wall-clock/frame guarantee. hVBlankCounter
freezes in several VBlank modes; rDIV is reset by native serial code. Neither is a sound
deadline."* (`patch/gen2/src/sfx.asm:1-5`). C3 must not swap `gSystem.vblankCounter` in as a
deadline: `gSystem.frameCounter` is zeroed every loop (`src/main.c:124`, the C2 ruling at
`C2_BEACON_SPEC.md:4`) and the C2 service already owns the clock policy.

**Do not call `slink_sound_service` (`patch/src/nds/common/sound_producer.h:13-24`).** Two
independent reasons, both from that file:

1. It takes a **native u16 song id** from `args[0..1]` and a `song_count` bound
   (`:20-21`), not a semantic code. The Gen 4 code table would then live host-side and the
   ROM could never refuse code 2 with a named reason — the falsifier the owner ruling requires.
2. It **cannot express a bounded hold.** It calls `e->effect(...)` exactly once and acks
   immediately (`:22-23`); a held sound would be reported `SLINK_ST_FAIL` with reason 2 on the
   visit the hold began. There is no state field to return to on the next visit.

C3 therefore reuses **`tp_ack` only** (`trade_producer.h:93-104`) and writes its own service body
in `patch/src/nds/gen4/sound.c`. Extending the shared producer to carry a hold would be a
Gen-5-owned shared edit (`PLAN.md:41`) and is out of scope at C3.

**`tp_ack` writes `m->opcode = 0` (`trade_producer.h:103`)**, so an ack *consumes* the request.
That gives the hold its shape: while holding, the ROM leaves `opcode = 19` and `seq` published
and leaves `status = SLINK_ST_BUSY` — which is exactly what C2 already reserves for an
outstanding request (`C2_BEACON_SPEC.md:249-252`). C3 must not set `status` itself; C2 owns it.

**Multi-producer hazard — CLOSED in the shared header (was: C2 routes by opcode).**
The hazard was real: `tp_service`'s `} else { tp_ack(m,seq,0,2); }` (`trade_producer.h:300-302`)
acked **every** opcode it did not own, so a held `SLINK_OP_PLAY_SE` would be acked
`SLINK_ST_FAIL/BAD_ARGS` while C3 was still holding it, and `tp_ack` would zero the opcode out
from under the hold. That arm is now gated on the trade-owned opcode set (Gen 4 commit
`efc76dd9`, `claude/gen4-tp-gate`): the shared producer **leaves foreign opcodes alone**. Its
state machine still runs on **every** visit — it must, for the save watchdog
(`trade_producer.h:160-171`) — but only `{29, 21, 30, 31}` reach dispatch. **The dispatcher calls
every producer every visit and each producer ignores foreign opcodes.** C3 is already symmetric:
`slink_sound_service` returns without acking anything that is not `SLINK_OP_PLAY_SE` /
`SLINK_OP_PLAY_FANFARE` (`sound_producer.h:17`). Falsifier F6 pins this.
(corrected 2026-10-03: the "The C2 dispatcher **must** route by opcode … before C5 lands" wording
is retired.)

### 2.2 Which SE handle, and how busy is polled

**Correction to `FEATURE_BAR.md:44`.** The bar says *"The companion reserves one and polls it
with `NNS_SndPlayerReadDriverTrackInfo`"*. There is no reserved handle, and the mechanism is
different. `PlaySE` does not take a handle at all — it derives one:

```
PlaySE:                     ; asm/unk_02005D10.s:413-428
    add r4, r0, #0          ; the u16 seq id
    bl  GF_GetPlayerNoBySeq ; <- from the SOUND ARCHIVE, not a constant
    bl  GF_GetSndHandleByPlayerNo
```

and `GF_GetPlayerNoBySeq` is a **data lookup into the SDAT sound arc**
(`asm/unk_02004A44.s:1501-1518`):

```
GF_GetPlayerNoBySeq:        ; 0x020054D4
    cmp  r0, #0
    bne  _020054DE
    mov  r0, #0xff          ; seq 0 -> no player
    ...
    bl   NNS_SndArcGetSeqParam
    ldrb r0, [r0, #5]       ; <- the player number comes from the SEQUENCE DATA
```

`GF_GetSndHandleByPlayerNo` then maps `PLAYER_SE_1..4` (3..6, `include/constants/sndseq.h:2505-2508`)
to `SND_HANDLE_SE_1..4` (`src/sound.c:436-443`, enum at `include/sound.h:19-22`). So:

> **Which of the four SE handles `PlaySE(1500/1501/1536)` lands on is ROM data in
> `gs_sound_data.sdat`, not a compile-time constant. It is UNVERIFIED and it is not the same for
> the three ids.**

Two consequences, and they change the design:

1. **The busy poll must resolve the handle at runtime, using the game's own two calls.** That is
   "the game's own pattern" in a stronger sense than the bar meant: same functions, same
   argument. No assumption about which handle is needed, and it is correct on HG, SS and hge
   because the code is identical static ARM9 on all three (§2.4).
2. **The live gate cannot pre-compute a handle address to watch.** The host-side falsifier watch
   address therefore depends on the archive, and must be *measured* per artifact at C3 PHYSICAL
   (falsifier F1).

**Where the handles live** (all three artifacts, identical):

| Fact | Value | Evidence |
|---|---|---|
| `sSoundWork` | `0x02111958`, size `0xBEC88`, object `sound.o` | `.cache/gen4/xmap/heartgoldus.xMAP:50131`; identical at `soulsilverus.xMAP:50131` |
| Handle array | `SND_WORK.unk_BEB78[SND_HANDLE_MAX]` at struct `+0xBEB78` | `src/sound.c:16`; enum max 9 (`include/sound.h:25`) |
| Array absolute | `0x02111958 + 0xBEB78 = 0x021D04D0` | derived; both operands above |
| Stride | **4 bytes** — `unk_BEB9C` follows the array (`src/sound.c:17`), and `0xBEB9C - 0xBEB78 = 0x24 = 9 × 4` | derived from `src/sound.c:16-17` |
| Handle *N* | `0x021D04D0 + 4N` | derived |
| Init | `NNS_SndHandleInit(&work->unk_BEB78[i])` for all 9 | `src/sound.c:461-467`, called from `InitSoundData:91` |
| hge layout | identical: `void *unk_BEB78[SND_HANDLE_MAX]` @`0xBEB78`; `SND_HANDLE_MAX 9` | `hg-engine/include/sound.h:50,8` |

**The busy test is one word.** `NNS_SndPlayerReadDriverTrackInfo` gates on exactly that
(`lib/asm/nnsys.s:23988-23999`):

```
NNS_SndPlayerReadDriverTrackInfo: ; 0x020C83C0
    ldr  r3, [r0]        ; handle word 0
    cmp  r3, #0
    moveq r0, #0         ; zero -> nothing playing on this handle
    ldmeqia sp!, {r3, pc}
```

So **busy ⇔ `*(u32 *)(0x021D04D0 + 4H) != 0`**, where `H` is the handle
`GF_GetSndHandleByPlayerNo(GF_GetPlayerNoBySeq(seq))` resolved at runtime. Reading the word
directly is equivalent to calling the SDK function and cheaper; the SDK declaration
(`lib/NitroSDK/include/nnsys/snd/main.h:8`) and the game's own use
(`src/sound.c:123`, inside the DEBUG-key branch) are the receipts.

An alternative, per-seq rather than per-handle, is the game's own `IsSEPlaying(u16)`
(`include/unk_02005D10.h:12`, body `asm/unk_02005D10.s:588-594`) =
`GF_SndPlayerCountPlayingSeqByPlayerNo(GF_GetPlayerNoBySeq(seq))`. **Recommend the handle-word
poll** (F1 is written against it) because it also covers *another* sequence occupying the same
channel group, which `IsSEPlaying` does not.

### 2.3 The bounded hold and the reset/fade guards, ported from Gen 2

Gen 2's service is 97 lines and every line is a guard (`patch/gen2/src/sfx.asm:30-97`). C3 ports
the discipline one-for-one, changing only the predicate sources.

| Gen 2 (`patch/gen2/src/sfx.asm`) | Rule | Gen 4 predicate | Evidence for the predicate |
|---|---|---|---|
| `:13-26` reset bridge; `SLINK_SFX_RESET_BLOCKED $ff` at `:7` | latch before the reset window; a request posted **during** it is discarded too, not just held | latch on `InitSoundData` | `src/sound.c:82-98`, called once per boot from `src/main.c:66` |
| `:34-36` check the latch **before** the empty/invalid path | order matters: blocked wins over "no request" | same | `sfx.asm:32-36` |
| `:43-45` `wMusicFade != 0` → hold | no new audio during a fade | `GF_SndGetFadeTimer() != 0` | `include/sound.h:38`; body `asm/unk_02005D10.s:311-318` returns attr 7; attr 7 is `&work->fadeTimer` (`src/sound.c:229-230`), which `DoSoundUpdateFrame` decrements every frame while no fanfare is playing (`src/sound.c:110-115`) |
| (not present) | — | also `GF_SndGetAfterFadeDelayTimer() != 0` — **INFERRED** as the second half of the guard | `include/sound.h:39`; body `asm/unk_02004A44.s:2184-2188` returns attr 8 = `&work->unk_BEBF4` (`src/sound.c:231-232`) |
| `:46-47` `CheckSFX` carry = busy channel 5..8 | hold while a native channel is busy | handle word-0 poll (§2.2) | `lib/asm/nnsys.s:23991-23994` |
| `:40-41` `cp SLINK_SFX_NOTIFY + 1 ; jr nc` | an out-of-range request byte is **consumed unplayed**, never queued | code `> 4` or `== 2` → ack FAIL, consume | `sfx.asm:37-41` |
| `:61-63` clear request + hold + hold-at on play | the request is consumed exactly once | same, then `tp_ack(ok=1)` | `sfx.asm:49-66` |
| `:77-83` saturating hold-at counter | **saturate, then consume once**; corrupted ages cannot wrap into a fresh hold | same, ported verbatim | `sfx.asm:77-83` |
| `:6` `SLINK_SFX_MAX_HOLD EQU 240`; `:1-5` the caveat | a 240-visit bound, not a deadline | 240 service visits | `sfx.asm:1-6` |
| `:79-80` "consume once and let `PlaySFX`'s native priority decide… a native call is not proof that a cue was audible" | the ROM's ACK is not an audible-output claim | `SLINK_ST_OK` means *handed to `PlaySE`*, not *heard* | same rule; also `sound_producer.h:1` and `README.md:57-58` |

**Two Gen-4-only additions.** Gen 2 had no equivalent and both are load-bearing:

1. **A "sound ready" bit, not just a reset latch.** Before `InitSoundData` runs there is no sound
   system at all: `NNS_SndArcInit(... "data/sound/gs_sound_data.sdat" ...)` is at
   `src/sound.c:88` and `GF_SndHandleInitAll(work)` at `:91`, both inside the function called at
   `src/main.c:66`. A `PlaySE` before that would read an uninitialised arc and a zeroed handle
   array (`GF_SoundDataInit` memsets `SND_WORK`, `src/sound.c:455`). **Refuse every request until
   the `InitSoundData` latch has fired** — not merely "hold" it. This is stronger than Gen 2's
   reset latch and it is cheap.
2. **The boot generation.** The mailbox is in ITCM, which survives a soft reset
   (`FEATURE_BAR.md:255`), so a `seq`+`opcode=19` pair from the previous boot is still there at
   the first service visit of the new one. Belt-and-braces: C3 also consumes-and-refuses a
   request whose `session_epoch` is zero or differs from the configured epoch — the identical
   gate `sound_producer.h:18-19` uses — and the C2 boot generation at mailbox `+0x4C`
   (`C2_BEACON_SPEC.md:115,248`) is the witness. The `InitSoundData` latch is the primary guard;
   the epoch gate is the invariant that holds if registration order ever changes.

**No `Sound_Stop()` latch.** `Sound_Stop` is called from six places
(`src/field_bgm.c:78`, `src/start_menu.c:1465`, `src/battle_system.c:1218`,
`src/main_menu.c:1506,1510,1514`) that are ordinary gameplay, not resets. Latching on it would
drop legitimate requests. `InitSoundData` is the one latch point, once per boot, from `NitroMain`.

### 2.4 Per-artifact notes

**Shared, and verified identical on all three — the premise of the card.**

| Fact | HG | SS | hge | Evidence |
|---|---|---|---|---|
| `PlaySE` address | `0x0200604C` | same | `0x0200604d` (Thumb bit) | `asm/unk_02005D10.s:414`; `.cache/gen4/build-fc5175764983/nm_all.txt:11` |
| `GetSoundDataPointer` | `0x020043F8` | same | `0x020043F8 \| 1` | `heartgoldus.xMAP:12141`, `soulsilverus.xMAP:12141`; `hg-engine/rom.ld:397`; `nm_all.txt:8` |
| `sSoundWork` | `0x02111958` | `0x02111958` | same routine returns it | `heartgoldus.xMAP:50131`, `soulsilverus.xMAP:50131` |
| `SND_WORK` layout | struct `src/sound.c:12-19` | same | `include/sound.h:46-63` | offsets agree byte for byte (`fadeTimer` at `+0xBEBF0`: `src/sound.c` vs `hg-engine/include/sound.h:60`) |
| hge hooks in the sound module | — | — | **only** `GF_Snd_LoadSeq` / `GF_Snd_LoadSeqEx` | `hg-engine/hooks:290-291` |

The last row is why the vanilla plan stands for all three: hge does not replace the sound module
(`FEATURE_BAR.md:182-185`), so `PlaySE`, `GF_GetPlayerNoBySeq`, `GF_GetSndHandleByPlayerNo` and
`GF_SndGetFadeTimer` are the same code everywhere.

**HG/SS (pret source rebuild, C6 re-pins).** One new file `patch/src/nds/gen4/sound.c` plus a
**source** edit at `src/main.c:66`, all inside the C2 overlay model
(`C2_BEACON_SPEC.md:154-181`; the pret tree is copied to a cache dir, never edited in place,
`PLAN.md:34`): (corrected 2026-10-03: "plus two static-ARM9 hook rows" was wrong — the pret build
has no `hooks` table; the latch is a source edit, and hge's equivalent is an armips `.org`, not a
row either.)

- the service body — folded into the **existing C2 `SysTask`** (`C2_BEACON_SPEC.md:166`), not a
  second task;
- a `InitSoundData` latch row at `src/main.c:66`.

`src/main.c` and `src/sound.c` are both static ARM9, so neither adds a static `.bss` symbol and
neither moves `SDK_STATIC_BSS_END = 0x021E5900` — the constraint that killed the old mailbox route
(`FEATURE_BAR.md:140-146`). All C3 state is in the SysTask heap data block
(`C2_BEACON_SPEC.md:5`). **This must be asserted in the C3 build, not assumed** — it is the same
class of hazard as `sfx.asm:10-11` (`ASSERT wAudioEnd <= wSlinkMailbox`).

**hge (in-fork, C6).** Registration rides hge's own `SaveData_New` replacement, **not**
`load_arm9_expansion` and **not** a `hooks` row — see the C2 decision block
(`C2_BEACON_SPEC.md:15-19`), which supersedes D-C2-2.

**The `InitSoundData` latch vehicle on hge — RESOLVED (Q7).** Two facts, both measured:

1. **The call site is 0x02000D12 on all three artifacts.** The pret Thumb `bl InitSoundData` whose
   target is `0x02004174` resolves to call-site `0x02000D12` in HG, SS **and** hge (pinned-ROM
   read, `ndspy` loadArm9; hge's static ARM9 keeps the vanilla addresses, `FEATURE_BAR.md:122-126`).
   (corrected 2026-10-03: the draft recorded this as "the hge `InitSoundData` row address is
   UNVERIFIED"; it is measured, and it is a `bl` — not the function.)
2. **The vehicle is a SLink-owned armips patch, not a `hooks` row.** A `hooks` row *replaces* the
   function (`scripts/make.py:151-155` for the 4-field form) and has no call-through, so it cannot
   latch after a call that must still happen. hge's `armips/asm/*.s` files are SLink-owned and
   already carry `.org` patches (`hg-engine/armips/asm/syntheticoverlay.s:8-10` is the precedent
   shape). So: `.org 0x02000D12` in a new SLink armips file, replacing the 4 B `bl` with a `bl` to
   a **pinned stub** that calls `InitSoundData` and then latches.

**Collision census (C6 SOURCE, blocking).** Because the latch is an `.org` write and not a table
row, it is invisible to any check that only reads `hooks`. The census must therefore cover **all
five writer classes** — `hooks`, `repoints`, `routinepointers`, `bytereplacement` and armips
`.org` — and assert that `0x02000D12` is claimed by at most one of them.
(corrected 2026-10-03: a `hooks`/`repoints`-only census would have passed while this write
collided.)

**Known baseline for the census:** in a default hge build the only NitroMain write is
`0x02000CD0`, 4 B. (corrected 2026-10-03: added as the census's starting datum.)

**OPEN design alternative, not decided:** replace the latch with a **read-only** check of a
`sSoundWork` field that only `InitSoundData` sets (e.g. `GF_SndHandleInitAll`'s handle
initialisation, or the arc's player-count table). That costs zero writes and removes the hge
collision problem entirely, but it needs a field proven set-and-only-set by `InitSoundData`.
Tracked as **Q10** (§6); it is an alternative to the latch, not a decision.

---

## 3. Host side

### 3.1 What ships where

| Piece | File | Window |
|---|---|---|
| Post/consume a sound request; caps + liveness gate | `lua/gen4/companion.lua` (the C2 new file, `PLAN.md:63`) | C3 — new `lua/gen4/*` touching nothing shared lands early (`PLAN.md:71`) |
| `play_sound` + local-cue seam in the client | `lua/gen4/client.lua` | **C7** — `PLAN.md:71` batches `lua/gen4/client.lua` into the single shared window |
| Code table test | `tests/unit/test_gen4_sound_codes.py` (`PLAN.md:64`) | C3; `tests/` does not stale the Gen 2 digest |

`lua/gen4/client.lua` currently has **no** `play_sound`, no `SE_*` and no `request_sfx` handling at
all (grep over `lua/gen4`: no matches). That is why the seam is a C7 item and why C3's unit test
must exercise the post path directly, not through the client.

### 3.2 The request flow

```
server play_sound <gen3 id>  ─┐
client local cue (start/win) ─┴─> sfx_arbiter (one cue per frame, ranked)
                                    -> code = sfx_code_for(gen3_id)   -- nil means "not a Gen 4 sound"
                                    -> caps_has(NATIVE_SOUND) and beacon fresh?
                                    -> queue (depth 1 in flight, drop-oldest beyond)
                                    -> mailbox: args[0] = code, then opcode = 19 LAST
                                    -> poll: ack_seq == seq and opcode == 0 -> dequeue
```

Ported rules, each with its receipt:

| Rule | Source |
|---|---|
| Map the Gen-3 wire id to a semantic code; an unmapped id is dropped silently, never sent | `lua/gen1/panel.lua:20,79-83`; `lua/gen2/panel.lua:42-43,154-157` |
| Gen-3 ids on the wire: `SE_BOO 22`, `SE_SUCCESS 25`, `SE_FAILURE 26`, `SE_SHINY 95` | `lua/memory_nds.lua:1193-1198` |
| Reject any code outside `1..4` | `lua/gb_panel.lua:133` |
| Refuse to post when the SFX capability is absent | `lua/gb_panel.lua:114` |
| Refuse to post when the beacon is stale | `lua/gen2/panel.lua:145-151` (the Gen 2 freshness rule) |
| One cue per frame; a losing cue is dropped, not deferred | `lua/sfx_arbiter.lua:1-14,42-47` |
| Mark the mailbox route as `native_ok` | `lua/sfx_arbiter.lua:22,30` — a cue without the flag never reaches the mailbox |
| Gate on `config.native_sounds == true`, and clear the queue when it goes false | `lua/gen2/client.lua:501,602` |

**Queue depth is 1 in flight, not 4.** GB's `SFX_QUEUE_MAX = 4` (`lua/gb_panel.lua:24,136`)
works because the GB mailbox has a *byte* that the ROM clears; four codes can queue behind it.
NDS has one `opcode` u16 (`abi.h:150`) that `tp_ack` zeroes (`trade_producer.h:103`). A second
posted request **overwrites the first** — mid-hold that would silently destroy the pending cue.
So: one outstanding sound request per player; a further cue in the same frame is dropped by the
arbiter or supersedes the outstanding one, and the ROM's hold bound (240 visits, §2.3) is the
ceiling on how long the host may hold the slot.

**The host must reserve the `seq` for the hold's duration.** `tp_ack` compares **only** the
sequence, and its own comment states the assumption: *"this assumes the host never reuses a seq
for a different opcode while a command is outstanding"* (`trade_producer.h:95-98`). With a
240-visit hold that is a ~4 s reservation window on a u16 counter (`abi.h:151`). A sound request
that is superseded must be replaced in place (new code, **same** seq, opcode republished) or
dropped — never re-sequenced. **Recommendation: replace in place**, so the host always has at
most one live `seq` for sound.

### 3.3 Rank, and the NOTIFY capability gate

**Rank FAILURE > BOO** is `lua/gen2/panel.lua:47`: `P.SFX_RANKS = { [SFX_FAILURE] = 2, [SFX_BOO] = 1 }`.
**With code 2 unwired, Gen 4 ships `{ [SFX_BOO] = 1 }` only.** The FAILURE row is added to the
rank table in the same commit that wires code 2; a rank for a code the ROM refuses would silently
suppress BOO in favour of a request that always fails. Unranked codes (1, 4) rank 0 and are
generic (`lua/sfx_arbiter.lua:19,32-33`).

**NOTIFY capability-gated** is `lua/gen2/panel.lua:155` / `lua/gen1/panel.lua:81`
(`if sound_id == P.SE_SUCCESS and self:caps_has(G.CAP_SFX_NOTIFY) then return P.SFX_NOTIFY end`).

> **Correction — the gate cannot be ported bit-for-bit.** The two caps vocabularies disagree at
> every bit:
>
> | bit | GB (`patch/gb/slink_abi.inc:23-27`) | NDS (`abi.h:88-96`) |
> |---|---|---|
> | 0 | `CAP_SFX` | `SLINK_CAP_DURABLE_TRADE` |
> | 1 | `CAP_PANEL` | `SLINK_CAP_INFO_PANEL` |
> | **2** | **`CAP_SFX_NOTIFY`** | **`SLINK_CAP_NATIVE_SOUND`** |
> | 3 | `CAP_PHONE` | `SLINK_CAP_EXPLODE` |
> | 4 | `CAP_TRADE` | `SLINK_CAP_RIVAL_SWAP` |
> | 5 | — | `SLINK_CAP_BATTLE_CALC` |
> | 6 | — | `SLINK_CAP_MATCH_CALL` |
>
> Reusing `G.CAP_SFX`/`G.CAP_SFX_NOTIFY` against an NDS mailbox would read **durable trade** as
> "sound present" and **native sound** as "notify available". The NDS *shared* vocabulary stops at
> bit 6 (`abi.h:88-96`); bits 7..31 carry no shared meaning, and of those **16..31 are the
> title-private range** (7..15 stay reserved for future shared caps) per the ABI owner's ruling.
> (`capabilities` is a `u32`, `abi.h:155`.)
>
> **DECISION (D-C3-1, RULED — no longer a proposal):** NOTIFY is gated on
> `capabilities & (1u << 16)`, the **title-private** bit declared in
> `patch/src/nds/gen4/sound.h` as `SLINK_GEN4_CAP_SE_NOTIFY`. No `abi.h` edit, no Gen 5
> coordination, and it stays inside the C2 ruling that Gen 4 may add no shared field
> (`C2_BEACON_SPEC.md:47-49`).
> (corrected 2026-10-03: the draft proposed `1u << 7` and left the gate itself open. Both are
> closed — the bit is `1<<16`, inside 16..31, and the gate is kept. The
> "alternative: drop the NOTIFY gate entirely" option below is **not chosen**; recorded here
> because it was a live question, not because it survived.)
> **Alternative considered and NOT chosen:** drop the NOTIFY gate entirely for Gen 4 — 1500 exists
> on all three artifacts and there is exactly one build shape, so the Gen 1/2 rationale ("an older
> cartridge drops code 4 unplayed") does not apply. Rejected: the bar asks for the gate
> (`FEATURE_BAR.md:181`) and the owner ruled it in.

**C3 sets two capability bits:** the shared `SLINK_CAP_NATIVE_SOUND` (bit 2, `abi.h:91`) and the
title-private NOTIFY bit **16** (D-C3-1, above). `capabilities` is ROM-owned
(`FEATURE_BAR.md:258`). (corrected 2026-10-03: the draft said NATIVE_SOUND was "the only sound cap
C3 sets", which contradicted the NOTIFY gate three lines above it.)

### 3.4 What C3 does **not** do host-side

- It does not write audio memory. `M.playSE` stays a no-op (`lua/memory_nds.lua:1206-1210`).
- It does not reuse `lua/gb_panel.lua`. That module's `CAP_*` and `OFF_*` are GB mailbox offsets
  (`lua/gb_panel.lua:18-19`) and would be wrong against an NDS mailbox at span `0x01FFEC00`
  (`C2_BEACON_SPEC.md:62`). C3 binds to the NDS mailbox layout directly.
- It does not parse the ack for meaning beyond `ack_seq`/`status`. **`SLINK_ST_OK` is "handed to
  `PlaySE`", not "audible"** (`sfx.asm:79-80`, `sound_producer.h:1`). The audible claim is F1 and
  only F1.

### 3.5 Ordering constraint

The sound request must be posted **after** C2's handshake is live (beacon fresh, epoch published),
because the ROM refuses a zero or mismatched `session_epoch` (`sound_producer.h:18-19`). C3's
`companion.lua` therefore depends on C2's liveness, not merely on its presence.

### 3.6 The C7 batch

`PLAN.md:71` is explicit: *"a possible `lua/gen4/client.lua` hookup … lands once in C7"*, and
`PLAN.md:49`: *"Any edit to `lua/*.lua`, `lua/core/**` or `server/**` stales the Gen 2 digest"*.
So `request_sfx_local`-style wiring in `lua/gen4/client.lua` is a **C7** deliverable. C3's PHYSICAL
evidence therefore exercises the post path through `companion.lua` directly (F1-F5), and C7 adds
the client seam plus the ~2 h re-sweep.

---

## 4. Falsifiers

Class per `PLAN.md:64`: **S** = SOURCE, **M** = MODEL (a lupa/host world), **P** = PHYSICAL.

| # | Falsifier | Class | How it is run | Pass |
|---|---|---|---|---|
| **F1** | **An SE plays — handle busy observed.** | P | On each artifact, with the ROM patched and the host posting code 1, 3, 4: watch the handle word at `0x021D04D0 + 4H`, `H = GF_GetSndHandleByPlayerNo(GF_GetPlayerNoBySeq(seq))` resolved at runtime. Confirm (a) the word goes non-zero within N frames of the ack and returns to zero, (b) it is the *same* `H` the ROM resolved, (c) it is audible to a human listener. | Word toggles on the resolved handle, and is audible. **A native call is not proof** (`sfx.asm:79-80`) — the word toggle plus the listen test is the proof. |
| **F2** | **A request during fade/reset is dropped, not queued forever.** | P + S | (a) Start a BGM fade, post code 3, assert no `PlaySE` and the request still held; (b) let the fade end, assert it plays; (c) with the request held, soft-reset, assert the post-boot service refuses and clears it (`src/main.c:66` latch) and never plays it; (d) let a hold run past 240 visits and assert it is consumed unplayed. | Every case terminates; no request survives a reset; no hold exceeds the bound. |
| **F3** | **No `PlaySE` off the main thread.** | S | Static: assert the companion adds no task on `gSystem.vwaitTaskQueue` (`src/main.c:131`) or `gSystem.vBlankIntr` (`src/main.c:127-128`), no `hooks` row on either, and that the only `PlaySE` call site is inside the `mainTaskQueue` SysTask. Runtime: a breakpoint/log gate on `PlaySE` recording the caller — only `Slink_NDS_Service`. | The only caller of `0x0200604C` is the C2 service. |
| **F4** | **An unknown code is refused.** | S + M | Post `args[0] = 0`, `5`, `255`, and `0xFFFF`; assert each is consumed unplayed with `status = SLINK_ST_FAIL`, `reason = SLINK_REASON_BAD_ARGS` (2, `abi.h:101`), and `opcode` cleared (`trade_producer.h:103`) — never held, never played. Model: a fake `SlinkSoundEngine` + a fake handle word. | Same as Gen 2's `cp SLINK_SFX_NOTIFY + 1 ; jr nc` (`sfx.asm:40-41`), with an ack. |
| **F5** | **Code 2 is refused with a named reason.** | S + M + P | Post `args[0] = 2` on each artifact. Assert: `SLINK_ST_FAIL`; `reason = 32` (`SOUND_CODE_REFUSED`, title-private per the ABI owner: 32..63 are title reasons, 16..31 are reserved for shared reasons); `opcode` cleared; no `PlaySE`; handle word unchanged; **no audible sound**. Additionally assert the *host* never emits code 2, and that the code table in `patch/src/nds/gen4/sound.h` has a hole at index 2 rather than a placeholder id. | Refused, named, silent, and `mailbox.reason == 32`. **This is the falsifier that proves the owner ruling (`DECISIONS_2026-10-02_companion.md:16`) is honoured rather than quietly filled.** (corrected 2026-10-03: "a **distinct** reason (not the generic 2)" → pinned at 32.) |
| **F6** | **Two producers do not steal each other's acks.** | S + M | With the C5 trade producer present in the same SysTask: hold a sound request across ≥ 1 visit, and assert the trade producer has not acked it. Then post a `TRADE_PREPARE` and assert the sound producer ignores it (returns without acking — `sound_producer.h:17`). Then assert the trade producer's save watchdog still advances with no trade request outstanding (its state machine runs every visit; only `{29,21,30,31}` reach dispatch). | Exactly one producer acks each request; no producer's watchdog stalls. **Passes only with the foreign-opcode gate in place** (`efc76dd9`); it failed against the C2-routed dispatcher the draft proposed. |

**What F1 cannot prove:** *which* SE handle an id maps to, statically. It resolves it at runtime on
the artifact under test, and that per-artifact result is what C3 records — it is the "the SE id
mapping" open item from `FEATURE_BAR.md:47` / `PLAN.md:96`.

**Not a falsifier:** "the hold counter reaches 240 visits". That is a bound on visits
(`sfx.asm:1-5`), not an observable.

---

## 5. Single-writer table

Mailbox span `0x01FFEC00 .. 0x01FFFC00` (`C2_BEACON_SPEC.md:62`). One writer per byte, ever.

| Offset (abs) | Field | Writer | C3 rule |
|---|---|---|---|
| `+0x00` | `signature` | ROM | C2 re-stamps every tick; C3 never touches (`C2_BEACON_SPEC.md:242-244`). |
| `+0x04` | `abi_version` | ROM | C2. |
| `+0x06` | `opcode` | **host** | host writes `19` LAST; **ROM clears it via `tp_ack` only** (`trade_producer.h:103`). C3 never writes this byte. |
| `+0x08` | `seq` | host | reserved for the whole hold window (§3.2). |
| `+0x0A` | `status` | ROM | **C2 owns it.** `SLINK_ST_BUSY` while C3 holds (`C2_BEACON_SPEC.md:249-252`); `OK`/`FAIL` from `tp_ack`. C3 never writes this byte. |
| `+0x0C` | `ack_seq` | ROM | `tp_ack` only. |
| `+0x0E` | `reason` | ROM | `tp_ack` only. F5's named reason lands here. |
| `+0x10` | `args[0]` | host | the semantic code, written **before** `opcode`. |
| `+0x11 .. +0x2F` | `args[1..31]` | host | C3 must zero them; a stale `args[1]` from a previous request is harmless here (C3 reads `args[0]` only) but F4 requires the ROM to ignore them. |
| `+0x30` | `result[16]` | ROM | untouched by C3. |
| `+0x40` | `capabilities` | ROM | C3's build sets `SLINK_CAP_NATIVE_SOUND` (`abi.h:91`) and, per D-C3-1, the title-private bit **16** (`1u << 16`). Never host-written (`FEATURE_BAR.md:258`). |
| `+0x44` | `session_epoch` | host | C3 **reads** it (`sound_producer.h:18-19`); never writes. |
| `+0x48` | `producer_phase` | ROM | C5's; C3 leaves it at `SLINK_PHASE_IDLE` (`abi.h:110`). |
| `+0x4C` | `reserved` = boot generation | ROM | C2's (`C2_BEACON_SPEC.md:115`); C3 uses it as the soft-reset witness (§2.3). |
| `+0xE00 .. +0xE3F` | title-private (`D-C2-1`) | ROM-written / host-read | **C3 uses none of it** — the hold state lives in the SysTask heap block (`C2_BEACON_SPEC.md:5`). Listed so nobody "finds room" here. |

**ROM-private, outside the mailbox entirely** (SysTask heap data block, `C2_BEACON_SPEC.md:5`):

| State | Owner | Reset by |
|---|---|---|
| pending code | C3 ROM | cleared on play, on refusal, on hold-expiry, by the `InitSoundData` latch |
| hold-at (visits elapsed) | C3 ROM | same |
| hold-blocked latch | C3 ROM | set by `InitSoundData` (`src/main.c:66`); released at the next service visit **after** sound is ready |
| sound-ready bit | C3 ROM | set by `InitSoundData`, cleared by any reset |

**Engine-private, read-only to C3** (never written by the companion):

| Object | Address | Access |
|---|---|---|
| `sSoundWork.unk_BEB78[]` | `0x021D04D0` | read word 0 per handle |
| `work->fadeTimer` | `0x02111958 + 0xBEBF0 = 0x021D0548` | read only; the engine decrements it (`src/sound.c:111`) |
| `work->unk_BEBF4` | `0x02111958 + 0xBEBF4 = 0x021D054C` | read only |

---

## 6. Open questions

Every inference in this document is marked **INFERRED**; these are the ones that need a ruling or
a measurement.

| # | Question | Status |
|---|---|---|
| **Q1** | **D-C3-1 — NOTIFY gate.** | **RULED.** Title-private bit **16** (`1u << 16`), gate kept (`C3_SOUND_SPEC.md:1-24`). The draft's `1u << 7` and its "drop the gate" alternative are both closed. (corrected 2026-10-03.) |
| **Q2** | **D-C3-2 — the named reason for code 2.** | **RULED.** Reason **32 = `SOUND_CODE_REFUSED`**, a title-private code (32..63), declared in `patch/src/nds/gen4/sound.h` and decoded only by the Gen 4 adapter. No `abi.h` edit; cite the ruling until the comments land. (corrected 2026-10-03: the draft offered "a title-private reason ≥ 16" and named `SLINK_REASON_BAD_ARGS` (2) as the alternative — 16 is in the reserved shared range and 2 is generic. Both retired.) |
| **Q3** | **Which SE handle does each id map to?** | **UNVERIFIED.** ROM archive data (`asm/unk_02004A44.s:1515`). Resolved at runtime by F1 and recorded per artifact. |
| **Q4** | **Is `SEQ_SE_DP_WALL_HIT` 1536 acceptable as BOO?** | **Provisional** (`FEATURE_BAR.md:176`) — no C caller; needs the C3 listen test in F1. |
| **Q5** | **Is `GF_SndGetAfterFadeDelayTimer()` a required second fade guard?** | **INFERRED.** It is the after-fade delay attribute (`src/sound.c:231-232`) and the name says what it says, but no call site was read. Cheap; keep it, revisit if it costs plays. |
| **Q6** | **Hold bound in visits or vblanks?** | **Visits**, by the Gen 2 rule (`sfx.asm:1-5`). A vblank-based bound is forbidden while `gSystem.frameCounter` is zeroed per loop (`src/main.c:124`; `C2_BEACON_SPEC.md:4`). |
| **Q7** | **hge `InitSoundData` hook address.** | **RESOLVED.** Not a hook. The call site is `0x02000D12` in HG, SS and hge (pinned-ROM read, `ndspy`), the pret Thumb `bl` targeting `0x02004174`; hge keeps vanilla static-ARM9 addresses. On hge the vehicle is a SLink-owned armips `.org 0x02000D12` patch replacing that 4 B `bl` with a `bl` to a pinned stub that calls `InitSoundData` then latches, following `hg-engine/armips/asm/syntheticoverlay.s:8-10`. Not a `hooks` row: `hooks` replaces the function and cannot call through. Collision census must cover all five writer classes (§2.4). (corrected 2026-10-03: was "UNVERIFIED — must be read off the hge nm/xMAP at C6".) |
| **Q8** | **F6's fix lands in C2 or C5?** | **Answered: neither.** It landed in the shared producer (Gen 4 `efc76dd9`, `claude/gen4-tp-gate`), which now ignores foreign opcodes, so the dispatcher does not route and no C2/C5 file carries the gate. (corrected 2026-10-03: the draft recommended "C2, as a routing-by-opcode rule".) |
| **Q9** | **Should the host replace or drop a superseded sound request?** | **Recommend replace-in-place, same `seq`** (§3.2), so the host never has two live sound `seq`s. Not yet exercised by any Gen 1/2 precedent — the GB byte mailbox has no seq. |
| **Q10** | **Latch vs a read-only sound-work check on hge.** | **OPEN — design alternative, undecided.** Instead of writing a latch through an armips `.org`, the service could read a `sSoundWork` field that only `InitSoundData` sets, and refuse until it is set. Zero writes, no collision with any writer class, but it needs a field proven set-and-only-set by `InitSoundData` on all three artifacts. §2.4. |

### §9. Citation drifts against `FEATURE_BAR.md` (all found by reading the pinned pret / the fork)

1. **`FEATURE_BAR.md:44`** — *"The companion reserves one and polls it"*. No handle is reservable:
   `PlaySE` derives the handle from the sound archive (`asm/unk_02005D10.s:413-428`,
   `asm/unk_02004A44.s:1501-1518`). Substantive, not a line slip. §2.2.
2. **`FEATURE_BAR.md:45`** — *"Service tick: the field task frame (FieldSystem.taskman +0x10)"*.
   Superseded by the C2 main-queue SysTask (`C2_BEACON_SPEC.md:166,178-181`;
   `FEATURE_BAR.md:205-211`). §2.1.
3. **`FEATURE_BAR.md:210`** — *"With no comm session … single-player always drains"*.
   Understated: `sub_02036144` returns 1 on **every** path (`asm/unk_02035900.s:1143-1144`), so
   `mainTaskQueue` drains unconditionally. §2.1.
4. **`FEATURE_BAR.md:181`** — the NOTIFY cap gate, quoted as host behaviour to carry over, does
   not port bit-for-bit: NDS bit 2 is `SLINK_CAP_NATIVE_SOUND`, not `CAP_SFX_NOTIFY`
   (`abi.h:91` vs `slink_abi.inc:25`). §3.3.
5. **Verified correct as cited:** the SE ids at `include/constants/sndseq.h:498,499,534` (and
   `:692` for `SEQ_SE_DP_DECIDE2`), `include/sound.h:19-25`, `src/sound.c:123`, and — for C4 —
   `SEQ_SE_GS_GEARCANCEL 2368` at `include/constants/sndseq.h:1366`.