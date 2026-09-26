; Trade-specific partner confirmation from the existing foreground service.
; The admitted caller owns the request and both staged names. No party is changed.
; D = 0 yes, 1 no/B, 3 unavailable. Result 2 stays reserved for uncertain effects.
DEF SlinkPromptPlayerName EQU wEnemyMons + 60
SECTION "SLink partner trade prompt", ROMX[$5800], BANK[SLINK_TRADE_BANK]
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
    IF SLINK_YELLOW
        ld a, [wPrinterConnectionOpen]
        and a
        jp nz, .unavailable
    ENDC
    ld a, [wTradingWhichPlayerMon]
    call SlinkTradeUIValidSlot
    jp c, .unavailable
    ld a, [wTradingWhichPlayerMon]
    ld hl, wPartyMonNicks
    nativecall SkipFixedLengthTextEntries
    push hl
    ld d, h
    ld e, l
    call SlinkTradeUIValidName
    pop hl
    jp c, .unavailable
    ; Slot1's first16 bytes retain the union preimage. This name uses the next
    ; eleven bytes of the otherwise unused enemy slot, never that preimage.
    ld de, SlinkPromptPlayerName
    ld bc, 11
    nativecall CopyData
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
    ld a, [wEnemyMons + 1]
    ld b, a
    ld a, [wEnemyMons + 2]
    or b
    jp z, .unavailable
    ld de, wEnemyMonNicks
    call SlinkTradeUIValidName
    jp c, .unavailable

    slink_save_prompt_state
    nativecall SaveScreenTilesToBuffer2
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
    nativecall ClearSprites
    nativecall LoadFontTilePatterns
    call SlinkTradeUIWaitReleased
    ld hl, .question
    nativecall PrintText
    call SlinkTradeUIWaitReleased
.choice
    nativecall YesNoChoice
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
    nativecall ClearScreen
    nativecall InGameTrade_RestoreScreen
    nativecall RedrawMapView
    nativecall Delay3
    pop de
    slink_restore_prompt_state
    push de
    nativecall UpdateSprites
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
SlinkPartnerPromptEnd::
ASSERT SlinkPartnerPromptEnd <= $6000
