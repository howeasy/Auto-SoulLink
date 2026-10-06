# P1-HOOKS — Gen 2 companion overlay -> Polished Crystal v3.2.3

Port investigation for `tools/build_gen2_companion.py` + `patch/gen2/src/*.asm` (the vanilla
pret/pokecrystal overlay) onto **Polished Crystal v3.2.3**.

| what | path |
|---|---|
| overlay builder | `F:/slink-work/wt/polished/tools/build_gen2_companion.py` |
| overlay asm | `F:/slink-work/wt/polished/patch/gen2/src/*.asm`, `patch/gb/slink_abi.inc` |
| Polished source | `F:/slink-work/cache/polished/src` (tag v3.2.3, read-only) |
| Polished link symbols | `F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym` (70 172 symbols) |
| vanilla link symbols (comparison only) | `data/gen2/pokecrystal.sym`, `data/gen2/pokegold.sym` |

Vanilla addresses are read out of `data/gen2/pokecrystal.sym` unless marked G/S. "P" below means
the Polished `.sym`.

**Verdicts** — `same` (label, meaning and matched text all unchanged; address moved) / `renamed`
(same thing, new label) / `moved` (same thing, different address *and* a different enclosing region,
e.g. WRAM0 -> HRAM) / `different` (exists and reachable, but the current same-size or
same-semantics edit does not port) / `absent` (no counterpart in v3.2.3) / `UNVERIFIED`.

---

## 1. Headline

The overlay is **not** a set of re-pointings. Of the 18 distinct hook/edit sites in
`build_gen2_companion.py`, **4 port unchanged**, **7 port as a rename/re-anchor with the byte budget
intact**, and **7 are different or gone**. Three structural facts dominate:

1. **There is no free ROM bank.** Vanilla Crystal has an empty bank `$75` and Gold/Silver an empty
   `$13` — `patch/gen2/src/slink.asm` asserts exactly that and is the reason the overlay can insist on
   growing only its own bank. Polished v3.2.3 is a 2 MiB ROM (banks `$00`-`$7F`) and fills banks
   `$01`-`$7D` to within 1-4 bytes of `$7FFF`. Only banks **`$7E`** and **`$7F`** are wholly unused
   (16 KiB each of `$FF` filler), plus a 660-byte tail on `$7D`. See §4.
2. **The mailbox anchor is gone and a better-published one exists.** Vanilla's fixed span
   `WRAM0[$CFD8]` sat in the gap after `wSecondsSince`/`wDaysSince`. Polished moved the clock into
   the `Options` block at `$CFF0`-`$CFFC` (`wSecondsSince` `00:cff8`, `wDaysSince` `00:cffb`) and now
   publishes an explicitly free `SECTION "Unused", WRAM0` of **69 bytes** at `$C60B`-`$C64F`,
   comment and all: *"it's free real estate"*. See §5.
3. **`wScriptVar` moved to HRAM and doubled.** `phone.asm`'s script hand-off depends on it; Polished
   has `hScriptVar:: dw` at `$FF85`. See §3.4.

Two of the four unchanged hooks — the title-screen `call EnableLCD` and the main-menu
`call SetUpMenu` — survive because Polished kept the vanilla *text*, not because it kept vanilla's
structure. Both sit in rewritten files and both will move again on the next Polished release.

---

## 2. Hook / edit sites in `tools/build_gen2_companion.py`

Ordered as `apply_overlay()` executes them.

| # | vanilla site (file:anchor) | what it does | Polished equivalent (file:line, symbol + address) | verdict | port note |
|---|---|---|---|---|---|
| 1 | `MAIN_ANCHORS` (`:228`) — `'INCLUDE "engine/events/odd_egg.asm"\n\n\nSECTION "Stadium 2 Checksums"'`; G/S variant ends at `data/credits_strings.asm` | inject `INCLUDE "engine/slink/*.asm"` above the Stadium checksum section | **no counterpart.** Polished `main.asm` has no Stadium section; it ends `SECTION "LureMenu", ROMX` / `INCLUDE "engine/menus/lure_menu.asm"` | **different** | Re-anchor. Better: every overlay file already opens with its own `SECTION "…", ROMX, BANK[…]`, so copy them into `engine/slink/` and add **one** include line. Only `panel_start.asm` genuinely needs to be inside bank 4. |
| 2 | `TITLE_ANCHOR = "\tcall EnableLCD\n"` (`:93`), counted in `engine/movie/title.asm` | same-size `call` operand rewrite to the ROM0 title bridge | `engine/movie/title.asm:179` `call EnableLCD` — **exactly one** occurrence in that file. `EnableLCD` itself moved `00:058a` -> `00:24da` | **same** | Keep the literal anchor and the same-size discipline. Only `verify_title_hook`'s `_TitleScreen`/`TitleScreen` branch and its "next global symbol in bank" heuristic need rewriting (§6). |
| 3 | `TITLE_SHEAR_EDITS["engine/movie/title.asm"]` (`:170` and two siblings): `ld b, 80 / 2`, `ld hl, wLYOverrides + 80`, `ld bc, wLYOverridesEnd - (wLYOverrides + 80)` | widen Crystal's logo-entrance shear 80 -> 88 lines so the SoulLink band shears with the logo | **absent.** All three literals have **zero** hits in the Polished tree. Polished no longer pre-bakes the initial `wLYOverrides`; it arms the STAT-interrupt LY trick instead (`engine/movie/title.asm:170` `set B_IE_STAT, [hl]`) | **absent** | Drop these three edits. The Crystal-only band placement has to be re-derived against Polished's new title screen anyway (§6). |
| 4 | `TITLE_SHEAR_EDITS["engine/menus/intro_menu.asm"]`: `ld bc, 8 * 10 ; logo height`, `ld b, 8 * 10 / 2 ; logo height / 2` | the other half of the shear | `engine/menus/intro_menu.asm:1194` and `:1203` — **both literals present, verbatim, once each**, inside `TitleScreenEntrance:` (`intro_menu.asm:1181`) | **same** | 8*11 = 88 and 8*11/2 = 44 are both one-byte immediates, so the same-size edit holds unchanged. |
| 5 | `MAIN_MENU_ANCHOR = "MainMenuJoypadLoop:\n\tcall SetUpMenu\n"` (`:151`) plus `text.count("call SetUpMenu") != 1` | same-size `call` operand rewrite to the ROM0 version bridge | `engine/menus/main_menu.asm:104` `MainMenuJoypadLoop:` / `:105` `call SetUpMenu` — adjacent, literal anchor matches byte-for-byte. Label moved to `12:43ca` | **same** | Anchor survives verbatim. `SetUpMenu` is at `00:19a0`. |
| 6 | `_start_menu_text()` edit 1 (`:272`): `"\tconst STARTMENUITEM_QUIT     ; 8\n"` | declare `STARTMENUITEM_SLINK ; 9` | `engine/menus/start_menu.asm:11` `const STARTMENUITEM_QUIT     ; 8` — **exact text match** | **same** | Unchanged. Polished's START menu is still bank `$4` (`StartMenu 04:6059`, `StartMenu_Quit 04:6267`), so `panel_start.asm`'s `ASSERT BANK(...) == 4` still holds. |
| 7 | `_start_menu_text()` edit 2: `"\tdw StartMenu_Quit,     .QuitString,     .QuitDesc\n"` | append the SLINK row to the item table | `engine/menus/start_menu.asm:171` `dw StartMenu_Quit,     .QuitString` — **no `.QuitDesc` column exists**; the table (`:163`-`:171`) is `dw handler, dw string` pairs only | **different** | Polished dropped the description column. The row becomes `dw SlinkStartMenuEntry, SlinkMenuString`, and `SlinkMenuDesc` (and the `next "status@"` text in `panel_start.asm`) has no consumer. |
| 8 | `_start_menu_text()` edit 3: `"\tld a, STARTMENUITEM_EXIT\n"` | repoint the EXIT choice at the SLINK handler | `engine/menus/start_menu.asm:266` `ld a, STARTMENUITEM_EXIT` — exactly one occurrence | **same** | Unchanged. `ld a, N` is 2 bytes either way. |
| 9 | `_start_menu_text()` tail appends `'\nINCLUDE "engine/slink/panel_start.asm"\n'` to `start_menu.asm` | place the panel entry in the START menu's own bank | `engine/menus/start_menu.asm` is `INCLUDE`d by `main.asm:80` inside `SECTION "bank4", ROMX` (`layout.link:47`) | **same** | Unchanged, *provided* the append still lands inside bank 4 — appending to the end of the included file does. |
| 10 | `_phone_table_text()` (`:142`): `anchor = "\tld hl, SpecialPhoneCallList\n"`, `text.count(anchor) != 2` -> fail | repoint both native pointer loads at the SLink table | `engine/phone/phone.asm:168` and `:212` — **exactly two** `ld hl, SpecialPhoneCallList` | **same** | Load count unchanged. Row stride still hard-coded `ld a, 6 / rst AddNTimes` (`:169`, `:213`). |
| 11 | `CALLER_NAME_ANCHOR` (`:134`): `"GetCallerName:\n\tld a, c\n\tand a\n\tjr z, .NotTrainer\n\n\tcall Phone_GetTrainerName\n"` | 4-byte entry rewrite: `jp SlinkPhoneCallerName` + `nop` | **renamed and reshaped.** `GetCallerClassAndName:` at `engine/phone/phone.asm:376`, entered as `ld h,d` / `ld l,e` / `ld a,b` / `call GetCallerTrainerClass` / `ld a,c` / `and a` / `jr z, .NotTrainer`, and the trainer name is fetched with `farcall GetTrainerName` (`:387`) | **different** | Both the label *and* the first two instructions differ, so the anchor cannot match. A same-size window still exists: bytes 377-382 are 8 bytes (`ld h,d` 1 + `ld l,e` 1 + `ld a,b` 1 + `call` 3 + `ld a,c` 1 + `and a` 1). Replace with `jp` + 5 `nop` and have the bridge replay the six instructions. Note Polished then prints `':'` + the trainer *class* (`:393`-`:400`), so PHONE-NAMES' "no colon" behaviour becomes a deliberate divergence. |
| 12 | `_trade_receptionist_text()` (`:103`): the `object_event  5,  2, SPRITE_LINK_RECEPTIONIST, …` line in `maps/Pokecenter2F.asm` | rewrite the last field `LinkReceptionistScript_Trade` -> `SlinkTradeReceptionistScript` | `maps/Pokecenter2F.asm:21` — same object, same column, **but Polished dropped the colour field**: vanilla `0, 0, -1, -1, PAL_NPC_GREEN, OBJECTTYPE_SCRIPT` vs Polished `0, 0, -1, 0, OBJECTTYPE_SCRIPT`. Still exactly one such line | **different** (anchor text only) | The *edit* is still a 2-byte script-pointer rewrite and still occurs once; only the matched literal changes. `LinkReceptionistScript_Trade` moved from bank `$64` to `24:7601`, so `verify_trade_hook`'s hard-coded `(bank, address, original)` triple must be re-derived. |
| 13 | `trade_export_text()`: `EXPORT` of `LinkReceptionistScript_Trade`, `Script_TradeCenterClosed`, `Text_*`; `NextOverworldFrame`; `Link_SaveGame`; `BackupGSBallFlag` (`mobile/mobile_41.asm`) | expose labels across object files; emits no ROM bytes | all five trade text/script labels exist; `NextOverworldFrame 25:5185`, `Link_SaveGame 05:46ea`. **`BackupGSBallFlag` absent**, and `mobile/mobile_41.asm` does not exist (no Mobile in Polished) | **renamed x4, absent x1** | Drop the `BackupGSBallFlag` export and the `farcall BackupGSBallFlag` in `trade_commit.asm`. Polished's own `LinkTrade` calls `farcall SaveAfterLinkTrade` and nothing after it. |
| 14 | `apply_delay_hook()`: `DELAY_ANCHOR` (`:242`) `'DelayFrame::\n; Wait for one frame\n\tld a, 1\n\tld [wVBlankOccurred], a\n'` | replace the 5-byte lead-in with `call SlinkDelayFrameBridge` + 2 `nop` | **textually absent.** Polished `home/delay.asm:33` `DelayFrame::` leads `ldh a, [rLY]` / `ldh [hDelayFrameLY], a` (`:36`) / `xor a` / `ldh [hVBlankOccurred], a` (`:38`) — **7 bytes**, and the flag is `hVBlankOccurred` in HRAM (`00:ff8f`), not `wVBlankOccurred` in WRAM0 | **different** | Better budget than vanilla: 7 bytes for a 3-byte `call`. Replace all four instructions with `call SlinkDelayFrameBridge` + 4 `nop` and move the four displaced instructions to the top of the bridge so native semantics are byte-identical. **A 5-byte patch truncates `ldh [hVBlankOccurred], a` and `DelayFrame` returns immediately on ~7 of every 8 frames** — this is the one edit that must be right first, because every menu, text box and overworld frame goes through it. |
| 15 | `_reset_sound_text()`: `RESET_ANCHORS` (`:252`) `"Reset::\n\tdi\n\tcall InitSound\n"` | locate Reset's start | `home/init.asm:1` `SoftReset::` / `:2` `di` / `:3` `call InitSound` — **the `di` + `call InitSound` pair is identical**; only the label changed | **renamed** | Trivial anchor edit. |
| 16 | `RESET_WAIT_ANCHOR` (`:253`) `"\tld c, 32\n\tcall DelayFrames\n\n\tjr Init\n"` | replace `call DelayFrames` with the reset-sound bridge, keeping C | `home/init.asm:16` `ld c, 3` / `:17` `call DelayFrames` / `:19` `jr Init` — **same instruction shapes** (`ld c, N` is 2 bytes either way; 3-frame wait, not 32) | **same size, different text** | Anchor needs `32` -> `3`. The byte budget, which is all `SlinkResetSoundBridge` depends on, is unchanged. |
| 17 | `sfx.asm`: `ASSERT wAudioEnd <= wSlinkMailbox` — proves `InitSound`'s WRAM clear cannot reach the mailbox | collision proof | `wAudio`/`wAudioEnd` **absent**. Polished's audio RAM is `wMusic 00:cb7e` … `wChannels 00:cb7f` / `wChannelsEnd 00:ccc0` / `wMusicEnd 00:ccc2`, in WRAM0 | **absent / must be rewritten** | The ordering assertion becomes a non-overlap assertion: `$CCC0 > $C64F`, so the audio clear and the proposed mailbox do not intersect — but `wAudioEnd <= wSlinkMailbox` is now **false** and would abort the build. |
| 18 | `trade_dispatch.asm`: hard-coded stack fingerprint — `BANK(NextOverworldFrame)` at `sp+5`, then `LOW/HIGH(DelayFrame + 3)`, `LOW/HIGH(DelayFrames + 3)`, `LOW/HIGH(NextOverworldFrame + 9)` | prove the service is only reached from the idle overworld's own frame wait | all four symbols exist (`NextOverworldFrame 25:5185`, `DelayFrame 00:0da8`, `DelayFrames 00:0da1`) but every address and every `sp+` offset differs, and Polished's caller chain runs through `farjp AnimateTitleCrystal` and a scene jumptable rather than vanilla's straight calls | **UNVERIFIED** | Must be re-measured. The most fragile thing in the overlay, and it has no static proof. |

---

## 3. Native symbols the overlay reads or writes

### 3.1 `slink.asm` — the main-thread service

| symbol | vanilla | Polished | verdict | note |
|---|---|---|---|---|
| `wVBlankOccurred` | `00:cfb3` (WRAM0) | `hVBlankOccurred 00:ff8f` (HRAM) | **moved** | The bridge now uses `ldh`. It lives in a ROM0 section, so that is fine. |
| `hVBlankCounter` | `00:ff9b` | `00:ff8e` | **same** | Clock source for `SLINK_OFS_FRAME_COUNTER` unchanged in kind. |
| `hROMBank` | `00:ff9d` | `00:ff87` | **same** | |
| `wSlinkMailbox` | fixed `WRAM0[$CFD8]`, 40 B | **no fixed span exists** | **moved** | §5. |
| `Bankswitch` | `00:0010` | `00:0008` | **same** | |
| `SLINK_SERVICE_BANK` | `$75` (C) / `$13` (G,S) | **`$7E`** (proposed) | **different** | §4. |

### 3.2 `sfx.asm`

| symbol | vanilla | Polished | verdict |
|---|---|---|---|
| `CheckSFX` | `00:3dde` | `00:3ac6` | **same** |
| `PlaySFX` | `00:3c23` | `00:39bd` | **same** |
| `wMusicFade` | `00:c2a7` | `00:ccb2` | **same** |
| `SFX_ITEM` / `SFX_WRONG` / `SFX_BUMP` / `SFX_READ_TEXT_2` | `$01`/`$19`/`$24`/`$08` (asserted) | **UNVERIFIED** — `src/constants/sound_constants.asm` not opened | **UNVERIFIED** |
| `wAudioEnd` | `00:c2c0` | absent | **absent** — §2 row 17 |
| `VBLANK_NORMAL` | a value compared with `hVBlank` | `hVBlank 00:ff8d` is now a **0-8 vblank mode selector** indexing a dispatch table | **different** — `cp VBLANK_NORMAL` in `sfx.asm` and `trade_dispatch.asm` must be re-derived |

### 3.3 `panel.asm` / `panel_start.asm`

| symbol | vanilla | Polished | verdict |
|---|---|---|---|
| `hInMenu` | `00:ffaa` | `00:ff9a` | **same** |
| `hJoyDown` / `hJoyPressed` | `00:ffa8` / `00:ffa7` | `00:ff98` / `00:ff97` | **same** |
| `hBGMapMode` | `00:ffd4` | `00:ffbe` | **same** |
| `hCGB` | `00:ffe6` | `00:ffd5` | **same** |
| `DelayFrame` / `JoyTextDelay` | `00:045a` / `00:0a57` | `00:0da8` / `00:07c3` | **same** |
| `FadeToMenu` | `00:2b29` | `00:280b` | **same** |
| `ClearBGPalettes` | `00:31f3` | `00:0d8f` | **same** |
| `GetSGBLayout` | `00:3340` | **absent** | **absent** — Polished has `GetCGBLayout 00:004c` / `GetMemCGBLayout 00:004b`; the SGB super-mode layout call has no counterpart, so `ld b, SCGB_DIPLOMA / call GetSGBLayout` in `panel.asm` and in `trade_commit.asm` needs replacing. **UNVERIFIED** which call is right. |
| `WaitBGMap2` | `00:3200` | **absent** | **absent** |
| `ClearTilemap` | `00:0fc8` | **absent by that spelling** | **renamed** — Polished writes `ClearTileMap` (`home/delay.asm:5` `ClearBGPalettes:: call ClearPalettes`). Treat as renamed pending a read of the definition. |
| `wAttrmap` | `00:cdd9` | `00:c308` | **moved** — `wTilemap`/`wAttrmap` are now `$C1A0`/`$C308`. The `SCREEN_AREA` `ByteFill` still works. |
| `PlaceString` / `ByteFill` | `00:1078` / `00:3041` | `00:0030` / `00:0028` | **same** |
| START-menu bank 4 | `ASSERT BANK(...) == 4` | `StartMenu 04:6059` | **same** |

### 3.4 `phone.asm`

| symbol | vanilla | Polished | verdict | note |
|---|---|---|---|---|
| `SpecialPhoneCallList` | `24:4188`, **8 rows x 6 B** | `24:4506`, **12 rows x 6 B** | **different (size)** | Stride unchanged (`dw cond / db contact / dba script` from the `specialcall` MACRO; `ld a, 6 / rst AddNTimes` at `phone.asm:169`/`:213`). Row count is a constant (`NUM_SPECIALCALLS`, `constants/phone_constants.asm:58`) and must be read from there, not hardcoded. **`SPECIALCALL_SLINK EQU 9` now aliases a native row.** |
| `CheckSpecialPhoneCall` / `.DoSpecialPhoneCall` | `24:4136` / local | `24:40bc` / `phone.asm:207` | **same** | Polished's copy indexes 1-based (`dec a`, `:165`-`:168`), same as vanilla. |
| `SpecialCallOnlyWhenOutside` / `SpecialCallWhereverYouAre` | `24:4188`/`24:4197` | `24:4109`/`24:4116` | **same** | |
| `GetCallerName` / `Phone_GetTrainerName` | `24:43a9` | **absent** -> `GetCallerClassAndName:` `phone.asm:376`, `GetTrainerName 07:41c8`, `GetTrainerClassName 00:2e35`, `GetCallerTrainerClass 24:42af` | **renamed** | §2 row 11. |
| `wSpecialPhoneCallID` | `01:dc31` | `01:dc6b` | **same** | Still a byte, 1-based. |
| `wCallerContact` + `PHONE_CONTACT_SCRIPT2_BANK` / `_ADDR` | `01:d03f` | `01:d03f`; offsets **identical** (`constants/phone_constants.asm:71`-`:72`) | **same** | The ninth-row guard ports verbatim. |
| **`wScriptVar`** | `00:c2dd`, 1 byte, WRAM0 | **`hScriptVar:: dw`, `$FF85`, HRAM** (`ram/hram.asm:3`) | **moved + widened** | `phone.asm` writes it and the script reads it back with `ifequal`. Polished's script VM also gained `setval` / `readmem` / `writemem` / `loadmem` opcodes that can hand a value back **without** a shared byte — the cleaner port; prefer it. |
| **`wUnusedMapBuffer` / `wUnusedMapBufferEnd`** | `00:c7e8` / `00:c800`, 24 B, never read, cleared by vanilla's `HandleNewMap` | **absent** (zero hits tree-wide) | **absent** | The 24-byte PHONE-NAMES staging record loses its home *and* its clear-on-map-change guarantee. §5.1 proposes a reserved sub-span; **UNVERIFIED** that nothing else writes it. |
| `wScriptRunning` | `01:d438` | `01:d437` | **same** | |
| `wLinkMode` | `00:c2dc` | `00:cec1` | **same** | |
| `wPokegearFlags` / `POKEGEAR_PHONE_CARD_F` | present / bit 6 | present `01:d9d8` / **`POKEGEAR_PHONE_CARD_F` is bit 2** (`constants/ram_constants.asm:303`) | **different (value)** | `bit POKEGEAR_PHONE_CARD_F, a` is symbolic so it compiles, but the *meaning* of the gate changed and must be re-read. |
| `wStringBuffer3/4/5` | `01:d099`/`d0ac`/`d0bf` | `01:d09f`/`d0b2`/`d0c5` | **same** | |
| `wNamedObjectIndex`, `GetPokemonName`, `PlaceString` | `01:d265`, `00:343b`, `00:1078` | `01:d26b`, `00:2dcf`, `00:0030` | **same** | |
| `ElmPhoneCallerScript` / `BikeShopPhoneCallerScript` / `MomPhoneLectureScript` | `2f:5081` / `28:4b09` / `2f:4fb1` | **`ElmPhoneCallerScript` absent**; `BikeShopPhoneCallerScript 28:4a2f`; `MomPhoneLectureScript 2f:4ef6` | **absent x1, same x2** | The eight native rows copied verbatim into `SlinkSpecialPhoneCallList` must be re-sourced from `data/phone/special_calls.asm`; at least one script label no longer exists. |
| `PHONE_00`, `PHONECONTACT_*`, `TRAINER_NONE`, `NonTrainerCallerNames` | present | present (`NonTrainerCallerNames 24:42de`) | **same** | |

### 3.5 `trade_*.asm`

Struct geometry first, because three `ASSERT`s depend on it — and they turn out **fine**:

| constant | vanilla | Polished | verdict |
|---|---|---|---|
| `PARTYMON_STRUCT_LENGTH` | 48 (asserted) | **48** — `wPartyMon1 01:dcd6`, `wPartyMon2 01:dd06`, `wPartyMon6 01:ddc6` -> stride `$30` | **same** |
| `NAME_LENGTH` / `MON_NAME_LENGTH` | 11 / 11 | 11 / 11 (`constants/text_constants.asm:2`, `:5`) | **same** |
| `PARTY_LENGTH` | 6 | 6 (`constants/pokemon_data_constants.asm:287`) | **same** |
| `PLAYER_NAME_LENGTH` | *(no such constant; player names live inside `NAME_LENGTH`)* | **8** (`constants/text_constants.asm:3`) | **different** — `trade_commit.asm`/`.PrepareAnimation` copies `wPlayerName -> wPlayerTrademonSenderName` and `wOTPlayerName -> wOTTrademonSenderName` with `bc NAME_LENGTH` (11). In Polished a player name is 7 glyphs + terminator, so an 11-byte copy **overruns by 2 bytes into the next field**. Must become `bc PLAYER_NAME_LENGTH`. A real latent bug the port introduces if missed. |
| `NUM_POKEMON` | 251 | `NUM_POKEMON EQU NUM_SPECIES - (2 * HIGH(NUM_SPECIES))` with `NUM_SPECIES EQU const_value - 1 ; 123` -> **113** | **different** — every `cp NUM_POKEMON + 1` species-range guard changes value, and Polished's species ids are dex-ordered, not NatDex-ordered. |

The struct's *contents* changed even though its size did not: Polished packs 6 EVs, packs 4 IVs into 2 bytes
(`MON_DVS rb NUM_STATS / 2`), folds gender/ability/nature/form/is-egg into the personality word
(`constants/pokemon_data_constants.asm:159`), and stores level plus a 3-byte caught-data block.
Consequences:

- `trade_snapshot.asm`'s "70 bytes must not change" preimage (48-byte struct + 11 OT + 11 nickname) is still
  70 bytes and still structurally right, but the byte *meaning* differs — Polished writes level/stats into the
  struct where vanilla computed them, so a native trade can legitimately mutate bytes vanilla never touched.
  The refusal check must be re-derived, not reused.
- `wPlayerTrademonCaughtData 00:c550` / `wOTTrademonCaughtData 00:c585` exist, but `trade_commit.asm` fills
  them via `farcall GetCaughtGender` and **`GetCaughtGender` is absent**. Gender now lives in `MON_GENDER`, an
  alias of `personality + 1`. The caught-data byte must be reconstructed from the personality word.

| symbol | vanilla | Polished | verdict | note |
|---|---|---|---|---|
| `LinkReceptionistScript_Trade` | `64:689d` | `24:7601` | **moved** | |
| `Script_TradeCenterClosed`, `Text_TradeReceptionistIntro`, `Text_MustSaveGame`, `Text_PleaseWait`, `Text_PleaseComeAgain` | bank `$64` | `24:76bc`, `24:7775`, `24:77c2`, `24:77e1`, `24:7822` | **same** | all five exist and are re-exportable |
| receptionist script *body* | vanilla control flow, `special TryQuickSave`, Mobile branch | `maps/Pokecenter2F.asm:78` uses the **rewritten dialect**: `iffalsefwd` / `iftruefwd` / `iffalse_endtext` / `warpcheck` / `readmem` / `scall`; `special Special_TryQuickSave` (`:99`); **no Mobile branch**; plus a link-cable handshake, version-mismatch and room-compatibility gauntlet (`:90`-`:119`) | **different** | `SlinkTradeReceptionistScript` cannot be a light edit. Two options: (a) branch after `Pokecenter2F.asm:101`'s second `writetext Text_PleaseWait` with `callasm SlinkTradeEntry` — what the vanilla overlay does; or (b) reimplement. (a) still works: `callasm` exists with identical encoding, and the forced quick-save at `:99` still precedes it. Prefer (a). |
| `TryQuickSave` | `0a:5e66` | `Special_TryQuickSave 0a:4e46` | **renamed** | |
| `Link_SaveGame` / `SaveAfterLinkTrade` | `05:4ab2` / `05:4a58` | `05:46ea` / `05:46cc` | **same** | Native `LinkTrade` calls `SaveAfterLinkTrade` and **nothing after it**. |
| `BackupGSBallFlag` | `41:6187` | **absent** | **absent** | Delete the `farcall` and its `EXPORT`. |
| `SelectTradeOrDayCareMon`, `PARTYMENUACTION_GIVE_MON` | `14:401d` | `14:4002` | **same** | |
| `RemoveMonFromPartyOrBox` | `03:6039` | **`RemoveMonFromParty 03:5d10`** (`engine/pokemon/move_mon.asm:894`) | **renamed** | Semantics narrowed — "or Box" is gone. **UNVERIFIED** whether Polished still supports withdrawing from a box mid-trade. |
| `AddTempmonToParty` | `03:5a96` | **`AddTempMonToParty 03:5980`** (`engine/pokemon/move_mon.asm:448`) | **renamed** | |
| `TradeAnimation` / `TradeAnimationPlayer2` | `0a:4f24` / `0a:4f63` | `0a:5290` / `0a:52de` | **same** | |
| `EvolvePokemon` / `wForceEvolution` | `10:61d8` / `01:d1e9` | `06:4000` / `01:d1ef` | **same** | bank `$10` (Pokedex) -> `$06` (Evolution). |
| `wOTPartyCount` / `wOTPartyMon1` / `wOTPartyMon2` / `wOTPartyMonOTs` / `wOTPartyMonNicknames` / `wOTPlayerName` | `01:d280`… | `01:d283`, `01:d28b`, `01:d2bb`, `01:d3ab`, `01:d3ed`, `01:d276` | **same** | 48-byte stride holds on the OT side too. |
| `wOTPartySpecies` | `01:d281` | **absent** | **absent** | The one-byte species list beside `wOTPartyCount` is gone; `trade_commit.asm` reads it 3x and `trade_service.asm` once. Polished presumably reads species from `wOTPartyMon1`'s first byte — **UNVERIFIED**, must be read off the new OT-staging definition. |
| `wPartySpecies` | `01:dcd8` | **absent** (one commented-out reference at `engine/overworld/events.asm:1164`) | **absent** | `SlinkTradeCheckParty`'s "species list whose `$FF` terminator is not at `wPartyCount`" bug-contest discriminator loses its input. A replacement is needed — **UNVERIFIED**. |
| the bulk: `wPartyMon1ID/DVs/Species`, `wPartyMonOTs`, `wPartyMonNicknames`, `wPlayerTrademon*`, `wOTTrademon*`, `wTempMonSpecies`, `GetPartyLocation`, `SkipNames`, `wCurTradePartyMon`, `wCurOTTradePartyMon`, `wCurPartyMon`, `wPokemonWithdrawDepositParameter`, `wStateFlags`, `wSpriteUpdatesEnabled`, `wJumptableIndex`, `wTradeDialog`, `wStatusFlags2`, `wSavedAtLeastOnce`, `wGameLogicPaused`, `wLinkMode`, `wBattleMode`, `wMapStatus`, `wMapEventStatus`, `wPlayerStepFlags`, `wScriptMode`, `wNamedObjectIndex`, `sPartyMail 00:a600` | all present | **all present**, addresses moved | **same** (as a set) | This is most of `trade_service.asm` and `trade_commit.asm`; every individual field exists. `sPartyMail 00:a600` is unchanged, so `.ShiftMail`'s stride math holds — except **`OpenSRAM` is absent** (only `CloseSRAM 00:2a94`); the enable/disable pair was split. **UNVERIFIED** which routine now enables SRAM. |
| `GetCaughtGender` | `13:7301` | **absent** | **absent** | see above |
| `CheckPartyForMail` | — | `0a:5274` (new native guard vanilla lacked) | **new** | Polished's receptionist calls `callasm CheckPartyForMail` at `Pokecenter2F.asm:88` before offering a trade. `SlinkTradeCheckIncoming` / `SlinkTradeItemAllowed` partially duplicate this; align them rather than shipping two divergent mail policies. |
| `NextOverworldFrame` | `25:67b7` | `25:5185` | **same** (label) | But see §2 row 18: the *stack fingerprint* is unverified. |

---

## 4. Where new code can be INCLUDEd, and where the service bank goes

### 4.1 INCLUDE placement

Polished's `main.asm` is a flat list of `SECTION … / INCLUDE …` pairs and has **no Stadium-checksums tail
to anchor on**. Two workable shapes:

- **Preferred:** stop depending on `main.asm`. Every overlay file already opens with its own
  `SECTION "…", ROMX, BANK[…]`, so copy them into `engine/slink/` and add **one** include (or one
  `SECTION "Slink", ROMX`) at the tail. Only `panel_start.asm` genuinely needs to be *inside* bank 4, and
  it already asserts that, so it keeps its append-to-`start_menu.asm` trick (§2 row 9).
- Otherwise the anchor becomes `SECTION "LureMenu", ROMX` + `INCLUDE "engine/menus/lure_menu.asm"` — the
  current tail. Same maintenance profile as the Stadium anchor (both move with the upstream release), no worse.

### 4.2 Why the service bank cannot be `$75` or `$13`

Vanilla's asserts hard-code an **empty** bank because the overlay refuses to grow an existing one. Polished
has none. Evidence, from the released ROM itself (`FILLER := 0xff`, `src/Makefile:12`;
`rgblink … -l layout.link -o $@`, `src/Makefile:160`), scanning each 16 KiB bank for its trailing `$FF` run:

| bank | trailing `$FF` in the released `.gbc` |
|---|---|
| `$01`-`$7C` | 1-4 bytes. Effectively full. |
| `$7D` | 660 bytes (`$7D6C`-`$7FFF`) |
| **`$7E`** | **16 384 bytes — entirely `$FF`** |
| **`$7F`** | **16 384 bytes — entirely `$FF`** |

Cross-check: no symbol in `polishedcrystal-3.2.3.sym` has bank `$7E` or `$7F`, and the highest bank carrying
any symbol is `$7D`. Note this scan is a **lower bound** on free space (real data can also be `$FF`); it is
exact for the two all-`$FF` banks because nothing at all is there.

**Recommendation: `SLINK_SERVICE_BANK EQU $7E`.** 16 KiB is roughly 4x what the overlay needs, it is
addressable inside the released 2 MiB image (rgbfix `-r 3`, MBC3+RAM+BATTERY), and it preserves the
"grow only my own bank" invariant the vanilla asserts were written to protect. `$7F` is the natural second
choice and a natural overflow.

**UNVERIFIED:** that `rgblink -Weverything -l layout.link` accepts `BANK[$7E]` with no `layout.link` entry.
`layout.link` pins only banks `$01`-`$15`, `$20`-`$34`, `$37`-`$3A`, `$3C`, `$3E`, `$3F`, `$41`, `$42`, `$48`,
`$49`; `$7E` is not among them, so it should land as an unpinned section — but only a link proves it. The
authoritative check is `tools/bankends $(ROM).map`; no `.map` ships in the cache.

### 4.3 The other overlay sections that must move

| overlay section | vanilla | note |
|---|---|---|
| `Slink DelayFrame Bridge` (currently `ROM0[$0063]`), `Slink Sound Reset` (`ROM0[$0080]`), `Slink Main Menu Bridge`, `Slink Title Bridge` | ROM0 fixed | **ROM0 `$0063` is taken.** Polished's `SECTION "High Home", ROM0[$005b]` (`home/header.asm:156`, `layout.link:30`-`:31`) includes `home/jumptable.asm`, which runs `OffsetStackJumpTable::` (`:1`) through `_hl_::` (`:21`, `00:006d`, last byte `$006f`). **ROM0 `$0070`-`$00FF` is free (144 bytes)** before the next `org`. Re-address every fixed ROM0 `SECTION` to `$0070`+. Also: the vanilla comment about a joypad vector at `$0060`-`$0062` is dead — Polished comments that vector out entirely (`JOYPAD is never enabled`). |
| `Slink Special Calls`, `Slink Caller Name` | bank `$24` | Polished's phone code is **also** bank `$24` (`CheckSpecialPhoneCall 24:40bc`, `NonTrainerCallerNames 24:42de`). Keeping `$24` keeps `verify_phone_hook`'s "ninth row must link in bank 24" gate meaningful — but the native table just grew 8 -> 12 rows, so the bank-fill risk is real. Run `tools/bankends`. |
| `Slink Trade Receptionist` | bank `$64` (C) / `$5c` (G/S) | Polished's receptionist script is bank `$24`. `trade_receptionist.asm` already carries `ASSERT BANK(LinkReceptionistScript_Trade) == SLINK_TRADE_MAP_BANK`, which is the right shape and will fail loudly at link time. |
| `Slink Panel`, `Slink Phone Service`, `Slink Sound Service`, `Slink Trade Service`, `Slink Trade Frame`, `Slink Trade Item Predicate`, `Slink Trade Snapshot`, `Slink Trade Commit`, `Slink Title Band`, `Slink Version` | `SLINK_SERVICE_BANK` | Move wholesale to `$7E`. |

---

## 5. WRAM / HRAM candidates for `wSlinkMailbox`

**Required size: 40 bytes.** `patch/gen2/src/slink_mailbox_crystal.asm:19` declares
`SECTION "SLink Mailbox", WRAM0[$CFD8]` / `ds $CFFF - $CFD8 + 1`. Polished is one ROM, so the Gold/Silver
39-byte variant is irrelevant and `slink_mailbox_goldsilver.asm` drops out of the plan entirely — which also
collapses `slink.asm`'s `IF DEF(_GOLD) || DEF(_SILVER) … ELSE … ENDC` bank/size split to one arm.

### 5.1 WRAM0 — the real candidate: `$C60B`-`$C64F`, 69 bytes

Polished publishes this span explicitly: `src/ram/wram0.asm:883` opens `SECTION "Unused", WRAM0` and line
885 reads, verbatim, `ds 69 ; it's free real estate`. Arithmetic from the link symbols:

- `wFootprintQueue 00:c604` (`ram/wram0.asm:880`, `ds 3 * 2 + 1` = 7 bytes) -> ends `$C60A`
- the next section starts at `wOverworldMapBlocks 00:c650`
- `$C650 - ($C604 + 7) = $45 = 69` — matches the declared `ds 69` exactly

So the span is `$C60B`-`$C64F`, and it is **verified free by the ROM's own linker**, not inferred.
`layout.link:224` places `"Unused"` between `"Footprint Queue"` and `"Misc 1326"`, in that order.

Proposed layout of that single 69-byte reservation:

| offset | size | use |
|---|---|---|
| `$C60B` | 40 | `wSlinkMailbox` (core 14 + trade lease 16 + 2 private sample = 32 used (the "public 30" already contains the lease); 40 reserved to keep the vanilla span's shape) |
| `$C633` | 24 | PHONE-NAMES staging record (replaces `wUnusedMapBuffer`, §3.4) |
| `$C64B`-`$C64F` | 5 | spare |

Why this beats the alternatives:

- **The vanilla anchor is gone.** `wSecondsSince 00:cff8` / `wDaysSince 00:cffb` now live inside the
  `Options` block at `$CFF0`-`$CFFC`, and `$CFFD`-`$CFFF` is `SRAM Access Count` + `Rom Checksum`. There is no
  `$CFD8` gap any more.
- `_Init` clears **all** of WRAM0: `ld hl, wRAM0Start` (`engine/init.asm:48`) /
  `ld bc, wRAM0End - wRAM0Start` (`:49`) / `rst ByteFill`, with `wRAM0Start 00:c000` and `wRAM0End 01:d000`.
  So the mailbox is zeroed on every boot and soft reset — the same lifecycle the vanilla overlay documents,
  and the same reason `sfx.asm` needs its reset-entry latch. **This behaviour is unchanged and must be preserved.**
- `NewGame`'s narrower clear is `ResetWRAM 01:5f4d` — **UNVERIFIED** which span it covers. If it is
  `wRAM0Start`-`wRAM0End` the question is moot; if narrower it must be checked, exactly as the vanilla tail
  comment in `slink.asm` required.
- SRAM is unaffected — this is WRAM0.

### 5.2 The `wAudioEnd` proof, restated for Polished

Vanilla proved safety with `ASSERT wAudioEnd <= wSlinkMailbox`, relying on `InitSound` clearing
`wAudio..wAudioEnd` and the mailbox sitting above it. Polished has no `wAudio`/`wAudioEnd`; the engine's
audio RAM is `wMusic 00:cb7e` .. `wMusicEnd 00:ccc2`, with `_InitSound` clearing `wChannels 00:cb7f` ..
`wChannelsEnd 00:ccc0`. So:

- the ordering assertion is now **false** (`$CCC0 > $C60B`) and will abort the build;
- the *property* still holds, as a **non-overlap** check: `$CCC0 < $C60B` is false and
  `$C60B + 40 = $C633 < $CB7F` is true. Rewrite as `ASSERT wChannelsEnd <= wSlinkMailbox || wSlinkMailbox + SLINK_MAILBOX_SIZE <= wChannels`,
  or simply the second disjunct.

### 5.3 Candidates considered and rejected

| candidate | why not |
|---|---|
| WRAM0 `$C650`+ | occupied from `$C650` by `wOverworldMapBlocks` / `wLinkData` / `wGameboyPrinterRAM` / `wLCDBillsPC1`, running to `wOverworldMapBlocksEnd 00:cb7e`. |
| WRAM0 `$CFF0`+ (`Options`) | the vanilla mailbox's old *neighbourhood* is now live options/clock data. |
| WRAMX bank 2 (`Music Player RAM`, `Sound Stack`, `Pic Animations RAM`, `Sprites Backup`) | only 8 KiB total, shared with the audio engine, and it would require an `rWBK` switch on every access, which the byte-at-a-time mailbox code does not do. |
| HRAM | `hScriptVar $FF85`, `hVBlankCounter $FF8E`, `hVBlankOccurred $FF8F`, `hROMBank $FF87`, `hInMenu`, `hJoy*`, `hBGMapMode`, `hCGB`, `hDelayFrameLY $FFD7` all live there (`layout.link:297` opens the HRAM section). `_Init` clears the **whole** HRAM section and the DMA stack owns the top. 40 bytes does not fit, and IRQ-time corruption is a second, independent hazard. **Rejected.** |
| WRAM0 `$C60B`-`$C64F`, mailbox + phone stage split | **chosen** (§5.1). |

---

## 6. Design consequences that are not "re-point and rebuild"

A hook table alone will not tell you these.

1. **The DelayFrame bridge gains budget and loses its anchor.** Polished's lead-in is 7 bytes, not 5, so the
   patch gets *easier* to place and *more* dangerous to get wrong: a 5-byte patch truncates
   `ldh [hVBlankOccurred], a` and `DelayFrame` returns immediately on ~7 of every 8 frames. Moving the four
   displaced instructions into the bridge is mechanical, but it means the bridge now *is* `DelayFrame`'s
   prologue — the vanilla comment "arm the native wait BEFORE servicing" must survive verbatim, because those
   four instructions are what make it true.
2. **PHONE-NAMES needs a new hand-off.** `wScriptVar` -> `hScriptVar` (HRAM word) is the mechanical port;
   Polished's `setval` / `loadmem` script opcodes are the better one. Either way the
   `ifequal SLINK_CALL_FALLEN, …` chain in `SlinkPhoneCallScript` must be re-expressed.
3. **PHONE-NAMES loses its staging buffer *and* its clear-on-map-change guarantee.** No `wUnusedMapBuffer`
   exists, so a stale 24-byte record could now survive a map change. The cookie + nonce + single-use
   discipline in `phone.asm` stops being belt-and-braces and becomes load-bearing. Re-verify before shipping.
4. **The special-call table grew 8 -> 12.** `SPECIALCALL_SLINK EQU 9` now aliases a native row; it must move
   to 13. `verify_phone_hook`'s `… == 9 * SPECIALCALL_SIZE` and its "copy the native 48-byte eight-row table"
   check must both be re-derived against 12 native rows (72 bytes) from `data/phone/special_calls.asm`.
5. **`StartMenu` lost its description column**, so `SlinkMenuDesc` has no consumer. Delete it, or find the
   new description mechanism.
6. **The title band must be re-derived.** Polished's title screen is a different composition: Suicune frames,
   `vBGMap1`, a palette gradient written at rows 3-9, and a STAT-interrupt LY trick instead of a pre-baked
   `wLYOverrides`. Both the Crystal placement (rows 10-11, tiles 6-14, palette 6, tile ids `$60`-`$7E`) and
   the G/S placement (rows 7-8, `$70`-`$7F`) are stale. Only the *hook* ports.
7. **`verify_symbol_scope` will not port as written.** Its rule — no existing symbol moves except bank 4 — is
   still a fine rule against a Polished baseline, but `verify_title_hook`'s "the routine runs to the next
   global symbol in its bank" heuristic has to survive Polished's label density, and its
   `_TitleScreen`/`TitleScreen` branch collapses to one label (`_TitleScreen`, bank `$35`).
8. **Two verifiers hold hard-coded addresses that are now wrong:** `verify_trade_hook`'s
   `("pokecrystal": (0x64, 0x73b1, 0x689d))` triple, and `verify_phone_hook`'s `$24`-bank + `+ 54` ninth-row
   arithmetic. Both must be computed, not pinned.
9. **`version_identity`'s Stadium tail is meaningless here.** `STADIUM_BYTES = 544` and the `N64PS3` magic check
   describe a Stadium 2 build; Polished has no such table. The canonical-identity masking and the provenance
   hashing must be re-specified from scratch.
10. **`tools/build_gen2_syms.py`'s engine-site receipt** is generated from a pret/pokecrystal build. A Polished
    port needs its own site table, or the Lua-side gate receipts that depend on it lose their basis.

---

## 7. UNVERIFIED

| item | what would settle it |
|---|---|
| `SFX_ITEM` / `SFX_WRONG` / `SFX_BUMP` / `SFX_READ_TEXT_2` still `$01/$19/$24/$08` | read `src/constants/sound_constants.asm` |
| `rgblink` accepts `BANK[$7E]` with no `layout.link` entry | run the Polished build; `tools/bankends $(ROM).map` |
| exact free bytes per bank (the `$FF` scan is a **lower bound**; real data can be `$FF`) | `tools/bankends` on a real `.map`; none is in the cache |
| ~~`ResetWRAM 01:5f4d`'s clear span vs `$C60B`-`$C64F`~~ SETTLED (review cx-4c455434): span 1 is `[$C100,$CB7E)`, so New Game clears the mailbox | - |
| nothing writes `$C633`-`$C64A` between boots (the phone-stage sub-span) | rgblink `.map` section extents for `$C60B`-`$C64F` |
| `trade_dispatch.asm`'s `sp+5` / `sp+12` stack fingerprint against Polished's overworld call chain | instrument or disassemble a Polished build |
| `OpenSRAM`'s replacement (only `CloseSRAM 00:2a94` exists) | grep Polished's `home/sram.asm` for the enable path |
| `RemoveMonFromParty`'s box behaviour (the "OrBox" half) | read `engine/pokemon/move_mon.asm:894` |
| `wOTPartySpecies` / `wPartySpecies` replacements | read Polished's OT-staging and party definitions |
| `GetSGBLayout` / `WaitBGMap2` replacements for `panel.asm` and `trade_commit.asm` | read Polished's tilemap-transfer path |
| `ClearTileMap` spelling (only the vanilla spelling greps empty) | read the definition, not the grep |
| Polished's caller-name suffix (`':'` + trainer class, `phone.asm:393`-`:400`) vs PHONE-NAMES' "no colon" | a decision, not a lookup — but confirm the class string is still wanted |
| trade receptionist branch point after `Pokecenter2F.asm:101` | read the full script to `:119` and its failure branches |

---

## CLAIMS

```json
[
  {
    "path": "F:/slink-work/cache/polished/src/layout.link",
    "line": 30,
    "expect": "org $005b"
  },
  {
    "path": "F:/slink-work/cache/polished/src/layout.link",
    "line": 31,
    "expect": "\"High Home\""
  },
  {
    "path": "F:/slink-work/cache/polished/src/layout.link",
    "line": 224,
    "expect": "\"Unused\""
  },
  {
    "path": "F:/slink-work/cache/polished/src/layout.link",
    "line": 47,
    "expect": "ROMX $04"
  },
  {
    "path": "F:/slink-work/cache/polished/src/layout.link",
    "line": 216,
    "expect": "WRAM0"
  },
  {
    "path": "F:/slink-work/cache/polished/src/layout.link",
    "line": 297,
    "expect": "\"HRAM\""
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/header.asm",
    "line": 156,
    "expect": "SECTION \"High Home\", ROM0[$005b]"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/jumptable.asm",
    "line": 1,
    "expect": "OffsetStackJumpTable::"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/jumptable.asm",
    "line": 21,
    "expect": "_hl_::"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/delay.asm",
    "line": 25,
    "expect": "SFXDelayFrames::"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/delay.asm",
    "line": 33,
    "expect": "DelayFrame::"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/delay.asm",
    "line": 36,
    "expect": "ldh [hDelayFrameLY], a"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/delay.asm",
    "line": 38,
    "expect": "ldh [hVBlankOccurred], a"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/delay.asm",
    "line": 45,
    "expect": "MaybeDelayFrame:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/init.asm",
    "line": 1,
    "expect": "SoftReset::"
  },
  {
    "path": "F:/slink-work/cache/polished/src/home/init.asm",
    "line": 16,
    "expect": "ld c, 3"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/init.asm",
    "line": 48,
    "expect": "ld hl, wRAM0Start"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/init.asm",
    "line": 49,
    "expect": "ld bc, wRAM0End - wRAM0Start"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/movie/title.asm",
    "line": 1,
    "expect": "_TitleScreen:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/movie/title.asm",
    "line": 179,
    "expect": "call EnableLCD"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/movie/title.asm",
    "line": 170,
    "expect": "set B_IE_STAT, [hl]"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/intro_menu.asm",
    "line": 1194,
    "expect": "ld bc, 8 * 10 ; logo height"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/intro_menu.asm",
    "line": 1203,
    "expect": "ld b, 8 * 10 / 2 ; logo height / 2"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/intro_menu.asm",
    "line": 1181,
    "expect": "TitleScreenEntrance:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/main_menu.asm",
    "line": 104,
    "expect": "MainMenuJoypadLoop:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/main_menu.asm",
    "line": 105,
    "expect": "call SetUpMenu"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
    "line": 11,
    "expect": "const STARTMENUITEM_QUIT     ; 8"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
    "line": 171,
    "expect": "dw StartMenu_Quit,     .QuitString"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/start_menu.asm",
    "line": 266,
    "expect": "ld a, STARTMENUITEM_EXIT"
  },
  {
    "path": "F:/slink-work/cache/polished/src/main.asm",
    "line": 80,
    "expect": "INCLUDE \"engine/menus/start_menu.asm\""
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/phone/phone.asm",
    "line": 160,
    "expect": "CheckSpecialPhoneCall::"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/phone/phone.asm",
    "line": 168,
    "expect": "ld hl, SpecialPhoneCallList"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/phone/phone.asm",
    "line": 376,
    "expect": "GetCallerClassAndName:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/phone/phone.asm",
    "line": 387,
    "expect": "farcall GetTrainerName"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/phone_constants.asm",
    "line": 71,
    "expect": "DEF PHONE_CONTACT_SCRIPT2_BANK   rb"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/phone_constants.asm",
    "line": 72,
    "expect": "DEF PHONE_CONTACT_SCRIPT2_ADDR   rw"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/ram_constants.asm",
    "line": 303,
    "expect": "const POKEGEAR_PHONE_CARD_F ; 2"
  },
  {
    "path": "F:/slink-work/cache/polished/src/ram/hram.asm",
    "line": 3,
    "expect": "hScriptVar:: dw"
  },
  {
    "path": "F:/slink-work/cache/polished/src/maps/Pokecenter2F.asm",
    "line": 21,
    "expect": "object_event  5,  2, SPRITE_LINK_RECEPTIONIST, SPRITEMOVEDATA_STANDING_DOWN, 0, 0, -1, 0, OBJECTTYPE_SCRIPT, 0, LinkReceptionistScript_Trade, -1"
  },
  {
    "path": "F:/slink-work/cache/polished/src/maps/Pokecenter2F.asm",
    "line": 78,
    "expect": "LinkReceptionistScript_Trade:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/maps/Pokecenter2F.asm",
    "line": 99,
    "expect": "special Special_TryQuickSave"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm",
    "line": 894,
    "expect": "RemoveMonFromParty:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/pokemon/move_mon.asm",
    "line": 448,
    "expect": "AddTempMonToParty:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/engine/menus/save.asm",
    "line": 36,
    "expect": "SaveAfterLinkTrade:"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/text_constants.asm",
    "line": 2,
    "expect": "DEF NAME_LENGTH        EQU 11"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/text_constants.asm",
    "line": 3,
    "expect": "DEF PLAYER_NAME_LENGTH EQU 8"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/text_constants.asm",
    "line": 5,
    "expect": "DEF MON_NAME_LENGTH    EQU 11"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
    "line": 185,
    "expect": "DEF PARTYMON_STRUCT_LENGTH EQU _RS"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/pokemon_data_constants.asm",
    "line": 287,
    "expect": "DEF PARTY_LENGTH EQU 6"
  },
  {
    "path": "F:/slink-work/cache/polished/src/constants/pokemon_constants.asm",
    "line": 318,
    "expect": "DEF NUM_POKEMON EQU NUM_SPECIES - (2 * HIGH(NUM_SPECIES)) ; 121"
  },
  {
    "path": "F:/slink-work/cache/polished/src/ram/wram0.asm",
    "line": 880,
    "expect": "wFootprintQueue:: ds 3 * 2 + 1"
  },
  {
    "path": "F:/slink-work/cache/polished/src/ram/wram0.asm",
    "line": 883,
    "expect": "SECTION \"Unused\", WRAM0"
  },
  {
    "path": "F:/slink-work/cache/polished/src/ram/wram0.asm",
    "line": 885,
    "expect": "ds 69 ; it's free real estate"
  },
  {
    "path": "F:/slink-work/cache/polished/src/Makefile",
    "line": 12,
    "expect": "FILLER := 0xff"
  },
  {
    "path": "F:/slink-work/cache/polished/src/Makefile",
    "line": 160,
    "expect": "$Q$(RGBLINK) $(RGBLINKFLAGS) -l layout.link -o $@ $(filter %.o,$^)"
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 242,
    "expect": "DELAY_ANCHOR = 'DelayFrame::\\n; Wait for one frame\\n\\tld a, 1\\n\\tld [wVBlankOccurred], a\\n'"
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 134,
    "expect": "CALLER_NAME_ANCHOR = \"GetCallerName:\\n\\tld a, c\\n\\tand a\\n\\tjr z, .NotTrainer\\n\\n\\tcall Phone_GetTrainerName\\n\""
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 151,
    "expect": "MAIN_MENU_ANCHOR = \"MainMenuJoypadLoop:\\n\\tcall SetUpMenu\\n\""
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 93,
    "expect": "TITLE_ANCHOR = \"\\tcall EnableLCD\\n\""
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 272,
    "expect": "(\"\\tconst STARTMENUITEM_QUIT     ; 8\\n\","
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 170,
    "expect": "(\"\\tld b, 80 / 2 ; alternate for 80 lines\\n\", \"\\tld b, 88 / 2 ; alternate for 88 lines (SLink: + the title band)\\n\"),"
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 103,
    "expect": "anchor = (\"\\tobject_event  5,  2, SPRITE_LINK_RECEPTIONIST, SPRITEMOVEDATA_STANDING_DOWN, \""
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 142,
    "expect": "anchor = \"\\tld hl, SpecialPhoneCallList\\n\""
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 253,
    "expect": "RESET_WAIT_ANCHOR = \"\\tld c, 32\\n\\tcall DelayFrames\\n\\n\\tjr Init\\n\""
  },
  {
    "path": "F:/slink-work/wt/polished/tools/build_gen2_companion.py",
    "line": 228,
    "expect": "MAIN_ANCHORS: dict[str, str] = {"
  },
  {
    "path": "F:/slink-work/wt/polished/patch/gen2/src/slink_mailbox_crystal.asm",
    "line": 19,
    "expect": "SECTION \"SLink Mailbox\", WRAM0[$CFD8]"
  },
  {
    "path": "F:/slink-work/wt/polished/patch/gen2/src/slink.asm",
    "line": 28,
    "expect": "SECTION \"SLink DelayFrame Bridge\", ROM0[$0063]"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 287,
    "expect": "00:0da8 DelayFrame"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 34,
    "expect": "00:006d _hl_"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 37,
    "expect": "00:0150 SoftReset"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 70046,
    "expect": "00:ff85 hScriptVar"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 64231,
    "expect": "00:c604 wFootprintQueue"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 64238,
    "expect": "00:c650 wOverworldMapBlocks"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 32325,
    "expect": "35:4000 _TitleScreen"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 12041,
    "expect": "12:43ca MainMenuJoypadLoop"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 22127,
    "expect": "24:4506 SpecialPhoneCallList"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 67524,
    "expect": "01:dcd6 wPartyMon1"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 67571,
    "expect": "01:dd06 wPartyMon2"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 22751,
    "expect": "24:7601 LinkReceptionistScript_Trade"
  },
  {
    "path": "F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.sym",
    "line": 3324,
    "expect": "03:5d10 RemoveMonFromParty"
  }
]
```

## 8. Review addendum (2026-10-04, cx-4c455434): two frame waits

`hVBlankOccurred` is written at exactly five sites tree-wide; the Pokedex input poll (`engine/pokedex/pokedex.asm:3124-3129`) re-implements the lead-in and calls `MaybeDelayFrame` directly, past the 7 bytes the overlay replaces. So the overlay's `FRAME_COUNTER` stops advancing while the Pokedex polls input. Latent: P5a publishes caps 0 and nothing consumes the counter yet. Decide before any capability gates on elapsed frames: sample from the VBlank handler instead (covers every wait), hook `MaybeDelayFrame` too, or scope `FRAME_COUNTER` as not a frame index.


## 9. Reconciliation pass (2026-10-04, cx-e1bb41ed)

Checked the rest of this document against `RAM.md` and `NEWBOX.md` and against
`data/polished/polishedcrystal.sym`. **No statement in HOOKS.md required a supersession marker** —
the frame-hook corrections already landed in §8, and every native/HRAM/SRAM address cited here
matches the built symbol file:

| Symbol | HOOKS.md | `.sym` | |
|---|---|---|---|
| `hVBlankOccurred` | `$FF8F` | `00:ff8f` | agree |
| `hDelayFrameLY` | `$FFD7` | `00:ffd7` | agree |
| `hScriptVar` | `$FF85` | `00:ff85` | agree |
| `hROMBank` | `$FF87` | `00:ff87` | agree |
| `hVBlankCounter` | `$FF8E` | `00:ff8e` | agree |
| `sBackupGameData` | `00:b208` | `00:b208` | agree |
| `sCheckValue1` | `01:a007` | `01:a007` | agree |
| `sChecksum` | `01:ad0d` | `01:ad0d` | agree |

The §7 open-item table is still accurate: its entries (the `trade_dispatch.asm` stack
fingerprint, `OpenSRAM`'s enable path, `RemoveMonFromParty`'s box behaviour, the
`wOTPartySpecies` replacements) are genuinely unmeasured at the time of writing (SUPERSEDED: the dispatch-entry fingerprint was measured in TRADE.md s10.9 and re-planned in s18; the service-internal population remains unmeasured) and are **not** superseded by any later
document. `NEWBOX.md` supplies the SRAM layout HOOKS.md defers to; where the two overlap they agree.

**One finding is recorded elsewhere, not here:** `RAM.md:72` documents `wTextboxFlags` as
`01:CFF4` in both the vanilla and Polished columns, but `polishedcrystal.sym:65521` places it at
`00:cff4`. RAM.md was not edited by this pass (out of scope); see `README.md` §Mismatch.


## 10. Allocation note (2026-10-04, Phone card SLink contact, Stage 1 — append-only)

`docs/polished/PHONE_SLOT.md` Stage 1 adds, in addition to the core overlay rows above:

| space | span | owner | bytes |
|---|---|---|---|
| ROM0 | `$3F34`-`$3F91` (fixed `SECTION "SLink Phone Bridge", ROM0[$3F34]`) | `SlinkPhone_*` bridges + the two ROM0 strings | 94 of the 204-byte gap `$3F34`-`$3FFF` |
| bank `$24` | five 2-byte `call` operands (flat `0x90A1D`, `0x90B0F`, `0x90B5F`, `0x90B67`, `0x90B7B`) | `PHONE_HOOKS` in `tools/build_polished_companion.py` | 10, same size, no symbol moves |

Correction to the earlier "ROM0 has 351 free bytes at `$015f`": `$015f` is the **count** (351 = `$15F`, as
`free_space.txt` prints `351 free ($015f)`), not an address. The clean map's ROM0 gaps are `$0057` (1 B),
`$006E`-`$00FF` (146 B; the DelayFrame bridge now holds `$0070`-`$0088`, leaving `$0089`-`$00FF`, 119 B) and
`$3F34`-`$3FFF` (204 B; the phone bridge holds `$3F34`-`$3F91`, leaving `$3F92`-`$3FFF`, 110 B). No ROMX
free space outside bank `$7E` is used. `data/polished/free_space.txt` describes the CLEAN build and is unchanged.
