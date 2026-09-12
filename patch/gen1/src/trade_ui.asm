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
SlinkTradeUINameTable::
    slink_name_table
SlinkTradeUIEnd::
ASSERT SlinkTradeUIEnd <= $5800
