# POKEGEAR-SLOT — putting the SLink entry in the Pokégear, and making it feel vanilla

**Design doc only.** Owner ruling 2026-10-04: *"the SLink entry lives in the POKEGEAR and must FEEL
VANILLA."*

Sources: `F:/slink-work/cache/polished/src` (polishedcrystal v3.2.3) and the pinned
`F:/slink-work/wt/polished/data/polished/polishedcrystal.sym`. Every address is read from the sym;
nothing is guessed. **UNVERIFIED** marks what I did not read.

---

## 0. The headline: a fifth card **fits**, and the reserved flag bit already exists

Two facts make this cheap, and both are in the source rather than inferred:

* `engine/pokegear/pokegear.asm:3-6` defines exactly four cards —
  `POKEGEARCARD_CLOCK ; 0`, `MAP ; 1`, `PHONE ; 2`, `RADIO ; 3` — and `:7`
  `DEF NUM_POKEGEAR_CARDS EQU const_value`.
* `constants/ram_constants.asm:301-304` declares **four** flag bits:
  `POKEGEAR_MAP_CARD_F ; 0`, `POKEGEAR_RADIO_CARD_F ; 1`, `POKEGEAR_PHONE_CARD_F ; 2`,
  **`POKEGEAR_EXPN_CARD_F ; 3`** — and bit 3 has **no card and no icon**. It is a reserved slot.

**No free or conditional slot needs inventing: bit 3 is already allocated and unused.**

## 1. How the Pokégear main menu is built and drawn

### 1.1 Card identities and the icon row

`pokegear.asm:3-7` (cards) and `Pokegear_FinishTilemap` (`:330-356`) draw the icon strip. Each icon
occupies **two columns**, on row 0:

| icon | column | first tile id | drawn at |
|---|---|---|---|
| Pokégear (frame + clock, unconditional) | `0,0` | `$56` | `:352-354` |
| Map | `2,0` | `$50` | `.PlaceMapIcon` `:356-359` |
| Phone | `4,0` | `$54` | `.PlacePhoneIcon` `:362-365` |
| Radio | `6,0` | `$52` | `.PlaceRadioIcon` `:367-370` |

`.PlacePokegearCardIcon` (`:371-380`) writes the top tile pair, then `ld bc, $14 / add hl, bc` (+20 =
one row down) and `add $f` (+15) to place the lower pair — so an icon is **2 tiles wide × 3 rows tall**.

**Column 8, row 0 is free.** The four native icons occupy x = 0, 2, 4, 6 on a 20-column tilemap, and
the cursor's x is `card id × 2` (`AnimatePokegearModeIndicatorArrow`, `:185-191`: `ld a,
[wPokegearCard] / swap a` — the high nibble of the doubled id). **Card 4 lands at x = 8, inside the
same row, with no shared-code change.**

### 1.2 Cards are flag-conditional, except the clock

`Pokegear_FinishTilemap` (`:340-350`) tests `wPokegearFlags` (`01:D9D8`) and draws Map / Phone / Radio
**only when their bit is set**; the Pokégear icon at `(0,0)` is unconditional. That is exactly the
vanilla feel the owner wants: **an SLink icon that appears only when the companion is present**, driven
by the reserved `POKEGEAR_EXPN_CARD_F` bit.

### 1.3 The one hard-coded cap — this is the only engine edit

`InitPokegearTilemap` (`:199-206`, sym **`24:4e35`**):

```
	ld a, [wPokegearCard]      ; wPokegearCard is 00:CE48
	and $3                     ; <-- hard caps the card to 0..3
	add a
	ld e, a
	ld d, 0
	ld hl, .Jumptable
	add hl, de                 ; 2 bytes per entry
```

**`and $3` is the single instruction that must change.** With it, card 4 aliases to 0 (CLOCK). It is
a one-byte same-size edit in `engine/pokegear/pokegear.asm` — a **shared game file**, not overlay
space, so it is the only change with cross-screen reach, and it is trivially auditable.

### 1.4 The state machine

`PokegearJumptable` (`:378-394`) is `StandardStackJumpTable` over **15** states, from
`POKEGEARSTATE_CLOCKINIT ; 0` to `POKEGEARSTATE_RADIOJOYPAD ; e` (`:12-26` for the list). States are
dispatched by `wJumptableIndex`. Adding a panel card means **appending** init/joypad states — the table
grows upward, so no existing index moves. (Contrast the Start menu, where the box was already full.)

## 2. What vanilla Gen 2 SLink did, and what is reusable

**Vanilla SLink uses the START MENU, not the Pokégear.** `patch/gen2/src/panel_start.asm:3` defines
`SlinkStartMenuEntry` and `:16` asserts it in bank 4; it is reached by rewriting the Start menu's item
table row (`StartMenu_Quit` → the SLink handler), and the panel itself is `SlinkPanel` in
`patch/gen2/src/panel.asm`.

**Reusable for a Pokégear card:**

| asset | reusable? |
|---|---|
| `lua/gen2/panel.lua` (198 lines) + `P.writes` | **Yes, unchanged.** It is drawn through the shared `gb_panel` mailbox lease and knows nothing about how the entry was reached. It is the panel's engine; the Pokégear only supplies a way in. |
| `patch/gen2/src/panel.asm` `SlinkPanel` | **Yes conceptually, needs the graphics re-pointing** documented in `docs/polished/PANEL.md` §2.3 (`WaitBGMap2`/`GetSGBLayout` replacements) — **UNVERIFIED**, that is still an open PANEL.md card |
| `panel_start.asm`'s bank-4 item row + `ASSERT BANK(...) == 4` | **No.** That is Start-menu specific and is retired by this ruling (see §5). |

## 3. What makes an entry "feel vanilla", concretely

A native card is: an icon pair in the row, a cursor that lands on it, B/START to back out, and the
standard Pokégear transition into that card's view. Concretely an SLink card needs:

1. **Icon tiles.** Two tile ids in the icon strip. Taken: `$50`/`$51` (Map), `$52`/`$53` (Radio),
   `$54`/`$55` (Phone), `$56` (Pokégear). **A free pair must be read off the tileset, not guessed** —
   **UNVERIFIED**: I did not read the gfx block for the next free pair.
2. **Placement.** `hlcoord 8, 0` and the same three-row write as `.PlacePokegearCardIcon` — copy that
   routine's shape exactly so the icon's shading matches.
3. **A flag bit** so the icon is absent until the companion is present (`POKEGEAR_EXPN_CARD_F ; 3`).
4. **Cursor.** Nothing to do: `swap` gives x = 8 for card 4 automatically.
5. **Transition + SFX.** Reuse `Pokegear_FinishTilemap`'s callers (`TownMapPals` at `:212`) and the
   standard Pokégear B-to-back path. **UNVERIFIED** — I did not trace the Pokégear's own B handling.
6. **Text.** Inside the panel, not the Pokégear: `panel.lua` already stages text.
7. **Space.** Per `docs/polished/HOOKS.md`, ROM0 has **351 free bytes at `$015f`**, and the overlay's
   service bank is `$7E`. Both are cited in HOOKS.md; **UNVERIFIED** — I did not re-derive either
   figure this pass.

## 4. The hook change set (HYPOTHESIS — addresses read, bytes not)

| # | change | where | size |
|---|---|---|---|
| H1 | `and $3` → a mask admitting 0..4 (e.g. `and $7`) | `engine/pokegear/pokegear.asm:203` (routine at sym `24:4e35`) | **1 byte**, same-size, **shared game file** |
| H2 | append `POKEGEARSTATE_SLINKINIT ; f` / `..._SLINKJOYPAD ; 10` to the state const list, and the matching two `dw` to `PokegearJumptable.Jumptable` | `pokegear.asm:26` / `:394` | **6 bytes** total, **shared game file** |
| H3 | an SLink branch in `Pokegear_FinishTilemap` gated on `POKEGEAR_EXPN_CARD_F`, placing the icon at `hlcoord 8, 0` | `pokegear.asm:350` (sym `24:…`, not read this pass — **UNVERIFIED**) | overlay-side hook |
| H4 | set `POKEGEAR_EXPN_CARD_F` when the companion advertises `SLINK_CAP_PANEL` | wherever the other three flags are set — **not traced, UNVERIFIED** | — |
| H5 | the panel itself | overlay, `bank $7E`, reusing `panel.lua` unchanged | unchanged |

**Only H1 and H2 touch shared engine files**, and both are same-size. That is a materially better
profile than the Start-menu route, where the box was full and `AutomaticGetMenuBottomCoord` was
shared by *every* menu.

## 5. What this retires and keeps in `docs/polished/PANEL.md`

**Retired by the ruling** (no longer needed):

* the Start-menu **item-table row** work — the two-word `dw SlinkStartMenuEntry, SlinkMenuString`, the
  full-line anchor, `const STARTMENUITEM_SLINK ; 9`, and the three
  `ASSERT BANK(...) == 4` lines;
* `.SetUpMenuItems` as a **new anchor** (the conditional append disappears);
* `SlinkMenuDesc` / `next "status@"` — already dead (Polished has no description column), and now
  doubly so;
* `docs/polished/PANEL_SLOT.md` **Option B** (enlarge to 9) and the whole bottom-19 / `wAttrmap`
  corruption analysis in `MENU_9.md` — **the Start menu never needs a 9th item**.

**Kept unchanged:**

* `PANEL.md` §2.3, §4 — the graphics re-pointing (`ClearTileMap`, `ClearPalettes`, `wAttrmap $C308`)
  and E6/E7 (`GetSGBLayout`, `WaitBGMap2`) are properties of `SlinkPanel`, **not** of the entry point;
* the mailbox contract — the panel uses core bytes `+9/+10/+11` and needs no ABI growth;
* `PANEL.md` §5's live-only list, unchanged.

**Newly relevant:** the `d8d75628` review's F-3 (a live `P.writes` panel writer whose only brake is
the ROM caps byte) is **not** retired by moving the entry — it is unchanged by this ruling.

## 6. The single live check that settles feel and rendering

Open the Pokégear on a Polished cartridge with `POKEGEAR_EXPN_CARD_F` set and the SLink state
appended, then:

> **Is the SLink icon indistinguishable from the four native ones?** Put the cursor on it with the
> left/right arrows, press A, and press B back out — and compare, side by side with Map/Radio/Phone:
> icon shading and size, cursor placement, the B-to-back transition and its SFX, and the fade into the
> card's view.

That single pass decides "feels vanilla", which no static check can: it is the only claim here about
perception rather than layout. It also implicitly settles the open `PANEL.md` §5 item 1 (whether
`ReloadTilesetAndPalettes` can stand in for `WaitBGMap2`), because entering the card reveals the panel.

## 7. UNVERIFIED inventory

| item | how to settle |
|---|---|
| the next free icon **tile pair** (§3.1) | read the gfx/tileset block and list allocated ids — do not guess |
| `Pokegear_FinishTilemap`'s own sym address (H3) | the sym lookup I ran returned only `AnimatePokegearModeIndicatorArrow 24:4e20` and `InitPokegearTilemap 24:4e35`; the Finish label is a local and needs a different lookup |
| where `wPokegearFlags`' three bits are set (H4) | read the flag-setters; not traced |
| the Pokégear's B-to-back path and SFX (§3.5) | read the Pokégear joypad handler |
| ROM0 `$015f` 351 bytes and bank `$7E` space (§3.7) | cited from HOOKS.md; not re-derived this pass |
| whether `panel.lua` needs any change to be reached from the Pokégear | my reading is that it does not (it is reached through the mailbox lease), but I did not trace `gb_panel`'s entry points |

---

## Coordinator verification (2026-10-04)

Re-read `engine/pokegear/pokegear.asm`: `InitPokegearTilemap` caps the card with `and $3` (:207), the
icons sit at x = 0/2/4/6 (:354,359,364 and the Pokegear icon at (0,0)), and the cursor x is `card << 4`
pixels (:185-191), so card 4 lands at tile column 8. **One omission in the design:** `Pokegear_FinishTilemap`
fills only the first 8 columns of rows 0-1 with the black bar (`hlcoord 0,0 / ld bc,$8` and `hlcoord 0,1 /
ld bc,$8`, :331-338), so an icon at column 8 would sit OUTSIDE the bar. A vanilla-looking fifth card therefore
also needs both `ld bc,$8` operands widened to `$A` (two more same-size byte edits in bank 24), and whatever
else draws on rows 0-1 at columns 8-9 per card (the title text/arrows) must be checked: UNVERIFIED. The free
icon tile pair and the B-back path remain UNVERIFIED, live-checkable. Ruling basis: owner 2026-10-04 "put it in
the Pokegear; has to feel vanilla".


---

## Coordinator note after the live Pokegear look (2026-10-04, LIVE_RESULTS.md Run 2 Stage C)

Measured on the real Pokegear (flags SYNTH-set to obtained + map/radio/phone cards): rows 0-1 columns 0-7 are the same
on every card and the cursor x is 16/32/48/64 (+16 per card); **columns 8-9 are drawn by every card** (clock border `$f7`,
the map's landmark name, phone/radio frames), so a fifth icon at column 8 collides with each card's own layout and
widening the black bar alone is not enough. `$58/$59` is NOT a usable icon pair (`$58` is drawn by the radio card, and
the lower half at +`$10` would hit `$68/$69`, the phone signal bars); no pair in `$50-$75` is free with its +`$10` pair.
Free tiles: `$59`, `$5B` (drawn, never referenced, not adjacent) and `$76-$7E` (never written by the Pokegear: the built
`pokegear.2bpp` is trimmed to 38 tiles), plus VRAM bank 1 tiles `$50-$7F` all zero. Consequence: the "one byte plus six
bytes" estimate above is WRONG; a native-looking fifth card needs its own tile load, a different placement routine and a
layout that leaves columns 8-9 to the other cards. The earlier claim that column 8 is free held only for the strip itself.
Open design choice for the owner (not yet asked): (a) a fifth card with its own tile load; (b) put the SLink entry inside an
existing card that already has a list UI (the Phone card's contact list is the natural vanilla-feeling host, an SLink
'contact'); (c) the retired Start-menu substitution. Nothing built.
