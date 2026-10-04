# PANEL-SLOT — giving SLink a Start-menu slot in Polished without a 9th item

**Follow-up to `docs/polished/PANEL.md`.** That card's §2.2 used `bottom = top + items + 1`; the
real arithmetic in `home/menu.asm` is **`add a` then `inc a` over the loaded item count**, i.e.
**2 rows per item**. The corrected consequence is stated in `PANEL.md` and is not repeated here —
this card takes it as given and asks the narrower question: **where does the SLink entry go, given
the box is already full at 8?**

Source: `F:/slink-work/cache/polished/src/engine/menus/start_menu.asm`,
`F:/slink-work/cache/polished/src/home/menu.asm`, and the vanilla overlay's menu hijack under
`F:/slink-work/wt/polished/patch/gen2/src/`. Absolute paths throughout.

---

## 1. The exact set of items that can be live at once, and the true maximum

`.SetUpMenuItems` (`engine/menus/start_menu.asm:213`) calls `.FillMenuList` (`:272`, which fills
`wMenuItemsList+1 … wMenuItemsListEnd` with `$FF` and returns `c = 0` in `de`) and then appends in a
**fixed order**, one `.AppendMenuList` (`:283`) per live item, incrementing `c` (which becomes
`wMenuItemsList` at `:268`):

| # | item | line | live when |
|---|---|---|---|
| 1 | `STARTMENUITEM_POKEDEX` | `:218-222` | `wStatusFlags` bit 0 set |
| 2 | `STARTMENUITEM_POKEMON` | `:225-229` | `wPartyCount != 0` |
| 3 | `STARTMENUITEM_PACK` | `:232-239` | **and** `wLinkMode == 0` **and** `STATUSFLAGS2_BUG_CONTEST_TIMER_F` clear |
| 4 | `STARTMENUITEM_POKEGEAR` | `:242-246` | `POKEGEAR_OBTAINED_F` set |
| 5 | `STARTMENUITEM_STATUS` | `:249-250` | **always** |
| 6 | `STARTMENUITEM_QUIT` **or** `STARTMENUITEM_SAVE` | `:252-261` | see §2 — **exactly one** |
| 7 | `STARTMENUITEM_OPTION` | `:263-264` | **always** |
| 8 | `STARTMENUITEM_EXIT` | `:265-266` | **always** |

**True maximum = 8**, reached only when Pokédex, party, Pack, Pokégear and the non-link Save are all
present. **True minimum = 3** (`STATUS`, `OPTION`, `EXIT`), when there is no party, no Pokédex, no
Pokégear and the player is in link or bug contest.

The dispatch table at `:163-171` lists **nine** `dw handler, dw string` rows. That is a *static*
table; `.SetUpMenuItems` builds a *dynamic* list of at most eight ids from it. **The ninth table row
(`StartMenu_Quit`) is reachable only through the dynamic list** — the static table is a superset,
which is why the vanilla overlay's "append a row to the table" anchor was never wrong in shape and
is wrong in reachability.

## 2. The mutually exclusive pair, and whether Quit could carry SLink

`engine/menus/start_menu.asm:252-261`:

```
	ld a, [wLinkMode]
	and a
	jr nz, .no_save
	ld hl, wStatusFlags2
	bit STATUSFLAGS2_BUG_CONTEST_TIMER_F, [hl]
	ld a, STARTMENUITEM_QUIT
	jr nz, .write          ; link OR bug contest -> QUIT
	ld a, STARTMENUITEM_SAVE
.write
	call .AppendMenuList
.no_save
```

**`SAVE` and `QUIT` are strictly exclusive — exactly one is appended.** `QUIT` exists *only* when
`wLinkMode != 0` or the bug-contest timer is running.

**Could the SLink entry ride on Quit?** In the states where Quit is live, the player is **mid link
battle or mid bug contest** — precisely the states where a status panel is not what they need, and
where Quit is the *only* way out. Taking that slot would remove the player's escape from a link or
contest to give them an information screen. **I recommend against it, and note it is also the wrong
shape: in the maximum (8-item) configuration Quit does not exist at all**, so it cannot be the slot
that resolves the collision.

**The useful corollary:** because `PACK` is dropped whenever `wLinkMode != 0` or the contest timer
runs (`:232-239`), **the link/contest configuration holds at most 7 items — one fewer than the
maximum.** That is the one state with a guaranteed free slot.

## 3. Options, ranked

**Option A — Conditionally substitute a native row, only in configurations that are not full.**
Add a ninth table row and have `.SetUpMenuItems` append `STARTMENUITEM_SLINK` **instead of** one
native row when the list would otherwise reach 8. The only rows with a defensible substitution are
the two gated ones (`POKEDEX` `:218`, `POKEGEAR` `:242`), because those are already conditional and
a player who has not obtained the Pokégear never sees it change.
*Cost:* in the full 8-item configuration a player permanently loses Pokédex **or** Pokégear access
from the Start menu. *Certainty:* the mechanics are static and provable; **which** row to drop is a
product decision, and **UNVERIFIED** whether either is acceptable to the owner.

**Option B — Enlarge the box to 9 and let the ninth item live below.**
The corrected arithmetic gives bottom `19` for 9 items at top `0`, against an 18-row screen
(`y 0..17`).
*Cost:* two possibilities, and the difference matters. Either the box simply extends past the
visible area and the ninth item's rows are **clipped**, or the engine scrolls. **UNVERIFIED — and
this is the named measurement:** read `wMenuBorderBottomCoord` and `wMenuDataItems` with 9 items
appended on a real cartridge, and read `wTileMap` for rows 18-19 to see whether anything is written
there.
*Do not* fix this by editing the `add a` / `inc a` pair in `home/menu.asm:454`: that routine is
**shared by every menu in the game**, so changing the pitch changes all of them. **UNVERIFIED** how
many other menus would move.

**Option C — Do not use the Start menu.**
Bind the panel to the Pokégear card, or to a key combination at the overworld.
*Cost:* no menu surgery at all, and no collision ever. *Certainty:* high for the "no collision"
claim; the binding mechanism is **UNVERIFIED** and is a design card of its own.

**Option D — Take over Quit's slot (rejected above).** Listed so the record shows it was considered:
it removes the only escape from a link or contest, and it does not even address the 8-item maximum.

**Ranking.** **A** if the owner will sacrifice one gated row in the full configuration; **C** if not.
**B** is last: it is the only option whose failure mode (clipping) is invisible until someone
notices a missing row, and it is the only one that could destabilise other menus.

## 4. What the builder anchors must become

For the chosen option, in `F:/slink-work/wt/polished/patch/gen2/src/panel_start.asm` and the
`_start_menu_text()` edits in `tools/build_gen2_companion.py`:

| anchor | vanilla | Polished today | must become |
|---|---|---|---|
| the item constant | insert `const STARTMENUITEM_SLINK ; 9` after `const STARTMENUITEM_QUIT ; 8` | `engine/menus/start_menu.asm:11` is an exact match | **unchanged** under every option |
| the item row | `\tdw StartMenu_Quit,     .QuitString,     .QuitDesc\n` | `engine/menus/start_menu.asm:171` is `\tdw StartMenu_Quit,     .ExitString` — **no description column** | a **two-word** row `dw SlinkStartMenuEntry, SlinkMenuString`, verified **exactly once** (the eight native rows make a substring match unsafe — anchor on the full line) |
| `SlinkMenuDesc` / `next "status@"` | live, feeds the description column | **no consumer** | **DELETE** under every option |
| `SlinkStartMenuEntry` body | `call FadeToMenu / farcall SlinkPanel / ld a, 6 / ret` | `StartMenu.ReturnRedraw` is the matching restore | unchanged, **but** under Option A the row is gated, so the handler must still return `6` on every path |
| `.SetUpMenuItems` | untouched | append order is fixed at `:213-266` | **this is the new anchor** — under Option A the builder must insert the conditional append (and its `.no_*` label) as verify-then-replace text, with a `skip` label per branch |

The three `ASSERT BANK(...) == 4` lines in `panel_start.asm` are unaffected: `StartMenu 04:6059` and
`StartMenu_Quit 04:6267` keep the menu in bank 4.

## 5. What the coordinator should re-derive before accepting

1. **The 2-rows-per-item pitch** from `home/menu.asm:454` — the load-bearing fact of the whole card.
2. **The eight `.AppendMenuList` call sites and their gates** in `engine/menus/start_menu.asm:213-266`.
3. **`wMenuItemsList` / `wMenuItemsListEnd`** capacity from the RAM constants — **UNVERIFIED** here;
   if the list is a fixed-size byte array, appending a ninth id could overflow it *before* the box
   arithmetic is even reached. **The measurement:** read `wMenuItemsListEnd - wMenuItemsList` and
   compare with 9.

## 6. UNVERIFIED, with the measurement that settles each

| item | measurement |
|---|---|
| clipping at bottom 19 | append 9 items on a cartridge; read `wTileMap` rows 18-19 |
| `wMenuItemsList` capacity for a 9th id | read the two symbols' addresses from the `.sym` |
| whether editing `AutomaticGetMenuBottomCoord` moves other menus | build, then compare two unrelated menus' box bottoms |
| whether Pokédex or Pokégear may be sacrificed | owner decision, not a measurement |
| a non-Start-menu binding for the panel | design card |
## 7. Machine-checkable citations

```json CLAIMS
[
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 213,
  "expect": ".SetUpMenuItems:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 216,
  "expect": "call .FillMenuList"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 272,
  "expect": ".FillMenuList:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 277,
  "expect": "wMenuItemsListEnd - (wMenuItemsList + 1)"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 283,
  "expect": ".AppendMenuList:"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 3,
  "expect": "STARTMENUITEM_POKEDEX"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 4,
  "expect": "STARTMENUITEM_POKEMON"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 5,
  "expect": "STARTMENUITEM_PACK"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 25,
  "expect": "STATUSFLAGS2_BUG_CONTEST_TIMER_F"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 243,
  "expect": "POKEGEAR_OBTAINED_F"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 10,
  "expect": "STARTMENUITEM_POKEGEAR"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 6,
  "expect": "STARTMENUITEM_STATUS"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 11,
  "expect": "STARTMENUITEM_QUIT"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 7,
  "expect": "STARTMENUITEM_SAVE"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 8,
  "expect": "STARTMENUITEM_OPTION"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 9,
  "expect": "STARTMENUITEM_EXIT"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 269,
  "expect": "[wMenuItemsList]"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 171,
  "expect": "dw StartMenu_Quit,"
 },
 {
  "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
  "line": 11,
  "expect": "const STARTMENUITEM_QUIT"
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
  "path": "F:/slink-work/cache/polished/src/home/menu.asm",
  "line": 360,
  "expect": "ld [wMenuBorderBottomCoord], a"
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
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel_start.asm",
  "line": 3,
  "expect": "SlinkStartMenuEntry:"
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
  "path": "F:/slink-work/wt/polished/patch/gen2/src/panel_start.asm",
  "line": 6,
  "expect": "ld a, 6"
 },
 {
  "path": "F:/slink-work/wt/polished/docs/polished/PANEL.md",
  "line": 145,
  "expect": "### 2.2"
 }
]
```


---

## Coordinator verification (2026-10-04)

* The 8 append sites, the SAVE/QUIT exclusivity and the true max of 8 re-derived from
  `engine/menus/start_menu.asm` `.SetUpMenuItems` (Pokedex, Pokemon, Pack, Pokegear, Status, Save|Quit,
  Option, Exit); box bottom = `top + 2*items + 1`. All 29 CLAIMS quotes verify.
* The OMP's open worry is **closed**: `wMenuItemsList` is `ds 16` (`ram/wramx.asm:171`, `01:d03e` to
  `01:d04e` in the pinned `.sym`), so a ninth id does not overflow the list. The collision is the
  18-row screen (bottom 19), not the buffer.
* The ranking is accepted as a recommendation only. Choosing A (sacrifice a gated native row), B
  (bigger box, clipping unmeasured) or C (no Start entry, e.g. Pokegear or a key combo) is an **owner
  decision** (UI placement, and the lane's rule is to mimic accepted frameworks). Not decided.
