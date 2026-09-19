; Shared cartridge UI helpers for the initiator and partner trade flows. Ported from
; patch/gen1/src/trade_ui.asm. These functions expose no general-purpose message/choice
; capability.

SECTION "SLink trade UI helpers", ROMX

SlinkTradeUIWaitReleased::
.loop
	call DelayFrame
	call Joypad
	ldh a, [hJoyHeld]
	and PAD_A | PAD_B
	jr nz, .loop
	ret

SlinkTradeUINotice::
	; The caller has restored any borrowed serial union before drawing text.
	push hl
	call LoadScreenTilesFromBuffer2
	call SlinkTradeUIWaitReleased
	pop hl
	call PrintText
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
	ld a, PAD_A | PAD_B
	ld [wMenuWatchedKeys], a
	call SlinkTradeUIWaitReleased
	call HandleMenuInput
	bit B_PAD_B, a
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
	cp PARTY_LENGTH + 1
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
	ld bc, PARTYMON_STRUCT_LENGTH
	call AddNTimes
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
	ld c, NAME_LENGTH
.loop
	ld a, [de]
	cp '@' ; $50 under the charmap
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
	cp NAME_LENGTH
	jr z, .invalid
	and a
	ret

; One flag per byte value: 1 = a literal glyph a nickname may carry through text_ram. From
; constants/charmap.asm: $7F space, $80-$BF letters/punctuation/é/apostrophe ligatures,
; $E0-$EB punctuation and the → + % glyphs, $EF-$FF symbols and digits. Excluded: control
; bytes below $7F, kana $C0-$DF and the cursor arrows $EC-$EE.
SlinkTradeUINameTable::
FOR i, 256
	db (i >= $7F && i < $C0) || (i >= $E0 && i < $EC) || (i >= $EF)
ENDR
