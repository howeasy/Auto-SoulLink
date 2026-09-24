; Shared cartridge UI helpers for the initiator and partner trade flows.
; These functions expose no general-purpose message/choice capability.
SECTION "SLink trade UI helpers", ROMX[$5400], BANK[SLINK_TRADE_BANK]
SlinkTradeUIWaitReleased::
.loop
    call DelayFrame
    nativecall Joypad
    ldh a, [hJoyHeld]
    and 3
    jr nz, .loop
    ret

SlinkTradeUINotice::
    ; The caller has restored any borrowed serial union before drawing text.
    push hl
    nativecall LoadScreenTilesFromBuffer2
    call SlinkTradeUIWaitReleased
    pop hl
    nativecall PrintText
SlinkTradeUINoticeDone::
    ret

SlinkTradeUIMenuInput::
    ; A=max visible row; D=top row. Returns selected row or FF for B.
    ld [wMaxMenuItem], a
    ld a, d
    ld [wTopMenuItemY], a
    ld a, 1
    ld [wTopMenuItemX], a
    ld [wMenuWrappingEnabled], a
    xor a
    ld [wCurrentMenuItem], a
    ld [wLastMenuItem], a
    ld [wMenuJoypadPollCount], a
    ld [wMenuWatchMovingOutOfBounds], a
    ld a, 3
    ld [wMenuWatchedKeys], a
    call SlinkTradeUIWaitReleased
    nativecall HandleMenuInput
    bit 1, a
    jr nz, .cancel
    ld a, [wCurrentMenuItem]
    ret
.cancel
    ld a, $ff
    ret

SlinkTradeUIValidSlot::
    ; A=physical slot. Carry means missing, malformed or fainted.
    ld c, a
    ld a, [wPartyCount]
    cp 7
    jr nc, .invalid
    cp c
    jr z, .invalid
    jr c, .invalid
    ld b, 0
    ld hl, wPartySpecies
    add hl, bc
    ld a, [hl]
    push af
    ld a, c
    ld hl, wPartyMons
    ld bc, 44
    nativecall AddNTimes
    pop de
    ld a, [hli]
    cp d
    jr nz, .invalid
    push hl
    call SlinkTradeApply.validSpecies
    pop hl
    ret c
    ld a, [hli]
    or [hl]
    jr z, .invalid
    and a
    ret
.invalid
    scf
    ret

SlinkTradeUIValidName::
    ; DE=name. Only ten literal glyphs plus a terminator may be interpreted.
    ld c, 11
.loop
    ld a, [de]
    cp $50
    jr z, .terminator
    ld l, a
    ld h, 0
    push bc
    ld bc, SlinkTradeUINameTable
    add hl, bc
    pop bc
    ld a, [hl]
    and a
    jr z, .invalid
    inc de
    dec c
    jr nz, .loop
.invalid
    scf
    ret
.terminator
    ld a, c
    cp 11
    jr z, .invalid
    and a
    ret

SlinkTradeUIMustSave::
    ; Vanilla asks before any link and saves on YES (pret engine/link/
    ; cable_club_npc.asm:56-67). Carry = NO or B. Asks only: the caller runs
    ; SlinkTradeUISave once every byte the save records is live again.
    call SlinkTradeUIWaitReleased
    ld hl, .text
    nativecall PrintText
    nativecall YesNoChoice
    ld a, [wCurrentMenuItem]
    and a
    ret z
    scf
    ret
.text
    text "We have to save"
    line "before trading."
    done

SlinkTradeUISave::
    ; The full native save and its jingle (cable_club_npc.asm:67-70).
    nativecall SaveGameData
    nativecall WaitForSoundToFinish
    ld a, SLINK_SFX_SAVE
    nativecall PlaySoundWaitForCurrent
    ret

SlinkTradeUIResetNotice::
    ; Result 2 holds the lease with no exit (trade_service.asm .waitForReceipt):
    ; say so on screen. Preserves D.
    push de
    xor a
    ld [wUpdateSpritesEnabled], a
    ldh [hWY], a
    ld a, 1
    ld [wFontLoaded], a
    ldh [hAutoBGTransferEnabled], a
    nativecall ClearSprites
    nativecall LoadFontTilePatterns
    ld hl, .text
    nativecall PrintText
    pop de
    ret
.text
    text "Trade error."
    line "Please reset."
    done
SlinkTradeUINameTable::
    slink_name_table
SlinkTradeUIEnd::
ASSERT SlinkTradeUIEnd <= $5800
