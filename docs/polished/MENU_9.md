# MENU-9 — evaluating a ninth Start-menu item

**Design/evaluation doc only. It recommends; it does not decide.** Owner ruling: *"Evaluate enlarging
the Start box to 9 items."*

Sources: `F:/slink-work/cache/polished/src` (polishedcrystal v3.2.3) and the pinned
`F:/slink-work/wt/polished/data/polished/polishedcrystal.sym`. Every address below was read from the
sym; nothing is guessed. **UNVERIFIED** marks anything I did not read.

---

## 0. The one fact that settles most of the card

`wTilemap` is at **`00:C1A0`** and the sym places **`wTilemapEnd` and `wAttrmap` at the same address,
`00:C308`** — exactly `0xC1A0 + 360`. 360 = 20 columns × 18 rows. So the tilemap is **18 rows tall and
the attribute map begins the instant row 17 ends.**

| tilemap row | first byte |
|---|---|
| 17 (last valid) | `0xC1A0 + 340 = 0xC2F4` |
| **18** | **`0xC308` — the first byte of `wAttrmap`** |
| **19** | **`0xC31C` — 20 bytes into `wAttrmap`** |

**Therefore a ninth item (bottom 19) does not fall off the screen and is not silently clipped: it
writes over the background attribute map.** The `wAttrmap` block runs `00:C308`-`00:C470`
(`wAttrmapEnd`), so rows 18–19 land inside a live, 360-byte structure. Answer to (1):
**corrupting.**

Corrupting attributes is worse than clipping: the menu box border and the whole BG attribute plane
go wrong in ways that do not look like "the last row is cut off", so the failure would be
misattributed.

## 1. What writes those rows

`home/menu.asm:105-112`, the per-item placement loop:

```
	rst PlaceString
	inc de
	ld bc, 2 * SCREEN_WIDTH
	add hl, bc          ; step down TWO rows per item
	pop bc
	dec b
	jr nz, .loop
```

That `2 * SCREEN_WIDTH` stride is the same pitch `AutomaticGetMenuBottomCoord` uses
(`home/menu.asm:495`: `ld bc, 2 * SCREEN_WIDTH + 2` — the `+2` being the two rows the pitch implies,
and `menu.asm:454`'s `add a` / `inc a` producing the `+1` border row).

So item *n*'s first text row is at `wTilemap + (top + 2n) * 20 + left`. With `top = 0`, item 8 (the
ninth) lands at row 16 — visible — and its **second** row at row 17 — visible. **The ninth item's
text itself fits inside 18 rows.** The overflow is the **box border**, drawn at
`wMenuBorderBottomCoord`, not the item's glyphs. That materially narrows what a fix must address.

Related sym facts: `wMenuBorderBottomCoord` **`00:CE5F`**, `wMenuDataItems` **`00:CE6D`**,
`wMenuItemsList` **`01:D03E`**.

## 2. Cursor / item-row math, and whether a scrollable window already exists

* Two rows per item is baked into the placement loop (§1) and into `AutomaticGetMenuBottomCoord`.
  The cursor moves by **item**, not by row, so a ninth entry does not break the cursor arithmetic
  on its own — **UNVERIFIED**: I did not trace `wMenuCursor`/the start menu's cursor buffer, and
  `wMenuCursor` did not appear under that exact name in the sym.
* `home/scrolling_menu.asm` exists and is where Polished puts its scrolling menus, but **I did not
  establish that it exposes a reusable "N visible of M" window** — my grep for its exports returned
  nothing. **UNVERIFIED**, and it is the load-bearing unknown for option R below.
* `wMenuItemsList` is `ds 16` (established in PANEL_SLOT), so a ninth id fits in the list. The
  binding constraint is the *box*, not the list.

## 3. Options, ranked by risk and by how much shared code they touch

`AutomaticGetMenuBottomCoord` is **shared by every menu in the game**. That is the dominant cost
term for any option that changes the pitch.

| # | Option | Risk | Shared code touched |
|---|---|---|---|
| **B1** | **Keep 8 rows; scroll the 9th entry** — reuse a scrolling window if one exists | **Lowest** if the primitive exists; **unknown** until §2 is traced | none (`start_menu.asm` only) |
| **A** | **Substitute a gated row** (Pokédex `:218` / Pokégear `:242`) when the list would reach 8 — the PANEL_SLOT Option A | Low; removes a feature in the full state | none |
| **C** | **Clamp the border to row 17** — keep 9 items, draw the box bottom at 17 and let the 9th item's lower half sit on the border row | **Medium**: a cosmetic clipping bug that is easy to misread; no corruption | one branch in `start_menu.asm`, **not** the shared routine |
| **D** | **Shrink the pitch to `SCREEN_WIDTH`** (1 row per item) | **High** | `home/menu.asm:111-112` **and** `:495` — changes **every** menu in the game |
| **X** | Do nothing to the box; let bottom 19 write `wAttrmap` | **Unacceptable** | — (§0) |

**Ranking: B1, then A, then C. Reject D; X is not an option.**

D is the tempting one — it makes the arithmetic fit — and it is the one to refuse: it edits a routine
every menu calls, to solve one menu's problem.

## 4. Byte-level change set for the best option (HYPOTHESIS)

For **B1**, if a scrolling window exists, the change set would be confined to
`engine/menus/start_menu.asm` and a new `SlinkStartMenuEntry` row in the overlay's
`panel_start.asm`:
1. the `const STARTMENUITEM_SLINK ; 9` declaration (already verified to match verbatim at
   `start_menu.asm:11` in PANEL_SLOT);
2. a **two-word** item row `dw SlinkStartMenuEntry, SlinkMenuString` (Polished has no description
   column);
3. an append in `.SetUpMenuItems` under whatever condition B1 needs.

**No shared ROM byte changes are hypothesised**, which is B1's main appeal. If B1 turns out not to
exist, C's change set is: one conditional clamp of `wMenuBorderBottomCoord` (`00:CE5F`) in the start
menu's own code — still no shared-routine edit.

**This section is a hypothesis and is deliberately not byte-level.** A same-size ROM patch needs the
*exact* call sites and operand bytes inside `start_menu.asm`; I did not disassemble them, and
guessing would be worse than leaving it open. **UNVERIFIED pending a ROM-byte read.**

## 5. The single live measurement that decides it

**Answer B2 first, because it is a five-minute source read and it gates everything else:** does
`home/scrolling_menu.asm` expose a reusable "show N of M entries" window? If yes → B1, done, no
shared code touched.

If the answer is no, the deciding measurement is a **cartridge** one: add a ninth entry, let the
menu open, and read `wTilemap`/`wAttrmap` around `$C308`. If the 20 bytes at `$C308`-`$C31B` carry
menu-border tile ids after opening, §0 is confirmed corrupting and C is the floor. If they still
carry the previous background attributes, the border is already clamped somewhere I have not read,
and the "overflow" is cosmetic only.

Read the sym before trusting §0 — the coordinator has said they will re-derive the memory layout
independently, and that is the right call, because the whole card rests on
`wTilemapEnd == wAttrmap == 0xC308`.

## 6. UNVERIFIED inventory

| item | how to settle |
|---|---|
| whether `scrolling_menu.asm` offers a reusable N-of-M window | read its entry points and the Start menu's consumer set |
| `wMenuCursor`'s actual name and item-step behaviour | grep the sym; I did not find it under that name |
| that the overflow is the **border** and not item glyphs | follows arithmetically from `2 * SCREEN_WIDTH` (§1) and matches "item 8 sits on rows 16/17", but I did not run it |
| the byte-level call sites for C | disassemble `start_menu.asm` around the menu draw; deliberately not guessed |
| whether anything else writes `wAttrmap` between a menu open and its redraw | read the sprite/BG update path; not traced |

---

## Coordinator correction (2026-10-04) to F-2 and the ranking

The sym facts hold (`wTilemap 00:C1A0`, `wTilemapEnd == wAttrmap 00:C308`, so rows 18-19 land inside the
attribute map). **F-2 is WRONG about where the ninth item's glyphs go.** `RunMenuItemPrintingFunction`
starts at the box origin plus `2 * SCREEN_WIDTH + 2` (`home/menu.asm:494-495`, two rows down and two columns
in) and advances `2 * SCREEN_WIDTH` per item, so item n (0-based) is printed on row `top + 2 + 2n`. With
top = 0 the eighth item is on row 16 and the **ninth item's text is on row 18 - inside `wAttrmap` - and its
border on row 19**. Both overflow, not just the border.

Consequences: Option C (clamp the border) does NOT fix it, because the text would still be written past the
tilemap. The remaining safe shapes are a **scrolling window** (the engine has one: `ScrollingMenu` /
`InitScrollingMenu` in `home/scrolling_menu.asm:1,34`, used by the elevator, Kurt and item lists, but the Start
menu is a plain `StartMenu` table menu, so reusing it is a rewrite of the Start menu's draw/input path) or
**substituting a gated row** (PANEL_SLOT Option A). Option D (one row per item) stays rejected: it edits the
shared `home/menu.asm` routines every menu calls. The owner asked to evaluate enlarging; the evaluation says a
true 9-row box is not viable on the 18-row screen without a scroll window or a compact pitch.
