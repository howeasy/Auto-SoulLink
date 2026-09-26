# Free WRAM/SRAM survey for a Gen 2 companion-patch mailbox (wayfinder ticket 14)

Scope per ticket: the WRAM/SRAM/HRAM half only. The ROM-space half (free ROM0/bank
bytes for the hook + code) needs a built ROM (ticket 11) and is explicitly out of
scope here.

Pins: pokecrystal `7a7881d0d62e0ddbd82dcf10e7116807487ac651` (`pokecrystal@7a7881d`),
pokegold `656583c939d30f920a316177311a502dd222b57c` (`pokegold@656583c`), both read at
`.../scratchpad/pret_head/{pokecrystal,pokegold}`. `data/pret_syms.json` addresses used
below inherit the caveat already recorded in `docs/gen2/research/pret_gen2_symbols.md`
(top of file, and "Cross-check against data/pret_syms.json"): `tools/build_pret_syms.py`
resets each cache to unpinned `origin/HEAD` before extracting symbols, so an address from
the JSON is corroborating, not proof, until ticket 11 builds from the exact pinned shas.

## Pins

- pokecrystal@7a7881d, pokegold@656583c (as above).
- Gen 1 precedent: `patch/gen1/src/slink.asm` (mailbox), `patch/gen1/README.md` (why
  Red/Blue had one byte range and Yellow had none), `lua/gen1/panel.lua` /
  `lua/gen1/trade_overlay.lua` (the ABI the Lua side expects).
- `docs/gen2/research/pret_gen2_symbols.md` §10 ("Save", SRAM section map) and
  `docs/gen2/research/codex_checkpoint_and_linktrade.md` §A (DelayFrame/IRQ stack shape)
  read as directed; cited below where they bear on candidate liveness.

## What the Gen 1 mailbox needs

- **Size and layout:** 30 bytes total (`patch/gen1/src/slink.asm:38-46`, comment block
  "Mailbox layout (30 bytes available, $DEE2-$DEFF)"), of which the shipped ABI 3 uses
  14: `+0..3` beacon, `+4` ABI version, `+5..6` 16-bit frame counter, `+7` SFX request,
  `+8` capability bits, `+9` panel state, `+10` page wanted, `+11` page count, `+12..13`
  SFX hold flag/start frame (`patch/gen1/src/slink.asm:41-56`). `lua/gen1/panel.lua:16-24`
  re-derives the same offsets as constants (`MAILBOX+4`..`MAILBOX+11`) — the Lua ABI is a
  fixed-offset struct over the mailbox base, not just a byte count.
- **Alignment:** none required — it is addressed byte-by-byte via `EQU MAILBOX + n`, not a
  paged or bank-aligned structure (`patch/gen1/src/slink.asm:38-56`).
- **Must survive across:** the frame counter increments every VBlank "in the overworld
  AND in battle AND in menus" (`patch/gen1/README.md` "How it hooks" section, and
  `slink.asm:1-19` design note) — i.e. it must never be cleared by battle entry/exit,
  menu open/close, or ordinary map transitions. It is explicitly allowed to be wiped on
  `Init`/new game: "`Init` zero-fills WRAM so a fresh cartridge never sees a stray
  request" (`patch/gen1/README.md`, "How sound is played" section). Save/load is a
  non-issue for Gen 1 because the mailbox is WRAM-only, never SRAM-backed.
- **Bank requirement — must be WRAM0 (always mapped), not WRAMX (banked):** the mailbox
  is read from arbitrary contexts (VBlank IRQ, the DelayFrame bridge, the Joypad stub,
  Lua running outside any bankswitch) with no bank-select protocol in the ABI at all — the
  design note is explicit that the *reason* $DEE2 was chosen is because it is
  "the only free WRAM in Red/Blue" full stop, not "the only free bank-0 WRAM" (Gen 1's
  WRAM is not banked at all below CGB double-speed considerations that don't apply here).
  For Gen 2 (which does have banked WRAMX, `ram/wram.asm:1907` `SECTION "WRAM 1", WRAMX`
  pokecrystal / `ram/wram.asm:1906` pokegold), the equivalent constraint carries forward
  as: **the mailbox must live in WRAM0** unless every reader/writer commits to swapping
  `hWRAMBank`/`rSVBK` first — the DelayFrame/IRQ chain documented in
  `codex_checkpoint_and_linktrade.md` §A (`home/vblank.asm:9-13`, "VBlank immediately
  pushes AF/BC/DE/HL") has no established WRAMX-bank discipline for an external writer,
  so a WRAM0 site avoids inventing one.
- **Trade lease is separate from the mailbox:** Gen 1's trade protocol runs over its own
  16-byte union (`wSerialPartyMonsPatchList`, aliased over enemy slot 1's first 16 bytes),
  not mailbox bytes (`patch/gen1/README.md` "What the mailbox carries";
  `lua/gen1/trade_overlay.lua:29-34`). A Gen 2 design does not need the mailbox to also
  carry trade staging — it can borrow an already-allocated struct the way Gen 1 did.

## Candidates: pokecrystal

All of the following were checked by grepping every apparent "free" or "unused" label for
non-declaration references across `engine/`, `home/`, `audio/`, and `mobile/`. **Every
labeled `wUnused*`/`hUnused*` byte checked is actively written by some engine routine** —
the "Unused" prefix in pret means "the *feature* is dummied out", not "the byte is never
touched". None of these are safe to overlay a persistent mailbox on without either the
game corrupting the mailbox or the mailbox corrupting game state:

| candidate | addr (JSON, unbuilt) | size | touched by |
|---|---|---|---|
| `wUnusedBCDNumber` | — | 1 | `home/audio.asm:482` |
| `wUnusedMusicF9Flag` | — | 1 | `audio/engine.asm:1682,2349` |
| `wUnusedScriptByte` | — | 1 | `engine/overworld/scripting.asm:2202` |
| `wUnusedPlayerLockedMove` | — | 1 | `engine/battle/core.asm:5508` |
| `wUnusedMysteryGiftStagedDataLength` | — | 1 | `engine/link/mystery_gift.asm:1466`, `mystery_gift_2.asm:52` |
| `wUnusedPokedexByte` | — | 1 | `engine/pokedex/pokedex.asm:93` |
| `wUnusedPokegearByte` | — | 1 | `engine/pokegear/pokegear.asm:95` |
| `wUnusedSlotReelIconDelay` | — | 1 | `engine/games/slot_machine.asm:258` |
| `wUnusedBillsPCData` | 0xCF64 | 3 | `engine/pokemon/bills_pc.asm:785-787` |
| `wUnusedSGB1eColorOffset` | — | 1 | `engine/gfx/sgb_layouts.asm:456` |
| `wUnusedLinkCommunicationByte` | 0xCFBB | 1 | `engine/link/link.asm:1647` |
| `wUnusedMovementBufferBank`/`Pointer` | — | 3 | `home/movement.asm:6-10` |
| `wUnusedNamesPointer` | — | 2 | `engine/link/init_list.asm:47-49`, `engine/link/link.asm:191-193,466-468`, `home/names.asm:61-63` |
| `wBaseUnusedFrontpic`/`Backpic` | — | 4 | bulk-copied every species load: `home/pokemon.asm:264-270` (`CopyBytes` over `BASE_DATA_SIZE`, which spans this field per `ram/wram.asm:2772-2774`) |
| `wUnusedEggHatchFlag` | — | 1 | `engine/pokemon/breeding.asm:257,329` |
| `wUnusedGameboyPrinterSafeCancelFlag` | — | 1 | `engine/printer/printer.asm:457` |
| `wUnusedTradeAnimPlayEvolutionMusic` | — | 1 | `engine/movie/trade_animation.asm:23,74,140` |
| `wUnusedTwoDayTimerOn`/`Timer`/`StartDate` | 0xDC39-0xDC3B | 3 contiguous | `engine/overworld/time.asm:8,112,208,211,216,219` — this is the closest thing to a "block", but it is written every day-rollover, disqualifying it |
| `wUnusedDailyFlag` | 0xDC21 | 1 | `engine/overworld/time.asm:112` (same routine as above) |

**`wUnusedMapBuffer` (WRAM0, 24 bytes, `ram/wram.asm:869-874`, addr 0xC7E8-0xC7FF per
JSON) is the most tempting candidate on paper** — it is WRAM0 (always mapped, matching
the Gen 1 requirement), and its own comment says it "was a buffer for map-related
pointers in the 1997 G/S prototype" — but it is **disqualified**: `ClearUnusedMapBuffer`
(`home/map.asm:3-8`) zero-fills it, and is called from `engine/overworld/warp_connection.asm:2`
— i.e. it is wiped on **every warp**, which directly violates the Gen 1 mailbox's
"survives warps" requirement.

**HRAM:** every `hUnused*` byte is also touched. `hUnusedBackup` (`ram/hram.asm:159`,
comment-adjacent to `hFrameCounter`) is written from `home/vblank.asm:146` — i.e. from
inside VBlank itself, the exact hook context Gen 1 used — so it is the worst possible
overlay target, not the best. `hUnusedByte` (`ram/hram.asm:34`) is written once from
`engine/overworld/events.asm:817`. `hMGUnusedMsgLength` (`ram/hram.asm:97`) is written
from `engine/link/mystery_gift.asm:1120`. No free HRAM byte was found.

**Numeric-address placeholder labels** (`wc303`, `wc319`..`wc3fc`, `wc608`..`wc9b6`,
`wcc60`..`wcd8d`, `wd002`..`wd036`, `wdc41`..`wdc42`, etc. — dozens, `ram/wram.asm:223-296,
705-865,1204-1327,1330-1340,1409-1534,2173-2197,3340-3341`) are pret's placeholders for
bytes whose *purpose* wasn't identified, inside the `SECTION UNION "Miscellaneous"` /
`"WRAM 1"` blocks that also hold named, actively-used script/battle/menu temp fields.
Because they sit inside structured regions that get bulk `ByteFill`/`CopyBytes` treatment
elsewhere in the same union, per-symbol grep (no hits by that literal name) does **not**
prove liveness the way it does for a named symbol — a range write to the enclosing struct
would touch them silently. This needs either a targeted trace of every `ds N`/`CopyBytes`
range that spans each address, or a build with an emulator memory-watch (ticket 11). Not
claimed as free here; listed under Open questions.

## Candidates: pokegold (Gold + Silver)

pokegold's `ram/wram.asm` mirrors pokecrystal's structure closely (fewer `Overworld Map`
UNION branches, no Crystal-only Battle Tower/Crystal-Data sections). The same audit
applies with the same result:

| candidate | addr (JSON, unbuilt) | size | touched by |
|---|---|---|---|
| `wUnusedMapBuffer` | 0xC6E8-0xC6FF | 24 | `home/map.asm:3-8`, called from `home/map.asm:217` (pokegold folds the warp-clear call into the same file) — same warp-clear disqualification as pokecrystal |
| `wUnusedBillsPCData` | 0xCE64 | 3 | `engine/pokemon/bills_pc.asm` (same source file, shared with pokecrystal's engine tree layout) |
| `wUnusedLinkCommunicationByte` | 0xD8B7 | 1 | `engine/link/link.asm` |
| `wUnusedTwoDayTimerOn`/`Timer`/`StartDate` | ~0xD983-0xD985 | 3 | `engine/overworld/time.asm:8,163-174` |
| `wUnusedPikachuFrameset` | — | 1 | `engine/sprite_anims/functions.asm:844` (pokegold-only symbol; Pichu/Pikachu-follower leftover) |
| `wUnusedJigglypuffNoteXCoord` | — | 1 | `engine/sprite_anims/functions.asm:876,914,922` |
| `wUnusedAddOutdoorSpritesReturnValue` | — | 1 | `engine/overworld/overworld.asm:122` |
| `wUnusedReanchorBGMapFlags` | — | 1 | `engine/overworld/init_map.asm:25`, `home/window.asm:41` |

Every pokegold-specific "Unused" label checked is touched, same as pokecrystal. No
pokegold-only free byte was found either.

**`_ResetWRAM` clears the whole WRAM0 body on New Game** in both titles:
`_ResetWRAM` (`patch/gen1`-style name reused by pret) zero-fills `wShadowOAM..wOptions`
(WRAM0), then `STARTOF(WRAMX)..wGameData` and `wGameData..wGameDataEnd`
(pokecrystal `engine/menus/intro_menu.asm:96-112`; pokegold
`engine/menus/intro_menu.asm:22-28` — pokegold's version is structurally the same call
chain, not independently re-quoted line-by-line here). This means **any** WRAM0 mailbox
candidate, free or not, is wiped on New Game — which matches Gen 1's own accepted
behavior ("Init zero-fills WRAM") and is not a disqualifier by itself.

`ClearWRAM` (pokecrystal `home/init.asm:186-200`) has a **documented pret bug**: the loop
that is supposed to wipe WRAMX banks 1-7 only ever clears bank 1, because `ldh [rWBK],a`
combined with the loop counter never re-selects past the first iteration's effect
correctly (comment at `home/init.asm:189`, cross-referenced to
`pokecrystal@7a7881d docs/bugs_and_glitches.md`). This is relevant only to a WRAMX
candidate (none are being proposed here) and is listed for completeness.

## Shared candidate across titles

**None found.** No byte or byte range survived the "is it ever referenced outside its own
declaration" filter in either repo. The one structurally-shared, always-WRAM0, comment-
documented-as-dead region — `wUnusedMapBuffer` — exists at a *different* address in each
title (0xC7E8 pokecrystal vs 0xC6E8 pokegold, a 0x100 offset difference that already rules
out a single hard-coded address working for both without per-title patching) and is
disqualified anyway by the warp clear. Since pokegold's own WRAM layout is confirmed
identical between Gold and Silver (`docs/gen2/research/pret_gen2_symbols.md` "Additional
pinned answers (c)": no `_SILVER`/`_GOLD` conditionals in `ram/wram.asm`), any address
found valid for pokegold is automatically shared between Gold and Silver — the open
question is only Crystal vs Gold/Silver, and it remains open.

## Ranking

No candidate cleared the bar ("provably never touched, WRAM0, survives battle/warp/save").
Ranked by how close each came, for ticket 11 to re-test on a built ROM with a live memory
watch:

1. **Section-end slack in `ram/wram.asm`'s WRAM0 body (unmeasured).** `layout.link`
   (`pokecrystal@7a7881d layout.link`, `pokegold@656583c layout.link`) does not fix WRAM
   section addresses — sections float and are packed by RGBLINK — so total WRAM0 slack
   cannot be computed from source alone the way Gen 1's "`WRAM0: TOTAL EMPTY: $001E`"
   linker-map line was read directly off a build. This is the single most likely place a
   real free byte exists (Gen 1's own free space was exactly this kind of linker leftover,
   not a named symbol) and is squarely what ticket 11's build should report.
2. **`wUnusedMapBuffer` (both titles) if the warp clear is patched around or the mailbox
   accepts being warp-wiped for a subset of fields.** It is WRAM0, 24 bytes, well
   documented, and the *only* clear (`ClearUnusedMapBuffer`) is a single, easily-hookable
   call site in both titles. Not usable as-is for the persistent frame counter, but usable
   for anything that only needs to survive within one map (a per-visit scratch flag,
   not a running counter or panel state).
3. **`sScratch`/`sDecompressScratch` (SRAM, both titles, `ram/sram.asm:1-4` pokecrystal /
   `:1-13` pokegold UNION with `sDecompressBuffer`).** Genuinely large (0x600 bytes) and
   the *union's largest member* only during decompression bursts, but it is written from
   battle animations, the Pokédex, GFX loading and cleared at Init (`ClearsScratch`,
   `home/init.asm:98,205-213`) — usable only as short-lived scratch during a period the
   caller controls, never as a resident mailbox. SRAM also carries `OpenSRAM`/`CloseSRAM`
   bank-switch and write-latency overhead a per-VBlank mailbox does not want, and any SRAM
   write is a power-loss/corruption risk the WRAM-only Gen 1 mailbox never had.

## Open questions

- Ticket 11 (built ROM) is required to get an actual `WRAM0/WRAMX: TOTAL EMPTY` linker
  report, the way Gen 1's evidence was gathered — nothing in `layout.link` or the source
  files fixes final addresses or reports slack.
- The dozens of numeric placeholder labels (`wc303`..`wc9b6`, `wcc60`..`wcd8d`,
  `wd002`..`wd036`, `wdc41`-`wdc42`, pokecrystal `ram/wram.asm:223-296,705-865,1204-1327,
  1330-1340,1409-1534,2173-2197,3340-3341`) were not individually traced against every
  bulk `ByteFill`/`CopyBytes` range in `engine/` that might silently touch them; a
  per-symbol grep found no direct reference, but that does not prove liveness inside a
  union/struct region the way it does for a named symbol.
- Whether any of the `SECTION UNION "Miscellaneous WRAM 1"` (pokecrystal
  `ram/wram.asm:1918-2200`) branches have a member strictly smaller than the union's
  largest member (true "union slack") was not computed — this requires summing each
  branch's declared bytes and diffing against the union max, which is mechanical but was
  not done here for lack of time budget; flagging as a concrete, bounded follow-up.
- pokegold's SRAM section map beyond "Scratch"/"SRAM Bank 0" (Backup Save 1/2/3, Boxes,
  Battle Tower) was read structurally in `pret_gen2_symbols.md` §10 but not re-audited
  here for unlabeled `ds N` padding; the ticket's "SRAM Scratch / unused bank-0 areas"
  instruction is satisfied only for `sScratch` above.
- No `.sym`/build exists for either repo in this pass (`pret_gen2_symbols.md` confirms
  the same), so every address cited from `data/pret_syms.json` here is corroborating, not
  proof, pending ticket 11.
- Whether a Gen 2 mailbox could instead live in **WRAMX with an explicit bank-swap
  convention** (rather than requiring WRAM0) was not explored — Gen 1 never needed this
  discipline because it has no banked WRAM, so there is no Gen 1 precedent to port, and it
  would need its own design pass against the DelayFrame/IRQ stack shape in
  `codex_checkpoint_and_linktrade.md` §A.
