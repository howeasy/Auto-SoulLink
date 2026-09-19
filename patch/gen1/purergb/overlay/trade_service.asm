; Foreground trade service. Ported from patch/gen1/src/trade_service.asm; the DelayFrame RST
; bridge is gone (SlinkForeground in slink.asm is called from OverworldLoop instead).
;
; Transient foreground lease over the first 16 bytes of the serial patch list. That buffer
; aliases wSurroundingTiles/wTileMapBackup: it is NEVER an idle mailbox. The local caller
; supplies its captured preimage in enemy slot 1's unused storage, after staging the only
; incoming Pokemon in enemy slot 0. No server-supplied bytes may substitute for that
; locally captured preimage.
DEF SlinkOverlay EQUS "wSerialPartyMonsPatchList"
DEF SlinkOverlayBackup EQUS "(wEnemyMons + PARTYMON_STRUCT_LENGTH)"

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

SECTION "SLink foreground trade service", ROMX

SlinkTradeService::
	; Check complete publication before treating tile bytes as a request.
	call .magic
	ret nz
	ld a, [SlinkOverlay + 4]
	cp 1
	ret nz
	ld a, [SlinkOverlay + 5]
	cp 3 ; partner confirmation, before any physical COMMIT
	jr z, .requestState
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
	call CopyData
	ld hl, sp + 10 ; command byte5 in the retained overlay
	ld a, [hl]
	cp 3
	jr nz, .apply
	call SlinkPartnerPrompt
	jr .publish
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
	call CopyData
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
	call CopyData
	ret
.magic
	ld a, [SlinkOverlay]
	cp $53 ; ASCII "SLT1"; a protocol marker, not cartridge text, so never a charmap string
	ret nz
	ld a, [SlinkOverlay + 1]
	cp $4C
	ret nz
	ld a, [SlinkOverlay + 2]
	cp $54
	ret nz
	ld a, [SlinkOverlay + 3]
	cp $31
	ret
