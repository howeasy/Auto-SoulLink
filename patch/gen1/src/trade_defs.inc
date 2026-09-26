; Generated/verified against committed data/pret/pokered.sym (pret 405b624).
; Project-only switches cite their defining trade source; no pret symbol exists for them.
DEF SLINK_TRADE_BANK EQU $3F ; patch/gen1/src/trade_service.asm:67; pret/home/header.asm:3-38 (reserved RST space); clean bank verified by build
DEF SLINK_YELLOW EQU 0 ; data/pret/pokered.sym:1 (Red build target); Yellow excluded by manifest.ROMS
DEF SLINK_TRADE_UI EQU 1 ; patch/gen1/src/trade_receptionist.asm:3-4 (this project-defined feature switch)
DEF SLINK_TRADE_MUSIC_BANK EQU $02 ; data/pret/pokered.sym:1957; pret/engine/link/cable_club.asm:832
DEF SLINK_TRADE_MUSIC_ID EQU $E5 ; data/pret/pokered.sym:1957,1848; pret/constants/music_constants.asm:4-6,22
; slink_species_table derives its 191 admission bytes from pret/data/pokemon/dex_order.asm:3-192.
MACRO slink_species_table
 db 0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,0,1,1,1,0,1,1,1,1,0,0,0,1,1,1,0,0,0,1,1,1,1,1,1,1,1,1,0,0,0,1,1,1,1,0,0,1,1,1,1,1,1,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,1,1,1,1,1,0,0,1,1,1,1,0,1,1,1,1,1,1,0,0,1,0,1,1,0,1,1,1,1,1,0,1,1,1,1,1,1,1,1,1,0,1,1,0,0,0,0,1,1,1,1,1,1,1,1,1,0,1,0,0,1,1,1,1,1,0,0,0,0,1,1,1,1,1,1
ENDM
DEF Bankswitch EQU $35D6 ; data/pret/pokered.sym:858
DEF BankswitchBank EQU $00 ; data/pret/pokered.sym:858
DEF SaveScreenTilesToBuffer2 EQU $36F4 ; data/pret/pokered.sym:882
DEF SaveScreenTilesToBuffer2Bank EQU $00 ; data/pret/pokered.sym:882
DEF SkipFixedLengthTextEntries EQU $3A7D ; data/pret/pokered.sym:946
DEF SkipFixedLengthTextEntriesBank EQU $00 ; data/pret/pokered.sym:946
DEF CopyData EQU $00B5 ; data/pret/pokered.sym:11
DEF CopyDataBank EQU $00 ; data/pret/pokered.sym:11
DEF AddNTimes EQU $3A87 ; data/pret/pokered.sym:948
DEF AddNTimesBank EQU $00 ; data/pret/pokered.sym:948
DEF RemovePokemon EQU $391F ; data/pret/pokered.sym:925
DEF RemovePokemonBank EQU $00 ; data/pret/pokered.sym:925
DEF AddEnemyMonToPlayerParty EQU $3A53 ; data/pret/pokered.sym:944
DEF AddEnemyMonToPlayerPartyBank EQU $00 ; data/pret/pokered.sym:944
DEF ClearScreen EQU $190F ; data/pret/pokered.sym:365
DEF ClearScreenBank EQU $00 ; data/pret/pokered.sym:365
DEF LoadFontTilePatterns EQU $3680 ; data/pret/pokered.sym:873
DEF LoadFontTilePatternsBank EQU $00 ; data/pret/pokered.sym:873
DEF LoadHpBarAndStatusTilePatterns EQU $36C0 ; data/pret/pokered.sym:877
DEF LoadHpBarAndStatusTilePatternsBank EQU $00 ; data/pret/pokered.sym:877
DEF InternalClockTradeAnim EQU $50E2 ; data/pret/pokered.sym:7575
DEF InternalClockTradeAnimBank EQU $10 ; data/pret/pokered.sym:7575
DEF TryEvolvingMon EQU $6D0E ; data/pret/pokered.sym:6299
DEF TryEvolvingMonBank EQU $0E ; data/pret/pokered.sym:6299
DEF InGameTrade_RestoreScreen EQU $5CA2 ; data/pret/pokered.sym:12491
DEF InGameTrade_RestoreScreenBank EQU $1C ; data/pret/pokered.sym:12491
DEF RedrawMapView EQU $6EDC ; data/pret/pokered.sym:3182
DEF RedrawMapViewBank EQU $03 ; data/pret/pokered.sym:3182
DEF UpdateSprites EQU $2429 ; data/pret/pokered.sym:572
DEF UpdateSpritesBank EQU $00 ; data/pret/pokered.sym:572
DEF Delay3 EQU $3DD7 ; data/pret/pokered.sym:1024
DEF Delay3Bank EQU $00 ; data/pret/pokered.sym:1024
DEF PlaySound EQU $23B1 ; data/pret/pokered.sym:564
DEF PlaySoundBank EQU $00 ; data/pret/pokered.sym:564
DEF DelayFrames EQU $3739 ; data/pret/pokered.sym:887
DEF DelayFramesBank EQU $00 ; data/pret/pokered.sym:887
DEF PlayDefaultMusic EQU $2307 ; data/pret/pokered.sym:546
DEF PlayDefaultMusicBank EQU $00 ; data/pret/pokered.sym:546
DEF SaveGameData EQU $7848 ; data/pret/pokered.sym:12646
DEF SaveGameDataBank EQU $1C ; data/pret/pokered.sym:12646
DEF WaitForSoundToFinish EQU $3748 ; data/pret/pokered.sym:889
DEF WaitForSoundToFinishBank EQU $00 ; data/pret/pokered.sym:889
DEF PlaySoundWaitForCurrent EQU $3740 ; data/pret/pokered.sym:888
DEF PlaySoundWaitForCurrentBank EQU $00 ; data/pret/pokered.sym:888
DEF SLINK_SFX_SAVE EQU $B6 ; data/pret/pokered.sym:1848,1941,14114,14207 (SFX_Save_1/_3 at header +$222 in banks $02/$1F); pret/constants/music_constants.asm:161
DEF DelayFrame EQU $20AF ; data/pret/pokered.sym:492
DEF DelayFrameBank EQU $00 ; data/pret/pokered.sym:492
DEF CableClubNPC EQU $71C5 ; data/pret/pokered.sym:1704
DEF CableClubNPCBank EQU $01 ; data/pret/pokered.sym:1704
DEF WaitForTextScrollButtonPress EQU $3865 ; data/pret/pokered.sym:910
DEF WaitForTextScrollButtonPressBank EQU $00 ; data/pret/pokered.sym:910
DEF TextBoxBorder EQU $1922 ; data/pret/pokered.sym:367
DEF TextBoxBorderBank EQU $00 ; data/pret/pokered.sym:367
DEF PlaceString EQU $1955 ; data/pret/pokered.sym:371
DEF PlaceStringBank EQU $00 ; data/pret/pokered.sym:371
DEF HandleMenuInput EQU $3ABE ; data/pret/pokered.sym:953
DEF HandleMenuInputBank EQU $00 ; data/pret/pokered.sym:953
DEF LoadScreenTilesFromBuffer2 EQU $3701 ; data/pret/pokered.sym:883
DEF LoadScreenTilesFromBuffer2Bank EQU $00 ; data/pret/pokered.sym:883
DEF ClearSprites EQU $0082 ; data/pret/pokered.sym:6
DEF ClearSpritesBank EQU $00 ; data/pret/pokered.sym:6
DEF Joypad EQU $019A ; data/pret/pokered.sym:17
DEF JoypadBank EQU $00 ; data/pret/pokered.sym:17
DEF PrintText EQU $3C49 ; data/pret/pokered.sym:988
DEF PrintTextBank EQU $00 ; data/pret/pokered.sym:988
DEF YesNoChoice EQU $35EC ; data/pret/pokered.sym:860
DEF YesNoChoiceBank EQU $00 ; data/pret/pokered.sym:860
DEF SlinkDelayFrameHalt EQU $20B3 ; data/pret/pokered.sym:493
DEF SlinkOverworldReturn EQU $0402 ; data/pret/pokered.sym:23; pret/home/overworld.asm:41-43
DEF SlinkOverworldLessReturn EQU $0405 ; data/pret/pokered.sym:24; pret/home/overworld.asm:43-45
DEF SLINK_SFX_REQUEST EQU $DEE9 ; patch/gen1/src/slink.asm:38-46 (mailbox +7); pret/ram/wram.asm free WRAM0 tail ($DEE2 + 7)
; slink_name_table derives its 256 glyph flags from pret/constants/charmap.asm:5-196.
MACRO slink_name_table
 db 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1
ENDM
; Prompt state fields are the named WRAM/HRAM symbols cited below; order from RC trade prompt.
MACRO slink_save_prompt_state
 ld a, [wOptions]
 push af
 ld a, [wStatusFlags5]
 push af
 ld a, [wFontLoaded]
 push af
 ld a, [wUpdateSpritesEnabled]
 push af
 ldh a, [hAutoBGTransferEnabled]
 push af
 ldh a, [hTileAnimations]
 push af
 ldh a, [hWY]
 push af
 ldh a, [hUILayoutFlags]
 push af
 ld a, [wPartyMenuAnimMonEnabled]
 push af
 ld a, [wWhichPokemon]
 push af
 ld a, [wTopMenuItemY]
 push af
 ld a, [wTopMenuItemX]
 push af
 ld a, [wCurrentMenuItem]
 push af
 ld a, [wTileBehindCursor]
 push af
 ld a, [wMaxMenuItem]
 push af
 ld a, [wMenuWatchedKeys]
 push af
 ld a, [wLastMenuItem]
 push af
 ld a, [wPartyAndBillsPCSavedMenuItem]
 push af
 ld a, [wMenuJoypadPollCount]
 push af
 ld a, [wMenuWrappingEnabled]
 push af
 ld a, [wMenuWatchMovingOutOfBounds]
 push af
 ld a, [wMenuCursorLocation]
 push af
 ld a, [wMenuCursorLocation + 1]
 push af
 ld a, [wTextBoxID]
 push af
 ld a, [wTwoOptionMenuID]
 push af
ENDM
MACRO slink_restore_prompt_state
 pop af
 ld [wTwoOptionMenuID], a
 pop af
 ld [wTextBoxID], a
 pop af
 ld [wMenuCursorLocation + 1], a
 pop af
 ld [wMenuCursorLocation], a
 pop af
 ld [wMenuWatchMovingOutOfBounds], a
 pop af
 ld [wMenuWrappingEnabled], a
 pop af
 ld [wMenuJoypadPollCount], a
 pop af
 ld [wPartyAndBillsPCSavedMenuItem], a
 pop af
 ld [wLastMenuItem], a
 pop af
 ld [wMenuWatchedKeys], a
 pop af
 ld [wMaxMenuItem], a
 pop af
 ld [wTileBehindCursor], a
 pop af
 ld [wCurrentMenuItem], a
 pop af
 ld [wTopMenuItemX], a
 pop af
 ld [wTopMenuItemY], a
 pop af
 ld [wWhichPokemon], a
 pop af
 ld [wPartyMenuAnimMonEnabled], a
 pop af
 ldh [hUILayoutFlags], a
 pop af
 ldh [hWY], a
 pop af
 ldh [hTileAnimations], a
 pop af
 ldh [hAutoBGTransferEnabled], a
 pop af
 ld [wUpdateSpritesEnabled], a
 pop af
 ld [wFontLoaded], a
 pop af
 ld [wStatusFlags5], a
 pop af
 ld [wOptions], a
ENDM
DEF wIsInBattle EQU $D057 ; data/pret/pokered.sym:18792
DEF wLinkState EQU $D12B ; data/pret/pokered.sym:18953
DEF hSerialConnectionStatus EQU $FFAA ; data/pret/pokered.sym:20131
DEF wEnteringCableClub EQU $CC47 ; data/pret/pokered.sym:18355
DEF wPartyCount EQU $D163 ; data/pret/pokered.sym:18984
DEF wPartySpecies EQU $D164 ; data/pret/pokered.sym:18986
DEF wTradingWhichPlayerMon EQU $CD3D ; data/pret/pokered.sym:18507
DEF wEnemyPartyCount EQU $D89C ; data/pret/pokered.sym:19409
DEF wEnemyPartySpecies EQU $D89D ; data/pret/pokered.sym:19410
DEF wEnemyMons EQU $D8A4 ; data/pret/pokered.sym:19413
DEF wOptions EQU $D355 ; data/pret/pokered.sym:19169
DEF wStatusFlags5 EQU $D730 ; data/pret/pokered.sym:19392
DEF wFontLoaded EQU $CFC4 ; data/pret/pokered.sym:18718
DEF wForceEvolution EQU $CCD4 ; data/pret/pokered.sym:18396
DEF wUpdateSpritesEnabled EQU $CFCB ; data/pret/pokered.sym:18725
DEF hAutoBGTransferEnabled EQU $FFBA ; data/pret/pokered.sym:20147
DEF hTileAnimations EQU $FFD7 ; data/pret/pokered.sym:20167
DEF hWY EQU $FFB0 ; data/pret/pokered.sym:20137
DEF wPartyMonOT EQU $D273 ; data/pret/pokered.sym:19145
DEF wTradedPlayerMonOT EQU $CD41 ; data/pret/pokered.sym:18564
DEF wPartyMons EQU $D16B ; data/pret/pokered.sym:18989
DEF wTradedPlayerMonSpecies EQU $CD3D ; data/pret/pokered.sym:18506
DEF wTradedPlayerMonOTID EQU $CD4C ; data/pret/pokered.sym:18585
DEF wEnemyMonOT EQU $D9AC ; data/pret/pokered.sym:19571
DEF wTradedEnemyMonOT EQU $CD4E ; data/pret/pokered.sym:18589
DEF wTradedEnemyMonOTID EQU $CD59 ; data/pret/pokered.sym:18597
DEF wTradedEnemyMonSpecies EQU $CD3E ; data/pret/pokered.sym:18530
DEF wWhichPokemon EQU $CF92 ; data/pret/pokered.sym:18684
DEF wRemoveMonFromBox EQU $CF95 ; data/pret/pokered.sym:18689
DEF wTradingWhichEnemyMon EQU $CD3E ; data/pret/pokered.sym:18531
DEF wCurPartySpecies EQU $CF91 ; data/pret/pokered.sym:18683
DEF wLoadedMon EQU $CF98 ; data/pret/pokered.sym:18692
DEF wAudioFadeOutControl EQU $CFC7 ; data/pret/pokered.sym:18721
DEF wAudioSavedROMBank EQU $C0F0 ; data/pret/pokered.sym:17461
DEF wNewSoundID EQU $C0EE ; data/pret/pokered.sym:17459
DEF wSerialPartyMonsPatchList EQU $C508 ; data/pret/pokered.sym:18119
DEF wEnemyMonNicks EQU $D9EE ; data/pret/pokered.sym:19578
DEF wLinkEnemyTrainerName EQU $D887 ; data/pret/pokered.sym:19406
DEF hLoadedROMBank EQU $FFB8 ; data/pret/pokered.sym:20145
DEF wPokedexOwned EQU $D2F7 ; data/pret/pokered.sym:19161
DEF wPlayerName EQU $D158 ; data/pret/pokered.sym:18983
DEF wPlayerID EQU $D359 ; data/pret/pokered.sym:19173
DEF wCurMap EQU $D35E ; data/pret/pokered.sym:19177
DEF wTileMap EQU $C3A0 ; data/pret/pokered.sym:18118
DEF wTopMenuItemY EQU $CC24 ; data/pret/pokered.sym:18329
DEF wTopMenuItemX EQU $CC25 ; data/pret/pokered.sym:18330
DEF wCurrentMenuItem EQU $CC26 ; data/pret/pokered.sym:18331
DEF wMaxMenuItem EQU $CC28 ; data/pret/pokered.sym:18333
DEF wMenuWatchedKeys EQU $CC29 ; data/pret/pokered.sym:18334
DEF wLastMenuItem EQU $CC2A ; data/pret/pokered.sym:18335
DEF wMenuJoypadPollCount EQU $CC34 ; data/pret/pokered.sym:18342
DEF wMenuWrappingEnabled EQU $CC4A ; data/pret/pokered.sym:18360
DEF wMenuWatchMovingOutOfBounds EQU $CC37 ; data/pret/pokered.sym:18345
DEF wPartyMonNicks EQU $D2B5 ; data/pret/pokered.sym:19152
DEF hFrameCounter EQU $FFD5 ; data/pret/pokered.sym:20165
DEF wPartyMenuAnimMonEnabled EQU $D09B ; data/pret/pokered.sym:18866
DEF hUILayoutFlags EQU $FFF6 ; data/pret/pokered.sym:20211
DEF hJoyHeld EQU $FFB4 ; data/pret/pokered.sym:20141
DEF wTileBehindCursor EQU $CC27 ; data/pret/pokered.sym:18332
DEF wPartyAndBillsPCSavedMenuItem EQU $CC2B ; data/pret/pokered.sym:18336
DEF wMenuCursorLocation EQU $CC30 ; data/pret/pokered.sym:18341
DEF wTextBoxID EQU $D125 ; data/pret/pokered.sym:18948
DEF wTwoOptionMenuID EQU $D12C ; data/pret/pokered.sym:18954
DEF wWalkCounter EQU $CFC5 ; data/pret/pokered.sym:18719
DEF wCurOpponent EQU $D059 ; data/pret/pokered.sym:18794
DEF wSafariZoneGameOver EQU $DA46 ; data/pret/pokered.sym:19592
DEF wJoyIgnore EQU $CD6B ; data/pret/pokered.sym:18607
DEF wMovementFlags EQU $D736 ; data/pret/pokered.sym:19396
DEF wStatusFlags3 EQU $D72D ; data/pret/pokered.sym:19390
DEF wStatusFlags6 EQU $D732 ; data/pret/pokered.sym:19393
