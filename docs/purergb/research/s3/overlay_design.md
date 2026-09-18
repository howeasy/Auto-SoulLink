# pureRGB SOURCE OVERLAY design (worker s3)

Time-boxed (~20 min). Where I ran out of budget I say so explicitly rather than guessing
silently. All sizes in section 1 are MEASURED (relinked the vanilla `slink.o`+`trade.o`
objects from `W/patch/gen1/build/` with `rgblink -m`, scratch output at
`…/scratchpad/relink/slink.map`, RGBDS 1.0.1 from `E:\Google Drive\SLink\.cache\build-tools\rgbds-v1.0.1`).
Nothing under `E:\Google Drive\SLink` or the pureRGB checkout was modified.

`P/` = pureRGB checkout root, `W/` = `E:\Google Drive\SLink\.claude\worktrees\gen1-master-release-plan-6b4279`.

---

## 0. Two load-bearing facts that change the vanilla design

1. **The vanilla ROM0 "RST bridge" trick cannot port.** The vanilla patch places
   `SlinkDelayFrameBridge` at `ROM0[$0001]`, one byte into the RST $00 vector, on the
   assumption that RST $00 is unused padding (`trade_service.asm:31-33`). In pureRGB it is
   not: `BUILD/pokered.map` line 1145's ROM0 section list shows
   `SECTION: $0000-$0007 ["rst0"] $0000 = _Bankswitch`, and `RST $18` (where
   `DelayFrames` lives, `pokered.sym:11 → 00:0018 DelayFrames`) is also a fully-occupied
   8-byte slot (`$0018-$001f ["rst18"], $0018=DelayFrames, $001d=TMCharText`). Writing a
   bridge at `$0001` or intercepting `DelayFrame`'s tail in pureRGB would corrupt a live
   RST handler. This is *why* the task already specifies replacing it with an explicit
   `call SlinkForeground` at `OverworldLoop` (`P/home/overworld.asm:28-29`) — confirmed
   correct, not just a nicety.
2. **The mailbox must move 8 bytes up and shrink from 30 to 22 free bytes.** pureRGB's
   `Current Box Data` WRAMX section ends later than vanilla's:
   `P/ram/wram.asm:2792 wBoxDataEnd::` assembles to `$DEEA`
   (`BUILD/pokered.sym:28571-28572 → 01:deea wBoxDataEnd / wBoxMonNicksEnd`), and
   `SECTION "Stack", WRAMX` starts at `P/ram/wram.asm:2796` → `$DF00`. So the free window
   is `$DEEA-$DEFF` = 22 bytes (matches the task's given figure), not vanilla's
   `$DEE2-$DEFF` = 30. `SLINK_MAILBOX` must be redefined `EQU $DEEA` (was `$DEE2` in
   `W/patch/gen1/src/slink.asm:38`).

---

## 1. SECTION PLAN

### 1a. ROMX bank $3F (measured, relinked vanilla objects)

`layout.link` (`P/layout.link:185-229`) lists ROMX banks only up to `$3D` ("newCode3");
`$3E`/`$3F` have **no entries at all**, consistent with the task's "entirely free." A new
`ROMX $3F` block must be **added** to `layout.link` (it does not exist today).

| Section (vanilla name, reused) | Measured size | Vanilla fixed addr (irrelevant to overlay — see note) |
|---|---|---|
| `SLink Hook` (VBlank body: beacon+counter+SFX-drain+chained `farcall TrackPlayTime`) | **51 bytes** ($4000-$4032) | was pinned `ROMX[$4000]` |
| `SLink Panel` (`SlinkPanel`+`SlinkWaitForButton`+`SlinkWaitForStage`+`SlinkDrawFallback`+2 strings) | **197 bytes** ($4100-$41c4) | was pinned `ROMX[$4100]` |
| `SLink foreground trade service` (`SlinkTradeService`) | **294 bytes** ($4500-$4625) | was pinned `ROMX[$4500]` |
| `SLink Native Trade` (`SlinkTradeApply` + 191-byte species table) | **653 bytes** ($4800-$4a8c) | was pinned `ROMX[$4800]` |
| `SLink trade receptionist` (`SlinkReceptionist`) | **1252 bytes** ($4c00-$50e3) | was pinned `ROMX[$4c00]` |
| `SLink trade UI helpers` (+256-byte name table) | **414 bytes** ($5400-$559d) | was pinned `ROMX[$5400]` |
| `SLink partner trade prompt` | **423 bytes** ($5800-$59a6) | was pinned `ROMX[$5800]` |
| **Total bank-$3F code** | **3284 bytes** | bank is 16384 bytes, entirely free |

**Note on the vanilla fixed addresses**: those `ROMX[$4000]`/`[$4100]`/… pins exist only
because the vanilla delivery is a *binary UPS patch* that must verify-then-write fixed
offsets (`W/patch/gen1/tools/build.py` "verify-then-write" + `manifest.py MENU_PATCHES`).
The source overlay is a **normal linked build**, not a binary overwrite, so none of that
spacing is needed — the 7 sections can be plain `SECTION "…", ROMX, BANK[$3F]` (no `[$addr]`)
and rgblink will pack them back-to-back. 3284 bytes into a 16384-byte free bank is not a
placement problem either way. **Recommendation: drop the fixed addresses in the overlay
source** (simpler diff, and it stops the linker map from having to explain 3.3 KB of
manifest-driven gaps that no longer serve a purpose).

`layout.link` diff (new block, e.g. inserted after the `ROMX $3D` block, `P/layout.link:228-229`):
```diff
 ROMX $3D
 	"newCode3"
+ROMX $3F
+	"SLink Hook"
+	"SLink Panel"
+	"SLink foreground trade service"
+	"SLink Native Trade"
+	"SLink trade receptionist"
+	"SLink trade UI helpers"
+	"SLink partner trade prompt"
 WRAM0
```
(Bank `$3E` is left untouched/free; nothing here needs it. If a future feature needs more
than one bank, `$3E` is next in line.)

### 1b. ROM0 additions

ROM0 has 1382 free bytes at `$3A9A-$3FFF` (confirmed: `BUILD/pokered.map` line-1 SUMMARY
`ROM0: 15002 bytes used / 1382 free`, and the same map's `EMPTY: $3a9a-$3fff ($0566 bytes)`
— 0x566 = 1382). Two additions, both trivial:

1. **`SlinkStartMenuEntry`** (ROM0, called from the new `StartMenuJumpTable` row):
   ```
   SlinkStartMenuEntry:
       farcall SlinkPanel        ; ld b,BANK(SlinkPanel)(2) / ld hl,SlinkPanel(3) / call Bankswitch(3) = 8 bytes
       jp RedisplayStartMenu     ; 3 bytes
   ```
   **11 bytes.**
2. **`SlinkForeground` call site** at `OverworldLoop` (see Hook Edit #4 below): one
   `farcall SlinkForeground` = **8 bytes**, inserted directly into `Home` (no wrapper
   label needed — `farcall` is inline).

**ROM0 total: 19 bytes**, against 1382 free — trivially fits (list these two ROM0 chunks
in `layout.link` "after Home" per the task's instruction, i.e. `P/layout.link:35 "Home"`
gets no new line — a `farcall` is inlined into `Home` itself for #2, and
`SlinkStartMenuEntry` is a new tiny standalone section placed right after it):
```diff
 	org $150
 	"Home"
+	"SLink Start Menu Entry"
 ROMX $1
```

### 1c. WRAMX bank 1 (mailbox)

Free window: `$DEEA-$DEFF`, 22 bytes (§0.2). ABI-3 mailbox is 12 bytes (`+0..3` 'SLNK',
`+4` ABI, `+5..6` frame ctr, `+7` SFX req, `+8` caps, `+9` panel state, `+10` page,
`+11` pages — `W/patch/gen1/src/slink.asm:41-58`). **12 of 22 bytes used, 10 spare.** The
16-byte lease needs **no new WRAM** — it already aliases the existing 200-byte
`wSerialPartyMonsPatchList::` (`P/ram/wram.asm:201`, confirmed exported `::`,
`BUILD/pokered.sym → 00:c508`), exactly as the vanilla design does
(`trade_service.asm:6 DEF SlinkOverlay EQU wSerialPartyMonsPatchList`). No conflict: 12 +
16-elsewhere = fits with room to spare, and the two never overlap in address space.

`layout.link` diff (`P/layout.link:238-244`, add after "Current Box Data", before the
`org $df00` / "Stack" line, per the task's instruction):
```diff
 WRAMX $1
 	org $d000
 	"WRAM 1"
 	"Party Data"
 	"Main Data"
 	"Current Box Data"
+	"SLink Mailbox"
 	org $df00
 	"Stack"
```

---

## 2. HOOK EDITS

### 2.1 `P/home/vblank.asm:73`

Current (confirmed by read, `vblank.asm:73`):
```
	farcall TrackPlayTime ; keep track of time played
```
Diff:
```diff
-	farcall TrackPlayTime ; keep track of time played
+	farcall SlinkHook ; SlinkHook chains to TrackPlayTime once, see slink.asm
```
`SlinkHook` (bank $3F) must, in order: **save `rWBK`/`rSVBK` ($FF70) → select WRAM bank 1
→ write the 12-byte mailbox at `$DEEA` → restore the saved `rWBK` value → `farcall
TrackPlayTime`(nested, safe — `Bankswitch` is reentrant per the vanilla design note,
`slink.asm:21-25`) → `ret`.** The save/select/restore is new versus the vanilla body
(`slink.asm:108-147`) because vanilla Red/Blue are DMG-only and have no `$FF70`; pureRGB
is GBC-aware (`P/home/overworld.asm:32 callfar GBCSetCPU2xSpeed`, `layout.link:246-248`
`WRAMX $2 "GBC WRAM"`), so an interrupt landing while game code has `rWBK` pointed at
WRAM bank 2 must not write the mailbox into bank-2-mapped `$DEEA` — it has to force bank 1
first. Net size add to the 51-byte `SlinkHook` body: `ldh a,[rWBK]`(2) + `push af`(1) +
`ld a,1`(2) + `ldh [rWBK],a`(2) + `pop af`(1) + `ldh [rWBK],a`(2) = **10 bytes**, all inside
bank $3F (irrelevant to the ROM0 budget).

### 2.2 `P/home/map_objects.asm:194-195`

Current:
```
TextScript_CableClubNPC::
	jpfar CableClubNPC
```
Diff:
```diff
 TextScript_CableClubNPC::
-	jpfar CableClubNPC
+	jpfar SlinkReceptionist
```
And inside the ported receptionist's `.original` fallback path (`W/patch/gen1/src/trade_receptionist.asm:126-138`), **delete** the extra wait:
```diff
 .original:
     add sp, 4
     pop hl
     pop de
     pop bc
     pop af
     nativecall CableClubNPC
-    ; The patched dispatch continues at HoldTextDisplayOpen. Reproduce the
-    ; original AfterDisplayingTextID wait on the ordinary Cable Club path.
-    ld a, [wEnteringCableClub]
-    and a
-    call z, WaitForTextScrollButtonPress
     ret
```
Why this is correct and not just simpler: `jpfar` (a `jp`, not `call`) into
`TextScript_CableClubNPC` is reached via the generic-script dispatcher
(`P/home/text_script.asm:80-89`), which pushes `AfterDisplayingTextID` as the return
address *before* jumping in. `SlinkReceptionist.original` reaches native `CableClubNPC`
through `nativecall` (a `call`, not `jp` — `native_trade.asm:8-16`), so when
`CableClubNPC` (or the vanilla `.original` fallthrough) eventually `ret`s, control lands
back on that same pushed return address: `AfterDisplayingTextID` →
`AfterDisplayingTextID2` (`P/home/text_script.asm:94-101`), which **already** does
```
ld a, [wEnteringCableClub]
and a
call z, WaitForTextScrollButtonPress
```
So the vanilla patch's own copy of that check-and-wait, if ported unmodified, would run
it a second time — wasted, and worse, `wEnteringCableClub` state could have changed
between the two checks. Deleting it is the root-cause fix (one fewer duplicate site),
not a symptom patch.

### 2.3 START-menu row

`StartMenuJumpTable` (`P/home/start_menu.asm:41-48`) is 7 `dw` entries (Pokedex, Pokemon,
Item, TrainerInfo, SaveReset, Option, `CloseTextDisplay`=Exit). Diff:
```diff
 StartMenuJumpTable:
 	dw StartMenu_Pokedex
 	dw StartMenu_Pokemon
 	dw StartMenu_Item
 	dw StartMenu_TrainerInfo
 	dw StartMenu_SaveReset
 	dw StartMenu_Option
+	dw SlinkStartMenuEntry
 	dw CloseTextDisplay
```
This appends SLINK *before* Exit (so Exit is always last, matching the vanilla design's
"every existing index keeps its position" — README.md:16). Consequences, all in
`P/engine/menus/draw_start_menu.asm`:

* **Row/box height** (`draw_start_menu.asm:5-9`, `hlcoord 10,0 / lb bc,14,8` with-dex,
  `ld b,12` without-dex): each menu row costs one 8-height unit in `b`; adding a row means
  `14→16` (with dex) and the without-dex path's `ld b,12` → `14`.
* **Text tables** (`draw_start_menu.asm:76-89`, `StartMenuWithPokedexText` /
  `StartMenuWithoutPokedexText`, terminated `next "EXIT@"`): insert `next "SLINK"` as the
  new second-to-last row before the `next "EXIT@"` line in both tables.
* **`wMaxMenuItem`** (`draw_start_menu.asm:26,30,34`, currently `ld a,5`/`inc a`→6 with
  dex): becomes `ld a,6`/`inc a`→7.
* **`CheckSavedStartMenuIndex`** (`draw_start_menu.asm:58-74`): bounds-agnostic (just
  restores a saved index into `wCurrentMenuItem`/`wLastMenuItem`) — **unaffected**, no
  edit needed, confirmed by reading the full routine.
* **`GetStartMenuPrompt`** (`P/engine/menus/custom_list_menu.asm:222-238`, not
  `custom_list_menu.asm` literally but same file per the task's path — confirmed at
  those exact lines): `decoord 12,15` / `decoord 12,13` locate the prompt row relative to
  the Pokedex-or-not row count. Adding one row before Exit means both must shift down by
  one row (`y+2` in this engine's coordinate macros, i.e. `12,17` / `12,15`), matching the
  task's stated `y+2` rule.
* **SELECT dispatch** (`start_menu.asm:27-38`, `.selectPressed: cp 4`/`cp 2`) compares
  `wCurrentMenuItem` against the fixed indices for SAVE(4) and ITEM(2). Since SLINK is
  inserted *after* SaveReset(4)/Option(5) and *before* Exit, indices 0-5 (Pokedex..Option)
  are **unchanged** — confirmed unaffected, as the task expected.

*Time-box note*: I did not derive the exact final byte values for the height/`decoord`
constants against pureRGB's real coordinate macros (`hlcoord`/`decoord`/`bccoord` — I did
not open `macros/coords.asm` in this session). The row/offset arithmetic above is correct
in direction and magnitude (+1 row, +2 in the y half of the coord pair) but should be
confirmed against a scratch assemble before treating the numbers as final.

### 2.4 Overworld foreground hook (replaces the RST-bridge trick)

Current (`P/home/overworld.asm:28-29`, confirmed):
```
OverworldLoop::
	rst _DelayFrame
```
Diff:
```diff
 OverworldLoop::
 	rst _DelayFrame
+	farcall SlinkForeground
 OverworldLoopLessDelay::
```
`SlinkForeground` (bank $3F, new — thin wrapper, not the vanilla `SlinkDelayFrameBridge`)
keeps exactly the payload predicate the vanilla bridge checked
(`trade_service.asm:51-56`: `ld a,[SlinkOverlay+10] / dec a / jr nz,.done` i.e. lease
byte +10 must equal 1) and, if true, `call`s the existing `SlinkTradeService` bank-$3F
routine unchanged:
```
SlinkForeground:
    ld a, [SlinkOverlay + 10]
    dec a
    ret nz
    jp SlinkTradeService
```
No return-address/stack inspection is needed anymore (that machinery,
`trade_service.asm:41-50`, existed only to distinguish "DelayFrame called from
OverworldLoop" from every other DelayFrame call site — irrelevant once the call is placed
directly at the one call site that matters). **Size impact on Home: 8 bytes** (the
`farcall` macro expansion), inside the 1382-byte ROM0 budget already counted in §1b.

---

## 3. SYMBOL EXPORT LIST

Checked directly against `BUILD/pokered.sym` (bank) and the declaring pureRGB source line
(`::` vs `:`). This covers every symbol in `trade_defs.inc:12-73` that I could verify in
the time available — see the note at the end for the ones I did not individually check.

| pureRGB label | `::`/`:` in P/ | pureRGB bank | Vanilla assumption still true? |
|---|---|---|---|
| `Bankswitch` | `::` (`home/bankswitch.asm:15`) | `00` | yes |
| `CopyData` | (not re-checked; `00:00ae` in sym) | `00` | yes |
| `RemovePokemon` | `::` (`home/move_mon.asm:20`) | `00` | yes |
| `AddEnemyMonToPlayerParty` | `::` (`home/move_mon.asm:58`) | `00` | yes |
| `TryEvolvingMon` | **`:` file-local** (`engine/pokemon/evos_moves.asm:2`) | **`2C`**, not `0E` | **NO — bank changed AND needs `::` added.** This is a required source edit: `TryEvolvingMon:` → `TryEvolvingMon::` in `evos_moves.asm:2`, plus every `TryEvolvingMonBank` constant in the ported overlay must read `$2C`. |
| `SavePartyAndDexData` | `::` (`engine/menus/save.asm:251`) | `1C` | yes — still called via `callfar`/`nativecall`, same bank as vanilla |
| `DelayFrame` | `::` (`home/vblank.asm:89`) | `00` | yes |
| `DelayFrames` | (RST vector, not a normal label) | `00` (`$0018`, `rst $18`) | yes — confirmed literally `rst $18` (`BUILD/pokered.map`: `SECTION $0018-$001f ["rst18"], $0018=DelayFrames`) |
| `CableClubNPC` | `::` (`engine/link/cable_club_npc.asm:1`) | `01` | yes (only the *dispatch site* changes, §2.2 — the routine itself is untouched) |
| `WaitForTextScrollButtonPress` | `::` (`home/joypad2.asm:56`) | `00` | yes |
| `InGameTrade_RestoreScreen` | `::` (`engine/events/in_game_trades.asm:194`) | `1C` | yes |
| `InternalClockTradeAnim` | `::` (`engine/movie/trade.asm:1`) | `10` | yes |
| `RedrawMapView` | `::` (`engine/overworld/update_map.asm:194`) | `03` | yes |
| `HandleMenuInput` | `::` (`home/window.asm:1`) | `00` | yes |
| `YesNoChoice` | `::` (`home/yes_no.asm:2`) | `00` | yes |
| `GBPalWhiteOut` / `GBPalNormal` | `::` (`home/palettes.asm:35` / `:28`) | `00` | yes |
| `ReloadMapData` | `::` (`home/reload_tiles.asm:2`) | `00` | yes |
| `wSerialPartyMonsPatchList` | `::` (`ram/wram.asm:201`, `ds 200`) | `00` (`$c508`) | yes — big enough for the 16-byte lease with room to spare (200 bytes total) |
| `Music_Evolution` | `::` (`audio/headers/musicheaders1.asm:85`) | `02` | yes — matches `SLINK_TRADE_MUSIC_BANK EQU $02` in vanilla `trade_defs.inc:6`; **must still be asserted as `BANK(Music_Evolution)`**, not hard-coded `$02`, since pureRGB could in principle reorder audio banks — use the symbolic `BANK()` operator in the overlay, not the vanilla numeric constant. |
| All WRAM/HRAM data symbols (`wIsInBattle`, `wLinkState`, `wPartyCount`, `wPartySpecies`, `wTradingWhichPlayerMon`, `wEnemyPartyCount/Species/Mons`, `wOptions`, `wStatusFlags5`, `wFontLoaded`, `wForceEvolution`, `wUpdateSpritesEnabled`, `wPartyMonOT`, `wTraded*`, `wWhichPokemon`, `wRemoveMonFromBox`, `wCurPartySpecies`, `wLoadedMon`, `wAudioFadeOutControl/SavedROMBank`, `wNewSoundID`, `wEnemyMonNicks`, `wPokedexOwned`, `wPlayerName/ID`, `wCurMap`, `wTileMap`, all `wMenu*`/`wTopMenuItem*`/`wCurrentMenuItem` menu state, `wPartyMonNicks`, `wPartyMenuAnimMonEnabled`, `hAutoBGTransferEnabled`, `hTileAnimations`, `hWY`, `hFrameCounter`, `hJoyHeld`, `hJoyPressed`, `hUILayoutFlags`, `hSerialConnectionStatus`, `hLoadedROMBank`) | resolved by name lookup against `BUILD/pokered.sym` (all present, all with the same *names* as vanilla `trade_defs.inc:186-248`) | see table below | assumed yes — **not individually checked for `::` vs `:`** in this pass (data symbols in `ram/wram.asm` are declared inline in one `SECTION` block and are effectively all visible within `INCLUDE`d/main-linked sources regardless of `::`, but a proper check should `grep -n "^wIsInBattle" P/ram/wram.asm` etc. before final implementation) |

Bank deltas worth flagging even though addresses matched (WRAM symbols report a *bank*
in `pokered.sym` because pureRGB is GBC-aware and `$D000-$DFFF` is a switchable WRAMX
window — vanilla Red/Blue has no such switching, the whole area is flat):
`wIsInBattle`(`01:d057`), `wLinkState`(`01:d133`), `wPartyCount`/`wPartySpecies`/`wPartyMons`
(`01:`), `wEnemyPartyCount/Species/Mons`(`01:`), `wOptions`/`wStatusFlags5`(`01:`),
`wPartyMonOT`(`01:d27b`), `wEnemyMonOT`(`01:d9b4`), `wPartyMonNicks`/`wPartyMenuAnimMonEnabled`
(`01:`), `wTextBoxID`/`wTwoOptionMenuID`(`01:`), `wEnemyMonNicks`/`wPokedexOwned`/`wPlayerName`/
`wPlayerID`/`wCurMap`(`01:`) are all **WRAM bank 1** (the normal, always-mapped-by-default
bank; distinct from `layout.link:246-248`'s WRAMX bank 2 "GBC WRAM" used for CGB-only
extras). As long as nothing in the overlay's call path switches `rWBK` away from bank 1
without restoring it before touching these, they behave exactly like vanilla's flat WRAM
— but this is the *same* class of hazard as the VBlank mailbox write (§2.1) and belongs on
the risk list (§6): any bank-1 read/write inside `SlinkTradeApply`/`SlinkReceptionist`
that runs while something else has switched to WRAM bank 2 would read/write the wrong
data. Recommend the overlay's outermost entry points (`SlinkForeground`,
`SlinkStartMenuEntry`→`SlinkPanel`, `SlinkReceptionist`) each save/force/restore `rWBK`
to 1 on entry/exit, the same pattern as §2.1's VBlank fix, rather than trusting ambient
state.

**Labels needing a source edit for export**: only `TryEvolvingMon` (`evos_moves.asm:2`,
`:`→`::`) was found among those checked. **No label needs `INCLUDE`-into-main.asm
treatment** — every symbol checked is already `::`-exported and bank-resolvable from a
separate linked object; the overlay can be its own object file(s) linked alongside
`main.o`, it does not need to become part of `main.asm`'s own `INCLUDE` chain. (The
7 bank-$3F sections and the 2 ROM0 additions are new files; simplest is one new
`slink_overlay.asm` `INCLUDE`d from `main.asm` once, mirroring how `P/main.asm` already
assembles `home.asm`/`engine`/etc. — I did not have time to open `P/main.asm` to confirm
its exact `INCLUDE` list and pick the insertion point; that's a 2-minute follow-up before
implementation.)

---

## 4. TEXT/CHARMAP

pureRGB preincludes its own charmap and text macros globally (unlike the vanilla
patch, which scopes a private `PUSHC`/`NEWCHARMAP` block, `slink.asm:357-368`, and
copies `pret_text.inc` in as a **file-local, unexported** set of macros/charmap
specifically so it doesn't collide with anything — `trade_defs.inc`/`pret_text.inc`
header comments call this out explicitly). Concretely, per source file:

* **`slink.asm` beacon bytes** (`ld a,'S'` etc., `slink.asm:111-118`) — these are raw
  ASCII character *literals*, not charmap-translated strings (`PUSHC`/`NEWCHARMAP` is
  scoped only around the `SlinkDrawFallback` strings below them). They assemble
  unchanged in pureRGB: `'S'` is still `$53` regardless of any preincluded charmap,
  because RGBDS character-literal (`'x'`) tokens use the *default* internal encoding
  unless a charmap remaps single-character tokens specifically — and pureRGB's charmap
  (`P/constants/charmap.asm`, mirrors `pret/constants/charmap.asm:94-119` for `A-Z`) remaps
  `"A".."Z"` as multi-char *strings*, not the `'A'` char-literal form used here. **No
  change needed.** Same for the `'SLT1'`/`$53,$4c,$54,$31` magic bytes in
  `trade_service.asm:174-185` and `trade_receptionist.asm:241` (`.queryHeader`) — these
  are already raw `db $53,$4c,...`/`cp $53` numeric byte comparisons, immune to any
  charmap by construction.
* **`SlinkDrawFallback` "SOUL LINK@"/"NO CLIENT@"** (`slink.asm:357-368`) — currently
  wrapped in a private `PUSHC NEWCHARMAP slinktext … POPC` specifically because vanilla
  Red/Blue's `rgbasm` has *no* charmap preincluded at all, so plain ASCII would break
  (documented in the file's own comment, `slink.asm:345-353`, "first panel build
  assembled `53 4F 55 4C…` and hung the game"). **In the pureRGB overlay this
  private charmap must be deleted** — pureRGB already preincludes the real Gen-1 charmap
  globally, so `db "SOUL LINK@"` should be written as an ordinary `text`/`db` string using
  pureRGB's own charmap (`P/constants/charmap.asm`, `A`=$80 etc. — same values the
  vanilla private charmap reinvented). Using pureRGB's real charmap is *better*, not just
  simpler: it gets the `é`, `#`("POKé"), and other special glyphs pureRGB's font supports,
  which the vanilla project's minimal 26-letter charmap did not.
* **`.title`, `.noData`, `.slinkText`, `.cableText`, `.cancelText`, `.welcomeText`,
  `.partyText`, `.noLinkedText`, `.offerSentText`, `.offerRejectedText`,
  `.offerUnknownText`, `.invalidPartyText`, `.selectionChangedText`** in
  `trade_receptionist.asm` and the `text`/`line`/`prompt` macro-built messages in
  `trade_prompt.asm` (`.question`, using `text_ram`) — these already use the standard
  `text`/`line`/`prompt`/`text_ram` macros from the *vanilla* `pret_text.inc` (copied
  verbatim from pret 405b624, `pret_text.inc:1-2` header comment). pureRGB's own
  `P/macros/scripts/text.asm` is very likely near-identical (Gen 1 text-command layout is
  a pret-family constant pureRGB does not renumber for `TX_START`..`TX_FAR`/`TX_END`,
  those are `$00`-`$17`/`$50` in both, per `pret_text.inc:488-632` matching pret's own
  numbering) — but the task's own framing says pureRGB **renumbers `$0E-$1B`**, which in
  pret's scheme are the `TX_SOUND_POKEDEX_RATING`..`TX_FAR` range
  (`pret_text.inc:575-624`). **I did not get to open `P/macros/scripts/text.asm` to
  confirm pureRGB's actual renumbering in the time available** — this is the single
  highest-value unresolved item for §4: if pureRGB shifted those IDs, then **every file
  in `W/patch/gen1/src/` must stop `INCLUDE`ing `pret_text.inc` and instead use pureRGB's
  own `text.asm` macros directly** (delete `pret_text.inc` from the overlay's include
  list in `trade.asm:6`; the macro *names* `text`/`line`/`prompt`/`text_ram`/`done` are
  standard pret-family names pureRGB almost certainly keeps, so the source bodies
  probably don't need edits beyond the include swap — but this must be verified against
  pureRGB's actual macro file before build, not assumed).
* **`slink_species_table`/`slink_name_table`** (`trade_defs.inc:9-11,78-80`) are raw
  `db` byte tables, not text — unaffected by any charmap change.

**Summary verdict**: beacon/magic bytes and the two species/name tables assemble
unchanged (numeric, not charmap-dependent). The `SlinkDrawFallback` strings need their
private charmap **deleted** in favor of pureRGB's real one (strict simplification). The
receptionist/prompt dialogue strings need `pret_text.inc` **replaced by pureRGB's own
`P/macros/scripts/text.asm`** — high-confidence direction, but the exact TX-command
renumbering was not independently confirmed this session; flagged as the top follow-up.

---

## 5. BUILD/ARTIFACT

**Recipe** (pinned checkout, not touched this session):
1. Apply the source edits in §2 to a pinned pureRGB checkout at tag `v2.7.6` /
   `7e7a4653` (same commit already checked out at `P/`).
2. Add the 7 new bank-$3F `SECTION`s + the 2 ROM0 additions as one new file (e.g.
   `home/slink_overlay.asm`, `engine/slink_trade.asm` — split however matches pureRGB's
   own `home/`+`engine/` convention) and wire it into `P/main.asm`'s `INCLUDE` list
   (exact insertion point TBD — see §3's follow-up note).
3. `rgbasm`/`rgblink` via `make pokered.gbc pokeblue.gbc pokegreen.gbc` — **RGBDS 1.0.3**
   per the task (not 1.0.1, which was only used here to relink the vanilla objects for
   measurement — pureRGB's own `Makefile`/`rgbdscheck.asm` presumably pins 1.0.3 already;
   I did not check this file this session).
4. Outputs: `pokered.gbc`/`pokeblue.gbc`/`pokegreen.gbc` + `.sym`/`.map` (same artifact
   shape as `BUILD/` already has for the clean build — good, that gives a same-day A/B
   diff).
5. **UPS creation** against the clean pure ROM via `W/patch/tools/make_ups.py`
   (`make_ups.py create <clean.gbc> <overlay.gbc> <dist-name>`), same tool the vanilla
   patch already uses (`README.md:76-77`).

**Acceptance checks**, concretely:
* **Section-placement equality** between clean `BUILD/pokered.map` and the overlay's new
  `.map`: every section name that exists in *both* maps must report the identical
  `bank:address` range. Compare explicitly: `"Home"` (ROM0, must be byte-identical up to
  the new `farcall SlinkForeground`/`SlinkStartMenuEntry` insertion points — anything
  after those points in the same bank is expected to shift and that's fine, but nothing
  *before* the insertion should move), `"rst0"`..`"rst38"` (must be untouched —
  regression check for the RST-corruption risk in §0.1), `"Current Box Data"` and
  `"Stack"` (WRAMX bank 1 — must be byte-identical; if `wBoxDataEnd` moved, the mailbox
  math in §0.2/§1c is stale and the build should fail loudly, not silently place the
  mailbox over live data).
* **Saved-region symbol equality**: `wSerialPartyMonsPatchList` and everything in §3's
  WRAM/HRAM table must resolve to the *same* addresses in both maps (a `diff` of the
  `grep`-filtered symbol lines from clean vs. overlay `.sym`, restricted to the names in
  §3's table, should be empty).
* **Hook anchors the Lua profile must pin** (the exact bytes at each hook site, read from
  the *overlay* build's own `.sym`+ROM dump, not assumed from vanilla numbers):
  - `vblank.asm:73` post-edit: the 8-byte `farcall SlinkHook` opcode bytes at whatever
    ROM0 address `TrackPlayTime`'s farcall currently sits at in `BUILD/pokered.map`
    (need a fresh lookup — the vanilla `$2094` offset is Red-dump-specific and does not
    transfer).
  - `map_objects.asm:194-195` post-edit: the `jpfar SlinkReceptionist` bytes at
    `TextScript_CableClubNPC`'s address.
  - `overworld.asm:28-29` post-edit: the `farcall SlinkForeground` bytes right after
    `rst _DelayFrame` inside `OverworldLoop`.
  - `start_menu.asm:41-48` post-edit: the new `dw SlinkStartMenuEntry` slot's absolute
    address inside `StartMenuJumpTable`.
  A short Lua-side helper (mirroring however the existing SLink Lua profile already pins
  vanilla hook addresses) should read these four anchors straight from the overlay
  build's `.sym`, not hardcode them, since a pureRGB point release could shift banks.

---

## 6. RISKS (source-grounded, not generic)

1. **VBlank re-entrancy / bank-switch hazard (new vs. vanilla, real).** §0.2/§2.1: the
   mailbox write in `SlinkHook` happens inside an interrupt handler that can fire while
   `rWBK` ($FF70) is pointed at WRAM bank 2 (`layout.link:246-248` "GBC WRAM" is real
   pureRGB content, not vanilla's flat WRAM). Every mailbox write must save/force
   bank-1/restore, or it silently corrupts whatever pureRGB feature currently owns bank 2,
   or writes garbage where the mailbox should be. This generalizes: `SlinkForeground`,
   `SlinkReceptionist`, and `SlinkTradeApply` all touch `$D000-$DFFF` symbols
   (`wPartyMons`, `wEnemyMons`, etc., all reported bank `01` in §3) and must make the same
   guarantee on entry, not just the VBlank hook.
2. **Stack depth inside an interrupt.** `SlinkHook` now does a nested `farcall`
   (`call Bankswitch`) plus the new save/restore, from inside VBlank, which itself
   fires on top of whatever the main thread's stack depth already is. The vanilla
   comment (`slink.asm:21-25`) argues `Bankswitch` is safe to nest once; nesting an
   *additional* `rWBK` save through a `push af`/`pop af` pair adds 2 bytes of transient
   stack — negligible on its own, but worth keeping in mind if a future feature adds a
   third level.
3. **`TryEvolvingMon` far-call from bank $3F, now against bank `$2C` not `$0E`.** §3:
   this is a real, confirmed bank change (`P/engine/pokemon/evos_moves.asm:2`, pureRGB
   moved evolution logic to bank `$2C`). Any leftover `$0E` literal anywhere in the ported
   overlay (e.g. if someone copy-pastes `TryEvolvingMonBank EQU $0E` from
   `trade_defs.inc:35` without updating it) calls into unrelated bank-$0E code
   ("Battle Engine 3-7", `layout.link:80-87`) — a wrong-bank far-call, not a crash you'd
   catch from a symbol-not-found error, since `$0E` is a valid bank that just contains the
   wrong thing.
4. **Cable Club reentry via the shared dispatcher.** §2.2's `jpfar` tail-call trick means
   `SlinkReceptionist` inherits `AfterDisplayingTextID`/`AfterDisplayingTextID2`'s
   assumptions about `wDoNotWaitForButtonPressAfterDisplayingText` and
   `wEnteringCableClub` being in the same state they'd be in for an ordinary generic NPC
   script. If `SlinkReceptionist`'s own internal menu loop (`.mainMenu`, `.partyMenu`)
   leaves either flag mutated on an early-exit path (e.g. `.selectedCancel`), the shared
   epilogue's behavior changes for reasons invisible from inside the receptionist code —
   worth an explicit save/restore of both flags around the entire `SlinkReceptionist`
   body, similar to what it already does for `wTopMenuItemY`/menu state
   (`trade_receptionist.asm:16-40`).
5. **GBC 2x-speed timing of the 90/60-frame windows.** `SLINK_STAGE_TIMEOUT=90`
   (`slink.asm:193`) and the receptionist's `d=30`/`ld a,180` timeouts
   (`trade_receptionist.asm:174`, `:476`) are frame counts driven by `DelayFrame`, which
   in turn is gated by VBlank — and pureRGB's `OverworldLoop` explicitly runs
   `callfar GBCSetCPU2xSpeed` (`overworld.asm:32`) for GBC double-speed CPU mode. CPU
   double-speed does **not** change VBlank's 59.7 Hz rate (that's a PPU/LCD timing
   constant, unaffected by CPU speed toggles), so the frame-count timeouts should still
   represent the same wall-clock durations as on vanilla DMG hardware — but this is an
   assumption, not something I verified against pureRGB's actual `GBCSetCPU2xSpeed`
   implementation in this session, and it's cheap to get wrong silently (a timeout that's
   actually 2x too short/long only shows up as an intermittent "client didn't answer in
   time" flake under real network jitter). Worth a dedicated one-line check of
   `GBCSetCPU2xSpeed` before trusting the 90/180/30-frame constants unchanged.
6. **`layout.link`'s `ROMX $3F` block is new, not edited.** Because bank $3F has zero
   existing sections, there's no "insert before/after X" precedent in this file for that
   bank — the ordering of the 7 section names in the new block doesn't have to match any
   existing convention, but *does* need to match whatever order the overlay's own source
   files declare them in (RGBDS requires section names to appear in `layout.link` if
   `layout.link` is used at all for placement — I did not confirm whether pureRGB's build
   actually uses `-l layout.link` vs. some other placement mechanism; that's a
   Makefile-reading follow-up, not assumed here).

---

## What I did not get to (be literal about the gaps)

- Did not open `P/main.asm` to find the exact `INCLUDE` insertion point for the new
  overlay file(s) (§3).
- Did not open `P/macros/scripts/text.asm` or `P/constants/charmap.asm`'s TX-command
  section to confirm the exact `$0E-$1B` renumbering the task states exists (§4) — this
  is the single most load-bearing unresolved fact, since it decides whether
  `pret_text.inc` can be dropped wholesale or needs a translation table.
- Did not verify `::`/`:` status for the ~50 WRAM/HRAM data symbols beyond confirming
  their names and banks resolve in `pokered.sym` (§3's data-symbol row).
- Did not open `P/macros/coords.asm` (or wherever `hlcoord`/`decoord`/`bccoord` live) to
  turn the START-menu row-height/`decoord` arithmetic in §2.3 into exact byte values.
- Did not check `P/Makefile`/`P/rgbdscheck.asm` for the RGBDS version pin or confirm
  `layout.link` is actually consumed via `-l` (§5, §6.6).
- Did not attempt an end-to-end scratch assemble of the *overlay* (only relinked the
  existing vanilla `.o` files to measure sizes, per §1) — the numbers in §1 are exact for
  the vanilla routines as they exist today; the two edits noted inline (§1b's 10-byte
  `SlinkHook` growth, §1c unaffected) are arithmetic add-ons, not re-measured.
