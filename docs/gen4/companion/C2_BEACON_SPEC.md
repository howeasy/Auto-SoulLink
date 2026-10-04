> **Status: DRAFT** (OMP cx-a817ec74, 2026-10-02). The coordinator's review decisions are below; where they conflict with the draft text, the decisions WIN.
>
> - **D-C2-4 ACCEPTED (provisional, to be proven at C2 MODEL).** The generation is a SESSION epoch: the boot generation plus the save-session identity (`PlayerProfile.id`). Verified: New Game re-enters no reset (`src/overlay_36.c`: the New Game app only registers the field app; `OS_ResetSystem` at `:247` is another path), so a boot-only generation cannot satisfy falsifier 1. The "stable for K polls" rule stays INFERRED until C2 MODEL measures it.
> - **`gSystem.frameCounter` is FORBIDDEN as a liveness clock** (verified: `src/main.c:124` zeroes it every loop). Use `gSystem.vblankCounter`. This goes in the C2 review checklist.
> - **The private cookie lives in the service SysTask's own heap data block** (allocated in NitroMain init every boot, freed by any reset, read only by the ROM), NOT in DTCM. C1 excluded the DTCM arena because it is the launcher stack (`lib/NitroSDK/src/os/os_thread.c:24-26`). No DTCM census rows are needed.
> - **D-C2-1 RULED by the ABI owner (Gen 5, 2026-10-02): allowed, on terms.** Gen 4 may use ONLY 0xE00..0xE40 (64 B; absolute 0x01FFFA00..0x01FFFA40) as title-private, ROM-written / host-read published state. The terms:
>   - shared code never touches it;
>   - the title versions it itself (own magic/version/size in its first bytes);
>   - it is NOT covered by the witness revision protocol, so publish-last / coherent-snapshot rules are the title's own, and the host treats it as untrusted-until-valid;
>   - it never carries rules or write permission;
>   - 0xE40..0x1000 stays free.
>   - Follow-up (Gen 5): a named `SLINK_TITLE_OFFSET 0xE00 / SLINK_TITLE_SIZE 0x40` in abi.h; until then cite this ruling.
> - **The link gate (`sub_02036144`):** C2 scope is single-player; the `vwaitTaskQueue` insurance site is not added now. Record it in the C8 checklist.
> - **C2 interface amendment (2026-10-04):** NEW reader files under `lua/nds` may land at C2; they are outside the Gen 2 digest scope and inside the Gen 4 evidence surface, so land before live checks. Edits to EXISTING shared modules still wait for C7. `lua/nds/mailbox.lua` supplies the raw reader and `lua/gen4/companion.lua` supplies title liveness (side branch `claude/gen4-nds-mailbox@1f339a29`; see `docs/shared-nds-mailbox.md`).
> - **Service registration site DECIDED (OMP cx-72f089e6, coordinator-verified):**
>   - **HG/SS:** call `Slink_NDS_Register()` (latched) in `NitroMain` right after `InitSystemForTheGame()` (`src/main.c:51`), before the first `RegisterMainOverlay` at **`:77`** (not `:83`). A soft reset re-runs `NitroMain`.
>   - **hge:** NO hooks row. hge already replaces `SaveData_New` (its only vanilla caller is `src/main.c:64`, during boot; `hooks:402`) with its own `src/save.c:139`, so append the register call before its `return`. That code calls `CreateSysTask`, which the fork already binds to `0x0200E320|1` = vanilla `SysTask_CreateOnMainQueue` (`rom.ld:477`, `include/task.h:51`).
>   - Prepare the fork change as a patch only. No commit to the owner's hg-engine fork until an approved branch (owner ruling 2026-10-04; see `docs/gen4/reviews/DECISIONS_2026-10-04_companion_and_g3a.md`).
>   - **Falsifier:** a published `registrations` counter stays 1 across a full route and becomes 2 after a START+SELECT+L+R soft reset.
>
# Gen 4 companion C2: beacon, capabilities and liveness (SPEC draft, 2026-10-02)

**Status (2026-10-04):** reviewed interface with ROM source/compile and title-reader MODEL
work on the cited branches; no linked companion or PHYSICAL qualification is claimed. Every fact carries a `file:line`. Anything I could not verify from a file in this tree
or the pinned pret is marked **UNVERIFIED**; anything I reasoned to but did not read is marked
**INFERRED**.

**Card:** C2 (`docs/gen4/companion/PLAN.md:63`), bar item 1
(`docs/gen4/companion/FEATURE_BAR.md:11`), direction `FEATURE_BAR.md:247-258`.

---

## 1. Scope

C2 delivers **only**: the 4 KiB arena placement, the shared ABI header republished every
service tick, the capability handshake, and liveness (cookie + save-session generation + engine-clock
delta).

C2 does **not** deliver:

| Excluded | Card | Why it is out of C2 |
|---|---|---|
| `SLINK_OP_PLAY_SE` dispatch and any sound semantics | C3 | The FAILURE SE is an unresolved owner content choice (`DECISIONS_2026-10-02_companion.md:16`, "Sound can pend for now"); a guess is forbidden |
| `SlinkInfoV2` panel draw and the `START_MENU_ACTION_7` row | C4 | `FEATURE_BAR.md:20,78-82` |
| `SlinkRecordStageV1` + `Party_SafeCopyMonToSlot_ResetAprijuiceModifiers` | C5 | `FEATURE_BAR.md:87-88`; trade is party-only by owner ruling (`DECISIONS_2026-10-02_companion.md:12`) |
| The `SlinkTradeWitnessV2` lifecycle | C5 | Only a producer populates a witness; at C2 the witness region stays zero |
| The `std_nurse_joy` branch and the companion `ScrCmd` slot | C5 | Already settled and **not re-opened here**: opcode **1**, not 486, because 486 is executed by vanilla scripts (`FEATURE_BAR.md:151-165`). C2 must not touch the script table |
| Any `PlaySE` call site | C3 | Sound is capability-gated at C3 and forbidden from IRQ context (`FEATURE_BAR.md:212`) |

Consequences of that boundary, which the rest of this document depends on:

- The shared ABI header is used **UNMODIFIED**. No field is added, moved or resized, so
  `patch/src/nds/common/abi.h` needs no Gen 4 change and the Gen 5-led shared header
  (`PLAN.md:63`) is not touched. Every static assert in `abi.h:261-286` therefore still holds.
- **No capability bit is advertised at C2** (`capabilities == 0`). See §5.
- C2 adds **zero bytes to any shared struct**. All C2 additions live in regions the ABI itself
  declares unused on NDS (§2.4).

---

## 2. Placement

### 2.1 The span

| Fact | Value | Evidence |
|---|---|---|
| C1 census default span | `0x01FFEC00 .. 0x01FFFC00` (end exclusive), exactly 4 KiB | `tools/gen4_mailbox_census.py:44` |
| Span size equals the shared arena | `SLINK_ARENA_SIZE 0x1000u` | `abi.h:40-44` |
| The span must sit in the ITCM arena tail | `ARENA = (0x01FF8620, 0x02000000)`, `span_check` refuses anything outside it | `gen4_mailbox_census.py:40,120-124` |
| BizHawk domain | `"Instruction TCM"`, 32768 bytes; base `ITCM_BASE = 0x01FF8000` | `lua/tests/probe_gen4_mailbox.lua:12-13`, `lua/tests/probe_gen4_hooks.lua:539` |
| Host-side domain offset | `0x01FFEC00 & 0x7FFF = 0x6C00` | `gen4_mailbox_census.py:513-514`; `tests/live/test_gen4_mailbox.py:105` |
| The host and the ROM see the same bytes | probe row `a` requires the ITCM window to agree with the ARM9 bus at `0x01FF8000 + off` | `lua/tests/probe_gen4_mailbox.lua:8,105` |
| Mirror hazard | the ITCM mirrors at `0x0..0x7FFF`; computed-pointer writes are not statically visible | `gen4_mailbox_census.py:268` |

**Gate (binding).** No ROM build ships, and no C2 source is merged, before C1's live canary
accepts this span:

- The census emits `"accepted": None` with the note *"needs the live canary receipts
  (tests/live/test_gen4_mailbox.py) on this artifact"* (`gen4_mailbox_census.py:515`).
- `combine()` only sets `accepted` on `status == "PASS"` (`tests/live/test_gen4_mailbox.py:104-106,318`),
  and `test_combine_never_accepts_an_address_without_a_passing_census` enforces that.
- RESUME records the live canary as **pending a free lane** (`docs/gen4/RESUME.md:84-85`).
- The shared doc says the same: census W1–W3 passed, *"the live canary watch is still pending,
  so it is not accepted"* (`docs/shared-nds-companion.md:306-307`).

The C1 rule itself (ELF/arena proof **and** a live write-watch on HG, SS **and** hge) is
`FEATURE_BAR.md:52`.

### 2.2 Region map (absolute, `offset + 0x01FFEC00`)

| ABI region | Offset | Size | Absolute start | Absolute end (excl.) | Evidence |
|---|---|---|---|---|---|
| `SlinkMailboxV2` | `0x000` | `0x50` | `0x01FFEC00` | `0x01FFEC50` | `abi.h:45,262` |
| `SlinkTradeWitnessV2` | `0x050` | `0x50` | `0x01FFEC50` | `0x01FFECA0` | `abi.h:46,264` |
| blob (`SlinkRecordStageV1`) | `0x100` | `600` (`0x258`) | `0x01FFED00` | `0x01FFEF58` | `abi.h:47-48,272` |
| text | `0x360` | `512` | `0x01FFEF60` | `0x01FFF160` | `abi.h:49-50,273` |
| menu | `0x560` | `384` | `0x01FFF160` | `0x01FFF2E0` | `abi.h:51-52,274` |
| info (`SlinkInfoV2`) | `0x6E0` | `288` (`0x120`) | `0x01FFF2E0` | `0x01FFF400` | `abi.h:53-54,277` |
| control (`SlinkControlV2`) | `0x800` | `0x600` | `0x01FFF400` | `0x01FFFA00` | `abi.h:60-61,282` |
| reserved | `0xE00` | `0x200` | `0x01FFFA00` | `0x01FFFC00` | `abi.h:62,283` |

`0x01FFFA00 + 0x200 = 0x01FFFC00`: the layout closes exactly on the span end.

### 2.3 Mailbox header fields (absolute)

| Field | Mailbox offset | Absolute | Owner at C2 |
|---|---|---|---|
| `signature` (`SLINK_SIGNATURE 0x4B4E4C53` = `"SLNK"`) | `0x00` | `0x01FFEC00` | ROM |
| `abi_version` (NDS = `3`) | `0x04` | `0x01FFEC04` | ROM |
| `opcode` | `0x06` | `0x01FFEC06` | host |
| `seq` | `0x08` | `0x01FFEC08` | host |
| `status` | `0x0A` | `0x01FFEC0A` | ROM |
| `ack_seq` | `0x0C` | `0x01FFEC0C` | ROM |
| `reason` | `0x0E` | `0x01FFEC0E` | ROM |
| `args[32]` | `0x10` | `0x01FFEC10` | host |
| `result[16]` | `0x30` | `0x01FFEC30` | ROM |
| `capabilities` | `0x40` | `0x01FFEC40` | ROM |
| `session_epoch` | `0x44` | `0x01FFEC44` | host |
| `producer_phase` | `0x48` | `0x01FFEC48` | ROM |
| `reserved` → **boot generation** | `0x4C` | `0x01FFEC4C` | ROM |

Source: `abi.h:148-159`. Cross-checked against the host-side compiled layout
(`mailbox_abi_version=4`, `mailbox_session_epoch=68`, `mailbox_producer_phase=72`,
`lua/nds/native_witness.lua:9`), which is itself generated by the host-C probe named at
`lua/nds/native_witness.lua:2-4`. The generation goes in `reserved` exactly as directed
(`FEATURE_BAR.md:254`: *"map it to `SlinkMailboxV2.reserved` @0x4C, ROM-owned, zero bytes
added"*).

### 2.4 Where the C2-only bytes go — a decision needing the coordinator's ack

The blob/text/menu/info regions belong to C3–C5 and the witness to C5. The only region the ABI
itself declares free on NDS is `SLINK_RESERVED`: *"Gen 3 call region: reserved, unused on NDS
v1"* (`abi.h:62`), which exists solely for the Match Call record that is *"never advertised"*
on NDS (`abi.h:70`, `patch/src/nds/common/README.md:108`).

**DECISION (D-C2-1), corrected 2026-10-04:** only the versioned, published
64-byte title block occupies `0xE00..0xE40` in the arena (absolute
`0x01FFFA00..0x01FFFA40`). The remainder `0xE40..0x1000` stays free. Private
cookie/identity/clock latches live in the service's heap `SlinkGen4State`, not ROM-private
cells in this window. Authoritative layout: `patch/src/nds/gen4/beacon.h:49-66` at c1046d07;
private state: `:97-111`. No shared ABI field is moved.

| Offset from title base | Size | Published field | Owner |
|---|---|---|---|
| `+0x00` | u32 | magic `0x34474C53` (little-endian `SLG4`) | ROM writes, host validates |
| `+0x04` | u16 | version `1` | ROM writes, host validates |
| `+0x06` | u16 | size `0x40` | ROM writes, host validates |
| `+0x08` | u32 | cookie | ROM writes, host reads |
| `+0x0C` | u32 | identity (`PlayerProfile.id`) | ROM writes, host reads |
| `+0x10` | u32 | engine-clock delta | ROM writes, host reads |
| `+0x14` | u32 | session generation, mirrors mailbox `+0x4C` | ROM writes, host reads |
| `+0x18` | u32 | registrations | ROM writes, host reads |
| `+0x1C..+0x40` | 36 bytes | reserved, zero headroom | ROM writes; host may report raw copy |

The superseded draft placed cookie at `+0` and invented private cells at `+0x0C/+0x10/+0x14`.
Those addresses now hold published fields; they are not forbidden/private reads.

---

## 3. ROM side

### 3.1 HG/SS (pret source rebuild)

One new source file, `patch/src/nds/gen4/beacon.c`, copied into the pinned build tree by
`tools/build_gen4_companion.py` (the C2 per-title file list is `PLAN.md:42,63`; the build
modelled on `build_gen2_companion.py` is `PLAN.md:34,43`). The pret tree is never edited in
place; the build runs in a cache directory (`PLAN.md:34`).

Functions to add:

| Function | Role |
|---|---|
| `void Slink_NDS_Register(void)` | Called once per boot. Mints the cookie, increments the boot generation, clears every host-owned request field (the reset latch), creates the service task. |
| `static void Slink_NDS_Service(void *arg)` | The per-tick body (§3.3). |
| `static u32 Slink_NDS_SaveIdentity(void)` | Reads the current save identity (see §4.3). |

Registration site — **one call, `NitroMain`, before the first app**:

- `NitroMain` starts at `src/main.c:50`; `InitSystemForTheGame()` is the first statement
  (`src/main.c:51`) and is what creates `gSystem.mainTaskQueue`
  (`src/system.c:123-126`, arena-allocated via `OS_AllocFromArenaLo(OS_ARENA_MAIN, …)`).
- The first app is registered at `src/main.c:77`
  (`RegisterMainOverlay(FS_OVERLAY_ID(OVY_36), &ov36_App_MainMenu_SelectOption_Continue)`).
- Therefore `Slink_NDS_Register()` goes **after `src/main.c:51` and before `src/main.c:77`**, so
  the queue exists and the service is live before any overlay can run.
  (corrected 2026-10-03: the decision block pins the site at the **first** `RegisterMainOverlay`,
  `main.c:77`; the draft's `:83` was the wrong call.)
- `SysTask_CreateOnMainQueue(func, data, priority)` is
  `SysTaskQueue_InsertTask(gSystem.mainTaskQueue, func, data, priority)`
  (`src/sys_task_api.c:7-9`) — a static-ARM9 function, already `.public` in overlay symbol
  includes, so the call needs no new plumbing.

**Re-registered every boot.** The main-queue service does **not** survive a soft reset:
START+SELECT+L+R → `DoSoftReset` (`src/main.c:101-105`, body `src/main.c:205-215`) →
`sub_02000F40` → `OS_ResetSystem(param)` (`src/main.c:180-185`, the call is at `:182`). The
`SysTask` dies with the old process, so registration must sit in `NitroMain`, not in a
one-shot app.

> Citation drift to fix: `FEATURE_BAR.md:208` cites `src/main.c:203-210` for
> `DoSoftReset -> OS_ResetSystem`. At the pinned pret those lines are
> `src/main.c:205-215` (the `DoSoftReset` body) with the `OS_ResetSystem` call at
> `src/main.c:182`. Same facts, wrong lines. **UNVERIFIED** that the pinned tree the
> coordinator read was the same revision; `ad7a3afa` is what I read.

### 3.2 hge (in-fork)

- The fork ships **no** `main.c`, `system.c` or `sys_task.c`, so a `SysTask` cannot be
  registered the same way (`FEATURE_BAR.md:215`).
- hge hooks **none** of `NitroMain`, `SysTaskQueue_RunTasks`, `Task_RunScripts` or the VBlank
  callbacks (`FEATURE_BAR.md:214`), so the vanilla `mainTaskQueue` drain at `src/main.c:111`
  is still the drain point on hge. A task created on `gSystem.mainTaskQueue` therefore runs on
  hge too — **INFERRED**, and it must be measured (it is falsifier 4, §6).
- Two **former** registration routes, both from `FEATURE_BAR.md:215,245`, **both now superseded**
  by the `SaveData_New` ruling below (corrected 2026-10-03: this list was live; it is history):
  1. a `hooks` row in the fork; or
  2. ride hge's own boot path `load_arm9_expansion`, called from `Main` at frame 9
     (`FEATURE_BAR.md:215`; the symbol row is `load_arm9_expansion` at `0x02110334`, Thumb,
     `.text`, `data/games/gen4_hge/profile.json:4514-4529,5383-5386`).
- **Forbidden:** hooking `0x02000CD0`. That address is hge's own `bl load_arm9_expansion`
  from `Main` (`tools/gen_gen4_pack.py:2310`, `data/games/gen4_hge/profile.json:65,96-99`)
  **and** our hge-discriminating admission anchor (`tests/unit/test_gen4_pack.py:1072-1073`).
  Breaking it would make an hge ROM pass as vanilla (`tools/gen_gen4_pack.py:2336-2340`).

**DECISION (D-C2-2, owner) — SUPERSEDED, retained for history.** The draft recommended route 2
(ride `load_arm9_expansion`). That recommendation is **void**. The decision block
(`C2_BEACON_SPEC.md:15-19`) rules: **hge already replaces `SaveData_New`** (its only vanilla
caller is `src/main.c:64`, during boot; `hooks:402`) with its own `src/save.c:139`, so the
register call is appended before its `return`, and there is **no new `hooks` row**. That code
calls `CreateSysTask`, which the fork already binds to `0x0200E320|1` = vanilla
`SysTask_CreateOnMainQueue` (`rom.ld:477`, `include/task.h:51`).
(corrected 2026-10-03: D-C2-2 and every `load_arm9_expansion` passage in this section are
superseded by the `SaveData_New` ruling. It is a one-line fork source edit, like the accepted C5
commonscript edit, and it beats both former options: it needs no new row, no new hook-budget line,
and it runs on every boot including a soft reset.)

**Also void:** the "**INFERRED** that `load_arm9_expansion` at frame 9 runs *after*
`InitSystemForTheGame()`" reasoning, and the open question built on it (§8 Q3). `SaveData_New` is
called from `src/main.c:64`, which is unconditionally after `:51`, so the premise is stronger
there, not weaker.

### 3.3 Exact fields written per tick

On **every** service visit, `Slink_NDS_Service` writes, in this order:

1. `signature` `0x01FFEC00` = `SLINK_SIGNATURE`; `abi_version` `0x01FFEC04` = 3. This is the
   Gen 2 "header repair" rule, which *"never clears host requests, panel state, holds or lease
   bytes"* (`patch/gen2/src/slink.asm:56-67`) — it re-stamps the ROM-owned header only.
2. `capabilities` `0x01FFEC40` = the build's advertised set (0 at C2, §5).
3. `session_epoch` is **not** written (host-owned). The ROM only *checks* it (§6 falsifier 3).
4. `producer_phase` `0x01FFEC48` = `SLINK_PHASE_IDLE` (0) at C2 (`abi.h:110`).
5. `reserved`/generation `0x01FFEC4C` = the current boot generation (§4.2).
6. `status` `0x01FFEC0A`: stays `SLINK_ST_BUSY` (1) while a host request is outstanding; set
   to `SLINK_ST_OK` (2) or `SLINK_ST_FAIL` (3) when the ROM finishes one (`abi.h:97`). At C2
   the ROM acknowledges and clears nothing but the sequence (§6, falsifier 3), because C2 has
   no command to execute.
7. `ack_seq` `0x01FFEC0C` = the `seq` of the request the ROM has consumed.
8. Delta accumulation: `d = (u32)(gSystem.vblankCounter - last_sample)`,
   `last_sample = gSystem.vblankCounter`, `delta += d`; publish `delta` to title `+0x10` (`0x01FFFA10`).
9. Identity check (§4.3): compare `Slink_NDS_SaveIdentity()` to the heap state's `identity` latch; on change run the reset latch (§4.4).
10. Republish cookie (`0x01FFFA08`) and identity (`0x01FFFA0C`) every tick. They are stable
    values, republished so that a host write into them is transient and always observable.

Fields the ROM **never** writes at C2: `opcode`, `seq`, `args[]`, `session_epoch`, and the
whole witness, blob, text, menu, info and control regions.

---

## 4. Liveness

Three independent facts, three independent failure modes. This is the Gen 2 rule generalised:
`FEATURE_BAR.md:255` — *"a private per-boot cookie plus an engine-clock delta … MORE necessary
here, because ITCM survives soft reset."*

### 4.1 The per-boot private cookie — the service SysTask's own heap data block, NOT DTCM

**Requirement (unchanged):** a latch whose value at the start of every boot is a known constant,
so the ROM can tell "first service visit of this boot" from "mid-boot".

**The ruling (decision block, `C2_BEACON_SPEC.md:5`):** the private cookie lives in the **service
SysTask's own heap data block** — allocated in NitroMain init **every boot**, freed by any reset,
read only by the ROM. It is **NOT in DTCM.**

**Why DTCM is excluded.** C1 excluded the DTCM arena because it is the **launcher stack**
(`lib/NitroSDK/src/os/os_thread.c:24-26`). The arena tail
`SDK_SECTION_ARENA_DTCM_START` (`0x027E0080`, `FEATURE_BAR.md:146`) is therefore not a candidate
for the latch either.

**The heap block is strictly better than the DTCM row this replaces,** on every axis the old
reasoning cared about:

1. **Freshness is structural, not argued.** The block is `OS_AllocFromArenaLo`-allocated inside
   `Slink_NDS_Register()` in `NitroMain`, so it cannot exist before the first boot tick and is
   destroyed by `OS_ResetSystem`. "Zero at the start of every boot" is a lifetime fact, not a
   link-order fact.
2. **No DTCM census rows are needed.** The old §4.1 carried an **Open/UNVERIFIED** note that the
   C1 census does not cover DTCM (`span_check` accepts only ITCM-arena spans,
   `gen4_mailbox_census.py:120-124`; the W3 reset analysis checks the ITCM autoload bss but not
   the DTCM block, `:373-375`). That entire open item disappears: there is no DTCM address to
   prove free.
3. **It is ROM-private by construction.** The host never sees it, so it cannot be confused with
   the published half (§2.4) and needs no `D-C2-1` carve-out.
4. **It costs one arena allocation** at registration, and the allocation is already made for the
   service task itself.

**What survives from the old §4.1, and is still load-bearing:** static ARM9 `.bss` is forbidden
for any of this state. Adding a static `.bss` symbol moves `0x021E5900` and therefore every
overlay address and every pinned hook site (`FEATURE_BAR.md:145`). The C0 result is explicit:
*"There is no free static RAM … The 'proven-free static span' mailbox route is dead."*
(`FEATURE_BAR.md:140-144`). The heap block is on the right side of that line; DTCM was on the
wrong one.

**VOIDED in this section** (retained here as history, not as live reasoning): the
`lib/asm/crt0.s:44-47` DTCM-clear row and every falsifier built on it. The ruling is that the
DTCM block is the **launcher stack**, i.e. live across a soft reset, so "cleared at every boot by
`crt0`" was not a property the latch could rely on. The heap block needs no such claim.
(corrected 2026-10-03: the DTCM cookie latch, D-C2-3 and the `crt0.s:44-47` falsifier reasoning
are removed as decisions; only the static-`.bss`-forbidden consequence is kept.)

**DECISION (D-C2-3): SUPERSEDED by the heap-block ruling above.** The private cookie latch is one
`u32` inside the service SysTask's heap data block, read only by the ROM, re-created each boot.

### 4.2 Boot generation

`u32` at mailbox `reserved` `0x01FFEC4C`. Incremented once per `Slink_NDS_Register()`, i.e.
once per boot. It answers *"which boot"* (`FEATURE_BAR.md:256`). It is ROM-owned and is
re-stamped every tick, so a host write to it is visible within one service visit.

> **Correction to the coordinator's framing, and the one place I disagree with the brief.**
> A generation that only counts boots does **not** change on New Game, because New Game never
> re-enters `NitroMain`: the chain is main menu → `ov36_TitleScreen_NewGame_AppExec` →
> `ov36_App_InitGameState_AfterOakSpeech_AppExec` → field (`src/overlay_36.c:101-141`,
> `docs/gen4/research/new_game_route.md:11-26`). The brief's falsifier *"a stale cookie after
> New Game is NOT live"* therefore cannot be satisfied by a boot counter alone.
>
> **DECISION (D-C2-4):** the generation is a **session epoch**: it increments on registration
> (so a soft reset always changes it — falsifier 2 holds) **and** on every detected change of
> the save identity (§4.3). This is a superset of `FEATURE_BAR.md:256` ("which boot"), not a
> contradiction of it. Flagging it because it is a deliberate deviation.

### 4.3 The session identity the ROM samples each tick

The ROM samples one `u32` per tick: the player profile id.

```
SaveData *sd = SaveData_Get();                                  // include/save.h:93
PlayerProfile *p = Save_PlayerData_GetProfile(sd);              // include/player_data.h:36
identity = p->id;                                               // include/player_data.h:14
```

`PlayerProfile` is `{ u16 name[PLAYER_NAME_LENGTH+1]; u32 id; u32 money; … }`
(`include/player_data.h:12-25`). This is the HG/SS analogue of the OT ID the server already
locks on (the player-identity lock, `docs/gen4/companion/PLAN.md`, §"Player Identity Lock").

Why this catches the events that matter:

| Event | Effect on the identity | Evidence |
|---|---|---|
| New Game wipes the save | `NewGame_InitSaveData` → `Save_InitDynamicRegion(saveData)` | `src/overlay_36.c:104,251-254` |
| New Game assigns a new id | `InitGameStateAfterOakSpeech_Internal(…, TRUE)` (the `set_trainer_id` parameter) | `src/overlay_36.c:129,180` |
| Continue on a failed load | `SaveData_TryLoadOnContinue` fails → `OS_ResetSystem(0)` → new boot | `src/overlay_36.c:246-248` |
| Delete save data | `OS_ResetSystem(0)` → new boot | `src/application/delete_savedata.c:210` |
| Erased cartridge | `OS_ResetSystem(0)` → new boot | `src/game_clear.c:253` |
| Reset from the error screen | `OS_ResetSystem(0)` → new boot | `src/error_message_reset.c:181` |

The Oak chain changes the id more than once (blank → set at `overlay_36.c:129`), so a New Game
produces a **burst** of generation changes. §6's host rule tolerates a burst by requiring the
triple to be stable for K consecutive polls before declaring live.

### 4.4 The reset latch

On a generation change the ROM must not leave host intent from the previous session in a place
the new session will honour. On detection, in one uninterrupted block:

- `generation += 1`, republish cookie (new mint) and identity;
- `opcode = 0`, `seq = 0`, `ack_seq = 0`, `status = SLINK_ST_BUSY (1)`,
  `args[32] = 0`, `result[16] = 0`;
- `producer_phase = SLINK_PHASE_IDLE (0)`;
- zero the whole witness region `0x01FFEC50 .. 0x01FFECA0`;
- latch the new identity and clock sample in the private SysTask heap state.

This is the Gen 1/2 "reset latch" discipline the shared NDS layer is meant to generalize
(`PLAN.md:47`).

### 4.5 The engine clock and the 256-aliasing caveat

**Use `gSystem.vblankCounter`, never `gSystem.frameCounter`.**

| Fact | Evidence |
|---|---|
| `struct System` declares `u32 vblankCounter;` then `u32 frameCounter;` | `include/system.h:33-34` |
| `vblankCounter` is incremented at least once per outer loop iteration | `src/main.c:123` (always), `:115` (inside the guard) |
| `frameCounter` is **zeroed** every iteration | `src/main.c:124` |
| `frameCounter` is incremented only in the VBlank callback | `src/system.c:24` |
| the game uses `frameCounter` as a "need another VBlank" flag, not a clock | `src/main.c:113-116` |

A `u16`/`u8` engine counter cannot be the Gen 4 clock for three separate reasons, and each
deserves to be written down because the brief bundles them as one "256-aliasing caveat":

1. **Gen 2's byte caveat does not transfer.** Gen 2 samples `hVBlankCounter`, a byte, and its
   own comment warns that *"unsigned deltas lose whole multiples of 256 if the service is not
   visited between source increments"* (`patch/gen2/src/slink.asm:88-90`). `vblankCounter` is
   a `u32`, so a skipped visit loses nothing — the delta is the true difference. **What
   replaces the caveat is a magnitude caveat:** the service visits at most once per outer loop
   iteration and only inside `if (sub_02036144())` (`src/main.c:106-117`), so under a
   wireless/link session a visit can be skipped for an unbounded number of frames. The host's
   liveness rule must be *"the delta advanced at all within N polls"*, **never** *"advanced by
   exactly N"*.
   **INFERRED:** with the guard true the counter advances **twice** per iteration
   (`src/main.c:115` and `:123`), once otherwise. Must be measured, not assumed.
2. **`frameCounter` aliases every frame.** It is cleared at `src/main.c:124` and only ever
   takes the value 0 or 1 between iterations, so it would alias on every single poll. It is
   **forbidden** as a liveness clock. Any implementation that reaches for it is wrong.
3. **The arena itself is aliased.** The same 4 KiB is reachable at `0x01FFEC00` (ARM9 CPU) and
   at `0x6C00` (the ITCM mirror, which is how BizHawk's `"Instruction TCM"` domain presents it)
   — `gen4_mailbox_census.py:268,513-514`. The host **must** read the ITCM domain, never the
   ARM9 bus mirror of it, and probe row `a` exists precisely to keep the two windows agreeing
   (`lua/tests/probe_gen4_mailbox.lua:8,105`).
4. **Sequences wrap.** `seq`/`ack_seq` are `u16` (`abi.h:151-152`). The host compares them
   with wrap-safe arithmetic; a plain `>` is a defect waiting for tick 65536.
5. **The GB lineage's own counter is 16-bit, so the precedent is worse than Gen 4.** Gen 1
   stamps a *"16-bit little-endian frame counter at +5"* with an explicit carry only when the
   low byte rolls over (`patch/gen1/src/slink.asm:166-173`). Gen 2 widens it to two bytes
   (`patch/gen2/src/slink.asm:99-113`). Gen 4 sources a **u32** delta from a u32 engine
   counter (`include/system.h:33`), which removes that wrap from the liveness path — but the
   mailbox's own `u16` sequences still carry it.

---

## 5. Capabilities

- The **ROM** writes `capabilities` (`0x01FFEC40`) every tick. The **host never writes it**
  (`FEATURE_BAR.md:258`: *"the ROM owns signature/version/caps/status/witness/boot/liveness;
  the host owns opcode/args/stage/info request fields"*).
- **At C2 the advertised set is `0`.** Only beacon/caps/liveness ship; C3 adds
  `SLINK_CAP_NATIVE_SOUND`, C4 adds `SLINK_CAP_INFO_PANEL`, C5 adds
  `SLINK_CAP_DURABLE_TRADE` (`abi.h:88-96`). No C2 build may set a bit ahead of its card —
  that is exactly how a build advertises a capability it does not implement.
- **There is no beacon capability bit.** The shared enum
  (`DURABLE_TRADE | INFO_PANEL | NATIVE_SOUND | EXPLODE | RIVAL_SWAP | BATTLE_CALC |
  MATCH_CALL`, `abi.h:88-96`) has no "beacon" or "liveness" member. **Therefore the host must
  not require any capability bit to consider C2 live** — the beacon's existence is proven by
  `signature` + `abi_version` alone. A host that gates liveness on a capability bit can never
  go live at C2. This is a real trap and it is the reason §6's rule lists the header fields
  first.
- Gen 4 must never set `SLINK_CAP_EXPLODE`, `SLINK_CAP_RIVAL_SWAP` (Radical Red concepts),
  `SLINK_CAP_BATTLE_CALC` (RR only) or `SLINK_CAP_MATCH_CALL` (*"keeps its id, never
  advertised"*, `abi.h:70`, `patch/src/nds/common/README.md:108`).
- `SLINK_CAP_TRADE` as a *name* is a Gen 1 defect: the Gen 1 build links and ships a trade but
  never advertises it (`patch/gen1/src/slink.asm:163-164`, `FEATURE_BAR.md:38`). Gen 4 must
  not copy that inconsistency: C5 sets `SLINK_CAP_DURABLE_TRADE` in the same commit that adds
  the commit primitive.
- Capability bits stay **opaque to verification** and are only vocabulary-level checked against
  `abi.h` (`docs/shared-nds-companion.md:196-199`). A capability bit is never an admission or
  qualification claim (`patch/src/nds/common/README.md:6-7`).

---

## 6. Host side and the falsifiers

### 6.1 What `lua/gen4` reads

`lua/gen4/companion.lua` is the title binder, composed with NEW shared
`lua/nds/mailbox.lua` (side branch `claude/gen4-nds-mailbox@1f339a29`). Both are **pure readers**: no writes, no emulator API beyond read, no retained
transaction state — the discipline `lua/nds/native_witness.lua:1` already sets.

Reads per poll, from `base = 0x01FFEC00`:

| Read | Address | Why |
|---|---|---|
| `signature` | `0x01FFEC00` | must equal `0x4B4E4C53` |
| `abi_version` | `0x01FFEC04` | must equal `3` |
| `capabilities` | `0x01FFEC40` | informational at C2; the future C3–C5 gate |
| `session_epoch` | `0x01FFEC44` | binds the request the host is about to publish |
| `producer_phase` | `0x01FFEC48` | must be `0` at C2 |
| Gen4 generation mirror (shared reader calls it reserved) | `0x01FFEC4C` | opaque to shared code; title-specific liveness |
| title magic / version / size | title `+0x00 / +0x04 / +0x06` | validate `SLG4`, 1, 0x40 before payload |
| cookie / identity / delta | `0x01FFFA08 / 0x01FFFA0C / 0x01FFFA10` | liveness and title identity |
| title generation / registrations | `0x01FFFA14 / 0x01FFFA18` | epoch mirror / registration observation |
| reserved[36] | title `+0x1C..+0x40` | report raw headroom; never a liveness gate |

**`native_witness.lua` is not applicable at C2, and this is a constraint, not a preference.**

- Its reader requires a valid witness revision — `if before == 0 … return "snapshot:revision"`
  (`lua/nds/native_witness.lua:166`) — and a zero witness is exactly what a C2 arena holds, so
  every read fails.
- It requires a full identity context (epoch, visit, pid, otid, 16 opaque token bytes) before
  it returns anything (`lua/nds/native_witness.lua:158-185`); that is C5 machinery.
- Its mailbox header read is a **local** function (`lua/nds/native_witness.lua:152-157`), not
  exported, so C2 cannot reuse it as-is.
- Editing that EXISTING module still belongs to C7. The C2 amendment instead permits a
  NEW `lua/nds/mailbox.lua`; it reads no witness revision or transaction identity. See
  `docs/shared-nds-mailbox.md` for its six-scalar consistency limit.

So: from C5 onward `native_witness` is the reader for the witness region and
`lua/nds/mailbox.lua` is the raw mailbox reader beneath `lua/gen4/companion.lua`. Both are cross-checked against
the same compiled layout (`lua/nds/native_witness.lua:2-4,9`) and against `abi.h`'s static
asserts (`abi.h:261-286`).

The ABI-3 PENDING rule is inherited verbatim when C5 arrives: under ABI ≥ 3,
`save_status == 2` is legal **only** while milestone bits `POST_SAVE_OK` (8) and `FINAL_RESULT`
(16) are both clear, and success still needs `save_status == 1` plus all five milestones
(`patch/src/nds/common/README.md:32-35`; implemented at `lua/nds/native_witness.lua:195-198`).
At C2 the rule is vacuous — no witness exists — and the host must not carry a C5 witness rule
forward into the beacon path.

### 6.2 The host's "live" rule

`live` is true only if **all** hold on one poll:

1. `signature == 0x4B4E4C53`;
2. `abi_version == 3`;
3. `generation` equals the generation the host bound to, **and** the cookie equals the cookie
   learned for that generation;
4. the delta has advanced since the previous poll;
5. `producer_phase == 0`;
6. (for any publish) `session_epoch` is the host's own nonzero epoch.

and the host has observed an unchanged `(generation, cookie)` pair advancing delta for **K
consecutive polls** before it treats the beacon as live at all. K is a **MODEL** number; the
default that survives a New Game burst is 3, and the Oak chain (§4.3) is the burst it is sized
against. **INFERRED** — measure it at C2 MODEL.

Any change to `generation` or `cookie`, or a stalled delta for N polls, ⇒ **not live**: drop
every outstanding request, drop the bound epoch, and re-handshake. The host must not replay a
request across a generation change.

### 6.3 The falsifiers

| # | Falsifier | Passes when | Evidence |
|---|---|---|---|
| 1 | **A stale cookie after New Game is NOT live.** | Run the New Game route (`docs/gen4/research/new_game_route.md:67-80`) with the host attached. The id is wiped and re-set (`src/overlay_36.c:104,129,251-254`), so the generation changes, the cookie is re-minted, and the host reports **not live**, drops the bound epoch and refuses to publish. A host that stays live here is the defect. | `PLAN.md:63`; §4.2, §4.3 |
| 2 | **After a soft reset the generation changes.** | Trigger START+SELECT+L+R (`src/main.c:101-105`). `OS_ResetSystem` (`src/main.c:182`) re-runs `crt0` and tears down the process, so the service SysTask's heap data block — which held the cookie latch — is freed and the latch is gone; the ROM re-registers in `NitroMain` (`src/main.c:50-77`) and `generation` is strictly greater than before. The host must see the change within one post-reset poll. | §3.1, §4.1, §4.2 | (corrected 2026-10-03: the old pass condition leaned on `crt0` clearing DTCM (`crt0.s:44-47`); that reasoning is void — DTCM is the launcher stack. The heap block is freed by the reset regardless.) |
| 3 | **A host write into a ROM-owned field is refused.** | Two halves. (a) *Host*: `lua/gen4/companion.lua` exposes no write path at all — an attempted write is a MODEL failure, not a runtime no-op. (b) *ROM*: a watch/canary that flips one ROM-owned byte (`capabilities`, `status`, `producer_phase`, `generation`, `cookie`) must observe it **restored within one service visit** and the change **visible to the host** as a liveness violation, because the header is re-stamped every tick (`patch/gen2/src/slink.asm:56-67`). A surviving write is a fail, not a soft repair. | §3.3, §7 |
| 4 | **The tick advances in field / every START-menu app / battle / SAVE / a fade / an overlay load / after a soft reset.** | The published delta advances in each of those states. This is the recorded C2 falsifier (`FEATURE_BAR.md:216`) and it is the only evidence that the `mainTaskQueue` site is app-independent (`src/main.c:109-111`) and arena-allocated so it survives app and overlay switches (`src/system.c:123-126`). | `FEATURE_BAR.md:203-216` |

Falsifier 4 has one known hole I am flagging rather than papering over: the drain at
`src/main.c:111` sits **inside** `if (sub_02036144())` (`src/main.c:106`), the wireless/link
frame-sync gate. With no comm session it branches straight out and single-player always drains
(`FEATURE_BAR.md:209-210`), so the honest reading is that C2 is proven **for single-player
only**. If a link session must also be covered, the insurance site is `gSystem.vwaitTaskQueue`,
which drains outside the guard at `src/main.c:131` (`FEATURE_BAR.md:211`). Decide at C2, not
later.

---

## 7. Single-writer table

| Field | Address | Writer | Reader | Notes |
|---|---|---|---|---|
| `signature` | `0x01FFEC00` | **ROM** | host | re-stamped every tick |
| `abi_version` | `0x01FFEC04` | **ROM** | host | `3`, NDS only (`abi.h:38,284`) |
| `opcode` | `0x01FFEC06` | host | ROM | `0` at C2; ROM consumes and clears |
| `seq` | `0x01FFEC08` | host | ROM | `u16`, wraps (§4.5.4) |
| `status` | `0x01FFEC0A` | **ROM** | host | |
| `ack_seq` | `0x01FFEC0C` | **ROM** | host | |
| `reason` | `0x01FFEC0E` | **ROM** | host | |
| `args[32]` | `0x01FFEC10` | host | ROM | |
| `result[16]` | `0x01FFEC30` | **ROM** | host | |
| `capabilities` | `0x01FFEC40` | **ROM** | host | `0` at C2 (§5) |
| `session_epoch` | `0x01FFEC44` | host | ROM | zero = unarmed (`abi.h:98,156`) |
| `producer_phase` | `0x01FFEC48` | **ROM** | host | `0` at C2 |
| generation (`reserved`) | `0x01FFEC4C` | **ROM** | host | zero bytes added to the ABI |
| witness (all) | `0x01FFEC50` | **ROM** | host | zero at C2; host read only from C5 |
| blob / stage | `0x01FFED00` | host (C5) | ROM | zero at C2 |
| text | `0x01FFEF60` | host (C4) | ROM | zero at C2 |
| menu | `0x01FFF160` | host (C4) | ROM | zero at C2 |
| info | `0x01FFF2E0` | host req / ROM drawn (C4) | both | split per `abi.h:207-217` |
| control | `0x01FFF400` | host (C5) | ROM | zero at C2 |
| title magic / version / size | `0x01FFFA00 / +4 / +6` | **ROM** | host | versioned header |
| published cookie | `0x01FFFA08` | **ROM** | host | |
| published identity | `0x01FFFA0C` | **ROM** | host | |
| published delta | `0x01FFFA10` | **ROM** | host | |
| published generation | `0x01FFFA14` | **ROM** | host | mirrors mailbox +0x4C |
| registrations | `0x01FFFA18` | **ROM** | host | |
| reserved[36] | `0x01FFFA1C..0x01FFFA40` | **ROM** | raw-copy host reader | zero headroom |
| private cookie / identity / clock / boot latch | SysTask heap block | **ROM** | *nobody* | never title-window cells |

The published block and private heap state are distinct (`beacon.h:49-66,97-111`).
The host has no write path. The former title-window private-cell table and DTCM latch are void.

---

## 8. Open questions

1. **D-C2-1 CLOSED:** the ABI-owner ruling permits the published 0x40-byte title block at
   offset 0xE00; private state is heap-only (§2.4). The larger reserved tail is not claimed.
2. ~~**DTCM latch proof (§4.1).**~~ **CLOSED / VOID.** The latch is not in DTCM, so the DTCM
   W1/W2/W3 census rows are not needed. The reasoning that required them assumed
   `crt0.s:44-47` cleared a usable block; the ruling is that DTCM is the launcher stack
   (`lib/NitroSDK/src/os/os_thread.c:24-26`) and the latch lives in the SysTask heap block
   (`C2_BEACON_SPEC.md:5`). (corrected 2026-10-03: removed as an open question.)
3. ~~**D-C2-2 (§3.2):** does the owner accept `Slink_NDS_Register` riding hge's
   `load_arm9_expansion`, or must it be a `hooks` row?~~ **CLOSED — SUPERSEDED.** Neither.
   Registration is appended to hge's own `SaveData_New` replacement at `src/save.c:139`
   (`hooks:402`), with no new row of any class. (corrected 2026-10-03: replaced by the
   `SaveData_New` ruling; the "UNVERIFIED that `gSystem.mainTaskQueue` exists at frame 9" tail is
   moot, because `SaveData_New` is called from `src/main.c:64`, after `:51`.)
4. **Session epoch vs boot generation (§4.2).** I widened the coordinator's "which boot" to
   "which boot **or** which save session". Without the widening, falsifier 1 is unsatisfiable.
   Accepted by D-C2-4 above; the title binder MODEL covers epoch/cookie changes
   (`claude/gen4-nds-mailbox@1f339a29`, `test_gen4_companion.py:462-490`).
5. **Oak-chain burst tolerance (§6.2).** K = 3 is **INFERRED**. Measure it: how many
   generation changes does the New Game route produce, and over how many polls?
6. **`sub_02036144()` gate (§6.3).** Is a link/wireless session in scope for C2? If yes, the
   service needs the `vwaitTaskQueue` insurance site (`src/main.c:131`, `FEATURE_BAR.md:211`)
   and falsifier 4 gains a link leg.
7. **Cookie mint source (§4.1).** Whether the mint is `H(ROM_CONST, OS_GetTick())` at
   registration or a stronger mixer. `OS_GetTick` is available (`src/main.c:96,108,110`); the
   choice is **INFERRED** and cheap to change at C2 SOURCE.
8. **BizHawk read window (§4.5.3).** The host reads the `"Instruction TCM"` domain
   (`lua/tests/probe_gen4_hooks.lua:539`). ARM9 CPU-local ITCM access is coherent by construction,
   but "ARM9/ARM7 cache coherence" is listed as *not* proven by the shared stack
   (`patch/src/nds/common/README.md:154`). Probe row `a` covers the ITCM window
   (`lua/tests/probe_gen4_mailbox.lua:8,105`); the cookie latch is a heap-block cell the host
   never reads, so it needs no domain receipt. (corrected 2026-10-03: the sentence no longer says
   "DTCM/ITCM" — DTCM is not part of the companion's footprint.)
9. **Citation drift (§3.1).** `FEATURE_BAR.md:208` cites `src/main.c:203-210` for
   `DoSoftReset -> OS_ResetSystem`; at `ad7a3afa` that is `src/main.c:205-215` with the call at
   `:182`. Also `docs/gen4/research/new_game_route.md:24` cites `overlay_36.c:145` for the
   trainer-id set, but `:145` is `InitializeMainRNG()` inside the **Continue** app; the id is
   set via the `set_trainer_id` parameter at `src/overlay_36.c:129,180`. Both are one-line
   fixes in docs I do not own.
10. **Out of C2 but named here so it is not lost:** the FAILURE SE is an unresolved owner
    content choice (`DECISIONS_2026-10-02_companion.md:16`, `FEATURE_BAR.md:175`). C3 may ship
    without code 2 wired and **must say so**.

---

## 9. What this card must not do

- No byte of `patch/src/nds/common/abi.h` changes; no Gen 5 shared-header conflict.
- No static ARM9 `.bss` symbol in the HG/SS rebuild (`FEATURE_BAR.md:145`).
- No new BizHawk exec hook. The host reads the mailbox by polling only; the owner's ruling
  allows zero steady-state hooks and one on-demand hook (`PLAN.md:95`).
- No write to a ROM-owned field, and no read of the private heap state. The published title payload and raw reserved tail are host-readable.
- No capability bit advertised ahead of its card (§5).
- No box/trade arm; trade is party-only (`DECISIONS_2026-10-02_companion.md:12`).
- No `PlaySE` from the vblank queue or `gSystem.vBlankIntr` — both are IRQ context
  (`FEATURE_BAR.md:212`, `src/system.c:20-25`, `src/main.c:127-128`).
- No ROM build before the C1 live canary accepts the span (§2.1).