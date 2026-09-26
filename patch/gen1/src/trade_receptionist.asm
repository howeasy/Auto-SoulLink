; Existing TX_SCRIPT_CABLE_CLUB_RECEPTIONIST dispatch only; no sprite insertion.
; Availability and offers use bounded foreground leases over the shared union.
SECTION "SLink trade receptionist", ROMX[$4c00], BANK[SLINK_TRADE_BANK]
SlinkReceptionist::
    push af
    push bc
    push de
    push hl
    ; The host's nonzero availability token survives only on this call's stack.
    ; A byte generation alone is not unique across visits to the receptionist.
    add sp, -4
    call .query
.afterQuery
    bit 7, b
    jp z, .original
    ; Preserve native menu state. Party data is never replaced for selection.
    push bc ; eligible mask plus query generation
    ld hl, wTopMenuItemY
    REPT 4
        ld a, [hli]
        ld d, a
        ld a, [hli]
        ld e, a
        push de
    ENDR
    ld a, [wMenuJoypadPollCount]
    push af
    ld a, [wMenuWrappingEnabled]
    push af
    ld a, [wMenuWatchMovingOutOfBounds]
    push af
    ld a, [wPartyMenuAnimMonEnabled]
    push af
    ldh a, [hUILayoutFlags]
    push af
    ld a, [wUpdateSpritesEnabled]
    push af
    xor a
    ldh [hUILayoutFlags], a
    ld [wUpdateSpritesEnabled], a
    nativecall SaveScreenTilesToBuffer2
    nativecall ClearSprites
    nativecall Delay3
    call .mainMenu
    push af
    nativecall LoadScreenTilesFromBuffer2
    nativecall Delay3
    pop af
    cp 1
    jr z, .selectedCable
    and a
    jr nz, .selectedCancel
    ; Vanilla's forced save before any link (cable_club_npc.asm:56-67); the
    ; APPLY's own full save comes later. NO/B cancels before any offer exists.
    call SlinkTradeUIMustSave
    jr c, .selectedCancel
    call SlinkTradeUISave
    ; The retained mask/query pair is below20 bytes of saved menu state.
    ld hl, sp + 20
    ld a, [hli]
    ld c, a
    ld a, [hl]
    and $3f
    ld b, a
    call .partyMenu
    cp $ff
    jr z, .selectedCancel
.selectionCheck
    push af
    call SlinkTradeUIValidSlot
    pop de ; D retains the slot without replacing the validation carry flag
    jr nc, .selectionValid
    ld hl, .selectionChangedText
    call SlinkTradeUINotice
    jr .selectedCancel
.selectionValid
    ; Publish only a chosen slot. This pre-COMMIT offer cannot mutate a party.
    ld hl, sp + 20
    ld a, [hl]
    ld e, a
    call .offer
.offerReturned
    ld a, b
    ld hl, .offerSentText
    and a
    jr z, .offerNotice
    ld hl, .offerRejectedText
    cp 1
    jr z, .offerNotice
    ld hl, .offerUnknownText
.offerNotice
    call SlinkTradeUINotice
.selectedCancel
    ld a, 2
    jr .restoreMenus
.selectedCable
    ld a, 1
.restoreMenus
    ld b, a
    pop af
    ld [wUpdateSpritesEnabled], a
    pop af
    ldh [hUILayoutFlags], a
    pop af
    ld [wPartyMenuAnimMonEnabled], a
    pop af
    ld [wMenuWatchMovingOutOfBounds], a
    pop af
    ld [wMenuWrappingEnabled], a
    pop af
    ld [wMenuJoypadPollCount], a
    ld hl, wTopMenuItemY + 7
    REPT 4
        pop de
        ld a, e
        ld [hld], a
        ld a, d
        ld [hld], a
    ENDR
    ld a, b
    pop bc
.menusRestored
    cp 1
    jr z, .original
    add sp, 4
    pop hl
    pop de
    pop bc
    pop af
    ret
.original
    add sp, 4
    pop hl
    pop de
    pop bc
    pop af
    nativecall CableClubNPC
    ; The patched dispatch continues at HoldTextDisplayOpen. Reproduce the
    ; original AfterDisplayingTextID wait on the ordinary Cable Club path.
    ld a, [wEnteringCableClub]
    and a
    call z, WaitForTextScrollButtonPress
    ret

.query
    ; The serial/map union may be borrowed only at this foreground dispatch,
    ; without a battle, connected cable, link operation or Yellow printer owner.
    ld b, 0
    ld a, [wIsInBattle]
    and a
    ret nz
    ld a, [wLinkState]
    and a
    ret nz
    ldh a, [hSerialConnectionStatus]
    cp $ff
    ret nz
    ld a, [wEnteringCableClub]
    and a
    ret nz
    IF SLINK_YELLOW
        ld a, [wPrinterConnectionOpen]
        and a
        ret nz
    ENDC
    save_overlay_on_stack
    ld bc, 16
    ; CopyData is hl->de, so put the protocol bytes in the destination union.
    ld hl, .queryHeader
    ld de, SlinkOverlay
    nativecall CopyData
    ldh a, [hFrameCounter]
    inc a
    ld c, a
    dec a
    ld [SlinkOverlay + 7], a
    ld a, c
    ld [SlinkOverlay + 6], a ; generation last
    ld d, 30 ; bounded availability window for the foreground client
.queryWait
    call DelayFrame
    ld a, [SlinkOverlay + 6]
    cp c
    jr nz, .unavailable
    ld a, [SlinkOverlay + 7]
    cp c
    jr z, .queryAcknowledged
    dec d
    jr nz, .queryWait
    jr .unavailable
.queryAcknowledged
    call SlinkTradeService.magic
    jr nz, .unavailable
    ld a, [SlinkOverlay + 4]
    cp 1
    jr nz, .unavailable
    ld a, [SlinkOverlay + 5]
    cp 1
    jr nz, .unavailable
    ld a, [SlinkOverlay + 10]
    cp 1
    jr nz, .unavailable
    ld a, [SlinkOverlay + 11]
    cp $40
    jr nc, .unavailable
    ld b, a
    ; Preserve the host's token across both transient overlay leases. It binds
    ; the subsequent slot selection and acknowledgement to this exact visit.
    ld a, [SlinkOverlay + 12]
    ld d, a
    ld a, [SlinkOverlay + 13]
    or d
    ld d, a
    ld a, [SlinkOverlay + 14]
    or d
    ld d, a
    ld a, [SlinkOverlay + 15]
    or d
    jr z, .unavailable
    push bc
    ld hl, sp + 20 ; saved BC + overlay + return address = caller's token
    ld d, h
    ld e, l
    ld hl, SlinkOverlay + 12
    ld bc, 4
    nativecall CopyData
    pop bc
    ld a, [wPartyCount]
    and a
    jr z, .unavailable
    cp 7
    jr nc, .unavailable
    push bc
    call .liveSlots
    pop bc
    and b
    or $80
    ld b, a
    jr .queryReturn
.unavailable
    ld b, 0
.queryReturn
    restore_overlay_from_stack
    ret
.queryHeader
    db $53,$4c,$54,$31,1,1,0,0,0,0,0,0,0,0,0,0

.liveSlots
    ; A is the current physical count. A reply cannot make a fainted or
    ; nonexistent slot selectable, even if availability became stale.
    ld c, a
    ld b, 1
    ld d, 0
    ld hl, wPartyMons + 1
.liveSlotLoop
    ld a, [hli]
    or [hl]
    jr z, .skipLiveSlot
    ld a, d
    or b
    ld d, a
.skipLiveSlot
    ld a, l
    add 43
    ld l, a
    jr nc, .nextLiveSlot
    inc h
.nextLiveSlot
    sla b
    dec c
    jr nz, .liveSlotLoop
    ld a, d
    ret

.mainMenu
    ld hl, wTileMap
    ld b, 6
    ld c, 16
    nativecall TextBoxBorder
    ld hl, wTileMap + 42
    ld de, .slinkText
    nativecall PlaceString
    ld hl, wTileMap + 82
    ld de, .cableText
    nativecall PlaceString
    ld hl, wTileMap + 122
    ld de, .cancelText
    nativecall PlaceString
    ld hl, wTileMap + 282
    ld de, .welcomeText
    nativecall PlaceString
    ld a, 2
    ld d, 2
    call SlinkTradeUIMenuInput
    ret
.slinkText
    db "SLINK TRADE@"
.cableText
    db "CABLE CLUB@"
.cancelText
    db "CANCEL@"
.welcomeText
    db "Trade a linked<NEXT>POKéMON?@"

.partyMenu
    ; B contains the six eligible physical slots. Render just those names,
    ; preserving real party storage and native menu input/cursor behavior.
    ld a, b
    and a
    jr nz, .drawParty
    ld hl, .noLinkedText
    call SlinkTradeUINotice
    ld a, $ff
    ret
.drawParty
    push bc
    call .validNames
    pop bc
    jr nc, .namesValid
    ld hl, .invalidPartyText
    call SlinkTradeUINotice
    ld a, $ff
    ret
.namesValid
    push bc
    nativecall ClearScreen
    ld hl, wTileMap
    ld b, 14
    ld c, 18
    nativecall TextBoxBorder
    ld hl, wTileMap + 22
    ld de, .partyText
    nativecall PlaceString
    pop bc
    push bc
    ld de, wPartyMonNicks
    ld hl, wTileMap + 62
    ld c, 0
.nameLoop
    srl b
    jr nc, .skipName
    push bc
    push de
    push hl
    nativecall PlaceString
    pop hl
    ld bc, 40
    add hl, bc
    pop de
    pop bc
    inc c
.skipName
    ld a, e
    add 11
    ld e, a
    jr nc, .namePointer
    inc d
.namePointer
    ld a, b
    and a
    jr nz, .nameLoop
    ld a, c
    dec a
    ld d, 3
    call SlinkTradeUIMenuInput
    pop bc
    cp $ff
    jr z, .partyReturn
    ld c, a
    ld d, 0
.findPhysicalSlot
    srl b
    jr nc, .nextPhysical
    ld a, c
    and a
    jr z, .foundPhysical
    dec c
.nextPhysical
    inc d
    ld a, d
    cp 6
    jr c, .findPhysicalSlot
.noSelection
    ld a, $ff
    ret
.foundPhysical
    ld a, d
.partyReturn
    push af
    nativecall LoadScreenTilesFromBuffer2
    nativecall Delay3
    pop af
    ret
.partyText
    db "TRADE WHICH?@"

.validNames
    ld de, wPartyMonNicks
.validNamesLoop
    srl b
    jr nc, .skipValidatedName
    push bc
    push de
    call SlinkTradeUIValidName
    pop de
    pop bc
    ret c
.skipValidatedName
    ld a, e
    add 11
    ld e, a
    jr nc, .nextValidatedName
    inc d
.nextValidatedName
    ld a, b
    and a
    jr nz, .validNamesLoop
    ret
.noLinkedText
    text "No linked POKéMON"
    line "in your party."
    prompt
.offerSentText
    text "Trade offer sent."
    line "Awaiting partner."
    prompt
.offerRejectedText
    text "Trade unavailable."
    line "Offer not sent."
    prompt
.offerUnknownText
    text "Offer status is"
    line "not confirmed."
    prompt
.invalidPartyText
    text "Party data cannot"
    line "be read."
    prompt
.selectionChangedText
    text "That POKéMON is"
    line "not available."
    prompt

.offer
    ; D=slot, E=query generation. Save the union for this separate offer lease.
    ld b, d
    ld c, e
    save_overlay_on_stack
    ld hl, .queryHeader
    ld de, SlinkOverlay
    push bc
    ld bc, 16
    nativecall CopyData
    pop bc
    push bc
    ; saved BC + saved overlay + return + menu state/mask = caller's token.
    ld hl, sp + 42
    ld de, SlinkOverlay + 12
    ld bc, 4
    nativecall CopyData
    pop bc
    ld a, 2
    ld [SlinkOverlay + 5], a
    ld a, $ff ; no result exists until a matching reply is published
    ld [SlinkOverlay + 8], a
    ld a, b
    ld [SlinkOverlay + 9], a
    ld a, c
    ld [SlinkOverlay + 7], a
    inc a
    ld [SlinkOverlay + 6], a
    ld c, a
    ld a, [SlinkOverlay + 12]
    ld d, a
    ld a, [SlinkOverlay + 13]
    ld e, a
    ld a, [SlinkOverlay + 14]
    ld h, a
    ld a, [SlinkOverlay + 15]
    ld l, a
    ld a, 180
    push af ; timeout counter; BC/DE/HL retain all expected reply fields
.offerWait
    call DelayFrame
    ld a, [SlinkOverlay + 6]
    cp c
    jr nz, .offerUnconfirmed
    ld a, [SlinkOverlay + 7]
    cp c
    jr nz, .offerPending
    call SlinkTradeService.magic
    jr nz, .offerUnconfirmed
    ld a, [SlinkOverlay + 4]
    cp 1
    jr nz, .offerUnconfirmed
    ld a, [SlinkOverlay + 5]
    cp 2
    jr nz, .offerUnconfirmed
    ld a, [SlinkOverlay + 9]
    cp b
    jr nz, .offerUnconfirmed
    ld a, [SlinkOverlay + 12]
    cp d
    jr nz, .offerPending
    ld a, [SlinkOverlay + 13]
    cp e
    jr nz, .offerPending
    ld a, [SlinkOverlay + 14]
    cp h
    jr nz, .offerPending
    ld a, [SlinkOverlay + 15]
    cp l
    jr nz, .offerPending
    ld a, [SlinkOverlay + 8]
    cp 2 ; 0 = durably accepted offer; 1 = confirmed rejection without offer
    jr nc, .offerUnconfirmed
    ld b, a
    jr .offerReturn
.offerPending
    pop af
    dec a
    push af
    jr nz, .offerWait
.offerUnconfirmed
    ld b, 2 ; a timeout or malformed receipt does not prove non-delivery
.offerReturn
    pop af
    restore_overlay_from_stack
    ret
SlinkReceptionistEnd::
ASSERT SlinkReceptionistEnd <= $5400
