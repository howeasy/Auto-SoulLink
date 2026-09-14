; Transient foreground lease over the first16 bytes of the serial patch list.
; That buffer aliases wSurroundingTiles/wTileMapBackup: it is NEVER an idle
; mailbox. The local caller supplies its captured preimage in enemy slot1's
; unused storage, after staging the only incoming Pokemon in enemy slot0.
; No server-supplied bytes may substitute for that locally captured preimage.
DEF SlinkOverlay EQU wSerialPartyMonsPatchList
DEF SlinkOverlayBackup EQU wEnemyMons + 44

MACRO save_overlay_on_stack
    ld hl, SlinkOverlay
    REPT 8
        ld a, [hli]
        ld d, a
        ld a, [hli]
        ld e, a
        push de
    ENDR
ENDM

MACRO restore_overlay_from_stack
    ld hl, SlinkOverlay + 15
    REPT 8
        pop de
        ld a, e
        ld [hld], a
        ld a, d
        ld [hld], a
    ENDR
ENDM

; Source-declared unused RST space. RST00, RST38 and every hardware interrupt
; entry remain intact. The builder rejects any source use of the other RSTs.
SECTION "SLink DelayFrame bridge", ROM0[$0001]
SlinkDelayFrameBridge::
    jp nz, SlinkDelayFrameHalt
    push af
    push bc
    push de
    push hl
    ; Original DelayFrame caller, before the four saved register pairs.
    ld hl, sp + 8
    ld a, [hli]
    cp LOW(SlinkOverworldReturn)
    jr z, .lowMatches
    cp LOW(SlinkOverworldLessReturn)
    jr nz, .done
.lowMatches
    ld a, [hl]
    cp HIGH(SlinkOverworldReturn)
    jr nz, .done
    ld a, [SlinkOverlay + 10]
    dec a
    jr nz, .done
    ld b, SLINK_TRADE_BANK
    ld hl, SlinkTradeService
    call Bankswitch
.done
    pop hl
    pop de
    pop bc
    pop af
    ret
SlinkDelayFrameBridgeEnd::
ASSERT HIGH(SlinkOverworldReturn) == HIGH(SlinkOverworldLessReturn)
ASSERT SlinkDelayFrameBridgeEnd <= $0038

SECTION "SLink foreground trade service", ROMX[$4500], BANK[SLINK_TRADE_BANK]
SlinkTradeService::
    ; Check complete publication before treating tile bytes as a request.
    call .magic
    ret nz
    ld a, [SlinkOverlay + 4]
    cp 1
    ret nz
    ld a, [SlinkOverlay + 5]
    IF SLINK_TRADE_UI
        cp 3 ; partner confirmation, before any physical COMMIT
        jr z, .requestState
    ENDC
    cp 5 ; APPLY, only after the caller's durable paired COMMIT
    ret nz
.requestState
    ld a, [SlinkOverlay + 6]
    ld b, a
    ld a, [SlinkOverlay + 7]
    cp b
    ret z
    ld a, [SlinkOverlay + 9]
    ld [wTradingWhichPlayerMon], a
    save_overlay_on_stack
    ; Release the borrowed union before native code uses menu/animation buffers.
    ld hl, SlinkOverlayBackup
    ld de, SlinkOverlay
    ld bc, 16
    nativecall CopyData
    IF SLINK_TRADE_UI
        ld hl, sp + 10 ; command byte5 in the retained overlay
        ld a, [hl]
        cp 3
        jr nz, .apply
        call SlinkPartnerPrompt
        jr .publish
    ENDC
.apply
    ; Existing physical engine owns all final guard/refusal and save behavior.
    call SlinkTradeApply
.publish
    ; Retain result in byte8 of the stack copy. Pairs were pushed in order, so
    ; byte8 is the high byte at SP+7; byte5 is the low byte at SP+10.
    ld hl, sp + 7
    ld [hl], d
    ld hl, sp + 10
    ld [hl], 7 ; DONE; result0/1 may release, result2 remains uncertain
    ; The native restoration owns the new tile preimage; do not put an old map
    ; backup over bytes the cartridge just reconstructed.
    ld hl, SlinkOverlay
    ld de, SlinkOverlayBackup
    ld bc, 16
    nativecall CopyData
    restore_overlay_from_stack
    ; Publish completion generation last, after the complete overlay is restored.
    ld a, [SlinkOverlay + 6]
    ld [SlinkOverlay + 7], a
    ld b, a
    ld a, [SlinkOverlay + 8]
    ld c, a
    ld a, [SlinkOverlay + 12]
    ld d, a
    ld a, [SlinkOverlay + 13]
    ld e, a
    ld a, [SlinkOverlay + 14]
    ld h, a
    ld a, [SlinkOverlay + 15]
    ld l, a
.waitForReceipt
    call DelayFrame
    ; No timeout may manufacture a completed transaction or resume an uncertain
    ; append. A disconnected client stays in this foreground lease for recovery.
    ld a, c
    cp 2
    jr z, .waitForReceipt
    ld a, [SlinkOverlay + 5]
    cp 8 ; RELEASE after the client has durably consumed the verified result
    jr nz, .waitForReceipt
    ld a, [SlinkOverlay + 6]
    cp b
    jr nz, .waitForReceipt
    ld a, [SlinkOverlay + 7]
    cp b
    jr nz, .waitForReceipt
    ld a, [SlinkOverlay + 4]
    cp 1
    jr nz, .waitForReceipt
    ld a, [SlinkOverlay + 12]
    cp d
    jr nz, .waitForReceipt
    ld a, [SlinkOverlay + 13]
    cp e
    jr nz, .waitForReceipt
    ld a, [SlinkOverlay + 14]
    cp h
    jr nz, .waitForReceipt
    ld a, [SlinkOverlay + 15]
    cp l
    jr nz, .waitForReceipt
    call .magic
    jr nz, .waitForReceipt
    ld hl, SlinkOverlayBackup
    ld de, SlinkOverlay
    ld bc, 16
    nativecall CopyData
    ret
.magic
    ld a, [SlinkOverlay]
    cp $53 ; ASCII S; this is a protocol marker, not cartridge text
    ret nz
    ld a, [SlinkOverlay + 1]
    cp $4c
    ret nz
    ld a, [SlinkOverlay + 2]
    cp $54
    ret nz
    ld a, [SlinkOverlay + 3]
    cp $31
    ret
SlinkTradeServiceEnd::
ASSERT SlinkTradeServiceEnd <= $4800
