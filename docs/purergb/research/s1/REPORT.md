# pureRGB engine-signal site verification (v2.7.6 / RGBDS 1.0.3, commit 7e7a465)

Method: parsed `pokered/blue/green.sym`, computed flat ROM offsets (bank\*0x4000 + addr-0x4000, or addr for bank 0), sliced 8 bytes from the matching `.gbc`, and checked them against instruction shapes derived by hand from the cited `P/` source lines (macro lengths taken from `macros/farcall.asm`, confirmed: farcall/callfar/jpfar/homecall/predef/rst byte counts all match the task's stated macro table). Every symbol resolved on the first try in all three `.sym` files; no unresolved names.

## 1. Site-by-site verification

All 40 code sites below are **byte-identical across red/blue/green** -- confirmed programmatically (zero cross-title differences found). pureRGB's code segments are shared across the three titles; only text/graphics ROMX content differs, which is why the SUMMARY byte counts differ slightly (see §3).

| kind | symbol (as resolved) | bank:addr | rom_offset | bytes (8) | verdict | note |
|---|---|---|---|---|---|---|
| wild_begin | InitWildBattle+0x13 | 0f:6f4a | 03ef4a | `CD8A6ACD426C2172` | PASS | Lands exactly on `call LoadEnemyMonData` (CD 8A 6A); the 3 bytes at +0x10 are EA 57 D0 = ld [wIsInBattle],a... |
| battle_loop_head | MainInBattleLoop+0x6 | 0f:4253 | 03c253 | `CD004E2115D02AB6` | PASS | call ReadPlayerMonCurHPAndStatus (CD 00 4E = call $4E00) |
| trainer_staging | _InitBattleCommon+0x48 | 0f:6fba | 03efba | `4E2174740635C7CD` | FAIL (see §4) | MISMATCH: task cites `_InitBattleCommon` (core.asm L7111, the SHARED tail both wild/trainer paths jump to) |
| battle_faint | RemoveFaintedPlayerMon+0x0 | 0f:47cd | 03c7cd | `FA2FCC4F2158D006` | PASS | ld a,[wPlayerMonNumber] (FA 2F CC = ld a,[$CC2F]) |
| poison_faint | ApplyOutOfBattlePoisonDamage.noBorrow+0x4 | 03:4731 | 00c731 | `E52323771AEA26D1` | PASS | E5 23 23 77 1A EA 26 D1 = push hl; inc hl; inc hl; ld [hl],a; ld a,[de]; ld [wPokedexNum],a ($D126) |
| bag_received | AddItemToInventory_.done+0x8 | 03:505c | 00d05c | `C9E523FA92CF8785` | PASS | C9 = ret, end of the 9-byte epilogue E1 D1 C1 C1 78 EA lo hi C9 |
| save_witness | SaveMenu.save+0x3 | 1c:77d1 | 0737d1 | `CD562921B9C421FF` | PASS | call ClearTextBox (CD 56 29 = call $2956), immediately after call SaveGameData at +0 |
| capture_party_begin | ItemUseBall.skipShowingPokedexData+0x22 | 03:5405 | 00d405 | `CD9A34F1A7283221` | PASS | call AddPartyMon (CD 9A 34 = call $349A) |
| capture_party_end | ItemUseBall.skipShowingPokedexData+0x25 | 03:5408 | 00d408 | `F1A72832219E5606` | PASS | pop af; and a (F1 A7), start of the Bill's Garden $80-nickname-skip branch epilogue right after AddPartyMon... |
| capture_box_begin | ItemUseBall.sendToBox+0x3 | 03:5421 | 00d421 | `CD4B65216854FAF9` | PASS | call SendNewMonToBox (CD 4B 65 = call $654B) |
| capture_box_end | ItemUseBall.sendToBox+0x6 | 03:5424 | 00d424 | `216854FAF9D7CB47` | PASS | ld hl, ItemUseBallText07 (21 68 54), the instruction right after call SendNewMonToBox returns |
| pc_deposit | BillsPCDeposit+0x4b | 33:4376 | 0cc376 | `CDAC33213DCDFAA8` | PASS | Derived (task asked us to derive it): call WaitForSoundToFinish (CD AC 33 = call $33AC), the instruction ri... |
| pc_withdraw | BillsPCWithdraw+0x67 | 33:441f | 0cc41f | `CDAC33212646CDCE` | PASS | Derived: call WaitForSoundToFinish (CD AC 33), same pattern as deposit, right after `call RemovePokemon` |
| pc_release | BillsPCRelease+0x70 | 33:44c2 | 0cc4c2 | `CDAC33FA91CFCD5F` | PASS | Derived: call WaitForSoundToFinish (CD AC 33), same pattern, right after `call RemovePokemon` |
| changebox_full_save | ChangeBox.yes+0x38 | 1c:798d | 07398d | `3EB6CDA533CDAC33` | FAIL (see §4) | MISMATCH: at +0x38 the real bytes are `3E B6 CD A5 33 CD AC 33` = ld a, SFX_SAVE($B6); call PlaySoundWaitFo... |
| evolve_species_store | Evolution_PartyMonLoop.skipfix_end+0x3c | 2c:56c5 | 0b16c5 | `77E56B6218012323` | PASS | 77 E5 6B 62 18 01 = ld [hl],a (final species-list store, wLoadedMonSpecies -> party species slot) ; push hl... |
| transform_base | ChangePartyPokemonSpecies+0x0 | 35:65b2 | 0d65b2 | `FA91CFEAB5D0CDBB` | PASS | ld a,[wCurPartySpecies] (FA 91 CF = ld a,[$CF91]) |
| transform_species_list | ChangePartyPokemonSpecies+0x16 | 35:65c8 | 0d65c8 | `77FA92CF2173D101` | PASS | 77 = ld [hl],a, the wPartySpecies-array write |
| transform_struct_species | ChangePartyPokemonSpecies+0x27 | 35:65d9 | 0d65d9 | `77012100092AEA2F` | PASS | 77 = ld [hl],a, the per-mon struct species write |
| transform_hp_hi | ChangePartyPokemonSpecies+0x4a | 35:65fc | 0d65fc | `227932E101050009` | PASS | 22 = ld [hli],a, new max-HP MSB stored into current-HP MSB |
| transform_hp_lo | ChangePartyPokemonSpecies+0x4c | 35:65fe | 0d65fe | `32E101050009FABE` | PASS | 32 = ld [hld],a, new max-HP LSB stored into current-HP LSB |
| apex_preflight | ItemUseMedicine.useApexChip+0xf | 03:5b43 | 00db43 | `2277E1E5CD4D5AE1` | PASS | = ItemUseMedicine.setDVs (confirmed by symbol table: both resolve to the same address) |
| apex_commit | ItemUseMedicine.useApexChip+0x11 | 03:5b45 | 00db45 | `E1E5CD4D5AE10122` | PASS | E1 E5 = pop hl ; push hl, immediately after both DV bytes are maxed, restoring hl before the stat recalc call |
| apex_recalc_call | ItemUseMedicine.useApexChip+0x13 | 03:5b47 | 00db47 | `CD4D5AE101220009` | PASS | call ItemUseMedicine.recalculateStats (CD 4D 5A = call $5A4D) |
| npc_trade_remove | InGameTrade_DoTrade+0x7b | 1c:5547 | 071547 | `CD93343E80EA49CC` | PASS | call RemovePokemon (CD 93 34 = call $3493) |
| npc_trade_add | InGameTrade_DoTrade+0x83 | 1c:554f | 07154f | `CD9A34CD0756CD34` | PASS | call AddPartyMon (CD 9A 34 = call $349A), preceded at +0x7E..+0x82 by 3E 80 EA 49 CC = ld a,$80 ; ld [wMonD... |
| npc_trade_done | InGameTrade_DoTrade+0x89 | 1c:5555 | 071555 | `CD3416CD95550603` | PASS | call ClearScreen (CD 34 16 = call $1634) |
| cable_remove | TradeCenter_Trade.doTrade+0x77 | 01:5650 | 005650 | `CD9334FA3ECD4FEA` | PASS | call RemovePokemon (CD 93 34 = call $3493) |
| cable_add | TradeCenter_Trade.doTrade+0xa0 | 01:5679 | 005679 | `FA6BD13DEA92CF3E` | FAIL (see §4) | MISMATCH: at +0xA0 the real bytes are `FA 6B D1 3D EA 92 CF 3E` = ld a,[wPartyCount] ; dec a ; ld [wWhichPo... |
| cable_partial_save | TradeCenter_Trade.tradeCompleted+0x2c | 01:56f0 | 0056f0 | `218078061CC70E32` | PASS | callfar SavePartyAndDexData (21 80 78 06 1C C7 = ld hl,$7880 ; ld b,$1C ; rst 0), matching bank $1C / addr ... |
| daycare_withdraw | DaycareGentlemanText.enoughMoney+0x27 | 15:69c8 | 0569c8 | `CDDC34FA67DAEA91` | PASS | call MoveMon (CD DC 34 = call $34DC), preceded by ld a,DAYCARE_TO_PARTY ; ld [wMoveMonType],a |
| blackout | ResetStatusAndHalveMoneyOnBlackout+0x0 | 01:40b0 | 0040b0 | `AFEA0BCFEA08D7EA` | PASS | AF EA 0B CF EA 08 D7 EA = xor a ; ld [wBattleResult],a ($CF0B) ; ld [wWalkBikeSurfState],a ($D708) ; ld [wI... |
| whiteout_endofbattle | EndOfBattle+0x0 | 3a:44fd | 0e84fd | `FA33D1FE042036FA` | PASS | Bank confirmed = $3A exactly as the task required |
| starter | OaksLabMonChoiceMenu.continue+0x23 | 07:49da | 01c9da | `CD9A342136D7CBDE` | PASS | call AddPartyMon (CD 9A 34 = call $349A) |
| checkpoint_delayframe_halt | DelayFrame+0x17 | 00:1e8d | 001e8d | `7600F0D6A720F9C9` | PASS | 76 00 = halt ; nop, exactly as the task predicted |
| checkpoint_overworldloop | OverworldLoop+0x0 | 00:03d6 | 0003d6 | `D721BD680635C7CD` | PASS | D7 = rst _DelayFrame, exactly as the task predicted |
| checkpoint_init | Init+0x0 | 00:1d10 | 001d10 | `F3AFE00FE0FFE043` | PASS | F3 AF E0 0F E0 FF E0 43 = di ; xor a ; ldh [rIF],a ; ldh [rIE],a ; ldh [rSCX],a(cut off) |
| checkpoint_softreset | SoftReset+0x0 | 00:1d07 | 001d07 | `CDDD1DCD32380E20` | PASS | CD DD 1D CD 32 38 0E 20 = call StopAllSounds($1DDD) ; call GBPalWhiteOut($3832) ; ld c,32 |
| checkpoint_start | _Start+0x0 | 00:0150 | 000150 | `FE113E0128013DE0` | PASS | FE 11 3E 01 28 01 3D E0 = cp BOOTUP_A_CGB($11) ; ld a,TRUE ; jr z,+1(.gbc) ; dec a ; ldh[hGBC],a(cut off) |
| checkpoint_vblank_vector | (raw addr) | 00:0040 | 000040 | `C3F31DA7A0B5A450` | PASS | C3 F3 1D = jp $1DF3 = VBlank, exactly as the task predicted |
| rst_0000 | (raw addr) | 00:0000 | 000000 | `C3973215144120FF` | PASS | C3 97 32 = jp $3297 = Bankswitch (_Bankswitch::) |
| rst_0008 | (raw addr) | 00:0008 | 000008 | `C3D038158B7728FD` | PASS | C3 D0 38 = jp $38D0 = Predef (_Predef::) |
| rst_0010 | (raw addr) | 00:0010 | 000010 | `C3761EA8A6A7B350` | PASS | C3 76 1E = jp $1E76 = DelayFrame (_DelayFrame::) |
| rst_0018 | (raw addr) | 00:0018 | 000018 | `D70D20FCC9938C50` | PASS | D7 0D 20 FC C9 = rst _DelayFrame ; dec c ; jr nz,-4(self loop) ; ret, exactly the DelayFrames loop body |
| rst_0020 | (raw addr) | 00:0020 | 000020 | `C3AE00B6A8B3A750` | PASS | C3 AE 00 = jp $00AE = CopyData (_CopyData::) |
| rst_0028 | (raw addr) | 00:0028 | 000028 | `C3A53615AE7728FF` | PASS | C3 A5 36 = jp $36A5 = PrintText (_PrintText::) |
| trainer_staging_corrected | InitBattleCommon+0x48 | 0f:6f22 | 03ef22 | `3E02EA57D0184921` | PASS | CORRECTED site for trainer_staging: same offset (0x48), correct label InitBattleCommon (no underscore) |
| changebox_full_save_corrected | ChangeBox.yes+0x35 | 1c:798a | 07398a | `CDB5783EB6CDA533` | PASS | CORRECTED offset for changebox_full_save: 0x35 (not 0x38) |
| cable_add_corrected | TradeCenter_Trade.doTrade+0x9d | 01:5676 | 005676 | `CDCB34FA6BD13DEA` | PASS | CORRECTED offset for cable_add: 0x9D (not 0xA0) |

Full per-site notes (source citation + byte-level derivation) are in `sites_purergb.json`; every entry's `note` field carries the file/line and the exact instruction sequence. Since bytes are identical across all three titles for every site, the table above is not repeated three times; `sites_purergb.json` still stores independent red/blue/green captures (cross-checked equal).

## 2. RAM symbols the SLink profile needs

All resolved in all three `.sym` files, all identical across titles (WRAM/HRAM layout is shared code, confirmed independently by §3's WRAMX/HRAM EMPTY blocks being byte-identical too).

| symbol | bank | address | identical across titles |
|---|---|---|---|
| wPartyCount | 1 | $D16B | yes |
| wPartySpecies | 1 | $D16C | yes |
| wPartyMons | 1 | $D173 | yes |
| wPartyMonOT | 1 | $D27B | yes |
| wPartyMonNicks | 1 | $D2BD | yes |
| wBoxCount | 1 | $DA88 | yes |
| wBoxSpecies | 1 | $DA89 | yes |
| wBoxMons | 1 | $DA9E | yes |
| wBoxMonOT | 1 | $DD32 | yes |
| wBoxMonNicks | 1 | $DE0E | yes |
| wCurrentBoxNum | 1 | $D5A8 | yes |
| wIsInBattle | 1 | $D057 | yes |
| wBattleType | 1 | $D05A | yes |
| wCurOpponent | 1 | $D059 | yes |
| wEnemyMonSpecies2 | 1 | $D000 | yes |
| wCurEnemyLevel | 1 | $D12F | yes |
| wCurMap | 1 | $D366 | yes |
| wPlayerID | 1 | $D361 | yes |
| wPlayerName | 1 | $D160 | yes |
| wNumBagItems | 1 | $D542 | yes |
| wBagItems | 1 | $D543 | yes |
| wPocketAbraNick | 1 | $D580 | yes |
| wPlayerMoney | 1 | $D34F | yes |
| wMonDataLocation | 0 | $CC49 | yes |
| wWhichPokemon | 0 | $CF92 | yes |
| wMoveMonType | 0 | $CF95 | yes |
| wRemoveMonFromBox | 0 | $CF95 | yes |
| wCurPartySpecies | 0 | $CF91 | yes |
| wLinkState | 1 | $D133 | yes |
| wDayCareMon | 1 | $DA67 | yes |
| wDayCareInUse | 1 | $DA50 | yes |
| wUsedItemOnWhichPokemon | 0 | $CF06 | yes |
| wSaveFileStatus | 1 | $D088 | yes |
| wOptions | 1 | $D35D | yes |
| wOptions2 | 1 | $DA45 | yes |
| wPkmnTypeRemapFlags | 1 | $DA3D | yes |
| wSafariType | 1 | $DA42 | yes |
| wGameInternalVersion | 1 | $D35F | yes |
| hLoadedROMBank | 0 | $FFB8 | yes |
| hGBC | 0 | $FFFE | yes |
| sPlayerName | 1 | $A598 | yes |
| sMainData | 1 | $A5A3 | yes |
| sPartyData | 1 | $AF2C | yes |
| sCurBoxData | 1 | $B0C0 | yes |
| sMainDataCheckSum | 1 | $B523 | yes |
| sBox1 | 2 | $A000 | yes |
| sBox7 | 3 | $A000 | yes |
| sBank2AllBoxesChecksum | 2 | $BA4C | yes |
| sBank3AllBoxesChecksum | 3 | $BA4C | yes |

Observation: `wMoveMonType` and `wRemoveMonFromBox` both resolve to `$CF95` (bank 0) -- they alias the same scratch byte. Not a bug in this resolver; confirmed directly from the `.sym` file, and consistent with the two flags never being live at the same time (one is used mid-`MoveMon`, the other only around `RemovePokemon`).

## 3. `.map` capacities (SUMMARY + EMPTY blocks)

| region | red used/free | blue used/free | green used/free | identical? |
|---|---|---|---|---|
| ROM0 | 15002/1382 | 15002/1382 | 15002/1382 | yes |
| ROMX | 909787/89637 in 61 banks | 909978/89446 in 61 banks | 909904/89520 in 61 banks | NO -- ROMX text/data differs per title |
| SRAM | 25983/6785 in 4 banks | 25983/6785 in 4 banks | 25983/6785 in 4 banks | yes |
| WRAM0 | 4096/0 | 4096/0 | 4096/0 | yes |
| WRAMX | 4202/3990 in 2 banks | 4202/3990 in 2 banks | 4202/3990 in 2 banks | yes |
| HRAM | 127/0 | 127/0 | 127/0 | yes |

ROM0 EMPTY: `$3a9a-$3fff` (1382 bytes / `$0566`), identical across all three titles.

ROMX bank `$3D` (decimal #61, the highest bank actually used) EMPTY tail:

| title | EMPTY range | free bytes |
|---|---|---|
| red | EMPTY: $4c47-$7fff ($33b9 bytes) | |
| blue | EMPTY: $4d14-$7fff ($32ec bytes) | |
| green | EMPTY: $4cb4-$7fff ($334c bytes) | |

ROMX banks `$3E` and `$3F` (decimal #62/#63): **not present in the map at all** for any of the three titles -- only 61 of the 63 possible ROMX banks are used, so both banks are entirely free (2 × 16 KiB = 32 KiB of unused capacity, on top of the 89 KiB of fragmented free space the SUMMARY reports scattered across the 61 used banks).

| region | EMPTY | identical across titles |
|---|---|---|
| WRAM0 | fully used, 0 free | yes |
| WRAMX bank 1 | `$deea-$deff` (22 bytes / `$0016`) | yes |
| WRAMX bank 2 | `$d080-$dfff` (3968 bytes / `$0f80`) | yes |
| HRAM | fully used, 0 free | yes |

## 4. Geometry via symbol arithmetic

| expression | red | blue | green | note |
|---|---|---|---|---|
| wPartyMon2-wPartyMon1 | 0x002c | 0x002c | 0x002c | = PARTYMON_STRUCT_LENGTH (44 bytes), matches vanilla. |
| wBoxMon2-wBoxMon1 | 0x0021 | 0x0021 | 0x0021 | = 33 bytes, matches vanilla box-mon struct length. |
| wPartyMonOT-wPartyMons | 0x0108 | 0x0108 | 0x0108 | 264 bytes = 6 party slots × 44. |
| sBox2-sBox1 | 0x0462 | 0x0462 | 0x0462 | 1122 bytes per box (SRAM). |
| sBox7-sBox1 | 0x0000 (banks differ: 0x3 vs 0x2) | 0x0000 (banks differ: 0x3 vs 0x2) | 0x0000 (banks differ: 0x3 vs 0x2) | 0x0000 delta but **different bank** (sBox7 is bank 3, sBox1 is bank 2) -- box 7 starts a second SRAM bank at the same local offset as box 1, it is not a linear 6× continuation. |
| wMainDataEnd-wMainDataStart | 0x0789 | 0x0789 | 0x0789 | 1929 bytes of main save data. |
| wBoxDataEnd-wBoxDataStart | 0x0462 | 0x0462 | 0x0462 | 1122 bytes = one box's worth (matches sBox2-sBox1). |
| wPartyDataEnd-wPartyDataStart | 0x0194 | 0x0194 | 0x0194 | 404 bytes of party save data. |

## 5. Offsets that did NOT match the task's literal site definition

Three of the ~40 sites, as literally specified, land on the wrong byte. All three were confirmed empirically (byte dump + symbol-address cross-check, not just hand-counted) and a corrected offset/symbol was found by walking the surrounding disassembly:

1. **trainer_staging** -- `_InitBattleCommon + 0x48/0x4D` (task's literal symbol, *with* underscore) does **not** contain `ld a,2`. That label is core.asm's shared wild/trainer tail (L7111); at +0x48 it sits mid-instruction inside `call z, DrawEnemyHUDAndHPBar` / a `callfar CheckInitSpecialBattleEffect`. **Corrected symbol: `InitBattleCommon` (no underscore, core.asm L7044)** -- a distinct, similarly-named label 67 lines earlier. Same offsets (0x48/0x4D) on the corrected symbol give exactly `3E 02 EA 57 D0 18 49 21` = `ld a,2 ; ld [wIsInBattle],a ; jr +0x49` (which lands exactly on `_InitBattleCommon`), matching the task's own '3E 02' hypothesis precisely.
2. **changebox_full_save** -- `ChangeBox.yes + 0x38` is `3E B6 ...` (`ld a, SFX_SAVE`), not `call SaveGameData`. The call is 3 bytes earlier. **Corrected offset: `ChangeBox.yes + 0x35`** -> `CD B5 78` = `call SaveGameData` ($78B5), confirmed against the resolved `SaveGameData` symbol address.
3. **cable_add** -- `TradeCenter_Trade.doTrade + 0xA0` is `FA 6B D1 ...` (`ld a,[wPartyCount]`), the instruction *after* the call. **Corrected offset: `TradeCenter_Trade.doTrade + 0x9D`** -> `CD CB 34` = `call AddEnemyMonToPlayerParty` ($34CB), confirmed against the resolved symbol address.

All other ~37 sites (including every RST vector, every `callfar`/`farcall` shape, and every checkpoint) matched their derived expectation exactly on the first try, with the target CALL/JP addresses cross-checked against the resolved symbol table (not just opcode shape) wherever the site names a specific callee. `sites_purergb.json` carries both the as-specified (FAILing) entry and a `*_corrected` shadow entry (PASSing) for all three of the above.
