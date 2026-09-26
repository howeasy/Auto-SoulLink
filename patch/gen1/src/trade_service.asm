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
;
; Reached from DelayFrame's tail (`jp` in place of `jr nz,.halt / ret`) with the flags of
; its `and a`: NZ means the VBlank has not happened yet and we go back to halt; Z means the
; main thread is about to resume. That makes this the one main-thread, every-context,
; once-per-frame point in the ROM, so both foreground services hang off it: the SFX
; request (slink.asm SlinkSfxService) and the trade lease. ROM0 only decides WHETHER to
; farcall; the predicates themselves live in bank $3F (SlinkForeground) where there is
; room. The lease byte aliases tile bytes when no lease is held, so it is tested for the
; exact armed value, not for nonzero.
SECTION "SLink DelayFrame bridge", ROM0[$0001]
SlinkDelayFrameBridge::
    jp nz, SlinkDelayFrameHalt
    push af
    push bc
    push de
    push hl
    ld a, [SLINK_SFX_REQUEST]
    and a
    jr nz, .go
    ld a, [SlinkOverlay + 10]
    dec a
    jr nz, .done
.go
    ld b, SLINK_TRADE_BANK
    ld hl, SlinkForeground
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
; Entered through Bankswitch from the bridge. Stack at this point, low to high: Bankswitch's
; .Return (2) and its saved af (2), the bridge's `call Bankswitch` return (2), the bridge's
; four saved pairs (8), then the address DelayFrame will return to — sp + 14.
SlinkForeground::
    call SlinkSfxService
    ; The trade service runs only for the OverworldLoop / OverworldLoopLessDelay caller
    ; and only while the lease's availability byte reads armed — the predicate the bridge
    ; used to hold in ROM0, moved here verbatim with the deeper stack offset.
    ld a, [SlinkOverlay + 10]
    dec a
    ret nz
    ld hl, sp + 14
    ld a, [hli]
    cp LOW(SlinkOverworldReturn)
    jr z, .lowMatches
    cp LOW(SlinkOverworldLessReturn)
    ret nz
.lowMatches
    ld a, [hl]
    cp HIGH(SlinkOverworldReturn)
    ret nz
    ; Only on a frame where vanilla could open the START menu and SAVE (pret
    ; home/overworld.asm:46-80): no step, ledge hop, scripted movement, START
    ; ignore, pending battle, Safari end or warp. The prompt opens text and both
    ; roles save, so mid-step pickup would misdraw the map and save a half step.
    ld a, [wWalkCounter]
    ld hl, wCurOpponent
    or [hl]
    ld hl, wSafariZoneGameOver
    or [hl]
    ret nz
    ld a, [wJoyIgnore]
    and 1 << 3 ; B_PAD_START, pret constants/hardware.inc:92
    ret nz
    ld a, [wMovementFlags]
    and 1 << 6 ; BIT_LEDGE_OR_FISHING, pret constants/ram_constants.asm:145
    ret nz
    ld a, [wStatusFlags5]
    and 1 << 7 ; BIT_SCRIPTED_MOVEMENT_STATE, ram_constants.asm:112
    ret nz
    ld a, [wStatusFlags3]
    and 1 << 3 ; BIT_WARP_FROM_CUR_SCRIPT, ram_constants.asm:86
    ret nz
    ld a, [wStatusFlags6]
    and (1 << 3) | (1 << 4) ; BIT_FLY_WARP, BIT_DUNGEON_WARP, ram_constants.asm:119-120
    ret nz
    jp SlinkTradeService

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
    ld a, d
    cp 2
    jr nz, .publish
    call SlinkTradeUIResetNotice ; the uncertain hold below never exits
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
