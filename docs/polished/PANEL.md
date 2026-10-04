# Polished Crystal 3.2.3 — porting SLink's Start-menu panel

**Design card. Nothing here is implemented.** It maps SLink's in-game START-MENU panel (the "SLINK"
entry that opens a partner/link status panel the host paints) from vanilla pokecrystal/GSC onto
Polished Crystal v3.2.3.

Sources: `patch/gen2/src/panel.asm`, `panel_start.asm`, `panel_flags.asm`,
`lua/gen2/panel.lua`, `patch/gb/slink_abi.inc`, `docs/polished/HOOKS.md` §2 rows 6/7/9 and §3.3,
and the pinned Polished source at `F:/slink-work/cache/polished/src` plus the release ROM at
`F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc`.

**Method, stated up front because this lane has already been burned twice.** ROM facts below are
`bank:addr` + `flat` + bytes **read by Python from the release ROM**. `flat = bank * 0x4000 + addr -
0x4000` for `bank != 0`, and `flat = addr` for bank `00`. **WRAM is not in the ROM**: a symbol whose
address is `$C000`-`$DFFF` or `$FF80`-`$FFFF` has **no ROM bytes**, and none is quoted for it. I hit
exactly that error earlier in this lane (a ROM read at a WRAM address) and re-checked every cell.
Second guard: **all Lua tables here are 1-based**; `bytes[9]` means offset 9.

---

## 1. The vanilla panel flow, step by step

### Step 0 — the menu entry (`patch/gen2/src/panel_start.asm`)

Included at the **end** of native `engine/menus/start_menu.asm`, still in bank 4:

```
SlinkStartMenuEntry:
	call FadeToMenu
	farcall SlinkPanel
	ld a, 6 ; StartMenu.ReturnRedraw owns the matching window/palette restoration.
	ret
SlinkMenuString:
	db "SLINK@"
SlinkMenuDesc:
	db "Partner"
	next "status@"
ASSERT BANK(SlinkStartMenuEntry) == 4
```

The three `ASSERT BANK(...) == 4` lines are the design's own guard: the entry must link in the Start
menu's own bank because the menu's item table is a bank-relative `dw` chain.

### Step 1 — entering the panel (`patch/gen2/src/panel.asm`)

`SlinkPanel` sets `hInMenu = TRUE` and **clears all three panel mailbox bytes to `SLINK_PANEL_CLOSED
(0)`** — state, page, pages. Then, because `FadeToMenu` has hidden the map, it establishes the text
palette's original colours with `ld b, SCGB_DIPLOMA / call GetSGBLayout`, **before** revealing
anything.

### Step 2 — the page loop

```
.page:
	call ClearBGPalettes      ; waits 4 frames
	call ClearTilemap
	ld hl, wAttrmap / ld bc, SCREEN_AREA / xor a / call ByteFill   ; zero the attribute map
	hlcoord 2, 2 / ld de, .title   / call PlaceString   ; "SOUL LINK"
	hlcoord 2, 4 / ld de, .fallback / call PlaceString ; "NO CLIENT"
	xor a / ldh [hBGMapMode], a
	ld a, SLINK_PANEL_AWAIT / ld [wSlinkMailbox + SLINK_OFS_PANEL_STATE], a
	call .WaitForStage
```

**The host paints into the tilemap and attribute map directly, while everything stays hidden.**
`SLINK_PANEL_AWAIT (1)` is published only after the ROM has drawn its fallback; the client sees
AWAIT and writes tiles. `.WaitForStage` polls `SLINK_PANEL_STAGED (2)` for **90 frames**, and on
timeout **closes the write lease before revealing** — "a late client cannot paint after this screen
has become visible".

### Step 3 — revealing and the joypad

```
.ready:
	call WaitBGMap2          ; native transfer: CGB attributes first, then the tilemap
	call SetDefaultBGPAndOBP
	call .WaitForButton
	ld c, a                 ; captured AFTER JoyTextDelay; it may change working registers
	and PAD_B | PAD_START
	jr nz, .close
	... PANEL_PAGE / PANEL_PAGES paging; A on the last page closes, no wrap ...
```

`.WaitForButton` consumes the opening A/held key before accepting a new edge (`hJoyDown` → release,
`hJoyPressed` → accept). Paging is host-driven: the ROM reads `PANEL_PAGE` and `PANEL_PAGES` and
decides whether to loop.

### Step 4 — exit

`.close` zeroes state/page/pages, restores `hInMenu` from the stack, and returns `6` to
`StartMenu.ReturnRedraw`, which owns the window/tileset/palette/sprite restoration.

### The mailbox contract (`patch/gb/slink_abi.inc`)

| offset | field | role |
|---|---|---|
| `+8` | `SLINK_OFS_CAPS` | capability bits; `SLINK_CAP_PANEL EQU 1 << 1` |
| `+9` | `SLINK_OFS_PANEL_STATE` | `CLOSED 0` / `AWAIT 1` / `STAGED 2` |
| `+10` | `SLINK_OFS_PANEL_PAGE` | current page |
| `+11` | `SLINK_OFS_PANEL_PAGES` | page count |

All three panel bytes are **inside the 14-byte `SLINK_CORE_SIZE`** — the panel needs **zero**
extension bytes. (The phone extension is different: `SLINK_OFS_PHONE_REQUEST EQU 32`,
`SLINK_OFS_PHONE_ARMED EQU 33`, well past the core.)

**The critical property:** the panel is a *lease on a graphics buffer*, not a message channel. ROM
publishes `AWAIT`, the host writes `wTileMap`/`wAttrmap`, ROM publishes `STAGED`, then the transfer
happens. Nothing in the mailbox carries pixels.

---

## 2. Polished, step by step

### 2.1 The Start menu item table — **CHANGED shape**

`engine/menus/start_menu.asm:163-171`:

```
.Items:
	dw StartMenu_Pokedex,  .PokedexString
	dw StartMenu_Pokemon,  .PartyString
	dw StartMenu_Pack,     .PackString
	dw StartMenu_Status,   .StatusString
	dw StartMenu_Save,     .SaveString
	dw StartMenu_Option,   .OptionString
	dw StartMenu_Exit,     .ExitString
	dw StartMenu_Pokegear, .PokegearString
	dw StartMenu_Quit,     .QuitString
```

**Nine items, `dw handler, dw string` pairs — no description column.** Vanilla's row is
`dw StartMenu_Quit, .QuitString, .QuitDesc`; Polished dropped the third field.

Consequences for the port:

* The edit becomes `dw SlinkStartMenuEntry, SlinkMenuString` — **two** words, not three.
* **`SlinkMenuDesc` has no consumer.** `panel_start.asm`'s `db "Partner" / next "status@"` is dead
  text on Polished. It should be dropped from the port rather than carried, or the bank-4 budget is
  spent on bytes nothing reads.
* The const declaration edit still matches verbatim: `engine/menus/start_menu.asm:11`
  `const STARTMENUITEM_QUIT ; 8`, so `const STARTMENUITEM_SLINK ; 9` still applies.
* Bank 4 still holds: `StartMenu 04:6059`, `StartMenu_Quit 04:6267` — so all three
  `ASSERT BANK(...) == 4` lines still hold.

### 2.2 Does a tenth item fit? — **YES, and the reason is not the `menu_coords` literal**

`home/menu.asm:454` `AutomaticGetMenuBottomCoord`:

```
AutomaticGetMenuBottomCoord::
	ld a, [wMenuBorderLeftCoord]  / ld c, a
	ld a, [wMenuBorderRightCoord] / sub c / ld c, a
	ld a, [wMenuDataItems]        / add a / inc a      ; <-- bottom grows with the ITEM COUNT
	ld b, a
	ld a, [wMenuBorderTopCoord]   / add b
	ld [wMenuBorderBottomCoord], a
```

**The bottom edge is computed as `top + item_count + 1` — the `menu_coords` literal's `y2` is not the
bottom.** The Start menu declares `menu_coords 10, 0, 19, 17` (`:145`) and `menu_coords 10, 2, 19, 17`
(`:151`), so `y2 = 17` is slack, not the rendered bottom.

Adding a tenth item moves the bottom down exactly **one row** (e.g. `0 + 9 + 1 = 10` becomes
`0 + 10 + 1 = 11`), well inside `17`. **The item fits with no box edit and no scrollbar change.**
This is the same point that retired an earlier menu-box claim in this lane, and the code above is the
proof.

**UNVERIFIED:** Polished's per-item *visibility* rules (whether Pokedex/Pokegear rows hide
conditionally and therefore change `wMenuDataItems` at runtime). The static table is 9 rows; the
effective count in a given state was not traced.

### 2.3 The graphics path — **three of five calls are renamed or absent**

| vanilla call | vanilla | Polished | verdict |
|---|---|---|---|
| `GetSGBLayout` | `00:3340` | **ABSENT** | Polished has `GetCGBLayout` `00:004c` and `GetMemCGBLayout` `00:004b` |
| `WaitBGMap2` | `00:3200` | **ABSENT** | no counterpart by that name |
| `ClearTilemap` | `00:0fc8` | **ABSENT by that spelling**; `ClearTileMap` `00:0de0` | **renamed** |
| `ClearBGPalettes` | `00:31f3` | `ClearPalettes` `00:2cdd` | **renamed** |
| `SetDefaultBGPAndOBP` | — | `00:2ea4` | **same** |
| `FadeToMenu` | `00:2b29` | `00:280b` | **same** |
| `PlaceString` / `ByteFill` | `00:1078` / `00:3041` | `00:0030` / `00:0028` | **same** |
| `DelayFrame` / `JoyTextDelay` | `00:045a` / `00:0a57` | `00:0da8` / `00:07c3` | **same** |
| `hInMenu` | `00:ffaa` | `00:ff9a` | **same** |
| `hJoyDown` / `hJoyPressed` | `00:ffa8` / `00:ffa7` | `00:ff98` / `00:ff97` | **same** |
| `hBGMapMode` | `00:ffd4` | `00:ffbe` | **same** |
| `wAttrmap` | `00:cdd9` | `00:c308` (with `wTilemap` `$C1A0`) | **moved** |

ROM bytes, read from the release ROM (all ROM0 code, none in WRAM):

```
GetCGBLayout            00:004c  flat 0x00004c  d7 8c c6 02 d9 f1 c1 d1 e1 c9 52 ff
ReloadTilesetAndPalettes 00:24b3 flat 0x0024b3  cd 5c 04 cd 9f 2a d7 3b 41 05 cd 1f
SetDefaultBGPAndOBP     00:2ea4  flat 0x002ea4  d5 3e e4 cd 17 0a 11 e4 e4 cd 3c 0a
ClearPalettes           00:2cdd  flat 0x002cdd  f0 70 f5 3e 05 e0 70 21 80 dd 01 80
ClearTileMap            00:0de0  flat 0x000de0
```

**`ReloadTilesetAndPalettes` is the Polished counterpart of the vanilla reveal step**, and Polished's
own Start menu already uses it — `engine/menus/start_menu.asm:136 call ReloadTilesetAndPalettes`, and
`home/map.asm:1624` defines it. That is the strongest available precedent for the reveal sequence,
and it is the one call in this table that comes with a native in-menu caller rather than a
guess.

**`wAttrmap` moved to `$C308`.** The `SCREEN_AREA` `ByteFill` still works — it is an area, not an
address — but any hardcoded `$C000`-relative constant in `panel.asm` must be re-derived.

**UNVERIFIED — and this is the port's central open question:** vanilla's `WaitBGMap2` is a
*per-VBlank attribute-then-tilemap transfer with a mode handshake through `hBGMapMode`*. Polished's
`ReloadTilesetAndPalettes` is a whole-tileset reload, which is a **different operation**. Whether it
can replace `WaitBGMap2` without re-uploading tiles the host just painted, or whether the port needs
a different transfer primitive, **cannot be settled from source** — it depends on what Polished's
sprite/BG update path does with `hBGMapMode` when a menu owns the screen. Same for which of
`GetCGBLayout` / `GetMemCGBLayout` replaces `GetSGBLayout`; the semantics differ (CGB vs SGB
super-mode layout) and neither is obviously right.

## 3. Text-engine constraints for a host-supplied panel body

**First, the panel body is not text.** The vanilla panel prints exactly two strings — `.title`
`"SOUL LINK@"` at `hlcoord 2, 2` and `.fallback` `"NO CLIENT@"` at `hlcoord 2, 4` — and everything else
on screen is **host-written tiles and attributes** into `wTileMap`/`wAttrmap` while hidden. The
host-side drawing lives in `lua/gen2/panel.lua` (198 lines) against the shared `lua/gb_panel.lua`
handshake.

So the text constraints bind only the ROM's own two strings and any host staging that goes through
`PlaceString`-style paths:

| constraint | value | evidence / status |
|---|---|---|
| charmap | the game's own; `PlaceString` at `00:0030` maps it | **same** in Polished |
| left margin | the panel draws at column **2** | `hlcoord 2, 2` / `hlcoord 2, 4` in `panel.asm` |
| screen width | `SCREEN_WIDTH` is referenced across the tree (e.g. `audio/music_player.asm:156`) but **I could not read its definition** in the pinned tree | **UNVERIFIED** |
| variable-width font | Polished keeps pret's proportional font; `STRLEN`/font-width constants are referenced but **their definitions were not located** | **UNVERIFIED** |
| `SCREEN_AREA` `ByteFill` | still valid after the `wAttrmap` move to `$C308` — it is an area, not an address | proven by HOOKS §3.3 |

**The practical constraint for the port is the visible rows, not the width.** The panel owns roughly
`hlcoord 2, 2` through the bottom of the screen, and the Start menu's own box is
`menu_coords 10, 0, 19, 17` / `10, 2, 19, 17` — so the host's painted body must stay inside the
rows the panel clears and must not collide with the menu box when `StartMenu.ReturnRedraw`
restores. **UNVERIFIED:** how many text rows fit once the font metrics are read.

**Do not port `SlinkMenuDesc`.** Polished has no description column, so the string has no consumer.

## 4. The overlay edit list

Bank `$7E` is the service bank for everything except `panel_start.asm`, which must stay in bank 4.

| # | edit | vanilla | Polished | design |
|---|---|---|---|---|
| **E1** | declare the item constant | `_start_menu_text()` edit 1: insert `const STARTMENUITEM_SLINK ; 9` after `const STARTMENUITEM_QUIT ; 8` | `engine/menus/start_menu.asm:11` is an **exact text match** | **UNCHANGED** — copy the edit verbatim |
| **E2** | add the item row | `	dw StartMenu_Quit,     .QuitString,     .QuitDesc
` (three words) | `engine/menus/start_menu.asm:171` is `	dw StartMenu_Quit,     .QuitString` (**two** words) | **CHANGED** — emit `dw SlinkStartMenuEntry, SlinkMenuString`; drop the description column |
| **E3** | place the code in bank 4 | append `
INCLUDE "engine/slink/panel_start.asm"
` to `start_menu.asm` | `engine/menus/start_menu.asm` is `INCLUDE`d by `main.asm:80` inside `SECTION "bank4", ROMX` (`layout.link:47`) | **UNCHANGED**, provided the append still lands inside bank 4 — appending to the end of the included file does |
| **E4** | `verify_symbol_scope(..., panel=True)` | panel grows bank 4 only | `StartMenu 04:6059`, `StartMenu_Quit 04:6267` | **UNCHANGED** — the carve-out still holds |
| **E5** | `SlinkMenuDesc` + `next "status@"` | live, feeds the description column | **no consumer** | **DELETE** from the port |
| **E6** | `ld b, SCGB_DIPLOMA / call GetSGBLayout` | SGB super-mode layout | **UNVERIFIED** replacement: `GetCGBLayout 00:004c` or `GetMemCGBLayout 00:004b` | **NEW DESIGN** |
| **E7** | `call WaitBGMap2` | attribute-then-tilemap transfer with `hBGMapMode` handshake | **UNVERIFIED** — `ReloadTilesetAndPalettes 00:24b3` is a different operation (whole tileset) | **NEW DESIGN — the central risk** |
| **E8** | `call ClearTilemap` | `00:0fc8` | `ClearTileMap` `00:0de0` | **rename** |
| **E9** | `call ClearBGPalettes` | `00:31f3` | `ClearPalettes` `00:2cdd` | **rename** |
| **E10** | `wAttrmap` | `00:cdd9` | `00:c308` | **moved** — any hardcoded constant must be re-derived |
| **E11** | `hInMenu`, `hJoyDown`, `hJoyPressed`, `hBGMapMode`, `FadeToMenu`, `PlaceString`, `ByteFill`, `SetDefaultBGPAndOBP`, `DelayFrame`, `JoyTextDelay` | vanilla addresses | Polished addresses in §2.3 | **rename/re-point only** |
| **E12** | service code | `SECTION "SLink Panel", ROMX, BANK[SLINK_SERVICE_BANK]` | move wholesale to `$7E` | **same** |
| **E13** | mailbox bytes | panel uses core `+8`/`+9`/`+10`/`+11`, `SLINK_CAP_PANEL EQU 1 << 1` | **identical** | **NO ABI CHANGE** — the panel needs zero extension bytes, unlike the phone |
| **E14** | `.WaitForStage` 90-frame timeout; `.WaitForButton` release/press | as written | unchanged logic, re-pointed calls | **same**, re-measure the frame budget on Polished's timing |

**Space budget:** the panel body lives in bank `$7E` alongside the other services (HOOKS §4 moves the
whole `Slink …` family there), so the added cost of `panel.asm` is whatever it is minus the deleted
`SlinkMenuDesc`. **UNVERIFIED:** the free bytes remaining in `$7E` after every service lands there.

## 5. What can be proven statically, and what cannot

**Provable statically (no cartridge):**
- the item table shape and therefore E1/E2/E5 — from `engine/menus/start_menu.asm:163-171`;
- that the tenth item fits — from `home/menu.asm:454` `AutomaticGetMenuBottomCoord`, whose bottom is
  `top + items + 1`;
- every symbol address above, from `data/polished/polishedcrystal.sym`;
- every ROM byte quoted, from the release ROM;
- that the three `ASSERT BANK(...) == 4` still hold — `StartMenu 04:6059`;
- that the panel needs no ABI growth — `SLINK_OFS_PANEL_STATE/PAGE/PAGES` are `+9/+10/+11`, inside
  the 14-byte core.

**Live-only (no static method):**
1. **Whether `ReloadTilesetAndPalettes` can replace `WaitBGMap2`** without destroying host-painted
   tiles. This is the port's central unknown. It is a property of the linked BG-update path.
2. **Which of `GetCGBLayout` / `GetMemCGBLayout` replaces `GetSGBLayout`.** The semantics differ
   (CGB layout vs SGB super-mode); neither is obviously right.
3. **How many text rows fit**, and the real font metrics (I could not locate `SCREEN_WIDTH`'s or
   `STRLEN`'s definition in the pinned tree).
4. **Polished's runtime item-visibility rules**, i.e. the value of `wMenuDataItems` in a given state —
   the static table is 9 rows.
5. **The 90-frame `.WaitForStage` budget** on Polished's timing, and whether 60 frames is enough for a
   host round trip at 1×.

The exact observation that settles (1): paint a distinctive pattern into `wTileMap`, call
`ReloadTilesetAndPalettes`, and read the tilemap back — if the pattern survives the transfer the
replacement is sound; if the tileset reload overwrites it, a `WaitBGMap2` equivalent must be written.

## 6. Risks

1. **E7 is the blocker.** A wrong replacement either destroys the host's pixels or shows a stale
   screen, and neither fails at link time.
2. **E6 has no obviously-correct answer**, and getting it wrong means the palette is wrong on entry
   — cosmetic but immediately visible.
3. **E5 is a silent waste.** Carrying `SlinkMenuDesc` into a table with no description column spends
   bank-4 bytes on nothing and looks like a bug to the next reader.
4. **E2 changes the anchor text.** A `verify-then-replace` builder keyed on vanilla's three-word row
   will fail to match and must be re-keyed — the failure mode is a clean "anchor not found", not a
   silent mis-patch, provided the verifier is kept.
5. **The panel is a write lease on a graphics buffer with a timeout.** Every design decision that
   lengthens the host round trip (E14) erodes the 90-frame window; the timeout already closes the
   lease before revealing so a late paint cannot corrupt a visible screen.

## 7. Ordered cards, with the first falsifier for each

| # | card | first falsifier (what would kill it) |
|---|---|---|
| **P1** | settle the reveal primitive (E7) | paint a pattern into `wTileMap`, call `ReloadTilesetAndPalettes`, read the tilemap back; if the pattern is gone, E7 needs a written `WaitBGMap2` equivalent and P1 stops being a rename |
| **P2** | settle the layout call (E6) | link both candidates and compare the resulting palettes on a CGB and a DMG boot; if neither matches vanilla's, the SGB path needs a Polished-native equivalent |
| **P3** | bank-4 row: re-key the anchor to the two-word form (E2), drop `SlinkMenuDesc` (E5) | assemble `panel_start.asm`; the three `ASSERT BANK(...) == 4` failing means the append escaped bank 4 |
| **P4** | rename/re-point the call set (E8, E9, E10, E11) | assemble `panel.asm` for Polished; an unresolved symbol or a wrong `wAttrmap` constant fails the build |
| **P5** | mailbox + caps (E13) | assert the panel still reads `+9/+10/+11` and `CAP_PANEL` bit 1; a drift here is a silent capability loss, so make it a build-time `ASSERT` |
| **P6** | text metrics and host staging (P2 of §5) | read `SCREEN_WIDTH`/`STRLEN` from the pinned tree and compute the usable row count; if it is below what the panel draws, the fallback strings move |
| **P7** | timing (E14) | measure one host round trip in frames on a 1× and a 4× build; if 90 frames is not enough, the timeout or the pump changes |

**Sequencing: P1 first.** It is the only one that cannot be decided by reading, and P2/P4 are cheap
only once its answer is known. **Do not port the panel to Polished before P1 is measured** — the
whole feature is a graphics lease, and the lease's reveal step is exactly what is unresolved.

## 8. Machine-checkable citations

```json CLAIMS
[
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 6,
  "expect": "SlinkPanel::"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 18,
  "expect": "ld b, SCGB_DIPLOMA"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 48,
  "expect": "call WaitBGMap2"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 24,
  "expect": "call ClearBGPalettes"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 25,
  "expect": "call ClearTilemap"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 30,
  "expect": "hlcoord 2, 2"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 38,
  "expect": "SLINK_PANEL_AWAIT"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 80,
  "expect": ".WaitForStage:"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 81,
  "expect": "ld b, 90"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 91,
  "expect": ".WaitForButton:"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 109,
  "expect": "db \"SOUL LINK@\""
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel.asm",
  "line": 111,
  "expect": "db \"NO CLIENT@\""
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel_start.asm",
  "line": 3,
  "expect": "SlinkStartMenuEntry:"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel_start.asm",
  "line": 5,
  "expect": "farcall SlinkPanel"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel_start.asm",
  "line": 10,
  "expect": "db \"SLINK@\""
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel_start.asm",
  "line": 12,
  "expect": "SlinkMenuDesc:"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel_start.asm",
  "line": 16,
  "expect": "ASSERT BANK(SlinkStartMenuEntry) == 4"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 15,
  "expect": "DEF SLINK_OFS_CAPS          EQU 8"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 16,
  "expect": "DEF SLINK_OFS_PANEL_STATE   EQU 9"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 17,
  "expect": "DEF SLINK_OFS_PANEL_PAGE    EQU 10"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 18,
  "expect": "DEF SLINK_OFS_PANEL_PAGES   EQU 11"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 24,
  "expect": "DEF SLINK_CAP_PANEL      EQU 1 << 1"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 32,
  "expect": "DEF SLINK_PANEL_AWAIT  EQU 1"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 33,
  "expect": "DEF SLINK_PANEL_STAGED EQU 2"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 21,
  "expect": "DEF SLINK_CORE_SIZE         EQU 14"
 },
 {
  "path": "F:/slink-work/wt/polished/patch/gb/slink_abi.inc",
  "line": 29,
  "expect": "DEF SLINK_OFS_PHONE_REQUEST EQU 32"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 11,
  "expect": "STARTMENUITEM_QUIT     ; 8"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 169,
  "expect": ".ExitString"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 170,
  "expect": ".PokegearString"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 145,
  "expect": "menu_coords 10, 0, 19, 17"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 136,
  "expect": "call ReloadTilesetAndPalettes"
 },
 {
  "path": "F:/slink-work/cache/polished/src/home/menu.asm",
  "line": 454,
  "expect": "AutomaticGetMenuBottomCoord::"
 },
 {
  "path": "F:/slink-work/cache/polished/src/home/menu.asm",
  "line": 94,
  "expect": "ld a, [wMenuDataItems]"
 },
 {
  "path": "F:/slink-work/cache/polished/src/home/map.asm",
  "line": 1624,
  "expect": "ReloadTilesetAndPalettes::"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 4201,
  "expect": "04:6059 StartMenu"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 4245,
  "expect": "04:6267 StartMenu_Quit"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 25,
  "expect": "00:004c GetCGBLayout"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 24,
  "expect": "00:004b GetMemCGBLayout"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 724,
  "expect": "00:24b3 ReloadTilesetAndPalettes"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 954,
  "expect": "00:2ea4 SetDefaultBGPAndOBP"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 907,
  "expect": "00:2cdd ClearPalettes"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 297,
  "expect": "00:0de0 ClearTileMap"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 543,
  "expect": "00:19d1 AutomaticGetMenuBottomCoord"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 789,
  "expect": "00:280b FadeToMenu"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 156,
  "expect": "00:07c3 JoyTextDelay"
 },
 {
  "path": "F:/slink-work/wt/polished/data/polished/polishedcrystal.sym",
  "line": 287,
  "expect": "00:0da8 DelayFrame"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 100,
  "expect": "### 3.3 `panel.asm` / `panel_start.asm`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 61,
  "expect": "Polished dropped the description column"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 111,
  "expect": "`GetSGBLayout`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 112,
  "expect": "`WaitBGMap2`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 114,
  "expect": "`wAttrmap`"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/HOOKS.md",
  "line": 60,
  "expect": "exact text match"
 },
 {
  "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
  "line": 661,
  "expect": "def verify_symbol_scope("
 }
]
```


---

## Coordinator correction (2026-10-04) - section 2.2 is WRONG

`home/menu.asm` `AutomaticGetMenuBottomCoord` does `ld a,[wMenuDataItems] / add a / inc a`: the
bottom edge is `top + 2*items + 1` (each item takes two rows), NOT `top + items + 1`. The OMP read
`add a` as a no-op. Consequences:

* Start menu at `menu_coords 10, 0, 19, 17`: the rows run 0..17, so the box holds at most **8 items**
  (`0 + 2*8 + 1 = 17`). `SetUpMenuItems` can already produce 8 (Pokedex, Pokemon, Pack, Pokegear,
  Status, Save, Option, Exit; Quit replaces Save only in a bug contest).
* A 9th (or the "tenth") SLink item gives bottom 19 and **does not fit**; the box overflows the
  18-row screen. The "no box edit and no scrollbar change" conclusion is retracted.
* The panel therefore needs an item **swap** (take over a dead or conditional id, as on Radical Red
  and vanilla Crystal), or a box/scroll change that is NOT yet designed. The table has 9 rows but only
  8 are ever live at once (Quit and Save are exclusive), so taking over the `STARTMENUITEM_QUIT`
  slot is an option only when it is not a bug contest; that conflict is UNRESOLVED.
* The `AutomaticGetMenuBottomCoord` CLAIMS row still verifies (the quote exists); only the
  conclusion drawn from it is wrong.
