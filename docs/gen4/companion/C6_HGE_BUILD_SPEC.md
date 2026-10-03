> **Status: DRAFT** (OMP cx-c385df62, 2026-10-02). The coordinator's review decisions are below; they WIN over the draft.
>
> - **The START row uses `repoints`, not `hooks`: ACCEPTED** (verified `hg-engine/repoints:44-46`, a 3-entry ARM9 function-table repoint). Only the inhibit-bit clear is a `hooks` row. FEATURE_BAR is corrected.
> - **The 36 B ARM9 expansion stub is full, so the C2 service registration rides a vanilla ARM9 site (an 8 B hook) or load_arm9_expansion's tail. ACCEPTED as a constraint**; the site is chosen at C6 SOURCE against all existing `hooks` rows.
> - **SUPERSEDED by the registration decision:** the service registers from hge's own `SaveData_New` replacement (`hg-engine/src/save.c:139`, hooked at `hooks:402`), with no new hook row. A `hooks` 4-field row REPLACES a function (`scripts/make.py:151-155`); the non-destructive 3-field form needs at least 0x1C bytes, so it is the fallback only. See C2_BEACON_SPEC's decision block.
> - **ov129 growth has no bounds check: ACCEPTED as a hard gate.** The first C6 build asserts ov129 memSize <= 0x7FA0 from the overlay table, plus `Slink_*` symbols in offsets.ini.
> - **Q2 ("the generic ORIGIN parser drops a hex digit") is REJECTED.** `line.split()[4]` is `"0x023C8000,"`, and `[len("0x"):-1]` strips the `0x` prefix AND the trailing comma, giving `023C8000` (correct). This matches the coordinator's ROM-table measurement (ov130 0x023C4000, ov131 0x023C8000).
> - The nurse line-number corrections in C5 and the ov131 origin (`src/field/linker.ld:5`) are ACCEPTED.
> - **The owner gate stands:** no fork branch, commit or build without the owner's approval of a SLink branch of hg-engine.
>
# Gen 4 companion C6: the hge in-fork build (SPEC draft, 2026-10-02)

**Status:** a specification draft for coordinator review and owner sign-off. Nothing here is built.
Every fact carries a `file:line`. Anything I reasoned to but did not read is marked **INFERRED**.
Anything I could not establish is marked **UNVERIFIED**.

**Card:** C6 (`docs/gen4/companion/PLAN.md:67`).

**Authority.** The coordinator decision blocks at the top of `C2_BEACON_SPEC.md:1-14`,
`C3_SOUND_SPEC.md:1-14`, `C4_PANEL_SPEC.md:1-18` and `C5_TRADE_SPEC.md:1-6` WIN over anything
below, and over any conflicting sentence in `FEATURE_BAR.md`. Where this draft cites
`FEATURE_BAR.md`, that is the *reconciled* text, not the original OMP draft.

**Fork paths.** All `hg-engine/...` citations are to the owner's checkout at
`E:/Howard/HGEngine_ROMHack/hg-engine`, recorded in the lock as
`data/gen4_sources.lock.json:183-189` (`hg_engine_fork.commit = fc5175764983…`, `tracked_clean:
true`). That commit **is** the fork's current `main`
(`hg-engine/.git/refs/heads/main` = `fc517576498305ecb5f5e1de44681c6e3822361b`), so the working
tree this draft reads is the pinned tree. **The ROM pin and the fork commit are two different
facts** in the lock (`artifacts.heartgold_hge.sha1` at `data/gen4_sources.lock.json:20` vs
`sources.hg_engine_fork.commit` at `:184`); C6 changes both.

---

## 1. Scope

### 1.1 What C6 adds to the fork

**One new overlay module plus rows and script/text edits.** Nothing else in the fork is touched.

| # | Fork change | Vehicle | Evidence for the vehicle |
|---|---|---|---|
| F1 | `hg-engine/src/slink/` — a new C overlay: the C2 service SysTask, the mailbox writer, the C3 sound table, the C4 row handler and panel app, the C5 `ScrCmd` | new directory, auto-discovered | `overlays.mk:7` (`OVERLAYS := … $(shell cd $(C_SUBDIR); ls)`), `:21-26` (wildcard `*.c`/`*.s` + `-T $(C_SUBDIR)/$1/linker.ld`), `:34` (`$(foreach overlay, $(OVERLAYS), $(eval …))`) |
| F2 | `hg-engine/src/slink/linker.ld` — **required**, first line `/* Overlay <id> */` | new file | `make.py:435-438` parses `line.split(" ")[2]` off the first line; `make.py:441-443` parses the first `ORIGIN` line |
| F3 | `hg-engine/hooks` rows (service entry, inhibit-bit filter) | append rows | `make.py:341-369` |
| F4 | `hg-engine/repoints` rows (the `START_MENU_ACTION_7` `.func`/`.ident`, `gScriptCmdTable[1]`) | append rows | `make.py:537-571`, `Repoint()` `:196-201`; precedent `repoints:44-46` |
| F5 | `hg-engine/armips/scr_seq/scr_seq_00003_commonscript.s` — the nurse branch (C5) | source edit | `FEATURE_BAR.md:166`; the nurse entry is this file at `:93` |
| F6 | `hg-engine/data/text/196.txt` — the START label (C4 decision) | new file, **CRLF** | `data/text/.gitattributes:1-2` (`* text eol=crlf`); `narcs.mk:21` (`MSGDATA_DEPENDENCIES := $(wildcard data/text/*)`) |
| F7 | `hg-engine/data/text/040.txt` — the trade consent string (C5) | edit, **append a row** | `armips/scr_seq/scr_seq_00003_commonscript.s:12` (`// text archive to grab from: 040.txt`); the archive the nurse's messages come from |
| F8 | `hg-engine/bytereplacement` rows | only if a hook site lacks room | `make.py:282-329`; precedent `bytereplacement:14-18,23-24` ("it's not even 0x1C bytes long") |

**Explicitly NOT a C6 change:** any `armips/asm/*.s` addition at `0x02000CD0`. That site is hge's own
boot branch to `load_arm9_expansion` (`armips/asm/syntheticoverlay.s:8-10`) and is SLink's hge
admission anchor (`FEATURE_BAR.md:245`). §3.1 explains why it is also refused as a registration
point.

### 1.2 The deliverable

1. A **new pinned `test.nds`**: `data/gen4_sources.lock.json` → `artifacts.heartgold_hge`, fields
   `sha1` (`:20`), `md5` (`:18`), `sha256` (`:21`), `size_bytes` (`:22`), and `state` stays
   `PINNED` (`:23`).
2. **New fork commit**: `sources.hg_engine_fork.commit` (`:184`), with `tracked_clean: true`
   (`:188`).
3. **New export-file pins**, because the new module changes all three symbol exports:
   `assets.hge_nm_all.sha256` (`:97`), `assets.hge_offsets.sha256` (`:105`),
   `assets.hge_rom_gen_ld.sha256` (`:113`), with their `size_bytes` (`:98,106,114`).
4. The `.cache/gen4/hge/build-<commit12>/manifest.json` written by the build tool
   (`tools/gen4_hge_build.py:122-131`) as the provenance receipt.

### 1.3 Owner-process gate (blocking)

**The fork belongs to the owner. Nothing in C6 happens until the owner approves a SLink branch of
that fork.** `PLAN.md:67` names the prerequisite as "owner's fork access"; `FEATURE_BAR.md:63`
records the same as an owner question ("a SLink branch of it"). Until that approval:

- no branch is created, no commit is made, no file in `hg-engine/` is edited;
- `tools/gen4_hge_build.py:75-76` **refuses to build a dirty tree**, so an uncommitted local edit
  cannot even be tested in place;
- `PLAN.md:102` records the pin as an owner sign-off item ("At C6: the new hge pin").

**Recommendation:** ask for approval of exactly one branch (`slink/gen4-companion`) off
`fc5175764983…`, not for merge rights.

---

## 2. Fork mechanics C6 depends on (read at the pinned commit)

### 2.1 A new overlay is a directory drop, but it needs a `linker.ld` and a number

| Fact | Evidence |
|---|---|
| `src/` subdirectories become overlays, with `individual` and `*.c`/`*.ld` filtered out | `overlays.mk:7`; the mirror filter in `scripts/make.py:53-57` |
| Each overlay gets its own link step with `-T $(C_SUBDIR)/$1/linker.ld` | `overlays.mk:25-26` |
| The overlay's **number comes from the first line of its `linker.ld`**, not from the directory name | `make.py:435-438` |
| Its **load address comes from the first `ORIGIN` line** of the same file | `make.py:441-443` |
| The table entry is written at `newOverlay*0x20` in `base/overarm9.bin`, with `bsssize=0`, `initstart=0`, `initend=0`, `uncompressed=0` | `make.py:450-459` |
| **Therefore `base/overarm9.bin` must already have a free 0x20-byte slot.** `y9Table.seek()` past the end silently writes nothing and the overlay is unreachable. | `make.py:451`; the table is ndspy-extracted from the vanilla ROM at `Makefile:313`, so its length is fixed at build time |
| The top-level `src/*.c` (all non-overlay C) links into `build/linked.o` and becomes **overlay 129**, placed at file offset 0x60 | `Makefile:123`; `make.py:80,84,403-411` |
| ov129's table address is `0x023D8000` (the `+ 0x60` in the linker ORIGIN is **not** parsed into the table) while the code runs at `0x023D8060` | `make.py:415-424` (`[len("0x"):]` on `src/linker.ld:5`) vs `src/linker.ld:5-6` and `make.py:84`. These two agree, because the file offset of the code *is* 0x60 — a `0129` hooks row would compute `offset = runtime − 0x023D8000` and land correctly. **INFERRED** from the two expressions; there are no `0129` rows in `hooks` today to confirm it. |

### 2.2 Row vehicles, and what each costs at the patch site

| Vehicle | File | Row grammar | Bytes written at the site | Evidence |
|---|---|---|---|---|
| jump hook | `hooks` | `<arm9\|overlayNNNN> <symbol> <address> [register]`, default register `255` | 8 B (4 B `ldr/bx` + 4 B literal) for a register hook; the unspecified-register form emits a 0x14 B trampoline + 4 B literal | `make.py:349-353,138-177` |
| register hook | `hooks` | same, 4 fields | as above; `register=0` yields `ldr r0,[pc,#0]; bx r0` | `make.py:151-155` |
| whole-function jump | `hooks`, 3 fields | — | 0x14 B sequence + 4 B literal; the source comment says "requires 0x1C of space" | `make.py:156-176`, comment at `:163` |
| raw bytes | `bytereplacement` | `<arm9\|NNNN> <addr at columns 4..12> <hex bytes>` — **the address is a fixed column slice, not a split**; bytes are written in the order given | exactly what you list | `make.py:299-309`, `ReplaceBytes` `:204-211` |
| pointer repoint | `repoints` | `<arm9\|NNNN> <symbol>[+N] <address of the pointer>` | 4 B, little-endian | `make.py:537-571`, `Repoint` `:196-201`; precedent `repoints:44-46` (`sItemFieldUseFuncs`, `+4`, `+8` — a 3-entry ARM9 table) |
| pointer repoint (+1 slide) | `routinepointers` | `<arm9\|NNNN> <symbol> <address>` | 4 B, pointing at `symbol+1` | `make.py:504-534`, `Repoint(..., 1)` `:533`; precedent `routinepointers:7-8` |

**Correction to `FEATURE_BAR.md:126`** ("on hge it is a `hooks` line" for the START row). A
`StartMenuAction` row's `.func`/`.ident` are **data pointers**, not a call site. A `hooks` row
writes a jump. The correct vehicle is `repoints`, matching `repoints:44-46` exactly. The
inhibit-bit clear at `FieldSystem_GetStartMenuButtonInhibitFlags_Normal` (0x0203BE60,
`FEATURE_BAR.md:125`) *is* a return-value filter and *is* a `hooks` row with register 0 — the
shape of `hooks:39` (`0012 CheckCanTakeItem 02241334 0`) and `hooks:312`
(`arm9 WindowClose 02041190 0`). **One `hooks` row, two `repoints` rows, plus text.**

### 2.3 Ordering inside the build

`make.py:618-624` runs `decompress()`, `writeall()`, `install()`, `hook()`, `repoint()`,
`offset()` in that order. So a `repoints`/`hooks` row referencing a symbol in a **new overlay**
resolves, because `writeall()` has already linked it and `GetSymbols()`
(`make.py:115-135`, `LINKED_SECTIONS` at `:80-82`) sees it. A `hooks` row referencing a symbol in
ov129 also resolves, because `build/linked.o` is `LINKED_SECTIONS[0]`. **INFERRED** from the call
order; not exercised.

---

## 3. Per-feature fork change

### 3.1 C2 — the service SysTask registration

**Decision: a `hooks` row at a vanilla ARM9 site, NOT a `hooks` row at `0x02000CD0`, and NOT a
`load_arm9_expansion` body edit.** Two reasons, both load-bearing:

1. `0x02000CD0` is hge's own `bl load_arm9_expansion` from `Main` (`armips/asm/syntheticoverlay.s:8-10`),
   and it is SLink's hge-discriminating admission anchor (`FEATURE_BAR.md:245`:
   `hge_differs`, `profile.json:65`). Hooking there would collide with admission. The ruling is
   explicit: *"The companion's hge registration must NOT hook this site; use a `hooks` row or ride
   `load_arm9_expansion`."*
2. Riding `load_arm9_expansion` means editing fork-owned assembly in
   `armips/asm/syntheticoverlay.s:17-28` — a second, more invasive SLink-owned edit surface than
   the table rows, and it couples the service to overlay 129's no-init load path
   (`syntheticoverlay.s:21-23`, `HandleLoadOverlay(129, 2)`). **`hooks` is the cheaper vehicle.**

| Fact | Evidence |
|---|---|
| hge hooks **none** of `NitroMain`, `SysTaskQueue_RunTasks`, `Task_RunScripts` or the VBlank callbacks | `FEATURE_BAR.md:214` |
| hge ships no `main.c`, `system.c` or `sys_task.c`, so there is no source to call from | `FEATURE_BAR.md:215`; confirmed — `grep SysTask hg-engine/src` finds only `src/battle/battle_input.c:272,345` |
| `gSystem` and `gSystem.mainTaskQueue` are declared in the fork | `include/system.h:16,48` |
| The SysTask API is callable from fork C — the fork already does it with a raw address | `src/battle/battle_input.c:345` (`CreateSysTask((SysTaskFunc)0x022684ED, …)`), `:272` (`DestroySysTask`) |
| The service must re-register every boot; the main queue does not survive a soft reset | `FEATURE_BAR.md:208` |

**Shape.** `SysTask_CreateOnMainQueue` is a static-ARM9 function and already `.public` in the
overlay symbol includes (`C2_BEACON_SPEC.md:178-181`), so it needs no new plumbing — but the fork's
headers do not declare it (`grep SysTask hg-engine/include` finds only `SysTaskQueue *
mainTaskQueue`), so `src/slink/slink.c` declares the prototype itself. **INFERRED**: the symbol
resolves through `offsets.ini` / `nm_all.txt` exactly as the raw-address cast at
`battle_input.c:345` implies it does.

**Row budget.** One `hooks` row, 8 bytes, at a site with a `ldr rN` of slack. **Which site is
OPEN** — hge has no `NitroMain` source, so the candidate is whatever vanilla ARM9 function runs
once per outer loop and is hookable with 8 bytes of room. `hooks` already claims many of those.
**This is the one C6 item that must be measured, not assumed** (§5.1).

### 3.2 C2 — the beacon / ITCM mailbox writer

No fork *plumbing*: the mailbox is the 4 KiB span `0x01FFEC00..0x01FFFC00`
(`C2_BEACON_SPEC.md:60-66`), inside the ITCM arena tail, and the ROM reaches it as a plain address
constant from `src/slink/*.c`. The title-private 0xE00..0xE40 window
(absolute `0x01FFFA00..0x01FFFA40`, `C2_BEACON_SPEC.md:6-12`) is likewise a constant.

**The C6-specific constraint is that ITCM survives a soft reset**
(`FEATURE_BAR.md:255`), so the private cookie must be re-derived every boot
(`C2_BEACON_SPEC.md:3-5`: boot generation = session epoch; `gSystem.frameCounter` is **forbidden**
as the clock — `src/main.c:124` zeroes it every loop; use `gSystem.vblankCounter`).

**GATE, carried from C2 and re-run at C6:** no hge ROM ships before the C1 live canary accepts the
span on hge (`C2_BEACON_SPEC.md:70-82`). A re-pin invalidates every build-bound receipt
(`PLAN.md:84`).

### 3.3 C3 — sound

**C3's decision block wins:** no SE handle is reservable; the handle is resolved at runtime and
polled with `NNS_SndPlayerReadDriverTrackInfo` (`C3_SOUND_SPEC.md:3`). The C3 service runs on the
**C2 SysTask** — there is no second service and no extra hook (`C3_SOUND_SPEC.md:89-90`, `:97-99`).
So C3 costs **zero new rows**; it is C source in `src/slink/`.

| Fact | Evidence |
|---|---|
| hge hooks only `GF_Snd_LoadSeq` and `GF_Snd_LoadSeqEx` — it does **not** replace the sound module | `hooks:290-291`; `FEATURE_BAR.md:182-185` |
| hge declares the same `SND_WORK` with the `unk_BEB78` handle array, and its `src/sound.c` uses it | `include/sound.h:46-50` (`/* 0xBEB78 */ void *unk_BEB78[SND_HANDLE_MAX];`), `SND_HANDLE_MAX 9` at `include/sound.h:8` |
| The SE id table is value-identical across 1373 shared ids, so the vanilla poll plan stands | `FEATURE_BAR.md:185` |
| `PlaySE` is never called from IRQ context | `FEATURE_BAR.md:212`; C3 falsifier F3 (`C3_SOUND_SPEC.md:78`) |

**Owner deferral honoured verbatim:** code 2 FAILURE stays **unwired** and is *refused* with reason
32, not guessed (`C3_SOUND_SPEC.md:57,67-71`, `:12`).

### 3.4 C4 — the START row, the label, and the inhibit bit

**C4's decision block wins:** row = `START_MENU_ACTION_7`; the **label goes in msg bank 196 row 7 on
every build**; the hge route is a `data/text/196.txt` drop (`C4_PANEL_SPEC.md:3,12-18`).

| Step | Fork change | Evidence |
|---|---|---|
| Row `.func` | `repoints` row: `arm9 <slink row array>+0 020FA0F4` | `sStartMenuActions` @0x020FA0F4 (104 B), `FEATURE_BAR.md:124`; vehicle `repoints:44-46` |
| Row `.ident` | `repoints` row at the row's `.ident` field | `FEATURE_BAR.md:126`; `src/start_menu.c:175-184` (pret, quoted in `C4_PANEL_SPEC.md:13`) |
| Inhibit bit | **one** `hooks` row with register `0` at `0203BE60` | `FieldSystem_GetStartMenuButtonInhibitFlags_Normal` @0x0203BE60 (`FEATURE_BAR.md:125`); `Hook` register-0 encoding `make.py:151-155`; precedent `hooks:39,312` |
| Label text | new `data/text/196.txt`, **CRLF**, member 196 unchanged in every other row | `C4_PANEL_SPEC.md:16-18`; `data/text/.gitattributes:1-2`; `narcs.mk:21` |
| Never move | `ACTION_9`/`_10` stay at display slots 7/8 | `C4_PANEL_SPEC.md:9-10` (`start_menu.c:518-519`) |

**Two C6-specific facts about the text route, both verified here:**

1. `MSGDATA_DEPENDENCIES := $(wildcard data/text/*)` (`narcs.mk:21`), so dropping `196.txt` in is
   enough to join the msgdata rule — no Makefile edit.
2. The rule **re-extracts every member from the base ROM** and then re-encodes only the members with
   a `data/text` file: `$(NARCHIVE) extract $(MSGDATA_TARGET) -o $(MSGDATA_DIR) -nf`, then
   `$(MSGENC) -e -c $(CHARMAP) $$file $(MSGDATA_DIR)/7_$$(basename $$file .txt)`
   (`narcs.mk:776-780`). The output file is therefore named **`7_196`** — the `7_` prefix is
   literal in the recipe, which is what C4's round-trip gate depends on
   (`C4_PANEL_SPEC.md:18`). `MSGDATA_TARGET := $(FILESYS)/a/0/2/7` (`narcs.mk:19`).
3. **196 has no existing `data/text` file** — the directory holds 52 files (852, 853, 850, …, 040)
   and 196 is not among them. So this is the first time hge rebuilds member 196, and the
   round-trip `cmp` gate must run **before** the edit (`C4_PANEL_SPEC.md:18`).

**Risk to record:** member 196 is byte-identical HG vs hge today (sha256 `d83267735d99b262`;
`C4_PANEL_SPEC.md:14`). Re-encoding a member for the first time may not round-trip byte-identically
even with an unchanged row. If it does not, the C6 diff to `test.nds` includes member-196 churn
beyond row 7. **Gate:** decode the hge member, re-encode with **no** edit, `cmp`; a difference is a
finding, not something to absorb.

### 3.5 C4 — the panel overlay

**C4's decision wins:** the hge panel overlay takes the **vanilla-style slot `0x021E5900`** — an app
slot exclusive with `field`, as hge's own ov142/ov147 do — and **not** the unproven top window
(`FEATURE_BAR.md:244`).

| Fact | Evidence |
|---|---|
| A new overlay is a directory drop with its own `linker.ld` | §2.1 |
| Its `linker.ld` must set `rom : ORIGIN = 0x021E5900, LENGTH = …` and a free table id | `make.py:435-443,450-459` |
| hge's ov129/ov130/ov131 sit at `0x023D8000` / `0x023C4000` / `0x023C8000`, **adjacent** | `src/linker.ld:5-6` (129, len 0x8000−0x60), `src/battle/linker.ld:5-6` (130, 0x023C4000 len 0x14000 → ends exactly at ov129's base), `src/field/linker.ld:5-6` (131) |
| ov131's origin file was not found by the earlier pass | `FEATURE_BAR.md:242` — **resolved here**: it is `src/field/linker.ld:5` |
| hge has **no ArenaHi lowering**; its only `OS_SetArenaHi` restores the initial value, so nothing proven keeps the main arena out of `0x023C0000..0x023E0000` | `FEATURE_BAR.md:243` |

**Choosing the overlay id is an OPEN item** (§6 Q1). `0x021E5900` is also the shared
`SDK_STATIC_BSS_END` on HG/SS (`FEATURE_BAR.md:143`), i.e. the vanilla app-overlay base — which is
exactly why it is mutually exclusive with `field` and `trainer_card` there
(`FEATURE_BAR.md:223-226`) and why hge's own ov142/147 use it.

### 3.6 C5 — the trade

**C5's decisions win:** party-only slot overwrite; no box arm; opcode **1**, never 486; the hge
route is a **source edit** to the common script (`C5_TRADE_SPEC.md:3-6,13-15,25-27`).

| Step | Fork change | Evidence (all re-read here at the pinned commit) |
|---|---|---|
| Nurse entry | `scr_seq_0003_002` at `armips/scr_seq/scr_seq_00003_commonscript.s:93` | the file declares `scrdef scr_seq_0003_002` at `:19`; `scrdef` is an **offset table** emitted inline (`.word offset - . - 4`, `armips/include/scriptmacros.s:3-5`), so index 2 is the third entry — 2002 resolves here exactly as `sScriptBankMapping` does on pret (`FEATURE_BAR.md:94`) |
| Insertion point | immediately before `end` at `:118`, after the `getmenuchoice` dispatch `:113-117` | `:111` `non_npc_msg_var`, `:112` `touchscreen_menu_hide`, `:113` `getmenuchoice`, `:114-115` / `:116-117` the two `goto_if_eq`, `:118` `end` |
| Safe point | `lockall` `:95` and `faceplayer` `:96` already hold | the visit-gate shape (`C5_TRADE_SPEC.md:110-121`) |
| Return path | decline epilogue `:120-127` (`releaseall` `:125`, `endstd` `:126`); heal epilogue `_02B2` at `:200-209` (`releaseall` `:207`, `endstd` `:208`) | **citation drift:** `C5_TRADE_SPEC.md:164` says "the epilogue is `:152-…`"; at the pinned commit the heal-path tail is `:200-209` and `:152` is inside `_020C` (the "no heal" message). The `:125` releaseall it also cites is correct. |
| Opcode slot | `repoints` row: `arm9 <slink cmd table>+4 020FAD08` | `gScriptCmdTable` @0x020FAD00, entry #1 is `ScrCmd_Dummy` in **both** HG and hge (`FEATURE_BAR.md:127-129,158-161`); vehicle precedent `repoints:44-46` |
| Opcode-1 gate | **independently re-confirmed:** the `dummy` macro is `armips/include/scriptmacros.s:17-19` (`.halfword 1`) and **has zero invocations** anywhere in `armips/` | grep over `hg-engine/armips` returns only the macro definition; matches `FEATURE_BAR.md:160` |
| Consent string | append a row to `data/text/040.txt` (121 rows today, last `:121`) | the nurse's messages come from 040 (`armips/scr_seq/scr_seq_00003_commonscript.s:12`), whose existing prompts already use `{YESNO 0}` (`data/text/040.txt:1,6,7,14`) |

**Append-only.** Adding row 122 to member 040 keeps every existing index stable, which the 25
Pokémon Centers all depend on. **INFERRED** that msgenc appends in file order — it does, but the
row count of the re-encoded member must be asserted (122) in the C6 build check.

---

## 4. Build + reproducibility

### 4.1 The command

```
python tools/gen4_hge_build.py --build
```

- Default is `--plan`, which touches nothing (`tools/gen4_hge_build.py:6`); `--build` runs for real.
- Key-based SSH only (`BatchMode=yes`, `:30-31`); there is no credential file and none is needed.
  **No password is used, stored, or recorded anywhere in this procedure.**
- Sync is `tar` over `ssh` into `~/git/hg-engine` with the excludes
  `--exclude-vcs --exclude=*.nds --exclude=.venv --exclude=./build_output --exclude=./docs`
  (`:33-34`), then `make -j8` (`:29,96`), then `scp` pulls `test.nds`, `offsets.ini`,
  `rom_gen.ld` (`:37-38,104-107`), then `arm-none-eabi-nm` over every `*_linked.o` into
  `nm_all.txt` (`:35-36,108-111`).
- Outputs go only to `.cache/gen4/hge/build-<commit12>/` and the tool refuses an output path outside
  that cache or inside the fork (`:78-81`). **It never writes inside the fork.**

### 4.2 The two gates the tool itself enforces

| Gate | Where | Meaning for C6 |
|---|---|---|
| tracked tree must be clean | `:75-76` | the SLink branch must be committed before any build. There is no "build my dirty edit" path. |
| `test.nds` sha1 vs the pin | `:82,114,127-128,133-136` | **the tool never repins.** A mismatch is `FAIL` + exit 1, and is explicitly "a finding for the owner: reproducibility is unproven (unpinned devkitARM/armips)" (`:10-11,134`) |

**So the C6 sequence is two builds, not one.** Build 1 is expected to `FAIL` (the ROM changed by
design). That FAIL is the *reproducibility receipt*: it proves the tool is comparing, not rubber-
stamping. Then the pin is re-pinned, and build 2 at the **same commit** must `PASS`. If build 2 also
fails, reproducibility is unproven and the owner decides — that is exactly the card's falsifier
(`PLAN.md:67`: "A fresh build whose `test.nds` sha1 is not reproducible (the tool's own finding)").

### 4.3 The expected sha1 change

**The sha1 changes; no number can be predicted.** It is `sha1(test.nds)` of a build that now contains
a new overlay, a changed common-script member, two re-encoded msgdata members, and new bytes in
ARM9. Record it; do not assert a value.

### 4.4 Re-pin procedure

1. Run the build; read `.cache/gen4/hge/build-<commit>/manifest.json` (`:122-131`).
2. **Before** re-pinning, check `exports_vs_cache` (`:115-121`): `offsets.ini`, `rom_gen.ld` and
   `nm_all.txt` should all read `different`. `offsets.ini` and `nm_all.txt` **must** now contain
   `Slink_*` symbols (`make.py:491-501` writes every symbol; `make.py:119-120` strips absolute
   `a`/`A` symbols from the cached comparison). If `offsets.ini` is `equal`, **the new module did
   not link** — stop.
3. Update `data/gen4_sources.lock.json`: `artifacts.heartgold_hge.{sha1,md5,sha256,size_bytes}`
   (`:18-22`) and `assets.hge_{nm_all,offsets,rom_gen_ld}.{sha256,size_bytes}` (`:93-115`).
4. Do **not** silently change `sources.hg_engine_fork.commit` (`:184`) — that is the branch's base
   plus the SLink commits, and it must be re-recorded at the exact commit that was built.
5. Re-run the build at the same commit. It must now exit 0 (`PASS`, `:136`).
6. Re-run the **C1 and C2-C5 receipts** on the new ROM (`PLAN.md:67` exit evidence: "C1-C5 receipts
   on the new hge"). A rebuild invalidates build-bound receipts (`PLAN.md:84`; G1 text).
7. Re-run the opcode-1 gate on the new pin — "Re-run this check (C0 sha1 + NARC member diff) on any
   new hge or pret pin" (`FEATURE_BAR.md:165`; `C5_TRADE_SPEC.md:189`). The re-pin **rebuilds
   member 3 of `a/0/1/2`**, so the "hge's `a/0/1/2` is member-for-member identical to HG except
   member 3" premise must be re-established by diff, not assumed.

### 4.5 Falsifier

`PLAN.md:67`: **a fresh build whose `test.nds` sha1 is not reproducible (the tool's own finding).**
Concretely: after the re-pin, build again at the same commit; if the sha1 differs from the re-pinned
value, the devkitARM/armips toolchain is not pinned and C6 cannot produce a distributable hge
artifact. That is an owner escalation, not a C6 workaround.

---

## 5. Risks

### 5.1 Hooks budget and ARM9 expansion space — **high**

- **The ARM9 expansion stub is 36 bytes.** `.org 0x02110334` … `.area 0x02110358-.` is exactly
  `0x24` = 36 B (`armips/asm/syntheticoverlay.s:13-15`, closed at `:42`). It already holds
  `load_arm9_expansion` (`:17-28`) and `HandleLoadOverlay129` (`:32-38`). **There is essentially no
  room for a service call there**, which is why real code goes in overlay 129
  (`FEATURE_BAR.md:59`) — i.e. in `src/*.c`, i.e. `src/slink/`. Confirms the F1 shape.
- **A register hook costs 8 bytes at the site** (`make.py:151-155`), a whole-function jump 0x14+4
  (`make.py:165-176`). The 36 B stub cannot absorb even one. If §3.1's candidate site has less
  than 8 bytes of slack, the escape hatch is a hand-written `bytereplacement` row, exactly as
  `bytereplacement:14-18,23-24` does for `Bag_HasSpaceForItem` and `CanUseItemOnMonInParty`.
- **Mitigation:** measure the chosen site against `offsets.ini` before writing the row, and record
  the byte count in the C6 receipt.

### 5.2 ov129 / ov130 adjacency — **medium**

- ov129 `0x023D8000 + 0x60`, length `0x8000 − 0x60` → ends at `0x023E0000`
  (`src/linker.ld:5-6`).
- ov130 `0x023C4000`, length `0x14000` → ends at **exactly** `0x023D8000`, ov129's base
  (`src/battle/linker.ld:5-6`). Zero gap.
- ov131 `0x023C8000`, length `0x18000` → `0x023E0000`, **overlapping ov129 entirely**
  (`src/field/linker.ld:5-6`).
- **hge has no ArenaHi lowering**; its only `OS_SetArenaHi` restores the initial value, so nothing
  proven keeps the main arena out of `0x023C0000..0x023E0000` (`FEATURE_BAR.md:243`).

**Consequence for C6:** `src/slink/*.c` goes into ov129, which is already overlapped by ov131 and
abutted by ov130. A **large** `src/slink` can grow ov129's file size past `0x8000 − 0x60` and change
every address above it. **Gate:** after the first C6 link, compare ov129's `memSize` in
`base/overarm9.bin` against `0x7FA0` and re-read `offsets.ini`. A silent overflow here would move
the whole top of RAM and invalidate the hge memory profile. **This is the risk most likely to be
missed**, because nothing in the fork errors on it.

### 5.3 The ArenaHi question — **open, unresolved by design**

`FEATURE_BAR.md:243` records it: nothing proven keeps the main arena out of
`0x023C0000..0x023E0000`, and **there is no lowering in the fork**. The panel overlay was moved
*off* the unproven top window onto `0x021E5900` for exactly this reason
(`FEATURE_BAR.md:244`), which is the right call and is C4's decision. **The residual question is
unrelated to the panel:** does hge's main arena, in practice, reach `0x023C0000`? If it does, ov129
/ov130/ov131 are already living on top of the heap and any growth is fatal. **Measure it at C6
PHYSICAL** — not statically.

### 5.4 The msgdata re-encode — **medium** (§3.4)

Member 196 has never been rebuilt by hge. The first re-encode of any member is the first time the
round-trip is exercised on a member other than the 52 that already work. Gate: no-edit round-trip
`cmp` on `7_196` before the row-7 edit.

### 5.5 The `base/overarm9.bin` slot — **medium** (§2.1)

`make.py:451` seeks `newOverlay*0x20` with no bounds check. A too-large id writes past EOF silently
and the overlay never loads. **Gate:** assert `os.path.getsize(base/overarm9.bin) > id*0x20` and
assert the written entry's `memaddress` equals the linker ORIGIN (§6 Q2).

---

## 6. Open questions

1. **Which overlay id?** `base/overarm9.bin` comes from the vanilla ROM (`Makefile:313`), so it has a
   fixed length; hge already claims 129–132 plus `individual/*` ids. `FEATURE_BAR.md:229` measured
   133–149 in the ROM table. **The highest free slot must be read out of `base/overarm9.bin`, not
   guessed.** Settled by: `python -c` over the extracted table, or one `nm`/table read.
2. **The generic overlay `ORIGIN` parser.** `make.py:442` and `:471` parse
   `int(line.split()[4][len("0x"):-1], 0x10)` while the ov129 path at `:418` uses
   `[len("0x"):]` (no `-1`). For every existing `linker.ld` the token is `'0x023C8000,'`, so `[-1]`
   drops the last hex digit and the generic parse yields `0x0023C800` — 256× too small. That
   cannot be what produced the measured table (`FEATURE_BAR.md:229` reads ov130 = `0x023C4000`,
   ov131 = `0x023C8000`), so **either the file differs from the pinned commit, or the earlier
   measurement is stale.** **UNVERIFIED.** Settled by one build: read the new overlay's
   `memaddress` back out of `base/overarm9.bin` and compare it with the linker ORIGIN. Until then,
   treat "my new overlay loads at the right address" as an assertion to *check*, not a fact.
3. **The §3.1 registration site.** Which vanilla ARM9 function gives an 8-byte hook on a
   once-per-loop path, and is it already claimed by an existing `hooks` row? **UNVERIFIED** — needs
   an `offsets.ini` read plus a collision check against all 636 lines of `hooks`.
4. **Does the trade consent prompt need a new row at all?** C5 prefers the visit-gate shape, which
   still needs *some* string for the Yes/No box (`data/text/040.txt`). If the owner would rather
   the gate be silent, F7 drops out and the trade becomes a one-press action. Owner call.
5. **The panel's `ramSize`** (`C4_PANEL_SPEC.md:618`, Q4) — one number out of the first C6 link.
   Because the panel takes `0x021E5900`, the C6 build answers this directly; the HG/SS build
   answers it for ov1.
6. **`ramSize` vs `fileSize` on hge.** `make.py:454` writes `memsize = file size` and `bsssize = 0`
   for every generic overlay. A `src/slink` with static `.bss` (the C2 cookie lives in a heap
   block, not `.bss` — `C2_BEACON_SPEC.md:5` — but the sound code table and the repoint arrays may
   not be) would get a `bsssize` of 0 and uninitialised `.bss`. **UNVERIFIED;** the same convention
   applies to all existing hge overlays, so it is a fork-wide property, not a C6 regression.

---

## 7. C6 falsifier set

| # | Falsifier | Class | Settled by |
|---|---|---|---|
| F1 | A fresh build's `test.nds` sha1 is not reproducible at a fixed commit | S | `PLAN.md:67`; `gen4_hge_build.py:133-136`, two builds at one commit |
| F2 | `offsets.ini` does not gain the `Slink_*` symbols | S | `make.py:491-501`; `gen4_hge_build.py:115-121` `exports_vs_cache` |
| F3 | The new overlay's registered `memaddress` ≠ its linker `ORIGIN` | S | §6 Q2 |
| F4 | ov129 `memSize` > `0x7FA0` | S | §5.2 |
| F5 | `7_196` does not round-trip with **no** edit | S | §5.4 |
| F6 | After the row-7 edit, any member other than 196, or any row of 196 other than 7, changed | S | NARC member diff |
| F7 | Member 040's row count ≠ 122 after the trade string is appended | S | §3.6 |
| F8 | Opcode 1 now has an emitter in the rebuilt `a/0/1/2` member 3 | S | `FEATURE_BAR.md:165` re-run gate; grep for `dummy` in `armips/scr_seq` |
| F9 | A start menu in a save with no panel capability shows no SLINK row | P | `C4_PANEL_SPEC.md` capability gate |
| F10 | A trade on hge-hge leaves the party byte-identical on refusal | P | `PLAN.md:66` |

---

## 8. What was NOT done

- Nothing was built, committed, branched or re-pinned. `hg-engine/` was **read only**.
- No password, key or credential appears in this document or is required by §4.1.
- The fork's `main` commit (`fc5175764983…`) matches `data/gen4_sources.lock.json:184`, so no
  divergence is claimed; the ROM pin (`:20`) and the fork commit are simply different facts.