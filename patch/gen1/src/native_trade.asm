; Foreground RBY physical trade engine. Caller owns a durably committed trade,
; revalidates both complete parties/identities and stages enemy slot0 before entry.
; This module is not wired to a public command or receptionist yet.
; No permanent WRAM: presentation state lives on the caller's ordinary stack.
; D returns 0=completed, 1=refused before mutation, 2=uncertain append failure.
; A mirrors D on direct return; Bankswitch preserves D/flags but replaces A.

MACRO nativecall
    IF \1Bank == 0
        call \1
    ELSE
        ld b, \1Bank
        ld hl, \1
        call Bankswitch
    ENDC
ENDM

SECTION "SLink Native Trade", ROMX[$4800], BANK[SLINK_TRADE_BANK]
SlinkTradeApply::
    ; Cheap last-moment geometry/ownership refusal. Full66-byte semantic checks,
    ; save/ROM admission, exact prepared digest and key collision checks are the
    ; caller's prerequisites; this entry alone must never grant admission.
    ld a, [wIsInBattle]
    and a
    jp nz, .refused
    ld a, [wLinkState]
    and a
    jp nz, .refused
    ldh a, [hSerialConnectionStatus]
    cp $ff
    jp nz, .refused
    ld a, [wEnteringCableClub]
    and a
    jp nz, .refused
    IF SLINK_YELLOW
        ld a, [wPrinterConnectionOpen]
        and a
        jp nz, .refused
    ENDC
    ld a, [wPartyCount]
    and a
    jp z, .refused
    cp 7
    jp nc, .refused
    ld b, a
    ld a, [wTradingWhichPlayerMon]
    cp b
    jp nc, .refused
    ld e, b
    ld d, 0
    ld hl, wPartySpecies
    add hl, de
    ld a, [hl]
    cp $ff
    jp nz, .refused
    ld a, [wTradingWhichPlayerMon]
    ld e, a
    ld hl, wPartySpecies
    add hl, de
    ld a, [hl]
    push af
    ld a, [wTradingWhichPlayerMon]
    ld hl, wPartyMons
    ld bc, 44
    nativecall AddNTimes
    pop de
    ld a, [hli]
    cp d
    jp nz, .refused
    push hl
    call .validSpecies
    pop hl
    jp c, .refused
    ld a, [hli]
    or [hl]
    jp z, .refused
    ld a, [wEnemyPartyCount]
    cp 1
    jp nz, .refused
    ld a, [wEnemyPartySpecies + 1]
    cp $ff
    jp nz, .refused
    ld a, [wEnemyPartySpecies]
    ld b, a
    ld a, [wEnemyMons]
    cp b
    jp nz, .refused
    call .validSpecies
    jp c, .refused
    ld a, [wEnemyMons + 1]
    ld b, a
    ld a, [wEnemyMons + 2]
    or b
    jp z, .refused

    ; The selection bytes are aliases of wTraded*MonSpecies. Preserve the
    ; outgoing slot BEFORE publishing animation metadata to that same storage.
    ld a, [wTradingWhichPlayerMon]
    ld [wWhichPokemon], a

    ld a, [wOptions]
    push af
    ld a, [wStatusFlags5]
    push af
    ld a, [wFontLoaded]
    push af
    ld a, [wForceEvolution]
    push af
    ld a, [wUpdateSpritesEnabled]
    push af
    ldh a, [hAutoBGTransferEnabled]
    push af
    ldh a, [hTileAnimations]
    push af
    ldh a, [hWY]
    push af
    xor a
    ldh [hTileAnimations], a
    nativecall SaveScreenTilesToBuffer2

    ; Native cable trade metadata uses each Pokemon's actual OT, not save ID.
    ld a, [wWhichPokemon]
    ld hl, wPartyMonOT
    nativecall SkipFixedLengthTextEntries
    ld de, wTradedPlayerMonOT
    ld bc, 11
    nativecall CopyData
    ld a, [wWhichPokemon]
    ld hl, wPartyMons
    ld bc, 44
    nativecall AddNTimes
    ld a, [hl]
    ld [wTradedPlayerMonSpecies], a
    ld bc, 12
    add hl, bc
    ld a, [hli]
    ld [wTradedPlayerMonOTID], a
    ld a, [hl]
    ld [wTradedPlayerMonOTID + 1], a
    ld hl, wEnemyMonOT
    ld de, wTradedEnemyMonOT
    ld bc, 11
    nativecall CopyData
    ld a, [wEnemyMons + 12]
    ld [wTradedEnemyMonOTID], a
    ld a, [wEnemyMons + 13]
    ld [wTradedEnemyMonOTID + 1], a
    ld a, [wEnemyMons]
    ld [wTradedEnemyMonSpecies], a

    IF SLINK_YELLOW
        ; Exactly the vanilla ordering: Pikachu must still occupy its old slot.
        ld d, 11 ; PIKAHAPPY_TRADE, generated source constant is checked by builder
        nativecall ModifyPikachuHappiness
    ENDC
    xor a
    ld [wRemoveMonFromBox], a
    nativecall RemovePokemon
    xor a
    ld [wWhichPokemon], a
    ld a, [wEnemyMons]
    ld [wCurPartySpecies], a
    ld hl, wEnemyMons
    ld de, wLoadedMon
    ld bc, 44
    nativecall CopyData
    nativecall AddEnemyMonToPlayerParty
    ; Removal made one free slot. Failure here is uncertain, never normal NACK.
    jp c, .unreachableAppendFailure

    ; The same fade/music setup used by native Cable Club trades.
    ld a, 10
    ld [wAudioFadeOutControl], a
    ld a, SLINK_TRADE_MUSIC_BANK
    ld [wAudioSavedROMBank], a
    ld a, SLINK_TRADE_MUSIC_ID
    ld [wNewSoundID], a
    nativecall PlaySound
    ld c, 100
    nativecall DelayFrames
    nativecall ClearScreen
    nativecall LoadFontTilePatterns
    nativecall LoadHpBarAndStatusTilePatterns
    nativecall InternalClockTradeAnim
    ld a, [wPartyCount]
    dec a
    ld [wWhichPokemon], a
    ld a, 1
    ld [wForceEvolution], a
    ld a, $32 ; LINK_STATE_TRADING
    ld [wLinkState], a
    nativecall TryEvolvingMon
    xor a
    ld [wLinkState], a

    ; Use the original NPC-trade restoration, preserving current map/object
    ; state instead of entering/reinitializing the map after the movie.
    nativecall ClearScreen
    nativecall InGameTrade_RestoreScreen
    nativecall RedrawMapView
    nativecall UpdateSprites
    nativecall Delay3
    nativecall PlayDefaultMusic
    nativecall SavePartyAndDexData
    ld d, 0
    jr .restore
.unreachableAppendFailure
    ld d, 2
.restore
    pop af
    ldh [hWY], a
    pop af
    ldh [hTileAnimations], a
    pop af
    ldh [hAutoBGTransferEnabled], a
    pop af
    ld [wUpdateSpritesEnabled], a
    pop af
    ld [wForceEvolution], a
    pop af
    ld [wFontLoaded], a
    pop af
    ld [wStatusFlags5], a
    pop af
    ld [wOptions], a
    ld a, d
    and a
    ret
.refused
    ld d, 1
    ld a, d
    scf
    ret
.validSpecies
    cp 191
    jr nc, .invalidSpecies
    ld l, a
    ld h, 0
    ld de, SlinkTradeSpeciesTable
    add hl, de
    ld a, [hl]
    and a
    ret nz
.invalidSpecies
    scf
    ret
SlinkTradeSpeciesTable:
    slink_species_table
SlinkTradeApplyEnd::
