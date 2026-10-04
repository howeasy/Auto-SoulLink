> **Status: DRAFT** (OMP cx-ac8472b6, 2026-10-02). The coordinator's review decisions are below; where they conflict with the draft, the decisions WIN.
>
> - **hge work is PATCH ONLY (owner 2026-10-04):** prepare outside the fork, no fork commit before an approved branch; see `docs/gen4/reviews/DECISIONS_2026-10-04_companion_and_g3a.md`.
> - **Row = `START_MENU_ACTION_7` ACCEPTED** (verified: `msg_0196_00007` is an empty "garbage" row and `_00008` is the live RETIRE, `files/msgdata/msg/msg_0196.gmm:31-39`; the inhibit is at `src/start_menu.c:303`; fixed slots 7/8 at `:518-519`).
> - **`SEQ_SE_GS_GEARCANCEL` = 2368 VERIFIED** (`pret/pokeheartgold@ad7a3afa`, `include/constants/sndseq.h:1366`). Re-read 2026-10-04; §3.4 agrees. C4 policy/facts are delivered on `claude/gen4-companion-policy@d68e8137`; `panel.c` game binding is still absent.
> - **Rows are 16 UTF-16 units incl. the 0xFFFF terminator**: the host truncates to 15 (`panel_producer.h:3-5`). Accepted.
> - **The ROM owns no page cursor**; the host re-posts pages (Gen 3/Gen 2 precedent). Accepted.
> - **Q1 RULED by the ABI owner (Gen 5, 2026-10-02): option (a).**
>   - The native side writes `0x7F` whenever the panel closes for ANY reason, including A on the last page (the Gen 2 no-wrap UX). `0` only when A advances to a further page.
>   - Hosts: a 0 on page == pages-1 is treated as close (never wrap on NDS); any non-zero result is done.
>   - Reason: the Gen 3 host wraps on 0 (`lua/gen3/native.lua:1148-1157`), so 0x7F is the backward-compatible close.
>   - The abi.h comment edit is queued with the SLINK_TITLE follow-up; cite this ruling until then.
> - **Q2 DECIDED: the label goes in msg bank 196 row 7 on every build** (OMP cx-6749bc7b + coordinator checks).
>   - Why not a runtime string: the START menu draws every row label from bank 196 via `sStartMenuActions[].ident` (`src/start_menu.c:175-184`; ACTION_7 = `msg_0196_00007`), so a runtime string would need a hook in the start-menu draw (vanilla ARM9 on hge). The OMP's runtime-buffer option is rejected for the ROW; the panel app's own body text stays host-supplied.
>   - Member 196 is byte-identical HG vs hge (sha256 d83267735d99b262; HG 829 members, hge 854). hge re-wraps the base msg NARC and re-encodes only members with a `data/text/<id>.txt` (`hg-engine/narcs.mk:776-780`, `Makefile:459-460`); 196 has none.
>   - **pret (HG/SS):** edit `files/msgdata/msg/msg_0196.gmm` row 7 changing BOTH the attribute (`garbage` -> `used`, :32) and the English text (:33). With `garbage` kept, msgenc encodes the blanked Japanese node instead (`tools/msgenc/Gmm.cpp:92-97`, verified): a silent blank label.
>   - **hge (C6):** add `data/text/196.txt` = the decoded member with row 7 filled.
>     - It MUST be CRLF (LF collapses the member to one row; `data/text/.gitattributes`).
>     - Gate: decode -> re-encode round-trip `cmp` on an output file named exactly `7_196` (the key derives from the filename) BEFORE the edit, then confirm the only changed member is 196 and the only changed row is 7.
>
> **Status: DRAFT** (OMP cx-ac8472b6, 2026-10-02). Peer spec draft for coordinator review and
> owner sign-off. Nothing here is built. Every fact carries a `file:line`. Anything I could not
> read is marked **UNVERIFIED**; anything I reasoned to but did not read is marked **INFERRED**.
>
> - Reads from the coordinator decision block of `docs/gen4/companion/C2_BEACON_SPEC.md:1-14`.
> - `FEATURE_BAR.md:218-231` (C4 panel placement) and `FEATURE_BAR.md:233-245` (C4/C6 follow-up)
>   WIN where this draft differs. The trainer card is a **LIFECYCLE template only**; its UI and
>   exit are asm (`FEATURE_BAR.md:235-238`).
> - Citation drift against `FEATURE_BAR.md` is listed in §9. Every drift is *my* reading of the
>   pinned pret tree at `ad7a3afa`; the FB lines were off by 1-3 lines, not in substance.

# Gen 4 companion C4: the START-menu SLINK row and the natively drawn info panel (SPEC draft, 2026-10-02)

**Card:** C4 (`docs/gen4/companion/PLAN.md:65`), bar item 3
(`docs/gen4/companion/FEATURE_BAR.md:13`), placement direction
`FEATURE_BAR.md:218-231`.

**Card inputs and outputs (`PLAN.md:65`):** exclusive files
`patch/src/nds/gen4/panel.c`, `panel.h`, `panel_policy.h` and the title-owned START
integration. `dispatch.c:41-43` names panel.c; the old start_menu_hook/panel_overlay
names are superseded, and shared ABI layout stays with its owner. Exit evidence S/M/P: `sStartMenuActions` bytes and the cleared
inhibit bit; payload round trip; a screenshot of the panel on both screens plus the menu closing
without a leak, on HG, SS and hge. Shared? **No.**

---

## 1. Scope

**One new row in the START menu that opens a read-only info panel whose pages of text come from
the host. B exits.**

IN:

| # | What | Owner |
|---|---|---|
| 1 | Repoint one inhibited `StartMenuAction` row and clear exactly one inhibit bit | ROM |
| 2 | A new single-overlay app (lifecycle cloned from the trainer card, UI written in C) | ROM |
| 3 | Row render from a host-staged `SlinkInfoV2` snapshot | ROM |
| 4 | `SLINK_CAP_INFO_PANEL` in the advertised capability set | ROM |
| 5 | Host staging of `SlinkInfoV2` (epoch, request, rows, page, pages, enable) | host |
| 6 | The `drawn_seq` / `closed_seq` handshake | shared `panel_producer.h`, used unmodified |

OUT:

| Excluded | Card / ruling | Why |
|---|---|---|
| Any menu/message box pop-up | owner deferral (`PLAN.md:25`) | no native message boxes this release |
| Peer ghost, phone-call names | `FEATURE_BAR.md:18,20` | HGSS has no special-call surface; the panel is the substitute |
| A trade UI | C5 (`PLAN.md:66`) | C5 *consumes* this panel for its UX; C4 does not build a trade screen |
| A boot-time capability probe for the host | C2 (`C2_BEACON_SPEC.md:30-32`) | the span and the header land at C2; C4 only adds the cap bit and the payload |
| Any new mailbox opcode, field, offset or struct | C2 D-C2-1 / ABI owner (`C2_BEACON_SPEC.md:6-12`) | the shared ABI is used **unmodified** (`C2_BEACON_SPEC.md:47-49`) |

**Capability gating is the whole of rule 1.** No `SLINK_CAP_INFO_PANEL`, no row: the inhibit bit
is a **build-time** constant decision, and the row's `.func` and the panel overlay only exist in a
build that advertises the cap. The host never gets to invent the row — that is the Gen 1/2 rule
stated from the other side in `lua/gb_panel.lua:104-106` (*"a build may ship one feature without
the other"*) and applied at the host end in `lua/gen3/native.lua:1163`.

---

## 2. The menu row

### 2.1 Which row: **`START_MENU_ACTION_7`**, not `RETIRE`

`FEATURE_BAR.md:79` offers both. `START_MENU_ACTION_7` is strictly better, on four counts, all
read at the pinned pret `ad7a3afa`:

1. **Its label message is a garbage row.** `files/msgdata/msg/msg_0196.gmm:31-35`:

   ```
   <row id="msg_0196_00007" index="7">
       <attribute name="window_context_name">garbage</attribute>
       <language name="English"></language>
       <language name="日本語">XXXX</language>
   </row>
   ```

   English is the **empty string**. `msg_0196_00008` (`RETIRE`) is a live row
   (`msg_0196.gmm:36-39`, `window_context_name="used"`, English `RETIRE`). Writing `SLINK` into
   `msg_0196_00007` fills a slot the game already reserves for garbage; overwriting
   `msg_0196_00008` would destroy the RETIRE string for a row that stays inhibited anyway.

2. **Its inhibit bit is set in strictly more contexts.** `START_MENU_ACTION_DISABLE_7` is
   asserted in six: `start_menu.c:303` (Normal), `:308` (Safari), `:312` (Bug Contest), `:316`
   (Pal Park), `:320` (Battle Tower Multi-Partner-Select) and `:328` (`sub_0203BEE8`).
   `START_MENU_ACTION_DISABLE_RETIRE` in three: `:303`, `:320`, `:328`. Repointing `ACTION_7` means
   the SLINK row is suppressed in every special field context where the panel's
   fade → app → field-reload chain is least likely to be safe; repointing `RETIRE` would expose it
   in Safari Zone, the Bug Contest and Pal Park.

3. **It needs no new insert point.** `StartMenuButton_Insert` (`start_menu.c:472-479`) puts a row
   at `position = *pLength` when passed `-1u`. `RETIRE` is inserted first (`start_menu.c:484-486`)
   → display position 0; `ACTION_7` second (`:487-489`) → display position 1. Both are existing
   call sites: no table growth, no shift.

4. **No icon work either way, but `ACTION_7` proves it.** `sActionToIconIndex[7] = 100`
   (`start_menu.c:159-172`), and `FieldSystem_ShouldDrawStartMenuIcon` returns `TRUE` from its
   `default:` arm (`:551-552`). `FieldSystem_StartMenuActionIsAvailable` (`:529-531`) therefore
   always admits the row. Icon index 100 is the game's "no icon" value, so the row renders as a
   label-only entry.

### 2.2 The exact table edit

One element of `sStartMenuActions` (`start_menu.c:174-188`) changes:

```c
[START_MENU_ACTION_7] = { .ident = msg_0196_00007, .func = Task_StartMenu_HandleSelection_SlinkPanel },
```

was

```c
[START_MENU_ACTION_7] = { .ident = msg_0196_00007, .func = Task_StartMenu_HandleSelection_RemovedEasyChatThing },
```

(`start_menu.c:182`). `.ident` is **not** changed — it stays `msg_0196_00007`; only the message
*content* changes (§2.4). No other array in the file is touched: `sActionToIconIndex`
(`:159-172`), `StartMenu_BuildActionLists` (`:481-521`) and the dispatch at `:596-600` (A) /
`:637-641` (touch) are all reused as they are.

### 2.3 The inhibit bit: clear exactly one

`start_menu.c:303`:

```c
ret |= (1 << START_MENU_ACTION_DISABLE_7) | (1 << START_MENU_ACTION_DISABLE_RETIRE);
```

becomes

```c
ret |= (1 << START_MENU_ACTION_DISABLE_RETIRE);
#if defined(SLINK_COMPANION_INFO_PANEL)
    /* SLINK_CAP_INFO_PANEL: the row is live in the ordinary overworld. The
       capability bit itself is published in the C2 service tick. */
#else
    ret |= (1 << START_MENU_ACTION_DISABLE_7);
#endif
```

The six other contexts (`:308`, `:312`, `:316`, `:320`, `:328`) are **left alone**. That is
deliberate: clearing `DISABLE_7` there would put the panel row in Safari Zone, the Bug Contest and
Pal Park, and §4's return path (`FieldSystem_LoadFieldOverlay`) is only proven for the plain field.

The `#if` guard is what makes falsifier 1 (§6) structural: a build without C4 compiles the
original expression and the byte at `sStartMenuActions` is unchanged.

### 2.4 The label message

`files/msgdata/msg/msg_0196.gmm:33` — the English `<language>` element of `msg_0196_00007`, empty,
becomes `SLINK`.

Two consequences worth stating:

- This is a **message-bank edit**, which `FEATURE_BAR.md:96` already prices in for the trade
  ("A named third option would mean a message-bank edit"). It is cheaper there because that edit
  needs a *live* row; here the row is `garbage`.
- The compiled msgdata NARC changes, so the HG/SS UPS carries it and the C0 byte-identical
  baseline is invalidated by construction. Re-run the C0 provenance comparison as a **delta**
  (expected non-empty, confined to the msgdata NARC + `start_menu.o`), not as a byte-identity check.
  **UNVERIFIED**: which ROM path carries `msg_0196` — the build's `filesystem.mk` would answer it.

Label text `SLINK` matches the existing Gen 2 relabel (`patch/gen2/src/panel_start.asm:9-14`,
`SlinkMenuString`), so the two GBA companions read the same. **Content choice** — the owner may
prefer something else; the length must fit the START-menu label column.

### 2.5 The never-move rule for slots 7 and 8

`start_menu.c:518-519`:

```c
StartMenuButton_Insert(insertionOrderDest, displayOrderDest, &numIcons, START_MENU_ACTION_9, 7);
StartMenuButton_Insert(insertionOrderDest, displayOrderDest, &numIcons, START_MENU_ACTION_10, 8);
```

These two rows are written at **explicit display positions 7 and 8**, unconditionally, after every
conditional insert. Two invariants follow and both must be checked by falsifier 2:

- **I1.** No companion edit may pass an explicit `position` to `StartMenuButton_Insert`, and no
  companion edit may insert a row *before* `:518` with an explicit position. The only companion
  insert is the pre-existing `ACTION_7` one at `:488`, position `-1u`.
- **I2.** The number of conditional inserts before `:518` must not change. `ACTION_7` is already
  there and already conditional; the panel neither adds nor removes one. `numIcons` is a `u32`
  count over `insertionOrderDest` (`StartMenuTaskData`, `start_menu.c:76-79` and the struct); its
  capacity is unchanged because the insert count is unchanged.

`INFERRED`: `insertionOrderDest` / `displayOrderDest` are `StartMenuTaskData` fields
(`start_menu.c:457`), so `displayOrderDest[8]` is the highest index written by the fixed slots.
A C4 edit that appended a row would need slot 9; C4 does not append.

---

## 3. The panel app

### 3.1 One overlay, cloned from the trainer card's *lifecycle*

`src/overlay_trainer_card.c` (124 lines) is the template (`FEATURE_BAR.md:235`). Its lifecycle:

| Step | Trainer card | Panel |
|---|---|---|
| `Init` | `Heap_Create(HEAP_ID_3, HEAP_ID_TRAINER_CARD, 0x1000)`; `OverlayManager_CreateAndGetData`; `MI_CpuClear8`; stash `parentData` (`overlay_trainer_card.c:37-48`) | same, `HEAP_ID_SLINK_PANEL`, size chosen at build |
| `Main` | state switch over `TRAINERCARD_RUN_*` (`:50-70`) | state switch over `SLINKPANEL_RUN_*` |
| child overlay | `TrainerCardMainApp` (`:81-91`) then `TrainerCardSignature` (`:103-112`) | **none** — the signature child is dropped (`FEATURE_BAR.md:231`) |
| `Exit` | `MI_CpuClear8`; `OverlayManager_FreeData`; `sub_02004B10()`; `Heap_Destroy(HEAP_ID_TRAINER_CARD)` (`:72-79`) | same, minus anything the panel never initialised |

The trainer card's UI, **including its exit, is hand-written asm** —
`asm/overlay_trainer_card_main.s`, 4367 lines (`FEATURE_BAR.md:236`). C4 writes none of that in
asm: the panel's window, text and B-exit are C (§3.3, §3.4).

### 3.2 Window and text calls

The HGSS UI APIs (`FEATURE_BAR.md:78`), all verified at the pinned pret:

| Call | Signature | Evidence |
|---|---|---|
| `AddWindow` | `void AddWindow(BgConfig*, Window*, const WindowTemplate*)` | `include/bg_window.h:249` |
| `RemoveWindow` | `void RemoveWindow(Window*)` | `include/bg_window.h:250` |
| `DrawFrameAndWindow1` | `void DrawFrameAndWindow1(Window*, BOOL dont_copy_to_vram, u16 baseTile, u8 palette_num)` | `include/render_window.h:11` |
| `DrawFrameAndWindow2` | same shape, second frame style | `include/render_window.h:13` |
| `RenderText` | `RenderResult RenderText(TextPrinter*)` | `include/render_text.h:35` |
| `TextPrinter` | `typedef struct TextPrinter {...} TextPrinter` | `include/font_types_def.h:49-64` |
| `Window` | `typedef struct Window {...}` | `include/bg_window.h:68` |

`ListMenuInit` (`include/list_menu.h`) is **not** used: the panel is read-only text with no
cursor, and the ABI carries no selection field (`SlinkInfoV2` at `patch/src/nds/common/abi.h:207-217`
has no selection byte). **INFERRED**: `list_menu.h` exists at the pinned pret; I did not read it.

### 3.3 The payload the app draws

`SlinkInfoV2` (`patch/src/nds/common/abi.h:207-217`), used unmodified:

```
+0x00 session_epoch (host)   +0x04 request_seq (host)   +0x06 drawn_seq (native)
+0x08 lines, +0x09 page, +0x0A pages, +0x0B enable   (all host)
+0x0C closed_seq (native)    +0x0E state, +0x0F result (native)
+0x20 text[8][32]            (host)
```

Geometry constants (`abi.h:55-59`):

- `SLINK_INFO_LINE_WIDTH 32` — **bytes per row** (`abi.h:55`).
- `SLINK_INFO_MAX_LINES 6`, `SLINK_INFO_ROW_COUNT 8`, `SLINK_INFO_PAGE_SLOT 7`,
  `SLINK_INFO_BAR_WIDTH 38`.

**Gen 4 rows are 16 characters.** `patch/src/nds/common/panel_producer.h:3-5` states the binding
rule: *"Gen 3 rows end in 0xFF, Gen 4/5 rows in 0xFFFF UTF-16 units within the same 32-byte row"*.
The `SlinkTextSpec` for Gen 4 is therefore `{ .width = 2, .charset = <HGSS font charset>,
.terminator = 0xFFFF }` (`record_binding.h:44`), and `slink_panel_valid` rejects any row without the
terminator (`panel_producer.h:27-30`, `record_binding.h:185-195`). **The host must truncate every
row to 15 characters plus the terminator; a 16th character is a silent overflow of the row's
intent and the producer will refuse the whole payload.**

Layout the app draws, mirroring Gen 3's host (`lua/gen3/native.lua:1110-1121`, `:1144-1147`):

- rows `0 .. lines-1` (at most 6) → text lines;
- **row 6 is never validated** (`panel_producer.h:28`: rows ≥ `lines` are skipped *except* row 7) and
  is used as the page bar; `SLINK_INFO_BAR_WIDTH 38` (`abi.h:59`) is the bar's cell count;
- **row 7 is always validated, even when `lines < 7`** (`panel_producer.h:28`) → it is the footer,
  `"PAGE n/m"`, exactly as Gen 3 writes it (`lua/gen3/native.lua:1121`).

The app never writes `text[]`, `lines`, `page`, `pages`, `enable`, `request_seq` or
`session_epoch` (§7).

### 3.4 The B-exit, in C

Behaviour to copy, read from `asm/overlay_trainer_card_main.s`:

```
1869  ldr r1, _021E6A9C ; =gSystem
1871  ldr r1, [r1, #0x48]        ; newKeys  (NOT heldKeys, which is +0x44)
1872  tst r2, r1  (r2 = 1)       ; bit 0 -> SELECT arm
1888  mov r0, #2
1889  tst r0, r1                  ; bit 1 -> B
1891  mov r0, #SEQ_SE_GS_GEARCANCEL>>6
1893  bl PlaySE
1894  mov r0, #5                  ; -> exit
```

(`:1866-1910` for the whole routine; the FB's `:1867-1904` is the same body with tighter bounds.)

and the fade the caller runs on that return value:

```
:379-398   cmp r0, #5  ->  call ov51_021E7D44;  BeginNormalPaletteFade(6, 1, 0x19, 4, 0);  state = 2
:409-415   case 2:  IsPaletteFadeFinished() ? -> return TRUE   (the app finishes)
```

`BeginNormalPaletteFade` is declared at `include/unk_0200FA24.h:6`:
`void BeginNormalPaletteFade(int pattern, int typeTop, int typeBottom, u16 color, int duration, int framesPer, enum HeapID heapID)`.

**C4's exit, in C:**

1. poll `gSystem->newKeys` (`gSystem + 0x48`) for B, mirroring `:1869-1889`. **`newKeys`, not
   `heldKeys`:** `+0x48` is the fresh-press word the trainer card tests — and which is what a
   "close the panel" gesture wants — while `heldKeys` is `+0x44` (`include/system.h:20-42`). A held
   read would close the panel the frame the button went down and make the B-exit untestable.
   (corrected 2026-10-03: the draft labelled `gSystem + 0x48` as `heldKeys` in both the asm
   excerpt and the C step, and told the panel to poll `heldKeys`. Repo data agrees with the
   correction — `data/games/gen4_hgss/profile.json:5223` and `data/games/gen4_hge/profile.json:5826`
   both record `gSystem+0x48 = newAndRepeatedKeys`.)
2. on B: `PlaySE(SEQ_SE_GS_GEARCANCEL)` — the same id, so the cancel sound is the engine's, not a
   companion guess (`FEATURE_BAR.md:175-177` left the *FAILURE* SE undecided; the cancel SE is a
   different, already-sourced id);
3. `BeginNormalPaletteFade(...)` with the trainer card's arguments;
4. poll `IsPaletteFadeFinished()` each frame;
5. when it finishes, return `TRUE` from `SlinkPanelApp_Main`, which takes `SlinkPanelApp_Exit` →
   `OverlayManager` deletes the app;
6. publish `result = 0x7F` (B/close) at `closed_seq` before returning (see §3.5 and §8-Q1).

**VERIFIED:** `SEQ_SE_GS_GEARCANCEL` is **2368**, read directly at pinned pret
`include/constants/sndseq.h:1366` (between GEARCURSOR 2367 and GEARDECIDE 2369).
The decision block and body use the same value; this is SOURCE, not an inferred sound id.

### 3.5 Page navigation (the ABI has pages, so use them)

The ABI is page-native: `page` and `pages` are host fields (`abi.h:211`) and `result` is
`0 = A/more, 0x7F = B/close` (`abi.h:213-214`). Gen 2's accepted UX is
`patch/gen2/src/panel.asm:57-69`:

```
57  ld a, c
58  and PAD_A
59  jr z, .close
60  ld a, [wSlinkMailbox + SLINK_OFS_PANEL_PAGE]
61  inc a
63  ld a, [wSlinkMailbox + SLINK_OFS_PANEL_PAGES]
65  jr c, .close     ; zero page count is one page
66  jr z, .close     ; A on last page closes; there is no wrap to the first page
68  ld [wSlinkMailbox + SLINK_OFS_PANEL_PAGE], a
69  jr .page
```

Gen 4's rule, same shape:

| Input | Action | `result` |
|---|---|---|
| B | close the app | `0x7F` |
| A, `page + 1 < pages` | close the app; the host re-posts the next page | `0` |
| A, `page + 1 >= pages` | close the app (Gen 2's **no-wrap** rule) | `0x7F` (see §8-Q1) |
| nothing | stay, redraw nothing | — |

**The ROM never advances a page cursor.** `page` is a host-owned field (§7), so the ROM reads
`info->page` and shows it; the host owns the turn. This is exactly Gen 3's loop
(`lua/gen3/native.lua:1151-1155`: `result == 0 and pages > 1` → advance and re-post, else reset to
page 0). Doing it the other way — a ROM-private cursor — would need ROM-writable app-durable
storage and would fight the single-writer table.

Gen 2 also prices a **no-payload fallback** (`panel.asm:21-46`): the ROM publishes AWAIT, waits
for the host with a 90-frame poll (`:80-88`), and on timeout closes the lease *before* revealing
a fallback screen, so a late host cannot paint over a visible screen. For Gen 4 the inversion is
that the ROM draws. C4's rule:

> The panel app **always opens** when the row is pressed. If the producer never started (no valid
> `SlinkInfoV2` staged, or the host is absent), the app draws Gen 3's own fallback row
> (`"No run data yet"`, `lua/gen3/native.lua:1120` and `:1139`), `pages = 1`, `page = 0`, and B
> closes it. A START-menu row that silently does nothing is a dead button.

**INFERRED**: this launch-always shape is the one I recommend because
`slink_panel_service` returns without calling `start()` when `slink_panel_valid` fails
(`panel_producer.h:49-53`), so a launch driven *only* by the producer never reaches the screen when
the host is late. The alternative — the row handler skips the launch on an invalid payload — is
recorded in §8-Q3.

---

## 4. Placement, per artifact

### 4.1 HG/SS — one `After main` overlay group

Append one group to `main.lsf`. The syntax, from the trainer card's own two groups:

```
main.lsf:847-851   Overlay trainer_card          { After main;         Object src/overlay_trainer_card.o; }
main.lsf:852-856   Overlay trainer_card_main     { After trainer_card; Object asm/overlay_trainer_card_main.o; }
main.lsf:857-861   Overlay trainer_card_signature{ After trainer_card_main; Object asm/overlay_trainer_card_signature.o; }
```

so:

```
Overlay slink_panel
{
    After main
    Object patch/slink_panel_overlay.o
}
```

Overlay groups carry no `Address` and are name-keyed, so `FS_OVERLAY_ID(slink_panel)` resolves the
id at link time (`FEATURE_BAR.md:225-226`).

**Why `After main` and not `After trainer_card`.** `After main` is a **predecessor constraint**, not
a placement choice: the group must be ordered after `main` or the linker may place it anywhere in
the overlay ordering. Within that constraint the draft's reasoning was: `FEATURE_BAR.md:223` claims
`field` (ov1) and `trainer_card` (ov50) **both** load at `0x021E5900` on HG, so loading the app
overlay evicts the field overlay by region conflict, which is why the return path reloads it — and a
panel in the same region is therefore mutually exclusive with both, which is what we want.
**SOURCE correction 2026-10-04:** HG sharing is also proven: pinned
`heartgoldus.xMAP:53318` (field) and `:130861` (trainer_card) both start at
`0x021E5900`; `:63123` puts field BSS_END at `0x02245B80`, giving ov1's footprint
`0x60280`. The window to the arena `0x0226EC40` is instead `0x89340`.
**The linked group's END must not exceed SDK_SECTION_ARENA_START**, not a guessed
"free 0x60280" budget. New panel placement/ramSize and SS values remain UNVERIFIED
until the corresponding link/ELF. See side-branch `C4_FACTS.md` Q9 at
`claude/gen4-companion-policy@d68e8137`; no HG number is asserted as SS evidence.

### 4.2 hge — a `src/<dir>` overlay at `0x021E5900`

- A new overlay is a **directory drop** (`overlays.mk:7,21-26`, per `FEATURE_BAR.md:228`); hooks are
  a flat text table (`FEATURE_BAR.md:60`).
- **The hge panel overlay takes the vanilla-style slot `0x021E5900`** — an app slot exclusive with
  `field`, as hge's own ov142/147 do — *not* the unproven top-of-RAM window. This is a settled
  coordinator decision (`FEATURE_BAR.md:244`), because hge has no `ArenaHi` lowering and nothing
  proven keeps the main arena out of `0x023C0000-0x023E0000` (`FEATURE_BAR.md:243`).
- The START-menu edit is **one site for both artifacts**: `start_menu.o` is static ARM9, and all 74
  of its symbols are byte-identical between HG (`4fcded0e`, BLZ-decompressed) and hge (`cb2dc435`,
  raw ARM9) (`FEATURE_BAR.md:122-126`). On HG/SS the edit lands in the source rebuild; on hge it is
  a `hooks` row.
- **Forbidden:** the hge registration must not hook `0x02000CD0` — it is hge's own
  `bl load_arm9_expansion` *and* our admission anchor (`FEATURE_BAR.md:245`,
  `C2_BEACON_SPEC.md:216-219`). That concerns the C2 service registration, not C4's row, but the
  rule stands for any C4 hge hook.
- **The msgdata edit on hge — SETTLED by the decision block, not open.** The route is a new
  `hg-engine/data/text/196.txt` holding the decoded member with row 7 filled, **CRLF**, with the
  round-trip `cmp` gate run **before** the edit (`C4_PANEL_SPEC.md:16-18`). (corrected 2026-10-03:
  this bullet said "**UNVERIFIED**, and it is the largest open risk on hge" and offered three
  unchosen options. The owner/coordinator has ruled; the only remaining work is executing the
  decided route and its gate — C6 §3.4 and C6 falsifiers F5/F6.)

### 4.3 The launch and return chain, once

Read end to end at the pinned pret:

```
start_menu.c:1096-1099   Task_StartMenu_HandleSelection_TrainerCard:  ov01_021E636C(0);
                                                        exitTaskFunc = sub_0203D1CC;
                                                        state = START_MENU_STATE_WAIT_FADE
start_menu.c:1102-1112   sub_0203D1CC:  args = sub_020691C4(HEAP_ID_FIELD2);
                                          sub_02068FC8(...);
                                          TrainerCard_LaunchApp(fieldSystem, args);
                                          exitTaskFunc = sub_0203D218
launch_application.c:1143-1150  TrainerCard_LaunchApp: static OverlayManagerTemplate
                                  { TrainerCard_Init, TrainerCard_Main, TrainerCard_Exit,
                                    FS_OVERLAY_ID(trainer_card) };
                                  FieldSystem_LaunchApplication(fieldSystem, &tpl, args)
field_system.c:127-133   FieldSystem_LaunchApplication:
                                  GF_ASSERT(fieldSystem->unk0->unk4 == NULL);
                                  sub_0203DF34(fieldSystem);
                                  fieldSystem->unk0->unk4 = OverlayManager_New(tpl, parentWork, HEAP_ID_FIELD2)
start_menu.c:1114-1122   sub_0203D218:  sub_020691E0(exitTaskEnvironment);
                                         FieldSystem_LoadFieldOverlay(fieldSystem);
                                         state = START_MENU_STATE_RETURN
field_system.c:89-98     FieldSystem_LoadFieldOverlayInternal:
                                  GF_ASSERT(unk0->unk4 == NULL);  GF_ASSERT(unk0->unk0 == NULL);
                                  HandleLoadOverlay(FS_OVERLAY_ID(field), OVY_LOAD_ASYNC);
                                  unk0->unk0 = OverlayManager_New(&ov01_02206378, fieldSystem, HEAP_ID_FIELD2)
```

C4 clones this with `SlinkPanel_Init/Main/Exit` and `FS_OVERLAY_ID(slink_panel)`. Two differences,
both deliberate:

- **No args struct.** The trainer card allocates `TrainerCardAppArgs` on `HEAP_ID_FIELD2`
  (`:1106`) because its child needs `saveData`. The panel needs none, so `SlinkPanel_LaunchApp`
  passes `parentWork = NULL`. **INFERRED**: safe, because the panel app takes no data from
  `parentData` — it takes its data from `OverlayManager_CreateAndGetData` on its own heap, and the
  host payload comes from the mailbox, not from the field. Must be confirmed that no engine path
  dereferences the manager's args before the app's `Init` runs.
- **`FieldSystem_LaunchApplication` asserts `unk0->unk4 == NULL`** (`field_system.c:128`), so at most
  one child app at a time. The panel inherits that guarantee from the start menu, which has already
  torn its own child down.

---

## 5. Host side: the `SlinkInfoV2` staging flow

### 5.1 The split

`patch/src/nds/common/abi.h:203-206` is the contract, verbatim:

> Host stages epoch/request/rows via the owned queue. Native owns `drawn_seq`, `closed_seq` and
> state. **ACK alone is not DRAWN**; rows stay owned until closed. Request sequence is published
> last and bound to `session_epoch`. Rows are `SLINK_INFO_LINE_WIDTH` bytes; each must hold the
> binding's text terminator.

Field offsets are named in `abi.h:218-228` (`SLINK_INFO_EPOCH_FIELD 0`, `_REQUEST_FIELD 4`,
`_DRAWN_FIELD 6`, `_LINES_FIELD 8`, `_PAGE_FIELD 9`, `_PAGES_FIELD 10`, `_ENABLE_FIELD 11`,
`_CLOSED_FIELD 12`, `_STATE_FIELD 14`, `_RESULT_FIELD 15`, `_TEXT_FIELD 32`), and the whole region
is `SLINK_INFO_OFFSET 0x6E0`, size `0x120` (`abi.h:53-54`).

The producer that enforces the split is `patch/src/nds/common/panel_producer.h:33-63`
(`slink_panel_service`), used **unmodified**:

1. If a panel is active, drain first: `poll` → `1` sets `drawn_seq = snapshot.request_seq`,
   `state = 2`; `poll` → `2` sets `result`, `closed_seq = snapshot.request_seq`, `state = 0`
   (`:41-42`) — all three **guarded** by "mailbox epoch == snapshot epoch **and** info epoch ==
   snapshot epoch **and** `request_seq == snapshot.request_seq` (`:39-40`). A host that rewrites the
   payload mid-panel is ignored, not obeyed.
2. Otherwise, take a request: `posted = (m->opcode == SLINK_OP_SHOW_INFO)`; a panel also starts
   un-posted when `menu_open` and `m->opcode == 0` (`:46-47`).
3. Refuse unless `e->safe()` and `slink_panel_valid(info, m->session_epoch, e->text)`
   (`:49-53`); a posted request that is refused is ACKed with status 0, reason 2
   (`SLINK_REASON_BAD_ARGS`, `abi.h:101`).
4. **Copy** the whole `SlinkInfoV2` into a private snapshot (`:54-56`) and start from *that*
   (`:57`). The drawn text is immune to host writes — this is the Gen 4 equivalent of Gen 2's
   "paint into the white screen, publish STAGED last" (`lua/gb_panel.lua:186-196`).
5. On success: `state = 1`, and a posted request is ACKed (`:61-62`).

### 5.2 The Gen 4 host

New file `lua/gen4/companion.lua` (C2's file, `PLAN.md:63`), reading the header itself with no
`lua/nds` edit at C2 (`C2_BEACON_SPEC.md:14`) — C4 adds to that file and touches nothing shared, so
it is not gated on the C7 window (`PLAN.md:71`).

Flow, per field, in publish order (the order matters — `abi.h:204-206` says the request sequence is
published **last**):

| # | Host write | Field | Note |
|---|---|---|---|
| 0 | refuse unless `capabilities & SLINK_CAP_INFO_PANEL` | — | the Gen 3 guard, verbatim: `lua/gen3/native.lua:1163` |
| 1 | clear `text[]` to `0xFF 0xFF` per unit | `+0x20` | an unwritten row would fail `slink_panel_valid` |
| 2 | write rows `0..lines-1`, truncated to **15 chars + `0xFFFF`** | `+0x20` | §3.3 |
| 3 | write row 6, the page bar (`SLINK_INFO_BAR_WIDTH 38`) | `+0x20` | §3.3 |
| 4 | write row 7, `"PAGE n/m"` | `+0x20` | `lua/gen3/native.lua:1121` |
| 5 | `lines`, `page`, `pages`, `enable` | `+0x08..0x0B` | `lines ≤ SLINK_INFO_MAX_LINES` (`panel_producer.h:26`) |
| 6 | `session_epoch` | `+0x00` | bound to the C2 session epoch, never zero |
| 7 | `request_seq` = previous + 1 | `+0x04` | **published last** |
| 8 | (optional) `m->opcode = SLINK_OP_SHOW_INFO`, `m->seq` | mailbox | `abi.h:83`; only needed to *force* an open — with `menu_open` the panel starts un-posted (`panel_producer.h:47`) |

`SLINK_OP_SHOW_INFO` is `27` (`abi.h:83`). `SLINK_CAP_INFO_PANEL` is `1 << 1` (`abi.h:90`); C2
advertises `0` and this is the card that adds the bit (`C2_BEACON_SPEC.md:427-430`).

Waiting on close: the host reads `state`, `drawn_seq` and `closed_seq` at `+0x0E`, `+0x06`, `+0x0C`
and resumes when `closed_seq == request_seq` and `result` says stop (`abi.h:212-214`). Gen 3's loop
is the reference (`lua/gen3/native.lua:1130`, `:1150-1156`).

**A/B semantics are inverted relative to the Gen 2 host and must be stated once.** Gen 2: the ROM
publishes AWAIT and *waits for the host to paint* (`patch/gen2/src/panel.asm:38-40`, `lua/gb_panel.lua:186-196`).
Gen 4: the ROM draws and the host publishes. Nothing in `lua/gb_panel.lua` may be reused verbatim
for the Gen 4 payload path; the file's *policies* (sanitise before staging, never open on blanks,
publish the marker last) are the reusable part (`lua/gb_panel.lua:151-196`).

---

## 6. Falsifiers

Each is a check with a named failure. S = SOURCE, M = MODEL (lupa), P = PHYSICAL
(`PLAN.md:57`, `:65`).

| # | Falsifier | Class | How it is checked | Fails when |
|---|---|---|---|---|
| **F1** | **No capability, no row.** | S + P | Build the tree twice: once with `SLINK_COMPANION_INFO_PANEL` undefined, once defined. Diff the `sStartMenuActions` bytes and the inhibit word. Then, on the capability-less build, open the START menu in a save. | The inhibit word at `start_menu.c:303` differs between the two builds; or `capabilities` has `SLINK_CAP_INFO_PANEL` (`abi.h:90`) set while the row is absent; or the row is present with no payload and something other than the §3.5 fallback draws. |
| **F2** | **Slots 7/8 unmoved.** | S | In the built `start_menu.o`, decode the two `StartMenuButton_Insert(..., 7)` / `(..., 8)` calls (`start_menu.c:518-519`) and confirm the immediate operands are still 7 and 8; and confirm the count of conditional inserts before them is unchanged from vanilla (12 call sites of `StartMenuButton_Insert` in `StartMenu_BuildActionLists`, `:484-519`). | Either immediate changed, or the insert count changed. Both are also caught by the vanilla-vs-patched `insertionOrderDest` byte trace with every inhibit combination exercised. |
| **F3** | **The panel draws host text.** | P | Stage three distinct payloads; open the row on HG, SS and hge; screenshot both screens. | The drawn glyphs are not the staged rows; a row exceeds 15 characters without truncation; a row's terminator is missing (`panel_producer.h:29` refuses). |
| **F4** | **B closes with no leak.** | P | Open → B → open → B ×50. After each close: (a) `Heap_Destroy(HEAP_ID_SLINK_PANEL)` ran (`overlay_trainer_card.c:77` is the shape); (b) the two `GF_ASSERT`s in `FieldSystem_LoadFieldOverlayInternal` (`field_system.c:90-91`) do **not** fire on the next open — `unk0->unk4` must be NULL, which is the engine's own proof that `OverlayManager_Delete` ran; (c) a heap high-water sample on `HEAP_ID_FIELD2` is unchanged across the 100-cycle loop. | Any assert, or monotonic growth on `HEAP_ID_FIELD2`, or a black screen after the second open (overlay region not released). |
| **F5** | **The field is reloaded.** | P | After B, assert the field app is alive: `unk0->unk0 != NULL` (`field_system.c:115-117`) and the player can move. | `unk0->unk0 == NULL` → the return path (`start_menu.c:1119` → `FieldSystem_LoadFieldOverlay`) did not run. |
| **F6** | **`drawn_seq` handshake.** | M + P | In the lupa world, drive `slink_panel_service` with a stub engine returning `poll` 0,1,1,2 and assert `state` goes `0 → 1 → 2 → 2 → 0` and `drawn_seq == request_seq` at the `2` (`panel_producer.h:41`). Then repeat with the host rewriting `request_seq` mid-panel and assert the `2` is **ignored** (`:39-40`). | `state` skips 1; `drawn_seq != request_seq`; or a mid-panel rewrite is obeyed. |
| **F7** | **`closed_seq` handshake.** | M | Same harness: after `poll` returns 2, assert `closed_seq == request_seq`, `result` is the app's byte, `state == 0`, and a **second** `poll` 2 does not re-publish (the `s->active` latch, `panel_producer.h:44`). | Any of the three is wrong, or the second close double-publishes. |
| **F8** | **Refusals never half-draw.** | M | Post a payload with `lines = 0`, `lines = 7`, a row with no terminator, a mismatched `session_epoch`, `request_seq = 0`. Assert `tp_ack(m, seq, 0, 2)` (`panel_producer.h:51`) and `state` untouched. | Any payload is accepted, or the app opens with a torn payload. |
| **F9** | **Capability gating is real at both ends.** | M | A build advertising `0` capabilities: the host's step 0 refuses; no row is drawn. A build advertising `SLINK_CAP_INFO_PANEL` with no host: the panel opens on the §3.5 fallback and B closes. | The host stages into a build that says no, or the ROM draws a payload that was never validated. |
| **F10** | **The appended `slink_panel` group lands where the linker says, and the arena has not moved.** | S | One `main.elf` read after the first HG/SS link, before any panel code is written: (a) the group's load address from the linked section headers, and (b) the resulting `SDK_SECTION_ARENA_START`. Assert the load address is inside the app-overlay base and the arena is still `0x0226EC40`. | The group loads elsewhere, or `SDK_SECTION_ARENA_START` moves. Either means §4.1's placement argument is wrong and the group must be re-planned before C4 SOURCE proceeds. |

**F4 is the one that cannot be faked by static analysis** — an unreleased overlay region, a
surviving `unk0->unk4`, and a grown `HEAP_ID_FIELD2` heap all present as a *working-looking* screen.
`PLAN.md:65`'s exit evidence says "the menu closing without a leak" for exactly this reason.

---

## 7. Single-writer table

Per field, one writer. This is the OMP F6 rule that C2 records as its review checklist
(`FEATURE_BAR.md:258`); C4 restates it for the info region only.

| Field | Offset | Writer | ROM may read? | ROM may write? |
|---|---|---|---|---|
| `signature` | `MB+0x00` | ROM (C2, every tick) | — | yes (re-stamp) |
| `capabilities` | `MB+0x40` | ROM (C2/C3/C4) | — | yes |
| `opcode`, `seq`, `args[]` | `MB+0x06/0x08/0x10` | host | yes | **never** |
| `session_epoch` (mailbox) | `MB+0x44` | host | yes (gate) | **never** |
| `status`, `ack_seq`, `reason` | `MB+0x0A/0x0C/0x0E` | ROM | yes | yes |
| `producer_phase` | `MB+0x48` | ROM | yes | yes |
| `reserved` → boot generation | `MB+0x4C` | ROM | yes | yes |
| `SlinkInfoV2.session_epoch` | `INFO+0x00` | **host** | yes (gate) | **never** |
| `SlinkInfoV2.request_seq` | `INFO+0x04` | **host** (published last) | yes | **never** |
| `SlinkInfoV2.drawn_seq` | `INFO+0x06` | **ROM** | yes | yes |
| `SlinkInfoV2.lines/page/pages/enable` | `INFO+0x08..0x0B` | **host** | yes | **never** |
| `SlinkInfoV2.closed_seq` | `INFO+0x0C` | **ROM** | yes | yes |
| `SlinkInfoV2.state` | `INFO+0x0E` | **ROM** | yes | yes |
| `SlinkInfoV2.result` | `INFO+0x0F` | **ROM** | yes | yes |
| `SlinkInfoV2.reserved[4]` | `INFO+0x10..0x1F` | **nobody** | no | **never** |
| `SlinkInfoV2.text[8][32]` | `INFO+0x20` | **host** | yes (copied, once, into the snapshot) | **never** |

Two rules that make the table enforceable rather than aspirational:

- **The ROM's only writer is `slink_panel_service`.** The app calls it; it never touches the
  mailbox directly. The engine seam is three function pointers plus a `SlinkTextSpec`
  (`panel_producer.h:10-16`), so "the app writes the info region" is impossible by construction.
- **The host's only writer is the staged-write helper**, which writes rows first, header fields
  second and `request_seq` **last** (`abi.h:204-206`). A torn payload is therefore always
  *unvalidated* rather than *half-drawn* — the producer refuses it (F8).

The mailbox-vs-info **epoch and request** agreement is checked twice, inside the producer
(`panel_producer.h:39-40`, `:50`), so the two halves cannot disagree about which request is live.

---

## 8. Open questions

| # | Question | Why it matters | What settles it |
|---|---|---|---|
| **Q1** | **`result = 0x7F` on A-on-last-page.** `abi.h:213-214` documents `result` as *"`0` A/more, `0x7F` B/close"*. Gen 2's accepted UX closes on A-at-last-page with no wrap (`patch/gen2/src/panel.asm:66`), which is not "B". Either (a) the ABI comment is widened to "`0x7F` = close, cause not distinguished", or (b) the host is taught to wrap, which **rejects Gen 2's no-wrap rule** and must be an owner ruling. I chose (a) and flagged it rather than deciding it. | The Gen 3 host tolerates any non-zero result as "done" (`lua/gen3/native.lua:1151-1155`), so (a) is backward compatible — but the ABI header is shared with Gen 3 and Gen 5, and C4 may not edit it (`C2_BEACON_SPEC.md:47-49`). | The ABI owner. One comment line in `abi.h:213`. |
| **Q2** | ~~**hge's msgdata.**~~ **RESOLVED by the decision block.** The label route is settled: new `hg-engine/data/text/196.txt`, **CRLF**, decoded member 196 with row 7 filled, gated on a no-edit decode → re-encode round-trip `cmp` on an output file named exactly `7_196` before the edit, then a NARC diff proving only member 196 and only row 7 changed (`C4_PANEL_SPEC.md:16-18`). The "largest open risk on hge" framing is void. | Carried into C6 SOURCE as falsifiers F5 and F6 (`C6_HGE_BUILD_SPEC.md:498-499`), not as an open question. (corrected 2026-10-03.) |
| **Q3** | **Launch-always vs launch-on-valid.** §3.5 recommends always launching (fallback inside the app). The alternative is a row handler that skips the launch when `slink_panel_valid` fails, so no window ever appears without a payload. | Gen 2 shows a fallback (`panel.asm:21-46`), which favours launch-always. But a Gen 4 window that appears with host-absent text may read as a bug to a player. | An owner UX ruling. Cheap to flip: the two shapes differ by one branch in the row handler. |
| **Q4** | **Panel ramSize remains OPEN.** HG ov1 footprint is 0x60280; the base-to-arena window is 0x89340 (C4_FACTS Q9e). | The new group must end at or below 0x0226EC40 on HG. SS placement is UNVERIFIED. | Read the actual linked panel sections and arena start, F10. |
| **Q5** | **SOURCE CLOSED: parentWork=NULL is stored verbatim.** `src/overlay_manager.c:5-18,41-43` neither dereferences it nor changes it. | Panel Init must not call OverlayManager_GetArgs expecting trainer-card arguments. | C4_FACTS Q5; actual panel binding still missing. |
| **Q6** | **The row's display position.** `ACTION_7` lands at display position 1 (`start_menu.c:487-489`), i.e. **second**, behind `RETIRE` — which is always inhibited — so in practice it is the **top** visible row in an ordinary save (Pokedex is not yet unlocked early on, `:490-492`). | Cosmetic, but it is the one thing a player sees first. If the owner wants SLINK below Pokédex, that needs a display-position edit, which brushes the §2.5 never-move rule. | Owner preference. The rule in §2.5 is satisfied either way as long as no explicit position ≥ 7 is used. |
| **Q7** | **SOURCE CLOSED: charset is not a font id.** Pass `&slink_binding_gen4_pk4.text` (width 2, charset GEN4=2, terminator 0xFFFF); `record_binding.h:165-171,185-195` validates width/terminator, not charset. | A wrong charset value alone cannot refuse a payload. HGSS window font 4 is a separate precedent (`src/party_menu.c:285`), not this enum. | C4_FACTS Q7; symbolic font name remains UNVERIFIED. |
| **Q8** | **Policy resolved; binding OPEN.** Fade-finished + launching menu context + no running child app (`panel_policy.h:146-153`). | `src/start_menu.c:705-715` supplies the fade wait. No text-window-active predicate is in this chain. | C4_FACTS Q8: menu_open/app_running remain adapter seams, not proven single engine flags. |
| **Q9** | **HG vanilla overlap SOURCE proven; new group and SS placement OPEN.** `heartgoldus.xMAP:53318,130861` both load at 0x021E5900; arena at 0x0226EC40. | Existing groups do not prove where a newly appended slink_panel group will link. | Actual HG/SS linked ELF plus new arena start, F10; C4_FACTS Q9. |

---

## 9. Citation drift found in `FEATURE_BAR.md` (all read at the pinned pret `ad7a3afa`)

Same facts, different lines. None changes a conclusion; all are worth fixing before the bar is
quoted again.

| `FEATURE_BAR.md` says | The pinned tree says | Note |
|---|---|---|
| inhibit `:305-306` (`:79`) | `start_menu.c:303` | `:305` is the closing brace of the function; the assertion is at `:303` |
| fixed slots `:517-518` (`:80`) | `start_menu.c:518-519` | `:517` is the closing brace of the RUNNING_SHOES `if` |
| launch chain `:1104-1112`, `:1120-1127` (`:81`) | `sub_0203D1CC` is `:1102-1112`; `sub_0203D218` is `:1114-1122` | `:1104` is a local decl; `:1120` is `state = RETURN`, `:1124-1131` is the Save handler |
| `field_system.c:89-96` (`:222`) | `:89-98` | the two `OverlayManager_New`/flag lines at `:97` are outside the cited range |
| `ov51_021E6A54 :1867-1904` (`:237`) | `:1866-1910` | body is `:1868-1904`; `:1906-1909` is the literal pool |
| `TrainerCardMainApp_Main :393-412` (`:237`) | `:323-479`; the fade-init is `:387-398`, the fade poll `:409-415` | `:393` lands inside the `BeginNormalPaletteFade` argument setup |

Also **new**, and not in the bar at all: `msg_0196_00007` is a garbage row with an empty English
string (`files/msgdata/msg/msg_0196.gmm:31-35`) — the fact that decides §2.1.

---

## 10. What the owner signs

1. **§2.1:** repurpose `START_MENU_ACTION_7`, not `RETIRE` (garbage label slot; suppressed in six
   contexts instead of three).
2. **§2.4:** the label is `SLINK`; the msgdata edit is accepted as part of the companion.
3. **§3.5 + Q1:** A-on-last-page closes (Gen 2's no-wrap), reported as `result = 0x7F`; the ABI
   comment is widened.
4. **§3.5 + Q3:** the panel always opens; the no-payload case shows the Gen 3 fallback row.
5. **§4.2 + Q2:** the hge msgdata route, before C6 builds.
6. **§6:** the falsifier set, with F4 (leak) and F2 (slots 7/8) as the two that fail silently.
