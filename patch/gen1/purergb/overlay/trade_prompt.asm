; Trade-specific partner confirmation from the existing foreground service. Ported from
; patch/gen1/src/trade_prompt.asm. The admitted caller owns the request and both staged
; names. No party is changed. D = 0 yes, 1 no/B, 3 unavailable. Result 2 stays reserved
; for uncertain effects.

; Slot 1's first 16 bytes retain the union preimage (SlinkOverlayBackup). This name uses
; the next eleven bytes of the otherwise unused enemy slot, never that preimage.
DEF SlinkPromptPlayerName EQUS "(wEnemyMons + PARTYMON_STRUCT_LENGTH + 16)"

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

SECTION "SLink partner trade prompt", ROMX

SlinkPartnerPrompt::
	ld a, [wIsInBattle]
	and a
	jp nz, .unavailable
	ld a, [wLinkState]
	and a
	jp nz, .unavailable
	ldh a, [hSerialConnectionStatus]
	cp $ff
	jp nz, .unavailable
	ld a, [wEnteringCableClub]
	and a
	jp nz, .unavailable
	ld a, [wTradingWhichPlayerMon]
	call SlinkTradeUIValidSlot
	jp c, .unavailable
	ld a, [wTradingWhichPlayerMon]
	ld hl, wPartyMonNicks
	call SkipFixedLengthTextEntries
	push hl
	ld d, h
	ld e, l
	call SlinkTradeUIValidName
	pop hl
	jp c, .unavailable
	ld de, SlinkPromptPlayerName
	ld bc, NAME_LENGTH
	call CopyData
	ld a, [wEnemyPartyCount]
	cp 1
	jp nz, .unavailable
	ld a, [wEnemyPartySpecies + 1]
	cp $ff
	jp nz, .unavailable
	ld a, [wEnemyPartySpecies]
	ld b, a
	ld a, [wEnemyMons]
	cp b
	jp nz, .unavailable
	call SlinkTradeApply.validSpecies
	jp c, .unavailable
	ld a, [wEnemyMons + MON_HP]
	ld b, a
	ld a, [wEnemyMons + MON_HP + 1]
	or b
	jp z, .unavailable
	ld de, wEnemyMonNicks
	call SlinkTradeUIValidName
	jp c, .unavailable

	slink_save_prompt_state
	call SaveScreenTilesToBuffer2
	xor a
	ld [wUpdateSpritesEnabled], a
	ld [wPartyMenuAnimMonEnabled], a
	ld [wMenuJoypadPollCount], a
	ldh [hTileAnimations], a
	ldh [hUILayoutFlags], a
	ldh [hWY], a
	ld a, 1
	ld [wFontLoaded], a
	ldh [hAutoBGTransferEnabled], a
	call ClearSprites
	call LoadFontTilePatterns
	call SlinkTradeUIWaitReleased
	ld hl, .question
	call PrintText
	call SlinkTradeUIWaitReleased
.choice
	call YesNoChoice
	ld a, [wCurrentMenuItem]
	and a
	ld d, 1
	jr nz, .restore
	; YES still needs vanilla's must-save consent; NO/B there is a decline.
	call SlinkTradeUIMustSave
	ld d, 1
	jr c, .restore
	dec d
.restore
	push de
	call ClearScreen
	farcall InGameTrade_RestoreScreen
	farcall RedrawMapView
	call Delay3
	pop de
	slink_restore_prompt_state
	push de
	call UpdateSprites
	pop de
	ld a, d
	and a
	ret nz
	; Saved only now: SaveMainData records hTileAnimations and wOptions,
	; which the prompt borrowed until the restore above.
	call SlinkTradeUISave
	ld d, 0
	ret
.unavailable
	ld d, 3
	ret
.question
	text "Trade @"
	text_ram SlinkPromptPlayerName
	text ""
	line "for @"
	text_ram wEnemyMonNicks
	text "?"
	done
